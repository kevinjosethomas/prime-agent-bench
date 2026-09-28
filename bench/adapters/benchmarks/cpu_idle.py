"""compare.cpu_idle: idle CPU% and wake rate of the process tree.

All five products: launch to a ready interactive session, settle, then
sample /proc/<pid>/stat (utime+stime clock ticks) and
/proc/<pid>/status (voluntary + nonvoluntary context switches) for the
whole process tree at the window's start and end. Deltas over the fixed
idle window give idle CPU% (ticks / CLK_TCK / seconds) and the wake rate
(context switches per second — each blocking wait that returns is a
voluntary switch, so the total switch rate is the wake proxy).
"""
from __future__ import annotations

import os
import time

from bench.adapters.benchmarks.cold_start import ONBOARDING_AUTODISMISS
from bench.adapters.benchmarks.support import PROBE_TOKEN, first_paint, prepass
from bench.core.benchmark import Benchmark
from bench.core.process import loadavg

IDLE_SETTLE_S = 3.0
IDLE_WINDOW_S = 10.0

CLK_TCK = os.sysconf("SC_CLK_TCK")


def cpu_tree(pid) -> dict:
    """utime+stime ticks and context-switch counts summed over the tree."""
    import psutil
    try:
        root = psutil.Process(pid)
        procs = [root] + root.children(recursive=True)
    except psutil.Error:
        return {"utime_ticks": 0, "stime_ticks": 0, "nvcsw": 0,
                "nivcsw": 0, "nproc": 0}
    utime = stime = nvcsw = nivcsw = 0
    for p in procs:
        try:
            with open("/proc/%d/stat" % p.pid) as f:
                # comm may contain spaces/parens: everything past the last ') '
                parts = f.read().rsplit(") ", 1)[1].split()
                utime += int(parts[11])   # stat field 14 (utime)
                stime += int(parts[12])   # stat field 15 (stime)
        except (OSError, ValueError, IndexError, psutil.Error):
            continue
        try:
            with open("/proc/%d/status" % p.pid) as f:
                for line in f:
                    if line.startswith("voluntary_ctxt_switches:"):
                        nvcsw += int(line.split()[1])
                    elif line.startswith("nonvoluntary_ctxt_switches:"):
                        nivcsw += int(line.split()[1])
        except (OSError, ValueError, psutil.Error):
            continue
    return {"utime_ticks": utime, "stime_ticks": stime, "nvcsw": nvcsw,
            "nivcsw": nivcsw, "nproc": len(procs)}


def _deltas(s0: dict, s1: dict, window_s: float) -> dict:
    ticks = (s1["utime_ticks"] - s0["utime_ticks"]) + (s1["stime_ticks"] - s0["stime_ticks"])
    vcsw = s1["nvcsw"] - s0["nvcsw"]
    ivcsw = s1["nivcsw"] - s0["nivcsw"]
    return {
        "idle_cpu_pct": round(ticks / CLK_TCK / window_s * 100.0, 3),
        "wakes_per_s": round((vcsw + ivcsw) / window_s, 2),
        "involuntary_wakes_per_s": round(ivcsw / window_s, 2),
        "cpu_ticks": ticks,
        "ctx_switches": vcsw + ivcsw,
    }


class CpuIdle(Benchmark):
    """Idle CPU% + wake rate at a plain ready session (all products)."""

    name = "compare.cpu_idle"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        spec = cfg.get("benchmarks", {}).get(self.name, {})
        self.ready_timeout_s = float(spec.get("ready_timeout_s", 120.0))
        self.window_s = float(spec.get("idle_window_s", IDLE_WINDOW_S))

    def measure(self, product, ctx, record, driver, fixture=None) -> None:
        if product.needs_prepass:
            prepass(product, ctx, driver)
        t_load = loadavg()
        app = product.launch(ctx, driver)
        try:
            t_paint = first_paint(app)
            probe = app.probe_input_ready(PROBE_TOKEN, retry_every=0.5,
                                          timeout=self.ready_timeout_s, start_ts=t_paint,
                                          dialog_steps=ONBOARDING_AUTODISMISS)
            erase_ok, erase_ms = app.erase_all(
                PROBE_TOKEN, max_backspaces=probe["chars_sent"] + 8)
            time.sleep(IDLE_SETTLE_S)
            s0 = cpu_tree(app.pid)
            t0 = time.monotonic()
            time.sleep(self.window_s)
            s1 = cpu_tree(app.pid)
            window_s = time.monotonic() - t0
            deltas = _deltas(s0, s1, window_s)
            record["metrics"] = {
                "launch_to_ready_ms": probe["echo_ts_offset_ms"],
                "erase_ok": erase_ok,
                "erase_ms": erase_ms,
                "idle_cpu_pct": deltas["idle_cpu_pct"],
                "wakes_per_s": deltas["wakes_per_s"],
                "involuntary_wakes_per_s": deltas["involuntary_wakes_per_s"],
                "idle_window_s": round(window_s, 2),
                "nproc_end": s1["nproc"],
            }
            record["probe"] = {"grid_ms": probe["probe_grid_ms"],
                               "input_buffered": probe["input_buffered"],
                               "quantized_ms": probe["quantized_ms"],
                               "sends": probe["sends"],
                               "dialog_ms": probe["dialog_ms"]}
            record["validation"] = {"echoed": True, "erased": erase_ok,
                                    "tree_alive": s1["nproc"] >= 1,
                                    "tree_stable": s0["nproc"] == s1["nproc"]}
            record["resource"] = {"cpu_window": {"start": s0, "end": s1,
                                                 "ticks": deltas["cpu_ticks"],
                                                 "ctx_switches": deltas["ctx_switches"],
                                                 "window_s": round(window_s, 2)},
                                 "loadavg_before": t_load, "loadavg_after": loadavg()}
        finally:
            app.kill_tree()
            product.reap(ctx)
