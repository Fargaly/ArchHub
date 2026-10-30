"""WSWATCH: stalled-delivery recovery, per-agent token cap, one activity row per action.
Real Workshop store and real router.sqlite, both inside the conftest-isolated profile."""
from contextlib import closing
from pathlib import Path
import sqlite3
import threading
import time
from types import SimpleNamespace

import pytest

from nodelang import agent_budget
from nodelang import workshop_mailbox as mail
from nodelang.application_server import ApplicationServer
from nodelang.conversation_history import ConversationHistoryStore
from nodelang.workshop_delivery_state import project_injection_delivery
from tests_replica.test_newapp_mailbox import peer


@pytest.fixture
def room(tmp_path):
    path = tmp_path / 'ROOM.sqlite3'
    with closing(sqlite3.connect(path, isolation_level=None, check_same_thread=False)) as db:
        with ConversationHistoryStore(path, instance_id='wswatch', connection=db) as history:
            history.ensure_conversation(mail.ROOM)
            owner = SimpleNamespace(mutation_lock=threading.RLock(),
                universal_store=SimpleNamespace(database_path=path),
                conversation_content=SimpleNamespace(_history=history, _require_live_owner=lambda: None))
            owner.shared_agent_mail = lambda method, body, **kw: ApplicationServer.shared_agent_mail(owner, method, body, **kw)
            yield owner


@pytest.fixture
def caps(monkeypatch):
    params = {**agent_budget.BUDGET_NODE['params'], 'caps': {}}
    monkeypatch.setitem(agent_budget.BUDGET_NODE, 'params', params)
    monkeypatch.setitem(mail.WATCH_NODE, 'params', {**mail.WATCH_NODE['params'], 'budget_cache_seconds': 0})
    return params['caps']


class Native:
    def __init__(self):
        self.turns = []

    def inject(self, recipient, text, **kw):
        self.turns.append((recipient, text, kw))
        return {'status': 'injected'}


def declare(owner, thread):
    return owner.shared_agent_mail('declare', {'task': 'WSWATCH court', 'paths': [str(Path.cwd() / thread)],
        'status': 'working', 'request_id': 'WSWATCH', 'context': {'threadId': thread}}, peer=peer())


def send(owner, text='Please reply here'):
    return owner.shared_agent_mail('send', {'to': 'codex', 'text': text,
        'context': {'claude/sessionID': 'claude-fixture'}}, peer=peer())


def events_of(message_id):
    with mail.application_history() as history:
        message = history.get(mail.ROOM, message_id, principal=mail.DELIVERY_AUTHOR)
        return mail.delivery_events(history, message)


def by_thread(message_id):
    return {records['addressed']['native_session_id']: records for records in events_of(message_id).values()
            if 'addressed' in records}


def activity():
    with mail.application_history() as history:
        history._db.execute(mail.ACTIVITY_SCHEMA)
        return [tuple(row) for row in history._db.execute(
            'SELECT actor, action, target FROM workshop_activity ORDER BY sequence')]


def usage(agent, message_id, tokens):
    return agent_budget.record_entries([{'type': 'assistant',  # no timestamp: counted now, inside the window
        'message': {'id': message_id, 'model': 'fixture', 'usage': {'input_tokens': tokens, 'output_tokens': 0}}}], agent)


def test_stalled_delivery_is_repushed_on_schedule_and_escalated_to_coordinator(room):
    declare(room, 'codex-fixture')
    native = Native()
    worker = mail.WorkshopInjection(room, native)
    note = send(room)
    t0 = time.time()
    worker.tick(now=t0)
    assert [kw['message_id'] for _r, _t, kw in native.turns] == [note['message_id'] + ':initial']
    schedule = [(30, None), (61, 'reminder'), (90, None), (125, 'reminder:2'), (245, 'reminder:3'), (485, 'escalated')]
    for offset, step in schedule:
        before = len(native.turns)
        worker.tick(now=t0 + offset)
        if step is None:
            assert len(native.turns) == before, 'no re-push before its retry step (%d s)' % offset
            continue
        assert len(native.turns) == before + 1, step
        target, text, kw = native.turns[-1]
        assert target == {'app': 'codex', 'id': 'codex-fixture'}
        assert kw['message_id'] == note['message_id'] + ':' + step
        assert 'Workshop follow-up #%d' % (mail.WATCH_STEPS.index(step) + 1) in text and 'Please reply here' in text
        assert step in by_thread(note['message_id'])['codex-fixture'], step
    state = project_injection_delivery(events_of(note['message_id']), addressed=True)['delivery'][0]
    assert state['reminded'] and state['escalated']
    with mail.application_history() as history:
        escalation = history._db.execute("SELECT content FROM messages WHERE idempotency_key LIKE "
            "'workshop-escalation:%'").fetchall()
    assert len(escalation) == 1
    header = escalation[0][0].split('\n', 1)[0]
    assert header.startswith('To 717') and 'founder' not in header.casefold() and 'ahmed' not in header.casefold()
    turns = len(native.turns)
    worker.tick(now=t0 + 600)
    worker.tick(now=t0 + 700)
    assert len(native.turns) == turns, 'every step runs once; the escalation note is never injected back'
    actions = [action for _actor, action, target in activity() if target == note['message_id']]
    assert actions == ['send', 'inject', 'reminder', 'reminder:2', 'reminder:3', 'escalated']


def test_answered_delivery_is_never_repushed(room):
    agent = declare(room, 'codex-fixture')
    native = Native()
    worker = mail.WorkshopInjection(room, native)
    note = send(room)
    t0 = time.time()
    worker.tick(now=t0)
    room.shared_agent_mail('send', {'to': 'claude-fixture', 'text': 'Answer.', 'reply_to': note['message_id'],
        'context': {'threadId': 'codex-fixture'}}, peer=peer())
    worker.tick(now=t0 + 5)
    assert 'answered' in by_thread(note['message_id'])['codex-fixture'], agent
    for offset in (61, 125, 245, 485):
        worker.tick(now=t0 + offset)
    assert len(native.turns) == 1


def test_capped_agent_pauses_alone_and_resumes_under_its_cap(room, caps):
    declare(room, 'codex-fixture')
    declare(room, 'codex-other')
    caps['codex:codex-fixture'] = 100
    usage('codex:codex-fixture', 'msg-a', 150)
    usage('codex:codex-other', 'msg-b', 150)  # same usage, no cap: never paused
    assert agent_budget.paused('codex:codex-fixture') and not agent_budget.paused('codex:codex-other')
    native = Native()
    worker = mail.WorkshopInjection(room, native)
    note = send(room)
    for _ in range(3):
        worker.tick()
    assert [target['id'] for target, _t, _kw in native.turns] == ['codex-other']
    held = by_thread(note['message_id'])['codex-fixture']
    assert 'paused' in held and 'attempt' not in held
    caps['codex:codex-fixture'] = 1000
    worker.tick()
    assert [target['id'] for target, _t, _kw in native.turns] == ['codex-other', 'codex-fixture']


def test_capped_composer_agent_is_refused_before_any_route(caps):
    from nodelang.model_router import ModelRouteRefused, composer_chat
    caps['BABOOM'] = 10
    usage('BABOOM', 'msg-c', 50)
    with pytest.raises(ModelRouteRefused) as refused:
        composer_chat({'prompt': 'hello', 'agent': 'BABOOM'})
    assert refused.value.reason_code == 'agent_paused'


def test_native_turn_usage_is_recorded_once_per_message_in_router_sqlite():
    entry = {'type': 'assistant', 'timestamp': '2026-10-30T09:00:00Z',
             'message': {'id': 'msg-1', 'model': 'claude-x',
                         'usage': {'input_tokens': 10, 'output_tokens': 5, 'cache_creation_input_tokens': 2,
                                   'cache_read_input_tokens': 999}}}
    agent_budget.record_entries([entry, entry, {'type': 'user'}], 'claude:session-1')
    agent_budget.record_entries([entry], 'claude:session-1')
    with closing(sqlite3.connect(agent_budget.router_database())) as db:
        rows = db.execute("SELECT agent, tokens, outcome FROM requests WHERE id='native:msg-1'").fetchall()
    assert rows == [('claude:session-1', 17, 'native-turn')]


def test_every_agent_mutation_writes_one_activity_row(room):
    declared = declare(room, 'codex-fixture')
    note = send(room, text='No reply needed. FYI only.')
    room.shared_agent_mail('seen', {'message_ids': [note['message_id']], 'channel': 'hook',
        'context': {'threadId': 'codex-fixture'}}, peer=peer())
    room.shared_agent_mail('read', {'since': 0, 'context': {'threadId': 'codex-fixture'}}, peer=peer())
    rows = activity()
    assert [action for _actor, action, _target in rows] == ['declare', 'send', 'seen'], 'reads are not actions'
    assert rows[0][0] == declared['sender'] and rows[1][2] == note['message_id']
