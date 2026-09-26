"""Fixture generators: byte-exact goldens, path independence, tree shape."""
from __future__ import annotations

import json

from bench.adapters.fixtures.corpus import FIXTURE_SESSION_CWD
from bench.adapters.fixtures.session_size import build_session
from bench.adapters.fixtures.subagent_tree import (level_counts, write_tree)

# The canonical 10MiB fixture, generator v2 (session-size/2).
#
# SHA history (recorded openly — historical artifacts are never silently
# relabeled):
# - v1 campaign canonical: f8d7fba0e81a972a5c31eb205a2ba23702ebf294c2b9db49ab42f63e783bc90a
#   (recorded cwd = the benchmark node's absolute fixtures/work path)
# - the 2026-09-24 sandbox smoke produced 8f8979d901de...: the same seed,
#   a different absolute cwd (/root/bench-root/fixtures/work) — the path
#   dependence this generator version fixes.
# - v2 canonical (recorded cwd = FIXTURE_SESSION_CWD on every host):
#   dadaecfcac511e24ed0e0df15fb1facbe556557856486d62bad628250194cdda
CANONICAL_SHA256 = "dadaecfcac511e24ed0e0df15fb1facbe556557856486d62bad628250194cdda"
# the historical v1 values remain asserted so a v1-built tree is never
# confused with the v2 canonical
V1_NODE_SHA256 = "f8d7fba0e81a972a5c31eb205a2ba23702ebf294c2b9db49ab42f63e783bc90a"
V1_NODE_CWD = "/home/ubuntu/bench/fixtures/work"


def test_session_10mib_is_byte_exact(tmp_path):
    info = build_session(10.0, tmp_path / "corpus.jsonl")
    assert info["bytes"] == 10 * (1 << 20)
    assert info["rows"] == 7391
    assert info["sha256"] == CANONICAL_SHA256
    assert info["generator"] == "session-size/2"
    assert info["cwd"] == FIXTURE_SESSION_CWD
    # the deliberate v2 switch is visible, never silent
    assert CANONICAL_SHA256 != V1_NODE_SHA256


def test_session_fixture_is_path_independent(tmp_path):
    """The 2026-09-24 reproducibility gate: two distinct bench roots must
    yield byte-identical fixtures (same sha256) — the v1 generator baked
    the host's absolute cwd into the session header and the golden hash
    silently changed per sandbox."""
    one = build_session(1.0, tmp_path / "root-a" / "corpus.jsonl")
    two = build_session(1.0, tmp_path / "completely-different-root-b" / "corpus.jsonl")
    assert one["sha256"] == two["sha256"]
    ten_a = build_session(10.0, tmp_path / "root-a" / "corpus10.jsonl")
    ten_b = build_session(10.0, tmp_path / "root-b" / "corpus10.jsonl")
    assert ten_a["sha256"] == ten_b["sha256"] == CANONICAL_SHA256
    # the recorded session cwd exists on this host (resume semantics)
    import os
    assert os.path.isdir(FIXTURE_SESSION_CWD)


def test_session_exact_bytes_small(tmp_path):
    info = build_session(1.0, tmp_path / "small.jsonl")
    assert info["bytes"] == 1 * (1 << 20)


def test_session_fixture_restores_mutated_artifact(tmp_path):
    from bench.adapters.fixtures.session_size import SessionSizeCompactedFixture, SessionSizeFixture
    from bench.core.env import BenchLayout

    for cls in (SessionSizeFixture, SessionSizeCompactedFixture):
        layout = BenchLayout.from_config({"bench_root": str(tmp_path / cls.name), "results_dir": str(tmp_path / cls.name / "results")})
        fixture = cls({"layout": layout, "fixture": {"size_mib": 1.0}})
        original = fixture.ensure()
        fixture.path().write_bytes(fixture.path().read_bytes() + b"mutated\n")
        restored = fixture.ensure()
        assert restored == original
        assert fixture.path().stat().st_size == original["bytes"]
        assert fixture.validate(original["sha256"])


def test_subagent_tree_shape(tmp_path):
    manifest = write_tree(tmp_path / "tree", n=6, active=2, depth=2, seed=1234)
    files = manifest["files"]
    assert "root.jsonl" in files
    assert level_counts(6, 2) == [3, 3]
    sub_files = [f for f in files if f != "root.jsonl"]
    assert len(sub_files) == 6
    assert manifest["tree_sha256"]
    # determinism: same spec, same tree hash — from ANY host path
    m2 = write_tree(tmp_path / "tree2", n=6, active=2, depth=2, seed=1234)
    assert m2["tree_sha256"] == manifest["tree_sha256"]
    m3 = write_tree(tmp_path / "an-entirely-different-root" / "t3",
                    n=6, active=2, depth=2, seed=1234)
    assert m3["tree_sha256"] == manifest["tree_sha256"]
    assert manifest["generator"] == "subagent-tree/2"
    assert manifest["spec"]["cwd"] == FIXTURE_SESSION_CWD


def test_bench_fixtures_command_on_a_fresh_root(tmp_path, capsys):
    """`bench fixtures` must be self-sufficient on a bench root that does
    not exist yet (the live smoke found the command assumed a pre-made
    layout fixtures dir)."""
    from bench.cli import cmd_fixtures
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(f"bench_root: {tmp_path / 'fresh-bench'}\n"
                        f"results_dir: {tmp_path / 'fresh-bench' / 'results'}\n")
    cmd_fixtures(type("Args", (), {"fixture": None, "config": str(cfg_path)})())
    out = capsys.readouterr().out
    assert "10485760 bytes 7391 rows" in out
    corpus = (tmp_path / "fresh-bench" / "fixtures" / "scale-corpus-10mib.jsonl")
    assert corpus.exists()
    assert corpus.stat().st_size == 10 * (1 << 20)
    assert (tmp_path / "fresh-bench" / "fixtures" / "subagent-tree-n24").is_dir()


def test_registry_fixture_ensure(tmp_path):
    from bench.core.config import load_config
    from bench.core.registry import discover
    cfg = load_config(None)
    cfg["bench_root"] = str(tmp_path / "bench")
    cfg["results_dir"] = str(tmp_path / "bench" / "results")
    reg = discover(cfg)
    fixture = reg.fixture("subagent-tree")
    info = fixture.ensure()
    assert fixture.path().exists()
    assert fixture.validate(info["tree_sha256"]) is True
