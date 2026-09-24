"""compare.memory_idle_load: process-tree RSS after a loaded cold start.

Rust/TS resume the verified 10MiB fixture (their argv consumes
resume_fixture), so their idle RSS is a loaded-session number with
sentinel evidence. Products whose argv ignores the fixture have no
vendor-native large history yet: the trial engine records them as
not_comparable status rows (spec §F) instead of measuring a fresh
session and calling it comparable — fresh-session RSS already lives in
compare.cold_start's resource evidence.
"""
from __future__ import annotations

import time

from bench.adapters.benchmarks.support import (PROBE_TOKEN, first_paint,
                                                prepass, wait_sentinel)
from bench.adapters.fixtures.session_size import SENTINEL
from bench.core.benchmark import Benchmark
from bench.core.process import loadavg, rss_tree

IDLE_SETTLE_S = 3.0


class MemoryIdleLoad(Benchmark):
    """Idle process-tree memory after a loaded cold start."""

    name = "compare.memory_idle_load"
    requires_fixture = "session-10mib"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        spec = cfg.get("benchmarks", {}).get(self.name, {})
        self.ready_timeout_s = float(spec.get("ready_timeout_s", 120.0))
        self.sentinel_timeout_s = float(spec.get("sentinel_timeout_s", 30.0))

    def measure(self, product, ctx, record, driver, fixture=None) -> None:
        if product.needs_prepass:
            prepass(product, ctx, driver)
        t_load = loadavg()
        app = product.launch(ctx, driver, resume_fixture=str(fixture) if fixture else None)
        try:
            t_paint = first_paint(app, timeout=120)
            probe = app.probe_input_ready(PROBE_TOKEN, retry_every=0.5,
                                          timeout=self.ready_timeout_s, start_ts=t_paint)
            # fixture evidence: the loaded 10MiB transcript's tail rendered.
            # Missing sentinel invalidates the row (fresh-session RSS must
            # never be ranked as a loaded-session number).
            t_sentinel = wait_sentinel(app, SENTINEL, timeout=self.sentinel_timeout_s)
            app.erase_all(PROBE_TOKEN)
            record.setdefault("fixture", {})["loaded"] = t_sentinel is not None
            time.sleep(IDLE_SETTLE_S)
            rss = rss_tree(app.pid)
            record["metrics"] = {
                "launch_to_ready_ms": probe["echo_ts_offset_ms"],
            }
            record["validation"] = {"sentinel": t_sentinel is not None, "echoed": True}
            record["resource"] = {"rss_settled": rss, "loadavg_before": t_load}
        finally:
            app.kill_tree()
            product.reap(ctx)
