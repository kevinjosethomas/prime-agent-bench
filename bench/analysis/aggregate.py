"""Trial-row aggregation into the shared summary model.

load_all reads every trials-*.jsonl under a results tree; aggregate groups
flattened metrics (core.measurement.metrics_for) by benchmark/product;
summarize attaches stats, ranks, and deltas; summarize_rows is the
Analyzer.compute_stats entry point and enforces the strict
result-validity gate (analysis.validity): only completed valid trials are
aggregated, published stats never mix A/A calibration or debug rows in,
and every exclusion is reported with count + reason.
"""
from __future__ import annotations

import glob
import json
from collections import defaultdict
from pathlib import Path

from bench.analysis.aa_validation import aa_validity
from bench.analysis.rankings import delta_vs_baseline, rank_products
from bench.analysis.stats import boot_ci_median, stats
from bench.analysis.validity import (ERROR_REASONS, gate_rows, is_aa_phase,
                                     settle_auth_products)
from bench.core.measurement import primary_metric


def load_all(results_dir) -> list:
    """Every trial row from every <results>/<benchmark>/trials-*.jsonl."""
    rows = []
    for path in glob.glob(str(Path(results_dir) / "*" / "trials-*.jsonl")):
        bench = Path(path).parent.name
        with open(path) as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    r["benchmark"] = r.get("benchmark", bench)
                    rows.append(r)
    return rows


def aggregate(rows: list):
    """(by[bench][product][metric] -> [vals], failures[bench][product]).

    The raw primitive: error rows count as failures, non-error rows are
    flattened into metrics. Validity gating happens in summarize_rows (the
    published path); direct callers get unfiltered behavior."""
    from bench.core.measurement import metrics_for
    by = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    failures = defaultdict(lambda: defaultdict(int))
    for r in rows:
        if r.get("error"):
            failures[r["benchmark"]][r["product"]] += 1
            continue
        mm = metrics_for(r)
        for k, v in mm.items():
            if k.endswith("_all"):
                by[r["benchmark"]][r["product"]].setdefault(k, []).extend(v)
            else:
                by[r["benchmark"]][r["product"]][k].append(v)
    return by, failures


def summarize(by: dict, failures: dict, cfg: dict, excluded: dict | None = None,
              trials: dict | None = None) -> dict:
    """The summary model: per-benchmark stats, primary ranks, ts deltas,
    plus the validity-gate report (excluded counts + reasons, per-phase
    trial denominators) when provided."""
    out = {}
    # union: benchmarks with valid rows AND fully-excluded benchmarks (their
    # exclusion report must still reach the summary artifacts)
    for bench in sorted(set(by) | set(excluded or {}) | set(trials or {})):
        prods = by.get(bench) or {}
        primary, _ = primary_metric(bench) or (None, None)
        entry = {"products": {}, "primary": primary}
        for prod, metrics in prods.items():
            s = {}
            for k, vals in metrics.items():
                if k.endswith("_all"):
                    continue
                st = stats(vals)
                if st["n"]:
                    st["ci95_median"] = boot_ci_median(vals)
                    s[k] = st
            entry["products"][prod] = s
        # after the metrics loop so mixed products keep their failure count
        for p in failures.get(bench, {}):
            entry["products"].setdefault(p, {})["failures"] = failures[bench][p]
        if primary:
            p50s = {p: s.get(primary, {}).get("p50") for p, s in entry["products"].items()}
            entry["ranks"] = rank_products(p50s)
            entry["primary_p50s"] = {p: v for v, p in
                                     sorted([(v, p) for p, v in p50s.items() if v is not None])}
            entry["delta_vs_ts"] = delta_vs_baseline(p50s)
        if excluded and excluded.get(bench):
            entry["excluded"] = excluded[bench]
        if trials and trials.get(bench):
            entry["trials"] = trials[bench]
        out[bench] = entry
    return out


def summarize_rows(rows: list, cfg: dict, settle_rows: list | None = None) -> dict:
    """The shared stats model: {"summary": ..., "aa": ..., "settle": ...}.

    The strict validity gate runs first (analysis.validity.gate_rows):
    invalid rows never reach stats, ranks, or deltas. Published stats
    aggregate the gated published-phase rows only (``aa`` rows calibrate
    in the A/A section); excluded rows are reported with counts + reasons."""
    gate = cfg.get("gate_benchmarks") or {}
    settle_auth = settle_auth_products(settle_rows or [])
    valid, excluded = gate_rows(rows, settle_auth=settle_auth, gate=gate)
    published = [r for r in valid if not is_aa_phase(r)]
    by, _ = aggregate(published)
    # trial-error counts derived from the gate's exclusion reasons
    failures = defaultdict(lambda: defaultdict(int))
    for bench, prods in excluded.items():
        for prod, info in prods.items():
            n = sum(info["reasons"].get(reason, 0) for reason in ERROR_REASONS)
            if n:
                failures[bench][prod] = n
    # per-product per-phase trial denominators over the valid rows
    trials: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for r in valid:
        trials[r["benchmark"]][r["product"]][str(r.get("phase") or "")] += 1
    threshold = float(cfg.get("aa", {}).get("spread_threshold_pct", 10.0))
    settle = {prod: dict(info, auth_error=True) for prod, info in settle_auth.items()}
    return {"summary": summarize(by, failures, cfg, excluded=excluded, trials=trials),
            "aa": aa_validity(valid, threshold), "settle": settle}
