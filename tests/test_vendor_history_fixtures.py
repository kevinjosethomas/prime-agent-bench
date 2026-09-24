"""Vendor-native loaded-session fixture import (spec §F, F4 repair).

Pi Mono is first: its persisted transcript IS the bench session-JSONL
schema, so the native import is a validated staged copy resumed via the
native `--session <path>` flag. The generic `prepare_native_fixture` hook
stays default-None so the gold rust/ts fixture manifest is never
rewritten; adapters that cannot import natively stay not_comparable.

All synthetic; no product launch, no inference.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bench.adapters.benchmarks.memory import MemoryIdleLoad
from bench.adapters.benchmarks.scroll_typing import ScrollTyping
from bench.adapters.fixtures.corpus import append_tail_sentinel, generate_rows
from bench.adapters.fixtures.session_size import SENTINEL, serialize
from bench.adapters.pi.adapter import PiMonoProduct
from bench.core.benchmark import Benchmark
from bench.core.config import load_config
from bench.core.fixture import Fixture
from bench.core.harness import HarnessDriver, Session, now
from bench.core.product import ProductAdapter, TrialContext
from bench.core.registry import discover


def _cfg(tmp_path):
    cfg = load_config(None)
    cfg["bench_root"] = str(tmp_path / "bench")
    cfg["results_dir"] = str(tmp_path / "bench" / "results")
    cfg["benchmarks"] = {}
    return cfg


def _corpus(tmp_path, turns=4, with_sentinel=True):
    """A small synthetic bench session corpus (the real generator)."""
    cwd = str(tmp_path / "recorded-cwd")
    rows = generate_rows(turns, cwd=cwd)
    if with_sentinel:
        rows = append_tail_sentinel(rows, cwd=cwd, sentinel=SENTINEL)
    path = tmp_path / "corpus.jsonl"
    path.write_bytes(serialize(rows))
    return path, rows


def _pi_product(tmp_path):
    return PiMonoProduct({"layout": _cfg(tmp_path) and __import__(
        "bench.core.env", fromlist=["BenchLayout"]).BenchLayout.from_config(_cfg(tmp_path)),
        "product": {}, "mock": {}})


def _ctx(tmp_path):
    trial = tmp_path / "trial"
    ctx: TrialContext = {"trial_dir": trial, "home": trial / "home",
                         "work": trial / "work", "tmp": trial / "tmp",
                         "agent_dir": trial / "home" / ".pi" / "agent",
                         "daemon_socket": None}
    ctx["agent_dir"].mkdir(parents=True, exist_ok=True)
    return ctx


# ---- pi: the native fixture import ------------------------------------------

def test_pi_stages_validated_byte_copy_with_semantic_evidence(tmp_path):
    corpus, rows = _corpus(tmp_path)
    product = _pi_product(tmp_path)
    ctx = _ctx(tmp_path)
    source_sha = hashlib.sha256(corpus.read_bytes()).hexdigest()
    evidence = product.prepare_native_fixture(ctx, str(corpus))
    staged = Path(evidence["path"])
    assert staged == ctx["agent_dir"] / "sessions" / f"bench-fixture-{source_sha[:16]}.jsonl"
    assert staged.read_bytes() == corpus.read_bytes()  # byte copy, same semantic workload
    assert evidence["format"] == "pi-session-jsonl-v3"
    assert evidence["sha256"] == source_sha == evidence["source"]["sha256"]
    assert evidence["bytes"] == corpus.stat().st_size
    assert evidence["rows"] == len(rows)
    assert evidence["turns"] == sum(
        1 for r in rows if r["type"] == "message" and r["message"]["role"] == "user")
    assert evidence["sentinel"] == SENTINEL
    assert Path(rows[0]["cwd"]).is_dir()  # recorded session cwd must exist
    assert hashlib.sha256(corpus.read_bytes()).hexdigest() == source_sha  # source untouched


def test_pi_argv_resumes_the_staged_native_session(tmp_path):
    corpus, _ = _corpus(tmp_path)
    product = _pi_product(tmp_path)
    ctx = _ctx(tmp_path)
    plain = product.argv(ctx)
    assert "--session" not in plain
    evidence = product.prepare_native_fixture(ctx, str(corpus))
    argv = product.argv(ctx, resume_fixture=str(corpus))
    i = argv.index("--session")
    assert argv[i + 1] == evidence["path"] == ctx["fixture_native_path"]


@pytest.mark.parametrize("broken", ["garbage", "no-header", "no-sentinel"])
def test_pi_refuses_non_native_fixture_shapes(tmp_path, broken):
    if broken == "garbage":
        corpus = tmp_path / "corpus.jsonl"
        corpus.write_text("not json at all\n")
    elif broken == "no-header":
        corpus, _ = _corpus(tmp_path, with_sentinel=True)
        lines = [l for l in corpus.read_text().splitlines() if json.loads(l)["type"] != "session"]
        corpus.write_text("\n".join(lines) + "\n")
    else:
        corpus, _ = _corpus(tmp_path, with_sentinel=False)
    product = _pi_product(tmp_path)
    ctx = _ctx(tmp_path)
    with pytest.raises(RuntimeError):
        product.prepare_native_fixture(ctx, str(corpus))
    assert "fixture_native_path" not in ctx  # nothing staged on refusal


def test_pi_is_comparable_for_loaded_session_benchmarks(tmp_path):
    reg = discover(_cfg(tmp_path))
    pi = reg.product("pi")
    assert pi.resume_fixture_capable is True
    corpus, _ = _corpus(tmp_path)
    level, reason = ScrollTyping({}).comparability(pi, corpus)
    assert level == "equivalent"
    level, _ = MemoryIdleLoad({}).comparability(pi, corpus)
    assert level == "equivalent"


def test_pi_version_info_reads_package_json_from_cli_ancestry(tmp_path, monkeypatch):
    """Sandbox layout: the vendor payload untars to the node layout
    (/root/bench/repos/pi-mono) while the sandbox bench root is
    /root/bench-root, so layout.repos has no pi-mono tree there —
    version_info must resolve package.json from the cli bundle's own
    ancestry (live finding from the 2026-09-24 proof run: bench versions
    errored inside the sandbox)."""
    pkg_dir = tmp_path / "node-layout" / "repos" / "pi-mono" / "packages" / "coding-agent"
    bundle = pkg_dir / "dist" / "bundle"
    bundle.mkdir(parents=True)
    (bundle / "cli.js").write_text("#!/usr/bin/env node\n")
    (pkg_dir / "package.json").write_text('{"version": "0.87.1"}')
    product = _pi_product(tmp_path)  # layout.repos = <tmp>/bench/repos: no pi-mono
    product.product_cfg["binary"] = str(bundle / "cli.js")

    class _NoNode:  # version falls back to package.json; no node needed here
        def __init__(self, *args, **kwargs):
            self.stdout = ""
            self.stderr = ""
            self.returncode = 0

    monkeypatch.setattr("bench.adapters.pi.adapter.subprocess.run", _NoNode)
    info = product.version_info()
    assert info["version"] == "0.87.1"
    assert info["revision"] == PiMonoProduct.default_revision
    assert info["binary"] == f"node {bundle / 'cli.js'}"
    assert info["binary_sha256"] == hashlib.sha256((bundle / "cli.js").read_bytes()).hexdigest()


# ---- the generic hook: default None keeps the gold manifest ------------------

class FakeSession(Session):
    def __init__(self):
        self.t_spawn = now()
        self.t_first_paint = now()
        self.pid = None
    def send(self, data): return now()
    def screen_text(self): return "screen"
    def alive(self): return True
    def kill_tree(self, sig=None): pass
    def start_echo_watch(self, token): pass
    def wait_echo(self, timeout=2.0): return now()
    def probe_input_ready(self, token="Zq7x", retry_every=0.5,
                          timeout=45.0, start_ts=None):
        return {"gap_ms": 1.0, "echo_ts_offset_ms": 10.0, "sends": 1,
                "dropped_probes": 0, "chars_sent": 5, "probe_token": token}


class FakeDriver(HarnessDriver):
    name = "fake"
    def start_session(self, argv, env=None, cwd=None, cols=120, rows=40):
        return FakeSession()


class HookProduct(ProductAdapter):
    """A capable product; prepare_native_fixture overridden per test."""
    name = "hookfake"
    resume_fixture_capable = True
    def __init__(self, cfg, native):
        super().__init__(cfg)
        self.native = native
    def version_info(self): return {"version": "fake"}
    def prepare_template(self, tpl): pass
    def new_trial(self, trial):
        trial.mkdir(parents=True, exist_ok=True)
        return {"trial_dir": trial, "home": trial / "home", "work": trial / "work",
                "tmp": trial / "tmp", "agent_dir": None, "daemon_socket": None}
    def prepare_native_fixture(self, ctx, fixture):
        return self.native(ctx, fixture) if callable(self.native) else self.native
    def argv(self, ctx, resume_fixture=None): return ["fake"]
    def reap(self, ctx): pass


class StubFixture(Fixture):
    name = "session-10mib"
    def __init__(self): pass
    def path(self): return Path("/tmp/corpus.jsonl")
    def generate(self, spec): return self.path()
    def validate(self, expected_sha256): return True
    def manifest(self):
        return {"path": "/tmp/corpus.jsonl", "bytes": 10485760, "rows": 7391,
                "sha256": "deadbeef", "sentinel": SENTINEL,
                "generator_seed": 1234, "target_mib": 10.0}


def _engine(tmp_path, monkeypatch, native):
    reg = discover(_cfg(tmp_path))
    reg.fixtures["session-10mib"] = StubFixture()
    reg.products["hookfake"] = HookProduct(
        {"layout": reg.layout, "product": {}, "mock": {}}, native)
    scroll = reg.benchmark("compare.scroll_typing")
    scroll.measure = lambda product, ctx, record, driver, fixture=None: record.update(
        {"metrics": {"typing_ms": [1.0], "typing_ok": True},
         "validation": {"sentinel": True, "echoed": True,
                        "typing_ok": True, "typing_scrolled_ok": True}})
    import bench.trials as trials_mod
    monkeypatch.setattr(trials_mod, "gate_idle", lambda cfg, tag="": None)
    monkeypatch.setattr(trials_mod, "node_is_busy", lambda cfg: None)
    out_dir = tmp_path / "results"
    out_dir.mkdir(parents=True)
    jsonl = trials_mod.run_trials(
        reg, FakeDriver({}), "compare.scroll_typing", ["hookfake"], 1, out_dir,
        {"session-10mib": Path("/tmp/corpus.jsonl")}, aa=False, phase_tag="w1")
    return [json.loads(l) for l in jsonl.read_text().splitlines()]


def test_default_hook_leaves_gold_fixture_manifest_untouched(tmp_path, monkeypatch):
    rows = _engine(tmp_path, monkeypatch, native=None)
    fixture = rows[0]["fixture"]
    assert fixture["sha256"] == "deadbeef" and fixture["rows"] == 7391
    assert "native" not in fixture  # default None: no native rewrite of gold evidence


def test_engine_records_native_fixture_evidence_on_the_row(tmp_path, monkeypatch):
    seen = {}
    def native(ctx, fixture):
        seen["fixture"] = fixture
        return {"format": "fake-native", "path": "/tmp/staged.jsonl",
                "sha256": "cafebabe", "bytes": 123, "rows": 9, "turns": 4,
                "sentinel": SENTINEL, "source": {"path": str(fixture), "sha256": "deadbeef"}}
    rows = _engine(tmp_path, monkeypatch, native=native)
    assert rows[0]["fixture"]["native"]["sha256"] == "cafebabe"
    assert seen["fixture"] == Path("/tmp/corpus.jsonl")
