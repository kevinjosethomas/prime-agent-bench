#!/usr/bin/env python3
"""Benchmark scenarios for the cross-product suite.

Measurement semantics (suite spec):
- launch = exec boundary; first paint = first non-blank rendered frame;
- interactive-ready = typed token echoed AND accepted AND erased (no submit);
- input_ready_gap = first paint -> first accepted keystroke (retries logged);
- resumed transcripts require tail sentinel AND typed echo;
- frame completeness = chunk-burst decomposition (popping-in detector);
- wall clock = monotonic controller-side seconds (ms reported).

Not part of any product. Benchmark harness only.
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import time
from pathlib import Path

import products as P
from ptybench import PTYApp, now

PROBE_TOKEN = "Zq7x"
TYPING_TEXT = "zqxjvtypingfeel0123456789"
MOCK_REPLY = "The benchmark acknowledges this message. All systems nominal."


def _loadavg():
    return P.loadavg()


DIALOG_STEPS = [
    ("3. Provide your own API key", ["3"]),
    ("Paste or type your API key", ["sk-bench-dummy-not-real\r"]),
    ("Share agent traces with Prime Intellect?", ["\x1b[B", "\r"]),
    ("1. Auto (match terminal)", ["\r"]),
    ("Do you want to use this API key?", ["\x1b[A", "\r"]),
    ("Press Enter to continue", ["\r"]),
    ("Press enter to continue", ["\r"]),
    ("Is this a project you created or one you trust?", ["\x1b[B", "\r"]),
    ("Trust this folder?", ["\r"]),
    ("auth.openai.com", ["\x1b", "3"]),
]


def dialog_walk(app, timeout=120.0):
    """Answer known onboarding dialogs until the editor echoes a probe."""
    answers = {}
    deadline = time.time() + timeout
    while time.time() < deadline:
        txt = app.screen_text()
        answered = False
        for marker, keys in DIALOG_STEPS:
            if marker in txt and answers.get(marker, 0) < 3:
                answers[marker] = answers.get(marker, 0) + 1
                for k in keys:
                    app.send(k)
                    time.sleep(0.7)
                answered = True
                break
        if not answered:
            app.start_echo_watch("Zq7prep01")
            app.send("Zq7prep01")
            try:
                app.wait_echo(1.2)
                return "ready"
            except TimeoutError:
                pass
        time.sleep(0.8)
    raise TimeoutError(f"dialog walk never reached ready; answered: {answers}")


def prepass(prod, ctx):
    """One onboarding-consumption launch on the trial home (claude/codex:
    their first-run dialogs re-appear unless walked in-place). The prepass is
    NOT part of any measurement; the measured launch follows on the same
    home."""
    app = PTYApp(prod.argv(ctx), env=prod.env(ctx), cwd=str(ctx["work"]))
    try:
        _first_paint(app, timeout=60)
        dialog_walk(app, timeout=150)
    finally:
        app.kill_tree()
        P.sweep_trial(ctx)


def _post_clean(record):
    """Cross-trial safety-net evidence recorded with every trial."""
    record["post_clean"] = {"product_markers_left": P.product_marker_processes()[:3]}


def _first_paint(app: PTYApp, timeout=45.0):
    deadline = now() + timeout
    while now() < deadline:
        if app.t_first_paint is not None:
            return app.t_first_paint
        time.sleep(0.001)
    raise TimeoutError("no first paint")


def _screen_hash(app):
    return hashlib.sha256(app.screen_text().encode()).hexdigest()[:16]


def cold_start(prod: P.Product, ctx: dict, record: dict):
    """Launch -> first paint -> typed echo accepted -> erase. Also input gap.

    Onboarding dialogs are NOT product performance: if one appears, the
    harness auto-dismisses it and the ready measurement starts after the
    dismissal (dialog time excluded, event recorded)."""
    if getattr(prod, "needs_prepass", False):
        prepass(prod, ctx)
    t_load = _loadavg()
    app = PTYApp(prod.argv(ctx), env=prod.env(ctx), cwd=str(ctx["work"]))
    try:
        t_paint = _first_paint(app)
        # onboarding-artifact safety net (should never fire with settled
        # templates; if it does, exclude its time)
        for marker, keys in (("Share agent traces with Prime Intellect?", ["\x1b[B", "\r"]),
                            ("Do you want to use this API key?", ["\x1b[A", "\r"])):
            try:
                app.wait_screen_contains(marker, timeout=1.0)
                for k in keys:
                    app.send(k)
                    time.sleep(0.4)
                app.wait_screen_missing(marker, timeout=3.0)
                record["dialog_autodismissed"] = marker[:40]
                t_paint = _first_paint(app)  # restart the clock after dismissal
            except TimeoutError:
                pass
        probe = app.probe_input_ready(PROBE_TOKEN, retry_every=0.5, timeout=45.0,
                                      start_ts=t_paint)
        erase_ok, erase_ms = app.erase_all(PROBE_TOKEN)
        time.sleep(1.0)  # settled idle
        rss = P.rss_tree(app.proc.pid)
        bursts = app.burst_stats(t_start=app.t_spawn, t_end=now())
        record["metrics"] = {
            "launch_to_first_paint_ms": round((t_paint - app.t_spawn) * 1000.0, 1),
            "launch_to_ready_ms": probe["echo_ts_offset_ms"],
            "input_ready_gap_ms": probe["gap_ms"],
            "dropped_probes": probe["dropped_probes"],
            "erase_ok": erase_ok,
            "erase_ms": erase_ms,
            "pty_bytes": app.bytes_out(),
            "frame_bursts": bursts["bursts"],
            "burst_bytes": bursts["per_burst_bytes"][:8],
        }
        record["validation"] = {"echoed": True, "erased": erase_ok}
        record["resource"] = {"rss_settled": rss, "loadavg_before": t_load, "loadavg_after": _loadavg()}
    finally:
        app.kill_tree()
        prod.reap(ctx)


def warm_start(prod: P.Product, ctx: dict, record: dict):
    """Launch -> echo with pre-warmed state (RT: resident daemon; others:
    repeat launch with warm OS caches, onboarded home)."""
    daemon_boot_ms = None
    if prod.daemon_argv(ctx) is None and not getattr(prod, "needs_prepass", False):
        # an unmeasured launch warms the home/caches; the measured launch
        # that follows is the product's native repeat-launch warm start
        warm_app = PTYApp(prod.argv(ctx), env=prod.env(ctx), cwd=str(ctx["work"]))
        try:
            _first_paint(warm_app, timeout=60)
            warm_app.start_echo_watch("Zqwarm01")
            warm_app.send("Zqwarm01")
            try:
                warm_app.wait_echo(20)
            except TimeoutError:
                pass
            time.sleep(0.5)
        finally:
            warm_app.kill_tree()
            P.sweep_trial(ctx)
    if prod.daemon_argv(ctx) is not None:
        t0 = time.perf_counter()
        dproc = subprocess.Popen(prod.daemon_argv(ctx), env=prod.env(ctx), cwd=str(ctx["work"]),
                                 stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.perf_counter() + 60
        while time.perf_counter() < deadline:
            if ctx["daemon_socket"].exists():
                try:
                    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                        s.settimeout(2)
                        s.connect(str(ctx["daemon_socket"]))
                    break
                except OSError:
                    pass
            time.sleep(0.005)
        daemon_boot_ms = round((time.perf_counter() - t0) * 1000.0, 1)
        record["daemon"] = {"prewarmed_boot_ms": daemon_boot_ms}
    cold_start(prod, ctx, record)
    record["metrics"]["warm_mode"] = "resident_daemon" if prod.daemon_argv(ctx) else "repeat_launch"
    record["benchmark"] = record["benchmark"].replace("compare.cold_start", "compare.warm_start")


def msg_send(prod: P.Product, ctx: dict, record: dict):
    """Keystroke Enter -> first submit-ack frame (client-side share), then
    full mock turn settle. No paid inference (mock-routed)."""
    if getattr(prod, "needs_prepass", False):
        prepass(prod, ctx)
    app = PTYApp(prod.argv(ctx), env=prod.env(ctx), cwd=str(ctx["work"]))
    try:
        _first_paint(app)
        app.probe_input_ready(PROBE_TOKEN, start_ts=app.t_first_paint)
        app.erase_all(PROBE_TOKEN)
        app.type_token("bench hello", per_key_timeout=2.0, inter_key_pause=0.02)
        chunks_before = len(app.chunks)
        t_enter = app.send("\r")
        # ack = first output after Enter
        deadline = now() + 10
        t_ack = None
        while now() < deadline:
            for t, n in app.chunks:
                if t > t_enter and t_ack is None:
                    t_ack = t
                    break
            if t_ack:
                break
            time.sleep(0.001)
        # settle: reply visible + 600ms screen stability (mock: fixed text;
        # codex real API: any screen content growth after the ack counts as
        # the streamed response, detected the same stability way)
        t_settle = None
        stable_since = None
        last_hash = None
        need = MOCK_REPLY[:20] if prod.name != "codex" else None
        deadline = now() + 90
        while now() < deadline:
            h = _screen_hash(app)
            txt_now = app.screen_text()
            if (need is None and t_ack is not None and h != last_hash) or (need and need in txt_now):
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
        routing = "real-api" if prod.name == "codex" else "mock"
        settle_needle = MOCK_REPLY[:20] if routing == "mock" else None
        record["metrics"] = {
            "submit_to_ack_ms": round((t_ack - t_enter) * 1000.0, 1) if t_ack else None,
            "submit_to_settle_ms": round((t_settle - t_enter) * 1000.0, 1) if t_settle else None,
        }
        record["msg_routing"] = routing
        record["validation"] = {"ack": t_ack is not None, "settle": t_settle is not None}
    finally:
        app.kill_tree()
        prod.reap(ctx)


def scroll_typing(prod: P.Product, ctx: dict, record: dict, fixture: str | None = None):
    """Typing + scroll latency on the 10MiB session (RT: --resume fixture;
    competitors: their native large history when available, else their
    current session; comparability recorded)."""
    if getattr(prod, "needs_prepass", False):
        prepass(prod, ctx)
    if getattr(prod, "needs_prepass", False):
        prepass(prod, ctx)
    app = PTYApp(prod.argv(ctx, resume_fixture=fixture), env=prod.env(ctx), cwd=str(ctx["work"]))
    try:
        t_paint = _first_paint(app, timeout=90)
        probe = app.probe_input_ready(PROBE_TOKEN, retry_every=0.5, timeout=90, start_ts=t_paint)
        app.erase_all(PROBE_TOKEN)
        # typing latency
        typing_ms, typing_ok = app.type_token(TYPING_TEXT, per_key_timeout=2.0, inter_key_pause=0.03)
        typing_ms2, _ = app.type_token(TYPING_TEXT[-10:], per_key_timeout=2.0, inter_key_pause=0.03)
        # scroll: PageUp x5, key -> screen-change first paint
        scroll_lat = []
        for _ in range(5):
            base = _screen_hash(app)
            t0 = app.send("\x1b[5~")
            t_hit = None
            deadline = now() + 3
            while now() < deadline:
                if _screen_hash(app) != base:
                    t_hit = now()
                    break
                time.sleep(0.001)
            scroll_lat.append(round((t_hit - t0) * 1000.0, 1) if t_hit else None)
            time.sleep(0.2)
        # wheel burst (SGR mouse): measure frames in the 1s window
        t_wheel = app.send("\x1b[<64;1;1;0;64M" * 30)
        time.sleep(1.0)
        wheel_bursts = app.burst_stats(t_start=t_wheel, t_end=t_wheel + 1.0)
        # typing again while scrolled
        typing_scrolled, _ = app.type_token(TYPING_TEXT[:12], per_key_timeout=2.0, inter_key_pause=0.03)
        rss = P.rss_tree(app.proc.pid)
        record["metrics"] = {
            "typing_ms": typing_ms + typing_ms2,
            "typing_ok": typing_ok,
            "typing_scrolled_ms": typing_scrolled,
            "scroll_pgup_ms": scroll_lat,
            "wheel_bursts": wheel_bursts["bursts"],
            "wheel_bytes": wheel_bursts["total_bytes"],
            "launch_to_ready_ms": probe["echo_ts_offset_ms"],
            "pty_bytes": app.bytes_out(),
        }
        record["resource"] = {"rss_10mib": rss}
    finally:
        app.kill_tree()
        prod.reap(ctx)


def session_open_10mib(prod: P.Product, ctx: dict, record: dict, fixture: str):
    """Cold process + daemon -> tail sentinel AND editor accepts echo."""
    t_load = _loadavg()
    if getattr(prod, "needs_prepass", False):
        prepass(prod, ctx)
    app = PTYApp(prod.argv(ctx, resume_fixture=fixture), env=prod.env(ctx), cwd=str(ctx["work"]))
    try:
        t_paint = _first_paint(app, timeout=120)
        # tail sentinel visible
        t_sentinel = None
        deadline = now() + 120
        while now() < deadline:
            if "CORPUS-TAIL-9f3a1c70" in app.screen_text():
                t_sentinel = now()
                break
            time.sleep(0.005)
        probe = app.probe_input_ready(PROBE_TOKEN, retry_every=0.5, timeout=120,
                                      start_ts=t_sentinel or t_paint)
        erase_ok, _ = app.erase_all(PROBE_TOKEN)
        time.sleep(1.0)
        rss = P.rss_tree(app.proc.pid)
        bursts = app.burst_stats(t_start=app.t_spawn, t_end=now())
        record["metrics"] = {
            "launch_to_first_paint_ms": round((t_paint - app.t_spawn) * 1000.0, 1),
            "launch_to_sentinel_ms": round((t_sentinel - app.t_spawn) * 1000.0, 1) if t_sentinel else None,
            "launch_to_ready_ms": probe["echo_ts_offset_ms"],
            "input_ready_gap_ms": probe["gap_ms"],
            "pty_bytes": app.bytes_out(),
            "frame_bursts": bursts["bursts"],
        }
        record["validation"] = {"sentinel": t_sentinel is not None, "echoed": True, "erased": erase_ok}
        record["resource"] = {"rss_10mib": rss, "loadavg_before": t_load}
    finally:
        app.kill_tree()
        prod.reap(ctx)


def daemon_boot(prod: P.Product, ctx: dict, record: dict):
    """Supervisor spawn -> socket accept -> protocol hello -> first create."""
    import products as PP
    t_load = _loadavg()
    t0 = time.perf_counter()
    dproc = subprocess.Popen(prod.daemon_argv(ctx), env=prod.env(ctx), cwd=str(ctx["work"]),
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    t_accept = None
    deadline = time.perf_counter() + 60
    while time.perf_counter() < deadline:
        if ctx["daemon_socket"].exists():
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                    s.settimeout(2)
                    s.connect(str(ctx["daemon_socket"]))
                t_accept = time.perf_counter()
                break
            except OSError:
                pass
        time.sleep(0.005)
    t_hello = t_create = None
    hello_ok = create_ok = False
    if t_accept:
        try:
            wire = Wire(ctx["daemon_socket"])
            t_hello = time.perf_counter()
            hello_ok = True
            resp = wire_request(wire, "b1", {"type": "create", "cwd": str(ctx["work"])}, timeout=30)
            create_ok = bool(resp.get("success", True)) or "data" in resp or "session" in json.dumps(resp)[:400]
            t_create = time.perf_counter()
            wire.close()
        except Exception as e:
            record["wire_error"] = str(e)[:200]
    dproc.terminate()
    try:
        dproc.wait(timeout=10)
    except Exception:
        dproc.kill()
    prod.reap(ctx)
    ms = lambda t: round((t - t0) * 1000.0, 1) if t else None
    record["metrics"] = {
        "spawn_to_accept_ms": ms(t_accept),
        "spawn_to_hello_ms": ms(t_hello),
        "spawn_to_first_create_ms": ms(t_create),
        "hello_ok": hello_ok,
        "create_ok": create_ok,
    }
    record["resource"] = {"loadavg_before": t_load}


def wire_request(wire, cid, command, timeout=30):
    deadline = time.perf_counter() + timeout
    wire.send_command(cid, command)
    while True:
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            raise TimeoutError(f"no response for {cid}")
        line = wire.read_line(timeout=remaining)
        if line.get("id") == cid:
            return line


class Wire:
    """JSONL daemon-wire client (protocol 7), minimal port of batterylib.Wire."""

    def __init__(self, socket_path):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(30)
        self.sock.connect(str(socket_path))
        self.buf = b""
        self.hello = self.read_line()

    def send_command(self, command_id, command):
        envelope = {"type": "command", "id": command_id,
                    "protocol": {"name": "prime-agent.daemon", "version": 7},
                    "command": command}
        self.sock.sendall((json.dumps(envelope) + chr(10)).encode())

    def read_line(self, timeout=30.0):
        import time as _t
        deadline = _t.perf_counter() + timeout
        while bytes([10]) not in self.buf:
            remaining = deadline - _t.perf_counter()
            if remaining <= 0:
                raise TimeoutError("daemon line timeout")
            self.sock.settimeout(max(0.1, remaining))
            chunk = self.sock.recv(65536)
            if not chunk:
                raise EOFError("daemon closed")
            self.buf += chunk
        line, self.buf = self.buf.split(bytes([10]), 1)
        return json.loads(line.decode())

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


SCENARIOS = {
    "compare.cold_start": cold_start,
    "compare.warm_start": warm_start,
    "compare.msg_send": msg_send,
    "compare.scroll_typing": scroll_typing,
    "session.cold_open_10mib": session_open_10mib,
    "daemon.boot": daemon_boot,
}
