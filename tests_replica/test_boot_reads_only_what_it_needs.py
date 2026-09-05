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
