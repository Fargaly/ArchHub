"""WSASKONLY: exercise mailbox delivery, durable follow-up and reply closure."""
import pytest

from nodelang import workshop_mailbox as mail
from tests_replica.test_newapp_mailbox import peer
from tests_replica.test_wsinject import NativeFixture, declare, send
from tests_replica.test_wsnoreply import assert_not_chased, message, start

pytest_plugins = ('tests_replica.test_wsinject',)


@pytest.mark.parametrize('text', [
    'Now check the patch.', 'Also confirm the SHA.', 'Next review the patch.',
    'And send the SHA.', 'So ship the patch.', 'Then publish the patch.',
    'Push the patch.', 'Release the patch.', 'ثم راجع الباتش', 'وبعدين ابعت النتيجة',
    'نزل البيلد', 'شغل الكورت', 'شغّل الكورت', 'صلح الباتش', 'صلّح الباتش',
    'اعمل الباتش', 'شوف الكورت', 'قول النتيجة',
])
def test_review2_additional_imperatives_are_asks(text):
    assert mail._asks_for_reply({'content': 'To codex:\n' + text})


@pytest.mark.parametrize('text', [
    'S09 verifier progress: the court is running; result follows.',
    'S10 status: 12 PASS; remaining court active.',
    'Progress: I will verify the patch next and run the court.',
    'Built and installed build 48; screenshot attached.',
    'Review complete. Final verdict: ACCEPT. The patch applies on main.',
    'Verdict: REJECT. Evidence is recorded in RESULT.md.',
    'Reconciled: the verifier reported its result and the thread is closed.',
    'The review is complete; no pending work.',
    'Review in progress.',
    'Review passed.',
    'Review passed all 27 courts.',
    'Review failed all courts.',
    'Review complete on main.',
    'Review verdict: ACCEPT.',
    'Check running.',
    'Verify complete.',
    'Run failed.',
    'Fix in progress.',
    'Land is pending.',
    'Install finished.',
    'Build complete on main.',
    'Test result: PASS.',
    'Update received.',
    'Deliver done.',
    'Build 49 complete on main.',
    'Run 2 passed.',
    'Install 49 is complete.',
    'Review is complete.',
    'Final verdict ACCEPT. DONE WHEN conditions all satisfied.',
    'Final verdict ACCEPT. DONE WHEN: satisfied.',
    'NEED: none. Progress recorded.',
    'Confirmed. The result is ready.',
    'ACK',
    'Please review the result. No reply needed.',
    'Final verdict ACCEPT. No reply needed. Court evidence retained.',
    'Please confirm? nO rEpLy ReQuIrEd!',
    'Please confirm the SHA. No reply needed. Evidence follows.',
    'No reply needed. Please review the result.',
])
def test_nonasks_are_delivered_once_and_never_chased(room, text):
    owner, history = room
    declare(owner, {'threadId': 'codex-fixture'})
    note = send(owner, text=text)
    native = NativeFixture()
    _worker, now = start(owner, history, note, native)
    assert_not_chased(owner, history, note, native, now)
    assert message(history, note)['content'] == 'To codex:\n' + text




@pytest.mark.parametrize('delayed', [False, True])
def test_verdict_closes_assignment_without_becoming_a_new_ask(room, delayed):
    owner, history = room
    declare(owner, {'threadId': 'codex-fixture'})
    declare(owner, {'claude/sessionID': 'claude-fixture'})
    ask = send(owner, text='Review the patch. DONE WHEN: verdict and evidence recorded.')
    native = NativeFixture()
    worker, now = start(owner, history, ask, native)
    if delayed:
        worker.tick(now=now + 300)
    reply = owner.shared_agent_mail('send', {
        'to': 'claude', 'text': 'Review complete. Verdict ACCEPT. Evidence is in RESULT.md.',
        'reply_to': ask['message_id'], 'context': {'threadId': 'codex-fixture'}}, peer=peer())
    worker.tick(now=now + (301 if delayed else 1))
    assert_not_chased(owner, history, reply, native, now + 301)
    events = mail.delivery_events(history, message(history, ask))
    assert any('answered' in row for row in events.values())
    assert all('escalated' not in row for row in events.values())


def test_wrong_recipient_verdict_does_not_close_assignment(room):
    owner, history = room
    declare(owner, {'threadId': 'codex-fixture'})
    declare(owner, {'gemini/sessionID': 'other-fixture'})
    ask = send(owner, text='Can you confirm the patch applies?')
    native = NativeFixture()
    worker, now = start(owner, history, ask, native)
    owner.shared_agent_mail('send', {
        'to': 'claude', 'text': 'Verdict ACCEPT.', 'reply_to': ask['message_id'],
        'context': {'gemini/sessionID': 'other-fixture'}}, peer=peer())
    for elapsed in (1, 300, 600, 601):
        worker.tick(now=now + elapsed)
    events = mail.delivery_events(history, message(history, ask))
    assert events and all('answered' not in row for row in events.values())


def test_nonasking_native_control_is_not_reminded(room):
    owner, history = room
    declare(owner, {'ai.opencode/sessionID': 'selected-target'})
    note = send(owner, to='selected-target', text='Explicitly selected free model',
                native_control={'app': 'opencode', 'id': 'selected-target'})
    native = NativeFixture()
    _worker, now = start(owner, history, note, native)
    for elapsed in (300, 600, 601, 1200):
        mail.WorkshopInjection(owner, native).tick(now=now + elapsed)
    assert native.turns == [], 'caller-owned delivery of a status must never be replayed or reminded'
    events = mail.delivery_events(history, message(history, note))
    assert any('attempt' in row for row in events.values())
    assert all('reminder' not in row and 'escalated' not in row for row in events.values())
