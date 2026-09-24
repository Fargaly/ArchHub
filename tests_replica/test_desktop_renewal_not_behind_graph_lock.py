"""Court: the desktop session renewal never waits behind unrelated graph work.

Observed on the founder's installed build 20260924-1255-4d88456 (py-spy, 2026-09-24):
``GET /api/universal/baboom-native-frame`` holds ``mutation_lock`` while it
builds three projections; the launcher's one-minute ``POST
/api/universal/browser-handoff`` waited for the same lock inside
``_dispatch_universal_machine_route`` and its 5 s caller bound expired, so
launcher.log alternated ``MachineTransportError[no_response] after 5.0s`` and
``ready``. The server time of ``dispatch`` is exactly the client's wait.

A fresh desktop session needs no graph write, so its renewal must answer while
another request holds the lock. A renewal that does write must still take the
lock and commit only after the holder leaves.
"""
from dataclasses import replace
import sys
import threading
import time
from pathlib import Path
from uuid import uuid4

import pytest

from nodelang.application_server import ApplicationServer
from tests_replica.test_universal_workshop_assignments import _green_runtime_compliance

_CLIENT_BOUND_SECONDS = 5.0  # launch_archhub_test._renew_desktop_session


def _handoff_request():
    return {"runtime_id": "renewal-lock-fixture", "request_id": uuid4().hex,
            "method": "POST", "path": "/api/universal/browser-handoff",
            "body": {}, "session": {}}


@pytest.fixture
def server(tmp_path, monkeypatch):
    from nodelang import application_machine_transport as transport
    from nodelang import application_server as app
    root = Path(transport.__file__).resolve().parents[1]
    peer = transport.MachinePipePeer(12345, 100.0, str(Path(sys.executable).resolve()),
        (sys.executable, str(root / "launch_archhub_test.py")), str(root))
    monkeypatch.setattr(transport, "_observe_machine_process", lambda pid: peer if pid == peer.pid else None)
    monkeypatch.setattr(app, "_verified_machine_pipe_peer", lambda request: peer)
    owner = ApplicationServer(
        universal_workspace_root=tmp_path,
        conversation_history_path=tmp_path / "content.sqlite3",
        runtime_compliance_runner=_green_runtime_compliance,
        enable_machine_transport=False, enable_machine_projection_prewarm=False,
    )
    try:
        yield owner
    finally:
        owner.close()


def _renew_while_lock_is_held(server, wait_seconds):
    """Hold mutation_lock in another thread, as the native frame does, and renew."""
    outcome = {}
    held, release = threading.Event(), threading.Event()

    def holder():
        with server.mutation_lock:
            held.set()
            release.wait(30)

    def renewal():
        started = time.monotonic()
        try:
            outcome["result"] = server._dispatch_verified_machine_route(_handoff_request())
        except BaseException as exc:  # reported by the assertion below
            outcome["error"] = exc
        outcome["seconds"] = time.monotonic() - started

    lock_thread = threading.Thread(target=holder, daemon=True)
    lock_thread.start()
    assert held.wait(5)
    worker = threading.Thread(target=renewal, daemon=True)
    worker.start()
    worker.join(wait_seconds)
    answered_while_held = not worker.is_alive()
    revision_while_held = server.universal_store.revision
    release.set()
    lock_thread.join(10)
    worker.join(30)
    assert not worker.is_alive(), "renewal never finished after the lock was released"
    return answered_while_held, revision_while_held, outcome


def test_fresh_desktop_renewal_answers_while_graph_work_holds_the_lock(server):
    # Warm once so the measured call is the steady one-minute renewal.
    server._dispatch_verified_machine_route(_handoff_request())
    revision = server.universal_store.revision
    answered, _, outcome = _renew_while_lock_is_held(server, _CLIENT_BOUND_SECONDS / 2)
    assert "error" not in outcome, outcome.get("error")
    assert answered, (
        "desktop renewal waited %.1fs behind mutation_lock; the launcher's %.0fs "
        "bound logs MachineTransportError[no_response]" % (outcome["seconds"], _CLIENT_BOUND_SECONDS))
    assert outcome["result"]["one_use"] is True
    assert outcome["result"]["session_root"] == server.browser_session_root
    assert server.universal_store.revision == revision  # no graph write on the fresh path


def test_due_desktop_renewal_still_writes_only_under_the_lock(server):
    authority = server.universal_registry.authorization
    digest = server._browser_token_digest(server.browser_session_token)
    binding = server._browser_sessions[digest]
    now = time.time()
    # The held context is inside the renewal lead window but still valid, so
    # the renewal must write (graph cells or lease storage, whichever is held).
    with authority.broker._lock:
        prior = authority.broker._entries[binding.context]
        authority.broker._entries[binding.context] = replace(prior, expires_at=now + 20)
    answered, _, outcome = _renew_while_lock_is_held(server, 1.0)
    assert "error" not in outcome, outcome.get("error")
    assert not answered, "a renewal that writes must wait for mutation_lock"
    renewed = server._browser_sessions[digest]
    assert renewed.session_root == binding.session_root
    assert renewed.context is not binding.context
    assert authority.broker.resolve(renewed.context).expires_at > now + 60
