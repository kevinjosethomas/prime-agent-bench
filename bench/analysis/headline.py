"""The headline startup table: one validated row per product.

Reads one sandbox results tree (compare.cold_start + compare.warm_start
JSONL, settle.jsonl, versions.json, aa-gate.json) and builds the table
the campaign publishes, or compares two trees (run-to-run agreement).

A product's cell holds numbers only when everything below holds; else it
reads INVALID with the reasons:
- its latest attempt passes the A/A gate (analysis.aa_validation.pair_verdict:
  halves' spread and A/A-to-wave drift within the thresholds, enough
  valid trials),
- every counted row passed its own validation (input row, raw tty, token
  persisted, ready >= paint, resident processes as expected, no foreign
  processes) - failing rows are dropped and counted,
- its template carried no personal state (settle template_audit),
- its binary is the same after every pass as before it (versions-check),
- warm only: the daemon the harness pre-warmed runs the same
  configuration as the one the product's TUI spawns on a cold launch
  (the env keys of ``daemon_identity.env_added`` equal on cold and warm rows),
- all rows of the tree ran on one trial filesystem.

Flags (shown, not invalidating): warm slower than cold beyond the A/A
tolerance on a daemon product.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from bench.analysis.aa_validation import latest_attempt, pair_verdict
from bench.analysis.stats import stats
from bench.analysis.validity import row_exclusion

BENCHES = ("compare.cold_start", "compare.warm_start")
METRIC = "launch_to_ready_ms"


def _rows(tree: Path, bench: str, phase: str) -> list:
    path = tree / bench / f"trials-{phase}.jsonl"
    if not path.exists():
        return []
    rows = (json.loads(line) for line in path.read_text().splitlines() if line.strip())
    return [r for r in rows if r.get("phase") == phase]  # not the warm-up rows


def _settle_findings(tree: Path) -> dict:
    latest = {}
    path = tree / "settle.jsonl"
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                rec = json.loads(line)
                latest[rec.get("product")] = rec.get("template_audit") or []
    return latest


def _changed_binaries(tree: Path) -> set:
    path = tree / "versions-check.jsonl"
    if not path.exists():
        return set()
    return {name for line in path.read_text().splitlines() if line.strip()
            for name in json.loads(line).get("changed", {})}


def tolerance_ms(a: float, b: float, aa_cfg: dict) -> float:
    """The A/A gate's tolerance between two p50s (the larger of the
    spread threshold's share of the smaller value and the absolute floor)."""
    return max(float(aa_cfg.get("spread_threshold_pct", 10.0)) / 100.0 * min(a, b),
               float(aa_cfg.get("abs_floor_ms", 5.0)))


def _cell(rows: list, key) -> dict:
    return stats([key(r) for r in rows if key(r) is not None])


def build_table(tree, aa_cfg: dict | None = None, phase: str = "w1",
                products: list | None = None) -> dict:
    """{"products": {name: {...}}, "trial_fs": [...]} for one results tree."""
    tree = Path(tree)
    aa_cfg = aa_cfg or {}
    settle = _settle_findings(tree)
    changed = _changed_binaries(tree)
    versions = {}
    if (tree / "versions.json").exists():
        versions = json.loads((tree / "versions.json").read_text()).get("products", {})
    out: dict = {"products": {}, "trial_fs": set()}
    per: dict = defaultdict(dict)
    for bench in BENCHES:
        aa_rows = latest_attempt([r for r in _rows(tree, bench, "aa") if r.get("metrics") or r.get("error")])
        wave_rows = latest_attempt([r for r in _rows(tree, bench, phase) if r.get("metrics") or r.get("error")])
        names = products or sorted({r["product"] for r in aa_rows + wave_rows})
        for name in names:
            mine = {"aa": [r for r in aa_rows if r["product"] == name],
                    "wave": [r for r in wave_rows if r["product"] == name]}
            valid = {k: [r for r in v if row_exclusion(r, {}, {}) is None] for k, v in mine.items()}
            failed = Counter()
            for r in mine["aa"] + mine["wave"]:
                if r.get("error"):
                    failed["error"] += 1
                for check, ok in (r.get("validation") or {}).items():
                    if not ok:
                        failed[check] += 1
            for r in mine["aa"] + mine["wave"]:
                fs = (r.get("env") or {}).get("trial_fs")
                if fs:
                    out["trial_fs"].add(fs)
            expected = max(len([r for r in mine["wave"]]), 1)
            verdict = pair_verdict(valid["aa"], valid["wave"], METRIC, aa_cfg,
                                   expected=expected)
            w = valid["wave"]
            per[name][bench] = {
                "verdict": verdict,
                "attempt": max([int(r.get("attempt") or 0) for r in mine["wave"]] or [0]),
                "ready": _cell(w, lambda r: r["metrics"].get(METRIC)),
                "paint": _cell(w, lambda r: r["metrics"].get("launch_to_first_paint_ms")),
                "rss_trial_mb": _cell(w, lambda r: ((r.get("resource") or {}).get("rss_trial") or {}).get("rss_mb")),
                "daemon_boot_ms": _cell(w, lambda r: (r.get("daemon") or {}).get("prewarmed_boot_ms")),
                "resident_at_launch": Counter(len(r.get("resident_at_launch") or []) for r in w),
                # the env KEYS the daemon carries beyond the launch env
                # (values hold per-trial paths and tokens)
                "daemon_env": Counter(json.dumps(sorted((r.get("daemon_identity") or {})
                                                        .get("env_added") or {}))
                                      for r in w if r.get("daemon_identity")),
                "rows_valid": len(valid["aa"]) + len(valid["wave"]),
                "rows_total": len(mine["aa"]) + len(mine["wave"]),
                "failed_checks": dict(failed),
            }
    for name, benches in per.items():
        identity = (next((r.get("product_identity") for b in BENCHES
                          for r in _rows(tree, b, phase) if r.get("product") == name
                          and r.get("product_identity")), None)
                    or versions.get(name) or {})
        entry = {"identity": {k: identity.get(k) for k in ("version", "revision", "binary_sha256")},
                 "benches": {}, "flags": []}
        for bench, cell in benches.items():
            reasons = list(cell["verdict"]["reasons"])
            if settle.get(name):
                reasons.append("template_personal_state")
            if name in changed:
                reasons.append("binary_changed_during_run")
            entry["benches"][bench] = dict(cell, reasons=reasons)
        cold = benches.get("compare.cold_start")
        warm = benches.get("compare.warm_start")
        if cold and warm and warm["daemon_env"]:
            if set(warm["daemon_env"]) != set(cold["daemon_env"]):
                entry["benches"]["compare.warm_start"]["reasons"].append("daemon_config_mismatch")
        if cold and warm and warm["daemon_boot_ms"].get("n"):
            c, h = cold["ready"].get("p50"), warm["ready"].get("p50")
            if c and h and h - c > tolerance_ms(c, h, aa_cfg):
                entry["flags"].append("warm slower than cold")
        for bench, cell in entry["benches"].items():
            cell["status"] = "INVALID" if cell["reasons"] else "VALID"
        out["products"][name] = entry
    out["trial_fs"] = sorted(out["trial_fs"])
    if len(out["trial_fs"]) > 1:
        for entry in out["products"].values():
            for cell in entry["benches"].values():
                cell["reasons"].append("mixed_trial_fs")
                cell["status"] = "INVALID"
    return out


def agreement(t1: dict, t2: dict, aa_cfg: dict | None = None) -> dict:
    """Run-to-run agreement per product x benchmark: both VALID and the
    p50s within the A/A gate's tolerance (tolerance_ms)."""
    aa_cfg = aa_cfg or {}
    out = {}
    for name in sorted(set(t1["products"]) | set(t2["products"])):
        for bench in BENCHES:
            c1 = (t1["products"].get(name) or {}).get("benches", {}).get(bench)
            c2 = (t2["products"].get(name) or {}).get("benches", {}).get(bench)
            if not c1 or not c2:
                continue
            a, b = c1["ready"].get("p50"), c2["ready"].get("p50")
            rec = {"run1_p50": a, "run2_p50": b,
                   "run1_status": c1["status"], "run2_status": c2["status"]}
            if a and b:
                rec["delta_ms"] = round(b - a, 1)
                rec["delta_pct"] = round((b - a) / a * 100, 1)
                rec["tolerance_ms"] = round(tolerance_ms(a, b, aa_cfg), 1)
                rec["agree"] = (c1["status"] == c2["status"] == "VALID"
                                and abs(b - a) <= rec["tolerance_ms"])
            else:
                rec["agree"] = False
            out[f"{bench}/{name}"] = rec
    return out


def _fmt(cell: dict) -> str:
    if cell["status"] != "VALID":
        return "INVALID (" + ", ".join(cell["reasons"]) + ")"
    r = cell["ready"]
    return f"{r['p50']} / {r['p90']}"


def markdown(table: dict, title: str) -> str:
    """The table as markdown (ready p50 / p90 ms, A/A spread, memory)."""
    lines = [f"### {title}", "",
             "| product | version / revision (binary sha256) | cold ready p50 / p90 | cold A/A spread / drift | "
             "warm ready p50 / p90 | warm A/A spread / drift | daemon boot p50 | "
             "memory cold / warm (MB, whole trial) | first paint cold / warm | flags |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for name, entry in table["products"].items():
        cold = entry["benches"].get("compare.cold_start")
        warm = entry["benches"].get("compare.warm_start")
        ident = entry["identity"]
        sha = (ident.get("binary_sha256") or "")[:12]
        rev = str(ident.get("revision") or "")
        rev = rev[:9] if len(rev) == 40 else rev

        def aa(cell):
            v = cell["verdict"]
            return f"{v.get('spread_pct')}% / {v.get('drift_pct')}%"

        def mem(cell):
            return cell["rss_trial_mb"].get("p50") if cell["status"] == "VALID" else "-"

        boot = warm["daemon_boot_ms"].get("p50") if warm and warm["daemon_boot_ms"].get("n") else "-"
        paint = (f"{cold['paint'].get('p50')} / {warm['paint'].get('p50')}"
                 if cold and warm else "-")
        lines.append(
            f"| {name} | {ident.get('version') or '?'} / {rev} ({sha}) | "
            f"{_fmt(cold) if cold else '-'} | {aa(cold) if cold else '-'} | "
            f"{_fmt(warm) if warm else '-'} | {aa(warm) if warm else '-'} | {boot} | "
            f"{mem(cold) if cold else '-'} / {mem(warm) if warm else '-'} | {paint} | "
            f"{', '.join(entry['flags']) or '-'} |")
    lines.append("")
    lines.append(f"trial filesystem: {', '.join(table['trial_fs']) or '?'}")
    return "\n".join(lines)
