"""compare.msg_send: keystroke Enter -> first submit-ack frame, then settle.

The ack is the client-side share (first output after Enter); the settle
is the full scripted turn (mock reply visible + 600ms screen stability).
The routing regime is the harness's own declaration
(``ProductAdapter.msg_routing``): mock-routed harnesses settle on the
scripted reply; real-api harnesses get no settle at all — the reply is
live and unknowable, and a screen-growth heuristic would certify error
frames (the captured Codex 401 render). No harness name is special
here.
"""
from __future__ import annotations

import time

from bench.adapters.benchmarks.support import PROBE_TOKEN, first_paint, prepass, screen_hash
from bench.core.benchmark import Benchmark
from bench.core.harness import now
from bench.drivers.mock_state import DEFAULT_REPLY


class MsgSend(Benchmark):
    """Keystroke Enter -> first submit-ack frame -> mock turn settle."""

    name = "compare.msg_send"
    # the settle metric is published alongside the ranked ack; a noisy
    # A/A on either must keep the product out of the rankings
    aa_metrics = ("submit_to_settle_ms",)

    def measure(self, product, ctx, record, driver, fixture=None) -> None:
        if product.needs_prepass:
            prepass(product, ctx, driver)
        app = product.launch(ctx, driver)
        try:
            first_paint(app)
            probe = app.probe_input_ready(PROBE_TOKEN, start_ts=app.t_first_paint)
            # erase EVERY attempt token with a budget that covers all of
            # them: leftover probe text would pollute the typed message
            app.erase_all(probe["probe_tokens"],
                          max_backspaces=probe["chars_sent"] + 8)
            app.type_token("bench hello", per_key_timeout=2.0, inter_key_pause=0.02)
            t_enter = app.send("\r")
            # ack = first output after Enter (driver primitive: exact chunk
            # timestamp on the PTY driver, first frame change otherwise)
            try:
                t_ack = app.wait_output_after(t_enter, timeout=10)
            except TimeoutError:
                t_ack = None
            routing = product.msg_routing  # the harness-declared regime
            metrics = {
                "submit_to_ack_ms": round((t_ack - t_enter) * 1000.0, 1) if t_ack else None,
            }
            validation = {"ack": t_ack is not None}
            if routing == "mock":
                # settle: the scripted reply visible + 600ms screen stability.
                # The reply text is known verbatim from the mock script; TUIs
                # hard-wrap, so match against the whitespace-normalized screen.
                need = " ".join(DEFAULT_REPLY[:20].split())
                t_settle = None
                stable_since = None
                last_hash = screen_hash(app)  # baseline at ack time: a dead screen cannot settle
                deadline = now() + 90
                while now() < deadline:
                    h = screen_hash(app)
                    if need in " ".join(app.screen_text().split()):
                        if h == last_hash:
                            if stable_since is None:
                                stable_since = now()
                            elif now() - stable_since >= 0.6:
                                t_settle = now()
                                break
                        else:
                            stable_since = None
                    last_hash = h
                    time.sleep(0.02)
                metrics["submit_to_settle_ms"] = (
                    round((t_settle - t_enter) * 1000.0, 1) if t_settle else None)
                validation["settle"] = t_settle is not None
                if t_settle is None:
                    record["settle_miss_screen"] = "\n".join(
                        ln for ln in app.screen_text().splitlines() if ln.strip())[-2000:]
            # real-api: no settle is attempted. Screen growth is not
            # evidence of a reply (the captured Codex 401 error render
            # certified as a "settle" under the old growth detector), so
            # the row carries the ack + the regime and the result-validity
            # gate keeps cross-regime values out of the rankings.
            record["metrics"] = metrics
            record["msg_routing"] = routing
            record["validation"] = validation
        finally:
            app.kill_tree()
            product.reap(ctx)
