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


def _stability_detail(reason: str, info: dict) -> str:
    """One stable/unstable mark rendered as evidence text."""
    if reason == "aa_drift":
        return (f"A/A p50 {info['aa_p50']} vs W1 p50 {info['w1_p50']} "
                f"(+{info['drift_pct']}% drift)")
    metrics = "; ".join(f"{m}: a={e['a_p50']} b={e['b_p50']} ({e['spread_pct']}%)"
                        for m, e in sorted(info["metrics"].items()))
    return f"A/A spread over threshold \u2014 {metrics}"


def markdown(stats: dict, cfg: dict) -> str:
    """The benchmark summary tables + the excluded-trials and A/A tables."""
    display = cfg.get("display", {})
    order = cfg.get("product_order", [])
    summary, aa = stats["summary"], stats["aa"]
    lines = ["# Benchmark summary", ""]
    methodology = stats.get("methodology") or {}
    if methodology:
        phases = methodology.get("published_phases") or []
        lines.append(f"_Published phases: {', '.join(phases)}; "
                     f"A/A rows calibrate only, never publish; gate: {methodology.get('gate')}._")
        lines.append("")
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
        status = entry.get("status") or {}
        if status:
            lines.append("Status (no trials ran):")
            lines.append("")
            for prod in [p for p in order if p in status] \
                    + [p for p in status if p not in order]:
                info = status[prod]
                line = f"- {display.get(prod, prod)}: {info.get('status')}"
                if info.get("reason"):
                    line += f" \u2014 {info['reason']}"
                lines.append(line)
            lines.append("")
        comparability = entry.get("comparability") or {}
        if comparability:
            comp = ", ".join(f"{display.get(p, p)}={mode}"
                             for p, mode in comparability.items())
            lines.append(f"_Comparability: {comp}_")
            lines.append("")
        identity = entry.get("identity") or {}
        if identity.get("mixed"):
            lines.append(f"**Mixed identity \u2014 never aggregate across these rows**: "
                         f"runs {identity.get('run_labels')}, "
                         f"harness {identity.get('harness_revs')}")
            lines.append("")
        disclosures = entry.get("disclosures") or {}
        if disclosures:
            cells = "; ".join(
                f"{display.get(p, p)}: " + ", ".join(f"{kind}={n}"
                                                    for kind, n in sorted(kinds.items()))
                for p, kinds in disclosures.items())
            lines.append(f"_Disclosures: {cells}_")
            lines.append("")
        unstable = entry.get("unstable") or {}
        if unstable:
            lines.append("Unstable (never ranked):")
            lines.append("")
            lines.append("| product | reason | detail |")
            lines.append("|---|---|---|")
            for p in [p for p in order if p in unstable] \
                    + [p for p in unstable if p not in order]:
                for reason, info in unstable[p].items():
                    lines.append(f"| {display.get(p, p)} | {reason} | "
                                 f"{_stability_detail(reason, info)} |")
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
    coverage = stats.get("aa_coverage") or {}
    uncalibrated = sorted(b for b, c in coverage.items() if not c.get("aa_rows"))
    if coverage:
        lines.append(f"_A/A coverage: {len(coverage) - len(uncalibrated)}/{len(coverage)} "
                     f"benchmarks calibrated"
                     + (f"; none for {', '.join(uncalibrated)}" if uncalibrated else "")
                     + " \u2014 an A/A table entry is the only noise evidence, "
                       "its absence is never an OK._")
        lines.append("")
    return "\n".join(lines)


class MarkdownAnalyzer(Analyzer):
    """Renders the stats model as the markdown summary."""

    name = "markdown"

    def format_output(self, stats: dict) -> str:
        """The markdown artifact."""
        return markdown(stats, self.cfg)
