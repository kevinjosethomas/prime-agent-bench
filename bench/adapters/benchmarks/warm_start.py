"""compare.warm_start: launch -> echo with pre-warmed state.

Products with a resident daemon (rust, ts, codex): the daemon is started
by the product's own daemon command and timed to socket accept (recorded
separately as daemon.prewarmed_boot_ms); the measured launch then rides
the warm daemon. Others: an unmeasured launch warms home/caches, then the
measured repeat-launch is the product's native warm start. Products that
need an onboarding prepass get it first; its sweep leaves nothing running,
so a pre-warmed daemon is never killed before the measured launch. The
full trial sweep still runs after the measured launch.
"""
from __future__ import annotations

import socket
import subprocess
import time

from bench.adapters.benchmarks.cold_start import measure_cold_start
from bench.adapters.benchmarks.support import first_paint, prepass
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
    if product.needs_prepass:
        prepass(product, ctx, driver)
    daemon_argv = product.daemon_argv(ctx)
    if daemon_argv is not None:
        t0 = time.perf_counter()
        starter = subprocess.Popen(daemon_argv, env=product.env(ctx), cwd=str(ctx["work"]),
                                   stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not _wait_daemon_socket(product.daemon_ready_socket(ctx), timeout=60):
            raise TimeoutError("pre-warmed daemon never accepted on its socket")
        if product.daemon_command_exits and starter.wait(timeout=60) != 0:
            raise RuntimeError(f"daemon start exited {starter.returncode}")
        record["daemon"] = {"prewarmed_boot_ms": round((time.perf_counter() - t0) * 1000.0, 1)}
    elif not product.needs_prepass:
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
    measure_cold_start(product, ctx, record, driver, prepassed=True,
                       expect_resident=daemon_argv is not None)
    record["metrics"]["warm_mode"] = "resident_daemon" if daemon_argv else "repeat_launch"


class WarmStart(Benchmark):
    """Launch -> echo with pre-warmed state."""

    name = "compare.warm_start"

    def measure(self, product, ctx, record, driver, fixture=None) -> None:
        measure_warm_start(product, ctx, record, driver)
