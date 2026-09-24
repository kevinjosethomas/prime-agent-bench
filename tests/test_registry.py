"""Registry discovery, config precedence, and trial-count resolution."""
from __future__ import annotations

from bench.core.config import deep_merge, load_config, product_config
from bench.core.measurement import primary_metric
from bench.core.registry import discover
from bench.trials import effective_trials


def _cfg(tmp_path, overrides=None):
    cfg = load_config(None)
    cfg["bench_root"] = str(tmp_path / "bench")
    cfg["results_dir"] = str(tmp_path / "bench" / "results")
    for key, value in (overrides or {}).items():
        cfg[key] = value
    return cfg


def test_discovery_finds_every_adapter(tmp_path):
    reg = discover(_cfg(tmp_path))
    assert set(reg.products) == {"rust", "ts", "claude", "codex", "pi"}
    assert set(reg.harnesses) == {"pty", "tmux"}
    assert set(reg.fixtures) == {"session-10mib", "session-10mib-v3", "subagent-tree"}
    assert "compare.cold_start" in reg.benchmarks
    assert "kernel.multi_kernel_10" in reg.benchmarks
    assert len(reg.benchmarks) == 17


def test_adapter_wiring(tmp_path):
    reg = discover(_cfg(tmp_path))
    rust = reg.product("rust")
    assert rust.has_daemon is True
    assert rust.template_dir() == rust.layout.homes / "rust" / "template"
    ts = reg.product("ts")
    assert ts.has_daemon is True
    assert reg.product("claude").needs_prepass is True
    assert reg.product("codex").needs_prepass is True
    driver = reg.driver()
    assert driver.name == "pty"
    assert reg.benchmark("daemon.boot").applicable("rust")
    assert not reg.benchmark("daemon.boot").applicable("claude")
    assert reg.benchmark("compare.scroll_typing").requires_fixture == "session-10mib-v3"
    assert reg.benchmark("session.cold_open_10mib").requires_fixture == "session-10mib-v3"


def test_deep_merge_override_wins():
    base = {"a": 1, "nested": {"x": 1, "y": 2}}
    out = deep_merge(base, {"nested": {"y": 3, "z": 4}})
    assert out == {"a": 1, "nested": {"x": 1, "y": 3, "z": 4}}


def test_product_config_loads_pinning():
    cfg = product_config("rust")
    # the campaign-verified build revision (audit F10 pin fix, live product.yaml)
    assert cfg["revision"] == "bdf82f4f15e7d8c0b5e41bf473e3f5b26a8a41ad"
    assert cfg["binary_sha256"] == "eaed8f003cfcc78ccabba2490d0062074e3528b77885855fbc25342440a98de1"
    assert "install" in cfg


def test_effective_trials_precedence(tmp_path):
    reg = discover(_cfg(tmp_path, {"benchmarks":
                                   {"compare.cold_start": {"trials": 4}}}))
    bench = reg.benchmark("compare.cold_start")
    bench.default_trials = 7
    assert effective_trials(reg, "compare.cold_start", None) == 4   # config wins
    assert effective_trials(reg, "compare.cold_start", 3) == 3      # CLI wins
    reg.cfg["benchmarks"].pop("compare.cold_start")
    assert effective_trials(reg, "compare.cold_start", None) == 7   # benchmark default


def test_every_primary_metric_direction(tmp_path):
    for name, (metric, direction) in primary_metric.__globals__["PRIMARY"].items():
        assert direction == "minimize"
        assert isinstance(metric, str) and metric
