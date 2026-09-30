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

from bench.core.config import REPO_ROOT
from bench.core.identity import bundle_identity
from bench.drivers.orchestrator.lifecycle import (collect_results, harness_bundle,
                                                  materialize, wave_once)
from bench.drivers.orchestrator.plan import (load_parallel_config, make_backend,
                                             plan_sandboxes)
from bench.drivers.orchestrator.reference import compare_references, run_reference

# r2 (2026-09-30): 6 concurrent sandboxes - the fleet holds 16 RUNNING lanes
# and the account quota is unproven above ~18; waves of 6 keep the campaign
# clear of hard provision rejections (12 types flow through 2 waves).
_MAX_PARALLEL = 6


def _iso_now() -> str:
    """The wall-clock stamp for manifest records."""
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def run_parallel(cfg: dict, parallel_config_path, benchmarks: list, products: list,
                 trials: int = 10, phase: str = "w1", aa: bool = True,
                 keep_sandboxes: bool = False, backend_name: str | None = None,
                 dry_run: bool = False) -> dict:
    """One parallel campaign; returns the run manifest (also written to disk)."""
    pcfg = load_parallel_config(parallel_config_path)
    run_id = time.strftime("%Y%m%d-%H%M%S")
    spec_cfg = {"trials": trials, "phase": phase, "aa": aa,
                "aa_trials": pcfg.get("aa_trials", 10),
                "retry": pcfg.get("retry", {}),
                "wave_timeout_s": pcfg.get("wave_timeout_s", 14400.0),
                "run_label": run_id}
    specs = plan_sandboxes(cfg, pcfg, benchmarks, products)
    backend = make_backend(cfg, pcfg, backend_name)
    manifest = {"run_id": run_id, "backend": backend.name,
                "benchmarks": benchmarks, "products": products,
                "wave": {k: spec_cfg[k] for k in
                         ("trials", "phase", "aa", "aa_trials", "run_label")},
                "sandboxes": [], "reference": {}, "kept_sandboxes": keep_sandboxes,
                "created_at": _iso_now(), "updated_at": _iso_now()}
    # the manifest is written incrementally: every stage that completes is
    # persisted immediately, so a run that dies mid-campaign still leaves
    # its provenance on disk (audit F9: referenced runs with no manifest)
    out_dir = Path(cfg["results_dir"]) / "parallel" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    def _write_manifest() -> None:
        manifest["updated_at"] = _iso_now()
        (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))

    print(f"[{run_id}] plan: " +
          json.dumps([{s["name"]: s["benchmarks"]} for s in specs]), flush=True)
    if dry_run:
        manifest["sandboxes"] = [{"name": s["name"], "benchmarks": s["benchmarks"],
                                  "spec": s, "status": "planned"} for s in specs]
        _write_manifest()
        return manifest

    bundle = harness_bundle()
    # the deploy-bundle identity: source revision + bundle sha256, recorded
    # in the manifest and written into every sandbox next to the harness
    harness = bundle_identity(REPO_ROOT, bundle)
    manifest["harness"] = harness
    handles = {}
    # 1. provision + deploy every sandbox (parallel, bounded)
    with futures.ThreadPoolExecutor(max_workers=_MAX_PARALLEL) as pool:
        done = {s["name"]: pool.submit(materialize, backend, s, bundle, harness)
                for s in specs}
        for name, fut in done.items():
            try:
                handles[name] = fut.result()
            except Exception as e:
                print(f"[{name}] materialize failed: {str(e)[:300]}", flush=True)
                manifest["sandboxes"].append({"name": name, "status": "provision-failed",
                                              "error": str(e)[:400]})
        _write_manifest()

    # 2. reference pass + outlier policy (replace or normalize); every
    # measurement is a timestamped record so calibration claims are
    # verifiable from the published tree (audit F9/F11)
    records = _reference_records(backend, handles)
    times = {r["sandbox"]: r["ms"] for r in records}
    ref_cfg = pcfg.get("reference", {})
    comparison = compare_references(times, float(ref_cfg.get("outlier_pct", 5.0)))
    comparison = _handle_outliers(backend, handles, times, comparison, ref_cfg,
                                  bundle, harness, records)
    comparison["records"] = records
    comparison["per_sandbox_ms"] = {r["sandbox"]: r["ms"] for r in records}
    manifest["reference"] = comparison
    _write_manifest()

    # 3. wave chains in parallel; failures re-provision and re-run
    wave_state = _run_waves(backend, handles, spec_cfg, bundle, harness)

    # 4. collect results from every sandbox + persist the manifest
    for name, handle in handles.items():
        state = wave_state.get(name) or {}
        entry = _sandbox_entry(handle, state)
        if state.get("exit") == 0:
            try:
                entry["results"] = collect_results(backend, handle, out_dir)
            except Exception as e:
                entry["collect_error"] = str(e)[:300]
        manifest["sandboxes"].append(entry)
        _write_manifest()

    # 5. teardown
    if not keep_sandboxes:
        for handle in handles.values():
            backend.destroy(handle)
    manifest["reference"]["per_sandbox_ms"] = times
    _write_manifest()
    print(f"[{run_id}] manifest: {out_dir / 'manifest.json'}", flush=True)
    return manifest


def _reference_record(name: str, ms: float, replaced: bool = False,
                       replaces_ms: float | None = None) -> dict:
    """One timestamped reference-calibration record (audit F9/F11)."""
    rec = {"sandbox": name, "ms": ms, "collected_at": _iso_now(),
           "replaced": replaced}
    if replaces_ms is not None:
        rec["replaces_ms"] = replaces_ms
    return rec


def _reference_records(backend, handles: dict) -> list:
    """The canonical reference on every sandbox (parallel), as records."""
    records = []
    with futures.ThreadPoolExecutor(max_workers=_MAX_PARALLEL) as pool:
        done = {n: pool.submit(run_reference, backend, h) for n, h in handles.items()}
        for name, fut in done.items():
            try:
                ms = fut.result()
                handles[name].reference_ms = ms
                handles[name].note(f"reference {ms:.0f}ms")
                records.append(_reference_record(name, ms))
            except Exception as e:
                handles[name].note(f"reference failed: {str(e)[:200]}")
    return records


def _handle_outliers(backend, handles: dict, times: dict, comparison: dict,
                     ref_cfg: dict, bundle, harness, records: list) -> dict:
    """Replace or normalize outlier sandboxes per policy; fresh comparison.

    Replacements append a second timestamped record for the sandbox (the
    full calibration history stays in the manifest, audit F9)."""
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
                fresh = materialize(backend, handle.spec, bundle, harness)
                fresh.replaced = True
                ms = run_reference(backend, fresh)
                fresh.reference_ms = ms
                times[name] = ms
                records.append(_reference_record(name, ms, replaced=True,
                                                 replaces_ms=outlier["ms"]))
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


def _run_waves(backend, handles: dict, spec_cfg: dict, bundle,
               harness: dict | None = None) -> dict:
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
                fresh = materialize(backend, handle.spec, bundle, harness)
                fresh.replaced = True
                fresh.retries = attempt
                handles[name] = fresh
            except Exception as e:
                handle.note(f"re-materialize failed: {str(e)[:200]}")
                continue
            handle = fresh
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
