"""Sandbox lifecycle mechanics: bundle, deploy, wave command, collection.

The per-sandbox primitives the orchestration loop composes: pack the
harness, write the sandbox config, provision+deploy, build the wave-chain
command, run one wave, and collect (tar + download + extract) results.
"""
from __future__ import annotations

import json
import shlex
import subprocess
import time
import uuid
from pathlib import Path

from bench.core.config import REPO_ROOT
from bench.core.identity import IDENTITY_FILE


def _scratch_dir() -> Path:
    """A local scratch dir for bundles and downloads."""
    import tempfile
    d = Path(tempfile.gettempdir()) / "bench-orchestrator"
    d.mkdir(parents=True, exist_ok=True)
    return d


def harness_bundle(repo_root: Path = REPO_ROOT) -> Path:
    """Tar the harness (bench/, configs/, requirements, pyproject) for deploy.

    vendor/ (products tarball + bootstrap recipe) rides along when present,
    so one upload gives the sandbox the full node setup."""
    members = ["bench", "configs", "requirements.txt", "pyproject.toml"]
    if (repo_root / "vendor").is_dir():
        members.append("vendor")
    bundle = _scratch_dir() / f"bench-harness-{uuid.uuid4().hex[:8]}.tar.gz"
    subprocess.run(["tar", "-czf", str(bundle), "-C", str(repo_root), *members],
                   check=True, timeout=1800)
    return bundle


def _sandbox_config_yaml(handle, backend, cfg: dict | None = None) -> str:
    """The per-sandbox config: bench root, results dir, mock port, and the
    controller's per-benchmark overrides (``benchmarks:`` — trial counts
    and the msg-routing regime — so a campaign's routing decisions reach
    the sandbox's own run_suite without touching the harness defaults),
    product pin overrides (``products:`` — a run's candidate binaries) and
    the measurement policy (``aa:`` gate, ``storage:`` trial filesystem,
    ``schedule:`` interleaving + warm-ups), so the sandbox measures under
    exactly the policy the controller's manifest records."""
    import yaml as _yaml
    root = backend.bench_root(handle)
    text = (f"bench_root: {root}\n"
            f"results_dir: {Path(root) / 'results'}\n"
            f"mock:\n  port: {handle.spec['mock_port']}\n")
    for section in ("benchmarks", "products", "aa", "storage", "schedule"):
        extra = ((cfg or {}).get(section) or {})
        if extra:
            text += _yaml.safe_dump({section: extra}, sort_keys=False)
    return text


def _upload_text(backend, handle, content: str, remote: Path) -> None:
    """Ship a small text file into the sandbox."""
    tmp = _scratch_dir() / f"upload-{uuid.uuid4().hex[:8]}.txt"
    tmp.write_text(content)
    backend.upload(handle, tmp, remote)


def deploy_harness(backend, handle, bundle: Path, identity: dict | None = None,
                   cfg: dict | None = None) -> None:
    """Deploy the harness bundle + sandbox config + python deps (+bootstrap).

    identity: the deploy-bundle provenance (revision + bundle sha256),
    written next to the harness as harness-identity.json. The wave chain
    stamps it on every trial row, so a results tree can never silently
    mix deploy versions (audit F7/F8)."""
    backend.deploy(handle, bundle)
    hd = Path(backend.harness_dir(handle))
    _upload_text(backend, handle, _sandbox_config_yaml(handle, backend, cfg),
                 hd / "configs" / "sandbox.yaml")
    if identity:
        _upload_text(backend, handle, json.dumps(identity, indent=1),
                     hd / IDENTITY_FILE)
    code, log = backend.exec_cmd(
        handle, f"python3 -m pip --version >/dev/null 2>&1 || "
                f"(apt-get update -qq && apt-get install -qq -y python3-pip); "
                f"PIPOPTS=$(python3 -m pip install --help 2>&1 | "
                f"grep -q break-system-packages && echo --break-system-packages || true); "
                f"cd {hd} && python3 -m pip install -q $PIPOPTS "
                f"-r requirements.txt && echo PIP-DONE", timeout=1800.0)
    if code != 0:
        raise RuntimeError(f"pip install failed on {handle.name}: {log[-300:]}")
    bootstrap = handle.spec.get("bootstrap")
    if bootstrap:
        handle.note("running bootstrap")
        code, log = backend.exec_cmd(handle, bootstrap, timeout=7200.0)
        if code != 0:
            raise RuntimeError(f"bootstrap failed on {handle.name}: {log[-400:]}")


def materialize(backend, spec: dict, bundle: Path, identity: dict | None = None):
    """Provision + deploy + bootstrap one sandbox; returns its handle."""
    handle = backend.provision(spec["name"], spec)
    deploy_harness(backend, handle, bundle, identity, cfg=backend.cfg)
    handle.status = "ready"
    return handle


def wave_chain_cmd(handle, backend, spec_cfg: dict) -> str:
    """The per-sandbox wave chain command (A/A pass, then the real waves).

    --run-label stamps the campaign run_id on every trial row and on
    versions.json, joining the sandbox's rows to the orchestrator run
    manifest (audit F9: referenced runs with no attributable data)."""
    hd = Path(backend.harness_dir(handle))
    root = Path(backend.bench_root(handle))
    benchmarks = ",".join(handle.spec["benchmarks"])
    products = ",".join(handle.spec["products"])
    aa = "--aa " if spec_cfg.get("aa", True) else "--no-aa "
    label = (f"--run-label {shlex.quote(str(spec_cfg.get('run_label')))} "
             if spec_cfg.get("run_label") else "")
    warm = (f"mkdir -p {root / 'logs'} && cd {hd} && "
            f"python3 -m bench.cli --config configs/sandbox.yaml settle "
            f"--products {shlex.quote(products)} && "
            f"python3 -m bench.drivers.warm_kernels --config configs/sandbox.yaml "
            f"--products {shlex.quote(products)} && ")
    return (warm + f"cd {hd} && "
            f"python3 -m bench.drivers.wave_chain --config configs/sandbox.yaml "
            f"--benchmarks {shlex.quote(benchmarks)} --products {shlex.quote(products)} "
            f"--trials {spec_cfg.get('trials', 10)} --phase {spec_cfg.get('phase', 'w1')} "
            f"--aa-trials {spec_cfg.get('aa_trials', 10)} {aa}{label}"
            f"> {root / 'logs' / 'wave-chain.log'} 2>&1")


def wave_once(backend, handle, spec_cfg: dict) -> dict:
    """One sandbox's wave chain; returns its exit state."""
    timeout = float(spec_cfg.get("wave_timeout_s", 14400.0))
    t0 = time.time()
    try:
        code, log = backend.exec_cmd(handle, wave_chain_cmd(handle, backend, spec_cfg),
                                     timeout=timeout)
    except Exception as e:
        return {"exit": 1, "error": str(e)[:400], "wallclock_s": round(time.time() - t0, 1)}
    return {"exit": code, "wallclock_s": round(time.time() - t0, 1),
            "tail": log[-400:]}


def collect_results(backend, handle, out_dir: Path) -> dict:
    """Tar the sandbox results tree, download, and extract it locally."""
    root = Path(backend.bench_root(handle))
    tar_remote = Path("/tmp/results.tar.gz") if backend.name == "prime" \
        else root.parent / "results.tar.gz"
    code, log = backend.exec_cmd(
        handle, f"tar -czf {tar_remote} -C {root} --ignore-failed-read "
                f"results logs", timeout=600.0)
    if code != 0:
        raise RuntimeError(f"results tar failed: {log[-300:]}")
    local_tar = out_dir / f"{handle.name}-results.tar.gz"
    backend.download(handle, tar_remote, local_tar)
    dest = out_dir / handle.name
    dest.mkdir(parents=True, exist_ok=True)
    subprocess.run(["tar", "-xzf", str(local_tar), "-C", str(dest)], check=True, timeout=300)
    return {"path": str(dest), "tarball": str(local_tar)}
