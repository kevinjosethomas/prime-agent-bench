"""The v4 representative session fixture: golden, gates, wire invariants.

The spec of record (metadata-only aggregates + gates) lives in
bench/adapters/fixtures/session_v4_spec.py; these tests re-derive every
gate INDEPENDENTLY from the built file bytes.
"""
from __future__ import annotations

import json
import math

import pytest

from bench.adapters.fixtures import session_v4_spec as spec
from bench.adapters.fixtures.session_v4 import (FIXTURE_SESSION_CWD_V4,
                                                 GENERATOR_V4,
                                                 build_session_v4)

#: the v4 canonical golden (seed 1234, 10MiB, marathon-conditioned sample)
CANONICAL_V4_SHA256 = ("5fa6e1932511a8a4084c06204c5dd647dcc349235925c"
                       "ab3c8b69a5483c63bba")
CANONICAL_V4_ROWS = 4411
#: the immutable v3 stress golden (must never change under v4 work)
CANONICAL_V3_SHA256 = "691d1ea772fa25f77a7aa07d7f57e69d7d29739a61d873e5efcfd9e3505de70a"
CANONICAL_V2_SHA256 = "dadaecfcac511e24ed0e0df15fb1facbe556557856486d62bad628250194cdda"


@pytest.fixture(scope="module")
def golden(tmp_path_factory):
    """The canonical v4 build, shared by every test in this module."""
    path = tmp_path_factory.mktemp("v4") / "scale-corpus-10mib-v4.jsonl"
    info = build_session_v4(10.0, path)
    return path, info


def _rows_and_sizes(path):
    data = path.read_bytes()
    lines = data.decode().split("\n")
    rows = [json.loads(line) for line in lines[:-1]]
    sizes = [len(line) + 1 for line in lines[:-1]]
    return data, rows, sizes


def test_canonical_golden_is_exact_and_byte_stable(tmp_path):
    info = build_session_v4(10.0, tmp_path / "a-root" / "corpus.jsonl")
    assert info["bytes"] == 10 * (1 << 20)
    assert info["rows"] == CANONICAL_V4_ROWS
    assert info["sha256"] == CANONICAL_V4_SHA256
    assert info["generator"] == GENERATOR_V4 == "session-size/4"
    assert info["cwd"] == FIXTURE_SESSION_CWD_V4
    assert info["sentinel"] == "CORPUS-TAIL-9f3a1c70"
    # path independence: a different root, same bytes
    again = build_session_v4(10.0, tmp_path / "entirely-other-root" / "c.jsonl")
    assert again["sha256"] == CANONICAL_V4_SHA256
    import os
    assert os.path.isdir(FIXTURE_SESSION_CWD_V4)


def test_no_giant_padded_row(golden):
    """The anti-v3 property: no row carries a pathological byte share."""
    _, rows, sizes = _rows_and_sizes(golden[0])
    total = sum(sizes)
    assert max(sizes) <= spec.CAP_OUTLIER_ROW_BYTES
    # the documented outlier tier: exactly 2 rows in the 128-256KB bucket
    big = [s for s in sizes if s > 128 * 1024]
    assert len(big) == spec.MARATHON_OUTLIER_ROWS_128K_256K
    # compaction rows sit in the 21-22K measured band
    compaction_sizes = [s for s, r in zip(sizes, rows) if r["type"] == "compaction"]
    assert all(s <= 26_000 for s in compaction_sizes)
    # top-0.1% of rows carry <= 10% of bytes (real pooled 5.8%; v3 was 40.9%)
    top = sorted(sizes, reverse=True)[:max(1, len(sizes) // 1000)]
    assert sum(top) / total <= spec.TOP_P001_BYTE_SHARE_MAX
    # the tail sentinel row is small and is the LAST assistant text row
    asst = [(s, r) for s, r in zip(sizes, rows)
            if r["type"] == "message" and r["message"]["role"] == "assistant"]
    sentinel_size, sentinel_row = asst[-1]
    texts = "".join(p["text"] for p in sentinel_row["message"]["content"]
                    if p["type"] == "text")
    assert "CORPUS-TAIL-9f3a1c70" in texts
    assert sentinel_size <= spec.SENTINEL_ROW_MAX_BYTES


def test_row_byte_distribution_matches_marathon_reference(golden):
    _, rows, sizes = _rows_and_sizes(golden[0])
    assert spec.ks_distance(sizes) <= spec.KS_D_MAX
    for q, tol in spec.QUANTILE_LOG2_TOL.items():
        realized = spec.quantile(sizes, {"p50": .50, "p75": .75,
                                        "p90": .90, "p99": .99}[q])
        assert abs(math.log2(realized) - math.log2(spec.MARATHON_ROW_BYTES[q])) <= tol
    assert spec.ROW_COUNT_BAND_10MIB[0] <= len(rows) <= spec.ROW_COUNT_BAND_10MIB[1]


def test_row_type_and_role_mix(golden):
    _, rows, sizes = _rows_and_sizes(golden[0])
    total = len(rows)
    counts = {}
    for r in rows:
        counts[r["type"]] = counts.get(r["type"], 0) + 1
    l1 = sum(abs(counts.get(k, 0) / total - s)
             for k, s in spec.MARATHON_ROW_TYPE_MIX.items())
    l1 += sum(v / total for k, v in counts.items()
              if k not in spec.MARATHON_ROW_TYPE_MIX)
    assert l1 <= spec.MIX_L1_MAX
    messages = [r for r in rows if r["type"] == "message"]
    roles = {}
    for r in messages:
        roles[r["message"]["role"]] = roles.get(r["message"]["role"], 0) + 1
    for role, share in spec.MARATHON_ROLE_MIX.items():
        assert abs(roles.get(role, 0) / len(messages) - share) <= spec.ROLE_SHARE_TOL
    stops = {}
    calls = errors = 0
    for r in messages:
        m = r["message"]
        if m["role"] == "assistant":
            stops[m["stopReason"]] = stops.get(m["stopReason"], 0) + 1
            calls += sum(1 for p in m["content"] if p["type"] == "toolCall")
        if m["role"] == "toolResult":
            errors += 1 if m["isError"] else 0
    assert stops["toolUse"] / sum(stops.values()) > 0.70
    assert stops["stop"] / sum(stops.values()) > 0.10
    assert errors >= 1 and errors / roles["toolResult"] < 0.01
    # toolcalls per assistant row stays within the measured max
    assert calls <= len([r for r in messages
                         if r["message"]["role"] == "assistant"]) * spec.MARATHON_TOOLCALLS_MAX
    compactions = counts.get("compaction", 0)
    assert spec.MARATHON_COMPACTIONS_10MIB_BAND[0] <= compactions <= 14


def test_wire_invariants(golden):
    """Schema-verified structural invariants, re-derived from the file."""
    _, rows, sizes = _rows_and_sizes(golden[0])
    assert rows[0]["type"] == "session" and rows[0]["version"] == 3
    assert rows[0]["cwd"] == FIXTURE_SESSION_CWD_V4
    assert rows[0]["rlmDepth"] == 0 and rows[0]["git"]["repoUrl"]
    assert sum(1 for r in rows if r["type"] == "session") == 1
    seen = set()
    previous = None
    last_ts = None
    calls, results = {}, {}
    for r in rows:
        if r["type"] != "session":
            assert r["parentId"] == previous
            previous = r["id"]
        assert r["id"] not in seen
        seen.add(r["id"])
        assert last_ts is None or r["timestamp"] > last_ts
        last_ts = r["timestamp"]
        if r["type"] == "message":
            m = r["message"]
            if m["role"] == "assistant":
                for part in m["content"]:
                    if part["type"] == "toolCall":
                        assert part["id"] not in calls
                        calls[part["id"]] = r
            elif m["role"] == "toolResult":
                results[m["toolCallId"]] = r
    assert set(calls) == set(results)
    call_index = {cid: next(i for i, r in enumerate(rows) if r is row)
                  for cid, row in calls.items()}
    for cid, row in results.items():
        assert next(i for i, r in enumerate(rows) if r is row) > call_index[cid]
    # the file ends on daemon-appended lifecycle rows (realistic final row)
    assert rows[-1]["type"] == "session_state"
    assert rows[-1]["state"]["status"] == "active"
    assert sum(1 for r in rows[-spec.MARATHON_TRAILING_ROWS:]
               if r["type"] != "message") == spec.MARATHON_TRAILING_ROWS


def test_hidden_harness_digest_rows(golden):
    _, rows, _ = _rows_and_sizes(golden[0])
    digests = [r for r in rows if r["type"] == "custom_message"
               and r.get("customType") == "harness_digest"]
    assert len(digests) == spec.MARATHON_HARNESS_DIGEST_ROWS
    for r in digests:
        assert r["display"] is False
        assert r["details"]["digest"] == r["content"][len("[harness-digest] "):]
        assert len(r["details"]["stateFingerprint"]) == 64
        assert spec.MARATHON_HARNESS_DIGEST_BYTES[0] <= len(r["details"]["digest"])


def test_registry_entry_and_v2_v3_unchanged(tmp_path):
    from bench.core.config import load_config
    from bench.core.registry import discover
    cfg = load_config(None)
    cfg["bench_root"] = str(tmp_path / "bench")
    cfg["results_dir"] = str(tmp_path / "bench" / "results")
    reg = discover(cfg)
    v4 = reg.fixture("session-10mib-v4")
    assert v4.path().name == "scale-corpus-10mib-v4.jsonl"
    assert v4.manifest_name == "manifest-10mib-v4.json"
    info = v4.ensure()
    assert info["generator"] == "session-size/4"
    assert info["bytes"] == 10 * (1 << 20)
    assert info["sha256"] == CANONICAL_V4_SHA256
    assert v4.validate(CANONICAL_V4_SHA256) is True
    assert v4.validate("deadbeef") is False
    # v2/v3 remain byte-identical: building v4 never touches them
    v2 = reg.fixture("session-10mib")
    v3 = reg.fixture("session-10mib-v3")
    v2.ensure()
    assert v2.validate(CANONICAL_V2_SHA256) is True
    v3.ensure()
    assert v3.validate(CANONICAL_V3_SHA256) is True
