"""Prime Agent (TypeScript) product adapter.

The official compiled beta binary; wire-compatible with the Rust adapter
(same daemon socket contract, same trial isolation), so it subclasses it.
"""
from __future__ import annotations

from bench.core.product import TrialContext
from bench.adapters.products.prime_agent_rust import PrimeAgentRustProduct


class PrimeAgentTsProduct(PrimeAgentRustProduct):
    name = "ts"
    display_name = "Prime Agent TS"
    has_daemon = True
    default_binary_subpath = None  # not under the bench tree; see configs/products/ts.yaml
    default_revision = "official-beta-0.9.5-beta.2043.1.acc5bc0"

    @property
    def binary(self):  # type: ignore[override]
        """The official installed binary (install.sh layout)."""
        from pathlib import Path
        if self.product_cfg.get("binary"):
            return Path(self.product_cfg["binary"])
        return Path.home() / ".local/share/prime-agent/bin/prime-agent"

    def version_info(self) -> dict:
        import subprocess
        v = subprocess.run([str(self.binary), "--version"], capture_output=True, text=True, timeout=90)
        return {"version": v.stdout.strip() or v.stderr.strip(),
                "revision": self.product_cfg.get("revision", self.default_revision),
                "binary": str(self.binary)}

    def argv(self, ctx: TrialContext, resume_fixture: str | None = None) -> list[str]:
        argv = [str(self.binary), "--daemon-socket", str(ctx["daemon_socket"]),
                "--provider", "prime-inference", "--model", "mock-1", "--offline"]
        if resume_fixture:
            argv += ["--resume", resume_fixture]
        return argv

    def daemon_argv(self, ctx: TrialContext) -> list[str] | None:
        return [str(self.binary), "--mode", "daemon", "--daemon-socket", str(ctx["daemon_socket"])]
