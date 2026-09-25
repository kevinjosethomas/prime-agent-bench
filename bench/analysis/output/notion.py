"""The Notion payload analyzer (summary.notion.json).

Builds a Notion API-ready children-blocks payload (headings, paragraphs,
bulleted rows) from the shared stats model. Payload builder only: it never
calls the Notion API.
"""
from __future__ import annotations

import json

from bench.core.analyzer import Analyzer

_MAX_PER_BLOCK = 2000


def _text(content: str) -> dict:
    """One Notion rich-text object."""
    return {"type": "text", "text": {"content": content[:_MAX_PER_BLOCK]}}


def _blocks(stats: dict, cfg: dict) -> list:
    """The children payload: one section per benchmark + the A/A table."""
    display = cfg.get("display", {})
    order = cfg.get("product_order", [])
    out = [{"object": "block", "type": "heading_1",
            "heading_1": {"rich_text": [_text("Benchmark summary")]}}]
    for bench, entry in stats["summary"].items():
        out.append({"object": "block", "type": "heading_2",
                    "heading_2": {"rich_text": [_text(bench)]}})
        primary = entry.get("primary") or "metrics"
        for p in order:
            s = entry["products"].get(p)
            if not s:
                continue
            phases = (entry.get("trials") or {}).get(p) or {}
            trials = ", ".join(f"{phase}={n}" for phase, n in sorted(phases.items()))
            if s.get("failures") and not s.get(primary):
                out.append({"object": "block", "type": "bulleted_list_item",
                            "bulleted_list_item": {"rich_text": [
                                _text(f"{display.get(p, p)}: FAILED x{s['failures']}")]}})
                continue
            st = s.get(primary)
            rank = entry.get("ranks", {}).get(p)
            delta = entry.get("delta_vs_ts", {}).get(p, {})
            cell = f"{display.get(p, p)}: {primary} p50={st['p50']} (n={st['n']})" if st \
                else f"{display.get(p, p)}: no data"
            if trials:
                cell += f", trials {trials}"
            if rank:
                cell += f", rank {rank}"
            if delta:
                cell += f", {delta['pct']:+.1f}% vs ts"
            out.append({"object": "block", "type": "bulleted_list_item",
                        "bulleted_list_item": {"rich_text": [_text(cell)]}})
        status = entry.get("status") or {}
        for prod in status:
            info = status[prod]
            cell = f"{display.get(prod, prod)}: {info.get('status')}"
            if info.get("reason"):
                cell += f" \u2014 {info['reason']}"
            out.append({"object": "block", "type": "bulleted_list_item",
                        "bulleted_list_item": {"rich_text": [_text(cell)]}})
        comparability = entry.get("comparability") or {}
        if comparability:
            comp = ", ".join(f"{display.get(p, p)}={mode}" for p, mode in comparability.items())
            out.append({"object": "block", "type": "bulleted_list_item",
                        "bulleted_list_item": {"rich_text": [_text(f"Comparability: {comp}")]}})
        unstable = entry.get("unstable") or {}
        for p in unstable:
            for reason, info in unstable[p].items():
                if reason == "aa_drift":
                    detail = (f"A/A p50 {info['aa_p50']} vs published p50 "
                              f"{info['published_p50']} (+{info['drift_pct']}% drift)")
                else:
                    detail = "; ".join(f"{m}: a={e['a_p50']} b={e['b_p50']} "
                                       f"({e['spread_pct']}%)"
                                       for m, e in sorted(info["metrics"].items()))
                out.append({"object": "block", "type": "bulleted_list_item",
                            "bulleted_list_item": {"rich_text": [_text(
                                f"{display.get(p, p)}: unstable ({reason}) \u2014 {detail}")]}})
        uncalibrated = entry.get("uncalibrated") or {}
        for p in uncalibrated:
            info = uncalibrated[p]
            out.append({"object": "block", "type": "bulleted_list_item",
                        "bulleted_list_item": {"rich_text": [_text(
                            f"{display.get(p, p)}: uncalibrated \u2014 {info['reason']} "
                            f"({info['aa_valid']}/{info['aa_expected']} valid A/A rows)")]}})
        withheld = entry.get("ranks_withheld") or {}
        if withheld:
            detail = withheld.get("detail") or "; ".join(
                f"{k}: {', '.join(v)}" for k, v in withheld.items()
                if k in ("unsupported", "absent", "uncalibrated", "unstable") and v)
            label = f"ranks withheld ({withheld['reason']})"
            if withheld.get("expected"):
                label += f" \u2014 expected cohort {withheld['expected']}"
            out.append({"object": "block", "type": "bulleted_list_item",
                        "bulleted_list_item": {"rich_text": [_text(
                            f"{label}: {detail}" if detail else label)]}})
        excluded = entry.get("excluded") or {}
        for p in excluded:
            info = excluded[p]
            reasons = ", ".join(f"{reason}={n}" for reason, n in sorted(info["reasons"].items()))
            out.append({"object": "block", "type": "bulleted_list_item",
                        "bulleted_list_item": {"rich_text": [_text(
                            f"{display.get(p, p)}: excluded {info['count']} trials ({reasons})")]}})
        out.append({"object": "block", "type": "paragraph",
                    "paragraph": {"rich_text": [_text("")]}})
    if stats["aa"]:
        out.append({"object": "block", "type": "heading_2",
                    "heading_2": {"rich_text": [_text("A/A calibration")]}})
        for k, v in stats["aa"].items():
            out.append({"object": "block", "type": "bulleted_list_item",
                        "bulleted_list_item": {"rich_text": [_text(
                            f"{k}: a={v['a_p50']} b={v['b_p50']} spread={v['spread_pct']}% "
                            f"{'valid' if v['valid'] else 'NOISY'}")]}})
    return out


class NotionAnalyzer(Analyzer):
    """Renders the stats model as a Notion blocks payload."""

    name = "notion"

    def format_output(self, stats: dict) -> str:
        """The {"children": [...]} JSON payload (POST /v1/blocks/<page>/children)."""
        return json.dumps({"children": _blocks(stats, self.cfg)}, indent=1)
