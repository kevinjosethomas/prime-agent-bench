"""compare.cold_start: launch -> first paint -> typed echo accepted -> erase.

Onboarding dialogs are NOT product performance, and consent-settled
products never see one: products that seed the return-user consent
baseline (``seeds_consent_baseline``) launch a home whose settings.json
already carries onboardingShown/agentTraces/telemetry.noticeShown, so any
first-run sheet sighted during the measured launch is a BASELINE BREACH —
the row records it, the validation fails, and the strict validity gate
excludes it (never auto-dismissed and measured; no pre-settle process
runs inside the measured cold-start). Products without a seedable
baseline keep the walk semantics: a dialog is auto-dismissed, dialog time
is excluded from the gap, and the event is disclosed per row.
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
    """The cold-start measurement (shared with compare.warm_start).

    First paint is the first non-blank frame (kept as its own metric; the
    onboarding dialogs, when they appear, do not restart it). Interactive
    readiness is probed from that paint with the onboarding markers
    answered inline by the probe loop: dialog time is excluded from the
    gap and disclosed per row (audit F13's ~2s probe floor was two 1.0s
    blocking waits for absent markers burned between paint and the first
    probe on every trial; the probe now starts immediately).
    """
    if product.needs_prepass:
        prepass(product, ctx, driver)
    # the measured launch runs on the consent-settled template home (no
    # pre-settle process: the baseline is seeded at template build, so a
    # measured cold-start is exactly what the campaign measures)
    baseline = product.seeds_consent_baseline
    breaches: list[str] = []
    t_load = loadavg()
    app = product.launch(ctx, driver)
    try:
        t_paint = first_paint(app)
        probe = app.probe_input_ready(PROBE_TOKEN, retry_every=0.5, timeout=45.0,
                                      start_ts=t_paint,
                                      dialog_steps=ONBOARDING_AUTODISMISS)
        if baseline:
            # sheets answered mid-probe survived the seeded baseline
            breaches += probe["dialogs"]
        # the erase budget must cover every probe char sent, and the
        # verification certifies EVERY attempt token gone (the input line
        # may hold buffered tokens from every unconfirmed attempt)
        erase_ok, erase_ms = app.erase_all(
            probe["probe_tokens"], max_backspaces=probe["chars_sent"] + 8)
        time.sleep(1.0)  # settled idle
        if baseline:
            # the observed sheet shape pops async AFTER ready (seconds in,
            # past the probe echo): a sighting in the settled window is a
            # breach even when the probe phase was clean
            settled = " ".join(app.screen_text().split())
            breaches += [m for m, _ in ONBOARDING_AUTODISMISS
                        if m in settled and m not in breaches]
        rss = rss_tree(app.pid)
        bursts = app.burst_stats(t_start=app.t_spawn, t_end=now())
        record["metrics"] = {
            "launch_to_first_paint_ms": round((t_paint - app.t_spawn) * 1000.0, 1),
            "launch_to_ready_ms": probe["echo_ts_offset_ms"],
            "input_ready_gap_ms": probe["gap_ms"],
            # legacy key, kept for row-schema continuity: None in new rows —
            # a true drop is unknowable from screen observation (see
            # probe_input_ready); old-campaign rows keep their raw values
            "dropped_probes": probe["dropped_probes"],
            "unconfirmed_attempts": probe["unconfirmed_attempts"],
            "erase_ok": erase_ok,
            "erase_ms": erase_ms,
            "pty_bytes": app.bytes_out(),
            "frame_bursts": bursts["bursts"] if bursts else None,
            "burst_bytes": bursts["per_burst_bytes"][:8] if bursts else None,
        }
        # harness-floor evidence (audit F13): how much of the ready value is
        # probe-grid quantization, and whether the product buffers input
        record["probe"] = {"grid_ms": probe["probe_grid_ms"],
                           "input_buffered": probe["input_buffered"],
                           "quantized_ms": probe["quantized_ms"],
                           "sends": probe["sends"],
                           "dialog_ms": probe["dialog_ms"]}
        if probe["dialogs"]:
            record["dialog_autodismissed"] = probe["dialogs"][0][:40]
        if baseline:
            # report-not-hack: a sheet on a consent-settled home means the
            # baseline did not hold (stale template or a product that
            # re-triggers first-run state, e.g. after a daemon restart) —
            # the row keeps its numbers but the validation fails, and the
            # strict validity gate excludes it as validation_failed
            record["consent_baseline_breach"] = breaches
            record["validation"] = {"echoed": True, "erased": erase_ok,
                                    "consent_baseline_intact": not breaches}
        else:
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
