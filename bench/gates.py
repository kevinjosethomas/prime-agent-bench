"""Load gates: block trials until the node is idle (fairness rule).

A confounding active process or elevated load invalidates cross-product
comparisons, so every trial waits for a clean environment first.
"""
from __future__ import annotations

import time

from bench.core.process import iter_proc_dirs, loadavg


def node_is_busy(cfg: dict) -> str | None:
    """A confounding active process, or None if the node is idle."""
    markers = tuple(cfg["load_gate"]["compile_markers"])
    try:
        load1 = loadavg()
    except OSError:
        return "loadavg-unreadable"
    for proc in iter_proc_dirs():
        try:
            argv = (proc / "cmdline").read_bytes().decode(errors="replace")
        except OSError:
            continue
        if any(m in argv for m in markers) and "bench" not in argv:
            return "compile:" + argv.split(chr(0))[0][:80]
    if load1 >= float(cfg["load_gate"]["load_threshold"]):
        return f"load:{load1}"
    return None


def gate_idle(cfg: dict, tag: str = "") -> str | None:
    """Block until the node is idle (fairness rule). Returns the last busy
    reason waited on, or None if it was idle immediately."""
    max_wait = float(cfg["load_gate"]["max_wait_s"])
    poll = float(cfg["load_gate"]["poll_s"])
    waited = None
    deadline = time.time() + max_wait
    while time.time() < deadline:
        busy = node_is_busy(cfg)
        if busy is None:
            return waited
        waited = busy
        time.sleep(poll)
    return waited
