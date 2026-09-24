"""The ABBA trial engine: one benchmark, N products, JSONL per trial.

ABBA ordering across products (alternating trial order to cancel drift),
A/A interleaving (the same product twice per round; halves are the
even/odd trial indices), sequential isolation (one product benchmarking
at a time, never concurrent), per-trial process sweep between trials.
"""
from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path

from bench.core.registry import Registry
from bench.core.harness import HarnessDriver
from bench.gates import gate_idle, node_is_busy


def effective_trials(reg: Registry, benchmark_name: str, cli_trials: int | None) -> int:
    """CLI override > config override > the benchmark's default."""
    if cli_trials is not None:
        return cli_trials
    cfg_trials = reg.cfg.get("benchmarks", {}).get(benchmark_name, {}).get("trials")
    if cfg_trials is not None:
        return int(cfg_trials)
    return reg.benchmark(benchmark_name).default_trials


def run_trials(reg: Registry, driver: HarnessDriver, benchmark_name: str, prod_names: list,
               trials: int, out_dir: Path, fixture_paths: dict, aa: bool, phase_tag: str) -> Path:
    """Run one benchmark's trials across products (ABBA-ordered)."""
    layout = reg.layout
    benchmark = reg.benchmark(benchmark_name)
    applicable = [n for n in prod_names if benchmark.applicable(n)]
    skipped = [n for n in prod_names if not benchmark.applicable(n)]
    if skipped:
        print(f"[{benchmark_name}] not applicable, skipping: {', '.join(skipped)}")
    if not applicable:
        return out_dir / benchmark_name / f"trials-{phase_tag}.jsonl"
    results_dir = out_dir / benchmark_name
    results_dir.mkdir(parents=True, exist_ok=True)
    jsonl = results_dir / f"trials-{phase_tag}.jsonl"
    run_id = str(uuid.uuid4())
    fixture = fixture_paths.get(benchmark.requires_fixture)
    order = list(applicable)
    total_rounds = max(1, trials // 2) if aa else trials
    trial_counter = {n: 0 for n in applicable}
    for rnd in range(total_rounds):
        seq = order if rnd % 2 == 0 else list(reversed(order))
        if aa:
            # A/A: the same product interleaved twice per round; halves are
            # the even/odd trial indices (interleaved in time).
            seq = seq + seq
        for name in seq:
            if trial_counter.get(name, 0) >= (trials if not aa else 1 << 30):
                continue
            gate_waited = gate_idle(reg.cfg, tag=name)
            prod = reg.product(name)
            trial_dir = layout.homes / name / "trials" / f"{benchmark_name.replace('.', '_')}-{phase_tag}-{trial_counter[name]:02d}"
            if trial_dir.exists():
                shutil.rmtree(trial_dir)
            t_start = time.time()
            record = {
                "schema_version": 1,
                "run_id": run_id,
                "benchmark": benchmark_name,
                "product": name,
                "phase": phase_tag,
                "trial": trial_counter[name],
                "round": rnd,
                "abba_position": seq.index(name),
                "wall_ts": t_start,
                "driver": driver.name,
                "env_gate": {"waited_for": gate_waited, "busy_now": node_is_busy(reg.cfg)},
            }
            ctx = prod.new_trial(trial_dir)
            error = None
            try:
                benchmark.setup(prod, ctx, fixture=fixture)
                benchmark.measure(prod, ctx, record, driver, fixture=fixture)
                record["validated"] = benchmark.validate(record)
            except Exception as e:
                error = f"{type(e).__name__}: {e}"
                record["error"] = error[:400]
            record["duration_s"] = round(time.time() - t_start, 2)
            if error or phase_tag.startswith("debug"):
                pass  # keep trial home as evidence
            else:
                shutil.rmtree(trial_dir, ignore_errors=True)
            with open(jsonl, "a") as f:
                f.write(json.dumps(record) + "\n")
            trial_counter[name] += 1
            m = record.get("metrics", {})
            print(f"[{benchmark_name}] {name} trial {trial_counter[name] - 1} "
                  f"ready={m.get('launch_to_ready_ms')} err={error is not None} "
                  f"({record['duration_s']}s)", flush=True)
    return jsonl
