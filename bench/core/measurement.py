"""Measurement types and the trial-record flattening rules.

PRIMARY maps every benchmark to its ranked metric and direction (all
current metrics minimize). metrics_for() is the single source of truth for
turning one JSONL trial row into flat numeric metrics for aggregation.
"""
from __future__ import annotations

PRIMARY: dict[str, tuple[str, str]] = {
    "compare.cold_start": ("launch_to_ready_ms", "minimize"),
    "compare.warm_start": ("launch_to_ready_ms", "minimize"),
    "compare.msg_send": ("submit_to_ack_ms", "minimize"),
    "compare.scroll_typing": ("typing_ms_p50", "minimize"),
    "session.cold_open_10mib": ("launch_to_ready_ms", "minimize"),
    "daemon.boot": ("spawn_to_accept_ms", "minimize"),
    "compare.install_disk": ("installed_bytes", "minimize"),
    "compare.memory_idle_load": ("rss_settled_mb", "minimize"),
}

_TYPING_LIST_KEYS = ("typing_ms", "typing_scrolled_ms")
_SUBMIT_MS_KEYS = ("submit_to_ack_ms", "submit_to_result_ms", "state_build_ms",
                   "compact_to_ack_ms", "post_compact_cell_ms", "kill_to_restored_cell_ms")


def primary_metric(benchmark_name: str) -> tuple[str, str] | None:
    """(metric key, direction) ranked for this benchmark, or None."""
    return PRIMARY.get(benchmark_name)


def metrics_for(row: dict) -> dict:
    """Flatten one trial row into numeric metrics for aggregation."""
    m = row.get("metrics", {})
    out: dict = {}
    for k, v in m.items():
        if isinstance(v, (int, float)) and v is not None:
            out[k] = v
        elif k in _TYPING_LIST_KEYS and isinstance(v, list):
            clean = [x for x in v if x is not None]
            if clean:
                out[k + "_p50"] = _pct(clean, 50)
                out[k + "_p95"] = _pct(clean, 95)
                out[k + "_n"] = len(clean)
                out[k + "_all"] = clean
        elif k in _SUBMIT_MS_KEYS and isinstance(v, (int, float)):
            out[k] = v
        elif k == "scroll_pgup_ms" and isinstance(v, list):
            clean = [x for x in v if x is not None]
            if clean:
                out["scroll_pgup_ms_p50"] = _pct(clean, 50)
                out["scroll_pgup_ms_p95"] = _pct(clean, 95)
                out["scroll_pgup_ms_all"] = clean
    if "per_type" in m and isinstance(m["per_type"], dict):
        # kernel.cell_exec: {type: {submit_to_ack_ms, submit_to_result_ms}}
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


def _pct(vals: list, p: float):
    """The p-th percentile (nearest-rank on the sorted values)."""
    if not vals:
        return None
    s = sorted(vals)
    idx = min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))
    return s[idx]
