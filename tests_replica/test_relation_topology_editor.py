"""Cell-native relation topology editing courts.

This replaces the old typed-runtime topology editor court.  A visible cable is a
projection of a real relation and exact incidence Cells; editing topology must
replace those incidence links, preserve relation identity, and keep public
interface ownership coherent.
"""
from __future__ import annotations

import pytest

from nodelang.cell_protocols import read_relation
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    build_universal_application,
    project_universal_canvas,
    rewire_universal_connection,
    set_universal_inspector_lens,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, InvalidCell


def _build_canvas():
    store, registry = build_universal_application(resolve_map_path())
    set_universal_inspector_lens(
        store, registry, registry.inspector_lens_roots["build"]
    )
    return store, registry


def _first_rewireable_wire(projection):
    return next(
        wire for wire in projection["wires"]
        if wire["nary"] is False
        and wire["source_incidence"]
        and wire["target_incidence"]
        and wire["source_rewire_choices"]
    )


def _relation_members_with(snapshot, relation_root, *participants):
    wanted = set(participants)
    return tuple(
        member for member in read_relation(snapshot, relation_root, budget=100_000)
        if member.participant_id in wanted
    )


def test_rewire_replaces_one_exact_incidence_and_preserves_relation_identity():
    store, registry = _build_canvas()
    before_projection = project_universal_canvas(store, registry)
    wire = _first_rewireable_wire(before_projection)
    source_incidence = wire["source_incidence"]
    target_incidence = wire["target_incidence"]
    old_source_interface = wire["source_interface"]
    old_target_interface = wire["target_interface"]
    new_source_interface = next(
        choice["id"] for choice in wire["source_rewire_choices"]
        if choice["id"] != old_source_interface
    )
    old_source_cell = store.read(source_incidence)
    old_target_cell = store.read(target_incidence)
    before_relation_ids = {item["id"] for item in before_projection["wires"]}

    revision = rewire_universal_connection(
        store, registry, source_incidence, new_source_interface
    )
    after_projection = project_universal_canvas(store, registry)
    updated = next(item for item in after_projection["wires"] if item["id"] == wire["id"])

    assert revision == store.revision
    assert {item["id"] for item in after_projection["wires"]} == before_relation_ids
    assert updated["id"] == wire["id"]
    assert updated["source_interface"] == new_source_interface
    assert updated["target_interface"] == old_target_interface
    assert updated["source_incidence"] == source_incidence
    assert updated["target_incidence"] == target_incidence
    assert store.read(source_incidence).link0 == old_source_cell.link0
    assert store.read(source_incidence).link1 == new_source_interface
    assert store.read(target_incidence) == old_target_cell
    assert _relation_members_with(
        store.snapshot(), old_source_interface, wire["id"], source_incidence
    ) == ()
    assert {
        (member.role_id, member.participant_id)
        for member in _relation_members_with(
            store.snapshot(), new_source_interface, wire["id"], source_incidence
        )
    } == {
        (registry.roles["seed"], wire["id"]),
        (registry.roles["authority"], source_incidence),
    }


def test_rewire_rejects_invisible_participant_without_partial_mutation():
    store, registry = _build_canvas()
    projection = project_universal_canvas(store, registry)
    wire = _first_rewireable_wire(projection)
    source_incidence = wire["source_incidence"]
    before_incidence = store.read(source_incidence)
    before_revision = store.revision
    store.commit(store.revision, create=(
        Cell("court:topology:invisible-target", NULL_CELL_ID, NULL_CELL_ID, b""),
    ))

    with pytest.raises(InvalidCell, match="declared visible interface"):
        rewire_universal_connection(
            store,
            registry,
            source_incidence,
            "court:topology:invisible-target",
        )

    assert store.revision == before_revision + 1
    assert store.read(source_incidence) == before_incidence
    assert next(
        item for item in project_universal_canvas(store, registry)["wires"]
        if item["id"] == wire["id"]
    )["source_interface"] == wire["source_interface"]
