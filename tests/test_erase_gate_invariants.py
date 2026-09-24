"""Erase-gate non-vacuity invariants (audit: run-2 TS stress 0/66 rendered).

A sheet covering the editor swallows raw stress sends, and erase_all
certifies absence — so without a positive pre-erase witness the stress
certification is vacuous (run-2 TS passed ``stress.erase_ok`` with 0/66
tokens rendered). The gate contract: dismiss sheets BEFORE sending
(positive screen match only), positively assert dialog-free at send
time, witness a sentinel appended right after the burst rendered in the
editor region (bounded wait), and the verdict rejects every vacuous
path. The sentinel proves focus, NOT full-cohort acceptance: the
missing-list is recorded and the full 66-token stress contract stays
uncertified until real proof.
"""
from __future__ import annotations

import importlib.util
import math
import sys
import time
import types
from pathlib import Path

import pytest

from bench.adapters.terminals.pty import PTYDriver

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_erase_pty.py"
TUI = str(Path(__file__).parent / "mini_tui.py")
MARKER = "Share agent traces with Prime Intellect?"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("verify_erase_pty", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeApp:
    """Screen-state machine: pops scripted screens, keeps the last."""

    def __init__(self, screens):
        self.screens = list(screens)
        self.sent = []

    def send(self, key: str) -> None:
        self.sent.append(key)

    def screen_text(self):
        if len(self.screens) > 1:
            return self.screens.pop(0)
        return self.screens[0] if self.screens else ""


def _passing_evidence() -> dict:
    return {
        "probe_witnessed": True,
        "erase_ok": True,
        "leftover_tokens": [],
        "post_erase_window_nonempty": True,
        "alive_after_erase": True,
        "fresh_echo_ok": True,
        "fresh_erase_ok": True,
        "mock_model_requests": 0,
        "stress": {"erase_ok": True},
        "stress_dialog_free": True,
        "stress_focus_verified": True,
        "stress_cohort_rendered_count": 66,
        "stress_early_rendered": True,
        "stress_late_rendered": True,
        "stress_missing_pre_erase": [],
    }


def test_dismiss_is_positive_match_only(gate, monkeypatch):
    monkeypatch.setattr(gate, "time",
                        types.SimpleNamespace(sleep=lambda s: None))
    sheet_then_clean = FakeApp([MARKER + "\neditor", "clean editor"])
    assert gate.dismiss_dialogs(sheet_then_clean) == 1
    assert sheet_then_clean.sent == ["\x1b[B", "\r"]
    clean = FakeApp(["clean editor"])
    assert gate.dismiss_dialogs(clean) == 0
    assert clean.sent == []  # never an unconditional keypress
    persistent = FakeApp([MARKER] * 3)
    # FakeApp keeps its last screen forever, so a never-clearing sheet
    # hits the bounded-rounds cap (4) — dismissals can never run unbounded
    assert gate.dismiss_dialogs(persistent) == 4


def test_sheet_covered_stress_input_is_not_certified(gate):
    """The run-2 TS shape: tokens sent under a sheet never render — the
    sentinel never echoes, so even a `true` stress erase (absence
    certified against the covered editor) must FAIL the gate."""
    covered_window = MARKER + "\n> Share\n  Not now"
    stress_tokens = [f"Zq7z{i:02d}" for i in range(1, 67)]
    missing = [t for t in stress_tokens if t not in covered_window]
    assert missing == stress_tokens  # zero rendered
    evidence = _passing_evidence()
    evidence["stress_focus_verified"] = False  # sentinel never echoed
    evidence["stress_missing_pre_erase"] = missing
    evidence["stress_cohort_rendered_count"] = 0
    assert gate.gate_pass(evidence) is False


def test_gate_pass_requires_every_witness(gate):
    assert gate.gate_pass(_passing_evidence()) is True
    flips = [
        ("probe_witnessed", False),
        ("erase_ok", False),
        ("leftover_tokens", ["Zq7x9"]),
        ("post_erase_window_nonempty", False),
        ("alive_after_erase", False),
        ("fresh_echo_ok", False),
        ("fresh_erase_ok", False),
        ("mock_model_requests", 1),
        ("stress_dialog_free", False),
        ("stress_focus_verified", False),
    ]
    for key, bad in flips:
        evidence = _passing_evidence()
        evidence[key] = bad
        assert gate.gate_pass(evidence) is False, key
    for key in ("reap_leftovers", "transcript_dump_error"):
        evidence = _passing_evidence()
        evidence[key] = "boom"
        assert gate.gate_pass(evidence) is False, key


def test_coalesced_cohort_does_not_false_fail(gate):
    """A partially-coalesced cohort (rust run-2 raw: 55/66 distinct) with
    the sentinel positively witnessed must still PASS: the missing-list
    is recorded evidence — never a synthetic pass nor a synthetic fail."""
    evidence = _passing_evidence()
    evidence["stress_missing_pre_erase"] = ["Zq7z58", "Zq7z66"]
    evidence["stress_cohort_rendered_count"] = 64
    evidence["stress_late_rendered"] = False
    assert gate.gate_pass(evidence) is True


def test_non_vacuous_probe_witness(gate):
    """probe_witnessed is the editor-region positive read of the
    SUCCESSFUL probe token (row-wise + seam-joined) — never a bare
    probe-return boolean; a product whose editor never rendered it
    must fail the gate."""
    evidence = _passing_evidence()
    evidence["probe_witnessed"] = False
    assert gate.gate_pass(evidence) is False


def test_real_pty_sheet_covered_input_witness(gate):
    """Real PTY: while the onboarding marker covers the screen, sent
    tokens are NOT on the editor rows (positive render absent); once the
    sheet clears and the queued input echoes, the witness clears. Bounded
    waits only."""
    driver = PTYDriver({})
    app = driver.start_session([sys.executable, TUI, "dialog", "1.5"])
    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and MARKER not in app.screen_text():
            time.sleep(0.05)
        assert MARKER in app.screen_text(), "mini-tui marker never rendered"
        tokens = ["Zb7q01", "Zb7q02", "Zb7q03"]
        for t in tokens:
            app.send(t)
        # bounded check inside the dialog window: tokens stay unrendered
        covered_at = time.monotonic() + 0.8
        covered = app.screen_text()
        while time.monotonic() < covered_at:
            covered = app.screen_text()
            if MARKER in covered and all(t not in covered for t in tokens):
                break
            time.sleep(0.05)
        assert MARKER in covered and all(t not in covered for t in tokens)
        # bounded wait for the queued input to echo after the sheet clears
        deadline = time.monotonic() + 6.0
        rendered = covered
        while time.monotonic() < deadline:
            rendered = app.screen_text()
            if all(t in rendered for t in tokens):
                break
            time.sleep(0.05)
        assert all(t in rendered for t in tokens), \
            "queued tokens never echoed after the sheet cleared"
    finally:
        app.kill_tree()


def test_real_pty_sentinel_witness_on_editor(gate):
    """Real PTY editor: the burst + sentinel land in the editor; the
    gate's own bounded wait witnesses the sentinel in the cursor-anchored
    editor region, and the representative early/late reads are positive."""
    driver = PTYDriver({})
    app = driver.start_session([sys.executable, TUI, "editor", "0.5"])
    try:
        tokens = [f"Zq7z{i:02d}" for i in range(1, 13)]  # small cohort
        for t in tokens:
            app.send(t)
        app.send(gate.STRESS_SENTINEL)
        cols = int(getattr(app, "cols", 0) or 120)
        rows_up_s = math.ceil(sum(len(t) for t in tokens) / cols) + 2
        app.wait_for(
            lambda: gate.token_in(*gate.editor_window(app, rows_up_s),
                                  gate.STRESS_SENTINEL),
            timeout=8.0, poll=0.05)
        window, joined = gate.editor_window(app, rows_up_s)
        assert gate.token_in(window, joined, gate.STRESS_SENTINEL)
        assert gate.token_in(window, joined, tokens[0])   # early
        assert gate.token_in(window, joined, tokens[-1])  # late
    finally:
        app.kill_tree()
