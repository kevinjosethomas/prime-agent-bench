"""Codex CLI product adapter.

npm-installed CLI; the FULL .codex state is copied (config/model
caches), and auth must be walked: codex shows the login menu for ANY
copied home (trial homes on the node AND sandboxes; the ChatGPT tokens
do not authenticate a copied .codex), so the prepass walks option 3
with a dummy key to the settled interactive state - the same state the
sequential baseline settled.

Messages route to the offline mock (``msg_routing: mock`` in
product.yaml): codex 0.156+ hard-rejects ``wire_api = "chat"`` (its
client only speaks the Responses API), so the mock provider serves the
responses protocol (the ``/v1/responses`` mode, keyed on the endpoint
path) and the trial home's ``~/.codex/config.toml`` pins
``openai_base_url`` — the config key that overrides the built-in
``openai`` provider's endpoint — at the per-sandbox mock port. The
walked dummy-key auth state rides unchanged: the mock ignores
credentials, exactly like the other mock-routed products. The wire_api
stays ``responses`` (its hard requirement); the mock now speaks it.

The real-api route remains available (the per-benchmark
``benchmarks.<name>.msg_routing: real-api`` override): apply_routing
then re-auths the trial home with the OpenAI API key and the model
pin rides ``-m`` — the live-inference regime the r2 measured."""
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
    # the api-key route's pinned model: the newest one the key actually
    # serves on /v1/responses (verified live: gpt-5.6-sol replies; the
    # codex-family models 404 under an API key despite appearing in the
    # catalog; gpt-6-sol itself is ChatGPT-backend-only). Every key-served
    # model opens the "Meet GPT-6 ..." migration NUX on each launch, so the
    # dialog join the walk and the measured probe answers it inline.
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
        """Route the trial home's provider: mock writes the config.toml
        endpoint pin; real-api re-auths with the API key.

        Mock: ``openai_base_url`` in the trial home's ~/.codex/config.toml
        points the built-in ``openai`` provider (wire_api responses) at
        the offline mock — the config key codex documents for exactly
        this override (user [model_providers.openai] entries cannot
        override the built-in provider). The prepass/settle walked
        dummy-key auth state is untouched: the mock ignores credentials.

        Real-api: the ChatGPT OAuth cannot survive isolated trial homes
        (its refresh token is single-use — the first trial's refresh
        rotates the token family and every copy answers "refresh token
        was already used" with the login screen, proven live in the
        sandbox). Codex's own api-key auth mode (its login menu option 3)
        has no rotation: the key lands in the trial auth.json and every
        trial authenticates."""
        if ctx.get("routing") == "real-api":
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
            return
        if ctx.get("routing") == "mock":
            # openai_base_url: the documented override for the built-in
            # openai provider (user [model_providers.openai] entries cannot
            # override a built-in provider; this top-level key can). Merged
            # into the walked config.toml text: replace an existing pin or
            # insert before the first [section] (a top-level key must
            # precede any section header in TOML).
            codex_dir = ctx["home"] / ".codex"
            codex_dir.mkdir(parents=True, exist_ok=True)
            cfg_path = codex_dir / "config.toml"
            line = f'openai_base_url = "http://127.0.0.1:{self.mock_port}/v1"'
            if cfg_path.exists():
                out, replaced = [], False
                for ln in cfg_path.read_text().splitlines():
                    if ln.strip().startswith("openai_base_url"):
                        out.append(line)
                        replaced = True
                    else:
                        out.append(ln)
                if not replaced:
                    out.insert(0, line)
                cfg_path.write_text("\n".join(out) + "\n")
            else:
                cfg_path.write_text(line + "\n")

    def model_info(self, ctx: TrialContext) -> str:
        """The model a submit routes to (evidence per row)."""
        if ctx.get("routing") == "mock":
            return f"mock-responses (http://127.0.0.1:{self.mock_port}/v1)"
        if ctx.get("routing") == "real-api":
            return f"openai/{self.KEY_MODEL} (api-key)"
        return self.DEFAULT_MODEL
