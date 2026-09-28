"""compare.memory_idle: plain idle process-tree RSS (no fixture).

The all-five-products complement to compare.memory_idle_load (which needs
the 10MiB fixture and therefore only applies to resume-capable products):
launch each product to a ready interactive session (the cold-start
readiness probe), erase the probe token, let the tree settle, then sample
the whole process tree's RSS/PSS with the same /proc sampler
(rss_tree: psutil tree + smaps_rollup PSS, nproc coverage flag).
"""
from __future__ import annotations

import time

from bench.adapters.benchmarks.cold_start import ONBOARDING_AUTODISMISS
from bench.adapters.benchmarks.support import PROBE_TOKEN, first_paint, prepass
from bench.core.benchmark import Benchmark
from bench.core.process import loadavg, rss_tree

IDLE_SETTLE_S = 3.0


class MemoryIdle(Benchmark):
    """Idle process-tree memory at a plain ready session (all products)."""

    name = "compare.memory_idle"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        spec = cfg.get("benchmarks", {}).get(self.name, {})
        self.ready_timeout_s = float(spec.get("ready_timeout_s", 120.0))

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
            rss = rss_tree(app.pid)
            record["metrics"] = {
                "launch_to_ready_ms": probe["echo_ts_offset_ms"],
                "erase_ok": erase_ok,
                "erase_ms": erase_ms,
            }
            record["probe"] = {"grid_ms": probe["probe_grid_ms"],
                               "input_buffered": probe["input_buffered"],
                               "quantized_ms": probe["quantized_ms"],
                               "sends": probe["sends"],
                               "dialog_ms": probe["dialog_ms"]}
            record["validation"] = {"echoed": True, "erased": erase_ok}
            record["resource"] = {"rss_settled": rss, "loadavg_before": t_load,
                                  "loadavg_after": loadavg()}
        finally:
            app.kill_tree()
            product.reap(ctx)
