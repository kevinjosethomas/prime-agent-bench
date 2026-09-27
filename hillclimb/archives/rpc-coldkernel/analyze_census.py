#!/usr/bin/env python3
"""Per-tid strace -ff census analyzer for the cold-kernel decomposition.

Parses <prefix>.<pid> files (strace -ff -f -tt -T: per-TID files, lines
carry NO leading pid - the rpc-baseline lesson; unfinished/resumed pairs
keyed by (tid,call)). Emits a JSON decomposition:
- execve timeline (uv / pip / probe / kernel rlm.repl / product)
- kernel boot windows: rlm.repl execve -> first stdout write (the ready frame)
- probe windows, venv-materialization window (first..last syscall touching the venv path)
- per-tid class census (openat/write/fsync/rename/unlink/clock_nanosleep counts + total T)
- command correlation: syscalls inside each receipt command's wall window

Usage: analyze_census.py <census_prefix> <receipt.json> <out.json>
"""
import glob, json, os, re, sys

LINE = re.compile(r"^(\d\d):(\d\d):(\d\d\.\d+)\s+(?:N\d+\s+)?(\w+)\((.*)$")
DUR = re.compile(r"<(\d+\.\d+)>$")

def ts_to_epoch(h, m, s):
    # relative day anchor is irrelevant: everything is same-run; use seconds-of-day
    return int(h) * 3600 + int(m) * 60 + float(s)

def parse_file(path, tid):
    events = []  # (rel_ts, call, args, result, dur)
    pending = {}  # call -> (ts, args) for unfinished
    with open(path, "r", errors="replace") as f:
        for raw in f:
            m = LINE.match(raw)
            if not m:
                if "<... " in raw and "resumed>" in raw:
                    mm = re.match(r"^(\d\d):(\d\d):(\d\d\.\d+)\s+<\.\.\. (\w+) resumed>(.*)$", raw)
                    if mm:
                        ts = ts_to_epoch(mm.group(1), mm.group(2), mm.group(3))
                        call = mm.group(4)
                        rest = mm.group(5)
                        if call in pending:
                            t0, args = pending.pop(call)
                            dm = DUR.search(rest)
                            dur = float(dm.group(1)) if dm else 0.0
                            events.append((t0, call, args, rest, dur))
                continue
            ts = ts_to_epoch(m.group(1), m.group(2), m.group(3))
            call = m.group(4)
            rest = m.group(5)
            if rest.rstrip().endswith("..."):
                pending[call] = (ts, rest)
                continue
            dm = DUR.search(rest)
            dur = float(dm.group(1)) if dm else 0.0
            events.append((ts, call, rest, None, dur))
    return events

def first_path(args):
    m = re.search(r'"([^"]*)"', args)
    return m.group(1) if m else ""

def main():
    prefix = sys.argv[1]
    receipt_path = sys.argv[2] if len(sys.argv) > 2 else None
    out_path = sys.argv[3] if len(sys.argv) > 3 else prefix + "-analysis.json"
    files = sorted(glob.glob(prefix + ".*"))
    tids = {}
    all_events = []
    for path in files:
        m = re.search(r"\.(\d+)$", path)
        if not m:
            continue
        tid = int(m.group(1))
        evs = parse_file(path, tid)
        if evs:
            tids[tid] = evs
            all_events.extend((ts, tid, call, args, res, dur) for (ts, call, args, res, dur) in evs)
    if not all_events:
        json.dump({"error": "no events", "files": files}, open(out_path, "w"), indent=1)
        return
    t0 = min(e[0] for e in all_events)
    tend = max(e[0] for e in all_events)
    rel = lambda ts: round(ts - t0, 3)

    # execve timeline
    execs = []
    for ts, tid, call, args, res, dur in all_events:
        if call != "execve":
            continue
        mm = re.match(r'^"([^"]*)", \[(.*?)\]', args)
        exe = mm.group(1) if mm else first_path(args)
        argv1 = ""
        if mm:
            m2 = re.search(r'"([^"]*)"', mm.group(2))
            argv1 = m2.group(1) if m2 else ""
        kind = ("kernel" if "rlm.repl" in args
                else "probe" if ("import inspect; import rlm" in args or "prime_agent_runtime" in args)
                else "uv" if exe.endswith("/uv")
                else "pip" if (" pip" in args and exe.endswith("python"))
                else "product" if "prime-agent" in exe
                else "other")
        execs.append({"t": rel(ts), "tid": tid, "exe": exe, "argv1": argv1, "kind": kind,
                      "args_head": args[:160]})
    # kernel boot windows: rlm.repl execve -> first write on fd 1/2 in same tid
    kernel_windows = []
    for e in execs:
        if e["kind"] != "kernel":
            continue
        evs = tids[e["tid"]]
        first_write = None
        n_openat = 0
        openat_span = None
        for ts, call, args, res, dur in evs:
            if ts < e["t"] + t0:
                continue
            if call == "write" and first_write is None and re.match(r"^[12],", args):
                first_write = rel(ts)
            if call == "openat":
                n_openat += 1
                if openat_span is None:
                    openat_span = [rel(ts), rel(ts)]
                else:
                    openat_span[1] = rel(ts)
        kernel_windows.append({"spawn_t": e["t"], "ready_write_t": first_write,
                               "boot_span_s": round(first_write - e["t"], 3) if first_write else None,
                               "import_openat_n": n_openat,
                               "import_storm_span": openat_span, "tid": e["tid"]})
    # probe windows: probe execve -> last event in that tid (or +120s)
    probe_windows = []
    for e in execs:
        if e["kind"] != "probe":
            continue
        evs = tids.get(e["tid"], [])
        last = max((x[0] for x in evs), default=e["t"] + t0)
        probe_windows.append({"start_t": e["t"], "end_t": rel(last),
                              "span_s": round(rel(last) - e["t"], 3), "tid": e["tid"]})
    # per-tid class census
    CLASSES = ("openat", "write", "fsync", "fdatasync", "rename", "unlink", "mkdir", "rmdir",
               "clock_nanosleep", "flock", "execve", "wait4")
    per_tid = {}
    for tid, evs in tids.items():
        counts = {}
        durations = {}
        for ts, call, args, res, dur in evs:
            if call not in CLASSES:
                continue
            counts[call] = counts.get(call, 0) + 1
            durations[call] = durations.get(call, 0.0) + dur
        if counts:
            per_tid[tid] = {k: {"n": counts.get(k, 0), "dur_ms": round(durations.get(k, 0.0) * 1000, 1)}
                            for k in CLASSES if counts.get(k, 0)}
    # clock_nanosleep retry census (the 20ms lock-retry class)
    sleeps = [(rel(ts), tid, dur) for ts, tid, call, args, res, dur in all_events
             if call == "clock_nanosleep"]
    # venv materialization window (any syscall mentioning the venv path)
    venv_token = None
    for ts, tid, call, args, res, dur in all_events:
        m = re.search(r'"(/[^"]*kvenv[^"]*)"', args)
        if m:
            venv_token = "/".join(m.group(1).split("/")[:5])
            break
    venv_events = [(rel(ts), tid, call) for ts, tid, call, args, res, dur in all_events
                   if venv_token and venv_token in args and call != "execve"]
    venv_window = {"token": venv_token,
                   "first_t": venv_events[0][0] if venv_events else None,
                   "last_t": venv_events[-1][0] if venv_events else None,
                   "n": len(venv_events)} if venv_token else None
    # command correlation
    commands = []
    if receipt_path and os.path.exists(receipt_path):
        rec = json.load(open(receipt_path))
        for c in rec.get("commands", []):
            t0w = c.get("t0_wall")
            if not t0w:
                continue
            # epoch sync: strace seconds-of-day vs receipt epoch seconds: derive offset
            # from the first receipt wall vs t0 is unreliable; instead use trial receipt
            # "launch" anchor: receipts carry frames with epoch walls; the first frame
            # after ready ~ t_ready. We compute offset lazily via the max-correlation
            # of the EOF: the last write to the driver pipe. Simpler: caller passes the
            # epoch of t0 via env RPC_CENSUS_T0_EPOCH when known.
            commands.append(c)
    analysis = {
        "prefix": prefix, "n_tids": len(tids),
        "t0_seconds_of_day": round(t0, 3), "span_s": round(tend - t0, 3),
        "execs": execs, "kernel_windows": kernel_windows, "probe_windows": probe_windows,
        "per_tid_census": per_tid,
        "clock_nanosleep": {"n": len(sleeps),
                            "total_s": round(sum(s[2] for s in sleeps), 3),
                            "events": [(t, tid, round(d * 1000, 1)) for t, tid, d in sleeps][:400]},
        "venv_window": venv_window,
        "write_p50_ms": None,
    }
    # overall write duration distribution (excluding the driver pipe)
    wds = [dur for ts, tid, call, args, res, dur in all_events if call == "write" and dur]
    if wds:
        wds.sort()
        analysis["write_p50_ms"] = round(wds[len(wds) // 2] * 1000, 3)
    json.dump(analysis, open(out_path, "w"), indent=1)
    print(f"ANALYSIS n_tids={len(tids)} span={tend-t0:.1f}s kernels={len(kernel_windows)} "
          f"probes={len(probe_windows)} out={out_path}")

if __name__ == "__main__":
    main()
