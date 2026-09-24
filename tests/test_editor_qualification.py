"""Editor qualification (offline): Claude Code, Codex CLI, Pi Mono.

The editor cohort's qualification checks run entirely offline: config
declarations, product-owned proof metadata, and PTY-synthetic dialog
walks against the harness's own drive_to_ready. Nothing here launches a
real product, provisions anything, or claims live proof — the recorded
cohort acceptance (records/editor-cohort-acceptance.md) carries the
pending live-proof ledger with its consent boundaries.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from bench.adapters.terminals.pty import PTYDriver
from bench.adapters.benchmarks.support import drive_to_ready
from bench.core.config import load_config, product_config
from bench.core.product import resolve_dialogs
from bench.core.registry import discover
from bench.drivers.vendor import undeclared_secret_srcs

TUI = str(Path(__file__).parent / "mini_tui.py")
EDITORS = ("claude", "codex", "pi")


def _cfg(tmp_path):
    cfg = load_config(None)
    cfg["bench_root"] = str(tmp_path / "bench")
    cfg["results_dir"] = str(tmp_path / "bench" / "results")
    return cfg


# ---- product-owned declarations -----------------------------------------------

def test_editor_dialogs_are_complete_config(tmp_path):
    """needs_prepass editors declare every onboarding dialog with at least
    one key (a markerless or keyless walk can never settle); pi's pinned
    revision declares the honest no-dialogs state."""
    reg = discover(_cfg(tmp_path))
    for name in EDITORS:
        prod = reg.product(name)
        steps = prod.dialog_steps
        assert all(marker.strip() and keys for marker, keys in steps), name
        assert prod.needs_prepass == bool(steps) or not prod.needs_prepass, name
        if prod.needs_prepass:
            assert steps, f"{name}: a prepass product must declare its dialogs"
    assert reg.product("claude").dialog_steps, "claude onboarding is a dialog walk"
    assert reg.product("codex").dialog_steps, "codex onboarding is a dialog walk"
    assert reg.product("pi").dialog_steps == [], "pi settles via flags at the pinned revision"


def test_editor_msg_routing_is_declared_honestly(tmp_path):
    """The regime is the product-owned routing truth: claude/pi route the
    mock (offline, zero paid traffic), codex declares real-api with its
    recorded auth limitation — never a silent cross-regime blend."""
    reg = discover(_cfg(tmp_path))
    assert reg.product("claude").msg_routing == "mock"
    assert reg.product("pi").msg_routing == "mock"
    codex = reg.product("codex")
    assert codex.msg_routing == "real-api"
    # product-owned flag: copied ChatGPT tokens do not authenticate a
    # copied home; version evidence reports it
    assert codex.product_cfg.get("auth_limited") is True


def test_editor_resume_capability_is_declared_not_assumed(tmp_path):
    """Fixture resume capability is a declared flag, never inferred; an
    editor without it records not_comparable status rows for fixture
    scenarios (spec §F) instead of measuring a fresh session."""
    reg = discover(_cfg(tmp_path))
    for name in EDITORS:
        flag = reg.product(name).resume_fixture_capable
        assert isinstance(flag, bool), name


def test_claude_launch_env_routes_offline_mock(tmp_path):
    """The load-bearing offline guard: claude's trial env points the
    product at the mock provider with a dummy key and disables
    nonessential traffic — no paid Anthropic path exists in a trial."""
    reg = discover(_cfg(tmp_path))
    claude = reg.product("claude")
    ctx = {"home": tmp_path / "home", "work": tmp_path / "work",
           "tmp": tmp_path / "tmp"}
    env = claude.env(ctx)
    port = claude.mock_port
    assert env["ANTHROPIC_BASE_URL"] == f"http://127.0.0.1:{port}"
    assert env["ANTHROPIC_API_KEY"] == "sk-bench-dummy-not-real"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "sk-bench-dummy-not-real"
    assert env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"
    assert env["HOME"] == str(tmp_path / "home")


def test_pi_launch_argv_pins_the_mock_route(tmp_path):
    """Pi's argv pins provider+model to the mock and disables
    extensions/skills/templates: without the flags pi selects Anthropic
    subscription auth from the copied auth.json (paid traffic) — the
    flag set is load-bearing. models.json routes the same mock."""
    from bench.core.env import write_models_json
    reg = discover(_cfg(tmp_path))
    pi = reg.product("pi")
    ctx = {"home": tmp_path / "home", "work": tmp_path / "work",
           "tmp": tmp_path / "tmp", "trial_dir": tmp_path}
    argv = pi.argv(ctx)
    assert "--provider" in argv and "prime-inference" in argv
    assert "--model" in argv and "mock-1" in argv
    assert "--no-extensions" in argv and "--no-skills" in argv
    assert "--no-prompt-templates" in argv
    agent_dir = tmp_path / "agent"
    write_models_json(agent_dir, f"http://127.0.0.1:{pi.mock_port}/v1")
    models = json.loads((agent_dir / "models.json").read_text())
    provider = models["providers"]["prime-inference"]
    assert provider["baseUrl"] == f"http://127.0.0.1:{pi.mock_port}/v1"
    assert provider["models"][0]["id"] == "mock-1"


# ---- product-owned proof records ------------------------------------------------

def test_editor_proof_records_parse_and_verify(tmp_path):
    """proofs: is the product-owned evidence ledger: pi records its
    function-only live proof with digest-pinned external artifacts
    (verified when the archive is present, absent-external otherwise —
    never a silent pass), claude/codex record the explicit none."""
    reg = discover(_cfg(tmp_path))
    assert reg.product("claude").proof_records() == []
    assert reg.product("codex").proof_records() == []
    pi_records = reg.product("pi").proof_records()
    assert len(pi_records) == 1
    rec = pi_records[0]
    assert rec["name"] == "native-session-resume"
    assert rec["kind"] == "live-function-only"
    assert rec["fixture"]["corpus"] == "v2"
    arts = rec["artifacts"]
    assert len(arts) == 4
    for art in arts:
        # honesty invariant: "verified" only when the file is present AND
        # matches its recorded sha256 (proof_records raises on mismatch)
        assert art["status"] in ("verified", "absent-external")
        if Path(art["path"]).exists():
            assert art["status"] == "verified"


def test_proof_records_reject_corrupt_evidence(tmp_path):
    """A recorded artifact that exists but mismatches its digest is
    corrupt evidence: it must fail loudly, never pass silently."""
    cfg = _cfg(tmp_path)
    bad = tmp_path / "bad-proof.json"
    bad.write_text("tampered")
    import hashlib
    cfg2 = dict(cfg)
    prod_cfg = product_config("claude")
    prod_cfg["proofs"] = [{
        "name": "x", "kind": "live", "date": "2026-09-24",
        "scope": "test scope",
        "artifacts": [{"path": str(bad), "sha256": "0" * 64}],
    }]
    reg = discover(cfg2)
    claude = reg.product("claude")
    claude.product_cfg = prod_cfg
    with pytest.raises(ValueError, match="sha256 mismatch"):
        claude.proof_records()

    # structural gaps are config errors, not silent empty records
    claude.product_cfg = {"proofs": [{"name": "x"}]}
    with pytest.raises(ValueError, match="missing"):
        claude.proof_records()
    claude.product_cfg = {"proofs": [{"name": "x", "kind": "live",
                                      "date": "2026-09-24", "scope": "s",
                                      "artifacts": [{"path": str(bad)}]}]}
    with pytest.raises(ValueError, match="sha256"):
        claude.proof_records()


def test_pi_recorded_proof_scope_disclaims_v3_and_capability(tmp_path):
    """The recorded pi proof is v2-corpus, function-only: its scope must
    say so in writing — the record may never read as v3 validation or as
    adapter capability at this revision."""
    reg = discover(_cfg(tmp_path))
    rec = reg.product("pi").proof_records()[0]
    scope = " ".join(rec["scope"].split()).lower()
    assert "not a campaign trial" in scope
    assert "not v3-corpus validation" in scope
    assert "not an adapter capability" in scope
    assert reg.product("pi").resume_fixture_capable is False


# ---- vendor/auth declaration hygiene ---------------------------------------------

def _registry_with_vendor(tmp_path, vendor, auth_sources):
    """A synthetic product config: checker semantics stay testable
    without asserting the live tree's transient merge state."""
    cfg = _cfg(tmp_path)
    reg = discover(cfg)
    prod = reg.product("claude")
    prod.product_cfg = {"vendor": vendor, "auth_sources": auth_sources}
    reg.products = {"claude": prod}
    return cfg, reg


def test_undeclared_prime_home_vendor_entries_are_reported(tmp_path):
    """The 2026-09-24 live finding class: a vendor entry sourced under
    the prime home is credential-bearing by default — undeclared, it
    rides a --no-secrets payload built on declared-auth redaction."""
    prime = str(Path("~/.prime").expanduser())
    cfg, reg = _registry_with_vendor(
        tmp_path,
        vendor=[{"src": prime + "/config.json", "dst": "root/.prime/config.json"},
                {"src": prime + "/agent/auth.json", "dst": "root/.prime/agent/auth.json"},
                {"src": "/usr/bin/claude", "dst": "usr/bin/claude"}],
        auth_sources=[{"src": prime + "/agent/auth.json"}],
    )
    gaps = undeclared_secret_srcs(cfg, ["claude"], reg=reg)
    assert gaps == {"claude": [prime + "/config.json"]}

    # declared fully: no gap; non-prime-home vendor entries never count
    cfg, reg = _registry_with_vendor(
        tmp_path,
        vendor=[{"src": prime + "/config.json", "dst": "root/.prime/config.json"},
                {"src": "/usr/bin/claude", "dst": "usr/bin/claude"}],
        auth_sources=[{"src": prime + "/config.json"}],
    )
    assert undeclared_secret_srcs(cfg, ["claude"], reg=reg) == {}


def test_real_editor_vendor_declarations_are_hygiene_checked(tmp_path):
    """claude/codex ship no prime-home vendor gap at this base. pi's gap
    is the recorded acceptance condition (records/editor-cohort-acceptance.md):
    it closes with the pi-pin-provenance integration, so the suite must
    not pin its transient state — only the healthy editors here."""
    cfg = _cfg(tmp_path)
    reg = discover(cfg)
    gaps = undeclared_secret_srcs(cfg, list(reg.products), reg=reg)
    for name in ("claude", "codex", "rust", "ts"):
        assert gaps.get(name, []) == [], name


# ---- PTY-synthetic dialog-walk floor ----------------------------------------------

def _walk_spec(steps):
    return {"steps": [{"marker": m, "keys": list(k)} for m, k in steps]}


@pytest.mark.parametrize("name", EDITORS)
def test_editor_dialog_walk_reaches_ready_offline(name, tmp_path):
    """The harness's own drive_to_ready must settle a synthetic TUI that
    replays THE PRODUCT'S OWN onboarding dialogs (its exact markers and
    keystroke-resolved keys; wrong keys never advance it). This
    certifies the dialog config end-to-end offline — it is a harness
    floor, NOT product proof: no product binary is involved."""
    cfg = _cfg(tmp_path)
    reg = discover(cfg)
    prod = reg.product(name)
    spec = tmp_path / "dialog-spec.json"
    spec.write_text(json.dumps(_walk_spec(prod.dialog_steps)))
    driver = PTYDriver({})
    app = driver.start_session([sys.executable, TUI, "dialog-script", str(spec)],
                               cols=120)
    try:
        app.wait_for(lambda: app.t_first_paint is not None, timeout=10.0)
        state = drive_to_ready(app, prod.dialog_steps, timeout=60.0,
                               probe="Zq7w", pacing={"key_pause_s": 0.3,
                                                     "loop_s": 0.4,
                                                     "echo_wait_s": 2.0})
        assert state == "ready"
        assert "Zq7w" in app.screen_text()
    finally:
        app.kill_tree()
