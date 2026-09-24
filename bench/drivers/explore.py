"""Interactive onboarding explorer (dev tool).

Launch a product with benchmark env and dump rendered screen frames so
settle answers can be scripted. Usage (via CLI):
  bench explore <product> [seconds] [key1,key2,...]
"""
from __future__ import annotations

import shutil
import sys
import time

from bench.core.registry import Registry

KEYS = {"enter": "\r", "esc": "\x1b", "tab": "\t", "space": " ",
        "up": "\x1b[A", "down": "\x1b[B"}


def explore(reg: Registry, name: str, secs: float = 15.0, keys: list[str] | None = None) -> None:
    """Launch, observe, optionally press keys; dump frame diffs."""
    prod = reg.product(name)
    tpl = prod.template_dir()
    if not (tpl / ".bench-template-ok").exists():
        tpl.mkdir(parents=True, exist_ok=True)
        prod.prepare_template(tpl)
        (tpl / ".bench-template-ok").write_text("ok")
    trial = prod.layout.homes / name / "trials" / ".explore"
    if trial.exists():
        shutil.rmtree(trial)
    ctx = prod.new_trial(trial)
    driver = reg.driver()
    app = driver.start_session(prod.argv(ctx), env=prod.env(ctx), cwd=str(ctx["work"]))
    t0 = time.time()
    presses = [KEYS.get(k, k) for k in (keys or [])]
    last = None

    def dump(tag: str) -> None:
        nonlocal last
        txt = app.screen_text()
        if hash(txt) != last:
            last = hash(txt)
            print(f"===== {tag} t+{time.time() - t0:.0f}s =====")
            print("\n".join(f"{i:2d}|{ln.rstrip()}" for i, ln in enumerate(txt.splitlines()) if ln.strip()), flush=True)

    i = 0
    while time.time() - t0 < secs:
        time.sleep(1.5)
        dump(f"wait{i}")
        i += 1
        if presses and i <= len(presses):
            app.send(presses[i - 1])
            time.sleep(1.5)
            dump(f"after-key-{presses[i - 1]!r}")
    app.kill_tree()
    prod.reap(ctx)
    shutil.rmtree(trial, ignore_errors=True)


def main() -> None:
    """CLI entry: explore <product> [secs] [keys]."""
    from bench.core.config import load_config
    reg = discover(load_config(None))
    explore(reg, sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 15.0,
            sys.argv[3].split(",") if len(sys.argv) > 3 else None)
