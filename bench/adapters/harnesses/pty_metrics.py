"""Byte-stream analytics over a PTY session's chunk ledger.

PtyStreamMixin: burst decomposition (frame completeness / popping-in
detector) and the raw-echo offset search. noop_control: the calibrated
harness floor (`cat` echo round-trip). The mixin expects PTYSession's
``chunks``/``raw``/``trimmed``/``_lock`` attributes.
"""
from __future__ import annotations

import bisect
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - annotation-only import
    from bench.adapters.harnesses.pty import PTYSession


class PtyStreamMixin:
    """Byte-stream metrics for a session that sees the raw PTY stream."""

    def burst_stats(self, t_start: float | None = None, t_end: float | None = None,
                    gap: float = 0.05) -> dict:
        """Chunk-burst decomposition in [t_start, t_end]: bursts separated by
        >`gap` seconds of silence. A clean single logical paint is few bursts;
        many small bursts indicate popping-in / incomplete frames."""
        chunks = self._chunks_in(t_start, t_end)
        bursts: list[dict] = []
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

    def raw_has_since(self, needle: bytes, t_from: float) -> bool:
        """True if `needle` bytes appear in raw output written at/after t_from.

        Uses cumulative chunk offsets against the (capped, trimmed) raw
        buffer: no false positives from earlier echoes of the same bytes.
        The raw echo is the accepted-keystroke timestamp (the app wrote the
        char to the terminal); this keeps the harness floor sub-ms."""
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

    # internal ---------------------------------------------------------------
    def _chunks_in(self, t_start: float | None, t_end: float | None) -> list[tuple[float, int]]:
        """(timestamp, chunk_bytes) pairs inside the window, lock-held copy."""
        with self._lock:
            allc = list(self.chunks)
        return [(t, allc[i][1] - (allc[i - 1][1] if i else 0))
                for i, (t, _) in enumerate(allc)
                if (t_start is None or t >= t_start) and (t_end is None or t <= t_end)]


def noop_control(rounds: int = 50, cols: int = 120, rows: int = 40) -> dict:
    """Calibrated harness floor: `cat` echo round-trip in the PTY driver."""
    from bench.adapters.harnesses.pty import PTYSession

    lat = []
    for i in range(rounds):
        app = PTYSession(["cat"], cols=cols, rows=rows)
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
