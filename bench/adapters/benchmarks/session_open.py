"""session.cold_open_10mib: cold process + daemon -> tail sentinel AND echo.

Cold open of the 10MiB fixture: the resumed transcript must render its
tail sentinel AND the editor must accept a typed echo. Spec §A scopes
session.* benchmarks to Prime Agent Rust/TS (they resume the Prime session
fixture); other products are preserved as not_applicable status rows by
the trial engine, never measured on a fresh session.
"""
from __future__ import annotations

import time

from bench.adapters.benchmarks.support import (PROBE_TOKEN, first_paint,
                                                prepass, wait_sentinel)
from bench.adapters.fixtures.session_size import SENTINEL
from bench.core.benchmark import Benchmark
from bench.core.harness import now
from bench.core.process import loadavg, rss_tree


class SessionColdOpen(Benchmark):
    """Cold open of the 10MiB session fixture -> interactive."""

    name = "session.cold_open_10mib"
    requires_fixture = "session-10mib"
    applicable_products = ["rust", "ts"]  # spec §A: session.* is RT-only
    applicability_note = ("session.* benchmarks resume the Prime session fixture; "
                          "BENCHMARK_SUITE_SPEC §A scopes them to Prime Agent Rust/TS")

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        spec = cfg.get("benchmarks", {}).get(self.name, {})
        self.ready_timeout_s = float(spec.get("ready_timeout_s", 120.0))
        self.sentinel_timeout_s = float(spec.get("sentinel_timeout_s", 30.0))

    def measure(self, product, ctx, record, driver, fixture=None) -> None:
        t_load = loadavg()
        if product.needs_prepass:
            prepass(product, ctx, driver)
        app = product.launch(ctx, driver, resume_fixture=str(fixture))
        try:
            t_paint = first_paint(app, timeout=120)
            # interactive-ready FIRST (bounded): the measured boundary is the
            # typed echo, so it must never sit behind the sentinel deadline
            probe = app.probe_input_ready(PROBE_TOKEN, retry_every=0.5,
                                          timeout=self.ready_timeout_s, start_ts=t_paint)
            # bounded tail-sentinel wait AFTER ready: the per-trial proof the
            # fixture transcript actually loaded. Missing -> the row is
            # invalid (never a fast success on an empty session).
            t_sentinel = wait_sentinel(app, SENTINEL, timeout=self.sentinel_timeout_s)
            erase_ok, _ = app.erase_all(probe["probe_tokens"],
                                         max_backspaces=probe["chars_sent"] + 8)
            record.setdefault("fixture", {})["loaded"] = t_sentinel is not None
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
            # harness-floor evidence (audit F13): probe-grid quantization of
            # the ready value, and whether input was buffered or dropped
            record["probe"] = {"grid_ms": probe["probe_grid_ms"],
                               "input_buffered": probe["input_buffered"],
                               "quantized_ms": probe["quantized_ms"],
                               "sends": probe["sends"]}
            record["validation"] = {"sentinel": t_sentinel is not None, "echoed": True, "erased": erase_ok}
            record["resource"] = {"rss_10mib": rss, "loadavg_before": t_load}
        finally:
            app.kill_tree()
            product.reap(ctx)
