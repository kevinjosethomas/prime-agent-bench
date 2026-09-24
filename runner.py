#!/usr/bin/env python3
"""Benchmark runner: ABBA-ordered trials, JSONL per trial, A/A calibration.

Usage:
  runner.py --benchmarks compare.cold_start --products ts,claude,codex,pi,rust \
            --trials 10 --out ~/bench/results
  runner.py --benchmarks compare.cold_start --products ts --aa --trials 10

Not part of any product. Benchmark harness only.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import products as P
import benchmarks as B
import kernel_bench as KB
from ptybench import noop_control

COMPILE_MARKERS = ("rustc", "cargo", "/tsc", "esbuild", "npm exec", "node-gyp", "cc1", "clang")


def node_is_busy() -> str | None:
    """A confounding active process, or None if the node is idle."""
    try:
        with open("/proc/loadavg") as f:
            load1 = float(f.read().split()[0])
    except OSError:
        return "loadavg-unreadable"
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            argv = (proc / "cmdline").read_bytes().decode(errors="replace")
        except OSError:
            continue
        if any(m in argv for m in COMPILE_MARKERS) and "runner.py" not in argv:
            return "compile:" + argv.split(chr(0))[0][:80]
    if load1 >= 0.6:
        return f"load:{load1}"
    return None


def gate_idle(max_wait=300.0, tag="") -> str | None:
    """Block until the node is idle (fairness rule). Returns the last busy
    reason waited on, or None if it was idle immediately."""
    waited = None
    deadline = time.time() + max_wait
    while time.time() < deadline:
        busy = node_is_busy()
        if busy is None:
            return waited
        waited = busy
        time.sleep(2.0)
    return waited

BENCH = P.BENCH


def start_mock(port=P.MOCK_PORT):
    import socket as _s
    try:
        with _s.create_connection(("127.0.0.1", port), timeout=0.5):
            print(f"mock provider already live on 127.0.0.1:{port}")
            return None
    except OSError:
        pass
    script = BENCH / "harness" / "mock-script.json"
    script.write_text(json.dumps({"responses": [{"text": B.MOCK_REPLY}]}))
    log = open(BENCH / "logs" / "mock.log", "ab")
    proc = subprocess.Popen([str(BENCH / "venv" / "bin" / "python"),
                             str(BENCH / "harness" / "bench_mock.py"), str(script), str(port)],
                            stdout=subprocess.PIPE, stderr=log, text=True)
    line = proc.stdout.readline()
    port = int(line.strip())
    print(f"mock provider on 127.0.0.1:{port}")
    return proc


def ensure_fixture_10mib():
    import fixtures
    out = BENCH / "fixtures" / "scale-corpus-10mib.jsonl"
    if not out.exists():
        info = fixtures.build_session(10.0, out, cwd=str(BENCH / "fixtures" / "work"))
        (BENCH / "fixtures" / "manifest-10mib.json").write_text(json.dumps(info, indent=1))
        print("fixture built:", info["bytes"], "bytes", info["rows"], "rows")
    return str(out)


def capture_versions(products):
    out = {}
    for name in products:
        try:
            out[name] = P.get_product(name).version_info()
        except Exception as e:
            out[name] = {"error": str(e)[:200]}
    return out


def prepare_templates(product_names):
    for name in product_names:
        prod = P.get_product(name)
        tpl = prod.template_dir()
        if (tpl / ".bench-template-ok").exists():
            continue
        if tpl.exists():
            shutil.rmtree(tpl)
        tpl.mkdir(parents=True)
        prod.prepare_template(tpl)
        (tpl / ".bench-template-ok").write_text("ok")
        print(f"template ready: {name}")


def rsync_dir(src: Path, dst: Path):
    subprocess.run(["rsync", "-a", str(src) + "/", str(dst) + "/"], check=True)


DIALOG_STEPS = [
    # (marker, [keys]) - dialogs are checked and answered BEFORE any probe
    # keystroke, so probe tokens never pollute text inputs.
    ("3. Provide your own API key", ["3"]),                          # codex welcome
    ("Paste or type your API key", ["sk-bench-dummy-not-real\r"]),  # codex key box
    ("Share agent traces with Prime Intellect?", ["\x1b[B", "\r"]),   # rust/ts trace consent -> Not now
    ("1. Auto (match terminal)", ["\r"]),                            # claude theme picker
    ("Do you want to use this API key?", ["\x1b[A", "\r"]),          # claude -> Yes
    ("Press Enter to continue", ["\r"]),                              # claude security note
    ("Press enter to continue", ["\r"]),                              # codex generic continue
    ("Is this a project you created or one you trust?", ["\x1b[B", "\r"]),  # claude workspace trust
    ("Trust this folder?", ["\r"]),                                    # codex folder trust (cursor prepositioned)
    ("auth.openai.com", ["\x1b", "3"]),                               # accidental OAuth page -> esc, pick 3
]


def settle_drive(app, timeout=300.0) -> str:
    """Answer known onboarding dialogs (dialogs first, probes second) until
    the editor echoes the probe token (ready)."""
    token = "Zq7x"
    answers = {}
    deadline = time.time() + timeout
    while time.time() < deadline:
        txt = app.screen_text()
        answered = False
        for marker, keys in DIALOG_STEPS:
            if marker in txt and answers.get(marker, 0) < 3:
                answers[marker] = answers.get(marker, 0) + 1
                for k in keys:
                    app.send(k)
                    time.sleep(0.7)
                answered = True
                break
        if not answered:
            app.start_echo_watch(token + "01")
            app.send(token + "01")
            try:
                app.wait_echo(1.2)
                return "ready"
            except TimeoutError:
                pass
        time.sleep(0.8)
    raise TimeoutError(f"settle never reached ready; dialogs answered: {answers}")


def settle_product(prod, out_dir: Path):
    """One onboard/bootstrap launch so one-time costs (kernel venv,
    onboarding, caches) are baked into the template; trials then measure
    steady-state process-cold starts (spec: 'clean home and documented
    caches'). The settle record is kept as evidence."""
    tmp = BENCH / "homes" / prod.name / "trials" / ".settle"
    if tmp.exists():
        shutil.rmtree(tmp)
    gate_idle(tag=prod.name)
    ctx = prod.new_trial(tmp)
    from ptybench import PTYApp
    import benchmarks as BB
    rec = {"benchmark": "settle", "product": prod.name}
    app = PTYApp(prod.argv(ctx), env=prod.env(ctx), cwd=str(ctx["work"]))
    err = None
    try:
        BB._first_paint(app, timeout=240)
        settle_drive(app, timeout=300)
        app.erase_all(BB.PROBE_TOKEN)
        time.sleep(1.0)
    except Exception as e:
        err = str(e)[:300]
        rec["screen_tail"] = "\n".join(ln for ln in app.screen_text().splitlines() if ln.strip())[-1500:]
    finally:
        app.kill_tree()
        prod.reap(ctx)
    tpl = prod.template_dir()
    rsync_dir(ctx["home"], tpl / "home")
    if ctx["agent_dir"] and (tpl / "agent").exists():
        rsync_dir(ctx["agent_dir"], tpl / "agent")
    shutil.rmtree(tmp, ignore_errors=True)
    rec["error"] = err
    (out_dir / "settle.jsonl").open("a").write(json.dumps(rec) + "\n")
    print(f"settle {prod.name}: {'OK' if not err else 'ERR ' + err}", flush=True)


def run_trials(benchmark: str, prod_names: list, trials: int, out_dir: Path,
               fixture: str | None, aa: bool, phase_tag: str):
    results_dir = out_dir / benchmark
    results_dir.mkdir(parents=True, exist_ok=True)
    jsonl = results_dir / f"trials-{phase_tag}.jsonl"
    run_id = str(uuid.uuid4())
    warm_cache = {}
    for name in prod_names:
        warm_cache[name] = 0
    order = list(prod_names)
    total_rounds = max(1, trials // 2) if aa else trials
    trial_counter = {n: 0 for n in prod_names}
    for rnd in range(total_rounds):
        seq = order if rnd % 2 == 0 else list(reversed(order))
        if aa:
            # A/A: the same product interleaved twice per round; halves are
            # the even/odd trial indices (interleaved in time).
            seq = seq + seq
        for name in seq:
            if trial_counter.get(name, 0) >= (trials if not aa else 1 << 30):
                continue
            gate_waited = gate_idle(tag=name)
            prod = P.get_product(name)
            trial_dir = BENCH / "homes" / name / "trials" / f"{benchmark.replace('.', '_')}-{phase_tag}-{trial_counter[name]:02d}"
            if trial_dir.exists():
                shutil.rmtree(trial_dir)
            t_start = time.time()
            record = {
                "schema_version": 1,
                "run_id": run_id,
                "benchmark": benchmark,
                "product": name,
                "phase": phase_tag,
                "trial": trial_counter[name],
                "round": rnd,
                "abba_position": seq.index(name),
                "wall_ts": t_start,
                "env_gate": {"waited_for": gate_waited, "busy_now": node_is_busy()},
            }
            ctx = prod.new_trial(trial_dir)
            error = None
            try:
                scenario = KB.SCENARIOS.get(benchmark) or B.SCENARIOS[benchmark]
                if benchmark == "compare.scroll_typing":
                    scenario(prod, ctx, record, fixture=fixture)
                elif benchmark == "session.cold_open_10mib":
                    scenario(prod, ctx, record, fixture=fixture)
                elif benchmark == "compare.warm_start":
                    scenario(prod, ctx, record)
                else:
                    scenario(prod, ctx, record)
            except Exception as e:
                error = f"{type(e).__name__}: {e}"
                record["error"] = error[:400]
            finally:
                pass
            record["duration_s"] = round(time.time() - t_start, 2)
            if error or phase_tag.startswith("debug"):
                pass  # keep trial home as evidence
            else:
                shutil.rmtree(trial_dir, ignore_errors=True)
            with open(jsonl, "a") as f:
                f.write(json.dumps(record) + "\n")
            trial_counter[name] += 1
            m = record.get("metrics", {})
            key = "launch_to_ready_ms" if "launch_to_ready_ms" in m else None
            print(f"[{benchmark}] {name} trial {trial_counter[name]-1} "
                  f"ready={m.get('launch_to_ready_ms')} err={error is not None} "
                  f"({record['duration_s']}s)", flush=True)
            shutil.rmtree(trial_dir, ignore_errors=True)
    return jsonl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--benchmarks", required=True)
    ap.add_argument("--products", default="rust,ts,claude,codex,pi")
    ap.add_argument("--trials", type=int, default=10)
    ap.add_argument("--out", default=str(BENCH / "results"))
    ap.add_argument("--aa", action="store_true")
    ap.add_argument("--phase", default="w1")
    ap.add_argument("--skip-versions", action="store_true")
    ap.add_argument("--settle-only", action="store_true")
    args = ap.parse_args()

    prod_names = [p for p in args.products.split(",") if p]
    bench_names = [b for b in args.benchmarks.split(",") if b]

    mock = start_mock()
    try:
        if not args.skip_versions:
            versions = capture_versions(sorted(set(prod_names)))
            (Path(args.out) / "versions.json").write_text(json.dumps(versions, indent=1))
            print(json.dumps(versions, indent=1))
        prepare_templates(prod_names)
        if args.settle_only:
            for name in prod_names:
                settle_product(P.get_product(name), Path(args.out))
            return
        fixture = ensure_fixture_10mib()
        if any(b.startswith("kernel.") for b in bench_names):
            KB.write_kernel_mock_script()
            print("kernel mock script installed")
        control = noop_control(rounds=30)
        (Path(args.out) / "noop-control.json").write_text(json.dumps(control, indent=1))
        print("noop control (harness floor):", control)
        for b in bench_names:
            print(f"=== {b} ===", flush=True)
            run_trials(b, prod_names, args.trials, Path(args.out), fixture, args.aa, args.phase)
    finally:
        if mock:
            mock.terminate()
        # safety net: sweep any process referencing a trial home
        for name in ("rust", "ts", "claude", "codex", "pi"):
            leftovers = P.pids_referencing([str(BENCH / "homes" / name / "trials")])
            for pid, cmd in leftovers:
                try:
                    os.kill(pid, 15)
                except ProcessLookupError:
                    pass


if __name__ == "__main__":
    main()
