"""Codex CLI product adapter.

npm-installed CLI with real ChatGPT auth (Kevin: codex msg_send may use
the real API under the $10 budget; codex 0.156 rejects chat wire_api, so
no mock provider override is installed). The FULL .codex state is copied:
codex 0.156 boots to the login menu when it finds auth.json without the
accompanying device state (installation_id/version/sqlites), and a login
walk would silently replace the real OAuth with a typed key. Onboarding
prepass required (the per-workdir trust dialog)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from bench.core.env import scrubbed_env
from bench.core.product import DialogStep, ProductAdapter, TrialContext

DIALOG_STEPS: list[DialogStep] = [
    ("Trust and continue", ["\r"]),   # folder trust (option 1 preselected, enter confirms)
]


class CodexProduct(ProductAdapter):
    name = "codex"
    display_name = "Codex CLI"
    needs_prepass = True
    dialog_steps = DIALOG_STEPS

    @property
    def binary(self) -> Path:
        """The installed codex binary."""
        if self.product_cfg.get("binary"):
            return Path(self.product_cfg["binary"])
        return Path("/usr/bin/codex")

    def version_info(self) -> dict:
        v = subprocess.run([str(self.binary), "--version"], capture_output=True, text=True, timeout=60)
        return {"version": v.stdout.strip(),
                "revision": self.product_cfg.get("revision", "npm@latest"),
                "binary": str(self.binary)}

    def prepare_template(self, tpl: Path) -> None:
        """The whole authenticated .codex state (tokens + device identity)."""
        src = Path.home() / ".codex"
        if src.exists():
            shutil.copytree(src, tpl / "home" / ".codex", dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("tmp", ".tmp"))

    def env(self, ctx: TrialContext) -> dict:
        return scrubbed_env({"HOME": str(ctx["home"]), "TMPDIR": str(ctx["tmp"])})

    def argv(self, ctx: TrialContext, resume_fixture: str | None = None) -> list[str]:
        return [str(self.binary)]
