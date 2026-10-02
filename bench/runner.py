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


def rsync_dir(src: Path, dst: Path, excludes: tuple = ()) -> None:
    """Mirror src/ into dst/ (rsync -a, runtime specials excluded).

    A settle launch can leave sockets/fifos behind (codex's app-server
    daemon-updater.sock); they are runtime junk, never template state.
    ``excludes``: src-relative runtime paths that must not reach the
    template either (a product's resident-daemon install and pid files)."""
    subprocess.run(["rsync", "-a", "--no-specials", "--no-devices",
                    *[f"--exclude=/{e}" for e in excludes],
                    str(src) + "/", str(dst) + "/"], check=True)


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
    log.close()  # the child keeps its dup; the parent must not hold it
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


#: settings keys that wire a user's own integrations into a product
#: (hooks run commands, plugins and MCP servers load code and open
#: connections); a trial template must carry none of them
PERSONAL_SETTINGS_KEYS = ("hooks", "enabledPlugins", "mcpServers")
#: path prefixes of an operator's machine
PERSONAL_PATH_MARKERS = (b"/Users/",)


#: config file types the audit reads; product-downloaded trees (plugin
#: marketplaces, caches) are product content, not operator state
CONFIG_SUFFIXES = (".json", ".toml", ".yaml", ".yml")
CONTENT_DIRS = ("plugins", "marketplaces", "cache", ".tmp", "tmp", "skills")


def template_audit(tpl: Path) -> list:
    """Operator-personal state found in a home template's config files:
    settings with hooks/plugins/MCP servers, or a config naming a macOS
    home path. An empty list = clean."""
    findings = []
    for path in sorted(p for p in tpl.rglob("*") if p.is_file() and not p.is_symlink()):
        rel_parts = path.relative_to(tpl).parts
        if path.suffix not in CONFIG_SUFFIXES or any(d in CONTENT_DIRS for d in rel_parts):
            continue
        try:
            if path.stat().st_size > (1 << 20):
                continue
            data = path.read_bytes()
        except OSError:
            continue
        rel = str(path.relative_to(tpl))
        if any(m in data for m in PERSONAL_PATH_MARKERS):
            findings.append(f"{rel}: names an operator home path")
        if path.suffix == ".json" and path.name.startswith("settings"):
            try:
                doc = json.loads(data)
            except ValueError:
                continue
            if isinstance(doc, dict):
                findings += [f"{rel}: {k}" for k in PERSONAL_SETTINGS_KEYS if doc.get(k)]
    return findings


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
        findings = template_audit(tpl)
        if findings:
            raise RuntimeError(f"{name} template carries personal state: {findings[:5]}")
        (tpl / ".bench-template-ok").write_text("ok")
        print(f"template ready: {name}")


def settle_product(reg: Registry, name: str, driver, out_dir: Path) -> None:
    """One onboard/bootstrap launch so one-time costs (kernel venv,
    onboarding, caches) are baked into the template; trials then measure
    steady-state process-cold starts. The settle record is kept as evidence."""
    cfg = reg.cfg
    prod = reg.product(name)
    tmp = prod.layout.trials_dir(name) / ".settle"
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
        rsync_dir(ctx["home"], tpl / "home", excludes=prod.template_excludes)
        if ctx["agent_dir"] and (tpl / "agent").exists():
            rsync_dir(ctx["agent_dir"], tpl / "agent")
        shutil.rmtree(tmp, ignore_errors=True)
    rec["template_audit"] = template_audit(prod.template_dir())
    if rec["template_audit"] and not err:
        err = f"template carries personal state: {rec['template_audit'][:5]}"
    rec["error"] = err
    with (out_dir / "settle.jsonl").open("a") as fh:
        fh.write(json.dumps(rec) + "\n")
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


def ensure_trial_storage(cfg: dict, layout: BenchLayout) -> str:
    """Put the trial root on the configured storage; returns its fs type.

    ``storage.trials: tmpfs`` mounts a tmpfs at <bench_root>/t (needs
    root, i.e. a sandbox): Prime VM disks flip between ~0.2 ms and ~40 ms
    per fsync for seconds to minutes at a time, and products that fsync on
    their startup path (rust, ts) then measure the host's storage regime,
    not themselves. tmpfs takes the host disk out of every product's
    launch alike. ``disk`` (default) leaves the trial root where it is."""
    from bench.core.process import fs_type
    root = layout.trials_root
    root.mkdir(parents=True, exist_ok=True)
    storage = cfg.get("storage") or {}
    want = str(storage.get("trials", "disk"))
    have = fs_type(root)
    if want == "tmpfs" and have != "tmpfs":
        size = str(storage.get("tmpfs_size", "5g"))
        subprocess.run(["mount", "-t", "tmpfs", "-o", f"size={size},mode=0755", "tmpfs",
                        str(root)], check=True)
        have = fs_type(root)
    if want == "tmpfs" and have != "tmpfs":
        raise RuntimeError(f"trial root {root} is {have}, storage.trials wants tmpfs")
    return have


def check_versions_unchanged(reg: Registry, names: list, start: dict, out_dir: Path,
                             phase: str, attempt: int) -> dict:
    """Re-collect every product's version evidence after a pass and record
    whether the binary changed under the measurement (a product that
    updates itself mid-run measured two builds). Appends to
    <results>/versions-check.jsonl; ``bench headline`` invalidates a
    changed product."""
    end = capture_versions(reg, names)
    changed = {n: {"start": identity_of(start.get(n) or {}), "end": identity_of(end.get(n) or {})}
               for n in names
               if (start.get(n) or {}).get("binary_sha256") != (end.get(n) or {}).get("binary_sha256")
               or (start.get(n) or {}).get("version") != (end.get(n) or {}).get("version")}
    rec = {"phase": phase, "attempt": attempt, "products": names, "changed": changed,
           "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    with open(out_dir / "versions-check.jsonl", "a") as f:
        f.write(json.dumps(rec) + "\n")
    for name, diff in changed.items():
        print(f"WARNING: {name} changed during the pass: {diff}", flush=True)
    return changed


def identity_of(info: dict) -> dict:
    """The per-row product identity: version + revision + binary sha256."""
    return {k: info.get(k) for k in ("version", "revision", "binary_sha256", "error")
            if info.get(k) is not None}


def run_suite(cfg: dict, reg: Registry, driver, benchmark_names: list, prod_names: list,
              trials: int | None = None, aa: bool = False, phase: str = "w1",
              skip_versions: bool = False, settle_only: bool = False,
              run_label: str | None = None, attempt: int = 0) -> list:
    """The sequential suite flow; returns the written JSONL paths.

    trials: CLI override; per-benchmark counts resolve CLI > config
    (benchmarks.<name>.trials) > the benchmark's default. run_label: the
    campaign provenance label stamped on every row and on versions.json
    (default: wall-clock; the orchestrator passes its manifest run_id).

    ``schedule.interleave: true`` runs the selected benchmarks in ONE
    ABBA schedule (every round visits every product x benchmark) instead
    of one benchmark block after another; ``schedule.warmup: true`` gives
    every product x benchmark one unmeasured warm-up trial per pass.
    ``attempt``: the A/A re-run index stamped on every row."""
    from bench.adapters.benchmarks.kernel import kernel_script
    from bench.trials import run_trials_interleaved
    cfg["run"] = {"label": run_label or default_run_label()}
    cfg["harness_identity"] = harness_identity()
    out_dir = Path(cfg["results_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    layout = BenchLayout.from_config(cfg)
    for d in (layout.logs, layout.harness_dir, layout.fixtures,
              layout.homes, layout.global_dir):
        d.mkdir(parents=True, exist_ok=True)
    ensure_trial_storage(cfg, layout)
    schedule = cfg.get("schedule") or {}
    jsonl_paths = []
    mock = start_mock(cfg)
    try:
        versions = capture_versions(reg, prod_names)
        if not skip_versions:
            # machine-collected evidence with its provenance stamp (audit
            # F10): the collecting run + harness revision ride with the
            # version records so hand-corrected files are detectable
            meta = {"run": cfg["run"], "harness": cfg["harness_identity"],
                    "collected_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
            (out_dir / "versions.json").write_text(
                json.dumps({"_meta": meta, "products": versions}, indent=1))
            print(json.dumps(versions, indent=1))
        identities = {name: identity_of(info) for name, info in versions.items()}
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
        groups = ([benchmark_names] if schedule.get("interleave")
                  else [[b] for b in benchmark_names])
        for group in groups:
            print(f"=== {','.join(group)} ===", flush=True)
            n_trials = max(effective_trials(reg, b, trials) for b in group)
            jsonl_paths += run_trials_interleaved(
                reg, driver, group, prod_names, n_trials, out_dir, fixture_paths, aa,
                phase, attempt=attempt, warmup=bool(schedule.get("warmup")),
                identities=identities)
        check_versions_unchanged(reg, prod_names, versions, out_dir, phase, attempt)
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
        leftovers = pids_referencing([str(reg.layout.trials_dir(name))])
        for pid, _cmd in leftovers:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
