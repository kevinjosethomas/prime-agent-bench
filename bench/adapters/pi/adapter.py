"""Pi Mono (pi-mono coding agent) product adapter.

Built from the pinned source checkout; provider/model flags select the
models.json mock provider, the copied auth.json keeps the product
authenticated (no onboarding).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from bench.core.env import copy_prime_auth, write_models_json
from bench.core.product import ProductAdapter, TrialContext


class PiMonoProduct(ProductAdapter):
    name = "pi"
    display_name = "Pi Mono"
    default_revision = "b45597504eeaba1f11a9920a1d1048c361ed4b8e"
    # argv() ignores resume_fixture: no native Prime-JSONL resume; a
    # vendor-native history fixture (spec §F) does not exist yet.
    resume_fixture_capable = False

    @property
    def cli_path(self) -> Path:
        """The bundled cli.js of the source checkout."""
        if self.product_cfg.get("binary"):
            return Path(self.product_cfg["binary"])
        return self.layout.repos / "pi-mono/packages/coding-agent/dist/bundle/cli.js"

    def version_info(self) -> dict:
        from bench.core.env import sha256_file
        v = subprocess.run(["node", str(self.cli_path), "--version"], capture_output=True, text=True, timeout=90)
        pkg = json.loads((self.layout.repos / "pi-mono/packages/coding-agent/package.json").read_text())
        return {"version": v.stdout.strip() or pkg["version"],
                "revision": self.product_cfg.get("revision", self.default_revision),
                "binary": f"node {self.cli_path}",
                "binary_sha256": sha256_file(self.cli_path)}

    #: the live provider pi routes through on real-api trials: the
    #: ChatGPT-backed openai-codex provider whose OAuth lives in the
    #: node's ~/.pi/agent/auth.json (verified ready via `pi auth check`)
    REAL_PROVIDER = "openai-codex"
    REAL_MODEL = "gpt-6-sol"

    def prepare_template(self, tpl: Path) -> None:
        # pi's trial home carries no dotdir state: its agent dir (auth +
        # provider config) is materialized per-trial by customize_trial
        # from template/agent, so the template home is just declared
        (tpl / "home").mkdir(parents=True, exist_ok=True)
        write_models_json(tpl / "agent", f"http://127.0.0.1:{self.mock_port}/v1")
        # pi's own credentials in pi's auth.json format. Only the
        # openai-codex OAuth rides: pi's WS retry fallback sends other
        # entries' api keys to the ChatGPT backend, which rejects them
        # (the observed invalid-key render), and the campaign's live route
        # is exactly that provider. Mock trials take their provider config
        # from models.json instead.
        auth = Path.home() / ".pi" / "agent" / "auth.json"
        if auth.exists():
            data = json.loads(auth.read_text())
            keep = {k: v for k, v in data.items() if k == self.REAL_PROVIDER}
            (tpl / "agent").mkdir(parents=True, exist_ok=True)
            (tpl / "agent" / "auth.json").write_text(json.dumps(keep, indent=1))
        else:
            copy_prime_auth(tpl / "agent")

    def customize_trial(self, ctx: TrialContext) -> None:
        ctx["agent_dir"] = ctx["home"] / ".pi" / "agent"
        ctx["agent_dir"].mkdir(parents=True, exist_ok=True)
        shutil.copytree(self.template_dir() / "agent", ctx["agent_dir"], dirs_exist_ok=True)

    def argv(self, ctx: TrialContext, resume_fixture: str | None = None) -> list[str]:
        provider, model = "prime-inference", "mock-1"
        if ctx.get("routing") == "real-api":
            provider, model = self.REAL_PROVIDER, self.REAL_MODEL
        return ["node", str(self.cli_path), "--provider", provider, "--model", model,
                "--no-extensions", "--no-skills", "--no-prompt-templates"]

    def model_info(self, ctx: TrialContext) -> str:
        """The model a real-api submit routes to (evidence per row)."""
        if ctx.get("routing") == "real-api":
            return f"{self.REAL_PROVIDER}/{self.REAL_MODEL}"
        return "prime-inference/mock-1"
