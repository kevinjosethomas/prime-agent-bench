"""Pi Mono (pi-mono coding agent) product adapter.

Built from the pinned source checkout; provider/model flags select the
models.json mock provider, the copied auth.json keeps the product
authenticated (no onboarding).

Loaded-session trials (spec §F): pi's persisted transcript IS the bench
session-JSONL schema (pi v3 session header + id/parentId entries; Prime
Agent forked pi), so the native fixture import is a validated byte copy of
the corpus staged into the trial's agent sessions dir and resumed with
the native `--session <path>` flag (SessionManager.open — a direct file
path is a first-class resume input in the pinned 0.73.0 source). The
staged copy is the only thing the TUI ever appends to; the gold fixture
file is never touched.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from bench.adapters.fixtures.session_size import SENTINEL
from bench.core.env import copy_prime_auth, write_models_json
from bench.core.product import ProductAdapter, TrialContext


def _fixture_rows(data: bytes, source: Path) -> list[dict]:
    """Parse + structurally validate the fixture as a pi session file.

    Fail loudly: a fixture that is not a parseable v3-style session must
    never be staged as a native one."""
    try:
        rows = [json.loads(line) for line in data.decode().splitlines() if line.strip()]
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise RuntimeError(f"fixture {source} is not parseable session JSONL: {e}")
    if not rows or rows[0].get("type") != "session" or not rows[0].get("cwd"):
        raise RuntimeError(f"fixture {source} lacks the pi session header row")
    return rows


def _assert_tail_sentinel(rows: list[dict], source: Path) -> None:
    """The last message row must be the assistant row carrying the visible
    tail sentinel — the row the scenarios' wait_sentinel must be able to
    render on the reopened UI."""
    msgs = [r for r in rows if r.get("type") == "message"]
    tail = msgs[-1] if msgs else None
    text = ""
    if tail and tail.get("message", {}).get("role") == "assistant":
        text = " ".join(
            part.get("text", "") for part in tail["message"].get("content", [])
            if isinstance(part, dict))
    if SENTINEL not in text:
        raise RuntimeError(
            f"fixture {source} tail message does not carry the suite sentinel "
            f"{SENTINEL!r}; refusing to stage it as a native session")


class PiMonoProduct(ProductAdapter):
    name = "pi"
    display_name = "Pi Mono"
    default_revision = "b45597504eeaba1f11a9920a1d1048c361ed4b8e"
    # Native loaded-session resume (spec §F): prepare_native_fixture stages
    # a validated copy of the corpus as a pi session file; argv resumes it
    # with `--session <path>`.
    resume_fixture_capable = True

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

    def prepare_native_fixture(self, ctx: TrialContext, fixture: str) -> dict:
        """Stage the corpus as a pi-native session file for this trial.

        The bench session-JSONL IS pi's v3 session format, so the native
        import is a byte copy (same semantic workload by construction:
        same rows, same turns, same visible tail sentinel, same bytes).
        Staging validates the fixture structure, ensures the recorded
        session cwd exists (pi asks an interactive continuation prompt
        otherwise — the recorded cwd must be real, per the fixture
        reproducibility contract), and never touches the source file."""
        source = Path(fixture)
        data = source.read_bytes()
        rows = _fixture_rows(data, source)
        _assert_tail_sentinel(rows, source)
        source_sha = hashlib.sha256(data).hexdigest()
        turns = sum(1 for r in rows if r.get("type") == "message"
                    and r.get("message", {}).get("role") == "user")

        staged = ctx["agent_dir"] / "sessions" / f"bench-fixture-{source_sha[:16]}.jsonl"
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(data)
        staged_sha = hashlib.sha256(staged.read_bytes()).hexdigest()
        if staged_sha != source_sha:
            raise RuntimeError(f"staged session {staged} hash {staged_sha} != source {source_sha}")
        Path(rows[0]["cwd"]).mkdir(parents=True, exist_ok=True)
        ctx["fixture_native_path"] = str(staged)
        return {
            "format": "pi-session-jsonl-v3",
            "mechanism": "cli --session <path> (SessionManager.open, direct file resume)",
            "path": str(staged),
            "sha256": staged_sha,
            "bytes": len(data),
            "rows": len(rows),
            "turns": turns,
            "sentinel": SENTINEL,
            "source": {"path": str(source), "sha256": source_sha,
                       "bytes": len(data), "rows": len(rows)},
        }

    def argv(self, ctx: TrialContext, resume_fixture: str | None = None) -> list[str]:
        argv = ["node", str(self.cli_path), "--provider", "prime-inference", "--model", "mock-1",
                "--no-extensions", "--no-skills", "--no-prompt-templates"]
        if resume_fixture:
            argv += ["--session", str(ctx["fixture_native_path"])]
        return argv
