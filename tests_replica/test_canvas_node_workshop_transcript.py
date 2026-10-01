"""Canvas live-node conversation contract (Workshop side, 2026-10-01; agreed with the canvas owner).

(1) A live canvas node carries `conversation_root` (the Workshop conversation that holds its
    transcript: the node's own `conversation` property) and `has_conversation`; null/false when none
    is bound.
(2) GET /api/universal/workshop-transcript?node=&scope=[&before=] reads that transcript READ-ONLY,
    keyed by the node at the viewer's canvas scope, under the Workshop's own browser/scope admission:
    {ok, node, conversation_root, revision, has_older, next_before,
     rows:[{id, who, is_me, time, text, kind}]}.
Real application, routes, relay and canvas; only the external native transport is a fixture.
"""
import json
from datetime import datetime
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from test_workshop_milestone_one import (  # noqa: F401  (harness is a pytest fixture)
    OPENCODE, _draft, _proposal_reply, harness)


def _get(h, path, expected=200):
    server = h.state['server']
    call = Request(server.url + path, headers={'Origin': server.url,
        'Cookie': 'ArchHub-Session=' + server.browser_session_token, 'X-ArchHub-CSRF': server.browser_csrf_token})
    try:
        with urlopen(call, timeout=60) as response:
            status, body = response.status, json.loads(response.read())
    except HTTPError as exc:
        status, body = exc.code, json.loads(exc.read())
    assert status == expected, (path, status, body)
    return body


def _transcript(h, node, scope, expected=200, **extra):
    return _get(h, '/api/universal/workshop-transcript?' + urlencode({'node': node, 'scope': scope, **extra}), expected)


def test_a_live_node_names_its_conversation_and_its_transcript_reads_render_ready(harness):
    h = harness
    h.start()
    convo = h.conversation_with_two_agents()
    drafted = _draft(h, convo, _proposal_reply(h, convo), 'draft-canvas-contract')
    room, builder, _judge = drafted['members']

    canvas = _get(h, '/api/universal/canvas')
    scope = canvas['scope']['current']
    nodes = {node['id']: node for node in canvas['nodes']}
    assert nodes[room]['conversation_root'] == convo['root'] and nodes[room]['has_conversation'] is True
    assert nodes[builder]['conversation_root'] is None and nodes[builder]['has_conversation'] is False
    assert all(set(('conversation_root', 'has_conversation')) <= set(node) for node in canvas['nodes'])

    read = _transcript(h, room, scope)
    assert set(read) == {'ok', 'node', 'conversation_root', 'revision', 'has_older', 'next_before', 'rows'}
    assert read['ok'] is True and read['node'] == room and read['conversation_root'] == convo['root']
    assert read['rows'] and all(set(row) == {'id', 'who', 'is_me', 'time', 'text', 'kind'} for row in read['rows'])
    for row in read['rows']:
        datetime.fromisoformat(row['time'].replace('Z', '+00:00'))   # a real timestamp, not a sequence
        assert row['kind'] in ('message', 'reply', 'tool')
        assert not row['who'].startswith('app:'), 'who is a display name, never an opaque root'
    mine = [row for row in read['rows'] if row['is_me']]
    assert mine and all(row['who'] == 'You' and row['kind'] == 'message' for row in mine)
    assert any('PROPOSE a workflow' in row['text'] for row in mine)
    replies = [row for row in read['rows'] if row['kind'] == 'reply']
    assert replies and all(row['who'] == OPENCODE['title'] and not row['is_me'] for row in replies)
    assert all('Session Link relayed reply' not in row['text'] for row in replies), 'the agent text, not the relay header'
    assert any('"actions"' in row['text'] for row in replies)
    times = [row['time'] for row in read['rows']]
    assert times == sorted(times), 'newest last'

    # A node with no bound conversation is honest-empty, not an error.
    empty = _transcript(h, builder, scope)
    assert empty['conversation_root'] is None and empty['rows'] == [] and empty['has_older'] is False


def test_the_read_is_keyed_and_scoped_by_the_canvas_and_has_no_write_path(harness):
    h = harness
    h.start()
    convo = h.conversation_with_two_agents()
    drafted = _draft(h, convo, _proposal_reply(h, convo), 'draft-canvas-contract-scope')
    room = drafted['members'][0]
    scope = _get(h, '/api/universal/canvas')['scope']['current']
    before = h.page(convo['root'], convo['scope'])['revision']
    _transcript(h, room, scope)
    assert h.page(convo['root'], convo['scope'])['revision'] == before, 'reading writes nothing'
    assert 'not on this canvas' in _transcript(h, 'app:no-such-node', scope, expected=403)['error']
    assert 'scope' in _transcript(h, room, 'app:some-other-scope', expected=403)['error'].lower()
    assert 'invalid' in _get(h, '/api/universal/workshop-transcript?node=' + room, expected=400)['error']
    assert 'invalid' in _get(h, '/api/universal/workshop-transcript?' + urlencode(
        {'node': room, 'scope': scope, 'root': convo['root']}), expected=400)['error'], 'never keyed by a raw root'
    server = h.state['server']
    post = Request(server.url + '/api/universal/workshop-transcript', method='POST', data=b'{}',
        headers={'Content-Type': 'application/json', 'Origin': server.url,
                 'Cookie': 'ArchHub-Session=' + server.browser_session_token, 'X-ArchHub-CSRF': server.browser_csrf_token})
    try:
        urlopen(post, timeout=30)
        posted = 200
    except HTTPError as exc:
        posted = exc.code
    assert posted >= 400, 'there is no write path on the transcript route'


def test_a_graph_created_before_the_route_existed_gains_it_on_open(harness, monkeypatch):
    # Fresh fixtures cannot prove an old graph opens: create the graph with the route table as it was
    # before this change (no workshop-transcript route cell), close it, reopen with the real table.
    from nodelang import universal_application as app
    h = harness
    before = tuple(spec for spec in app._APPLICATION_HTTP_ROUTE_SPECS if spec[1] != '/api/universal/workshop-transcript')
    assert len(before) == len(app._APPLICATION_HTTP_ROUTE_SPECS) - 1
    with monkeypatch.context() as patch:
        patch.setattr(app, '_APPLICATION_HTTP_ROUTE_SPECS', before)
        h.start()
        convo = h.conversation_with_two_agents()
        drafted = _draft(h, convo, _proposal_reply(h, convo), 'draft-before-route')
        h.stop()
    h.start()
    scope = _get(h, '/api/universal/canvas')['scope']['current']
    read = _transcript(h, drafted['members'][0], scope)
    assert read['conversation_root'] == convo['root'] and read['rows']
