"""A/A half balancing: the halves gate must compare like with like.

cmp-v4 W1 (compare.cold_start, campaign 1, VM tiequu6qsneqk9jxpwcdrw85,
2026-09-24) is the design evidence: the legacy even/odd halves aliased
with launch-occurrence position (every first-in-round launch in one
half, every second in the other) and with ABBA direction; claude's
~+40ms second-occurrence effect surfaced as a 13.8% spread and the
ranking was correctly withheld under the then-declared design. The
withholding stands — this suite is prospective design proof, never a
retroactive requalification of W1.

The suite proves, in order:
1. the half assignment is a pure function of the trial index, balanced
   over occurrence position and direction independent of any values;
2. a schedule-position effect of the observed claude scale does not
   masquerade as instability at the 20-trial calibration default (and
   still fails at 10 trials, which is why 20 is the default);
3. genuine non-schedule instability still fails the unchanged 10%
   threshold;
4. the real W1 A/A rows pass under balanced halves while the legacy
   pairing on the same rows reproduces the recorded 13.8% (incident
   record only).
"""
from __future__ import annotations

import json
from pathlib import Path

from bench.analysis.aa_validation import _aa_half, aa_validity

FIXTURE = Path(__file__).parent / "fixtures" / "aa_incident" / \
    "compare.cold_start-trials-aa-cmpv4w1.jsonl"


def _row(trial, ready_ms, product="claude", bench="compare.cold_start"):
    return {"benchmark": bench, "product": product, "trial": trial,
            "phase": "aa", "metrics": {"launch_to_ready_ms": ready_ms},
            "validation": {"echoed": True, "erased": True}, "validated": True}


def _legacy_spread(rows, bench="compare.cold_start",
                   metric="launch_to_ready_ms"):
    """The legacy even/odd pairing, kept here as the incident yardstick."""
    halves = {0: [], 1: []}
    for r in rows:
        if r.get("phase") != "aa" or r.get("error"):
            continue
        v = (r.get("metrics") or {}).get(metric)
        if v is not None:
            halves[r["trial"] % 2].append(v)
    # stats() rounds each p50 to 1 decimal before the spread — same here
    a = round(sorted(halves[0])[len(halves[0]) // 2], 1)
    b = round(sorted(halves[1])[len(halves[1]) // 2], 1)
    return round(abs(a - b) / min(a, b) * 100, 1)


def test_half_assignment_pure_and_balanced():
    # a pure function of the trial index — no product, metric or value
    # enters the assignment; schedule factors are balanced by count
    for n, exp in ((10, ([0, 3, 4, 7, 8], [1, 2, 5, 6, 9])),
                   (20, ([0, 3, 4, 7, 8, 11, 12, 15, 16, 19],
                         [1, 2, 5, 6, 9, 10, 13, 14, 17, 18]))):
        h0 = [t for t in range(n) if _aa_half(t) == 0]
        h1 = [t for t in range(n) if _aa_half(t) == 1]
        assert (h0, h1) == exp
        assert len(h0) == len(h1) == n // 2
    # at the 20-trial calibration default the balance is EXACT: every
    # half sees 5 first-occurrence and 5 second-occurrence launches and
    # 5 forward and 5 reversed rounds
    h0 = [t for t in range(20) if _aa_half(t) == 0]
    h1 = [t for t in range(20) if _aa_half(t) == 1]
    for half in (h0, h1):
        assert sum(t % 2 == 0 for t in half) == 5
        assert sum(t % 2 == 1 for t in half) == 5
        assert sum((t // 2) % 2 == 0 for t in half) == 5
        assert sum((t // 2) % 2 == 1 for t in half) == 5


def test_position_effect_is_schedule_not_instability():
    # claude's observed W1 scale: second-occurrence launches ~+40ms
    rows = [_row(t, 330.0 if t % 2 == 0 else 370.0) for t in range(20)]
    out = aa_validity(rows, threshold_pct=10.0)["compare.cold_start/claude"]
    assert out == {"a_p50": 330.0, "b_p50": 330.0,
                   "spread_pct": 0.0, "valid": True}
    # at 10 trials the 3-vs-2 position majority still leaks through the
    # median — the residual that motivated the 20-trial calibration default
    rows10 = [_row(t, 330.0 if t % 2 == 0 else 370.0) for t in range(10)]
    out10 = aa_validity(rows10, threshold_pct=10.0)["compare.cold_start/claude"]
    assert out10["valid"] is False and out10["spread_pct"] == 12.1


def test_genuine_instability_detected():
    # a position- AND direction-balanced bimodal draw whose halves land
    # on different modes: run-to-run non-repeatability, must fail
    slow = {0, 1, 2, 3, 4, 5, 6, 7, 8, 11}
    rows = [_row(t, 500.0 if t in slow else 300.0) for t in range(20)]
    assert sum(1 for t in slow if t % 2 == 0) == 5
    assert sum(1 for t in slow if t % 2 == 1) == 5  # not position-locked
    out = aa_validity(rows, threshold_pct=10.0)["compare.cold_start/claude"]
    assert out["valid"] is False and out["spread_pct"] == 66.7


def test_half_assignment_matches_runner_block_structure():
    # the engine's aa blocks (bench/trials.py): each round runs the product
    # order twice (one first-occurrence and one second-occurrence launch)
    # and reverses direction every other round — the real W1 rows carry
    # that structure, and the balanced assignment equals the block-derived
    # pairing (round + occurrence) % 2 on every row
    rows = [json.loads(l) for l in FIXTURE.read_text().splitlines() if l.strip()]
    fwd = {"rust": 0, "ts": 1, "claude": 2, "pi": 3}
    rev = {"pi": 0, "claude": 1, "ts": 2, "rust": 3}
    for r in rows:
        assert r["round"] == r["trial"] // 2          # 2 launches per round
        assert r["abba_position"] == (fwd if r["round"] % 2 == 0 else rev)[r["product"]]
        assert _aa_half(r["trial"]) == (r["round"] + r["trial"] % 2) % 2
    # every half sees exactly one launch of each product per round, so
    # direction and occurrence cannot concentrate in either half
    for half in (0, 1):
        picked = [r for r in rows if r["product"] == "claude"
                  and _aa_half(r["trial"]) == half]
        assert sorted(r["round"] for r in picked) == [0, 1, 2, 3, 4]


def test_w1_incident_replay():
    # the real 40 cmp-v4 W1 A/A rows (4 products x 10 trials), pulled
    # from the campaign VM: balanced halves pass; the legacy pairing on
    # the same rows reproduces the recorded 13.8% withholding. This is
    # the incident record — it does NOT requalify W1.
    rows = [json.loads(l) for l in FIXTURE.read_text().splitlines() if l.strip()]
    assert len(rows) == 40
    out = aa_validity(rows, threshold_pct=10.0)
    assert out["compare.cold_start/claude"] == {
        "a_p50": 332.0, "b_p50": 336.8, "spread_pct": 1.4, "valid": True}
    for prod in ("rust", "ts", "pi"):
        assert out[f"compare.cold_start/{prod}"]["valid"] is True
    claude_rows = [r for r in rows if r["product"] == "claude"]
    assert _legacy_spread(claude_rows) == 13.8
