"""The markdown results analyzer (summary.md)."""
from __future__ import annotations

from bench.core.analyzer import Analyzer


def _trials_cell(entry: dict, product: str) -> str:
    """The per-phase trial denominators for one product, e.g. "w1=8 aa=10"."""
    phases = (entry.get("trials") or {}).get(product) or {}
    return " ".join(f"{phase}={n}" for phase, n in sorted(phases.items())) or "\u2014"


def _reasons_cell(info: dict) -> str:
    """The exclusion reasons as "code=count, ..."."""
    return ", ".join(f"{reason}={n}" for reason, n in sorted(info["reasons"].items()))


def markdown(stats: dict, cfg: dict) -> str:
    """The benchmark summary tables + the excluded-trials and A/A tables."""
    display = cfg.get("display", {})
    order = cfg.get("product_order", [])
    summary, aa = stats["summary"], stats["aa"]
    lines = ["# Benchmark summary", ""]
    for bench, entry in summary.items():
        lines.append(f"## {bench}")
        lines.append("")
        prods = [p for p in order if p in entry["products"]]
        keys = sorted({k for p in prods for k in entry["products"][p]})
        keys = [k for k in keys if not k.endswith("_n") and k != "failures"]
        if prods:
            lines.append("| product | trials | " + " | ".join(keys) + " | rank | \u0394 vs TS |")
            lines.append("|---|" + "---|" * (len(keys) + 3))
            for p in prods:
                s = entry["products"][p]
                trials = _trials_cell(entry, p)
                if s.get("failures") and not s.get(entry.get("primary") or ""):
                    lines.append(f"| {display.get(p, p)} | {trials} | FAILED x{s['failures']} |" + " | " * len(keys) + " \u2014 | \u2014 |")
                    continue
                cells = []
                for k in keys:
                    st = s.get(k)
                    cells.append(f"{st['p50']} (n{st['n']})" if st else "\u2014")
                rank = entry.get("ranks", {}).get(p, "\u2014")
                d = entry.get("delta_vs_ts", {}).get(p)
                dcell = f"{d['pct']:+.0f}%" if d else ("\u2014" if p != "ts" else "baseline")
                lines.append(f"| {display.get(p, p)} | {trials} | " + " | ".join(cells) + f" | {rank} | {dcell} |")
            lines.append("")
        if not prods:
            lines.append("_No valid published trials._")
            lines.append("")
        unstable = entry.get("unstable") or {}
        if unstable:
            lines.append("Unstable (A/A-to-wave drift over threshold):")
            lines.append("")
            lines.append("| product | A/A p50 | W1 p50 | drift |")
            lines.append("|---|---|---|---|")
            for p in unstable:
                info = unstable[p]
                lines.append(f"| {display.get(p, p)} | {info['aa_p50']} | "
                             f"{info['w1_p50']} | +{info['drift_pct']}% |")
            lines.append("")
        excluded = entry.get("excluded") or {}
        if excluded:
            lines.append("Excluded from rankings (validity gate):")
            lines.append("")
            lines.append("| product | excluded | reasons |")
            lines.append("|---|---|---|")
            named = [p for p in order if p in excluded]
            for p in named + [p for p in excluded if p not in named]:
                info = excluded[p]
                lines.append(f"| {display.get(p, p)} | {info['count']} | {_reasons_cell(info)} |")
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


class MarkdownAnalyzer(Analyzer):
    """Renders the stats model as the markdown summary."""

    name = "markdown"

    def format_output(self, stats: dict) -> str:
        """The markdown artifact."""
        return markdown(stats, self.cfg)
