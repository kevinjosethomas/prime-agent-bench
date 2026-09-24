"""The tmux driver: the proven alternative to raw-PTY emulation.

Runs the product in an isolated tmux server (`-L` socket per session) and
drives it via send-keys / capture-pane polling. Use it when a TUI misbe-
haves under pyte emulation. Timing floor is the capture poll interval
(~25 ms), not chunk arrival: good for functional correctness, coarser
than the PTY driver for sub-100ms measurements. Not part of any product.
"""
from __future__ import annotations

import os
import shlex
import signal
import subprocess
import threading
import time
import uuid

from bench.core.harness import HarnessDriver, Session, now

SESSION_NAME = "bench"
POLL_INTERVAL = 0.025


class TmuxSession(Session):
    """One product process in a tmux pane, capture-poll driven."""

    def __init__(self, argv, env=None, cwd=None, cols=120, rows=40):
        self.server = f"bench-{uuid.uuid4().hex[:8]}"
        self.cols, self.rows = cols, rows
        cmd = ["tmux", "-L", self.server, "new-session", "-d",
               "-x", str(cols), "-y", str(rows), "-P", "-F", "#{pane_pid}"]
        for key, value in (env or {}).items():
            cmd += ["-e", f"{key}={value}"]
        if cwd:
            cmd += ["-c", str(cwd)]
        cmd.append(shlex.join([str(a) for a in argv]))
        self.t_spawn = now()
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            raise RuntimeError(f"tmux new-session failed: {out.stderr.strip()[:300]}")
        self.pid = int(out.stdout.strip().splitlines()[-1])
        self.t_first_paint = None
        self.chunks: list = []  # no byte stream: chunk-based metrics degrade to None
        self._screen_text = ""
        self._last_change_ts = None
        self._echo_needle = None
        self._echo_seen_ts = None
        self._lock = threading.Lock()
        self._alive = True
        self._poller = threading.Thread(target=self._poll_loop, daemon=True)
        self._poller.start()

    def _tmux(self, *args: str, timeout: float = 30.0) -> str:
        """Run one tmux command on this session's isolated server."""
        out = subprocess.run(["tmux", "-L", self.server, *args],
                              capture_output=True, text=True, timeout=timeout)
        if out.returncode != 0:
            raise RuntimeError(f"tmux {' '.join(args)} failed: {out.stderr.strip()[:200]}")
        return out.stdout

    def _poll_loop(self) -> None:
        while self._alive:
            try:
                text = self._tmux("capture-pane", "-p", "-t", SESSION_NAME, timeout=10)
            except Exception:
                break  # server or pane gone
            t = now()
            with self._lock:
                if text != self._screen_text:
                    self._last_change_ts = t
                self._screen_text = text
                if self.t_first_paint is None and any(ln.strip() for ln in text.splitlines()):
                    self.t_first_paint = t
                if (self._echo_needle is not None and self._echo_seen_ts is None
                        and self._echo_needle in text):
                    self._echo_seen_ts = t
            time.sleep(POLL_INTERVAL)

    # ---- primitives --------------------------------------------------------
    def screen_text(self) -> str:
        """The last captured pane text."""
        with self._lock:
            return self._screen_text

    def send(self, data) -> float:
        if isinstance(data, bytes):
            data = data.decode("utf-8", errors="replace")
        t = now()
        self._tmux("send-keys", "-t", SESSION_NAME, "-l", data)
        return t

    def start_echo_watch(self, token: str) -> None:
        """Watch for ``token`` anywhere on the captured pane text."""
        with self._lock:
            self._echo_needle = token
            self._echo_seen_ts = None

    def wait_echo(self, timeout: float = 2.0) -> float:
        """Block until the watched token appears (poll-timestamped)."""
        deadline = now() + timeout
        while True:
            with self._lock:
                if self._echo_seen_ts is not None:
                    return self._echo_seen_ts
            if now() >= deadline:
                raise TimeoutError(f"echo not rendered in {timeout:.1f}s")
            time.sleep(0.001)

    def wait_output_after(self, t_start: float, timeout: float = 10.0) -> float:
        """The first capture-poll timestamp after t_start whose pane text
        changed (poll-clocked: the ~25ms floor applies)."""
        deadline = now() + timeout
        while now() < deadline:
            with self._lock:
                if self._last_change_ts is not None and self._last_change_ts > t_start:
                    return self._last_change_ts
            time.sleep(0.001)
        raise TimeoutError(f"no output after t={t_start:.3f} in {timeout:.0f}s")

    # ---- lifecycle -----------------------------------------------------------
    def alive(self) -> bool:
        try:
            os.kill(self.pid, 0)
            return True
        except OSError:
            return False

    def kill_tree(self, sig=signal.SIGTERM) -> None:
        """Kill the pane process group, then the isolated tmux server."""
        self._alive = False
        try:
            pgid = os.getpgid(self.pid)
            for s in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(pgid, s)
                except ProcessLookupError:
                    break
                time.sleep(0.3)
                try:
                    os.kill(self.pid, 0)
                except OSError:
                    break
        except ProcessLookupError:
            pass
        subprocess.run(["tmux", "-L", self.server, "kill-server"],
                       capture_output=True, timeout=15)


class TmuxDriver(HarnessDriver):
    """Driver that spawns products in isolated tmux servers (capture-poll)."""

    name = "tmux"

    def start_session(self, argv, env=None, cwd=None, cols=120, rows=40) -> TmuxSession:
        return TmuxSession(argv, env=env, cwd=cwd, cols=cols, rows=rows)

    def noop_control(self, rounds: int = 50, cols: int = 120, rows: int = 40) -> dict:
        """Harness floor through tmux (`cat` echo round-trip; poll-limited)."""
        lat = []
        for i in range(rounds):
            app = TmuxSession(["cat"], cols=cols, rows=rows)
            token = f"zqxjv{i:03d}"
            app.wait_for(lambda: True, timeout=2)
            app.start_echo_watch(token)
            t0 = app.send(token)
            try:
                ts = app.wait_echo(2.0)
                lat.append((ts - t0) * 1000.0)
            except TimeoutError:
                pass
            app.kill_tree()
        lat.sort()
        if not lat:
            return {"n": 0}
        n = len(lat)
        return {"n": n, "min_ms": round(lat[0], 3), "p50_ms": round(lat[n // 2], 3),
                "p95_ms": round(lat[min(n - 1, int(0.95 * n))], 3)}
