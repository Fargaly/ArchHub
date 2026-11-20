"""Behavioral tests for NoGraphServer WorkshopInjection wiring and runtime-agnostic escalation."""
from __future__ import annotations

import threading
import time

from nodelang import nograph_server, workshop_mailbox, workshop_tasks


class _RecordingTransport:
    def __init__(self):
        self.calls = []

    def inject(self, target, text, *, message_id, timeout_seconds=10.0, cancel_event=None):
        self.calls.append({"target": dict(target), "text": text, "message_id": message_id})
        return {"status": "delivered", "dispatch_attempted": True}

    def close(self):
        pass


def test_nograph_server_starts_and_stops_workshop_injection(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHHUB_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("ARCHHUB_DISABLE_WORKSHOP_WATCH", raising=False)
    monkeypatch.setattr(nograph_server.NoGraphServer, "_warm_after_listen", lambda self: None)
    monkeypatch.setattr(nograph_server, "_refresh_opencode_plugin", lambda state_dir: None)

    transport = _RecordingTransport()
    monkeypatch.setattr(workshop_mailbox, "_local_transport", lambda env=None: transport)

    server = nograph_server.NoGraphServer(tmp_path / "state", port=0, agent_source=lambda: [])
    server.start()
    try:
        worker = server.workshop_injection
        assert isinstance(worker, workshop_mailbox.WorkshopInjection)
        assert worker._thread is not None and worker._thread.is_alive()
        assert any(t.name == "archhub-workshop-injection" and t.is_alive() for t in threading.enumerate())
    finally:
        server.close()

    assert server.workshop_injection is None
    assert not worker._thread.is_alive()
    assert not any(t.name == "archhub-workshop-injection" and t.is_alive() for t in threading.enumerate())


def test_nograph_server_respects_disable_workshop_watch_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHHUB_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("ARCHHUB_DISABLE_WORKSHOP_WATCH", "1")
    monkeypatch.setattr(nograph_server.NoGraphServer, "_warm_after_listen", lambda self: None)
    monkeypatch.setattr(nograph_server, "_refresh_opencode_plugin", lambda state_dir: None)

    server = nograph_server.NoGraphServer(tmp_path / "state", port=0, agent_source=lambda: [])
    server.start()
    try:
        assert server.workshop_injection is None
    finally:
        server.close()


def test_unanswered_message_auto_chases_and_escalates_to_active_coordinator_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHHUB_STATE_DIR", str(tmp_path / "state"))
    transport = _RecordingTransport()

    with workshop_mailbox.application_history() as history:
        declarations = [
            {
                "current": True,
                "runtime": "codex",
                "session": "codex-coord-1",
                "native_session_id": "cdx-coord-1",
                "agent": "Codex Coord",
            },
            {
                "current": True,
                "runtime": "opencode",
                "session": "opencode-worker-1",
                "native_session_id": "oc-worker-1",
                "agent": "Worker",
            },
        ]
        assert workshop_tasks.claim_coordinator_seat(history, "codex-coord-1", "Codex Coord", lease_seconds=600)

        t0 = time.time() - 600.0
        msg = history.append(
            workshop_mailbox.ROOM,
            author="Codex Coord [codex-coord-1]",
            content="To Worker:\nPlease report status?",
            category=workshop_mailbox.CATEGORY,
            idempotency_key="test-auto-chase-1",
        )
        recipient = {"session": "opencode-worker-1", "agent": "Worker"}
        target = {
            "session": "opencode-worker-1",
            "agent": "Worker",
            "runtime": "opencode",
            "native_session_id": "oc-worker-1",
        }
        assert workshop_mailbox.claim_delivery(history, msg, target, "initial", "watch", now=t0)[0]
        workshop_mailbox.record_claim_outcome(history, msg["id"], target, "initial", "delivered")
        with history._transaction(write=True):
            workshop_mailbox._delivery_receipt(
                history, msg, recipient, "addressed", now=t0, via="workshop",
                runtime="opencode", native_session_id="oc-worker-1",
            )

        worker = workshop_mailbox.WorkshopInjection(owner="test", transport=transport)
        monkeypatch.setattr(worker, "_paused", lambda runtime, native_id: False)

        # 1) Retry follow-ups (reminder, reminder:2, reminder:3) at 60/120/240s, then 4) escalation at 480s
        for elapsed in (65.0, 125.0, 245.0, 500.0):
            worker._watched_at = -1e9
            assert worker._watch(history, t0 + elapsed, declarations) is True

        # First 3 pushes are retries to the unanswered opencode worker
        assert len(transport.calls) == 4
        for idx, step in enumerate(("reminder", "reminder:2", "reminder:3")):
            assert transport.calls[idx]["target"] == {"app": "opencode", "id": "oc-worker-1"}
            assert transport.calls[idx]["message_id"] == f"{msg['id']}:{step}"

        # 4th push is escalation to the active seat-coordinator using its actual runtime ("codex", not "claude")
        esc = transport.calls[3]
        assert esc["target"] == {"app": "codex", "id": "cdx-coord-1"}
        assert esc["message_id"].endswith(":escalation")
        assert "has not answered Workshop message" in esc["text"]
