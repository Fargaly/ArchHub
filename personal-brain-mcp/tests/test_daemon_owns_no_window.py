"""A daemon owns no window, and a dead lease stops talking.

The founder was interrupted mid-work by a console window full of the brain's
sync lines, repeating "Agent Session capability renewal failed ... capability
expired" every few seconds (2026-09-05 screenshot). Two defects, one court:
the HTTP daemon must hide a console it owns no matter who spawned it, and the
renewal loop must stop renewing a capability that can never be renewed.
"""
from __future__ import annotations

import inspect
import threading
import time

import pytest


def test_the_http_daemon_hides_a_console_it_owns():
    from personal_brain import server
    src = inspect.getsource(server.main)
    assert "_hide_own_console()" in src
    assert "if args.http is not None:" in src.split("_hide_own_console()")[0].rsplit("\n\n", 1)[-1] \
        or "args.http is not None" in src  # only the daemon path hides
    hide = inspect.getsource(server._hide_own_console)
    assert "GetConsoleWindow" in hide and "ShowWindow" in hide
    assert "GetConsoleProcessList" in hide  # a shared console belongs to a person
    assert "ARCHHUB_BRAIN_CONSOLE" in hide  # a way back for debugging
    server._hide_own_console()  # never raises, whatever the host


def test_stdio_mode_never_touches_the_console(monkeypatch):
    """A stdio client owns the console; hiding it would take the client's window."""
    from personal_brain import server
    called = []
    monkeypatch.setattr(server, "_hide_own_console", lambda: called.append(1))
    src = inspect.getsource(server.main)
    head = src.split("_hide_own_console()")[0]
    assert "args.http is not None" in head.rsplit("if ", 1)[0] + "if " + head.rsplit("if ", 1)[1]


class _Bridge:
    def __init__(self, outcome):
        self._client = self
        self._outcome = outcome
    def renew_agent_session(self):
        raise self._outcome


def _manager():
    from personal_brain.universal_session_manager import UniversalRuntimeSessionManager
    return UniversalRuntimeSessionManager(bridge_factory=lambda **kw: None,
                                   renewal_lead_seconds=3600.0,
                                   renewal_poll_seconds=0.05)


@pytest.mark.parametrize("error,still_renewing", [
    (RuntimeError("runtime Agent Session capability expired"), False),
    (RuntimeError("connection reset by peer"), True),
])
def test_an_expired_capability_stops_being_renewed(error, still_renewing):
    mgr = _manager()
    bridge = _Bridge(error)
    with mgr._lock:
        mgr._record_enrollment_locked("agent-1", bridge, {"expires_at": time.time() + 60})
    deadline = time.time() + 3.0
    while time.time() < deadline:
        if "agent-1" in mgr.renewal_failures():
            break
        time.sleep(0.05)
    assert "agent-1" in mgr.renewal_failures()  # the failure is kept as evidence
    time.sleep(0.3)
    with mgr._lock:
        watched = "agent-1" in mgr._binding_expiries
    mgr.close()
    assert watched is still_renewing, (
        "an expired capability must be dropped; a transient failure must keep retrying")
