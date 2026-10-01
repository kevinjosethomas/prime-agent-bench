"""`bench diagnose <product>`: the settle-failure evidence bundle, one command.

Reproduces the settle walk (fresh trial home from the template, launch,
first paint, the configured first-run dialog walk) and — on failure OR
success — captures the evidence the campaign used to extract by hand:
the rendered screen at the end, the raw output tail, the dialog steps
actually answered, the mock provider's request log, the settle JSONL
tail, and the version/argv/env facts. Writes
<results>/diagnose/<product>-<ts>/ and prints the bundle path.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from bench.adapters.benchmarks.support import drive_to_ready, first_paint
from bench.core.config import load_config
from bench.core.registry import discover
from bench.runner import prepare_templates, start_mock


def _screens_txt(session) -> str:
    """The final rendered screen (blank lines kept, numbered)."""
    lines = session.screen_text().splitlines()
    return "\n".join(f"{i:3d}| {ln}" for i, ln in enumerate(lines))


def _raw_tail(session, cap: int = 200_000) -> str:
    """The raw output tail (PTY driver: the true stream; tmux: none)."""
    raw = getattr(session, "raw", None)
    if raw is None:
        return ""
    data = bytes(raw[-cap:])
    return data.decode(errors="replace")


def _dialog_trace(session, steps, timeout: float, pacing: dict,
                  probe: str) -> dict:
    """The settle walk with per-dialog evidence captured as it goes."""
    answered: dict[str, int] = {}
    errors: list[str] = []
    key_pause = float(pacing.get("key_pause_s", 0.7))
    loop_s = float(pacing.get("loop_s", 0.8))
    echo_wait = float(pacing.get("echo_wait_s", 1.2))
    deadline = time.monotonic() + timeout
    last_screen = ""
    while time.monotonic() < deadline:
        txt = " ".join(session.screen_text().split())
        last_screen = session.screen_text()
        hit = False
        for marker, keys in steps:
            if marker in txt and answered.get(marker, 0) < 3:
                answered[marker] = answered.get(marker, 0) + 1
                for k in keys:
                    session.send(k)
                    time.sleep(key_pause)
                hit = True
                break
        if not hit:
            session.start_echo_watch(probe)
            session.send(probe)
            try:
                session.wait_echo(echo_wait)
                return {"ready": True, "dialogs_answered": answered}
            except TimeoutError:
                pass
        time.sleep(loop_s)
    errors.append(f"settle walk never reached ready in {timeout:.0f}s")
    return {"ready": False, "dialogs_answered": answered,
            "errors": errors, "last_screen": last_screen}


def diagnose(cfg: dict, reg, product_name: str,
             out_dir: Path | None = None) -> Path:
    """Reproduce the settle and write the evidence bundle; returns its path."""
    from bench.core.process import sweep_trial
    import shutil
    prod = reg.product(product_name)
    settle_cfg = cfg["settle"]
    out_dir = out_dir or Path(cfg["results_dir"]) / "diagnose" / (
        f"{product_name}-{time.strftime('%Y%m%d-%H%M%S')}")
    out_dir.mkdir(parents=True, exist_ok=True)
    driver = reg.driver()
    mock = start_mock(cfg)
    trial = prod.layout.trials_dir(product_name) / ".diagnose"
    if trial.exists():
        shutil.rmtree(trial)
    prepare_templates(reg, [product_name])
    ctx = prod.new_trial(trial)
    report: dict = {"product": product_name,
                    "argv": None, "version": None,
                    "home": str(ctx["home"]),
                    "settle_cfg": settle_cfg,
                    "first_run_dialogs": [m for m, _ in prod.dialog_steps],
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    try:
        report["version"] = prod.version_info()
        report["argv"] = prod.argv(ctx)
        app = prod.launch(ctx, driver)
        try:
            t0 = time.monotonic()
            first_paint(app, timeout=float(settle_cfg["first_paint_timeout_s"]))
            report["first_paint_s"] = round(time.monotonic() - t0, 2)
            trace = _dialog_trace(app, prod.dialog_steps,
                                  timeout=float(settle_cfg["timeout_s"]),
                                  pacing=settle_cfg, probe="Zq7x01")
            report["ready"] = trace.pop("ready", False)
            report["dialogs_answered"] = trace.pop("dialogs_answered", {})
            if trace.get("errors"):
                report["errors"] = trace["errors"]
            (out_dir / "screen-at-end.txt").write_text(
                trace.get("last_screen") or _screens_txt(app))
            (out_dir / "raw-output-tail.txt").write_text(_raw_tail(app))
            app.kill_tree()
        except Exception as e:
            report["errors"] = [f"{type(e).__name__}: {e}"[:400]]
            try:
                (out_dir / "screen-at-end.txt").write_text(_screens_txt(app))
                (out_dir / "raw-output-tail.txt").write_text(_raw_tail(app))
                app.kill_tree()
            except Exception:
                pass
    finally:
        try:
            prod.reap(ctx)
        except Exception as e:  # sweep leftovers are themselves evidence
            report.setdefault("errors", []).append(f"reap: {e}"[:200])
        sweep_trial(ctx)
        shutil.rmtree(trial, ignore_errors=True)
    # the mock request log + settle evidence
    from bench.core.env import BenchLayout
    req_log = BenchLayout.from_config(cfg).harness_dir / "mock-script.json.requests.jsonl"
    if req_log.exists():
        lines = req_log.read_text(errors="replace").splitlines()
        (out_dir / "mock-requests.jsonl").write_text("\n".join(lines[-200:]))
    settle_jsonl = Path(cfg["results_dir"]) / "settle.jsonl"
    if settle_jsonl.exists():
        rows = [l for l in settle_jsonl.read_text().splitlines()
                if '"product": "%s"' % product_name in l
                or '"product":"%s"' % product_name in l]
        (out_dir / "settle-records.jsonl").write_text("\n".join(rows[-10:]))
    (out_dir / "report.json").write_text(json.dumps(report, indent=1))
    if mock:
        mock.terminate()
    print(json.dumps(report, indent=1))
    print(f"diagnose bundle: {out_dir}")
    return out_dir


def main() -> None:
    """Usage: python -m bench.drivers.diagnose <product>"""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("product")
    ap.add_argument("--config", default=None)
    args = ap.parse_args()
    cfg = load_config(args.config)
    reg = discover(cfg)
    diagnose(cfg, reg, args.product)


if __name__ == "__main__":
    main()
