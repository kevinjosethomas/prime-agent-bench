#!/usr/bin/env python3
"""Publish a campaign's records bundle (offline; nothing is uploaded).

Builds ``records/campaigns/<run-label>/`` from one results tree: eligible
rows only, the strict-gate summary, provenance + invalid-row notes, the
privacy audit, and SHASUMS.txt. Raw screens/logs/homes/vendor payloads
are never read. Ranks follow the campaign config's rank policy — the
default is validation-only (no ranks).

    python scripts/publish_records.py --results-dir ~/bench/results \
        [--config configs/default.yaml] [--label <run-label>] \
        [--phase w1] [--out-root records/campaigns] [--force]

    python scripts/publish_records.py --check records/campaigns/<label>

This commits nothing and uploads nothing: `git add` the bundle when the
record is the one you want kept.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench.core.config import load_config  # noqa: E402
from bench.core.registry import discover  # noqa: E402


def _gate_benchmarks(cfg: dict) -> dict:
    """The per-benchmark gate metadata the validity gate needs (the same
    map cmd_analyze injects: fixture requirement, applicability,
    completeness keys, aa metrics)."""
    reg = discover(cfg)
    return {name: {"requires_fixture": b.requires_fixture,
                   "applicable_products": b.applicable_products,
                   "completeness_keys": tuple(b.completeness_keys),
                   "aa_metrics": tuple(b.aa_metrics)}
            for name, b in reg.benchmarks.items()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results-dir", help="the campaign results tree to read")
    ap.add_argument("--config", default=None, help="YAML config path")
    ap.add_argument("--label", default=None,
                    help="campaign run label (required when the tree mixes labels)")
    ap.add_argument("--phase", default=None,
                    help="published phases, comma-separated (default: all non-aa)")
    ap.add_argument("--out-root", default=None,
                    help="bundle root (default: <repo>/records/campaigns)")
    ap.add_argument("--force", action="store_true",
                    help="rebuild an existing bundle dir")
    ap.add_argument("--check", metavar="BUNDLE_DIR",
                    help="verify one bundle (SHASUMS + required files)")
    args = ap.parse_args(argv)

    from bench.records.publish import BundleError, build_records_bundle, check_bundle

    if args.check:
        report = check_bundle(Path(args.check).expanduser())
        print(json.dumps(report, indent=1))
        return 0 if report["ok"] else 1

    if not args.results_dir:
        ap.error("--results-dir is required to build a bundle")
    cfg = load_config(args.config)
    cfg["gate_benchmarks"] = _gate_benchmarks(cfg)
    phases = [p for p in (args.phase or "").split(",") if p] or None
    out_root = Path(args.out_root).expanduser() if args.out_root else None
    try:
        report = build_records_bundle(args.results_dir, cfg, label=args.label,
                                      out_root=out_root, phases=phases,
                                      force=args.force)
    except BundleError as e:
        print(f"bundle error: {e}", file=sys.stderr)
        return 1
    prov = report["provenance"]
    print(json.dumps({
        "bundle_dir": str(report["bundle_dir"]),
        "run_label": prov["run_label"],
        "kept_total": prov["rows"]["kept_total"],
        "excluded_summary": prov["rows"]["excluded_summary"],
        "privacy_dropped_keys": prov["privacy"]["dropped_keys"],
        "rank_status": prov["gate"]["rank_status"],
    }, indent=1))
    print(f"verify: python scripts/publish_records.py --check {report['bundle_dir']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
