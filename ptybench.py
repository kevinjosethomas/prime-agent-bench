#!/usr/bin/env python3
"""Raw-PTY benchmark driver: monotonic-clock spawn/read/write timing + pyte screen emulation.

Clock: time.perf_counter() (monotonic). Timestamps are controller-side seconds
since process start of the driver. `interactive-ready` = typed token echoed,
accepted, and erased without submitting (the suite notation), not first paint.

Not part of any product. Benchmark harness only.
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


def now() -> float:
    return time.perf_counter()


class PTYApp:
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

    def _read_loop(self):
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

    # ---- queries ----

    def screen_text(self) -> str:
        with self._lock:
            return "\n".join(self.screen.display)

    def screen_has(self, needle: str) -> bool:
        return needle in self.screen_text()

    def bytes_out(self) -> int:
        with self._lock:
            return self.chunks[-1][1] if self.chunks else 0

    def wait_for(self, predicate, timeout=30.0, poll=0.001):
        deadline = now() + timeout
        while True:
            v = predicate()
            if v:
                return now(), v
            if now() >= deadline:
                raise TimeoutError(f"wait_for timeout after {timeout:.1f}s")
            time.sleep(poll)

    def wait_screen_contains(self, text, timeout=30.0):
        return self.wait_for(lambda: text in self.screen_text(), timeout)

    def wait_screen_missing(self, text, timeout=30.0):
        return self.wait_for(lambda: text not in self.screen_text(), timeout)

    # ---- input ----

    def send(self, data) -> float:
        if isinstance(data, str):
            data = data.encode()
        t = now()
        os.write(self.master, data)
        return t

    def type_token(self, token, per_key_timeout=2.0, inter_key_pause=0.03):
        """Type token char by char; per-key send->rendered-echo latency in ms
        (screen-level detection on the cursor rows). A dropped key is None
        and stops the sequence (kept honest, not silently skipped)."""
        lat = []
        for i, ch in enumerate(token):
            prefix = token[: i + 1]
            self.start_echo_watch(prefix)
            t0 = self.send(ch)
            try:
                ts = self.wait_echo(per_key_timeout)
                lat.append(round((ts - t0) * 1000.0, 2))
            except TimeoutError:
                lat.append(None)
                return lat, False
            if inter_key_pause:
                time.sleep(inter_key_pause)
        return lat, True

    def erase_all(self, needle, max_backspaces=40, timeout=6.0):
        """Backspace until `needle` is no longer rendered anywhere (clears all
        accumulated probe chars). Returns (ok, ms)."""
        t0 = now()
        for _ in range(max_backspaces):
            self.send("\x7f")
            try:
                self.wait_for(lambda: needle not in self.screen_text(), timeout=0.35, poll=0.005)
                return True, round((now() - t0) * 1000.0, 2)
            except TimeoutError:
                continue
        return False, round((now() - t0) * 1000.0, 2)

    def start_echo_watch(self, token: str):
        """Watch for `token` rendered on the cursor-row window (the input
        line). Renders are screen-level: some TUIs draw typed chars via
        positioned cells with escape bytes between them, so raw-byte search
        never matches. The check runs in the reader thread (per-chunk), so
        detection latency is the chunk-arrival delta, not a poll loop."""
        with self._lock:
            self._echo_needle = token
            self._echo_seen_ts = None

    def wait_echo(self, timeout: float = 2.0):
        deadline = now() + timeout
        while True:
            with self._lock:
                if self._echo_seen_ts is not None:
                    return self._echo_seen_ts
            if now() >= deadline:
                raise TimeoutError(f"echo not rendered in {timeout:.1f}s")
            time.sleep(0.0005)

    def raw_has_since(self, needle: bytes, t_from: float) -> bool:
        """True if `needle` bytes appear in raw output written at/after t_from.

        Uses cumulative chunk offsets against the (capped, trimmed) raw
        buffer: no false positives from earlier echoes of the same bytes.
        The raw echo is the accepted-keystroke timestamp (the app wrote the
        char to the terminal); this keeps the harness floor sub-ms."""
        import bisect
        with self._lock:
            if not self.chunks:
                return False
            ts = [t for t, _ in self.chunks]
            i = bisect.bisect_left(ts, t_from)
            if i == 0:
                start_offset = 0
            else:
                start_offset = self.chunks[i - 1][1]  # include prior chunk: needle may straddle
            pos = max(0, start_offset - self.trimmed)
            return bytes(needle) in bytes(self.raw[pos:])

    def probe_input_ready(self, token="Zq7x", retry_every=0.5, timeout=45.0, start_ts=None):
        """From start_ts (default first paint), send unique probe tokens
        until one is echoed on the input line (rendered = accepted).
        Returns gap_ms (appearance - start), echo offset from spawn, and
        dropped-probe count. Each retry uses a fresh token so stale input
        can never satisfy the check."""
        start = start_ts if start_ts is not None else (self.t_first_paint or self.t_spawn)
        sends = []
        deadline = now() + timeout
        attempt = 0
        while now() < deadline:
            attempt += 1
            probe = f"{token}{attempt:02d}"
            self.start_echo_watch(probe)
            t_send = self.send(probe)
            sends.append(t_send)
            wait_for = min(retry_every, max(0.05, deadline - now()))
            try:
                ts = self.wait_echo(wait_for)
                chars_sent = sum(len(f"{token}{a:02d}") for a in range(1, attempt + 1))
                return {
                    "gap_ms": round((ts - start) * 1000.0, 2),
                    "echo_ts_offset_ms": round((ts - self.t_spawn) * 1000.0, 2),
                    "sends": len(sends),
                    "dropped_probes": len(sends) - 1,
                    "chars_sent": chars_sent,
                    "probe_token": f"{token}{attempt:02d}",
                }
            except TimeoutError:
                continue
        raise TimeoutError(f"input never became ready in {timeout:.0f}s ({len(sends)} probes)")

    # ---- frame stats ----

    def burst_stats(self, t_start=None, t_end=None, gap=0.05):
        """Chunk-burst decomposition in [t_start, t_end]: bursts separated by
        >`gap` seconds of silence. A clean single logical paint is few bursts;
        many small bursts indicate popping-in / incomplete frames."""
        with self._lock:
            allc = list(self.chunks)
        chunks = [(t, allc[i][1] - (allc[i - 1][1] if i else 0))
                  for i, (t, _) in enumerate(allc)
                  if (t_start is None or t >= t_start) and (t_end is None or t <= t_end)]
        bursts = []
        for t, n in chunks:
            if bursts and t - bursts[-1]["t_last"] <= gap:
                bursts[-1]["bytes"] += n
                bursts[-1]["n_chunks"] += 1
                bursts[-1]["t_last"] = t
            else:
                bursts.append({"t_first": t, "t_last": t, "bytes": n, "n_chunks": 1})
        return {
            "bursts": len(bursts),
            "per_burst_bytes": [b["bytes"] for b in bursts],
            "total_bytes": sum(b["bytes"] for b in bursts),
            "span_s": round((chunks[-1][0] - chunks[0][0]), 3) if chunks else 0,
        }

    # ---- lifecycle ----

    def alive(self) -> bool:
        return self.proc.poll() is None

    def kill_tree(self, sig=signal.SIGTERM):
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


def noop_control(rounds=50, cols=120, rows=40):
    """Calibrated harness floor: `cat` echo round-trip in the same PTY driver."""
    lat = []
    for i in range(rounds):
        app = PTYApp(["cat"], cols=cols, rows=rows)
        token = f"zqxjv{i:03d}"
        app.wait_for(lambda: True, timeout=1)
        app.start_echo_watch(token)
        t0 = app.send(token)
        try:
            ts = app.wait_echo(1.0)
            lat.append((ts - t0) * 1000.0)
        except TimeoutError:
            pass
        app.kill_tree()
    lat.sort()
    if not lat:
        return {"n": 0}
    n = len(lat)
    return {
        "n": n,
        "min_ms": round(lat[0], 3),
        "p50_ms": round(lat[n // 2], 3),
        "p95_ms": round(lat[min(n - 1, int(0.95 * n))], 3),
    }
