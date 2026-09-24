"""The strict result-validity gate, regression-tested on captured fixtures.

Captured evidence under tests/fixtures/captured/ encodes the observed
failure classes: 120s probe-deadline session-open artifacts (the sentinel
wait burns the fixed 120s on products whose argv ignores the resume
fixture), the Codex 401 auth-error settle, A/A rows pooled into W1 stats,
scroll/typing rows without fixture confirmation, typing_ok=false rows,
validation-failed and debug/missing-metrics rows. The gate must keep
every one of them out of stats/rankings/deltas and report counts+reasons.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from bench.analysis.aggregate import load_all, summarize_rows
from bench.analysis.output.markdown import MarkdownAnalyzer
from bench.analysis.output.notion import NotionAnalyzer
from bench.analysis.validity import (classify_error, gate_rows, load_settle,
                                      row_exclusion, settle_auth_products)

FIXTURES = Path(__file__).parent / "fixtures" / "captured"
CFG = {"product_order": ["rust", "ts", "claude", "codex", "pi"],
       "display": {"rust": "Prime Agent Rust", "ts": "Prime Agent TS",
                   "claude": "Claude Code", "codex": "Codex CLI", "pi": "Pi Mono"},
       "aa": {"spread_threshold_pct": 10.0}}


def gate_map() -> dict:
    """The per-benchmark gate metadata cmd_analyze injects from the registry."""
    from bench.core.config import load_config
    from bench.core.registry import discover
    reg = discover(load_config(None))
    return {name: {"requires_fixture": b.requires_fixture,
                   "applicable_products": b.applicable_products,
                   "completeness_keys": tuple(b.completeness_keys),
                   "aa_metrics": tuple(b.aa_metrics)}
            for name, b in reg.benchmarks.items()}


@pytest.fixture(scope="module")
def model():
    rows = load_all(FIXTURES)
    settle_rows = load_settle(FIXTURES)
    cfg = dict(CFG, gate_benchmarks=gate_map())
    return summarize_rows(rows, cfg, settle_rows=settle_rows)


@pytest.fixture(scope="module")
def model_clean_settle():
    """The audited campaign's shape: settle.jsonl all-clean, codex routed
    through the real API (its 'settle' is the 401 error render)."""
    rows = load_all(FIXTURES)
    cfg = dict(CFG, gate_benchmarks=gate_map())
    return summarize_rows(rows, cfg, settle_rows=[])


def _reasons(model, bench, product):
    return (model["summary"][bench].get("excluded") or {}).get(product) or {}


# ---- gate metadata from the registry -----------------------------------------

def test_gate_map_reflects_registry():
    gate = gate_map()
    session = gate["session.cold_open_10mib"]
    assert session["applicable_products"] == ["rust", "ts"]          # RT-only
    assert session["requires_fixture"] == "session-10mib"
    assert gate["compare.scroll_typing"]["completeness_keys"] == ("typing_ok",)
    assert gate["compare.memory_idle_load"]["requires_fixture"] == "session-10mib"
    assert gate["compare.cold_start"]["applicable_products"] is None
    assert gate["compare.msg_send"]["aa_metrics"] == ("submit_to_settle_ms",)


# ---- probe-deadline rows ------------------------------------------------------

def test_classify_error_captures_deadline_and_auth():
    from bench.analysis.validity import auth_markers_in
    assert classify_error("TimeoutError: input never became ready in 120s (240 probes)") \
        == "probe_deadline"
    assert classify_error("TimeoutError: settle walk never reached ready; 401 Unauthorized") \
        == "auth_error"
    assert classify_error("stream error: Unexpected status 401 Unauthorized from ChatGPT auth") \
        == "auth_error"
    assert classify_error("TimeoutError: no first paint") == "error"
    # a timestamp like t=401.5s is not an HTTP 401
    assert classify_error("TimeoutError: no output after t=401.5s in 10s") == "error"
    assert auth_markers_in("Unexpected status 401 Unauthorized")


def test_probe_deadline_rows_excluded(model):
    reasons = _reasons(model, "session.cold_open_10mib", "rust")
    assert reasons["reasons"].get("probe_deadline") == 2
    assert "probe_deadline" not in model["summary"]["session.cold_open_10mib"]["primary_p50s"]


def test_session_open_120s_artifacts_never_ranked(model):
    """The fixed 120s sentinel wait burned on unresumed launches produced
    ~120s "cold opens"; they must not enter ranks or deltas."""
    entry = model["summary"]["session.cold_open_10mib"]
    p50s = entry["primary_p50s"]
    assert all(v < 90_000 for v in p50s.values())       # no 120s artifact ranked
    assert set(entry["ranks"]) <= {"rust", "ts"}       # RT-only benchmark
    # claude/codex fake rows: excluded as not_applicable, persisted
    assert _reasons(model, "session.cold_open_10mib", "claude")["reasons"]["not_applicable"] == 5
    assert _reasons(model, "session.cold_open_10mib", "codex")["reasons"]["not_applicable"] == 4
    # ts rows where the fixture resumed but the sentinel never rendered
    assert _reasons(model, "session.cold_open_10mib", "ts")["reasons"]["fixture_not_confirmed"] == 4


def test_session_open_historical_rows_need_clone_proof_to_rank(model):
    """The 2026-09-24 shared-golden mutation incident: rows carry the
    golden manifest hash but no proof of the bytes actually loaded, so
    pre-clone-era rows are unrankable — excluded LOUDLY with a visible
    reason (fixture_no_clone_evidence), never silently rewritten. Only
    rows with per-trial clone evidence rank on the completion boundary
    (spec §A primary launch_to_complete_ms); the boundary derivation
    itself stays covered by metrics_for (test_scenario_correctness) and
    the clone-proven synthetic rank test (test_fixture_integrity). The
    derived boundary's A/A-calibration requirement now gates only
    clone-proven rows — composed with this gate it is tested below
    (test_legacy_boundary_rows_require_aa_calibration_to_rank)."""
    entry = model["summary"]["session.cold_open_10mib"]
    assert entry["primary"] == "launch_to_complete_ms"
    assert entry["primary_p50s"] == {}
    assert entry.get("ranks") in (None, {})
    # the sentinel-passing historical rows are the loud exclusion class
    # (5 w1 + 8 aa for rust, 2 w1 for ts)
    assert _reasons(model, "session.cold_open_10mib", "rust")["reasons"] \
        ["fixture_no_clone_evidence"] == 13
    assert _reasons(model, "session.cold_open_10mib", "ts")["reasons"] \
        ["fixture_no_clone_evidence"] == 2


def test_legacy_boundary_rows_require_aa_calibration_to_rank():
    """The derived boundary may not rank uncalibrated: legacy rows (no
    recorded launch_to_complete_ms) rank only once an A/A pass calibrates
    the boundary; rows that record the metric (new waves) rank under the
    normal policy exactly as before. Every synthetic row carries per-trial
    clone proof (staged sha == golden sha), so the fixture byte-proof gate
    passes and the A/A calibration requirement is exactly what's under
    test."""
    cfg = dict(CFG, gate_benchmarks=gate_map())
    GOLD = "d" * 64

    def sess_row(product, trial, ready, sentinel, phase="w1", recorded=False):
        m = {"launch_to_ready_ms": ready, "launch_to_sentinel_ms": sentinel}
        if recorded:
            m["launch_to_complete_ms"] = max(ready, sentinel)
        return {"benchmark": "session.cold_open_10mib", "product": product,
                "phase": phase, "trial": trial, "metrics": m, "validated": True,
                "validation": {"sentinel": True, "echoed": True, "erased": True},
                "fixture": {"loaded": True, "sha256": GOLD,
                            "clone": {"sha256": GOLD}},
                "comparability": "equivalent"}

    legacy = [sess_row("rust", i, 9000.0 + i, 8000.0) for i in range(4)]
    entry = summarize_rows(legacy, cfg)["summary"]["session.cold_open_10mib"]
    # legacy-derived boundary, no A/A anywhere: unrankable, marked
    assert entry["ranks"] == {} and entry["primary_p50s"] == {}
    assert entry["unstable"]["rust"]["aa_missing_boundary"]
    # the same pool with an A/A pass on the derived boundary ranks
    calibrated = legacy + [sess_row("rust", i, 9000.0, 8000.0, phase="aa")
                           for i in range(6)]
    entry = summarize_rows(calibrated, cfg)["summary"]["session.cold_open_10mib"]
    assert entry["ranks"] == {"rust": 1}
    assert "unstable" not in entry
    # rows that record the boundary rank without the legacy requirement
    recorded = [sess_row("ts", i, 100.0, 90.0, recorded=True) for i in range(4)]
    entry = summarize_rows(recorded, cfg)["summary"]["session.cold_open_10mib"]
    assert entry["ranks"] == {"ts": 1}
    assert "unstable" not in entry


# ---- auth-error settle (Codex 401) -------------------------------------------

def test_settle_auth_error_excludes_product(model):
    """Healthy-looking codex rows are invalid: the settle evidence shows a
    401, so the template was baked unauthenticated."""
    assert model["settle"]["codex"]["auth_error"] is True
    assert "401" in model["settle"]["codex"]["markers"]
    entry = model["summary"]["compare.cold_start"]
    assert _reasons(model, "compare.cold_start", "codex")["reasons"]["settle_auth_error"] == 5
    assert "codex" not in entry["ranks"]
    assert "codex" not in entry["primary_p50s"]


def test_row_level_auth_error_excluded(model):
    assert _reasons(model, "compare.cold_start", "codex")["reasons"]["auth_error"] == 1


def test_settle_latest_record_wins():
    stale = [{"benchmark": "settle", "product": "codex",
              "error": "TimeoutError: 401 Unauthorized", "screen_tail": ""}]
    clean = [{"benchmark": "settle", "product": "codex", "error": None}]
    assert settle_auth_products(stale + clean) == {}      # re-settled clean
    assert "401" in settle_auth_products(clean + stale)["codex"]["markers"]
    assert settle_auth_products([]) == {}


def test_load_settle_missing_file(tmp_path):
    assert load_settle(tmp_path) == []


# ---- A/A vs W1 phase separation ----------------------------------------------

def test_aa_rows_never_pool_into_published_stats(model):
    entry = model["summary"]["compare.cold_start"]
    rust = entry["products"]["rust"]["launch_to_ready_ms"]
    assert rust["n"] == 5                                  # w1 only, not 15
    assert rust["p50"] == 1002.0                           # 900ms aa rows excluded
    assert entry["trials"]["rust"] == {"w1": 5, "aa": 10}  # labeled denominators
    assert entry["trials"]["ts"] == {"w1": 5}


def test_aa_calibrates_primary_and_declared_metrics(model):
    """msg_send A/A calibrates submit_to_ack_ms AND the declared settle
    metric (the old hardcoded launch_to_ready_ms left msg_send/daemon A/A
    absent, and settle was never calibrated)."""
    aa = model["aa"]
    assert "compare.msg_send/rust" in aa
    assert "compare.msg_send/rust/submit_to_settle_ms" in aa
    assert aa["compare.msg_send/rust"]["spread_pct"] == 10.7
    assert aa["compare.msg_send/rust"]["valid"] is False          # captured shape
    assert aa["compare.msg_send/rust/submit_to_settle_ms"]["valid"] is False
    assert aa["compare.msg_send/claude"]["valid"] is True
    # the captured session.cold_open AA rows would calibrate the derived
    # boundary through metrics_for, but they predate the per-trial clone
    # proof too, so the byte-proof gate excludes them (loudly, as
    # fixture_no_clone_evidence) before the A/A machinery ever sees them:
    # the historical tree calibrates nothing. The metrics_for reading path
    # stays proven by the clone-proven synthetic rows
    # (test_legacy_boundary_rows_require_aa_calibration_to_rank).
    assert "session.cold_open_10mib/rust" not in aa


# ---- fixture comparability ---------------------------------------------------

def test_unconfirmed_fixture_rows_never_ranked(model):
    """scroll/typing and memory rows carry no fixture-loaded evidence
    (competitors launched empty sessions); nothing ranks for them."""
    for bench in ("compare.scroll_typing", "compare.memory_idle_load"):
        entry = model["summary"][bench]
        assert entry["products"] == {}                    # nothing aggregated
        assert entry.get("ranks") in (None, {})
        excluded = entry["excluded"]
        assert sum(info["count"] for info in excluded.values()) > 0
    assert _reasons(model, "compare.scroll_typing", "rust")["reasons"]["fixture_not_confirmed"] == 4
    assert _reasons(model, "compare.memory_idle_load", "claude")["reasons"]["fixture_not_confirmed"] == 3


def test_completeness_keys_exclude_dropped_typing(model):
    """Historical captured rows cannot reach the completeness check at all:
    the two dropped-key ts rows have no per-trial clone proof, so they are
    excluded as fixture_no_clone_evidence first (the loaded-bytes proof
    precedes metric-level checks). The incomplete_measurement class stays
    proven by the clone-proven synthetic row in
    test_fixture_integrity.test_clone_proven_incomplete_row_excluded."""
    reasons = _reasons(model, "compare.scroll_typing", "ts")
    assert reasons["reasons"]["fixture_no_clone_evidence"] == 2


def test_validation_failed_excluded(model):
    reasons = _reasons(model, "compare.msg_send", "ts")
    assert reasons["reasons"]["validation_failed"] == 1
    valid = model["summary"]["compare.msg_send"]["products"]["ts"]["submit_to_ack_ms"]
    assert valid["n"] == 5


def test_debug_and_missing_metrics_excluded(model):
    reasons = _reasons(model, "compare.cold_start", "rust")
    assert reasons["reasons"]["debug_phase"] == 1
    assert reasons["reasons"]["missing_metrics"] == 1


# ---- row_exclusion precedence (unit) ------------------------------------------

def test_row_exclusion_precedence():
    gate = gate_map()
    GOLD = "d" * 64
    settle = {"codex": "401"}
    debug = {"benchmark": "compare.cold_start", "product": "rust", "phase": "debug-x"}
    assert row_exclusion(debug, settle, gate) == "debug_phase"
    na = {"benchmark": "session.cold_open_10mib", "product": "claude",
          "phase": "w1", "error": "boom"}
    assert row_exclusion(na, settle, gate) == "not_applicable"   # beats error
    err = {"benchmark": "compare.cold_start", "product": "codex", "phase": "w1",
           "error": "TimeoutError: input never became ready in 45s (90 probes)"}
    assert row_exclusion(err, settle, gate) == "probe_deadline"  # beats settle
    healthy = {"benchmark": "compare.cold_start", "product": "codex", "phase": "w1",
               "metrics": {"launch_to_ready_ms": 100.0}}
    assert row_exclusion(healthy, settle, gate) == "settle_auth_error"
    unconfirmed = {"benchmark": "compare.scroll_typing", "product": "rust",
                   "phase": "w1", "metrics": {"typing_ms": [1.0], "typing_ok": True},
                   "validated": False}
    assert row_exclusion(unconfirmed, {}, gate) == "fixture_not_confirmed"
    incomplete = {"benchmark": "compare.scroll_typing", "product": "ts",
                  "phase": "w1", "fixture": {"loaded": True, "sha256": GOLD,
                                             "clone": {"sha256": GOLD}},
                  "metrics": {"typing_ms": [1.0], "typing_ok": False},
                  "validated": True,
                  "validation": {"sentinel": True, "echoed": True, "erased": True}}
    assert row_exclusion(incomplete, {}, gate) == "incomplete_measurement"
    # fixture byte-proof precedence: clone sha != golden sha -> never ranked
    mismatch = {"benchmark": "compare.scroll_typing", "product": "ts",
                "phase": "w1", "fixture": {"loaded": True, "sha256": GOLD,
                                           "clone": {"sha256": "8c717..."}},
                "metrics": {"typing_ms": [1.0], "typing_ok": True},
                "validated": True,
                "validation": {"sentinel": True, "echoed": True, "erased": True}}
    assert row_exclusion(mismatch, {}, gate) == "fixture_hash_mismatch"
    # a fixture row with NO clone proof at all: the loud historical class
    no_evidence = {"benchmark": "compare.scroll_typing", "product": "ts",
                   "phase": "w1", "fixture": {"loaded": True, "sha256": GOLD},
                   "metrics": {"typing_ms": [1.0], "typing_ok": True},
                   "validated": True,
                   "validation": {"sentinel": True, "echoed": True, "erased": True}}
    assert row_exclusion(no_evidence, {}, gate) == "fixture_no_clone_evidence"
    # clone proof on a fixture benchmark + render proof + complete
    # evidence + metrics: no exclusion (proven rows rank)
    proven = {"benchmark": "compare.scroll_typing", "product": "ts",
              "phase": "w1", "fixture": {"loaded": True, "sha256": GOLD,
                                         "clone": {"sha256": GOLD}},
              "metrics": {"typing_ms": [1.0], "typing_ok": True},
              "validated": True,
              "validation": {"sentinel": True, "echoed": True, "erased": True}}
    assert row_exclusion(proven, {}, gate) is None
    vacuous = {"benchmark": "kernel.cold_start", "product": "rust", "phase": "w1",
               "metrics": {"submit_to_result_ms": 100.2}, "validated": True}
    assert row_exclusion(vacuous, {}, gate) == "no_validation_evidence"
    ok = {"benchmark": "compare.cold_start", "product": "rust", "phase": "w1",
          "metrics": {"launch_to_ready_ms": 100.0}, "validated": True,
          "validation": {"echoed": True, "erased": True}}
    assert row_exclusion(ok, {}, gate) is None


def test_gate_rows_counts_and_reasons():
    gate = gate_map()
    rows = [
        {"benchmark": "compare.cold_start", "product": "rust", "phase": "w1",
         "metrics": {"launch_to_ready_ms": 100.0}, "validated": True,
         "validation": {"echoed": True, "erased": True}},
        {"benchmark": "compare.cold_start", "product": "rust", "phase": "w1",
         "metrics": {}, "error": "TimeoutError: input never became ready in 45s (90 probes)"},
    ]
    valid, excluded = gate_rows(rows, settle_auth={}, gate=gate)
    assert len(valid) == 1
    assert excluded["compare.cold_start"]["rust"] == {"count": 1,
                                                       "reasons": {"probe_deadline": 1}}


# ---- AA-to-wave drift (stability) --------------------------------------------

def test_drift_gate_marks_unstable_never_ranks(model):
    """daemon.boot rust: A/A p50 ~46 vs W1 p50 ~220 (~4.8x pass-to-pass
    shift) -> marked unstable, excluded from ranks and deltas; ts (4%
    drift) still ranks."""
    entry = model["summary"]["daemon.boot"]
    unstable = entry["unstable"]
    assert "rust" in unstable and "ts" not in unstable
    assert unstable["rust"]["aa_drift"]["drift_pct"] > 300.0
    assert entry["ranks"].get("rust") is None
    assert "rust" not in entry["primary_p50s"]
    assert "rust" not in entry["delta_vs_ts"]
    assert entry["ranks"]["ts"] == 1
    # the unstable product's raw stats stay visible for inspection
    assert entry["products"]["rust"]["spawn_to_accept_ms"]["p50"] \
        == unstable["rust"]["aa_drift"]["w1_p50"]


def test_daemon_aa_calibrates_spawn_to_accept(model):
    """daemon.boot A/A exists on its primary metric (the audit found no
    tool-produced daemon A/A entries)."""
    assert "daemon.boot/rust" in model["aa"]


# ---- A/A noise floor enforcement ----------------------------------------------

def test_failing_aa_never_ranks(model):
    """The captured campaign: rust msg_send A/A ack spread 10.7% (fail) and
    settle spread far over; pi ack spread 12.5% (fail) — both must be out
    of the rankings; claude (0.7%) and ts (no A/A evidence) still rank."""
    entry = model["summary"]["compare.msg_send"]
    unstable = entry["unstable"]
    assert unstable["rust"]["aa_spread"]["metrics"]["submit_to_ack_ms"]["spread_pct"] == 10.7
    assert "submit_to_settle_ms" in unstable["rust"]["aa_spread"]["metrics"]
    assert unstable["pi"]["aa_spread"]["metrics"]["submit_to_ack_ms"]["spread_pct"] == 12.5
    assert "rust" not in entry["ranks"] and "pi" not in entry["ranks"]
    assert "rust" not in entry["primary_p50s"] and "pi" not in entry["primary_p50s"]
    assert "rust" not in entry["delta_vs_ts"]
    assert entry["ranks"] == {"claude": 1, "ts": 2}
    # the failing products' raw stats stay visible for inspection
    assert entry["products"]["rust"]["submit_to_ack_ms"]["p50"] == 84.0


def test_settle_aa_required_only_when_published():
    """A failing A/A on a declared metric that is NOT published must not
    suppress the product (the requirement is 'if settling published, AA
    settle must pass')."""
    cfg = dict(CFG, gate_benchmarks=gate_map())
    rows = []
    for i in range(6):          # waves: ack published, settle never measured
        rows.append({"benchmark": "compare.msg_send", "product": "rust", "phase": "w1",
                     "trial": i, "metrics": {"submit_to_ack_ms": 80.0 + i},
                     "validation": {"ack": True, "settle": True}, "validated": True,
                     "comparability": "equivalent"})
    for i in range(10):         # A/A: ack halves agree, settle halves diverge
        rows.append({"benchmark": "compare.msg_send", "product": "rust", "phase": "aa",
                     "trial": i,
                     "metrics": {"submit_to_ack_ms": 80.0 if i % 2 == 0 else 82.0,
                                 "submit_to_settle_ms": 900.0 if i % 2 == 0 else 300.0},
                     "validation": {"ack": True, "settle": True}, "validated": True,
                     "comparability": "equivalent"})
    entry = summarize_rows(rows, cfg)["summary"]["compare.msg_send"]
    assert "unstable" not in entry          # settle A/A failed but settle is not published
    assert entry["ranks"] == {"rust": 1}


# ---- real-api regime -----------------------------------------------------------

def test_real_api_regime_rows_never_ranked(model, model_clean_settle):
    """codex msg_send rows are routed through the real API (the settle
    detector fires on the 401 error render); cross-regime, never ranked.
    With a clean settle pass (the audited campaign's shape) they fall to
    real_api_regime; with a settle-auth failure, settle_auth_error —
    either way they never rank."""
    clean = model_clean_settle["summary"]["compare.msg_send"]
    assert _reasons(model_clean_settle, "compare.msg_send", "codex")["reasons"] \
        ["real_api_regime"] == 5
    assert "codex" not in clean["ranks"]
    assert "codex" not in clean["primary_p50s"]
    assert "14650.0" not in json.dumps(clean["products"])
    # and in the settle-401 tree the same rows are settle_auth_error
    assert _reasons(model, "compare.msg_send", "codex")["reasons"]["settle_auth_error"] == 5


# ---- universal validation evidence -------------------------------------------

def test_kernel_vacuous_validation_unrankable(model):
    """kernel.* rows carry validated=true with NO validation block (the
    benchmark never records completion evidence, so validate() passes
    vacuously): unrankable until in-scope completion validation lands.
    Rows that DO record evidence publish stats (kernel has no PRIMARY
    metric, so no ranks exist for it regardless)."""
    entry = model["summary"]["kernel.cold_start"]
    assert _reasons(model, "kernel.cold_start", "rust")["reasons"] \
        ["no_validation_evidence"] == 5
    assert "ranks" not in entry                       # no PRIMARY metric
    assert entry["products"]["rust"]["submit_to_result_ms"]["n"] == 3


def test_unvalidated_rows_excluded():
    """A non-error row without a validated verdict cannot certify a
    completed valid trial."""
    gate = gate_map()
    r = {"benchmark": "compare.cold_start", "product": "rust", "phase": "w1",
         "metrics": {"launch_to_ready_ms": 100.0}, "validation": {"echoed": True}}
    assert row_exclusion(r, {}, gate) == "unvalidated"


def test_status_rows_reported_not_excluded(model):
    """Engine status rows (products that ran no trials) are reported as
    entry["status"], never counted as exclusions, failures or trials."""
    session = model["summary"]["session.cold_open_10mib"]
    assert session["status"]["pi"]["status"] == "not_applicable"
    assert "pi" not in (session.get("excluded") or {})
    assert "pi" not in session.get("trials", {})
    assert "pi" not in session["products"]
    mem = model["summary"]["compare.memory_idle_load"]
    assert mem["status"]["pi"]["status"] == "not_comparable"
    assert mem["status"]["pi"]["comparability"] == "not_comparable"
    assert "pi" not in (mem.get("excluded") or {})


def test_comparability_modes_surfaced(model):
    """Measured rows carry comparability modes (equivalent/qualified); the
    summary surfaces them per product for the report. The session.*
    captured rows are all excluded now (no clone proof), so the session
    entry surfaces no comparability; the equivalent mode on a
    fixture-resumed benchmark is asserted by the clone-proven synthetic
    test (test_fixture_integrity.test_clone_proven_rows_rank)."""
    session = model["summary"]["session.cold_open_10mib"]
    assert session.get("comparability", {}) == {}
    assert model["summary"]["compare.msg_send"]["comparability"]["claude"] == "qualified"


# ---- artifacts report the gate ----------------------------------------------

def test_outputs_render_exclusions_and_denominators(model, model_clean_settle):
    md = MarkdownAnalyzer(dict(CFG, gate_benchmarks=gate_map())).format_output(model)
    assert "Excluded from rankings" in md
    assert "Status (no trials ran)" in md
    assert "not_comparable" in md
    assert "_Comparability: " in md
    assert "not_applicable=5" in md
    assert "settle_auth_error=5" in md
    assert "fixture_not_confirmed=4" in md
    md_clean = MarkdownAnalyzer(dict(CFG, gate_benchmarks=gate_map())).format_output(model_clean_settle)
    assert "real_api_regime=5" in md_clean
    assert "w1=5" in md and "aa=10" in md      # labeled denominators
    assert "(n5)" in md                        # per-metric sample size
    assert "Unstable (never ranked)" in md
    assert "aa_drift" in md and "aa_spread" in md
    assert "+373.7% drift" in md              # the daemon.boot rust drift
    assert "(10.7%)" in md                    # the msg_send rust A/A ack spread
    payload = json.loads(NotionAnalyzer(dict(CFG, gate_benchmarks=gate_map())).format_output(model))
    bullets = [b for b in payload["children"]
               if b["type"] == "bulleted_list_item"]
    assert any("excluded 5 trials (not_applicable=5)" in
               b["bulleted_list_item"]["rich_text"][0]["text"]["content"] for b in bullets)
    assert any("(n=5)" in b["bulleted_list_item"]["rich_text"][0]["text"]["content"]
               for b in bullets)


def test_end_to_end_analyze_on_captured_tree(tmp_path, capsys, monkeypatch):
    """The full cmd_analyze path (registry injection, settle loading, all
    three artifacts) over the captured tree."""
    from bench.cli import cmd_analyze
    results = tmp_path / "results"
    shutil.copytree(FIXTURES, results)
    cmd_analyze(type("Args", (), {"config": None, "results_dir": str(results),
                                   "phase": None})())
    out = capsys.readouterr().out
    assert "excluded from rankings" in out
    summary = json.loads((results / "summary.json").read_text())
    session = summary["summary"]["session.cold_open_10mib"]
    assert set(session["ranks"]) <= {"rust", "ts"}
    assert all(v < 90_000 for v in session["primary_p50s"].values())
    assert summary["settle"]["codex"]["auth_error"] is True
    # methodology provenance: the artifact states its own aggregation rule
    method = summary["methodology"]
    assert method["published_phases"] == ["all non-aa phases"]
    assert method["gate"].startswith("strict")
    assert "aa_coverage" in summary
    # captured rows carry no run stamp: a single unstamped identity, never mixed
    ident = summary["summary"]["compare.cold_start"]["identity"]
    assert ident["run_labels"] == ["(unstamped)"]
    assert not ident.get("mixed")
    md = (results / "summary.md").read_text()
    assert "Excluded from rankings" in md
    assert "Published phases:" in md
    notion_payload = json.loads((results / "summary.notion.json").read_text())
    assert any("excluded" in json.dumps(b) for b in notion_payload["children"])
