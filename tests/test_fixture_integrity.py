"""Per-trial fixture clone integrity (the 2026-09-24 incident class).

The resumed product appends live session events to the file it resumed IN
PLACE, so a shared golden pointed at --resume mutates mid-wave (7391 rows
sha dadaec... -> 7418 rows sha 8c717...). The fix under test: every
trial stages a writable byte-exact clone of the hash-verified golden into
the product's isolated trial session dir, the row carries the ACTUAL
staged-clone hash, and the validity gate refuses ranking without that
proof (mismatch -> invalid; no proof -> loud exclusion, never silent).

No product is launched, no inference runs: staging and the trial engine
run against real files and fake sessions.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bench.adapters.rust.adapter import PrimeAgentRustProduct
from bench.adapters.ts.adapter import PrimeAgentTsProduct
from bench.core.config import load_config
from bench.core.harness import HarnessDriver, Session, now
from bench.core.product import ProductAdapter, TrialContext
from bench.core.registry import discover
from bench.core.trial_fixture import (FixtureSourceError, clone_post_evidence,
                                      count_rows, sha256_bytes,
                                      stage_trial_fixture)
from bench.adapters.fixtures.session_size import SENTINEL


# ---- helpers ----------------------------------------------------------------

def _golden(tmp_path, rows=4):
    """A real tiny golden corpus file + its manifest record."""
    path = tmp_path / "golden" / "corpus.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = "\n".join(json.dumps(
        {"type": "message", "id": str(i),
         "message": {"role": "user",
                     "content": [{"type": "text", "text": f"row {i} {SENTINEL}"}]}})
        for i in range(rows)) + "\n"
    path.write_text(data)
    return path


def _sha(path):
    return sha256_bytes(Path(path).read_bytes())


class FakeSession(Session):
    def __init__(self):
        self.t_spawn = now()
        self.t_first_paint = now()
        self.pid = None

    def send(self, data):
        return now()

    def screen_text(self):
        return "ready"

    def alive(self):
        return True

    def kill_tree(self, sig=None):
        pass

    def start_echo_watch(self, token):
        pass

    def wait_echo(self, timeout=2.0):
        return now()

    def probe_input_ready(self, token="Zq7x", retry_every=0.5, timeout=45.0,
                          start_ts=None, **kwargs):
        return {"gap_ms": 1.0, "echo_ts_offset_ms": 10.0, "sends": 1,
                "dropped_probes": 0, "chars_sent": 5, "probe_token": f"{token}01",
                "input_buffered": False, "probe_grid_ms": 50.0,
                "quantized_ms": 50.0, "dialogs": [], "dialog_ms": 0.0}


class FakeDriver(HarnessDriver):
    name = "fake"

    def __init__(self):
        pass

    def start_session(self, argv, env=None, cwd=None, cols=120, rows=40):
        return FakeSession()


class FakeProduct(ProductAdapter):
    """Records the resume path it was given (argv contract) and appends a
    live session event to the file it resumed — exactly what the real
    products do in place."""

    name = "fake"
    resume_fixture_capable = True

    def __init__(self, cfg):
        super().__init__(cfg)
        self.resume_paths: list[str | None] = []

    def version_info(self):
        return {"version": "fake"}

    def prepare_template(self, tpl):
        pass

    def new_trial(self, trial: Path) -> TrialContext:
        trial.mkdir(parents=True, exist_ok=True)
        ctx: TrialContext = {"trial_dir": trial, "home": trial / "home",
                             "work": trial / "work", "tmp": trial / "tmp",
                             "agent_dir": None, "daemon_socket": None}
        return ctx

    def launch(self, ctx, driver, resume_fixture=None):
        self.resume_paths.append(resume_fixture)
        if resume_fixture:  # the resumed product appends IN PLACE
            with open(resume_fixture, "a") as f:
                f.write(json.dumps({"type": "message", "id": "live",
                                    "message": {"role": "assistant",
                                                "content": [{"type": "text",
                                                             "text": "live"}]}}) + "\n")
        return FakeSession()

    def argv(self, ctx, resume_fixture=None):
        return ["fake"]

    def reap(self, ctx):
        pass


class StubFixture:
    """Manifest stand-in reporting the golden's sha256 — snapshotted at
    construction (a real manifest is a persisted build record, so it does
    NOT track a mid-run mutation of the artifact)."""

    def __init__(self, golden, sha=None):
        self.golden = Path(golden)
        self.sha = sha or _sha(golden)

    def manifest(self):
        return {"path": str(self.golden), "bytes": self.golden.stat().st_size,
                "rows": count_rows(self.golden.read_bytes()),
                "sha256": self.sha, "sentinel": SENTINEL,
                "generator": "stub"}


def _cfg(tmp_path):
    cfg = load_config(None)
    cfg["bench_root"] = str(tmp_path / "bench")
    cfg["results_dir"] = str(tmp_path / "bench" / "results")
    cfg["benchmarks"] = {}
    return cfg


def _engine_reg(tmp_path, monkeypatch, golden, stub_sha=None):
    reg = discover(_cfg(tmp_path))
    reg.fixtures["session-10mib"] = StubFixture(golden, sha=stub_sha)
    product = FakeProduct({"layout": reg.layout, "product": {}, "mock": {}})
    reg.products["fake"] = product
    import bench.trials as trials_mod
    monkeypatch.setattr(trials_mod, "gate_idle", lambda cfg, tag="": None)
    monkeypatch.setattr(trials_mod, "node_is_busy", lambda cfg: None)
    return reg


def _measure_ok(product, ctx, record, driver, fixture=None):
    app = product.launch(ctx, driver, resume_fixture=str(fixture) if fixture else None)
    app.kill_tree()
    record["metrics"] = {"launch_to_ready_ms": 10.0, "typing_ms": [1.0],
                         "typing_ok": True}
    record["validation"] = {"sentinel": True, "echoed": True, "erased": True}


# ---- staging primitive -------------------------------------------------------

def test_stage_clones_byte_exact_and_verifies_golden(tmp_path):
    golden = _golden(tmp_path)
    dest = tmp_path / "trial" / "sessions" / "corpus.jsonl"
    ev = stage_trial_fixture(golden, dest, _sha(golden))
    assert ev["path"] == str(dest)
    assert ev["sha256"] == _sha(golden)
    assert ev["bytes"] == golden.stat().st_size
    assert ev["rows"] == 4
    assert dest.read_bytes() == golden.read_bytes()
    # the clone is a real independent FILE (no hardlink: an in-place append
    # through a hardlink would mutate the golden inode)
    assert dest.stat().st_ino != golden.stat().st_ino
    # and it is writable: the resumed product appends to it
    with open(dest, "a") as f:
        f.write("{}\n")
    assert _sha(dest) != _sha(golden)
    # no torn temp file left behind
    assert [p.name for p in dest.parent.iterdir()] == ["corpus.jsonl"]


def test_golden_pollution_fails_stage_without_overwrite(tmp_path):
    golden = _golden(tmp_path)
    manifest_sha = _sha(golden)
    polluted = golden.read_bytes() + b'{"type": "message", "id": "x"}\n'
    golden.write_bytes(polluted)  # the incident: 7391 rows -> 7418 rows
    dest = tmp_path / "trial" / "sessions" / "corpus.jsonl"
    with pytest.raises(FixtureSourceError, match="polluted"):
        stage_trial_fixture(golden, dest, manifest_sha)
    # the source is NOT overwritten or reset from inside the trial path
    assert golden.read_bytes() == polluted
    # and no clone was staged for a failed verification
    assert not dest.exists()


def test_staged_clone_mismatch_refused(tmp_path, monkeypatch):
    """A torn/incorrect copy must never reach a launch (defense in depth:
    the staged bytes are re-read and re-verified against the golden hash)."""
    golden = _golden(tmp_path)
    dest = tmp_path / "trial" / "sessions" / "corpus.jsonl"
    real_read = Path.read_bytes

    def torn_read(self):
        data = real_read(self)
        if self.name == "corpus.jsonl" and self.parent.name == "sessions":
            return data[:-1]  # the bytes that landed on disk are torn
        return data

    monkeypatch.setattr(Path, "read_bytes", torn_read)
    with pytest.raises(FixtureSourceError, match="torn copy"):
        stage_trial_fixture(golden, dest, _sha(golden))
    assert not dest.exists()  # the refused copy is removed


# ---- the incident mechanics: append modifies the clone, not the golden ----

def test_loaded_session_append_modifies_clone_golden_unchanged(tmp_path):
    golden = _golden(tmp_path)
    golden_sha = _sha(golden)
    dest = tmp_path / "trial" / "sessions" / "corpus.jsonl"
    ev = stage_trial_fixture(golden, dest, golden_sha)
    # the resumed product appends live events to the clone IN PLACE
    live_line = json.dumps({"type": "message", "id": "live"}) + "\n"
    with open(dest, "a") as f:
        f.write(live_line)
    post = clone_post_evidence(dest)
    assert post["post_sha256"] != ev["sha256"]        # the append is visible
    assert post["post_rows"] == ev["rows"] + 1
    assert post["post_bytes"] == ev["bytes"] + len(live_line.encode())
    # the golden source never changed: this is the whole fix
    assert _sha(golden) == golden_sha
    assert golden.read_bytes().count(b"\n") == 4
    # post drift is EVIDENCE, not a validation failure: a row whose record
    # keeps its pre-launch proof stays valid (validation block intact)
    row = {"fixture": {"sha256": golden_sha, "clone": dict(ev, **post)},
           "validation": {"sentinel": True, "echoed": True, "erased": True},
           "validated": True}
    from bench.analysis.validity import fixture_clone_proven
    assert fixture_clone_proven(row) == "proven"   # pre proof + golden equality


def test_two_sequential_trials_stage_identical_clones_from_one_golden(tmp_path):
    """Two trials in a row: the first product append lands in ITS clone; the
    second trial stages a fresh byte-exact clone from the untouched golden
    — identical pre-hash both times, golden unchanged."""
    golden = _golden(tmp_path)
    golden_sha = _sha(golden)
    trial_dir = tmp_path / "t1"
    trial_dir.mkdir()
    ctx = FakeProduct({"layout": None, "product": {}, "mock": {}}).new_trial(trial_dir)
    ev1 = stage_trial_fixture(golden, ctx["trial_dir"] / "sessions" / "corpus.jsonl",
                             golden_sha)
    with open(ev1["path"], "a") as f:  # trial 1's product appended
        f.write("{}\n")
    trial2 = tmp_path / "t2"
    ev2 = stage_trial_fixture(golden, trial2 / "sessions" / "corpus.jsonl",
                              golden_sha)
    assert ev1["sha256"] == ev2["sha256"] == golden_sha
    assert Path(ev2["path"]).read_bytes() == golden.read_bytes()
    assert _sha(golden) == golden_sha  # still untouched after both trials


# ---- trial engine: clones staged, evidence on the row ------------------------

def test_run_trials_stages_clones_and_carries_actual_hash(tmp_path, monkeypatch):
    reg = _engine_reg(tmp_path, monkeypatch, golden := _golden(tmp_path))
    golden_sha = _sha(golden)
    scroll = reg.benchmark("compare.scroll_typing")
    scroll.measure = _measure_ok
    out_dir = tmp_path / "results"
    out_dir.mkdir()
    from bench.trials import run_trials
    jsonl = run_trials(reg, FakeDriver(), "compare.scroll_typing", ["fake"], 2,
                       out_dir, {"session-10mib": golden}, aa=False, phase_tag="w1")
    rows = [json.loads(l) for l in jsonl.read_text().splitlines()]
    assert len(rows) == 2
    for row in rows:
        fx = row["fixture"]
        assert fx["sha256"] == golden_sha                 # golden manifest claim
        clone = fx["clone"]
        assert clone["sha256"] == golden_sha              # ACTUAL staged bytes
        assert clone["rows"] == 4
        assert clone["path"].startswith(str(out_dir.parent))  # inside the trial tree
        # the product resumed the CLONE, never the shared golden
        assert row["product"] == "fake"
    product = reg.product("fake")
    assert len(product.resume_paths) == 2
    for p in product.resume_paths:
        assert p != str(golden)
        assert Path(p).name == "corpus.jsonl"
    # the live append landed in the clones (post evidence), golden untouched
    for row in rows:
        clone = row["fixture"]["clone"]
        assert clone["post_sha256"] != clone["sha256"]    # the product wrote
        assert clone["post_rows"] == clone["rows"] + 1
    assert _sha(golden) == golden_sha
    # per-row manifest verification passes for both rows
    from bench.analysis.validity import row_exclusion
    gate = {"compare.scroll_typing": {"requires_fixture": "session-10mib",
                                      "applicable_products": None,
                                      "completeness_keys": ("typing_ok",)}}
    assert all(row_exclusion(r, {}, gate) is None for r in rows)


def test_run_trials_polluted_golden_fails_rows_without_launch(tmp_path, monkeypatch):
    golden = _golden(tmp_path)
    manifest_sha = _sha(golden)   # the persisted manifest predates the mutation
    reg = _engine_reg(tmp_path, monkeypatch, golden, stub_sha=manifest_sha)
    golden.write_bytes(golden.read_bytes() + b'{"live": true}\n')  # mid-wave mutation
    scroll = reg.benchmark("compare.scroll_typing")
    scroll.measure = _measure_ok
    out_dir = tmp_path / "results"
    out_dir.mkdir()
    from bench.trials import run_trials
    jsonl = run_trials(reg, FakeDriver(), "compare.scroll_typing", ["fake"], 1,
                       out_dir, {"session-10mib": golden}, aa=False, phase_tag="w1")
    rows = [json.loads(l) for l in jsonl.read_text().splitlines()]
    assert len(rows) == 1
    row = rows[0]
    assert "FixtureSourceError" in row["error"]
    assert "polluted" in row["error"]
    # no launch happened: the product never received a resume path
    assert reg.product("fake").resume_paths == []
    # the source stays as-is (evidence), never reset from inside a trial
    assert golden.read_bytes().endswith(b'{"live": true}\n')


def test_trial_session_dir_is_the_product_native_sessions_dir(tmp_path):
    """The clone stages into each product's isolated trial session path:
    Prime Agent's agent dir (agent/sessions) for rust AND ts — the same
    hook, so adapter protocol parity is structural."""
    product = PrimeAgentRustProduct({"layout": None,
                                    "product": {"binary": "/bin/true"},
                                    "mock": {}})
    ctx: TrialContext = {"trial_dir": tmp_path / "t", "home": tmp_path / "t" / "home",
                        "work": tmp_path / "t" / "work", "tmp": tmp_path / "t" / "tmp",
                        "agent_dir": tmp_path / "t" / "agent",
                        "daemon_socket": None}
    assert product.trial_session_dir(ctx) == tmp_path / "t" / "agent" / "sessions"
    ctx["agent_dir"] = None  # generic fallback for products without one
    assert product.trial_session_dir(ctx) == tmp_path / "t" / "sessions"
    # ts is wire-compatible: same session dir, same --resume argv contract
    ts = PrimeAgentTsProduct({"layout": None, "product": {"binary": "/bin/true"},
                              "mock": {}})
    ctx["agent_dir"] = tmp_path / "ts-agent"
    clone = ts.trial_session_dir(ctx) / "corpus.jsonl"
    argv = ts.argv(ctx, str(clone))
    assert argv[-2:] == ["--resume", str(clone)]
    rust_argv = product.argv(ctx, str(clone))
    assert rust_argv[-2:] == ["--resume", str(clone)]
    # the staged clone path is what reaches argv (bench.trials stages into
    # trial_session_dir and never passes the shared golden to any product)


# ---- the validity gate: per-row manifest verification ------------------------

# NOTE (fixture-layer scope): the golden-source hardening at the fixture
# layer (read-only built artifact, ensure() failing loudly on a polluted
# golden, the explicit bench fixtures --reset) belongs to the fixture
# generator owner (session_size.py) and is intentionally NOT in this
# branch to avoid collisions with the fixture-v3 worker. This branch's
# load-bearing gate is the per-trial one: stage_trial_fixture verifies
# the golden against its manifest on EVERY trial and refuses to launch
# on any drift, whatever the file's mode is.

def _clone_row(bench, product, clone_sha, golden_sha, typing_ok=True,
               sentinel=True, **extra):
    row = {"benchmark": bench, "product": product, "phase": "w1",
           "fixture": {"loaded": sentinel, "sha256": golden_sha,
                       "clone": {"sha256": clone_sha, "rows": 4, "bytes": 100,
                                 "path": "/trial/sessions/corpus.jsonl"}},
           "metrics": {"typing_ms": [1.0], "typing_ok": typing_ok,
                       "launch_to_ready_ms": 10.0},
           "validated": True,
           "validation": {"sentinel": sentinel, "echoed": True, "erased": True},
           "comparability": "equivalent"}
    row.update(extra)
    return row


def test_clone_proven_rows_rank():
    """A clone-proven row on a fixture benchmark ranks on the completion
    boundary under a complete strict campaign: the derived
    max(ready, sentinel) value from its own timestamps (the historical
    rows' back-fill path) plus the byte proof plus an A/A pass that
    calibrates the same derived boundary (spread-stable halves)."""
    from bench.analysis.aggregate import summarize_rows
    GOLD = "d" * 64
    rows = []
    for i, ready in enumerate((751.0, 752.0)):
        rows.append({"benchmark": "session.cold_open_10mib", "product": "ts",
                     "phase": "w1", "trial": i,
                     "fixture": {"loaded": True, "sha256": GOLD,
                                 "clone": {"sha256": GOLD}},
                     "metrics": {"launch_to_ready_ms": ready,
                                 "launch_to_sentinel_ms": 2507.0},
                     "validated": True,
                     "validation": {"sentinel": True, "echoed": True,
                                    "erased": True},
                     "comparability": "equivalent"})
    for i in range(4):            # A/A on the derived boundary, spread-stable
        rows.append({"benchmark": "session.cold_open_10mib", "product": "ts",
                     "phase": "aa", "trial": i,
                     "fixture": {"loaded": True, "sha256": GOLD,
                                 "clone": {"sha256": GOLD}},
                     "metrics": {"launch_to_ready_ms": 751.0,
                                 "launch_to_sentinel_ms": 2507.0},
                     "validated": True,
                     "validation": {"sentinel": True, "echoed": True,
                                    "erased": True},
                     "comparability": "equivalent"})
    gate = {"session.cold_open_10mib": {"requires_fixture": "session-10mib",
                                        "applicable_products": None,
                                        "completeness_keys": ()}}
    cfg = {"product_order": ["ts"], "display": {"ts": "Prime Agent TS"},
           "aa": {"spread_threshold_pct": 10.0, "drift_threshold_pct": 10.0,
                  "required": True, "trials": 4,
                  "expected_products": ["ts"]},
           "gate_benchmarks": gate}
    model = summarize_rows(rows, cfg)
    entry = model["summary"]["session.cold_open_10mib"]
    assert entry["primary_p50s"] == {"ts": 2507.0}    # boundary derived + ranked
    assert entry["ranks"] == {"ts": 1}
    assert entry["comparability"]["ts"] == "equivalent"


def test_fixture_mismatch_becomes_invalid_never_ranks():
    """manifest per-row verifies actual clone: clone sha != golden sha ->
    excluded as fixture_hash_mismatch (the mutated-golden row class)."""
    from bench.analysis.aggregate import summarize_rows
    GOLD, DRIFT = "d" * 64, "8" * 64
    rows = [_clone_row("compare.scroll_typing", "rust", DRIFT, GOLD)]
    gate = {"compare.scroll_typing": {"requires_fixture": "session-10mib",
                                     "applicable_products": None,
                                     "completeness_keys": ("typing_ok",)}}
    cfg = {"product_order": ["rust"], "display": {"rust": "Prime Agent Rust"},
           "aa": {"spread_threshold_pct": 10.0}, "gate_benchmarks": gate}
    model = summarize_rows(rows, cfg)
    entry = model["summary"]["compare.scroll_typing"]
    assert entry["products"] == {}
    assert entry["excluded"]["rust"]["reasons"]["fixture_hash_mismatch"] == 1


def test_no_clone_evidence_is_a_loud_exclusion():
    """The historical class: fixture rows with no per-row clone proof are
    unrankable and the exclusion is VISIBLE (reason + count), never silent."""
    from bench.analysis.aggregate import summarize_rows
    GOLD = "d" * 64
    rows = [{"benchmark": "compare.scroll_typing", "product": "rust",
             "phase": "w1", "fixture": {"loaded": True, "sha256": GOLD},
             "metrics": {"typing_ms": [1.0], "typing_ok": True},
             "validated": True,
             "validation": {"sentinel": True, "echoed": True, "erased": True}}]
    gate = {"compare.scroll_typing": {"requires_fixture": "session-10mib",
                                     "applicable_products": None,
                                     "completeness_keys": ("typing_ok",)}}
    cfg = {"product_order": ["rust"], "display": {"rust": "Prime Agent Rust"},
           "aa": {"spread_threshold_pct": 10.0}, "gate_benchmarks": gate}
    model = summarize_rows(rows, cfg)
    entry = model["summary"]["compare.scroll_typing"]
    assert entry["products"] == {}
    assert entry["excluded"]["rust"]["reasons"]["fixture_no_clone_evidence"] == 1


def test_clone_proven_incomplete_row_excluded():
    """Clone-proven + render-proven, but a dropped key: the row reaches the
    completeness check and is excluded as incomplete_measurement."""
    from bench.analysis.validity import row_exclusion
    GOLD = "d" * 64
    row = _clone_row("compare.scroll_typing", "ts", GOLD, GOLD, typing_ok=False)
    gate = {"compare.scroll_typing": {"requires_fixture": "session-10mib",
                                     "applicable_products": None,
                                     "completeness_keys": ("typing_ok",)}}
    assert row_exclusion(row, {}, gate) == "incomplete_measurement"
