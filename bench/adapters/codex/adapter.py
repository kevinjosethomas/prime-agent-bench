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

import json
import shutil
import subprocess
from pathlib import Path

from bench.core.env import scrubbed_env
from bench.core.product import ProductAdapter, TrialContext


class CodexProduct(ProductAdapter):
    name = "codex"
    display_name = "Codex CLI"
    needs_prepass = True
    # codex 0.157's resolved default under ChatGPT auth (session rollouts
    # record model "gpt-6-sol", model_provider "openai")
    DEFAULT_MODEL = "openai/gpt-6-sol"
    # the api-key route's pinned model: the newest one the key can serve
    # (gpt-6-sol is ChatGPT-backend-only; the key's catalog tops out at
    # gpt-5.6-sol — verified against api.openai.com/v1/models)
    KEY_MODEL = "gpt-5.6-sol"
    #: where the real OpenAI API key lives on the node (pi's auth.json
    #: carries it under the "openai" entry; codex's own vendor payload
    #: ships the ChatGPT OAuth instead)
    KEY_SOURCE = Path.home() / ".pi" / "agent" / "auth.json"
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
        # --no-daemon: codex 0.157's background app-server binds a UNIX
        # socket under $HOME/.codex/app-server-control/, and the isolated
        # trial-home paths exceed the kernel's 107-char socket path limit
        # (node AND sandbox geometry); codex's own error message
        # recommends this fallback for exactly that case
        argv = [str(self.binary), "--no-daemon"]
        if ctx.get("routing") == "real-api":
            argv += ["-m", self.KEY_MODEL]
        return argv

    def apply_routing(self, ctx: TrialContext) -> None:
        """Real-api routing re-auths the trial home with the API key.

        The ChatGPT OAuth cannot survive isolated trial homes: its refresh
        token is single-use, so the first trial's refresh rotates the token
        family and every other copy (template included) answers "refresh
        token was already used" with the login screen — proven live in the
        sandbox. Codex's own api-key auth mode (its login menu option 3)
        has no rotation: the key lands in the trial auth.json and every
        trial authenticates."""
        if ctx.get("routing") != "real-api":
            return
        key = ""
        try:
            key = json.loads(self.KEY_SOURCE.read_text()).get("openai", {}).get("key", "")
        except (OSError, ValueError):
            pass
        if not key:
            raise RuntimeError("codex real-api routing needs the OpenAI API key at "
                               f"{self.KEY_SOURCE} (openai.key)")
        auth = {"auth_mode": "apikey", "OPENAI_API_KEY": key}
        codex_dir = ctx["home"] / ".codex"
        codex_dir.mkdir(parents=True, exist_ok=True)
        (codex_dir / "auth.json").write_text(json.dumps(auth, indent=1))

    def model_info(self, ctx: TrialContext) -> str:
        """The model a real-api submit routes to (evidence per row)."""
        if ctx.get("routing") == "real-api":
            return f"openai/{self.KEY_MODEL} (api-key)"
        return self.DEFAULT_MODEL
