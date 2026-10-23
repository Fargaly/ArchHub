"""Source-lane integration: real graph owners, isolated profile and mocked UI/network."""
import json
import sqlite3
from contextlib import closing
from pathlib import Path
import pytest
from nodelang import cloud_session, persistence
from nodelang.universal_cell import CellStore, InvalidCell


def test_workshop_library_inputs_use_the_same_typed_settings_contract():
    from nodelang.library_engines import LIBRARY_ITEM_ENGINES, engine_sockets
    from nodelang.pipeline_engines import tool_settings
    params = dict(LIBRARY_ITEM_ENGINES['tool_workshop']['params'])
    result, _ = tool_settings(params, {'backup_count': 7, 'keep_running_in_tray': True})
    assert result['out']['backup_count'] == 7
    assert result['out']['backup_budget_bytes'] == params['backup_budget_bytes']
    assert result['out']['keep_running_in_tray'] is True
    assert set(params) <= set(engine_sockets('tool.workshop')['target'])
    with pytest.raises(ValueError, match='backup_count'):
        tool_settings(params, {'backup_count': 0})


def test_second_launch_forwards_arguments_to_the_existing_qt_owner():
    import ast
    import socket
    import threading
    from types import SimpleNamespace
    source = ast.parse((Path(__file__).resolve().parents[2] / "01.APP/nodelang/launcher.py").read_text(encoding='utf-8'))
    names = {'_forward_launch_arguments', '_serve_launch_requests', '_resume_from_launch'}
    definitions = [node for node in ast.walk(source) if isinstance(node, ast.FunctionDef) and node.name in names]
    properties, activated = {}, []
    verified_owner = SimpleNamespace(is_running=lambda: True)
    namespace = {'_verified_launch_owner': lambda port: verified_owner,
        'app': SimpleNamespace(setProperty=lambda key, value: properties.update({key: value})),
        'window': SimpleNamespace(showNormal=lambda: activated.append('show'),
            raise_=lambda: activated.append('raise'), activateWindow=lambda: activated.append('activate'))}
    exec(compile(ast.Module(body=definitions, type_ignores=[]), '<launcher IPC>', 'exec'), namespace)
    received, done = [], threading.Event()
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        class Once:
            used = False
            def accept(self):
                if self.used:
                    raise OSError('fixture done')
                self.used = True
                return listener.accept()
        def deliver(arguments):
            received.append(arguments)
            namespace['_resume_from_launch'](arguments)
            done.set()
        worker = threading.Thread(target=namespace['_serve_launch_requests'], args=(Once(), deliver), daemon=True)
        worker.start()
        arguments = ['archhub://workshop/existing', '--source=second launch']
        assert namespace['_forward_launch_arguments'](listener.getsockname()[1], arguments) is True
        assert done.wait(3)
        worker.join(3)
        assert not worker.is_alive()
    assert received == [arguments]
    assert properties['archhubLaunchArguments'] == arguments
    assert activated == ['show', 'raise', 'activate']
    assert namespace['_forward_launch_arguments'](0, ['x' * 9000]) is False
    namespace['_verified_launch_owner'] = lambda port: None
    assert namespace['_forward_launch_arguments'](0, ['private document']) is False


def test_account_locator_uses_os_profile_and_explicit_court_profile(tmp_path, monkeypatch):
    normal = tmp_path / 'windows-roaming'
    monkeypatch.delenv('ARCHHUB_TEST_STATE_DIR', raising=False)
    monkeypatch.setenv('APPDATA', str(tmp_path / 'agent-roaming'))
    monkeypatch.setattr(cloud_session, '_roaming_directory', lambda: normal)
    assert cloud_session.cloud_session_path() == normal / 'ArchHub' / 'brain' / 'cloud.json'
    isolated = tmp_path / 'isolated'
    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(isolated))
    monkeypatch.setattr(cloud_session, '_roaming_directory', lambda: pytest.fail('court used the Windows profile'))
    assert cloud_session.cloud_session_path() == isolated / 'brain' / 'cloud.json'
    assert not normal.exists() and not isolated.exists()


def test_router_and_settings_share_one_graph_binding_and_restart(tmp_path, monkeypatch):
    from app import secrets_store
    from nodelang import model_router
    source = tmp_path / 'settings.json'
    source.write_text('{"default_model":"openrouter/vendor/old"}', encoding='utf-8')
    original = source.read_bytes()
    monkeypatch.setattr(secrets_store, 'SETTINGS_FILE', source)
    graph = tmp_path / 'authority.sqlite3'
    with CellStore(graph) as owner:
        persistence.migrate_local_truths(owner, settings_path=source)
        secrets_store.bind_settings_owner(owner)
        try:
            assert model_router._application_secrets_store() is secrets_store
            assert secrets_store.load_setting('default_model') == 'openrouter/vendor/old'
            secrets_store.save_setting('default_model', 'openrouter/vendor/new')
            assert model_router._application_secrets_store().load_setting('default_model') == 'openrouter/vendor/new'
        finally:
            secrets_store.unbind_settings_owner(owner)
    with CellStore(graph) as owner:
        secrets_store.bind_settings_owner(owner)
        try:
            assert secrets_store.load_setting('default_model') == 'openrouter/vendor/new'
            assert persistence.migrate_local_truths(owner, settings_path=source)['state'] == 'already_migrated'
        finally:
            secrets_store.unbind_settings_owner(owner)
    assert source.read_bytes() == original


def test_backup_graph_parameters_restart_and_final_close_publish_one_database(tmp_path, monkeypatch):
    from nodelang.application_server import ApplicationServer
    from nodelang.cell_secret_keys import MemorySigningKeyProvider
    from nodelang import universal_application as app
    from nodelang import commit_intent
    from nodelang.backup_retention import backup_policy
    provider = MemorySigningKeyProvider('archhub.local.relationship-authority', b'r' * 32)
    provider.add_key('archhub.local.court-attestation', b'c' * 32)
    graph = tmp_path / 'authority.sqlite3'
    def boot():
        return ApplicationServer(universal_state_path=graph, universal_key_provider=provider,
            enable_machine_transport=False, enable_universal_cloud_gateway=False, live_watch=False)
    server = boot()
    try:
        store, registry = server.universal_store, server.universal_registry
        assert app.read_universal_keep_running_in_tray(store.snapshot(), registry) is True
        root = app._system_tool_canvas_root('tool_workshop')
        with commit_intent.declare(commit_intent.USER_ACTION, actor='app:archhub', reason='fixture changes Settings'):
            app.apply_universal_canvas_gesture(store, registry, roots=[root], focus_root=root)
            for key, value in [('backup_count', 5), ('backup_budget_bytes', 128 * 1024**2)]:
                relation, _ = app._workshop_board_property_root(root, key)
                app.edit_universal_property(store, registry, relation, str(value))
            relation, _ = app._workshop_board_property_root(root, 'keep_running_in_tray')
            app.edit_universal_property(store, registry, relation, 'false')
        assert app.read_universal_keep_running_in_tray(store.snapshot(), registry) is False
        assert backup_policy(store.snapshot(), registry) == {'keep_count':5,'max_bytes':128 * 1024**2}
        assert backup_policy(store.snapshot()) == backup_policy(store.snapshot(), registry)
        canvas = app.project_universal_canvas(store, registry)
        params = next(node['params'] for node in canvas['nodes'] if node['id'] == root)
        assert next(row['value'] for row in params if row['label'] == 'backup_count') == 5
        assert next(row['value'] for row in params if row['label'] == 'keep_running_in_tray') is False
        with pytest.raises(InvalidCell):
            with commit_intent.declare(commit_intent.USER_ACTION, actor='app:archhub', reason='fixture invalid Settings'):
                relation, _ = app._workshop_board_property_root(root, 'backup_count')
                app.edit_universal_property(store, registry, relation, '0')
    finally:
        server.close()


    server = boot()
    try:
        assert backup_policy(server.universal_store.snapshot(), server.universal_registry)['keep_count'] == 5
        assert app.read_universal_keep_running_in_tray(server.universal_store.snapshot(), server.universal_registry) is False
        assert server.conversation_content._path == graph
        from nodelang import application_recovery_files
        def fail_preservation(*args, **kwargs):
            raise OSError('fixture preservation failure')
        with monkeypatch.context() as failure:
            failure.setattr(application_recovery_files, 'publish_application_recovery', fail_preservation)
            with pytest.raises(OSError, match='fixture preservation failure'):
                server.close(recovery_directory=tmp_path / 'backups',
                    recovery_authentication_context=server.universal_registry.authorization.session.context(),
                    recovery_timeout_seconds=60)
        assert server._runtime_fence_release is not None
        primary = server.universal_store.sqlite_storage()[0]
        assert primary.execute('PRAGMA main.locking_mode').fetchone()[0] == 'exclusive'
        with closing(sqlite3.connect(graph, timeout=0.05, isolation_level=None)) as other:
            with pytest.raises(sqlite3.OperationalError, match='locked'):
                other.execute('BEGIN IMMEDIATE')
        assert server.runtime_ownership_state()[2] == 'released'
        assert server.universal_store._runtime_presence_lease_storage._connection is primary
        recovery = server.close(recovery_directory=tmp_path / 'backups',
            recovery_authentication_context=server.universal_registry.authorization.session.context(),
            recovery_timeout_seconds=60)
        manifest = json.loads((Path(recovery) / 'recovery.json').read_text(encoding='utf-8'))
        assert manifest['files']['graph'] == manifest['files']['content']
        assert len(list(Path(recovery).glob('*.sqlite3'))) == 1
    finally:
        server.close()

def test_selected_authority_and_desktop_coordination_use_the_same_live_store(tmp_path, monkeypatch):
    from tests_replica.test_clean_server_visual_projection import _provision_clean_runtime
    from nodelang.application_server import ApplicationServer
    from nodelang import desktop, cell_secret_keys
    from nodelang.runtime_caller_capability import WindowsDpapiCallerKeyStore
    from urllib.request import urlopen
    built, provider = _provision_clean_runtime(tmp_path)
    location = built.location
    database = location.database_path
    provider.add_key('archhub.local.relationship-authority', b'r' * 32)
    provider.add_key('archhub.local.court-attestation', b'c' * 32)
    original_cells = dict(location.authority.store.snapshot().cells)
    original_revision = location.authority.store.revision
    location.authority.store.close()
    server = ApplicationServer(universal_state_path=database, universal_key_provider=provider,
        enable_machine_transport=False, enable_universal_cloud_gateway=False, live_watch=False)
    class FixedProvider:
        @staticmethod
        def default_path():
            return tmp_path / 'unused-provider'
        def __new__(cls, path):
            return provider
    monkeypatch.setattr(cell_secret_keys, 'WindowsDpapiSigningKeyProvider', FixedProvider)
    monkeypatch.setattr(WindowsDpapiCallerKeyStore, 'default_path', staticmethod(lambda: location.root / 'callers.dpapi.json'))
    monkeypatch.setenv('ARCHHUB_COORDINATION_ENDPOINT', 'http://127.0.0.1:0/coordination')
    try:
        assert dict(server.universal_store.at(original_revision).cells) == original_cells
        preserved = list((database.parent / 'backups').glob('application-cutover-*/graph.sqlite3'))
        assert len(preserved) == 1
        with closing(sqlite3.connect(preserved[0])) as saved:
            saved_cells = {row[0]: (row[1], row[2], bytes(row[3])) for row in
                saved.execute('SELECT cell_id,link0,link1,atom FROM current_cells')}
        assert saved_cells == {root: (cell.link0, cell.link1, cell.atom) for root, cell in original_cells.items()}
        surface = desktop.bind_coordination_surface(server, tmp_path)
        assert surface is not None
        assert surface.coordination_host.store is server.universal_store
        assert server.conversation_content._path == database
        with urlopen('http://127.0.0.1:%d/health' % surface.server_address[1], timeout=3) as answer:
            assert json.load(answer)['graph_id'] == server.universal_store.authority_identity
    finally:
        server.close()
    server = ApplicationServer(universal_state_path=database, universal_key_provider=provider,
        enable_machine_transport=False, enable_universal_cloud_gateway=False, live_watch=False)
    try:
        assert dict(server.universal_store.at(original_revision).cells) == original_cells
        assert getattr(server.universal_store, '_signed_commit_authority', None) is None
    finally:
        server.close()
