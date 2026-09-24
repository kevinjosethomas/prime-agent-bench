"""Return-user consent baseline: template seeding + trial-clone survival.

Source-verified shape (pinned TS acc5bc0 settings-manager.ts/onboarding.ts
+ Rust bdf82f4f settings types.rs/interactive_mode.rs): the baseline is
{"onboardingShown": true, "agentTraces": {"enabled": false},
 "telemetry": {"noticeShown": true}} — the persisted "Not now" — never
{"traces": "not-now"} (that shape existed only in an old bench fake).
These tests pin: the rust adapter seeds BOTH product-visible locations
at template build; the trial clone carries both to their real paths
(the agent dir the product reads via PRIME_AGENT_CODING_AGENT_DIR, and
the HOME default path); seeding merges over product-persisted keys; and
both registry products (rust, ts) declare the baseline.
"""
from __future__ import annotations

import json
from pathlib import Path

from bench.adapters.rust.adapter import PrimeAgentRustProduct
from bench.core.config import load_config
from bench.core.env import CONSENT_BASELINE_SETTINGS
from bench.core.registry import discover


def _cfg(tmp_path):
    cfg = load_config(None)
    cfg["bench_root"] = str(tmp_path / "bench")
    cfg["results_dir"] = str(tmp_path / "bench" / "results")
    cfg["mock"] = {"port": 8788}
    return cfg


def _rust(tmp_path):
    reg = discover(_cfg(tmp_path))
    return reg.product("rust")


def test_consent_baseline_shape_is_the_pinned_keys():
    """The pinned return-user consent shape — the persisted "Not now" —
    and never the old fake's traces:not-now."""
    assert CONSENT_BASELINE_SETTINGS == {
        "onboardingShown": True,
        "agentTraces": {"enabled": False},
        "telemetry": {"noticeShown": True},
    }


def test_rust_template_seeds_both_product_visible_locations(tmp_path):
    prod = _rust(tmp_path)
    tpl = tmp_path / "tpl"
    prod.prepare_template(tpl)
    agent = json.loads((tpl / "agent" / "settings.json").read_text())
    home = json.loads((tpl / "home" / ".prime" / "agent"
                       / "settings.json").read_text())
    assert agent == CONSENT_BASELINE_SETTINGS
    assert home == CONSENT_BASELINE_SETTINGS
    # the existing mock/auth config is retained, not replaced
    assert json.loads((tpl / "agent" / "models.json").read_text())[
        "providers"]["prime-inference"]["models"][0]["id"] == "mock-1"


def test_trial_clone_carries_both_settings_copies(tmp_path):
    """The template->trial clone must land the home-level baseline at the
    trial HOME default path (the historical clone nested <template>/home
    inside the trial home where no product read it) and the agent-dir
    copy at the dir PRIME_AGENT_CODING_AGENT_DIR pins."""
    prod = _rust(tmp_path)
    tpl = prod.template_dir()
    tpl.mkdir(parents=True)
    prod.prepare_template(tpl)
    ctx = prod.new_trial(tmp_path / "trial-01")
    home = json.loads((Path(ctx["home"]) / ".prime" / "agent"
                       / "settings.json").read_text())
    agent = json.loads((Path(ctx["agent_dir"]) / "settings.json").read_text())
    assert home == CONSENT_BASELINE_SETTINGS
    assert agent == CONSENT_BASELINE_SETTINGS
    assert prod.env(ctx)["PRIME_AGENT_CODING_AGENT_DIR"] == str(ctx["agent_dir"])


def test_seeding_merges_over_product_persisted_settings(tmp_path):
    """A template rebuilt over product-persisted settings keeps the
    product's other keys; the three consent keys are enforced pinned."""
    from bench.core.env import write_consent_baseline
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    (agent_dir / "settings.json").write_text(json.dumps({
        "onboardingShown": False,
        "defaultProvider": "prime-inference",
        "defaultModel": "mock-1",
        "recentModels": ["prime-inference/mock-1"],
    }))
    merged = write_consent_baseline(agent_dir)
    assert merged["defaultProvider"] == "prime-inference"
    assert merged["recentModels"] == ["prime-inference/mock-1"]
    assert merged["onboardingShown"] is True
    assert merged["agentTraces"] == {"enabled": False}
    assert merged["telemetry"] == {"noticeShown": True}


def test_registry_products_declare_the_baseline(tmp_path):
    reg = discover(_cfg(tmp_path))
    assert reg.product("rust").seeds_consent_baseline is True
    assert reg.product("ts").seeds_consent_baseline is True
    for name in ("claude", "codex", "pi"):
        assert reg.product(name).seeds_consent_baseline is False


# ---- the measured cold-start: breach semantics ------------------------------

MARKER = "Share agent traces with Prime Intellect?"


class FakeColdSession:
    """The probe/erase surface measure_cold_start drives (no product,
    no inference): dialogs reported by the probe, an optional sheet
    marker sitting on the screen at the settled-window check (the
    observed async post-ready shape)."""

    t_spawn = 0.0
    t_first_paint = 0.0
    pid = None

    def __init__(self, probe_dialogs=(), settled_marker=False):
        self.probe_dialogs = list(probe_dialogs)
        self.settled_marker = settled_marker
        self.killed = False

    def probe_input_ready(self, token, **kwargs):
        return {"gap_ms": 1.0, "echo_ts_offset_ms": 1.0, "sends": 1,
                "unconfirmed_attempts": 0, "dropped_probes": None,
                "chars_sent": len(token), "probe_token": token,
                "probe_tokens": [token], "input_buffered": False,
                "probe_grid_ms": 50.0, "quantized_ms": 50.0,
                "dialogs": list(self.probe_dialogs), "dialog_ms": 0.0}

    def erase_all(self, tokens, max_backspaces=0, timeout=0):
        return True, 1.0

    def screen_text(self):
        return MARKER + "\n> Share\n  Not now" if self.settled_marker \
            else "Prime Agent editor"

    def bytes_out(self):
        return 16

    def burst_stats(self, t_start=None, t_end=None, gap=0.05):
        return {"bursts": 0, "per_burst_bytes": []}

    def kill_tree(self):
        self.killed = True


class FakeColdProduct:
    """Product surface for measure_cold_start (no prepass, no daemon)."""

    needs_prepass = False

    def __init__(self, session, seeds_consent_baseline=True):
        self.session = session
        self.seeds_consent_baseline = seeds_consent_baseline
        self.reaped = False

    def launch(self, ctx, driver, resume_fixture=None):
        return self.session

    def reap(self, ctx):
        self.reaped = True


def _cold_record(product):
    from bench.adapters.benchmarks.cold_start import measure_cold_start
    record = {}
    measure_cold_start(product, {"trial_dir": Path("/tmp/x")}, record, None)
    return record


def test_cold_start_seeded_clean_trial_validates():
    """A consent-settled launch with no sheet anywhere: the baseline
    holds, the validation certifies it."""
    record = _cold_record(FakeColdProduct(FakeColdSession()))
    assert record["consent_baseline_breach"] == []
    assert record["validation"] == {"echoed": True, "erased": True,
                                    "consent_baseline_intact": True}


def test_cold_start_midprobe_sheet_invalidates():
    """A sheet answered mid-probe survived the seeded baseline: the row
    records the breach and the validation FAILS (the strict validity
    gate then excludes it — never silently measured dialog time)."""
    record = _cold_record(FakeColdProduct(
        FakeColdSession(probe_dialogs=[MARKER])))
    assert record["consent_baseline_breach"] == [MARKER]
    assert record["validation"]["consent_baseline_intact"] is False
    from bench.adapters.benchmarks.cold_start import ColdStart
    assert ColdStart(None).validate(record) is False


def test_cold_start_post_ready_sheet_invalidates():
    """The observed async shape: the probe phase is clean, the sheet pops
    after ready and sits on the screen in the settled window — a breach
    (seconds in, past the echo — exactly the shape a probe-phase check
    alone would miss)."""
    record = _cold_record(FakeColdProduct(
        FakeColdSession(settled_marker=True)))
    assert record["consent_baseline_breach"] == [MARKER]
    assert record["validation"]["consent_baseline_intact"] is False


def test_cold_start_non_baseline_product_keeps_walk_semantics():
    """Products without a seedable baseline keep the measured-walk
    semantics: a dialog is answered, disclosed per row, dialog time is
    excluded from the gap, and the trial validates as before."""
    record = _cold_record(FakeColdProduct(
        FakeColdSession(probe_dialogs=[MARKER]),
        seeds_consent_baseline=False))
    assert "consent_baseline_breach" not in record
    assert record["validation"] == {"echoed": True, "erased": True}
    assert record["dialog_autodismissed"] == MARKER[:40]
    from bench.adapters.benchmarks.cold_start import ColdStart
    assert ColdStart(None).validate(record) is True
