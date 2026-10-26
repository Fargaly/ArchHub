"""NOBLOCK: elapsed silence stays visible without creating another session turn."""
import json
import time

import pytest

from nodelang import workshop_mailbox as mail
from tests_replica.test_newapp_mailbox import peer
from tests_replica.test_wsinject import NativeFixture, declare, send

pytest_plugins = ('tests_replica.test_wsinject',)


@pytest.mark.parametrize('read_first', [False, True])
def test_unanswered_message_is_delivered_once_and_only_waits(room, read_first):
    owner, history = room
    context = {'threadId': 'codex-fixture'}
    recipient = declare(owner, context)
    native = NativeFixture()
    worker = mail.WorkshopInjection(owner, native)
    owner.workshop_injection = worker
    note = send(owner, text='Please review this patch and reply here.')
    started = time.time()
    worker.tick(now=started)
    assert len(native.turns) == 1
    assert native.turns[0][2]['message_id'] == note['message_id'] + ':initial'
    if read_first:
        owner.shared_agent_mail('read', {'since': note['sequence'], 'context': context}, peer=peer())
        worker.tick(now=started + 1)
    for elapsed in (299, 300, 301, 599, 600, 601, 1200):
        if elapsed == 599:
            worker = mail.WorkshopInjection(owner, native)
            owner.workshop_injection = worker
        worker.tick(now=started + elapsed)
    message = history.get(mail.ROOM, note['message_id'], principal=mail.DELIVERY_AUTHOR)
    events = mail.delivery_events(history, message)
    receipts = events[recipient['sender_key']]
    followups = [key for key in receipts if 'reminder' in key or 'escalat' in key]
    nags = history._db.execute("SELECT count(*) FROM messages WHERE author='Workshop coordination' "
        "OR idempotency_key LIKE 'workshop-escalation:%'").fetchone()[0]
    page = owner.shared_agent_mail('read', {'since': 0, 'context': context}, peer=peer())
    visible = next(row for row in page['messages'] if row['id'] == note['message_id'])
    print(json.dumps({'read_first': read_first, 'native_injections': len(native.turns),
        'followup_receipts': followups, 'escalation_messages': nags,
        'waiting_state': visible['state']}, sort_keys=True))
    assert len(native.turns) == 1, 'elapsed silence must never inject another native turn'
    assert followups == [], 'elapsed silence must never write reminder/escalation receipts'
    assert nags == 0, 'elapsed silence must never append a coordinator nag'
    assert visible['state'] == ('delivered' if read_first else 'pending')
    assert 'answered' not in receipts
    owner.shared_agent_mail('send', {'to': 'claude-fixture', 'text': 'Reviewed; complete.',
        'reply_to': note['message_id'], 'context': context}, peer=peer())
    worker.tick(now=started + 1201)
    events = mail.delivery_events(history, message)[recipient['sender_key']]
    assert 'answered' in events
    page = owner.shared_agent_mail('read', {'since': 0, 'context': context}, peer=peer())
    assert next(row for row in page['messages'] if row['id'] == note['message_id'])['state'] == 'answered'
    worker = mail.WorkshopInjection(owner, native)
    worker.tick(now=started + 1800)
    assert len([turn for turn in native.turns
        if turn[2]['message_id'].startswith(note['message_id'] + ':')]) == 1


def test_persisted_old_escalation_stays_readable_without_delivery(room):
    owner, history = room
    context = {'claude/sessionID': '71700000-0000-4000-8000-000000000001'}
    declare(owner, context)
    note = history.append(mail.ROOM, author='Workshop coordination', category=mail.CATEGORY,
        content='To 717:\nNo reply from Codex to Workshop message old. One reminder was issued; reconcile this thread.',
        idempotency_key='workshop-escalation:fixture')
    native = NativeFixture()
    worker = mail.WorkshopInjection(owner, native)
    owner.workshop_injection = worker
    worker.tick()
    pending = owner.shared_agent_mail('pending', {'context': context}, peer=peer())['pending']
    page = owner.shared_agent_mail('read', {'since': 0, 'context': context}, peer=peer())
    print(json.dumps({'legacy_native_injections': len(native.turns),
        'legacy_pending': len(pending), 'legacy_readable': any(row['id'] == note['id']
            for row in page['messages'])}, sort_keys=True))
    assert native.turns == [], 'persisted automatic nags must never enter a session again'
    assert not any(row['id'] == note['id'] for row in pending)
    assert any(row['id'] == note['id'] for row in page['messages']), 'history remains readable'
