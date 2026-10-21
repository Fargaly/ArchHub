"""Single-entry desktop ownership and persistence, without opening any UI."""
from __future__ import annotations

import importlib
import json
from pathlib import Path
import runpy
import uuid

import pytest

from nodelang import desktop, persistence
from nodelang.conversation_history import ConversationHistoryStore
from nodelang.universal_cell import Cell, CellStore, DatabaseOwnerConflict, NULL_CELL_ID


def _cell(name, value=b'user work'):
    return Cell(name, NULL_CELL_ID, NULL_CELL_ID, value)


@pytest.fixture
def small_journal_backup_policy(monkeypatch):
    """Tiny journal courts omit the separately tested application Settings map."""
    from nodelang import backup_retention
    monkeypatch.setattr(backup_retention, 'backup_policy', lambda *_: {
        'keep_count': 3, 'max_bytes': 10 * 1024**3})


def _generation(root, ident=None):
    ident = ident or str(uuid.uuid4())
    selected = root / 'unified-authority' / 'generations' / ident
    selected.mkdir(parents=True)
    database = selected / 'authority.sqlite3'
    with CellStore(database):
        pass
    (selected / 'bootstrap.json').write_text(json.dumps({'graph_id': ident}), encoding='utf-8')
    (root / 'unified-authority' / 'CURRENT').write_text(ident, encoding='ascii')
    return database


def test_the_selected_application_graph_survives_reopen(tmp_path):
    database = persistence.application_database_path(tmp_path)
    with CellStore(database) as owner:
        owner.commit(owner.revision, create=(_cell('test:saved-user-work'),))
    with CellStore(database) as owner:
        assert owner.read('test:saved-user-work').atom == b'user work'
        assert owner.database_path == str(database)


def test_closing_history_cannot_close_the_running_graph_owner(tmp_path):
    with CellStore(tmp_path / 'authority.sqlite3') as owner:
        history = ConversationHistoryStore(owner.database_path, instance_id='account', store=owner)
        history.ensure_conversation('room')
        history.append('room', author='person', content='survives', idempotency_key='message')
        history.close()
        owner.commit(owner.revision, create=(_cell('test:still-open'),))
        assert owner.read('test:still-open').atom == b'user work'


def test_invalid_current_pointer_refuses_without_creating_a_replacement(tmp_path):
    current = tmp_path / 'unified-authority' / 'CURRENT'
    current.parent.mkdir()
    current.write_text('../somewhere-else', encoding='ascii')
    with pytest.raises(ValueError):
        persistence.application_database_path(tmp_path)
    assert not (tmp_path / 'authority.sqlite3').exists()


def test_current_selects_one_generation_without_choosing_the_latest_folder(tmp_path):
    selected = _generation(tmp_path)
    unrelated = selected.parent.parent / str(uuid.uuid4())
    unrelated.mkdir()
    assert persistence.application_database_path(tmp_path) == selected
    assert persistence.selected_application_generation(selected)


def test_missing_selected_graph_never_falls_back_to_a_retired_copy(tmp_path):
    selected = _generation(tmp_path)
    selected.unlink()
    with CellStore(tmp_path / 'archhub-test.universal.sqlite3'):
        pass
    with pytest.raises(ValueError, match='missing'):
        persistence.application_database_path(tmp_path)
    assert not (tmp_path / 'authority.sqlite3').exists()


def test_explicit_profile_keeps_all_state_inside_its_declared_folder(tmp_path, monkeypatch):
    selected = tmp_path / 'profile'
    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(selected))
    assert persistence.application_database_path() == selected / 'authority.sqlite3'
    from nodelang.unified_authority_runtime import default_runtime_root
    assert default_runtime_root() == selected / 'unified-authority'


def test_normal_state_no_longer_defaults_to_node_native_wip(tmp_path, monkeypatch):
    monkeypatch.delenv('ARCHHUB_TEST_STATE_DIR', raising=False)
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    assert persistence.application_database_path() == tmp_path / 'ArchHub' / 'authority.sqlite3'


def test_a_second_owner_of_the_same_graph_is_refused(tmp_path):
    database = tmp_path / 'authority.sqlite3'
    with CellStore(database) as owner:
        owner.commit(owner.revision, create=(_cell('test:active'),))
        with pytest.raises(DatabaseOwnerConflict):
            CellStore(database)
        assert owner.read('test:active').atom == b'user work'


def test_a_retired_store_is_an_import_source_and_never_a_default_head(tmp_path):
    old = tmp_path / 'archhub-test.universal.sqlite3'
    with CellStore(old):
        pass
    assert old in persistence.legacy_application_sources(tmp_path)
    assert persistence.application_database_path(tmp_path) == tmp_path / 'authority.sqlite3'


def test_retired_graph_merge_is_idempotent_and_preserves_unique_work(tmp_path):
    source, target = tmp_path / 'old.sqlite3', tmp_path / 'authority.sqlite3'
    with CellStore(source) as old:
        old.commit(old.revision, create=(_cell('test:old-work'),))
    original = source.read_bytes()
    with CellStore(target) as owner:
        owner.commit(owner.revision, create=(_cell('test:current-work'),))
        result = persistence.migrate_graph_source(owner, source)
        revision = owner.revision
        assert result['state'] == 'migrated' and Path(result['backup_path']).is_dir()
        assert owner.read('test:old-work').atom == b'user work'
        assert owner.read('test:current-work').atom == b'user work'
        assert persistence.migrate_graph_source(owner, source)['state'] == 'already_migrated'
        assert owner.revision == revision
    assert source.read_bytes() == original


def test_conflicting_retired_graph_never_overwrites_or_discards_current_work(tmp_path):
    source = tmp_path / 'old.sqlite3'
    with CellStore(source) as old:
        old.commit(old.revision, create=(_cell('test:shared', b'old'),))
    with CellStore(tmp_path / 'authority.sqlite3') as owner:
        owner.commit(owner.revision, create=(_cell('test:shared', b'current'),))
        revision = owner.revision
        with pytest.raises(ValueError, match='conflicting truth'):
            persistence.migrate_graph_source(owner, source)
        assert owner.revision == revision and owner.read('test:shared').atom == b'current'


def test_historical_server_entry_routes_to_the_installed_desktop(monkeypatch):
    from nodelang import application_server
    calls = []
    monkeypatch.setattr(desktop, 'main', lambda: calls.append('desktop') or 37)
    assert application_server.main() == 37
    assert calls == ['desktop']


def test_import_does_not_construct_an_owner_or_open_qt_and_main_preserves_refusal(monkeypatch):
    from nodelang import application_server
    def forbidden(*args, **kwargs):
        pytest.fail('import constructed a second application')
    monkeypatch.setattr(application_server, 'ApplicationServer', forbidden)
    importlib.reload(desktop)
    def refused(*args, **kwargs):
        raise RuntimeError('fixture boot refusal')
    monkeypatch.setattr(runpy, 'run_path', refused)
    with pytest.raises(RuntimeError, match='fixture boot refusal'):
        desktop.main()


def test_upgrade_preserves_2230_journal_revisions_before_receipts_are_restored(tmp_path, monkeypatch):
    from nodelang import backup_retention
    # This tiny journal exercises history, not the separately courted Settings graph.
    monkeypatch.setattr(backup_retention, 'backup_policy', lambda *_: {
        'keep_count': 3, 'max_bytes': 10 * 1024**3})
    source = tmp_path / 'archhub-test.universal.sqlite3'
    with CellStore(source) as old:
        first = old.commit(old.revision, create=(_cell('app:archhub'), _cell('work:first')))
        last = old.commit(old.revision, create=(_cell('work:second'),))
    before = source.read_bytes()
    target = tmp_path / 'authority.sqlite3'
    result = persistence.prepare_application_database(tmp_path, target)
    assert result['state'] == 'migrated' and Path(result['backup_path']).is_dir()
    assert source.read_bytes() == before
    with CellStore(target) as current:
        assert current.revision == last
        assert current.read('work:first', revision=first).atom == b'user work'
        assert 'work:second' not in current.at(first).cells
        assert current.read('work:second', revision=last).atom == b'user work'
        persistence.migrate_graph_source(current, source)
        assert current.revision > last
        assert current.read('work:first', revision=first).atom == b'user work'


def test_upgrade_never_replaces_an_existing_selected_or_partial_target(tmp_path):
    source = tmp_path / 'archhub-test.universal.sqlite3'
    with CellStore(source) as old:
        old.commit(old.revision, create=(_cell('app:archhub'),))
    target = tmp_path / 'authority.sqlite3'
    target.write_bytes(b'existing target must stay')
    assert persistence.prepare_application_database(tmp_path, target)['state'] == 'existing'
    assert target.read_bytes() == b'existing target must stay'
    target.unlink()
    Path(str(target) + '-wal').write_bytes(b'unreconciled target write')
    with pytest.raises(ValueError, match='recovery'):
        persistence.prepare_application_database(tmp_path, target)
    assert not target.exists()


def test_interrupted_upgrade_copy_can_retry_without_publishing_partial_database(tmp_path, monkeypatch, small_journal_backup_policy):
    from nodelang import application_recovery_files as recovery
    source = tmp_path / 'archhub-test.universal.sqlite3'
    with CellStore(source) as old:
        old.commit(old.revision, create=(_cell('app:archhub'),))
    original = recovery._backup_sqlite
    def interrupted(connection, path, check):
        path.write_bytes(b'partial copy')
        raise TimeoutError('owned migration copy interrupted')
    monkeypatch.setattr(recovery, '_backup_sqlite', interrupted)
    target = tmp_path / 'authority.sqlite3'
    with pytest.raises(TimeoutError, match='interrupted'):
        persistence.prepare_application_database(tmp_path, target)
    assert not target.exists()
    monkeypatch.setattr(recovery, '_backup_sqlite', original)
    assert persistence.prepare_application_database(tmp_path, target)['state'] == 'migrated'
    with CellStore(target) as current:
        assert current.read('app:archhub').atom == b'user work'


def test_interrupted_merge_backup_does_not_poison_its_final_name(tmp_path, monkeypatch):
    source = tmp_path / 'old.sqlite3'
    with CellStore(source) as old:
        old.commit(old.revision, create=(_cell('old:work'),))
    with CellStore(tmp_path / 'authority.sqlite3') as owner:
        original = owner.backup_to
        def interrupted(path):
            Path(path).write_bytes(b'partial copy')
            raise TimeoutError('merge backup interrupted')
        monkeypatch.setattr(owner, 'backup_to', interrupted)
        with pytest.raises(TimeoutError, match='interrupted'):
            persistence.migrate_graph_source(owner, source)
        assert not list((tmp_path / 'backups').glob('graph-migration-*/graph.sqlite3'))
        monkeypatch.setattr(owner, 'backup_to', original)
        assert persistence.migrate_graph_source(owner, source)['state'] == 'migrated'
        assert owner.read('old:work').atom == b'user work'


def test_upgrade_adopts_committed_wal_only_revisions_and_historical_values(tmp_path, small_journal_backup_policy):
    import sqlite3
    import time
    from contextlib import closing

    source = tmp_path / 'archhub-test.universal.sqlite3'
    with CellStore(source) as old:
        first = old.commit(old.revision, create=(_cell('app:archhub'),))
    target = tmp_path / 'authority.sqlite3'
    # A raw SQLite connection keeps committed WAL frames uncheckpointed without
    # retaining a CellStore owner fence. No writer runs during the adoption.
    with closing(sqlite3.connect(source, isolation_level=None)) as journal:
        assert journal.execute('PRAGMA journal_mode=WAL').fetchone()[0] == 'wal'
        journal.execute('PRAGMA wal_autocheckpoint=0')
        main_before = source.read_bytes()
        for revision, value in ((first + 1, b'wal-first'), (first + 2, b'wal-latest')):
            journal.execute('BEGIN IMMEDIATE')
            journal.execute('INSERT INTO revisions(revision,committed_at) VALUES(?,?)',
                            (revision, time.time()))
            journal.execute('INSERT INTO cell_versions(revision,cell_id,link0,link1,atom) VALUES(?,?,?,?,?)',
                            (revision, 'work:wal-history', NULL_CELL_ID, NULL_CELL_ID, value))
            journal.execute('INSERT OR REPLACE INTO current_cells(cell_id,revision,link0,link1,atom) VALUES(?,?,?,?,?)',
                            ('work:wal-history', revision, NULL_CELL_ID, NULL_CELL_ID, value))
            journal.execute('COMMIT')
        assert source.read_bytes() == main_before
        assert Path(str(source) + '-wal').stat().st_size > 0
        versions = journal.execute('SELECT * FROM cell_versions ORDER BY revision,cell_id').fetchall()
        revisions = journal.execute('SELECT * FROM revisions ORDER BY revision').fetchall()
        assert persistence.prepare_application_database(tmp_path, target)['state'] == 'migrated'
        assert source.read_bytes() == main_before
        assert journal.execute('SELECT * FROM cell_versions ORDER BY revision,cell_id').fetchall() == versions
        with closing(sqlite3.connect(target)) as adopted:
            assert adopted.execute('SELECT * FROM revisions ORDER BY revision').fetchall() == revisions
            assert adopted.execute('SELECT * FROM cell_versions ORDER BY revision,cell_id').fetchall() == versions
        with CellStore(target) as current:
            assert current.revision == first + 2
            assert 'work:wal-history' not in current.at(first).cells
            assert current.read('work:wal-history', revision=first + 1).atom == b'wal-first'
            assert current.read('work:wal-history').atom == b'wal-latest'


def test_upgrade_refuses_a_retired_journal_while_its_owner_fence_is_held(tmp_path, small_journal_backup_policy):
    from nodelang.universal_cell import InterprocessOwnerFence

    source = tmp_path / 'archhub-test.universal.sqlite3'
    with CellStore(source) as old:
        old.commit(old.revision, create=(_cell('app:archhub'), _cell('work:owned')))
    before = source.read_bytes()
    target = tmp_path / 'authority.sqlite3'
    fence = InterprocessOwnerFence(str(source))
    try:
        with pytest.raises(DatabaseOwnerConflict, match='already owned'):
            persistence.prepare_application_database(tmp_path, target)
        assert not target.exists()
        assert source.read_bytes() == before
        assert not (tmp_path / 'backups').exists()
    finally:
        fence.close()
    assert persistence.prepare_application_database(tmp_path, target)['state'] == 'migrated'
    with CellStore(target) as current:
        assert current.read('work:owned').atom == b'user work'


def test_upgrade_refuses_real_pending_bootstrap_custody_without_rebinding_it(tmp_path):
    from nodelang.conversation_content import (
        FRESH_CONTENT_BOOTSTRAP_ROOT, record_fresh_content_bootstrap,
        read_fresh_content_bootstrap,
    )

    source = tmp_path / 'archhub-test.universal.sqlite3'
    with CellStore(source) as old:
        record_fresh_content_bootstrap(old, source)
        # Construction can have created its application root before crashing
        # while the content cutover still carries the original pending custody.
        old.commit(old.revision, create=(_cell('app:archhub'),))
        pending = read_fresh_content_bootstrap(old.snapshot())
        assert pending['state'] == 'pending'
        assert pending['graph_path'] == str(source.resolve())
        assert pending['authority'] == old.authority_identity
        custody_atom = old.read(FRESH_CONTENT_BOOTSTRAP_ROOT).atom
    before = source.read_bytes()
    target = tmp_path / 'authority.sqlite3'
    with pytest.raises(ValueError, match='pending bootstrap custody cannot move'):
        persistence.prepare_application_database(tmp_path, target)
    assert source.read_bytes() == before
    assert not target.exists()
    assert not (tmp_path / 'backups').exists()
    with CellStore(source) as old:
        assert old.read(FRESH_CONTENT_BOOTSTRAP_ROOT).atom == custody_atom
        assert read_fresh_content_bootstrap(old.snapshot()) == pending


def test_upgrade_uses_saved_graph_when_enforcing_its_backup_budget(tmp_path, monkeypatch):
    from nodelang import backup_retention
    source = tmp_path / 'archhub-test.universal.sqlite3'
    with CellStore(source) as old:
        revision = old.commit(old.revision, create=(
            _cell('app:archhub'), _cell('settings:budget-probe', b'saved user budget')))
    observed = []
    def saved_policy(snapshot, registry=None):
        assert snapshot.revision == revision
        assert snapshot.cells['settings:budget-probe'].atom == b'saved user budget'
        observed.append(True)
        return {'keep_count': 3, 'max_bytes': 1}
    monkeypatch.setattr(backup_retention, 'backup_policy', saved_policy)
    with pytest.raises(ValueError, match='backup disk budget'):
        persistence.prepare_application_database(tmp_path, tmp_path / 'authority.sqlite3')
    assert observed == [True]
    assert not (tmp_path / 'authority.sqlite3').exists()
