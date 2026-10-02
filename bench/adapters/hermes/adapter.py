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

Trustworthy-suite rules (one enforced definition per metric): no daemon —
`hermes` is a single interactive process, so compare.warm_start measures
the product's native repeat launch (warm_mode=repeat_launch); ready is
the typed token on the ``❯`` input row (product.yaml input_prompt) that
persists; version evidence is machine-collected where the trials run (the
in-sandbox FHS tree: live `--version` + a digest of the installed code
tree), so a changed install fails the pass's version check. No
self-update: the trial config.yaml pins ``updates.check: false`` — the
banner's passive GitHub-API check (cached at ~/.hermes/.update_check) is
off for every trial (v0.21.5 has no HERMES_NO_UPDATE_CHECK env; the
config key is the release's own switch).
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from bench.core.env import scrubbed_env
from bench.core.product import ProductAdapter, TrialContext

#: the sandbox-side install paths (the vendored payload's targets)
FHS_CODE = Path("/usr/local/lib/hermes-agent")
FHS_COMMAND = Path("/usr/local/bin/hermes")


def tree_digest(root: Path) -> str | None:
    """A stable digest of an installed code tree: sha256 over the sorted
    (relative path, file sha256) pairs. ``.git`` and ``__pycache__`` are
    skipped (vendored away / regenerated at first import), so the digest
    is the installed product, not its build litter or bytecode cache."""
    import hashlib
    if not root.is_dir():
        return None
    acc = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if any(part in (".git", "__pycache__") for part in path.parts):
            continue
        if path.is_symlink():
            acc.update(f"L {rel} -> {os.readlink(path)}\n".encode())
        elif path.is_file():
            acc.update(f"F {rel} ".encode())
            acc.update(hashlib.sha256(path.read_bytes()).hexdigest().encode())
            acc.update(b"\n")
    return acc.hexdigest()


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

    def __init__(self, cfg: dict):
        """Resolve the install footprint to the live install when present.

        The vendored payload stages the FHS layout under a node-side
        prefix (~/bench-r2/hermes-payload/usr/local/...); a machine that
        carries the install itself (every sandbox, the benchmark node)
        has it at the FHS paths. compare.install_disk's accounting must
        read the REAL install wherever it lives, or the r2-era trap
        returns: installed_bytes 0 on the machine that actually runs the
        trials (the staging tree is not the footprint)."""
        super().__init__(cfg)
        marker = "hermes-payload/"
        resolved = []
        for p in (self.product_cfg.get("install") or {}).get("installed_paths") or []:
            p = str(p)
            if marker in p:
                fhs = "/" + p.split(marker, 1)[1]
                resolved.append(fhs if Path(fhs).exists() else p)
            else:
                resolved.append(p)
        if resolved:
            self.product_cfg.setdefault("install", {})["installed_paths"] = resolved

    def version_info(self) -> dict:
        """Machine-collected version evidence, collected where trials run.

        In-sandbox the FHS install is live: /usr/local/bin/hermes execs
        /usr/local/lib/hermes-agent/hermes (the venv python), so the
        launcher's own `--version` runs (its fast path answers before the
        config/network import wall; a scratch HOME keeps the probe
        stateless) and ``binary_sha256`` is a digest of the installed code
        tree — the whole product for a source install, not just the 3-line
        launcher shim. The digest skips ``.git`` (vendored out) and
        ``__pycache__`` (regenerated at first import), so it is stable
        across a pass; anything else that rewrites the install tree fails
        the end-of-pass version check. Node-side dry-runs (no FHS install)
        fall back to the product.yaml staging paths: the version string is
        then the pin captured at install time."""
        import subprocess
        import tempfile
        from bench.core.env import sha256_file
        install = self.product_cfg.get("install") or {}
        launcher = Path(self.product_cfg.get("binary") or FHS_COMMAND)
        if not launcher.exists():
            alt = install.get("launcher_src")
            launcher = Path(alt).expanduser() if alt else launcher
        code = FHS_CODE if FHS_CODE.exists() else self.payload_code
        entry = code / "hermes"
        version = None
        if launcher.exists():
            with tempfile.TemporaryDirectory() as td:
                try:
                    v = subprocess.run([str(launcher), "--version"],
                                        capture_output=True, text=True, timeout=90,
                                        env=scrubbed_env({"HOME": td}))
                    lines = [ln.strip() for ln in (v.stdout or v.stderr).splitlines()
                             if ln.strip()]
                    version = lines[0] if v.returncode == 0 and lines else None
                except (OSError, subprocess.SubprocessError):
                    version = None
        info = {
            "version": version or self.product_cfg.get("version") or "unknown",
            "revision": self.product_cfg.get("revision", "unknown"),
            "binary": str(launcher),
            "entry": str(entry),
            "binary_sha256": tree_digest(code) if code.is_dir() else None,
            "binary_digest_note": ("sha256 over the sorted (path, sha256) of every "
                                   "file under the install tree, .git and "
                                   "__pycache__ excluded"),
        }
        pinned = self.product_cfg.get("binary_sha256")
        if pinned and info["binary_sha256"] and pinned != info["binary_sha256"]:
            raise RuntimeError(
                f"{self.name} install-tree digest {info['binary_sha256']} != pinned "
                f"{pinned}; a swapped or modified payload must never masquerade as "
                "the pinned install - restore the payload or update the pin")
        note = install.get("note")
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
        to the trial home's .hermes (per-trial state). The update switch is
        the trial config.yaml's ``updates.check: false`` (v0.21.5's own
        knob); HERMES_NO_UPDATE_CHECK rides as inert belt-and-braces for
        any release that starts honoring it."""
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
