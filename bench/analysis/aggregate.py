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
              derived_aa_required: dict | None = None,
              aa_coverage: dict | None = None) -> dict:
    """The summary model: per-benchmark stats, primary ranks, ts deltas,
    plus the validity-gate report (excluded counts + reasons, per-phase
    trial denominators, engine status rows, comparability modes) when
    provided.

    Rank policy (aa_coverage supplied — the published path; direct
    callers without it keep the raw primitive): products with stability
    marks (A/A-to-wave drift over threshold, a failing A/A noise floor
    on the primary or a published declared metric) are never ranked or
    delta'd — marks land in ``entry["unstable"]``. Products whose
    published primary lacks the declared A/A calibration (``aa.trials``
    valid rows on the primary) are UNCALIBRATED, not unstable — no
    evidence vs failed evidence — and land in ``entry["uncalibrated"]``.
    Ranks themselves are a campaign decision: ``aa.required=false`` (the
    default) is validation-only — stats, marks and denominators, but
    ranks are never emitted; a publishable campaign declares
    ``aa.required=true`` + explicit ``aa.expected_products`` (the
    eligible cohort, global list or per-benchmark map — never inferred
    from rows) and ranks appear only when every expected product is
    present in the pool, A/A-calibrated and spread/drift-stable; any
    gap withholds the whole benchmark (``entry["ranks_withheld"]`` — no
    partial leaderboards)."""
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
                                        drift_threshold_pct, aa_failing)
            if unstable:
                entry["unstable"] = unstable
            entry["ranks"] = {}
            entry["primary_p50s"] = {}
            entry["delta_vs_ts"] = {}
            if aa_coverage is None:
                # raw primitive (no coverage supplied): unfiltered behavior
                pool = {p: v for p, v in p50s.items()
                        if v is not None and p not in unstable}
                entry["ranks"] = rank_products(pool)
                entry["primary_p50s"] = _ordered_p50s(pool)
                entry["delta_vs_ts"] = delta_vs_baseline(pool)
            else:
                policy = _aa_policy(bench, cfg)
                uncalibrated = _uncalibrated_marks(
                    bench, p50s, aa_coverage, policy["expected_trials"],
                    (derived_aa_required or {}).get(bench) or ())
                if uncalibrated:
                    entry["uncalibrated"] = uncalibrated
                published = {p: v for p, v in p50s.items() if v is not None}
                pool = {p: v for p, v in published.items()
                        if p not in unstable and p not in uncalibrated}
                if policy["required"]:
                    expected = policy["expected_products"] or []
                    pool = {p: v for p, v in pool.items() if p in expected}
                entry["primary_p50s"] = _ordered_p50s(pool)
                withheld = _rank_withholding(bench, policy, published,
                                             uncalibrated, unstable, cfg)
                if withheld is not None:
                    entry["ranks_withheld"] = withheld
                else:
                    entry["ranks"] = rank_products(pool)
                    entry["delta_vs_ts"] = delta_vs_baseline(pool)
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
    aa = cfg.get("aa") or {}
    rank_policy = ("validation-only (aa.required=false): ranks are never emitted"
                   if not aa.get("required") else
                   "strict (aa.required=true): ranks require the explicit "
                   "aa.expected_products cohort — every expected product "
                   "A/A-calibrated (aa.trials valid rows on the primary) "
                   "and spread/drift-stable, else the benchmark is withheld")
    return {"analyzed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "rank_policy": rank_policy,
            "source_dir": str(analyze.get("results_dir") or ""),
            "published_phases": phases or ["all non-aa phases"],
            "aa_rows": "calibration only, never in published stats",
            "gate": "strict result-validity (bench.analysis.validity)",
            "denominators": "entry.trials per product per phase",
            "fixture_proof": ("fixture benchmarks rank only rows carrying "
                              "per-trial clone evidence (fixture.clone.sha256 "
                              "== golden sha256, the bytes actually staged for "
                              "--resume); rows measured before the 2026-09-24 "
                              "per-trial clone fix (the historical campaign "
                              "trees, e.g. the 820 campaign) carry no such "
                              "proof and are excluded as "
                              "fixture_no_clone_evidence / "
                              "fixture_hash_mismatch — loudly, never silently")}


def _ordered_p50s(pool: dict) -> dict:
    """{product: p50} ordered by ascending p50 (the rank pool's shape)."""
    return {p: v for v, p in sorted([(v, p) for p, v in pool.items()])}


def _stability_marks(bench: str, p50s: dict, entry_products: dict,
                     aa_p50s: dict | None, drift_threshold_pct: float | None,
                     aa_failing: dict | None) -> dict:
    """{product: {"aa_drift"?: {...}, "aa_spread"?: {...}}} — the STABILITY
    marks: measured calibration that FAILED quality, keeping a product
    out of the rankings:

    - aa_drift: the primary p50 shifted between the A/A pass and the
      published waves beyond the drift threshold;
    - aa_spread: a calibrated A/A metric failed the noise floor (the
      primary, plus benchmark-declared aa_metrics when published).

    A missing or partial A/A pass is a different defect — no evidence,
    not failed evidence — and is marked uncalibrated (``uncalibrated``),
    never here."""
    marks: dict = defaultdict(dict)
    if aa_p50s is not None and drift_threshold_pct is not None:
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


def _aa_policy(bench: str, cfg: dict) -> dict:
    """The rank policy for one benchmark, resolved from the declared aa
    config: required (strict campaign vs validation-only smoke), the
    expected valid A/A row count per product (``aa.trials``), and the
    explicit eligible cohort (``aa.expected_products`` — global list or
    per-benchmark map). The cohort is NEVER inferred from rows: a
    selected product that produced zero rows must stay detectable as
    incomplete, and rows cannot reveal what the campaign selected."""
    aa = cfg.get("aa") or {}
    declared = aa.get("expected_products")
    expected = declared.get(bench) if isinstance(declared, dict) else declared
    return {"required": bool(aa.get("required")),
            "expected_trials": int(aa.get("trials") or 10),
            "expected_products": list(expected) if expected else None}


def _aa_primary_coverage(valid: list) -> dict:
    """{(benchmark, product): n} — the gate-valid A/A rows carrying the
    benchmark's PRIMARY metric, read through metrics_for (the same
    flattening the published stats use, so legacy rows derive the same
    boundary they rank on; fresh rows carry the recorded metric). Only
    ``aa``-phase rows calibrate — phase identity is the pass's boundary,
    published rows never masquerade as a calibration."""
    counts: dict = defaultdict(int)
    for r in valid:
        if not is_aa_phase(r):
            continue
        primary, _ = primary_metric(r.get("benchmark")) or (None, None)
        if primary and metrics_for(r).get(primary) is not None:
            counts[(r["benchmark"], r["product"])] += 1
    return dict(counts)


def _uncalibrated_marks(bench: str, p50s: dict, coverage: dict,
                        expected_trials: int, derived_products) -> dict:
    """{product: {"reason", "aa_valid", "aa_expected"}} for every product
    whose published primary p50 carries no complete A/A calibration —
    UNCALIBRATED, distinct from unstable (no evidence vs failed
    evidence). Missing (0 valid rows) and partial (below the declared
    ``aa.trials``) both keep the product out of the ranks; stats stay
    visible. Products ranked only through legacy-row derivation say so
    in the reason (the derived boundary calibrates from the A/A rows'
    own timestamps when present)."""
    out = {}
    for product, p50 in p50s.items():
        if p50 is None:
            continue
        n = coverage.get((bench, product), 0)
        if n >= expected_trials:
            continue
        reason = ("no A/A calibration rows on the primary metric" if n == 0
                  else f"partial A/A calibration ({n}/{expected_trials} valid rows)")
        if product in derived_products:
            reason += "; ranked values derive from legacy rows"
        out[product] = {"reason": reason, "aa_valid": n,
                        "aa_expected": expected_trials}
    return out


def _rank_withholding(bench: str, policy: dict, published: dict,
                     uncalibrated: dict, unstable: dict, cfg: dict) -> dict | None:
    """Why this benchmark's ranks are withheld, or None when the strict
    campaign's cohort is complete and ranks may be emitted.

    - validation_only: aa.required=false — the smoke default; analysis is
      validation-only and ranks are NEVER emitted (no partial
      leaderboards from uncalibrated trees).
    - missing_expected_products: strict campaign without an explicit
      aa.expected_products declaration for this benchmark — the eligible
      cohort is never inferred from rows.
    - incomplete_cohort: an expected product is unsupported by the
      benchmark's applicability, absent from the published pool (zero
      valid primary rows), uncalibrated (missing/partial A/A), or
      unstable (failed spread/drift) — any gap withholds the WHOLE
      benchmark's ranks and deltas; a complete comparison needs an
      equivalent stable cohort, never a lone survivor."""
    if not policy["required"]:
        return {"reason": "validation_only",
                "detail": "aa.required=false: validation-only analysis — "
                          "ranks are never emitted"}
    expected = policy["expected_products"]
    if not expected:
        return {"reason": "missing_expected_products",
                "detail": "strict campaign (aa.required=true) requires explicit "
                          "aa.expected_products for every ranked benchmark; "
                          "none declared for this one"}
    blockers: dict = {}
    applicable = (cfg.get("gate_benchmarks") or {}).get(bench, {}) \
        .get("applicable_products")
    if applicable:
        unsupported = sorted(p for p in expected if p not in applicable)
        if unsupported:
            blockers["unsupported"] = unsupported
    absent = sorted(p for p in expected if p not in published)
    if absent:
        blockers["absent"] = absent
    cohort_uncalibrated = sorted(p for p in expected if p in uncalibrated)
    if cohort_uncalibrated:
        blockers["uncalibrated"] = cohort_uncalibrated
    cohort_unstable = sorted(p for p in expected if p in unstable)
    if cohort_unstable:
        blockers["unstable"] = cohort_unstable
    if blockers:
        blockers["reason"] = "incomplete_cohort"
        blockers["expected"] = list(expected)
    return blockers or None


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
    # the A/A primary coverage behind every rank decision: gate-valid
    # aa-phase rows carrying the primary (analysis gate only — the raw
    # rows are historical evidence and are never rewritten)
    aa_coverage = _aa_primary_coverage(valid)
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
                                 aa_coverage=aa_coverage,
                                 status=status,
                                 comparability=dict(comparability),
                                 phase_p50s=_phase_p50s(published),
                                 identity=_identity_report(published),
                                 disclosures=_disclosure_report(published)),
            "aa": aa, "settle": settle,
            "aa_coverage": _aa_coverage(trial_rows),
            "methodology": methodology_block(cfg, phases)}
