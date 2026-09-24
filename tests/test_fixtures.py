"""Fixture generators: byte-exact goldens and tree shape."""
from __future__ import annotations

import json

from bench.adapters.fixtures.session_size import build_session
from bench.adapters.fixtures.subagent_tree import (level_counts, write_tree)

# The 10MiB fixture as built on the benchmark node (manifest-10mib.json).
# cwd is embedded in the session header, so the golden pins it.
NODE_CWD = "/home/ubuntu/bench/fixtures/work"
NODE_SHA256 = "f8d7fba0e81a972a5c31eb205a2ba23702ebf294c2b9db49ab42f63e783bc90a"


def test_session_10mib_is_byte_exact(tmp_path):
    info = build_session(10.0, tmp_path / "corpus.jsonl", cwd=NODE_CWD)
    assert info["bytes"] == 10 * (1 << 20)
    assert info["rows"] == 7391
    assert info["sha256"] == NODE_SHA256


def test_session_exact_bytes_small(tmp_path):
    info = build_session(1.0, tmp_path / "small.jsonl", cwd=NODE_CWD)
    assert info["bytes"] == 1 * (1 << 20)


def test_subagent_tree_shape(tmp_path):
    manifest = write_tree(tmp_path / "tree", n=6, active=2, depth=2, seed=1234,
                          cwd=NODE_CWD)
    files = manifest["files"]
    assert "root.jsonl" in files
    assert level_counts(6, 2) == [3, 3]
    sub_files = [f for f in files if f != "root.jsonl"]
    assert len(sub_files) == 6
    assert manifest["tree_sha256"]
    # determinism: same spec, same tree hash
    m2 = write_tree(tmp_path / "tree2", n=6, active=2, depth=2, seed=1234,
                    cwd=NODE_CWD)
    assert m2["tree_sha256"] == manifest["tree_sha256"]


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
