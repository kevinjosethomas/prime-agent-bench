"""Trial-row aggregation into the shared summary model.

load_all reads every trials-*.jsonl under a results tree; aggregate groups
flattened metrics (core.measurement.metrics_for) by benchmark/product;
summarize attaches stats, ranks, and deltas; summarize_rows is the
Analyzer.compute_stats entry point.
"""
from __future__ import annotations

import glob
import json
from collections import defaultdict
from pathlib import Path

from bench.analysis.aa_validation import aa_validity
from bench.analysis.rankings import delta_vs_baseline, rank_products
from bench.analysis.stats import boot_ci_median, stats
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
    """(by[bench][product][metric] -> [vals], failures[bench][product])."""
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


def summarize(by: dict, failures: dict, cfg: dict) -> dict:
    """The summary model: per-benchmark stats, primary ranks, ts deltas."""
    out = {}
    for bench, prods in by.items():
        primary, _ = primary_metric(bench) or (None, None)
        entry = {"products": {}, "primary": primary}
        for p in failures.get(bench, {}):
            entry["products"].setdefault(p, {})["failures"] = failures[bench][p]
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
        if primary:
            p50s = {p: s.get(primary, {}).get("p50") for p, s in entry["products"].items()}
            entry["ranks"] = rank_products(p50s)
            entry["primary_p50s"] = {p: v for v, p in
                                     sorted([(v, p) for p, v in p50s.items() if v is not None])}
            entry["delta_vs_ts"] = delta_vs_baseline(p50s)
        out[bench] = entry
    return out


def summarize_rows(rows: list, cfg: dict) -> dict:
    """The shared stats model: {"summary": ..., "aa": ...}."""
    by, failures = aggregate(rows)
    threshold = float(cfg.get("aa", {}).get("spread_threshold_pct", 10.0))
    return {"summary": summarize(by, failures, cfg), "aa": aa_validity(rows, threshold)}
