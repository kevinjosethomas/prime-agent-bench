#!/usr/bin/env python3
"""External, isolated, real-daemon session I/O benchmark. No product imports.

Each --base/--candidate gets its own supervisor and state per trial, in
sequential B/C order. Writes use append_custom_message (no model turn); a
script prevents network use if a turn is later added. All JSONL rows are
compared in order; only header ID/timestamp, entry ID/parentId/timestamp, and
predeclared trial-local path fields are normalized. --strace traces process
creation and all workers; run untraced trials for latency numbers.
"""

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

PROTOCOL = {"name": "prime-agent.daemon", "version": 7}
SYSCALLS = "openat,close,read,write,writev,pwrite64,fsync,fdatasync,rename,renameat,renameat2"


def require(condition, explanation):
    if not condition:
        raise RuntimeError(explanation)


def until(predicate, seconds=20):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        result = predicate()
        if result:
            return result
        time.sleep(0.025)
    raise TimeoutError("daemon/worker did not reach requested state")


class Wire:
    def __init__(self, path):
        # A socket file may exist before the listener is ready.
        def connected():
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                sock.connect(str(path))
                return sock
            except OSError:
                sock.close()
                return None
        self.sock = until(connected)
        self.sock.settimeout(20)
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
        payload = {"type": "command", "id": request_id, "protocol": PROTOCOL, "command": command}
        start = time.perf_counter_ns()
        self.sock.sendall((json.dumps(payload, separators=(",", ":")) + "\n").encode())
        while True:
            response = self.read()  # session events may interleave responses
            if response.get("id") != request_id:
                continue
            elapsed = time.perf_counter_ns() - start
            require(response.get("success") is True, f"{command['type']} failed: {response}")
            return response.get("data") or {}, elapsed

    def close(self):
        self.lines.close()
        self.sock.close()


def rows(path):
    raw = path.read_bytes()
    require(not raw or raw.endswith(b"\n"), f"unterminated JSONL: {path}")
    return raw, [json.loads(line) for line in raw.splitlines()]


# Only these envelope fields may vary by run. Other fields, including nested
# metadata, compaction state, model selection, and message bodies, stay exact.
PATH_KEYS = frozenset(("cwd", "path", "sessionPath", "sessionFile", "sessionDir", "script"))


def normalize_rows(parsed, trial_dir):
    require(parsed and parsed[0].get("type") == "session", "missing session header")
    require(isinstance(parsed[0].get("id"), str), "missing header id")
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
            if key in PATH_KEYS and isinstance(item, str) and (item == prefix or item.startswith(prefix + "/")):
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
                require(parent in ids, f"row {index} has dangling parentId {parent}")
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


def expected_messages(phase, count, payload_size):
    for i in range(count):
        yield {"customType": "bench", "content": f"{phase}:{i:06d}:" + "x" * payload_size,
               "display": False}


def expected_semantics(messages):
    return [{**m, "details": None} for m in messages]


def worker_pid(agent_dir, sock_path, active_id):
    slot = hashlib.sha256(str(sock_path).encode()).hexdigest()[:12]
    descriptor = agent_dir / "daemon-workers" / slot / f"{active_id}.json"
    if not descriptor.exists():
        return None
    return json.loads(descriptor.read_text())["pid"]


def process_alive(pid):
    stat = Path(f"/proc/{pid}/stat")
    return stat.exists() and stat.read_text().split(") ", 1)[1][0] != "Z"


def check_jsonl(parsed):
    require(parsed and parsed[0].get("type") == "session", "missing session header")
    seen = set()
    for row in parsed[1:]:
        row_id = row.get("id")
        require(isinstance(row_id, str) and row_id not in seen, "missing/duplicate entry ID")
        parent = row.get("parentId")
        require(parent is None or parent in seen, "invalid entry parent chain")
        seen.add(row_id)


def fd_snapshot(pid):
    directory = Path(f"/proc/{pid}/fd")
    require(directory.exists(), f"pid {pid} exited before FD sampling")
    targets = []
    for fd in directory.iterdir():
        try:
            targets.append(os.readlink(fd))
        except FileNotFoundError:  # normal racing FD close
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
    return {"pid": pid, "count": len(targets), "classes": dict(sorted(Counter(map(klass, targets)).items()))}


def owned_workers(binary, agent_dir):
    """Discover only this trial's detached workers (not other live daemons)."""
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


def parse_syscalls(directory):
    counts = Counter()
    for file in directory.glob("trace.*"):
        for line in file.read_text(errors="replace").splitlines():
            match = re.match(r"(?:\d+(?:\.\d+)? )?([a-z_0-9]+)\(", line)
            if match:
                counts[match.group(1)] += 1
    return dict(sorted(counts.items()))


def run_one(label, binary, trial, options, root):
    trial_dir = root / label / f"trial-{trial:03d}"
    require(not trial_dir.exists(), f"refusing to overwrite {trial_dir}")
    trial_dir.mkdir(parents=True)
    agent_dir = trial_dir / "agent"
    agent_dir.mkdir()
    sock_path = trial_dir / "daemon.sock"
    script = trial_dir / "script.json"
    script.write_text(json.dumps({"responses": [{"text": "scripted"}]}))
    config = {"cwd": str(trial_dir), "sessionDir": str(agent_dir / "sessions"), "script": str(script)}
    cmd = [str(binary), "supervisor", "--socket", str(sock_path), "--agent-dir", str(agent_dir)]
    trace_dir = trial_dir / "syscalls"
    if options.strace:
        require(shutil.which("strace") is not None, "strace unavailable")
        trace_dir.mkdir()
        cmd = ["strace", "-ff", "-ttt", "-T", "-yy", "-e", f"trace={SYSCALLS}",
               "-o", str(trace_dir / "trace"), *cmd]
    log = (trial_dir / "daemon.log").open("wb")
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                            env={**os.environ, "PRIME_AGENT_CODING_AGENT_DIR": str(agent_dir),
                                 "PRIME_AGENT_SESSION_DIR": str(agent_dir / "sessions")})
    client = None
    active = None
    result = {"label": label, "trial": trial, "binary": str(binary), "trace": options.strace,
              "trial_dir": str(trial_dir), "supervisor_pid": proc.pid}
    try:
        client = Wire(sock_path)
        created, _ = client.call({"type": "create", "config": config})
        active = created.get("id") or created.get("sessionId")
        require(active, f"create returned no active ID: {created}")
        client.call({"type": "attach", "activeSessionId": active})
        stats, _ = client.call({"type": "get_session_stats", "activeSessionId": active})
        session_file = Path(stats["sessionFile"])
        pid = until(lambda: worker_pid(agent_dir, sock_path, active))
        result["session_file"] = str(session_file)
        result["fds_created"] = fd_snapshot(pid)
        fixture_bytes, fixture_rows = rows(session_file)
        result["fixture_sha256"] = hashlib.sha256(fixture_bytes).hexdigest()
        result["fixture_semantics_sha256"] = semantics_hash(fixture_rows, trial_dir)
        result["binary_sha256"] = hashlib.sha256(binary.read_bytes()).hexdigest()

        seed = list(expected_messages("seed", options.seed_appends, options.payload_size))
        for message in seed:
            client.call({"type": "append_custom_message", "activeSessionId": active,
                         "message": message})
        _, seeded_rows = rows(session_file)
        check_jsonl(seeded_rows)
        require(custom_semantics(seeded_rows) == expected_semantics(seed), "seed writes differ")
        result["fds_seeded"] = fd_snapshot(pid)
        client.call({"type": "kill", "activeSessionId": active})
        until(lambda: not process_alive(pid))
        active = None
        before_resume_bytes, before_resume_rows = rows(session_file)
        resume_start = time.perf_counter_ns()
        resumed, _ = client.call({"type": "create", "sessionPath": str(session_file),
                                   "config": config})
        result["resume_ns"] = time.perf_counter_ns() - resume_start
        active = resumed.get("id") or resumed.get("sessionId")
        require(active, f"resume returned no active ID: {resumed}")
        client.call({"type": "attach", "activeSessionId": active})
        new_pid = until(lambda: worker_pid(agent_dir, sock_path, active))
        require(new_pid != pid, "cold resume reused prior worker")
        result["fds_resumed"] = fd_snapshot(new_pid)
        result["worker_pid_before_resume"] = pid
        result["worker_pid_after_resume"] = new_pid
        baseline, resumed_rows = rows(session_file)
        check_jsonl(resumed_rows)
        prior = {row["id"]: row for row in before_resume_rows[1:]}
        current = {row["id"]: row for row in resumed_rows[1:]}
        require(all(current.get(key) == row for key, row in prior.items()),
                "resume altered a pre-existing JSONL row")
        require(custom_semantics(resumed_rows) == expected_semantics(seed), "resume lost seed rows")
        result["pre_resume_sha256"] = hashlib.sha256(before_resume_bytes).hexdigest()
        result["resume_preserves_bytes_prefix"] = baseline.startswith(before_resume_bytes)
        require(result["resume_preserves_bytes_prefix"], "resume changed pre-resume JSONL bytes")
        require(len(resumed_rows) >= len(before_resume_rows), "resume lost JSONL rows")
        require(normalize_rows(resumed_rows[:len(before_resume_rows)], trial_dir) ==
                normalize_rows(before_resume_rows, trial_dir), "resume changed pre-resume JSONL rows")
        result["pre_resume_semantics_sha256"] = semantics_hash(before_resume_rows, trial_dir)
        result["post_resume_semantics_sha256"] = semantics_hash(resumed_rows, trial_dir)
        result["baseline_bytes"] = len(baseline)
        messages = list(expected_messages("measure", options.appends, options.payload_size))
        latencies = []
        wall_start = time.perf_counter_ns()
        for message in messages:
            _, elapsed = client.call({"type": "append_custom_message", "activeSessionId": active,
                                      "message": message})
            latencies.append(elapsed)
        result["append_wall_ns"] = time.perf_counter_ns() - wall_start
        result["append_latency_ns"] = latencies
        result["appends"] = options.appends
        result["seed_appends"] = options.seed_appends
        result["payload_size"] = options.payload_size
        after, after_rows = rows(session_file)
        check_jsonl(after_rows)
        # Strict byte parity for append phase, even when small-session resume rewrote the file.
        require(after.startswith(baseline), "append phase changed existing JSONL bytes")
        appended_bytes = after[len(baseline):]
        appended_rows = [json.loads(line) for line in appended_bytes.splitlines()]
        require(len(appended_rows) == options.appends, "unexpected append row count")
        require(custom_semantics(appended_rows) == expected_semantics(messages),
                "append rows differ from requested messages")
        require(custom_semantics(after_rows) == expected_semantics(seed + messages),
                "session custom rows differ after append")
        result["append_bytes"] = len(appended_bytes)
        result["after_sha256"] = hashlib.sha256(after).hexdigest()
        normalized = normalize_rows(after_rows, trial_dir)
        (trial_dir / "normalized.json").write_text(json.dumps(normalized, sort_keys=True, ensure_ascii=False))
        result["normalized_semantics_sha256"] = semantics_hash(after_rows, trial_dir)
        result["row_count"] = len(after_rows)
        result["append_prefix_sha256"] = hashlib.sha256(baseline).hexdigest()
        result["append_preserves_bytes_prefix"] = True
        result["fds_after_append"] = fd_snapshot(new_pid)
        result["validated"] = True
        return result
    finally:
        if client is not None:
            if active is not None:
                try:
                    client.call({"type": "kill", "activeSessionId": active})
                except Exception:
                    pass
            client.close()
        # The group is created by this runner, never a user's existing daemon.
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)
        stop_owned_workers(binary, agent_dir)
        log.close()
        if options.strace:
            result["syscalls"] = parse_syscalls(trace_dir)
        (trial_dir / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True, help="baseline pa-daemon executable")
    parser.add_argument("--candidate", type=Path, required=True, help="candidate pa-daemon executable")
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--rows", type=int, default=100, help="fixed measured append count per trial")
    parser.add_argument("--seed-appends", type=int, default=1,
                        help="fixed pre-resume append count per trial")
    parser.add_argument("--payload-size", type=int, default=64)
    parser.add_argument("--out", type=Path, required=True, help="new output directory")
    parser.add_argument("--strace", action="store_true", help="traces all workers; timings are NOT comparable")
    args = parser.parse_args()
    require(args.trials > 0 and args.seed_appends >= 0 and args.rows > 0 and
            args.payload_size >= 0, "invalid count or size")
    args.appends = args.rows
    binaries = [(label, path.expanduser().resolve()) for label, path in
                (("base", args.base), ("candidate", args.candidate))]
    for label, path in binaries:
        require(path.is_file() and os.access(path, os.X_OK), f"{label} binary not executable: {path}")
    root = args.out.expanduser().resolve()
    require(not root.exists(), f"refusing existing output: {root}")
    root.mkdir(parents=True, exist_ok=True)
    results = []
    try:
        for trial in range(args.trials):
            for label, binary in binaries:
                result = run_one(label, binary, trial, args, root)
                results.append(result)
                print(json.dumps({key: result[key] for key in ("label", "trial", "validated",
                      "resume_ns", "append_wall_ns", "normalized_semantics_sha256")}), flush=True)
            base = json.loads((root / "base" / f"trial-{trial:03d}" / "normalized.json").read_text())
            candidate = json.loads((root / "candidate" / f"trial-{trial:03d}" / "normalized.json").read_text())
            require(base == candidate, f"full ordered JSONL semantics differ in trial {trial}")
            for key in ("fixture_semantics_sha256", "pre_resume_semantics_sha256",
                        "post_resume_semantics_sha256"):
                require(results[-2][key] == results[-1][key],
                        f"{key} differs between base/candidate in trial {trial}")
        require(len({r["normalized_semantics_sha256"] for r in results}) == 1,
                "full ordered JSONL semantics differ across roles/trials")
    finally:
        (root / "trials.json").write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
    def percentile(values, p):
        ordered = sorted(values)
        index = (len(ordered) - 1) * p
        low = int(index)
        return (ordered[low] + (ordered[min(low + 1, len(ordered) - 1)] - ordered[low]) *
                (index - low)) / 1e6
    summary = {label: {"trials": args.trials, "appends_per_trial": args.rows,
                       "per_append_p50_ms": percentile([latency for result in results
                           if result["label"] == label for latency in result["append_latency_ns"]], .5),
                       "per_append_p95_ms": percentile([latency for result in results
                           if result["label"] == label for latency in result["append_latency_ns"]], .95),
                       "resume_p50_ms": percentile([result["resume_ns"] for result in results
                           if result["label"] == label], .5)} for label, _ in binaries}
    (root / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"Results: {root / 'summary.json'}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"session_io_hillclimb: {error}", file=sys.stderr)
        raise
