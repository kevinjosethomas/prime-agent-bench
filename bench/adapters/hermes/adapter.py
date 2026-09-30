"""Hermes Agent product adapter (Nous Research).

The release-tag install (v0.21.5, tag v2026.9.24) via the repo's own
scripts/install.sh in the root FHS layout: code at /usr/local/lib/hermes-agent
(venv inside), command at /usr/local/bin/hermes, uv-managed Python at
/usr/local/share/uv — every path identical in each sandbox, so the vendored
payload relocates cleanly. Data/config/sessions live under $HERMES_HOME
(default $HOME/.hermes): the trial home carries a fresh config.yaml per
trial, so state is isolated. Model traffic routes to the offline mock
through Hermes' OpenAI-compatible custom provider
(model.provider=custom + base_url + api_key), the same mock regime as
rust/ts/claude/pi; Enter always submits the composer (multiline is opt-in
via ctrl-j / escape-enter), and the TUI is prompt_toolkit-based, so the
pty driver's screen model applies.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from bench.core.env import scrubbed_env
from bench.core.product import ProductAdapter, TrialContext

#: the sandbox-side install paths (the vendored payload's targets)
FHS_CODE = Path("/usr/local/lib/hermes-agent")
FHS_COMMAND = Path("/usr/local/bin/hermes")


class HermesAgentProduct(ProductAdapter):
    name = "hermes"
    display_name = "Hermes Agent"
    # no vendor-native Prime-JSONL resume; no daemon; no python kernel
    resume_fixture_capable = False
    msg_routing = "mock"

    @property
    def binary(self) -> Path:
        """The published hermes command (product.yaml overrides)."""
        if self.product_cfg.get("binary"):
            return Path(self.product_cfg["binary"])
        return FHS_COMMAND

    @property
    def payload_code(self) -> Path:
        """The install tree used for version evidence (node-side source)."""
        src = (self.product_cfg.get("install") or {}).get("payload_code")
        return Path(src).expanduser() if src else FHS_CODE

    def version_info(self) -> dict:
        """Pinned version evidence: the release tag + commit + launcher sha256.

        The node never executes the product (the payload only ships); the
        version string is the one captured in-sandbox at install time
        (`hermes --version`), cross-checked against the payload's
        pyproject.toml, and the launcher sha256 pins the exact payload."""
        from bench.core.env import sha256_file
        src_launcher = (self.product_cfg.get("install") or {}).get("launcher_src")
        sha_src = Path(src_launcher).expanduser() if src_launcher else self.binary
        version = self.product_cfg.get("version")
        if not version:
            pyproject = self.payload_code / "pyproject.toml"
            for line in pyproject.read_text().splitlines():
                if line.startswith("version"):
                    version = line.split("=", 1)[1].strip().strip("\"'")
                    break
        info = {
            "version": version or "unknown",
            "revision": self.product_cfg.get("revision", "unknown"),
            "binary": str(self.binary),
            "binary_sha256": sha256_file(sha_src) if sha_src and sha_src.exists() else None,
        }
        note = (self.product_cfg.get("install") or {}).get("note")
        if note:
            info["note"] = note
        return info

    def prepare_template(self, tpl: Path) -> None:
        """The trial home template: a hermes config.yaml routing to the mock.

        The custom provider (OpenAI-compatible) points at the offline mock;
        the dummy key mirrors the other mock-routed products."""
        hermes_home = tpl / "home" / ".hermes"
        hermes_home.mkdir(parents=True, exist_ok=True)
        (hermes_home / "config.yaml").write_text(
            "model:\n"
            "  default: mock-1\n"
            "  provider: custom\n"
            f"  base_url: http://127.0.0.1:{self.mock_port}/v1\n"
            "  api_key: sk-bench-dummy-not-real\n"
            # the banner's background update check is a GitHub-API network call
            # (cached at ~/.hermes/.update_check): off for deterministic
            # benchmarking, the same nonessential-traffic scrub claude gets
            "updates:\n"
            "  check: false\n")

    def customize_trial(self, ctx: TrialContext) -> None:
        """Per-trial hermes state: the template's .hermes lands in the trial
        home (config.yaml, fresh sessions dir); the /usr/local install tree
        is shared code and never written by a trial."""
        src = self.template_dir() / "home" / ".hermes"
        if src.exists():
            dst = ctx["home"] / ".hermes"
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)

    def env(self, ctx: TrialContext) -> dict:
        """The launch env: trial home + tmp; scrubbed_env carries
        /usr/local/bin (the published command) on PATH; HERMES_HOME defaults
        to the trial home's .hermes (per-trial state)."""
        return scrubbed_env({"HOME": str(ctx["home"]), "TMPDIR": str(ctx["tmp"]),
                             "HERMES_NO_UPDATE_CHECK": "1"})

    def argv(self, ctx: TrialContext, resume_fixture: str | None = None) -> list[str]:
        """The TUI launch: bare `hermes` (the product's natural entry), with
        the model route carried by the trial home's ~/.hermes/config.yaml
        (Hermes' own persistence form for a custom endpoint: model.provider=
        custom + base_url + api_key, written in prepare_template). The
        top-level command dispatches subcommands, so provider flags belong
        to `hermes chat`; the config route is the launch-neutral equivalent
        and matches the bare-launch shape of the claude/codex adapters."""
        return [str(self.binary)]

    def model_info(self, ctx: TrialContext) -> str:
        """The model a submit routes to (evidence per row)."""
        return "custom/mock-1"

    def reap(self, ctx: TrialContext) -> None:
        """Teardown: per-trial process sweep (the TUI is one python process
        with threads; sweep defensively like the other products)."""
        from bench.core.process import sweep_trial
        leftovers = sweep_trial(ctx)
        if leftovers:
            raise RuntimeError(f"trial sweep leftovers: {leftovers[:3]}")
