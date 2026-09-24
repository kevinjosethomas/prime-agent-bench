"""Fixture/scenario correctness: comparability gating, status rows,
probe-before-sentinel ordering, missing-sentinel invalidation, and the
version-provenance pin (audit F10).

No product is launched and no inference runs: scenarios run against fake
sessions/products through the real Benchmark/Session ABCs.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bench.adapters.benchmarks.memory import MemoryIdleLoad
from bench.adapters.benchmarks.scroll_typing import ScrollTyping
from bench.adapters.benchmarks.session_open import SessionColdOpen
from bench.adapters.fixtures.session_size import SENTINEL
from bench.adapters.products.rust.adapter import PrimeAgentRustProduct
from bench.core.benchmark import COMPARABILITY_LEVELS
from bench.core.config import load_config
from bench.core.harness import HarnessDriver, Session, now
from bench.core.product import ProductAdapter, TrialContext
from bench.core.registry import discover


def _cfg(tmp_path, benchmark_overrides=None):
    cfg = load_config(None)
    cfg["bench_root"] = str(tmp_path / "bench")
    cfg["results_dir"] = str(tmp_path / "bench" / "results")
    cfg["benchmarks"] = benchmark_overrides or {}
    return cfg


# ---- fakes: no product launch, no inference --------------------------------

class FakeSession(Session):
    """Scripted session recording the measurement call order."""

    def __init__(self, show_sentinel=False, typing_ok=True):
        self.t_spawn = now()
        self.t_first_paint = now()
        self.pid = None
        self.calls: list[str] = []
        self.screen = ["hello"] + ([SENTINEL] if show_sentinel else [])
        self.typing_ok = typing_ok

    def send(self, data):
        self.calls.append("send")
        self.screen.append(str(data))  # typing changes the rendered screen
        return now()

    def screen_text(self):
        self.calls.append("screen")
        return "\n".join(self.screen)

    def alive(self):
        return True

    def kill_tree(self, sig=None):
        self.calls.append("kill")

    def start_echo_watch(self, token):
        self.calls.append(f"watch:{token}")

    def wait_echo(self, timeout=2.0):
        if not self.typing_ok:
            raise TimeoutError("echo not rendered")
        return now()

    def probe_input_ready(self, token="Zq7x", retry_every=0.5,
                          timeout=45.0, start_ts=None):
        self.calls.append("probe")
        return {"gap_ms": 1.0, "echo_ts_offset_ms": 10.0, "sends": 1,
                "dropped_probes": 0, "chars_sent": 5, "probe_token": f"{token}01"}


class FakeDriver(HarnessDriver):
    name = "fake"

    def __init__(self, session):
        self.session = session

    def start_session(self, argv, env=None, cwd=None, cols=120, rows=40):
        return self.session


class FakeProduct(ProductAdapter):
    """A product that never launches: the driver fakes the session."""

    name = "fake"
    resume_fixture_capable = True

    def __init__(self, cfg, session):
        super().__init__(cfg)
        self.session = session

    def version_info(self):
        return {"version": "fake"}

    def prepare_template(self, tpl):
        pass

    def new_trial(self, trial: Path) -> TrialContext:
        """No template copy: the trial context is all the engine needs."""
        trial.mkdir(parents=True, exist_ok=True)
        ctx: TrialContext = {"trial_dir": trial, "home": trial / "home",
                             "work": trial / "work", "tmp": trial / "tmp",
                             "agent_dir": None, "daemon_socket": None}
        return ctx

    def launch(self, ctx, driver, resume_fixture=None):
        self.last_resume_fixture = resume_fixture
        return self.session

    def argv(self, ctx, resume_fixture=None):
        return ["fake"]

    def reap(self, ctx):
        pass


class FreshSessionProduct(FakeProduct):
    """A product whose argv ignores resume_fixture (fresh sessions)."""

    name = "fresh"
    resume_fixture_capable = False


def _ctx(tmp_path):
    trial = tmp_path / "trial"
    trial.mkdir(parents=True, exist_ok=True)
    ctx: TrialContext = {"trial_dir": trial, "home": trial / "home",
                         "work": trial / "work", "tmp": trial / "tmp",
                         "agent_dir": None, "daemon_socket": None}
    for key in ("home", "work", "tmp"):
        ctx[key].mkdir(parents=True, exist_ok=True)
    return ctx


def _record():
    return {"benchmark": "x", "product": "fake", "phase": "w1"}


# ---- scenario ordering + validation ----------------------------------------

def test_session_cold_open_probes_ready_before_sentinel_wait(tmp_path, monkeypatch):
    from bench.adapters.benchmarks import session_open as mod
    monkeypatch.setattr(mod, "rss_tree", lambda pid: {"rss_mb": 1.0})
    monkeypatch.setattr(mod, "loadavg", lambda: 0.0)
    session = FakeSession(show_sentinel=False)
    cfg = _cfg(tmp_path, {"session.cold_open_10mib": {"sentinel_timeout_s": 0.05}})
    bench = SessionColdOpen(cfg)
    product = FakeProduct({"layout": None, "product": {}, "mock": {}}, session)
    bench.measure(product, _ctx(tmp_path), _record(), FakeDriver(session),
                  fixture=Path("corpus.jsonl"))
    # ready probe precedes every sentinel screen poll
    assert session.calls.index("probe") < session.calls.index("screen")


def test_session_cold_open_missing_sentinel_invalidates_row(tmp_path, monkeypatch):
    from bench.adapters.benchmarks import session_open as mod
    monkeypatch.setattr(mod, "rss_tree", lambda pid: {"rss_mb": 1.0})
    monkeypatch.setattr(mod, "loadavg", lambda: 0.0)
    session = FakeSession(show_sentinel=False)
    cfg = _cfg(tmp_path, {"session.cold_open_10mib": {"sentinel_timeout_s": 0.05}})
    bench = SessionColdOpen(cfg)
    record = _record()
    bench.measure(FakeProduct({"layout": None, "product": {}, "mock": {}}, session),
                  _ctx(tmp_path), record, FakeDriver(session), fixture=Path("corpus.jsonl"))
    assert record["metrics"]["launch_to_sentinel_ms"] is None
    assert record["validation"] == pytest.approx({"sentinel": False, "echoed": True, "erased": True})
    assert bench.validate(record) is False


def test_session_cold_open_valid_when_sentinel_renders(tmp_path, monkeypatch):
    from bench.adapters.benchmarks import session_open as mod
    monkeypatch.setattr(mod, "rss_tree", lambda pid: {"rss_mb": 1.0})
    monkeypatch.setattr(mod, "loadavg", lambda: 0.0)
    session = FakeSession(show_sentinel=True)
    bench = SessionColdOpen(_cfg(tmp_path))
    product = FakeProduct({"layout": None, "product": {}, "mock": {}}, session)
    record = _record()
    bench.measure(product, _ctx(tmp_path), record, FakeDriver(session),
                  fixture=Path("corpus.jsonl"))
    assert product.last_resume_fixture == "corpus.jsonl"
    assert record["metrics"]["launch_to_sentinel_ms"] is not None
    assert bench.validate(record) is True


def test_memory_sentinel_gates_loaded_session_rss(tmp_path, monkeypatch):
    from bench.adapters.benchmarks import memory as mod
    monkeypatch.setattr(mod, "rss_tree", lambda pid: {"rss_mb": 1.0})
    monkeypatch.setattr(mod, "IDLE_SETTLE_S", 0.0)
    session = FakeSession(show_sentinel=False)
    cfg = _cfg(tmp_path, {"compare.memory_idle_load": {"sentinel_timeout_s": 0.05}})
    bench = MemoryIdleLoad(cfg)
    record = _record()
    bench.measure(FreshSessionProduct({"layout": None, "product": {}, "mock": {}}, session),
                  _ctx(tmp_path), record, FakeDriver(session), fixture=Path("corpus.jsonl"))
    assert record["validation"]["sentinel"] is False
    assert bench.validate(record) is False


def test_scroll_typing_dropped_keys_invalidate_row(tmp_path, monkeypatch):
    from bench.adapters.benchmarks import scroll_typing as mod
    monkeypatch.setattr(mod, "rss_tree", lambda pid: {"rss_mb": 1.0})
    session = FakeSession(show_sentinel=True, typing_ok=False)
    bench = ScrollTyping(_cfg(tmp_path))
    record = _record()
    bench.measure(FakeProduct({"layout": None, "product": {}, "mock": {}}, session),
                  _ctx(tmp_path), record, FakeDriver(session), fixture=Path("corpus.jsonl"))
    assert record["validation"] == pytest.approx(
        {"sentinel": True, "echoed": True, "typing_ok": False, "typing_scrolled_ok": False})
    assert bench.validate(record) is False


def test_scroll_typing_valid_when_everything_renders(tmp_path, monkeypatch):
    from bench.adapters.benchmarks import scroll_typing as mod
    monkeypatch.setattr(mod, "rss_tree", lambda pid: {"rss_mb": 1.0})
    session = FakeSession(show_sentinel=True, typing_ok=True)
    bench = ScrollTyping(_cfg(tmp_path))
    record = _record()
    bench.measure(FakeProduct({"layout": None, "product": {}, "mock": {}}, session),
                  _ctx(tmp_path), record, FakeDriver(session), fixture=Path("corpus.jsonl"))
    assert record["validation"]["typing_ok"] is True
    assert bench.validate(record) is True


# ---- applicability + comparability levels -----------------------------------

def test_session_cold_open_is_rust_ts_only(tmp_path):
    reg = discover(_cfg(tmp_path))
    bench = reg.benchmark("session.cold_open_10mib")
    assert bench.applicable("rust") and bench.applicable("ts")
    assert not any(bench.applicable(p) for p in ("claude", "codex", "pi"))
    assert bench.applicability_note


def test_comparability_levels_follow_spec_section_f(tmp_path):
    reg = discover(_cfg(tmp_path))
    capable = reg.product("rust")
    fresh = reg.product("claude")
    fixture_bench = reg.benchmark("compare.memory_idle_load")
    plain_bench = reg.benchmark("compare.cold_start")
    level, _ = fixture_bench.comparability(capable, Path("corpus.jsonl"))
    assert level == "equivalent"
    level, reason = fixture_bench.comparability(fresh, Path("corpus.jsonl"))
    assert level == "not_comparable"
    assert "resume_fixture" in reason or "vendor-native" in reason
    level, _ = plain_bench.comparability(capable)
    assert level == "qualified"
    assert set(COMPARABILITY_LEVELS) == {"equivalent", "qualified", "not_comparable"}


def test_resume_fixture_capability_flags(tmp_path):
    reg = discover(_cfg(tmp_path))
    assert reg.product("rust").resume_fixture_capable is True
    assert reg.product("ts").resume_fixture_capable is True
    assert all(reg.product(p).resume_fixture_capable is False
               for p in ("claude", "codex", "pi"))


# ---- trial engine: status rows + stamped comparability ----------------------

class StubFixture:
    """Manifest-only fixture stand-in (no artifact build in tests)."""

    def manifest(self):
        return {"path": "/tmp/corpus.jsonl", "bytes": 10485760, "rows": 7391,
                "sha256": "deadbeef", "sentinel": SENTINEL,
                "generator_seed": 1234, "target_mib": 10.0}


def _engine_reg(tmp_path, monkeypatch):
    reg = discover(_cfg(tmp_path))
    reg.fixtures["session-10mib"] = StubFixture()
    # no real product launches; no load gating in unit tests
    for name, cls in (("capfake", FakeProduct), ("freshfake", FreshSessionProduct)):
        product = cls({"layout": reg.layout, "product": {}, "mock": {}}, FakeSession())
        product.name = name  # instance attr: matches the registry key
        reg.products[name] = product
    import bench.trials as trials_mod
    monkeypatch.setattr(trials_mod, "gate_idle", lambda cfg, tag="": None)
    monkeypatch.setattr(trials_mod, "node_is_busy", lambda cfg: None)
    return reg


def test_run_trials_skips_fresh_session_products_as_status_rows(tmp_path, monkeypatch):
    reg = _engine_reg(tmp_path, monkeypatch)
    scroll = reg.benchmark("compare.scroll_typing")
    measured = []
    def fake_measure(product, ctx, record, driver, fixture=None):
        measured.append(product.name)
        record["metrics"] = {"typing_ms": [1.0], "typing_ok": True}
        record["validation"] = {"sentinel": True, "echoed": True,
                                "typing_ok": True, "typing_scrolled_ok": True}
    scroll.measure = fake_measure
    out_dir = Path(cfg_results := tmp_path / "results")
    out_dir.mkdir(parents=True)
    jsonl = __import__("bench.trials", fromlist=["run_trials"]).run_trials(
        reg, FakeDriver(FakeSession()), "compare.scroll_typing",
        ["freshfake", "capfake"], 2, out_dir,
        {"session-10mib": Path("/tmp/corpus.jsonl")}, aa=False, phase_tag="w1")
    rows = [json.loads(l) for l in jsonl.read_text().splitlines()]
    status_rows = [r for r in rows if r.get("status")]
    measured_rows = [r for r in rows if not r.get("status")]
    assert len(status_rows) == 1
    status = status_rows[0]
    assert status["product"] == "freshfake"
    assert status["status"] == "not_comparable"
    assert status["comparability"] == "not_comparable"
    assert "metrics" not in status  # status, not numeric zero
    assert measured == ["capfake", "capfake"]
    assert len(measured_rows) == 2
    assert all(r["comparability"] == "equivalent" for r in measured_rows)
    assert all(r["fixture"]["rows"] == 7391 and r["fixture"]["sentinel"] == SENTINEL
               for r in measured_rows)  # §F sentinel + message-count equivalence evidence
    assert all(r["validated"] is True for r in measured_rows)


def test_run_trials_preserves_not_applicable_products_as_status_rows(tmp_path, monkeypatch):
    reg = _engine_reg(tmp_path, monkeypatch)
    # the fake capable product stands in for rust (the RT-only scope)
    reg.products["rust"] = reg.products.pop("capfake")
    reg.products["rust"].name = "rust"
    bench = reg.benchmark("session.cold_open_10mib")
    bench.measure = lambda product, ctx, record, driver, fixture=None: record.update(
        {"metrics": {"launch_to_ready_ms": 5.0},
         "validation": {"sentinel": True, "echoed": True, "erased": True}})
    out_dir = tmp_path / "results"
    out_dir.mkdir(parents=True)
    from bench.trials import run_trials
    jsonl = run_trials(reg, FakeDriver(FakeSession()), "session.cold_open_10mib",
                       ["rust", "freshfake", "claude"], 1, out_dir,
                       {"session-10mib": Path("/tmp/corpus.jsonl")}, aa=False,
                       phase_tag="w1")
    rows = [json.loads(l) for l in jsonl.read_text().splitlines()]
    by_product = {r["product"]: r for r in rows}
    # claude and the fresh-session fake are out of the RT-only scope (spec §A)
    assert by_product["claude"]["status"] == "not_applicable"
    assert by_product["freshfake"]["status"] == "not_applicable"
    assert "metrics" not in by_product["claude"]
    assert "metrics" not in by_product["freshfake"]
    # the in-scope capable product is measured and comparable
    assert "metrics" in by_product["rust"]
    assert by_product["rust"]["comparability"] == "equivalent"


def test_run_trials_requires_the_fixture_to_be_ensured(tmp_path, monkeypatch):
    reg = _engine_reg(tmp_path, monkeypatch)
    out_dir = tmp_path / "results"
    out_dir.mkdir(parents=True)
    from bench.trials import run_trials
    with pytest.raises(ValueError, match="session-10mib"):
        run_trials(reg, FakeDriver(FakeSession()), "compare.memory_idle_load",
                   ["capfake"], 1, out_dir, {}, aa=False, phase_tag="w1")


# ---- audit F10: the live pin + provenance check ------------------------------

def test_rust_pin_is_the_campaign_verified_revision(tmp_path):
    from bench.core.config import product_config
    cfg = product_config("rust")
    assert cfg["revision"] == "bdf82f4f15e7d8c0b5e41bf473e3f5b26a8a41ad"
    assert PrimeAgentRustProduct.default_revision == cfg["revision"]


class _FakeRun:
    """subprocess.run stub: the --version probe never execs the fake binary."""

    def __call__(self, argv, capture_output=True, text=True, timeout=None):
        class R:
            stdout = "0.1.0"
            stderr = ""
        return R()


def test_version_info_enforces_pinned_binary_sha256(tmp_path, monkeypatch):
    binary = tmp_path / "prime-agent"
    binary.write_bytes(b"fake-binary")
    import hashlib
    from bench.adapters.products.rust import adapter as rust_mod
    monkeypatch.setattr(rust_mod.subprocess, "run", _FakeRun())
    sha = hashlib.sha256(b"fake-binary").hexdigest()
    product = PrimeAgentRustProduct({"layout": None,
                                    "product": {"binary": str(binary),
                                                "binary_sha256": sha,
                                                "revision": "r1"},
                                    "mock": {}})
    info = product.version_info()
    assert info["version"] == "0.1.0"
    assert info["revision"] == "r1"
    assert info["binary_sha256"] == sha
    assert info["binary_bytes"] == len(b"fake-binary")
    stale = PrimeAgentRustProduct({"layout": None,
                                   "product": {"binary": str(binary),
                                               "binary_sha256": "0" * 64,
                                               "revision": "r1"},
                                   "mock": {}})
    with pytest.raises(RuntimeError, match="pinned"):
        stale.version_info()


def test_version_info_collects_identity_without_a_hash_pin(tmp_path, monkeypatch):
    binary = tmp_path / "prime-agent"
    binary.write_bytes(b"fake-binary")
    from bench.adapters.products.rust import adapter as rust_mod
    monkeypatch.setattr(rust_mod.subprocess, "run", _FakeRun())
    product = PrimeAgentRustProduct({"layout": None,
                                    "product": {"binary": str(binary)},
                                    "mock": {}})
    info = product.version_info()
    assert info["binary_sha256"]
    assert info["binary_bytes"] == len(b"fake-binary")
