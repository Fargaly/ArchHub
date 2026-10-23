"""WSNOREPLY: real mailbox/receipt paths, isolated native injection recorder."""
from datetime import datetime
import json

import pytest

from nodelang import workshop_mailbox as mail
from tests_replica.test_newapp_mailbox import peer
from tests_replica.test_wsinject import NativeFixture, declare, send

pytest_plugins = ('tests_replica.test_wsinject',)


def message(history, note):
    return history.get(mail.ROOM, note['message_id'], principal='court')


def start(owner, history, note, native):
    worker = mail.WorkshopInjection(owner, native)
    owner.workshop_injection = worker
    now = datetime.fromisoformat(message(history, note)['created_at']).timestamp()
    worker.tick(now=now)
    return worker, now


def assert_not_chased(owner, history, note, native, now):
    # Restart at each boundary: in-memory settlement must not be the protection.
    for elapsed in (299, 300, 599, 600, 601, 1200):
        mail.WorkshopInjection(owner, native).tick(now=now + elapsed)
    turns = [turn for turn in native.turns if turn[2]['message_id'].startswith(note['message_id'] + ':')]
    assert len(turns) == 1, 'a non-asking note must be injected once, never reminded'
    events = mail.delivery_events(history, message(history, note))
    assert all('reminder' not in row and 'escalated' not in row for row in events.values())
    assert history._db.execute("SELECT count(*) FROM messages WHERE reply_to=? AND author='Workshop coordination'",
        (note['message_id'],)).fetchone()[0] == 0
    assert 'Reply through MCP' not in turns[0][1], 'an FYI must not instruct the recipient to reply'


@pytest.mark.parametrize('text', ['No reply needed', 'NO REPLY REQUIRED.',
    'Result is ready.\n  nO rEpLy NeEdEd!  ', 'Status update.\r\nNo reply required\r\n'])
def test_explicit_no_reply_delivered_once_without_followup(room, text):
    owner, history = room
    declare(owner, {'threadId':'codex-fixture'})
    note = send(owner, text=text)
    native = NativeFixture()
    _worker, now = start(owner, history, note, native)
    assert_not_chased(owner, history, note, native, now)
    assert message(history, note)['content'] == 'To codex:\n' + text


@pytest.mark.parametrize('text', ['ACK', 'Acknowledged.', 'Received', 'Noted.',
    'Understood', 'Thanks!', 'Thank you.', 'Got it.', 'Done.', 'Confirmed.'])
def test_reply_acknowledgement_is_delivered_without_followup(room, text):
    owner, history = room
    declare(owner, {'threadId':'codex-fixture'})
    declare(owner, {'claude/sessionID':'claude-fixture'})
    ask = send(owner)
    native = NativeFixture()
    worker, now = start(owner, history, ask, native)
    reply = owner.shared_agent_mail('send', {'to':'claude', 'text':text,
        'reply_to':ask['message_id'], 'context':{'threadId':'codex-fixture'}}, peer=peer())
    worker.tick(now=now)
    assert_not_chased(owner, history, reply, native, now)
    assert any('answered' in row for row in mail.delivery_events(history, message(history, ask)).values())


@pytest.mark.parametrize('text,reply', [('Can you review the patch?', False),
    ('ACK. Can you review the patch?', True), ('Can you confirm?', True),
    ('The phrase no reply needed appears in the quoted brief; can you review?', False),
    ('> No reply required\nCan you confirm?', False),
    ('No reply needed unless the court fails; can you check?', False),
    ('ACK', False)])
def test_real_ask_keeps_five_and_ten_minute_followup(room, text, reply):
    owner, history = room
    declare(owner, {'threadId':'codex-fixture'})
    parent = history.append(mail.ROOM, author='Fixture asker', category=mail.CATEGORY,
        content='To claude:\nOriginal ask', idempotency_key='parent-ask') if reply else None
    note = send(owner, text=text, **({'reply_to':parent['id']} if parent else {}))
    native = NativeFixture()
    worker, now = start(owner, history, note, native)
    worker.tick(now=now + 299)
    assert len(native.turns) == 1
    worker.tick(now=now + 300)
    assert len(native.turns) == 2 and native.turns[-1][2]['message_id'] == note['message_id'] + ':reminder'
    worker.tick(now=now + 599)
    assert not any('escalated' in row for row in mail.delivery_events(history, message(history, note)).values())
    worker = mail.WorkshopInjection(owner, native)
    worker.tick(now=now + 600)
    worker.tick(now=now + 601)
    events = mail.delivery_events(history, message(history, note))
    assert any('escalated' in row for row in events.values())
    assert len(native.turns) == 2
    assert history._db.execute("SELECT count(*) FROM messages WHERE reply_to=? AND author='Workshop coordination'",
        (note['message_id'],)).fetchone()[0] == 1


def test_coordinator_fallback_never_injects_its_own_to_717_note(room):
    owner, history = room
    context = {'claude/sessionID':'coordinator-fixture'}
    declare(owner, context)
    class Coordinator(NativeFixture):
        def discover(self, **_kw):
            return {'recipients':[{'title':'717 coordinator (live)', 'id':'coordinator-fixture'}]}
    native = Coordinator()
    note = owner.shared_agent_mail('send', {'to':'717', 'text':'Own coordinator update', 'context':context}, peer=peer())
    worker, now = start(owner, history, note, native)
    for elapsed in (300, 600, 601):
        worker.tick(now=now + elapsed)
    assert native.turns == [], 'coordinator fallback must apply the sender exclusion too'
    assert all('attempt' not in row and 'reminder' not in row and 'escalated' not in row
        for row in mail.delivery_events(history, message(history, note)).values())


def test_self_addressed_note_still_reaches_other_recipient(room):
    owner, history = room
    declare(owner, {'threadId':'codex-fixture'})
    declare(owner, {'claude/sessionID':'claude-fixture'})
    note = send(owner, to='claude, codex', text='No reply needed')
    native = NativeFixture()
    _worker, now = start(owner, history, note, native)
    assert_not_chased(owner, history, note, native, now)
    assert [turn[0]['id'] for turn in native.turns] == ['codex-fixture']


def test_no_reply_note_waits_for_a_late_recipient_without_chasing(room):
    owner, history = room
    note = send(owner, text='No reply needed')
    native = NativeFixture()
    worker, now = start(owner, history, note, native)
    worker.tick(now=now + 1)
    assert native.turns == []
    declare(owner, {'threadId':'codex-fixture'})
    worker.tick(now=now + 2)
    assert len(native.turns) == 1, 'the running worker must retain unresolved FYIs until declaration'
    assert_not_chased(owner, history, note, native, now + 2)
    assert [turn[0]['id'] for turn in native.turns] == ['codex-fixture']


@pytest.mark.parametrize('receipt', [False, True])
def test_recorded_sender_route_never_returns_through_native_or_pending(room, receipt):
    owner, history = room
    context = {'threadId':'codex-fixture'}
    sender = declare(owner, context)
    recipient = sender['declaration']
    routing = {'recipients':[{key:recipient.get(key) for key in
        ('session', 'agent', 'runtime', 'native_session_id')}], 'native_control':None}
    encoded = json.dumps(routing)
    saved = history.append(mail.ROOM, author=sender['sender'], category=mail.CATEGORY,
        content='To codex:\nOwn saved route', idempotency_key='saved-self',
        evidence=[mail.ROUTING_EVIDENCE, *(encoded[i:i+512] for i in range(0, len(encoded), 512))])
    if receipt:
        mail._delivery_receipt(history, saved, recipient, 'addressed',
            runtime=recipient['runtime'], native_session_id=recipient['native_session_id'])
    native = NativeFixture()
    worker, now = start(owner, history, {'message_id':saved['id']}, native)
    worker.tick(now=now + 300)
    worker.tick(now=now + 600)
    assert native.turns == []
    pending = owner.shared_agent_mail('pending', {'context':context}, peer=peer())
    assert pending['pending'] == [], 'saved self-addressing must not attach the sender note to MCP results'


def test_coordinator_self_note_never_returns_through_pending(room):
    owner, history = room
    context = {'claude/sessionID':'coordinator-fixture'}
    declare(owner, context)
    class Coordinator(NativeFixture):
        def discover(self, **_kw):
            return {'recipients':[{'title':'717 coordinator (live)', 'id':'coordinator-fixture'}]}
    note = owner.shared_agent_mail('send', {'to':'717', 'text':'Own update', 'context':context}, peer=peer())
    start(owner, history, note, Coordinator())
    assert owner.shared_agent_mail('pending', {'context':context}, peer=peer())['pending'] == []
