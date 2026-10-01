"""The ABBA trial engine: one benchmark, N products, JSONL per trial.

ABBA ordering across products (alternating trial order to cancel drift),
A/A interleaving (the same product twice per round; halves are the
even/odd trial indices), sequential isolation (one product benchmarking
at a time, never concurrent), per-trial process sweep between trials.

Comparability is resolved before any trial runs: products the spec scopes
out (applicability) or that cannot consume the fixture (spec §F
not_comparable) are preserved as one status row each — never measured,
never numeric, never ranked.
"""
from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from pathlib import Path

from bench.core.env import sha256_file
from bench.core.process import fs_type
from bench.core.registry import Registry
from bench.core.harness import HarnessDriver
from bench.core.identity import default_run_label, harness_identity
from bench.gates import gate_idle, node_is_busy


def bench_tag(benchmark_name: str) -> str:
    """A short, unique trial-dir tag per benchmark: word initials, numeric
    words kept whole (compare.cold_start -> cs, kernel.state_snapshot_50MB
    -> kss50MB). Trial paths stay short enough for the products' unix
    sockets under the trial home (see BenchLayout.trials_dir)."""
    words = re.split(r"[._]", benchmark_name.removeprefix("compare."))
    return "".join(w if w[:1].isdigit() else w[:1] for w in words if w)


def cfg_run_label(reg: Registry) -> str:
    """The campaign label configured for this suite run (``run.label``)."""
    return str(reg.cfg.get("run", {}).get("label") or default_run_label())


def effective_trials(reg: Registry, benchmark_name: str, cli_trials: int | None) -> int:
    """CLI override > config override > the benchmark's default."""
    if cli_trials is not None:
        return cli_trials
    cfg_trials = reg.cfg.get("benchmarks", {}).get(benchmark_name, {}).get("trials")
    if cfg_trials is not None:
        return int(cfg_trials)
    return reg.benchmark(benchmark_name).default_trials


def _status_record(run_id: str, benchmark_name: str, product: str, phase_tag: str,
                   status: str, reason: str, run: dict) -> dict:
    """One preserved row for a product that gets no trials: status, not zeros."""
    return {
        "schema_version": 1,
        "run_id": run_id,
        "run": run,
        "benchmark": benchmark_name,
        "product": product,
        "phase": phase_tag,
        "trial": None,
        "round": None,
        "abba_position": None,
        "wall_ts": time.time(),
        "driver": None,
        "status": status,
        "reason": reason,
        "comparability": "not_comparable",
        "duration_s": 0.0,
    }


def run_trials(reg: Registry, driver: HarnessDriver, benchmark_name: str, prod_names: list,
               trials: int, out_dir: Path, fixture_paths: dict, aa: bool, phase_tag: str,
               run_label: str | None = None, **kw) -> Path:
    """One benchmark's trials across products (ABBA-ordered); see
    run_trials_interleaved. Returns the benchmark's JSONL path."""
    return run_trials_interleaved(reg, driver, [benchmark_name], prod_names, trials,
                                  out_dir, fixture_paths, aa, phase_tag,
                                  run_label=run_label, **kw)[0]


def _comparable(reg: Registry, benchmark, prod_names: list, fixture) -> tuple[list, list]:
    """(comparable [(product, level)], status rows [(product, status, reason)])."""
    comparable, status_rows = [], []
    for name in prod_names:
        if not benchmark.applicable(name):
            status_rows.append((name, "not_applicable",
                                benchmark.applicability_note
                                or f"benchmark applies to {benchmark.applicable_products} only"))
            continue
        level, reason = benchmark.comparability(reg.product(name), fixture)
        if level == "not_comparable":
            status_rows.append((name, level, reason))
        else:
            comparable.append((name, level))
    return comparable, status_rows


def round_sequence(products: list, benchmarks: list, rnd: int, aa: bool) -> list:
    """The (product, benchmark) order of one round: products ABBA across
    rounds, each product's benchmarks alternating with them; under A/A
    every product appears twice per round (the two halves interleave in
    time)."""
    seq = products if rnd % 2 == 0 else list(reversed(products))
    if aa:
        seq = seq + seq
    benches = benchmarks if rnd % 2 == 0 else list(reversed(benchmarks))
    return [(p, b) for p in seq for b in benches]


def run_trials_interleaved(reg: Registry, driver: HarnessDriver, benchmark_names: list,
                           prod_names: list, trials: int, out_dir: Path, fixture_paths: dict,
                           aa: bool, phase_tag: str, run_label: str | None = None,
                           attempt: int = 0, warmup: bool = False,
                           identities: dict | None = None) -> list:
    """Run several benchmarks' trials interleaved in one ABBA schedule.

    Every round visits every (product, benchmark) pair, so a drift in the
    host (CPU, storage) lands on every product and benchmark alike instead
    of on whichever benchmark block it happened to overlap. ``warmup``:
    one unmeasured trial per pair before round 0 (the page-cache/first-run
    policy every product gets; rows carry phase ``warmup`` and never enter
    stats). ``attempt``: the A/A re-run index (0 = first pass); the
    analysis keeps the latest attempt per (benchmark, product).
    ``identities``: product -> version evidence stamped on every row.

    Every row (trials and status rows alike) carries the provenance stamp
    ``run = {"label": ..., "harness": {...}}`` (audit F7/F8/F9)."""
    layout = reg.layout
    run_id = str(uuid.uuid4())
    run = {"label": run_label or cfg_run_label(reg),
           "harness": reg.cfg.get("harness_identity") or harness_identity()}
    identities = identities or {}
    plans = {}
    for benchmark_name in benchmark_names:
        benchmark = reg.benchmark(benchmark_name)
        results_dir = out_dir / benchmark_name
        results_dir.mkdir(parents=True, exist_ok=True)
        jsonl = results_dir / f"trials-{phase_tag}.jsonl"
        fixture = fixture_paths.get(benchmark.requires_fixture)
        if benchmark.requires_fixture and not fixture:
            raise ValueError(f"{benchmark_name} requires fixture {benchmark.requires_fixture!r} "
                             "but no fixture path was ensured")
        fixture_manifest = (reg.fixture(benchmark.requires_fixture).manifest()
                            if benchmark.requires_fixture else None)
        comparable, status_rows = _comparable(reg, benchmark, prod_names, fixture)
        with open(jsonl, "a") as f:
            for product, status, reason in status_rows:
                rec = _status_record(run_id, benchmark_name, product, phase_tag,
                                     status, reason, run)
                f.write(json.dumps(rec) + "\n")
                print(f"[{benchmark_name}] {product}: status={status} ({reason[:90]})", flush=True)
        if not comparable:
            print(f"[{benchmark_name}] no comparable products to measure", flush=True)
        plans[benchmark_name] = {"benchmark": benchmark, "jsonl": jsonl, "fixture": fixture,
                                 "manifest": fixture_manifest, "levels": dict(comparable)}

    order = [n for n in prod_names if any(n in p["levels"] for p in plans.values())]
    counters: dict = {}

    def one_trial(name: str, benchmark_name: str, rnd, pos, phase: str) -> None:
        plan = plans[benchmark_name]
        benchmark = plan["benchmark"]
        fixture = plan["fixture"]
        gate_waited = gate_idle(reg.cfg, tag=name)
        prod = reg.product(name)
        key = (name, benchmark_name, phase)
        n = counters.get(key, 0)
        suffix = "wu" if phase == "warmup" else f"{n:02d}"
        trial_dir = layout.trials_dir(name) / f"{bench_tag(benchmark_name)}-{phase_tag}{attempt or ''}-{suffix}"
        if trial_dir.exists():
            shutil.rmtree(trial_dir)
        t_start = time.time()
        record = {
            "schema_version": 1,
            "run_id": run_id,
            "run": run,
            "benchmark": benchmark_name,
            "product": name,
            "variant": {"config": prod.config_name or name, "argv_mode": prod.display_name},
            "product_identity": identities.get(name),
            "phase": phase,
            "attempt": attempt,
            "trial": None if phase == "warmup" else n,
            "round": rnd,
            "abba_position": pos,
            "wall_ts": t_start,
            "driver": driver.name,
            "trial_dir": str(trial_dir),
            "comparability": plan["levels"][name],
            "env_gate": {"waited_for": gate_waited, "busy_now": node_is_busy(reg.cfg)},
        }
        if plan["manifest"] is not None:
            # semantic-equivalence evidence (spec §F): bytes/rows/sha256
            # + the fixture sentinel, which the scenario verifies per trial
            record["fixture"] = {"name": benchmark.requires_fixture, **plan["manifest"]}
        ctx = prod.new_trial(trial_dir)
        record["env"] = {"trial_fs": fs_type(trial_dir)}
        # the per-benchmark routing regime (mock vs real-api), resolved
        # before any launch and applied to the trial's provider/auth
        # state (adapters that route per-trial do it in apply_routing)
        ctx["routing"] = benchmark.routing_for(reg.cfg, prod)
        prod.apply_routing(ctx)
        # Session resume writes bookkeeping rows to its input. Give each
        # trial a fresh inode with identical canonical bytes so no later
        # row advertises a stale manifest for a mutated shared corpus.
        # Manifest-only fixture stubs (no on-disk artifact) keep the
        # original path: there is nothing to copy or verify.
        trial_fixture = fixture
        if (benchmark.requires_fixture in ("session-10mib", "session-10mib-compacted")
                and fixture and Path(fixture).exists()):
            trial_fixture = trial_dir / fixture.name
            shutil.copyfile(fixture, trial_fixture)
            if sha256_file(trial_fixture) != plan["manifest"]["sha256"]:
                raise RuntimeError(f"{trial_fixture} differs from its manifest before trial")
        error = None
        try:
            benchmark.setup(prod, ctx, fixture=trial_fixture)
            benchmark.measure(prod, ctx, record, driver, fixture=trial_fixture)
            record["validated"] = benchmark.validate(record)
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            record["error"] = error[:400]
        record["duration_s"] = round(time.time() - t_start, 2)
        if error or phase.startswith("debug"):
            pass  # keep trial home as evidence
        else:
            shutil.rmtree(trial_dir, ignore_errors=True)
        with open(plan["jsonl"], "a") as f:
            f.write(json.dumps(record) + "\n")
        if phase != "warmup":
            counters[key] = n + 1
        m = record.get("metrics", {})
        print(f"[{benchmark_name}] {name} {phase} {suffix} "
              f"ready={m.get('launch_to_ready_ms')} err={error is not None} "
              f"({record['duration_s']}s)", flush=True)

    if warmup:
        for name, benchmark_name in round_sequence(order, benchmark_names, 0, aa=False):
            if name in plans[benchmark_name]["levels"]:
                one_trial(name, benchmark_name, None, None, "warmup")
    total_rounds = max(1, trials // 2) if aa else trials
    for rnd in range(total_rounds):
        seq = round_sequence(order, benchmark_names, rnd, aa)
        round_order = order if rnd % 2 == 0 else list(reversed(order))
        for name, benchmark_name in seq:
            if name not in plans[benchmark_name]["levels"]:
                continue
            one_trial(name, benchmark_name, rnd, round_order.index(name), phase_tag)
    return [plans[b]["jsonl"] for b in benchmark_names]
