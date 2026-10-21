"""Historical Cell identity survives physical retirement; synthetic owners only."""
from contextlib import closing
import hashlib
import sqlite3

import pytest

from nodelang import conversation_archive as archive
from nodelang.universal_cell import Cell, CellStore, InvalidCell, NULL_CELL_ID


def _retire(store, cold_path):
    cell = Cell('app:workshop:identity:chain:0', NULL_CELL_ID, NULL_CELL_ID, b'original')
    store.commit(store.revision, create=(cell,))
    with pytest.raises(InvalidCell, match='cannot create existing cell'):
        store.commit(store.revision, create=(cell,))
    connection, lock = store.sqlite_storage()
    with lock, closing(archive.preserve_trace_batch(connection, cold_path,
            store.authority_identity, (cell.id,), {cell.id: 'identity-session'},
            lambda: None)[0]) as cold:
        store.partition_archived_cells(cold, (cell.id,), check=lambda: None)
    assert cell.id not in store.snapshot().cells
    assert connection.execute('SELECT 1 FROM cell_versions WHERE cell_id=?',
                              (cell.id,)).fetchone() is None
    return cell


@pytest.mark.parametrize('reopen', [False, True])
def test_retired_id_cannot_be_created_again_and_custody_stays_unchanged(tmp_path, reopen):
    path, cold_path = tmp_path / 'live.sqlite3', tmp_path / 'cold.sqlite3'
    store = CellStore(path)
    try:
        original = _retire(store, cold_path)
        if reopen:
            store.close()
            store = CellStore(path)
        revision = store.revision
        digest = store.set_accumulator(store.snapshot())
        connection, _ = store.sqlite_storage()
        before = tuple(connection.execute('SELECT * FROM trace_set_deltas ORDER BY revision'))
        for atom in (b'original', b'replacement identity'):
            with pytest.raises(InvalidCell, match='cannot create existing cell'):
                store.commit(revision, create=(Cell(original.id, NULL_CELL_ID, NULL_CELL_ID, atom),))
        assert store.revision == revision
        assert store.set_accumulator(store.snapshot()) == digest
        assert tuple(connection.execute('SELECT * FROM trace_set_deltas ORDER BY revision')) == before
        reserved = tuple(connection.execute('SELECT identity FROM trace_retired_identities'))
        assert reserved == ((hashlib.sha256(original.id.encode()).digest(),),)
        for statement in (
                'DELETE FROM trace_retired_identities',
                "UPDATE trace_retired_identities SET identity=zeroblob(32)",
                "INSERT INTO trace_retired_identities VALUES(zeroblob(32))",
                'INSERT OR REPLACE INTO trace_retired_identities SELECT identity FROM trace_retired_identities'):
            with pytest.raises(sqlite3.Error):
                connection.execute(statement)
        with closing(sqlite3.connect(path)) as external:
            with pytest.raises(sqlite3.Error):
                external.execute('INSERT OR REPLACE INTO trace_retired_identities '
                                 'SELECT identity FROM trace_retired_identities')
        assert tuple(connection.execute('SELECT identity FROM trace_retired_identities')) == reserved
        assert archive.read_trace_archive(cold_path, 'identity-session')['cells'][0]['atom'] == original.atom
        fresh = Cell('work:fresh', NULL_CELL_ID, NULL_CELL_ID, b'new user work')
        store.commit(revision, create=(fresh,))
        assert store.read(fresh.id) == fresh
    finally:
        store.close()


def test_retired_owner_opens_without_any_archive_reads(tmp_path, monkeypatch):
    path, cold_path = tmp_path / 'live.sqlite3', tmp_path / 'cold.sqlite3'
    with CellStore(path) as store:
        _retire(store, cold_path)
    connect = sqlite3.connect
    opened = []

    def observed(database, *args, **kwargs):
        if str(cold_path) in str(database):
            opened.append(str(database))
        return connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, 'connect', observed)
    with CellStore(path) as store:
        assert len(store.snapshot().cells) == 1
    assert opened == []


def test_missing_archive_cannot_release_identity_or_block_unrelated_work(tmp_path):
    path, cold_path = tmp_path / 'live.sqlite3', tmp_path / 'cold.sqlite3'
    with CellStore(path) as store:
        original = _retire(store, cold_path)
        cold_path.rename(tmp_path / 'missing.sqlite3')
        revision = store.revision
        with pytest.raises(InvalidCell, match='cannot create existing cell'):
            store.commit(revision, create=(original,))
        assert store.revision == revision
        fresh = Cell('work:archive-offline', NULL_CELL_ID, NULL_CELL_ID, b'new work')
        store.commit(revision, create=(fresh,))
        assert store.read(fresh.id) == fresh
