"""The parallel plan: benchmark types -> sandbox specs.

Default: one sandbox per benchmark type (the parallel axis; all products
run sequentially inside each sandbox). configs/parallel.yaml can group
several benchmark types into one sandbox and override per-benchmark
resources, images, bootstrap, and retry policy.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import yaml

from bench.core.config import REPO_ROOT
from bench.drivers.orchestrator.backend_local import LocalSandboxBackend
from bench.drivers.orchestrator.backend import PrimeSandboxBackend

PARALLEL_DEFAULTS: dict = {
    "backend": "prime",
    "aa_trials": 10,
    "keep_sandboxes": False,
    "wave_timeout_s": 14400.0,
    "reference": {"seconds": None, "outlier_pct": 5.0,
                  "outlier_policy": "replace", "max_replacements": 2},
    "retry": {"max_retries": 2},
    "groupings": {},
    "sandbox_defaults": {
        "image": "python:3.11-slim",
        "cpu_cores": 4,
        "memory_gb": 8,
        "disk_gb": 60,
        "timeout_minutes": 180,
        "bootstrap": None,
    },
    "benchmarks": {},
}


def load_parallel_config(path: str | Path | None) -> dict:
    """defaults <- configs/parallel.yaml (deep merge; missing file ok)."""
    cfg = deepcopy(PARALLEL_DEFAULTS)
    if path is not None and Path(path).exists():
        loaded = yaml.safe_load(Path(path).read_text()) or {}
        cfg = _deep_merge(cfg, loaded)
    return cfg


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _sandbox_spec(pcfg: dict, name: str, benchmarks: list, products: list,
                  port: int) -> dict:
    """Resolve one sandbox's spec: defaults <- per-benchmark overrides."""
    spec = {"name": name, "benchmarks": benchmarks, "products": products,
            "mock_port": port}
    defaults = deepcopy(pcfg["sandbox_defaults"])
    for bench in benchmarks:
        _deep_merge_into(defaults, pcfg["benchmarks"].get(bench, {}))
    spec.update(defaults)
    return spec


def _deep_merge_into(target: dict, override: dict) -> None:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge_into(target[key], value)
        else:
            target[key] = value


def plan_sandboxes(cfg: dict, pcfg: dict, benchmarks: list, products: list) -> list:
    """One SandboxSpec per benchmark type (or per configured grouping)."""
    groupings = pcfg.get("groupings") or {}
    grouped: dict = {}
    for gname, gbenches in groupings.items():
        members = [b for b in benchmarks if b in gbenches]
        if members:
            grouped[gname] = members
    leftovers = [b for b in benchmarks if not any(b in g for g in grouped.values())]
    plans = []
    port_base = int(pcfg.get("port_base", 8890))
    for gname, members in grouped.items():
        plans.append(_sandbox_spec(pcfg, gname.replace(".", "_"), members, products,
                                  port_base + len(plans)))
    for bench in leftovers:
        plans.append(_sandbox_spec(pcfg, bench.replace(".", "_"), [bench], products,
                                  port_base + len(plans)))
    return plans


def make_backend(cfg: dict, pcfg: dict, backend_name: str | None = None) -> object:
    """The configured (or explicitly requested) backend instance."""
    name = backend_name or pcfg.get("backend", "prime")
    if name == "prime":
        return PrimeSandboxBackend(cfg, pcfg)
    if name == "local":
        return LocalSandboxBackend(cfg, pcfg)
    raise ValueError(f"unknown sandbox backend: {name}")
