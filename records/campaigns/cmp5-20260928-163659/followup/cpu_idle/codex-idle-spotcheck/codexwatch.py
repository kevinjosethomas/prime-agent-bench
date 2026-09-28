#!/usr/bin/env python3
"""Independent codex idle spot-check (cmp5 follow-up verification).

Reuses the harness launch path EXACTLY (registry, PTY driver, mock routing,
readiness probe, erase) but samples /proc directly — no harness sampler:
  launch A: ready -> erase -> 3s settle -> 15 direct /proc reads @2s (30s)
            -> pidstat 10x3 (if present) -> strace -c -f 10s (if permitted)
  launch B: churn watch — direct /proc tree-shape reads @1s x 30 from ready.
Every raw counter read is recorded verbatim.
"""
import json, os, shutil, subprocess, sys, time

sys.path.insert(0, "/root/bench-harness")
os.chdir("/root/bench-harness")

from bench.core.config import load_config
from bench.core.registry import discover
from bench.adapters.benchmarks.cold_start import ONBOARDING_AUTODISMISS
from bench.adapters.benchmarks.support import PROBE_TOKEN, first_paint

OUT = {"meta": {"purpose": "independent codex idle spot-check",
                "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}}

def tree_pids(root_pid):
    """Pure-/proc tree enumeration (no psutil)."""
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

def read_proc(pid):
    d = {"pid": pid}
    try:
        raw = open("/proc/%d/stat" % pid).read()
        comm = raw[raw.index("(") + 1:raw.rindex(")")]
        parts = raw.rsplit(") ", 1)[1].split()
        d["comm"] = comm
        d["state"] = parts[0]
        d["utime"] = int(parts[11])   # field 14
        d["stime"] = int(parts[12])   # field 15
        vcsw = ivcsw = None
        for line in open("/proc/%d/status" % pid):
            if line.startswith("voluntary_ctxt_switches:"):
                vcsw = int(line.split()[1])
            elif line.startswith("nonvoluntary_ctxt_switches:"):
                ivcsw = int(line.split()[1])
        d["nvcsw"], d["nivcsw"] = vcsw, ivcsw
        try:
            d["wchan"] = open("/proc/%d/wchan" % pid).read().strip()
        except OSError:
            d["wchan"] = "?"
        try:
            d["cmdline"] = open("/proc/%d/cmdline" % pid).read().replace("\0", " ").strip()[:140]
        except OSError:
            d["cmdline"] = ""
    except (OSError, ValueError, IndexError) as e:
        d["gone"] = "%s: %s" % (type(e).__name__, e)
    return d

def sample_tree(root_pid):
    return {"t": round(time.time(), 3), "utc": time.strftime("%H:%M:%S", time.gmtime()),
            "nproc": len(tree_pids(root_pid)),
            "procs": [read_proc(p) for p in tree_pids(root_pid)]}

def launch_ready(prod, bench, reg, driver, trial_dir):
    shutil.rmtree(trial_dir, ignore_errors=True)
    from pathlib import Path
    ctx = prod.new_trial(Path(trial_dir))
    ctx["routing"] = bench.routing_for(reg.cfg, prod)
    prod.apply_routing(ctx)
    bench.setup(prod, ctx, fixture=None)
    t_launch = time.time()
    app = prod.launch(ctx, driver)
    t_paint = first_paint(app)
    probe = app.probe_input_ready(PROBE_TOKEN, retry_every=0.5, timeout=120.0,
                                  start_ts=t_paint, dialog_steps=ONBOARDING_AUTODISMISS)
    erase_ok, erase_ms = app.erase_all(PROBE_TOKEN, max_backspaces=probe["chars_sent"] + 8)
    info = {"launch_to_ready_ms": probe["echo_ts_offset_ms"], "erase_ok": bool(erase_ok),
            "erase_ms": erase_ms, "probe_sends": probe["sends"],
            "launch_wall_s": round(time.time() - t_launch, 2),
            "pid": app.pid}
    return app, info

cfg = load_config("configs/sandbox.yaml")
reg = discover(cfg)
bench = reg.benchmark("compare.cpu_idle")
prod = reg.product("codex")
driver = reg.driver()
OUT["meta"]["routing"] = bench.routing_for(reg.cfg, prod)
OUT["meta"]["codex_binary"] = getattr(prod, "binary", None) or getattr(prod, "cmd", None)

# ---- launch A: the frozen-counter check (same settle discipline as harness) ----
app, info = launch_ready(prod, bench, reg, driver, "/root/bench-root/homes/codex/trials/codexcheck-A")
OUT["launchA"] = info
time.sleep(3.0)  # identical to IDLE_SETTLE_S
OUT["watchA_samples"] = []
t0 = time.time()
for i in range(15):
    s = sample_tree(app.pid)
    s["t_rel_s"] = round(time.time() - t0, 2)
    OUT["watchA_samples"].append(s)
    if i < 14:
        time.sleep(2.0 - ((time.time() - t0) % 2.0))
OUT["watchA_window_s"] = round(time.time() - t0, 2)

pids = tree_pids(app.pid)
OUT["watchA_final_pids"] = pids

# pidstat (sysstat) — an independent instrument over the same counters
try:
    r = subprocess.run(["pidstat", "-p", ",".join(str(p) for p in pids), "10", "3"],
                       capture_output=True, text=True, timeout=45)
    OUT["pidstat"] = {"returncode": r.returncode, "stdout": r.stdout[-4000:], "stderr": r.stderr[-500:]}
except FileNotFoundError:
    OUT["pidstat"] = {"absent": "pidstat not installed"}
except subprocess.TimeoutExpired:
    OUT["pidstat"] = {"error": "timeout"}

# strace -c -f over both procs, 10s — what does the tree block in?
try:
    cmd = ["timeout", "10", "strace", "-c", "-f"] + sum((["-p", str(p)] for p in pids), [])
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    OUT["strace"] = {"returncode": r.returncode, "summary": r.stderr[-4000:], "stdout": r.stdout[-500:]}
except FileNotFoundError:
    OUT["strace"] = {"absent": "strace not installed"}
except subprocess.TimeoutExpired as e:
    OUT["strace"] = {"error": "timeout", "partial": (e.stderr or b"").decode()[-2000:] if e.stderr else ""}

app.kill_tree()
time.sleep(1.0)

# ---- launch B: the churn watch — tree shape every 1s from ready, 30s ----
app2, info2 = launch_ready(prod, bench, reg, driver, "/root/bench-root/homes/codex/trials/codexcheck-B")
OUT["launchB"] = info2
OUT["watchB_samples"] = []
t1 = time.time()
for i in range(30):
    s = sample_tree(app2.pid)
    s["t_rel_s"] = round(time.time() - t1, 2)
    OUT["watchB_samples"].append(s)
    if i < 29:
        time.sleep(1.0 - ((time.time() - t1) % 1.0))
app2.kill_tree()

# ---- reduce: did ANY counter move in watchA? ----
def totals(sample):
    ut = st = vc = iv = 0
    for p in sample["procs"]:
        if "gone" not in p:
            ut += p["utime"]; st += p["stime"]; vc += p["nvcsw"]; iv += p["nivcsw"]
    return {"utime": ut, "stime": st, "nvcsw": vc, "nivcsw": iv}

first, last = totals(OUT["watchA_samples"][0]), totals(OUT["watchA_samples"][-1])
OUT["watchA_delta"] = {k: last[k] - first[k] for k in first}
OUT["watchA_nproc_series"] = [s["nproc"] for s in OUT["watchA_samples"]]
OUT["watchB_nproc_series"] = [s["nproc"] for s in OUT["watchB_samples"]]
OUT["meta"]["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

with open("/root/codexwatch-results.json", "w") as f:
    json.dump(OUT, f, indent=1, default=str)
print(json.dumps({"watchA_delta": OUT["watchA_delta"],
                  "watchA_nproc_series": OUT["watchA_nproc_series"],
                  "watchB_nproc_series": OUT["watchB_nproc_series"],
                  "pidstat_present": "returncode" in OUT.get("pidstat", {}),
                  "strace_present": "summary" in OUT.get("strace", {})}, indent=1))
print("WROTE /root/codexwatch-results.json")
