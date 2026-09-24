"""compare.warm_start: launch -> echo with pre-warmed state.

RT/TS: the resident daemon is pre-warmed (its boot time recorded); the
measured launch then rides the warm daemon. Others: an unmeasured launch
warms home/caches, then the measured repeat-launch is the product's native
warm start.
"""
from __future__ import annotations

import socket
import subprocess
import time

from bench.adapters.benchmarks.cold_start import measure_cold_start
from bench.adapters.benchmarks.support import first_paint
from bench.core.benchmark import Benchmark
from bench.core.product import ProductAdapter, TrialContext
from bench.core.process import sweep_trial


def _wait_daemon_socket(socket_path, timeout: float = 60.0) -> bool:
    """Block until the daemon's Unix socket accepts connections."""
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if socket_path.exists():
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                    s.settimeout(2)
                    s.connect(str(socket_path))
                return True
            except OSError:
                pass
        time.sleep(0.005)
    return False


def measure_warm_start(product: ProductAdapter, ctx: TrialContext, record: dict,
                       driver) -> None:
    """The warm-start measurement (prewarm + cold-start semantics)."""
    if product.daemon_argv(ctx) is None and not product.needs_prepass:
        # an unmeasured launch warms the home/caches; the measured launch
        # that follows is the product's native repeat-launch warm start
        warm_app = product.launch(ctx, driver)
        try:
            first_paint(warm_app, timeout=60)
            warm_app.start_echo_watch("Zqwarm01")
            warm_app.send("Zqwarm01")
            try:
                warm_app.wait_echo(20)
            except TimeoutError:
                pass
            time.sleep(0.5)
        finally:
            warm_app.kill_tree()
            sweep_trial(ctx)
    if product.daemon_argv(ctx) is not None:
        t0 = time.perf_counter()
        subprocess.Popen(product.daemon_argv(ctx), env=product.env(ctx), cwd=str(ctx["work"]),
                         stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _wait_daemon_socket(ctx["daemon_socket"], timeout=60)
        record["daemon"] = {"prewarmed_boot_ms": round((time.perf_counter() - t0) * 1000.0, 1)}
    measure_cold_start(product, ctx, record, driver)
    record["metrics"]["warm_mode"] = "resident_daemon" if product.daemon_argv(ctx) else "repeat_launch"


class WarmStart(Benchmark):
    """Launch -> echo with pre-warmed state."""

    name = "compare.warm_start"

    def measure(self, product, ctx, record, driver, fixture=None) -> None:
        measure_warm_start(product, ctx, record, driver)
