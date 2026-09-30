"""kernel.*: CPython-kernel benchmarks (Section G, RT only: rust vs ts).

All product-mediated: the agent submits prompts through the TUI, the
offline mock responds with scripted `ipython` tool calls, and the kernel
result must render in the transcript (sentinel visible). The bridge
overhead is isolated by comparing against the raw kernel probes
(bench.drivers.kernel_raw).
"""
from __future__ import annotations

import socket
import subprocess
import time

from bench.adapters.benchmarks.support import first_paint
from bench.core.benchmark import Benchmark
from bench.core.harness import now
from bench.core.process import rss_tree
from bench.drivers.mock_state import DEFAULT_REPLY

STATE_CODE = {
    "1MB": "import numpy as np, pandas as pd\nbigframe = pd.DataFrame(np.random.rand(131072, 1))\nprint('STATEBUILT-1MB', int(bigframe.memory_usage().sum()))",
    "10MB": "import numpy as np, pandas as pd\nbigframe = pd.DataFrame(np.random.rand(1310720, 1))\nprint('STATEBUILT-10MB', int(bigframe.memory_usage().sum()))",
    "50MB": "import numpy as np, pandas as pd\nbigframe = pd.DataFrame(np.random.rand(6553600, 1))\nprint('STATEBUILT-50MB', int(bigframe.memory_usage().sum()))",
}


def kernel_script() -> dict:
    """The mock-provider script for the kernel benchmarks (queues by prompt).

    The aux/title requests (the products' qwen3-30b session-title calls)
    quote the user prompt, so they match the benchmark queues and corrupt
    the per-queue response parity: a main submit then gets the queue's
    TEXT response instead of its toolCall and the cell never runs. The
    aux queue matches by model FIRST, so aux requests never touch the
    benchmark queues."""
    queues = [
        {"name": "aux", "matchModels": ["qwen/qwen3-30b-a3b-instruct-2507"],
         "responses": [{"text": "ok"}]},
        {"name": "kcell", "match": ["run the kernel marker cell"], "responses": [
            {"toolCall": {"name": "ipython", "arguments": {"code": "print('KREADY-bench marker'); %who"}}},
            {"text": "kernel marker cell done."}]},
        {"name": "simple", "match": ["cell simple"], "responses": [
            {"toolCall": {"name": "ipython", "arguments": {"code": "xk = 1 + 1\nprint('CELLDONE-simple', xk)"}}},
            {"text": "simple cell done."}]},
        {"name": "multiline", "match": ["cell multiline"], "responses": [
            {"toolCall": {"name": "ipython", "arguments": {"code": "am = [i * 2 for i in range(10)]\nbm = sum(am)\nprint('CELLDONE-multiline', bm)"}}},
            {"text": "multiline cell done."}]},
        {"name": "async", "match": ["cell async"], "responses": [
            {"toolCall": {"name": "ipython", "arguments": {"code": "import asyncio\nasync def _m():\n    await asyncio.sleep(0.05)\n    return 7\nprint('CELLDONE-async', asyncio.run(_m()))"}}},
            {"text": "async cell done."}]},
        {"name": "subprocess", "match": ["cell subprocess"], "responses": [
            {"toolCall": {"name": "ipython", "arguments": {"code": "import subprocess\nr = subprocess.run(['echo', 'hello-subprocess'], capture_output=True, text=True)\nprint('CELLDONE-subprocess', r.stdout.strip())"}}},
            {"text": "subprocess cell done."}]},
    ]
    for size, code in STATE_CODE.items():
        queues.append({"name": f"statebuild-{size}", "match": [f"build the {size} state"], "responses": [
            {"toolCall": {"name": "ipython", "arguments": {"code": code}}},
            {"text": f"{size} state built."}]})
    queues.append({"name": "statecheck", "match": ["check the state"], "responses": [
        {"toolCall": {"name": "ipython", "arguments": {"code": "print('STATECHECK', len(bigframe))"}}},
        {"text": "state check done."}]})
    return {
        "responses": [{"text": DEFAULT_REPLY}],
        "queues": queues,
    }


def submit_and_wait(app, prompt: str, sentinel: str, timeout: float = 120.0):
    """Type prompt + Enter -> (ack_ts, sentinel_ts, enter_ts)."""
    app.send(prompt)
    t_enter = app.send("\r")
    try:
        t_ack = app.wait_output_after(t_enter, timeout=timeout)
    except TimeoutError:
        t_ack = None
    app.wait_screen_contains(sentinel, timeout=timeout)
    t_sent = now()
    return t_ack, t_sent, t_enter


def launch_ready(product, ctx, driver, timeout: float = 120):
    """Launch to interactive-ready (first paint + typed echo accepted).

    The erase budget covers every probe char sent (buffered/dropped tokens
    from each attempt can all sit on the input line)."""
    app = product.launch(ctx, driver)
    first_paint(app, timeout=timeout)
    probe = app.probe_input_ready("Zq7k", retry_every=0.5, timeout=timeout,
                                  start_ts=app.t_first_paint)
    app.erase_all("Zq7k", max_backspaces=probe["chars_sent"] + 8,
                  refresh_keys=product.erase_refresh_keys)
    return app


class KernelColdStart(Benchmark):
    """Fresh session -> first kernel cell executes and renders (warm venv)."""

    name = "kernel.cold_start"
    applicable_products = ["rust", "ts"]

    def measure(self, product, ctx, record, driver, fixture=None) -> None:
        app = launch_ready(product, ctx, driver)
        try:
            t_ack, t_sent, t_enter = submit_and_wait(app, "run the kernel marker cell", "KREADY-bench marker")
            rss = rss_tree(app.pid)
            record["metrics"] = {
                "submit_to_ack_ms": round((t_ack - t_enter) * 1000, 1) if t_ack else None,
                "submit_to_result_ms": round((t_sent - t_enter) * 1000, 1),
                "rss_after_first_cell": rss,
            }
            # launch_ready's probe and submit_and_wait's sentinel wait both
            # raise on failure, so reaching here proves the echo and render
            record["validation"] = {"echoed": True, "marker_rendered": True}
        finally:
            app.kill_tree()
            product.reap(ctx)


class KernelCellExec(Benchmark):
    """One warm session; one cell per type on the resident kernel."""

    name = "kernel.cell_exec"
    applicable_products = ["rust", "ts"]

    def measure(self, product, ctx, record, driver, fixture=None) -> None:
        app = launch_ready(product, ctx, driver)
        try:
            submit_and_wait(app, "run the kernel marker cell", "KREADY-bench marker", timeout=180)
            per_type = {}
            for kind in ("simple", "multiline", "async", "subprocess"):
                t_ack, t_sent, t_enter = submit_and_wait(app, f"cell {kind}", f"CELLDONE-{kind}", timeout=120)
                per_type[kind] = {
                    "submit_to_ack_ms": round((t_ack - t_enter) * 1000, 1) if t_ack else None,
                    "submit_to_result_ms": round((t_sent - t_enter) * 1000, 1),
                }
            record["metrics"] = per_type
            record["validation"] = {"echoed": True, "marker_rendered": True,
                                    "cells_done": len(per_type) == 4}
            record["resource"] = {"rss_after_cells": rss_tree(app.pid)}
        finally:
            app.kill_tree()
            product.reap(ctx)


class KernelMultiKernel(Benchmark):
    """N sessions (TUIs) under ONE daemon; per-kernel first-cell latency."""

    name = "kernel.multi_kernel_3"
    n_sessions = 3
    applicable_products = ["rust", "ts"]

    def measure(self, product, ctx, record, driver, fixture=None) -> None:
        daemon = subprocess.Popen(product.daemon_argv(ctx), env=product.env(ctx), cwd=str(ctx["work"]),
                                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        t_daemon = time.perf_counter()
        deadline = t_daemon + 60
        while time.perf_counter() < deadline:
            if ctx["daemon_socket"].exists():
                try:
                    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                        s.settimeout(2)
                        s.connect(str(ctx["daemon_socket"]))
                    break
                except OSError:
                    pass
            time.sleep(0.01)
        apps = []
        try:
            first_cell = []
            for i in range(self.n_sessions):
                t0 = time.perf_counter()
                app = product.launch(ctx, driver)
                first_paint(app, timeout=120)
                probe = app.probe_input_ready(f"Zq7m{i}", retry_every=0.5, timeout=120,
                                              start_ts=app.t_first_paint)
                app.erase_all("Zq7m", max_backspaces=probe["chars_sent"] + 8,
                              refresh_keys=product.erase_refresh_keys)
                apps.append(app)
                t_ready = time.perf_counter()
                _, t_sent, _ = submit_and_wait(app, "run the kernel marker cell", "KREADY-bench marker", timeout=240)
                first_cell.append({
                    "tui_ready_ms": round((t_ready - t0) * 1000, 1),
                    "submit_to_result_ms": round((time.perf_counter() - t_sent) * 1000, 1),
                })
            rss_total = rss_tree(daemon.pid)
            for a in apps:
                rss_total["rss_mb"] = round(rss_total["rss_mb"] + rss_tree(a.pid)["rss_mb"], 1)
            record["metrics"] = {
                "n": self.n_sessions,
                "per_kernel": first_cell,
                "daemon_tree_rss_mb": rss_total.get("rss_mb"),
                "marginal_rss_per_kernel_mb": round(rss_total.get("rss_mb", 0) / max(1, self.n_sessions), 1),
            }
            record["validation"] = {"echoed": True, "marker_rendered": True,
                                    "kernels_done": len(first_cell) == self.n_sessions}
        finally:
            for a in apps:
                a.kill_tree()
            daemon.terminate()
            try:
                daemon.wait(timeout=10)
            except Exception:
                daemon.kill()
            product.reap(ctx)


class KernelMultiKernel1(KernelMultiKernel):
    """N=1 baseline for the multi-kernel scaling curve."""

    name = "kernel.multi_kernel_1"
    n_sessions = 1


class KernelMultiKernel10(KernelMultiKernel):
    """N=10 stress point for the multi-kernel scaling curve."""

    name = "kernel.multi_kernel_10"
    n_sessions = 10
