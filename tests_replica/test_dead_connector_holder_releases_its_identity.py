"""A connector that died must not lock its own replacement out for the lease.

Founder 2026-09-30: the coordination connector never came back after a restart.
A replacement process for the same agent session was refused with "runtime Agent
Session identity is already bound; renew it instead" until the dead process's
15-minute lease ran out, because the bound check looked only at expiry. The
holder is the exact recorded OS process (pid + creation time); once it is gone
the binding holds nothing, unless work of that session is still unsettled.
"""
import subprocess
import sys
import threading
import time

import psutil
import pytest

from nodelang import application_server as server_module
from nodelang.application_server import ApplicationServer

RUNTIME, ENTRY, CUSTODY, FINGERPRINT = "claude-code", "entry:1", "custody:1", "fp:1"


def _server(bindings, *, active=None):
    server = ApplicationServer.__new__(ApplicationServer)
    server._machine_agent_session_lock = threading.RLock()
    server._machine_agent_sessions = dict(bindings)
    server._machine_agent_active_requests = dict(active or {})
    server.universal_store = type("Store", (), {"snapshot": lambda self: object()})()
    server.universal_registry = type("Registry", (), {"cde_write_authority_protocol": object()})()
    return server


def _binding(peer):
    return {"enrollment_peer": peer, "token": "t", "runtime": RUNTIME, "catalog_entry": ENTRY,
            "device_custody": CUSTODY, "external_session_fingerprint": FINGERPRINT,
            "issued_at": time.time(), "expires_at": time.time() + 900}


def _bound(server):
    return server._machine_agent_identity_is_currently_bound(
        runtime=RUNTIME, catalog_entry_root=ENTRY, custody_root=CUSTODY,
        external_session_fingerprint=FINGERPRINT)


def _peer_of(pid):
    return {"pid": pid, "created_at": psutil.Process(pid).create_time()}


@pytest.fixture
def no_permits(monkeypatch):
    import nodelang.native_session_release as release
    monkeypatch.setattr(release, "_has_pending_permit", lambda *a: False)


@pytest.fixture
def dead_peer():
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    peer = _peer_of(child.pid)
    child.wait()
    return peer


def test_a_dead_holder_no_longer_binds_the_identity(no_permits, dead_peer):
    server = _server({"session:a": _binding(dead_peer)})
    assert _bound(server) is False
    assert "session:a" not in server._machine_agent_sessions


def test_a_live_holder_still_binds_the_identity(no_permits):
    assert _bound(_server({"session:a": _binding(_peer_of(psutil.Process().pid))})) is True


def test_a_reused_pid_is_not_the_holder(no_permits):
    me = _peer_of(psutil.Process().pid)
    stale = {"pid": me["pid"], "created_at": me["created_at"] - 1000.0}
    assert _bound(_server({"session:a": _binding(stale)})) is False


def test_an_unknown_holder_stays_bound(no_permits):
    assert _bound(_server({"session:a": _binding(None)})) is True


def test_a_request_in_flight_keeps_a_dead_holder_bound(no_permits, dead_peer):
    assert _bound(_server({"session:a": _binding(dead_peer)}, active={"session:a": 1})) is True


def test_an_unsettled_permit_keeps_a_dead_holder_bound(monkeypatch, dead_peer):
    import nodelang.native_session_release as release
    monkeypatch.setattr(release, "_has_pending_permit", lambda *a: True)
    assert _bound(_server({"session:a": _binding(dead_peer)})) is True


def test_the_server_imports_the_identity_comparison():
    assert server_module.peer_matches_process is not None


def _bound_conditional(server):
    # Conditional continuation calls the check without pruning.
    return server._machine_agent_identity_is_currently_bound(
        runtime=RUNTIME, catalog_entry_root=ENTRY, custody_root=CUSTODY,
        external_session_fingerprint=FINGERPRINT, prune_expired=False)


def test_the_conditional_continuation_path_also_releases_a_dead_holder(no_permits, dead_peer):
    server = _server({"session:a": _binding(dead_peer)})
    assert _bound_conditional(server) is False
    # Without pruning the record itself is kept; it just holds nothing.
    assert "session:a" in server._machine_agent_sessions


def test_the_conditional_path_keeps_a_live_holder_bound(no_permits):
    assert _bound_conditional(_server({"session:a": _binding(_peer_of(psutil.Process().pid))})) is True


@pytest.mark.parametrize("peer", [
    {"pid": None, "created_at": 1.0},
    {"pid": 0, "created_at": 1.0},
    {"created_at": 1.0},
    {"pid": 123},
    "not-a-dict",
])
def test_a_malformed_record_is_never_proof_the_holder_is_gone(no_permits, peer):
    assert _bound(_server({"session:a": _binding(peer)})) is True


def test_a_live_pid_with_a_malformed_timestamp_stays_bound(no_permits):
    pid = psutil.Process().pid
    for created_at in (None, "x", float("nan"), float("inf"), -1.0, 0):
        assert _bound(_server({"session:a": _binding({"pid": pid, "created_at": created_at})})) is True


def test_an_extra_key_in_the_record_stays_bound(no_permits, dead_peer):
    assert _bound(_server({"session:a": _binding({**dead_peer, "extra": 1})})) is True


def test_access_denied_on_the_holder_stays_bound(no_permits, dead_peer, monkeypatch):
    def denied(pid):
        raise psutil.AccessDenied(pid)
    monkeypatch.setattr(psutil, "Process", denied)
    assert _bound(_server({"session:a": _binding(dead_peer)})) is True


def test_without_psutil_the_holder_stays_bound(no_permits, dead_peer, monkeypatch):
    import builtins
    real = builtins.__import__
    def fake(name, *a, **k):
        if name == "psutil":
            raise ImportError("no psutil")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", fake)
    assert _bound(_server({"session:a": _binding(dead_peer)})) is True


def test_a_permit_check_that_errors_keeps_a_dead_holder_bound(monkeypatch, dead_peer):
    import nodelang.native_session_release as release
    def broken(*a):
        raise RuntimeError("store unavailable")
    monkeypatch.setattr(release, "_has_pending_permit", broken)
    assert _bound(_server({"session:a": _binding(dead_peer)})) is True
