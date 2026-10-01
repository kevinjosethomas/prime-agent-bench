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


def gate_attempt(cfg: dict, reg, out_dir: Path, benchmarks: list, products: list,
                 phase: str, attempt: int, trials: int, aa_trials: int) -> dict:
    """The A/A verdict per (benchmark, product) for one attempt's rows."""
    from bench.analysis.aa_validation import pair_verdict
    from bench.analysis.validity import row_exclusion
    from bench.core.measurement import primary_metric
    verdicts = {}
    for b in benchmarks:
        metric, _ = primary_metric(b) or (None, None)
        rows = {}
        for ph in ("aa", phase):
            path = out_dir / b / f"trials-{ph}.jsonl"
            rows[ph] = [json.loads(line) for line in path.read_text().splitlines()
                        if line.strip()] if path.exists() else []
        for p in products:
            def pick(ph):
                return [r for r in rows[ph] if r.get("product") == p
                        and int(r.get("attempt") or 0) == attempt
                        and row_exclusion(r, {}, {}) is None]
            verdicts[f"{b}/{p}"] = pair_verdict(pick("aa"), pick(phase), metric,
                                                cfg.get("aa", {}), expected=min(trials, aa_trials))
    return verdicts


def run_wave_chain(config_path: str | None, benchmarks: list, products: list,
                   trials: int | None, phase: str, aa: bool,
                   aa_trials: int = 10, run_label: str | None = None) -> list:
    """Run the A/A calibration pass then the real trial waves, gated.

    After each attempt every (benchmark, product) gets its A/A verdict
    (analysis.aa_validation.pair_verdict). A product failing it on any
    benchmark is re-measured — A/A pass + waves, alone — up to
    ``aa.max_reruns`` times; the analysis keeps each product's latest
    attempt, and a product still failing is INVALID in the headline
    table. The verdict history lands in <results>/aa-gate.json.

    run_label: the campaign provenance label stamped on every row and on
    versions.json (the orchestrator passes its manifest run_id so a
    sandbox's rows join back to the run that scheduled them; audit F9)."""
    cfg = load_config(config_path)
    reg = discover(cfg)
    driver = reg.driver()
    out_dir = Path(cfg["results_dir"])
    max_reruns = int(cfg.get("aa", {}).get("max_reruns", 2)) if aa else 0
    history = []
    jsonl_paths = []
    pending = list(products)
    for attempt in range(max_reruns + 1):
        if aa:
            print(f"=== A/A calibration pass (attempt {attempt}: {pending}) ===", flush=True)
            jsonl_paths += run_suite(cfg, reg, driver, benchmarks, pending,
                                     trials=aa_trials, aa=True, phase="aa",
                                     skip_versions=attempt > 0, run_label=run_label,
                                     attempt=attempt)
        print(f"=== waves {benchmarks} phase {phase} (attempt {attempt}) ===", flush=True)
        jsonl_paths += run_suite(cfg, reg, driver, benchmarks, pending,
                                 trials=trials, aa=False, phase=phase,
                                 skip_versions=aa or attempt > 0, run_label=run_label,
                                 attempt=attempt)
        if not aa:
            break
        verdicts = gate_attempt(cfg, reg, out_dir, benchmarks, pending, phase, attempt,
                                trials or 10, aa_trials)
        history.append({"attempt": attempt, "products": pending, "verdicts": verdicts})
        (out_dir / "aa-gate.json").write_text(json.dumps(history, indent=1))
        pending = sorted({key.split("/", 1)[1] for key, v in verdicts.items() if not v["ok"]},
                         key=products.index)
        for key, v in verdicts.items():
            print(f"[aa-gate] attempt {attempt} {key}: {'ok' if v['ok'] else v['reasons']} "
                  f"spread={v.get('spread_pct')} drift={v.get('drift_pct')}", flush=True)
        if not pending:
            break
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
    ap.add_argument("--run-label", default=None,
                    help="campaign label stamped on every row (the orchestrator passes its run_id)")
    args = ap.parse_args()
    benchmarks = [b for b in args.benchmarks.split(",") if b]
    products = [p for p in args.products.split(",") if p]
    paths = run_wave_chain(args.config, benchmarks, products,
                           args.trials, args.phase, args.aa, args.aa_trials,
                           args.run_label)
    print(json.dumps([str(p) for p in paths], indent=1))


if __name__ == "__main__":
    main()
