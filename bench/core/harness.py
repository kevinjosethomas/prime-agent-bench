"""The HarnessDriver/Session ABCs: interchangeable TUI drivers.

The raw-PTY driver (pyte screen emulation, per-chunk echo detection,
sub-ms floor) is the default; a tmux driver covers TUIs that misbehave
under PTY emulation. Timestamps are controller-side monotonic seconds;
``interactive-ready`` = typed token echoed, accepted, and erased without
submitting. Not part of any product. Benchmark harness only.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Callable


def now() -> float:
    """The monotonic controller clock (relative; deltas only)."""
    return time.perf_counter()


class Session(ABC):
    """One product process attached through a driver.

    Drivers implement the echo/kill primitives; the generic probe helpers
    (typing, erase, input-ready) are built on top so every driver gets the
    same measurement semantics. Byte-stream metrics (bytes_out, burst_stats)
    are None for drivers without a raw stream.
    """

    t_spawn: float = 0.0
    t_first_paint: float | None = None
    pid: int | None = None

    # ---- driver primitives ----------------------------------------------
    @abstractmethod
    def send(self, data) -> float:
        """Write input to the product; returns the send timestamp."""

    @abstractmethod
    def screen_text(self) -> str:
        """The rendered screen text right now."""

    @abstractmethod
    def alive(self) -> bool:
        """Whether the product process is still running."""

    @abstractmethod
    def kill_tree(self, sig=None) -> None:
        """Kill the whole process tree."""

    @abstractmethod
    def start_echo_watch(self, token: str) -> None:
        """Watch for ``token`` rendered on the input line."""

    @abstractmethod
    def wait_echo(self, timeout: float = 2.0) -> float:
        """Block until the watched token echoes; returns its timestamp."""

    def wait_output_after(self, t_start: float, timeout: float = 10.0) -> float:
        """Block until the product writes output after t_start; returns its
        timestamp. Default: the first rendered-frame change (poll-clocked);
        drivers with a byte stream override with the exact first-chunk
        timestamp."""
        base = self.screen_text()
        deadline = now() + timeout
        while now() < deadline:
            if self.screen_text() != base:
                return now()
            time.sleep(0.001)
        raise TimeoutError(f"no output after t={t_start:.3f} in {timeout:.0f}s")

    # ---- byte-stream metrics (driver-specific, optional) -----------------
    def bytes_out(self) -> int | None:
        """Total bytes written by the product, if the driver sees a stream."""
        return None

    def burst_stats(self, t_start: float | None = None, t_end: float | None = None,
                    gap: float = 0.05) -> dict | None:
        """Chunk-burst decomposition, if the driver sees a stream."""
        return None

    # ---- generic probes ---------------------------------------------------
    def screen_has(self, needle: str) -> bool:
        """Whether the needle appears anywhere on the screen."""
        return needle in self.screen_text()

    def wait_for(self, predicate: Callable, timeout: float = 30.0, poll: float = 0.001):
        """Poll a predicate until truthy; returns (timestamp, value)."""
        deadline = now() + timeout
        while True:
            v = predicate()
            if v:
                return now(), v
            if now() >= deadline:
                raise TimeoutError(f"wait_for timeout after {timeout:.1f}s")
            time.sleep(poll)

    def wait_screen_contains(self, text: str, timeout: float = 30.0):
        """Block until the screen contains ``text``."""
        return self.wait_for(lambda: text in self.screen_text(), timeout)

    def wait_screen_missing(self, text: str, timeout: float = 30.0):
        """Block until the screen no longer contains ``text``."""
        return self.wait_for(lambda: text not in self.screen_text(), timeout)

    def type_token(self, token: str, per_key_timeout: float = 2.0,
                   inter_key_pause: float = 0.03):
        """Type token char by char; per-key send->rendered-echo latency in ms.
        A dropped key is None and stops the sequence (kept honest)."""
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

    def erase_all(self, needle: str, max_backspaces: int = 40, timeout: float = 6.0):
        """Backspace until ``needle`` is no longer rendered anywhere.
        Returns (ok, ms)."""
        t0 = now()
        for _ in range(max_backspaces):
            self.send("\x7f")
            try:
                self.wait_for(lambda: needle not in self.screen_text(), timeout=0.35, poll=0.005)
                return True, round((now() - t0) * 1000.0, 2)
            except TimeoutError:
                continue
        return False, round((now() - t0) * 1000.0, 2)

    def probe_input_ready(self, token: str = "Zq7x", retry_every: float = 0.5,
                          timeout: float = 45.0, start_ts: float | None = None) -> dict:
        """From start_ts (default first paint), send unique probe tokens
        until one is echoed on the input line (rendered = accepted).
        Each retry uses a fresh token so stale input can never satisfy the
        check. Returns gap_ms, echo offset from spawn, dropped-probe count."""
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


class HarnessDriver(ABC):
    """A TUI driver: spawns products and yields measurement-grade sessions."""

    name: str = ""

    def __init__(self, cfg: dict):
        self.cfg = cfg

    @abstractmethod
    def start_session(self, argv, env: dict | None = None, cwd: str | None = None,
                      cols: int = 120, rows: int = 40) -> Session:
        """Spawn argv attached to the driver; returns the instrumented session."""

    def noop_control(self, rounds: int = 50, cols: int = 120, rows: int = 40) -> dict | None:
        """Calibrated harness floor (``cat`` echo round-trip); None if the
        driver cannot measure one."""
        return None
