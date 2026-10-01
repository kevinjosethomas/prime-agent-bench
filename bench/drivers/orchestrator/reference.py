"""The canonical reference benchmark and cross-sandbox comparison.

A fixed CPU-bound loop runs on every sandbox before any trial wave; its
wall time is the sandbox's speed-of-light. Sandboxes deviating more than
the threshold (>5% default) are flagged — replaced (re-provisioned) or
normalized (the factor recorded for the analysis layer), per policy.
"""
from __future__ import annotations

import statistics

REFERENCE_CODE = """
import time
t0 = time.perf_counter()
acc = 0
for i in range(25_000_000):
    acc = (acc + i * 7) % 1000003
ms = (time.perf_counter() - t0) * 1000.0
print(f"REFERENCE-MS {round(ms, 1)} {acc}")
"""


def run_reference(backend, handle) -> float:
    """The reference wall time in ms on this sandbox."""
    code, out = backend.exec_cmd(
        handle, f"python3 -c {shlex_quote(REFERENCE_CODE)}", timeout=300.0)
    if code != 0:
        raise RuntimeError(f"reference failed on {handle.name}: {out[-300:]}")
    for line in out.splitlines():
        if line.startswith("REFERENCE-MS"):
            return float(line.split()[1])
    raise RuntimeError(f"no REFERENCE-MS marker from {handle.name}: {out[-300:]}")


def shlex_quote(code: str) -> str:
    """Quote python code for `python3 -c` inside a bash -lc command."""
    import shlex
    return shlex.quote(code.strip())


def compare_references(times: dict, threshold_pct: float = 5.0,
                       median_ms: float | None = None) -> dict:
    """Flag sandboxes whose reference deviates from the median by >threshold.

    ``median_ms``: a recorded fleet median to calibrate against instead of
    this run's own (a one-sandbox re-run lines up with an earlier campaign).
    Returns {"median_ms", "outliers": {name: {"ms", "dev_pct"}}}.
    """
    if not times:
        return {"median_ms": median_ms, "outliers": {}}
    median = median_ms or statistics.median(times.values())
    outliers = {}
    for name, ms in times.items():
        dev_pct = (ms - median) / median * 100.0 if median else 0.0
        if abs(dev_pct) > threshold_pct:
            outliers[name] = {"ms": ms, "dev_pct": round(dev_pct, 1)}
    return {"median_ms": round(median, 1), "outliers": outliers}
