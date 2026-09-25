"""compare.msg_send: keystroke Enter -> first submit-ack frame, then settle.

The ack is the client-side share (first output after Enter); the settle
is the full turn. The routing regime is the harness's own declaration
(``ProductAdapter.msg_routing``, overridable per benchmark via
``benchmarks.compare.msg_send.msg_routing``): mock-routed harnesses
settle on the scripted reply (known verbatim); real-api harnesses settle
only on the fixed sentinel token the prompt demands — the live reply is
unknowable in general, so the prompt pins it, and the settle detector
never fires on screen growth alone (the captured Codex 401 render). No
harness name is special here.
"""
from __future__ import annotations

import time

from bench.adapters.benchmarks.support import PROBE_TOKEN, first_paint, prepass, screen_hash
from bench.core.benchmark import Benchmark
from bench.core.harness import now
from bench.drivers.mock_state import DEFAULT_REPLY

#: the fixed reply token the real-api prompt demands: the only reply
#: text that can certify a live-inference settle
REAL_API_SENTINEL = "BENCH-OK-7f3d9a"

#: the real-api submit prompt: live inference, one fixed reply token
REAL_API_PROMPT = "Reply with exactly BENCH-OK-7f3d9a and nothing else."


class MsgSend(Benchmark):
    """Keystroke Enter -> first submit-ack frame -> turn settle.

    The settle is regime-aware: mock harnesses wait for the scripted
    reply; real-api harnesses demand one fixed sentinel token in a fresh
    rendered line (the prompt asks for it), so live-inference replies
    are certified semantically — never by screen growth alone.
    """

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
            app.probe_input_ready(PROBE_TOKEN, start_ts=app.t_first_paint)
            app.erase_all(PROBE_TOKEN)
            routing_pre = ctx.get("routing") or product.msg_routing
            prompt = REAL_API_PROMPT if routing_pre == "real-api" else "bench hello"
            app.type_token(prompt, per_key_timeout=2.0, inter_key_pause=0.02)
            t_enter = app.send("\r")
            # ack = first output after Enter (driver primitive: exact chunk
            # timestamp on the PTY driver, first frame change otherwise)
            try:
                t_ack = app.wait_output_after(t_enter, timeout=10)
            except TimeoutError:
                t_ack = None
            # the harness-declared regime, resolved per benchmark
            # (benchmarks.compare.msg_send.msg_routing) before any launch
            routing = ctx.get("routing") or product.msg_routing
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
            else:
                # real-api: live inference. The reply is made knowable by
                # the prompt itself: it demands one fixed sentinel token, so
                # the settle detector matches exactly that token — screen
                # growth alone (the captured Codex 401 error render) never
                # certifies. The sentinel is a NEW rendered line: the typed
                # prompt carries the token too, so the line set at ack time
                # is the baseline a reply line must not come from.
                t_settle = None
                stable_since = None
                baseline = {ln.strip() for ln in app.screen_text().splitlines()
                            if ln.strip()}
                last_hash = screen_hash(app)
                deadline = now() + 120
                while now() < deadline:
                    h = screen_hash(app)
                    lines = [ln.strip() for ln in app.screen_text().splitlines()
                             if ln.strip()]
                    fresh = any(REAL_API_SENTINEL in ln and ln not in baseline
                                for ln in lines)
                    if fresh:
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
                # the certification the validity gate requires before a
                # real-api row ranks: the sentinel reply actually rendered
                record["real_api_certified"] = t_settle is not None
                model_info = getattr(product, "model_info", None)
                record["model"] = model_info(ctx) if callable(model_info) else None
                if t_settle is None:
                    record["settle_miss_screen"] = "\n".join(
                        ln for ln in app.screen_text().splitlines() if ln.strip())[-2000:]
            record["metrics"] = metrics
            record["msg_routing"] = routing
            record["validation"] = validation
        finally:
            app.kill_tree()
            product.reap(ctx)
