"""Summary statistics: nearest-rank percentiles and bootstrap CIs."""
from __future__ import annotations

import math
import random


def pct(vals, p: float):
    """The p-th percentile (nearest-rank on the sorted values)."""
    if not vals:
        return None
    s = sorted(vals)
    idx = min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))
    return s[idx]


def stats(vals) -> dict:
    """n/min/p50/p95/p99/max/mean/stdev over the non-None values."""
    vals = [v for v in vals if v is not None]
    if not vals:
        return {"n": 0}
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / max(1, len(vals) - 1)
    return {"n": len(vals), "min": round(min(vals), 1), "p50": round(pct(vals, 50), 1),
            "p95": round(pct(vals, 95), 1), "p99": round(pct(vals, 99), 1),
            "max": round(max(vals), 1), "mean": round(mean, 1),
            "stdev": round(math.sqrt(var), 2)}


def boot_ci_median(vals, n: int = 1000, seed: int = 7):
    """The 95% bootstrap CI of the median (None under n<3 samples)."""
    vals = [v for v in vals if v is not None]
    if len(vals) < 3:
        return None
    rng = random.Random(seed)
    meds = []
    for _ in range(n):
        sample = [vals[rng.randrange(len(vals))] for _ in vals]
        meds.append(sorted(sample)[len(sample) // 2])
    meds.sort()
    return [round(meds[int(0.025 * n)], 1), round(meds[int(0.975 * n)], 1)]
