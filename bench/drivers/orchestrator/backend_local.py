"""The local sandbox backend: isolated bench roots on one machine.

Dev/CI backend (no cloud spend): each sandbox is a directory tree
<local_root>/<name>/{harness,bench-root} with its own mock port and
results dir. Sandboxes share one machine, so this validates orchestration
mechanics and wave chains, not published cross-product numbers.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from bench.drivers.orchestrator.backend import (EXIT_SENTINEL, SandboxBackend,
                                                SandboxHandle, _run)


class LocalSandboxBackend(SandboxBackend):
    """Isolated bench roots on one machine."""

    name = "local"

    def sandbox_dir(self, handle: SandboxHandle) -> Path:
        """This sandbox's tree root."""
        return Path(self.pcfg.get("local_root", "~/bench-sandboxes")).expanduser() / handle.name

    def harness_dir(self, handle: SandboxHandle) -> str:
        return str(self.sandbox_dir(handle) / "harness")

    def bench_root(self, handle: SandboxHandle) -> str:
        return str(self.sandbox_dir(handle) / "bench-root")

    def provision(self, name: str, spec: dict) -> SandboxHandle:
        handle = SandboxHandle(name=name, spec=spec)
        d = self.sandbox_dir(handle)
        if d.exists():
            shutil.rmtree(d)
        (d / "bench-root" / "logs").mkdir(parents=True)
        handle.note(f"provisioned at {d}")
        return handle

    def deploy(self, handle: SandboxHandle, harness_tar: Path) -> None:
        hd = Path(self.harness_dir(handle))
        hd.mkdir(parents=True, exist_ok=True)
        out = _run(["tar", "-xzf", str(harness_tar), "-C", str(hd)], timeout=600)
        if out.returncode != 0:
            raise RuntimeError(f"untar failed: {out.stderr[-300:]}")

    def exec_cmd(self, handle: SandboxHandle, cmd: str,
                 timeout: float | None = None) -> tuple[int, str]:
        out = _run(["bash", "-lc", f"{cmd}; echo {EXIT_SENTINEL}$?"], timeout=timeout)
        text = out.stdout + out.stderr
        code = out.returncode
        for line in text.splitlines():
            if line.startswith(EXIT_SENTINEL):
                try:
                    code = int(line[len(EXIT_SENTINEL):].strip() or 1)
                except ValueError:
                    code = 1
        return code, text

    def upload(self, handle: SandboxHandle, local: Path, remote: Path) -> None:
        remote_p = Path(remote)
        if not remote_p.is_absolute():
            remote_p = self.sandbox_dir(handle) / remote_p
        remote_p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(local, remote_p)

    def download(self, handle: SandboxHandle, remote: Path, local: Path) -> None:
        remote_p = Path(remote)
        if not remote_p.is_absolute():
            remote_p = self.sandbox_dir(handle) / remote_p
        local.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(remote_p, local)

    def destroy(self, handle: SandboxHandle) -> None:
        shutil.rmtree(self.sandbox_dir(handle), ignore_errors=True)
