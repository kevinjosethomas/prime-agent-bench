#!/usr/bin/env python3
"""Aggregate benchmark JSONL -> summary stats, ranks, delta-vs-TS, markdown.

Outputs results/summary.json + results/summary.md. A/A runs (phase 'aa')
are validated: >10% p50 spread between the two interleaved halves of the
same product marks the environment too noisy (Kevin's fairness rule).

Not part of any product. Benchmark harness only.
"""
from __future__ import annotations

import glob
import json
import math
import random
from collections import defaultdict
from pathlib import Path

RESULTS = Path.home() / "bench" / "results"
PRODUCT_ORDER = ["rust", "ts", "claude", "codex", "pi"]
DISPLAY = {"rust": "Prime Agent Rust", "ts": "Prime Agent TS", "claude": "Claude Code",
           "codex": "Codex CLI", "pi": "Pi Mono"}

PRIMARY = {
    "compare.cold_start": ("launch_to_ready_ms", "minimize"),
    "compare.warm_start": ("launch_to_ready_ms", "minimize"),
    "compare.msg_send": ("submit_to_ack_ms", "minimize"),
    "compare.scroll_typing": ("typing_ms_p50", "minimize"),
    "session.cold_open_10mib": ("launch_to_ready_ms", "minimize"),
    "daemon.boot": ("spawn_to_accept_ms", "minimize"),
    "compare.install_disk": ("installed_bytes", "minimize"),
    "compare.memory_idle_load": ("rss_settled_mb", "minimize"),
}


def pct(vals, p):
    if not vals:
        return None
    s = sorted(vals)
    idx = min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))
    return s[idx]


def stats(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return {"n": 0}
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / max(1, len(vals) - 1)
    return {"n": len(vals), "min": round(min(vals), 1), "p50": round(pct(vals, 50), 1),
            "p95": round(pct(vals, 95), 1), "p99": round(pct(vals, 99), 1),
            "max": round(max(vals), 1), "mean": round(mean, 1),
            "stdev": round(math.sqrt(var), 2)}


def boot_ci_median(vals, n=1000, seed=7):
    vals = [v for v in vals if v is not None]
    if len(vals) < 3:
        return None
    rng = random.Random(seed)
    meds = []
    for _ in range(n):
        sample = [vals[rng.randrange(len(vals))] for _ in vals]
        meds.append(sorted(sample)[len(sample) // 2])
    meds.sort()
    return [round(meds[int(0.025 * n)], 1), round(meds[int(0.975 * n)], 1)]


def load_all():
    rows = []
    for path in glob.glob(str(RESULTS / "*" / "trials-*.jsonl")):
        bench = Path(path).parent.name
        with open(path) as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    r["benchmark"] = r.get("benchmark", bench)
                    rows.append(r)
    return rows


def metrics_for(row):
    m = row.get("metrics", {})
    out = {}
    for k, v in m.items():
        if isinstance(v, (int, float)) and v is not None:
            out[k] = v
        elif k in ("typing_ms", "typing_scrolled_ms") and isinstance(v, list):
            clean = [x for x in v if x is not None]
            if clean:
                out[k + "_p50"] = pct(clean, 50)
                out[k + "_p95"] = pct(clean, 95)
                out[k + "_n"] = len(clean)
                out[k + "_all"] = clean
        elif k in ("submit_to_ack_ms", "submit_to_result_ms", "state_build_ms",
                   "compact_to_ack_ms", "post_compact_cell_ms", "kill_to_restored_cell_ms") and isinstance(v, (int, float)):
            out[k] = v
        elif k == "scroll_pgup_ms" and isinstance(v, list):
            clean = [x for x in v if x is not None]
            if clean:
                out["scroll_pgup_ms_p50"] = pct(clean, 50)
                out["scroll_pgup_ms_p95"] = pct(clean, 95)
                out["scroll_pgup_ms_all"] = clean
    for k, v in m.items():
        # kernel.cell_exec: {type: {submit_to_ack_ms, submit_to_result_ms}}
        if k == "per_type" if False else False:
            pass
    if "per_type" in m and isinstance(m["per_type"], dict):
        for kind, vals in m["per_type"].items():
            for mk, mv in vals.items():
                if isinstance(mv, (int, float)):
                    out[f"cell_exec_{kind}_{mk}"] = mv
    if "per_kernel" in m and isinstance(m["per_kernel"], list):
        for pk in m["per_kernel"]:
            for mk, mv in pk.items():
                if isinstance(mv, (int, float)):
                    out.setdefault(f"multi_kernel_{mk}", []).append(mv)
        out.pop("per_kernel", None)
        out["multi_kernel_n"] = m.get("n")
    if "rss_after_first_cell" in m and isinstance(m["rss_after_first_cell"], dict):
        out["kernel_rss_mb"] = m["rss_after_first_cell"].get("rss_mb")
    res = row.get("resource", {})
    if "rss_settled" in res:
        out["rss_settled_mb"] = res["rss_settled"].get("rss_mb")
        out["pss_settled_mb"] = res["rss_settled"].get("pss_mb")
        out["nproc_settled"] = res["rss_settled"].get("nproc")
    if "rss_10mib" in res:
        out["rss_10mib_mb"] = res["rss_10mib"].get("rss_mb")
        out["pss_10mib_mb"] = res["rss_10mib"].get("pss_mb")
        out["nproc_10mib"] = res["rss_10mib"].get("nproc")
    return out


def aggregate(rows):
    by = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))  # bench -> product -> metric -> [vals]
    failures = defaultdict(lambda: defaultdict(int))  # bench -> product -> n_errors
    for r in rows:
        if r.get("error"):
            failures[r["benchmark"]][r["product"]] += 1
            continue
        mm = metrics_for(r)
        for k, v in mm.items():
            if k.endswith("_all"):
                by[r["benchmark"]][r["product"]].setdefault(k, []).extend(v)
            else:
                by[r["benchmark"]][r["product"]][k].append(v)
    return by, failures


def summarize(by, failures):
    out = {}
    for bench, prods in by.items():
        primary, direction = PRIMARY.get(bench, (None, "minimize"))
        entry = {"products": {}, "primary": primary}
        for p in failures.get(bench, {}):
            entry["products"].setdefault(p, {})["failures"] = failures[bench][p]
        for prod, metrics in prods.items():
            s = {}
            for k, vals in metrics.items():
                if k.endswith("_all"):
                    continue
                st = stats(vals)
                if st["n"]:
                    st["ci95_median"] = boot_ci_median(vals)
                    s[k] = st
            entry["products"][prod] = s
        # ranks on the primary metric
        if primary:
            p50s = {p: s.get(primary, {}).get("p50") for p, s in entry["products"].items()}
            ranked = sorted([(v, p) for p, v in p50s.items() if v is not None])
            entry["ranks"] = {p: i + 1 for i, (v, p) in enumerate(ranked)}
            entry["primary_p50s"] = {p: v for v, p in ranked}
            ts = p50s.get("ts")
            entry["delta_vs_ts"] = {}
            for p, v in p50s.items():
                if v is not None and ts:
                    entry["delta_vs_ts"][p] = {
                        "abs": round(v - ts, 1),
                        "pct": round((v - ts) / ts * 100.0, 1),
                    }
        out[bench] = entry
    return out


def aa_validity(rows):
    """A/A check: same product interleaved as two pseudo-sides."""
    out = {}
    aa_rows = [r for r in rows if r.get("phase") == "aa"]
    by = defaultdict(list)
    for r in aa_rows:
        if not r.get("error"):
            by[(r["benchmark"], r["product"], r["trial"] % 2)].append(
                r.get("metrics", {}).get("launch_to_ready_ms"))
    grouped = defaultdict(dict)
    for (bench, prod, half), vals in by.items():
        grouped[(bench, prod)][half] = [v for v in vals if v is not None]
    for (bench, prod), halves in grouped.items():
        a = stats(halves.get(0, []))
        b = stats(halves.get(1, []))
        if a.get("p50") and b.get("p50"):
            spread = abs(a["p50"] - b["p50"]) / min(a["p50"], b["p50"]) * 100
            out[f"{bench}/{prod}"] = {"a_p50": a["p50"], "b_p50": b["p50"],
                                      "spread_pct": round(spread, 1),
                                      "valid": spread <= 10.0}
    return out


def markdown(summary, aa):
    lines = ["# Benchmark summary", ""]
    for bench, entry in summary.items():
        primary = entry.get("primary")
        lines.append(f"## {bench}")
        lines.append("")
        prods = [p for p in PRODUCT_ORDER if p in entry["products"]]
        if not prods:
            continue
        keys = sorted({k for p in prods for k in entry["products"][p]})
        keys = [k for k in keys if not k.endswith("_n")]
        lines.append("| product | " + " | ".join(keys) + " | rank | Δ vs TS |")
        lines.append("|---|" + "---|" * (len(keys) + 2))
        for p in prods:
            s = entry["products"][p]
            if s.get("failures") and not s.get(entry.get("primary") or ""):
                lines.append(f"| {DISPLAY.get(p, p)} | FAILED x{s['failures']} |" + " | " * len(keys) + " — | — |")
                continue
            cells = []
            for k in keys:
                st = s.get(k)
                cells.append(f"{st['p50']}" if st else "—")
            rank = entry.get("ranks", {}).get(p, "—")
            d = entry.get("delta_vs_ts", {}).get(p)
            dcell = f"{d['pct']:+.0f}%" if d else "—" if p != "ts" else "baseline"
            lines.append(f"| {DISPLAY.get(p, p)} | " + " | ".join(cells) + f" | {rank} | {dcell} |")
        lines.append("")
    if aa:
        lines.append("## A/A calibration")
        lines.append("")
        lines.append("| pair | p50 a | p50 b | spread | valid |")
        lines.append("|---|---|---|---|---|")
        for k, v in aa.items():
            lines.append(f"| {k} | {v['a_p50']} | {v['b_p50']} | {v['spread_pct']}% | {'YES' if v['valid'] else 'NO'} |")
        lines.append("")
    return "\n".join(lines)


def main():
    rows = load_all()
    by, failures = aggregate(rows)
    summary = summarize(by, failures)
    aa = aa_validity(rows)
    (RESULTS / "summary.json").write_text(json.dumps({"summary": summary, "aa": aa}, indent=1))
    (RESULTS / "summary.md").write_text(markdown(summary, aa))
    print(markdown(summary, aa))
    print("\nA/A:", json.dumps(aa, indent=1))


if __name__ == "__main__":
    main()
