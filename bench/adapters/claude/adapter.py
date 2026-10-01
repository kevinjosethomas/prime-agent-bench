"""Claude Code product adapter.

npm-installed CLI; onboarding prepass required (first-run dialogs reappear
unless walked in-place); model traffic routed to the offline mock.
"""
from __future__ import annotations

import json
import glob
import os
import subprocess
from pathlib import Path

from bench.core.env import scrubbed_env
from bench.core.product import ProductAdapter, TrialContext


class ClaudeCodeProduct(ProductAdapter):
    name = "claude"
    display_name = "Claude Code"
    needs_prepass = True
    # argv() ignores resume_fixture: no native Prime-JSONL resume; a
    # vendor-native history fixture (spec §F) does not exist yet.
    resume_fixture_capable = False

    @property
    def binary(self) -> Path:
        """The installed claude binary."""
        if self.product_cfg.get("binary"):
            return Path(self.product_cfg["binary"])
        return Path("/usr/bin/claude")

    def version_info(self) -> dict:
        from bench.core.env import sha256_file
        v = subprocess.run([str(self.binary), "--version"], capture_output=True, text=True, timeout=60,
                            env=scrubbed_env({"HOME": str(Path.home())}))
        return {"version": v.stdout.strip(),
                "revision": self.product_cfg.get("revision", "npm@latest"),
                "binary": str(self.binary),
                "binary_sha256": sha256_file(Path(self.binary).resolve())}

    def prepare_template(self, tpl: Path) -> None:
        """A clean Claude Code home: no operator settings, hooks, plugins,
        history or identity. Nothing from the node's ~/.claude is needed:
        mock-routed trials authenticate with ANTHROPIC_API_KEY from the
        env (real-api with ANTHROPIC_AUTH_TOKEN), and the prepass walks the
        first-run dialogs. The one harness-owned key turns the auto-updater
        off so no trial downloads an update mid-measurement."""
        claude_dir = tpl / "home" / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        (tpl / "home" / ".claude.json").write_text(json.dumps({"autoUpdates": False}))

    def customize_trial(self, ctx: TrialContext) -> None:
        cj = ctx["home"] / ".claude.json"
        if cj.exists():
            data = json.loads(cj.read_text())
            data.setdefault("projects", {})[str(ctx["work"])] = {"hasTrustDialogAccepted": True}
            cj.write_text(json.dumps(data))

    #: the live provider this harness routes claude through when the
    #: benchmark requests real-api routing (no OAuth state on the node):
    #: Prime Inference's Anthropic-protocol endpoint (verified: the
    #: messages API speaks the Anthropic wire format; personal balances
    #: are empty, so the team header selects team billing)
    REAL_BASE_URL = "https://api.pinference.ai/api"
    REAL_MODEL = "anthropic/claude-fable-5"

    def _prime_config(self) -> dict:
        """The node's Prime credentials (api key + team id) for the live route."""
        try:
            return json.loads((Path.home() / ".prime" / "config.json").read_text())
        except (OSError, ValueError):
            return {}

    def env(self, ctx: TrialContext) -> dict:
        extra = {
            "HOME": str(ctx["home"]),
            "TMPDIR": str(ctx["tmp"]),
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        }
        if ctx.get("routing") == "real-api":
            cfg = self._prime_config()
            extra.update({
                "ANTHROPIC_BASE_URL": self.REAL_BASE_URL,
                "ANTHROPIC_AUTH_TOKEN": cfg.get("api_key", ""),
                "ANTHROPIC_MODEL": self.REAL_MODEL,
                "ANTHROPIC_SMALL_FAST_MODEL": self.REAL_MODEL,
            })
            if cfg.get("team_id"):
                extra["ANTHROPIC_CUSTOM_HEADERS"] = f"X-Prime-Team-ID: {cfg['team_id']}"
        else:
            extra.update({
                "ANTHROPIC_API_KEY": "sk-bench-dummy-not-real",
                "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{self.mock_port}",
                "ANTHROPIC_AUTH_TOKEN": "sk-bench-dummy-not-real",
            })
        return scrubbed_env(extra)

    def model_info(self, ctx: TrialContext) -> str:
        """The model a real-api submit routes to (evidence per row)."""
        return self.REAL_MODEL if ctx.get("routing") == "real-api" else "mock"

    def argv(self, ctx: TrialContext, resume_fixture: str | None = None) -> list[str]:
        return [str(self.binary)]


class ClaudeCodeDaemonProduct(ClaudeCodeProduct):
    """Claude Code on its resident daemon: the ``claude agents`` view, the
    daemon-backed front end (dispatch prompt + background sessions).

    Cold: no claude daemon runs for the trial home; ``claude agents``
    starts the transient supervisor itself (``claude.exe daemon run
    --origin transient``, plus a bg-pty-host and a pre-spawned bg-spare
    session). Warm: the supervisor already runs, started by claude's own
    ``claude daemon run``; ``claude agents`` connects to it. The daemon's
    control socket lives under /tmp/cc-daemon-<uid>/<hash>/ (hard-coded
    /tmp, one hash per config dir), so readiness is the one accepting
    control.sock there (sequential trials: every earlier trial's daemon is
    swept, its socket refuses)."""

    name = "claude_daemon"
    display_name = "Claude Code (daemon: claude agents)"
    config_name = "claude"
    has_daemon = True
    daemon_process_args = ("daemon", "run")
    # what `claude agents` stamps on the supervisor it spawns (observed on
    # 2.1.285): agent/launcher markers, not daemon configuration
    daemon_spawn_env_keys = ("AI_AGENT", "COREPACK_ENABLE_AUTO_PIN", "INVOCATION_ID",
                             "NoDefaultCurrentDirectoryInExePath")

    def argv(self, ctx: TrialContext, resume_fixture: str | None = None) -> list[str]:
        return [str(self.binary), "agents"]

    def daemon_argv(self, ctx: TrialContext) -> list[str] | None:
        return [str(self.binary), "daemon", "run"]

    def wait_daemon_ready(self, ctx: TrialContext, timeout: float = 60.0) -> bool:
        import socket
        import time
        lock = ctx["home"] / ".claude" / "daemon.lock"
        pattern = f"/tmp/cc-daemon-{os.getuid()}/*/control.sock"
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            if lock.exists():
                for path in glob.glob(pattern):
                    try:
                        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                            s.settimeout(2)
                            s.connect(path)
                        return True
                    except OSError:
                        continue
            time.sleep(0.005)
        return False
