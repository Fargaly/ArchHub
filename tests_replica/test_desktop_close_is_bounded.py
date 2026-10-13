"""Founder 2026-10-13: the window X must end the app.

RED before the fix: DesktopRuntime.close() waited up to 60 s for in-flight
requests, so a long poll held the process after the window closed (PM rig CL:
"app still running 10.1 s after WM_CLOSE").
"""
import time

from nodelang import desktop
from nodelang.runtime_gateway import GatewayUnavailable


def _runtime_class():
    for value in vars(desktop).values():
        if isinstance(value, type) and hasattr(value, "close") and hasattr(value, "handoff"):
            return value
    raise AssertionError("desktop runtime class not found")


class _NeverDrainsGate:
    def __init__(self):
        self.backend = type("B", (), {"generation": 7})()
        self.timeouts = []

    def begin_drain(self, generation, *, timeout=30.0):
        self.timeouts.append(timeout)
        time.sleep(min(float(timeout), 30.0))
        raise GatewayUnavailable("runtime drain timed out")


class _Gateway:
    def __init__(self):
        self.gate = _NeverDrainsGate()
        self.closed = False

    def close(self):
        self.closed = True


class _Server:
    def __init__(self):
        self.closed = False

    def close(self, **_):
        self.closed = True


def test_close_returns_within_seconds_when_a_request_never_drains(monkeypatch):
    # The watchdog must not end the test process.
    monkeypatch.setattr(desktop.os, "_exit", lambda code=0: None)
    cls = _runtime_class()
    fake = cls.__new__(cls)
    fake.server = _Server()
    fake.gateway = _Gateway()
    started = time.monotonic()
    cls.close(fake)
    elapsed = time.monotonic() - started
    assert elapsed < 5.0, "close() waited %.1fs for an in-flight request" % elapsed
    assert fake.gateway.gate.timeouts and max(fake.gateway.gate.timeouts) <= 2.0
    assert fake.server.closed and fake.gateway.closed
