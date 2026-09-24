"""Codex CLI product adapter.

npm-installed CLI with real ChatGPT auth copied verbatim (Kevin: codex
msg_send may use the real API under the $10 budget; codex 0.156 rejects
chat wire_api, so no mock provider override is installed). Onboarding
prepass required.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from bench.core.env import scrubbed_env
from bench.core.product import DialogStep, ProductAdapter, TrialContext

DIALOG_STEPS: list[DialogStep] = [
    ("3. Provide your own API key", ["3"]),                           # welcome menu
    ("Paste or type your API key", ["sk-bench-dummy-not-real\r"]),   # key box
    ("Press enter to continue", ["\r"]),                             # generic continue
    ("Trust this folder?", ["\r"]),                                   # folder trust (cursor prepositioned)
    ("auth.openai.com", ["\x1b", "3"]),                              # accidental OAuth page -> esc, pick 3
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
        codex = tpl / "home" / ".codex"
        codex.mkdir(parents=True, exist_ok=True)
        src_auth = Path.home() / ".codex" / "auth.json"
        if src_auth.exists():
            shutil.copy(src_auth, codex / "auth.json")
        cfg = Path.home() / ".codex" / "config.toml"
        if cfg.exists():
            shutil.copy(cfg, codex / "config.toml")

    def env(self, ctx: TrialContext) -> dict:
        return scrubbed_env({"HOME": str(ctx["home"]), "TMPDIR": str(ctx["tmp"])})

    def argv(self, ctx: TrialContext, resume_fixture: str | None = None) -> list[str]:
        return [str(self.binary)]
