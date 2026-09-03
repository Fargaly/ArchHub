"""Operational admission court for source-built standard assemblies."""
from pathlib import Path

import pytest

from nodelang.cell_catalog import (
    bootstrap_assembly_protocol,
    instantiate_catalog_definition,
    open_instance,
    project_catalog,
)
from nodelang.cell_protocols import (
    insert_relation_member,
    read_relation,
    remove_relation_member,
    reorder_relation_members,
)
from nodelang.cell_standard_library import build_standard_library_v0
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


def _instance_state(store, protocol, instance_root):
    members = read_relation(store.snapshot(), instance_root, budget=100_000)
    states = [
        member.participant_id for member in members
        if member.role_id == protocol.role("state")
    ]
    assert len(states) == 1
    return states[0]


def _participants(store, root):
    return [
        member.participant_id
        for member in read_relation(store.snapshot(), root, budget=100_000)
    ]


def test_ordered_list_is_operational():
    store = CellStore()
    protocol = bootstrap_assembly_protocol(store)
    library = build_standard_library_v0(store, protocol)
    projected = project_catalog(store.snapshot(), protocol, library.catalog_root)
    assert projected[0] == {
        "id": library.definition_roots[0],
        "name": "Ordered List",
        "version": "1.0.0",
        "interfaces": 1,
        "parts": 17,
    }
    assert projected[1]["name"] == "Watcher"

    store.commit(store.revision, create=(
        Cell("value:a", NULL_CELL_ID, NULL_CELL_ID, b"A"),
        Cell("value:b", NULL_CELL_ID, NULL_CELL_ID, b"B"),
        Cell("value:c", NULL_CELL_ID, NULL_CELL_ID, b"C"),
        Cell("value:duplicate-a", NULL_CELL_ID, NULL_CELL_ID, b"A"),
    ))
    instance = instantiate_catalog_definition(
        store,
        protocol,
        library.catalog_root,
        library.definition_roots[0],
    )
    state = _instance_state(store, protocol, instance.root_id)
    item_role = library.shared_roots["item-role"]
    a = insert_relation_member(store, state, item_role, "value:a")
    c = insert_relation_member(store, state, item_role, "value:c")
    b = insert_relation_member(
        store, state, item_role, "value:b", before_incidence=c
    )
    duplicate = insert_relation_member(
        store, state, item_role, "value:duplicate-a", after_incidence=c
    )
    assert _participants(store, state) == [
        "value:a", "value:b", "value:c", "value:duplicate-a",
    ]

    reorder_relation_members(store, state, (duplicate, b, a, c))
    assert _participants(store, state) == [
        "value:duplicate-a", "value:b", "value:a", "value:c",
    ]
    assert [member.incidence_id for member in read_relation(
        store.snapshot(), state
    )] == [duplicate, b, a, c]

    revision_before_remove = store.revision
    remove_relation_member(store, state, b)
    assert _participants(store, state) == [
        "value:duplicate-a", "value:a", "value:c",
    ]
    assert [
        member.participant_id for member in read_relation(
            store.at(revision_before_remove), state
        )
    ] == ["value:duplicate-a", "value:b", "value:a", "value:c"]
    assert set(instance.cell_map.values()).issubset(
        open_instance(store.snapshot(), protocol, instance.root_id)
    )


def test_ordered_list_instances_do_not_share_mutable_state():
    store = CellStore()
    protocol = bootstrap_assembly_protocol(store)
    library = build_standard_library_v0(store, protocol)
    store.commit(store.revision, create=(
        Cell("value", NULL_CELL_ID, NULL_CELL_ID, b"value"),
    ))
    first = instantiate_catalog_definition(
        store, protocol, library.catalog_root, library.definition_roots[0]
    )
    second = instantiate_catalog_definition(
        store, protocol, library.catalog_root, library.definition_roots[0]
    )
    first_state = _instance_state(store, protocol, first.root_id)
    second_state = _instance_state(store, protocol, second.root_id)
    insert_relation_member(
        store, first_state, library.shared_roots["item-role"], "value"
    )
    assert _participants(store, first_state) == ["value"]
    assert _participants(store, second_state) == []


def test_rejected_order_edit_is_atomic_and_preserves_previous_snapshot():
    store = CellStore()
    protocol = bootstrap_assembly_protocol(store)
    library = build_standard_library_v0(store, protocol)
    store.commit(store.revision, create=(
        Cell("value", NULL_CELL_ID, NULL_CELL_ID, b"value"),
    ))
    instance = instantiate_catalog_definition(
        store, protocol, library.catalog_root, library.definition_roots[0]
    )
    state = _instance_state(store, protocol, instance.root_id)
    incidence = insert_relation_member(
        store, state, library.shared_roots["item-role"], "value"
    )
    before = store.snapshot()
    with pytest.raises(InvalidCell, match="exact member permutation"):
        reorder_relation_members(store, state, (incidence, "forged"))
    assert store.snapshot() == before


def test_ordered_list_survives_process_store_restart(tmp_path: Path):
    database = tmp_path / "library.sqlite3"
    store = CellStore(database)
    protocol = bootstrap_assembly_protocol(store)
    library = build_standard_library_v0(store, protocol)
    store.commit(store.revision, create=(
        Cell("value", NULL_CELL_ID, NULL_CELL_ID, b"persisted"),
    ))
    instance = instantiate_catalog_definition(
        store, protocol, library.catalog_root, library.definition_roots[0]
    )
    state = _instance_state(store, protocol, instance.root_id)
    incidence = insert_relation_member(
        store, state, library.shared_roots["item-role"], "value"
    )
    store.close()

    reopened = CellStore(database)
    assert _participants(reopened, state) == ["value"]
    member = read_relation(reopened.snapshot(), state)[0]
    assert member.incidence_id == incidence
    assert project_catalog(
        reopened.snapshot(), protocol, library.catalog_root
    )[0]["name"] == "Ordered List"
    reopened.close()
