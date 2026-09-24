#!/usr/bin/env python3
"""Interactive onboarding explorer: launch a product with benchmark env and
dump rendered screen frames so the settle answers can be scripted."""
import sys, time
sys.path.insert(0, "/home/ubuntu/bench/harness")
import products as P
from ptybench import PTYApp

name = sys.argv[1]
secs = float(sys.argv[2]) if len(sys.argv) > 2 else 15
prod = P.get_product(name)
tpl = prod.template_dir()
if not (tpl / ".bench-template-ok").exists():
    tpl.mkdir(parents=True, exist_ok=True)
    prod.prepare_template(tpl)
    (tpl / ".bench-template-ok").write_text("ok")
import pathlib, shutil
trial = P.BENCH / "homes" / name / "trials" / ".explore"
if trial.exists():
    shutil.rmtree(trial)
ctx = prod.new_trial(trial)
app = PTYApp(prod.argv(ctx), env=prod.env(ctx), cwd=str(ctx["work"]))
t0 = time.time()
KEYS = {"enter": "\r", "esc": "\x1b", "tab": "\t", "space": " ", "up": "\x1b[A", "down": "\x1b[B"}
keys = [KEYS.get(k, k) for k in sys.argv[3].split(",")] if len(sys.argv) > 3 else []
last = None
def dump(tag):
    global last
    txt = app.screen_text()
    if hash(txt) != last:
        last = hash(txt)
        print(f"===== {tag} t+{time.time()-t0:.0f}s =====")
        print("\n".join(f"{i:2d}|{ln.rstrip()}" for i, ln in enumerate(txt.splitlines()) if ln.strip()))
        print(flush=True)

i = 0
while time.time() - t0 < secs:
    time.sleep(1.5)
    dump(f"wait{i}")
    i += 1
    if keys and i <= len(keys):
        app.send(keys[i - 1])
        time.sleep(1.5)
        dump(f"after-key-{keys[i-1]!r}")
app.kill_tree()
prod.reap(ctx)
shutil.rmtree(trial, ignore_errors=True)
