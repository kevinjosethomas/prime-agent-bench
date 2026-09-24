"""Claude Code product adapter.

npm-installed CLI; onboarding prepass required (first-run dialogs reappear
unless walked in-place); model traffic routed to the offline mock.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from bench.core.env import scrubbed_env
from bench.core.product import DialogStep, ProductAdapter, TrialContext

DIALOG_STEPS: list[DialogStep] = [
    ("1. Auto (match terminal)", ["\r"]),                     # theme picker
    ("Do you want to use this API key?", ["\x1b[A", "\r"]),   # -> Yes
    ("Press Enter to continue", ["\r"]),                       # security note
    ("Is this a project you created or one you trust?", ["\x1b[B", "\r"]),  # workspace trust
]


class ClaudeCodeProduct(ProductAdapter):
    name = "claude"
    display_name = "Claude Code"
    needs_prepass = True
    dialog_steps = DIALOG_STEPS

    @property
    def binary(self) -> Path:
        """The installed claude binary."""
        if self.product_cfg.get("binary"):
            return Path(self.product_cfg["binary"])
        return Path("/usr/bin/claude")

    def version_info(self) -> dict:
        v = subprocess.run([str(self.binary), "--version"], capture_output=True, text=True, timeout=60,
                           env=scrubbed_env({"HOME": str(Path.home())}))
        return {"version": v.stdout.strip(),
                "revision": self.product_cfg.get("revision", "npm@latest"),
                "binary": str(self.binary)}

    def prepare_template(self, tpl: Path) -> None:
        """Copy the node's authenticated .claude state minus project data."""
        src = Path.home() / ".claude"
        if src.exists():
            shutil.copytree(src, tpl / "home" / ".claude", dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("projects", "todos", "statsig", "shell-snapshots"))
        cj = Path.home() / ".claude.json"
        if cj.exists():
            data = json.loads(cj.read_text())
            data.pop("projects", None)
            (tpl / "home" / ".claude.json").write_text(json.dumps(data))

    def customize_trial(self, ctx: TrialContext) -> None:
        cj = ctx["home"] / ".claude.json"
        if cj.exists():
            data = json.loads(cj.read_text())
            data.setdefault("projects", {})[str(ctx["work"])] = {"hasTrustDialogAccepted": True}
            cj.write_text(json.dumps(data))

    def env(self, ctx: TrialContext) -> dict:
        extra = {
            "HOME": str(ctx["home"]),
            "TMPDIR": str(ctx["tmp"]),
            "ANTHROPIC_API_KEY": "sk-bench-dummy-not-real",
            "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{self.mock_port}",
            "ANTHROPIC_AUTH_TOKEN": "sk-bench-dummy-not-real",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        }
        return scrubbed_env(extra)

    def argv(self, ctx: TrialContext, resume_fixture: str | None = None) -> list[str]:
        return [str(self.binary)]
