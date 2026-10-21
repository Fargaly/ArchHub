"""Courts for stepping a snapshot back one revision."""

from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore


def _cell(cell_id, atom=b"one"):
    return Cell(cell_id, NULL_CELL_ID, NULL_CELL_ID, atom)


def test_stepping_back_a_revision_equals_rebuilding_it(tmp_path):
    """A snapshot reached by delta is the snapshot built from scratch.

    The step-back exists for speed, and speed is exactly the pressure
    that makes a shortcut drift from what it replaced. So the two are
    compared cell for cell down a whole history, including the revisions
    that only introduce a cell -- because a cell that appears at a
    revision has to disappear when stepping below it, and a delta that
    forgets to drop it still answers every lookup successfully.
    """
    store = CellStore(tmp_path / "walk.sqlite3")
    try:
        store.commit(store.revision, create=[_cell("kept")])
        store.commit(store.revision, create=[_cell("changing")])
        store.commit(store.revision, replace=[_cell("changing", b"two")])
        store.commit(store.revision, create=[_cell("late")])
        store.commit(
            store.revision,
            replace=[_cell("changing", b"three"), _cell("kept", b"revised")],
        )
        store.commit(store.revision, create=[_cell("latest")])

        head = store.revision
        assert head >= 6, head
        reader = store._history_reader
        assert reader is not None, "this court needs the sqlite history"

        for revision in range(head - 1, 0, -1):
            above = reader.snapshot_at(revision + 1)
            stepped = reader.snapshot_stepped_back(above)
            rebuilt = reader.snapshot_at(revision)
            assert stepped.revision == rebuilt.revision == revision
            assert set(stepped.cells) == set(rebuilt.cells), (
                "revision %d: stepping back kept or dropped the wrong cells; "
                "extra %s, missing %s"
                % (
                    revision,
                    sorted(set(stepped.cells) - set(rebuilt.cells)),
                    sorted(set(rebuilt.cells) - set(stepped.cells)),
                )
            )
            for cell_id, cell in rebuilt.cells.items():
                assert stepped.cells[cell_id] == cell, (
                    "revision %d: cell %s differs after stepping back"
                    % (revision, cell_id)
                )
    finally:
        store.close()


def test_walking_down_a_history_does_not_rescan_the_whole_store(tmp_path):
    """Descending revision by revision must cost deltas, not full scans.

    This is the defect that made the founder canvas take hours to start:
    every step of the audit aggregated every version row in the store, so
    a graph with six hundred revisions read itself six hundred times over
    before it would serve a page. Nothing was wrong with the answer, which
    is why it survived so long.
    """
    store = CellStore(tmp_path / "descend.sqlite3")
    try:
        for index in range(12):
            store.commit(store.revision, create=[_cell("cell-%d" % index)])
        head = store.revision
        reader = store._history_reader
        assert reader is not None

        rescans = []
        original = reader.snapshot_at

        def counting_snapshot_at(revision):
            rescans.append(revision)
            return original(revision)

        reader.snapshot_at = counting_snapshot_at
        try:
            for revision in range(head - 1, 0, -1):
                store.at(revision)
        finally:
            reader.snapshot_at = original

        assert len(rescans) <= 1, (
            "walking down rebuilt %d snapshots from scratch: %s"
            % (len(rescans), rescans)
        )
    finally:
        store.close()