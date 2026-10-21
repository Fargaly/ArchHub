"""Bounded incremental maintenance cancellation/crash on synthetic custody."""
from contextlib import closing
import hashlib
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace

import pytest

from nodelang import commit_intent, conversation_archive as archive
from nodelang import conversation_retention_maintenance as maintenance
from nodelang.conversation_history import ConversationHistoryStore
from nodelang.universal_cell import Cell, CellStore, NULL_CELL_ID
from tests_replica.test_adopt_archive import ROOT, _export, _open_after_killed_child, _rows


@pytest.fixture(autouse=True)
def _private_temporary_files(tmp_path, monkeypatch):
    temporary = tmp_path / 'TEMP'
    temporary.mkdir()
    monkeypatch.setenv('TEMP', str(temporary))
    monkeypatch.setenv('TMP', str(temporary))
    monkeypatch.setattr(tempfile, 'tempdir', str(temporary))


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _state(store):
    connection, _lock = store.sqlite_storage()
    return (dict(store.snapshot().cells), store.revision,
            store.revision_chain_digest(), _rows(connection))


def _retired_fixture(tmp_path, monkeypatch):
    import nodelang.universal_cell as kernel
    path = tmp_path / 'compaction.sqlite3'
    content = tmp_path / 'compaction.conversations.sqlite3'
    cold = archive.trace_archive_path(content)
    session = 'app:workshop:compaction-old'
    previous = NULL_CELL_ID
    cells = []
    for number in range(2000):
        cell = Cell(session + ':chain:%05d' % number, previous, NULL_CELL_ID,
                    b'preserved text ' + b'x' * 32768 if number == 0 else b'')
        cells.append(cell)
        previous = cell.id
    sessions = {cell.id: session for cell in cells}
    with closing(sqlite3.connect(path)) as initial:
        initial.execute('PRAGMA auto_vacuum=INCREMENTAL')
    with CellStore(path) as store, ConversationHistoryStore(content, instance_id='compaction-court') as history:
        with commit_intent.declare(commit_intent.MIGRATION, actor='court', reason='synthetic retained graph'):
            store.commit(store.revision, create=tuple(Cell('work:' + kind, NULL_CELL_ID,
                NULL_CELL_ID, kind.encode()) for kind in ('nodes', 'wires', 'settings',
                    'brain', 'authority', 'receipts', 'workflows')))
        graph = dict(store.snapshot().cells)
        old = time.time() - 40 * 86400
        with monkeypatch.context() as clock:
            clock.setattr(kernel, 'time', SimpleNamespace(time=lambda: old))
            with commit_intent.declare(commit_intent.MIGRATION, actor='court', reason='synthetic old trace'):
                store.commit(store.revision, create=tuple(cells))
        history.initialize_trace_maintenance()
        for offset in range(0, len(cells), 256):
            identifiers = tuple(cell.id for cell in cells[offset:offset + 256])
            _export(store, cold, identifiers, sessions, history)
            assert maintenance.partition_archived_trace_batch(store, history, cold,
                identifiers, sessions, check=lambda: None) == len(identifiers)
        assert dict(store.snapshot().cells) == graph
        connection, _lock = store.sqlite_storage()
        assert connection.execute('SELECT COUNT(*) FROM trace_retired_identities').fetchone()[0] == 2000
        assert connection.execute('PRAGMA auto_vacuum').fetchone()[0] == 2
        assert connection.execute('PRAGMA freelist_count').fetchone()[0] > 0
        before = _state(store)
        pages = connection.execute('PRAGMA page_count').fetchone()[0]
    # Close/checkpoint all fixture owners before measuring physical custody.
    total_bytes = sum(item.stat().st_size for item in tmp_path.rglob('*') if item.is_file())
    assert total_bytes < 5 * 1024 * 1024
    print('ADOPT_COMPACTION_FIXTURE_BYTES', total_bytes)
    return path, cold, before, pages


def _retry_compaction(store, pages_before):
    connection, _lock = store.sqlite_storage()
    for _attempt in range(pages_before + 1):
        result = maintenance.compact_trace_journal(store, check=lambda: None)
        assert result['reclaimed_pages'] <= 128
        if result['status'] == 'compacted':
            break
    else:
        raise AssertionError('bounded incremental compaction did not complete')
    assert connection.execute('PRAGMA auto_vacuum').fetchone()[0] == 2
    assert connection.execute('PRAGMA freelist_count').fetchone()[0] == 0
    assert connection.execute('PRAGMA page_count').fetchone()[0] < pages_before


def test_incremental_maintenance_answers_reads_and_yields_to_foreground_edit(tmp_path, monkeypatch):
    path, cold, before, pages = _retired_fixture(tmp_path, monkeypatch)
    cold_digest = _digest(cold)
    paused, release, active = (threading.Event() for _ in range(3))
    errors = []
    def check():
        if active.is_set():
            raise TimeoutError('court user became active')
    def progress(event):
        if event['completed'] == 0 and not paused.is_set():
            paused.set()
            assert release.wait(10)
    with CellStore(path) as store:
        def compact():
            try:
                maintenance.compact_trace_journal(store, check=check, on_progress=progress)
            except BaseException as error:
                errors.append(error)
        worker = threading.Thread(target=compact, daemon=True)
        worker.start()
        try:
            assert paused.wait(10)
            started = time.monotonic()
            assert store.read('work:nodes') == before[0]['work:nodes']
            assert time.monotonic()-started < 2
            assert worker.is_alive()
            active.set()
        finally:
            release.set()
            worker.join(10)
        assert not worker.is_alive()
        assert len(errors) == 1 and isinstance(errors[0], TimeoutError)
        assert _state(store) == before
        store.commit(store.revision, create=(Cell('work:foreground', NULL_CELL_ID,
            NULL_CELL_ID, b'user edit'),))
        _retry_compaction(store, pages)
        assert store.read('work:foreground').atom == b'user edit'
    assert _digest(cold) == cold_digest
    with CellStore(path) as reopened:
        assert reopened.read('work:foreground').atom == b'user edit'
    assert archive.read_trace_archive(cold, 'app:workshop:compaction-old')['cells']


_INCREMENTAL_CHILD = """
from pathlib import Path
import sys,threading
from nodelang.universal_cell import CellStore
from nodelang.conversation_retention_maintenance import compact_trace_journal
path,marker=map(Path,sys.argv[1:])
with CellStore(path) as store:
    def progress(event):
        if event['stage']=='Compacted archived trace space':
            marker.write_text(str(event['completed']))
            threading.Event().wait()
    compact_trace_journal(store,check=lambda:None,on_progress=progress)
"""


def test_killed_incremental_chunk_resumes_without_restarting_full_work(tmp_path, monkeypatch):
    path, cold, before, pages = _retired_fixture(tmp_path, monkeypatch)
    cold_digest = _digest(cold)
    marker = tmp_path / 'chunk-completed.txt'
    process = subprocess.Popen([sys.executable, '-c', _INCREMENTAL_CHILD,
        str(path), str(marker)], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic()+20
        while not marker.exists() and process.poll() is None and time.monotonic()<deadline:
            time.sleep(0.02)
        assert marker.exists(), process.communicate(timeout=1) if process.poll() is not None else 'chunk stalled'
        assert int(marker.read_text()) > 0
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True)) as observer:
            assert observer.execute('SELECT atom FROM current_cells WHERE cell_id=?',
                ('work:nodes',)).fetchone()[0] == b'nodes'
        process.kill()
        process.wait(10)
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)
    with CellStore(path) as reopened:
        assert _state(reopened) == before
        _retry_compaction(reopened, pages)
    assert _digest(cold) == cold_digest
