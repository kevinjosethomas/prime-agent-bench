"""session.agent_view_roundtrip: chat -> agents view -> same session chat.

BENCHMARK_SUITE_SPEC section A P0 row (spec grid: the S fixture with one
active session; this scenario pins the canonical 10MiB tier first):
"Chat -> agents view -> same session/tail & echo; break out each leg."

Navigation is the RT parity surface both products ship by default
(`app.agents.back` / `app.agents.open`): LEFT in the chat with an EMPTY
editor hands the terminal to the agents view; RIGHT opens the selected
row's session chat. If a release ever diverges, the per-benchmark config
keys (agents_view_key/agents_open_key) override - a product whose live
markers never render is never ranked, it records a partial row.

Metric boundaries (all clocks are controller-side monotonic; the settle
sleep before RSS happens after every boundary below is captured):
  chat_to_agents_ms   send(LEFT)  -> view chrome AND the roster's identity
                                     row visible (chrome alone is a splash)
  agents_chrome_ms    send(LEFT)  -> view chrome visible (diagnostic)
  agents_to_tail_ms   send(RIGHT) -> the SAME session's tail sentinel
                                     rendered again
  chat_ready_after_ms send(RIGHT) -> a FRESH probe echoed (the chat editor
                                     accepts input again)

The same-session proof stacks, because the sentinel alone is shared by
every session on the fixture and the view's search field also accepts
text (a probe echoed there would fake a ready chat):
  1. roster_row    the resumed session's identity row rendered in the
                   view (the fixture's first user message - the row title
                   source sessionName -> firstMessage -> cwd basename ->
                   sessionId -> id). A fixture whose first user text
                   cannot be read never passes this leg.
  2. sentinel_gone the pre-nav chat tail left the screen before RIGHT:
                   the view must have replaced the chat, and the tail
                   observed after RIGHT is a fresh render, not a stale
                   screen.
  3. tail_after    the same fixture sentinel rendered again after RIGHT.
  4. chrome_gone_after  the view chrome left the screen on return (the
                   chat replaced the view, so the fresh echo cannot have
                   come from the view's search field).
  5. echoed_after  a fresh probe token echoed in the chat (the probe
                   sequence uses a new token per attempt, so stale input
                   can never satisfy it).
RT-only (spec A: session.* resumes the Prime session fixture).
"""
from __future__ import annotations

import json
import time

from bench.adapters.benchmarks.support import (PROBE_TOKEN, first_paint,
                                                prepass, wait_sentinel)
from bench.adapters.fixtures.session_size import SENTINEL
from bench.core.benchmark import Benchmark
from bench.core.harness import Session, now
from bench.core.process import loadavg, rss_tree
from bench.core.product import keystroke

#: the agents-view search placeholder - the view chrome both products
#: render (the search field is the view's persistent surface)
AGENTS_CHROME = "Search sessions"


def _wait_or_none(session: Session, predicate, timeout: float,
                  poll: float = 0.005) -> float | None:
    """A bounded wait that returns None instead of raising: a leg that
    never lands is a partial measurement, not a crashed trial."""
    try:
        ts, _ = session.wait_for(predicate, timeout=timeout, poll=poll)
        return ts
    except TimeoutError:
        return None


def _first_user_text(fixture) -> str | None:
    """The fixture's first user-message text, whitespace-normalized -
    the roster row title source (sessionName -> firstMessage -> cwd
    basename -> sessionId -> id; the corpus fixture has no sessionName,
    so firstMessage is the rendered identity)."""
    if not fixture:
        return None
    try:
        with open(fixture, encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                msg = row.get("message") or {}
                if row.get("type") == "message" and msg.get("role") == "user":
                    for part in msg.get("content") or []:
                        text = (part or {}).get("text") or ""
                        if text.strip():
                            return " ".join(text.split())
    except (OSError, json.JSONDecodeError):
        return None
    return None


def _dismiss_dialogs(app, steps, rounds: int = 4, key_pause: float = 0.4) -> bool:
    """Answer any on-screen first-run dialog (a bounded walk over the
    product's dialog_steps config); True when the screen is dialog-free.

    A first-run dialog can surface on a fresh trial home AFTER the
    readiness probe (the probe's own dialog walk only covers dialogs
    that appear while it is probing): the observed case is TS's
    trace-sharing welcome dialog, which swallows the navigation keys
    for as long as it stays up.
    """
    markers = [marker for marker, _keys in steps]
    for _ in range(max(1, rounds)):
        text = " ".join(app.screen_text().split())
        pending = [(marker, keys) for marker, keys in steps if marker in text]
        if not pending:
            return True
        for _marker, keys in pending:
            for key in keys:
                app.send(keystroke(key))
                time.sleep(key_pause)
    text = " ".join(app.screen_text().split())
    return not any(marker in text for marker in markers)


def _editor_dock_state(screen: str, dock_rows: int = 5):
    """Classify the chat's bottom dock: 'bare', 'text', or None.

    The editor prompt renders in the last few non-empty rows (the dock:
    the prompt row, its wrapped continuation rows, status/footer chrome);
    the transcript renders above the dock, so its '>' blockquote rows
    never collide with the check.

    The verdict is deliberately strict - a dirty or ambiguous dock never
    passes vacuously:

    - no prompt row, or more than one, in the dock -> ``None``: an
      ambiguous surface (a first-run dialog, the roster, a splash) is
      never treated as an empty editor, and the caller must stop
      instead of sending keys into an unknown surface
    - a single prompt row with typed text -> ``'text'``: the probe's
      buffered fragments sit on the prompt row
    - a fragment row inside the dock (the wrapped head of a long input,
      above or below a bare prompt) -> ``'text'``: the cursor can sit at
      the end of a wrapped line whose head renders off the prompt row
    - a single bare prompt row and no fragments in the dock ->
      ``'bare'``
    """
    nonempty = [line for line in screen.splitlines() if line.strip()]
    dock = nonempty[-dock_rows:]
    prompts = [i for i, line in enumerate(dock)
               if line.lstrip().startswith(">")]
    if len(prompts) != 1:
        return None
    if dock[prompts[0]].strip() != ">":
        return "text"
    for i, line in enumerate(dock):
        if i != prompts[0] and PROBE_TOKEN in line:
            return "text"
    return "bare"


class SessionAgentViewRoundtrip(Benchmark):
    """Chat -> agents view -> the SAME session's chat, each leg timed."""

    name = "session.agent_view_roundtrip"
    requires_fixture = "session-10mib"
    applicable_products = ["rust", "ts"]  # spec section A: session.* is RT-only
    applicability_note = ("session.* benchmarks resume the Prime session fixture; "
                          "BENCHMARK_SUITE_SPEC section A scopes them to Prime Agent Rust/TS")
    completeness_keys = ("roundtrip_ok",)  # a leg that never landed = incomplete
    # the return legs are published beside the primary, so the A/A gate
    # calibrates their noise floor too (aa_metrics, spec methodology)
    aa_metrics = ("agents_to_tail_ms", "chat_ready_after_ms")

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        spec = cfg.get("benchmarks", {}).get(self.name, {})
        self.ready_timeout_s = float(spec.get("ready_timeout_s", 120.0))
        self.sentinel_timeout_s = float(spec.get("sentinel_timeout_s", 30.0))
        self.agents_view_timeout_s = float(spec.get("agents_view_timeout_s", 20.0))
        self.return_timeout_s = float(spec.get("return_timeout_s", 30.0))
        # the RT parity defaults; configs/default.yaml overrides per product
        # if a release ever diverges
        self.agents_view_key = keystroke(spec.get("agents_view_key", "left"))
        self.agents_open_key = keystroke(spec.get("agents_open_key", "right"))

    def measure(self, product, ctx, record, driver, fixture=None) -> None:
        t_load = loadavg()
        row_title = _first_user_text(fixture)
        if product.needs_prepass:
            prepass(product, ctx, driver)
        app = product.launch(ctx, driver, resume_fixture=str(fixture))
        try:
            t_paint = first_paint(app, timeout=120)
            probe = app.probe_input_ready(PROBE_TOKEN, retry_every=0.5,
                                          timeout=self.ready_timeout_s, start_ts=t_paint,
                                          dialog_steps=tuple(product.dialog_steps))
            t_sentinel = wait_sentinel(app, SENTINEL, timeout=self.sentinel_timeout_s)
            record.setdefault("fixture", {})["loaded"] = t_sentinel is not None
            # agents-back requires an empty editor; the ready probe left
            # its tokens behind, so erase them ALL before navigating
            erase_ok, _ = app.erase_all(probe["probe_tokens"],
                                        max_backspaces=probe["chars_sent"] + 8)
            # a first-run dialog that surfaced after the probe swallows
            # the navigation keys while it is up: answer it from the
            # product's dialog config before touching the nav keys
            dialogs_clear = _dismiss_dialogs(app, product.dialog_steps)
            # the probe's retry loop can buffer EVERY dropped fragment in
            # the editor (slow mounts) and erase_all only removes the
            # last one: clear the whole input line (ctrl+u, delete to
            # line start) and require the bottom dock's prompt row to be
            # bare. An ambiguous dock (no single prompt row - a dialog,
            # the roster, a splash) stops the gate immediately: never a
            # vacuous pass, and never keys sent into an unknown surface
            dock = _editor_dock_state(app.screen_text())
            for _ in range(3):
                if dock in (None, "bare"):
                    break
                app.send(keystroke("ctrl+u"))
                time.sleep(0.2)
                dock = _editor_dock_state(app.screen_text())
            line_cleared = dock == "bare"

            # ---- leg 1: chat -> agents view --------------------------------
            # fully rendered = chrome AND the resumed session's identity
            # row; both are REQUIRED (an unreadable fixture or a missing
            # row is a partial row, never a chrome-only pass)
            # the pre-nav state is a precondition, not a measurement: a
            # dialog still up or a non-empty editor means the navigation
            # keys would be consumed by the wrong surface (the observed
            # failure: LEFT as an editor cursor move), so the legs stay
            # partial and the row stays unrankable
            t_left = None
            t_chrome = None
            t_row = None
            if dialogs_clear and line_cleared:
                t_left = app.send(self.agents_view_key)
                t_chrome = _wait_or_none(
                    app, lambda: AGENTS_CHROME in app.screen_text(),
                    timeout=self.agents_view_timeout_s)
                if t_chrome is not None and row_title:
                    t_row = _wait_or_none(
                        app, lambda: row_title in app.screen_text(),
                        timeout=self.agents_view_timeout_s)
            t_agents = max(t_chrome, t_row) if (t_chrome is not None
                                                and t_row is not None) else None

            # ---- leg 2: agents view -> the same session's chat --------------
            t_right = t_tail = sentinel_gone = None
            probe2 = None
            chrome_gone_after = False
            echoed_after = False
            if t_agents is not None:
                # the view must have REPLACED the chat: the pre-nav tail
                # leaving the screen proves the tail seen after RIGHT is
                # a fresh render, not the stale chat behind the view
                sentinel_gone = _wait_or_none(
                    app, lambda: SENTINEL not in app.screen_text(),
                    timeout=self.agents_view_timeout_s)
                if sentinel_gone is not None:
                    t_right = app.send(self.agents_open_key)
                    t_tail = _wait_or_none(
                        app, lambda: SENTINEL in app.screen_text(),
                        timeout=self.return_timeout_s)
                    if t_tail is not None:
                        # the chat must have replaced the view: with the
                        # chrome still up, a probe echo could come from
                        # the view's search field, not the chat editor
                        chrome_gone_after = AGENTS_CHROME not in app.screen_text()
                        if chrome_gone_after:
                            try:
                                probe2 = app.probe_input_ready(
                                    PROBE_TOKEN, retry_every=0.5,
                                    timeout=self.ready_timeout_s, start_ts=t_right)
                                echoed_after = True
                            except TimeoutError:
                                probe2 = None

            # the settle sleep is AFTER every boundary timestamp above:
            # it only feeds the RSS snapshot, never a leg metric
            time.sleep(1.0)
            rss = rss_tree(app.pid)
            record["metrics"] = {
                "launch_to_ready_ms": probe["echo_ts_offset_ms"],
                "chat_to_agents_ms": round((t_agents - t_left) * 1000.0, 1) if t_agents else None,
                "agents_chrome_ms": round((t_chrome - t_left) * 1000.0, 1) if t_chrome else None,
                "agents_to_tail_ms": round((t_tail - t_right) * 1000.0, 1) if t_tail else None,
                "chat_ready_after_ms": probe2["gap_ms"] if probe2 else None,
                "roundtrip_ok": bool(t_agents and t_tail and probe2),
                "pty_bytes": app.bytes_out(),
            }
            record["validation"] = {
                "sentinel_loaded": t_sentinel is not None,
                # the generic erase is needle-based (it proves the LAST
                # probe fragment left the screen, not that the editor is
                # clean): the verified dock gate is the authority - if
                # ctrl+u produced a bare prompt the residue is genuinely
                # gone even when the needle bookkeeping failed, and a
                # retained residue never certifies this key alone
                # (line_cleared carries the failure)
                "erased_before_nav": bool(erase_ok or line_cleared),
                "dialogs_clear": dialogs_clear,
                "line_cleared": line_cleared,
                "agents_chrome": t_chrome is not None,
                "roster_row": t_row is not None,
                "sentinel_gone": sentinel_gone is not None,
                "tail_after": t_tail is not None,
                "chrome_gone_after": chrome_gone_after,
                "echoed_after": echoed_after,
            }
            record["resource"] = {"rss_10mib": rss, "loadavg_before": t_load}
        finally:
            app.kill_tree()
            product.reap(ctx)
