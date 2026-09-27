#!/usr/bin/env python3
"""RPC cold second-kernel-boot decomposition probe (Wave-5, perf-rpc-coldkernel).

Characterization-only: the replacement flavors' (new_session/switch_session/
fork) response walls + the per-kernel background boot anatomy, across
warm-venv steady state, immediate-replacement-while-boot-1-in-flight, and
per-trial COLD venv decomposition (the 10.8s one-shot: venv materialization
vs ipykernel boot vs handshake). Per-trial fresh agent dir/home/tmp, per-trial
fixture prehash assert, loadavg quiet gate, product-only zombie sweep,
per-command wall receipts, /proc watcher for kernel/uv/pip/probe lifetimes,
strace -ff census support. Fixed 10ms pump windows (the rpc-baseline lesson).

Usage:
  rpc_coldkernel_probe.py <mode> <trials> <bin> <out.json> [fixture]
modes: warm-census | warm-immediate | cold-early | cold-late
"""
import hashlib, json, os, pathlib, shutil, statistics, subprocess, sys, time, threading

MOCK_BASE = os.environ.get("MOCK_BASE", "http://127.0.0.1:8890/v1")
TRIALS_ROOT = "/root/rpc-trials"
DBG = os.environ.get("RPC_DBG")

def dbg(msg):
    if DBG: print(f'DBG {time.monotonic():.3f} {msg}', flush=True)

def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def write_models_json(agent_dir):
    agent_dir = pathlib.Path(agent_dir)
    agent_dir.mkdir(parents=True, exist_ok=True)
    models = {"providers": {"prime-inference": {
        "api": "openai-completions", "baseUrl": MOCK_BASE, "apiKey": "sk-bench",
        "models": [{"id": "mock-1", "name": "Mock 1", "api": "openai-completions",
                    "baseUrl": MOCK_BASE, "contextWindow": 128000, "maxTokens": 4096}]}}}
    (agent_dir / "models.json").write_text(json.dumps(models, indent=1))

def scrub_env(base):
    env = {}
    for k, v in base.items():
        if k.startswith(("PI_", "PRIME_", "UV_", "XDG_")):
            continue
        env[k] = v
    return env

def loadavg():
    with open("/proc/loadavg") as f:
        return float(f.read().split()[0])

def zombie_sweep():
    # product processes ONLY, by explicit pid list (fleet lesson: never pkill -f)
    out = subprocess.run(["ps", "-eo", "pid,comm,args"], capture_output=True, text=True).stdout
    me = os.getpid()
    pids = []
    for line in out.splitlines()[1:]:
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        pid, comm, args = parts
        pid = int(pid)
        if pid == me:
            continue
        is_product = (comm.startswith("prime-agent")
                      or (comm in ("python", "python3") and "rlm.repl" in args)
                      or comm == "uv"
                      or (comm in ("python", "python3") and " pip " in args))
        if is_product:
            pids.append(pid)
    for pid in pids:
        try:
            os.kill(pid, 15)
        except ProcessLookupError:
            pass
    if pids:
        time.sleep(1.5)
    return pids

class ProcWatcher(threading.Thread):
    """Sample /proc every 100ms; record kernel/uv/pip/probe process
    lifetimes with wall-clock stamps (never in the measured path)."""
    def __init__(self):
        super().__init__(daemon=True)
        self.events = []
        self._seen = {}
        self._halt = threading.Event()

    @staticmethod
    def _classify(exe, args):
        a = args.replace("\x00", " ")
        if "rlm.repl" in a:
            return ("kernel", a[-90:])
        if exe.endswith("/uv") or a.endswith(" uv") or a.startswith("uv "):
            return ("uv", a[-90:])
        if " pip " in a or "pip install" in a:
            return ("pip", a[-90:])
        if ("import inspect; import rlm" in a) or ("import prime_agent_runtime" in a):
            return ("probe", a[-90:])
        return None

    def _sample(self):
        now = time.time()
        live = {}
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                with open(f"/proc/{entry}/cmdline", "rb") as f:
                    raw = f.read()
                if not raw:
                    continue
                args = raw.decode(errors="replace")
                exe = args.split("\x00", 1)[0]
                kind = self._classify(exe, args)
                if kind:
                    live[int(entry)] = (kind[0], kind[1])
            except (OSError, ValueError):
                continue
        for pid, (kind, tail) in live.items():
            if pid not in self._seen:
                self.events.append({"t": now, "ev": "start", "kind": kind, "pid": pid, "tail": tail})
        for pid in list(self._seen):
            if pid not in live:
                self.events.append({"t": now, "ev": "end", "pid": pid,
                                    "kind": self._seen[pid][0]})
        self._seen = live

    def run(self):
        while not self._halt.is_set():
            try:
                self._sample()
            except Exception:
                pass
            time.sleep(0.1)

    def stop(self):
        self._halt.set()
        self.join(timeout=2.0)
        try:
            self._sample()
        except Exception:
            pass

class Conn:
    def __init__(self, proc):
        self.proc = proc
        self.frames = []
        self._raw_buf = b""
        self.stderr_tail = []
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()

    def _drain_stderr(self):
        for raw in iter(self.proc.stderr.readline, b""):
            self.stderr_tail.append((time.time(), raw.decode(errors="replace")))
            if len(self.stderr_tail) > 4000:
                self.stderr_tail.pop(0)

    def _read_frames(self, timeout_s, idle_s=None, max_s=30.0):
        import select
        fd = self.proc.stdout.fileno()
        os.set_blocking(fd, False)
        t0 = time.monotonic()
        last = t0
        n = 0
        while True:
            now = time.monotonic()
            if now - t0 > min(timeout_s, max_s):
                break
            if idle_s is not None and now - last > idle_s:
                break
            ready, _, _ = select.select([fd], [], [], 0.01)
            if ready:
                try:
                    chunk = os.read(fd, 65536)
                except (BlockingIOError, OSError):
                    chunk = b""
                if chunk:
                    self._raw_buf += chunk
                    last = time.monotonic()
                while b"\n" in self._raw_buf:
                    raw, self._raw_buf = self._raw_buf.split(b"\n", 1)
                    if not raw.strip():
                        continue
                    try:
                        obj = json.loads(raw)
                    except ValueError:
                        continue
                    self.frames.append((time.time(), time.monotonic(), obj))
                    n += 1
        return n, last

    def send(self, obj):
        self.proc.stdin.write((json.dumps(obj) + "\n").encode())
        self.proc.stdin.flush()

    def read_until_response(self, rid, timeout=120.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            before = len(self.frames)
            self._read_frames(timeout_s=0.01, max_s=0.01)
            for _, _, obj in self.frames[before:]:
                if obj.get("type") == "response" and obj.get("id") == rid:
                    return obj
            if self.proc.poll() is not None and not self._raw_buf:
                raise RuntimeError(f"rpc exited rc={self.proc.returncode}; "
                                  f"stderr_tail={''.join(x[1] for x in self.stderr_tail)[-1500:]}")
        raise TimeoutError(f"no response for {rid} in {timeout}s; partial_buf={self._raw_buf[-400:]!r}; "
                           f"frames={[(round(m, 2), o.get('type')) for _, m, o in self.frames][-10:]}; "
                           f"stderr_tail={''.join(x[1] for x in self.stderr_tail)[-1500:]}")

    def drain_events(self, idle_s=0.35, max_s=30.0):
        _, last = self._read_frames(timeout_s=max_s, idle_s=idle_s, max_s=max_s)
        return last

def first_user_entry_id(session_file):
    """The first user message row's id in a session JSONL (the fork target)."""
    with open(session_file, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            msg = row.get("message") or {}
            if row.get("type") == "message" and msg.get("role") == "user" and row.get("id"):
                return row["id"]
    return None

def run_trial(mode, i, binpath, fixture, root):
    trial = os.path.join(root, f"{mode}-{i:02d}")
    os.makedirs(trial, exist_ok=True)
    agent = os.path.join(trial, "agent")
    write_models_json(agent)
    for name in ("auth.json", "settings.json"):
        src = os.path.join("/root/.prime/agent", name)
        if os.path.exists(src):
            shutil.copy(src, os.path.join(agent, name))
    proj = os.path.join(trial, "proj")
    os.makedirs(proj, exist_ok=True)
    home = os.path.join(trial, "home")
    tmp = os.path.join(trial, "tmp")
    os.makedirs(home, exist_ok=True)
    os.makedirs(tmp, exist_ok=True)
    args = [binpath, "--mode", "rpc",
            "--provider", "prime-inference", "--model", "mock-1",
            "--daemon-socket", os.path.join(trial, "d.sock")]
    env = scrub_env(os.environ)
    env.update({"HOME": home, "TMPDIR": tmp,
                "PRIME_AGENT_CODING_AGENT_DIR": agent,
                "PRIME_API_KEY": "sk-bench",
                "RUST_LOG": "error",
                "PATH": "/root/.cargo/bin:/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"})
    venv_env_path = os.path.join(TRIALS_ROOT, "venv-env.json")
    if os.path.exists(venv_env_path):
        env.update(json.load(open(venv_env_path)))
    else:
        env.update({"UV_CACHE_DIR": "/root/rpc-uv-cache",
                    "UV_PYTHON_INSTALL_DIR": "/root/rpc-uv-python"})
    fixture_copy = None
    if mode in ("warm-immediate", "cold-early", "cold-late"):
        fixture_copy = os.path.join(trial, "sess", "fixture.jsonl")
        os.makedirs(os.path.dirname(fixture_copy), exist_ok=True)
        shutil.copy(fixture, fixture_copy)
        src_sha = sha256_file(fixture)
        if sha256_file(fixture_copy) != src_sha:
            raise RuntimeError("fixture prehash mismatch")
        args += ["--resume", fixture_copy]
    elif mode == "warm-census" and i == 0:
        pass  # fresh session for every warm-census trial
    if mode.startswith("cold-"):
        # per-trial COLD venv: wipe any leftover so every run is a true cold
        # materialization (the product builds it in the background)
        kvenv = os.path.join(trial, "kvenv")
        if os.path.exists(kvenv):
            shutil.rmtree(kvenv)
        env["PRIME_AGENT_KERNEL_VENV"] = kvenv
    receipt = {"trial": trial, "mode": mode, "argv_tail": args[1:],
               "kernel_venv": env.get("PRIME_AGENT_KERNEL_VENV")}
    zombie_sweep()
    while loadavg() > 1.0:
        time.sleep(2.0)
    spawn_args = args
    census_dir = os.environ.get("RPC_CENSUS_DIR")
    if census_dir:
        os.makedirs(census_dir, exist_ok=True)
        tag = os.environ.get("RPC_CENSUS_TAG", f"{mode}-{i:02d}")
        spawn_args = (["strace", "-ff", "-f", "-tt", "-T",
                       "-e", "trace=mkdir,rmdir,openat,open,fsync,fdatasync,rename,renameat,write,clock_nanosleep,unlink,unlinkat,flock,fcntl,setxattr,execve,clone,clone3,wait4",
                       "-o", os.path.join(census_dir, tag)]
                      + args)
        receipt["census"] = tag
    t_spawn_wall, t_spawn_mono = time.time(), time.monotonic()
    proc = subprocess.Popen(spawn_args, cwd=proj, env=env,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    watcher = ProcWatcher()
    watcher.start()
    conn = Conn(proc)
    cmds = []

    def do(cid, obj, settle=0.35):
        t0w, t0m = time.time(), time.monotonic()
        conn.send({"id": cid, **obj})
        r = conn.read_until_response(cid)
        t1m = time.monotonic()
        if settle:
            conn.drain_events(idle_s=settle, max_s=6.0)
        cmds.append({"id": cid, "ok": r.get("success"),
                     "ms": (t1m - t0m) * 1000.0,
                     "t0_wall": t0w, "err": r.get("error")})
        return r

    try:
        rid = "rdy"
        conn.send({"type": "get_state", "id": rid})
        resp = conn.read_until_response(rid)
        t_ready_mono = time.monotonic()
        state = (resp.get("data") or {})
        receipt["launch_to_ready_ms"] = (t_ready_mono - t_spawn_mono) * 1000.0
        first_session_file = state.get("sessionFile")
        receipt["ready_state"] = {"sessionId": state.get("sessionId"),
                                  "messageCount": state.get("messageCount"),
                                  "sessionFile": first_session_file,
                                  "model": (state.get("model") or {}).get("id"),
                                  "success": resp.get("success")}
        if mode == "warm-census":
            do("st2", {"type": "get_state"})
            do("ssn", {"type": "set_session_name", "name": "rpc-bench"})
            do("stl", {"type": "set_thinking_level", "level": "low"})
            do("pr1", {"type": "prompt", "id": "pr1", "message": f"BENCHPROMPT {mode} {i}"},
               settle=0.5)
            do("ns1", {"type": "new_session"}, settle=3.0)
            do("ns2", {"type": "new_session"}, settle=3.0)
            do("ns3", {"type": "new_session"}, settle=2.0)
            if first_session_file and os.path.exists(first_session_file):
                do("sw1", {"type": "switch_session", "sessionPath": first_session_file}, settle=2.0)
                eid = first_user_entry_id(first_session_file)
                if eid:
                    do("fk1", {"type": "fork", "entryId": eid}, settle=2.0)
            do("eof_gm", {"type": "get_messages"})
        elif mode == "warm-immediate":
            do("ns1", {"type": "new_session"}, settle=0.15)
            do("sw1", {"type": "switch_session", "sessionPath": fixture_copy}, settle=0.15)
            eid = first_user_entry_id(fixture_copy)
            if eid:
                do("fk1", {"type": "fork", "entryId": eid}, settle=0.15)
            do("ns2", {"type": "new_session"}, settle=0.15)
            do("ns3", {"type": "new_session"}, settle=0.15)
            do("st2", {"type": "get_state"})
            do("pr1", {"type": "prompt", "id": "pr1", "message": "BENCHPROMPT immediate"}, settle=0.5)
        elif mode == "cold-early":
            time.sleep(1.0)   # boot #1 (venv materialization) still in flight
            do("ns1", {"type": "new_session"}, settle=0.15)
            do("sw1", {"type": "switch_session", "sessionPath": fixture_copy}, settle=0.15)
            do("ns2", {"type": "new_session"}, settle=0.15)
            do("st2", {"type": "get_state"})
            time.sleep(2.0)
        elif mode == "cold-late":
            time.sleep(25.0)  # boot #1 + venv materialization fully settled
            do("ns1", {"type": "new_session"}, settle=3.0)
            do("ns2", {"type": "new_session"}, settle=3.0)
            do("sw1", {"type": "switch_session", "sessionPath": fixture_copy}, settle=2.0)
            do("st2", {"type": "get_state"})
        receipt["commands"] = cmds
        receipt["frames_n"] = len(conn.frames)
        t0m3 = time.monotonic()
        proc.stdin.close()
        rc = proc.wait(timeout=180)
        receipt["stdin_close_to_exit_ms"] = (time.monotonic() - t0m3) * 1000.0
        receipt["exit_code"] = rc
    finally:
        watcher.stop()
        if proc.poll() is None:
            proc.kill()
        try:
            proc.wait(timeout=10)
        except Exception:
            pass
        stderr = "".join(x[1] for x in conn.stderr_tail)[-4000:]
        receipt["stderr_tail"] = stderr
    t0w = t_spawn_wall
    receipt["proc_events"] = [{"dt_ms": round((e["t"] - t0w) * 1000.0, 1), **{k: e[k] for k in ("ev", "kind", "pid")}}
                              for e in watcher.events]
    receipt["frames"] = [(w, round(m, 3), o.get("type"),
                          o.get("command") or (o.get("data") or {}).get("type"))
                         for w, m, o in conn.frames]
    with open(os.path.join(trial, "receipt.json"), "w") as f:
        json.dump(receipt, f, indent=1)
    if mode != "no-session":
        sess_dir = os.path.join(agent, "sessions")
        receipt["session_files"] = []
        for name in sorted(os.listdir(sess_dir)) if os.path.isdir(sess_dir) else []:
            p = os.path.join(sess_dir, name)
            with open(p, "rb") as f:
                receipt["session_files"].append({"name": name, "bytes": os.path.getsize(p)})
    return receipt

def main():
    mode = sys.argv[1]
    trials = int(sys.argv[2])
    binpath = os.path.abspath(sys.argv[3])
    fixture = sys.argv[4] if len(sys.argv) > 4 and sys.argv[4].endswith(".jsonl") else None
    out = sys.argv[-1]
    assert os.path.exists(binpath), binpath
    bin_sha = sha256_file(binpath)
    root = TRIALS_ROOT
    os.makedirs(root, exist_ok=True)
    receipts = []
    print("COLDKERNEL_START", mode, "trials", trials, "bin_sha", bin_sha[:16], flush=True)
    for i in range(trials):
        print("TRIAL_START", mode, i, flush=True)
        t0 = time.monotonic()
        r = run_trial(mode, i, binpath, fixture, root)
        r["trial_wall_s"] = round(time.monotonic() - t0, 2)
        receipts.append(r)
        print(f"TRIAL {mode} {i} ready_ms={r.get('launch_to_ready_ms', -1):.1f} "
              f"ns1_ms={[c['ms'] for c in r.get('commands', []) if c['id'] == 'ns1']} "
              f"exit={r.get('exit_code')} eof_ms={r.get('stdin_close_to_exit_ms')}", flush=True)
        time.sleep(2.0)
    summary = {"mode": mode, "trials": trials, "binary_sha256": bin_sha,
               "loadavg_last": loadavg(), "receipts": receipts}
    with open(out, "w") as f:
        json.dump(summary, f, indent=1)
    print(f"OUT {out}", flush=True)

if __name__ == "__main__":
    main()
