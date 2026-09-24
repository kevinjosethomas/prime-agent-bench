"""One-command sandbox setup: provision, deploy, bootstrap, verify.

`bench sandbox setup <name> --products <list>` provisions one sandbox
(from configs/parallel.yaml's sandbox_defaults), ships the harness bundle
(bench/ + configs/ + vendor/), runs the vendor bootstrap (apt deps, node,
the products tarball untarred to /), runs the warm-kernel pass, then
verifies every selected product reaches its settled interactive state
(the settle walk — dialogs answered from each product.yaml) and prints a
readiness report. The sandbox stays alive for `bench run --sandbox <name>`.

State lives at <bench_root>/sandboxes/<name>.json (sandbox id, spec,
readiness report) so setup and run share one source of truth.
"""
from __future__ import annotations

import argparse
import json
import shlex
import time
from pathlib import Path

from bench.core.config import load_config
from bench.core.env import BenchLayout
from bench.drivers.orchestrator.backend_local import LocalSandboxBackend
from bench.drivers.orchestrator.backend import PrimeSandboxBackend, SandboxHandle
from bench.drivers.orchestrator.lifecycle import (deploy_harness, harness_bundle,
                                                  wave_once)
from bench.drivers.orchestrator.plan import load_parallel_config
from bench.drivers.orchestrator.reference import run_reference


def make_backend(cfg: dict, pcfg: dict, backend_name: str | None = None):
    """The configured (or explicitly requested) sandbox backend."""
    name = backend_name or pcfg.get("backend", "prime")
    if name == "prime":
        return PrimeSandboxBackend(cfg, pcfg)
    if name == "local":
        return LocalSandboxBackend(cfg, pcfg)
    raise ValueError(f"unknown sandbox backend: {name}")


def sandbox_spec(pcfg: dict, name: str, products: list, port: int) -> dict:
    """One sandbox spec: sandbox_defaults (+ any named sandbox overrides)."""
    from copy import deepcopy
    spec = {"name": name, "benchmarks": [], "products": products,
            "mock_port": port}
    defaults = deepcopy(pcfg["sandbox_defaults"])
    defaults.update(pcfg.get("sandboxes", {}).get(name, {}))
    spec.update(defaults)
    return spec


def state_path(cfg: dict, name: str) -> Path:
    """The on-disk handle for one setup sandbox."""
    return BenchLayout.from_config(cfg).sandboxes / f"{name}.json"


def load_state(cfg: dict, name: str) -> dict:
    path = state_path(cfg, name)
    if not path.exists():
        raise FileNotFoundError(
            f"no sandbox named {name!r} (looked at {path}). "
            f"`bench sandbox list` shows the live ones")
    return json.loads(path.read_text())


def _exec_json(backend, handle, cmd: str, timeout: float = 900.0) -> list:
    """Run a command inside the sandbox; return its JSON lines output."""
    code, log = backend.exec_cmd(handle, cmd, timeout=timeout)
    if code != 0:
        raise RuntimeError(f"exec failed ({code}): {log[-400:]}")
    rows = []
    for line in log.splitlines():
        line = line.strip()
        if line.startswith("BENCH-JSON "):
            rows.append(json.loads(line[len("BENCH-JSON "):]))
    return rows


def _download_json(backend, handle, remote: str, scratch: Path) -> dict | list:
    """Pull one JSON file out of the sandbox (the exec channel wraps long
    lines; downloads are the proven path for structured data)."""
    local = scratch / Path(remote).name
    backend.download(handle, remote, local)
    return json.loads(local.read_text())


def _download_json_rows(backend, handle, remote: str, scratch: Path) -> list:
    """Pull one JSONL file out of the sandbox; one row per line."""
    local = scratch / Path(remote).name
    backend.download(handle, remote, local)
    return [json.loads(line) for line in local.read_text().splitlines()
            if line.strip()]


def verify_products(backend, handle, products: list) -> dict:
    """Per-product interactive-state verification from inside the sandbox:
    version evidence, the warm-kernel pass, and the settle walk (the
    configured first-run dialogs)."""
    import tempfile
    scratch = Path(tempfile.mkdtemp(prefix="bench-setup-verify-"))
    hd = backend.harness_dir(handle)
    root = backend.bench_root(handle)
    versions_remote = f"{root}/readiness/versions.json"
    # 1. version evidence (binary version + sha256, from the same registry)
    code, log = backend.exec_cmd(
        handle,
        f"cd {hd} && mkdir -p {root}/readiness && python3 -m bench.cli "
        f"--config configs/sandbox.yaml versions --products {','.join(products)} "
        f"--out {versions_remote}", timeout=900.0)
    if code != 0:
        raise RuntimeError(f"version probe failed inside the sandbox: {log[-400:]}")
    versions = _download_json(backend, handle, versions_remote, scratch)
    report: dict = {}
    for name, info in versions.items():
        report[name] = {"version": info}
    # 2. the settle walk (dialogs from product.yaml) IS the interactive
    # state check; it also builds the home templates, and its first launch
    # starts the daemon's kernel-venv bootstrap. settle FIRST, then warm:
    # warm_kernels launches from the template (the proven wave order).
    settle = ("python3 -m bench.cli --config configs/sandbox.yaml settle "
              f"--products {','.join(products)}")
    code, log = backend.exec_cmd(handle, f"cd {hd} && {settle}", timeout=7200.0)
    if code != 0:
        raise RuntimeError(f"settle failed inside the sandbox: {log[-400:]}")
    try:
        rows = _download_json_rows(
            backend, handle, f"{root}/results/settle.jsonl", scratch)
    except FileNotFoundError:
        rows = []
    for row in rows:
        name = row.get("product")
        if name in report:
            report[name]["settle"] = {"ok": not row.get("error"),
                                      "error": row.get("error")}
            if row.get("screen_tail"):
                report[name]["settle"]["screen_tail"] = row["screen_tail"][-600:]
    # 3. the warm-kernel pass: WAIT for the daemon's own venv build (never
    # pre-built - the daemon wipes those); idempotent: an already-ready
    # venv returns immediately. The --status flags land in the report.
    warm = "python3 -m bench.drivers.warm_kernels --config configs/sandbox.yaml"
    code, log = backend.exec_cmd(handle, f"cd {hd} && {warm}", timeout=7200.0)
    if code != 0:
        raise RuntimeError(f"warm_kernels failed inside the sandbox: {log[-400:]}")
    code, log = backend.exec_cmd(handle, f"cd {hd} && {warm} --status",
                                 timeout=300.0)
    for line in log.splitlines():
        line = line.strip()
        if line.startswith("BENCH-JSON "):
            row = json.loads(line[len("BENCH-JSON "):])
            if row["product"] in report:
                report[row["product"]]["kernel_venv_ready"] = row["ready"]
    return report


def setup_sandbox(cfg: dict, parallel_config_path, name: str, products: list,
                  backend_name: str | None = None, mock_port: int = 8890,
                  keep_alive: bool = True) -> dict:
    """Provision + deploy + bootstrap + warm + verify; the readiness report."""
    pcfg = load_parallel_config(parallel_config_path)
    backend = make_backend(cfg, pcfg, backend_name)
    spec = sandbox_spec(pcfg, name, products, mock_port)
    if spec.get("bootstrap"):
        # bootstrap.sh takes the product list as argv 1: version checks +
        # vendor payload only cover the selected products
        spec["bootstrap"] = f"{spec['bootstrap']} {','.join(products)}"
    handle = backend.provision(name, spec)
    handle.note("sandbox setup: provisioned")
    try:
        deploy_harness(backend, handle, harness_bundle())
        handle.note("sandbox setup: harness + vendor deployed, bootstrap ran")
        reference_ms = run_reference(backend, handle)
        handle.note(f"sandbox setup: reference {reference_ms:.0f}ms")
        report = verify_products(backend, handle, products)
    except Exception as e:
        state = {"name": name, "sandbox_id": handle.sandbox_id,
                 "backend": backend.name, "spec": spec, "products": products,
                 "status": "setup-failed", "error": str(e)[:400],
                 "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        state_path(cfg, name).parent.mkdir(parents=True, exist_ok=True)
        state_path(cfg, name).write_text(json.dumps(state, indent=1))
        raise
    state = {"name": name, "sandbox_id": handle.sandbox_id, "backend": backend.name,
             "spec": spec, "products": products, "status": "ready",
             "reference_ms": reference_ms, "readiness": report,
             "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    state_path(cfg, name).parent.mkdir(parents=True, exist_ok=True)
    state_path(cfg, name).write_text(json.dumps(state, indent=1))
    handle.note("sandbox setup: READY")
    if not keep_alive:  # pragma: no cover - setup keeps by default
        backend.destroy(handle)
    return state


def print_readiness(state: dict) -> None:
    """The human-readable readiness report."""
    print(f"\nsandbox {state['name']}: {state['status']} "
          f"(id {state['sandbox_id']}, backend {state['backend']})")
    if state.get("reference_ms"):
        print(f"  reference: {state['reference_ms']:.0f}ms")
    for name, row in (state.get("readiness") or {}).items():
        version = row.get("version", {})
        settle = row.get("settle", {})
        venv = row.get("kernel_venv_ready")
        bits = [f"version={version.get('version', '?')}"]
        if venv is not None:
            bits.append(f"kernel_venv={'ready' if venv else 'NOT READY'}")
        bits.append(f"settle={'OK' if settle.get('ok') else 'ERR ' + str(settle.get('error'))}")
        print(f"  {name}: " + ", ".join(bits) +
              f"  sha={str(version.get('binary_sha256', ''))[:12]}")


def destroy_sandbox(cfg: dict, parallel_config_path, name: str,
                    backend_name: str | None = None) -> dict:
    """Tear one setup sandbox down and forget its state."""
    state = load_state(cfg, name)
    pcfg = load_parallel_config(parallel_config_path)
    backend = make_backend(cfg, pcfg, backend_name or state.get("backend"))
    handle = SandboxHandle(name=state["name"], spec=state["spec"],
                           sandbox_id=state.get("sandbox_id"))
    backend.destroy(handle)
    state_path(cfg, name).unlink(missing_ok=True)
    return {"destroyed": name, "sandbox_id": state.get("sandbox_id")}


def list_sandboxes(cfg: dict) -> list:
    """The setup sandboxes this controller knows about."""
    import os
    d = BenchLayout.from_config(cfg).sandboxes
    if not d.exists():
        return []
    out = []
    for f in sorted(d.glob("*.json")):
        try:
            out.append(json.loads(f.read_text()))
        except ValueError:
            out.append({"name": f.stem, "status": "unreadable-state"})
    return out


def adopt_handle(cfg: dict, sandbox_ref: str, parallel_config_path,
                 backend_name: str | None = None):
    """Resolve --sandbox <name|raw-id> to (backend, live handle, state)."""
    pcfg = load_parallel_config(parallel_config_path)
    backend = make_backend(cfg, pcfg, backend_name)
    if state_path(cfg, sandbox_ref).exists():
        state = load_state(cfg, sandbox_ref)
    else:
        state = {"name": sandbox_ref, "sandbox_id": sandbox_ref,
                 "backend": backend.name,
                 "spec": sandbox_spec(pcfg, sandbox_ref, [], 8890),
                 "products": []}
    handle = SandboxHandle(name=state["name"], spec=state["spec"],
                           sandbox_id=state.get("sandbox_id"))
    return backend, handle, state


def run_in_sandbox(cfg: dict, parallel_config_path, sandbox_ref: str,
                   benchmarks: list, products: list, trials: int,
                   aa: bool, phase: str, aa_trials: int = 10,
                   backend_name: str | None = None) -> dict:
    """Run the trial waves inside a live sandbox (setup + run share the
    product configs: the deployed bundle carries bench/). Idempotent:
    templates and kernel venvs from setup are reused, A/A calibration
    runs first, results collect locally."""
    backend, handle, state = adopt_handle(cfg, sandbox_ref, parallel_config_path,
                                         backend_name)
    spec = dict(state["spec"])
    spec["benchmarks"] = benchmarks
    spec["products"] = products or spec.get("products") or []
    spec_cfg = {"trials": trials, "phase": phase, "aa": aa,
                "aa_trials": aa_trials, "retry": {}, "wave_timeout_s": 14400.0}
    handle.note(f"run in sandbox: {benchmarks} x {spec['products']}")
    result = wave_once(backend, handle, spec_cfg)
    out_dir = Path(cfg["results_dir"]) / "sandbox-runs" / f"{handle.name}-{time.strftime('%Y%m%d-%H%M%S')}"
    collected = None
    if result.get("exit") == 0:
        from bench.drivers.orchestrator.lifecycle import collect_results
        out_dir.mkdir(parents=True, exist_ok=True)
        collected = collect_results(backend, handle, out_dir)
    return {"sandbox": handle.name, "sandbox_id": handle.sandbox_id,
            "wave": result, "results": collected}


def main() -> None:
    """Usage: python -m bench.drivers.sandbox setup|destroy|list <name>"""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("action", choices=["setup", "destroy", "list"])
    ap.add_argument("name", nargs="?", default=None)
    ap.add_argument("--config", default=None)
    ap.add_argument("--parallel-config", default="configs/parallel.yaml")
    ap.add_argument("--products", default="rust,ts,claude,codex,pi")
    ap.add_argument("--backend", default=None, choices=["prime", "local"])
    ap.add_argument("--mock-port", type=int, default=8890)
    args = ap.parse_args()
    cfg = load_config(args.config)
    products = [p for p in args.products.split(",") if p]
    if args.action == "list":
        print(json.dumps(list_sandboxes(cfg), indent=1))
        return
    if not args.name:
        ap.error(f"{args.action} needs a sandbox name")
    if args.action == "setup":
        state = setup_sandbox(cfg, args.parallel_config, args.name, products,
                              backend_name=args.backend, mock_port=args.mock_port)
        print_readiness(state)
    elif args.action == "destroy":
        print(json.dumps(destroy_sandbox(cfg, args.parallel_config, args.name,
                                         backend_name=args.backend), indent=1))


if __name__ == "__main__":
    main()
