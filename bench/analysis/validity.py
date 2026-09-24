"""Strict result-validity gate: only completed, valid trials are ranked.

Rankings and deltas are publishable only over trials that completed with
valid evidence. The gate classifies every trial row into (valid, reason)
and the summary reports excluded counts + reasons per benchmark/product.
Captured failure classes it excludes (reason codes):

- ``probe_deadline``: the interactive-ready probe hit its deadline
  ("input never became ready in 120s") — a harness-deadline artifact, not
  a product measurement (session.cold_open_10mib on products whose argv
  ignores the resume fixture paints in ~0.25s, then the sentinel wait
  burns the fixed 120s before the probe).
- ``settle_auth_error``: the product's latest settle record failed with
  an auth error (the observed case: Codex 401 with stale ChatGPT auth).
  The template was baked unauthenticated, so every measured trial of that
  product is invalid — even healthy-looking rows.
- ``auth_error``: the trial's own error shows an auth failure.
- ``not_applicable``: the benchmark does not apply to the product
  (session.*/daemon.*/kernel.* are Prime-Agent-only). Captured rows from
  unsupported combinations are persisted as excluded, never fake-ranked.
- ``fixture_not_confirmed``: a fixture-requiring benchmark without
  positive fixture-loaded evidence (``record["fixture"]["loaded"]`` or
  the session-open tail-sentinel render proof) — e.g. scroll/typing and
  memory rows measured against an empty session while Rust/TS resumed
  the 10MiB fixture.
- ``fixture_hash_mismatch``: the row's per-trial clone proof contradicts
  the golden manifest — ``fixture.clone.sha256`` (the hash of the bytes
  actually staged for the product's --resume) differs from the golden
  ``fixture.sha256``. Never ranked: the measured number describes loaded
  bytes that are provably not the golden corpus (the 2026-09-24
  shared-golden mutation incident class).
- ``fixture_no_clone_evidence``: a fixture-requiring row with no
  per-trial clone proof on the row at all. Historical rows measured
  before the per-trial clone staging landed are exactly this class:
  unrankable because nothing proves which bytes were loaded, and
  excluded LOUDLY (visible reason + count) — never silently, never
  overwritten.
- ``validation_failed``: the trial completed but its validation evidence
  failed (probe echoed but not erased; ack or settle missing, ...).
- ``unvalidated``: no validation verdict at all (``validated`` absent on
  a non-error row) — a completed valid trial must be certified.
- ``no_validation_evidence``: ``validated=true`` without a validation
  block — the vacuous certification (kernel.* and daemon.boot rows have
  no ``record["validation"]``, so their ``validate()`` passes vacuously).
  Such benchmarks stay unrankable until they record real completion
  evidence in their own scope.
- ``real_api_regime``: msg_send rows routed through the real API
  (``msg_routing == "real-api"``) while the benchmark's peers measure the
  scripted mock; the settle detector fires on any screen growth, so the
  observed Codex 401 auth-error render certifies as a "settle" —
  cross-regime values never rank.
- ``incomplete_measurement``: a declared completeness metric was falsy
  (e.g. scroll_typing ``typing_ok`` — a dropped key truncates the typing
  sequence).
- ``missing_metrics``: the trial produced no measurable metrics.
- ``debug_phase``: debug evidence rows never enter published stats.

Phase rule: ``aa`` rows feed the A/A calibration section only; published
stats aggregate the remaining non-debug phases, with per-product
per-phase trial counts (``trials``) labeling every denominator.

Stability rule: a product with a failing A/A calibration (noise-floor
spread over ``aa.spread_threshold_pct`` on the primary metric or on a
benchmark-declared ``aa_metrics`` metric whenever it is published) or a
primary-p50 drift between the A/A pass and the published waves over
``aa.drift_threshold_pct`` is marked unstable (``summary.unstable``:
``aa_spread`` / ``aa_drift``) and never ranked or delta'd — the captured
cases: msg_send rust ack A/A 10.7% and pi 12.5% still ranked before;
daemon.boot rust AA 46.1 vs W1 219.6, a ~4.8x pass-to-pass shift that
pooled medians hid.

Status rows (engine declarations for products that ran no trials:
``{"status": "not_applicable"|"not_comparable", "reason": ...,
"trial": null}``) are NOT exclusions and NOT failures; they are reported
as ``entry["status"]`` per product. Measured rows may carry a
``comparability`` mode (equivalent/qualified) surfaced in
``entry["comparability"]`` — evidence for the report, never gated on.

Per-benchmark gate metadata (fixture requirement, applicability,
completeness keys) comes from the registry via ``cfg["gate_benchmarks"]``
(injected by ``bench.cli.cmd_analyze``): {name: {"requires_fixture": ...,
"applicable_products": ..., "completeness_keys": [...]}}. Without the
map the universal checks (error / settle / validation / metrics / phase)
still apply; the per-benchmark checks need the map.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from bench.analysis.stats import stats
from bench.core.measurement import metrics_for, primary_metric

#: (label, pattern) auth-failure markers; the label is what reports show.
#: HTTP 401 is its own token so a timestamp like "t=401.5s" never matches.
AUTH_ERROR_MARKERS = (
    ("401", re.compile(r"\b401\b(?![.\d])")),
    ("unauthorized", re.compile(r"unauthorized")),
    ("invalid api key", re.compile(r"invalid api key")),
    ("not logged in", re.compile(r"not logged in")),
    ("please log in", re.compile(r"please log in")),
    ("authentication required", re.compile(r"authentication required")),
    ("login required", re.compile(r"login required")),
)
PROBE_DEADLINE_MARKERS = ("input never became ready",)
#: exclusion reasons that denote a trial-level error (vs environment/phase)
ERROR_REASONS = ("error", "auth_error", "probe_deadline")


def auth_markers_in(text: str) -> list:
    """The auth-failure marker labels found in one evidence string."""
    low = text.lower()
    return [label for label, pattern in AUTH_ERROR_MARKERS if pattern.search(low)]


def classify_error(error: str) -> str:
    """Categorize one trial error string: auth_error | probe_deadline | error."""
    if auth_markers_in(error):
        return "auth_error"
    if any(m in error.lower() for m in PROBE_DEADLINE_MARKERS):
        return "probe_deadline"
    return "error"


def load_settle(results_dir) -> list:
    """Every settle record from <results_dir>/settle.jsonl (missing -> [])."""
    path = Path(results_dir) / "settle.jsonl"
    if not path.exists():
        return []
    rows = []
    with open(path) as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def settle_auth_products(settle_rows: list) -> dict:
    """{product: {"error": snippet, "markers": [...]}} for products whose
    LATEST settle record failed with an auth error. The settle JSONL is
    append-only, so the last record per product is the current template
    state; a later clean settle clears the exclusion. The snippet is the
    settle record's error field; the markers (e.g. 401) are what matched,
    often visible only in the screen tail."""
    latest: dict = {}
    for rec in settle_rows:
        product = rec.get("product")
        if product:
            latest[product] = rec
    out = {}
    for product, rec in latest.items():
        hay = " ".join(str(rec.get(k) or "") for k in ("error", "screen_tail"))
        markers = auth_markers_in(hay)
        if markers:
            out[product] = {"error": str(rec.get("error") or "auth error"),
                            "markers": markers}
    return out


def fixture_confirmed(row: dict) -> bool:
    """Positive fixture-loaded evidence: the explicit fixture block, or
    the session-open tail-sentinel render proof (the sentinel pair only
    renders when the fixture transcript was resumed)."""
    if (row.get("fixture") or {}).get("loaded"):
        return True
    return bool((row.get("validation") or {}).get("sentinel"))


def fixture_clone_proven(row: dict) -> str:
    """The byte-proof verdict for one fixture row: ``proven`` |
    ``mismatch`` | ``no_evidence``.

    ``proven`` requires BOTH hashes on the row and their equality: the
    golden manifest sha256 (``fixture.sha256``, the versioned corpus
    identity) AND the actual staged-clone pre-launch sha256
    (``fixture.clone.sha256``). A row with no clone block predates the
    per-trial clone staging and proves nothing about its loaded bytes."""
    fixture = row.get("fixture") or {}
    pre_sha = (fixture.get("clone") or {}).get("sha256")
    if not pre_sha:
        return "no_evidence"
    golden_sha = fixture.get("sha256")
    if not golden_sha or pre_sha != golden_sha:
        return "mismatch"
    return "proven"


def row_exclusion(row: dict, settle_auth: dict, gate: dict) -> str | None:
    """The reason code excluding this row from rankings, or None if valid.

    Precedence: phase evidence first, then benchmark applicability, then
    the trial's own error, then the product-level causes (settle auth,
    routing regime), then the row-level evidence (fixture, validation,
    completeness, metrics)."""
    phase = str(row.get("phase") or "")
    if phase.startswith("debug"):
        return "debug_phase"
    meta = gate.get(row.get("benchmark")) or {}
    applicable = meta.get("applicable_products")
    if applicable and row.get("product") not in applicable:
        return "not_applicable"
    if row.get("error"):
        return classify_error(str(row["error"]))
    if row.get("product") in settle_auth:
        return "settle_auth_error"
    if row.get("msg_routing") == "real-api":
        return "real_api_regime"
    if meta.get("requires_fixture"):
        if not fixture_confirmed(row):
            return "fixture_not_confirmed"
        proven = fixture_clone_proven(row)
        if proven == "mismatch":
            return "fixture_hash_mismatch"
        if proven == "no_evidence":
            return "fixture_no_clone_evidence"
    if row.get("validated") is False:
        return "validation_failed"
    if row.get("validated") is not True:
        return "unvalidated"
    if not (row.get("validation") or {}):
        return "no_validation_evidence"
    for key in meta.get("completeness_keys") or ():
        if not (row.get("metrics") or {}).get(key):
            return "incomplete_measurement"
    if not metrics_for(row):
        return "missing_metrics"
    return None


def gate_rows(rows: list, settle_auth: dict | None = None,
              gate: dict | None = None) -> tuple[list, dict]:
    """Split rows into (valid, excluded-report).

    ``valid`` keeps every phase's valid rows (the caller separates the
    published phases from the ``aa`` calibration rows). ``excluded`` is
    {benchmark: {product: {"count": n, "reasons": {code: n}}}}."""
    settle_auth = settle_auth or {}
    gate = gate or {}
    valid = []
    counts: dict = defaultdict(lambda: defaultdict(lambda: [0, defaultdict(int)]))
    for row in rows:
        reason = row_exclusion(row, settle_auth, gate)
        if reason is None:
            valid.append(row)
            continue
        entry = counts[row.get("benchmark")][row.get("product")]
        entry[0] += 1
        entry[1][reason] += 1
    excluded = {bench: {prod: {"count": c, "reasons": dict(reasons)}
                         for prod, (c, reasons) in prods.items()}
                for bench, prods in counts.items()}
    return valid, excluded


def is_aa_phase(row: dict) -> bool:
    """Whether the row belongs to the A/A calibration pass."""
    return str(row.get("phase") or "") == "aa"


def is_status_row(row: dict) -> bool:
    """Whether the row is an engine status declaration (a product that ran
    no trials), not a trial: {"status": ..., "reason": ..., trial: null}."""
    return bool(row.get("status")) and not (row.get("metrics") or {})


def status_report(rows: list) -> dict:
    """{benchmark: {product: {status, reason, comparability}}} from the
    engine status rows (one per product that ran no trials)."""
    out: dict = defaultdict(dict)
    for row in rows:
        if is_status_row(row):
            out[row.get("benchmark")][row.get("product")] = {
                "status": row.get("status"),
                "reason": row.get("reason"),
                "comparability": row.get("comparability")}
    return dict(out)


def aa_primary_p50s(rows: list) -> dict:
    """{(benchmark, product): p50} over the rows' A/A pass, on each
    benchmark's PRIMARY metric (the same metric the waves are ranked on),
    read through metrics_for so legacy rows whose primary is derived at
    flattening (session.cold_open's completion boundary) calibrate too."""
    vals: dict = defaultdict(list)
    for row in rows:
        if not is_aa_phase(row):
            continue
        primary, _ = primary_metric(row.get("benchmark")) or (None, None)
        if not primary:
            continue
        value = metrics_for(row).get(primary)
        if value is not None:
            vals[(row["benchmark"], row["product"])].append(value)
    return {key: stats(v)["p50"] for key, v in vals.items() if v}
