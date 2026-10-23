"""Real compiler courts for the existing self-extension install action."""
import os
from pathlib import Path

import pytest

from nodelang import Store
from nodelang.domains import selfext
from tools.pipeline import strict_check
from tests_domains.test_selfext import _green_court

pytest_plugins = ['tests_replica.test_canvas_graph_owner']


@pytest.fixture(autouse=True)
def real_compiler(monkeypatch, tmp_path):
    binary = Path(os.environ['ACOMPILER_REAL_BINARY'])
    assert binary.is_file()
    monkeypatch.setattr(strict_check, '_command', lambda *_: [str(binary)])
    # Ordinary installed action has no product Git checkout. All its temporary
    # observations stay in the one isolated fixture root.
    from nodelang import enforce
    defaults = enforce.defaults
    monkeypatch.setattr(enforce, 'defaults', lambda: {**defaults(), 'repo_root': str(tmp_path)})


def extension(**options):
    store = Store()
    domain = selfext.build_self_extension_domain(store, **options)
    _green_court(store, domain)
    selfext.set_install_approval(store, domain, True, approver='fixture-founder', approved_at='fixture')
    return store, domain


@pytest.mark.parametrize('baseline', [None, {'previous': 'graph'}])
def test_install_runs_and_rolls_back_through_real_compiler(baseline):
    store, domain = extension(generated=[{'role': 'value', 'title': 'Fixture extension',
        'primitive': 'value', 'configuration': {'value': 42}}], baseline=baseline)
    sink = {}
    receipt = selfext.apply_installation(store, domain, sink)
    assert receipt['fired'] and sink[receipt['target']] == receipt['after']
    assert store.pull(domain['generated_manifest'])[0]['configuration']['value'] == 42
    assert receipt['enforcement']['content_sha256'] == receipt['enforcement']['readback_sha256']
    assert store.pull(domain['installed']) is True
    selfext.set_rollback_approval(store, domain, True, approver='fixture-founder', approved_at='fixture')
    rolled = selfext.apply_rollback(store, domain, sink)
    assert rolled['fired'] and sink[receipt['target']]['action'] == 'restore_baseline'
    assert sink[receipt['target']]['baseline'] == baseline
    assert store.pull(domain['installed']) is False


def test_rollback_without_baseline_is_refused_by_real_compiler(tmp_path):
    store, domain = extension()
    pending = selfext._selfext_pending(store, domain, domain['rollback_effect'])
    del pending['content']['baseline']
    result = strict_check.check_artifact(tmp_path, pending, context=pending)
    assert not result['ok']
    assert any(row['code'] == 'E0009' and 'baseline' in row['message'] for row in result['diagnostics'])


@pytest.mark.parametrize('gate', ['conduct', 'scan'])
@pytest.mark.parametrize('file', [None, '10.PRODUCT/11.ARCHHUB-APP', 'README.md'], ids=['EMPTY', 'EXACT', 'OTHER'])
@pytest.mark.parametrize('identity', ['SELFEXT-RUNTIME', ' SELFEXT-RUNTIME '], ids=['PLAIN', 'PADDED'])
def test_runtime_intent_source_gate(tmp_path, gate, file, identity):
    import json
    import subprocess

    repo = tmp_path / 'REPO'
    repo.mkdir()
    subprocess.run(['git', '-c', 'core.longpaths=true', 'init', '-q', str(repo)], check=True)
    subprocess.run(['git', '-C', str(repo), 'config', 'core.longpaths', 'true'], check=True)
    if file:
        path = repo / file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('', encoding='utf-8')
        subprocess.run(['git', '-C', str(repo), 'add', '--', file], check=True)
    subprocess.run(['git', '-C', str(repo), '-c', 'user.name=EXTINSTALL fixture',
        '-c', 'user.email=fixture@example.invalid', 'commit', '-q', '--allow-empty',
        '-m', 'Fixture change\n\nIntent: SELFEXT-RUNTIME'], check=True)
    context = tmp_path / 'CONTEXT.json'
    context.write_text(json.dumps({'intent': identity, 'author': 'EXTINSTALL fixture',
        'files': [file] if file else [], 'why': 'Real compiler boundary court',
        'conduct_events': [{'kind': 'operation', 'effect': 'read'}]}), encoding='utf-8')
    args = [os.environ['ACOMPILER_REAL_BINARY'], gate, '--root', str(repo), '--context', str(context)]
    if gate == 'scan':
        args += ['--json', '--report-only']
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    assert result.returncode != 0, result.stdout
    assert 'SELFEXT-RUNTIME is reserved for self-extension artifact checks' in result.stderr


def test_harmful_generated_engine_is_refused_before_any_write():
    store, domain = extension()
    store.edit(domain['generated_params'][0]['primitive'], ['body', 'floor', 'value'], 'host')
    sink = {}
    with pytest.raises(PermissionError, match='E0009.*no type rule'):
        selfext.apply_installation(store, domain, sink)
    assert not sink and store.pull(domain['installed']) is False


def test_exact_approval_remains_required_after_content_changes():
    store, domain = extension()
    store.edit(domain['generated_params'][0]['configuration'], ['body', 'floor', 'value'], {'value': 'unapproved'})
    sink = {}
    with pytest.raises(PermissionError, match='content changed since exact approval'):
        selfext.apply_installation(store, domain, sink)
    assert not sink and store.pull(domain['installed']) is False


def test_unrelated_host_target_gets_no_runtime_install_authority():
    proposal = {**selfext.DEFAULT_PROPOSAL, 'target_scope': 'revit://private/element/1'}
    store, domain = extension(proposal=proposal)
    sink = {}
    with pytest.raises(PermissionError, match='E0010|E0101'):
        selfext.apply_installation(store, domain, sink)
    assert not sink


def test_library_folder_install_run_disable_remove_and_harm_refusal(ops, tmp_path):
    import json
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen

    def post(body, path='/api/universal/mods'):
        request = Request(ops.server.public_url + path, data=json.dumps(body).encode(), method='POST',
            headers={'Content-Type': 'application/json', 'X-ArchHub-Session': ops.server.browser_session_token,
                     'X-ArchHub-CSRF': ops.server.browser_csrf_token})
        try:
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as error:
            error.msg += ': ' + error.read().decode()
            raise

    folder = tmp_path / 'PACKAGE'
    folder.mkdir()
    path = folder / 'manifest.json'
    content = {'name': 'Fixture counter', 'nodes': [
        {'title': 'Fixture count', 'behavior': {'engine': 'shape.count'}, 'params': {}}]}
    path.write_text(json.dumps(content), encoding='utf-8')
    reviewed = post({'action': 'review', 'path': str(folder)})['review']
    installed = post({'action': 'install', 'path': str(folder), 'reviewed_digest': reviewed['digest']})['mod']
    made = post({'op': 'import_mod_node', 'args': [installed['id'], installed['nodes'][0]['id']]},
                '/api/universal/canvas-op')['result']['id']
    run = post({'roots': [made]}, '/api/universal/run-graph')
    assert run['pending'][made] == 'input items is not wired'
    from nodelang.universal_pipeline import create_engine_node
    source = create_engine_node(ops.store, ops.registry, title='Fixture input', engine='data.list',
        properties={'value': '[1, 2, 3]'}, authentication_context=ops.context)['root']
    ops._connect(source, made, ('value', 'items'))
    run = post({'roots': [source, made]}, '/api/universal/run-graph')
    assert made in run['outputs'], run
    assert run['outputs'][made]['count'] == 3 and run['ran'] == 2
    post({'action': 'enable', 'id': installed['id'], 'enabled': False})
    with pytest.raises(HTTPError):
        post({'op': 'import_mod_node', 'args': [installed['id'], installed['nodes'][0]['id']]},
             '/api/universal/canvas-op')
    post({'action': 'enable', 'id': installed['id'], 'enabled': True})
    post({'action': 'remove', 'id': installed['id']})
    assert installed['id'] not in {row['id'] for row in post({'action': 'state'})['mods']['rows']}
    path.write_text(json.dumps({**content, 'permissions': ['host.write']}), encoding='utf-8')
    revision = ops.store.revision
    with pytest.raises(HTTPError) as refusal:
        post({'action': 'review', 'path': str(folder)})
    assert 'executable permission or hook adapter' in str(refusal.value)
    assert ops.store.revision == revision


def test_previous_release_graph_adds_only_the_missing_mod_route(monkeypatch):
    from nodelang import universal_application as app
    from nodelang.map_import import resolve_map_path
    from tests_replica.test_application_agent_body_security import _provider

    keys = _provider()
    with monkeypatch.context() as previous:
        previous.setattr(app, '_APPLICATION_HTTP_ROUTE_SPECS', tuple(
            row for row in app._APPLICATION_HTTP_ROUTE_SPECS if row[1] != '/api/universal/mods'))
        previous.setattr(app, '_NEWAPP_HTTP_ROUTE_KEYS', app._NEWAPP_HTTP_ROUTE_KEYS - {'POST /api/universal/mods'})
        store, registry = app.build_universal_application(resolve_map_path(), key_provider=keys)
    before = dict(registry.application_http_route_roots)
    assert 'POST /api/universal/mods' not in before
    store, restored = app.restore_universal_application(resolve_map_path(), store, key_provider=keys)
    assert restored.application_http_route_roots['POST /api/universal/mods']
    assert all(restored.application_http_route_roots[key] == root for key, root in before.items())


def test_parameter_socket_does_not_shadow_wire_but_duplicate_connections_refuse():
    from nodelang.universal_cell import InvalidCell
    from nodelang.universal_pipeline import _pipeline_port_name

    port = {'id': 'connection', 'owner': 'node', 'side': 'target', 'mode': 'connection',
            'name': 'items', 'name_root': 'connection-name'}
    node = {'id': 'node', 'ports': [port, {**port, 'id': 'parameter', 'mode': 'parameter'}]}
    assert _pipeline_port_name(node, 'connection', 'target', 'wire') == 'items'
    node['ports'].append({**port, 'id': 'duplicate'})
    with pytest.raises(InvalidCell, match='ambiguous target interface name'):
        _pipeline_port_name(node, 'connection', 'target', 'wire')
