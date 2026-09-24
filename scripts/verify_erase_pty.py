"""Real-PTY erase verification (not a unit test; manual/evidence run).

Runs the exact cold_start probe+erase flow against the REAL product TUIs
on a raw PTY: launch -> first paint -> probe_input_ready (fine grid,
onboarding dialogs auto-dismissed) -> erase_all burst -> every-token
certification -> editor acceptance (fresh echo) -> teardown.

Offline-only by construction: products launch with --offline and their
models.json routes prime-inference to 127.0.0.1 (the bench mock
provider); the trial env carries a dummy PRIME_API_KEY and the trial
home's config.json is sanitized before launch, so no real credential is
used even if a submit somehow happened — and the mock's request log
asserts ZERO model requests (no submit side effects at all).

Gate: run only when PRIME_BENCH_REAL_PTY=1 and the binaries exist
(skips cleanly otherwise — never in CI):

    PRIME_BENCH_REAL_PTY=1 python scripts/verify_erase_pty.py \
        --products rust,ts            # local: TS release + a Rust build
    PRIME_BENCH_REAL_PTY=1 python scripts/verify_erase_pty.py \
        --products pi                 # on the bench node (built bundle)

Rust binary resolution: product.yaml pins the node build; locally the
script overrides the pin with --rust-binary (default: the local
release build) and drops the sha pin (the override is recorded in the
evidence, never silently passed off as the pinned build).

Stress bound (audit follow-up): the 66-token cohort is sent only after
a positive dialog-free check, and a sentinel appended right after the
burst must be positively witnessed rendered in the editor region
before the erase. The sentinel proves editor focus at burst end — NOT
full-cohort acceptance: the missing-list records the cohort render
state, and the full 66-token stress contract stays uncertified until
real proof.

Pre-settle (verification-only): before the measured launch, ONE isolated
launch on the same trial home walks the product-owned first-run dialogs
to ready and then drains any sheet that pops after ready (the observed
share-traces sheet lands seconds in, after the probe echo), answering
it with the product's own dialog keys. Campaign templates, fixtures and
scenarios are untouched — the settled home is the gate's ephemeral
trial home only.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from bench.adapters.benchmarks.support import (  # noqa: E402
    PROBE_TOKEN, drive_to_ready, first_paint,
)
from bench.core.process import sweep_trial  # noqa: E402
from bench.adapters.terminals.pty import PTYDriver  # noqa: E402
from bench.core.config import load_config  # noqa: E402
from bench.core.env import scrubbed_env  # noqa: E402
from bench.core.registry import discover  # noqa: E402
from bench.drivers.mock_state import default_script  # noqa: E402

ONBOARDING_AUTODISMISS = [
    ("Share agent traces with Prime Intellect?", ["\x1b[B", "\r"]),
    ("Do you want to use this API key?", ["\x1b[A", "\r"]),
]
DUMMY_KEY = "sk-bench-mock-offline"

EVIDENCE_DIR_DEFAULT = "/tmp/erase-gate-evidence"
STRESS_SENTINEL = "Zq9s"


def evidence_dir() -> Path:
    """Stable evidence dir that survives the trial-root cleanup."""
    d = Path(os.environ.get("PRIME_BENCH_ERASE_EVIDENCE_DIR",
                            EVIDENCE_DIR_DEFAULT))
    d.mkdir(parents=True, exist_ok=True)
    return d


def dump_transcripts(name: str, app) -> None:
    """Raw PTY stream + rendered screen (kept for every product, pass or
    failure). PTYSession keeps a capped raw bytearray (raw_cap 4MiB,
    trimmed prefix); captured under its lock, trim + totals recorded."""
    out = evidence_dir() / name
    out.mkdir(parents=True, exist_ok=True)
    with app._lock:
        raw = bytes(app.raw)
        trimmed = app.trimmed
    (out / "raw.pty").write_bytes(raw)
    (out / "screen.txt").write_text(app.screen_text())
    (out / "bytes.json").write_text(json.dumps(
        {"captured": len(raw), "trimmed": trimmed,
         "total": app.bytes_out()}))


def dismiss_dialogs(app, rounds: int = 4, pause: float = 0.4) -> int:
    """Dismiss any onboarding sheet that appears mid-trial. The probe's
    dialog_steps only cover the probe phase, but TS pops the share-traces
    sheet AFTER readiness; later phases must measure the real editor."""
    keys_by_marker = dict(ONBOARDING_AUTODISMISS)
    dismissed = 0
    for _ in range(rounds):
        text = app.screen_text()
        marker = next((m for m in keys_by_marker if m in text), None)
        if marker is None:
            return dismissed
        for key in keys_by_marker[marker]:
            app.send(key)
            time.sleep(pause)
        dismissed += 1
        time.sleep(0.5)
    return dismissed


def editor_window(app, rows_up: int, rows_down: int = 1) -> tuple:
    """Cursor-anchored editor window text, row-wise + seam-joined."""
    window = app.echo_window_text(rows_up=rows_up, rows_down=rows_down) \
        or app.screen_text()
    return window, "".join(window.splitlines())


def token_in(window: str, joined: str, token: str) -> bool:
    return token in window or token in joined


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_mock(port: int, workdir: Path):
    script_path = workdir / "mock-script.json"
    script_path.write_text(json.dumps(default_script()))
    proc = subprocess.Popen(
        [sys.executable, "-m", "bench.drivers.mock_provider",
         str(script_path), str(port)],
        cwd=REPO, stdout=subprocess.PIPE, text=True)
    port_line = proc.stdout.readline().strip()
    return proc, int(port_line), str(script_path) + ".requests.jsonl"


def sanitize_trial_home(ctx, product_name: str) -> None:
    """No real credentials ride in the trial env/home for this run."""
    cfgjson = Path(ctx["home"]) / ".prime" / "config.json"
    if cfgjson.exists():
        try:
            cfg = json.loads(cfgjson.read_text())
            cfg["api_key"] = DUMMY_KEY
            cfgjson.write_text(json.dumps(cfg))
        except Exception:
            pass


def launch_isolated(prod, ctx, driver):
    """launch() with the PRIME_API_KEY override (offline, mock only)."""
    env = prod.env(ctx)
    env["PRIME_API_KEY"] = DUMMY_KEY
    return driver.start_session(prod.argv(ctx), env=env, cwd=str(ctx["work"]))


def gate_pass(evidence: dict) -> bool:
    """The gate verdict: every witness positive. The stress bound proves
    EDITOR-FOCUS-AT-BURST-END — a dialog-free screen at send time plus a
    sentinel (appended right after the burst) positively witnessed in
    the editor region before the erase — NOT full 66-token acceptance:
    the cohort render state is recorded (rendered count + missing list)
    and the full-stress contract stays uncertified until real proof."""
    return bool(
        evidence.get("probe_witnessed")
        and evidence.get("erase_ok") and not evidence.get("leftover_tokens")
        and evidence.get("post_erase_window_nonempty")
        and evidence.get("alive_after_erase")
        and evidence.get("fresh_echo_ok") and evidence.get("fresh_erase_ok")
        and evidence.get("mock_model_requests") == 0
        and evidence.get("stress", {}).get("erase_ok")
        and evidence.get("stress_dialog_free")
        and evidence.get("stress_focus_verified")
        and "reap_leftovers" not in evidence
        and "transcript_dump_error" not in evidence)


def pre_settle(prod, ctx, driver, post_ready_s: float = 10.0) -> str:
    """Verification-only onboarding consumption (the harness prepass
    pattern): one isolated launch on the trial home walks the
    product-owned first-run dialogs to ready, then DRAINS any sheet that
    pops after ready — the observed share-traces sheet lands seconds
    in, after the probe echo, so a bare to-ready walk would miss it. The
    measured launch that follows runs against the settled home. Mock-only
    by construction (the same offline argv + dummy key as the measured
    launch); the settle session is killed and swept, never measured."""
    app = launch_isolated(prod, ctx, driver)
    try:
        first_paint(app, timeout=60)
        result = drive_to_ready(app, prod.dialog_steps, timeout=150,
                                probe="Zq7prep01", pacing={})
        keys_by_marker = dict(prod.dialog_steps)
        quiet = 0.0
        deadline = time.monotonic() + post_ready_s
        while time.monotonic() < deadline:
            norm = " ".join(app.screen_text().split())
            marker = next((m for m in keys_by_marker if m in norm), None)
            if marker is None:
                quiet += 0.2
                if quiet >= 2.0:
                    break
                time.sleep(0.2)
                continue
            quiet = 0.0
            for key in keys_by_marker[marker]:
                app.send(key)
                time.sleep(0.4)
            time.sleep(0.5)
        return result
    finally:
        app.kill_tree()
        sweep_trial(ctx)


def verify_product(name: str, reg, driver, mock_log: str, root: Path) -> dict:
    prod = reg.product(name)
    trial = root / "trials" / name / "verify-erase"
    if trial.exists():
        shutil.rmtree(trial)
    trial.parent.mkdir(parents=True, exist_ok=True)
    if not prod.template_dir().exists():
        prod.prepare_template(prod.template_dir())
    ctx = prod.new_trial(trial)
    sanitize_trial_home(ctx, name)
    evidence: dict = {"product": name}
    # verification-only pre-settle: consume onboarding sheets BEFORE the
    # measured launch so the async share-traces sheet cannot steal focus
    # mid-burst; campaigns keep their own fresh-home templates untouched
    evidence["pre_settle"] = pre_settle(prod, ctx, driver)
    sanitize_trial_home(ctx, name)
    app = None
    try:
        evidence["version"] = prod.version_info()
        app = launch_isolated(prod, ctx, driver)
        t_paint = first_paint(app, timeout=90)
        probe = app.probe_input_ready(
            PROBE_TOKEN, retry_every=0.5, timeout=45.0, start_ts=t_paint,
            dialog_steps=ONBOARDING_AUTODISMISS)
        evidence["probe"] = {
            "sends": probe["sends"],
            "unconfirmed_attempts": probe["unconfirmed_attempts"],
            "dropped_probes": probe["dropped_probes"],
            "input_buffered": probe["input_buffered"],
            "chars_sent": probe["chars_sent"],
            "ready_ms": probe["echo_ts_offset_ms"],
            "dialogs": probe["dialogs"],
        }
        tokens = probe["probe_tokens"]
        evidence["dialog_dismissals"] = []
        n = dismiss_dialogs(app)
        if n:
            evidence["dialog_dismissals"].append(("post_probe", n))
        # the SUCCESSFUL probe token must be positively witnessed in the
        # editor region before its erase can certify clearing it (a bare
        # probe return is not itself a render witness)
        pw, pwj = editor_window(app, rows_up=6)
        last_probe = tokens[-1] if tokens else ""
        evidence["probe_witnessed"] = bool(last_probe) and token_in(pw, pwj, last_probe)
        erase_ok, erase_ms = app.erase_all(
            tokens, max_backspaces=probe["chars_sent"] + 8)
        evidence["erase_ok"] = erase_ok
        evidence["erase_ms"] = erase_ms
        # EVERY attempt token must be gone from the editor rows: row-wise
        # and seam-joined (a token split at a wrap seam has no full
        # substring in any single row)
        window = app.echo_window_text(rows_up=6, rows_down=1) or app.screen_text()
        joined = "".join(window.splitlines())
        evidence["post_erase_window_nonempty"] = bool(window.strip())
        evidence["leftover_tokens"] = [t for t in tokens
                                       if t in window or t in joined]
        # 66-send stress: 396 chars pre-queued raw (pre-mount), plus the
        # probe flow's own attempts — the live Rust shape was SIX wrapped
        # rows of residue; the burst + dynamic-cap gate must clear it all.
        # A sheet up at send time swallows the input (run-2 TS: 0/66
        # rendered), so dismiss BEFORE sending.
        n = dismiss_dialogs(app)
        if n:
            evidence["dialog_dismissals"].append(("pre_stress", n))
        # guaranteed dialog-free at send time (positive no-marker check)
        evidence["stress_dialog_free"] = not any(
            m in app.screen_text() for m, _ in ONBOARDING_AUTODISMISS)
        stress_tokens = [f"Zq7z{i:02d}" for i in range(1, 67)]
        for tok in stress_tokens:
            app.send(tok)
        # sentinel appended in the SAME input block, right after the
        # burst: its positive echo in the editor region proves the editor
        # held focus at burst end (run-2 TS had zero renders). The
        # sentinel proves focus, NOT full-cohort acceptance — the missing
        # list below records the cohort render state.
        app.send(STRESS_SENTINEL)
        n = dismiss_dialogs(app)
        if n:
            evidence["dialog_dismissals"].append(("post_stress", n))
        # bounded wait (no blind sleeps): the sentinel echo on the input
        # line is the mount signal for the whole queued block
        cols = int(getattr(app, "cols", 0) or 120)
        stress_chars = sum(len(t) for t in stress_tokens) + len(STRESS_SENTINEL)
        rows_up_s = math.ceil(stress_chars / cols) + 2
        try:
            app.wait_for(
                lambda: token_in(*editor_window(app, rows_up_s), STRESS_SENTINEL),
                timeout=10.0, poll=0.05)
            evidence["stress_focus_verified"] = True
        except TimeoutError:
            evidence["stress_focus_verified"] = False
        sw, swj = editor_window(app, rows_up_s)
        # representative early/late witnesses + the full cohort state:
        # recorded, not gated — viewport/burst coalescing can legitimately
        # hide per-token raw echoes (rust run-2 raw showed 55/66)
        evidence["stress_early_rendered"] = token_in(sw, swj, stress_tokens[0])
        evidence["stress_late_rendered"] = token_in(sw, swj, stress_tokens[-1])
        evidence["stress_missing_pre_erase"] = [t for t in stress_tokens
                                                if not token_in(sw, swj, t)]
        evidence["stress_cohort_rendered_count"] = (
            len(stress_tokens) - len(evidence["stress_missing_pre_erase"]))
        all_tokens = tokens + stress_tokens + [STRESS_SENTINEL]
        stress_budget = sum(len(t) for t in all_tokens) + 8
        stress_ok, stress_ms = app.erase_all(all_tokens,
                                             max_backspaces=stress_budget)
        evidence["stress"] = {
            "tokens": len(all_tokens), "chars": stress_budget - 8,
            "erase_ok": stress_ok, "erase_ms": stress_ms,
        }
        # editor state + acceptance: alive, and fresh input still echoes
        evidence["alive_after_erase"] = app.alive()
        n = dismiss_dialogs(app)
        if n:
            evidence["dialog_dismissals"].append(("pre_fresh_echo", n))
        app.start_echo_watch("Zq9k")
        app.send("Zq9k")
        t_echo = None
        try:
            app.wait_echo(3.0)
            t_echo = True
        except TimeoutError:
            # one bounded retry after dismissing a sheet that stole focus
            n = dismiss_dialogs(app)
            if n:
                evidence["dialog_dismissals"].append(("fresh_retry", n))
                app.start_echo_watch("Zq9k")
                app.send("Zq9k")
                try:
                    app.wait_echo(3.0)
                    t_echo = True
                except TimeoutError:
                    t_echo = False
            else:
                t_echo = False
        evidence["fresh_echo_ok"] = t_echo
        # clean the fresh token too (same burst mechanics, small budget)
        evidence["fresh_erase_ok"] = app.erase_all(
            ["Zq9k"], max_backspaces=16)[0]
        # submit side effects: zero model requests proves nothing was
        # submitted anywhere (offline + mock routing + empty request log)
        evidence["mock_model_requests"] = 0
        if os.path.exists(mock_log):
            evidence["mock_model_requests"] = sum(
                1 for _ in open(mock_log))
    finally:
        if app is not None:
            try:
                dump_transcripts(name, app)
            except Exception as e:
                evidence["transcript_dump_error"] = f"{type(e).__name__}: {e}"[:200]
            app.kill_tree()
        try:
            prod.reap(ctx)
        except Exception as e:
            evidence["reap_leftovers"] = str(e)[:200]
    evidence["pass"] = gate_pass(evidence)
    out = evidence_dir() / name
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(json.dumps(evidence, indent=1, default=str))
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--products", default="rust,ts")
    parser.add_argument("--rust-binary", default=str(
        Path.home() / "pi/prime-agent/target/release/prime-agent"))
    args = parser.parse_args()
    if os.environ.get("PRIME_BENCH_REAL_PTY") != "1":
        print("SKIP: set PRIME_BENCH_REAL_PTY=1 to run the real-PTY "
              "erase verification (never in CI)")
        return 0
    names = [n.strip() for n in args.products.split(",") if n.strip()]

    port = free_port()
    root = Path(tempfile.mkdtemp(prefix="prime-bench-erase-verify-"))
    cfg = load_config()
    cfg["bench_root"] = str(root / "bench")
    cfg["mock"] = {"port": port}
    reg = discover(cfg)

    # local rust: override the node pin (recorded, sha pin dropped)
    rust = reg.products.get("rust")
    if rust and "rust" in names:
        rust.product_cfg["binary"] = args.rust_binary
        rust.product_cfg.pop("binary_sha256", None)

    mock_proc, mock_port, mock_log = start_mock(port, root)
    driver = PTYDriver({})
    results = []
    try:
        for name in names:
            try:
                results.append(verify_product(name, reg, driver, mock_log, root))
            except Exception as e:
                rec = {"product": name, "error": f"{type(e).__name__}: {e}"[:400]}
                try:
                    out = evidence_dir() / name
                    out.mkdir(parents=True, exist_ok=True)
                    (out / "result.json").write_text(json.dumps(rec, indent=1))
                except Exception:
                    pass
                results.append(rec)
    finally:
        mock_proc.terminate()
    ok = (len(results) == len(names)
          and all(r.get("product") in names and r.get("pass") is True
                  for r in results))
    print(json.dumps({"results": results, "ok": ok,
                      "evidence_dir": str(evidence_dir())}, indent=1))
    shutil.rmtree(root, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
