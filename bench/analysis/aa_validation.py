"""A/A noise-floor validation (Kevin's fairness rule).

The same product measured as two interleaved halves must agree within the
configured spread or the environment is too noisy for cross-product
comparisons — and a product with a failing A/A is never ranked (the
analysis stability gate). The halves are BALANCED (_aa_half): each half
samples the same mix of launch-occurrence positions and ABBA directions,
so a schedule-locked effect cannot masquerade as instability (the
cmp-v4 W1 lesson: the legacy even/odd split aliased halves with
occurrence position and claude's ~+40ms second-occurrence effect
surfaced as a 13.8% spread — a schedule artifact, not environment
instability; the withholding stood under the then-declared design, and
this fix is prospective only). The calibrated metric is the benchmark's
PRIMARY metric (core.measurement), plus any benchmark-declared
``aa_metrics`` (e.g. msg_send's settle, published alongside the ranked
ack) whenever they are published.
"""
from __future__ import annotations

from collections import defaultdict

from bench.analysis.stats import stats
from bench.core.measurement import metrics_for, primary_metric


def _aa_half(trial: int) -> int:
    """The balanced A/A half for one trial: a pure function of the
    within-product trial index, fixed before any measurement.

    The aa pass runs each product twice per round (seq + seq, one
    first-occurrence and one second-occurrence launch) and reverses the
    product order every other round. The legacy even/odd split put every
    first-occurrence launch in one half and every second-occurrence
    launch in the other (and every forward round in one half, every
    reversed round in the other), so any effect tied to occurrence
    position or direction landed entirely in one half — cmp-v4 W1's
    claude 13.8% "instability" was exactly that. Alternating the half
    assignment across rounds keeps each half balanced over both
    factors: at 20 aa trials per product (the calibration default)
    every half sees exactly 5 first-occurrences, 5 second-occurrences,
    5 forward rounds and 5 reversed rounds, so the halves compare like
    with like and the spread measures what it claims to measure —
    run-to-run repeatability of the position/direction-balanced
    published estimator."""
    return (trial // 2 + trial % 2) % 2


def aa_validity(rows: list, threshold_pct: float = 10.0,
                aa_metrics: dict | None = None) -> dict:
    """Per (benchmark, product[, metric]): balanced halves' p50s, spread,
    validity.

    The PRIMARY metric's entry is keyed ``bench/product``; each declared
    extra metric gets its own ``bench/product/metric`` entry. Without the
    ``aa_metrics`` map only the primary metric is calibrated. Status rows
    (trial None, no metrics) contribute nothing, by construction."""
    aa_metrics = aa_metrics or {}
    out = {}
    aa_rows = [r for r in rows if str(r.get("phase") or "") == "aa"]
    by = defaultdict(list)
    for r in aa_rows:
        if r.get("error"):
            continue
        bench = r.get("benchmark")
        primary, _ = primary_metric(bench) or (None, None)
        # the calibrated metrics are read through the same flattening as the
        # published stats (core.measurement.metrics_for): a primary that is
        # derived for legacy rows (session.cold_open's completion boundary)
        # calibrates from the A/A rows' own raw timestamps, no row rewrite
        flat = metrics_for(r)
        metrics = [m for m in (primary,) + tuple(aa_metrics.get(bench) or ())
                   if m and flat.get(m) is not None]
        for metric in metrics:
            by[(bench, r["product"], metric, _aa_half(r["trial"]))].append(
                flat.get(metric))
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
