"""The per-sandbox wave chain: sequential benchmark waves on ONE sandbox.

The parallel orchestrator launches one wave chain per sandbox (one
benchmark type per sandbox, all products sequentially within it). Also the
single-node convenience entry point for a full campaign. Replaces the raw
wave_chain.sh: same wave structure, adapter-discovered products and
benchmarks, per-sandbox mock port and results dir from the config.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from bench.core.config import load_config
from bench.core.registry import discover
from bench.runner import run_suite

# The campaign waves: warm start, msg send, scroll+typing, cold open,
# daemon boot. install_disk is a one-shot accounting pass (bench install-disk).
DEFAULT_WAVES = [
    "compare.warm_start",
    "compare.msg_send",
    "compare.scroll_typing",
    "session.cold_open_10mib",
    "daemon.boot",
]


def run_wave_chain(config_path: str | None, benchmarks: list, products: list,
                   trials: int | None, phase: str, aa: bool,
                   aa_trials: int = 10) -> list:
    """Run the A/A calibration pass then the real trial waves."""
    cfg = load_config(config_path)
    reg = discover(cfg)
    driver = reg.driver()
    jsonl_paths = []
    if aa:
        print("=== A/A calibration pass ===", flush=True)
        jsonl_paths += run_suite(cfg, reg, driver, benchmarks, products,
                                 trials=aa_trials, aa=True, phase="aa",
                                 skip_versions=False)
    print(f"=== waves {benchmarks} phase {phase} ===", flush=True)
    jsonl_paths += run_suite(cfg, reg, driver, benchmarks, products,
                             trials=trials, aa=False, phase=phase,
                             skip_versions=False)
    return jsonl_paths


def main() -> None:
    """Usage: python -m bench.drivers.wave_chain --benchmarks b1,b2 [...]"""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default=None, help="YAML config path")
    ap.add_argument("--benchmarks", default=",".join(DEFAULT_WAVES))
    ap.add_argument("--products", default="rust,ts,claude,codex,pi")
    ap.add_argument("--trials", type=int, default=10)
    ap.add_argument("--phase", default="w1")
    ap.add_argument("--aa", dest="aa", action="store_true", default=True,
                    help="run the per-sandbox A/A calibration pass first (default)")
    ap.add_argument("--no-aa", dest="aa", action="store_false",
                    help="debugging only: skip the A/A calibration pass")
    ap.add_argument("--aa-trials", type=int, default=10)
    args = ap.parse_args()
    benchmarks = [b for b in args.benchmarks.split(",") if b]
    products = [p for p in args.products.split(",") if p]
    paths = run_wave_chain(args.config, benchmarks, products,
                           args.trials, args.phase, args.aa, args.aa_trials)
    print(json.dumps([str(p) for p in paths], indent=1))


if __name__ == "__main__":
    main()
