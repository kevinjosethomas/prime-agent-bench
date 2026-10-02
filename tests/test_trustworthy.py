"""The trustworthy-startup harness rules: one ready definition (raw tty,
input row, persistence), interleaved scheduling, the A/A gate with
re-runs, clean templates, daemon parity, and the headline table."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from bench.adapters.benchmarks.cold_start import input_row_ok
from bench.adapters.terminals.pty import PTYDriver
from bench.analysis.aa_validation import latest_attempt, pair_verdict
from bench.analysis.headline import agreement, build_table
from bench.core.config import load_config
from bench.core.process import pids_referencing
from bench.core.registry import discover
from bench.runner import template_audit
from bench.trials import round_sequence

TUI = str(Path(__file__).parent / "mini_tui.py")
AA = {"spread_threshold_pct": 10.0, "drift_threshold_pct": 10.0, "abs_floor_ms": 5.0}


def _reg(tmp_path):
    cfg = load_config(None)
    cfg["bench_root"] = str(tmp_path / "bench")
    cfg["results_dir"] = str(tmp_path / "bench" / "results")
    return discover(cfg)


def test_probe_never_types_into_a_cooked_tty():
    """While the tty still echoes, the kernel renders the probe by itself;
    the probe waits for raw mode, so readiness is the product's echo."""
    app = PTYDriver({}).start_session([sys.executable, TUI, "cooked", "0.4"])
    try:
        app.wait_for(lambda: app.t_first_paint is not None, timeout=10.0)
        probe = app.probe_input_ready("Zq7c", start_ts=app.t_first_paint, timeout=20.0)
    finally:
        app.kill_tree()
    assert probe["tty_raw_at_first_send"] is True
    assert probe["tty_raw_ms"] >= 350.0
    assert probe["echo_ts_offset_ms"] >= probe["tty_raw_ms"]


def test_input_row_needs_the_prompt_glyph(tmp_path):
    rust = _reg(tmp_path).product("rust")
    assert input_row_ok(rust, " >  Zq7x01")
    assert input_row_ok(rust, " >  Zq7x01Zq7x02")
    assert not input_row_ok(rust, "Zq7x01")            # a bare echo at column 0
    assert not input_row_ok(rust, " status Zq7x01")
    assert not input_row_ok(rust, None)


def test_rounds_interleave_benchmarks_abba():
    seq0 = round_sequence(["a", "b"], ["cold", "warm"], 0, aa=False)
    seq1 = round_sequence(["a", "b"], ["cold", "warm"], 1, aa=False)
    assert seq0 == [("a", "cold"), ("a", "warm"), ("b", "cold"), ("b", "warm")]
    assert seq1 == [("b", "warm"), ("b", "cold"), ("a", "warm"), ("a", "cold")]
    assert len(round_sequence(["a", "b"], ["cold"], 0, aa=True)) == 4


def _row(product, phase, trial, ready, attempt=0, bench="compare.cold_start", **extra):
    row = {"benchmark": bench, "product": product, "phase": phase, "trial": trial,
           "attempt": attempt, "validated": True, "validation": {"echoed": True},
           "metrics": {"launch_to_ready_ms": ready, "launch_to_first_paint_ms": 1.0},
           "env": {"trial_fs": "tmpfs"}, "resource": {"rss_trial": {"rss_mb": 100.0}}}
    row.update(extra)
    return row


def test_pair_verdict_floor_spread_and_drift():
    aa = [_row("p", "aa", i, v) for i, v in enumerate([40, 44, 41, 45])]
    ok = pair_verdict(aa, [_row("p", "w1", i, 42) for i in range(4)], "launch_to_ready_ms", AA)
    assert ok["ok"], ok                          # 4 ms apart: inside the 5 ms floor
    aa_bad = [_row("p", "aa", i, v) for i, v in enumerate([100, 130, 100, 130])]
    bad = pair_verdict(aa_bad, [_row("p", "w1", i, 130) for i in range(4)],
                       "launch_to_ready_ms", AA)
    assert bad["reasons"] == ["aa_spread"]
    drift = pair_verdict(aa, [_row("p", "w1", i, 80) for i in range(4)], "launch_to_ready_ms", AA)
    assert drift["reasons"] == ["aa_drift"]
    few = pair_verdict(aa, [_row("p", "w1", 0, 42)], "launch_to_ready_ms", AA, expected=4)
    assert "wave_valid_1_of_4" in few["reasons"]


def test_latest_attempt_replaces_a_rerun_product_only():
    rows = [_row("p", "w1", 0, 1, attempt=0), _row("p", "w1", 0, 2, attempt=1),
            _row("q", "w1", 0, 3, attempt=0)]
    kept = latest_attempt(rows)
    assert sorted(r["metrics"]["launch_to_ready_ms"] for r in kept) == [2, 3]


def _tree(tmp_path, name, products):
    tree = tmp_path / name
    for bench in ("compare.cold_start", "compare.warm_start"):
        (tree / bench).mkdir(parents=True)
        for phase in ("aa", "w1"):
            rows = []
            for product, values in products.items():
                for i, v in enumerate(values[bench][phase]):
                    extra = {}
                    ident = values.get("daemon_env", {}).get(bench)
                    if ident is not None:
                        extra["daemon_identity"] = {"argv": [], "env_added": ident}
                    rows.append(_row(product, phase, i, v, bench=bench, **extra))
            (tree / bench / f"trials-{phase}.jsonl").write_text(
                "".join(json.dumps(r) + "\n" for r in rows))
    return tree


def _vals(cold, warm, aa_cold=None):
    return {"compare.cold_start": {"aa": aa_cold or [cold] * 4, "w1": [cold] * 4},
            "compare.warm_start": {"aa": [warm] * 4, "w1": [warm] * 4}}


def test_headline_marks_invalid_rows_and_daemon_mismatch(tmp_path):
    good = _vals(40, 38)
    noisy = _vals(300, 290, aa_cold=[200, 300, 200, 300])
    mismatch = dict(_vals(40, 38), daemon_env={"compare.cold_start": {"PI_OFFLINE": "1"},
                                               "compare.warm_start": {}})
    table = build_table(_tree(tmp_path, "t1", {"good": good, "noisy": noisy,
                                               "mismatch": mismatch}), AA)
    p = table["products"]
    assert p["good"]["benches"]["compare.cold_start"]["status"] == "VALID"
    assert p["good"]["benches"]["compare.cold_start"]["ready"]["p50"] == 40
    assert p["noisy"]["benches"]["compare.cold_start"]["reasons"] == ["aa_spread"]
    assert p["mismatch"]["benches"]["compare.warm_start"]["reasons"] == ["daemon_config_mismatch"]
    assert table["trial_fs"] == ["tmpfs"]


def test_agreement_uses_the_aa_tolerance(tmp_path):
    t1 = build_table(_tree(tmp_path, "a", {"p": _vals(100, 90)}), AA)
    t2 = build_table(_tree(tmp_path, "b", {"p": _vals(108, 120)}), AA)
    agree = agreement(t1, t2, AA)
    assert agree["compare.cold_start/p"]["agree"] is True      # 8 ms <= 10 ms
    assert agree["compare.warm_start/p"]["agree"] is False     # 30 ms > 9 ms


def test_template_audit_flags_personal_state(tmp_path):
    tpl = tmp_path / "tpl"
    (tpl / "home" / ".claude").mkdir(parents=True)
    (tpl / "home" / ".claude" / "settings.json").write_text(json.dumps(
        {"hooks": {"SessionStart": [{"hooks": [{"command": "bash /Users/kevin/x.sh"}]}]}}))
    findings = template_audit(tpl)
    assert any("hooks" in f for f in findings)
    assert any("operator home path" in f for f in findings)
    (tpl / "home" / ".claude" / "settings.json").write_text("{}")
    # product-downloaded content (a plugin marketplace's docs) is not operator state
    docs = tpl / "home" / ".claude" / "plugins" / "marketplaces" / "x"
    docs.mkdir(parents=True)
    (docs / "manifest.json").write_text('{"example": "/Users/someone/plugin"}')
    assert template_audit(tpl) == []


def test_claude_templates_are_clean_and_the_daemon_variant_uses_agents(tmp_path):
    reg = _reg(tmp_path)
    for name in ("claude", "claude_daemon"):
        tpl = tmp_path / name
        reg.product(name).prepare_template(tpl)
        assert template_audit(tpl) == []
        assert json.loads((tpl / "home" / ".claude.json").read_text()) == {"autoUpdates": False}
    daemon = reg.product("claude_daemon")
    assert daemon.argv({})[1:] == ["agents"]
    assert daemon.daemon_argv({})[1:] == ["daemon", "run"]
    assert reg.product("claude").daemon_argv({}) is None


def test_rust_daemon_gets_the_tuis_offline_config(tmp_path):
    rust = _reg(tmp_path).product("rust")
    ctx = {"home": tmp_path / "h", "tmp": tmp_path / "t", "agent_dir": tmp_path / "a",
           "routing": "mock"}
    assert rust.daemon_env(ctx)["PI_OFFLINE"] == "1"
    assert "PI_OFFLINE" not in rust.daemon_env(dict(ctx, routing="real-api"))
    ts_env = _reg(tmp_path).product("ts").daemon_env(ctx)
    assert (ts_env["PI_OFFLINE"], ts_env["PI_CODING_AGENT"], ts_env["PI_SKIP_VERSION_CHECK"]) == \
        ("1", "true", "1")


def test_trial_processes_are_found_by_their_environment(tmp_path):
    trial = tmp_path / "trial"
    (trial / "home").mkdir(parents=True)
    proc = subprocess.Popen(["sleep", "30"], cwd="/", env={"HOME": str(trial / "home"),
                                                            "PATH": os.environ["PATH"]})
    try:
        time.sleep(0.2)
        assert proc.pid in {pid for pid, _ in pids_referencing([str(trial)])}
    finally:
        proc.kill()
        proc.wait()
