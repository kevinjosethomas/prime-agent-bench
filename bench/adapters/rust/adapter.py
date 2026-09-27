"""Prime Agent (Rust) product adapter.

Pinned release binary, per-trial daemon socket, isolated agent dir,
offline mock-provider routing. Not part of any product. Benchmark harness
only.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from bench.core.env import (NODE_HOME_AUTH_PRIME, copy_prime_auth,
                            global_caches, scrubbed_env, write_models_json)
from bench.core.product import ProductAdapter, TrialContext, copy_tree
from bench.core.process import sweep_trial


class PrimeAgentRustProduct(ProductAdapter):
    name = "rust"
    display_name = "Prime Agent Rust"
    has_daemon = True
    needs_kernel_venv = True
    resume_fixture_capable = True  # argv passes --resume <fixture>
    # the install-rust.sh layout (launcher + payload under ~/.local);
    # product.yaml is the source of truth for the live pin
    default_binary_subpath = None
    # The deployed lane pin's revision (product.yaml is the source of truth
    # for the live pin; audit F10: the earlier pin fix landed in a config
    # file no code reads — product_config() now reads the config products
    # section too, closing that trap class).
    default_revision = "7152746b99f6767843bb40b4674a23a5a501fdc0"

    @property
    def binary(self) -> Path:
        """The pinned binary (product.yaml overrides)."""
        if self.product_cfg.get("binary"):
            return Path(self.product_cfg["binary"])
        return self.layout.root / self.default_binary_subpath

    def mock_base_url(self) -> str:
        """The mock provider base URL this product routes model traffic to."""
        return f"http://127.0.0.1:{self.mock_port}"

    def version_info(self) -> dict:
        """Pinned binary version + revision + machine-collected identity.

        The --version output prints no revision, so the revision is the pin
        and the sha256/bytes are collected from the binary itself. When the
        product.yaml pins ``binary_sha256``, a mismatch fails loudly: a
        stale pin or a swapped binary must never masquerade as collected
        provenance (audit F10). The pinned binary may be the install-rust.sh
        launcher (a 1KB script exec'ing the payload); the sha256/bytes then
        target the RESOLVED payload binary — the file that actually runs.
        """
        from bench.core.env import sha256_file
        v = subprocess.run([str(self.binary), "--version"], capture_output=True, text=True, timeout=60)
        payload = (self.binary.parent / ".." / "share" / "prime-agent-rust"
                   / "prime-agent").resolve()
        evidence = payload if payload.exists() else self.binary
        binary_sha256 = sha256_file(evidence)
        info = {"version": v.stdout.strip() or v.stderr.strip(),
                "revision": self.product_cfg.get("revision", self.default_revision),
                "binary": str(self.binary),
                "payload": str(evidence),
                "binary_sha256": binary_sha256,
                "binary_bytes": evidence.stat().st_size}
        pinned = self.product_cfg.get("binary_sha256")
        if pinned and pinned != binary_sha256:
            raise RuntimeError(
                f"{self.name} binary sha256 {binary_sha256} != pinned {pinned}; "
                "update the pin or restore the pinned binary before benchmarking")
        return info

    def prepare_template(self, tpl: Path) -> None:
        """Agent dir with mock models.json; preprovisioned Prime auth."""
        write_models_json(tpl / "agent", self.mock_base_url() + "/v1")
        copy_prime_auth(tpl / "agent")
        prime = tpl / "home" / ".prime"
        prime.mkdir(parents=True, exist_ok=True)
        cfg = NODE_HOME_AUTH_PRIME / "config.json"
        if cfg.exists():
            shutil.copy(cfg, prime / "config.json")

    # the pinned live route (real-api trials): the product's canonical
    # provider with its headline default model — NOT the live node
    # settings (other sessions on the node flip their default model
    # mid-campaign; the benchmark needs one deterministic answer)
    REAL_PROVIDER = "prime-inference"
    REAL_MODEL = "openai/gpt-6-sol"
    REAL_THINKING = "high"

    def customize_trial(self, ctx: TrialContext) -> None:
        ctx["agent_dir"] = ctx["trial_dir"] / "agent"
        copy_tree(self.template_dir() / "agent", ctx["agent_dir"])
        ctx["daemon_socket"] = ctx["trial_dir"] / "d.sock"
        if ctx.get("routing") != "real-api":
            write_models_json(ctx["agent_dir"], self.mock_base_url() + "/v1")

    def apply_routing(self, ctx: TrialContext) -> None:
        """Live routing: the product's own provider config. The mock
        models.json must go (it would pin traffic to the offline mock) and
        a settled settings.json lands in its place: the onboarding state of
        a user who already set the product up, with the campaign's pinned
        provider/model/thinking (deterministic across the campaign)."""
        if ctx.get("routing") != "real-api":
            return
        (ctx["agent_dir"] / "models.json").unlink(missing_ok=True)
        settings: dict = {}
        src = NODE_HOME_AUTH_PRIME / "agent" / "settings.json"
        try:
            settings = json.loads(src.read_text())
        except (OSError, ValueError):
            settings = {}
        settings.update({"defaultProvider": self.REAL_PROVIDER,
                        "defaultModel": self.REAL_MODEL,
                        "defaultThinkingLevel": self.REAL_THINKING,
                        "onboardingShown": True,
                        # the live node settings carry other sessions' model
                        # allowlists; the daemon blocks any model outside
                        # them (no fallback), so the pinned model must be
                        # allowed — one entry, exactly the pinned route
                        "allowedModels": [f"{self.REAL_PROVIDER}/{self.REAL_MODEL}"]})
        (ctx["agent_dir"] / "settings.json").write_text(json.dumps(settings, indent=1))

    def env(self, ctx: TrialContext) -> dict:
        cfg = {}
        try:
            cfg = json.loads((NODE_HOME_AUTH_PRIME / "config.json").read_text())
        except Exception:
            pass
        team_id = str(cfg.get("team_id") or "")
        extra = {
            "HOME": str(ctx["home"]),
            "TMPDIR": str(ctx["tmp"]),
            "PRIME_AGENT_CODING_AGENT_DIR": str(ctx["agent_dir"]),
            "PRIME_API_KEY": cfg.get("api_key", "sk-bench-missing"),
            # billing: the env-provided key bills the personal balance
            # (empty) unless the request carries the team id; the product
            # honors this env override (real-api trials need team billing)
            "PRIME_TEAM_ID": team_id,
        }
        extra.update(global_caches(self.name, self.layout))
        return scrubbed_env(extra)

    def argv(self, ctx: TrialContext, resume_fixture: str | None = None) -> list[str]:
        argv = [str(self.binary), "--daemon-socket", str(ctx["daemon_socket"])]
        if ctx.get("routing") != "real-api":
            # mock-routed launches pin the offline provider/model; live
            # launches run the product's settled defaults (settings.json)
            argv += ["--provider", "prime-inference", "--model", "mock-1", "--offline"]
        if resume_fixture:
            argv += ["--resume", resume_fixture]
        return argv

    def model_info(self, ctx: TrialContext) -> str:
        """The model a real-api submit routes to (evidence per row)."""
        return f"{self.REAL_PROVIDER}/{self.REAL_MODEL}"

    def daemon_argv(self, ctx: TrialContext) -> list[str] | None:
        return [str(self.binary), "--mode", "daemon",
                "--daemon-socket", str(ctx["daemon_socket"])]

    def reap(self, ctx: TrialContext) -> None:
        leftovers = sweep_trial(ctx)
        if leftovers:
            raise RuntimeError(f"trial sweep leftovers: {leftovers[:3]}")
