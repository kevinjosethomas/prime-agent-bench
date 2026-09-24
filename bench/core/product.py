"""The ProductAdapter ABC: one product = one self-contained adapter file.

Lifecycle: install/authenticate (node setup), prepare_template (the settled
home template), new_trial (isolated per-trial copy), launch/settle/act/
observe (driver-facing interaction), reap/cleanup (process-tree teardown).
Adding a product = one file under bench/adapters/products/.
"""
from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

from bench.core.env import BenchLayout, make_workdir

if TYPE_CHECKING:  # pragma: no cover - import cycle guard for type checkers
    from bench.core.harness import HarnessDriver, Session


class TrialContext(TypedDict, total=False):
    """The per-trial filesystem: isolated home/work/tmp plus product state."""

    trial_dir: Path
    home: Path
    work: Path
    tmp: Path
    agent_dir: Path | None
    daemon_socket: Path | None


DialogStep = tuple[str, list[str]]
"""(screen marker, keystrokes) answered during onboarding settle walks."""


class ProductAdapter(ABC):
    """A product under comparison (Prime Agent Rust/TS, Claude Code, ...).

    ``cfg`` carries the resolved BenchLayout under ``cfg["layout"]`` and the
    per-product pinning from configs/products/<name>.yaml under
    ``cfg["product"]``.
    """

    name: str = ""
    display_name: str = ""
    has_daemon: bool = False
    needs_prepass: bool = False
    dialog_steps: list[DialogStep] = []

    def __init__(self, cfg: dict):
        """cfg keys: layout (BenchLayout), product (per-product pinning
        slice), mock ({"port": int} of the offline mock provider)."""
        self.cfg = cfg
        self.product_cfg: dict = dict(cfg.get("product") or {})
        self.mock_port: int = int(cfg.get("mock", {}).get("port", 8788))
        self.layout: BenchLayout = cfg["layout"]

    # ---- node setup: install + authenticate -----------------------------
    def install(self) -> dict:
        """Verify the pinned install (the node setup itself is documented
        per-product; this is the cheap preflight that fails loudly)."""
        binary = Path(self.product_cfg.get("binary", ""))
        return {"ok": binary.exists(), "binary": str(binary), "product": self.name}

    def authenticate(self, home: Path) -> None:
        """Preprovision auth for a trial home. Default: nothing to do; the
        products that need credentials copy them in prepare_template."""

    # ---- trial lifecycle -------------------------------------------------
    @abstractmethod
    def version_info(self) -> dict:
        """The pinned version/revision record for results evidence."""

    @abstractmethod
    def prepare_template(self, tpl: Path) -> None:
        """Build the settled home template (auth, config, onboarding state)."""

    def template_dir(self) -> Path:
        """The per-product template directory trials copy from."""
        return self.layout.homes / self.name / "template"

    def new_trial(self, trial: Path) -> TrialContext:
        """Materialize an isolated trial (template home + fresh work repo)."""
        shutil.copytree(self.template_dir(), trial / "home", symlinks=True)
        work = trial / "work"
        make_workdir(work)
        (trial / "tmp").mkdir(exist_ok=True)
        ctx: TrialContext = {
            "trial_dir": trial,
            "home": trial / "home",
            "work": work,
            "tmp": trial / "tmp",
            "agent_dir": None,
            "daemon_socket": None,
        }
        self.customize_trial(ctx)
        return ctx

    def customize_trial(self, ctx: TrialContext) -> None:
        """Per-trial state overrides (agent dirs, daemon sockets)."""

    def env(self, ctx: TrialContext) -> dict:
        """The launch env for this trial."""
        from bench.core.env import scrubbed_env
        return scrubbed_env({"HOME": str(ctx["home"]), "TMPDIR": str(ctx["tmp"])})

    @abstractmethod
    def argv(self, ctx: TrialContext, resume_fixture: str | None = None) -> list[str]:
        """The TUI launch argv (optionally resuming a session fixture)."""

    def daemon_argv(self, ctx: TrialContext) -> list[str] | None:
        """The resident-daemon argv, or None if the product has none."""
        return None

    def reap(self, ctx: TrialContext) -> None:
        """Tear down every process belonging to this trial."""

    def cleanup(self, ctx: TrialContext) -> None:
        """Post-trial teardown (alias for reap by default)."""
        self.reap(ctx)

    # ---- driver-facing interaction ---------------------------------------
    def launch(self, ctx: TrialContext, driver: HarnessDriver,
               resume_fixture: str | None = None) -> Session:
        """Start this product in the given harness driver and return the
        session (the PTY and tmux drivers are interchangeable)."""
        return driver.start_session(self.argv(ctx, resume_fixture),
                                     env=self.env(ctx), cwd=str(ctx["work"]))

    def settle(self, session: Session, timeout: float, pacing: dict) -> str:
        """Answer onboarding dialogs until the editor echoes a probe token
        (ready). Pacing keys: key_pause_s, loop_s, echo_wait_s."""
        from bench.adapters.benchmarks.support import drive_to_ready
        return drive_to_ready(session, self.dialog_steps, timeout=timeout,
                              probe="Zq7x01", pacing=pacing)

    def act(self, session: Session, keys: str) -> float:
        """Send keystrokes; returns the send timestamp."""
        return session.send(keys)

    def observe(self, session: Session) -> str:
        """The rendered screen text right now."""
        return session.screen_text()
