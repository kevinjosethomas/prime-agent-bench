"""The sandbox vendor tarball builder.

`bench vendor build` assembles vendor/products.tar.gz from the adapters'
product configs (``vendor:`` blocks + the kernel toolchain when a selected
product needs it): binaries, auth/config state, and the uv toolchain laid
out for the sandbox's HOME=/root. No manual recipe: one product config
change = one tarball rebuild. bootstrap.sh untars it to ``/`` so every
sandbox starts from the proven, authenticated node setup.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from bench.core.config import REPO_ROOT, load_config
from bench.core.registry import discover

DEFAULT_OUT = REPO_ROOT / "vendor" / "products.tar.gz"


def toolchain_entries(cfg: dict) -> list[dict]:
    """The shared kernel toolchain (uv + its python installs)."""
    return list(cfg.get("vendor", {}).get("toolchain", []))


def vendor_entries(cfg: dict, products: list, reg=None) -> list[dict]:
    """The resolved {src, dst, exclude?} list for the selected products.

    Shared entries (the prime toolchain, the auth files pi also needs)
    are de-duplicated by dst. The kernel toolchain rides along whenever
    any selected product builds a kernel venv."""
    if reg is None:
        reg = discover(cfg)
    by_dst: dict[str, dict] = {}
    if any(reg.product(n).needs_kernel_venv for n in products if n in reg.products):
        for entry in toolchain_entries(cfg):
            by_dst[str(entry["dst"])] = dict(entry)
    for name in products:
        prod = reg.product(name)
        for entry in prod.product_cfg.get("vendor", []):
            dst = str(entry["dst"])
            if dst in by_dst and by_dst[dst].get("src") != str(entry["src"]):
                raise ValueError(f"vendor dst conflict on {dst}: "
                                  f"{by_dst[dst].get('src')} vs {entry['src']}")
            by_dst.setdefault(dst, dict(entry))
    return list(by_dst.values())


def build_vendor_tarball(cfg: dict, products: list, out: Path,
                         dry_run: bool = False, reg=None) -> dict:
    """Stage every entry and tar it; returns the build manifest."""
    if reg is None:
        reg = discover(cfg)
    entries = vendor_entries(cfg, products, reg=reg)
    missing = [e for e in entries
               if not Path(e["src"]).exists() and not Path(e["src"]).is_symlink()]
    if missing and not dry_run:
        # fail loudly: a broken payload silently ships broken sandboxes
        detail = "; ".join(f"dst={e['dst']}: {e['src']}" for e in missing)
        raise FileNotFoundError(f"vendor src missing ({len(missing)}): {detail}")
    for entry in entries:
        entry["src_exists"] = Path(entry["src"]).exists() or Path(entry["src"]).is_symlink()
    manifest = {
        "products": {},
        "entries": [{k: v for k, v in e.items()} for e in entries],
        "dry_run": dry_run,
    }
    for name in products:
        try:
            manifest["products"][name] = reg.product(name).version_info()
        except Exception as e:
            # dry-run planning off-node: record the error, fail on build
            manifest["products"][name] = {"error": str(e)[:200]}
    if dry_run:
        print(f"vendor plan: {len(entries)} entries, {len(products)} products"
              + (f", {sum(1 for e in entries if not e['src_exists'])} srcs missing"
                 " (build on the node)" if any(not e["src_exists"] for e in entries)
                 else ""))
        return manifest
    staging = Path(tempfile.mkdtemp(prefix="bench-vendor-"))
    try:
        for entry in entries:
            src = Path(entry["src"])
            dst = staging / entry["dst"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_symlink():
                dst.symlink_to(os.readlink(src))
            elif src.is_dir():
                argv = ["rsync", "-a"]
                for excl in entry.get("exclude", []):
                    argv += [f"--exclude={excl}"]
                subprocess.run(argv + [str(src) + "/", str(dst) + "/"], check=True)
            else:
                shutil.copy2(src, dst)
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["tar", "-czf", str(out), "-C", str(staging), "."],
                      check=True, timeout=3600)
    finally:
        subprocess.run(["rm", "-rf", str(staging)])
    manifest["tarball"] = str(out)
    manifest["bytes"] = out.stat().st_size
    manifest_path = out.parent / "build-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=1))
    print(f"vendor tarball: {out} ({manifest['bytes']} bytes, "
          f"{len(entries)} entries, {len(products)} products)")
    return manifest


def main() -> None:
    """Usage: python -m bench.drivers.vendor [--products ...] [--out ...]"""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default=None)
    ap.add_argument("--products", default="rust,ts,claude,codex,pi")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--dry-run", action="store_true",
                    help="list the entries and manifest without tarring")
    args = ap.parse_args()
    cfg = load_config(args.config)
    products = [p for p in args.products.split(",") if p]
    manifest = build_vendor_tarball(cfg, products, Path(args.out).expanduser(),
                                    dry_run=args.dry_run)
    print(json.dumps(manifest, indent=1))


if __name__ == "__main__":
    main()
