"""Erase-probe semantics: one bounded backspace burst + one final screen
verification.

The live 4c59054 evidence: 22 buffered probe attempts queued ~132 chars
onto a wrapped input line, and the per-backspace 0.35s harness waits
burned 45,200ms of erase inside a ~50s trial (the needle stays rendered
until the last character goes, so every per-key wait timed out). The
burst erase must clear the same shape in processing time, must leave no
stale wrapped rows, and a stuck editor must report failure — never a
false success. Timing asserts here are evidence bounds: the old code's
cost on this exact shape is the 45,200ms live row, so a 2s ceiling has
~20x margin and is not a fudged-to-pass timeout.
"""
from __future__ import annotations

import sys
from pathlib import Path

from bench.adapters.terminals.pty import PTYDriver

TUI = str(Path(__file__).parent / "mini_tui.py")


def _editor_session(mode: str, delay: float, width: int = 120):
    driver = PTYDriver({})
    # the PTY and the mini editor MUST agree on cols: the editor's
    # wrapped-redraw math is width-based, a mismatched PTY drifts the
    # cursor (the harness would chase a phantom editor forever)
    app = driver.start_session([sys.executable, TUI, mode, str(delay), str(width)],
                               cols=width)
    try:
        app.wait_for(lambda: app.t_first_paint is not None, timeout=10.0)
    except Exception:
        app.kill_tree()
        raise
    return app


def test_buffered_probe_burst_erase_is_bounded_and_complete():
    """The buffered shape that burned 45s live: many probe attempts, every
    char queued and rendered at mount, wrapped across rows."""
    app = _editor_session("editor", 1.3)
    try:
        probe = app.probe_input_ready("Zq7e", retry_every=0.5, timeout=30.0,
                                      start_ts=app.t_first_paint)
        assert probe["sends"] >= 15          # the fine grid queued many tokens
        assert probe["input_buffered"] is True
        assert probe["unconfirmed_attempts"] == probe["sends"] - 1
        assert probe["dropped_probes"] is None   # disposition unknowable
        # certify EVERY attempt token gone — a base/last-token-only check
        # can leave earlier attempt tokens rendered (false success)
        ok, ms = app.erase_all(probe["probe_tokens"],
                               max_backspaces=probe["chars_sent"] + 8)
        assert ok is True
        # the per-key path burned 45,200ms live on this shape; the burst
        # must cost processing time, not per-key harness waits
        assert ms < 2000.0
        # no stale wrapped rows: every token is gone row-wise AND across
        # the wrap seam (a token split at the seam has no full substring
        # in any single row)
        text = app.screen_text()
        joined = "".join(text.splitlines())
        for tok in probe["probe_tokens"] + ["Zq7e"]:
            assert tok not in text and tok not in joined, tok
        # editor acceptance after the burst (surplus backspaces are no-ops):
        # fresh input still echoes
        app.start_echo_watch("Rf")
        app.send("Rf")
        app.wait_echo(2.0)
        assert "Rf" in app.screen_text()
    finally:
        app.kill_tree()


def test_sixty_six_token_stress_clears_a_six_row_wrapped_block():
    """The live DIAG3 shape: 66 probe attempts wrapped SIX rows on the
    Rust screen. The erase cap derives rows_up from the token list
    itself (ceil(total chars / cols) + margin — no fixed row count), so
    the editor scope covers the whole wrapped block and the burst clears
    it in processing time (the old per-key path cost 45,200ms on a
    fraction of this)."""
    app = _editor_session("editor", 0.2, width=60)  # 60 cols -> 66 tokens wrap >6 rows
    try:
        probe = app.probe_input_ready("Zq7q", retry_every=0.5, timeout=30.0,
                                      start_ts=app.t_first_paint)
        stress = [f"Zq7q{i:02d}" for i in range(101, 167)]  # 66 unique tokens
        for tok in stress:
            app.send(tok)
        # certify the probe block AND the stress block together: the probe
        # tokens sit at the line head (typed first), so a stress-only burst
        # budget strands probe-prefix residue once the stress block pops
        all_tokens = probe["probe_tokens"] + stress
        budget = sum(len(t) for t in all_tokens) + 8
        ok, ms = app.erase_all(all_tokens, max_backspaces=budget)
        assert ok is True
        assert ms < 2000.0   # the live per-key cost on a smaller shape: 45,200ms
        text = app.screen_text()
        joined = "".join(text.splitlines())
        for tok in all_tokens:
            assert tok not in text and tok not in joined, tok
        # editor acceptance after the full-block DEL burst: fresh input
        # still echoes (surplus DELs were no-ops on an already-empty line)
        app.start_echo_watch("Rf")
        app.send("Rf")
        app.wait_echo(2.0)
        assert "Rf" in app.screen_text()
    finally:
        app.kill_tree()


def test_residue_above_editor_stays_out_of_scope_but_conservative():
    """The DIAG3 shape: probe fragments rendered in the transcript ABOVE
    a clean editor. The dynamic rows-up cap keeps the transcript within
    scope, so the gate reports the conservative False — never a false
    True; in-benchmark flows never reach this state (erase runs before
    any submit), and the cap is what keeps every wrapped input row of a
    LIVE block (66 sends = 6 rows on the live Rust screen) certified."""
    app = _editor_session("editor-residue", 0.2)
    try:
        probe = app.probe_input_ready("Zq7r", retry_every=0.5, timeout=30.0,
                                      start_ts=app.t_first_paint)
        # the residue line holds fragments of attempts 3/4 above the editor
        ok, _ms = app.erase_all(probe["probe_tokens"],
                                max_backspaces=probe["chars_sent"] + 8,
                                timeout=3.0)
        assert ok is False           # conservative: fragments sit within the cap
        assert "Zq7r04" in app.screen_text()   # the transcript residue persists
        assert "> " in app.screen_text()       # the editor itself rendered clean
    finally:
        app.kill_tree()


def test_stuck_editor_erase_reports_failure_not_false_success():
    """A TUI that will not process backspaces must fail the erase: the
    needle stays rendered and erase_all reports (False, budget), never a
    vacuous success."""
    app = _editor_session("editor-stuck", 0.2)
    try:
        probe = app.probe_input_ready("Zq7s", retry_every=0.5, timeout=30.0,
                                      start_ts=app.t_first_paint)
        assert probe["sends"] >= 1
        # backspaces are ignored entirely: the erase must burn its budget
        # and report failure with the tokens still rendered
        ok, _ms = app.erase_all(probe["probe_tokens"], max_backspaces=12,
                                timeout=2.0)
        assert ok is False
        assert "Zq7s" in app.screen_text()   # still rendered: no false success
    finally:
        app.kill_tree()
