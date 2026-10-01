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
    assert set(reg.products) == {"rust", "rust_b", "ts", "claude", "codex",
                                 "codex_nodaemon", "pi", "hermes"}
    assert set(reg.terminals) == {"pty", "tmux"}
    assert set(reg.fixtures) == {"session-10mib", "session-10mib-compacted",
                                 "subagent-tree"}
    assert "compare.cold_start" in reg.benchmarks
    assert "kernel.multi_kernel_10" in reg.benchmarks
    assert "session.agent_view_roundtrip" in reg.benchmarks
    assert "session.cold_open_10mib_compacted" in reg.benchmarks
    assert len(reg.benchmarks) == 19


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


def test_variants_share_their_harness_pinning(tmp_path):
    reg = discover(_cfg(tmp_path, {"products": {"rust_b": {"revision": "b-pin"}}}))
    codex, nodaemon = reg.product("codex"), reg.product("codex_nodaemon")
    assert nodaemon.dialog_steps == codex.dialog_steps
    assert codex.daemon_argv({}) is not None and nodaemon.daemon_argv({}) is None
    assert reg.product("rust_b").product_cfg["revision"] == "b-pin"
    assert reg.product("rust").product_cfg["revision"] != "b-pin"
    assert reg.product("rust_b").template_dir() == reg.layout.homes / "rust_b" / "template"


def test_trial_paths_fit_codex_daemon_sockets(tmp_path):
    # the sandbox bench root + the longest product and benchmark names: the
    # codex updater socket under the trial home must fit the 107-byte cap
    from bench.trials import bench_tag
    cfg = _cfg(tmp_path)
    cfg["bench_root"] = "/root/bench-root"
    reg = discover(cfg)
    tags = {bench_tag(b) for b in reg.benchmarks}
    assert len(tags) == len(reg.benchmarks)
    longest = max(tags, key=len)
    trial = reg.layout.trials_dir(max(reg.products, key=len)) / f"{longest}-aa-19"
    sock = trial / "home/.codex/app-server-daemon/daemon-updater.sock"
    assert len(str(sock)) <= 107


def test_deep_merge_override_wins():
    base = {"a": 1, "nested": {"x": 1, "y": 2}}
    out = deep_merge(base, {"nested": {"y": 3, "z": 4}})
    assert out == {"a": 1, "nested": {"x": 1, "y": 3, "z": 4}}


def test_product_config_loads_pinning():
    cfg = product_config("rust")
    # the deployed lane pin: the per-VM candidate path every bundle deploy
    # populates (deploy_bench.sh + the wave briefs); the cmp5 campaign pin
    # (59a9c658, run 36193301325) lives in records/campaigns/cmp5-20260926/
    assert cfg["binary"] == "/root/bench/repos/prime-agent-rust/target/release/prime-agent"
    assert cfg["revision"] == "7152746b99f6767843bb40b4674a23a5a501fdc0"
    assert "install" in cfg


def test_product_config_honors_config_section_override():
    """The config ``products: <name>:`` section is REAL: a deployment
    overrides any product.yaml pin (binary/revision/...) without editing
    repo files — the audit-F10 trap class (a pin landing in a section no
    code reads) stays closed. Unoverridden keys keep the file default."""
    deploy = {"products": {"rust": {
        "binary": "/root/bench/repos/prime-agent-rust/target/release/prime-agent",
        "revision": "13d5c0d781d28228ab95d60760e5e018d283083a"}}}
    cfg = product_config("rust", deploy)
    assert cfg["binary"] == "/root/bench/repos/prime-agent-rust/target/release/prime-agent"
    assert cfg["revision"] == "13d5c0d781d28228ab95d60760e5e018d283083a"
    assert cfg["needs_kernel_venv"] is True          # file default preserved
    assert cfg["install"]["download_bytes"] == 53291156
    assert cfg["vendor"]                              # vendor list preserved
    assert product_config("rust", {"products": {}})["revision"] ==         "7152746b99f6767843bb40b4674a23a5a501fdc0"   # empty section = file pin


def test_discovery_passes_config_product_overrides(tmp_path):
    """discover() wires the products-section override into the instantiated
    adapter (the registry is the only product_config call site that sees
    the loaded config)."""
    reg = discover(_cfg(tmp_path, {"products": {"rust": {
        "binary": "/tmp/vm-built-candidate",
        "revision": "cafebabecafebabecafebabecafebabe"}}}))
    rust = reg.product("rust")
    assert rust.product_cfg["binary"] == "/tmp/vm-built-candidate"
    assert rust.product_cfg["revision"] == "cafebabecafebabecafebabecafebabe"
    assert rust.binary == Path("/tmp/vm-built-candidate")


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
