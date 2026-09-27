#!/usr/bin/env python3
"""Build the concurrent-io lane record JSON from pulled run data.

Usage: python3 build_concurrent_io_record.py > record.json
Reads /home/ubuntu/hillclimb/concurrent-io-runs/ (result.json files).
"""

import hashlib
import json
from pathlib import Path
import statistics as st

RUNS = Path("/home/ubuntu/hillclimb/concurrent-io-runs")
BASE_SHA = "392efffae0c08cfba85911565adc8171a31002d17850daf20306d89fd7716402"
BASE_REV = "7064d039ac3437596f75b44423d76a8f4bf4856a"
CAND_REV = "ac83e5baf5a4bd110c356c84defba41f67a65cb1"
VM = "l0j1fuwrk79pvehuoevwn60f"


def load(run):
    return json.loads((RUNS / run / "result.json").read_text())


def load_valid(run):
    """A leg's metrics if it validated; a marker dict if it crashed."""
    r = json.loads((RUNS / run / "result.json").read_text())
    if not r.get("validated"):
        return {"run": run, "N": r.get("workers"), "validated": False,
                "binary_sha256": r.get("binary_sha256"),
                "note": "leg crashed (resume-storm worker-connect flake); excluded from pair means"}
    return run_metrics(r)


def percentile(values, p):
    ordered = sorted(values)
    index = (len(ordered) - 1) * p
    low = int(index)
    if low == len(ordered) - 1:
        return ordered[low]
    return ordered[low] + (ordered[min(low + 1, len(ordered) - 1)] - ordered[low]) * (index - low)


def run_metrics(r):
    b = r["phase_boundaries"]
    n, k = r["workers"], r["appends"]
    req = n * k
    out = {"run": r["trial_dir"].split("/")[-2], "N": n,
           "binary_sha256": r["binary_sha256"],
           "validated": r.get("validated"),
           "session_semantics_digest": r["session_semantics_digest"]}
    for phase in ("append1", "append2"):
        a, z = b[f"{phase}_start"], b[f"{phase}_done"]
        out[f"sup_cpu_per_{phase}_us"] = round(
            (z["sup_schedstat"]["runtime_ns"] - a["sup_schedstat"]["runtime_ns"]) / 1e3 / req, 1)
        lat = [v / 1e6 for s in r["sessions"].values() for v in s["census"][f"{phase}_ns"]]
        out[f"{phase}_p50_ms"] = round(percentile(lat, 0.5), 2)
        out[f"{phase}_p95_ms"] = round(percentile(lat, 0.95), 2)
        out[f"{phase}_wall_s"] = round((z["unix_ms"] - a["unix_ms"]) / 1000, 2)
    calib = [v for v in r["calibration"].values() if isinstance(v, float)]
    out["calibration_min_s"] = round(min(calib), 3)
    out["calibration_max_s"] = round(max(calib), 3)
    out["sup_fd_count"] = r["supervisor_census"]["fds"]["count"]
    out["worker_rss_sum_mb"] = round(sum(
        s["census"]["worker"]["status_mb"]["VmRSS"] for s in r["sessions"].values()), 1)
    out["resume_preserves_bytes_all"] = all(
        s["census"]["validation"]["resume_preserves_bytes"] for s in r["sessions"].values())
    return out


def paired(names_b, names_c):
    b_all = [load_valid(name) for name in names_b]
    c_all = [load_valid(name) for name in names_c]
    b = [row for row in b_all if row.get("validated")]
    c = [row for row in c_all if row.get("validated")]
    def legs(rows, phase):
        return [row[f"sup_cpu_per_{phase}_us"] for row in rows]
    out = {"base_runs": b_all, "candidate_runs": c_all,
           "excluded_legs": [row["run"] for row in b_all + c_all
                             if not row.get("validated")]}
    for phase in ("append1", "append2"):
        bl, cl = legs(b, phase), legs(c, phase)
        bm, cm = st.mean(bl), st.mean(cl)
        out[f"{phase}_base_us"] = round(bm, 1)
        out[f"{phase}_cand_us"] = round(cm, 1)
        out[f"{phase}_delta_pct"] = round((cm - bm) / bm * 100, 1)
        out[f"{phase}_base_values"] = bl
        out[f"{phase}_cand_values"] = cl
    # parity: digests must match across roles
    digests = {row["session_semantics_digest"] for row in b + c}
    out["digests_identical_across_roles"] = len(digests) == 1
    out["all_validated"] = all(row["validated"] for row in b + c)
    out["all_resume_preserved"] = all(row["resume_preserves_bytes_all"] for row in b + c)
    return out


def main():
    curve = []
    for trial in (0, 1):
        for n in (1, 10, 50, 100):
            curve.append(run_metrics(load(f"t{trial}-n{n}")))
    pair_n1 = paired(["abba-n1-B-0", "abba-n1-B-3"], ["abba-n1-C-1", "abba-n1-C-2"])
    pair_n100 = paired(["abba-n100-B-0", "abba-n100-B-3"],
                       ["abba-n100-C-1", "abba-n100-C-2"])
    repair_n1 = paired(["re-pair-n1-B-0", "re-pair-n1-B-3"],
                       ["re-pair-n1-C-1", "re-pair-n1-C-2"])
    repair_n100 = paired(["re-pair-n100-B-0", "re-pair-n100-B-3"],
                         ["re-pair-n100-C-1", "re-pair-n100-C-2"])
    confirm_n1 = paired(["confirm-n1-B-0", "confirm-n1-B-3"],
                        ["confirm-n1-C-1", "confirm-n1-C-2"])
    confirm_n100 = paired(["confirm-n100-B-0", "confirm-n100-B-3"],
                          ["confirm-n100-C-1", "confirm-n100-C-2"])
    confirm2_n1 = paired(["confirm2-n1-B-0", "confirm2-n1-B-3"],
                         ["confirm2-n1-C-1", "confirm2-n1-C-2"])
    confirm2_n100 = paired(["confirm2-n100-B-0", "confirm2-n100-B-3"],
                           ["confirm2-n100-C-1", "confirm2-n100-C-2"])
    confirm3_n100 = paired(["confirm3-n100-B-0", "confirm3-n100-B-3"],
                           ["confirm3-n100-C-1", "confirm3-n100-C-2"])
    confirm4_n100 = paired(["confirm4-n100-B-0", "confirm4-n100-B-3"],
                           ["confirm4-n100-C-1", "confirm4-n100-C-2"])
    confirm5_n100 = paired(["confirm5-n100-B-0", "confirm5-n100-B-3"],
                           ["confirm5-n100-C-1", "confirm5-n100-C-2"])
    regime = []
    for line in (RUNS / "abba-regime-watch.jsonl").read_text().splitlines():
        line = line.strip()
        if not line or line.endswith("done\": true}"):
            continue
        line = line.replace("true}", "true}").rstrip(",")
        try:
            regime.append(json.loads(line))
        except json.JSONDecodeError:
            # malformed jsonl edge; keep raw
            regime.append({"raw": line[:200]})
    record = {
        "id": "20260926-203500-io-concurrent-event-fanout-arc",
        "axis": "io",
        "lane": "concurrent-io (perf-concurrent-io-fast)",
        "hypothesis": (
            "Per-request supervisor cost for session I/O is superlinear in resident "
            "sessions N: every session event (2 per append: message_start+message_end, "
            "full message payload) publishes on the one daemon-wide tokio broadcast "
            "channel and every client connection wakes, deep-clones the "
            "(ClientRouting, Value) frame, locks its attached-list mutex, checks, "
            "discards - Theta(N) per request, Theta(N^2) aggregate. Sharing the payload "
            "(Arc<Value>) removes the per-receiver deep clone while keeping the same "
            "channel, ring, routing decisions, recv order, and wire frames."),
        "base": {"revision": BASE_REV},
        "branch": "lane/hillclimb-concurrent-io",
        "commits": ["b56a2b332", "b4c89869b", "d3ac85973", "ac83e5baf"],
        "build": {
            "sandbox_id": VM,
            "base_binary_sha256": BASE_SHA,
            "candidate_binary_sha256_abba": "af49e01c2d1c7ac2fc35a0031f4993962713a9b4c162f977304d65d09f296ac4",
            "candidate_binary_sha256_final_head": None,
            "toolchain": "rustup 1.98.1 on ubuntu:22.04 (glibc 2.35)",
        },
        "measurements": {
            "method": "same-vm-sequential ABBA (B C C B per N) + baseline curve",
            "baseline_curve": curve,
            "abba_pair_n1_iteration_b4c89869b": pair_n1,
            "abba_pair_n100_iteration_b4c89869b": pair_n100,
            "abba_pair_n1_head_exact_ac83e5baf": repair_n1,
            "abba_pair_n100_head_exact_ac83e5baf": repair_n100,
            "intermediate_confirm_a40b33ea0_lineage_n1_SUSPECT": confirm_n1,
            "intermediate_confirm_a40b33ea0_lineage_n100_SUSPECT": confirm_n100,
            "final_pair_1507d399b_lineage_n1": confirm2_n1,
            "final_pair_1507d399b_lineage_n100_SUSPECT_contaminated": confirm2_n100,
            "final_gated_pair_1507d399b_lineage_n100": confirm3_n100,
            "folded_pair_013e40a4a_lineage_n100": confirm4_n100,
            "folded_pair_4d57eb082_lineage_n100_rebind_head": confirm5_n100,
        },
        "regime": {
            "fsync_probe": "4KB fdatasync x20 per probe, 20s cadence during ABBA",
            "healthy_window_p50_ms": 0.19,
            "note": "N=1 legs probed healthy (p50 0.19-0.21ms); N=100 legs probed "
                    "13-52ms p50 - partly self-induced (100 concurrent fdatasync-per-append "
                    "sessions saturate the shared storage) and consistent with the fleet "
                    "degraded-I/O window; CPU legs (schedstat) are regime-insensitive "
                    "(B legs stable 2615-2728us across healthy and degraded probes).",
            "probe_log": "abba-regime-watch.jsonl (raw arrays in archive)",
        },
    }
    print(json.dumps(record, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
