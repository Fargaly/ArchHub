"""Chain preparation must advance across small idle slices, without new bytes."""
import sqlite3

import pytest

from nodelang import universal_cell as kernel


def _journal(connection):
    journal = object.__new__(kernel._SqliteJournal)
    journal._connection = connection
    return journal


@pytest.fixture
def source(tmp_path):
    path = tmp_path / 'synthetic-chain.sqlite3'
    connection = sqlite3.connect(path, isolation_level=None)
    connection.execute('CREATE TABLE cell_versions(revision INTEGER,cell_id TEXT,link0 TEXT,link1 TEXT,atom BLOB,PRIMARY KEY(revision,cell_id))')
    genesis = kernel.Cell(kernel.NULL_CELL_ID, kernel.NULL_CELL_ID, kernel.NULL_CELL_ID, b'')
    cells = tuple(kernel.Cell(f'trace:{number:04d}', kernel.NULL_CELL_ID,
        kernel.NULL_CELL_ID, b'payload') for number in range(120))
    for revision, rows in ((0, (genesis,)), (1, cells)):
        connection.executemany('INSERT INTO cell_versions VALUES(?,?,?,?,?)',
            ((revision, cell.id, cell.link0, cell.link1, cell.atom) for cell in rows))
    journal = _journal(connection)
    yield path, journal, genesis, cells
    pending = getattr(journal, '_trace_chain_preparation', None)
    if pending is not None:
        pending[2].close()
    connection.close()


def _budget(limit=8):
    calls = 0
    def check():
        nonlocal calls
        calls += 1
        if calls >= limit:
            raise TimeoutError('synthetic idle slice ended')
    return check


def _finish(journal, through):
    for slices in range(64):
        try:
            journal._prepare_trace_chain(through, _budget())
            return slices + 1
        except TimeoutError:
            pass
    raise AssertionError('idle slices restarted the same large revision without progress')


def _expected(genesis, cells):
    initial = kernel._ordered_revision_chain_digest_step(bytes(32), 0, (genesis,))
    return kernel._ordered_revision_chain_digest_step(initial, 1, cells)


def test_small_idle_slices_hash_each_cell_once_and_keep_original_digest(source, monkeypatch):
    _path, journal, genesis, cells = source
    visited = []
    validate = kernel._validate_cell
    def observed(cell):
        visited.append(cell.id)
        return validate(cell)
    with monkeypatch.context() as recording:
        recording.setattr(kernel, '_validate_cell', observed)
        slices = _finish(journal, 1)
    assert slices > 1
    assert visited == [genesis.id, *(cell.id for cell in cells)]
    actual = journal._connection.execute('SELECT digest FROM trace_chain_proofs WHERE revision=1').fetchone()[0]
    assert actual == _expected(genesis, cells)
    assert getattr(journal, '_trace_chain_preparation', None) is None


def test_restart_preserves_completed_revision_and_restarts_only_partial_one(source):
    path, journal, genesis, cells = source
    with pytest.raises(TimeoutError):
        journal._prepare_trace_chain(1, _budget())
    completed = journal._connection.execute('SELECT revision,digest FROM trace_chain_proofs').fetchall()
    assert [row[0] for row in completed] == [0]
    pending = getattr(journal, '_trace_chain_preparation', None)
    if pending is not None:
        pending[2].close()
    journal._trace_chain_preparation = None
    journal._connection.close()
    connection = sqlite3.connect(path, isolation_level=None)
    restarted = _journal(connection)
    try:
        _finish(restarted, 1)
        assert connection.execute('SELECT revision,digest FROM trace_chain_proofs WHERE revision=0').fetchall() == completed
        assert connection.execute('SELECT digest FROM trace_chain_proofs WHERE revision=1').fetchone()[0] == _expected(genesis, cells)
    finally:
        pending = getattr(restarted, '_trace_chain_preparation', None)
        if pending is not None:
            pending[2].close()
        connection.close()


def test_foreground_append_does_not_discard_partial_revision(source):
    _path, journal, genesis, cells = source
    with pytest.raises(TimeoutError):
        journal._prepare_trace_chain(1, _budget())
    appended = kernel.Cell('trace:new-head', kernel.NULL_CELL_ID, kernel.NULL_CELL_ID, b'new')
    journal._connection.execute('INSERT INTO cell_versions VALUES(?,?,?,?,?)',
        (2, appended.id, appended.link0, appended.link1, appended.atom))
    _finish(journal, 2)
    expected = kernel._ordered_revision_chain_digest_step(_expected(genesis, cells), 2, (appended,))
    assert journal._connection.execute('SELECT digest FROM trace_chain_proofs WHERE revision=2').fetchone()[0] == expected


def test_shared_sqlite_row_fingerprints_equal_tuples_after_cache_rebuild(source, monkeypatch):
    _path, journal, _genesis, _cells = source
    journal.append_only_fence_present = True
    fingerprints = []
    for factory in (None, sqlite3.Row, sqlite3.Row):
        journal._connection.row_factory = factory
        cache = sqlite3.connect(':memory:', isolation_level=None)
        monkeypatch.setattr(journal, '_accelerators', lambda: cache)
        try:
            reader = kernel._SqliteHistoryReader(journal, 1, '0'*64)
            fingerprints.append((reader.accepted_prefix_fingerprint(1),
                                 reader.chained_prefix_fingerprint(1)))
        finally:
            cache.close()
    assert fingerprints[0] == fingerprints[1] == fingerprints[2]
