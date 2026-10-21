"""An agent's relayed reply is visible on the Workshop's default messages feed (2026-10-01).

Installed-app run, build 20261001-1850-3be57fd: the founder asked a connected Claude session to
propose a workflow; the relay recorded the reply, yet on the default "messages" feed the
founder's message kept "STARTED" and the reply never appeared. The reply is a tool-category
relay record, and the feed's conditional refresh only watched note records, so every re-read
answered "unchanged". Now the messages feed shows each page message's relayed reply as an agent
row named by the relay's own header, and any newer record re-reads the page.
Real application, HTTP routes and relay worker; only the external native transport is a fixture.
"""
import threading
from urllib.parse import urlencode

from test_workshop_milestone_one import (  # noqa: F401  (harness is a pytest fixture)
    OPENCODE, _message, _opencode_digest, _send_contact, harness)


def _feed(h, convo, feed, content_after=None):
    query = {'root': convo['root'], 'scope': convo['scope'], 'feed': feed}
    if content_after is not None:
        query['content_after'] = content_after
    return h.request('/api/universal/workshop?' + urlencode(query))


def _hold_replies(h):
    transport = h.state['transport']
    gate, original = threading.Event(), transport.request

    def held(recipient, text, **kwargs):
        gate.wait(15)
        return original(recipient, text, **kwargs)
    transport.request = held
    return gate


def test_a_relayed_reply_and_its_delivery_reach_the_default_messages_feed(harness):
    h = harness
    h.start()
    convo = h.conversation_with_two_agents()
    gate = _hold_replies(h)
    sent = _send_contact(h, convo, convo['opencode'], _opencode_digest(h, convo),
                         'Please confirm the release note plan.', 'ask-messages-feed')
    first = _feed(h, convo, 'messages')
    asked = _message(first, sent['message_id'])
    assert [row['state'] for row in asked['delivery']] == ['started']
    assert not [row for row in first['messages'] if row.get('reply_to_root') == sent['message_id']]

    gate.set()
    h.settle()
    # The page's own conditional refresh, with the cursor it was handed while the reply was pending.
    second = _feed(h, convo, 'messages', content_after=first['content_cursor'])
    assert second.get('unchanged') is not True, 'a newer relay record must re-read the page'
    asked = _message(second, sent['message_id'])
    assert [row['state'] for row in asked['delivery']] == ['replied']
    reply_id = asked['delivery'][0]['reply_message_id']
    replies = [row for row in second['messages'] if row.get('reply_to_root') == sent['message_id']]
    assert [row['message_id'] for row in replies] == [reply_id]
    reply = replies[0]
    assert reply['agent_text'] == 'OpenCode fixture acknowledges.'
    assert reply['relayed_label'] == OPENCODE['title']
    assert reply['relayed_from'] == convo['opencode'] and reply['sequence'] > asked['sequence']
    # The opening message's earlier reply is on the page too: every agent answer is, not just the newest.
    assert len([row for row in second['messages'] if row.get('relayed_from') == convo['opencode']]) == 2
    # Notes stay in order, the reply sits after the message it answers, and nothing else of the
    # relay's bookkeeping (decision/started records) leaks into the messages feed.
    sequences = [row['sequence'] for row in second['messages']]
    # The page envelope the client validates: total covers every row shown (rig 2026-10-01: a
    # page with the replies but a note-only total was refused as 'Workshop history is invalid').
    assert second['total'] >= len(second['messages'])
    assert sequences == sorted(sequences)
    assert all(row['category'] == 'note' or row.get('relayed_from') for row in second['messages'])

    # A re-read with the new cursor and no new record is unchanged again.
    third = _feed(h, convo, 'messages', content_after=second['content_cursor'])
    assert third.get('unchanged') is True


def test_a_workflow_drafted_from_a_shown_reply_is_on_the_messages_feed(harness):
    # Rig 2026-10-01: "Draft as workflow" on the reply answered 200 but no workflow card appeared,
    # because the draft record replies to the agent reply, not to a page note.
    h = harness
    h.start()
    convo = h.conversation_with_two_agents()
    sent = _send_contact(h, convo, convo['opencode'], _opencode_digest(h, convo),
                         'PROPOSE a workflow: you build the release note.', 'ask-propose-messages')
    h.settle()
    page = _feed(h, convo, 'messages')
    reply_id = _message(page, sent['message_id'])['delivery'][0]['reply_message_id']
    assert [row['message_id'] for row in page['messages'] if row.get('reply_to_root') == sent['message_id']] == [reply_id]
    drafted = h.request('/api/universal/workshop', {'action': 'workflow-draft', 'root': convo['root'],
        'scope': convo['scope'], 'message': reply_id, 'idempotency_key': 'draft-from-messages-feed',
        'revision': page['revision']})
    after = _feed(h, convo, 'messages')
    assert [row['root'] for row in after['workflows']] == [drafted['workflow']]
    assert after['total'] >= len(after['messages'])


def test_the_activity_feed_is_unchanged_by_this(harness):
    h = harness
    h.start()
    convo = h.conversation_with_two_agents()
    _send_contact(h, convo, convo['opencode'], _opencode_digest(h, convo), 'Status?', 'ask-activity')
    h.settle()
    activity = _feed(h, convo, 'activity')
    assert activity['messages'] and all(row['category'] == 'tool' for row in activity['messages'])


def test_more_note_and_reply_rows_than_one_page_page_through_the_real_client(harness):
    # Ping 2026-10-01: notes plus their relayed replies could exceed the client's 100-row page
    # (studio-existing-workshop.js refuses more), and every agent answer would vanish again.
    # 60 notes each with a reply, served over HTTP and read by the REAL client, newest page first.
    import json as _json
    import shutil
    import subprocess
    from pathlib import Path
    h = harness
    h.start()
    convo = h.conversation_with_two_agents()
    digest = _opencode_digest(h, convo)
    asked = []
    for index in range(60):
        asked.append(_send_contact(h, convo, convo['opencode'], digest, 'Status %d?' % index,
                                   'ask-page-%02d' % index)['message_id'])
        h.settle()
    first = _feed(h, convo, 'messages')
    server = h.state['server']
    driver = Path(__file__).with_name('workshop_feed_client_driver.cjs')
    ran = subprocess.run([shutil.which('node'), str(driver), server.url, server.browser_session_token,
                          server.browser_csrf_token, first['graph_id'], convo['root'], convo['scope'],
                          str(first['revision'])], capture_output=True, text=True, encoding='utf-8', timeout=120)
    assert ran.returncode == 0, ran.stderr[-2000:]
    seen = _json.loads(ran.stdout.strip().splitlines()[-1])
    assert seen['error'] is None, seen
    assert len(seen['admitted']) >= 2 and all(0 < rows <= 100 for rows in seen['admitted']), seen['admitted']
    roots = [row['root'] for row in seen['seen']]
    assert len(roots) == len(set(roots)), 'no row is served on two pages'
    replies = {row['reply_to']: row['root'] for row in seen['seen'] if row['relayed_from'] == convo['opencode']}
    for message_id in asked:
        assert message_id in roots, 'every note is reachable through older pages'
        assert message_id in replies, 'every note arrives with its agent reply'
    # Each page's notes and their replies travel together: a reply is on its note's page.
    page_of = {}
    index = 0
    for number, count in enumerate(seen['admitted']):
        for row in seen['seen'][index:index + count]:
            page_of[row['root']] = number
        index += count
    assert all(page_of[note] == page_of[reply] for note, reply in replies.items() if note in page_of)
