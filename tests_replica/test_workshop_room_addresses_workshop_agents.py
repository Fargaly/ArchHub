from urllib.parse import urlencode
from types import SimpleNamespace as NS
from contextlib import nullcontext

from tests_replica.test_workshop_milestone_one import OPENCODE, CLAUDE, harness, _message
from nodelang.cell_authorization import AuthorizationDenied
from nodelang import native_contact


def _send_contact(h, root, scope, contact, digest, text, key, expected=200):
    return h.request('/api/universal/native-contact', {'action': 'send',
        'root': root, 'scope': scope, 'contact': contact,
        'binding_digest': digest, 'text': text, 'idempotency_key': key},
        expected=expected)


def _contacts(h, root, scope):
    found = h.request('/api/universal/native-agents?' + urlencode({
        'apps': 'claude,opencode', 'root': root, 'scope': scope}))
    return found['contacts']


def _conversation_with_two_agents(h, key):
    opened = h.request('/api/universal/workshop', {'action': 'start-session',
        'prompt': 'Hello OpenCode, please confirm you can hear this Workshop.',
        'native': {'app': 'opencode', 'session_id': OPENCODE['id']},
        'idempotency_key': key})
    assert opened['delivery']['state'] == 'started', opened
    h.settle()
    bound = h.request('/api/universal/native-contact', {'action': 'bind',
        'root': opened['root'], 'scope': opened['scope'], 'node': None,
        'app': 'claude', 'session_id': CLAUDE['id'],
        'revision': h.page(opened['root'], opened['scope'])['revision']})
    return {'root': opened['root'], 'scope': opened['scope'],
        'opencode': opened['contact'], 'opencode_first': opened['message_id'],
        'claude': bound['contact'], 'claude_digest': bound['binding_digest']}


def test_saved_room_addresses_general_workshop_bound_native_contact(harness):
    h = harness
    server = h.start()
    registry = server.universal_registry
    workshop_root = registry.workshop_root
    workshop_scope = registry.workshop_workbench_root
    current_page = h.request('/api/universal/canvas')
    bound = h.request('/api/universal/native-contact', {'action': 'bind',
        'root': workshop_root, 'scope': workshop_scope, 'node': None,
        'app': 'opencode', 'session_id': OPENCODE['id'],
        'revision': current_page['revision']})

    room = h.conversation_with_two_agents()
    room_contacts = _contacts(h, room['root'], room['scope'])
    rows = [row for row in room_contacts if row['root'] == bound['contact']]
    assert len(rows) == 1
    assert rows[0]['binding_digest'] == bound['binding_digest']

    sent = _send_contact(h, room['root'], room['scope'], bound['contact'],
        bound['binding_digest'], 'OpenCode, answer in this saved room.',
        'room-to-general-opencode')
    h.settle()
    room_page = h.page(room['root'], room['scope'])
    general_page = h.page(workshop_root, room['scope'])
    addressed = _message(room_page, sent['message_id'])
    assert addressed['state'] == 'replied'
    replies = [row for row in room_page['messages']
        if row.get('relayed_from') == bound['contact']]
    assert len(replies) == 1
    assert replies[0]['agent_text'] == 'OpenCode fixture acknowledges.'
    assert not [row for row in general_page['messages']
        if row.get('relayed_from') == bound['contact']]


def test_room_refuses_contact_bound_to_a_different_room(harness):
    h = harness
    h.start()
    first = _conversation_with_two_agents(h, 'foreign-room-first-open-opencode')
    second = _conversation_with_two_agents(h, 'foreign-room-second-open-opencode')
    assert first['root'] != second['root']

    first_contacts = _contacts(h, first['root'], first['scope'])
    assert second['claude'] not in {row['root'] for row in first_contacts}
    _send_contact(h, first['root'], first['scope'], second['claude'],
        second['claude_digest'], 'This must not cross rooms.',
        'foreign-room-claude', expected=403)


def test_room_refuses_general_workshop_contact_with_stale_digest(harness):
    h = harness
    server = h.start()
    registry = server.universal_registry
    bound = h.request('/api/universal/native-contact', {'action': 'bind',
        'root': registry.workshop_root, 'scope': registry.workshop_workbench_root,
        'node': None, 'app': 'opencode', 'session_id': OPENCODE['id'],
        'revision': h.request('/api/universal/canvas')['revision']})
    room = h.conversation_with_two_agents()
    stale = ('0' if bound['binding_digest'][0] != '0' else '1') + bound['binding_digest'][1:]
    _send_contact(h, room['root'], room['scope'], bound['contact'], stale,
        'This stale binding must not relay.', 'stale-general-opencode',
        expected=403)


def test_read_contact_owner_predicate_refuses_another_subject(monkeypatch):
    value = {'kind': 'native-contact', 'version': 1,
        'endpoint': {'app': 'opencode', 'id': OPENCODE['id']},
        'conversation': 'app:workshop', 'scope': 'app:workshop-workbench',
        'owner': 'subject:owner'}
    monkeypatch.setattr(native_contact, '_admit_contact_conversation',
        lambda owner, browser, root, scope: None)
    monkeypatch.setattr(native_contact, '_property',
        lambda owner, contact, context: ('relation', native_contact.json.dumps(
            value, sort_keys=True, separators=(',', ':'))))
    owner = NS(mutation_lock=nullcontext(),
        universal_registry=NS(workshop_root='app:workshop',
            workshop_workbench_root='app:workshop-workbench'))
    browser = NS(subject_root='subject:other', context=object())
    digest = native_contact._digest(value)
    try:
        native_contact.read_contact(owner, browser, 'contact', digest,
            'app:workshop', 'app:workshop-workbench')
    except AuthorizationDenied:
        pass
    else:
        raise AssertionError('foreign owner contact was accepted')
