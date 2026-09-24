"""compare.cold_start: launch -> first paint -> typed echo accepted -> erase.

Onboarding dialogs are NOT product performance: if one appears, the harness
auto-dismisses it and the ready measurement starts after the dismissal
(dialog time excluded, event recorded). Also records the input gap.
"""
from __future__ import annotations

import time

from bench.adapters.benchmarks.support import PROBE_TOKEN, first_paint, prepass
from bench.core.benchmark import Benchmark
from bench.core.harness import HarnessDriver, now
from bench.core.product import ProductAdapter, TrialContext
from bench.core.process import loadavg, rss_tree

ONBOARDING_AUTODISMISS = [
    ("Share agent traces with Prime Intellect?", ["\x1b[B", "\r"]),
    ("Do you want to use this API key?", ["\x1b[A", "\r"]),
]


def measure_cold_start(product: ProductAdapter, ctx: TrialContext, record: dict,
                       driver: HarnessDriver) -> None:
    """The cold-start measurement (shared with compare.warm_start)."""
    if product.needs_prepass:
        prepass(product, ctx, driver)
    t_load = loadavg()
    app = product.launch(ctx, driver)
    try:
        t_paint = first_paint(app)
        # onboarding-artifact safety net (should never fire with settled
        # templates; if it does, exclude its time)
        for marker, keys in ONBOARDING_AUTODISMISS:
            try:
                app.wait_screen_contains(marker, timeout=1.0)
                for k in keys:
                    app.send(k)
                    time.sleep(0.4)
                app.wait_screen_missing(marker, timeout=3.0)
                record["dialog_autodismissed"] = marker[:40]
                t_paint = first_paint(app)  # restart the clock after dismissal
            except TimeoutError:
                pass
        probe = app.probe_input_ready(PROBE_TOKEN, retry_every=0.5, timeout=45.0,
                                      start_ts=t_paint)
        erase_ok, erase_ms = app.erase_all(PROBE_TOKEN)
        time.sleep(1.0)  # settled idle
        rss = rss_tree(app.pid)
        bursts = app.burst_stats(t_start=app.t_spawn, t_end=now())
        record["metrics"] = {
            "launch_to_first_paint_ms": round((t_paint - app.t_spawn) * 1000.0, 1),
            "launch_to_ready_ms": probe["echo_ts_offset_ms"],
            "input_ready_gap_ms": probe["gap_ms"],
            "dropped_probes": probe["dropped_probes"],
            "erase_ok": erase_ok,
            "erase_ms": erase_ms,
            "pty_bytes": app.bytes_out(),
            "frame_bursts": bursts["bursts"] if bursts else None,
            "burst_bytes": bursts["per_burst_bytes"][:8] if bursts else None,
        }
        record["validation"] = {"echoed": True, "erased": erase_ok}
        record["resource"] = {"rss_settled": rss, "loadavg_before": t_load, "loadavg_after": loadavg()}
    finally:
        app.kill_tree()
        product.reap(ctx)


class ColdStart(Benchmark):
    """Launch -> typed echo accepted -> erase (interactive-ready)."""

    name = "compare.cold_start"

    def measure(self, product, ctx, record, driver, fixture=None) -> None:
        measure_cold_start(product, ctx, record, driver)
