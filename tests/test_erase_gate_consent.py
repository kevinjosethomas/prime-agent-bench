"""Consent-baseline gate tests (offline; no VM, no real product).

The gate's return-user consent contract: the trial home carries the
SEEDED baseline (the pinned settings.json — onboardingShown,
agentTraces.enabled=false, telemetry.noticeShown, verified from the
pinned TS acc5bc0 + Rust bdf82f4f sources — at both product-visible
locations) BEFORE any launch, NO pre-settle launch runs, and every
onboarding marker sighted during the gate flow is a BREACH that fails
the gate — the report-not-hack posture, never a vacuous pass. These
tests pin: a seeded home passes with zero breaches and exactly ONE
launch (the measured one); the two observed sheet timings on a
baseline-breaking product — the async sheet landing right after the
probe echo (caught at the next phase boundary) and the mid-burst sheet
(dialog-free at send, stolen mid-burst) — both fail on breach; a stale
template (no seed) fails loudly with the launch recorded as evidence;
non-baseline products keep the walk semantics (markers answered and
recorded, never gated); gate_pass rejects every consent-baseline
failure mode; and the real-PTY dialog walk still answers an ACTUAL
first-run sheet (the settle/prepass path for non-baseline products).
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
from bench.core.env import CONSENT_BASELINE_SETTINGS, write_consent_baseline

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
    """Stateful fake product. Probe tokens echo; the share-traces sheet
    steals focus while up (token input is DISCARDED — the run-3 TS
    shape). The sheet pops when no consent is persisted OR the product
    ignores its persisted baseline, in one of the two observed timings:
    ``async`` (pop_delay_s after the probe echo) or ``burst`` (on the
    first stress-burst token — dialog-free at send, stolen mid-burst).
    The product reads consent from its agent dir (the env pins
    PRIME_AGENT_CODING_AGENT_DIR there), falling back to the HOME
    default path — exactly the real products' resolution."""

    def __init__(self, home, ignores_baseline, launch_index, argv, env,
                 pop_mode="burst", pop_delay_s=0.0):
        self.home = Path(home)
        self.ignores_baseline = ignores_baseline
        self.launch_index = launch_index
        self.argv, self.env = argv, env
        self.pop_mode = pop_mode
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

    def agent_dir(self) -> Path:
        env_dir = self.env.get("PRIME_AGENT_CODING_AGENT_DIR")
        return Path(env_dir) if env_dir else self.home / ".prime" / "agent"

    def consent(self) -> bool:
        return (self.agent_dir() / "settings.json").exists()

    def sheet_due(self) -> bool:
        """The async timing: pop_delay_s AFTER the probe echo."""
        if self.pop_mode == "burst" or not self.echoed_once or self.sheet_up:
            return False
        if self.last_echo is None:
            return False
        if self.consent() and not self.ignores_baseline:
            return False
        return time.monotonic() - self.last_echo >= self.pop_delay_s

    def screen_text(self):
        if self.sheet_due():
            self.sheet_up = True
        if self.sheet_up:
            return MARKER + "\n> Share\n  Not now"
        return "Prime Agent fake editor|" + self.buffer

    def echo_window_text(self, rows_up=0, rows_down=0):
        return self.screen_text()

    def send(self, key):
        if key.startswith("\x1b"):
            return
        if key == "\r":
            self.sheet_up = False
            return
        # the burst timing: the sheet pops on the first stress-burst token
        # when the baseline does not hold (dialog-free at send, stolen
        # mid-burst)
        if (self.pop_mode == "burst" and not self.sheet_up
                and (not self.consent() or self.ignores_baseline)
                and key.startswith("Zq7z") and "Zq7z" not in self.buffer):
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
        # the probe echo IS the editor accepting input (the real probe
        # waits for exactly this render)
        self.echoed_once = True
        self.last_echo = time.monotonic()
        if not self.sheet_up:
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
    """Fake adapter with the real rust/ts adapter surface (template/
    trial/launch + seeds_consent_baseline)."""

    name = "fake"
    has_daemon = False
    seeds_consent_baseline = True
    dialog_steps = [(MARKER, ["\x1b[B", "\r"])]

    def __init__(self, template=None, ignores_baseline=False,
                 seed_baseline=True, pop_mode="burst", pop_delay_s=0.0):
        self.template = template
        self.ignores_baseline = ignores_baseline
        self.seed_baseline = seed_baseline
        self.pop_mode = pop_mode
        self.pop_delay_s = pop_delay_s
        self.launches = []

    def template_dir(self):
        return self.template

    def prepare_template(self, tpl):
        # mirrors the real rust/ts adapter template layout exactly:
        # agent/ with mock models.json + the seeded consent baseline at
        # both product-visible locations; home/.prime/ (the authless VM
        # ships no real config — the dummy key rides in the env)
        tpl.mkdir(parents=True, exist_ok=True)
        (tpl / "home" / ".prime").mkdir(parents=True, exist_ok=True)
        (tpl / "agent").mkdir(exist_ok=True)
        (tpl / "agent" / "models.json").write_text('{"mock": true}')
        if self.seed_baseline:
            write_consent_baseline(tpl / "agent")
            write_consent_baseline(tpl / "home" / ".prime" / "agent")

    def new_trial(self, trial):
        # mirrors the fixed ProductAdapter.new_trial: <template>/home is
        # the trial home's content; <template>/agent is the agent dir
        trial.mkdir(parents=True, exist_ok=True)
        shutil.copytree(self.template / "home", trial / "home", symlinks=True)
        agent_dir = trial / "agent"
        shutil.copytree(self.template / "agent", agent_dir)
        (trial / "work").mkdir(exist_ok=True)
        (trial / "tmp").mkdir(exist_ok=True)
        return {"trial_dir": trial, "home": trial / "home",
                "work": trial / "work", "tmp": trial / "tmp",
                "agent_dir": agent_dir, "daemon_socket": None}

    def env(self, ctx):
        return {"HOME": str(ctx["home"]),
                "PRIME_AGENT_CODING_AGENT_DIR": str(ctx["agent_dir"])}

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
        app = FakeApp(env["HOME"], self.prod.ignores_baseline, len(self.apps),
                      argv, dict(env), pop_mode=self.prod.pop_mode,
                      pop_delay_s=self.prod.pop_delay_s)
        self.prod.launches.append((argv, dict(env)))
        self.apps.append(app)
        return app


class FakeReg:
    def __init__(self, prod):
        self.prod = prod

    def product(self, name):
        return self.prod


def test_drive_to_ready_answers_first_run_sheet(gate):
    """The product-owned walk (settle/prepass for NON-baseline products)
    answers an ACTUAL first-run sheet on a real PTY: the onboarding
    marker pops, the walk matches it, and reaches echo-ready."""
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


def _run_gate(gate, tmp_path, **prod_kwargs):
    prod = FakeProd(template=tmp_path / "template", **prod_kwargs)
    driver = FakeDriver(prod)
    root = tmp_path / "gate-root"
    root.mkdir(parents=True, exist_ok=True)
    mock_log = str(tmp_path / "mock.requests.jsonl")  # absent -> 0
    return gate.verify_product("fake", FakeReg(prod), driver,
                               mock_log, root), prod, driver


def test_seeded_home_one_launch_sheet_free_pass(gate, tmp_path):
    """The seeded baseline is the whole mechanism: ONE launch (the measured
    one — no pre-settle process), zero breaches, and the gate passes."""
    evidence, prod, driver = _run_gate(gate, tmp_path)
    assert "pre_settle" not in evidence                # no pre-settle launch
    assert len(driver.apps) == 1                      # the measured launch only
    cb = evidence["consent_baseline"]
    assert cb["seed"] == {"agent_dir": True, "home_default": True}
    assert cb["breaches"] == []
    assert "stale_template" not in cb
    assert evidence["pass"] is True
    assert evidence["stress_focus_verified"] is True
    assert evidence["stress_cohort_rendered_count"] == 66
    # the trial home carries the pinned REAL shape (never traces:not-now)
    settings = json.loads((Path(prod.launches[0][1]["PRIME_AGENT_CODING_AGENT_DIR"])
                            / "settings.json").read_text())
    assert settings == CONSENT_BASELINE_SETTINGS
    # the authless flow ships no trial config.json (the dummy key rides in
    # the env), and nothing was ever submitted
    assert not (Path(driver.apps[0].home) / ".prime" / "config.json").exists()
    assert evidence["mock_model_requests"] == 0


def test_midburst_sheet_despite_seed_fails_on_breach(gate, tmp_path):
    """The run-3 shape: the sheet is dialog-free at send time and steals
    focus mid-burst. Despite the seed being present and read, the
    sighting is a breach — recorded, sentinel unwitnessed, gate FAILED.
    Never a vacuous pass."""
    evidence, prod, driver = _run_gate(gate, tmp_path,
                                        ignores_baseline=True,
                                        pop_mode="burst")
    assert evidence["consent_baseline"]["breaches"] == [MARKER]
    assert evidence["consent_baseline"]["seed"]["agent_dir"] is True
    assert evidence["stress_focus_verified"] is False
    assert evidence["stress_cohort_rendered_count"] == 0
    assert evidence["pass"] is False


def test_async_post_echo_sheet_is_caught_at_next_boundary(gate, tmp_path):
    """The async timing: the sheet lands right after the probe echo (the
    observed TS share-traces shape, seconds in). The next phase boundary
    must witness the marker, answer it, and record the breach."""
    evidence, prod, driver = _run_gate(gate, tmp_path,
                                        ignores_baseline=True,
                                        pop_mode="async", pop_delay_s=0.0)
    cb = evidence["consent_baseline"]
    assert cb["breaches"] == [MARKER]
    assert cb["seed"]["agent_dir"] is True
    assert evidence["pass"] is False


def test_stale_template_fails_loudly(gate, tmp_path):
    """A template without the seed (built before the baseline landed) is
    a stale template: the seed check fails pre-launch, the sheet pops
    (nothing settled it), and the gate fails — never a first-run walk
    masquerading as a settled home."""
    evidence, prod, driver = _run_gate(gate, tmp_path, seed_baseline=False)
    cb = evidence["consent_baseline"]
    assert cb["seed"] == {"agent_dir": False, "home_default": False}
    assert cb["stale_template"] is True
    assert cb["breaches"] == [MARKER]
    assert evidence["pass"] is False


def test_non_baseline_product_keeps_walk_semantics(gate, tmp_path):
    """Products without a seedable baseline (claude/codex/pi shape) keep
    the walk semantics: their first-run sheet is answered (dialog
    dismissals recorded), no consent_baseline evidence exists, and the
    verdict comes from the other witnesses — a stolen-focus burst still
    fails the gate, but never as a "breach"."""
    prod = FakeProd(template=tmp_path / "template", seed_baseline=False)
    prod.seeds_consent_baseline = False      # walk-semantics product
    driver = FakeDriver(prod)
    root = tmp_path / "gate-root"
    root.mkdir(parents=True, exist_ok=True)
    evidence = gate.verify_product("fake", FakeReg(prod), driver,
                                   str(tmp_path / "mock.requests.jsonl"),
                                   root)
    assert "consent_baseline" not in evidence
    assert evidence["dialog_dismissals"]      # the walk answered the sheet
    assert evidence["stress_focus_verified"] is False
    assert evidence["pass"] is False          # focus was stolen mid-burst


def test_gate_pass_requires_clean_consent_baseline(gate):
    """gate_pass: a present consent_baseline block must be seeded at BOTH
    locations with an EMPTY breach ledger; each failure mode alone fails
    the verdict."""
    def evidence(seed, breaches):
        return {
            "probe_witnessed": True, "erase_ok": True, "leftover_tokens": [],
            "post_erase_window_nonempty": True, "alive_after_erase": True,
            "fresh_echo_ok": True, "fresh_erase_ok": True,
            "mock_model_requests": 0, "stress": {"erase_ok": True},
            "stress_dialog_free": True, "stress_focus_verified": True,
            "consent_baseline": {"seed": seed, "breaches": breaches},
        }
    ok = evidence({"agent_dir": True, "home_default": True}, [])
    assert gate.gate_pass(ok) is True
    assert gate.gate_pass(evidence({"agent_dir": False,
                                    "home_default": True}, [])) is False
    assert gate.gate_pass(evidence({"agent_dir": True,
                                    "home_default": False}, [])) is False
    assert gate.gate_pass(evidence({"agent_dir": True,
                                    "home_default": True},
                                   [MARKER])) is False
