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

    def prepare_template(self, tpl: Path) -> None:
        write_models_json(tpl / "agent", f"http://127.0.0.1:{self.mock_port}/v1")
        copy_prime_auth(tpl / "agent")

    def customize_trial(self, ctx: TrialContext) -> None:
        ctx["agent_dir"] = ctx["home"] / ".pi" / "agent"
        ctx["agent_dir"].mkdir(parents=True, exist_ok=True)
        shutil.copytree(self.template_dir() / "agent", ctx["agent_dir"], dirs_exist_ok=True)

    def argv(self, ctx: TrialContext, resume_fixture: str | None = None) -> list[str]:
        return ["node", str(self.cli_path), "--provider", "prime-inference", "--model", "mock-1",
                "--no-extensions", "--no-skills", "--no-prompt-templates"]
