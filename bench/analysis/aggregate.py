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

from bench.analysis.aa_validation import aa_failing, aa_validity
from bench.analysis.rankings import delta_vs_baseline, rank_products
from bench.analysis.stats import boot_ci_median, stats
from bench.analysis.validity import (ERROR_REASONS, aa_primary_p50s, gate_rows,
                                     is_aa_phase, is_status_row,
                                     settle_auth_products, status_report)
from bench.core.measurement import (derived_primary, metrics_for,
                                          primary_metric)

#: the provenance label recorded for rows that predate run stamping
UNSTAMPED = "(unstamped)"


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
              trials: dict | None = None, aa_p50s: dict | None = None,
              drift_threshold_pct: float | None = None,
              aa_failing: dict | None = None, status: dict | None = None,
              comparability: dict | None = None, phase_p50s: dict | None = None,
              identity: dict | None = None, disclosures: dict | None = None,
              derived_aa_required: dict | None = None) -> dict:
    """The summary model: per-benchmark stats, primary ranks, ts deltas,
    plus the validity-gate report (excluded counts + reasons, per-phase
    trial denominators, engine status rows, comparability modes) when
    provided.

    Products with stability marks (A/A-to-wave drift over threshold, a
    failing A/A noise floor on the primary or a published declared
    metric, or ranked values that exist only through legacy-row
    derivation without an A/A calibration on the derived metric) are
    never ranked or delta'd; their stats stay visible and the marks land
    in ``entry["unstable"]``."""
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
            unstable = _stability_marks(bench, p50s, entry["products"], aa_p50s,
                                        drift_threshold_pct, aa_failing,
                                        derived_aa_required)
            if unstable:
                entry["unstable"] = unstable
                p50s = {p: v for p, v in p50s.items() if p not in unstable}
            entry["ranks"] = rank_products(p50s)
            entry["primary_p50s"] = {p: v for v, p in
                                     sorted([(v, p) for p, v in p50s.items() if v is not None])}
            entry["delta_vs_ts"] = delta_vs_baseline(p50s)
        if excluded and excluded.get(bench):
            entry["excluded"] = excluded[bench]
        if trials and trials.get(bench):
            entry["trials"] = trials[bench]
        if status and status.get(bench):
            entry["status"] = status[bench]
        if comparability and comparability.get(bench):
            entry["comparability"] = comparability[bench]
        if phase_p50s and phase_p50s.get(bench):
            entry["phase_p50s"] = phase_p50s[bench]
        if identity and identity.get(bench):
            entry["identity"] = identity[bench]
        if disclosures and disclosures.get(bench):
            entry["disclosures"] = disclosures[bench]
        out[bench] = entry
    return out


def _row_label(row: dict) -> str:
    """The campaign label on a row (unstamped rows name themselves)."""
    return str((row.get("run") or {}).get("label") or UNSTAMPED)


def _row_rev(row: dict) -> str:
    """The harness revision on a row (unstamped rows name themselves)."""
    return str((row.get("run") or {}).get("harness", {}).get("git_rev") or UNSTAMPED)


def _identity_report(published: list) -> dict:
    """Per benchmark: the run labels + harness revisions among the
    published rows, flagged when a tree mixes them (audit F7/F8: one
    canonical file mixed two deployed bundle versions)."""
    labels: dict = defaultdict(set)
    revs: dict = defaultdict(set)
    for r in published:
        labels[r["benchmark"]].add(_row_label(r))
        revs[r["benchmark"]].add(_row_rev(r))
    out = {}
    for bench in labels:
        entry = {"run_labels": sorted(labels[bench]),
                 "harness_revs": sorted(revs[bench])}
        if len(labels[bench]) > 1 or len(revs[bench]) > 1:
            entry["mixed"] = True
        out[bench] = entry
    return out


def _disclosure_report(published: list) -> dict:
    """Per (benchmark, product): row-level disclosures that qualify the
    measured numbers — onboarding dialogs auto-dismissed inside the
    measurement (audit F13) and readiness values carrying probe-grid
    quantization (audit F13's ~2s floor: now bounded and disclosed per
    row by record["probe"]["quantized_ms"])."""
    counts: dict = defaultdict(int)
    for r in published:
        if r.get("dialog_autodismissed"):
            counts[(r["benchmark"], r["product"], "dialog_autodismissed")] += 1
        if (r.get("probe") or {}).get("quantized_ms"):
            counts[(r["benchmark"], r["product"], "probe_quantized")] += 1
    out: dict = defaultdict(dict)
    for (bench, prod, kind), n in counts.items():
        out[bench].setdefault(prod, {})[kind] = n
    return {b: dict(p) for b, p in out.items()}


def _phase_p50s(published: list) -> dict:
    """Per benchmark: {product: {phase: primary p50}} — every denominator's
    own median, so pooled rows can never masquerade as one phase's value
    (audit F1). Read through metrics_for so legacy rows whose primary is
    derived at flattening report the same derived boundary the rankings
    use, never a silently absent phase median."""
    vals: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for r in published:
        primary, _ = primary_metric(r.get("benchmark")) or (None, None)
        if not primary:
            continue
        v = metrics_for(r).get(primary)
        if v is not None:
            vals[r["benchmark"]][r["product"]][str(r.get("phase") or "")].append(v)
    return {bench: {prod: {phase: stats(vs)["p50"]
                           for phase, vs in phases.items()}
                    for prod, phases in prods.items()}
            for bench, prods in vals.items()}


def _aa_coverage(rows: list) -> dict:
    """Per benchmark: the A/A calibration coverage — how many calibration
    rows exist (audit F11: the report must not claim A/A OK for benchmarks
    that never calibrated)."""
    counts: dict = defaultdict(int)
    trial_rows = [r for r in rows if not is_status_row(r)]
    for r in trial_rows:
        if is_aa_phase(r):
            counts[r.get("benchmark")] += 1
    return {bench: {"aa_rows": counts.get(bench, 0)} for bench in
            {r.get("benchmark") for r in trial_rows}}


def methodology_block(cfg: dict, phases: list | None) -> dict:
    """The self-describing aggregation rule stamped on every summary
    artifact (audit F1/F12): which phases were published, the gate that
    filtered them, where the numbers came from."""
    import time
    analyze = cfg.get("analyze") or {}
    return {"analyzed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "source_dir": str(analyze.get("results_dir") or ""),
            "published_phases": phases or ["all non-aa phases"],
            "aa_rows": "calibration only, never in published stats",
            "gate": "strict result-validity (bench.analysis.validity)",
            "denominators": "entry.trials per product per phase"}


def _stability_marks(bench: str, p50s: dict, entry_products: dict,
                     aa_p50s: dict | None, drift_threshold_pct: float | None,
                     aa_failing: dict | None,
                     derived_aa_required: dict | None = None) -> dict:
    """{product: {"aa_drift"?: {...}, "aa_spread"?: {...},
    "aa_missing_boundary"?: {...}}} — the stability marks that keep a
    product out of the rankings:

    - aa_drift: the primary p50 shifted between the A/A pass and the
      published waves beyond the drift threshold;
    - aa_spread: a calibrated A/A metric failed the noise floor (the
      primary, plus benchmark-declared aa_metrics when published);
    - aa_missing_boundary: the product's ranked values exist only through
      legacy-row derivation (rows predating the recorded metric) and the
      tree carries no A/A calibration on the derived boundary — derived
      numbers must never rank uncalibrated (the A/A rows' own raw
      timestamps calibrate it when present; no row rewrite is involved).
    """
    marks: dict = defaultdict(dict)
    if aa_p50s is not None:
        for product in (derived_aa_required or {}).get(bench, ()):
            if product in p50s and (bench, product) not in aa_p50s:
                marks[product]["aa_missing_boundary"] = {
                    "reason": "ranked value derived from legacy rows; "
                              "no A/A calibration on the derived primary"}
        if drift_threshold_pct is not None:
            for product, w1 in p50s.items():
                aa = aa_p50s.get((bench, product))
                if w1 and aa:
                    drift = abs(w1 - aa) / min(w1, aa) * 100.0
                    if drift > drift_threshold_pct:
                        marks[product]["aa_drift"] = {"aa_p50": aa, "w1_p50": w1,
                                                     "drift_pct": round(drift, 1)}
    for product, failing in (aa_failing or {}).get(bench, {}).items():
        published = {m: e for m, e in failing.items()
                    if m in (entry_products.get(product) or {})}
        if published:
            marks[product]["aa_spread"] = {"metrics": published}
    return dict(marks)


def summarize_rows(rows: list, cfg: dict, settle_rows: list | None = None,
                   phases: list | None = None) -> dict:
    """The shared stats model: {"summary": ..., "aa": ..., "settle": ...,
    "aa_coverage": ..., "methodology": ...}.

    Engine status rows (products that ran no trials) are split out first
    and reported as entry["status"] — not exclusions, not failures. The
    strict validity gate then runs (analysis.validity.gate_rows): invalid
    rows never reach stats, ranks, or deltas. Published stats aggregate
    the gated published-phase rows only (``aa`` rows calibrate in the A/A
    section); excluded rows are reported with counts + reasons.

    phases: the explicit published denominator (audit F1) — e.g.
    ["w1"]; None publishes every non-aa phase present. Per-phase trial
    counts and per-phase primary p50s label every pool, the run-identity
    report flags mixed trees (audit F7/F8), and row-level disclosures
    (dialogs, probe quantization) qualify the measured numbers."""
    gate = cfg.get("gate_benchmarks") or {}
    settle_auth = settle_auth_products(settle_rows or [])
    status = status_report(rows)
    trial_rows = [r for r in rows if not is_status_row(r)]
    valid, excluded = gate_rows(trial_rows, settle_auth=settle_auth, gate=gate)
    published = [r for r in valid if not is_aa_phase(r)]
    if phases is not None:
        published = [r for r in published if str(r.get("phase") or "") in phases]
    threshold = float(cfg.get("aa", {}).get("spread_threshold_pct", 10.0))
    drift_threshold = float(cfg.get("aa", {}).get("drift_threshold_pct", 10.0))
    aa_metrics = {name: meta.get("aa_metrics") for name, meta in gate.items()}
    aa = aa_validity(valid, threshold, aa_metrics)
    # products whose ranked primary exists only through legacy-row derivation:
    # ranking them additionally requires an A/A calibration on the derived
    # metric (core.measurement.derived_primary scopes which rows those are)
    derived_aa_required: dict = defaultdict(set)
    for r in published:
        if derived_primary(r):
            derived_aa_required[r["benchmark"]].add(r["product"])
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
    comparability: dict = defaultdict(dict)
    for r in valid:
        trials[r["benchmark"]][r["product"]][str(r.get("phase") or "")] += 1
        mode = r.get("comparability")
        if mode:
            comparability[r["benchmark"]].setdefault(r["product"], mode)
    settle = {prod: dict(info, auth_error=True) for prod, info in settle_auth.items()}
    return {"summary": summarize(by, failures, cfg, excluded=excluded, trials=trials,
                                 aa_p50s=aa_primary_p50s(valid),
                                 drift_threshold_pct=drift_threshold,
                                 aa_failing=aa_failing(aa),
                                 derived_aa_required=dict(derived_aa_required),
                                 status=status,
                                 comparability=dict(comparability),
                                 phase_p50s=_phase_p50s(published),
                                 identity=_identity_report(published),
                                 disclosures=_disclosure_report(published)),
            "aa": aa, "settle": settle,
            "aa_coverage": _aa_coverage(trial_rows),
            "methodology": methodology_block(cfg, phases)}
