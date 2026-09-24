"""session.agent_view_roundtrip scenario correctness: leg boundaries,
partial-measurement honesty (chrome without the roster row never ranks;
a stale tail or a co-rendered view chrome never validates), same-session
proof (row identity + replaced screen + tail + fresh echo), registry
discovery, and the keystroke translation the key knobs rely on.

No product is launched and no inference runs: the scenario drives fake
sessions through the real Benchmark/Session ABCs.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bench.adapters.benchmarks.agent_view_roundtrip import (
    AGENTS_CHROME, SessionAgentViewRoundtrip, _first_user_text)
from bench.adapters.fixtures.session_size import SENTINEL
from bench.core.config import load_config
from bench.core.harness import HarnessDriver, Session, now
from bench.core.product import ProductAdapter, TrialContext, keystroke
from bench.core.registry import discover

LEFT, RIGHT = "\x1b[D", "\x1b[C"
FIRST_USER = "please do task number 0"
FAST_LEGS = {"session.agent_view_roundtrip": {"agents_view_timeout_s": 0.05,
                                              "return_timeout_s": 0.05}}


def _cfg(tmp_path, benchmark_overrides=None):
    cfg = load_config(None)
    cfg["bench_root"] = str(tmp_path / "bench")
    cfg["results_dir"] = str(tmp_path / "bench" / "results")
    cfg["benchmarks"] = benchmark_overrides or {}
    return cfg


class NavSession(Session):
    """The scripted roundtrip: the chat screen (tail sentinel), LEFT ->
    the agents view (chrome + the resumed session's roster row), RIGHT ->
    the same chat screen again. Flags degrade single legs.

    stale_chat: LEFT swaps in the view but the old tail stays on screen
    (the view never replaced the chat). keeps_chrome: RIGHT brings the
    tail back but the view chrome co-renders (the echo could come from
    the view's search field)."""

    def __init__(self, row_title=FIRST_USER, open_view=True, returns=True,
                 stale_chat=False, keeps_chrome=False,
                 editor_rows=(), editor_clearable=True,
                 dialog_marker=None, dialog_dismissible=True,
                 prompt_visible=True):
        self.t_spawn = now()
        self.t_first_paint = now()
        self.pid = None
        self.row_title = row_title
        self.open_view = open_view
        self.returns = returns
        self.stale_chat = stale_chat
        self.keeps_chrome = keeps_chrome
        # pre-nav gate surfaces: typed text on the editor prompt row and
        # a first-run dialog overlay, each with its own dismiss behavior
        self.editor_rows = list(editor_rows)
        self.editor_clearable = editor_clearable
        self.dialog_marker = dialog_marker
        self.dialog_dismissible = dialog_dismissible
        self.prompt_visible = prompt_visible
        self._dialog_down_seen = False
        self.sends: list[str] = []
        self.screen = self._chat_screen()

    def _chat_screen(self):
        # the chat dock the real products render: transcript, then the
        # editor prompt row (bare when nothing is typed, dirty when
        # fragments sit on it), then any first-run dialog overlay
        rows = ["chat", SENTINEL]
        rows.extend(self.editor_rows if self.editor_rows else [" >"])
        if not self.prompt_visible:
            rows = [r for r in rows if not r.lstrip().startswith(">")]
        if self.dialog_marker:
            rows.append(self.dialog_marker)
        return rows

    def send(self, data):
        self.sends.append(data)
        if self.dialog_marker and data == "\x1b[B":
            self._dialog_down_seen = True
        elif (self.dialog_marker and self.dialog_dismissible
              and data == "\r" and self._dialog_down_seen):
            self.dialog_marker = None
            self.screen = self._chat_screen()
        elif data == "\x7f" and self.editor_rows and self.editor_clearable:
            # erase_all's backspaces trim the typed text char by char
            last = self.editor_rows[-1].rstrip()
            if len(last.rstrip(">").rstrip()) <= 1:
                self.editor_rows = []
            else:
                self.editor_rows[-1] = last[:-1]
            self.screen = self._chat_screen()
        elif data == "\x15" and self.editor_rows and self.editor_clearable:
            self.editor_rows = []
            self.screen = self._chat_screen()
        elif data == LEFT and self.open_view:
            view = ["chat", AGENTS_CHROME, self.row_title]
            if self.stale_chat:
                view.append(SENTINEL)
            self.screen = view
        elif data == RIGHT and self.returns:
            chat = ["chat", SENTINEL]
            if self.keeps_chrome:
                chat.append(AGENTS_CHROME)
            self.screen = chat
        return now()

    def screen_text(self):
        return "\n".join(self.screen)

    def alive(self):
        return True

    def kill_tree(self, sig=None):
        self.screen = ["dead"]

    def start_echo_watch(self, token):
        pass

    def wait_echo(self, timeout=2.0):
        return now()

    def probe_input_ready(self, token="Zq7x", retry_every=0.5,
                          timeout=45.0, start_ts=None, dialog_steps=()):
        return {"gap_ms": 3.0, "echo_ts_offset_ms": 30.0, "sends": 1,
                "dropped_probes": 0, "chars_sent": 5, "probe_token": f"{token}01"}


class FakeDriver(HarnessDriver):
    name = "fake"

    def __init__(self, session):
        self.session = session

    def start_session(self, argv, env=None, cwd=None, cols=120, rows=40):
        return self.session


class FakeProduct(ProductAdapter):
    """A product that never launches: the driver fakes the session."""

    name = "fake"
    resume_fixture_capable = True

    def __init__(self, cfg, session):
        super().__init__(cfg)
        self.session = session

    def version_info(self):
        return {"version": "fake"}

    def prepare_template(self, tpl):
        pass

    def new_trial(self, trial: Path) -> TrialContext:
        trial.mkdir(parents=True, exist_ok=True)
        ctx: TrialContext = {"trial_dir": trial, "home": trial / "home",
                             "work": trial / "work", "tmp": trial / "tmp",
                             "agent_dir": None, "daemon_socket": None}
        return ctx

    def launch(self, ctx, driver, resume_fixture=None):
        self.last_resume_fixture = resume_fixture
        return self.session

    def argv(self, ctx, resume_fixture=None):
        return ["fake"]

    def reap(self, ctx):
        pass


def _ctx(tmp_path):
    trial = tmp_path / "trial"
    trial.mkdir(parents=True, exist_ok=True)
    ctx: TrialContext = {"trial_dir": trial, "home": trial / "home",
                         "work": trial / "work", "tmp": trial / "tmp",
                         "agent_dir": None, "daemon_socket": None}
    for key in ("home", "work", "tmp"):
        ctx[key].mkdir(parents=True, exist_ok=True)
    return ctx


def _record():
    return {"benchmark": "x", "product": "fake", "phase": "w1"}


def _nav_keys(session):
    """The navigation keys only (erase_all legitimately sends \x7f first)."""
    return [s for s in session.sends if s in (LEFT, RIGHT)]


def _fixture(tmp_path, rows=None):
    """A minimal session JSONL: the row-title source is the first user
    message (the corpus fixture shape)."""
    if rows is None:
        rows = [
            {"type": "session", "id": "scale-corpus", "version": 3,
             "cwd": str(tmp_path), "rlmDepth": 0},
            {"type": "custom_message", "customType": "harness_digest",
             "content": "[harness-digest] base note"},
            {"type": "message", "id": "0001", "parentId": None,
             "message": {"role": "user",
                         "content": [{"type": "text", "text": FIRST_USER}]}},
        ]
    path = tmp_path / "fixture.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return path


def _measure(tmp_path, session, monkeypatch, fixture=None,
             benchmark_overrides=None, product_dialog_steps=None):
    from bench.adapters.benchmarks import agent_view_roundtrip as mod
    monkeypatch.setattr(mod, "rss_tree", lambda pid: {"rss_mb": 1.0})
    monkeypatch.setattr(mod, "loadavg", lambda: 0.0)
    bench = SessionAgentViewRoundtrip(_cfg(tmp_path, benchmark_overrides))
    product = FakeProduct({"layout": None, "product": {}, "mock": {}}, session)
    if product_dialog_steps is not None:
        product.dialog_steps = product_dialog_steps
    record = _record()
    bench.measure(product, _ctx(tmp_path), record, FakeDriver(session),
                  fixture=fixture or _fixture(tmp_path))
    return bench, product, record


# ---- the roundtrip: legs measured, boundaries explicit ----------------------

def test_roundtrip_measures_each_leg_and_validates(tmp_path, monkeypatch):
    session = NavSession()
    bench, product, record = _measure(tmp_path, session, monkeypatch)
    # the fixture resumed through the product argv (1 active session)
    assert product.last_resume_fixture.endswith("fixture.jsonl")
    # parity key combo: LEFT opens the view, RIGHT reopens the session
    assert _nav_keys(session) == [LEFT, RIGHT]
    m = record["metrics"]
    assert m["chat_to_agents_ms"] is not None
    assert m["agents_to_tail_ms"] is not None
    assert m["chat_ready_after_ms"] is not None
    assert m["roundtrip_ok"] is True
    assert record["validation"] == {
        "sentinel_loaded": True, "erased_before_nav": True,
        "dialogs_clear": True, "line_cleared": True,
        "agents_chrome": True, "roster_row": True,
        "sentinel_gone": True, "tail_after": True,
        "chrome_gone_after": True, "echoed_after": True}
    assert bench.validate(record) is True


# ---- pre-nav gate: dialog dismissed, editor line truly empty -------------

TRACE_DIALOG = "Share agent traces with Prime Intellect?"
TRACE_STEPS = [(TRACE_DIALOG, ["down", "enter"])]


def test_first_run_dialog_is_answered_before_navigation(tmp_path, monkeypatch):
    # a dialog that surfaces after the probe is answered with the
    # product's own dialog keys, then the roundtrip proceeds
    session = NavSession(dialog_marker=TRACE_DIALOG)
    bench, _, record = _measure(tmp_path, session, monkeypatch,
                                product_dialog_steps=TRACE_STEPS)
    assert "\x1b[B" in session.sends and "\r" in session.sends
    assert _nav_keys(session) == [LEFT, RIGHT]
    assert record["validation"]["dialogs_clear"] is True
    assert record["validation"]["line_cleared"] is True
    assert bench.validate(record) is True


def test_undismissable_dialog_is_partial_not_rankable(tmp_path, monkeypatch):
    # the dialog never leaves: the nav keys are never sent (they would
    # be consumed by the dialog), the row stays a partial invalid row
    session = NavSession(dialog_marker=TRACE_DIALOG, dialog_dismissible=False)
    bench, _, record = _measure(tmp_path, session, monkeypatch,
                                product_dialog_steps=TRACE_STEPS)
    assert _nav_keys(session) == []
    assert record["metrics"]["chat_to_agents_ms"] is None
    assert record["validation"]["dialogs_clear"] is False
    assert bench.validate(record) is False


def test_probe_residue_on_editor_line_is_cleared_before_left(tmp_path, monkeypatch):
    # buffered probe fragments sit ON the prompt row: ctrl+u clears the
    # whole line, the bare prompt gates, and the roundtrip proceeds
    session = NavSession(editor_rows=[" >  Zq7x01Zq7x02Zq7x03"])
    bench, _, record = _measure(tmp_path, session, monkeypatch)
    assert session.sends.count("\x15") >= 1  # ctrl+u: delete to line start
    assert _nav_keys(session) == [LEFT, RIGHT]
    assert record["validation"]["line_cleared"] is True
    assert bench.validate(record) is True


def test_unclearable_editor_line_is_partial_not_rankable(tmp_path, monkeypatch):
    # the editor row keeps its text: LEFT would be an editor cursor move,
    # so the nav never starts and the row stays unrankable
    session = NavSession(editor_rows=[" >  Zq7x01Zq7x02Zq7x03"],
                         editor_clearable=False)
    bench, _, record = _measure(tmp_path, session, monkeypatch)
    assert _nav_keys(session) == []
    assert record["metrics"]["chat_to_agents_ms"] is None
    # ctrl+u was a no-op and the residue is retained: neither the
    # needle-based erase nor the verified-clean recomputation certifies
    assert record["validation"]["erased_before_nav"] is False
    assert record["validation"]["line_cleared"] is False
    assert bench.validate(record) is False


def test_no_prompt_row_is_ambiguous_never_a_clean_editor(tmp_path, monkeypatch):
    # a screen with no editor prompt row in the dock (a dialog, the
    # roster, a splash) is NOT a vacuous pass: the gate stops, sends no
    # ctrl+u into the unknown surface, and the row stays unrankable
    session = NavSession(prompt_visible=False)
    bench, _, record = _measure(tmp_path, session, monkeypatch)
    assert session.sends.count("\x15") == 0  # no keys into an unknown surface
    assert _nav_keys(session) == []
    assert record["metrics"]["chat_to_agents_ms"] is None
    assert record["validation"]["line_cleared"] is False
    assert bench.validate(record) is False


def test_multiple_prompt_rows_in_dock_are_ambiguous(tmp_path, monkeypatch):
    # two '>' rows in the dock (a blockquote quoted into the dock) never
    # certify which one is the editor: stop rather than guess (rows carry
    # no probe token, so erase_all never touches them)
    session = NavSession(editor_rows=[" >  quoted reply", " >  older quote"],
                         editor_clearable=True)
    bench, _, record = _measure(tmp_path, session, monkeypatch)
    assert _nav_keys(session) == []
    assert record["validation"]["line_cleared"] is False
    assert bench.validate(record) is False


def test_first_user_text_is_the_row_identity(tmp_path):
    assert _first_user_text(_fixture(tmp_path)) == FIRST_USER
    assert _first_user_text(None) is None
    assert _first_user_text(tmp_path / "missing.jsonl") is None


# ---- partial honesty: measured legs, never a silent fast roundtrip ---------

def test_chrome_without_roster_row_is_partial_not_rankable(tmp_path, monkeypatch):
    # the view renders chrome but never the session's identity row
    session = NavSession(row_title="a different session entirely")
    bench, _, record = _measure(tmp_path, session, monkeypatch,
                                benchmark_overrides=FAST_LEGS)
    assert record["metrics"]["agents_chrome_ms"] is not None
    assert record["metrics"]["chat_to_agents_ms"] is None
    assert record["metrics"]["roundtrip_ok"] is False
    # leg 2 never starts: no RIGHT without a rendered roster row
    assert _nav_keys(session) == [LEFT]
    assert record["validation"]["roster_row"] is False
    assert record["validation"]["echoed_after"] is False
    assert bench.validate(record) is False


def test_unreadable_fixture_never_passes_chrome_only(tmp_path, monkeypatch):
    # a fixture with no readable first user text has no row identity:
    # the chrome wait succeeding must NOT validate the leg
    blank = _fixture(tmp_path, rows=[{"type": "session", "id": "x"}])
    session = NavSession()
    bench, _, record = _measure(tmp_path, session, monkeypatch,
                                fixture=blank, benchmark_overrides=FAST_LEGS)
    assert _first_user_text(blank) is None
    assert record["metrics"]["agents_chrome_ms"] is not None
    assert record["metrics"]["chat_to_agents_ms"] is None
    assert _nav_keys(session) == [LEFT]  # no leg 2 without the identity row
    assert bench.validate(record) is False


def test_view_never_opening_still_records_partial_legs(tmp_path, monkeypatch):
    session = NavSession(open_view=False)
    bench, _, record = _measure(tmp_path, session, monkeypatch,
                                benchmark_overrides=FAST_LEGS)
    assert record["metrics"]["chat_to_agents_ms"] is None
    assert record["metrics"]["agents_to_tail_ms"] is None
    assert record["validation"]["agents_chrome"] is False
    assert bench.validate(record) is False


def test_stale_tail_in_view_blocks_the_return_leg(tmp_path, monkeypatch):
    # the view rendered but the old chat tail never left the screen:
    # the tail seen after RIGHT would be stale, so no RIGHT is sent
    session = NavSession(stale_chat=True)
    bench, _, record = _measure(tmp_path, session, monkeypatch,
                                benchmark_overrides=FAST_LEGS)
    assert _nav_keys(session) == [LEFT]
    assert record["validation"]["sentinel_gone"] is False
    assert record["validation"]["tail_after"] is False
    assert bench.validate(record) is False


def test_missing_tail_after_return_invalidates(tmp_path, monkeypatch):
    # RIGHT pressed, the chat never comes back: no tail, no echo
    session = NavSession(returns=False)
    bench, _, record = _measure(tmp_path, session, monkeypatch,
                                benchmark_overrides=FAST_LEGS)
    assert _nav_keys(session) == [LEFT, RIGHT]
    assert record["metrics"]["chat_to_agents_ms"] is not None
    assert record["metrics"]["agents_to_tail_ms"] is None
    assert record["metrics"]["chat_ready_after_ms"] is None
    assert record["metrics"]["roundtrip_ok"] is False
    assert record["validation"]["tail_after"] is False
    assert record["validation"]["echoed_after"] is False
    assert bench.validate(record) is False


def test_chrome_co_render_after_return_is_not_a_chat(tmp_path, monkeypatch):
    # the tail is back but the view chrome co-renders: a probe echo could
    # come from the view's search field, so the return never validates
    session = NavSession(keeps_chrome=True)
    bench, _, record = _measure(tmp_path, session, monkeypatch,
                                benchmark_overrides=FAST_LEGS)
    assert record["metrics"]["agents_to_tail_ms"] is not None
    assert record["validation"]["tail_after"] is True
    assert record["validation"]["chrome_gone_after"] is False
    assert record["validation"]["echoed_after"] is False
    assert record["metrics"]["chat_ready_after_ms"] is None
    assert bench.validate(record) is False


def test_echo_timeout_after_return_is_not_validated(tmp_path, monkeypatch):
    session = NavSession()
    probes = {"n": 0}

    def flaky_probe(*args, **kwargs):
        # the initial chat-ready probe succeeds; the post-return probe
        # never echoes (the chat never accepts input again)
        probes["n"] += 1
        if probes["n"] == 1:
            return {"gap_ms": 3.0, "echo_ts_offset_ms": 30.0, "sends": 1,
                    "dropped_probes": 0, "chars_sent": 5, "probe_token": "Zq7x01"}
        raise TimeoutError("never ready")

    session.probe_input_ready = flaky_probe
    bench, _, record = _measure(tmp_path, session, monkeypatch,
                                benchmark_overrides=FAST_LEGS)
    # the legs are measured; without a typed echo the row never validates
    assert record["metrics"]["agents_to_tail_ms"] is not None
    assert record["metrics"]["chat_ready_after_ms"] is None
    assert record["validation"]["tail_after"] is True
    assert record["validation"]["echoed_after"] is False
    assert bench.validate(record) is False


# ---- scope: RT-only, registry discovery, key translation --------------------

def test_session_scenarios_are_rt_only(tmp_path):
    bench = SessionAgentViewRoundtrip(_cfg(tmp_path))
    assert bench.applicable("rust") and bench.applicable("ts")
    assert not bench.applicable("claude")


def test_keys_default_to_the_parity_combo(tmp_path):
    bench = SessionAgentViewRoundtrip(_cfg(tmp_path))
    assert bench.agents_view_key == LEFT
    assert bench.agents_open_key == RIGHT


def test_keystroke_translates_modifier_combos():
    # the PTY drivers write verbatim, so the configured key must resolve
    # to the bytes a terminal delivers - literal text would type "ctrl+a"
    assert keystroke("ctrl+a") == "\x01"
    assert keystroke("ctrl+z") == "\x1a"
    assert keystroke("alt+left") == "\x1b\x1b[D"
    assert keystroke("ctrl+A") == "\x01"
    # tokens and literals keep their behavior (pinned in test_adapters_folder)
    assert keystroke("enter") == "\r"
    assert keystroke("sk-bench-dummy") == "sk-bench-dummy"


def test_config_overrides_reach_the_scenario(tmp_path):
    bench = SessionAgentViewRoundtrip(_cfg(tmp_path, {
        "session.agent_view_roundtrip": {"agents_view_timeout_s": 1.5,
                                         "agents_view_key": "ctrl+a"}}))
    assert bench.agents_view_timeout_s == 1.5
    assert bench.agents_view_key == "\x01"


def test_registry_discovers_scenario_and_slices_config(tmp_path):
    cfg = _cfg(tmp_path, {"session.agent_view_roundtrip":
                          {"return_timeout_s": 12.0}})
    reg = discover(cfg)
    bench = reg.benchmark("session.agent_view_roundtrip")
    assert isinstance(bench, SessionAgentViewRoundtrip)
    assert bench.return_timeout_s == 12.0  # the 22b3f8e override path


def test_primary_metric_registered():
    from bench.core.measurement import primary_metric
    assert primary_metric("session.agent_view_roundtrip") == ("chat_to_agents_ms", "minimize")
