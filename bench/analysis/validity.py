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
- ``validation_failed``: the trial completed but its validation evidence
  failed (probe echoed but not erased; ack or settle missing, ...).
- ``incomplete_measurement``: a declared completeness metric was falsy
  (e.g. scroll_typing ``typing_ok`` — a dropped key truncates the typing
  sequence).
- ``missing_metrics``: the trial produced no measurable metrics.
- ``debug_phase``: debug evidence rows never enter published stats.

Phase rule: ``aa`` rows feed the A/A calibration section only; published
stats aggregate the remaining non-debug phases, with per-product
per-phase trial counts (``trials``) labeling every denominator.

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

from bench.core.measurement import metrics_for

AUTH_ERROR_MARKERS = ("unauthorized", "invalid api key", "not logged in",
                      "please log in", "authentication required", "login required")
# HTTP 401 as its own token, never a numeric substring like "t=401.5s"
AUTH_ERROR_CODE_PATTERNS = (r"\b401\b(?![.\d])",)
PROBE_DEADLINE_MARKERS = ("input never became ready",)
#: exclusion reasons that denote a trial-level error (vs environment/phase)
ERROR_REASONS = ("error", "auth_error", "probe_deadline")


def auth_markers_in(text: str) -> list:
    """The auth-failure markers found in one evidence string."""
    low = text.lower()
    return [m for m in AUTH_ERROR_MARKERS if m in low] \
        + [p for p in AUTH_ERROR_CODE_PATTERNS if re.search(p, low)]


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


def row_exclusion(row: dict, settle_auth: dict, gate: dict) -> str | None:
    """The reason code excluding this row from rankings, or None if valid.

    Precedence: phase evidence first, then the product-level causes, then
    the row-level evidence (most-specific cause wins)."""
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
    if meta.get("requires_fixture") and not fixture_confirmed(row):
        return "fixture_not_confirmed"
    if row.get("validated") is False:
        return "validation_failed"
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
