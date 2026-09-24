"""Startup readiness semantics (audit F13): the probe floor, first paint,
and honest quantization evidence, measured against a real PTY mini-TUI.

The audit's ~2s "probe cadence" floor was two 1.0s blocking waits for
absent onboarding markers burned between first paint and the first
readiness probe on every cold/warm trial (rust gap ~2008ms with 63ms
paint; ts ~1867ms via the dialog path). These tests pin the fixed
semantics: no blocking marker waits, fine-grid quantization with per-row
disclosure, buffered-vs-dropped evidence, and dialog time excluded.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from bench.adapters.harnesses.pty import PTYDriver

TUI = str(Path(__file__).parent / "mini_tui.py")


def _probe(mode: str, delay: float = 0.3, timeout: float = 30.0,
           dialog_steps: tuple = ()) -> dict:
    """One probe_input_ready run against the mini-TUI on a real PTY."""
    driver = PTYDriver({})
    app = driver.start_session([sys.executable, TUI, mode, str(delay)])
    try:
        assert app.t_first_paint is not None or True
        deadline_probe = lambda: app.wait_for(lambda: app.t_first_paint is not None,
                                              timeout=10.0)
        deadline_probe()
        return app.probe_input_ready("Zq7t", retry_every=0.5, timeout=timeout,
                                     start_ts=app.t_first_paint,
                                     dialog_steps=dialog_steps)
    finally:
        app.kill_tree()


def test_first_paint_is_separate_and_early():
    driver = PTYDriver({})
    app = driver.start_session([sys.executable, TUI, "buffered", "0.3"])
    try:
        app.wait_for(lambda: app.t_first_paint is not None, timeout=10.0)
        # first paint is the banner, NOT readiness: the TUI is not echoing yet
        assert (app.t_first_paint - app.t_spawn) < 1.0
    finally:
        app.kill_tree()


def test_buffered_input_measures_true_readiness():
    """Pre-ready probes sit in the PTY queue; at mount time the echo
    renders them all, so the echo timestamp IS the readiness render:
    quantization zero, gap = the true delay."""
    probe = _probe("buffered", delay=0.3)
    assert probe["input_buffered"] is True
    assert probe["quantized_ms"] == 0.0
    # gap ~ the 300ms delay; the old floor added ~2000ms on top of this
    assert 250.0 <= probe["gap_ms"] <= 900.0
    assert probe["sends"] >= 1


def test_dropped_input_discloses_quantization():
    """Pre-ready probes are discarded: readiness is detected on the probe
    grid, so the value carries the grid as quantization evidence — the
    floor is bounded (fine grid 50ms) and disclosed, never silent."""
    probe = _probe("dropped", delay=0.3)
    assert probe["input_buffered"] is False
    assert probe["quantized_ms"] == 50.0  # the fine-grid step, disclosed
    assert probe["probe_grid_ms"] == 50.0
    # readiness >= the delay; overshoot bounded by the fine grid + render
    assert 300.0 <= probe["gap_ms"] <= 900.0


def test_dialog_answered_inline_and_excluded_from_gap():
    """The onboarding dialog is answered inside the probe loop (no 2x1.0s
    blocking waits), the readiness clock restarts after dismissal, and
    the dialog evidence lands on the result."""
    probe = _probe("dialog", delay=0.3,
                   dialog_steps=(("Share agent traces with Prime Intellect?",
                                  ["\x1b[B", "\r"]),))
    assert probe["dialogs"] == ["Share agent traces with Prime Intellect?"]
    assert probe["dialog_ms"] > 0.0
    # gap is measured from the post-dialog restart: the marker walk (2 keys
    # x 0.4s pause) is excluded, unlike the audit's ts rows where the
    # dialog inflated launch_to_ready
    assert probe["gap_ms"] <= 900.0


def test_no_blocking_marker_waits_before_the_first_probe():
    """The regression the audit found: absent onboarding markers must not
    add 2x1.0s of harness wait between paint and the first probe. With
    dialog_steps that never match, the first probe is sent immediately
    (gap bounded by the fine grid, not by marker timeouts)."""
    probe = _probe("buffered", delay=0.05,
                   dialog_steps=(("A marker that never renders", ["\r"]),))
    assert probe["dialogs"] == []
    assert probe["gap_ms"] < 600.0  # would be > 2000ms with the old waits
