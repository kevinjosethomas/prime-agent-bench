"""Warm the per-product kernel venvs before the measured waves.

The products' daemons build their kernel venvs on first session launch
(uv venv + runtime + extras, ~1-4 min) and CLEAR any venv whose recorded
runtime identity does not match - a harness-built venv has no
.bootstrap-version marker, so it is wiped and rebuilt. The warm-up
launches each kernel product once and WAITS for the daemon's own
bootstrap to finish (marker present + rlm.repl importable), so no
measured trial ever races a rebuild."""
from __future__ import annotations

import argparse
import subprocess
import sys
import time

from bench.core.config import load_config
from bench.core.registry import discover


def kernel_products(reg) -> list:
    """The products that build a kernel venv (from product.yaml, not code)."""
    return sorted(name for name, prod in reg.products.items()
                  if prod.needs_kernel_venv)


def venv_ready(venv) -> bool:
    """Marker present AND rlm.repl importable.

    The marker is the daemon's own bootstrap identity: a venv without it
    (a harness-pre-built one) gets wiped and rebuilt on first launch, so
    warm-up always waits for the daemon's own build."""
    python = venv / "bin" / "python"
    marker = venv / ".bootstrap-version"
    if not python.exists() or not marker.exists():
        return False
    try:
        r = subprocess.run([str(python), "-c", "import rlm.repl"],
                           capture_output=True, timeout=60)
        return r.returncode == 0
    except Exception:
        return False


def warm(cfg, name: str, timeout_s: float = 480.0) -> bool:
    reg = discover(cfg)
    prod = reg.product(name)
    layout = reg.layout
    venv = layout.global_dir / name / "kernel-venv"
    if venv_ready(venv):
        print(f"[warm] {name}: kernel venv already ready", flush=True)
        return True
    driver = reg.driver()
    print(f"[warm] {name}: launching to build {venv}", flush=True)
    import tempfile, shutil
    from pathlib import Path
    tmp = Path(tempfile.mkdtemp(prefix=f"warm-{name}-"))
    ctx = prod.new_trial(Path(tmp) / "trial")
    app = prod.launch(ctx, driver)
    try:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if venv_ready(venv):
                print(f"[warm] {name}: kernel venv READY", flush=True)
                return True
            time.sleep(5)
        print(f"[warm] {name}: kernel venv NOT ready after {timeout_s:.0f}s", flush=True)
        return False
    finally:
        app.kill_tree()
        try:
            prod.reap(ctx)
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)


def status(cfg: dict) -> dict:
    """Per-product kernel-venv readiness (no launching)."""
    reg = discover(cfg)
    out = {}
    for name in kernel_products(reg):
        venv = reg.layout.global_dir / name / "kernel-venv"
        out[name] = venv_ready(venv)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default=None)
    ap.add_argument("--status", action="store_true",
                    help="report readiness (JSON markers) without launching")
    args = ap.parse_args()
    cfg = load_config(args.config)
    if args.status:
        import json
        for name, ready in status(cfg).items():
            print(f"BENCH-JSON {json.dumps({'product': name, 'ready': ready})}")
        return
    reg = discover(cfg)
    ok = all(warm(cfg, name) for name in kernel_products(reg))
    if not ok:
        print("[warm] FAILED: kernel venvs not ready", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
