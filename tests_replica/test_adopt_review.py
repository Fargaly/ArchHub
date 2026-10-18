"""RESUME4 acceptance on synthetic colleague profiles only."""
from contextlib import closing
from contextlib import nullcontext
import json
from pathlib import Path
import sqlite3
import threading
from types import SimpleNamespace

from nodelang import persistence
from nodelang import conversation_archive as archive
from nodelang import conversation_retention_maintenance as maintenance
from nodelang.universal_cell import Cell, CellStore, NULL_CELL_ID
from tests_replica.test_adopt import fixture
pytest_plugins = ("tests_replica.test_ogboot_upgrade_selection",)


def test_adoption_keeps_original_flat_journal(isolated_profile):
    root, stale, source, _backup = fixture(isolated_profile)
    identity = source.stat().st_ino
    persistence.prepare_application_database(root, stale)
    assert source.is_file(), '2230 must still open the original flat journal'
    assert persistence.application_database_path(root) == source
    assert source.stat().st_ino == identity
    with CellStore(source) as store:
        assert store.read('app:archhub').atom == b'saved edit'


def test_newer_empty_2230_journal_never_displaces_work(isolated_profile):
    root, stale, _source, _backup = fixture(isolated_profile)
    persistence.prepare_application_database(root, stale)
    selected = persistence.application_database_path(root)
    # A different explicitly released legacy location with only genesis.
    empty = root / 'archhub-test.universal.sqlite3'
    with CellStore(empty):
        pass
    persistence.prepare_application_database(root, selected)
    assert persistence.application_database_path(root) == selected
    with CellStore(selected) as store:
        assert store.read('app:archhub').atom == b'saved edit'


def test_graph_controls_inside_trace_namespaces_outweigh_newer_empty(isolated_profile):
    from tests_replica.test_adopt import closed_backup
    source = isolated_profile / 'ArchHub-Test/archhub-test.universal.sqlite3'
    source.parent.mkdir()
    with CellStore(source) as store:
        store.commit(store.revision, create=(Cell('app:workshop:conversation:graph:control',
            NULL_CELL_ID, NULL_CELL_ID, b'workshop graph'),))
    closed_backup(source.parent, source)
    root = isolated_profile / 'ArchHub'
    root.mkdir()
    empty = root / 'authority.sqlite3'
    with CellStore(empty):
        pass
    persistence.prepare_application_database(root, empty)
    assert persistence.application_database_path(root) == source
    with CellStore(source) as store:
        assert store.read('app:workshop:conversation:graph:control').atom == b'workshop graph'


def test_product_backup_on_colleague_profile(isolated_profile):
    from nodelang.application_recovery_files import preserve_closed_application_journals
    from tests_replica.test_ogboot_upgrade_selection import _journal
    source = _journal(isolated_profile / 'ArchHub-Test/archhub-test.universal.sqlite3', 'colleague work', 300)
    before = source.read_bytes()
    backups = preserve_closed_application_journals(isolated_profile, 'colleague-upgrade')
    backup, _digest = persistence._installer_closed_backup(isolated_profile / 'ArchHub', source)
    assert str(backup) in backups
    assert (backup / source.name).read_bytes() == before == source.read_bytes()
    assert json.loads((backup / 'closed-files.json').read_text())['retain_until_user_deletes'] is True
    root = isolated_profile / 'ArchHub'
    root.mkdir(exist_ok=True)
    persistence.prepare_application_database(root, root / 'authority.sqlite3')
    assert persistence.application_database_path(root) == source
    from tests_replica.test_adopt_review_kernel import _rollback_kernel
    restored = isolated_profile / 'rollback-2230' / source.name
    restored.parent.mkdir()
    restored.write_bytes((backup / source.name).read_bytes())
    with _rollback_kernel() as previous_kernel:
        with previous_kernel.CellStore(restored) as previous:
            assert previous.read('app:archhub').atom == b'colleague work'
    preserve_closed_application_journals(isolated_profile, 'colleague-next-upgrade')
    assert (backup / source.name).read_bytes() == before


def test_none_vacuum_journal_never_runs_full_vacuum(tmp_path):
    path = tmp_path / 'live.sqlite3'
    with CellStore(path) as store:
        db, _lock = store.sqlite_storage()
        db.execute('CREATE TABLE discarded(value BLOB)')
        db.execute('INSERT INTO discarded VALUES(zeroblob(1048576))')
        db.execute('DROP TABLE discarded')
        assert db.execute('PRAGMA auto_vacuum').fetchone()[0] == 0
        result = maintenance.compact_trace_journal(store, check=lambda: None)
        assert result['status'] == 'space-reusable'
        assert db.execute('PRAGMA auto_vacuum').fetchone()[0] == 0
        assert db.execute('PRAGMA freelist_count').fetchone()[0] > 0


def test_adopt_archive_and_2230_flat_save_then_empty_reupgrade(isolated_profile, monkeypatch):
    import time
    import nodelang.universal_cell as kernel
    from nodelang.application_recovery_files import preserve_closed_application_journals
    from nodelang.conversation_history import ConversationHistoryStore
    from tests_replica.test_adopt_review_kernel import _rollback_kernel
    from tests_replica import test_adopt_archive as custody
    from tests_replica import test_ogboot_upgrade_selection as upgrade
    root = isolated_profile / 'ArchHub'
    stale = upgrade._selected(root)
    source = upgrade._journal(isolated_profile / 'ArchHub-Test/archhub-test.universal.sqlite3', 'saved edit', 200)
    old = Cell('app:deliberation:flat-rollback:entry:old', NULL_CELL_ID, NULL_CELL_ID, b'old archive text')
    with CellStore(source) as store:
        store.commit(store.revision, create=(Cell('work:flat-rollback', NULL_CELL_ID, NULL_CELL_ID, b'user work'),))
        with monkeypatch.context() as clock:
            clock.setattr(kernel, 'time', SimpleNamespace(time=lambda: time.time()-40*86400))
            store.commit(store.revision, create=(old,))
    preserve_closed_application_journals(isolated_profile, 'flat-rollback-upgrade')
    inode = source.stat().st_ino
    persistence.prepare_application_database(root, stale)
    assert persistence.application_database_path(root) == source and source.stat().st_ino == inode
    content = Path(str(source)+'.conversations.sqlite3')
    session = 'app:deliberation:flat-rollback'
    with CellStore(source) as store, ConversationHistoryStore(content, instance_id='flat-rollback') as history:
        history.initialize_trace_maintenance()
        history.admit_trace_custody(store.authority_identity, 'app:archhub')
        cold = archive.trace_archive_path(content)
        custody._export(store, cold, (old.id,), {old.id: session}, history)
        assert maintenance.partition_archived_trace_batch(store, history, cold, (old.id,),
            {old.id: session}, check=lambda: None) == 1
    for suffix in ('.accelerators', '.accelerators-wal', '.accelerators-shm'):
        Path(str(source)+suffix).unlink(missing_ok=True)
    with _rollback_kernel() as previous_kernel:
        with previous_kernel.CellStore(source) as previous:
            assert previous.read('app:archhub').atom == b'saved edit'
            assert previous.read('work:flat-rollback').atom == b'user work'
            marker = previous_kernel.Cell('work:2230-flat-save', previous_kernel.NULL_CELL_ID,
                previous_kernel.NULL_CELL_ID, b'2230 saved')
            previous.commit(previous.revision, create=(marker,))
        empty = root / 'archhub-test.universal.sqlite3'
        with previous_kernel.CellStore(empty):
            pass
    persistence.prepare_application_database(root, persistence.application_database_path(root))
    assert persistence.application_database_path(root) == source and source.stat().st_ino == inode
    with CellStore(source) as store:
        assert store.read(marker.id).atom == marker.atom
        assert old.id not in store.snapshot().cells


def test_boot_receipt_roots_are_never_generic_trace_candidates():
    for suffix in ('view-receipt', 'scope-receipt', 'close-receipt'):
        _session, candidate = maintenance._trace_family_descriptor('app:agent-session:founder:' + suffix)
        assert candidate is False, 'boot verification reads this receipt root'


def test_generation_archive_locator_follows_relocated_profile(tmp_path):
    generation_id = '11111111-1111-4111-8111-111111111111'
    root = tmp_path / 'relocated' / 'ArchHub'
    generation = root / 'unified-authority/generations' / generation_id
    generation.mkdir(parents=True)
    (root / 'unified-authority/CURRENT').write_text(generation_id)
    (generation / 'migration.json').write_text(json.dumps(dict(
        format='archhub-application-journal-migration/v1', generation_id=generation_id,
        source_path='Z:/unavailable/old-user/ArchHub-Test/archhub-test.universal.sqlite3')))
    content = generation / 'authority.sqlite3.conversations.sqlite3'
    assert archive.archive_directory(content) == root.parent / 'ArchHub-Test/Conversation archive'


def test_trace_storage_error_is_visible_and_stops_background_retry(tmp_path):
    from tests_replica.test_launcher_boot_refusal import _launcher_names
    calls, events = [], []
    def full(**_kwargs):
        calls.append('attempt')
        raise sqlite3.OperationalError('database or disk is full')
    service = SimpleNamespace(maintain_legacy_trace_inventory=full,
        _path=tmp_path / 'conversations.sqlite3')
    namespace = _launcher_names('_maintain_legacy_conversations',
        _update_stop=threading.Event(), _trace_retention_status=None,
        _trace_retention_cursor=None, _trace_inventory_completed_at=None,
        _migration_status=None, _conversation_maintenance_context=lambda: object(),
        _trace_background_priority=nullcontext, server=SimpleNamespace(conversation_content=service),
        _boot_surface=SimpleNamespace(progress=SimpleNamespace(migration=events.append)))
    assert namespace['_maintain_legacy_conversations']() is False
    assert namespace['_trace_retention_status'] == 'failed'
    assert events[-1]['stage'] == 'failed'
    assert 'disk is full' in events[-1]['error']
    assert namespace['_maintain_legacy_conversations']() is False
    assert calls == ['attempt']


def test_product_backup_pair_reserves_once_and_cleans_failed_stage(isolated_profile, monkeypatch):
    from nodelang import application_recovery_files as files
    from tests_replica.test_ogboot_upgrade_selection import _journal
    source = _journal(isolated_profile / 'ArchHub-Test/archhub-test.universal.sqlite3', 'paired work', 300)
    content = Path(str(source) + '.conversations.sqlite3')
    with closing(sqlite3.connect(content)) as db:
        db.execute('CREATE TABLE content(value BLOB)')
        db.execute('INSERT INTO content VALUES(zeroblob(4096))')
        db.commit()
    reserves = []
    monkeypatch.setattr(files, '_require_disk_reserve', lambda parent, size: reserves.append(size))
    backups = files.preserve_closed_application_journals(isolated_profile, 'paired-upgrade')
    assert reserves == [source.stat().st_size + content.stat().st_size]
    backup = Path(backups[0])
    assert (backup / content.name).read_bytes() == content.read_bytes()
    original = files.os.fsync
    # A changed content pair requires a new copy; unchanged pairs now reuse it.
    with closing(sqlite3.connect(content)) as db:
        db.execute('INSERT INTO content VALUES(?)', (b'changed before failed upgrade',))
        db.commit()
    def disk_full(_descriptor):
        raise OSError('synthetic disk full during backup')
    monkeypatch.setattr(files.os, 'fsync', disk_full)
    import pytest
    with pytest.raises(OSError, match='disk full'):
        files.preserve_closed_application_journals(isolated_profile, 'failed-upgrade')
    monkeypatch.setattr(files.os, 'fsync', original)
    assert not list((source.parent / 'backups').glob('*-pending'))
    assert (backup / source.name).read_bytes() == source.read_bytes()


def test_on_demand_archive_paging_is_portable_cached_generation_bound_and_verified(tmp_path, monkeypatch):
    import pytest
    from nodelang.conversation_history import ConversationHistoryStore
    from tests_replica.test_adopt_archive_p1 import _source, _add, _preserve
    content = tmp_path / 'content.sqlite3'
    cold_path = archive.trace_archive_path(content)
    with closing(_source()) as source, ConversationHistoryStore(content, instance_id='read-court') as history:
        history.initialize_trace_maintenance()
        history.admit_trace_custody('synthetic-authority', 'synthetic-workspace')
        _add(source, '000-text', b'A' * 20000)
        _add(source, '001-text', ('unique archived text ' + '\u03a9' * 100).encode())
        with closing(_preserve(source, cold_path, ('000-text', '001-text'))[0]) as cold:
            history.index_trace_archive(cold, ('synthetic-session',), archive_path=cold_path,
                cell_ids=('000-text', '001-text'))
        real_connect, opened = sqlite3.connect, []
        def connect(database, *args, **kwargs):
            if archive.TRACE_ARCHIVE_NAME in str(database):
                opened.append(str(database))
            return real_connect(database, *args, **kwargs)
        monkeypatch.setattr(sqlite3, 'connect', connect)
        def no_text(operation, table, column, _database, _trigger):
            return (sqlite3.SQLITE_DENY if operation == sqlite3.SQLITE_READ and table == 'trace_sessions'
                and column in ('content', 'text_atoms') else sqlite3.SQLITE_OK)
        history._db.set_authorizer(no_text)
        metadata = history.archived_trace_session('synthetic-session', metadata_only=True)
        assert opened == []
        history._db.set_authorizer(None)
        first = history.archived_trace_session('synthetic-session', offset=0,
            expected_generation=metadata['generation'])
        assert first['content'] == 'A' * 16384 and first['next_offset'] == 16384
        assert opened
        history._db.set_authorizer(no_text)
        second = history.archived_trace_session('synthetic-session', offset=16384,
            expected_generation=metadata['generation'])
        assert 'unique archived text' in second['content'] and second['next_offset'] is None
        history._db.set_authorizer(None)
        with closing(real_connect(cold_path)) as cold:
            cold.execute('UPDATE trace_current SET atom=? WHERE cell_id=?', (b'tampered', '001-text'))
            cold.commit()
        with pytest.raises(archive.ArchiveConflict, match='content verification failed'):
            history.archived_trace_session('synthetic-session', offset=16384,
                expected_generation=metadata['generation'])
        history._db.execute('UPDATE trace_sessions SET content=content WHERE session_id=?', ('synthetic-session',))
        before = len(opened)
        with pytest.raises(ValueError, match='return to latest'):
            history.archived_trace_session('synthetic-session', offset=16384,
                expected_generation=metadata['generation'])
        assert len(opened) == before
