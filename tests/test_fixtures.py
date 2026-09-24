"""Fixture generators: byte-exact goldens and tree shape."""
from __future__ import annotations

import json

from bench.adapters.fixtures.session_size import build_session
from bench.adapters.fixtures.subagent_tree import (level_counts, write_tree)

# The 10MiB fixture as built on the benchmark node (manifest-10mib.json).
# cwd is embedded in the session header, so the golden pins it.
NODE_CWD = "/home/ubuntu/bench/fixtures/work"
NODE_SHA256 = "f8d7fba0e81a972a5c31eb205a2ba23702ebf294c2b9db49ab42f63e783bc90a"
#: v3 (product-parity digest rows): same size/seed, its own corpus+golden
V3_SHA256 = "4b580429dc97bd317c21ef85821ab5a85cb639d5067a9e8f25eca01b374aa7be"
V3_ROWS = 7330
V3_DIGEST_ROWS = 130


def test_session_10mib_is_byte_exact(tmp_path):
    info = build_session(10.0, tmp_path / "corpus.jsonl", cwd=NODE_CWD)
    assert info["bytes"] == 10 * (1 << 20)
    assert info["rows"] == 7391
    assert info["sha256"] == NODE_SHA256
    assert info["fixture_version"] == 2
    # v2 keeps the historical digest shape: no visibility fields at all
    rows = [json.loads(l) for l in (tmp_path / "corpus.jsonl").read_text().splitlines()]
    digests = [r for r in rows if r.get("customType") == "harness_digest"]
    assert len(digests) == 131
    assert all("display" not in r and "details" not in r for r in digests)


def test_session_10mib_v3_is_byte_exact_with_product_parity_digest_rows(tmp_path):
    """v3: harness_digest rows persist display:false + details.digest like
    both real products (TS createHarnessDigestMessage / Rust
    harness_digest_prompt_row), so replay renders no digest panels."""
    info = build_session(10.0, tmp_path / "corpus-v3.jsonl", cwd=NODE_CWD,
                         digest_display=False)
    assert info["bytes"] == 10 * (1 << 20)
    assert info["rows"] == V3_ROWS
    assert info["sha256"] == V3_SHA256
    assert info["fixture_version"] == 3
    assert info["sha256"] != NODE_SHA256  # v3 is its own corpus, not a v2 edit
    rows = [json.loads(l) for l in (tmp_path / "corpus-v3.jsonl").read_text().splitlines()]
    digests = [r for r in rows if r.get("customType") == "harness_digest"]
    assert len(digests) == V3_DIGEST_ROWS
    assert all(r["display"] is False for r in digests)
    assert all(r["details"]["digest"] in r["content"] for r in digests)
    # only the digest rows carry visibility fields; message rows stay bare
    assert all("display" not in r for r in rows if r.get("type") == "message")


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
