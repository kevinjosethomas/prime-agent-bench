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
from bench.core.product import ProductAdapter, TrialContext
from bench.core.process import sweep_trial


class PrimeAgentRustProduct(ProductAdapter):
    name = "rust"
    display_name = "Prime Agent Rust"
    has_daemon = True
    needs_kernel_venv = True
    resume_fixture_capable = True  # argv passes --resume <fixture>
    default_binary_subpath = "repos/prime-agent-rust/target/release/prime-agent"
    # The campaign-verified build revision (audit F10: the earlier pin fix
    # landed in a config file no code reads, leaving the live pin stale).
    default_revision = "bdf82f4f15e7d8c0b5e41bf473e3f5b26a8a41ad"

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
        provenance (audit F10).
        """
        from bench.core.env import sha256_file
        v = subprocess.run([str(self.binary), "--version"], capture_output=True, text=True, timeout=60)
        binary_sha256 = sha256_file(self.binary)
        info = {"version": v.stdout.strip() or v.stderr.strip(),
                "revision": self.product_cfg.get("revision", self.default_revision),
                "binary": str(self.binary),
                "binary_sha256": binary_sha256,
                "binary_bytes": self.binary.stat().st_size}
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

    def customize_trial(self, ctx: TrialContext) -> None:
        ctx["agent_dir"] = ctx["trial_dir"] / "agent"
        shutil.copytree(self.template_dir() / "agent", ctx["agent_dir"])
        ctx["daemon_socket"] = ctx["trial_dir"] / "d.sock"
        write_models_json(ctx["agent_dir"], self.mock_base_url() + "/v1")

    def env(self, ctx: TrialContext) -> dict:
        cfg = {}
        try:
            cfg = json.loads((NODE_HOME_AUTH_PRIME / "config.json").read_text())
        except Exception:
            pass
        extra = {
            "HOME": str(ctx["home"]),
            "TMPDIR": str(ctx["tmp"]),
            "PRIME_AGENT_CODING_AGENT_DIR": str(ctx["agent_dir"]),
            "PRIME_API_KEY": cfg.get("api_key", "sk-bench-missing"),
        }
        extra.update(global_caches(self.name, self.layout))
        return scrubbed_env(extra)

    def argv(self, ctx: TrialContext, resume_fixture: str | None = None) -> list[str]:
        argv = [str(self.binary), "--daemon-socket", str(ctx["daemon_socket"]),
                "--provider", "prime-inference", "--model", "mock-1", "--offline"]
        if resume_fixture:
            argv += ["--resume", resume_fixture]
        return argv

    def daemon_argv(self, ctx: TrialContext) -> list[str] | None:
        return [str(self.binary), "--mode", "daemon",
                "--daemon-socket", str(ctx["daemon_socket"])]

    def reap(self, ctx: TrialContext) -> None:
        leftovers = sweep_trial(ctx)
        if leftovers:
            raise RuntimeError(f"trial sweep leftovers: {leftovers[:3]}")
