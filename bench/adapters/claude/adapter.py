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
from bench.core.product import ProductAdapter, TrialContext


class ClaudeCodeProduct(ProductAdapter):
    name = "claude"
    display_name = "Claude Code"
    needs_prepass = True
    # argv() ignores resume_fixture: no native Prime-JSONL resume; a
    # vendor-native history fixture (spec §F) does not exist yet.
    resume_fixture_capable = False

    @property
    def binary(self) -> Path:
        """The installed claude binary."""
        if self.product_cfg.get("binary"):
            return Path(self.product_cfg["binary"])
        return Path("/usr/bin/claude")

    def version_info(self) -> dict:
        from bench.core.env import sha256_file
        v = subprocess.run([str(self.binary), "--version"], capture_output=True, text=True, timeout=60,
                            env=scrubbed_env({"HOME": str(Path.home())}))
        return {"version": v.stdout.strip(),
                "revision": self.product_cfg.get("revision", "npm@latest"),
                "binary": str(self.binary),
                "binary_sha256": sha256_file(Path(self.binary).resolve())}

    def prepare_template(self, tpl: Path) -> None:
        """Copy the node's authenticated .claude state minus project data."""
        src = Path.home() / ".claude"
        if src.exists():
            shutil.copytree(src, tpl / "home" / ".claude", dirs_exist_ok=True,
                            symlinks=True,
                            ignore=shutil.ignore_patterns(
                                "projects", "todos", "statsig", "shell-snapshots", "debug"))
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

    #: the live provider this harness routes claude through when the
    #: benchmark requests real-api routing (no OAuth state on the node):
    #: Prime Inference's Anthropic-protocol endpoint (verified: the
    #: messages API speaks the Anthropic wire format; personal balances
    #: are empty, so the team header selects team billing)
    REAL_BASE_URL = "https://api.pinference.ai/api"
    REAL_MODEL = "anthropic/claude-fable-5"

    def _prime_config(self) -> dict:
        """The node's Prime credentials (api key + team id) for the live route."""
        try:
            return json.loads((Path.home() / ".prime" / "config.json").read_text())
        except (OSError, ValueError):
            return {}

    def env(self, ctx: TrialContext) -> dict:
        extra = {
            "HOME": str(ctx["home"]),
            "TMPDIR": str(ctx["tmp"]),
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        }
        if ctx.get("routing") == "real-api":
            cfg = self._prime_config()
            extra.update({
                "ANTHROPIC_BASE_URL": self.REAL_BASE_URL,
                "ANTHROPIC_AUTH_TOKEN": cfg.get("api_key", ""),
                "ANTHROPIC_MODEL": self.REAL_MODEL,
                "ANTHROPIC_SMALL_FAST_MODEL": self.REAL_MODEL,
            })
            if cfg.get("team_id"):
                extra["ANTHROPIC_CUSTOM_HEADERS"] = f"X-Prime-Team-ID: {cfg['team_id']}"
        else:
            extra.update({
                "ANTHROPIC_API_KEY": "sk-bench-dummy-not-real",
                "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{self.mock_port}",
                "ANTHROPIC_AUTH_TOKEN": "sk-bench-dummy-not-real",
            })
        return scrubbed_env(extra)

    def model_info(self, ctx: TrialContext) -> str:
        """The model a real-api submit routes to (evidence per row)."""
        return self.REAL_MODEL if ctx.get("routing") == "real-api" else "mock"

    def argv(self, ctx: TrialContext, resume_fixture: str | None = None) -> list[str]:
        return [str(self.binary)]
