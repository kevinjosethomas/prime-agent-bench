"""The bench CLI: run, settle, explore, install-disk, analyze, orchestrator.

python -m bench <command> [...]; the console script `bench` wraps the same
entrypoint. Every command takes --config (a YAML over the defaults) and
resolves products/benchmarks/drivers through the registry.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from bench.core.config import load_config
from bench.core.registry import discover


def _reg(config_path: str | None):
    cfg = load_config(config_path)
    return cfg, discover(cfg)


def _driver_arg(cfg: dict, driver_name: str | None) -> dict:
    if driver_name:
        cfg["driver"] = driver_name
    return cfg


def cmd_run(args) -> None:
    """The sequential suite (the gold-standard path)."""
    from bench.runner import run_suite
    cfg, reg = _reg(args.config)
    _driver_arg(cfg, args.driver)
    benchmarks = [b for b in args.benchmarks.split(",") if b]
    products = [p for p in args.products.split(",") if p]
    if args.out:
        cfg["results_dir"] = args.out
    run_suite(cfg, reg, reg.driver(), benchmarks, products, trials=args.trials,
              aa=args.aa, phase=args.phase, skip_versions=args.skip_versions,
              settle_only=args.settle_only)


def cmd_settle(args) -> None:
    """The settle pass only (templates for steady-state measurement)."""
    from bench.runner import run_suite
    cfg, reg = _reg(args.config)
    _driver_arg(cfg, args.driver)
    products = [p for p in args.products.split(",") if p]
    run_suite(cfg, reg, reg.driver(), [], products, settle_only=True)


def cmd_explore(args) -> None:
    """Interactive onboarding explorer (dev tool)."""
    from bench.drivers.explore import explore
    cfg, reg = _reg(args.config)
    _driver_arg(cfg, args.driver)
    keys = [k for k in args.keys.split(",") if k] if args.keys else None
    explore(reg, args.product, args.seconds, keys)


def cmd_install_disk(args) -> None:
    """The one-shot install-footprint accounting artifact."""
    from bench.adapters.benchmarks.install_disk import account_all
    cfg, reg = _reg(args.config)
    tmp = reg.layout.fixtures / "npm-pack"
    out = account_all(list(reg.products.values()), tmp,
                      cfg["install"]["node_runtime_paths"])
    out_dir = Path(cfg["results_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "install-disk.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


def cmd_analyze(args) -> None:
    """Aggregate trial JSONLs into summary.json / summary.md / summary.notion.json.

    The strict result-validity gate applies: only completed valid trials
    enter stats/rankings/deltas; excluded counts + reasons are reported.
    """
    from bench.analysis.aggregate import load_all
    from bench.analysis.output.json import JsonAnalyzer
    from bench.analysis.output.markdown import MarkdownAnalyzer
    from bench.analysis.output.notion import NotionAnalyzer
    from bench.analysis.validity import load_settle
    cfg, reg = _reg(args.config)
    results_dir = Path(args.results_dir or cfg["results_dir"])
    rows = load_all(results_dir)
    settle_rows = load_settle(results_dir)
    # per-benchmark gate metadata from the registry (fixture requirement,
    # applicability, completeness keys) for the validity gate
    cfg["gate_benchmarks"] = {name: {"requires_fixture": b.requires_fixture,
                                     "applicable_products": b.applicable_products,
                                     "completeness_keys": tuple(b.completeness_keys)}
                              for name, b in reg.benchmarks.items()}
    analyzers = {"summary.json": JsonAnalyzer(cfg), "summary.md": MarkdownAnalyzer(cfg),
                 "summary.notion.json": NotionAnalyzer(cfg)}
    stats = None
    for name, analyzer in analyzers.items():
        stats = analyzer.compute_stats(rows, settle_rows=settle_rows)
        (results_dir / name).write_text(analyzer.format_output(stats))
        print(f"wrote {results_dir / name}")
    if stats:
        excluded = {bench: {p: info["count"] for p, info in (entry.get("excluded") or {}).items()}
                       for bench, entry in stats["summary"].items()}
        if any(excluded.values()):
            print("excluded from rankings: " + json.dumps(excluded))
        print(json.dumps(stats["aa"], indent=1))


def cmd_list(args) -> None:
    """The registry inventory."""
    cfg, reg = _reg(args.config)
    print(json.dumps({"products": sorted(reg.products),
                      "benchmarks": sorted(reg.benchmarks),
                      "harnesses": sorted(reg.harnesses),
                      "fixtures": sorted(reg.fixtures),
                      "driver": cfg["driver"]}, indent=1))


def cmd_noop_control(args) -> None:
    """The calibrated harness floor (cat echo round-trip)."""
    cfg, reg = _reg(args.config)
    _driver_arg(cfg, args.driver)
    control = reg.driver().noop_control(rounds=args.rounds)
    out_dir = Path(cfg["results_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "noop-control.json").write_text(json.dumps(control, indent=1))
    print(json.dumps(control, indent=1))


def cmd_fixtures(args) -> None:
    """Ensure (build if missing) every fixture, or one named fixture."""
    cfg, reg = _reg(args.config)
    names = [args.fixture] if args.fixture else list(reg.fixtures)
    for name in names:
        info = reg.fixture(name).ensure()
        print(f"{name}: {json.dumps(info)[:400]}")


def cmd_orchestrator(args) -> None:
    """The multi-sandbox parallel orchestrator (iteration mode)."""
    from bench.drivers.orchestrator import run_parallel
    cfg, _ = _reg(args.config)
    benchmarks = [b for b in args.benchmarks.split(",") if b]
    products = [p for p in args.products.split(",") if p]
    manifest = run_parallel(cfg, args.parallel_config, benchmarks, products,
                            trials=args.trials, phase=args.phase,
                            aa=not args.no_aa, keep_sandboxes=args.keep_sandboxes,
                            backend_name=args.backend, dry_run=args.dry_run)
    print(json.dumps(manifest, indent=1))


def build_parser() -> argparse.ArgumentParser:
    """The argument tree; shared flags per command group."""
    ap = argparse.ArgumentParser(prog="bench", description=__doc__.splitlines()[0])
    ap.add_argument("--config", default=None, help="YAML config path")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run", help="run benchmark trials (sequential)")
    p.add_argument("--benchmarks", required=True)
    p.add_argument("--products", default="rust,ts,claude,codex,pi")
    p.add_argument("--trials", type=int, default=10)
    p.add_argument("--aa", action="store_true")
    p.add_argument("--phase", default="w1")
    p.add_argument("--out", default=None)
    p.add_argument("--driver", default=None)
    p.add_argument("--skip-versions", action="store_true")
    p.add_argument("--settle-only", action="store_true")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("settle", help="build settled home templates only")
    p.add_argument("--products", default="rust,ts,claude,codex,pi")
    p.add_argument("--driver", default=None)
    p.set_defaults(func=cmd_settle)

    p = sub.add_parser("explore", help="interactive onboarding explorer")
    p.add_argument("product")
    p.add_argument("--seconds", type=float, default=15.0)
    p.add_argument("--keys", default="")
    p.add_argument("--driver", default=None)
    p.set_defaults(func=cmd_explore)

    sub.add_parser("install-disk", help="one-shot install footprint accounting"
                   ).set_defaults(func=cmd_install_disk)

    p = sub.add_parser("analyze", help="aggregate results into summaries")
    p.add_argument("--results-dir", default=None)
    p.set_defaults(func=cmd_analyze)

    sub.add_parser("list", help="registry inventory").set_defaults(func=cmd_list)

    p = sub.add_parser("noop-control", help="calibrated harness floor")
    p.add_argument("--rounds", type=int, default=30)
    p.add_argument("--driver", default=None)
    p.set_defaults(func=cmd_noop_control)

    p = sub.add_parser("fixtures", help="ensure fixtures")
    p.add_argument("--fixture", default=None)
    p.set_defaults(func=cmd_fixtures)

    p = sub.add_parser("orchestrator", help="multi-sandbox parallel run")
    p.add_argument("--benchmarks", required=True)
    p.add_argument("--products", default="rust,ts,claude,codex,pi")
    p.add_argument("--trials", type=int, default=10)
    p.add_argument("--phase", default="w1")
    p.add_argument("--parallel-config", default="configs/parallel.yaml")
    p.add_argument("--backend", default=None, choices=["prime", "local"])
    p.add_argument("--no-aa", action="store_true")
    p.add_argument("--keep-sandboxes", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_orchestrator)
    return ap


def main() -> None:
    """python -m bench <command>."""
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
