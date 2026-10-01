"""Workshop ACTIVITY panel on the default feed (design audit gap 10, 2026-10-01).

The messages feed pages notes only, so its tool records never reached the ACTIVITY panel. The
read now carries `activity`: the newest tool records, read in storage under the same browser and
scope admission, bounded (rows and text), never an agent's relayed reply, and only on that feed.
Real application, routes and relay; only the external native transport is a fixture.
"""
from urllib.parse import urlencode

from test_workshop_milestone_one import (  # noqa: F401  (harness is a pytest fixture)
    _draft, _proposal_reply, harness)

# The browser contract (studio-existing-workshop.js refuses more rows or longer text).
WORKSHOP_ACTIVITY_ROWS, WORKSHOP_ACTIVITY_TEXT = 8, 240


def _feed(h, convo, feed):
    return h.request('/api/universal/workshop?' + urlencode(
        {'root': convo['root'], 'scope': convo['scope'], **({'feed': feed} if feed != 'all' else {})}))


def test_the_default_feed_carries_the_newest_tool_records_as_activity(harness):
    h = harness
    h.start()
    convo = h.conversation_with_two_agents()
    reply = _proposal_reply(h, convo)
    _draft(h, convo, reply, 'draft-activity-panel')
    for index in range(6):
        h.request('/api/universal/workshop', {'root': convo['root'], 'scope': convo['scope'], 'category': 'note',
            'text': 'Everyone: acknowledge %d.' % index, 'refs': [], 'evidence': [], 'recipients': [],
            'reply_to': None, 'idempotency_key': 'activity-%d' % index, 'created_at': None})
        h.settle()

    tools = _feed(h, convo, 'activity')
    relayed = {row['root'] for row in tools['messages'] if row.get('relayed_from')}
    expected = [row for row in tools['messages'] if row['root'] not in relayed]
    assert len(expected) > WORKSHOP_ACTIVITY_ROWS, 'the fixture writes more tool records than the panel shows'

    before = h.page(convo['root'], convo['scope'])['revision']
    read = _feed(h, convo, 'messages')
    activity = read['activity']
    assert [row['root'] for row in activity] == [row['root'] for row in expected][-WORKSHOP_ACTIVITY_ROWS:]
    assert all(set(row) == {'root', 'sequence', 'sender_root', 'body', 'created_at'} for row in activity)
    assert all(len(row['body']) <= WORKSHOP_ACTIVITY_TEXT for row in activity)
    by_root = {row['root']: row for row in expected}
    assert all(by_root[row['root']]['body'].startswith(row['body']) for row in activity)
    sequences = [row['sequence'] for row in activity]
    assert sequences == sorted(sequences), 'newest last'
    assert not relayed & {row['root'] for row in activity}, "an agent's reply is a conversation row, not activity"
    assert relayed, 'the fixture relayed agent replies'
    # The notes page is unchanged: activity rows are not page rows.
    assert not {row['root'] for row in activity} & {row['root'] for row in read['messages']
                                                     if row['category'] == 'note'}
    assert h.page(convo['root'], convo['scope'])['revision'] == before, 'reading writes nothing'

    # Only the messages feed carries it; the tool and full feeds page those records themselves.
    assert 'activity' not in tools
    assert 'activity' not in _feed(h, convo, 'all')
