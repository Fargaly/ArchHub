import json
from urllib.parse import urlencode

from nodelang import universal_application as app
from nodelang import workshop_workflow
from nodelang.universal_cell import InvalidCell
from tests_replica.test_workshop_milestone_one import (
    _proposal_reply,
    harness,
)


def _canvas(h, scope):
    return h.request('/api/universal/canvas?' + urlencode({'scope': scope}))


def _canvas_node_ids(h, scope):
    return {str(row['id']) for row in _canvas(h, scope)['nodes']}


def _draft_expected(h, convo, reply_id, key, expected=200):
    return h.request('/api/universal/workshop', {'action': 'workflow-draft', 'root': convo['root'],
        'scope': convo['scope'], 'message': reply_id, 'idempotency_key': key,
        'revision': h.page(convo['root'], convo['scope'])['revision']}, expected=expected)


def _anchor_rows(h, convo, reply_id):
    owner = h.state['server']
    snapshot = owner.universal_store.snapshot()
    rows = []
    for node in _canvas(h, convo['scope'])['nodes']:
        try:
            value = workshop_workflow._workflow_value(snapshot, str(node['id']), convo['root'])
        except InvalidCell:
            continue
        if value.get('source_message') == reply_id:
            rows.append((str(node['id']), value))
    return rows


def test_retry_after_compensated_anchor_failure_drafts_fresh(harness, monkeypatch):
    h = harness
    h.start()
    convo = h.conversation_with_two_agents()
    reply_id = _proposal_reply(h, convo)
    before = _canvas_node_ids(h, convo['scope'])

    def crash_anchor(*args, **kwargs):
        raise RuntimeError('fixture anchor crash')

    monkeypatch.setattr(app, 'instantiate_universal_primitive', crash_anchor)
    refused = _draft_expected(h, convo, reply_id, 'retry-anchor-crash', expected=400)

    assert refused['ok'] is False
    assert 'fixture anchor crash' in refused['error']
    assert _canvas_node_ids(h, convo['scope']) == before

    monkeypatch.undo()
    drafted = _draft_expected(h, convo, reply_id, 'retry-anchor-crash')

    assert drafted['ok'] is True
    assert drafted['reused'] is False
    assert set(drafted['members']) <= _canvas_node_ids(h, convo['scope'])
    assert len(_anchor_rows(h, convo, reply_id)) == 1


def test_retry_after_final_content_failure_reuses_committed_anchor(harness, monkeypatch):
    h = harness
    h.start()
    convo = h.conversation_with_two_agents()
    reply_id = _proposal_reply(h, convo)
    real_append = workshop_workflow._append
    crashed = {'done': False}

    def crash_final(owner, browser, root, space, content, key, **kwargs):
        try:
            record = json.loads(content)
        except ValueError:
            record = {}
        if record.get('kind') == 'workshop-workflow-draft' and not crashed['done']:
            crashed['done'] = True
            raise RuntimeError('fixture final append crash')
        return real_append(owner, browser, root, space, content, key, **kwargs)

    monkeypatch.setattr(workshop_workflow, '_append', crash_final)
    refused = _draft_expected(h, convo, reply_id, 'retry-final-crash', expected=400)

    assert refused['ok'] is False
    assert 'fixture final append crash' in refused['error']
    anchors = _anchor_rows(h, convo, reply_id)
    assert len(anchors) == 1
    anchor, anchor_value = anchors[0]
    members = set(anchor_value['members'])
    assert members <= _canvas_node_ids(h, convo['scope'])

    drafted = _draft_expected(h, convo, reply_id, 'retry-final-crash')

    assert drafted['ok'] is True
    assert drafted['reused'] is True
    assert drafted['workflow'] == anchor
    assert set(drafted['members']) == members
    assert _anchor_rows(h, convo, reply_id) == anchors
    assert [row for row in h.page(convo['root'], convo['scope'])['workflows'] if row['root'] == anchor]


def test_retry_after_success_reuses_existing_draft_without_new_nodes(harness):
    h = harness
    h.start()
    convo = h.conversation_with_two_agents()
    reply_id = _proposal_reply(h, convo)
    drafted = _draft_expected(h, convo, reply_id, 'retry-success')
    before = _canvas_node_ids(h, convo['scope'])

    retry = _draft_expected(h, convo, reply_id, 'retry-success')

    assert retry['ok'] is True
    assert retry['reused'] is True
    assert retry['workflow'] == drafted['workflow']
    assert _canvas_node_ids(h, convo['scope']) == before
    assert len(_anchor_rows(h, convo, reply_id)) == 1
