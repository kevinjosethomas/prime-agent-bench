"""Sandbox lifecycle mechanics: bundle, deploy, wave command, collection.

The per-sandbox primitives the orchestration loop composes: pack the
harness, write the sandbox config, provision+deploy, build the wave-chain
command, run one wave, and collect (tar + download + extract) results.
"""
from __future__ import annotations

import shlex
import subprocess
import time
import uuid
from pathlib import Path

from bench.core.config import REPO_ROOT


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


def _sandbox_config_yaml(handle, backend) -> str:
    """The per-sandbox config: bench root, results dir, mock port."""
    root = backend.bench_root(handle)
    return (f"bench_root: {root}\n"
            f"results_dir: {Path(root) / 'results'}\n"
            f"mock:\n  port: {handle.spec['mock_port']}\n")


def _upload_text(backend, handle, content: str, remote: Path) -> None:
    """Ship a small text file into the sandbox."""
    tmp = _scratch_dir() / f"upload-{uuid.uuid4().hex[:8]}.txt"
    tmp.write_text(content)
    backend.upload(handle, tmp, remote)


def deploy_harness(backend, handle, bundle: Path) -> None:
    """Deploy the harness bundle + sandbox config + python deps (+bootstrap)."""
    backend.deploy(handle, bundle)
    hd = Path(backend.harness_dir(handle))
    _upload_text(backend, handle, _sandbox_config_yaml(handle, backend),
                 hd / "configs" / "sandbox.yaml")
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


def materialize(backend, spec: dict, bundle: Path):
    """Provision + deploy + bootstrap one sandbox; returns its handle."""
    handle = backend.provision(spec["name"], spec)
    deploy_harness(backend, handle, bundle)
    handle.status = "ready"
    return handle


def wave_chain_cmd(handle, backend, spec_cfg: dict) -> str:
    """The per-sandbox wave chain command (A/A pass, then the real waves)."""
    hd = Path(backend.harness_dir(handle))
    root = Path(backend.bench_root(handle))
    benchmarks = ",".join(handle.spec["benchmarks"])
    products = ",".join(handle.spec["products"])
    aa = "--aa " if spec_cfg.get("aa", True) else "--no-aa "
    return (f"mkdir -p {root / 'logs'} && cd {hd} && "
            f"python3 -m bench.drivers.wave_chain --config configs/sandbox.yaml "
            f"--benchmarks {shlex.quote(benchmarks)} --products {shlex.quote(products)} "
            f"--trials {spec_cfg.get('trials', 10)} --phase {spec_cfg.get('phase', 'w1')} "
            f"--aa-trials {spec_cfg.get('aa_trials', 10)} {aa}"
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
        handle, f"tar -czf {tar_remote} -C {root} results", timeout=600.0)
    if code != 0:
        raise RuntimeError(f"results tar failed: {log[-300:]}")
    local_tar = out_dir / f"{handle.name}-results.tar.gz"
    backend.download(handle, tar_remote, local_tar)
    dest = out_dir / handle.name
    dest.mkdir(parents=True, exist_ok=True)
    subprocess.run(["tar", "-xzf", str(local_tar), "-C", str(dest)], check=True, timeout=300)
    return {"path": str(dest), "tarball": str(local_tar)}
