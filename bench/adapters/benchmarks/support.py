"""Shared scenario helpers: onboarding walks, first paint, screen hashing.

Every scenario composes these over the driver-agnostic Session surface.
"""
from __future__ import annotations

import hashlib
import time

from bench.core.harness import HarnessDriver, Session, now
from bench.core.product import DialogStep, ProductAdapter, TrialContext
from bench.core.process import sweep_trial

PROBE_TOKEN = "Zq7x"


def first_paint(session: Session, timeout: float = 45.0) -> float:
    """Block until the first non-blank rendered frame; returns its timestamp."""
    deadline = now() + timeout
    while now() < deadline:
        if session.t_first_paint is not None:
            return session.t_first_paint
        time.sleep(0.001)
    raise TimeoutError("no first paint")


def screen_hash(session: Session) -> str:
    """A short hash of the rendered screen (stability detection)."""
    return hashlib.sha256(session.screen_text().encode()).hexdigest()[:16]


def drive_to_ready(session: Session, steps: list[DialogStep], timeout: float,
                   probe: str, pacing: dict) -> str:
    """Answer known onboarding dialogs (dialogs first, probes second) until
    the editor echoes the probe token (ready). Returns "ready"."""
    answers = {}
    key_pause = float(pacing.get("key_pause_s", 0.7))
    loop_s = float(pacing.get("loop_s", 0.8))
    echo_wait = float(pacing.get("echo_wait_s", 1.2))
    deadline = now() + timeout
    while now() < deadline:
        txt = session.screen_text()
        answered = False
        for marker, keys in steps:
            if marker in txt and answers.get(marker, 0) < 3:
                answers[marker] = answers.get(marker, 0) + 1
                for k in keys:
                    session.send(k)
                    time.sleep(key_pause)
                answered = True
                break
        if not answered:
            session.start_echo_watch(probe)
            session.send(probe)
            try:
                session.wait_echo(echo_wait)
                return "ready"
            except TimeoutError:
                pass
        time.sleep(loop_s)
    raise TimeoutError(f"settle walk never reached ready; dialogs answered: {answers}")


def prepass(product: ProductAdapter, ctx: TrialContext, driver: HarnessDriver) -> None:
    """One onboarding-consumption launch on the trial home (claude/codex:
    their first-run dialogs re-appear unless walked in-place). The prepass is
    NOT part of any measurement; the measured launch follows on the same
    home."""
    app = product.launch(ctx, driver)
    try:
        first_paint(app, timeout=60)
        drive_to_ready(app, product.dialog_steps, timeout=150,
                       probe="Zq7prep01", pacing={})
    finally:
        app.kill_tree()
        sweep_trial(ctx)
