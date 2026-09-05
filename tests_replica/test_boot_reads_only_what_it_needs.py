"""Boot must not read the whole journal to answer small questions.

boot-profile.log on the founder's machine (2026-09-05, 259s): half the samples
sat in universal_cell.stream_ids -- set(snapshot.cells) inside _require on every
protocol projection -- and a third in revision_cells/snapshot_at -- the
authority restore reading every cell of all 21,700 revisions. These courts hold
both reads to their scope."""
from __future__ import annotations

import inspect

from nodelang import cell_identity, cell_registry_projection
from nodelang.universal_cell import Cell, CellStore, NULL_CELL_ID


def test_require_uses_point_reads_not_the_whole_map():
    src = inspect.getsource(cell_registry_projection._require)
    code = chr(10).join(line for line in src.splitlines() if not line.strip().startswith("#"))
    assert "set(snapshot.cells)" not in code
    assert "root not in snapshot.cells" in src


def test_the_store_names_the_revisions_that_touched_a_root(tmp_path):
    store = CellStore(str(tmp_path / "j.sqlite3"))
    base = store.revision
    r1 = store.commit(base, create=(Cell("a", NULL_CELL_ID, NULL_CELL_ID, b"a"),))
    r2 = store.commit(r1, create=(Cell("b", NULL_CELL_ID, NULL_CELL_ID, b"b"),))
    r3 = store.commit(r2, create=(Cell("a:child", "a", NULL_CELL_ID, b"c"),))
    r4 = store.commit(r3, create=(Cell("ab", NULL_CELL_ID, NULL_CELL_ID, b"x"),))  # sibling prefix, not under a:
    assert store.revisions_touching("a") == (r1, r3)
    assert store.revisions_touching("b") == (r2,)
    assert store.revisions_touching("nope") == ()
    assert r4 not in store.revisions_touching("a")


def test_the_authority_restore_asks_the_journal_not_every_revision():
    src = inspect.getsource(cell_identity.restore_relationship_authority_history)
    assert 'getattr(store, "revisions_touching", None)' in src
    assert "scoped(protocol.root_id)" in src and "scoped(relationship_root)" in src
    # the full walk survives only as the fallback for stores without the index
    assert src.count("store.revision_changes(revision)") == 1


def test_scoped_scans_agree_with_the_full_walk(tmp_path):
    from nodelang.universal_cell import cells_with_link0, ids_with_prefix
    store = CellStore(str(tmp_path / "s.sqlite3"))
    r = store.revision
    r = store.commit(r, create=(Cell("app:theme:a", NULL_CELL_ID, NULL_CELL_ID, b"1"),
                                Cell("app:theme:b", NULL_CELL_ID, NULL_CELL_ID, b"2"),
                                Cell("app:themes", NULL_CELL_ID, NULL_CELL_ID, b"3"),
                                Cell("role:iface", NULL_CELL_ID, NULL_CELL_ID, b"r")))
    r = store.commit(r, create=(Cell("x:1", "role:iface", "app:theme:a", b""),
                                Cell("x:2", "role:iface", "app:themes", b""),
                                Cell("x:3", NULL_CELL_ID, "app:theme:a", b"")))
    snap = store.snapshot()
    full = sorted(k for k in snap.cells if k.startswith("app:theme:"))
    assert sorted(ids_with_prefix(snap.cells, "app:theme:")) == full == ["app:theme:a", "app:theme:b"]
    assert sorted(c.id for c in cells_with_link0(snap.cells, "role:iface")) == ["x:1", "x:2"]
    # reopened: the lazy head answers the same
    store.close()
    store2 = CellStore(str(tmp_path / "s.sqlite3"))
    snap2 = store2.snapshot()
    assert sorted(ids_with_prefix(snap2.cells, "app:theme:")) == full
    assert sorted(c.id for c in cells_with_link0(snap2.cells, "role:iface")) == ["x:1", "x:2"]


def test_a_past_revision_reads_lazily_and_exactly(tmp_path):
    store = CellStore(str(tmp_path / "h.sqlite3"))
    r0 = store.revision
    r1 = store.commit(r0, create=(Cell("a", NULL_CELL_ID, NULL_CELL_ID, b"v1"),))
    r2 = store.commit(r1, replace=(Cell("a", NULL_CELL_ID, NULL_CELL_ID, b"v2"),),
                      create=(Cell("b", "a", NULL_CELL_ID, b"b"),))
    for _ in range(260):   # beyond _STEP_BACK_LIMIT: the lazy path, not the step-back walk
        r2 = store.commit(r2, create=(Cell("pad:%d" % r2, NULL_CELL_ID, NULL_CELL_ID, b"p"),))
    store.close()
    reopened = CellStore(str(tmp_path / "h.sqlite3"))
    at1 = reopened.at(r1)
    assert at1.cells["a"].atom == b"v1" and "b" not in at1.cells
    at2 = reopened.at(r2 - 260)
    assert at2.cells["a"].atom == b"v2" and at2.cells["b"].link0 == "a"
    assert type(at1.cells).__name__ == "_LazyRevisionCellMap"
