"""compare.cold_start: launch -> first paint -> typed echo accepted -> erase.

Onboarding dialogs are NOT product performance: if one appears, the harness
auto-dismisses it and the ready measurement starts after the dismissal
(dialog time excluded, event recorded). Also records the input gap.
"""
from __future__ import annotations

import os
import re
import time

from bench.adapters.benchmarks.support import PROBE_TOKEN, first_paint, prepass
from bench.core.benchmark import Benchmark
from bench.core.harness import HarnessDriver, now
from bench.core.product import ProductAdapter, TrialContext
from bench.core.process import (loadavg, pids_referencing, proc_identity, rss_pids,
                                rss_tree)

ONBOARDING_AUTODISMISS = [
    ("Share agent traces with Prime Intellect?", ["\x1b[B", "\r"]),
    ("Do you want to use this API key?", ["\x1b[A", "\r"]),
]


def _contains_seq(argv: list, tokens: tuple) -> bool:
    """Whether ``tokens`` appear contiguously in ``argv``."""
    n = len(tokens)
    return any(tuple(argv[i:i + n]) == tokens for i in range(len(argv) - n + 1))


def daemon_identity(product: ProductAdapter, ctx: TrialContext, pids: list) -> dict | None:
    """The launch identity of the product's resident daemon among ``pids``
    (argv + env beyond the trial launch env), or None if none runs."""
    if not product.daemon_process_args:
        return None
    base = product.env(ctx)
    for pid in pids:
        ident = proc_identity(pid, base, ctx["trial_dir"])
        if ident and _contains_seq(ident["argv"], product.daemon_process_args):
            # env the product's CLI stamps on every child it spawns is
            # disclosed, not compared (it marks the spawner, not a setting)
            ident["spawn_env"] = {k: ident["env_added"].pop(k)
                                  for k in product.daemon_spawn_env_keys
                                  if k in ident["env_added"]}
            return ident
    return None


def input_row_ok(product: ProductAdapter, row: str | None) -> bool:
    """Whether the echoed token sits on the product's prompt input row: the
    row text before the first probe token matches the product's declared
    ``input_prompt`` (its prompt glyph)."""
    if not row or PROBE_TOKEN not in row:
        return False
    return re.fullmatch(product.input_prompt, row[:row.index(PROBE_TOKEN)]) is not None


def measure_cold_start(product: ProductAdapter, ctx: TrialContext, record: dict,
                       driver: HarnessDriver, prepassed: bool = False,
                       expect_resident: bool = False) -> None:
    """The cold-start measurement (shared with compare.warm_start).

    First paint is the first non-blank frame (kept as its own metric; the
    onboarding dialogs, when they appear, do not restart it). Interactive
    readiness = the product's prompt input is mounted and a typed probe
    token renders in it: probes are typed only once the product has taken
    the tty out of cooked mode (a cooked tty echoes by itself), the echo
    must land on the product's input row, and it must still be there after
    the settle (a pre-mount echo cell that the mounted UI wipes is not
    readiness). Onboarding markers are answered inline by the probe loop:
    dialog time is excluded from the gap and disclosed per row.

    Every product gets the same storage treatment right before the
    measured launch: ``os.sync()`` flushes what the harness wrote (trial
    home copy, prepass, daemon prewarm), so no product's own fsyncs pay
    for it. The trial's processes alive at launch are recorded and
    checked: a cold launch starts with none (the prepass sweep killed any
    daemon it left), a warm launch onto a resident daemon
    (``expect_resident``) with it; no other trial's process may be alive.
    """
    if product.needs_prepass and not prepassed:
        prepass(product, ctx, driver)
    trial_needle = [str(ctx["trial_dir"])]
    os.sync()
    resident = pids_referencing(trial_needle)
    resident_pids = {pid for pid, _ in resident}
    foreign = [cmd for pid, cmd in pids_referencing([str(product.layout.trials_root)])
               if pid not in resident_pids]
    daemon_at_launch = daemon_identity(product, ctx, sorted(resident_pids))
    t_load = loadavg()
    app = product.launch(ctx, driver)
    try:
        t_paint = first_paint(app)
        probe = app.probe_input_ready(PROBE_TOKEN, retry_every=0.5, timeout=45.0,
                                      start_ts=t_paint,
                                      dialog_steps=ONBOARDING_AUTODISMISS)
        time.sleep(0.5)
        persisted_row = app.screen_row_with(probe["probe_token"])
        # the erase budget must cover every probe char sent (the input line
        # may hold dropped/buffered tokens from every attempt)
        erase_ok, erase_ms = app.erase_all(
            PROBE_TOKEN, max_backspaces=probe["chars_sent"] + 8,
            refresh_keys=product.erase_refresh_keys)
        time.sleep(1.0)  # settled idle
        rss = rss_tree(app.pid)
        trial_procs = pids_referencing(trial_needle)
        bursts = app.burst_stats(t_start=app.t_spawn, t_end=now())
        paint_ms = round((t_paint - app.t_spawn) * 1000.0, 1)
        record["metrics"] = {
            "launch_to_first_paint_ms": paint_ms,
            "launch_to_ready_ms": probe["echo_ts_offset_ms"],
            "input_ready_gap_ms": probe["gap_ms"],
            "dropped_probes": probe["dropped_probes"],
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
                           "dialog_ms": probe["dialog_ms"],
                           "tty_raw_ms": probe["tty_raw_ms"],
                           "echo_row": (probe["echo_row"] or "").strip()[:120],
                           "persisted_row": (persisted_row or "").strip()[:120]}
        if probe["dialogs"]:
            record["dialog_autodismissed"] = probe["dialogs"][0][:40]
        record["resident_at_launch"] = [cmd for _pid, cmd in resident]
        record["foreign_at_launch"] = foreign
        record["trial_procs_settled"] = [cmd for _pid, cmd in trial_procs]
        settled_daemon = daemon_identity(product, ctx, [pid for pid, _ in trial_procs])
        record["daemon_identity"] = daemon_at_launch or settled_daemon
        record["validation"] = {
            "echoed": True,
            "erased": erase_ok,
            "resident_as_expected": bool(resident) == expect_resident,
            "no_foreign_processes": not foreign,
            # a raw tty at the first probe (None: the driver cannot tell)
            "typed_into_raw_tty": probe["tty_raw_at_first_send"] is not False,
            "token_in_input_row": input_row_ok(product, probe["echo_row"]),
            "token_persisted": input_row_ok(product, persisted_row),
            "ready_after_paint": probe["echo_ts_offset_ms"] >= paint_ms,
        }
        # rss_settled: the TUI's process tree; rss_trial: every process of
        # the trial (adds a detached daemon the tree does not contain)
        record["resource"] = {"rss_settled": rss,
                              "rss_trial": rss_pids([pid for pid, _ in trial_procs]),
                              "loadavg_before": t_load, "loadavg_after": loadavg()}
    finally:
        app.kill_tree()
        product.reap(ctx)


class ColdStart(Benchmark):
    """Launch -> typed echo accepted -> erase (interactive-ready)."""

    name = "compare.cold_start"

    def measure(self, product, ctx, record, driver, fixture=None) -> None:
        measure_cold_start(product, ctx, record, driver)
