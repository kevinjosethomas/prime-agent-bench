#!/usr/bin/env python3
"""Raw kernel-substrate probe (RT only): drives `python -m rlm.repl` over its
JSONL protocol 3 directly, per product venv, measuring the kernel WITHOUT any
product bridge (the bridge overhead = product-mediated E2E - this).

Protocol driver ported from the TS repo's scripts/benchmarks/kernel.py (the
reference implementation). Not part of any product.
"""
from __future__ import annotations

import json
import os
import selectors
import subprocess
import sys
import time
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import products as P


class RawKernel:
    def __init__(self, command, cwd, env, stderr_path):
        self.selector = selectors.DefaultSelector()
        self.pending = b""
        self.lines = deque()
        self.sequence = 0
        self.started = time.perf_counter()
        self.stderr = open(stderr_path, "wb")
        self.process = subprocess.Popen(
            command, cwd=cwd, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr,
            bufsize=0, start_new_session=True)
        self.selector.register(self.process.stdout, selectors.EVENT_READ)

    def event(self, deadline):
        while not self.lines:
            remaining = deadline - time.perf_counter()
            if remaining <= 0 or not self.selector.select(remaining):
                raise TimeoutError("kernel protocol timeout")
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                raise RuntimeError("kernel exited early")
            self.lines.extend((self.pending + chunk).split(b"\n")[:-1])
            self.pending = (self.pending + chunk).split(b"\n")[-1]
        event = json.loads(self.lines.popleft())
        if not isinstance(event, dict) or not isinstance(event.get("event"), str):
            raise ValueError("invalid kernel event")
        return event

    def ready(self):
        event = self.event(time.perf_counter() + 60)
        if event.get("event") != "ready" or event.get("protocol") != 3:
            raise ValueError(f"expected protocol-3 ready, got {event}")
        return time.perf_counter() - self.started, event.get("python")

    def send(self, request):
        data = (json.dumps(request) + "\n").encode()
        self.process.stdin.write(data)
        self.process.stdin.flush()

    def done(self, request_id):
        deadline = time.perf_counter() + 60
        events = []
        while True:
            event = self.event(deadline)
            events.append(event)
            if event.get("event") == "done" and event.get("id") == request_id:
                if event.get("status") != "ok":
                    raise RuntimeError(f"kernel request failed: {str(events)[-300:]}")
                return events

    def request(self, kind, **fields):
        self.sequence += 1
        rid = str(self.sequence)
        self.send({"type": kind, "id": rid, **fields})
        return self.done(rid)

    def execute(self, code):
        t0 = time.perf_counter()
        self.request("execute", code=code)
        return (time.perf_counter() - t0) * 1000.0

    def snapshot(self, path, manifest_path, max_bytes=100 << 20, max_variable_bytes=16 << 20, prune_oversized=True):
        t0 = time.perf_counter()
        self.request("snapshot", path=path, manifest_path=manifest_path,
                     max_bytes=max_bytes, max_variable_bytes=max_variable_bytes,
                     prune_oversized=prune_oversized)
        return (time.perf_counter() - t0) * 1000.0

    def restore(self, path):
        t0 = time.perf_counter()
        self.request("restore", path=path)
        return (time.perf_counter() - t0) * 1000.0

    def close(self):
        try:
            self.process.terminate()
            self.process.wait(timeout=5)
        except Exception:
            self.process.kill()
        self.stderr.close()
        self.selector.close()


def product_kernel_env(product_name):
    """The venv python + env for one product's kernel substrate."""
    venv = P.GLOBAL / product_name / "kernel-venv"
    return [str(venv / "bin" / "python"), "-m", "rlm.repl"]


def run_raw_probe(product_name, out_path, repeats=10):
    """Ready time, 50 sequential pass cells, warm cell, snapshot/restore of a
    ~5MiB namespace. `repeats` independent kernel instances."""
    results = []
    for i in range(repeats):
        cmd = product_kernel_env(product_name)
        work = Path("/tmp")
        env = {"PATH": "/usr/bin:/bin", "HOME": str(P.BENCH / "global" / product_name),
               "TERM": "xterm-256color", "LANG": "C.UTF-8"}
        k = RawKernel(cmd, cwd=str(work), env=env,
                      stderr_path=str(P.BENCH / f"logs/kernel-raw-{product_name}-{i}.stderr"))
        try:
            ready_s, py = k.ready()
            first_cell_ms = k.execute("pass")
            warm = [k.execute("pass") for _ in range(50)]
            state_ms = k.execute(
                "import numpy as np, pandas as pd\n"
                "raw_frame = pd.DataFrame(np.random.rand(655360, 8))\n"
                "raw_list = list(range(10000))\nprint('raw-state-ok')")
            snap_dir = Path(f"/tmp/bench-kraw-{product_name}-{i}")
            snap_dir.mkdir(exist_ok=True)
            snap_path = str(snap_dir / "state.snap")
            manifest_path = str(snap_dir / "state.manifest.json")
            snap_ms = k.snapshot(snap_path, manifest_path)
            snap_bytes = Path(snap_path).stat().st_size if Path(snap_path).exists() else 0
            k.close()
            # restore in a FRESH kernel process (true cross-process restore)
            k2 = RawKernel(cmd, cwd=str(work), env=env,
                           stderr_path=str(P.BENCH / f"logs/kernel-raw-{product_name}-r{i}.stderr"))
            ready2_s, _ = k2.ready()
            restore_ms = k2.restore(snap_path)
            check_ms = k2.execute("assert len(raw_frame) == 655360\nprint('raw-check-ok')")
            results.append({
                "product": product_name, "trial": i, "python": py,
                "ready_ms": round(ready_s * 1000, 1),
                "first_cell_ms": round(first_cell_ms, 1),
                "warm_cell_p50_ms": round(sorted(warm)[len(warm) // 2], 1),
                "state_build_ms": round(state_ms, 1),
                "snapshot_ms": round(snap_ms, 1),
                "snapshot_bytes": snap_bytes,
                "restore_ready_ms": round(ready2_s * 1000, 1),
                "restore_ms": round(restore_ms, 1),
                "post_restore_cell_ms": round(check_ms, 1),
            })
        finally:
            k.close()
    with open(out_path, "a") as f:
        for r in results:
            f.write(json.dumps({"benchmark": "kernel.raw_substrate", **r}) + "\n")
    return results


if __name__ == "__main__":
    out = P.BENCH / "results" / "kernel.raw_substrate" / "trials-raw.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    prod = sys.argv[1] if len(sys.argv) > 1 else "rust"
    reps = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    for r in run_raw_probe(prod, out, reps):
        print(json.dumps(r))
