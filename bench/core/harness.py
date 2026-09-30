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

    def erase_all(self, needle: str, max_backspaces: int = 40, timeout: float = 6.0,
                  refresh_keys: tuple = ()):
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
        for key in refresh_keys:
            self.send(key)
            try:
                self.wait_for(lambda: needle not in self.screen_text(), timeout=3.0, poll=0.01)
                return True, round((now() - t0) * 1000.0, 2)
            except TimeoutError:
                continue
        return False, round((now() - t0) * 1000.0, 2)

    def probe_input_ready(self, token: str = "Zq7x", retry_every: float = 0.5,
                          timeout: float = 45.0, start_ts: float | None = None,
                          dialog_steps: tuple = (), fine_grid_s: float = 0.05,
                          fine_window_s: float = 1.0,
                          dialog_key_pause_s: float = 0.4) -> dict:
        """From start_ts (default first paint), send unique probe tokens
        until one is echoed on the input line (rendered = accepted).
        Each retry uses a fresh token so stale input can never satisfy the
        check. Returns gap_ms, echo offset from spawn, dropped-probe count.

        Harness-floor honesty (audit F13): readiness is detected on a probe
        grid, so the measured value can overstate the true input-accept
        moment by up to one grid step. The first ``fine_window_s`` after
        start probes on the fine grid (``fine_grid_s``); after that the
        grid backs off to ``retry_every``. Two evidence fields quantify the
        floor per row: ``input_buffered`` (an earlier probe token rendered
        alongside the echoed one — the product queued pre-ready input and
        rendered it at mount time, so the echo timestamp IS the readiness
        render and quantization is zero) and ``quantized_ms`` (the
        worst-case harness overshoot when input was dropped instead:
        the successful attempt's grid step). Probes sent into a rendered
        onboarding dialog would inflate "readiness" with dialog walk time,
        so ``dialog_steps`` markers are answered inline between probe
        attempts (mid-probe dialogs) and the readiness clock restarts after
        each dismissal — dialog time is excluded from gap_ms and reported
        separately (dialogs, dialog_ms)."""
        start = start_ts if start_ts is not None else (self.t_first_paint or self.t_spawn)
        sends = []
        dialogs = []
        dialog_time = 0.0
        answered: dict = {}
        deadline = now() + timeout
        attempt = 0
        while now() < deadline:
            if dialog_steps:
                txt_norm = " ".join(self.screen_text().split())
                handled = False
                for marker, keys in dialog_steps:
                    # TUIs wrap dialog text at arbitrary columns: match the
                    # whitespace-normalized screen, not the raw rows
                    if marker in txt_norm and answered.get(marker, 0) < 3:
                        answered[marker] = answered.get(marker, 0) + 1
                        t_dialog = now()
                        for k in keys:
                            self.send(k)
                            time.sleep(dialog_key_pause_s)
                        dialog_time += now() - t_dialog
                        dialogs.append(marker)
                        start = now()  # dialog time is excluded from the gap
                        handled = True
                        break
                if handled:
                    continue
            grid = fine_grid_s if (now() - start) < fine_window_s else retry_every
            attempt += 1
            probe = f"{token}{attempt:02d}"
            self.start_echo_watch(probe)
            t_send = self.send(probe)
            sends.append(t_send)
            wait_for = min(grid, max(0.005, deadline - now()))
            try:
                ts = self.wait_echo(wait_for)
                chars_sent = sum(len(f"{token}{a:02d}") for a in range(1, attempt + 1))
                earlier = [f"{token}{a:02d}" for a in range(1, attempt)]
                buffered = bool(earlier) and any(t in self.screen_text()
                                                for t in earlier)
                return {
                    "gap_ms": round((ts - start) * 1000.0, 2),
                    "echo_ts_offset_ms": round((ts - self.t_spawn) * 1000.0, 2),
                    "sends": len(sends),
                    "dropped_probes": len(sends) - 1,
                    "chars_sent": chars_sent,
                    "probe_token": f"{token}{attempt:02d}",
                    "input_buffered": buffered,
                    "probe_grid_ms": round(grid * 1000.0, 1),
                    "quantized_ms": 0.0 if buffered else round(grid * 1000.0, 1),
                    "dialogs": dialogs,
                    "dialog_ms": round(dialog_time * 1000.0, 1),
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
