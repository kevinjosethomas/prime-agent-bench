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
    def echo_window_text(self, rows_up: int = 0, rows_down: int = 1) -> str | None:
        """The rendered text of the EDITOR ROWS: the cursor row plus
        ``rows_down`` below it (or None for drivers without cursor
        state — erase_all then falls back to the whole screen).

        Scope rationale (the live nav diagnostic): the caller derives the
        rows-up cap from the probe metadata (ceil(total chars / cols) +
        margin) so every wrapped row of the input block is inspected
        (66 probe attempts wrapped SIX rows on the live Rust screen —
        the cursor row alone can never certify that block). Rows above
        the capped block start are the transcript tail: gating on the
        whole screen would false-negative a clean editor whose
        transcript shows probe fragments (``editor_line_empty=true``
        with probe text still rendered in the transcript after an
        accidental polluted submit). Conservative False is acceptable;
        false True is forbidden."""
        return None

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

    def erase_all(self, needles, max_backspaces: int = 40, timeout: float = 6.0):
        """Erase the input line: one bounded DEL burst, then ONE
        editor-scoped verification of EVERY needle. Returns (ok, ms);
        (False, budget) whenever the erase cannot be certified — never
        a vacuous success.

        ``needles`` is one token or a list (probe_input_ready returns the
        full ``probe_tokens`` list): certifying only the last/base token
        can leave earlier attempt tokens rendered — the live agent-view
        failure had ``erase_ok=true`` while TS's editor still held
        ``Zq7x20..25`` (plus a ``/resumeq`` fragment), silently breaking
        every navigation leg. A token split at a line wrap has no full
        substring in any single row, so the window text is checked both
        row-wise and seam-joined; the seam-join is conservative — it
        can only extend the wait or fail the erase, never certify a
        line that still holds needle text.

        The verification scope is the EDITOR REGION (``echo_window_text``
        — the cursor row, the rows below it, and up to
        ceil(total_chars/cols)+2 rows above it, the probe-derived cap on
        the wrapped input block), not the whole screen: a clean editor
        can coexist with probe text elsewhere (the live Rust diagnostic
        had ``editor_line_empty=true`` while the screen still showed
        probe fragments in the transcript), and a whole-screen check
        would false-negative there. The cap keeps every wrapped row of
        the block in scope (66 sends wrap 4 rows — a cursor-row-only
        gate would false-certify while earlier rows still hold tokens)
        while transcript rows above the block stay out. In-benchmark
        flows are structurally immune to transcript probe text (erase
        runs before any submit), so the conservative direction here is
        safe: the verdict can only fail loudly. Drivers without cursor
        state fall back to the whole screen.

        No erase mechanism is assumed universal: a DEL burst cannot
        reach every input surface (the pinned Pi proof: the pre-mount
        probe echoes at ~0.28s, a 14-byte DEL burst fails to clear it,
        Ctrl-U clears it, post-mount DEL works). This primitive stays
        conservative — the burst plus the all-token gate returns False
        on a surface DEL cannot reach; a proven key for a specific
        product belongs in that product's adapter, not here. The burst
        is a single queued write (chunked only above 256 bytes);
        surplus DELs no-op on an already-empty line. One bounded
        ``wait_for`` at the end replaces the per-key 0.35s waits that
        burned the harness's own timeout per character on a wrapped
        line (the live 4c59054 evidence: 22 buffered probe tokens =
        132 chars = a 45,200ms erase inside a ~50s trial). The total
        budget stays ``timeout`` (unchanged default 6s). Real-TUI proof
        for the products in scope runs through scripts/verify_erase_pty.py
        before a wave relies on this."""
        if isinstance(needles, str):
            needles = [needles]
        needles = [n for n in needles if n]

        # the editor-block cap (from the probe metadata itself): the input
        # block can wrap ceil(total_chars / cols) rows above the cursor
        # (the live stress case: 66 probe sends = 4 wrapped rows of
        # residue), so a cursor-row-only gate would false-certify while
        # earlier wrapped rows still hold tokens. The cap uses the
        # needles' own length plus prompt slack and margin; rows above
        # the cap are the transcript and stay out of scope.
        total_chars = sum(len(n) for n in needles)
        cols = int(getattr(self, "cols", 0) or 120)
        rows_up = min(40, -(-(total_chars + 2) // cols) + 2)

        def _clean() -> bool:
            window = self.echo_window_text(rows_up=rows_up, rows_down=1)
            if window is None:
                window = self.screen_text()
            joined = "".join(window.splitlines())
            return all(n not in window and n not in joined for n in needles)

        t0 = now()
        burst = b"\x7f" * max(0, int(max_backspaces))
        for i in range(0, len(burst), 256):
            self.send(burst[i:i + 256])
            if i:
                time.sleep(0.01)
        try:
            self.wait_for(_clean, timeout=timeout, poll=0.005)
            return True, round((now() - t0) * 1000.0, 2)
        except TimeoutError:
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
        separately (dialogs, dialog_ms).

        Attempt-disposition honesty (the dropped_probes misnomer): an
        attempt whose token did not echo within its grid step is an
        UNCONFIRMED attempt — the token may have been discarded, may
        still sit unread, or may have been accepted and rendered later
        (buffered). ``unconfirmed_attempts`` counts them without
        claiming a disposition. The legacy ``dropped_probes`` key stays
        in the result for row-schema continuity but carries None in
        new rows: a true drop can never be established from screen
        observation alone (earlier tokens may be queued, rendered at
        mount, or scroll-hidden). When ``input_buffered`` is true the
        echo timestamp is the mount-time render of queued input — the
        exact input-accept moment is unknown and never claimed;
        gap_ms/echo_ts_offset_ms keep their observed-render meaning
        (no change to the readiness metric)."""
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
                    "unconfirmed_attempts": len(sends) - 1,
                    # legacy key: disposition is unknowable from the screen
                    # (queued vs discarded vs scroll-hidden); None = unknown
                    "dropped_probes": None,
                    "chars_sent": chars_sent,
                    "probe_token": f"{token}{attempt:02d}",
                    # every attempt token: erase_all(probe_tokens) certifies
                    # the whole line clean, not just the echoed token
                    "probe_tokens": [f"{token}{a:02d}" for a in range(1, attempt + 1)],
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
