#!/usr/bin/env python3
"""Product adapters for the cross-product benchmark suite.

Each product: pinned version, isolated per-trial home/agent dirs, offline
mock-provider routing, launch argv, daemon handling (where applicable),
and install-footprint accounting. Auth is preprovisioned per trial home
(real credentials copied from the authenticated node home; model traffic
routed to the local mock so no paid inference can occur).

Not part of any product. Benchmark harness only.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

HOME = Path.home()
BENCH = HOME / "bench"
NODE_HOME_AUTH_PRIME = HOME / ".prime"
MOCK_PORT = 8788
MOCK_URL = f"http://127.0.0.1:{MOCK_PORT}"

GLOBAL = Path.home() / "bench" / "global"


def global_caches(name: str) -> dict:
    """Shared per-product caches across trials: kernel venv, uv cache, XDG
    cache. Trial homes stay isolated for state (auth/sessions); these are the
    warm dependency caches (install-cost measured by kernel.venv_bootstrap,
    not by every cold start)."""
    g = GLOBAL / name
    (g / "kernel-venv").mkdir(parents=True, exist_ok=True)
    (g / "uv-cache").mkdir(parents=True, exist_ok=True)
    (g / "xdg-cache").mkdir(parents=True, exist_ok=True)
    return {
        "PRIME_AGENT_KERNEL_VENV": str(g / "kernel-venv"),
        "UV_CACHE_DIR": str(g / "uv-cache"),
        "XDG_CACHE_HOME": str(g / "xdg-cache"),
    }

RUST_BIN = BENCH / "repos/prime-agent-rust/target/release/prime-agent"
TS_CLI = HOME / ".local/share/prime-agent/bin/prime-agent"
PI_CLI = BENCH / "repos/pi-mono/packages/coding-agent/dist/bundle/cli.js"
CLAUDE_BIN = Path("/usr/bin/claude")
CODEX_BIN = Path("/usr/bin/codex")

PRODUCTS = ["rust", "ts", "claude", "codex", "pi"]

SCRUB_PREFIXES = ("PRIME_AGENT_INTERNAL", "RLM_", "PI_", "ANTHROPIC", "OPENAI", "CODEX", "CLAUDE", "BENCH_")
SCRUB_KEYS = ("TMUX", "TMUX_PANE", "PRIME_AGENT_SESSION_DIR", "PRIME_AGENT_CODING_AGENT_DIR",
              "PRIME_AGENT_CODING_AGENT_SESSION_DIR", "PRIME_AGENT_KERNEL_OWNER_PID",
              "PI_CODING_AGENT_DIR", "PI_CODING_AGENT", "PRIME_API_KEY")


def scrubbed_env(extra: dict | None = None) -> dict:
    env = {k: v for k, v in os.environ.items()
           if not any(k.startswith(p) for p in SCRUB_PREFIXES) and k not in SCRUB_KEYS}
    env.pop("COLORTERM", None)
    env["TERM"] = "xterm-256color"
    env["LANG"] = "C.UTF-8"
    env["LC_ALL"] = "C.UTF-8"
    env["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:" + str(HOME / ".local/bin")
    if extra:
        env.update(extra)
    return env


def write_models_json(agent_dir: Path, base_url: str = MOCK_URL + "/v1"):
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


def make_workdir(work: Path):
    work.mkdir(parents=True, exist_ok=True)
    (work / "README.md").write_text("# bench fixture\nDeterministic benchmark work repository.\n")
    (work / "src").mkdir(exist_ok=True)
    (work / "src" / "main.py").write_text("def main():\n    print('bench fixture')\n\n\nif __name__ == '__main__':\n    main()\n")
    subprocess.run(["git", "init", "-q"], cwd=work, check=True)
    subprocess.run(["git", "-c", "user.email=bench@local", "-c", "user.name=bench",
                    "add", "-A"], cwd=work, check=True)
    subprocess.run(["git", "-c", "user.email=bench@local", "-c", "user.name=bench",
                    "commit", "-qm", "bench fixture"], cwd=work, check=True)


class Product:
    name = ""
    has_daemon = False

    def version_info(self) -> dict:
        raise NotImplementedError

    def prepare_template(self, tpl: Path):
        raise NotImplementedError

    def template_dir(self) -> Path:
        return BENCH / "homes" / self.name / "template"

    def new_trial(self, trial: Path) -> dict:
        shutil.copytree(self.template_dir(), trial / "home", symlinks=True)
        work = trial / "work"
        make_workdir(work)
        (trial / "tmp").mkdir(exist_ok=True)
        ctx = {
            "trial_dir": trial,
            "home": trial / "home",
            "work": work,
            "tmp": trial / "tmp",
            "agent_dir": None,
            "daemon_socket": None,
        }
        self.customize_trial(ctx)
        return ctx

    def customize_trial(self, ctx: dict):
        pass

    def env(self, ctx: dict) -> dict:
        return scrubbed_env({"HOME": str(ctx["home"]), "TMPDIR": str(ctx["tmp"])})

    def argv(self, ctx: dict, resume_fixture: str | None = None) -> list[str]:
        raise NotImplementedError

    def daemon_argv(self, ctx: dict) -> list[str] | None:
        return None

    def reap(self, ctx: dict):
        pass


class RustProduct(Product):
    name = "rust"
    has_daemon = True

    def version_info(self):
        v = subprocess.run([str(RUST_BIN), "--version"], capture_output=True, text=True, timeout=60)
        return {"version": v.stdout.strip() or v.stderr.strip(),
                "revision": "2017ac619e8cc83dd652704be072c4d7a22ff0aa",
                "binary": str(RUST_BIN)}

    def prepare_template(self, tpl: Path):
        agent = tpl / "agent"
        write_models_json(agent)
        prime = tpl / "home" / ".prime"
        prime.mkdir(parents=True, exist_ok=True)
        cfg = NODE_HOME_AUTH_PRIME / "config.json"
        if cfg.exists():
            shutil.copy(cfg, prime / "config.json")
        auth = NODE_HOME_AUTH_PRIME / "agent" / "auth.json"
        if auth.exists():
            agent.mkdir(parents=True, exist_ok=True)
            shutil.copy(auth, agent / "auth.json")

    def customize_trial(self, ctx: dict):
        ctx["agent_dir"] = ctx["trial_dir"] / "agent"
        shutil.copytree(self.template_dir() / "agent", ctx["agent_dir"])
        ctx["daemon_socket"] = ctx["trial_dir"] / "d.sock"
        write_models_json(ctx["agent_dir"])

    def env(self, ctx: dict) -> dict:
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
        extra.update(global_caches(self.name))
        return scrubbed_env(extra)

    def argv(self, ctx, resume_fixture=None):
        argv = [str(RUST_BIN), "--daemon-socket", str(ctx["daemon_socket"]),
                "--provider", "prime-inference", "--model", "mock-1", "--offline"]
        if resume_fixture:
            argv += ["--resume", resume_fixture]
        return argv

    def daemon_argv(self, ctx):
        return [str(RUST_BIN), "--mode", "daemon", "--daemon-socket", str(ctx["daemon_socket"])]

    def reap(self, ctx):
        leftovers = sweep_trial(ctx)
        if leftovers:
            raise RuntimeError(f"trial sweep leftovers: {leftovers[:3]}")


class TSProduct(RustProduct):
    name = "ts"

    def version_info(self):
        v = subprocess.run([str(TS_CLI), "--version"], capture_output=True, text=True, timeout=90)
        return {"version": v.stdout.strip() or v.stderr.strip(),
                "revision": "official-beta-0.9.5-beta.2043.1.acc5bc0",
                "binary": str(TS_CLI)}

    def argv(self, ctx, resume_fixture=None):
        argv = [str(TS_CLI), "--daemon-socket", str(ctx["daemon_socket"]),
                "--provider", "prime-inference", "--model", "mock-1", "--offline"]
        if resume_fixture:
            argv += ["--resume", resume_fixture]
        return argv

    def daemon_argv(self, ctx):
        return [str(TS_CLI), "--mode", "daemon", "--daemon-socket", str(ctx["daemon_socket"])]


class ClaudeProduct(Product):
    name = "claude"
    needs_prepass = True

    def version_info(self):
        v = subprocess.run([str(CLAUDE_BIN), "--version"], capture_output=True, text=True, timeout=60,
                           env=scrubbed_env({"HOME": str(HOME)}))
        return {"version": v.stdout.strip(), "revision": "npm@latest", "binary": str(CLAUDE_BIN)}

    def prepare_template(self, tpl: Path):
        src = HOME / ".claude"
        if src.exists():
            shutil.copytree(src, tpl / "home" / ".claude", dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("projects", "todos", "statsig", "shell-snapshots"))
        cj = HOME / ".claude.json"
        if cj.exists():
            data = json.loads(cj.read_text())
            data.pop("projects", None)
            (tpl / "home" / ".claude.json").write_text(json.dumps(data))

    def customize_trial(self, ctx):
        cj = ctx["home"] / ".claude.json"
        if cj.exists():
            data = json.loads(cj.read_text())
            data.setdefault("projects", {})[str(ctx["work"])] = {"hasTrustDialogAccepted": True}
            cj.write_text(json.dumps(data))

    def env(self, ctx):
        extra = {
            "HOME": str(ctx["home"]),
            "TMPDIR": str(ctx["tmp"]),
            "ANTHROPIC_API_KEY": "sk-bench-dummy-not-real",
            "ANTHROPIC_BASE_URL": MOCK_URL,
            "ANTHROPIC_AUTH_TOKEN": "sk-bench-dummy-not-real",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        }
        return scrubbed_env(extra)

    def argv(self, ctx, resume_fixture=None):
        return [str(CLAUDE_BIN)]


class CodexProduct(Product):
    name = "codex"
    needs_prepass = True

    def version_info(self):
        v = subprocess.run([str(CODEX_BIN), "--version"], capture_output=True, text=True, timeout=60)
        return {"version": v.stdout.strip(), "revision": "npm@latest", "binary": str(CODEX_BIN)}

    def prepare_template(self, tpl: Path):
        # real ChatGPT auth, verbatim (Kevin: codex msg_send may use the real
        # API under the $10 budget; codex 0.156 rejects chat wire_api, so no
        # mock provider override is installed)
        codex = tpl / "home" / ".codex"
        codex.mkdir(parents=True, exist_ok=True)
        src_auth = HOME / ".codex" / "auth.json"
        if src_auth.exists():
            shutil.copy(src_auth, codex / "auth.json")
        cfg = HOME / ".codex" / "config.toml"
        if cfg.exists():
            shutil.copy(cfg, codex / "config.toml")

    def env(self, ctx: dict) -> dict:
        extra = {
            "HOME": str(ctx["home"]),
            "TMPDIR": str(ctx["tmp"]),
        }
        return scrubbed_env(extra)

    def argv(self, ctx, resume_fixture=None):
        return [str(CODEX_BIN)]


class PiProduct(Product):
    name = "pi"

    def version_info(self):
        v = subprocess.run(["node", str(PI_CLI), "--version"], capture_output=True, text=True, timeout=90)
        pkg = json.loads((BENCH / "repos/pi-mono/packages/coding-agent/package.json").read_text())
        return {"version": v.stdout.strip() or pkg["version"],
                "revision": "b45597504eeaba1f11a9920a1d1048c361ed4b8e",
                "binary": f"node {PI_CLI}"}

    def prepare_template(self, tpl: Path):
        write_models_json(tpl / "agent", base_url=MOCK_URL + "/v1")
        auth = NODE_HOME_AUTH_PRIME / "agent" / "auth.json"
        if auth.exists():
            (tpl / "agent").mkdir(parents=True, exist_ok=True)
            shutil.copy(auth, tpl / "agent" / "auth.json")

    def customize_trial(self, ctx):
        ctx["agent_dir"] = ctx["home"] / ".pi" / "agent"
        ctx["agent_dir"].mkdir(parents=True, exist_ok=True)
        shutil.copytree(self.template_dir() / "agent", ctx["agent_dir"], dirs_exist_ok=True)

    def argv(self, ctx, resume_fixture=None):
        # provider/model flags select the models.json mock provider; the
        # copied auth.json keeps the product authenticated (no onboarding).
        return ["node", str(PI_CLI), "--provider", "prime-inference", "--model", "mock-1",
                "--no-extensions", "--no-skills", "--no-prompt-templates"]


def get_product(name: str) -> Product:
    return {"rust": RustProduct, "ts": TSProduct, "claude": ClaudeProduct,
            "codex": CodexProduct, "pi": PiProduct}[name]()


def daemon_pids_matching(needles) -> list:
    seen = []
    live = [n for n in needles if n]
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            argv = (proc / "cmdline").read_bytes().decode(errors="replace")
        except OSError:
            continue
        if "--mode" not in argv or "daemon" not in argv:
            continue
        if any(n in argv for n in live):
            seen.append(int(proc.name))
    return seen


def wire_shutdown(socket_path: str):
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect(socket_path)
        envelope = {"type": "command", "id": "sd", "protocol": {"name": "prime-agent.daemon", "version": 7},
                    "command": {"type": "shutdown"}}
        s.sendall((json.dumps(envelope) + "\n").encode())
        time.sleep(1.5)
        s.close()
    except Exception:
        pass


def reap_daemons(socket_paths, needles):
    import signal
    for sp in socket_paths:
        wire_shutdown(sp)
    for _ in range(3):
        pids = daemon_pids_matching(list(socket_paths) + list(needles))
        if not pids:
            return
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        time.sleep(1.0)
        for pid in daemon_pids_matching(list(socket_paths) + list(needles)):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        time.sleep(0.5)


PRODUCT_MARKERS = ("prime-agent", "dist/bundle/cli.js", "/usr/bin/claude", "/usr/bin/codex")


def pids_referencing(needles) -> list:
    """(pid, cmdline-head) for processes whose argv or cwd references any
    needle path. The trial dir is unique per trial, so this is exact."""
    seen = []
    live = [str(n) for n in needles if n]
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        pid = int(proc.name)
        if pid in (1, os.getpid()):
            continue
        try:
            argv = (proc / "cmdline").read_bytes().decode(errors="replace").replace(chr(0), " ")
        except OSError:
            continue
        try:
            cwd = os.readlink(proc / "cwd")
        except OSError:
            cwd = ""
        hit = any((n in argv) or (cwd and (cwd == n or cwd.startswith(n + "/"))) for n in live)
        if hit:
            seen.append((pid, argv[:110]))
    return seen


def sweep_trial(ctx) -> list:
    """Kill EVERY process belonging to this trial (TUI tree is already dead;
    this catches the daemon, its supervisor, detached workers, and kernels),
    with graceful wire shutdown first and SIGTERM->SIGKILL escalation until
    the table is clean. Returns the leftovers that survived (must be empty)."""
    import signal
    if ctx.get("daemon_socket"):
        wire_shutdown(str(ctx["daemon_socket"]))
    needles = [str(ctx["trial_dir"]), str(ctx["tmp"])]
    leftovers = []
    for attempt in range(4):
        leftovers = pids_referencing(needles)
        if not leftovers:
            return []
        sig = signal.SIGTERM if attempt < 2 else signal.SIGKILL
        for pid, _ in leftovers:
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass
        time.sleep(1.0 if attempt < 2 else 0.7)
    return pids_referencing(needles)


def product_marker_processes() -> list:
    """Any product process still alive anywhere (cross-trial safety net).
    Excludes the harness itself."""
    seen = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        pid = int(proc.name)
        if pid in (1, os.getpid()):
            continue
        try:
            argv = (proc / "cmdline").read_bytes().decode(errors="replace").replace(chr(0), " ")
        except OSError:
            continue
        if any(m in argv for m in PRODUCT_MARKERS) and "runner.py" not in argv and "explore.py" not in argv:
            seen.append((pid, argv[:110]))
    return seen


def rss_tree(pid: int) -> dict:
    import psutil
    try:
        root = psutil.Process(pid)
        procs = [root] + root.children(recursive=True)
    except psutil.Error:
        return {"rss_mb": 0.0, "pss_mb": None, "nproc": 0}
    rss = 0
    pss = 0
    pss_ok = True
    for p in procs:
        try:
            rss += p.memory_info().rss
        except psutil.Error:
            continue
        try:
            with open(f"/proc/{p.pid}/smaps_rollup") as f:
                for line in f:
                    if line.startswith("Pss:"):
                        pss += int(line.split()[1]) * 1024
                        break
        except OSError:
            pss_ok = False
    return {"rss_mb": round(rss / (1 << 20), 1), "pss_mb": round(pss / (1 << 20), 1) if pss_ok else None,
            "nproc": len(procs)}


def loadavg() -> float:
    with open("/proc/loadavg") as f:
        return float(f.read().split()[0])
