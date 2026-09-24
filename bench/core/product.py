"""The ProductAdapter ABC: one harness = one self-contained adapter folder.

Lifecycle: install/authenticate (node setup), prepare_template (the settled
home template), new_trial (isolated per-trial copy), launch/settle/act/
observe (driver-facing interaction), reap/cleanup (process-tree teardown).
Adding a harness = one folder under bench/adapters/<name>/.
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

MSG_ROUTING_REGIMES = ("mock", "real-api")
"""How a submitted message routes to a model. ``mock``: the offline mock
provider, so the scripted reply is known verbatim and settle detectors
match its text. ``real-api``: live inference — the reply is unknowable,
so message-settle scenarios do not measure a settle at all; the row
records the regime and the result-validity gate keeps cross-regime
values out of the rankings."""

KEY_TOKENS: dict[str, str] = {
    "enter": "\r", "return": "\r",
    "up": "\x1b[A", "down": "\x1b[B", "right": "\x1b[C", "left": "\x1b[D",
    "esc": "\x1b", "escape": "\x1b", "tab": "\t", "space": " ",
    "pgup": "\x1b[5~", "pgdn": "\x1b[6~", "home": "\x1b[H", "end": "\x1b[F",
}


def keystroke(spec: str) -> str:
    """One configured key: a token name (``enter``, ``down``, ...), a
    ``ctrl+<key>``/``alt+<key>`` combo, or the literal text to type (any
    other string, newlines become ``\r``).

    The PTY/tmux drivers write keystrokes verbatim, so a modifier combo
    must resolve to the bytes a terminal actually delivers:
    ``ctrl+a``..``ctrl+z`` are the C0 control range (``\x01``..``\x1a``),
    ``alt+<token-or-char>`` is the ESC-prefixed sequence. Anything else
    stays the literal text (the onboarding dialogs type API keys)."""
    raw = str(spec).strip().lower()
    token = KEY_TOKENS.get(raw)
    if token is not None:
        return token
    if raw.startswith("ctrl+"):
        key = raw[len("ctrl+"):]
        # ctrl+<letter> -> C0 control byte (a -> \x01 ... z -> \x1a)
        if len(key) == 1 and "a" <= key <= "z":
            return chr(ord(key) - ord("a") + 1)
    if raw.startswith("alt+"):
        key = raw[len("alt+"):]
        base = KEY_TOKENS.get(key) or key
        return "\x1b" + base
    return str(spec).replace("\n", "\r")


def resolve_dialogs(entries: list | None) -> list[DialogStep]:
    """``first_run_dialogs`` config entries -> (marker, keys) walk steps.

    One config entry = one dialog a product shows on first run: the
    ``marker`` (whitespace-normalized text match against the rendered
    screen; TUIs hard-wrap at arbitrary columns) and the ``keys`` to type
    when it appears. A new dialog in a product version is one config
    entry, not a debugging session."""
    steps: list[DialogStep] = []
    for entry in entries or []:
        if "marker" not in entry:
            raise ValueError(f"first_run_dialogs entry without marker: {entry}")
        marker = str(entry["marker"]).strip()
        if not marker:
            raise ValueError(f"first_run_dialogs entry with empty marker: {entry}")
        keys = [keystroke(k) for k in (entry.get("keys") or [])]
        steps.append((marker, keys))
    return steps


class ProductAdapter(ABC):
    """A product under comparison (Prime Agent Rust/TS, Claude Code, ...).

    ``cfg`` carries the resolved BenchLayout under ``cfg["layout"]`` and
    the harness folder's pinning (bench/adapters/<name>/product.yaml)
    under ``cfg["product"]``.
    """

    name: str = ""
    display_name: str = ""
    has_daemon: bool = False
    needs_prepass: bool = False
    needs_kernel_venv: bool = False
    # Whether argv() actually resumes the Prime session-JSONL fixture
    # (--resume). Competitors without a vendor-native equivalent stay
    # False: fixture-based scenarios then record them not_comparable
    # (spec §F) instead of measuring a fresh session.
    resume_fixture_capable: bool = False
    # How a submitted message routes (MSG_ROUTING_REGIMES); product.yaml
    # ``msg_routing:`` overrides. Message-settle scenarios measure the
    # settle only in the mock regime — the harness declares the regime,
    # scenarios never branch on the harness's name.
    msg_routing: str = "mock"
    dialog_steps: list[DialogStep] = []  # fallback; config is the source of truth

    def __init__(self, cfg: dict):
        """cfg keys: layout (BenchLayout), product (per-product pinning
        slice), mock ({"port": int} of the offline mock provider)."""
        self.cfg = cfg
        self.product_cfg: dict = dict(cfg.get("product") or {})
        self.mock_port: int = int(cfg.get("mock", {}).get("port", 8788))
        self.layout: BenchLayout = cfg["layout"]
        self.dialog_steps = resolve_dialogs(self.product_cfg.get("first_run_dialogs"))
        self.msg_routing = str(self.product_cfg.get("msg_routing", type(self).msg_routing))
        if self.msg_routing not in MSG_ROUTING_REGIMES:
            raise ValueError(
                f"{self.name or type(self).__name__}: msg_routing must be one of "
                f"{list(MSG_ROUTING_REGIMES)}, not {self.msg_routing!r}")

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
