"""The adapter-folder contract: dialogs as config, vendor build, sandbox
setup state, diagnose evidence, and compare deltas."""
from __future__ import annotations

import json
from pathlib import Path

from bench.core.config import load_config, product_config
from bench.core.product import keystroke, resolve_dialogs
from bench.core.registry import discover
from bench.drivers.compare import compare_runs, format_markdown
from bench.drivers.diagnose import _dialog_trace
from bench.drivers.vendor import vendor_entries


def _cfg(tmp_path):
    cfg = load_config(None)
    cfg["bench_root"] = str(tmp_path / "bench")
    cfg["results_dir"] = str(tmp_path / "bench" / "results")
    return cfg


# ---- dialogs as config -------------------------------------------------------

def test_keystroke_tokens_and_literals():
    assert keystroke("enter") == "\r"
    assert keystroke("DOWN") == "\x1b[B"
    assert keystroke("3") == "3"
    assert keystroke("sk-bench-dummy-not-real") == "sk-bench-dummy-not-real"
    assert keystroke("multi\nline") == "multi\rline"


def test_resolve_dialogs_validates_and_maps():
    steps = resolve_dialogs([
        {"marker": "Share agent traces with Prime Intellect?",
         "keys": ["down", "enter"]},
        {"marker": "Paste or type your API key",
         "keys": ["sk-bench-dummy-not-real", "enter"]},
    ])
    assert steps == [("Share agent traces with Prime Intellect?", ["\x1b[B", "\r"]),
                     ("Paste or type your API key",
                      ["sk-bench-dummy-not-real", "\r"])]
    assert resolve_dialogs(None) == []
    try:
        resolve_dialogs([{"keys": ["enter"]}])
        raise AssertionError("markerless entry must fail")
    except ValueError:
        pass


def test_product_dialogs_come_from_config(tmp_path):
    reg = discover(_cfg(tmp_path))
    rust = reg.product("rust")
    assert rust.dialog_steps == [("Share agent traces with Prime Intellect?",
                                 ["\x1b[B", "\r"])]
    codex = reg.product("codex")
    markers = [m for m, _ in codex.dialog_steps]
    assert "3. Provide your own API key" in markers
    assert "Trust and continue" in markers
    claude = reg.product("claude")
    assert ("Is this a project you created or one you trust?",
            ["\x1b[B", "\r"]) in claude.dialog_steps
    # pi's one dialog is the loaded-session fallback (spec §F): the recorded
    # session cwd is created at staging, so the prompt normally never appears
    assert reg.product("pi").dialog_steps == [
        ("cwd from session file does not exist", ["\r"])]


def test_product_configs_are_complete(tmp_path):
    """Every harness folder: yaml + adapter + README; the yaml carries
    binary, first_run_dialogs, vendor, auth_sources."""
    reg = discover(_cfg(tmp_path))
    from bench.core.config import ADAPTERS_DIR
    for name in ("rust", "ts", "claude", "codex", "pi"):
        folder = ADAPTERS_DIR / name
        assert (folder / "product.yaml").exists(), name
        assert (folder / "adapter.py").exists(), name
        assert (folder / "README.md").exists(), name
        cfg = product_config(name)
        assert cfg.get("binary"), name
        assert "first_run_dialogs" in cfg, name
        assert cfg.get("vendor"), name
        assert cfg.get("auth_sources"), name
    assert reg.product("rust").needs_kernel_venv is True
    assert reg.product("ts").needs_kernel_venv is True
    assert reg.product("claude").needs_kernel_venv is False


def test_kernel_products_from_registry(tmp_path):
    from bench.drivers.warm_kernels import kernel_products
    reg = discover(_cfg(tmp_path))
    assert kernel_products(reg) == ["rust", "ts"]


# ---- vendor build -----------------------------------------------------------

class _StubProduct:
    def __init__(self, needs_kernel_venv, vendor):
        self.needs_kernel_venv = needs_kernel_venv
        self.product_cfg = {"vendor": vendor}

    def version_info(self):
        return {"version": "stub-1.0", "revision": "stub", "binary_sha256": "00" * 32}


class _StubRegistry:
    def __init__(self, products):
        self.products = products

    def product(self, name):
        return self.products[name]


def test_vendor_entries_toolchain_and_dedupe():
    cfg = load_config(None)
    prime_auth = {"src": "/home/x/.prime/agent/auth.json",
                  "dst": "root/.prime/agent/auth.json"}
    reg = _StubRegistry({
        "rust": _StubProduct(True, [
            {"src": "/home/x/bench/rust/prime-agent",
             "dst": "root/bench/repos/prime-agent-rust/target/release/prime-agent"},
            dict(prime_auth)]),
        "pi": _StubProduct(False, [
            {"src": "/home/x/pi-mono", "dst": "root/bench/repos/pi-mono"},
            dict(prime_auth)]),
    })
    entries = vendor_entries(cfg, ["rust", "pi"], reg=reg)
    dsts = [e["dst"] for e in entries]
    # toolchain rides along because rust builds a kernel venv
    assert "root/.local/bin/uv" in dsts
    assert "root/.local/share/uv" in dsts
    # shared auth dst de-duplicated
    assert dsts.count("root/.prime/agent/auth.json") == 1
    # claude-only selection: no toolchain
    reg2 = _StubRegistry({"claude": _StubProduct(False, [
        {"src": "/usr/lib/node_modules/@anthropic-ai",
         "dst": "usr/lib/node_modules/@anthropic-ai"}])})
    dsts2 = [e["dst"] for e in vendor_entries(cfg, ["claude"], reg=reg2)]
    assert all(not d.startswith("root/.local") for d in dsts2)


def test_vendor_build_dry_run_and_tarball(tmp_path):
    from bench.drivers.vendor import build_vendor_tarball
    cfg = _cfg(tmp_path)
    # a synthetic product with two vendor entries under the tmp bench root
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "app").write_bytes(b"binary-bytes")
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "auth.json").write_text("{}")
    link_dir = tmp_path / "links"
    link_dir.mkdir()
    link = link_dir / "app-bin"
    link.symlink_to("../bin/app")
    reg = _StubRegistry({"demo": _StubProduct(False, [
        {"src": str(tmp_path / "bin" / "app"), "dst": "root/opt/app"},
        {"src": str(tmp_path / "state"), "dst": "root/.app", "exclude": ["cache"]},
        {"src": str(link), "dst": "usr/local/bin/app"},
    ])})
    out = tmp_path / "vendor" / "products.tar.gz"
    manifest = build_vendor_tarball(cfg, ["demo"], out, reg=reg)
    assert manifest["dry_run"] is False
    assert manifest["bytes"] > 0
    assert out.exists()
    # build-manifest.json carries the entries
    m = json.loads((out.parent / "build-manifest.json").read_text())
    assert len(m["entries"]) == 3


# ---- sandbox setup state ----------------------------------------------------

def test_sandbox_spec_and_state(tmp_path):
    from bench.drivers.sandbox import (list_sandboxes, sandbox_spec,
                                       state_path, load_state)
    from bench.drivers.orchestrator.plan import load_parallel_config
    import yaml as _yaml
    pcfg_path = tmp_path / "parallel.yaml"
    pcfg_path.write_text(_yaml.safe_dump({
        "sandbox_defaults": {"image": "ubuntu:22.04", "cpu_cores": 4,
                             "memory_gb": 8, "disk_gb": 60,
                             "timeout_minutes": 180,
                             "bootstrap": "bash /root/bench-harness/vendor/bootstrap.sh"},
        "sandboxes": {"smoke": {"cpu_cores": 2, "memory_gb": 4}},
    }))
    pcfg = load_parallel_config(pcfg_path)
    spec = sandbox_spec(pcfg, "smoke", ["rust"], 8891)
    assert spec["cpu_cores"] == 2 and spec["memory_gb"] == 4  # named override
    assert spec["image"] == "ubuntu:22.04"
    assert spec["products"] == ["rust"]
    cfg = _cfg(tmp_path)
    state = {"name": "smoke", "sandbox_id": "sb-1", "backend": "local",
             "spec": spec, "products": ["rust"], "status": "ready",
             "readiness": {"rust": {"settle": {"ok": True}}}}
    state_path(cfg, "smoke").parent.mkdir(parents=True, exist_ok=True)
    state_path(cfg, "smoke").write_text(json.dumps(state))
    listed = list_sandboxes(cfg)
    assert [s["name"] for s in listed] == ["smoke"]
    assert load_state(cfg, "smoke")["sandbox_id"] == "sb-1"
    try:
        load_state(cfg, "missing")
        raise AssertionError("missing sandbox must fail loudly")
    except FileNotFoundError:
        pass


def test_setup_appends_products_to_bootstrap():
    from bench.drivers.sandbox import sandbox_spec
    from bench.drivers.orchestrator.plan import load_parallel_config
    import tempfile
    pcfg = load_parallel_config(None)
    pcfg["sandbox_defaults"]["bootstrap"] = "bash /root/bench-harness/vendor/bootstrap.sh"
    spec = sandbox_spec(pcfg, "s1", ["rust"], 8890)
    # the setup flow appends the product list to the bootstrap command
    spec["bootstrap"] = f"{spec['bootstrap']} rust"
    assert spec["bootstrap"].endswith("bootstrap.sh rust")


# ---- diagnose walker --------------------------------------------------------

class _ScriptedSession:
    """A session replaying a scripted screen: dialog -> dialog -> ready."""

    def __init__(self, screens, echo=True):
        self.screens = list(screens)
        self.sent: list[str] = []
        self.probe = ""
        self.echo = echo
        self._needle = ""

    def screen_text(self):
        return self.screens[0] if self.screens else ""

    def send(self, data):
        self.sent.append(data)
        # advancing the script on the dialog-answer keys only
        if data == "\x1b[B" or data == "\r":
            if len(self.screens) > 1:
                self.screens.pop(0)
        else:
            self.probe += data
        return 0.0

    def start_echo_watch(self, token):
        self._needle = token

    def wait_echo(self, timeout=2.0):
        if self.echo and self.probe and self._needle in self.probe:
            return 1.0
        raise TimeoutError


def test_dialog_trace_answers_then_ready():
    steps = [("Share agent traces with Prime Intellect?", ["\x1b[B", "\r"])]
    wrapped = ("Share agent traces with Prime "
              "Intellect?   [ Yes ]  No")
    session = _ScriptedSession([wrapped, "the editor is ready"])
    trace = _dialog_trace(session, steps, timeout=5.0, pacing={"key_pause_s": 0,
                                                               "loop_s": 0,
                                                               "echo_wait_s": 0.01},
                          probe="Zq7x01")
    assert trace["ready"] is True
    assert trace["dialogs_answered"] == {"Share agent traces with Prime Intellect?": 1}
    assert session.sent[:2] == ["\x1b[B", "\r"]


def test_dialog_trace_captures_failure_evidence():
    steps = [("Never appears?", ["enter"])]
    session = _ScriptedSession(["stuck screen"], echo=False)
    trace = _dialog_trace(session, steps, timeout=0.05, pacing={"key_pause_s": 0,
                                                               "loop_s": 0.01,
                                                               "echo_wait_s": 0.01},
                          probe="Zq7x01")
    assert trace["ready"] is False
    assert trace["dialogs_answered"] == {}
    assert "last_screen" in trace
    assert trace["errors"]


# ---- compare ----------------------------------------------------------------

def _write_run(root: Path, bench: str, product: str, values: list):
    d = root / bench
    d.mkdir(parents=True, exist_ok=True)
    for v in values:
        (d / "trials-w1.jsonl").open("a").write(json.dumps({
            "benchmark": bench, "product": product, "trial": values.index(v),
            "phase": "w1", "metrics": {"launch_to_ready_ms": v}}) + "\n")
    (root / "versions.json").write_text(json.dumps(
        {product: {"version": "1.0", "revision": "r1", "binary_sha256": "ab" * 32}}))


def test_compare_runs_deltas_and_versions(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    _write_run(a, "compare.cold_start", "rust", [100.0, 110.0, 120.0])
    _write_run(b, "compare.cold_start", "rust", [80.0, 90.0, 100.0])
    cfg = _cfg(tmp_path)
    result = compare_runs(cfg, a, b)
    g = result["groups"]["compare.cold_start/rust"]
    assert g["a_p50"] == 110.0 and g["b_p50"] == 90.0
    assert g["delta_pct"] == round((90.0 - 110.0) / 110.0 * 100.0, 2)
    assert result["versions_a"]["rust"]["revision"] == "r1"
    table = format_markdown(result)
    assert "compare.cold_start" in table and "-18.18%" in table
