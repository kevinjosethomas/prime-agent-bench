"""The parallel run loop: provision, deploy, reference-check, wave, collect.

One sandbox per benchmark type (all products sequentially inside it), a
canonical reference benchmark compared across sandboxes (>5% outliers are
replaced or normalized per policy), per-sandbox A/A + wave chains in the
background, results collected as sandboxes finish, and failed sandboxes
re-provisioned and re-run. Sandboxes are destroyed at the end unless
keep_sandboxes is set.
"""
from __future__ import annotations

import concurrent.futures as futures
import json
import time
from pathlib import Path

from bench.drivers.orchestrator.lifecycle import (collect_results, harness_bundle,
                                                  materialize, wave_once)
from bench.drivers.orchestrator.plan import (load_parallel_config, make_backend,
                                             plan_sandboxes)
from bench.drivers.orchestrator.reference import compare_references, run_reference

_MAX_PARALLEL = 8


def run_parallel(cfg: dict, parallel_config_path, benchmarks: list, products: list,
                 trials: int = 10, phase: str = "w1", aa: bool = True,
                 keep_sandboxes: bool = False, backend_name: str | None = None,
                 dry_run: bool = False) -> dict:
    """One parallel campaign; returns the run manifest (also written to disk)."""
    pcfg = load_parallel_config(parallel_config_path)
    spec_cfg = {"trials": trials, "phase": phase, "aa": aa,
                "aa_trials": pcfg.get("aa_trials", 10),
                "retry": pcfg.get("retry", {}),
                "wave_timeout_s": pcfg.get("wave_timeout_s", 14400.0)}
    specs = plan_sandboxes(cfg, pcfg, benchmarks, products)
    run_id = time.strftime("%Y%m%d-%H%M%S")
    backend = make_backend(cfg, pcfg, backend_name)
    manifest = {"run_id": run_id, "backend": backend.name,
                "benchmarks": benchmarks, "products": products,
                "sandboxes": [], "reference": {}, "kept_sandboxes": keep_sandboxes}
    print(f"[{run_id}] plan: " +
          json.dumps([{s["name"]: s["benchmarks"]} for s in specs]), flush=True)
    if dry_run:
        manifest["sandboxes"] = [{"name": s["name"], "benchmarks": s["benchmarks"],
                                  "spec": s, "status": "planned"} for s in specs]
        return manifest

    bundle = harness_bundle()
    handles = {}
    # 1. provision + deploy every sandbox (parallel, bounded)
    with futures.ThreadPoolExecutor(max_workers=_MAX_PARALLEL) as pool:
        done = {s["name"]: pool.submit(materialize, backend, s, bundle) for s in specs}
        for name, fut in done.items():
            try:
                handles[name] = fut.result()
            except Exception as e:
                print(f"[{name}] materialize failed: {str(e)[:300]}", flush=True)
                manifest["sandboxes"].append({"name": name, "status": "provision-failed",
                                              "error": str(e)[:400]})

    # 2. reference pass + outlier policy (replace or normalize)
    times = _reference_pass(backend, handles)
    ref_cfg = pcfg.get("reference", {})
    comparison = compare_references(times, float(ref_cfg.get("outlier_pct", 5.0)))
    comparison = _handle_outliers(backend, handles, times, comparison, ref_cfg, bundle)
    manifest["reference"] = comparison

    # 3. wave chains in parallel; failures re-provision and re-run
    wave_state = _run_waves(backend, handles, spec_cfg, bundle)

    # 4. collect results from every sandbox + persist the manifest
    out_dir = Path(cfg["results_dir"]) / "parallel" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, handle in handles.items():
        state = wave_state.get(name) or {}
        entry = _sandbox_entry(handle, state)
        if state.get("exit") == 0:
            try:
                entry["results"] = collect_results(backend, handle, out_dir)
            except Exception as e:
                entry["collect_error"] = str(e)[:300]
        manifest["sandboxes"].append(entry)

    # 5. teardown
    if not keep_sandboxes:
        for handle in handles.values():
            backend.destroy(handle)
    manifest["reference"]["per_sandbox_ms"] = times
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"[{run_id}] manifest: {out_dir / 'manifest.json'}", flush=True)
    return manifest


def _reference_pass(backend, handles: dict) -> dict:
    """The canonical reference on every sandbox (parallel)."""
    times = {}
    with futures.ThreadPoolExecutor(max_workers=_MAX_PARALLEL) as pool:
        done = {n: pool.submit(run_reference, backend, h) for n, h in handles.items()}
        for name, fut in done.items():
            try:
                times[name] = fut.result()
                handles[name].reference_ms = times[name]
                handles[name].note(f"reference {times[name]:.0f}ms")
            except Exception as e:
                handles[name].note(f"reference failed: {str(e)[:200]}")
    return times


def _handle_outliers(backend, handles: dict, times: dict, comparison: dict,
                     ref_cfg: dict, bundle) -> dict:
    """Replace or normalize outlier sandboxes per policy; fresh comparison."""
    policy = ref_cfg.get("outlier_policy", "replace")
    max_replace = int(ref_cfg.get("max_replacements", 2))
    for name, outlier in comparison["outliers"].items():
        handle = handles.get(name)
        if handle is None:
            continue
        if policy == "replace" and max_replace > 0:
            handle.note(f"reference outlier {outlier['dev_pct']:+.1f}% -> replacing")
            backend.destroy(handle)
            try:
                fresh = materialize(backend, handle.spec, bundle)
                fresh.replaced = True
                ms = run_reference(backend, fresh)
                fresh.reference_ms = ms
                times[name] = ms
                fresh.note(f"replacement reference {ms:.0f}ms")
            except Exception as e:
                fresh_note = str(e)[:200]
                fresh = handle
                fresh.note(f"replacement failed: {fresh_note}")
                continue
            handles[name] = fresh
            max_replace -= 1
        else:
            factor = round(outlier["ms"] / comparison["median_ms"], 4) \
                if comparison["median_ms"] else 1.0
            handle.normalize_factor = factor
            handle.note(f"reference outlier {outlier['dev_pct']:+.1f}% -> normalize x{factor}")
    comparison = compare_references(times, float(ref_cfg.get("outlier_pct", 5.0)))
    comparison["policy"] = policy
    return comparison


def _run_waves(backend, handles: dict, spec_cfg: dict, bundle) -> dict:
    """All wave chains in parallel, then bounded re-provision retries."""
    wave_state = {}
    with futures.ThreadPoolExecutor(max_workers=_MAX_PARALLEL) as pool:
        done = {n: pool.submit(wave_once, backend, h, spec_cfg)
                for n, h in handles.items()}
        for name, fut in done.items():
            wave_state[name] = fut.result()
            state = wave_state[name]
            handles[name].note(f"wave exit {state.get('exit')} "
                               f"in {state.get('wallclock_s', 0):.0f}s")
    max_retries = int(spec_cfg.get("retry", {}).get("max_retries", 2))
    for name, state in list(wave_state.items()):
        if state.get("exit") == 0:
            continue
        handle = handles[name]
        for attempt in range(1, max_retries + 1):
            handle.note(f"wave failed; re-provision (retry {attempt})")
            backend.destroy(handle)
            try:
                fresh = materialize(backend, handle.spec, bundle)
                fresh.replaced = True
                fresh.retries = attempt
                handles[name] = fresh
            except Exception as e:
                handle.note(f"re-materialize failed: {str(e)[:200]}")
                continue
            wave_state[name] = wave_once(backend, fresh, spec_cfg)
            if wave_state[name].get("exit") == 0:
                break
    return wave_state


def _sandbox_entry(handle, state: dict) -> dict:
    """The manifest record for one sandbox."""
    return {"name": handle.name, "benchmarks": handle.spec["benchmarks"],
            "reference_ms": handle.reference_ms,
            "normalize_factor": handle.normalize_factor,
            "replaced": handle.replaced, "retries": handle.retries,
            "status": "done" if state.get("exit") == 0 else "failed",
            "wave": state, "notes": handle.notes}
