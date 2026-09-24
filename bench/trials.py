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
import shutil
import time
import uuid
from pathlib import Path

from bench.core.registry import Registry
from bench.core.harness import HarnessDriver
from bench.core.identity import default_run_label, harness_identity
from bench.core.trial_fixture import (FixtureSourceError, clone_post_evidence,
                                       stage_trial_fixture)
from bench.gates import gate_idle, node_is_busy


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
               run_label: str | None = None) -> Path:
    """Run one benchmark's trials across products (ABBA-ordered).

    Every row (trials and status rows alike) carries the provenance stamp
    ``run = {"label": ..., "harness": {...}}`` (audit F7/F8/F9): the
    campaign label groups a campaign's rows under the orchestrator's
    manifest run_id; the harness revision names the code that measured
    the row, so a results tree can never silently mix deploy versions."""
    layout = reg.layout
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

    run_id = str(uuid.uuid4())
    run = {"label": run_label or cfg_run_label(reg),
           "harness": reg.cfg.get("harness_identity") or harness_identity()}
    # comparability resolution: measure only what the spec can compare;
    # everything else is preserved as one status row (never numeric)
    comparable: list[tuple[str, str]] = []
    status_rows: list[tuple[str, str, str]] = []  # (product, status, reason)
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
    with open(jsonl, "a") as f:
        for product, status, reason in status_rows:
            rec = _status_record(run_id, benchmark_name, product, phase_tag,
                                status, reason, run)
            f.write(json.dumps(rec) + "\n")
            print(f"[{benchmark_name}] {product}: status={status} ({reason[:90]})", flush=True)
    if not comparable:
        print(f"[{benchmark_name}] no comparable products to measure", flush=True)
        return jsonl

    order = [n for n, _ in comparable]
    levels = dict(comparable)
    total_rounds = max(1, trials // 2) if aa else trials
    trial_counter = {n: 0 for n in order}
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
                "run": run,
                "benchmark": benchmark_name,
                "product": name,
                "phase": phase_tag,
                "trial": trial_counter[name],
                "round": rnd,
                "abba_position": seq.index(name),
                "wall_ts": t_start,
                "driver": driver.name,
                "comparability": levels[name],
                "env_gate": {"waited_for": gate_waited, "busy_now": node_is_busy(reg.cfg)},
            }
            ctx = prod.new_trial(trial_dir)
            clone_path = None
            error = None
            try:
                if fixture is not None and fixture_manifest is not None:
                    # Per-trial fixture clone (2026-09-24 integrity fix): the
                    # resumed product appends to the file it resumes IN PLACE,
                    # so --resume must never point at the shared golden. The
                    # golden is hash-verified against its manifest on EVERY
                    # trial (a polluted source fails the row, never gets
                    # overwritten here), the clone is staged into the
                    # product's isolated trial session dir BEFORE setup (setup
                    # may import/modify sessions), and the row carries the
                    # ACTUAL staged-clone hash — the load proof, not the
                    # manifest claim. Semantic-equivalence evidence (spec §F):
                    # golden bytes/rows/sha256 + the fixture sentinel, which
                    # the scenario verifies per trial.
                    clone_path = prod.trial_session_dir(ctx) / Path(fixture).name
                    record["fixture"] = {
                        "name": benchmark.requires_fixture, **fixture_manifest,
                        "clone": stage_trial_fixture(fixture, clone_path,
                                                     str(fixture_manifest.get(
                                                         "sha256", ""))),
                    }
                benchmark.setup(prod, ctx, fixture=clone_path)
                benchmark.measure(prod, ctx, record, driver, fixture=clone_path)
                record["validated"] = benchmark.validate(record)
            except FixtureSourceError as e:
                # polluted/missing golden: the row fails without any launch
                # and without touching the source (reset is explicit and
                # out of trial, owned by the fixture layer)
                error = f"{type(e).__name__}: {e}"
                record["error"] = error[:400]
                record["fixture"] = {"name": benchmark.requires_fixture,
                                     **(fixture_manifest or {}),
                                     "source_error": error[:400]}
            except Exception as e:
                error = f"{type(e).__name__}: {e}"
                record["error"] = error[:400]
            if clone_path is not None:
                # post-trial clone state: a resumed session legitimately
                # appends to the clone in place, so post drift is EVIDENCE
                # of the product's write, never a validation failure (the
                # pre hash on the row is the load proof)
                clone_ev = (record.get("fixture") or {}).get("clone") or {}
                clone_ev.update(clone_post_evidence(clone_path))
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
