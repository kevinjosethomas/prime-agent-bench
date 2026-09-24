"""compare.memory_idle_load: process-tree RSS after a loaded cold start.

Launch (resuming the session fixture when the product supports --resume),
reach interactive-ready, settle for the idle window, then account the
whole process tree (RSS/PSS/process count).
"""
from __future__ import annotations

import time

from bench.adapters.benchmarks.support import PROBE_TOKEN, first_paint, prepass
from bench.core.benchmark import Benchmark
from bench.core.process import loadavg, rss_tree

IDLE_SETTLE_S = 3.0


class MemoryIdleLoad(Benchmark):
    """Idle process-tree memory after a (optionally loaded) cold start."""

    name = "compare.memory_idle_load"
    requires_fixture = "session-10mib"

    def measure(self, product, ctx, record, driver, fixture=None) -> None:
        if product.needs_prepass:
            prepass(product, ctx, driver)
        t_load = loadavg()
        app = product.launch(ctx, driver, resume_fixture=str(fixture) if fixture else None)
        try:
            t_paint = first_paint(app, timeout=120)
            probe = app.probe_input_ready(PROBE_TOKEN, retry_every=0.5, timeout=120,
                                          start_ts=t_paint)
            app.erase_all(PROBE_TOKEN)
            time.sleep(IDLE_SETTLE_S)
            rss = rss_tree(app.pid)
            record["metrics"] = {
                "launch_to_ready_ms": probe["echo_ts_offset_ms"],
            }
            record["validation"] = {"echoed": True}
            record["resource"] = {"rss_settled": rss, "loadavg_before": t_load}
        finally:
            app.kill_tree()
            product.reap(ctx)
