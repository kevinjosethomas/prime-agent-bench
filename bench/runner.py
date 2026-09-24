"""The sequential suite runner: the gold-standard single-node path.

Mock provider lifecycle, version evidence, home templates, the settle
pass, fixture ensure, the noop control, ABBA trial waves (bench.trials),
and the final cross-trial sweep. One product benchmarks at a time (the
fairness rule); parallel iteration belongs to bench.drivers.orchestrator.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from bench.adapters.benchmarks.support import PROBE_TOKEN, first_paint
from bench.core.env import BenchLayout
from bench.core.identity import default_run_label, harness_identity
from bench.core.process import pids_referencing
from bench.core.registry import Registry, discover
from bench.drivers.mock_state import DEFAULT_REPLY
from bench.gates import gate_idle
from bench.trials import effective_trials, run_trials


def rsync_dir(src: Path, dst: Path) -> None:
    """Mirror src/ into dst/ (rsync -a)."""
    subprocess.run(["rsync", "-a", str(src) + "/", str(dst) + "/"], check=True)


def mock_script_path(cfg: dict) -> Path:
    """The on-disk mock script path."""
    return BenchLayout.from_config(cfg).harness_dir / "mock-script.json"


def write_mock_script(cfg: dict, script: dict) -> Path:
    """Write the mock-provider script and return its path."""
    path = mock_script_path(cfg)
    path.write_text(json.dumps(script))
    return path


def start_mock(cfg: dict, script: dict | None = None):
    """Ensure the offline mock provider is live; returns its process (or
    None when one is already serving the configured port)."""
    port = int(cfg["mock"]["port"])
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            print(f"mock provider already live on 127.0.0.1:{port}")
            return None
    except OSError:
        pass
    path = write_mock_script(cfg, script or {"responses": [{"text": DEFAULT_REPLY}]})
    layout = BenchLayout.from_config(cfg)
    layout.logs.mkdir(parents=True, exist_ok=True)
    log = open(layout.logs / "mock.log", "ab")
    proc = subprocess.Popen([sys.executable, "-m", "bench.drivers.mock_provider",
                             str(path), str(port)],
                            stdout=subprocess.PIPE, stderr=log, text=True)
    port = int(proc.stdout.readline().strip())
    print(f"mock provider on 127.0.0.1:{port}")
    return proc


def capture_versions(reg: Registry, names: list) -> dict:
    """The pinned version/revision evidence per product."""
    out = {}
    for name in sorted(set(names)):
        try:
            out[name] = reg.product(name).version_info()
        except Exception as e:
            out[name] = {"error": str(e)[:200]}
    return out


def prepare_templates(reg: Registry, names: list) -> None:
    """Build each product's settled home template once (.bench-template-ok)."""
    for name in names:
        prod = reg.product(name)
        tpl = prod.template_dir()
        if (tpl / ".bench-template-ok").exists():
            continue
        if tpl.exists():
            shutil.rmtree(tpl)
        tpl.mkdir(parents=True)
        prod.prepare_template(tpl)
        (tpl / ".bench-template-ok").write_text("ok")
        print(f"template ready: {name}")


def settle_product(reg: Registry, name: str, driver, out_dir: Path) -> None:
    """One onboard/bootstrap launch so one-time costs (kernel venv,
    onboarding, caches) are baked into the template; trials then measure
    steady-state process-cold starts. The settle record is kept as evidence."""
    cfg = reg.cfg
    prod = reg.product(name)
    tmp = prod.layout.homes / name / "trials" / ".settle"
    if tmp.exists():
        shutil.rmtree(tmp)
    gate_idle(cfg, tag=name)
    ctx = prod.new_trial(tmp)
    rec = {"benchmark": "settle", "product": name}
    app = None
    err = None
    try:
        app = prod.launch(ctx, driver)
        first_paint(app, timeout=float(cfg["settle"]["first_paint_timeout_s"]))
        prod.settle(app, timeout=float(cfg["settle"]["timeout_s"]), pacing=cfg["settle"])
        app.erase_all(PROBE_TOKEN)
        time.sleep(1.0)
    except Exception as e:
        err = str(e)[:300]
        if app is not None:
            rec["screen_tail"] = "\n".join(
                ln for ln in app.screen_text().splitlines() if ln.strip())[-1500:]
    finally:
        if app is not None:
            app.kill_tree()
        prod.reap(ctx)
        tpl = prod.template_dir()
        rsync_dir(ctx["home"], tpl / "home")
        if ctx["agent_dir"] and (tpl / "agent").exists():
            rsync_dir(ctx["agent_dir"], tpl / "agent")
        shutil.rmtree(tmp, ignore_errors=True)
    rec["error"] = err
    (out_dir / "settle.jsonl").open("a").write(json.dumps(rec) + "\n")
    print(f"settle {name}: {'OK' if not err else 'ERR ' + err}", flush=True)


def ensure_fixtures(reg: Registry, benchmark_names: list) -> dict:
    """Build every fixture the selected benchmarks require (idempotent)."""
    paths = {}
    needed = set()
    for b in benchmark_names:
        requires = reg.benchmark(b).requires_fixture if b in reg.benchmarks else None
        if requires:
            needed.add(requires)
    for name in needed:
        fixture = reg.fixture(name)
        info = fixture.ensure()
        paths[name] = fixture.path()
        print(f"fixture {name}: {info.get('bytes', '?')} bytes")
    return paths


def kernel_benchmarks_selected(benchmark_names: list) -> bool:
    """Whether any kernel.* benchmark is selected (needs the kernel script)."""
    return any(b.startswith("kernel.") for b in benchmark_names)


def run_suite(cfg: dict, reg: Registry, driver, benchmark_names: list, prod_names: list,
              trials: int | None = None, aa: bool = False, phase: str = "w1",
              skip_versions: bool = False, settle_only: bool = False,
              run_label: str | None = None) -> list:
    """The sequential suite flow; returns the written JSONL paths.

    trials: CLI override; per-benchmark counts resolve CLI > config
    (benchmarks.<name>.trials) > the benchmark's default. run_label: the
    campaign provenance label stamped on every row and on versions.json
    (default: wall-clock; the orchestrator passes its manifest run_id)."""
    from bench.adapters.benchmarks.kernel import kernel_script
    cfg["run"] = {"label": run_label or default_run_label()}
    cfg["harness_identity"] = harness_identity()
    out_dir = Path(cfg["results_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    layout = BenchLayout.from_config(cfg)
    for d in (layout.logs, layout.harness_dir, layout.fixtures,
              layout.homes, layout.global_dir):
        d.mkdir(parents=True, exist_ok=True)
    jsonl_paths = []
    mock = start_mock(cfg)
    try:
        if not skip_versions:
            versions = capture_versions(reg, prod_names)
            # machine-collected evidence with its provenance stamp (audit
            # F10): the collecting run + harness revision ride with the
            # version records so hand-corrected files are detectable
            meta = {"run": cfg["run"], "harness": cfg["harness_identity"],
                    "collected_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
            (out_dir / "versions.json").write_text(
                json.dumps({"_meta": meta, "products": versions}, indent=1))
            print(json.dumps(versions, indent=1))
        prepare_templates(reg, prod_names)
        if settle_only:
            for name in prod_names:
                settle_product(reg, name, driver, out_dir)
            return jsonl_paths
        if kernel_benchmarks_selected(benchmark_names):
            write_mock_script(cfg, kernel_script())
            print("kernel mock script installed")
        fixture_paths = ensure_fixtures(reg, benchmark_names)
        control = driver.noop_control(rounds=int(cfg["noop_control"]["rounds"]))
        (out_dir / "noop-control.json").write_text(json.dumps(control, indent=1))
        print("noop control (harness floor):", control)
        for b in benchmark_names:
            print(f"=== {b} ===", flush=True)
            n_trials = effective_trials(reg, b, trials)
            jsonl = run_trials(reg, driver, b, prod_names, n_trials, out_dir,
                              fixture_paths, aa, phase)
            jsonl_paths.append(jsonl)
    finally:
        if mock:
            mock.terminate()
            try:
                mock.wait(timeout=10)
            except Exception:
                pass
        final_sweep(reg)
    return jsonl_paths


def final_sweep(reg: Registry) -> None:
    """Safety net: SIGTERM every process still referencing any trial home."""
    for name in reg.products:
        leftovers = pids_referencing([str(reg.layout.homes / name / "trials")])
        for pid, _cmd in leftovers:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
