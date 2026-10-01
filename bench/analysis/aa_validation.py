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


def latest_attempt(rows: list) -> list:
    """Keep each (benchmark, product)'s rows of its latest A/A attempt only
    (a re-run replaces the failed attempt; rows without ``attempt`` are 0)."""
    last: dict = {}
    for r in rows:
        key = (r.get("benchmark"), r.get("product"))
        last[key] = max(last.get(key, 0), int(r.get("attempt") or 0))
    return [r for r in rows
            if int(r.get("attempt") or 0) == last[(r.get("benchmark"), r.get("product"))]]


def pair_verdict(aa_rows: list, wave_rows: list, metric: str, aa_cfg: dict,
                 expected: int | None = None) -> dict:
    """The A/A gate for one (benchmark, product) attempt.

    ``aa_rows``/``wave_rows``: the attempt's VALID rows. The A/A halves are
    the even/odd trial indices (interleaved in time). Failing: the halves'
    p50s differ by more than ``spread_threshold_pct`` AND more than
    ``abs_floor_ms`` (the floor keeps sub-50 ms products from failing on
    single-digit-ms jitter), or the published wave's p50 drifts from the
    A/A p50 by more than ``drift_threshold_pct`` AND ``abs_floor_ms``, or
    fewer than ``min_valid_frac`` of the expected trials are valid."""
    spread_t = float(aa_cfg.get("spread_threshold_pct", 10.0))
    drift_t = float(aa_cfg.get("drift_threshold_pct", 10.0))
    floor = float(aa_cfg.get("abs_floor_ms", 5.0))
    min_frac = float(aa_cfg.get("min_valid_frac", 0.8))

    def vals(rows, half=None):
        return [(r.get("metrics") or {}).get(metric) for r in rows
                if half is None or (r.get("trial") or 0) % 2 == half]

    a, b = stats(vals(aa_rows, 0)), stats(vals(aa_rows, 1))
    aa_all, wave = stats(vals(aa_rows)), stats(vals(wave_rows))
    out = {"metric": metric, "aa_a_p50": a.get("p50"), "aa_b_p50": b.get("p50"),
           "aa_p50": aa_all.get("p50"), "wave_p50": wave.get("p50"),
           "aa_n": aa_all["n"], "wave_n": wave["n"], "reasons": []}
    if expected:
        for label, n in (("aa", aa_all["n"]), ("wave", wave["n"])):
            if n < min_frac * expected:
                out["reasons"].append(f"{label}_valid_{n}_of_{expected}")
    if a.get("p50") and b.get("p50"):
        diff = abs(a["p50"] - b["p50"])
        out["spread_pct"] = round(diff / min(a["p50"], b["p50"]) * 100, 1)
        if out["spread_pct"] > spread_t and diff > floor:
            out["reasons"].append("aa_spread")
    else:
        out["reasons"].append("aa_missing")
    if aa_all.get("p50") and wave.get("p50"):
        diff = abs(wave["p50"] - aa_all["p50"])
        out["drift_pct"] = round(diff / aa_all["p50"] * 100, 1)
        if out["drift_pct"] > drift_t and diff > floor:
            out["reasons"].append("aa_drift")
    else:
        out["reasons"].append("wave_missing")
    out["ok"] = not out["reasons"]
    return out
