"""Behavioral tests for NoGraphServer WorkshopInjection wiring and runtime-agnostic escalation."""
from __future__ import annotations

import threading
import time

import pytest

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


@pytest.mark.parametrize('initial,retry_status,expected_count', [
    ('delivered', 'delivered', 0),
    ('refused', 'delivered', 1),
    ('refused', 'failed', 4),
])
def test_delivery_recovery_stops_after_confirmation(tmp_path, monkeypatch, initial, retry_status, expected_count):
    monkeypatch.setenv("ARCHHUB_STATE_DIR", str(tmp_path / "state"))
    transport = _RecordingTransport()
    record = transport.inject
    def deliver(target, text, **options):
        result = record(target, text, **options)
        return {'status': retry_status, 'dispatch_attempted': retry_status == 'delivered'} if target['id'] == 'oc-worker-1' else result
    monkeypatch.setattr(transport, 'inject', deliver)

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
        workshop_mailbox.record_claim_outcome(history, msg["id"], target, "initial", initial)
        with history._transaction(write=True):
            workshop_mailbox._delivery_receipt(
                history, msg, recipient, "addressed", now=t0, via="workshop",
                runtime="opencode", native_session_id="oc-worker-1",
            )

        worker = workshop_mailbox.WorkshopInjection(owner="test", transport=transport)
        monkeypatch.setattr(worker, "_paused", lambda runtime, native_id: False)

        for elapsed in (65.0, 125.0, 245.0, 500.0):
            worker._watched_at = -1e9
            worker._watch(history, t0 + elapsed, declarations)

        assert len(transport.calls) == expected_count
        expected_steps = ('reminder', 'reminder:2', 'reminder:3') if expected_count == 4 else ('reminder',) if expected_count else ()
        for call, step in zip(transport.calls, expected_steps):
            assert call['target'] == {'app': 'opencode', 'id': 'oc-worker-1'}
            assert call['message_id'] == f"{msg['id']}:{step}"
        events = workshop_mailbox.delivery_events(history, msg)
        observed = {step for row in events.values() for step in row if step in workshop_mailbox.WATCH_STEPS}
        assert observed == set(expected_steps) | ({'escalated'} if expected_count == 4 else set())
        if expected_count == 4:
            escalation = transport.calls[-1]
            assert escalation['target'] == {'app': 'codex', 'id': 'cdx-coord-1'}
            assert escalation['message_id'].endswith(':escalation')
            assert 'has not answered Workshop message' in escalation['text']


def test_earlier_retry_confirmation_survives_later_legacy_failure(tmp_path, monkeypatch):
    monkeypatch.setenv('ARCHHUB_STATE_DIR', str(tmp_path / 'state'))
    target = {'session': 'opencode-worker-1', 'agent': 'Worker', 'runtime': 'opencode',
              'native_session_id': 'oc-worker-1'}
    declarations = [{**target, 'current': True}]
    t0 = time.time() - 600.0
    with workshop_mailbox.application_history() as history:
        message = history.append(workshop_mailbox.ROOM, author='Owner', content='To Worker:\nPlease report status?',
                                 category=workshop_mailbox.CATEGORY, idempotency_key='saved-confirmed-retry')
        for step, state, elapsed in [('initial', 'refused', 0), ('reminder', 'delivered', 65),
                                     ('reminder:2', 'refused', 125)]:
            assert workshop_mailbox.claim_delivery(history, message, target, step, 'watch', now=t0 + elapsed)[0]
            workshop_mailbox.record_claim_outcome(history, message['id'], target, step, state)
            if step == 'initial':
                workshop_mailbox._delivery_receipt(history, message, target, 'addressed', now=t0, via='workshop',
                    runtime=target['runtime'], native_session_id=target['native_session_id'])
            else:
                workshop_mailbox._delivery_receipt(history, message, target, step, now=t0 + elapsed,
                    via='workshop', status='delivered' if state == 'delivered' else 'failed',
                    dispatch_attempted=state == 'delivered')
    # Reopen the saved owner state as an upgrade would; preserve the earlier delivery proof.
    transport = _RecordingTransport()
    worker = workshop_mailbox.WorkshopInjection(owner='upgrade-test', transport=transport)
    monkeypatch.setattr(worker, '_paused', lambda runtime, native_id: False)
    with workshop_mailbox.application_history() as history:
        before = history._db.execute('SELECT MAX(sequence) FROM messages').fetchone()[0]
        for elapsed in (245.0, 500.0, 600.0):
            worker._watched_at = -1e9
            worker._watch(history, t0 + elapsed, declarations)
        assert not transport.calls, [call['message_id'] for call in transport.calls]
        assert history._db.execute('SELECT MAX(sequence) FROM messages').fetchone()[0] == before
