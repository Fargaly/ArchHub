from urllib.parse import urlencode

from nodelang import universal_application as app
from nodelang.universal_pipeline import create_engine_node
from tests_replica.test_workshop_milestone_one import (
    _message,
    _proposal_reply,
    _send_contact,
    _opencode_digest,
    harness,
)


def _canvas_node_ids(h, scope):
    canvas = h.request('/api/universal/canvas?' + urlencode({'scope': scope}))
    return {str(row['id']) for row in canvas['nodes']}


def _draft_expected(h, convo, reply_id, key, expected):
    return h.request('/api/universal/workshop', {'action': 'workflow-draft', 'root': convo['root'],
        'scope': convo['scope'], 'message': reply_id, 'idempotency_key': key,
        'revision': h.page(convo['root'], convo['scope'])['revision']}, expected=expected)


def test_failed_workflow_anchor_creation_retracts_draft_members(harness, monkeypatch):
    h = harness
    h.start()
    convo = h.conversation_with_two_agents()
    reply_id = _proposal_reply(h, convo)
    before = _canvas_node_ids(h, convo['scope'])

    def crash_anchor(*args, **kwargs):
        raise RuntimeError('fixture anchor crash')

    monkeypatch.setattr(app, 'instantiate_universal_primitive', crash_anchor)
    refused = _draft_expected(h, convo, reply_id, 'draft-anchor-crash', 400)

    assert 'fixture anchor crash' in refused['error']
    assert _canvas_node_ids(h, convo['scope']) == before


def test_workflow_proposal_with_no_executable_node_retracts_placed_roots(harness, monkeypatch):
    h = harness
    h.start()
    convo = h.conversation_with_two_agents()
    opencode_digest = _opencode_digest(h, convo)
    asked = _send_contact(h, convo, convo['opencode'], opencode_digest,
        'PROPOSE a workflow with no executable node.', 'ask-no-executable')
    h.settle()
    reply_id = _message(h.page(convo['root'], convo['scope']), asked['message_id'])['delivery'][0]['reply_message_id']
    before = _canvas_node_ids(h, convo['scope'])

    def apply_non_executable(store, registry, projection, plan, actions, *, authentication_context,
            unplaced_when_omitted=False):
        created = create_engine_node(store, registry, title='temporary draft card',
            engine='workshop.conversation', x=260.0, y=240.0,
            properties={'conversation': convo['root']},
            authentication_context=authentication_context)
        return {'applied': [{'op': 'place', 'ok': True, 'root': created['root']}]}

    monkeypatch.setattr('nodelang.agent_composer._apply_draft_actions', apply_non_executable)
    refused = _draft_expected(h, convo, reply_id, 'draft-no-executable', 400)

    assert 'placed no executable node' in refused['error']
    assert _canvas_node_ids(h, convo['scope']) == before


def test_failed_mid_apply_workflow_draft_retracts_projected_nodes(harness, monkeypatch):
    h = harness
    h.start()
    convo = h.conversation_with_two_agents()
    reply_id = _proposal_reply(h, convo)
    before = _canvas_node_ids(h, convo['scope'])

    def crash_connect(*args, **kwargs):
        raise RuntimeError('fixture mid-apply crash')

    monkeypatch.setattr(app, 'connect_universal_roots', crash_connect)
    refused = _draft_expected(h, convo, reply_id, 'draft-mid-apply-crash', 400)

    assert 'fixture mid-apply crash' in refused['error']
    assert _canvas_node_ids(h, convo['scope']) == before
