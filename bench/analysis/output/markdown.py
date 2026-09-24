"""The markdown results analyzer (summary.md)."""
from __future__ import annotations

from bench.core.analyzer import Analyzer


def markdown(stats: dict, cfg: dict) -> str:
    """The benchmark summary tables + the A/A calibration table."""
    display = cfg.get("display", {})
    order = cfg.get("product_order", [])
    summary, aa = stats["summary"], stats["aa"]
    lines = ["# Benchmark summary", ""]
    for bench, entry in summary.items():
        lines.append(f"## {bench}")
        lines.append("")
        prods = [p for p in order if p in entry["products"]]
        if not prods:
            continue
        keys = sorted({k for p in prods for k in entry["products"][p]})
        keys = [k for k in keys if not k.endswith("_n")]
        lines.append("| product | " + " | ".join(keys) + " | rank | \u0394 vs TS |")
        lines.append("|---|" + "---|" * (len(keys) + 2))
        for p in prods:
            s = entry["products"][p]
            if s.get("failures") and not s.get(entry.get("primary") or ""):
                lines.append(f"| {display.get(p, p)} | FAILED x{s['failures']} |" + " | " * len(keys) + " \u2014 | \u2014 |")
                continue
            cells = []
            for k in keys:
                st = s.get(k)
                cells.append(f"{st['p50']}" if st else "\u2014")
            rank = entry.get("ranks", {}).get(p, "\u2014")
            d = entry.get("delta_vs_ts", {}).get(p)
            dcell = f"{d['pct']:+.0f}%" if d else ("\u2014" if p != "ts" else "baseline")
            lines.append(f"| {display.get(p, p)} | " + " | ".join(cells) + f" | {rank} | {dcell} |")
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
