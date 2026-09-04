"""The journal connection is shared across threads; a lazy head read racing an
append used to be SQLITE_MISUSE ('bad parameter or other API misuse') and a None
row mid-chain ('relation chain contains a dangling cell') -- the 10:31 launch."""
import threading

from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore


def _grow(store, start, count):
    for i in range(start, start + count):
        snapshot = store.snapshot()
        store.commit(snapshot.revision, create=(Cell("race:%d" % i, NULL_CELL_ID, NULL_CELL_ID, b"v"),))


def test_lazy_reads_and_appends_share_one_lock(tmp_path):
    path = tmp_path / "race.sqlite3"
    seed = CellStore(path)
    _grow(seed, 0, 200)
    seed.close()
    store = CellStore(path)  # reopened: the head is read lazily from the shared connection
    errors = []
    stop = threading.Event()

    def reader():
        i = 0
        try:
            while not stop.is_set():
                snapshot = store.snapshot()
                cell = snapshot.cells.get("race:%d" % (i % 200))
                assert cell is not None, "an existing head row read as missing"
                i += 1
        except Exception as exc:  # noqa: BLE001 - the court records any failure
            errors.append(repr(exc))

    def writer():
        try:
            _grow(store, 200, 150)
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))
        finally:
            stop.set()

    threads = [threading.Thread(target=reader, daemon=True) for _ in range(3)] + [threading.Thread(target=writer, daemon=True)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    store.close()
    assert not errors, errors
