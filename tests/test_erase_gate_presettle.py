"""Pre-settle verification tests (offline; no VM, no real product).

The gate's verification-only pre-settle: ONE isolated launch on the trial
home walks the product-owned first-run dialogs to ready, then drains any
sheet that pops after ready (the observed share-traces sheet lands after
the probe echo), answering it with the product's own keys. The measured
launch that follows runs against the settled home. These tests pin:
the walk answers an ACTUAL first-run sheet on a real PTY; the settle
launch persists consent (product-owned) and the measured launch is
sheet-free on the same home; both launches are isolated (offline argv +
dummy key); and if the product does NOT persist consent, the measured
launch pops the sheet mid-burst and the gate FAILS on focus — the
report-not-hack posture, never a vacuous pass.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import threading
import time
from pathlib import Path

import pytest

from bench.adapters.benchmarks.support import drive_to_ready
from bench.adapters.terminals.pty import PTYDriver

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_erase_pty.py"
TUI = str(Path(__file__).parent / "mini_tui.py")
MARKER = "Share agent traces with Prime Intellect?"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("verify_erase_pty", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeApp:
    """Stateful fake product: probe echoes; the share-traces sheet pops
    AFTER the first echo when no consent is persisted; answering it
    persists consent when the product does; while the sheet is up, token
    input is DISCARDED (focus stolen — the run-3 TS shape)."""

    def __init__(self, home, persist, launch_index, argv, env,
                 pop_delay_s=0.0):
        self.home = Path(home)
        self.persist = persist
        self.launch_index = launch_index
        self.argv, self.env = argv, env
        self.pop_delay_s = pop_delay_s
        self.sheet_up = False
        self.buffer = ""
        self.echoed_once = False
        self.last_echo = None
        self.alive_flag = True
        self.t_first_paint = 1.0
        self._lock = threading.Lock()
        self.raw = bytearray(b"fake-pty-stream")
        self.trimmed = 0

    def consent(self) -> bool:
        return (self.home / ".prime" / "agent" / "settings.json").exists()

    def maybe_pop(self):
        """The observed async shape: the sheet pops pop_delay_s AFTER the
        first echo when no consent is persisted."""
        if (not self.echoed_once or self.sheet_up or self.consent()
                or self.last_echo is None):
            return
        if time.monotonic() - self.last_echo >= self.pop_delay_s:
            self.sheet_up = True

    def screen_text(self):
        self.maybe_pop()
        if self.sheet_up:
            return MARKER + "\n> Share\n  Not now"
        return "Prime Agent fake editor|" + self.buffer

    def echo_window_text(self, rows_up=0, rows_down=0):
        return self.screen_text()

    def send(self, key):
        if key.startswith("\x1b"):
            return
        if key == "\r":
            if self.sheet_up:
                if self.persist:
                    path = self.home / ".prime" / "agent" / "settings.json"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps({"traces": "not-now"}))
                self.sheet_up = False
            return
        # token input: the async sheet pops on the first stress burst token
        # when no consent exists (dialog-free at send, stolen mid-burst)
        if (self.launch_index == 1 and not self.consent()
                and key.startswith("Zq7z") and not self.sheet_up
                and "Zq7z" not in self.buffer):
            self.sheet_up = True
            return
        if self.sheet_up:
            return  # focus stolen: input discarded
        self.buffer += key

    def start_echo_watch(self, token):
        pass

    def wait_echo(self, timeout):
        self.echoed_once = True
        self.last_echo = time.monotonic()
        return

    def wait_for(self, pred, timeout=0, poll=0):
        if pred():
            return time.monotonic(), True
        raise TimeoutError("not rendered")

    def probe_input_ready(self, token, **kwargs):
        if not self.sheet_up:  # the editor accepts and renders the probe
            self.buffer += token
        return {
            "sends": 1, "unconfirmed_attempts": 0, "dropped_probes": None,
            "input_buffered": False, "chars_sent": len(token),
            "echo_ts_offset_ms": 1.0, "dialogs": [], "probe_tokens": [token],
        }

    def erase_all(self, needles, max_backspaces=0, timeout=0):
        for n in (needles if isinstance(needles, list) else [needles]):
            self.buffer = self.buffer.replace(n, "")
        return True, 1.0

    def alive(self):
        return self.alive_flag

    def kill_tree(self):
        self.alive_flag = False

    def bytes_out(self):
        return len(self.raw)


class FakeProd:
    """Fake adapter with the real adapter's surface (template/trial/launch)."""

    name = "fake"
    has_daemon = False
    dialog_steps = [(MARKER, ["\x1b[B", "\r"])]

    def __init__(self, persist=True, template=None, pop_delay_s=0.0):
        self.persist = persist
        self.template = template
        self.pop_delay_s = pop_delay_s
        self.launches = []

    def template_dir(self):
        return self.template

    def prepare_template(self, tpl):
        # mirrors the real rust/ts adapter template layout exactly:
        # agent/ with mock models.json + home/.prime/ (the authless VM
        # ships no real config — the dummy key rides in the env)
        tpl.mkdir(parents=True, exist_ok=True)
        (tpl / "home" / ".prime").mkdir(parents=True, exist_ok=True)
        (tpl / "agent").mkdir(exist_ok=True)
        (tpl / "agent" / "models.json").write_text('{"mock": true}')

    def new_trial(self, trial):
        trial.mkdir(parents=True, exist_ok=True)
        shutil.copytree(self.template, trial / "home", symlinks=True)
        (trial / "work").mkdir(exist_ok=True)
        (trial / "tmp").mkdir(exist_ok=True)
        return {"trial_dir": trial, "home": trial / "home",
                "work": trial / "work", "tmp": trial / "tmp",
                "daemon_socket": None}

    def env(self, ctx):
        return {"HOME": str(ctx["home"])}

    def argv(self, ctx):
        return ["/fake/prime-agent", "--provider", "prime-inference",
                "--model", "mock-1", "--offline"]

    def version_info(self):
        return {"version": "fake"}

    def reap(self, ctx):
        pass


class FakeDriver:
    def __init__(self, prod):
        self.prod = prod
        self.apps = []

    def start_session(self, argv, env=None, cwd=None, cols=120, rows=40):
        app = FakeApp(env["HOME"], self.prod.persist, len(self.apps),
                      argv, dict(env), pop_delay_s=self.prod.pop_delay_s)
        self.prod.launches.append((argv, dict(env)))
        self.apps.append(app)
        return app


class FakeReg:
    def __init__(self, prod):
        self.prod = prod

    def product(self, name):
        return self.prod


def test_drive_to_ready_answers_first_run_sheet(gate):
    """The product-owned walk answers an ACTUAL first-run sheet on a real
    PTY: the onboarding marker pops, the walk matches it, and reaches
    echo-ready."""
    driver = PTYDriver({})
    app = driver.start_session([sys.executable, TUI, "dialog", "1.5"])
    try:
        result = drive_to_ready(
            app, [(MARKER, ["\x1b[B", "\r"])], timeout=10.0,
            probe="Zq7prep01",
            pacing={"key_pause_s": 0.05, "loop_s": 0.2, "echo_wait_s": 1.0})
        assert result == "ready"
    finally:
        app.kill_tree()


def _run_gate(gate, tmp_path, persist, pop_delay_s=0.0):
    prod = FakeProd(persist=persist,
                    template=tmp_path / "template",
                    pop_delay_s=pop_delay_s)
    driver = FakeDriver(prod)
    root = tmp_path / "gate-root"
    root.mkdir(parents=True, exist_ok=True)
    mock_log = str(tmp_path / "mock.requests.jsonl")  # absent -> 0
    return gate.verify_product("fake", FakeReg(prod), driver,
                               mock_log, root), prod, driver


def test_settle_persists_consent_and_measured_launch_is_sheet_free(gate, tmp_path):
    evidence, prod, driver = _run_gate(gate, tmp_path, persist=True)
    assert evidence["pre_settle"]["ready"] == "ready"
    assert evidence["pre_settle"]["post_ready_answers"] == 1
    assert len(driver.apps) == 2                      # settle + measured
    assert evidence["pass"] is True
    # both launches: same settled home, isolated argv + dummy key
    homes = {Path(env["HOME"]) for _, env in prod.launches}
    assert len(homes) == 1
    for argv, env in prod.launches:
        assert "--offline" in argv and "mock-1" in argv
        assert env["PRIME_API_KEY"] == gate.DUMMY_KEY
    home = Path(next(iter(homes)))
    # consent persisted BY THE SETTLE LAUNCH (product-owned), seen by the
    # measured launch: no sheet ever during the measured flow
    consent = home / ".prime" / "agent" / "settings.json"
    assert consent.exists()
    assert driver.apps[1].sheet_up is False
    assert evidence["stress_focus_verified"] is True
    assert evidence["stress_cohort_rendered_count"] == 66
    # the authless flow ships no trial config.json (matching the real
    # auth-less VM) — the dummy key rides in the env on BOTH launches,
    # asserted above; and nothing was ever submitted
    assert not (home / ".prime" / "config.json").exists()
    assert evidence["mock_model_requests"] == 0


def test_delayed_sheet_is_caught_by_stable_window(gate, tmp_path):
    """Regression guard for the premature-exit flaw: the async sheet pops
    >2s AFTER ready (the old early-quiet logic exited at 2s and missed it —
    the exact run-3 failure). The stable window must still be observing,
    witness the marker, answer it with the product's keys, and persist
    consent so the measured launch is sheet-free."""
    evidence, prod, driver = _run_gate(gate, tmp_path, persist=True,
                                        pop_delay_s=3.0)   # > 2s old-quiet exit
    assert evidence["pre_settle"]["post_ready_answers"] == 1
    assert evidence["pre_settle"]["window_s"] >= 6.0     # stable window held
    assert evidence["pass"] is True
    home = Path(prod.launches[1][1]["HOME"])
    assert (home / ".prime" / "agent" / "settings.json").exists()
    assert driver.apps[1].sheet_up is False              # measured: clean
    assert evidence["stress_focus_verified"] is True


def test_no_persist_consent_gate_refuses_vacuous_pass(gate, tmp_path):
    """Report-not-hack posture: if answering the sheet does NOT persist
    consent, the settle cannot pre-complete onboarding — the measured
    launch pops the sheet mid-burst (dialog-free at send), input is
    swallowed, and the gate FAILS on focus. Never a vacuous pass."""
    evidence, prod, driver = _run_gate(gate, tmp_path, persist=False)
    assert evidence["pre_settle"]["ready"] == "ready"   # walk + drain ran
    # no persistence -> the sheet RE-POPPED inside the stable window and
    # the drain answered it repeatedly until the bounded cap — the honest
    # signature of a product that does not persist consent
    assert evidence["pre_settle"]["post_ready_answers"] >= 2
    assert evidence["pre_settle"]["window_s"] >= 6.0
    home = Path(prod.launches[1][1]["HOME"])
    assert not (home / ".prime" / "agent" / "settings.json").exists()
    assert evidence["stress_dialog_free"] is True      # true AT send time
    assert evidence["stress_focus_verified"] is False  # sheet stole focus
    assert evidence["stress_cohort_rendered_count"] == 0
    assert evidence["pass"] is False
