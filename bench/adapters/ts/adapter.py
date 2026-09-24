"""Prime Agent (TypeScript) product adapter.

The official compiled beta binary; wire-compatible with the Rust adapter
(same daemon socket contract, same trial isolation), so it subclasses it.
"""
from __future__ import annotations

from bench.adapters.rust.adapter import PrimeAgentRustProduct
from bench.core.product import TrialContext


class PrimeAgentTsProduct(PrimeAgentRustProduct):
    name = "ts"
    display_name = "Prime Agent TS"
    has_daemon = True
    needs_kernel_venv = True
    default_binary_subpath = None  # not under the bench tree; see product.yaml
    default_revision = "official-beta-0.9.5-beta.2043.1.acc5bc0"

    @property
    def binary(self):  # type: ignore[override]
        """The official installed binary (install.sh layout)."""
        from pathlib import Path
        if self.product_cfg.get("binary"):
            return Path(self.product_cfg["binary"])
        return Path.home() / ".local/share/prime-agent/bin/prime-agent"

    def argv(self, ctx: TrialContext, resume_fixture: str | None = None) -> list[str]:
        argv = [str(self.binary), "--daemon-socket", str(ctx["daemon_socket"]),
                "--provider", "prime-inference", "--model", "mock-1", "--offline"]
        if resume_fixture:
            argv += ["--resume", resume_fixture]
        return argv

    def daemon_argv(self, ctx: TrialContext) -> list[str] | None:
        return [str(self.binary), "--mode", "daemon",
                "--daemon-socket", str(ctx["daemon_socket"])]
