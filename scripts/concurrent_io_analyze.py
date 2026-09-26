#!/usr/bin/env python3
"""Aggregate concurrent_io_curve.py run directories into the N-scaling table.

Usage: python3 concurrent_io_analyze.py RUN_DIR [RUN_DIR ...]
Each RUN_DIR is one (label, N) run root containing result.json.
Prints a per-run table + a cross-N ratio summary (superlinearity readout).
"""

import json
import sys
from pathlib import Path
import statistics as st


def percentile(values, p):
    ordered = sorted(values)
    index = (len(ordered) - 1) * p
    low = int(index)
    return (ordered[low] + ordered[min(low + 1, len(ordered) - 1)] * 0) \
        if low == len(ordered) - 1 else \
        (ordered[low] + (ordered[min(low + 1, len(ordered) - 1)] - ordered[low])
         * (index - low))


def ms(values):
    return [v / 1e6 for v in values]


def phase_sup_cpu_ms(boundaries, start, done):
    a, b = boundaries[start], boundaries[done]
    return (b["sup_schedstat"]["runtime_ns"] - a["sup_schedstat"]["runtime_ns"]) / 1e6


def phase_sup_syscw(boundaries, start, done):
    a, b = boundaries[start], boundaries[done]
    return b["sup_io"]["syscw"] - a["sup_io"]["syscw"]


def phase_wall_s(boundaries, start, done):
    a, b = boundaries[start], boundaries[done]
    return (b["unix_ms"] - a["unix_ms"]) / 1000.0


def analyze(path):
    result = json.loads((Path(path) / "result.json").read_text())
    n = result["workers"]
    k = result["appends"]
    sessions = result["sessions"]
    bounds = result["phase_boundaries"]
    row = {"run": str(path), "N": n, "label": result["label"],
           "binary_sha256": result["binary_sha256"][:12]}
    # per-append latency distributions (client-observed)
    for phase, key in (("append1", "append1_ns"), ("append2", "append2_ns")):
        values = ms([v for s in sessions.values() for v in s["census"][key]])
        row[f"{phase}_p50_ms"] = round(percentile(values, 0.50), 3)
        row[f"{phase}_p95_ms"] = round(percentile(values, 0.95), 3)
        row[f"{phase}_p99_ms"] = round(percentile(values, 0.99), 3)
        row[f"{phase}_max_ms"] = round(max(values), 3)
    creates = ms([s["create_ns"] for s in sessions.values()])
    row["create_p50_ms"] = round(percentile(creates, 0.50), 3)
    row["create_p95_ms"] = round(percentile(creates, 0.95), 3)
    row["create_max_ms"] = round(max(creates), 3)
    resumes = ms([s["census"]["resume"]["create_ns"] for s in sessions.values()])
    row["resume_create_p50_ms"] = round(percentile(resumes, 0.50), 3)
    row["resume_create_p95_ms"] = round(percentile(resumes, 0.95), 3)
    row["resume_create_max_ms"] = round(max(resumes), 3)
    # supervisor CPU per phase
    requests = n * k
    sup_append1 = phase_sup_cpu_ms(bounds, "append1_start", "append1_done")
    sup_append2 = phase_sup_cpu_ms(bounds, "append2_start", "append2_done")
    row["sup_cpu_append1_ms_total"] = round(sup_append1, 3)
    row["sup_cpu_per_append1_us"] = round(sup_append1 * 1000 / requests, 3)
    row["sup_cpu_append2_us"] = round(sup_append2 * 1000 / requests, 3)
    row["sup_cpu_boot_ms_total"] = round(
        phase_sup_cpu_ms(bounds, "boot_start", "created_done"), 3)
    row["sup_cpu_per_create_us"] = round(
        row["sup_cpu_boot_ms_total"] * 1000 / n, 3)
    row["sup_cpu_resume_ms_total"] = round(
        phase_sup_cpu_ms(bounds, "resume1_start", "resume1_done"), 3)
    row["sup_cpu_per_resume_us"] = round(
        row["sup_cpu_resume_ms_total"] * 1000 / n, 3)
    row["sup_cpu_idle_us_per_s"] = round(
        phase_sup_cpu_ms(bounds, "idle_start", "idle_done") * 1000
        / result["idle_seconds"], 3)
    # supervisor write syscalls per append
    row["sup_syscw_per_append1"] = round(
        phase_sup_syscw(bounds, "append1_start", "append1_done") / requests, 3)
    row["sup_syscw_per_append2"] = round(
        phase_sup_syscw(bounds, "append2_start", "append2_done") / requests, 3)
    # worker CPU + write syscalls per append (io_after - io_before)
    worker_cpu_per_append = []
    worker_syscw_per_append = []
    for s in sessions.values():
        for phase in ("append1", "append2"):
            snap = s["census"][f"{phase}_schedstat"]
            cpu = snap["after"]["runtime_ns"] - snap["before"]["runtime_ns"]
            worker_cpu_per_append.append(cpu / 1e3 / k)
            syscw = snap["io_after"]["syscw"] - snap["io_before"]["syscw"]
            worker_syscw_per_append.append(syscw / k)
    row["worker_cpu_per_append_us_mean"] = round(st.mean(worker_cpu_per_append), 3)
    row["worker_syscw_per_append_mean"] = round(st.mean(worker_syscw_per_append), 3)
    worker_write_bytes = [s["census"]["worker"]["io"]["write_bytes"]
                          for s in sessions.values()]
    row["worker_census_write_bytes_mean_mb"] = round(
        st.mean(worker_write_bytes) / 1e6, 2)
    # idle worker CPU rate
    idle_rates = []
    for s in sessions.values():
        idle = s["census"]["idle"]
        idle_rates.append((idle["after"]["runtime_ns"]
                           - idle["before"]["runtime_ns"]) / 1e6
                          / result["idle_seconds"])
    row["worker_idle_cpu_us_per_s_mean"] = round(st.mean(idle_rates), 3)
    # fds + memory
    row["sup_fd_count"] = result["supervisor_census"]["fds"]["count"]
    row["sup_rss_mb"] = result["supervisor_census"]["status_mb"].get("VmRSS")
    row["sup_pss_mb"] = result["supervisor_census"]["pss_mb"]
    row["worker_fd_count_mean"] = round(st.mean(
        [s["census"]["worker"]["fds"]["count"] for s in sessions.values()]), 2)
    row["worker_rss_mb_mean"] = round(st.mean(
        [s["census"]["worker"]["status_mb"]["VmRSS"] for s in sessions.values()]), 2)
    row["worker_pss_mb_mean"] = round(st.mean(
        [s["census"]["worker"]["pss_mb"] for s in sessions.values()]), 2)
    row["worker_rss_mb_sum"] = round(sum(
        s["census"]["worker"]["status_mb"]["VmRSS"] for s in sessions.values()), 1)
    # meminfo page-cache deltas
    for phase in ("append1", "append2", "resume1"):
        a = result["meminfo"][f"{phase}_start"]
        b = result["meminfo"][f"{phase}_done"]
        row[f"dirty_delta_{phase}_mb"] = round(
            (b["Dirty"] - a["Dirty"]) / 1024, 2)
        row[f"cached_delta_{phase}_mb"] = round(
            (b["Cached"] - a["Cached"]) / 1024, 2)
    # walls
    row["boot_wall_s"] = round(phase_wall_s(bounds, "boot_start", "created_done"), 2)
    row["append1_wall_s"] = round(phase_wall_s(bounds, "append1_start", "append1_done"), 2)
    row["resume1_wall_s"] = round(phase_wall_s(bounds, "resume1_start", "resume1_done"), 2)
    row["append2_wall_s"] = round(phase_wall_s(bounds, "append2_start", "append2_done"), 2)
    # validation summary
    row["validated"] = result.get("validated")
    row["session_semantics_digest"] = result["session_semantics_digest"]
    row["all_resume_preserve_bytes"] = all(
        s["census"]["validation"]["resume_preserves_bytes"]
        for s in sessions.values())
    # calibration drift
    calib = result["calibration"]
    values = [v for v in calib.values() if isinstance(v, float)]
    row["calib_min_s"] = round(min(values), 3)
    row["calib_max_s"] = round(max(values), 3)
    row["calib_drift_pct"] = round((max(values) - min(values)) / min(values) * 100, 1)
    return row


def main():
    rows = [analyze(arg) for arg in sys.argv[1:]]
    keys = ["run", "N", "validated", "append1_p50_ms", "append1_p95_ms",
            "append2_p50_ms", "append2_p95_ms", "create_p50_ms",
            "resume_create_p50_ms", "sup_cpu_per_append1_us",
            "sup_cpu_per_append2_us", "sup_cpu_per_create_us",
            "sup_cpu_per_resume_us", "sup_cpu_idle_us_per_s",
            "sup_syscw_per_append1", "sup_syscw_per_append2",
            "worker_cpu_per_append_us_mean", "worker_syscw_per_append_mean",
            "worker_idle_cpu_us_per_s_mean", "sup_fd_count",
            "worker_fd_count_mean", "sup_rss_mb", "sup_pss_mb",
            "worker_rss_mb_mean", "worker_pss_mb_mean", "worker_rss_mb_sum",
            "dirty_delta_append1_mb", "cached_delta_append1_mb",
            "boot_wall_s", "append1_wall_s", "resume1_wall_s", "append2_wall_s",
            "all_resume_preserve_bytes", "calib_drift_pct",
            "session_semantics_digest"]
    widths = {k: max(len(k), *(len(str(r.get(k))) for r in rows)) for k in keys}
    print(" | ".join(k[: widths[k]] for k in keys))
    for row in rows:
        print(" | ".join(str(row.get(k))[: widths[k]] for k in keys))
    # superlinearity ratios vs the smallest N present
    base = [r for r in rows if r["N"] == min(r["N"] for r in rows)]
    base = base[0]
    print("\nRATIOS vs N=%d (%s)" % (base["N"], base["run"]))
    for r in rows:
        print(f"N={r['N']:>4}  append1_p50 x{r['append1_p50_ms']/base['append1_p50_ms']:.2f}"
              f"  sup_cpu/append x{r['sup_cpu_per_append1_us']/max(base['sup_cpu_per_append1_us'],1e-9):.2f}"
              f"  create_p50 x{r['create_p50_ms']/base['create_p50_ms']:.2f}"
              f"  resume_p50 x{r['resume_create_p50_ms']/max(base['resume_create_p50_ms'],1e-9):.2f}"
              f"  sup_fds x{r['sup_fd_count']/max(base['sup_fd_count'],1):.2f}")


if __name__ == "__main__":
    main()
