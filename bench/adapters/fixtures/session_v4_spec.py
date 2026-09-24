"""The v4 session-fixture spec of record (metadata-only; n=1,543 real files).

The v4 fixture ("session-size/4") is the REPRESENTATIVE structural synthetic
session corpus: one synthetic root marathon session, exactly 10MiB, whose
row schema, row-type mix, role mix, and row-byte distribution match the
measured aggregates of real Prime Agent session files. It replaces the v3
corpus (kept byte-identical as the pathological STRESS corpus) as the
fixture behind the representative benchmarks.

Provenance of every number in this module (2026-09-24 metadata-only scan of
the local session store; no content, no paths, no ids crossed the boundary:
lengths/counts/enums only; nothing here is or derives from private text):

- POOLED_* tables: the pooled scan across all 1,543 files
  (200 root + 1,343 subagent; 264,552 rows).
- MARATHON_* tables: the marathon-conditioned scan (root files >= 0.5MiB,
  n=11, 40,551 rows; the two >8MiB roots are 27.5 and 50.9MiB). Per the
  parent directive the v4 default is calibrated to the MARATHON
  conditioning, not the pooled percentages: pooled mixes are dominated by
  60% stub roots and by subagent files, which a single marathon root is
  not.
- CAVEAT (recorded openly): marathon conditioning rests on n=11 files
  (n=2 above 8MiB) from a single-user corpus. The v4 sample is "calibrated
  to measured marathon quantiles, small-n"; the pooled table stays the
  fallback whole-corpus reference.

Sampling bias of the source corpus (recorded, not corrected here): one
user, one Mac, 2026-09 vintage, ipython-dominant tool mix, sub sessions
carry most byte mass, sandbox/cloud sessions contribute the custom row
mass, usage spans up to 311h (heartbeat-driven).

Structure of the v4 default sample (the specific root marathon 10MiB
sample): ~4.1K rows (measured marathon mean 2,547 B/row), messages 79.6%
(user 4.9 / assistant 52.9 / toolResult 42.3 within messages), 0.80
toolcalls per assistant row (max 2), stop reasons toolUse 79.5 / stop
15.6 / error 4.8 / aborted 0.15, isError 0.26% of toolResults, ~6
compaction rows (band 5-14), agent_status/child_usage at their
marathon-accumulated (~8x pooled) shares, 3 hidden harness_digest
custom_message rows (~10.2KB), a small (<640B) tail-sentinel assistant
row, 2 trailing non-message lifecycle rows (realistic final row), ZERO
image parts (measured ZERO in all 11 marathon roots; images occur only in
sub sessions - a follow-up sub bucket carries them). The genuine
marathon outlier tier is preserved: ~2 toolResult rows in the 128-256KB
bucket (measured 17/40,551 rows) and a documented ~1.05MB ceiling row that
this 10MiB sample does not need (0.1 expected at this row count).

The v3 corpus is NOT representative (its single 4.28MB padded tail row is
40.9% of file bytes - ~3.5x the pooled real max row and ~200x the
marathon p99) and stays untouched as the explicit stress corpus.
"""

from __future__ import annotations

import bisect
import math

# ---------------------------------------------------------------------------
# Pooled reference (whole corpus; n=1,543 files, 264,552 rows)
# ---------------------------------------------------------------------------

#: pooled per-row byte quantiles (bytes)
POOLED_ROW_BYTES = {"p50": 1250, "p90": 7775, "p99": 38579, "max": 1212493}
#: pooled row-type mix (share of all rows)
POOLED_ROW_TYPE_MIX = {
    "message": 0.792, "custom": 0.097, "custom_message": 0.050,
    "agent_status": 0.016, "child_usage_attributed": 0.010,
    "session_state": 0.007, "session": 0.006, "model_change": 0.0058,
    "thinking_level_change": 0.0057, "service_tier_change": 0.0056,
    "session_info": 0.005, "compaction": 0.0003, "git_state": 0.0002,
}
#: pooled role mix inside message rows
POOLED_ROLE_MIX = {"assistant": 0.508, "toolResult": 0.475, "user": 0.017}
#: pooled part-size quantiles (bytes of the text payload)
POOLED_PART_BYTES = {
    "user_text": {"p50": 282, "p90": 1229, "max": 13312},
    "assistant_text": {"p50": 144, "p90": 813, "max": 73728},
    "thinking": {"p50": 420, "p90": 3994, "p99": 18432, "max": 140288},
    "toolcall_arguments": {"p50": 268, "p90": 1331, "p99": 7168, "max": 77824},
    "toolresult_text": {"p50": 694, "p90": 6451, "p99": 29696, "max": 326656},
}
#: pooled custom_message type mix (counts, 12,122 rows)
POOLED_CUSTOM_MESSAGE_COUNTS = {
    "agent_message": 4958, "async_bash_completion": 3300,
    "goal_context": 2076, "heartbeat_prompt": 1048, "harness_digest": 866,
    "rlm_child_terminal_notice": 203, "refinement_outcome": 178,
    "refinement_notice": 163, "ipython_state_restored": 119,
    "ipython_state": 89, "update_restart": 62, "worker_recovery": 29,
    "provider_retry_outcome": 16, "slash": 8, "rlm_child_failure": 6,
}
#: pooled per-row byte histogram, 0.5-octave buckets [2^e, 2^(e+0.5)) ->
#: count (lower edge 2^e); n = 264,552 rows
POOLED_ROW_BYTE_HISTOGRAM = {
    6.0: 0, 6.5: 0, 7.0: 7305, 7.5: 4724, 8.0: 3505, 8.5: 28112,
    9.0: 33238, 9.5: 38537, 10.0: 27522, 10.5: 23941, 11.0: 25989,
    11.5: 21014, 12.0: 14216, 12.5: 10734, 13.0: 8233, 13.5: 5764,
    14.0: 4954, 14.5: 2673, 15.0: 1501, 15.5: 1002, 16.0: 433,
    16.5: 260, 17.0: 229, 17.5: 3, 18.0: 15, 18.5: 14, 19.0: 15,
    19.5: 5, 20.0: 3, 20.5: 0,
}

# ---------------------------------------------------------------------------
# Marathon conditioning (root files >= 0.5MiB; n=11, 40,551 rows)
# ---------------------------------------------------------------------------

#: marathon per-row byte quantiles (bytes); the ~1.05MB max is the single
#: giant-row ceiling observed in 40.5K marathon rows (0.0025%)
MARATHON_ROW_BYTES = {"p50": 1366, "p75": 2677, "p90": 4779, "p99": 21291,
                      "max": 1057127}
#: measured marathon mean bytes/row -> a 10MiB sample is ~4.1K rows
MARATHON_AVG_ROW_BYTES = 2547
MARATHON_ROWS_PER_10MIB = (10 * (1 << 20)) / MARATHON_AVG_ROW_BYTES
#: marathon row-type mix (share of all rows; agent_status/child_usage run
#: ~8x their pooled share - marathon roots are orchestration parents)
MARATHON_ROW_TYPE_MIX = {
    "message": 0.7962, "custom_message": 0.0625, "custom": 0.0535,
    "agent_status": 0.0528, "child_usage_attributed": 0.0287,
    "session_state": 0.0034, "compaction": 0.0008, "model_change": 0.0007,
    "git_state": 0.0003, "thinking_level_change": 0.0003, "session": 0.0003,
    "service_tier_change": 0.0003, "session_info": 0.0002,
}
#: marathon role mix inside message rows (user turns are far more frequent
#: than pooled: marathon sessions are user/heartbeat-interactive)
MARATHON_ROLE_MIX = {"user": 0.049, "assistant": 0.529, "toolResult": 0.423}
#: marathon stop-reason mix inside assistant rows
MARATHON_STOP_REASON_MIX = {"toolUse": 0.7946, "stop": 0.1556,
                            "error": 0.0483, "aborted": 0.0015}
#: toolcalls per assistant row (mean; hard max 2)
MARATHON_TOOLCALLS_PER_ASSISTANT = 0.80
MARATHON_TOOLCALLS_MAX = 2
#: share of toolResult rows carrying isError (with the error details shape)
MARATHON_IS_ERROR_SHARE = 0.00256
#: compactions per 10MiB marathon file (measured band; ~1/1000 rows in
#: compacted sessions)
MARATHON_COMPACTIONS_10MIB_BAND = (5, 14)
#: marathon per-row byte histogram (same bucketing as pooled; n=40,551;
#: ZERO rows in 256KB-1MB - the 128-256KB bucket holds the genuine outliers)
MARATHON_ROW_BYTE_HISTOGRAM = {
    6.0: 0, 6.5: 10, 7.0: 170, 7.5: 2019, 8.0: 1259, 8.5: 2125,
    9.0: 3259, 9.5: 6300, 10.0: 5963, 10.5: 4419, 11.0: 5917,
    11.5: 3907, 12.0: 2249, 12.5: 1230, 13.0: 706, 13.5: 366,
    14.0: 300, 14.5: 215, 15.0: 79, 15.5: 24, 16.0: 10,
    16.5: 6, 17.0: 17, 17.5: 0, 18.0: 0, 18.5: 0, 19.0: 0,
    19.5: 0, 20.0: 1, 20.5: 0,
}
#: marathon custom_message type mix (pooled counts across the 11 roots;
#: heartbeat_prompt + agent_message are the marathon signature)
MARATHON_CUSTOM_MESSAGE_COUNTS = {
    "agent_message": 901, "heartbeat_prompt": 898, "refinement_outcome": 170,
    "refinement_notice": 157, "async_bash_completion": 151,
    "rlm_child_terminal_notice": 124, "harness_digest": 36,
    "ipython_state": 32,
}
#: derived completion of the marathon custom_message mix to 100% (the scan
#: listed the 8 dominant types; the remainder are the pooled rarer kinds,
#: allocated by their pooled order; documented derivation, not a scan value)
MARATHON_CUSTOM_MESSAGE_REMAINDER = {
    "goal_context": 0.020, "update_restart": 0.008, "worker_recovery": 0.005,
    "ipython_state_restored": 0.004, "provider_retry_outcome": 0.002,
    "slash": 0.001, "rlm_child_failure": 0.001,
}
#: harness_digest custom_message rows in the 10MiB sample (measured
#: per-file p50 0 / p75 2 / p90 12 / B4 8-12; ~1.2% of custom_message rows)
MARATHON_HARNESS_DIGEST_ROWS = 3
#: harness_digest content size band (bytes; measured 9.7-10.8KB)
MARATHON_HARNESS_DIGEST_BYTES = (9700, 10800)
#: compaction row payload bands (bytes; summary measured p50 ~11.7KB max
#: ~33KB, harnessDigest 9.0-10.3KB, tokensBefore p50 256K p90 431K)
MARATHON_COMPACTION_SUMMARY_BYTES = (11000, 12500)
MARATHON_COMPACTION_DIGEST_BYTES = (9000, 10300)
MARATHON_COMPACTION_TOKENS_BEFORE = (230_000, 460_000)
#: trailing non-message rows per file (measured p50 1 / max 3; B4 1 and 3)
MARATHON_TRAILING_ROWS = 2
#: model_change rows per file (measured p50 1 / p90 7 / max 9)
MARATHON_MODEL_CHANGE_ROWS = 2
#: ipython tool duration ms quantiles (pooled; details.durationMs)
TOOL_DURATION_MS = {"p50": 39, "p75": 2200, "p90": 7000, "p99": 79900,
                    "max": 6034000}
#: image parts: measured ZERO in all 11 marathon roots (they occur only in
#: sub sessions, ~225-266KB base64) - the default v4 sample carries none
MARATHON_IMAGE_PARTS = 0
#: the genuine marathon outlier tier: rows in the 128-256KB bucket
#: (measured 17/40,551 = 0.042% -> ~2 rows at 4.1K-row scale)
MARATHON_OUTLIER_ROWS_128K_256K = 2
#: generator hard caps (documented tiers, NOT a claim that real sessions
#: are bounded: the pooled real max row is 1.21MB and the marathon ceiling
#: is ~1.05MB - see POOLED_ROW_BYTES / MARATHON_ROW_BYTES)
#: representative tier cap: the marathon p99 row
CAP_REPRESENTATIVE_ROW_BYTES = 21291
#: outlier-tier cap: the top of the measured 128-256KB marathon bucket
CAP_OUTLIER_ROW_BYTES = 260_000

# ---------------------------------------------------------------------------
# Gates (what the v4 corpus must satisfy; enforced by the generator AND
# asserted by tests/test_session_v4.py)
# ---------------------------------------------------------------------------

#: KS gate: max |ECDF_emp - ECDF_ref| on log2(row bytes) against the
#: marathon histogram reference
KS_D_MAX = 0.05
#: row-type mix L1 distance vs MARATHON_ROW_TYPE_MIX
MIX_L1_MAX = 0.02
#: per-role tolerance (absolute share) vs MARATHON_ROLE_MIX
ROLE_SHARE_TOL = 0.015
#: realized row-count band for the 10MiB sample. The scan's measured
#: marathon mean (2,547 B/row) implies ~4.1K rows; the realized
#: KS-calibrated distribution averages ~2.23KB/row (the mid-tail mass of
#: the reference lives in sparse buckets the calibrated draws undershoot)
#: so the representative sample lands ~4.6-4.8K rows. The band admits the
#: calibration's scale while excluding the v3 7.4K-row uniform shape and
#: stub-scale corpora.
ROW_COUNT_BAND_10MIB = (3900, 5300)
#: top-0.1% rows byte share (real pooled 5.8%; v3 pathological 40.9%)
TOP_P001_BYTE_SHARE_MAX = 0.10
#: the tail-sentinel assistant row stays small (a wire-complete
#: assistant row is ~550B; v3's padded sentinel row was 4.28MB)
SENTINEL_ROW_MAX_BYTES = 640
#: realized row-byte quantile bands vs the marathon anchors (+/- in log2
#: space, dex)
QUANTILE_LOG2_TOL = {"p50": 0.30, "p75": 0.30, "p90": 0.30, "p99": 0.40}


def _histogram_cdf(histogram: dict) -> list:
    """The (log2 upper edge, cumulative share) anchor list of a histogram."""
    total = sum(histogram.values())
    anchors, cumulative = [], 0
    for edge in sorted(histogram):
        cumulative += histogram[edge]
        anchors.append((edge + 0.5, cumulative / total))
    return anchors


def reference_cdf(log2_bytes: float, histogram: dict | None = None) -> float:
    """The reference ECDF at log2_bytes for a bucketed histogram.

    Piecewise-linear in log2 between bucket upper-edge cumulative anchors
    (uniform density within a bucket); 0 below the first anchor, 1 above
    the last.
    """
    ref = histogram or MARATHON_ROW_BYTE_HISTOGRAM
    anchors = _histogram_cdf(ref)
    if log2_bytes <= anchors[0][0]:
        return 0.0
    if log2_bytes >= anchors[-1][0]:
        return 1.0
    for (lo, f_lo), (hi, f_hi) in zip(anchors, anchors[1:]):
        if lo <= log2_bytes <= hi:
            if hi == lo:
                return f_hi
            return f_lo + (f_hi - f_lo) * (log2_bytes - lo) / (hi - lo)
    return 1.0


def ks_distance(row_byte_sizes, histogram: dict | None = None) -> float:
    """The KS statistic D of realized row sizes vs a histogram reference.

    Evaluated at every realized row (empirical vs interpolated reference)
    and at every reference anchor (reference vs empirical step function):
    the standard two-sided KS sup over the union of jump points.
    """
    ref = histogram or MARATHON_ROW_BYTE_HISTOGRAM
    values = sorted(math.log2(b) for b in row_byte_sizes)
    n = len(values)
    best = 0.0
    for i, v in enumerate(values):
        d = abs((i + 1) / n - reference_cdf(v, ref))
        if d > best:
            best = d
    for edge, f_ref in _histogram_cdf(ref):
        i = bisect.bisect_right(values, edge)
        d = abs(i / n - f_ref)
        if d > best:
            best = d
    return best


def quantile(values, q: float):
    """The linear-interpolated q-quantile of a sequence of numbers."""
    data = sorted(values)
    if not data:
        raise ValueError("quantile of empty sequence")
    pos = (len(data) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(data) - 1)
    frac = pos - lo
    return data[lo] * (1 - frac) + data[hi] * frac
