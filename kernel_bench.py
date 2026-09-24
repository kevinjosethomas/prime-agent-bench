#!/usr/bin/env python3
"""CPython-kernel benchmarks (Section G, RT only: rust vs ts).

All product-mediated: the agent submits prompts through the TUI, the
offline mock responds with scripted `ipython` tool calls, and the kernel
result must render in the transcript (sentinel visible). The bridge
overhead is isolated by comparing against the raw kernel probes
(TS: python -m rlm.repl JSONL; Rust: pa-core kernel_bench example).

Not part of any product. Benchmark harness only.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path

import products as P
from ptybench import PTYApp, now
import benchmarks as B

STATE_CODE = {
    "1MB": "import numpy as np, pandas as pd\nbigframe = pd.DataFrame(np.random.rand(131072, 1))\nprint('STATEBUILT-1MB', int(bigframe.memory_usage().sum()))",
    "10MB": "import numpy as np, pandas as pd\nbigframe = pd.DataFrame(np.random.rand(1310720, 1))\nprint('STATEBUILT-10MB', int(bigframe.memory_usage().sum()))",
    "50MB": "import numpy as np, pandas as pd\nbigframe = pd.DataFrame(np.random.rand(6553600, 1))\nprint('STATEBUILT-50MB', int(bigframe.memory_usage().sum()))",
}


def write_kernel_mock_script():
    script = P.BENCH / "harness" / "mock-script.json"
    queues = [
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
    script.write_text(json.dumps({
        "responses": [{"text": "Checkpoint summary: the conversation state was summarized for compaction."}],
        "queues": queues,
    }))
    return script


def submit_and_wait(app, prompt: str, sentinel: str, timeout=120.0):
    """Type prompt + Enter -> (ack_ts, sentinel_ts) both relative to Enter."""
    app.send(prompt)
    t_enter = app.send("\r")
    t_ack = None
    deadline = now() + timeout
    while now() < deadline and t_ack is None:
        for t, _ in app.chunks:
            if t > t_enter:
                t_ack = t
                break
        time.sleep(0.002)
    app.wait_screen_contains(sentinel, timeout=max(1.0, deadline - now()))
    t_sent = now()
    return t_ack, t_sent, t_enter


def _launch_ready(prod, ctx, timeout=120):
    app = PTYApp(prod.argv(ctx), env=prod.env(ctx), cwd=str(ctx["work"]))
    B._first_paint(app, timeout=timeout)
    app.probe_input_ready("Zq7k", retry_every=0.5, timeout=timeout, start_ts=app.t_first_paint)
    app.erase_all("Zq7k")
    return app


def kernel_cold_start(prod, ctx, record):
    """Fresh session -> first kernel cell executes and renders (warm venv;
    the venv bootstrap itself is kernel.venv_bootstrap)."""
    app = _launch_ready(prod, ctx)
    try:
        t_ack, t_sent, t_enter = submit_and_wait(app, "run the kernel marker cell", "KREADY-bench marker")
        rss = P.rss_tree(app.proc.pid)
        record["metrics"] = {
            "submit_to_ack_ms": round((t_ack - t_enter) * 1000, 1) if t_ack else None,
            "submit_to_result_ms": round((t_sent - t_enter) * 1000, 1),
            "rss_after_first_cell": rss,
        }
    finally:
        app.kill_tree()
        prod.reap(ctx)


def kernel_cell_exec(prod, ctx, record):
    """One warm session; the first cell warms the kernel, then one cell per
    type measures submit->result on the resident kernel."""
    app = _launch_ready(prod, ctx)
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
        record["resource"] = {"rss_after_cells": P.rss_tree(app.proc.pid)}
    finally:
        app.kill_tree()
        prod.reap(ctx)


def kernel_state_snapshot(prod, ctx, record, size="10MB"):
    """Build a realistic state fixture in the kernel (pandas frame), then
    trigger the product's kernel-state snapshot via /compact and measure;
    verify the state survives (state check cell)."""
    app = _launch_ready(prod, ctx)
    try:
        _, t_built, t0 = submit_and_wait(app, f"build the {size} state", f"STATEBUILT-{size}", timeout=300)
        build_ms = round((t_built - t0) * 1000, 1)
        # snapshot/compact: the engine-driven compaction serializes kernel state
        t_compact_enter = app.send("/compact\r")
        app.wait_screen_contains("Checkpoint summary", timeout=180)
        t_compact_done = now()
        time.sleep(1.0)
        _, t_check, t1 = submit_and_wait(app, "check the state", "STATECHECK", timeout=180)
        record["metrics"] = {
            "state_build_ms": build_ms,
            "compact_to_ack_ms": round((t_compact_done - t_compact_enter) * 1000, 1),
            "post_compact_cell_ms": round((t_check - t1) * 1000, 1),
            "state_size": size,
            "state_preserved": True,
        }
    finally:
        app.kill_tree()
        prod.reap(ctx)


def _kernel_pids(ctx, product_name) -> list:
    """Kernel processes: python under this product's global venv, belonging
    to this trial (cwd or cmdline references the trial dir)."""
    venv = str(P.GLOBAL / product_name / "kernel-venv")
    needles = [str(ctx["trial_dir"]), venv]
    pids = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            argv = (proc / "cmdline").read_bytes().decode(errors="replace")
            cwd = os.readlink(proc / "cwd")
        except OSError:
            continue
        if venv in argv and (str(ctx["trial_dir"]) in argv or str(ctx["trial_dir"]) in cwd or str(ctx["work"]) in cwd):
            pids.append(int(proc.name))
    return pids


def kernel_restart_restore(prod, ctx, record, size="10MB"):
    """Build state -> SIGKILL the kernel -> submit a cell referencing the
    state -> measure the product's restart + restore path."""
    app = _launch_ready(prod, ctx)
    try:
        submit_and_wait(app, f"build the {size} state", f"STATEBUILT-{size}", timeout=300)
        pids = _kernel_pids(ctx, prod.name)
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
            "kill_to_restored_cell_ms": round((t_check - t_kill) * 1000, 1),
            "submit_to_result_ms": round((t_check - t1) * 1000, 1),
            "state_size": size,
            "state_restored": "STATECHECK" in app.screen_text(),
        }
    finally:
        app.kill_tree()
        prod.reap(ctx)


def kernel_multi_kernel(prod, ctx, record, n=3):
    """N sessions (TUIs) under ONE daemon; per-kernel first-cell latency,
    total tree RSS, marginal memory per kernel."""
    import subprocess as sp
    daemon = sp.Popen(prod.daemon_argv(ctx), env=prod.env(ctx), cwd=str(ctx["work"]),
                      stdin=sp.DEVNULL, stdout=sp.DEVNULL, stderr=sp.DEVNULL)
    t_daemon = time.perf_counter()
    deadline = t_daemon + 60
    import socket
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
        for i in range(n):
            t0 = time.perf_counter()
            app = PTYApp(prod.argv(ctx), env=prod.env(ctx), cwd=str(ctx["work"]))
            B._first_paint(app, timeout=120)
            app.probe_input_ready(f"Zq7m{i}", retry_every=0.5, timeout=120, start_ts=app.t_first_paint)
            app.erase_all(f"Zq7m")
            apps.append(app)
            t_ready = time.perf_counter()
            _, t_sent, _ = submit_and_wait(app, "run the kernel marker cell", "KREADY-bench marker", timeout=240)
            first_cell.append({
                "tui_ready_ms": round((t_ready - t0) * 1000, 1),
                "submit_to_result_ms": round((time.perf_counter() - t_sent) * 1000, 1),
            })
        rss_total = P.rss_tree(daemon.pid)
        for a in apps:
            rss_total["rss_mb"] = round(rss_total["rss_mb"] + P.rss_tree(a.proc.pid)["rss_mb"], 1)
        record["metrics"] = {
            "n": n,
            "per_kernel": first_cell,
            "daemon_tree_rss_mb": rss_total.get("rss_mb"),
            "marginal_rss_per_kernel_mb": round(rss_total.get("rss_mb", 0) / max(1, n), 1),
        }
    finally:
        for a in apps:
            a.kill_tree()
        daemon.terminate()
        try:
            daemon.wait(timeout=10)
        except Exception:
            daemon.kill()
        prod.reap(ctx)


SCENARIOS = {
    "kernel.cold_start": kernel_cold_start,
    "kernel.cell_exec": kernel_cell_exec,
    "kernel.state_snapshot_10MB": lambda p, c, r: kernel_state_snapshot(p, c, r, "10MB"),
    "kernel.state_snapshot_1MB": lambda p, c, r: kernel_state_snapshot(p, c, r, "1MB"),
    "kernel.state_snapshot_50MB": lambda p, c, r: kernel_state_snapshot(p, c, r, "50MB"),
    "kernel.restart_restore_10MB": lambda p, c, r: kernel_restart_restore(p, c, r, "10MB"),
    "kernel.multi_kernel_3": lambda p, c, r: kernel_multi_kernel(p, c, r, 3),
    "kernel.multi_kernel_1": lambda p, c, r: kernel_multi_kernel(p, c, r, 1),
    "kernel.multi_kernel_10": lambda p, c, r: kernel_multi_kernel(p, c, r, 10),
}
