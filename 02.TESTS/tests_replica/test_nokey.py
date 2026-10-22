"""Normal desktop coordination uses its existing graph without owner adoption."""
import json
from pathlib import Path
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from nodelang import cloud_session, desktop
from nodelang.application_server import ApplicationServer
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.clean_coordination_service import MAX_REQUEST_BYTES
from nodelang.universal_pipeline import _owner_properties
from tests_replica import test_workspace_roots_graph_current as legacy_workspaces

legacy_workspace_graph = legacy_workspaces.graph


@pytest.fixture
def owner(tmp_path, monkeypatch):
    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(tmp_path))
    monkeypatch.setenv('ARCHHUB_COORDINATION_ENDPOINT', 'http://127.0.0.1:0/coordination')
    monkeypatch.setattr(cloud_session, 'signed_in_cloud_account', lambda: 'owner@example.test')
    provider = MemorySigningKeyProvider('archhub.local.relationship-authority', b'r' * 32)
    provider.add_key('archhub.local.court-attestation', b'c' * 32)
    provider.add_key('archhub.local.private-root-grants', b'g' * 32)
    generation = tmp_path / 'unified-authority' / 'generations' / ('a' * 32)
    database = generation / 'authority.sqlite3'
    built_in = tmp_path / 'BUILTIN'
    built_in.mkdir()
    server = ApplicationServer(universal_state_path=database, universal_key_provider=provider,
        universal_workspace_root=built_in, private_root_grants_path=tmp_path / 'private-root-grants.json',
        enable_machine_transport=False, enable_universal_cloud_gateway=False, live_watch=False)
    (generation.parent.parent / 'CURRENT').write_text(generation.name, encoding='ascii')
    (generation / 'migration.json').write_text(json.dumps({
        'format': 'archhub-application-journal-migration/v1',
        'generation_id': generation.name, 'adoption': 'court-no-owner',
    }), encoding='utf-8')
    try:
        assert getattr(server.universal_store, '_signed_commit_authority', None) is None
        yield server, tmp_path
    finally:
        server.close()


def _post(surface, payload, *, timeout_seconds: float = 10.0, headers=None):
    request = Request('http://127.0.0.1:%d/coordination' % surface.server_address[1],
        data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json', **(headers or {})})
    with urlopen(request, timeout=timeout_seconds) as response:
        return json.load(response)


def test_normal_coordination_without_signed_owner_round_trips_workshop(owner):
    server, root = owner
    surface = desktop.bind_coordination_surface(server, root)
    assert surface is not None
    assert surface.coordination_host.store is server.universal_store
    sent = _post(surface, {'method': 'POST', 'path': '/api/universal/agent-mail/send',
        'body': {'to': 'NOKEY court', 'text': 'one shared Workshop', 'idempotency_key': 'nokey-roundtrip'}})
    page = _post(surface, {'method': 'GET', 'path': '/api/universal/agent-mail/read', 'body': {'since': 0}})
    message = next(row for row in page['messages'] if row['id'] == sent['message_id'])
    assert message['content'] == 'To NOKEY court:\none shared Workshop'
    assert 'owner@example.test' in message['author']
    assert server.conversation_content._path == Path(server.universal_store.database_path)
    assert not (Path(server.universal_store.database_path).parent / 'adoption.json').exists()
    assert getattr(server.universal_store, '_signed_commit_authority', None) is None


def test_no_owner_broker_call_returns_and_persists_on_the_same_graph(owner, monkeypatch):
    from nodelang import clean_revit_adapter as adapter, host_bridge_auth
    from nodelang.universal_cell import CellStore
    server, root = owner
    calls = []
    class Broker(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            calls.append((self.path, body))
            answer = json.dumps({'status': 'ok', 'result': [{'id': 9}]}).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(answer)))
            self.end_headers()
            self.wfile.write(answer)

    broker = ThreadingHTTPServer(('127.0.0.1', 0), Broker)
    worker = threading.Thread(target=broker.serve_forever, daemon=True)
    worker.start()
    monkeypatch.setattr(adapter, 'live_sessions', lambda: [{
        'port': broker.server_address[1], 'pid': 7, 'revit_version': '2026', 'document': 'NOKEY fixture'}])
    monkeypatch.setattr(host_bridge_auth, 'ensure_secret', lambda: 'isolated-host-boundary-fixture-secret')
    def isolated_call(port, route, body=None, *, timeout_seconds: float = 5.0):
        assert port == broker.server_address[1]
        status, answer = host_bridge_auth.bridge_request('http://127.0.0.1:%d%s' % (port, route),
            body, timeout=timeout_seconds)
        assert status == 200
        return answer
    monkeypatch.setattr(adapter, '_call', isolated_call)
    try:
        surface = desktop.bind_coordination_surface(server, root)
        before = server.universal_store.revision
        result = _post(surface, {'method': 'POST', 'path': '/api/universal/baboom-command-execute',
            'body': {'utterance': 'run revit.read'}})
        assert result['kind'] == 'engine-ran'
        assert result['data']['status'] == '1 row(s) from revit.list_walls'
        assert len(calls) == 1 and calls[0][0] == '/exec'
        assert calls[0][1]['transaction_name'] == 'ArchHub read'
        assert 'FilteredElementCollector' in calls[0][1]['code']
        node = result['data']['node']['root']
        assert _owner_properties(server.universal_store.snapshot(), server.universal_registry)[node]['status'][1] == result['data']['status']
        assert server.universal_store.revision > before
        database = server.universal_store.database_path
        registry = server.universal_registry
        server.close()
        with CellStore(database) as reopened:
            assert _owner_properties(reopened.snapshot(), registry)[node]['status'][1] == result['data']['status']
            assert getattr(reopened, '_signed_commit_authority', None) is None
        print('NOKEY_BROKER actual_http_calls=1 persisted_status=1 signed_owner=absent')
    finally:
        broker.shutdown()
        broker.server_close()
        worker.join()


def test_coordination_binding_never_opens_or_signs_a_graph(owner, monkeypatch, *, timeout_seconds: float = 3.0):
    from nodelang import cell_secret_keys, runtime_caller_capability
    import sqlite3
    server, root = owner
    def forbidden(*_args, **_kwargs):
        pytest.fail('coordination opened storage or asked for a machine key')
    monkeypatch.setattr(cell_secret_keys, 'WindowsDpapiSigningKeyProvider', forbidden)
    monkeypatch.setattr(runtime_caller_capability, 'WindowsDpapiCallerKeyStore', forbidden)
    monkeypatch.setattr(sqlite3, 'connect', forbidden)
    snapshot = server.universal_store.snapshot
    monkeypatch.setattr(server.universal_store, 'snapshot', forbidden)
    revision = server.universal_store.revision
    surface = desktop.bind_coordination_surface(server, root)
    assert desktop.bind_coordination_surface(server, root) is surface
    _post(surface, {'method': 'GET', 'path': '/api/universal/agent-mail/read', 'body': {'since': 0}})
    with urlopen('http://127.0.0.1:%d/health' % surface.server_address[1], timeout=timeout_seconds) as response:
        assert json.load(response)['revision'] == revision
    assert server.universal_store.revision == revision
    monkeypatch.setattr(server.universal_store, 'snapshot', snapshot)


def test_normal_reopen_does_not_bind_an_old_signed_manifest(owner, monkeypatch):
    from nodelang import application_server, persistence
    server, root = owner
    database = server.universal_store.database_path
    provider = server.universal_registry.authorization.relationship_broker._key_provider
    server.close()
    manifest = Path(database).parent / 'adoption.json'
    original = b'historical manifest is never a coordination admission credential'
    manifest.write_bytes(original)
    def forbidden(*_args, **_kwargs):
        pytest.fail('normal startup entered signed-owner adoption')
    monkeypatch.setattr(persistence, 'bind_selected_application_authority', forbidden)
    monkeypatch.setattr(application_server, 'bind_selected_application_authority', forbidden, raising=False)
    reopened = ApplicationServer(universal_state_path=database, universal_key_provider=provider,
        enable_machine_transport=False, enable_universal_cloud_gateway=False, live_watch=False)
    try:
        assert reopened.conversation_content._history is None
        surface = desktop.bind_coordination_surface(reopened, root)
        assert surface is not None
        sent = _post(surface, {'method': 'POST', 'path': '/api/universal/agent-mail/send',
            'body': {'to': 'NOKEY reopen', 'text': 'first use before any UI projection'}})
        page = _post(surface, {'method': 'GET', 'path': '/api/universal/agent-mail/read', 'body': {'since': 0}})
        assert any(row['id'] == sent['message_id'] for row in page['messages'])
        assert manifest.read_bytes() == original
        assert getattr(reopened.universal_store, '_signed_commit_authority', None) is None
    finally:
        reopened.close()


def test_local_channel_stays_available_without_a_verified_cloud_account(owner, monkeypatch):
    server, root = owner
    monkeypatch.setattr(cloud_session, 'signed_in_cloud_account', lambda: None)
    surface = desktop.bind_coordination_surface(server, root)
    assert _post(surface, {'method': 'GET', 'path': '/api/universal/agent-mail/read',
        'body': {'since': 0}})['account'] is None


def test_native_mailbox_caller_reaches_the_running_owner(owner, monkeypatch, *, timeout_seconds: float = 30.0):
    from nodelang.agent_declarations import canonical_path
    import os
    import subprocess
    import sys
    server, root = owner
    surface = desktop.bind_coordination_surface(server, root)
    monkeypatch.setenv('ARCHHUB_COORDINATION_ENDPOINT',
        'http://127.0.0.1:%d/coordination' % surface.server_address[1])
    program = '''
import json, os
from nodelang.native_agent_mcp import _mailbox_call
context = {'threadId': 'nokey-native'}
declaration = _mailbox_call('declare', {'task': 'NOKEY native caller', 'paths': ['relative.txt'],
    'status': 'working', 'request_id': 'NOKEY'}, context)
sent = _mailbox_call('send', {'to': '*', 'text': 'native HTTP owner path',
    'idempotency_key': 'native-owner'}, context)
text_budget = 65536 - len('To *:\\n'.encode())
unicode_text = '漢' * (text_budget // len('漢'.encode()))
large = _mailbox_call('send', {'to': '*', 'text': unicode_text}, context)
page = _mailbox_call('read', {'since': 0}, context)
escaped = _mailbox_call('send', {'to': '*', 'text': '\\x01' * text_budget}, context)
print(json.dumps({'pid': os.getpid(), 'declaration': declaration,
    'escaped_id': escaped['message_id'],
    'large_read_back': any(row['id'] == large['message_id'] and row['content'] == 'To *:\\n' + unicode_text for row in page['messages']),
    'read_back': any(row['id'] == sent['message_id'] for row in page['messages'])}))
'''
    child = subprocess.run([sys.executable, '-c', program], cwd=root,
        capture_output=True, text=True, check=True, timeout=timeout_seconds)
    result = json.loads(child.stdout)
    assert result['pid'] != os.getpid()
    assert result['declaration']['declaration']['pid'] == result['pid']
    assert result['declaration']['declaration']['paths'] == [canonical_path('relative.txt', str(root))]
    assert 'owner@example.test' in result['declaration']['sender']
    assert result['read_back'] is True
    assert result['large_read_back'] is True
    stored = server.conversation_content._history._db.execute(
        'SELECT content FROM messages WHERE id=?', (result['escaped_id'],)).fetchone()[0]
    assert stored == 'To *:\n' + '\x01' * (65536 - len('To *:\n'.encode()))


@pytest.mark.parametrize('payload,headers,status', [
    ({'method': 'GET', 'path': '/api/universal/agent-mail/read', 'body': {'since': 0}, 'account': 'forged@example.test'}, {}, 400),
    ({'method': 'GET', 'path': '/api/universal/agent-mail/read', 'body': {'since': 0}}, {'Origin': 'https://outside.example'}, 403),
    ({'method': 'GET', 'path': '/api/universal/agent-mail/read', 'body': {'since': 0}}, {'Host': 'outside.example'}, 403),
    ({'method': 'GET', 'path': '/api/universal/agent-mail/read', 'body': {'since': 0, 'padding': 'x' * MAX_REQUEST_BYTES}}, {}, 413),
    ({'method': 'POST', 'path': '/api/universal/model-delegation-execute', 'body': {}}, {}, 403),
    ({'method': 'GET', 'path': '/api/universal/agent-mail/read', 'body': {'since': 0, '_peer': {'pid': 1}}}, {}, 400),
])
def test_local_channel_preserves_request_and_effect_boundaries(owner, payload, headers, status):
    server, root = owner
    surface = desktop.bind_coordination_surface(server, root)
    with pytest.raises(HTTPError) as refused:
        _post(surface, payload, headers=headers)
    assert refused.value.code == status
    refused.value.close()


def test_other_os_user_cannot_inherit_the_desktop_account(owner, monkeypatch, *, timeout_seconds: float = 10.0):
    import os
    import psutil
    import subprocess
    import sys
    server, root = owner
    surface = desktop.bind_coordination_surface(server, root)
    username = psutil.Process.username
    monkeypatch.setattr(psutil.Process, 'username',
        lambda process: username(process) if process.pid == os.getpid() else 'OTHER-OS-USER')
    program = '''
import sys
from urllib.request import urlopen
from urllib.error import HTTPError
try:
    with urlopen(sys.argv[1]) as response:
        print(response.status)
except HTTPError as refused:
    print(refused.code)
    refused.close()
'''
    child = subprocess.run([sys.executable, '-c', program,
        'http://127.0.0.1:%d/health' % surface.server_address[1]],
        capture_output=True, text=True, check=True, timeout=timeout_seconds)
    assert child.stdout.strip() == '403'


def test_shutdown_does_not_close_the_graph_under_an_inflight_request(owner, monkeypatch, *, timeout_seconds: float = 10.0):
    from nodelang import app_brain
    server, root = owner
    entered, release = threading.Event(), threading.Event()
    unbound = []
    original_unbind = app_brain.unbind
    def unbind(store):
        unbound.append(store)
        original_unbind(store)
    monkeypatch.setattr(app_brain, 'unbind', unbind)
    def dispatch(_request, *, timeout_seconds: float = 10.0):
        entered.set()
        assert release.wait(timeout_seconds)
        return {'settled': True}
    monkeypatch.setattr(server, 'dispatch_universal_machine_route', dispatch)
    surface = desktop.bind_coordination_surface(server, root)
    shutdown = surface.shutdown
    def immediate_shutdown(*, timeout_seconds: float = 0.0):
        shutdown(timeout_seconds=timeout_seconds)
    monkeypatch.setattr(surface, 'shutdown', immediate_shutdown)
    results = []
    worker = threading.Thread(target=lambda: results.append(_post(surface, {
        'method': 'GET', 'path': '/api/universal/mcp-broker', 'body': {}})), daemon=True)
    worker.start()
    try:
        assert entered.wait(timeout_seconds)
        with pytest.raises(TimeoutError, match='owner stays open'):
            server.close()
        assert unbound == []
        assert server.universal_store.snapshot().revision > 0
    finally:
        release.set()
        worker.join(timeout_seconds)
        monkeypatch.setattr(surface, 'shutdown', shutdown)
    assert results[0]['settled'] is True


@pytest.mark.parametrize('method,path,body', [
    ('POST', '/api/universal/workspace-roots', {'action': 'list'}),
    ('GET', '/api/universal/workspace-roots-state', {}),
])
def test_desktop_owns_workspace_reads_without_a_signed_owner(owner, method, path, body):
    server, root = owner
    before = server.universal_store.revision
    surface = desktop.bind_coordination_surface(server, root)
    answer = _post(surface, {'method': method, 'path': path, 'body': body})
    assert answer['account'] == 'owner@example.test'
    assert not hasattr(server, 'clean_authority')
    if method == 'POST':
        assert Path(answer['built_in']['path']) == server.universal_workspace_root
        assert answer['roots'] == []
    else:
        assert answer['graph_id']
        assert answer['revision'] == before
        assert len(answer['registry_digest']) == 64
    assert server.universal_store.revision == before
    assert getattr(server.universal_store, '_signed_commit_authority', None) is None


def test_desktop_workspace_registration_and_private_grants_round_trip(owner, monkeypatch):
    from nodelang import workspace_roots_catalogue as roots
    from tests_replica.test_workspace_roots_catalogue import _Key
    server, root = owner
    home = root / 'REGISTRY'
    home.mkdir()
    snapshot = home / 'workspace-roots.json'
    pin = home / 'workspace-roots.pin'
    monkeypatch.setattr(roots, 'default_snapshot_path', lambda: snapshot)
    monkeypatch.setattr(roots, 'default_pin_path', lambda: pin)
    monkeypatch.setattr(roots, 'default_last_good_path', lambda: home / 'last-good.json')
    # Only the existing hook-projection signer is isolated; no coordination key.
    key = _Key()
    monkeypatch.setattr(roots, 'app_signing_components',
        lambda: (lambda pinned: key, key.fingerprint, key))
    server.workspace_roots_boot = 'missing'
    surface = desktop.bind_coordination_surface(server, root)
    monkeypatch.setenv('ARCHHUB_COORDINATION_ENDPOINT',
        'http://127.0.0.1:%d/coordination' % surface.server_address[1])
    monkeypatch.setattr(roots, 'graph_context', roots._default_graph_context)
    folder = root / 'CLIENT'
    folder.mkdir()
    def workspace(body):
        return _post(surface, {'method': 'POST', 'path': '/api/universal/workspace-roots', 'body': body})
    registered = workspace({'action': 'register', 'id': 'client', 'path': str(folder),
        'privacy': 'private', 'writers': ['codex']})
    assert registered['roots'][0]['root_id'] == 'client'
    assert registered['roots'][0]['writers'] == ['codex']
    state = roots.verified_graph_state()
    body = json.loads(snapshot.read_text(encoding='utf-8'))
    assert state['registry_digest'] == roots.registry_digest({k:v for k,v in body.items() if k != 'signature'})
    session = 'app:agent-session:wsowner'
    granted = workspace({'action': 'grant-private-root', 'id': 'client', 'runtime': 'codex',
        'session_id': session, 'operations': ['write_file']})
    assert granted['last_private_grant_event']['message'] == 'Agent access granted.'
    grant = server.private_root_grants.list()[0]
    def no_self_forward():
        pytest.fail('the desktop Workspaces route forwarded to its own HTTP/pipe surface')
    monkeypatch.setattr(roots, 'graph_context', no_self_forward)
    from nodelang.settings_owner import SettingsOwner
    with server.mutation_lock:
        listed = SettingsOwner(server.universal_store, runtime=server)._roots()
        assert [row['root_id'] for row in listed] == ['archhub', 'client']
    server.native_folder_picker = lambda title: str(folder)
    server.start()
    def browser(body, *, timeout_seconds: float = 10.0):
        request = Request(server.url + '/api/universal/workspace-roots',
            data=json.dumps(body).encode(), headers={'Content-Type': 'application/json',
                'Cookie': 'ArchHub-Session=' + server.browser_session_token,
                'X-ArchHub-CSRF': server.browser_csrf_token})
        with urlopen(request, timeout=timeout_seconds) as response:
            return json.load(response)
    assert Path(browser({'action': 'browse'})['path']) == folder
    assert browser({'action': 'list'})['roots'][0]['root_id'] == 'client'
    with pytest.raises(HTTPError) as refused:
        workspace({'action': 'grant-private-root', 'id': 'missing', 'runtime': 'codex',
                   'session_id': session})
    assert refused.value.code == 400
    assert 'not a registered workspace root' in json.load(refused.value)['error']
    refused.value.close()
    assert grant['root_id'] == 'client' and grant['session_id'] == session
    assert grant['operations'] == ['write_file']
    assert grant['revoked'] is False
    assert granted['private_grants'][0]['root_digest'] == grant['root_digest']
    revoked = workspace({'action': 'revoke-private-root', 'id': 'client', 'runtime': 'codex',
        'session_id': session})
    assert revoked['last_private_grant_event']['message'] == 'Agent access revoked.'
    assert server.private_root_grants.list()[0]['revoked'] is True
    assert revoked['private_grants'] == []
    removed = workspace({'action': 'unregister', 'id': 'client'})
    assert removed['roots'][0]['state'] == 'unregistered'
    assert folder.is_dir()
    assert getattr(server.universal_store, '_signed_commit_authority', None) is None
    database, registry = server.universal_store.database_path, server.universal_registry
    server.close()
    from nodelang.universal_cell import CellStore
    with CellStore(database) as reopened:
        binding = roots.ApplicationWorkspaceAuthority(reopened, registry)
        assert binding.read()['roots'][0]['state'] == 'unregistered'
    print('WSOWNER register=1 grant=1 revoke=1 unregister=1 persisted=1 signed_owner=absent')


def test_native_workspace_binding_keeps_fingerprint_only_enrollment(owner):
    from nodelang import workspace_roots_catalogue as roots, commit_intent
    server, _root = owner
    binding = server._workspace_roots_binding
    with commit_intent.declare(commit_intent.USER_ACTION, actor=server.universal_registry.authorization.subject_root,
                              reason='isolated historical workspace enrollment'):
        binding.save({'installed': True, 'roots': [],
                      'key': {'key_id': roots.KEY_ID, 'fingerprint': 'a' * 64}})
    catalogue = roots.find_workspace_root_catalogue(binding, caller=server.workspace_roots_caller)
    assert roots.read_enrollment(binding, catalogue, caller=server.workspace_roots_caller) == {
        'fingerprint': 'a' * 64, 'mode': 'legacy', 'enrolled_by': '', 'enrolled_at': ''}


def test_native_workspace_binding_preserves_the_existing_graph_catalogue(legacy_workspace_graph, monkeypatch):
    from types import SimpleNamespace
    from nodelang import workspace_roots_catalogue as roots, commit_intent
    from nodelang.universal_cell import CellStore
    graph = legacy_workspace_graph
    authority = graph['authority']
    original = roots.read_state(authority, graph['catalogue'], caller=graph['built'].caller)
    database = authority.store.database_path
    registry = SimpleNamespace(application_root=authority.manifest.application_root,
        authorization=SimpleNamespace(subject_root=authority.manifest.principal_root))
    authority.store.close()
    def no_adoption_or_key(*args, **kwargs):
        pytest.fail('reading the existing workspace catalogue attempted adoption or signing')
    from nodelang import persistence, unified_authority
    monkeypatch.setattr(persistence, 'bind_selected_application_authority', no_adoption_or_key)
    monkeypatch.setattr(unified_authority, 'open_unified_authority', no_adoption_or_key)
    monkeypatch.setattr(graph['provider'], 'sign', no_adoption_or_key)
    with CellStore(database) as store:
        binding = roots.ApplicationWorkspaceAuthority(store, registry)
        before = store.revision
        state = binding.read()
        assert state['installed'] is True
        assert state['roots'] == list(original[1])
        assert state['key']['fingerprint'] == original[2]
        assert store.revision == before
        with commit_intent.declare(commit_intent.USER_ACTION, actor=registry.authorization.subject_root,
                                  reason='isolated workspace writer update'):
            binding.revise('client-a', {'writers': ['codex']})
        assert binding.read()['roots'][0]['writers'] == ['codex']
        assert getattr(store, '_signed_commit_authority', None) is None
    with CellStore(database) as store:
        assert roots.ApplicationWorkspaceAuthority(store, registry).read()['roots'][0]['writers'] == ['codex']


def test_desktop_rejects_legacy_workspace_approvals_without_writes(owner):
    from nodelang import workspace_roots_catalogue as roots
    from tests_replica.test_workspace_roots_catalogue import _Key
    server, root = owner
    surface = desktop.bind_coordination_surface(server, root)
    folder = root / 'CLIENT'
    folder.mkdir()
    key = _Key()
    requests = [{'action': 'prepare', 'change': {'action': 'register', 'id': 'client',
                 'path': str(folder), 'privacy': 'private'},
                 'public_blob': key.public_blob().hex(), 'key_check': key.sign(roots.KEY_CHECK)}]
    requests += [{'action': 'list', field: None}
                 for field in ('signature', 'public_blob', 'key_check', 'admission_ticket')]
    before = server.universal_store.revision
    for body in requests:
        with pytest.raises(HTTPError) as refused:
            _post(surface, {'method': 'POST', 'path': '/api/universal/workspace-roots', 'body': body})
        assert refused.value.code == 400
        assert 'signed approvals are no longer used' in json.load(refused.value)['error']
        refused.value.close()
        assert server.universal_store.revision == before
    assert server._workspace_roots_binding.read()['installed'] is False
