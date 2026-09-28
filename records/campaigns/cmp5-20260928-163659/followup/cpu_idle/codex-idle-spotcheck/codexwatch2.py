#!/usr/bin/env python3
"""Instrument pass: pidstat 10x3 + strace -c -f 10s over a fresh codex ready session,
plus concurrent direct /proc reads to see the instruments' own perturbation."""
import json, os, shutil, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, "/root/bench-harness")
os.chdir("/root/bench-harness")

from bench.core.config import load_config
from bench.core.registry import discover
from bench.adapters.benchmarks.cold_start import ONBOARDING_AUTODISMISS
from bench.adapters.benchmarks.support import PROBE_TOKEN, first_paint

OUT = {"meta": {"purpose": "codex idle instrument pass (pidstat + strace)",
                "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}}

def tree_pids(root_pid):
    pids, stack = [], [root_pid]
    while stack:
        p = stack.pop()
        pids.append(p)
        try:
            for line in open("/proc/%d/task/%d/children" % (p, p)):
                stack.extend(int(x) for x in line.split())
        except OSError:
            pass
    return sorted(set(pids))

def read_counters(pid):
    raw = open("/proc/%d/stat" % pid).read()
    parts = raw.rsplit(") ", 1)[1].split()
    vcsw = ivcsw = None
    for line in open("/proc/%d/status" % pid):
        if line.startswith("voluntary_ctxt_switches:"):
            vcsw = int(line.split()[1])
        elif line.startswith("nonvoluntary_ctxt_switches:"):
            ivcsw = int(line.split()[1])
    return {"utime": int(parts[11]), "stime": int(parts[12]), "nvcsw": vcsw, "nivcsw": ivcsw}

cfg = load_config("configs/sandbox.yaml")
reg = discover(cfg)
bench = reg.benchmark("compare.cpu_idle")
prod = reg.product("codex")
driver = reg.driver()

trial_dir = "/root/bench-root/homes/codex/trials/codexcheck-C"
shutil.rmtree(trial_dir, ignore_errors=True)
ctx = prod.new_trial(Path(trial_dir))
ctx["routing"] = bench.routing_for(reg.cfg, prod)
prod.apply_routing(ctx)
bench.setup(prod, ctx, fixture=None)

app = prod.launch(ctx, driver)
t_paint = first_paint(app)
probe = app.probe_input_ready(PROBE_TOKEN, retry_every=0.5, timeout=120.0,
                              start_ts=t_paint, dialog_steps=ONBOARDING_AUTODISMISS)
erase_ok, erase_ms = app.erase_all(PROBE_TOKEN, max_backspaces=probe["chars_sent"] + 8)
OUT["launch"] = {"launch_to_ready_ms": probe["echo_ts_offset_ms"], "erase_ok": bool(erase_ok), "pid": app.pid}
time.sleep(3.0)

pids = tree_pids(app.pid)
OUT["pids"] = pids
OUT["pre"] = {p: read_counters(p) for p in pids}

# pidstat over the tree, 10s interval x 3 (30s), in the background
pidstat = subprocess.Popen(["pidstat", "-p", ",".join(str(p) for p in pids), "10", "3"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

# strace -c -f attach both procs for 10s
strace = subprocess.Popen(["timeout", "10", "strace", "-c", "-f"] + sum((["-p", str(p)] for p in pids), []),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

# concurrent direct /proc reads every 2s for 12s (covers the strace window)
direct = []
t0 = time.time()
for i in range(6):
    direct.append({"t_rel_s": round(time.time() - t0, 2),
                   "counters": {p: read_counters(p) for p in tree_pids(app.pid)}})
    if i < 5:
        time.sleep(2.0)
OUT["direct_during_instruments"] = direct

strace.wait(timeout=15)
strace_out, strace_err = strace.communicate()
OUT["strace"] = {"returncode": strace.returncode, "summary": strace_err[-3500:], "stdout": strace_out[-500:]}

pidstat_out, pidstat_err = pidstat.communicate(timeout=40)
OUT["pidstat"] = {"returncode": pidstat.returncode, "stdout": pidstat_out[-4500:], "stderr": pidstat_err[-500:]}

OUT["post"] = {p: read_counters(p) for p in pids}
app.kill_tree()
OUT["meta"]["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

with open("/root/codexwatch2-results.json", "w") as f:
    json.dump(OUT, f, indent=1, default=str)
print("PRE:", json.dumps(OUT["pre"]))
print("POST:", json.dumps(OUT["post"]))
print("STRACE rc:", OUT["strace"]["returncode"])
print(OUT["strace"]["summary"][-1200:])
print("PIDSTAT rc:", OUT["pidstat"]["returncode"])
print(OUT["pidstat"]["stdout"][-1800:])
print("WROTE /root/codexwatch2-results.json")
