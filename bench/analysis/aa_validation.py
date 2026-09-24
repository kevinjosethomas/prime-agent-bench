"""A/A noise-floor validation (Kevin's fairness rule).

The same product measured as two interleaved halves must agree within the
configured spread or the environment is too noisy for cross-product
comparisons.
"""
from __future__ import annotations

from collections import defaultdict

from bench.analysis.stats import stats


def aa_validity(rows: list, threshold_pct: float = 10.0) -> dict:
    """Per (benchmark, product): the two halves' p50s, spread, validity."""
    out = {}
    aa_rows = [r for r in rows if r.get("phase") == "aa"]
    by = defaultdict(list)
    for r in aa_rows:
        if not r.get("error"):
            by[(r["benchmark"], r["product"], r["trial"] % 2)].append(
                r.get("metrics", {}).get("launch_to_ready_ms"))
    grouped = defaultdict(dict)
    for (bench, prod, half), vals in by.items():
        grouped[(bench, prod)][half] = [v for v in vals if v is not None]
    for (bench, prod), halves in grouped.items():
        a = stats(halves.get(0, []))
        b = stats(halves.get(1, []))
        if a.get("p50") and b.get("p50"):
            spread = abs(a["p50"] - b["p50"]) / min(a["p50"], b["p50"]) * 100
            out[f"{bench}/{prod}"] = {"a_p50": a["p50"], "b_p50": b["p50"],
                                      "spread_pct": round(spread, 1),
                                      "valid": spread <= threshold_pct}
    return out
