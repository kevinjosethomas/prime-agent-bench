"""daemon.boot: supervisor spawn -> socket accept -> protocol hello -> first create.

Prime Agent products only (resident-daemon architecture). The wire client
is a minimal port of the TS repo's batterylib.Wire (JSONL protocol 7).
"""
from __future__ import annotations

import json
import socket
import subprocess
import time

from bench.core.benchmark import Benchmark
from bench.core.process import loadavg


class Wire:
    """JSONL daemon-wire client (protocol 7), minimal port of batterylib.Wire."""

    def __init__(self, socket_path):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(30)
        self.sock.connect(str(socket_path))
        self.buf = b""
        self.hello = self.read_line()

    def send_command(self, command_id, command):
        """Send one command envelope."""
        envelope = {"type": "command", "id": command_id,
                    "protocol": {"name": "prime-agent.daemon", "version": 7},
                    "command": command}
        self.sock.sendall((json.dumps(envelope) + chr(10)).encode())

    def read_line(self, timeout=30.0):
        """Read one JSONL line from the daemon."""
        deadline = time.perf_counter() + timeout
        while bytes([10]) not in self.buf:
            remaining = deadline - time.perf_counter()
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
        """Close the socket (best-effort)."""
        try:
            self.sock.close()
        except Exception:
            pass


def wire_request(wire: Wire, cid: str, command: dict, timeout: float = 30.0) -> dict:
    """Send a command and wait for its matching response line."""
    deadline = time.perf_counter() + timeout
    wire.send_command(cid, command)
    while True:
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            raise TimeoutError(f"no response for {cid}")
        line = wire.read_line(timeout=remaining)
        if line.get("id") == cid:
            return line


class DaemonBoot(Benchmark):
    """Supervisor spawn -> socket accept -> protocol hello -> first create."""

    name = "daemon.boot"
    applicable_products = ["rust", "ts"]

    def measure(self, product, ctx, record, driver, fixture=None) -> None:
        t_load = loadavg()
        t0 = time.perf_counter()
        dproc = subprocess.Popen(product.daemon_argv(ctx), env=product.env(ctx), cwd=str(ctx["work"]),
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
        product.reap(ctx)

        def ms(t) -> float | None:
            return round((t - t0) * 1000.0, 1) if t else None

        record["metrics"] = {
            "spawn_to_accept_ms": ms(t_accept),
            "spawn_to_hello_ms": ms(t_hello),
            "spawn_to_first_create_ms": ms(t_create),
            "hello_ok": hello_ok,
            "create_ok": create_ok,
        }
        record["resource"] = {"loadavg_before": t_load}
