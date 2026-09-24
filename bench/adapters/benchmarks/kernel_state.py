"""kernel.state_snapshot_* / kernel.restart_restore_*: kernel state lifecycle.

Build a realistic state fixture in the kernel (pandas frame), then trigger
the product's engine-driven compaction (snapshot) or kill the kernel
outright, and measure the restore path.
"""
from __future__ import annotations

import os
import signal
import time

from bench.adapters.benchmarks.kernel import launch_ready, submit_and_wait
from bench.core.benchmark import Benchmark
from bench.core.harness import now
from bench.core.process import rss_tree


def kernel_pids(ctx, product) -> list:
    """Kernel processes: python under this product's global venv, belonging
    to this trial (cwd or cmdline references the trial dir)."""
    venv = str(product.layout.global_dir / product.name / "kernel-venv")
    pids = []
    from bench.core.process import iter_proc_dirs
    for proc in iter_proc_dirs():
        try:
            argv = (proc / "cmdline").read_bytes().decode(errors="replace")
            cwd = os.readlink(proc / "cwd")
        except OSError:
            continue
        if venv in argv and (str(ctx["trial_dir"]) in argv or str(ctx["trial_dir"]) in cwd or str(ctx["work"]) in cwd):
            pids.append(int(proc.name))
    return pids


class KernelStateSnapshot(Benchmark):
    """Build state -> /compact (snapshot) -> state survives (check cell)."""

    name = "kernel.state_snapshot_10MB"
    size = "10MB"
    applicable_products = ["rust", "ts"]

    def measure(self, product, ctx, record, driver, fixture=None) -> None:
        app = launch_ready(product, ctx, driver)
        try:
            _, t_built, t0 = submit_and_wait(app, f"build the {self.size} state",
                                             f"STATEBUILT-{self.size}", timeout=300)
            build_ms = round((t_built - t0) * 1000.0, 1)
            # snapshot/compact: the engine-driven compaction serializes kernel state
            t_compact_enter = app.send("/compact\r")
            app.wait_screen_contains("Checkpoint summary", timeout=180)
            t_compact_done = now()
            time.sleep(1.0)
            _, t_check, t1 = submit_and_wait(app, "check the state", "STATECHECK", timeout=180)
            record["metrics"] = {
                "state_build_ms": build_ms,
                "compact_to_ack_ms": round((t_compact_done - t_compact_enter) * 1000.0, 1),
                "post_compact_cell_ms": round((t_check - t1) * 1000.0, 1),
                "state_size": self.size,
                "state_preserved": True,
            }
        finally:
            app.kill_tree()
            product.reap(ctx)


class KernelStateSnapshot1MB(KernelStateSnapshot):
    """The 1MB state-snapshot point."""

    name = "kernel.state_snapshot_1MB"
    size = "1MB"


class KernelStateSnapshot50MB(KernelStateSnapshot):
    """The 50MB state-snapshot point."""

    name = "kernel.state_snapshot_50MB"
    size = "50MB"


class KernelRestartRestore(Benchmark):
    """Build state -> SIGKILL the kernel -> state-restoring cell measures the
    product's restart + restore path."""

    name = "kernel.restart_restore_10MB"
    size = "10MB"
    applicable_products = ["rust", "ts"]

    def measure(self, product, ctx, record, driver, fixture=None) -> None:
        app = launch_ready(product, ctx, driver)
        try:
            submit_and_wait(app, f"build the {self.size} state", f"STATEBUILT-{self.size}", timeout=300)
            pids = kernel_pids(ctx, product)
            killed = 0
            for pid in pids:
                try:
                    os.kill(pid, signal.SIGKILL)
                    killed += 1
                except ProcessLookupError:
                    pass
            t_kill = now()
            _, t_check, t1 = submit_and_wait(app, "check the state", "STATECHECK", timeout=300)
            record["metrics"] = {
                "kernels_killed": killed,
                "kill_to_restored_cell_ms": round((t_check - t_kill) * 1000.0, 1),
                "submit_to_result_ms": round((t_check - t1) * 1000.0, 1),
                "state_size": self.size,
                "state_restored": "STATECHECK" in app.screen_text(),
            }
        finally:
            app.kill_tree()
            product.reap(ctx)
