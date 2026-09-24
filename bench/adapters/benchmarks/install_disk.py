"""compare.install_disk: downloaded artifact bytes + installed footprint bytes.

One-shot per product (artifact accounting, not a timed benchmark): runs as
a benchmark writing per-product trial rows AND as the one-shot artifact
accounting (``bench install-disk``) writing install-disk.json. The kernel
venv under ~/.prime/agent is runtime state, not install footprint, and is
excluded; Node itself is shared infrastructure (recorded, not charged).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from bench.core.benchmark import Benchmark
from bench.core.product import ProductAdapter


def du(path) -> int:
    """Apparent-size bytes of a path (du -sb)."""
    if isinstance(path, str):
        path = Path(path)
    if not path.exists():
        return 0
    out = subprocess.run(["du", "-sb", str(path)], capture_output=True, text=True)
    return int(out.stdout.split()[0])


def npm_pack(pkg: str, version: str, dest: Path) -> int:
    """Download the npm tarball and return its size (the download bytes)."""
    dest.mkdir(parents=True, exist_ok=True)
    subprocess.run(["npm", "pack", f"{pkg}@{version}", "--pack-destination", str(dest)],
                   capture_output=True, text=True, cwd=str(dest))
    tarballs = list(dest.glob("*.tgz"))
    return max((t.stat().st_size for t in tarballs), default=0)


def account_product(product: ProductAdapter, tmp_dir: Path) -> dict:
    """The install-footprint accounting for one product (from its install spec)."""
    spec = product.product_cfg.get("install") or {}
    installed = sum(du(p) for p in spec.get("installed_paths", []))
    if spec.get("npm_pkg"):
        download = npm_pack(spec["npm_pkg"], str(spec.get("npm_version", "latest")),
                           tmp_dir / product.name)
    elif "download_bytes" in spec:
        download = int(spec["download_bytes"])
    elif spec.get("download_is_installed"):
        download = installed
    else:
        download = 0
    out = {"installed_bytes": installed, "download_bytes": download}
    if spec.get("note"):
        out["note"] = spec["note"]
    return out


def account_all(products, tmp_dir: Path, node_runtime_paths: list[str]) -> dict:
    """The one-shot accounting artifact for every product + shared node runtime."""
    out = {p.name: account_product(p, tmp_dir) for p in products}
    out["_node_runtime"] = {"bytes": sum(du(p) for p in node_runtime_paths),
                           "note": "shared infra, not charged per product"}
    return out


class InstallDisk(Benchmark):
    """Downloaded + installed footprint bytes (one trial per product)."""

    name = "compare.install_disk"
    default_trials = 1

    def measure(self, product, ctx, record, driver, fixture=None) -> None:
        tmp = ctx["tmp"].parent / "npm-pack"
        record["metrics"] = account_product(product, tmp)
        record["validation"] = {"installed": record["metrics"]["installed_bytes"] > 0}
