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
# - v3 canonical (same 7391-row corpus shape; every harness_digest row
#   persists display:false plus the raw digest in details, exactly like
#   real TS/Rust session files (TS createHarnessDigestMessage
#   messages.ts:141-153; Rust harness_digest_prompt_row /
#   persist_digest harness_digest.rs:117-145) — the v2 rows omitted the
#   keys and product renderers fall back to visible, so all 131 digest
#   rows rendered as visible custom panels):
#   691d1ea772fa25f77a7aa07d7f57e69d7d29739a61d873e5efcfd9e3505de70a
CANONICAL_SHA256 = "dadaecfcac511e24ed0e0df15fb1facbe556557856486d62bad628250194cdda"
CANONICAL_V3_SHA256 = "691d1ea772fa25f77a7aa07d7f57e69d7d29739a61d873e5efcfd9e3505de70a"
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


def test_session_10mib_v3_is_byte_exact_with_hidden_digests(tmp_path):
    """The v3 golden: the display-corrected corpus — same 7391-row shape,
    every harness_digest row persisted hidden exactly like real product
    session files."""
    from bench.adapters.fixtures.session_size import GENERATOR_V3
    info = build_session(10.0, tmp_path / "corpus-v3.jsonl", generator=GENERATOR_V3)
    assert info["bytes"] == 10 * (1 << 20)
    assert info["rows"] == 7391
    assert info["sha256"] == CANONICAL_V3_SHA256
    assert info["generator"] == "session-size/3"
    assert info["cwd"] == FIXTURE_SESSION_CWD
    assert info["sentinel"] == "CORPUS-TAIL-9f3a1c70"
    digests = 0
    first_user = None
    last_text = None
    for line in open(tmp_path / "corpus-v3.jsonl"):
        row = json.loads(line)
        if row.get("type") == "custom_message" and row.get("customType") == "harness_digest":
            # full product-parity row: hidden AND carrying the raw digest
            assert row["display"] is False
            assert row["details"]["digest"] == \
                row["content"][len("[harness-digest] "):]
            digests += 1
        else:
            # message rows stay bare — no visibility keys outside digests
            assert "display" not in row and "details" not in row
        if (row.get("type") == "message" and row.get("message", {}).get("role") == "user"
                and first_user is None):
            first_user = row["message"]["content"][0]["text"]
        if row.get("type") == "message":
            texts = [p["text"] for p in row["message"].get("content", [])
                     if p.get("type") == "text"]
            if texts:
                last_text = texts[0]
    assert digests == 131
    # the roster-row identity source and the visible tail sentinel survive
    assert first_user == "please do task number 0"
    assert "CORPUS-TAIL-9f3a1c70" in last_text


def test_session_v3_is_v2_plus_digest_parity_only(tmp_path):
    """The semantic-repair contract: v3 differs from the immutable v2
    golden ONLY by the visibility fields on digest rows (display + the
    details digest; plus the sentinel pad that absorbs those bytes) —
    same 7391 rows, same ids, same corpus."""
    from bench.adapters.fixtures.session_size import GENERATOR_V3
    v2 = build_session(10.0, tmp_path / "v2.jsonl")
    v3 = build_session(10.0, tmp_path / "v3.jsonl", generator=GENERATOR_V3)
    assert v2["sha256"] == CANONICAL_SHA256
    lines2 = open(tmp_path / "v2.jsonl").read().splitlines()
    lines3 = open(tmp_path / "v3.jsonl").read().splitlines()
    assert len(lines2) == len(lines3) == 7391
    for i, (b, c) in enumerate(zip(lines2, lines3)):
        r2, r3 = json.loads(b), json.loads(c)
        assert (r2["type"], r2["id"], r2.get("parentId"), r2.get("timestamp")) == \
               (r3["type"], r3["id"], r3.get("parentId"), r3.get("timestamp"))
        if b == c:
            continue
        if r2.get("customType") == "harness_digest":
            assert "display" not in r2 and "details" not in r2
            assert r3["display"] is False
            assert r3["details"] == \
                {"digest": r3["content"][len("[harness-digest] "):]}
            sans = lambda r: {k: v for k, v in r.items()
                              if k not in ("display", "details")}
            assert sans(r2) == sans(r3)
        else:
            # the sentinel pad row alone absorbs the visibility-field bytes
            assert i == len(lines2) - 1


def test_session_v3_is_path_independent(tmp_path):
    """The reproducibility gate applied to v3: two distinct fresh roots
    yield the byte-identical v3 golden."""
    from bench.adapters.fixtures.session_size import GENERATOR_V3
    one = build_session(10.0, tmp_path / "fresh-root-a" / "corpus.jsonl",
                        generator=GENERATOR_V3)
    two = build_session(10.0, tmp_path / "an-entirely-different-root-b" / "corpus.jsonl",
                        generator=GENERATOR_V3)
    assert one["sha256"] == two["sha256"] == CANONICAL_V3_SHA256


def test_registry_session_10mib_v3_entry(tmp_path):
    """session-10mib-v3 registers alongside the immutable v2 entry with
    its own artifact and manifest, and ensure() builds it byte-exact."""
    from bench.core.config import load_config
    from bench.core.registry import discover
    cfg = load_config(None)
    cfg["bench_root"] = str(tmp_path / "bench")
    cfg["results_dir"] = str(tmp_path / "bench" / "results")
    reg = discover(cfg)
    assert set(reg.fixtures) >= {"session-10mib", "session-10mib-v3", "subagent-tree"}
    v3 = reg.fixture("session-10mib-v3")
    assert v3.path().name == "scale-corpus-10mib-v3.jsonl"
    assert v3.manifest_name == "manifest-10mib-v3.json"
    v2 = reg.fixture("session-10mib")
    assert v2.path().name == "scale-corpus-10mib.jsonl"
    v2.ensure()  # build the historical artifact first
    info = v3.ensure()
    assert info["generator"] == "session-size/3"
    assert info["bytes"] == 10 * (1 << 20)
    assert info["sha256"] == CANONICAL_V3_SHA256
    assert v3.validate(CANONICAL_V3_SHA256) is True
    # no source mutation: building v3 never touches the v2 artifact or
    # its manifest — v2 historical rows keep referring to their own
    # immutable golden, never v3's
    assert v2.validate(CANONICAL_SHA256) is True
    assert v2.manifest_name == "manifest-10mib.json"
    assert v2.manifest()["generator"] == "session-size/2"


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
    corpus_v3 = (tmp_path / "fresh-bench" / "fixtures" / "scale-corpus-10mib-v3.jsonl")
    assert corpus_v3.exists()
    assert corpus_v3.stat().st_size == 10 * (1 << 20)
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
