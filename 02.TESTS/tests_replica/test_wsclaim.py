"""WSCLAIM: structural lane notices are delivered without reply debt."""
import pytest
from nodelang import workshop_mailbox as mail
from tests_replica.test_newapp_mailbox import peer
from tests_replica.test_wsinject import NativeFixture, declare, send
from tests_replica.test_wsnoreply import assert_not_chased, message, start

pytest_plugins = ('tests_replica.test_wsinject',)

CLAIM = 'DESIGNMATCH Run 4 CLAIM: continuing retained ff7cd470 plus focus correction in isolated designmatch/01.WIP/PRODUCT only. Editing universal_application.py/studio api.js and existing DESIGNMATCH regressions only as needed for retained-member sockets; preserving Work/header/Schedule fixes. Need no duplicate ownership. PROVIDE cumulative patch against 5389bfe1, final compiled suite/compiler and four real-route captures. No installed/live/profile/ROOTSREPUB changes.'

@pytest.mark.parametrize('text', [
    pytest.param(CLAIM, id='exact-8d10add2'),
    'CLAIM: Need no duplicate ownership.',
    'PROVIDE cumulative patch and court evidence. Need no review.',
    'DONE: need no further changes?',
    'RELEASED: please note ownership ended.',
    'STATUS: need more time for my build.',
    'Progress: need another local run.',
    'STATUS: Finished run. Another local run is underway.',
    'STATUS: Court took 4.2 seconds; please note timing.',
    'STATUS need no further action?',
    'PROGRESS: Court took 4.2 seconds. One more run is underway.',
    'claim: ownership recorded.',
    'Verdict: ACCEPT; need no changes.',
    '> Please reply?\nSTATUS: need more time.',
])
@pytest.mark.parametrize('target', ['all', 'codex'])
def test_structural_notice_never_creates_reply_debt(room, text, target):
    owner, history = room
    declare(owner, {'threadId': 'codex-fixture'})
    note = send(owner, to=target, text=text)
    original = message(history, note)
    native = NativeFixture()
    _worker, now = start(owner, history, note, native)
    if target == 'codex':
        assert_not_chased(owner, history, note, native, now)
    else:
        for elapsed in (299, 300, 599, 600, 601, 1200):
            mail.WorkshopInjection(owner, native).tick(now=now + elapsed)
        events = mail.delivery_events(history, original)
        assert events and all('reminder' not in row and 'escalated' not in row
                              for row in events.values()), events
        assert history._db.execute("SELECT count(*) FROM messages WHERE reply_to=? AND author='Workshop coordination'", (note['message_id'],)).fetchone()[0] == 0
    assert not mail._asks_for_reply(original)
    # A false escalation must not force the recipient to read before sending.
    owner.shared_agent_mail('send', {'to': 'claude', 'text': 'ACK',
        'context': {'threadId': 'codex-fixture'}},
        peer=peer())

@pytest.mark.parametrize('text', [
    'CLAIM: taking WSCLAIM. Codex, can you confirm the base SHA?',
    'DONE. Can you land it?',
    'RELEASED lane; please confirm you got it.',
    'I claim the fixture is wrong, can you check it?',
    'Your claim about 5389bfe1 is wrong. Can you re-run?',
    'I need the build SHA before I can land.',
    'The result is ready. CLAIM: can you confirm it?',
    'claim: Can you confirm ownership?',
    'CLAIM: taking WSCLAIM; NEED from codex: confirm the SHA.',
    'CLAIM: taking WSCLAIM, can you confirm the SHA?',
    'PROVIDE the patch. Please reply with the SHA.',
    'Can you confirm https://example.com/build?sha=123 applies?',
    'Can you confirm the patch applies?',
    'STATUS: Court took 4.2 seconds. Please confirm the patch.',
    'STATUS courts passed. Please confirm the patch.',
    'I need you to confirm the SHA.',
    'Need you to review the patch.',
    'CLAIM: Need no duplicate ownership.\nNEED from codex: confirm the SHA.',
    'STATUS: need more time.\nPlease reply with the SHA.',
    'Progress: need another run. Can you confirm the result?',
    'Verdict: REJECT. Please fix the failing court.',
])
def test_addressed_request_still_escalates(room, text):
    owner, history = room
    declare(owner, {'threadId': 'codex-fixture'})
    note = send(owner, text=text)
    native = NativeFixture()
    _worker, now = start(owner, history, note, native)
    assert mail._asks_for_reply(message(history, note))
    for elapsed in (299, 300, 599, 600, 601, 1200):
        mail.WorkshopInjection(owner, native).tick(now=now + elapsed)
    events = mail.delivery_events(history, message(history, note))
    assert any('reminder' in row and 'escalated' in row for row in events.values())
    assert history._db.execute("SELECT count(*) FROM messages WHERE reply_to=? AND author='Workshop coordination'", (note['message_id'],)).fetchone()[0] == 1

@pytest.mark.parametrize('text', [
    'Artifact: https://example.com/build?sha=123',
    'Artifact: <https://example.com/build?sha=123>',
    'Artifact: [build](https://example.com/build?sha=123)',
    r'Artifact: C:\BUILD\output?.txt',
    'Artifact: ./BUILD/output?.txt',
    'Artifact: file?.txt',
    'Artifact: /BUILD/output?.txt',
    'Artifact: BUILD/output?.txt',
])
def test_url_or_path_question_mark_does_not_create_reply_debt(room, text):
    owner, history = room
    declare(owner, {'threadId': 'codex-fixture'})
    note = send(owner, text=text)
    native = NativeFixture()
    _worker, now = start(owner, history, note, native)
    assert_not_chased(owner, history, note, native, now)
    assert not mail._asks_for_reply(message(history, note))
