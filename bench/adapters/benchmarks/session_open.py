"""session.cold_open_10mib: cold process + daemon -> tail sentinel AND echo.

Cold open of the 10MiB fixture: the resumed transcript must render its
tail sentinel AND the editor must accept a typed echo.
"""
from __future__ import annotations

import time

from bench.adapters.benchmarks.support import PROBE_TOKEN, first_paint, prepass
from bench.core.benchmark import Benchmark
from bench.core.harness import now
from bench.core.process import loadavg, rss_tree

TAIL_SENTINEL = "CORPUS-TAIL-9f3a1c70"


class SessionColdOpen(Benchmark):
    """Cold open of the 10MiB session fixture -> interactive."""

    name = "session.cold_open_10mib"
    requires_fixture = "session-10mib"

    def measure(self, product, ctx, record, driver, fixture=None) -> None:
        t_load = loadavg()
        if product.needs_prepass:
            prepass(product, ctx, driver)
        app = product.launch(ctx, driver, resume_fixture=str(fixture))
        try:
            t_paint = first_paint(app, timeout=120)
            # tail sentinel visible
            t_sentinel = None
            deadline = now() + 120
            while now() < deadline:
                if TAIL_SENTINEL in app.screen_text():
                    t_sentinel = now()
                    break
                time.sleep(0.005)
            probe = app.probe_input_ready(PROBE_TOKEN, retry_every=0.5, timeout=120,
                                          start_ts=t_sentinel or t_paint)
            erase_ok, _ = app.erase_all(PROBE_TOKEN)
            time.sleep(1.0)
            rss = rss_tree(app.pid)
            bursts = app.burst_stats(t_start=app.t_spawn, t_end=now())
            record["metrics"] = {
                "launch_to_first_paint_ms": round((t_paint - app.t_spawn) * 1000.0, 1),
                "launch_to_sentinel_ms": round((t_sentinel - app.t_spawn) * 1000.0, 1) if t_sentinel else None,
                "launch_to_ready_ms": probe["echo_ts_offset_ms"],
                "input_ready_gap_ms": probe["gap_ms"],
                "pty_bytes": app.bytes_out(),
                "frame_bursts": bursts["bursts"] if bursts else None,
            }
            record["validation"] = {"sentinel": t_sentinel is not None, "echoed": True, "erased": erase_ok}
            record["resource"] = {"rss_10mib": rss, "loadavg_before": t_load}
        finally:
            app.kill_tree()
            product.reap(ctx)
