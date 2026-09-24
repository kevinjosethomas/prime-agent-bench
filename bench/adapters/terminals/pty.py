"""The raw-PTY driver: monotonic-clock spawn/read/write + pyte screen emulation.

The timing-grade driver: per-chunk read loop timestamps, cursor-row echo
detection in the reader thread (detection latency = chunk-arrival delta,
not a poll loop), sub-ms floor. Not part of any product.
"""
from __future__ import annotations

import errno
import fcntl
import os
import pty
import select
import signal
import struct
import subprocess
import termios
import threading
import time

import pyte

from bench.adapters.terminals.pty_metrics import PtyStreamMixin, noop_control
from bench.core.harness import HarnessDriver, Session, now


class PTYSession(PtyStreamMixin, Session):
    """One product process attached to a fresh PTY with timing instrumentation."""

    def __init__(self, argv, env=None, cwd=None, cols=120, rows=40, raw_cap=4 * 1024 * 1024):
        self.cols, self.rows = cols, rows
        self.argv = list(argv)
        self.master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        fl = fcntl.fcntl(self.master, fcntl.F_GETFL)
        fcntl.fcntl(self.master, fcntl.F_SETFL, fl | os.O_NONBLOCK)
        self.t_spawn = now()
        self.proc = subprocess.Popen(
            argv,
            env=env,
            cwd=cwd,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            start_new_session=True,
            close_fds=True,
        )
        os.close(slave)
        self.pid = self.proc.pid
        self.exit_code = None
        self.raw = bytearray()
        self.raw_cap = raw_cap
        self.chunks = []  # (t, cumulative_end_offset) tuples
        self.trimmed = 0
        self.screen = pyte.Screen(cols, rows)
        self.stream = pyte.ByteStream(self.screen)
        self.t_first_byte = None
        self.t_first_paint = None  # first chunk after which the screen is non-blank
        self._echo_needle = None   # token being watched on the cursor rows
        self._echo_seen_ts = None  # chunk timestamp when the token appeared
        self._lock = threading.Lock()
        self._alive = True
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self) -> None:
        while self._alive:
            try:
                r, _, _ = select.select([self.master], [], [], 0.002)
            except (OSError, ValueError):
                break
            if not r:
                continue
            try:
                data = os.read(self.master, 65536)
            except OSError as e:
                if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                    continue
                break  # EIO: all writers closed
            if not data:
                break
            t = now()
            with self._lock:
                if self.t_first_byte is None:
                    self.t_first_byte = t
                if self.chunks:
                    self.chunks.append((t, self.chunks[-1][1] + len(data)))
                else:
                    self.chunks.append((t, len(data)))
                self.raw.extend(data)
                if len(self.raw) > self.raw_cap:
                    drop = len(self.raw) - self.raw_cap
                    del self.raw[:drop]
                    self.trimmed += drop
                self.stream.feed(data)
                if self.t_first_paint is None:
                    try:
                        if any(row.strip() for row in self.screen.display):
                            self.t_first_paint = t
                    except Exception:
                        pass
                if self._echo_needle is not None and self._echo_seen_ts is None:
                    try:
                        y = self.screen.cursor.y
                        rows = self.screen.display[max(0, y - 1): y + 2]
                        if any(self._echo_needle in r for r in rows):
                            self._echo_seen_ts = t
                    except Exception:
                        pass
        try:
            self.proc.wait(timeout=10)
        except Exception:
            pass
        self.exit_code = self.proc.returncode

    # ---- primitives --------------------------------------------------------
    def screen_text(self) -> str:
        """The emulated screen text (all rows joined)."""
        with self._lock:
            return "\n".join(self.screen.display)

    def bytes_out(self) -> int:
        """Total PTY bytes written by the product so far."""
        with self._lock:
            return self.chunks[-1][1] if self.chunks else 0

    def echo_window_text(self, rows_up: int = 0, rows_down: int = 1) -> str | None:
        """The cursor-anchored editor rows (driver cursor state)."""
        with self._lock:
            y = self.screen.cursor.y
            top = max(0, y - max(0, rows_up))
            return "\n".join(self.screen.display[top:y + 1 + max(0, rows_down)])

    def send(self, data) -> float:
        if isinstance(data, str):
            data = data.encode()
        t = now()
        os.write(self.master, data)
        return t

    def start_echo_watch(self, token: str) -> None:
        """Watch for ``token`` rendered on the cursor-row window (the input
        line). Renders are screen-level: some TUIs draw typed chars via
        positioned cells with escape bytes between them, so raw-byte search
        never matches. The check runs per-chunk in the reader thread."""
        with self._lock:
            self._echo_needle = token
            self._echo_seen_ts = None

    def wait_echo(self, timeout: float = 2.0) -> float:
        """Block until the watched token echoes (reader-thread timestamp)."""
        deadline = now() + timeout
        while True:
            with self._lock:
                if self._echo_seen_ts is not None:
                    return self._echo_seen_ts
            if now() >= deadline:
                raise TimeoutError(f"echo not rendered in {timeout:.1f}s")
            time.sleep(0.0005)

    def wait_output_after(self, t_start: float, timeout: float = 10.0) -> float:
        """The first chunk timestamp after t_start (exact, from the ledger)."""
        deadline = now() + timeout
        while now() < deadline:
            with self._lock:
                for t, _ in self.chunks:
                    if t > t_start:
                        return t
            time.sleep(0.002)
        raise TimeoutError(f"no output after t={t_start:.3f} in {timeout:.0f}s")

    # ---- lifecycle -----------------------------------------------------------
    def alive(self) -> bool:
        return self.proc.poll() is None

    def kill_tree(self, sig=signal.SIGTERM) -> None:
        """SIGTERM the process group, escalate to SIGKILL."""
        self._alive = False
        try:
            pgid = os.getpgid(self.proc.pid)
        except ProcessLookupError:
            return
        for s in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(pgid, s)
            except ProcessLookupError:
                return
            time.sleep(0.4)
            if self.proc.poll() is not None:
                break
        try:
            self.proc.wait(timeout=5)
        except Exception:
            pass


class PTYDriver(HarnessDriver):
    """Driver that spawns products on a raw PTY (the default, timing-grade)."""

    name = "pty"

    def start_session(self, argv, env=None, cwd=None, cols=120, rows=40) -> PTYSession:
        return PTYSession(argv, env=env, cwd=cwd, cols=cols, rows=rows)

    def noop_control(self, rounds: int = 50, cols: int = 120, rows: int = 40) -> dict:
        """The harness floor calibration (`cat` echo round-trip)."""
        return noop_control(rounds, cols, rows)
