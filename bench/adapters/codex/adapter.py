"""Codex CLI product adapter.

npm-installed CLI with real ChatGPT auth (Kevin: codex msg_send may use
the real API under the $10 budget; codex 0.156 rejects chat wire_api, so
no mock provider override is installed). The FULL .codex state is copied
(config/model caches), but auth must be walked: codex 0.156 shows the
login menu for ANY copied home (trial homes on the node AND sandboxes;
the ChatGPT tokens do not authenticate a copied .codex), so the prepass
walks option 3 with a dummy key to the settled interactive state - the
same state the sequential baseline settled.

Messages route to the real API (``msg_routing: real-api`` in
product.yaml): the settled dummy-key state 401s there, so
message-settle scenarios do not measure a settle for codex at all —
the ack is measured, the row records the regime, and the
result-validity gate excludes cross-regime values. A settle resumes
only with real auth (Kevin's call) or a codex that accepts the mock
wire_api (product.yaml flip to ``mock``)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from bench.core.env import scrubbed_env
from bench.core.product import ProductAdapter, TrialContext


class CodexProduct(ProductAdapter):
    name = "codex"
    display_name = "Codex CLI"
    needs_prepass = True
    # argv() ignores resume_fixture: no native Prime-JSONL resume; a
    # vendor-native history fixture (spec §F) does not exist yet.
    resume_fixture_capable = False

    @property
    def binary(self) -> Path:
        """The installed codex binary."""
        if self.product_cfg.get("binary"):
            return Path(self.product_cfg["binary"])
        return Path("/usr/bin/codex")

    def version_info(self) -> dict:
        from bench.core.env import sha256_file
        v = subprocess.run([str(self.binary), "--version"], capture_output=True, text=True, timeout=60)
        return {"version": v.stdout.strip(),
                "revision": self.product_cfg.get("revision", "npm@latest"),
                "binary": str(self.binary),
                "binary_sha256": sha256_file(Path(self.binary).resolve()),
                "auth_limited": True}

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
