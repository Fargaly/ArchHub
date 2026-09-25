"""A head rebase hands the old reader's cache to the new one.

Before, every rebase started a fresh reader and the old one kept its full
cache for as long as anything referenced an older head: live readers and
cached bytes grew with use. The court forces a rebase on every commit while
old snapshots stay referenced, and requires (1) the cached bytes across all
live readers to stay bounded by one reader's working set, (2) every old
snapshot to keep reading its own revision, and (3) the new head to start
warm for identities no commit rewrote.
"""
from __future__ import annotations

import gc

from nodelang import universal_cell as uc
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore


def _live_readers():
    gc.collect()
    return [item for item in gc.get_objects() if type(item) is uc._HeadRowReader]


def test_rebases_keep_reader_caches_bounded_and_snapshots_exact(tmp_path):
    store = CellStore(tmp_path / "rebase.sqlite3")
    try:
        ids = ["test:handover:%03d" % index for index in range(300)]
        store.commit(store.revision, create=tuple(
            Cell(cell_id, NULL_CELL_ID, NULL_CELL_ID, b"v0") for cell_id in ids
        ))
        store._SQLITE_HEAD_OVERLAY_MAX_CELLS = 1  # every commit rebases
        held = []
        for step in range(1, 13):
            head = store.snapshot()
            for cell_id in ids:  # fill the current reader's cache
                head.cells[cell_id]
            held.append((head, step - 1))
            store.commit(store.revision, replace=(
                Cell(ids[step], NULL_CELL_ID, NULL_CELL_ID, b"v%d" % step),
            ))
        readers = [reader for reader in _live_readers() if reader._lock is store._journal._io_lock]
        cached = sum(len(reader._cache) for reader in readers)
        # One working set (300 identities), not one per rebase.
        assert cached <= len(ids), (len(readers), cached)
        # The new head starts warm: untouched identities moved across.
        current = store.snapshot().cells._reader
        assert len(current._cache) >= len(ids) - 13
        # Every older head still reads its own revision exactly.
        for snapshot, last_written in held:
            for step in range(1, 13):
                expected = b"v%d" % step if step <= last_written else b"v0"
                assert snapshot.cells[ids[step]].atom == expected
        assert store.snapshot().cells[ids[12]].atom == b"v12"
    finally:
        store.close()
