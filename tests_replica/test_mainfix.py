"""MAINFIX real SQLite adoption courts, synthetic profiles only."""
from pathlib import Path

import pytest

from nodelang import persistence
from nodelang.universal_cell import CellStore
from tests_replica import test_ogboot_upgrade_selection as upgrade
from tests_replica.test_adopt import closed_backup

isolated_profile = upgrade.isolated_profile


@pytest.fixture(autouse=True)
def backup_drives_stay_in_lane(monkeypatch):
    from nodelang import application_recovery_files as files
    monkeypatch.setattr(files, '_fixed_backup_drives', lambda: [])


@pytest.mark.parametrize('hot_wal', [False, True])
def test_old_graph_without_installer_backup_opens(isolated_profile, hot_wal):
    root = isolated_profile / 'ArchHub'
    stale = upgrade._selected(root)
    source = upgrade._journal(isolated_profile / 'ArchHub-Test/archhub-test.universal.sqlite3', 'saved edit', 200)
    live = CellStore(source) if hot_wal else None
    try:
        if live:
            live.close()
            # A crashed process may leave an empty recovered WAL beside a valid head.
            Path(str(source) + '-wal').touch()
        events = []
        result = persistence.prepare_application_database(root, stale, on_progress=events.append)
        assert Path(result['database_path']) == source
        assert persistence.application_database_path(root) == source
        with CellStore(source) as reopened:
            assert reopened.snapshot().cells['app:archhub'].atom == b'saved edit'
        assert result['backup_path'] or any('backup' in str(event).lower() for event in events)
    finally:
        if live:
            live.close()


def test_newer_saved_graph_outranks_larger_old_scaffold(isolated_profile):
    root = isolated_profile / 'ArchHub'
    stale = upgrade._selected(root, timestamp=100, commits=9)
    source = upgrade._journal(isolated_profile / 'ArchHub-Test/archhub-test.universal.sqlite3',
        'five nodes six wires saved edit', 200, commits=5)
    closed_backup(source.parent, source)
    result = persistence.prepare_application_database(root, stale)
    assert Path(result['database_path']) == source, 'a larger fresh scaffold must not defeat a newer saved graph'
    with CellStore(source) as store:
        # Older released application locations are superseded, never head-merged.
        assert persistence.migrate_graph_source(store, stale)['state'] == 'older_application_journal'
        assert store.snapshot().cells['app:archhub'].atom == b'five nodes six wires saved edit'


def test_over_budget_boot_opens_and_exposes_a_visible_backup_warning(isolated_profile, monkeypatch):
    from nodelang import application_recovery_files as files
    root = isolated_profile / 'ArchHub'
    stale = upgrade._selected(root)
    source = upgrade._journal(isolated_profile / 'ArchHub-Test/archhub-test.universal.sqlite3', 'saved edit', 200)
    monkeypatch.setattr(files.shutil, 'disk_usage', lambda _: type('Disk', (), {'free': 25 * 1024**3})())
    result = persistence.prepare_application_database(root, stale)
    assert Path(result['database_path']) == source
    assert result['backup_path'] is None
    from nodelang.application_server import _CleanAuthorityHttpServer
    from types import SimpleNamespace
    import threading
    server = _CleanAuthorityHttpServer.__new__(_CleanAuthorityHttpServer)
    server._boot_error = None
    server._boot_ready = threading.Event()
    server._boot_ready.set()
    server.clean_store = SimpleNamespace(database_path=source)
    status = server._boot_status()
    assert status['state'] == 'ready'
    assert status.get('warning') is True
    assert 'backup' in status['message'].lower()


def test_installer_copy_survives_empty_wal_created_by_a_content_probe(isolated_profile):
    import sqlite3
    root = isolated_profile / 'ArchHub'
    stale = upgrade._selected(root)
    source = upgrade._journal(isolated_profile / 'ArchHub-Test/archhub-test.universal.sqlite3', 'saved edit', 200)
    backup = closed_backup(source.parent, source)
    # Exact first-boot caller: asking where content lives may create an empty WAL.
    with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as reader:
        reader.execute('SELECT COUNT(*) FROM current_cells').fetchone()
    reader.close()
    result = persistence.prepare_application_database(root, stale)
    assert Path(result['database_path']) == source
    assert result['backup_path'] == str(backup), 'a harmless reader sidecar must not discard verified installer custody'


def test_invalid_backup_location_cannot_refuse_saved_graph(isolated_profile):
    root = isolated_profile / 'ArchHub'
    stale = upgrade._selected(root)
    source = upgrade._journal(isolated_profile / 'ArchHub-Test/archhub-test.universal.sqlite3', 'saved edit', 200)
    (root / 'backup-location.json').write_text('{invalid metadata', encoding='utf-8')
    result = persistence.prepare_application_database(root, stale)
    assert Path(result['database_path']) == source
    assert result['backup_path'] is None
    assert persistence.application_backup_warning(source)
    with CellStore(source) as reopened:
        assert reopened.snapshot().cells['app:archhub'].atom == b'saved edit'


def test_declared_state_root_can_adopt_its_profile_legacy_graph(isolated_profile, monkeypatch):
    root = isolated_profile.parent / 'state'
    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(root))
    stale = upgrade._selected(root)
    source = upgrade._journal(isolated_profile / 'ArchHub-Test/archhub-test.universal.sqlite3', 'saved edit', 200)
    persistence.prepare_application_database(root, stale)
    assert persistence.selected_application_generation(source)
    assert persistence.application_state_directory(source) == root


def test_committed_nonempty_wal_edit_reopens_without_installer_copy(isolated_profile):
    from contextlib import closing
    import sqlite3
    from nodelang.universal_cell import NULL_CELL_ID
    root = isolated_profile / 'ArchHub'
    stale = upgrade._selected(root)
    source = upgrade._journal(isolated_profile / 'ArchHub-Test/archhub-test.universal.sqlite3', 'saved edit', 200)
    with closing(sqlite3.connect(source, isolation_level=None)) as writer:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('PRAGMA wal_autocheckpoint=0')
        revision = writer.execute('SELECT MAX(revision) FROM revisions').fetchone()[0] + 1
        writer.execute('BEGIN IMMEDIATE')
        writer.execute('INSERT INTO revisions VALUES(?,?)', (revision, 300))
        writer.execute('INSERT INTO cell_versions VALUES(?,?,?,?,?)',
            (revision, 'work:wal', NULL_CELL_ID, NULL_CELL_ID, b'committed only in WAL'))
        writer.execute('INSERT INTO current_cells VALUES(?,?,?,?,?)',
            ('work:wal', revision, NULL_CELL_ID, NULL_CELL_ID, b'committed only in WAL'))
        writer.execute('COMMIT')
        assert Path(str(source) + '-wal').stat().st_size > 32
        result = persistence.prepare_application_database(root, stale)
        assert Path(result['database_path']) == source
        with CellStore(source) as reopened:
            assert reopened.read('work:wal').atom == b'committed only in WAL'
        if result['backup_path']:
            with CellStore(Path(result['backup_path']) / 'graph.sqlite3') as backup:
                assert backup.read('work:wal').atom == b'committed only in WAL'


def test_small_graph_large_content_is_admitted_as_one_backup_budget(isolated_profile, monkeypatch):
    import sqlite3
    from nodelang import application_recovery_files as files
    root = isolated_profile / 'ArchHub'
    stale = upgrade._selected(root)
    source = upgrade._journal(isolated_profile / 'ArchHub-Test/archhub-test.universal.sqlite3', 'saved edit', 200)
    content = Path(str(source) + '.conversations.sqlite3')
    with sqlite3.connect(content) as db:
        db.execute('CREATE TABLE payload(value BLOB)')
    db.close()
    with content.open('r+b') as stream:
        stream.truncate(65 * 1024**2)
    def refuse_copy(*args, **kwargs):
        raise AssertionError('combined graph/content size must be admitted before any copy')
    monkeypatch.setattr(files, 'publish_application_recovery', refuse_copy)
    result = persistence.prepare_application_database(root, stale)
    assert result['backup_path'] is None
    assert persistence.application_backup_warning(source)


def test_real_saved_five_nodes_six_wires_reopen_without_bootstrap_merge(isolated_profile, monkeypatch):
    from nodelang.application_server import ApplicationServer
    from nodelang.cell_secret_keys import MemorySigningKeyProvider
    from nodelang import universal_application as app, commit_intent
    from nodelang.universal_pipeline import create_engine_node
    from nodelang.universal_cell import Cell, NULL_CELL_ID
    monkeypatch.setenv('ARCHHUB_GRAND_MAP_PATH', str(Path(app.__file__).parent / 'data/public_runtime_map.json'))
    root = isolated_profile / 'ArchHub'
    stale = root / 'authority.sqlite3'
    source = isolated_profile / 'ArchHub-Test/archhub-test.universal.sqlite3'
    keys = MemorySigningKeyProvider('archhub.local.relationship-authority', b'r' * 32)
    keys.add_key('archhub.local.court-attestation', b'c' * 32)
    def server(path, **kwargs):
        return ApplicationServer(universal_state_path=path, universal_key_provider=keys,
            universal_workspace_root=isolated_profile, enable_machine_transport=False,
            enable_universal_cloud_gateway=False, live_watch=False, **kwargs)
    old = server(stale)
    try:
        with commit_intent.declare(commit_intent.MIGRATION, actor='court', reason='older generated scaffold'):
            old.universal_store.commit(old.universal_store.revision, create=tuple(
                Cell('scaffold:' + str(i), NULL_CELL_ID, NULL_CELL_ID, b'generated') for i in range(5000)))
    finally:
        old.close()
    saved = server(source)
    try:
        store, registry = saved.universal_store, saved.universal_registry
        def user_canvas(value):
            visible = [item for item in value['nodes'] if not item.get('application')]
            ids = {item['id'] for item in visible}
            return {'nodes': visible, 'wires': [item for item in value['wires']
                if item['source'] in ids and item['target'] in ids]}
        with commit_intent.declare(commit_intent.USER_ACTION, actor='court', reason='save five-node six-wire graph'):
            initial = user_canvas(app.project_universal_canvas(store, registry))
            print('MAINFIX_OGF initial=%d/%d' % (len(initial['nodes']), len(initial['wires'])))
            nodes = [item['id'] for item in initial['nodes']]
            for i in range(5 - len(nodes)):
                nodes.append(create_engine_node(store, registry, title='Saved ' + str(i), engine='library.think')['root'])
            canvas = app.project_universal_canvas(store, registry)
            def port(root_id, side):
                node = next(item for item in canvas['nodes'] if item['id'] == root_id)
                return next(item['id'] for item in node['ports'] if item['side'] == side and item.get('mode') == 'connection')
            pairs = ((0,4),(1,4),(2,4),(3,4),(4,0),(4,1))
            for left, right in pairs[:6-len(initial['wires'])]:
                app.connect_universal_roots(store, registry, nodes[left], nodes[right],
                    source_interface=port(nodes[left], 'source'), target_interface=port(nodes[right], 'target'))
        canvas = user_canvas(app.project_universal_canvas(store, registry))
        assert len(canvas['nodes']) == 5 and len(canvas['wires']) == 6
        expected_nodes = {item['id'] for item in canvas['nodes']}
        expected_wires = {item['id'] for item in canvas['wires']}
    finally:
        saved.close()
    closed_backup(source.parent, source)
    persistence.prepare_application_database(root, stale, key_provider=keys)
    selected = persistence.application_database_path(root)
    reopened = server(selected, legacy_state_directory=root,
        conversation_history_path=persistence.application_content_path(selected))
    try:
        canvas = user_canvas(app.project_universal_canvas(reopened.universal_store, reopened.universal_registry))
        assert {item['id'] for item in canvas['nodes']} == expected_nodes
        assert {item['id'] for item in canvas['wires']} == expected_wires
        print('MAINFIX_OGF saved=5/6 reopened=5/6 bootstrap_conflict=False')
        _assert_foreground_interrupts_inventory(reopened, monkeypatch)
    finally:
        reopened.close()


def _assert_foreground_interrupts_inventory(server, monkeypatch):
    import threading
    import time
    from nodelang import conversation_retention_maintenance as maintenance
    store = server.universal_store
    history = maintenance._legacy_trace_history(server.conversation_content, store.snapshot())
    history.initialize_trace_maintenance()
    history.admit_trace_custody(store.authority_identity, server.universal_registry.application_root)
    history._db.execute("UPDATE trace_family_state SET phase='scan',cursor='',watermark=? WHERE singleton=1", (store.revision,))
    tables = ('trace_family_state', 'trace_family_sessions', 'trace_family_protected')
    def rows():
        return [list(map(tuple, history._db.execute('SELECT * FROM ' + table))) for table in tables]
    before, revision = rows(), store.revision
    record = maintenance._record_family_cell
    touched = []
    def interrupt(*args):
        record(*args)
        touched.append(True)
        server.last_user_action_monotonic = time.monotonic()
    with monkeypatch.context() as patch:
        patch.setattr(maintenance, '_advance_trace_registry', lambda *args: None)
        patch.setattr(maintenance, '_record_family_cell', interrupt)
        result = maintenance.maintain_trace_families(server.conversation_content,
            authentication_context=server.universal_registry.authorization.session.context(minimum_validity_seconds=5),
            max_cells=8192)
    assert touched and result['status'] == 'family-deferred'
    assert rows() == before and store.revision == revision
    acquired = []
    def probe():
        if server.mutation_lock.acquire(timeout=.1):
            acquired.append(True)
            server.mutation_lock.release()
    thread = threading.Thread(target=probe)
    thread.start()
    thread.join(.2)
    assert acquired == [True]
    print('MAINFIX_IDLE foreground_interrupt=True inventory_rolled_back=True lock_released=True')
    server.last_user_action_monotonic = 0.0
    def sql_budget(*args):
        record(*args)
        history._db.execute('WITH RECURSIVE n(x) AS (VALUES(0) UNION ALL SELECT x+1 FROM n WHERE x<1000000) SELECT sum(x) FROM n').fetchone()
    with monkeypatch.context() as patch:
        patch.setattr(maintenance, '_advance_trace_registry', lambda *args: None)
        patch.setattr(maintenance, '_record_family_cell', sql_budget)
        result = maintenance.maintain_trace_families(server.conversation_content,
            authentication_context=server.universal_registry.authorization.session.context(minimum_validity_seconds=5))
    assert result['status'] == 'family-deferred'
    assert rows() == before and store.revision == revision
    print('MAINFIX_SQL operation_budget_interrupt_deferred=True inventory_rolled_back=True')
