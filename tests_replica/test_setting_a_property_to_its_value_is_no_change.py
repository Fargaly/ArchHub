"""Setting a property to the value it already holds is no change, not an error.

The installed app (beebac5, real window on a hidden desktop, 2026-10-01): a
connection's REVERT ALL answered 400 "tracked change requires a continuing Cell
anchor for compensation" on /api/universal/set-property, and the Properties
panel showed "tree: not saved" and "condition: not saved". The values were
already at their defaults, so the tracked change held no replacement and was
refused. Re-picking the option a parameter already shows did the same.
"""
from __future__ import annotations

import pytest

from nodelang import universal_application as app
from nodelang.map_import import resolve_map_path
from nodelang.universal_pipeline import _ensure_wire_parameters, _owner_properties, create_engine_node
from tests_replica.test_wiring2_lane_repairs import _wire


@pytest.fixture()
def graph():
    store, registry = app.build_universal_application(resolve_map_path())
    try:
        yield store, registry
    finally:
        store.close()


def _wire_with_parameters(store, registry):
    note = create_engine_node(store, registry, title="Note", engine="library.add_text",
                              properties={"text": "A"})["root"]
    merge = create_engine_node(store, registry, title="Merge", engine="library.merge", x=500.0)["root"]
    wire = _wire(store, registry, note, "out", merge, "in")
    _ensure_wire_parameters(store, registry, wire)
    return wire


def _condition(store, registry, wire):
    return _owner_properties(store.snapshot(), registry)[wire]["condition"]


def test_reverting_a_connection_parameter_to_the_value_it_holds_is_no_change(graph):
    store, registry = graph
    wire = _wire_with_parameters(store, registry)
    relation, current = _condition(store, registry, wire)[:2]
    before = store.revision
    assert app.edit_universal_property(store, registry, relation, current)
    assert store.revision == before, "an unchanged value commits nothing"
    assert _condition(store, registry, wire)[1] == current


def test_a_real_change_still_commits_and_undoes(graph):
    store, registry = graph
    wire = _wire_with_parameters(store, registry)
    relation, current = _condition(store, registry, wire)[:2]
    before = store.revision
    app.edit_universal_property(store, registry, relation, "count > 5")
    assert store.revision > before
    assert _condition(store, registry, wire)[1] == "count > 5"
    app.undo_universal_change(store, registry)
    assert _condition(store, registry, wire)[1] == current
