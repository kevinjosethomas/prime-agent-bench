"""Analysis: aggregation, ranks, deltas, A/A validation, output artifacts."""
from __future__ import annotations

import json

from bench.analysis.aa_validation import aa_validity
from bench.analysis.aggregate import aggregate, load_all, summarize, summarize_rows
from bench.analysis.output.json import JsonAnalyzer
from bench.analysis.output.markdown import MarkdownAnalyzer
from bench.analysis.output.notion import NotionAnalyzer
from bench.analysis.rankings import delta_vs_baseline, rank_products
from bench.analysis.stats import boot_ci_median, pct, stats

CFG = {"product_order": ["rust", "ts"], "display": {"rust": "Prime Agent Rust",
        "ts": "Prime Agent TS"}, "aa": {"spread_threshold_pct": 10.0}}


def _row(bench, product, trial, ready_ms, phase="w1", error=None):
    row = {"benchmark": bench, "product": product, "trial": trial, "phase": phase,
           "metrics": {"launch_to_ready_ms": ready_ms},
           # the validity gate requires a certified trial: a validation
           # block plus an explicit validated verdict
           "validation": {"echoed": True, "erased": True}, "validated": True}
    if error:
        row["error"] = error
    return row


def test_pct_and_stats():
    vals = [10, 20, 30, 40, 50]
    assert pct(vals, 50) == 30
    assert stats(vals)["n"] == 5
    assert stats(vals)["p50"] == 30
    ci = boot_ci_median(vals)
    assert ci[0] <= 30 <= ci[1]


def test_rank_and_delta():
    p50s = {"rust": 100.0, "ts": 200.0, "codex": 150.0}
    assert rank_products(p50s) == {"rust": 1, "codex": 2, "ts": 3}
    assert delta_vs_baseline(p50s)["ts"]["abs"] == 0.0
    assert delta_vs_baseline(p50s)["rust"]["pct"] == -50.0


def test_aggregate_summarize_ranks():
    rows = [_row("compare.cold_start", "rust", i, 100.0 + i) for i in range(5)]
    rows += [_row("compare.cold_start", "ts", i, 200.0 + i) for i in range(5)]
    rows += [_row("compare.cold_start", "codex", 0, None, error="boom")]
    by, failures = aggregate(rows)
    assert failures["compare.cold_start"]["codex"] == 1
    summary = summarize(by, failures, CFG)
    entry = summary["compare.cold_start"]
    assert entry["primary"] == "launch_to_ready_ms"
    assert entry["ranks"] == {"rust": 1, "ts": 2}
    assert entry["delta_vs_ts"]["rust"]["pct"] == -49.5  # p50 102 vs 202
    assert entry["products"]["codex"]["failures"] == 1


def test_aa_validity():
    # halves are the even/odd trial indices (interleaved in time)
    rows = [_row("compare.cold_start", "rust", i,
                 100.0 if i % 2 == 0 else 250.0, phase="aa")
            for i in range(12)]
    out = aa_validity(rows, threshold_pct=10.0)
    assert out["compare.cold_start/rust"]["valid"] is False
    assert out["compare.cold_start/rust"]["spread_pct"] == 150.0
    rows2 = [_row("compare.warm_start", "ts", i,
                  100.0 if i % 2 == 0 else 105.0, phase="aa")
             for i in range(12)]
    out2 = aa_validity(rows2)
    assert out2["compare.warm_start/ts"]["valid"] is True


def test_load_all_and_outputs(tmp_path):
    d = tmp_path / "compare.cold_start"
    d.mkdir(parents=True)
    with (d / "trials-w1.jsonl").open("w") as f:
        for row in [_row("compare.cold_start", "rust", 0, 100.0),
                    _row("compare.cold_start", "ts", 0, 120.0)]:
            f.write(json.dumps(row) + "\n")
    rows = load_all(tmp_path)
    assert len(rows) == 2
    stats_model = summarize_rows(rows, CFG)
    assert JsonAnalyzer(CFG).format_output(stats_model)
    md = MarkdownAnalyzer(CFG).format_output(stats_model)
    assert "| Prime Agent Rust |" in md
    assert "## compare.cold_start" in md
    payload = json.loads(NotionAnalyzer(CFG).format_output(stats_model))
    assert payload["children"][0]["type"] == "heading_1"
    kinds = {b["type"] for b in payload["children"]}
    assert "heading_2" in kinds and "bulleted_list_item" in kinds
