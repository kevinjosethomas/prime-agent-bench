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
                                          timeout=self.ready_timeout_s, start_ts=t_paint)
            t_sentinel = wait_sentinel(app, SENTINEL, timeout=self.sentinel_timeout_s)
            record.setdefault("fixture", {})["loaded"] = t_sentinel is not None
            # agents-back requires an empty editor; the ready probe left
            # its token behind, so erase before navigating
            erase_ok, _ = app.erase_all(probe["probe_token"])

            # ---- leg 1: chat -> agents view --------------------------------
            # fully rendered = chrome AND the resumed session's identity
            # row; both are REQUIRED (an unreadable fixture or a missing
            # row is a partial row, never a chrome-only pass)
            t_left = app.send(self.agents_view_key)
            t_chrome = _wait_or_none(
                app, lambda: AGENTS_CHROME in app.screen_text(),
                timeout=self.agents_view_timeout_s)
            t_row = None
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
                "erased_before_nav": erase_ok,
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
