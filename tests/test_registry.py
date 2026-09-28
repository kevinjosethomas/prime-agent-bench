"""Registry discovery, config precedence, and trial-count resolution."""
from __future__ import annotations

from pathlib import Path

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
    assert set(reg.terminals) == {"pty", "tmux"}
    assert set(reg.fixtures) == {"session-10mib", "subagent-tree"}
    assert "compare.cold_start" in reg.benchmarks
    assert "kernel.multi_kernel_10" in reg.benchmarks
    assert "session.agent_view_roundtrip" in reg.benchmarks
    assert len(reg.benchmarks) == 20


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
    assert reg.benchmark("compare.scroll_typing").requires_fixture == "session-10mib"


def test_deep_merge_override_wins():
    base = {"a": 1, "nested": {"x": 1, "y": 2}}
    out = deep_merge(base, {"nested": {"y": 3, "z": 4}})
    assert out == {"a": 1, "nested": {"x": 1, "y": 3, "z": 4}}


def test_product_config_loads_pinning():
    cfg = product_config("rust")
    # the cmp5-20260928-163659 campaign pin: origin/rust frozen at campaign
    # start, sandbox-built replicating the pinned commit's CI recipe
    assert cfg["revision"] == "b5bf28f1d752ca9bea0ab1d3d24b572e682d69e5"
    assert cfg["binary"].endswith("/bin/prime-agent")
    assert "install" in cfg


def test_benchmark_config_overrides_reach_registry_adapters(tmp_path):
    """The configs/default.yaml ``benchmarks:`` overrides must reach the
    adapter __init__s through discover() — not just the hand-constructed
    tests. session_open/memory/scroll_typing slice their own entry
    (ready_timeout_s, sentinel_timeout_s, ...) out of the map."""
    reg = discover(_cfg(tmp_path, {"benchmarks": {
        "session.cold_open_10mib": {"sentinel_timeout_s": 5.0,
                                    "ready_timeout_s": 7.0}}}))
    bench = reg.benchmark("session.cold_open_10mib")
    assert bench.sentinel_timeout_s == 5.0
    assert bench.ready_timeout_s == 7.0
    base = discover(_cfg(tmp_path))
    defaults = base.benchmark("session.cold_open_10mib")
    assert defaults.sentinel_timeout_s == 30.0
    assert defaults.ready_timeout_s == 120.0


def test_results_dir_expands_home(tmp_path):
    """A configured results_dir carries ``~``: load_config expands it, so
    no run ever writes a literal ``./~`` tree relative to the CWD."""
    import yaml as _yaml
    from bench.core.config import load_config
    cfg_file = tmp_path / "campaign.yaml"
    cfg_file.write_text(_yaml.safe_dump(
        {"results_dir": "~/bench-results-test", "bench_root": "~/bench"}))
    cfg = load_config(cfg_file)
    assert Path(cfg["results_dir"]) == Path.home() / "bench-results-test"
    # bench_root keeps its configured form; BenchLayout.from_config expands
    # it at use time
    assert cfg["bench_root"] == "~/bench"


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
