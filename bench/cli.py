"""The bench CLI.

python -m bench <command> [...]; the console script `bench` wraps the same
entrypoint. Every command takes --config (a YAML over the defaults) and
resolves products/benchmarks/drivers through the registry.

Commands: run | settle | explore | install-disk | analyze | list |
noop-control | fixtures | versions | vendor | sandbox | diagnose |
compare | orchestrator.
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
    """The sequential suite (the gold-standard path), on this node or in a sandbox."""
    from bench.runner import run_suite
    cfg, reg = _reg(args.config)
    _driver_arg(cfg, args.driver)
    benchmarks = [b for b in args.benchmarks.split(",") if b]
    products = [p for p in args.products.split(",") if p]
    if args.out:
        cfg["results_dir"] = args.out
    if args.sandbox:
        from bench.drivers.sandbox import run_in_sandbox
        # A/A calibration defaults ON for sandbox runs (never skippable by
        # default); --no-aa is the explicit debugging escape hatch
        aa = True if args.aa is None else args.aa
        state = run_in_sandbox(cfg, args.parallel_config, args.sandbox,
                               benchmarks, products, trials=args.trials,
                               aa=aa, phase=args.phase,
                               aa_trials=args.aa_trials or 10)
        print(json.dumps(state, indent=1))
        return
    run_suite(cfg, reg, reg.driver(), benchmarks, products, trials=args.trials,
              aa=bool(args.aa), phase=args.phase, skip_versions=args.skip_versions,
              settle_only=args.settle_only)


def cmd_versions(args) -> None:
    """The pinned version/revision/sha evidence per product."""
    cfg, reg = _reg(args.config)
    products = [p for p in args.products.split(",") if p]
    versions = {}
    for name in products:
        try:
            versions[name] = reg.product(name).version_info()
        except Exception as e:
            versions[name] = {"error": str(e)[:200]}
    if args.out:
        Path(args.out).write_text(json.dumps(versions, indent=1))
        print(f"wrote {args.out}")
    print(json.dumps(versions, indent=1))


def cmd_vendor(args) -> None:
    """Build the sandbox vendor tarball from the product configs."""
    from bench.drivers.vendor import DEFAULT_OUT, build_vendor_tarball
    cfg, _ = _reg(args.config)
    products = [p for p in args.products.split(",") if p]
    out = Path(args.out).expanduser() if args.out else DEFAULT_OUT
    manifest = build_vendor_tarball(cfg, products, out, dry_run=args.dry_run)
    print(json.dumps(manifest, indent=1))


def cmd_sandbox(args) -> None:
    """One-command sandbox setup / destroy / list (the deploy path)."""
    from bench.drivers.sandbox import (destroy_sandbox, list_sandboxes,
                                       print_readiness, setup_sandbox)
    cfg, _ = _reg(args.config)
    products = [p for p in args.products.split(",") if p]
    if args.action == "list":
        print(json.dumps(list_sandboxes(cfg), indent=1))
        return
    if not args.name:
        raise SystemExit("sandbox setup/destroy needs a name")
    if args.action == "setup":
        state = setup_sandbox(cfg, args.parallel_config, args.name, products,
                              backend_name=args.backend, mock_port=args.mock_port)
        print_readiness(state)
    elif args.action == "destroy":
        print(json.dumps(destroy_sandbox(cfg, args.parallel_config, args.name,
                                         backend_name=args.backend), indent=1))


def cmd_diagnose(args) -> None:
    """The settle-failure evidence bundle for one product."""
    from bench.drivers.diagnose import diagnose
    cfg, reg = _reg(args.config)
    diagnose(cfg, reg, args.product)


def cmd_compare(args) -> None:
    """Before/after deltas between two result sets."""
    from bench.drivers.compare import compare_runs, format_markdown
    cfg, _ = _reg(args.config)
    result = compare_runs(cfg, Path(args.run_a).expanduser(),
                          Path(args.run_b).expanduser())
    table = format_markdown(result)
    print(table)
    if args.out:
        Path(args.out).expanduser().write_text(table + "\n")


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
                       for bench, entry in stats["summary"].items()
                       if entry.get("excluded")}
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
    p.add_argument("--aa", dest="aa", action="store_true", default=None,
                   help="explicit A/A on (sandbox runs default to it)")
    p.add_argument("--no-aa", dest="aa", action="store_false",
                   help="debugging only: skip the A/A calibration pass")
    p.add_argument("--aa-trials", type=int, default=None,
                   help="A/A pass trial count for sandbox runs (default 10)")
    p.add_argument("--phase", default="w1")
    p.add_argument("--out", default=None)
    p.add_argument("--driver", default=None)
    p.add_argument("--skip-versions", action="store_true")
    p.add_argument("--settle-only", action="store_true")
    p.add_argument("--sandbox", default=None,
                   help="a live sandbox (name from `bench sandbox setup` or a raw id): run inside it")
    p.add_argument("--parallel-config", default="configs/parallel.yaml")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("versions", help="pinned version/sha evidence per product")
    p.add_argument("--products", default="rust,ts,claude,codex,pi")
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_versions)

    p = sub.add_parser("vendor", help="build the sandbox vendor tarball")
    p.add_argument("--products", default="rust,ts,claude,codex,pi")
    p.add_argument("--out", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_vendor)

    p = sub.add_parser("sandbox", help="one-command sandbox setup/destroy/list")
    p.add_argument("action", choices=["setup", "destroy", "list"])
    p.add_argument("name", nargs="?", default=None)
    p.add_argument("--products", default="rust,ts,claude,codex,pi")
    p.add_argument("--backend", default=None, choices=["prime", "local"])
    p.add_argument("--parallel-config", default="configs/parallel.yaml")
    p.add_argument("--mock-port", type=int, default=8890)
    p.set_defaults(func=cmd_sandbox)

    p = sub.add_parser("diagnose", help="settle-failure evidence bundle")
    p.add_argument("product")
    p.set_defaults(func=cmd_diagnose)

    p = sub.add_parser("compare", help="before/after deltas of two runs")
    p.add_argument("run_a")
    p.add_argument("run_b")
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_compare)

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
