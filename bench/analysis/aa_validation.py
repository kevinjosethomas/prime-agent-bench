"""A/A noise-floor validation (Kevin's fairness rule).

The same product measured as two interleaved halves must agree within the
configured spread or the environment is too noisy for cross-product
comparisons — and a product with a failing A/A is never ranked (the
analysis stability gate). The halves are the even/odd trial indices; the
calibrated metric is the benchmark's PRIMARY metric (core.measurement),
plus any benchmark-declared ``aa_metrics`` (e.g. msg_send's settle,
published alongside the ranked ack) whenever they are published.
"""
from __future__ import annotations

from collections import defaultdict

from bench.analysis.stats import stats
from bench.core.measurement import primary_metric


def aa_validity(rows: list, threshold_pct: float = 10.0,
                aa_metrics: dict | None = None) -> dict:
    """Per (benchmark, product[, metric]): halves' p50s, spread, validity.

    The PRIMARY metric's entry is keyed ``bench/product``; each declared
    extra metric gets its own ``bench/product/metric`` entry. Without the
    ``aa_metrics`` map only the primary metric is calibrated."""
    aa_metrics = aa_metrics or {}
    out = {}
    aa_rows = [r for r in rows if str(r.get("phase") or "") == "aa"]
    by = defaultdict(list)
    for r in aa_rows:
        if r.get("error"):
            continue
        bench = r.get("benchmark")
        primary, _ = primary_metric(bench) or (None, None)
        metrics = [m for m in (primary,) + tuple(aa_metrics.get(bench) or ())
                   if m and (r.get("metrics") or {}).get(m) is not None]
        for metric in metrics:
            by[(bench, r["product"], metric, r["trial"] % 2)].append(
                r.get("metrics", {}).get(metric))
    grouped = defaultdict(dict)
    for (bench, prod, metric, half), vals in by.items():
        grouped[(bench, prod, metric)][half] = vals
    for (bench, prod, metric), halves in grouped.items():
        a = stats(halves.get(0, []))
        b = stats(halves.get(1, []))
        if a.get("p50") and b.get("p50"):
            spread = abs(a["p50"] - b["p50"]) / min(a["p50"], b["p50"]) * 100
            primary, _ = primary_metric(bench) or (None, None)
            key = f"{bench}/{prod}" if metric == primary else f"{bench}/{prod}/{metric}"
            out[key] = {"a_p50": a["p50"], "b_p50": b["p50"],
                        "spread_pct": round(spread, 1),
                        "valid": spread <= threshold_pct}
    return out


def aa_failing(aa: dict) -> dict:
    """{benchmark: {product: {metric: entry}}} for every FAILING A/A entry
    (the primary and declared extra metrics), keyed for the stability gate."""
    failing: dict = defaultdict(lambda: defaultdict(dict))
    for key, entry in aa.items():
        if entry.get("valid"):
            continue
        parts = key.split("/")
        if len(parts) < 2:
            continue
        bench, prod = parts[0], parts[1]
        primary, _ = primary_metric(bench) or (None, None)
        metric = primary if len(parts) == 2 else "/".join(parts[2:])
        failing[bench][prod][metric] = entry
    return dict(failing)
