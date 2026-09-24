"""Provenance and methodology gates (audit F1/F7/F8/F9/F10/F11/F13).

Run identity on every row, phase-explicit denominators, mixed-identity
trees flagged instead of silently aggregated, A/A coverage surfaced (no
calibration claimed where none ran), the versions.json provenance stamp,
and the secret-free vendor redaction.
"""
from __future__ import annotations

import json
import shutil
import tarfile
from pathlib import Path

from bench.analysis.aggregate import (UNSTAMPED, load_all, summarize_rows)
from bench.analysis.validity import load_settle

FIXTURES = Path(__file__).parent / "fixtures" / "captured"
CFG = {"product_order": ["rust", "ts", "claude", "codex", "pi"],
       "display": {"rust": "Prime Agent Rust", "ts": "Prime Agent TS",
                   "claude": "Claude Code", "codex": "Codex CLI", "pi": "Pi Mono"},
       "aa": {"spread_threshold_pct": 10.0, "drift_threshold_pct": 10.0}}


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


def _model(rows, phases=None, settle_rows=None):
    cfg = dict(CFG, gate_benchmarks=gate_map(),
               analyze={"results_dir": "results", "phases": phases})
    return summarize_rows(rows, cfg, settle_rows=settle_rows or [], phases=phases)


def _row(bench, product, trial, ready_ms, phase="w1", label="run-A", rev="abc123",
         dialog=None, quantized=None):
    row = {"benchmark": bench, "product": product, "trial": trial, "phase": phase,
           "metrics": {"launch_to_ready_ms": ready_ms},
           "validation": {"echoed": True, "erased": True}, "validated": True,
           "run": {"label": label, "harness": {"git_rev": rev}}}
    if dialog:
        row["dialog_autodismissed"] = dialog
    if quantized is not None:
        row["probe"] = {"quantized_ms": quantized}
    return row


def test_phase_filter_publishes_only_the_named_phases():
    """Audit F1's tooling fix: `bench analyze --phase w1` fixes the
    denominator; a second wave's rows must never pool into it."""
    rows = ([_row("compare.cold_start", "rust", i, 100.0 + i, phase="w1")
             for i in range(4)]
            + [_row("compare.cold_start", "rust", i, 900.0 + i, phase="w2")
               for i in range(4)])
    pooled = _model(rows)
    assert pooled["summary"]["compare.cold_start"]["products"]["rust"]["launch_to_ready_ms"]["n"] == 8
    w1 = _model(rows, phases=["w1"])
    entry = w1["summary"]["compare.cold_start"]
    assert entry["products"]["rust"]["launch_to_ready_ms"]["n"] == 4
    assert entry["products"]["rust"]["launch_to_ready_ms"]["p50"] == 102.0
    # per-phase p50s label every pool in scope: the filter scope shows w1,
    # the unfiltered model labels both pools that would silently pool
    assert entry["phase_p50s"]["rust"] == {"w1": 102.0}
    assert pooled["summary"]["compare.cold_start"]["phase_p50s"]["rust"] == {
        "w1": 102.0, "w2": 902.0}
    # the methodology block names the denominator it was produced by
    assert w1["methodology"]["published_phases"] == ["w1"]


def test_aa_rows_never_publish_even_with_phase_filter():
    rows = ([_row("compare.cold_start", "rust", i, 100.0, phase="aa", label="cal")
             for i in range(4)]
            + [_row("compare.cold_start", "rust", i, 150.0, phase="w1", label="wave")
               for i in range(4)])
    stats = _model(rows, phases=["w1"])
    rust = stats["summary"]["compare.cold_start"]["products"]["rust"]
    assert rust["launch_to_ready_ms"]["n"] == 4
    # the aa rows still calibrate
    assert stats["aa_coverage"]["compare.cold_start"]["aa_rows"] == 4


def test_mixed_identity_tree_is_flagged_never_silent():
    """Audit F7/F8: one canonical tree mixed two deployed bundle versions;
    the analysis must flag it loudly instead of aggregating silently."""
    rows = ([_row("compare.cold_start", "rust", i, 100.0, label="20260924-0805",
                  rev="8313fe4") for i in range(3)]
            + [_row("compare.cold_start", "rust", i, 100.0, label="20260924-1509",
                    rev="b04cb71b") for i in range(3)])
    stats = _model(rows)
    ident = stats["summary"]["compare.cold_start"]["identity"]
    assert ident["mixed"] is True
    assert ident["run_labels"] == ["20260924-0805", "20260924-1509"]
    assert ident["harness_revs"] == ["8313fe4", "b04cb71b"]


def test_single_identity_tree_not_flagged():
    rows = [_row("compare.cold_start", "rust", i, 100.0, label="one-run", rev="r1")
            for i in range(3)]
    stats = _model(rows)
    ident = stats["summary"]["compare.cold_start"]["identity"]
    assert not ident.get("mixed")
    assert ident["run_labels"] == ["one-run"]


def test_unstamped_rows_are_labeled_not_mixed():
    """Captured historical rows carry no run stamp: they are labeled
    (unstamped) — one identity, never a false mixed flag."""
    rows = [_row("compare.cold_start", "rust", i, 100.0, label=None, rev=None)
            for i in range(3)]
    for r in rows:
        r["run"] = {}
    stats = _model(rows)
    ident = stats["summary"]["compare.cold_start"]["identity"]
    assert ident["run_labels"] == [UNSTAMPED]
    assert not ident.get("mixed")


def test_disclosures_surface_dialogs_and_probe_quantization():
    """Audit F13: onboarding-dialog auto-dismissals inside measured trials
    and readiness values carrying probe-grid quantization are disclosed
    per product, never silent environment noise."""
    rows = ([_row("compare.cold_start", "rust", 0, 100.0, dialog="Share agent traces…",
                  quantized=50.0)]
            + [_row("compare.cold_start", "rust", i, 100.0) for i in range(1, 4)])
    stats = _model(rows)
    disc = stats["summary"]["compare.cold_start"]["disclosures"]["rust"]
    assert disc == {"dialog_autodismissed": 1, "probe_quantized": 1}
    # a row with no disclosures adds nothing (never noise)
    clean = _model([_row("compare.cold_start", "rust", i, 100.0) for i in range(2)])
    assert not (clean["summary"]["compare.cold_start"].get("disclosures") or {})


def test_aa_coverage_names_uncalibrated_benchmarks():
    """Audit F11: the report must never claim A/A OK where no calibration
    rows exist (the doc's install/daemon "<6% OK" with no tool data)."""
    rows = load_all(FIXTURES)
    stats = _model(rows)
    coverage = stats["aa_coverage"]
    assert coverage["compare.cold_start"]["aa_rows"] > 0
    # the captured tree's benchmarks that ran no A/A pass are named
    uncalibrated = sorted(b for b, c in coverage.items() if not c["aa_rows"])
    assert "compare.scroll_typing" in uncalibrated
    assert "compare.memory_idle_load" in uncalibrated
    # the markdown renders the coverage line so absence is visible
    from bench.analysis.output.markdown import MarkdownAnalyzer
    cfg = dict(CFG, gate_benchmarks=gate_map(),
               analyze={"results_dir": "results", "phases": None})
    md = MarkdownAnalyzer(cfg).format_output(stats)
    assert "A/A coverage:" in md
    assert "compare.scroll_typing" in md


def test_captured_tree_runs_clean_through_the_provenance_model():
    """The captured campaign tree end-to-end: the model produces the
    provenance blocks without excluding anything new."""
    rows = load_all(FIXTURES)
    stats = _model(rows, settle_rows=load_settle(FIXTURES))
    assert stats["methodology"]["published_phases"] == ["all non-aa phases"]
    assert stats["aa_coverage"]
    for entry in stats["summary"].values():
        ident = entry.get("identity") or {}
        assert not ident.get("mixed"), ident
        for prod, kinds in (entry.get("disclosures") or {}).items():
            assert isinstance(kinds, dict) and kinds


def test_versions_meta_stamp_and_compare_unwrap(tmp_path):
    """Audit F10: versions.json carries a provenance _meta (collecting run
    + harness revision); `bench compare` unwraps it without rendering it
    as a bogus product."""
    from bench.drivers.compare import compare_runs, format_markdown
    run = tmp_path / "run"
    run.mkdir()
    versions = {"_meta": {"run": {"label": "run-X"},
                          "harness": {"git_rev": "deadbeef" * 5},
                          "collected_at": "2026-09-24T16:03:44Z"},
                "products": {"rust": {"version": "0.9.5", "revision": "abc",
                                      "binary_sha256": "0123456789abcdef"}}}
    (run / "versions.json").write_text(json.dumps(versions))
    (run / "compare.cold_start").mkdir()
    (run / "compare.cold_start" / "trials-w1.jsonl").write_text(
        json.dumps({"benchmark": "compare.cold_start", "product": "rust", "trial": 0,
                    "phase": "w1", "metrics": {"launch_to_ready_ms": 1234.0},
                    "validation": {"echoed": True}, "validated": True}) + "\n")
    result = compare_runs({}, run, run)
    assert result["versions_a"]["_meta"]["run"]["label"] == "run-X"
    md = format_markdown(result)
    assert "run `run-X`" in md
    assert "_meta" not in md.split("run `run-X`")[1].split("\n")[0]
    assert "rust" in md


def test_trials_stamp_run_identity(tmp_path, monkeypatch):
    """Every trial row (and status row) carries run = {label, harness} so a
    results tree joins back to its campaign (audit F9)."""
    import bench.trials as trials_mod
    from bench.core.harness import HarnessDriver, Session

    class FakeDriver(HarnessDriver):
        name = "fake"

        def start_session(self, argv, env=None, cwd=None, cols=120, rows=40):
            raise AssertionError("no session is launched: the product is not comparable")

    from bench.core.registry import Registry
    from bench.core.config import load_config
    from bench.core.product import ProductAdapter, TrialContext
    from pathlib import Path as _P

    class FreshProduct(ProductAdapter):
        """A product that is never measured: not_comparable for b.x."""
        name = "fresh"
        resume_fixture_capable = False

        def version_info(self):
            return {"version": "fake"}

        def prepare_template(self, tpl):
            pass

        def new_trial(self, trial):
            trial.mkdir(parents=True, exist_ok=True)
            return {"trial_dir": trial, "home": trial / "home",
                    "work": trial / "work", "tmp": trial / "tmp",
                    "agent_dir": None, "daemon_socket": None}

        def argv(self, ctx, resume_fixture=None):
            return ["fake"]

        def reap(self, ctx):
            pass

        def launch(self, ctx, driver, resume_fixture=None):
            raise AssertionError("never launched")

    reg = Registry(load_config(None))
    reg.cfg["bench_root"] = str(tmp_path / "bench")
    reg.cfg["run"] = {"label": "campaign-20260924"}
    reg.cfg["harness_identity"] = {"git_rev": "feedface", "dirty": False}
    reg.products["fresh"] = FreshProduct({"layout": None, "product": {}, "mock": {}})

    class UnmeasurableBenchmark:
        name = "b.x"
        requires_fixture = None
        default_trials = 2
        applicable_products = None
        applicability_note = ""
        completeness_keys = ()
        aa_metrics = ()

        def applicable(self, product_name):
            return True

        def comparability(self, product, fixture=None):
            return ("not_comparable", "status-only product for the stamp test")

        def setup(self, product, ctx, fixture=None):
            pass

        def measure(self, product, ctx, record, driver, fixture=None):
            raise AssertionError("never measured")

        def validate(self, record):
            return True

    reg.benchmarks["b.x"] = UnmeasurableBenchmark()
    reg.layout = type("L", (), {"homes": tmp_path / "homes"})()
    monkeypatch.setattr(trials_mod, "gate_idle", lambda cfg, tag="": None)
    monkeypatch.setattr(trials_mod, "node_is_busy", lambda cfg: None)
    jsonl = trials_mod.run_trials(reg, FakeDriver({}), "b.x", ["fresh"], 2,
                                  tmp_path, {}, aa=False, phase_tag="w1")
    rows = [json.loads(l) for l in jsonl.read_text().splitlines() if l.strip()]
    assert len(rows) == 1  # the status row: not_comparable products never measure
    assert rows[0]["run"] == {"label": "campaign-20260924",
                              "harness": {"git_rev": "feedface", "dirty": False}}
    assert rows[0]["status"] == "not_comparable"


def test_secret_free_vendor_redaction(tmp_path, monkeypatch):
    """`bench vendor --no-secrets` drops every declared auth_sources entry,
    writes the .secret-free marker, and records the redaction in the
    build manifest (the live smoke had to strip secrets by hand)."""
    from bench.core.config import load_config
    from bench.core.registry import discover
    from bench.drivers.vendor import build_vendor_tarball

    cfg = load_config(None)
    cfg["vendor"] = dict(cfg.get("vendor") or {}, toolchain=[])  # no 160MB uv tree
    reg = discover(cfg)
    # the declared secret sources for the selected products
    from bench.drivers.vendor import secret_srcs
    secrets = secret_srcs(cfg, ["rust", "ts"], reg=reg)
    assert any(s.endswith("auth.json") for s in secrets)

    # the pure redaction split over the REAL declared entries, before any
    # staging remap: src-path matching against declared auth sources
    from bench.drivers.vendor import _redact_secrets, vendor_entries
    real_entries = vendor_entries(cfg, ["rust", "ts"], reg=reg)
    kept, redacted = _redact_secrets(real_entries, cfg, ["rust", "ts"], reg)
    assert any(e["src"].endswith("auth.json") for e in redacted)
    assert not any(e["src"].endswith("auth.json") for e in kept)

    # the tarred payload: staged fakes stand in for every src, and the
    # declared-secret set is remapped identically so the redaction,
    # marker, and manifest are exercised end to end
    staging = tmp_path / "staging"
    staged = {}
    for entry in real_entries:
        src = str(Path(entry["src"]).expanduser())
        fake = staging / (entry["dst"].replace("/", "_"))
        fake.parent.mkdir(parents=True, exist_ok=True)
        fake.write_text("fake payload")
        staged[src] = str(fake)
    for name in ["rust", "ts"]:
        remapped = [dict(e, src=staged[str(Path(e["src"]).expanduser())])
                    for e in reg.product(name).product_cfg.get("vendor", [])]
        monkeypatch.setitem(reg.product(name).product_cfg, "vendor", remapped)
    monkeypatch.setattr("bench.drivers.vendor.secret_srcs",
                        lambda cfg_, products_, reg=None:
                        {staged[s] for s in secrets if s in staged})
    out = tmp_path / "products.tar.gz"
    manifest = build_vendor_tarball(cfg, ["rust", "ts"], out, reg=reg, no_secrets=True)
    assert manifest["no_secrets"] is True
    redacted_dsts = {e["dst"] for e in manifest["redacted_entries"]}
    assert any(d.endswith("auth.json") for d in redacted_dsts)
    kept_dsts = {e["dst"] for e in manifest["entries"]}
    assert not any(d.endswith("auth.json") for d in kept_dsts)
    assert manifest["bytes"] > 0
    with tarfile.open(out) as tar:
        names = tar.getnames()
    # the marker rides in the tarball root (tar prefixes ./; macOS adds
    # resource-fork ._ files that are not the marker)
    assert any(n.split("/")[-1] == ".secret-free" and not n.split("/")[-1].startswith("._")
               for n in names)
    assert not any(n.split("/")[-1].endswith("auth.json") for n in names)
