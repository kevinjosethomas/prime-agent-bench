"""compare.msg_send: keystroke Enter -> first submit-ack frame, then settle.

The ack is the client-side share (first output after Enter); the settle is
the full scripted turn (mock reply visible + 600ms screen stability). No
paid inference (mock-routed; codex uses the real API under its budget).
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

    def measure(self, product, ctx, record, driver, fixture=None) -> None:
        if product.needs_prepass:
            prepass(product, ctx, driver)
        app = product.launch(ctx, driver)
        try:
            first_paint(app)
            app.probe_input_ready(PROBE_TOKEN, start_ts=app.t_first_paint)
            app.erase_all(PROBE_TOKEN)
            app.type_token("bench hello", per_key_timeout=2.0, inter_key_pause=0.02)
            t_enter = app.send("\r")
            # ack = first output after Enter (driver primitive: exact chunk
            # timestamp on the PTY driver, first frame change otherwise)
            try:
                t_ack = app.wait_output_after(t_enter, timeout=10)
            except TimeoutError:
                t_ack = None
            # settle: reply visible + 600ms screen stability (mock: fixed text;
            # codex real API: any screen content growth after the ack counts as
            # the streamed response, detected the same stability way)
            t_settle = None
            stable_since = None
            last_hash = screen_hash(app)  # baseline at ack time: a dead screen cannot settle
            seen_change = False
            need = DEFAULT_REPLY[:20] if product.name != "codex" else None
            need_norm = " ".join(need.split()) if need else None
            deadline = now() + 90
            while now() < deadline:
                h = screen_hash(app)
                txt_now = app.screen_text()
                # TUIs hard-wrap text at arbitrary columns, so match against
                # the whitespace-normalized screen (collapse all wrapping)
                matched = (need and need_norm in " ".join(txt_now.split())) or \
                    (need is None and t_ack is not None and seen_change)
                if matched:
                    if h == last_hash:
                        if stable_since is None:
                            stable_since = now()
                        elif now() - stable_since >= 0.6:
                            t_settle = now()
                            break
                    else:
                        stable_since = None
                if h != last_hash:
                    seen_change = True
                last_hash = h
                time.sleep(0.02)
            routing = "real-api" if product.name == "codex" else "mock"
            record["metrics"] = {
                "submit_to_ack_ms": round((t_ack - t_enter) * 1000.0, 1) if t_ack else None,
                "submit_to_settle_ms": round((t_settle - t_enter) * 1000.0, 1) if t_settle else None,
            }
            record["msg_routing"] = routing
            record["validation"] = {"ack": t_ack is not None, "settle": t_settle is not None}
            if t_settle is None:
                record["settle_miss_screen"] = "\n".join(
                    ln for ln in app.screen_text().splitlines() if ln.strip())[-2000:]
        finally:
            app.kill_tree()
            product.reap(ctx)
