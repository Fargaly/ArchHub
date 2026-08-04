from __future__ import annotations

from types import SimpleNamespace

import pytest
import nodelang.cell_change_history as change_history_module

from nodelang.cell_change_history import (
    ROLE_NAMES,
    bootstrap_change_history_protocol,
    commit_tracked_change,
    history_state,
    read_change_transaction,
    redo_last_change,
    undo_last_change,
)
from nodelang.cell_protocols import CellBatch, read_relation
from nodelang.universal_cell import (
    NULL_CELL_ID,
    Cell,
    CellStore,
    Conflict,
)


def _fixture(database_path=None):
    store = CellStore(database_path)
    protocol = bootstrap_change_history_protocol(
        store, prefix="test:change-history-protocol"
    )
    batch = CellBatch(store)
    for root, atom in (
        ("test:actor", b"Actor"),
        ("test:session", b"Session"),
        ("test:operation:set", b"Set"),
        ("test:operation:undo", b"Undo"),
        ("test:operation:redo", b"Redo"),
        ("test:authority:set", b"Set value"),
        ("test:value", b"one"),
    ):
        batch.add(Cell(root, NULL_CELL_ID, NULL_CELL_ID, atom))
    batch.relation((), relation_id="test:history")
    batch.commit()
    return store, protocol


def _set_value(store, protocol, value, *, history_root="test:history"):
    snapshot = store.snapshot()
    current = snapshot.cells["test:value"]
    return commit_tracked_change(
        store,
        protocol,
        history_root=history_root,
        actor_root="test:actor",
        session_root="test:session",
        operation_root="test:operation:set",
        authority_root="test:authority:set",
        scope_roots=("test:value",),
        replace=(Cell(
            current.id, current.link0, current.link1, value.encode("ascii")
        ),),
    )


def test_change_is_a_graph_transaction_and_undo_redo_append_revisions():
    store, protocol = _fixture()
    original_ids = frozenset(store.snapshot().cells)

    forward = _set_value(store, protocol, "two")
    assert store.read("test:value").atom == b"two"
    transaction = read_change_transaction(
        store.snapshot(), protocol, forward.root_id
    )
    assert transaction.actor_root == "test:actor"
    assert transaction.session_root == "test:session"
    assert transaction.operation_root == "test:operation:set"
    assert transaction.authority_root == "test:authority:set"
    assert transaction.scope_roots == ("test:value",)
    assert transaction.interface_root is None
    assert transaction.base_revision == forward.revision - 1
    assert transaction.result_revision == forward.revision
    assert len(transaction.changes) == 1
    assert transaction.changes[0].target_root == "test:value"
    assert transaction.changes[0].before.atom == b"one"
    assert transaction.changes[0].after.atom == b"two"
    assert history_state(
        store.snapshot(), protocol, "test:history"
    ).undo_root == forward.root_id

    undone = undo_last_change(
        store,
        protocol,
        history_root="test:history",
        actor_root="test:actor",
        session_root="test:session",
        operation_root="test:operation:undo",
    )
    assert undone.revision == forward.revision + 1
    assert store.read("test:value").atom == b"one"
    state = history_state(store.snapshot(), protocol, "test:history")
    assert state.undo_root is None
    assert state.redo_root == forward.root_id

    redone = redo_last_change(
        store,
        protocol,
        history_root="test:history",
        actor_root="test:actor",
        session_root="test:session",
        operation_root="test:operation:redo",
    )
    assert redone.revision == undone.revision + 1
    assert store.read("test:value").atom == b"two"
    state = history_state(store.snapshot(), protocol, "test:history")
    assert state.undo_root == forward.root_id
    assert state.redo_root is None
    assert original_ids.issubset(store.snapshot().cells)
    assert len(read_relation(store.snapshot(), "test:history")) == 3


def test_replacement_only_undo_does_not_scan_for_created_cell_links():
    class EmptyTargetsMustNotTraverse:
        def values(self):
            raise AssertionError("empty created-target set scanned the whole graph")

    incoming = change_history_module._incoming_links_for_targets(
        SimpleNamespace(cells=EmptyTargetsMustNotTraverse()),
        frozenset(),
    )

    assert dict(incoming) == {}


def test_history_is_session_scoped_and_new_work_clears_redo():
    store, protocol = _fixture()
    batch = CellBatch(store)
    batch.relation((), relation_id="test:history:other")
    batch.commit()
    first = _set_value(store, protocol, "two")
    undo_last_change(
        store,
        protocol,
        history_root="test:history",
        actor_root="test:actor",
        session_root="test:session",
        operation_root="test:operation:undo",
    )
    assert history_state(
        store.snapshot(), protocol, "test:history:other"
    ).undo_root is None

    second = _set_value(store, protocol, "three")
    state = history_state(store.snapshot(), protocol, "test:history")
    assert state.undo_root == second.root_id
    assert state.redo_root is None
    assert first.root_id != second.root_id
    with pytest.raises(Conflict, match="nothing to redo"):
        redo_last_change(
            store,
            protocol,
            history_root="test:history",
            actor_root="test:actor",
            session_root="test:session",
            operation_root="test:operation:redo",
        )


def test_undo_fails_closed_when_the_changed_cell_has_diverged():
    store, protocol = _fixture()
    _set_value(store, protocol, "two")
    current = store.read("test:value")
    store.commit(store.revision, replace=(Cell(
        current.id, current.link0, current.link1, b"concurrent"
    ),))
    with pytest.raises(Conflict, match="changed after the recorded transaction"):
        undo_last_change(
            store,
            protocol,
            history_root="test:history",
            actor_root="test:actor",
            session_root="test:session",
            operation_root="test:operation:undo",
        )
    assert store.read("test:value").atom == b"concurrent"


def test_history_and_recovery_survive_database_restart(tmp_path):
    path = tmp_path / "history.sqlite3"
    store, protocol = _fixture(path)
    forward = _set_value(store, protocol, "two")
    revision = store.revision
    store.close()

    reopened = CellStore(path)
    restored_protocol = bootstrap_change_history_protocol(
        reopened, prefix="test:change-history-protocol"
    )
    assert reopened.revision == revision
    assert history_state(
        reopened.snapshot(), restored_protocol, "test:history"
    ).undo_root == forward.root_id
    undo_last_change(
        reopened,
        restored_protocol,
        history_root="test:history",
        actor_root="test:actor",
        session_root="test:session",
        operation_root="test:operation:undo",
    )
    assert reopened.read("test:value").atom == b"one"
    reopened.close()


def test_existing_history_vocabulary_is_extended_without_replacing_its_root():
    store = CellStore()
    prefix = "test:legacy-change-history"
    legacy_names = tuple(
        name for name in ROLE_NAMES
        if name not in {"authority", "scope", "interface"}
    )
    roles = {name: "%s:role:%s" % (prefix, name) for name in legacy_names}
    batch = CellBatch(store)
    for name, root in roles.items():
        batch.add(Cell(root, NULL_CELL_ID, NULL_CELL_ID, name.encode("ascii")))
    batch.relation(
        ((roles["vocabulary-member"], root) for root in roles.values()),
        relation_id=prefix + ":root",
    )
    batch.commit()
    old_root = store.read(prefix + ":root")

    protocol = bootstrap_change_history_protocol(store, prefix=prefix)

    assert protocol.root_id == old_root.id
    assert set(protocol.roles) == set(ROLE_NAMES)
    assert store.read(protocol.root_id).id == old_root.id
