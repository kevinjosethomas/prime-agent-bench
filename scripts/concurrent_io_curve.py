#!/usr/bin/env python3
"""Concurrent session I/O curve benchmark (hillclimb lane: concurrent-io).

N live sessions on ONE pa-daemon supervisor, driven with real wire traffic:
create+attach, seed appends, an idle window, measured appends, kill+resume
(create with sessionPath), a second measured append phase, then census. No
product imports; the daemon is driven exactly like a real client.

Driver fan-out: P driver processes (each with one thread per owned session)
sleep until a parent-written wall-clock deadline so all N sessions fire a
phase at once. Per-request client latencies; supervisor+worker schedstat
(CFS runtime ns) and /proc/<pid>/io at phase boundaries; fd counts and
RSS/PSS at census (supervisor census is taken while all sessions are still
live); meminfo at every boundary; fixed-work calibration spins between
phases for host-drift detection. Byte-parity oracles per session: JSONL
structure, custom-row semantics, resume prefix preservation.

--strace wraps the supervisor process tree in strace -ff -ttt -T -yy;
traced timings are NOT comparable and are used only for syscall counts.
"""

import argparse
from collections import Counter
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import resource
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import traceback

PROTOCOL = {"name": "prime-agent.daemon", "version": 7}
SYSCALLS = ("openat,close,read,write,writev,pwrite64,fsync,fdatasync,rename,"
            "renameat,renameat2")
# Durable-I/O-only trace set: boot-heavy openat/read/close stay untraced so
# traced worker boots fit their connect budget at N>1.
SYSCALLS_IO = "write,writev,pwrite64,fsync,fdatasync,rename,renameat,renameat2"
CLK_TCK = os.sysconf("SC_CLK_TCK")


def require(condition, explanation):
    if not condition:
        raise RuntimeError(explanation)


def until(predicate, seconds=60):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        result = predicate()
        if result:
            return result
        time.sleep(0.025)
    raise TimeoutError("condition not reached in time")


def raise_limits():
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(resource.RLIMIT_NOFILE, (max(soft, 65536), max(hard, 65536)))


class Wire:
    """One client connection to the daemon (blocking socket)."""

    def __init__(self, path, timeout=120):
        def connected():
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                sock.connect(str(path))
                return sock
            except OSError:
                sock.close()
                return None
        self.sock = until(connected, seconds=180)
        self.sock.settimeout(timeout)
        self.lines = self.sock.makefile("rb")
        require(self.read()["type"] == "daemon_hello", "missing daemon hello")
        self.serial = 0

    def read(self):
        line = self.lines.readline()
        require(line, "daemon closed connection")
        return json.loads(line)

    def call(self, command):
        self.serial += 1
        request_id = f"bench-{self.serial}"
        payload = {"type": "command", "id": request_id, "protocol": PROTOCOL,
                   "command": command}
        start = time.perf_counter_ns()
        self.sock.sendall((json.dumps(payload, separators=(",", ":")) + "\n").encode())
        while True:
            response = self.read()  # session events interleave responses
            if response.get("id") != request_id:
                continue
            elapsed = time.perf_counter_ns() - start
            require(response.get("success") is True,
                    f"{command['type']} failed: {response}")
            return response.get("data") or {}, elapsed

    def close(self):
        self.lines.close()
        self.sock.close()


# ---------------------------------------------------------------- validation

PATH_KEYS = frozenset(("cwd", "path", "sessionPath", "sessionFile", "sessionDir",
                       "script"))


def rows(path):
    raw = path.read_bytes()
    require(not raw or raw.endswith(b"\n"), f"unterminated JSONL: {path}")
    return raw, [json.loads(line) for line in raw.splitlines()]


def normalize_rows(parsed, trial_dir):
    require(parsed and parsed[0].get("type") == "session", "missing session header")
    row_ids = [row.get("id") for row in parsed[1:]]
    require(all(isinstance(value, str) for value in row_ids), "missing entry id")
    require(len(set(row_ids)) == len(row_ids), "duplicate entry id")
    ids = {value: f"<entry-{i}>" for i, value in enumerate(row_ids)}
    ids[parsed[0]["id"]] = "<session-id>"
    prefix = str(trial_dir)

    def nested_paths(value):
        if isinstance(value, list):
            return [nested_paths(item) for item in value]
        if not isinstance(value, dict):
            return value
        output = {}
        for key, item in value.items():
            if (key in PATH_KEYS and isinstance(item, str)
                    and (item == prefix or item.startswith(prefix + "/"))):
                output[key] = "<trial>" + item[len(prefix):]
            else:
                output[key] = nested_paths(item)
        return output

    normalized = []
    for index, original in enumerate(parsed):
        row = nested_paths(original)
        require("timestamp" in row, f"row {index} missing timestamp")
        row["timestamp"] = "<timestamp>"
        if index == 0:
            row["id"] = "<session-id>"
        else:
            row["id"] = ids[original["id"]]
            parent = original.get("parentId")
            if parent is not None:
                require(parent in ids, f"row {index} dangling parentId")
                row["parentId"] = ids[parent]
        normalized.append(row)
    return normalized


def semantics_hash(parsed, trial_dir):
    payload = json.dumps(normalize_rows(parsed, trial_dir), sort_keys=True,
                         separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(payload).hexdigest()


def custom_semantics(parsed):
    return [
        {key: row.get(key) for key in ("customType", "content", "display", "details")}
        for row in parsed if row.get("type") == "custom_message" and row.get("customType") == "bench"
    ]


def expected_messages(phase, count, payload_size, session_index):
    tag = f"{phase}:{session_index:04d}"
    for i in range(count):
        yield {"customType": "bench",
               "content": f"{tag}:{i:06d}:" + "x" * payload_size,
               "display": False}


def expected_semantics(messages):
    return [{**m, "details": None} for m in messages]


def check_jsonl(parsed):
    require(parsed and parsed[0].get("type") == "session", "missing session header")
    seen = set()
    for row in parsed[1:]:
        row_id = row.get("id")
        require(isinstance(row_id, str) and row_id not in seen, "missing/duplicate entry ID")
        parent = row.get("parentId")
        require(parent is None or parent in seen, "invalid entry parent chain")
        seen.add(row_id)


# -------------------------------------------------------------------- /proc

def read_schedstat(pid):
    """CFS runtime summed over ALL threads (tokio workers live off-main)."""
    runtime_ns = 0
    wait_ns = 0
    slices = 0
    found = False
    for task in Path(f"/proc/{pid}/task").iterdir():
        try:
            parts = (task / "schedstat").read_text().split()
        except (FileNotFoundError, ProcessLookupError):
            continue
        found = True
        runtime_ns += int(parts[0])
        wait_ns += int(parts[1])
        slices += int(parts[2])
    if not found:  # racing exit; caller handles the miss
        parts = Path(f"/proc/{pid}/schedstat").read_text().split()
        runtime_ns, wait_ns, slices = (int(parts[0]), int(parts[1]), int(parts[2]))
    return {"runtime_ns": runtime_ns, "wait_ns": wait_ns, "slices": slices}


def read_stat_ticks(pid):
    text = Path(f"/proc/{pid}/stat").read_text()
    fields = text[text.rindex(")") + 2:].split()
    return {"utime_ticks": int(fields[11]), "stime_ticks": int(fields[12])}


def read_io(pid):
    data = {}
    for line in Path(f"/proc/{pid}/io").read_text().splitlines():
        key, value = line.split(": ")
        data[key] = int(value)
    return data


def read_status_mb(pid):
    values = {}
    for line in Path(f"/proc/{pid}/status").read_text().splitlines():
        if line.startswith(("VmRSS:", "VmHWM:", "VmSwap:")):
            key, rest = line.split(":", 1)
            values[key] = round(int(rest.strip().split()[0]) / 1024, 3)
    return values


def read_pss_mb(pid):
    for line in Path(f"/proc/{pid}/smaps_rollup").read_text().splitlines():
        if line.startswith("Pss:"):
            return round(int(line.split()[1]) / 1024, 3)
    return None


def fd_snapshot(pid):
    directory = Path(f"/proc/{pid}/fd")
    require(directory.exists(), f"pid {pid} exited before FD sampling")
    targets = []
    for fd in directory.iterdir():
        try:
            targets.append(os.readlink(fd))
        except FileNotFoundError:
            pass
    def klass(target):
        if target.startswith("socket:"):
            return "socket"
        if target.startswith("pipe:"):
            return "pipe"
        if target.startswith("/memfd:"):
            return "memfd"
        if target.startswith("/dev/"):
            return "device"
        return "file"
    return {"pid": pid, "count": len(targets),
            "classes": dict(sorted(Counter(map(klass, targets)).items()))}


def meminfo():
    keys = ("MemFree", "MemAvailable", "Cached", "Dirty", "Writeback",
            "AnonPages", "SwapCached")
    values = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, rest = line.split(":", 1)
        if key in keys:
            values[key] = int(rest.strip().split()[0])
    return values


def worker_pid(agent_dir, sock_path, active_id):
    slot = hashlib.sha256(str(sock_path).encode()).hexdigest()[:12]
    descriptor = agent_dir / "daemon-workers" / slot / f"{active_id}.json"
    if not descriptor.exists():
        return None
    return json.loads(descriptor.read_text())["pid"]


def process_alive(pid):
    stat = Path(f"/proc/{pid}/stat")
    return stat.exists() and stat.read_text().split(") ", 1)[1][0] != "Z"


def find_supervisor(binary, agent_dir):
    """The real supervisor pid (past a possible strace wrapper)."""
    marker = ("PRIME_AGENT_CODING_AGENT_DIR=" + str(agent_dir)).encode()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            if Path(os.readlink(entry / "exe")) != binary:
                continue
            environment = (entry / "environ").read_bytes().split(b"\0")
            if marker not in environment:
                continue
            command = (entry / "cmdline").read_bytes().split(b"\0")
            if b"supervisor" in command:
                return int(entry.name)
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
    return None


def owned_workers(binary, agent_dir):
    owned = []
    marker = ("PRIME_AGENT_CODING_AGENT_DIR=" + str(agent_dir)).encode()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            if Path(os.readlink(entry / "exe")) != binary:
                continue
            environment = (entry / "environ").read_bytes().split(b"\0")
            if marker not in environment:
                continue
            command = (entry / "cmdline").read_bytes().split(b"\0")
            if b"worker" in command:
                owned.append(int(entry.name))
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
    return owned


def stop_owned_workers(binary, agent_dir):
    for pid in owned_workers(binary, agent_dir):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        until(lambda: not owned_workers(binary, agent_dir), seconds=5)
    except TimeoutError:
        for pid in owned_workers(binary, agent_dir):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


CALIBRATION_BYTES = 32 * 1024 * 1024


def calibration_seconds():
    data = b"calibration-block" * (CALIBRATION_BYTES // 16)
    start = time.perf_counter()
    hashlib.sha256(data).digest()
    return time.perf_counter() - start


# -------------------------------------------------------------------- driver

class SessionSlot:
    def __init__(self, index, trial_dir, agent_dir):
        self.index = index
        self.cwd = trial_dir / "work" / f"s{index:04d}"
        self.cwd.mkdir(parents=True)
        self.session_file = None
        self.active_id = None
        self.worker_pid = None
        self.wire = None
        self.create_ns = None
        self.fixture_sha = None
        self.fixture_semantics = None
        self.seed_latency_ns = []
        self.append1_ns = []
        self.append2_ns = []
        self.resume = {}
        self.snapshots = {}
        self.validation = {}


class Child:
    def __init__(self, options, procs_index, indexes, trial_dir, agent_dir,
                 sock_path, ctl):
        self.options = options
        self.procs_index = procs_index
        self.slots = [SessionSlot(i, trial_dir, agent_dir) for i in indexes]
        self.trial_dir = trial_dir
        self.agent_dir = agent_dir
        self.sock_path = sock_path
        self.ctl = ctl
        self.result = {"procs_index": procs_index,
                       "session_indexes": list(indexes), "sessions": {}}

    # --- phase implementations -------------------------------------------

    def phase_created(self, slot):
        config = {"cwd": str(slot.cwd), "sessionDir": str(self.agent_dir / "sessions"),
                  "script": str(self.trial_dir / "script.json")}
        created, create_ns = slot.wire.call({"type": "create", "config": config})
        slot.active_id = created.get("id") or created.get("sessionId")
        require(slot.active_id, f"create returned no active ID: {created}")
        slot.wire.call({"type": "attach", "activeSessionId": slot.active_id})
        stats, _ = slot.wire.call({"type": "get_session_stats",
                                   "activeSessionId": slot.active_id})
        slot.session_file = Path(stats["sessionFile"])
        slot.create_ns = create_ns
        until(lambda: worker_pid(self.agent_dir, self.sock_path, slot.active_id),
              seconds=600)
        slot.worker_pid = worker_pid(self.agent_dir, self.sock_path, slot.active_id)
        raw, parsed = rows(slot.session_file)
        slot.fixture_sha = hashlib.sha256(raw).hexdigest()
        slot.fixture_semantics = semantics_hash(parsed, self.trial_dir)
        self.result["sessions"][slot.index] = {
            "active_id": slot.active_id, "worker_pid": slot.worker_pid,
            "session_file": str(slot.session_file), "create_ns": create_ns,
            "fixture_sha256": slot.fixture_sha,
            "fixture_semantics_sha256": slot.fixture_semantics}

    def phase_seed(self, slot):
        messages = list(expected_messages("seed", self.options.seed_rows,
                                          self.options.payload_size, slot.index))
        for message in messages:
            _, elapsed = slot.wire.call({"type": "append_custom_message",
                                         "activeSessionId": slot.active_id,
                                         "message": message})
            slot.seed_latency_ns.append(elapsed)

    def phase_idle(self, slot):
        before = read_schedstat(slot.worker_pid)
        time.sleep(self.options.idle_seconds)
        after = read_schedstat(slot.worker_pid)
        slot.snapshots["idle"] = {"before": before, "after": after}

    def phase_append(self, slot, phase, tag):
        messages = list(expected_messages(tag, self.options.appends,
                                          self.options.payload_size, slot.index))
        before_stat = read_schedstat(slot.worker_pid)
        before_io = read_io(slot.worker_pid)
        latencies = slot.append1_ns if phase == "append1" else slot.append2_ns
        for message in messages:
            _, elapsed = slot.wire.call({"type": "append_custom_message",
                                         "activeSessionId": slot.active_id,
                                         "message": message})
            latencies.append(elapsed)
        slot.snapshots[phase] = {
            "before": before_stat, "after": read_schedstat(slot.worker_pid),
            "io_before": before_io, "io_after": read_io(slot.worker_pid)}

    def phase_resume(self, slot):
        raw_before, parsed_before = rows(slot.session_file)
        slot.snapshots["pre_resume_semantics"] = semantics_hash(
            parsed_before, self.trial_dir)
        _, kill_ns = slot.wire.call({"type": "kill", "activeSessionId": slot.active_id})
        old_pid = slot.worker_pid
        until(lambda: not process_alive(old_pid), seconds=120)
        dead_ns = time.perf_counter_ns()
        config = {"cwd": str(slot.cwd), "sessionDir": str(self.agent_dir / "sessions"),
                  "script": str(self.trial_dir / "script.json")}
        resumed, create_ns = slot.wire.call(
            {"type": "create", "sessionPath": str(slot.session_file),
             "config": config})
        new_active = resumed.get("id") or resumed.get("sessionId")
        require(new_active, f"resume returned no active ID: {resumed}")
        slot.wire.call({"type": "attach", "activeSessionId": new_active})
        until(lambda: worker_pid(self.agent_dir, self.sock_path, new_active),
              seconds=600)
        new_pid = worker_pid(self.agent_dir, self.sock_path, new_active)
        require(new_pid != old_pid, "resume reused the dead worker pid")
        slot.resume = {"kill_ns": kill_ns, "create_ns": create_ns,
                       "attach_done_ns": time.perf_counter_ns() - dead_ns,
                       "old_pid": old_pid, "new_pid": new_pid,
                       "active_before": slot.active_id, "active_after": new_active}
        slot.active_id = new_active
        slot.worker_pid = new_pid
        raw_after, parsed_after = rows(slot.session_file)
        slot.snapshots["post_resume_raw"] = raw_after
        slot.snapshots["resume_preserves_bytes"] = raw_after.startswith(raw_before)
        slot.snapshots["resume_prefix_semantics"] = semantics_hash(
            parsed_after[:len(parsed_before)], self.trial_dir)
        slot.snapshots["pre_resume_sha256"] = hashlib.sha256(raw_before).hexdigest()
        slot.snapshots["post_resume_sha256"] = hashlib.sha256(raw_after).hexdigest()
        slot.snapshots["post_resume_rows"] = len(parsed_after)
        require(len(parsed_after) >= len(parsed_before), "resume lost JSONL rows")

    def phase_census(self, slot):
        worker = {"pid": slot.worker_pid, "fds": fd_snapshot(slot.worker_pid),
                  "status_mb": read_status_mb(slot.worker_pid),
                  "pss_mb": read_pss_mb(slot.worker_pid),
                  "schedstat": read_schedstat(slot.worker_pid),
                  "io": read_io(slot.worker_pid)}
        raw, parsed = rows(slot.session_file)
        check_jsonl(parsed)
        seed = list(expected_messages("seed", self.options.seed_rows,
                                      self.options.payload_size, slot.index))
        measure1 = list(expected_messages("m1", self.options.appends,
                                          self.options.payload_size, slot.index))
        measure2 = list(expected_messages("m2", self.options.appends,
                                          self.options.payload_size, slot.index))
        expected = seed + measure1 + measure2
        require(custom_semantics(parsed) == expected_semantics(expected),
                f"s{slot.index:04d} custom rows differ from requested traffic")
        require(raw.startswith(slot.snapshots["post_resume_raw"]),
                "append2 phase altered existing JSONL bytes")
        slot.validation = {
            "row_count": len(parsed), "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "semantics_sha256": semantics_hash(parsed, self.trial_dir),
            "resume_preserves_bytes": slot.snapshots["resume_preserves_bytes"],
            "resume_prefix_semantics_sha256":
                slot.snapshots["resume_prefix_semantics"],
            "pre_resume_semantics_sha256":
                slot.snapshots["pre_resume_semantics"]}
        self.result["sessions"][slot.index].update({
            "census": {"worker": worker, "validation": slot.validation,
                       "resume": slot.resume,
                       "append1_ns": slot.append1_ns,
                       "append2_ns": slot.append2_ns,
                       "seed_latency_ns": slot.seed_latency_ns,
                       "idle": slot.snapshots.get("idle"),
                       "append1_schedstat": slot.snapshots.get("append1"),
                       "append2_schedstat": slot.snapshots.get("append2")}})

    def phase_teardown(self, slot):
        try:
            slot.wire.call({"type": "kill", "activeSessionId": slot.active_id})
        except Exception:
            pass
        slot.wire.close()

    # --- orchestration ----------------------------------------------------

    def child_phase(self, phase, fn):
        errors = []

        def run(slot):
            try:
                fn(slot)
            except Exception as error:  # noqa: BLE001 - surfaced to parent
                errors.append(f"s{slot.index:04d}: {error!r}")

        threads = [threading.Thread(target=run, args=(slot,))
                   for slot in self.slots]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        require(not errors, f"{phase} failed: " + "; ".join(errors[:4]))
        (self.ctl / f"{phase}.{self.procs_index}.done").write_text("{}")

    def wait_deadline(self, phase):
        marker = self.ctl / f"{phase}.go"
        until(lambda: marker.exists(), seconds=3600)
        deadline_ms = int(marker.read_text().strip())
        while True:
            remaining = deadline_ms - time.time() * 1000
            if remaining <= 0:
                return
            time.sleep(min(remaining / 1000.0, 0.05))

    def run(self):
        raise_limits()
        for slot in self.slots:
            slot.wire = Wire(self.sock_path)
        self.child_phase("created", self.phase_created)
        self.child_phase("seed", self.phase_seed)
        self.run_phase("idle", self.phase_idle)
        self.run_phase("append1",
                       lambda slot: self.phase_append(slot, "append1", "m1"))
        self.run_phase("resume1", self.phase_resume)
        self.run_phase("append2",
                       lambda slot: self.phase_append(slot, "append2", "m2"))
        self.run_phase("census", self.phase_census)
        self.run_phase("teardown", self.phase_teardown)
        (self.ctl / f"result.{self.procs_index}.json").write_text(
            json.dumps(self.result, sort_keys=True))

    def run_phase(self, phase, fn):
        self.wait_deadline(phase)
        self.child_phase(phase, fn)


def child_entry(options_dict, procs_index, indexes, trial_dir, agent_dir,
                sock_path, ctl):
    options = argparse.Namespace(**options_dict)
    try:
        Child(options, procs_index, indexes, Path(trial_dir), Path(agent_dir),
              Path(sock_path), Path(ctl)).run()
    except Exception:
        (Path(ctl) / f"error.{procs_index}.json").write_text(
            traceback.format_exc())
        raise


# --------------------------------------------------------------------- main

def run_one(label, binary, trial, options, root):
    trial_dir = root / label / f"trial-{trial:03d}"
    require(not trial_dir.exists(), f"refusing to overwrite {trial_dir}")
    trial_dir.mkdir(parents=True)
    agent_dir = trial_dir / "agent"
    agent_dir.mkdir()
    sock_path = trial_dir / "daemon.sock"
    ctl = trial_dir / "ctl"
    ctl.mkdir()
    (trial_dir / "work").mkdir()
    (trial_dir / "script.json").write_text(
        json.dumps({"responses": [{"text": "scripted"}]}))
    raise_limits()
    cmd = [str(binary), "supervisor", "--socket", str(sock_path),
           "--agent-dir", str(agent_dir)]
    trace_dir = trial_dir / "syscalls"
    if options.strace or options.strace_io:
        require(shutil.which("strace") is not None, "strace unavailable")
        trace_dir.mkdir()
        traced = SYSCALLS_IO if options.strace_io else SYSCALLS
        cmd = ["strace", "-ff", "-ttt", "-T", "-yy", "-e", f"trace={traced}",
               "-o", str(trace_dir / "trace"), *cmd]
    log = (trial_dir / "daemon.log").open("wb")
    env = {**os.environ,
           "PRIME_AGENT_CODING_AGENT_DIR": str(agent_dir),
           "PRIME_AGENT_SESSION_DIR": str(agent_dir / "sessions")}
    if options.strace or options.strace_io:
        # strace slows every spawn/trace enormously; the product's own env
        # seam (PA_DAEMON_WORKER_CONNECT_TIMEOUT_MS, used by tests under
        # parallel load) keeps 100 concurrent launches inside their budget.
        # Traced timings are never comparable; this run is for counts only.
        env.setdefault("PA_DAEMON_WORKER_CONNECT_TIMEOUT_MS", "180000")
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                            start_new_session=True, env=env)
    result = {"label": label, "trial": trial, "binary": str(binary),
              "workers": options.workers, "appends": options.appends,
              "seed_rows": options.seed_rows,
              "payload_size": options.payload_size,
              "idle_seconds": options.idle_seconds,
              "trace": bool(options.strace or options.strace_io),
              "trace_io_only": bool(options.strace_io),
              "trial_dir": str(trial_dir),
              "wrapper_pid": proc.pid,
              "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
              "phase_boundaries": {}, "meminfo": {}, "calibration": {},
              "host": {"uname": " ".join(os.uname()),
                       "clk_tck": CLK_TCK, "nproc": os.cpu_count()}}
    supervisor_pid = None
    children = []

    def boundary(name):
        nonlocal supervisor_pid
        if supervisor_pid is None:
            supervisor_pid = find_supervisor(Path(binary), agent_dir)
        require(supervisor_pid, "supervisor process not found")
        result["phase_boundaries"][name] = {
            "unix_ms": round(time.time() * 1000, 3), "pid": supervisor_pid,
            "sup_schedstat": read_schedstat(supervisor_pid),
            "sup_stat_ticks": read_stat_ticks(supervisor_pid),
            "sup_io": read_io(supervisor_pid)}

    def note_meminfo(name):
        result["meminfo"][name] = meminfo()

    def wait_all(marker, children):
        def ready():
            if any((ctl / f"error.{i}.json").exists() for i in range(len(children))):
                for index in range(len(children)):
                    error = ctl / f"error.{index}.json"
                    if error.exists():
                        raise RuntimeError(f"driver {index} crashed:\n"
                                           + error.read_text()[:2000])
            return all((ctl / f"{marker}.{i}.done").exists()
                       for i in range(len(children)))
        until(ready, seconds=3600)

    def go(phase, children):
        deadline = time.time() * 1000 + 1200
        (ctl / f"{phase}.go").write_text(str(round(deadline)))
        while time.time() * 1000 < deadline - 20:
            time.sleep(0.01)
        boundary(f"{phase}_start")
        note_meminfo(f"{phase}_start")
        wait_all(phase, children)
        boundary(f"{phase}_done")
        note_meminfo(f"{phase}_done")
        result["calibration"][f"after_{phase}"] = calibration_seconds()

    try:
        until(lambda: sock_path.exists(), seconds=180)
        result["calibration"]["pre"] = calibration_seconds()
        note_meminfo("start")
        procs = options.procs or max(1, (options.workers + 9) // 10)
        indexes = [list(range(i, options.workers, procs)) for i in range(procs)]
        indexes = [chunk for chunk in indexes if chunk]
        children = []
        for procs_index, chunk in enumerate(indexes):
            child = multiprocessing.Process(
                target=child_entry,
                args=(vars(options), procs_index, chunk, trial_dir, agent_dir,
                      sock_path, ctl))
            child.start()
            children.append(child)
        boundary("boot_start")
        wait_all("created", children)
        boundary("created_done")
        note_meminfo("created_done")
        result["calibration"]["after_boot"] = calibration_seconds()
        for phase in ("seed", "idle", "append1", "resume1", "append2", "census"):
            go(phase, children)
        # Supervisor census with every session still live, before teardown.
        result["supervisor_census"] = {"fds": fd_snapshot(supervisor_pid),
                                       "status_mb": read_status_mb(supervisor_pid),
                                       "pss_mb": read_pss_mb(supervisor_pid),
                                       "schedstat": read_schedstat(supervisor_pid),
                                       "io": read_io(supervisor_pid)}
        boundary("teardown_start")
        (ctl / "teardown.go").write_text(str(round(time.time() * 1000)))
        for child in children:
            child.join(timeout=300)
        for child in children:
            require(child.exitcode == 0,
                    f"driver process failed rc={child.exitcode}")
        boundary("teardown_done")
        note_meminfo("teardown_done")
        result["calibration"]["post"] = calibration_seconds()
        driver_results = {}
        for index in range(len(indexes)):
            path = ctl / f"result.{index}.json"
            require(path.exists(), f"driver result missing: {path}")
            driver_results[index] = json.loads(path.read_text())
        sessions = {}
        for chunk in driver_results.values():
            for index, data in chunk["sessions"].items():
                sessions[int(index)] = data
        result["driver_results"] = driver_results
        result["sessions"] = sessions
        result["session_semantics_digest"] = hashlib.sha256(
            json.dumps({str(k): sessions[k]["census"]["validation"]["semantics_sha256"]
                        for k in sorted(sessions)}).encode()).hexdigest()
        result["fixture_semantics_digest"] = hashlib.sha256(
            json.dumps({str(k): sessions[k]["fixture_semantics_sha256"]
                        for k in sorted(sessions)}).encode()).hexdigest()
        result["validated"] = True
        return result
    finally:
        for child in children:
            if child.is_alive():
                child.terminate()
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)
        stop_owned_workers(Path(binary), agent_dir)
        log.close()
        (trial_dir / "result.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--label", default="base")
    parser.add_argument("--workers", type=int, required=True)
    parser.add_argument("--appends", type=int, default=200)
    parser.add_argument("--seed-rows", type=int, default=20)
    parser.add_argument("--payload-size", type=int, default=2048)
    parser.add_argument("--procs", type=int, default=0,
                        help="driver processes (default: workers/10, min 1)")
    parser.add_argument("--idle-seconds", type=float, default=3.0)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--strace", action="store_true")
    parser.add_argument("--strace-io", action="store_true",
                        help="trace only durable-I/O syscalls (boot stays fast)")
    args = parser.parse_args()
    require(args.workers > 0 and args.appends > 0 and args.seed_rows >= 0
            and args.payload_size >= 0, "invalid counts")
    require(args.binary.is_file() and os.access(args.binary, os.X_OK),
            f"binary not executable: {args.binary}")
    root = args.out.expanduser().resolve()
    require(not root.exists(), f"refusing existing output: {root}")
    root.mkdir(parents=True)
    result = run_one(args.label, args.binary.resolve(), 0, args, root)
    print(json.dumps({"label": result["label"], "workers": result["workers"],
                      "validated": result["validated"],
                      "session_semantics_digest":
                          result["session_semantics_digest"]}))


if __name__ == "__main__":
    main()
