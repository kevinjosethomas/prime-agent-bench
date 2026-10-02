"""fd-stability: PTY sessions must not leak file descriptors.

A wave chain runs hundreds of launches in ONE process; a leaked master fd
per session is a deterministic EMFILE at the sandbox fd cap. The
2026-10-01 campaign's first wave died exactly there (~530 trials in,
Errno 24 on a rust warm-start launch)."""
import os

import pytest

from bench.adapters.terminals.pty import PTYDriver, PTYSession

pytestmark = pytest.mark.skipif(not os.path.isdir("/proc/self/fd"),
                                reason="the harness targets Linux")


def _nfd() -> int:
    return len(os.listdir("/proc/self/fd"))


def test_noop_control_does_not_leak_fds():
    driver = PTYDriver(cfg={})
    driver.noop_control(rounds=2)  # settle pyte/select first-use state
    before = _nfd()
    driver.noop_control(rounds=12)
    assert _nfd() <= before


def test_kill_tree_closes_the_master():
    before = _nfd()
    for _ in range(16):
        app = PTYSession(["cat"])
        app.kill_tree()
    assert _nfd() <= before
    assert app.master == -1  # the last one closed, not just gc-cleaned


def test_failed_spawn_closes_the_master(monkeypatch):
    before = _nfd()
    for _ in range(4):
        with pytest.raises(OSError):
            PTYSession(["/nonexistent/binary-xyz"])
    assert _nfd() <= before

