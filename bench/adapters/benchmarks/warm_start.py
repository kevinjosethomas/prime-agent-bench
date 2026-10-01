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

import subprocess
import time

from bench.adapters.benchmarks.cold_start import measure_cold_start
from bench.adapters.benchmarks.support import first_paint, prepass
from bench.core.benchmark import Benchmark
from bench.core.product import ProductAdapter, TrialContext
from bench.core.process import sweep_trial


def measure_warm_start(product: ProductAdapter, ctx: TrialContext, record: dict,
                       driver, daemon_dwell_s: float = 2.0) -> None:
    """The warm-start measurement (prewarm + cold-start semantics).

    Warm = the product's normal steady state. A daemon product's daemon is
    started by its own command with the configuration its TUI would give
    it (``daemon_env``), timed to socket accept, then left to settle for
    ``daemon_dwell_s`` so the measured launch never races the daemon's own
    boot work. The same dwell applies to every daemon product."""
    if product.needs_prepass:
        prepass(product, ctx, driver)
    daemon_argv = product.daemon_argv(ctx)
    if daemon_argv is not None:
        t0 = time.perf_counter()
        starter = subprocess.Popen(daemon_argv, env=product.daemon_env(ctx), cwd=str(ctx["work"]),
                                   stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   start_new_session=True)
        if not product.wait_daemon_ready(ctx, timeout=60):
            raise TimeoutError("pre-warmed daemon never accepted on its socket")
        boot_ms = round((time.perf_counter() - t0) * 1000.0, 1)
        if product.daemon_command_exits and starter.wait(timeout=60) != 0:
            raise RuntimeError(f"daemon start exited {starter.returncode}")
        time.sleep(daemon_dwell_s)
        record["daemon"] = {"prewarmed_boot_ms": boot_ms, "dwell_s": daemon_dwell_s}
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
        dwell = float((self.cfg.get("benchmarks", {}).get(self.name) or {})
                      .get("daemon_dwell_s", 2.0))
        measure_warm_start(product, ctx, record, driver, daemon_dwell_s=dwell)
