"""YAML configuration loading with built-in defaults.

``configs/default.yaml`` externalizes trial counts, timeout budgets, load
gates, and thresholds so no orchestration knob is a magic number in code.
Per-harness pinning lives in each harness folder's ``product.yaml``
(``bench/adapters/<name>/product.yaml``).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "configs" / "default.yaml"
ADAPTERS_DIR = REPO_ROOT / "bench" / "adapters"

DEFAULTS: dict[str, Any] = {
    # The proven single-node layout: ~/bench/{harness,venv,homes,results,...}
    "bench_root": "~/bench",
    "results_dir": None,  # None -> <bench_root>/results
    "product_order": ["rust", "ts", "claude", "codex", "pi"],
    "display": {"rust": "Prime Agent Rust", "ts": "Prime Agent TS",
                "claude": "Claude Code", "codex": "Codex CLI", "pi": "Pi Mono"},
    "install": {"node_runtime_paths": ["/usr/lib/node_modules/npm", "/usr/bin/node"]},
    "driver": "pty",
    "load_gate": {
        "compile_markers": ["rustc", "cargo", "/tsc", "esbuild", "npm exec",
                            "node-gyp", "cc1", "clang"],
        "load_threshold": 0.6,
        "max_wait_s": 300.0,
        "poll_s": 2.0,
    },
    "mock": {"port": 8788},
    # the kernel toolchain `bench vendor build` ships for kernel-venv products
    "vendor": {"toolchain": [
        {"src": "~/.local/bin/uv", "dst": "root/.local/bin/uv"},
        {"src": "~/.local/bin/uvx", "dst": "root/.local/bin/uvx"},
        {"src": "~/.local/share/uv", "dst": "root/.local/share/uv"},
    ]},
    "settle": {
        "timeout_s": 300.0,
        "first_paint_timeout_s": 240.0,
        "key_pause_s": 0.7,
        "loop_s": 0.8,
        "echo_wait_s": 1.2,
    },
    "aa": {"spread_threshold_pct": 10.0, "drift_threshold_pct": 10.0,
           # rank policy (audit: rankings must never emerge uncalibrated):
           # required=false (the default) is the validation-only smoke
           # mode — stats, marks and denominators, but ranks are never
           # emitted. A publishable campaign declares required=true +
           # expected_products (the eligible cohort per benchmark, global
           # list or map — never inferred from rows) + trials (the
           # expected valid A/A rows per product; mirrors --aa-trials).
           "required": False, "trials": 10, "expected_products": None},
    "noop_control": {"rounds": 30},
    "benchmarks": {},  # per-benchmark overrides, e.g. compare.install_disk.trials
}


def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge ``override`` into ``base`` (override wins)."""
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path: str | Path | None = None) -> dict:
    """Load a YAML config over the built-in defaults.

    A missing config file is not an error: the defaults describe the proven
    node setup. Raises ``yaml.YAMLError`` on malformed YAML.
    """
    from copy import deepcopy
    cfg = deepcopy(DEFAULTS)
    if path is not None:
        text = Path(path).read_text()
        cfg = deep_merge(cfg, yaml.safe_load(text) or {})
    expand_toolchain(cfg)
    if cfg.get("results_dir") is None:
        cfg["results_dir"] = str(Path(cfg["bench_root"]).expanduser() / "results")
    return cfg


def product_config(name: str) -> dict:
    """The product's COMPLETE config: bench/adapters/<name>/product.yaml.

    The one file pinning the binary source, the auth/config sources, the
    install spec, the warm-up/settle behavior, the first-run dialogs, and
    the vendor payload for sandbox setup. ``~`` in path-valued keys
    (binary, install.installed_paths, vendor[].src, auth_sources[])
    expands to the controller home so pinning stays portable across
    nodes."""
    path = ADAPTERS_DIR / name / "product.yaml"
    if not path.exists():
        return {}
    cfg = yaml.safe_load(path.read_text()) or {}
    if isinstance(cfg.get("binary"), str):
        cfg["binary"] = str(Path(cfg["binary"]).expanduser())
    install = cfg.get("install")
    if isinstance(install, dict) and isinstance(install.get("installed_paths"), list):
        install["installed_paths"] = [str(Path(p).expanduser()) for p in install["installed_paths"]]
    for key in ("vendor", "auth_sources"):
        for entry in cfg.get(key) or []:
            if isinstance(entry, dict) and isinstance(entry.get("src"), str):
                entry["src"] = str(Path(entry["src"]).expanduser())
    return cfg


def expand_toolchain(cfg: dict) -> dict:
    """Expand ``~`` in the default config's vendor toolchain sources."""
    for entry in (cfg.get("vendor") or {}).get("toolchain", []):
        entry["src"] = str(Path(entry["src"]).expanduser())
    return cfg
