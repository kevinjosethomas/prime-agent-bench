"""Linux /proc process accounting for fair, isolated trials.

Trial sweeps, daemon reaping, marker detection, RSS accounting, and load
averages. On non-Linux dev machines the /proc-dependent sweeps degrade to
no-ops (nothing to sweep) so the package stays importable and testable.
Not part of any product. Benchmark harness only.
"""
from __future__ import annotations

import json
import os
import signal
import socket
import time
from pathlib import Path
from typing import Iterator

def iter_proc_dirs() -> Iterator[Path]:
    """Yield /proc/<pid> directories; nothing on non-Linux machines."""
    try:
        entries = list(Path("/proc").iterdir())
    except OSError:
        return
    for proc in entries:
        if proc.name.isdigit():
            yield proc


def loadavg() -> float:
    """The 1-minute load average (/proc/loadavg, os.getloadavg fallback)."""
    try:
        with open("/proc/loadavg") as f:
            return float(f.read().split()[0])
    except OSError:
        return os.getloadavg()[0]


def pids_referencing(needles) -> list:
    """(pid, cmdline-head) for processes whose argv or cwd references any
    needle path. The trial dir is unique per trial, so this is exact."""
    seen = []
    live = [str(n) for n in needles if n]
    for proc in iter_proc_dirs():
        pid = int(proc.name)
        if pid in (1, os.getpid()):
            continue
        try:
            argv = (proc / "cmdline").read_bytes().decode(errors="replace").replace(chr(0), " ")
        except OSError:
            continue
        try:
            cwd = os.readlink(proc / "cwd")
        except OSError:
            cwd = ""
        hit = any((n in argv) or (cwd and (cwd == n or cwd.startswith(n + "/"))) for n in live)
        if hit:
            seen.append((pid, argv[:110]))
    return seen


def wire_shutdown(socket_path: str) -> None:
    """Graceful daemon shutdown over the prime-agent.daemon wire protocol."""
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect(socket_path)
        envelope = {"type": "command", "id": "sd", "protocol": {"name": "prime-agent.daemon", "version": 7},
                    "command": {"type": "shutdown"}}
        s.sendall((json.dumps(envelope) + "\n").encode())
        time.sleep(1.5)
        s.close()
    except Exception:
        pass


def sweep_trial(ctx: dict) -> list:
    """Kill EVERY process belonging to this trial (TUI tree is already dead;
    this catches the daemon, its supervisor, detached workers, and kernels),
    with graceful wire shutdown first and SIGTERM->SIGKILL escalation until
    the table is clean. Returns the leftovers that survived (must be empty)."""
    if ctx.get("daemon_socket"):
        wire_shutdown(str(ctx["daemon_socket"]))
    needles = [str(ctx["trial_dir"]), str(ctx["tmp"])]
    leftovers = []
    for attempt in range(4):
        leftovers = pids_referencing(needles)
        if not leftovers:
            return []
        sig = signal.SIGTERM if attempt < 2 else signal.SIGKILL
        for pid, _ in leftovers:
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass
        time.sleep(1.0 if attempt < 2 else 0.7)
    return pids_referencing(needles)


def rss_pids(pids: list) -> dict:
    """Summed RSS of a flat pid set (each process counted once)."""
    import psutil
    rss = 0
    n = 0
    for pid in pids:
        try:
            rss += psutil.Process(pid).memory_info().rss
            n += 1
        except psutil.Error:
            continue
    return {"rss_mb": round(rss / (1 << 20), 1), "nproc": n}


def rss_tree(pid: int) -> dict:
    """RSS/PSS of a process tree (psutil for the tree, smaps for PSS)."""
    import psutil
    try:
        root = psutil.Process(pid)
        procs = [root] + root.children(recursive=True)
    except psutil.Error:
        return {"rss_mb": 0.0, "pss_mb": None, "nproc": 0}
    rss = 0
    pss = 0
    pss_ok = True
    for p in procs:
        try:
            rss += p.memory_info().rss
        except psutil.Error:
            continue
        try:
            with open(f"/proc/{p.pid}/smaps_rollup") as f:
                for line in f:
                    if line.startswith("Pss:"):
                        pss += int(line.split()[1]) * 1024
                        break
        except OSError:
            pss_ok = False
    return {"rss_mb": round(rss / (1 << 20), 1), "pss_mb": round(pss / (1 << 20), 1) if pss_ok else None,
            "nproc": len(procs)}
