"""Sandbox backends: Prime VM sandboxes (prime CLI) and local roots.

One backend interface for provision / deploy / exec / upload / download /
destroy, so the orchestrator is agnostic to where sandboxes live. The
prime backend drives the documented CLI (create/get/run/upload/download/
delete); the local backend provisions isolated bench roots on one machine
(dev, CI, orchestrator-mechanics testing without cloud spend).
"""
from __future__ import annotations

import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_HARNESS_REMOTE = "/root/bench-harness"       # prime VM layout
DEFAULT_BENCH_ROOT_REMOTE = "/root/bench-root"
EXIT_SENTINEL = "BENCH-EXIT:"


@dataclass
class SandboxHandle:
    """One provisioned sandbox and its orchestration state."""

    name: str
    spec: dict
    sandbox_id: str | None = None
    status: str = "provisioned"
    reference_ms: float | None = None
    normalize_factor: float = 1.0
    retries: int = 0
    replaced: bool = False
    notes: list = field(default_factory=list)

    def note(self, text: str) -> None:
        """Record an orchestration event on this sandbox."""
        self.notes.append(text)
        print(f"[{self.name}] {text}", flush=True)


class SandboxBackend(ABC):
    """Provisions and drives sandboxes for one parallel run."""

    name: str = ""

    def __init__(self, cfg: dict, pcfg: dict):
        """cfg: main config; pcfg: configs/parallel.yaml (merged)."""
        self.cfg = cfg
        self.pcfg = pcfg

    # ---- lifecycle ---------------------------------------------------------
    @abstractmethod
    def provision(self, name: str, spec: dict) -> SandboxHandle:
        """Create one sandbox; returns its handle (status provisioned)."""

    @abstractmethod
    def deploy(self, handle: SandboxHandle, harness_tar: Path) -> None:
        """Ship the harness bundle; leaves a runnable harness dir."""

    @abstractmethod
    def exec_cmd(self, handle: SandboxHandle, cmd: str,
                 timeout: float | None = None) -> tuple[int, str]:
        """Run a shell command; returns (exit_code, combined_output)."""

    @abstractmethod
    def upload(self, handle: SandboxHandle, local: Path, remote: Path) -> None:
        """Push one file into the sandbox."""

    @abstractmethod
    def download(self, handle: SandboxHandle, remote: Path, local: Path) -> None:
        """Pull one file out of the sandbox."""

    @abstractmethod
    def destroy(self, handle: SandboxHandle) -> None:
        """Tear the sandbox down (best-effort)."""

    # ---- shared helpers ------------------------------------------------------
    def harness_dir(self, handle: SandboxHandle) -> str:
        """Where the deployed harness lives inside the sandbox."""
        raise NotImplementedError

    def bench_root(self, handle: SandboxHandle) -> str:
        """The sandbox's bench tree root (homes/results/logs inside)."""
        raise NotImplementedError


def _run(argv: list, timeout: float | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


class PrimeSandboxBackend(SandboxBackend):
    """Prime VM sandboxes via the prime CLI (one VM per sandbox)."""

    name = "prime"

    def harness_dir(self, handle: SandboxHandle) -> str:
        return self.pcfg.get("harness_remote", DEFAULT_HARNESS_REMOTE)

    def bench_root(self, handle: SandboxHandle) -> str:
        return self.pcfg.get("bench_root_remote", DEFAULT_BENCH_ROOT_REMOTE)

    def _prime(self, *args: str, timeout: float | None = None) -> subprocess.CompletedProcess:
        return _run(["prime", "--plain", "sandbox", *args], timeout=timeout)

    def _sdk(self):
        """The prime_sandboxes SDK client (VM sandboxes: create/get).

        The CLI (0.6.16) cannot create VM sandboxes (it passes start_command
        as a string; the API requires a structured StartCommand for VMs) and
        `prime sandbox get` crashes on the Sandbox model; the SDK is the
        proven path."""
        from prime_sandboxes import APIClient, SandboxClient
        return SandboxClient(APIClient())

    def provision(self, name: str, spec: dict) -> SandboxHandle:
        from prime_sandboxes import CreateSandboxRequest
        handle = SandboxHandle(name=name, spec=spec)
        request = CreateSandboxRequest(
            name=f"bench-{name}",
            docker_image=spec.get("image", "ubuntu:22.04"),
            cpu_cores=float(spec.get("cpu_cores", 4)),
            memory_gb=float(spec.get("memory_gb", 8)),
            disk_size_gb=float(spec.get("disk_gb", 60)),
            timeout_minutes=int(spec.get("timeout_minutes", 180)),
            vm=True,
            network_access=True,
        )
        sb = self._sdk().create(request)
        if not sb or not getattr(sb, "id", None):
            raise RuntimeError(f"provision failed for {name}: no sandbox id")
        handle.sandbox_id = sb.id
        self._wait_running(handle)
        handle.note(f"provisioned as {handle.sandbox_id} (vm)")
        return handle

    def _wait_running(self, handle: SandboxHandle, timeout: float = 600.0) -> None:
        sdk = self._sdk()
        deadline = time.time() + timeout
        while time.time() < deadline:
            sb = sdk.get(handle.sandbox_id)
            if sb.status == "RUNNING":
                return
            if sb.status in ("TERMINATED", "FAILED", "ERROR"):
                raise RuntimeError(f"sandbox {handle.sandbox_id} is {sb.status}")
            time.sleep(5)
        raise TimeoutError(f"sandbox {handle.sandbox_id} not RUNNING in {timeout:.0f}s")


    #: the CLI upload reads the whole file into RAM twice (read + multipart),
    #: so large bundles must ride in slices: 200MB keeps the node's peak safe
    UPLOAD_SLICE_BYTES = 200 * 1024 * 1024

    def deploy(self, handle: SandboxHandle, harness_tar: Path) -> None:
        import subprocess as _sp
        import os as _os
        hd = self.harness_dir(handle)
        size = harness_tar.stat().st_size
        if size <= self.UPLOAD_SLICE_BYTES:
            remote_tar = f"/tmp/{harness_tar.name}"
            out = self._prime("upload", handle.sandbox_id, str(harness_tar), remote_tar)
            if "success" not in (out.stdout + out.stderr).lower():
                raise RuntimeError(f"upload failed: {out.stdout[-200:]}")
        else:
            # slice upload: split locally, upload each slice, rejoin remotely
            tmp = Path("/tmp") / f"bench-upload-{handle.sandbox_id}-{harness_tar.stem}"
            tmp.mkdir(parents=True, exist_ok=True)
            _sp.run(["split", "-b", str(self.UPLOAD_SLICE_BYTES), "-d",
                     str(harness_tar), str(tmp / "part-")], check=True)
            parts = sorted(tmp.glob("part-*"))
            try:
                for i, part in enumerate(parts):
                    remote_part = f"/tmp/{harness_tar.name}.part-{i:02d}"
                    out = self._prime("upload", handle.sandbox_id, str(part), remote_part)
                    if "success" not in (out.stdout + out.stderr).lower():
                        raise RuntimeError(
                            f"slice {i} upload failed: {out.stdout[-200:]}")
                    part.unlink()
                remote_tar = f"/tmp/{harness_tar.name}"
                rejoin = (f"cat {remote_tar}.part-* > {remote_tar}"
                          f" && rm {remote_tar}.part-*")
                code, log = self.exec_cmd(handle, rejoin, timeout=600)
                if code != 0:
                    raise RuntimeError(f"slice rejoin failed: {log[-300:]}")
            finally:
                _sp.run(["rm", "-rf", str(tmp)], check=False)
        code, log = self.exec_cmd(handle, f"mkdir -p {hd} && tar -xzf {remote_tar} -C {hd}"
                                         f" && rm {remote_tar}", timeout=600)
        if code != 0:
            raise RuntimeError(f"untar failed: {log[-300:]}")

    def exec_cmd(self, handle: SandboxHandle, cmd: str,
                 timeout: float | None = None) -> tuple[int, str]:
        wrapped = f"{cmd}; echo {EXIT_SENTINEL}$?"
        argv = ["prime", "--plain", "sandbox", "run", handle.sandbox_id]
        if timeout:
            # the gateway's default exec timeout is 300s; ask for the caller's
            # whole budget (less a margin) whenever one is given
            argv += ["--timeout", str(max(1, int(timeout) - 10))]
        argv += ["--", "bash", "-lc", wrapped]
        out = _run(argv, timeout=timeout)
        text = out.stdout + out.stderr
        code = 1
        for line in text.splitlines():
            if line.startswith(EXIT_SENTINEL):
                try:
                    code = int(line[len(EXIT_SENTINEL):].strip() or 1)
                except ValueError:
                    code = 1
        return code, text

    def upload(self, handle: SandboxHandle, local: Path, remote: Path) -> None:
        out = self._prime("upload", handle.sandbox_id, str(local), str(remote))
        if "success" not in (out.stdout + out.stderr).lower():
            raise RuntimeError(f"upload failed: {out.stdout[-200:]}")

    def download(self, handle: SandboxHandle, remote: Path, local: Path) -> None:
        local.parent.mkdir(parents=True, exist_ok=True)
        out = self._prime("download", handle.sandbox_id, str(remote), str(local))
        if not local.exists():
            raise RuntimeError(f"download failed: {out.stdout[-200:]} {out.stderr[-200:]}")

    def destroy(self, handle: SandboxHandle) -> None:
        if handle.sandbox_id:
            self._prime("delete", handle.sandbox_id, "-y", timeout=120)