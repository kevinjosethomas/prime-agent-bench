"""`bench compare <runA> <runB>`: attributable before/after deltas.

The improvement-loop convenience: load two result sets (trial JSONL
directories), group per (benchmark, product), and print per-group p50s,
the delta, and the bootstrap-CI check the analysis layer already uses —
plus the versions.json evidence of both runs so a delta is never
attributed blind. `--out` writes the same table as markdown.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from bench.analysis.aggregate import load_all
from bench.analysis.stats import boot_ci_median, stats
from bench.core.measurement import primary_metric


def _group(rows: list) -> dict:
    """rows -> {(benchmark, product): [metric values]}."""
    out: dict = {}
    for row in rows:
        bench = row.get("benchmark")
        product = row.get("product")
        if not bench or not product or row.get("error"):
            continue
        primary = primary_metric(bench)
        metric = primary[0] if primary else None
        if metric is None:
            continue
        value = (row.get("metrics") or {}).get(metric)
        if value is None:
            continue
        out.setdefault((bench, product), []).append(float(value))
    return out


def compare_runs(cfg: dict, run_a: Path, run_b: Path) -> dict:
    """The delta table between two result sets."""
    a_rows = load_all(run_a)
    b_rows = load_all(run_b)
    a = _group(a_rows)
    b = _group(b_rows)
    versions_a = _versions(run_a)
    versions_b = _versions(run_b)
    out = {"run_a": str(run_a), "run_b": str(run_b),
           "versions_a": versions_a, "versions_b": versions_b, "groups": {}}
    for key in sorted(set(a) | set(b)):
        bench, product = key
        av, bv = a.get(key, []), b.get(key, [])
        entry = {"benchmark": bench, "product": product}
        if av:
            sa = stats(av)
            entry["a_p50"] = sa["p50"]
            entry["a_ci"] = boot_ci_median(av)
        if bv:
            sb = stats(bv)
            entry["b_p50"] = sb["p50"]
            entry["b_ci"] = boot_ci_median(bv)
        if av and bv:
            delta = entry["b_p50"] - entry["a_p50"]
            entry["delta_abs"] = round(delta, 3)
            entry["delta_pct"] = round(delta / entry["a_p50"] * 100.0, 2)
            # the CI check needs >=3 samples per side (boot_ci_median is
            # None below that); with no CI the separation claim is undefined
            entry["ci_disjoint"] = bool(
                entry.get("a_ci") and entry.get("b_ci")
                and (entry["b_ci"][1] < entry["a_ci"][0]
                     or entry["a_ci"][1] < entry["b_ci"][0]))
        out["groups"][f"{bench}/{product}"] = entry
    return out


def _versions(run: Path) -> dict:
    """A run's versions.json (attribution evidence), if present."""
    path = Path(run) / "versions.json"
    if not path.exists():
        for candidate in sorted(Path(run).glob("*/versions.json"), reverse=True):
            path = candidate
            break
        else:
            return {}
    try:
        return json.loads(path.read_text())
    except ValueError:
        return {}


def format_markdown(result: dict) -> str:
    """The scannable delta table."""
    lines = [f"# {result['run_b']} vs {result['run_a']}", ""]
    lines.append("| benchmark | product | A p50 | B p50 | delta | CI-separated |")
    lines.append("|---|---|---|---|---|---|")
    for key, g in result["groups"].items():
        if "a_p50" in g and "b_p50" in g:
            lines.append(
                f"| {g['benchmark']} | {g['product']} | {g['a_p50']:.1f} "
                f"| {g['b_p50']:.1f} | {g['delta_pct']:+.2f}% "
                f"| {'yes' if g['ci_disjoint'] else 'no'} |")
        elif "a_p50" in g:
            lines.append(f"| {g['benchmark']} | {g['product']} | {g['a_p50']:.1f} | - | - | - |")
        else:
            lines.append(f"| {g['benchmark']} | {g['product']} | - | {g['b_p50']:.1f} | - | - |")
    for side in ("a", "b"):
        v = result.get(f"versions_{side}") or {}
        meta = v.get("_meta") if isinstance(v, dict) else None
        products = v.get("products", v) if isinstance(v, dict) else {}
        if meta:
            lines.append(f"\n* {side.upper()} run `{(meta.get('run') or {}).get('label')}` "
                         f"harness `{str((meta.get('harness') or {}).get('git_rev', ''))[:12]}`")
        for name, info in sorted(products.items()):
            lines.append(f"\n* {side.upper()} {name}: `{info.get('version')}` "
                         f"rev `{info.get('revision')}` sha `{str(info.get('binary_sha256', ''))[:12]}`")
    return "\n".join(lines)


def main() -> None:
    """Usage: python -m bench.drivers.compare <runA> <runB>"""
    from bench.core.config import load_config
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run_a")
    ap.add_argument("run_b")
    ap.add_argument("--out", default=None, help="write the markdown table here")
    args = ap.parse_args()
    cfg = load_config(None)
    result = compare_runs(cfg, Path(args.run_a).expanduser(),
                         Path(args.run_b).expanduser())
    table = format_markdown(result)
    print(table)
    if args.out:
        Path(args.out).expanduser().write_text(table + "\n")
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
