"""Product rankings and deltas on a benchmark's primary metric."""
from __future__ import annotations


def rank_products(p50s: dict) -> dict:
    """Rank products by primary-metric p50 (all metrics minimize)."""
    ranked = sorted([(v, p) for p, v in p50s.items() if v is not None])
    return {p: i + 1 for i, (v, p) in enumerate(ranked)}


def delta_vs_baseline(p50s: dict, baseline: str = "ts") -> dict:
    """Per-product absolute and percent delta vs the baseline product."""
    base = p50s.get(baseline)
    out = {}
    for p, v in p50s.items():
        if v is not None and base:
            out[p] = {"abs": round(v - base, 1),
                       "pct": round((v - base) / base * 100.0, 1)}
    return out
