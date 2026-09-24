"""Environment policy shared by every product adapter.

Scrubbed env, isolated per-trial homes, shared warm caches, mock-provider
models.json, and the on-disk bench layout. Not part of any product.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

HOME = Path.home()
NODE_HOME_AUTH_PRIME = HOME / ".prime"

SCRUB_PREFIXES = ("PRIME_AGENT_INTERNAL", "RLM_", "PI_", "ANTHROPIC", "OPENAI",
                  "CODEX", "CLAUDE", "BENCH_")
SCRUB_KEYS = ("TMUX", "TMUX_PANE", "PRIME_AGENT_SESSION_DIR",
              "PRIME_AGENT_CODING_AGENT_DIR",
              "PRIME_AGENT_CODING_AGENT_SESSION_DIR",
              "PRIME_AGENT_KERNEL_OWNER_PID", "PI_CODING_AGENT_DIR",
              "PI_CODING_AGENT", "PRIME_API_KEY")


@dataclass(frozen=True)
class BenchLayout:
    """The bench tree on the benchmark node (config-overridable for dev)."""

    root: Path
    logs: Path
    harness_dir: Path
    fixtures: Path
    homes: Path
    results: Path
    global_dir: Path
    sandboxes: Path

    @classmethod
    def from_config(cls, cfg: dict) -> BenchLayout:
        root = Path(cfg["bench_root"]).expanduser()
        return cls(
            root=root,
            logs=root / "logs",
            harness_dir=root / "harness",
            fixtures=root / "fixtures",
            homes=root / "homes",
            results=Path(cfg["results_dir"]).expanduser(),
            global_dir=root / "global",
            sandboxes=root / "sandboxes",
        )

    @property
    def repos(self) -> Path:
        """Pinned product source checkouts (rust, pi-mono)."""
        return self.root / "repos"


def sha256_file(path: Path) -> str:
    """The sha256 of one file (binary attribution evidence; None-safe)."""
    import hashlib
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def scrubbed_env(extra: dict | None = None) -> dict:
    """The controlled launch env: harness/product vars scrubbed, fixed
    locale/term, node PATH. Product-specific extras are merged last."""
    env = {k: v for k, v in os.environ.items()
           if not any(k.startswith(p) for p in SCRUB_PREFIXES) and k not in SCRUB_KEYS}
    env.pop("COLORTERM", None)
    env["TERM"] = "xterm-256color"
    env["LANG"] = "C.UTF-8"
    env["LC_ALL"] = "C.UTF-8"
    env["PATH"] = ("/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:"
                   + str(HOME / ".local/bin"))
    if extra:
        env.update(extra)
    return env


def mock_url(cfg: dict) -> str:
    """Base URL of the offline mock provider."""
    return f"http://127.0.0.1:{int(cfg['mock']['port'])}"


def global_caches(name: str, layout: BenchLayout) -> dict:
    """Shared per-product caches across trials: kernel venv, uv cache, XDG
    cache. Trial homes stay isolated for state (auth/sessions); these are the
    warm dependency caches (install-cost measured by kernel.venv_bootstrap,
    not by every cold start)."""
    g = layout.global_dir / name
    for sub in ("kernel-venv", "uv-cache", "xdg-cache"):
        (g / sub).mkdir(parents=True, exist_ok=True)
    return {
        "PRIME_AGENT_KERNEL_VENV": str(g / "kernel-venv"),
        "UV_CACHE_DIR": str(g / "uv-cache"),
        "UV_PYTHON_INSTALL_DIR": str(Path.home() / ".local" / "share" / "uv" / "python"),
        "XDG_CACHE_HOME": str(g / "xdg-cache"),
    }


def write_models_json(agent_dir: Path, base_url: str) -> None:
    """Point the product's models.json at the offline mock provider."""
    agent_dir.mkdir(parents=True, exist_ok=True)
    models = {
        "providers": {
            "prime-inference": {
                "api": "openai-completions",
                "baseUrl": base_url,
                "apiKey": "sk-battery",
                "models": [
                    {
                        "id": "mock-1",
                        "name": "Mock 1",
                        "api": "openai-completions",
                        "baseUrl": base_url,
                        "contextWindow": 128000,
                        "maxTokens": 4096,
                    }
                ],
            }
        }
    }
    (agent_dir / "models.json").write_text(json.dumps(models, indent=1))


def copy_prime_auth(agent_dir: Path) -> None:
    """Copy the node's preprovisioned Prime Agent auth into an agent dir."""
    auth = NODE_HOME_AUTH_PRIME / "agent" / "auth.json"
    if auth.exists():
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / "auth.json").write_bytes(auth.read_bytes())


#: The return-user consent baseline in the products' own settings schema,
#: verified against the pinned sources: TS acc5bc0 (settings-manager.ts +
#: onboarding.ts — ``shouldRunOnboarding`` is gated on ``onboardingShown``
#: alone; the share-traces sheet's "Not now" persists
#: ``agentTraces.enabled=false``; the telemetry notice is gated on
#: ``telemetry.noticeShown``) and Rust bdf82f4f (pa-core/src/settings/
#: types.rs + pa-cli/src/interactive_mode.rs — the same camelCase keys).
#: ``{"traces": "not-now"}`` is NOT a product shape; it existed only in an
#: old bench fake and must never be seeded.
CONSENT_BASELINE_SETTINGS = {
    "onboardingShown": True,
    "agentTraces": {"enabled": False},
    "telemetry": {"noticeShown": True},
}


def write_consent_baseline(agent_dir: Path) -> dict:
    """Seed the return-user consent baseline into a product settings.json.

    Writes ``<agent_dir>/settings.json`` with the pinned keys; an existing
    file keeps its other keys (a template rebuilt over product-persisted
    settings must not lose them), and the three consent keys are enforced
    to the pinned values — a seeded trial is a return user who has seen
    onboarding, declined traces, and seen the telemetry notice, so no
    consent sheet can appear in a measured launch. Returns the file's
    final parsed content (evidence for tests)."""
    agent_dir.mkdir(parents=True, exist_ok=True)
    path = agent_dir / "settings.json"
    settings: dict = {}
    if path.exists():
        try:
            settings = json.loads(path.read_text())
            if not isinstance(settings, dict):
                settings = {}
        except Exception:
            settings = {}
    settings.update(json.loads(json.dumps(CONSENT_BASELINE_SETTINGS)))
    path.write_text(json.dumps(settings, indent=1) + "\n")
    return settings


def make_workdir(work: Path) -> None:
    """The deterministic work repo every trial launches in."""
    work.mkdir(parents=True, exist_ok=True)
    (work / "README.md").write_text("# bench fixture\nDeterministic benchmark work repository.\n")
    (work / "src").mkdir(exist_ok=True)
    (work / "src" / "main.py").write_text(
        "def main():\n    print('bench fixture')\n\n\n"
        "if __name__ == '__main__':\n    main()\n")
    subprocess.run(["git", "init", "-q"], cwd=work, check=True)
    subprocess.run(["git", "-c", "user.email=bench@local", "-c", "user.name=bench",
                    "add", "-A"], cwd=work, check=True)
    subprocess.run(["git", "-c", "user.email=bench@local", "-c", "user.name=bench",
                    "commit", "-qm", "bench fixture"], cwd=work, check=True)
