"""compare.scroll_typing: typing + scroll latency on a 10MiB session.

RT: --resume the fixture; competitors: their native large history when
available, else their current session (comparability recorded via the
fixture column in the row).
"""
from __future__ import annotations

import time

from bench.adapters.benchmarks.support import PROBE_TOKEN, first_paint, prepass, screen_hash
from bench.core.benchmark import Benchmark
from bench.core.harness import now
from bench.core.process import rss_tree

TYPING_TEXT = "zqxjvtypingfeel0123456789"


class ScrollTyping(Benchmark):
    """Typing + scroll latency on the loaded session fixture."""

    name = "compare.scroll_typing"
    requires_fixture = "session-10mib"

    def measure(self, product, ctx, record, driver, fixture=None) -> None:
        if product.needs_prepass:
            prepass(product, ctx, driver)
        app = product.launch(ctx, driver, resume_fixture=str(fixture) if fixture else None)
        try:
            t_paint = first_paint(app, timeout=90)
            probe = app.probe_input_ready(PROBE_TOKEN, retry_every=0.5, timeout=90, start_ts=t_paint)
            app.erase_all(PROBE_TOKEN)
            # typing latency
            typing_ms, typing_ok = app.type_token(TYPING_TEXT, per_key_timeout=2.0, inter_key_pause=0.03)
            typing_ms2, _ = app.type_token(TYPING_TEXT[-10:], per_key_timeout=2.0, inter_key_pause=0.03)
            # scroll: PageUp x5, key -> screen-change first paint
            scroll_lat = []
            for _ in range(5):
                base = screen_hash(app)
                t0 = app.send("\x1b[5~")
                t_hit = None
                deadline = now() + 3
                while now() < deadline:
                    if screen_hash(app) != base:
                        t_hit = now()
                        break
                    time.sleep(0.001)
                scroll_lat.append(round((t_hit - t0) * 1000.0, 1) if t_hit else None)
                time.sleep(0.2)
            # wheel burst (SGR mouse): measure frames in the 1s window
            t_wheel = app.send("\x1b[<64;1;1;0;64M" * 30)
            time.sleep(1.0)
            wheel = app.burst_stats(t_start=t_wheel, t_end=t_wheel + 1.0)
            # typing again while scrolled
            typing_scrolled, _ = app.type_token(TYPING_TEXT[:12], per_key_timeout=2.0, inter_key_pause=0.03)
            rss = rss_tree(app.pid)
            record["metrics"] = {
                "typing_ms": typing_ms + typing_ms2,
                "typing_ok": typing_ok,
                "typing_scrolled_ms": typing_scrolled,
                "scroll_pgup_ms": scroll_lat,
                "wheel_bursts": wheel["bursts"] if wheel else None,
                "wheel_bytes": wheel["total_bytes"] if wheel else None,
                "launch_to_ready_ms": probe["echo_ts_offset_ms"],
                "pty_bytes": app.bytes_out(),
            }
            record["resource"] = {"rss_10mib": rss}
        finally:
            app.kill_tree()
            product.reap(ctx)
