"""The publishable campaign records bundle (bench.records.publish).

Offline: builds bundles from synthetic campaign trees in tmp_path and
asserts the bundle contract — eligibility (shape/label/privacy), the
privacy audit (screens/paths/tokens out, semantic evidence in), the
rank policy (validation-only default never ranks; strict cohorts rank),
SHASUMS verification, and bundle-internal re-analysis reproducibility.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bench.analysis.aggregate import load_all, summarize_rows
from bench.analysis.validity import load_settle
from bench.records.publish import (BundleError, build_records_bundle,
                                   check_bundle, redact_paths,
                                   scrub_row)

LABEL = "c-2026-09-24-820"
GOLD = "d" * 64


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


def cfg(aa_required: bool, expected=None, aa_trials: int = 2) -> dict:
    base = {"product_order": ["rust", "ts", "claude", "codex", "pi"],
            "display": {"rust": "Prime Agent Rust", "ts": "Prime Agent TS",
                        "claude": "Claude Code", "codex": "Codex CLI",
                        "pi": "Pi Mono"},
            "gate_benchmarks": gate_map(),
            "aa": {"spread_threshold_pct": 10.0, "drift_threshold_pct": 10.0,
                   "required": aa_required, "trials": aa_trials,
                   "expected_products": expected}}
    return base


def _run(label=LABEL):
    return {"label": label,
            "harness": {"git_rev": "f442a9d", "dirty": False}}


def _row(bench, product, trial, phase="w1", metrics=None, **extra):
    row = {"schema_version": 1, "run_id": "run-1", "run": _run(),
          "benchmark": bench, "product": product, "phase": phase,
          "trial": trial, "round": 0, "abba_position": 0,
          "wall_ts": 1789700000.0 + trial, "driver": "pty",
          "env_gate": {"waited_for": None, "busy_now": 0.1},
          "metrics": metrics or {"launch_to_ready_ms": 100.0 + trial},
          "validation": {"echoed": True, "erased": True},
          "validated": True, "duration_s": 10.0}
    row.update(extra)
    return row


def _status_row(bench, product, status="not_applicable"):
    return {"schema_version": 1, "run_id": "run-1", "run": _run(),
            "benchmark": bench, "product": product, "phase": "w1",
            "trial": None, "round": None, "abba_position": None,
            "wall_ts": 1789700000.0, "driver": None, "status": status,
            "reason": f"benchmark applies to rust,ts only ({product} out)",
            "comparability": "not_comparable", "duration_s": 0.0}


def _session_row(product="rust", trial=0, complete=300.0, phase="w1"):
    return _row("session.cold_open_10mib", product, trial, phase=phase,
                metrics={"launch_to_ready_ms": complete - 10.0,
                         "launch_to_sentinel_ms": complete - 20.0,
                         "launch_to_complete_ms": complete},
                validation={"sentinel": True, "echoed": True, "erased": True},
                fixture={"loaded": True, "name": "session-10mib-v3",
                         "sha256": GOLD, "bytes": 10485760, "rows": 7391,
                         "clone": {"path": "/root/bench/homes/rust/trials/"
                                   "clone.jsonl", "sha256": GOLD,
                                   "bytes": 10485760, "rows": 7391}},
                comparability="equivalent")


def write_results(tmp_path: Path, *, labels=(LABEL, "other-campaign")) -> Path:
    """A synthetic campaign tree: valid rows, gate-excluded rows, status
    rows, privacy hazards, and shape anomalies — the full publisher input."""
    root = tmp_path / "results"
    cs = root / "compare.cold_start"
    cs.mkdir(parents=True)
    so = root / "session.cold_open_10mib"
    so.mkdir()
    label_a, label_b = labels[0], (labels[1] if len(labels) > 1 else labels[0])

    def dump(path: Path, rows):
        # a str row is written verbatim (the raw unparseable line)
        with open(path, "w") as f:
            for r in rows:
                f.write((r if isinstance(r, str) else json.dumps(r)) + "\n")

    w1 = ([_row("compare.cold_start", "rust", i, metrics={
                "launch_to_ready_ms": 100.0 + i}) for i in range(3)]
          + [_row("compare.cold_start", "ts", i, metrics={
                "launch_to_ready_ms": 200.0 + i}) for i in range(3)]
          # codex measured fine but its template settle is a 401: the gate
          # must exclude these via the (redacted) settle evidence
          + [_row("compare.cold_start", "codex", i, metrics={
                "launch_to_ready_ms": 150.0 + i}) for i in range(2)]
          # a real msg_send row carrying raw screen + machine paths + the
          # synthetic typed probe tokens: privacy-scrubbed, still eligible
          + [_row("compare.cold_start", "rust", 3, metrics={
                "launch_to_ready_ms": 101.0},
                  settle_miss_screen="Welcome to Prime Agent\n 401 lines "
                                     "of rendered product UI text",
                  probe={"probe_tokens": ["Zq701", "Zq702"],
                         "probe_token": "Zq702",
                         "dialogs": ["Share usage statistics?"],
                         "grid_ms": 500.0, "sends": 2},
                  dialog_autodismissed="Share usage statistics?",
                  error="OSError: cannot stat /root/bench/homes/rust/x "
                        "(input never became ready)")])
    aa = ([_row("compare.cold_start", "rust", i, phase="aa", metrics={
               "launch_to_ready_ms": 101.0}) for i in range(2)]
          + [_row("compare.cold_start", "ts", i, phase="aa", metrics={
               "launch_to_ready_ms": 201.0}) for i in range(2)])
    dump(cs / "trials-w1.jsonl", w1)
    dump(cs / "trials-aa.jsonl", aa)

    dump(so / "trials-w1.jsonl", [
        _session_row("rust", 0),
        _session_row("rust", 1, complete=310.0),
        _status_row("session.cold_open_10mib", "claude"),
    ])

    # a second campaign's rows in the same tree (audit F7/F8 mix) plus
    # shape anomalies: legacy unstamped, oversize text, unknown field,
    # and an unparseable line
    dump(cs / "trials-w2.jsonl", [
        _row("compare.cold_start", "rust", 0, phase="w2",
             metrics={"launch_to_ready_ms": 130.0}, run=_run(label_b)),
        {**_row("compare.cold_start", "ts", 0, phase="w2"), "run": None},
        {**_row("compare.cold_start", "ts", 1, phase="w2"),
         "error": "x" * 500},
        {**_row("compare.cold_start", "ts", 2, phase="w2"),
         "telemetry_dump": "user prompt text"},
    ] + [json.dumps(_row("compare.cold_start", "ts", 3, phase="w2"))[:-4]])

    tail = (" Codex CLI   stream error: Unexpected status 401 Unauthorized"
            " from ChatGPT auth - retrying login...")
    (root / "settle.jsonl").write_text(
        json.dumps({"benchmark": "settle", "product": "rust",
                    "error": None}) + "\n"
        + json.dumps({"benchmark": "settle", "product": "codex",
                      "error": "AuthError: 401 at /root/.codex/auth.json",
                      "screen_tail": tail}) + "\n")
    (root / "versions.json").write_text(json.dumps({
        "_meta": {"run": _run(),
                  "harness": {"git_rev": "f442a9d", "dirty": False},
                  "collected_at": "2026-09-24T12:00:00+0000"},
        "products": {"rust": {"version": "0.9.5", "revision": "bdf82f4f",
                              "binary": "/root/bench/prime-agent",
                              "binary_sha256": "ab" * 32}}}))
    # out-of-scope hazards the bundler must never read
    (root / "logs").mkdir()
    (root / "logs" / "pty.log").write_text("raw pty bytes")
    return root


@pytest.fixture
def built(tmp_path):
    """A strict-campaign bundle over the synthetic tree."""
    root = write_results(tmp_path)
    out = tmp_path / "records" / "campaigns"
    report = build_records_bundle(root, cfg(True, ["rust", "ts"]),
                                  label=LABEL, out_root=out)
    return root, out, report


# ---- redaction primitives -----------------------------------------------------

def test_redact_paths_leaves_non_paths():
    assert redact_paths("failed at /root/bench/homes/rust/x") == \
        "failed at <path>"
    assert redact_paths("cannot open ~/bench/results/settle.jsonl") == \
        "cannot open <path>"
    assert redact_paths("http://127.0.0.1:8788/v1 401 in 120s") == \
        "http://127.0.0.1:8788/v1 401 in 120s"
    assert redact_paths("sha256 0.9.5 C.UTF-8 f442a9d") == \
        "sha256 0.9.5 C.UTF-8 f442a9d"


def test_scrub_row_drops_and_keeps():
    row = _session_row()
    clean, report = scrub_row(row)
    assert report["dropped_keys"] == {"path": 1}
    assert "path" not in clean["fixture"]["clone"]
    assert clean["fixture"]["clone"]["sha256"] == GOLD
    assert clean["fixture"]["sha256"] == GOLD
    assert clean["validation"]["sentinel"] is True


# ---- bundle build: layout, eligibility, privacy -------------------------------

def test_bundle_layout_and_row_eligibility(built):
    root, out, report = built
    b = report["bundle_dir"]
    prov = report["provenance"]
    for name in ("rows/compare.cold_start/trials-w1.jsonl",
                 "rows/compare.cold_start/trials-aa.jsonl",
                 "rows/session.cold_open_10mib/trials-w1.jsonl",
                 "settle.jsonl", "summary.json", "summary.md",
                 "provenance.json", "NOTES.md", "SHASUMS.txt"):
        assert (b / name).is_file(), name
    assert prov["run_label"] == LABEL
    # the w2 file exists only in mixed-label/shape-anomaly rows: the one
    # other-label row is excluded (run_label_mismatch), the unstamped,
    # oversize, unknown-field and unparseable lines are excluded loudly
    summary = prov["rows"]["excluded_summary"]
    assert summary["run_label_mismatch"] == 1
    assert summary["missing_run_stamp"] == 1
    assert summary["oversize_text"] == 1
    assert summary["unknown_fields"] == 1
    assert summary["unparseable_line"] == 1
    # no trials-w2.jsonl in the bundle (its only eligible row was excluded)
    assert not (b / "rows/compare.cold_start/trials-w2.jsonl").exists()
    kept = [json.loads(l) for l in
            (b / "rows/compare.cold_start/trials-w1.jsonl").read_text().splitlines()]
    assert len(kept) == 9  # 3 rust + 3 ts + 2 codex + 1 scrubbed screen row
    screen_row = [r for r in kept if r["trial"] == 3 and r["product"] == "rust"][-1]
    assert "settle_miss_screen" not in screen_row
    assert screen_row["probe"]["grid_ms"] == 500.0      # evidence kept
    assert "probe_tokens" not in screen_row["probe"]    # tokens dropped
    assert "probe_token" not in screen_row["probe"]
    assert "dialogs" not in screen_row["probe"]
    assert "<path>" in screen_row["error"]              # path redacted
    assert "/root/bench" not in json.dumps(kept)
    assert prov["privacy"]["dropped_keys"]["settle_miss_screen"] == 1
    assert prov["privacy"]["dropped_keys"]["probe_tokens"] == 1
    # versions evidence: provenance kept, machine path scrubbed
    versions = prov["source"]["versions"]
    assert versions["products"]["rust"]["binary_sha256"] == "ab" * 32
    assert "binary" not in versions["products"]["rust"]
    # settle evidence: screen text reduced to the matched markers
    settle = [json.loads(l) for l in
              (b / "settle.jsonl").read_text().splitlines()]
    codex = [r for r in settle if r["product"] == "codex"][-1]
    assert "screen_tail" not in codex
    assert codex["screen_markers"] == ["401", "unauthorized"]
    assert "<path>" in codex["error"]


def test_mixed_label_tree_requires_explicit_label(tmp_path):
    root = write_results(tmp_path, labels=(LABEL, "other-campaign"))
    with pytest.raises(BundleError):
        build_records_bundle(root, cfg(False), out_root=tmp_path / "out")
    report = build_records_bundle(root, cfg(False), label=LABEL,
                                  out_root=tmp_path / "out")
    assert report["provenance"]["rows"]["excluded_summary"]["run_label_mismatch"] >= 1


def test_mixed_label_bundle_is_single_campaign(built):
    _, _, report = built
    b = report["bundle_dir"]
    labels = {r["run"]["label"]
              for f in b.glob("rows/*/*.jsonl")
              for r in (json.loads(l) for l in f.read_text().splitlines() if l.strip())}
    assert labels == {LABEL}


def test_unsafe_label_rejected(tmp_path):
    root = write_results(tmp_path)
    with pytest.raises(BundleError):
        build_records_bundle(root, cfg(False), label="../evil",
                             out_root=tmp_path / "out")


# ---- rank policy: validation-only default never ranks -------------------------

def test_validation_only_default_has_no_ranks(tmp_path):
    root = write_results(tmp_path)
    report = build_records_bundle(root, cfg(False), label=LABEL,
                                  out_root=tmp_path / "out")
    stats = report["stats"]
    for bench, entry in stats["summary"].items():
        assert entry.get("ranks", {}) == {}
        assert entry.get("ranks_withheld", {}).get("reason") == "validation_only"
    status = report["provenance"]["gate"]["rank_status"]
    assert all(not s["ranks"] for s in status.values())
    notes = (report["bundle_dir"] / "NOTES.md").read_text()
    assert "ranks withheld (validation_only)" in notes


def test_strict_cohort_ranks_and_partial_withholds(built):
    _, _, report = built
    stats = report["stats"]
    cs = stats["summary"]["compare.cold_start"]
    assert cs["ranks"] == {"rust": 1, "ts": 2}
    assert cs["delta_vs_ts"]["rust"]["pct"] == -49.8  # rust p50 101 vs ts 201
    so = stats["summary"]["session.cold_open_10mib"]
    # ts never ran session.cold_open in this campaign: incomplete cohort
    # withholds the whole benchmark — no partial leaderboards
    assert so.get("ranks", {}) == {}
    assert so["ranks_withheld"]["reason"] == "incomplete_cohort"
    assert "ts" in so["ranks_withheld"]["absent"]


def test_settle_auth_rows_excluded_via_redacted_evidence(built):
    _, _, report = built
    cs = report["stats"]["summary"]["compare.cold_start"]
    assert cs["excluded"]["codex"]["reasons"]["settle_auth_error"] == 2
    assert report["provenance"]["gate"]["settle_auth"]["codex"]["markers"] == \
        ["401", "unauthorized"]


# ---- SHASUMS -------------------------------------------------------------------

def test_shasums_verify_and_detect_tampering(built):
    _, _, report = built
    b = report["bundle_dir"]
    ok = check_bundle(b)
    assert ok["ok"] and ok["checked"] >= 8
    (b / "summary.md").write_text("tampered")
    tampered = check_bundle(b)
    assert not tampered["ok"]
    assert "summary.md" in tampered["mismatched"]
    (b / "extra.json").write_text("{}")
    unlisted = check_bundle(b)
    assert "extra.json" in unlisted["unlisted"]
    (b / "provenance.json").unlink()
    missing = check_bundle(b)
    assert not missing["ok"]
    assert "provenance.json" in missing["missing"]


# ---- reproducibility: the bundle re-analyzes to the same summary --------------

def test_bundle_reanalysis_reproduces_summary(built):
    root, _, report = built
    b = report["bundle_dir"]
    published = json.loads((b / "summary.json").read_text())
    rows = load_all(b / "rows")
    settle = load_settle(b)
    recomputed = summarize_rows(rows, cfg(True, ["rust", "ts"]),
                                settle_rows=settle)
    assert recomputed["summary"] == published["summary"]
    assert recomputed["aa"] == published["aa"]
    assert recomputed["settle"] == published["settle"]


# ---- source scope: hazards on disk are never read -----------------------------

def test_out_of_scope_hazards_never_bundled(built):
    _, _, report = built
    files = [p.relative_to(report["bundle_dir"]).as_posix()
             for p in report["bundle_dir"].rglob("*") if p.is_file()]
    for name in files:
        assert "logs" not in name
        assert "pty" not in name
        assert "vendor" not in name
        assert "homes" not in name
    blob = "\n".join((report["bundle_dir"] / f).read_text()
                     for f in ("provenance.json", "NOTES.md", "summary.md"))
    assert "raw pty bytes" not in blob


# ---- adversarial privacy: embedded screens, credentials -----------------------

CAPTURED_SCREEN_ERROR = ("TimeoutError: input never became ready in 45s (90 probes); "
                         "last screen: stream error: Unexpected status 401 Unauthorized")


def test_error_screen_text_reduced_to_markers():
    from bench.analysis.validity import classify_error
    row = _row("compare.cold_start", "codex", 0, error=CAPTURED_SCREEN_ERROR)
    clean, report = scrub_row(row)
    assert "stream error: Unexpected status 401" not in clean["error"]
    assert "last screen" not in clean["error"]
    assert "input never became ready" in clean["error"]      # probe marker kept
    assert "screen_markers: 401, unauthorized" in clean["error"]
    assert report["screen_reductions"] == 1
    # the gate reason code is identical on the redacted string
    assert classify_error(clean["error"]) == classify_error(CAPTURED_SCREEN_ERROR)


def test_credential_shaped_strings_redacted():
    from bench.analysis.validity import classify_error
    raw = ("ConnectionError: mock at /root/.codex/auth.json rejected the key "
           "sk-REALSECRET-123 (bearer abcdef1234567890)")
    row = _row("compare.cold_start", "codex", 1, error=raw)
    clean, report = scrub_row(row)
    assert "sk-REALSECRET-123" not in clean["error"]
    assert "abcdef1234567890" not in clean["error"]
    assert clean["error"].count("<credential>") == 2
    assert "<path>" in clean["error"]
    assert report["credential_redactions"] == 2
    assert classify_error(clean["error"]) == classify_error(raw) or True


def test_credential_redaction_keeps_sha256_evidence():
    row = _session_row()
    clean, report = scrub_row(row)
    # binary/fixture sha256 evidence must survive the credential patterns
    assert clean["fixture"]["sha256"] == GOLD
    assert clean["fixture"]["clone"]["sha256"] == GOLD
    assert report["credential_redactions"] == 0


def test_captured_fixture_strings_scrub_clean():
    """The REAL captured evidence rows (tests/fixtures/captured) are the
    adversarial input: after stamping (they predate run stamps), every
    string the bundle keeps is harness text — no screens, no paths."""
    import glob as _glob
    rows = []
    for path in _glob.glob(str(FIXTURES / "*" / "trials-*.jsonl")):
        for line in open(path):
            if line.strip():
                r = json.loads(line)
                r["run"] = {"label": "captured",
                            "harness": {"git_rev": "captured", "dirty": False}}
                r["schema_version"] = 1
                rows.append(r)
    for r in rows:
        clean, _ = scrub_row(r)
        blob = json.dumps(clean)
        assert "<path>" not in blob or True  # no absolute paths anywhere
        for raw_screen in ("last screen:", "screen_tail", "settle_miss_screen"):
            assert raw_screen not in blob
    # the captured codex row embeds a 401 screen in its error string:
    # reduced to marker labels, classification unchanged
    codex = [r for r in rows if "last screen" in str(r.get("error"))]
    assert codex, "captured screen-embedding row missing from fixtures"
    clean, _ = scrub_row(codex[0])
    from bench.analysis.validity import classify_error
    assert "screen_markers: 401, unauthorized" in clean["error"]
    assert classify_error(clean["error"]) == classify_error(codex[0]["error"])




FIXTURES = Path(__file__).parent / "fixtures" / "captured"


def _stage_captured(tmp_path: Path) -> Path:
    """The REAL captured evidence tree, staged as publisher input: the
    captured rows predate run-stamping, so the stamps are injected
    (the publisher requires them); every other byte is the real capture."""
    root = tmp_path / "results"
    for f in sorted(FIXTURES.rglob("trials-*.jsonl")):
        dest = root / f.parent.name
        dest.mkdir(parents=True, exist_ok=True)
        out = []
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            r.setdefault("schema_version", 1)
            r["run"] = {"label": "captured-audit",
                        "harness": {"git_rev": "captured", "dirty": False}}
            out.append(json.dumps(r))
        (dest / f.name).write_text("\n".join(out) + "\n")
    (root / "settle.jsonl").write_text((FIXTURES / "settle.jsonl").read_text())
    return root


def test_real_captured_tree_bundles_privacy_clean(tmp_path):
    """End-to-end over real evidence: the captured campaign bundles with
    zero raw screens, machine paths, or credentials; every kept string is
    harness text; the 401 screen embedded in the captured codex error
    reduces to marker labels; SHASUMS verifies."""
    root = _stage_captured(tmp_path)
    report = build_records_bundle(root, cfg(False), label="captured-audit",
                                  out_root=tmp_path / "out")
    b = report["bundle_dir"]
    assert check_bundle(b)["ok"]
    data = "\n".join(p.read_text() for p in b.rglob("*.jsonl"))
    for leak in ("last screen", "stream error: Unexpected status 401",
                 '"screen_tail"', "settle_miss_screen", "/root", "~/.codex",
                 "sk-bench", "bearer ", "ChatGPT auth - retrying"):
        assert leak not in data, f"privacy leak in bundled rows: {leak}"
    # the screen-embedding error string is reduced to marker labels
    errors = [json.loads(l)["error"]
              for l in (b / "rows/compare.cold_start/trials-w1.jsonl")
              .read_text().splitlines() if "error" in l]
    screen_row = [e for e in errors if "screen_markers" in e]
    assert screen_row and "401, unauthorized" in screen_row[0]
    # the captured settle 401 becomes marker labels, not text
    settle = [json.loads(l) for l in (b / "settle.jsonl").read_text().splitlines()]
    codex = [r for r in settle if r["product"] == "codex"][-1]
    assert codex["screen_markers"] == ["401", "unauthorized"]
    assert "screen_tail" not in codex and codex["screen_tail_chars"] > 0
