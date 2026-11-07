"""GRAPHOUT: release bytes, complete lazy import closure, and real route dispatch."""
import ast
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / '01.APP'
RETIRED_MODULES = {
    '.'.join(Path(row['path']).relative_to('01.APP').with_suffix('').parts)
    for row in json.loads((ROOT / '05.EVIDENCE/graphout/removed.json').read_text(encoding='utf-8'))
    if row['path'].startswith('01.APP/')
}


def retired(name):
    return name in RETIRED_MODULES or 'nodelang.' + name in RETIRED_MODULES or any(part.startswith(('cell_', 'universal_')) or part in {
        'application_server', 'postgres_cell_journal', 'core', 'laws_structure', 'laws_effect', 'laws_relation', 'laws_surface', 'laws_decision', 'serve_canvas', 'graph_api', 'application_machine_transport',
        'persistence', 'canvas_graph_owner', 'app_brain',
    } for part in name.split('.'))


def preflight():
    spec = importlib.util.spec_from_file_location('preflight_imports', ROOT / '03.TOOLS/packaging/preflight_imports.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_tree_has_no_retired_runtime():
    offenders = [str(path.relative_to(SOURCE)) for path in SOURCE.rglob('*.py') if retired('.'.join(path.relative_to(SOURCE).with_suffix('').parts))]
    assert not offenders, offenders


def test_complete_release_import_closure():
    module = preflight()
    files = module.import_closure(ROOT, module.release_entries(ROOT))
    assert files
    assert not [str(path) for path in files if retired(path.stem)]
    # Missing local lazy imports must not disappear silently from the closure.
    for relative in files:
        package = '.'.join(relative.with_suffix('').parts[1:-1])
        for node in ast.walk(ast.parse((ROOT / relative).read_text(encoding='utf-8-sig'))):
            if isinstance(node, ast.ImportFrom):
                target = importlib.util.resolve_name('.' * node.level + (node.module or ''), package) if node.level else (node.module or '')
                assert not retired(target), (relative, node.lineno, target)
                assert not any(retired(target + '.' + alias.name) for alias in node.names), (relative, node.lineno, target)
            elif isinstance(node, ast.Import):
                assert not any(retired(alias.name) for alias in node.names), (relative, node.lineno)


@pytest.mark.parametrize('arguments', [[], ['--baboom']])
def test_boot_entries_import_no_retired_modules(arguments):
    script = '''
import importlib, runpy, sys
from unittest.mock import patch
from nodelang import nograph_launcher
for name in ('nograph_server', 'nograph_launcher', 'native_agent_mcp', 'hook_decision', 'baboom_native_runtime'):
    importlib.import_module('nodelang.' + name)
sys.argv = ['launcher.py', *sys.argv[1:]]
stdout, stderr = sys.stdout, sys.stderr
try:
    with patch.object(nograph_launcher, 'run', return_value=0):
        try:
            runpy.run_module('nodelang.launcher', run_name='__main__')
        except SystemExit as exit:
            assert exit.code == 0, exit.code
finally:
    sys.stdout, sys.stderr = stdout, stderr
bad = [name for name in sys.modules if name.startswith('nodelang.') and
       (name in retired_modules or any(part.startswith(('cell_', 'universal_')) for part in name.split('.')))]
assert not bad, bad
print('GRAPHOUT boot imports: zero retired modules')
'''
    script = 'retired_modules = ' + repr(sorted(RETIRED_MODULES)) + '\n' + script
    environment = {**os.environ, 'PYTHONPATH': str(SOURCE), 'QT_QPA_PLATFORM': 'offscreen'}
    result = subprocess.run([sys.executable, '-B', '-c', script, *arguments], env=environment,
                            capture_output=True, text=True, encoding='utf-8', timeout=90,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'zero retired modules' in result.stdout


def test_every_route_lazily_imports_no_retired_modules(tmp_path, monkeypatch):
    from nodelang import nograph_server as ng
    from nodelang.nograph_server import NoGraphServer, Refused
    from nodelang.social_linkedin_signin import LinkedInNotReady
    from nodelang.social_meta_signin import MetaNotReady

    server = NoGraphServer(tmp_path / 'state')
    monkeypatch.setattr(ng, '_SERVER', server)
    # Outside services are absent. Route handlers and file owners remain real.
    monkeypatch.setattr(server, 'account_read', lambda: {'ok': False, 'signed_in': False})
    for name in ('_hosts', '_local', '_models', '_providers', '_workshop_agents', '_live_agents', '_messages'):
        cache = getattr(server, name, None)
        if cache is not None:
            monkeypatch.setattr(cache, 'get', lambda: {})
    monkeypatch.setattr(ng, '_list_messages', lambda before=None: {'messages': [], 'more': False})
    monkeypatch.setattr(ng, '_baboom_brain', lambda: {'ok': False})
    from nodelang import notion_mcp
    monkeypatch.setattr(notion_mcp, 'connect', lambda: {'ok': False, 'error': 'Not connected in this court'})
    visited = []
    try:
        for path, (_owner, handler) in ng.ROUTES.items():
            body = {'action': 'state'}
            if path == '/api/session-files':
                body = {'action': 'new', 'title': 'GRAPHOUT route'}
            request = SimpleNamespace(method='GET', path=path, query={}, body=body)
            try:
                response = handler(server, request)
                assert response is not None, path
            except (Refused, ValueError, LinkedInNotReady, MetaNotReady) as refusal:
                assert str(refusal), path
            assert not [name for name in sys.modules if name.startswith('nodelang.') and retired(name)], path
            visited.append(path)
        assert visited == list(ng.ROUTES)
    finally:
        server.httpd.server_close()
        from nodelang.brain_files import close
        close()


def test_remote_claim_uses_the_same_workshop_task_file(tmp_path):
    from nodelang.cloud_relay import McpWorkshopAgents
    from nodelang.workshop_mailbox import call
    database = tmp_path / 'messages.sqlite3'
    created = call('task_create', {'title': 'GRAPHOUT remote claim'},
                   {'archhub/sessionID': 'creator'}, database=database)
    task = created['task']['id']
    relay = McpWorkshopAgents(mailbox_path=database)
    claimed = relay.call({'client_id': 'graphout-fixture', 'client_name': 'Codex'},
                         'claim_work', {'work_root': task})
    assert claimed['ok'] and claimed['task']['id'] == task
    assert Path(created['session']['path']).is_file()
    assert not [name for name in sys.modules if name.startswith('nodelang.') and retired(name)]


def test_mod_effect_configuration_uses_the_current_settings_owner(tmp_path):
    from nodelang.enforce import graph_parameters
    from nodelang.nograph_server import JsonFile, _mods_rows
    from nodelang.domains.selfext import run_mod_node
    owner = JsonFile(tmp_path / 'mods.json', {'packages': {}, 'enabled': {}})
    owner.write({'packages': {}, 'enabled': {}, 'params': {'element-limit': {'Limit': 7}},
                 'fired_today': {'element-limit': 2}})
    row = next(row for row in _mods_rows(owner)['rows'] if row['id'] == 'element-limit')
    assert row['nodes'][0]['params']['Limit'] == 7 and row['fired_today'] == 2
    assert graph_parameters(owner)
    owner.update({'enabled': {'enforce': False}})
    with pytest.raises(ValueError, match='disabled'):
        graph_parameters(owner)
    assert run_mod_node({'text': 'kept'}) == ({'out': 'kept'}, 'kept')


def test_historical_journals_are_never_opened_by_profile_content_audit(tmp_path, monkeypatch):
    from test_state_isolation import _marked_files
    marker = 'graphout-isolated-marker'
    journal = tmp_path / 'previous.universal.sqlite3'
    sidecar = tmp_path / 'previous.universal.sqlite3-wal'
    ordinary = tmp_path / 'owner.json'
    for path in (journal, sidecar, ordinary):
        path.write_text(marker, encoding='utf-8')
    opened = []
    original = Path.open
    def observe(path, *args, **kwargs):
        opened.append(path)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', observe)
    assert _marked_files(tmp_path, marker) == {str(ordinary)}
    assert journal not in opened and sidecar not in opened


def test_plain_preferences_keep_secret_validation_and_atomic_readback(tmp_path, monkeypatch):
    import json
    import app.secrets_store as secrets
    path = tmp_path / 'settings.json'
    monkeypatch.setattr(secrets, 'SETTINGS_FILE', path)
    secrets.save_setting('theme', 'dark')
    assert json.loads(path.read_text(encoding='utf-8'))['theme'] == 'dark'
    before = path.read_bytes()
    with pytest.raises(ValueError, match='secret-bearing'):
        secrets.save_setting('nested', {'access_token': 'fixture-value'})
    assert path.read_bytes() == before


def test_native_prompt_context_reads_the_current_workshop_owner():
    from nodelang.workshop_mailbox import application_history, ROOM, CATEGORY
    from nodelang.native_agent_hooks import user_prompt_submit_context
    with application_history() as history:
        history.append(ROOM, author='fixture', category=CATEGORY,
                       content='graphout-context-' + 'a' * 2000, idempotency_key='graphout-context')
    result = user_prompt_submit_context(context={'archhub/sessionID': 'graphout-context'})
    context = result['hookSpecificOutput']['additionalContext']
    assert 'graphout-context-' in context and 'a' * 1500 not in context
    assert not [name for name in sys.modules if name.startswith('nodelang.') and retired(name)]


def test_workshop_history_refuses_historical_journals_before_sqlite_open(tmp_path):
    from nodelang.conversation_history import ConversationHistoryStore
    journal = tmp_path / 'history.universal.sqlite3'
    journal.write_bytes(b'founder-owned historical journal')
    with pytest.raises(ValueError, match='Retired graph journals'):
        ConversationHistoryStore(journal, instance_id='test')
    assert journal.read_bytes() == b'founder-owned historical journal'


def test_optional_remote_session_relay_uses_the_current_account_owner(tmp_path, monkeypatch):
    from nodelang import cloud_relay, cloud_session, cloud_publish_consent
    account = ['owner@example.test']
    monkeypatch.setattr(cloud_session, 'signed_in_cloud_account', lambda *a, **kw: account[0])
    monkeypatch.setattr(cloud_publish_consent, 'cloud_publish_allowed', lambda *a, **kw: True)
    monkeypatch.setattr(cloud_relay, 'load_cloud_session', lambda *a: {'base_url': 'https://api.archhub.io', 'token': 'fixture'})
    monkeypatch.setattr(cloud_relay.CloudRelay, 'start', lambda self: self)
    transport = SimpleNamespace(discover=lambda: {'status': 'ok', 'recipients': []})
    relay = cloud_relay.start_cloud_relay(appdata=tmp_path, state_dir=tmp_path,
        respond=lambda _: {}, execute=lambda _: {}, session_transport=transport)
    assert relay.session_caller(account[0], 'list_sessions', {}) == {'sessions': []}
    account[0] = 'changed@example.test'
    with pytest.raises(PermissionError, match='another signed-in account'):
        relay.session_caller('owner@example.test', 'list_sessions', {})


def test_cursor_hook_resolves_the_current_graph_free_entry():
    from nodelang.native_agent_hooks import cursor_hook_command
    command = cursor_hook_command()
    assert 'native_stop_hook.py' in command and '--vendor cursor' in command
    assert not [name for name in sys.modules if name.startswith('nodelang.') and retired(name)]


def test_updater_protects_journals_and_recovery_sidecars(tmp_path):
    from nodelang.quiet_update import _protected_file, _payload_files
    app = tmp_path / 'payload'
    source = app / 'nodelang'
    source.mkdir(parents=True)
    for name in ('history.universal.sqlite3', 'history.universal.sqlite3-wal',
                 'history.universal.sqlite3-shm', 'router.db-wal'):
        path = source / name
        path.write_bytes(b'isolated recovery fixture')
        assert _protected_file(path), name
    code = source / 'current.py'
    code.write_text('pass', encoding='utf-8')
    assert list(_payload_files(app)) == [code]
