"""A library placement is one recorded change: one Undo takes the whole card back, Redo restores it.

Founder smoke 2026-10-01: Undo right after placing a library card answered 400 "created Cell gained
references after the recorded transaction". create_engine_node wrote the instance, then each
parameter, then the card's sockets as separate writes; the history recorded only the instance, so
the later writes pinned it. The card, its parameters and its sockets now land in one transaction.
A real later change that depends on the card (a wire to it) still blocks taking the card back.
"""
from __future__ import annotations

import pytest

from nodelang.map_import import resolve_map_path
from nodelang.universal_cell import NULL_CELL_ID, Cell
from nodelang.universal_application import (
    build_universal_application,
    connect_universal_roots,
    project_universal_canvas,
    redo_universal_change,
    undo_universal_change,
)
from nodelang.universal_pipeline import create_engine_node


@pytest.fixture()
def graph():
    store, registry = build_universal_application(resolve_map_path())
    try:
        yield store, registry
    finally:
        store.close()


def _node(store, registry, root):
    return next((node for node in project_universal_canvas(store, registry)["nodes"] if node["id"] == root), None)


def _card(node):
    """What the person sees of one card: title, parameters and sockets."""
    return (
        node["label"],
        sorted((row["label"], row["value"]) for row in node["params"]),
        sorted((port["id"], port["side"]) for port in node["ports"] if port.get("mode") == "connection"),
    )


def test_one_undo_takes_the_placed_card_back_and_redo_restores_the_same_card(graph):
    store, registry = graph
    root = create_engine_node(store, registry, title="Placed", engine="lines.watch")["root"]
    placed = _card(_node(store, registry, root))
    assert placed[2], "the card has its sockets"
    undo_universal_change(store, registry)
    assert _node(store, registry, root) is None, "one Undo takes the whole card back"
    redo_universal_change(store, registry)
    assert _card(_node(store, registry, root)) == placed, "Redo restores the same card, parameters and sockets"


def _wire(store, registry, source, target):
    canvas = project_universal_canvas(store, registry)
    out = next(port["id"] for node in canvas["nodes"] if node["id"] == source
               for port in node["ports"] if port["side"] == "source" and port.get("mode") == "connection")
    into = next(port["id"] for node in canvas["nodes"] if node["id"] == target
                for port in node["ports"] if port["side"] == "target" and port.get("mode") == "connection")
    return connect_universal_roots(store, registry, source, target, source_interface=out, target_interface=into)[0]


def test_a_wire_to_the_placed_card_is_undone_first_then_the_card(graph):
    store, registry = graph
    source = create_engine_node(store, registry, title="Source", engine="lines.watch")["root"]
    target = create_engine_node(store, registry, title="Target", engine="lines.watch")["root"]
    wire = _wire(store, registry, source, target)
    undo_universal_change(store, registry)
    assert wire not in {item["id"] for item in project_universal_canvas(store, registry)["wires"]}, "the wire is undone"
    assert _node(store, registry, target) is not None, "the card stays while only the wire is undone"
    undo_universal_change(store, registry)
    assert _node(store, registry, target) is None, "then the placement is taken back"


def test_a_later_dependency_outside_the_history_still_blocks_taking_the_placement_back(graph):
    store, registry = graph
    root = create_engine_node(store, registry, title="Pinned", engine="lines.watch")["root"]
    # A change the history does not record now points into the card: taking the card back would
    # orphan it, so the existing guard must still refuse.
    store.commit(store.revision, create=(Cell("test:later-dependency", root, NULL_CELL_ID, b"pin"),))
    with pytest.raises(Exception, match="created Cell gained references after the recorded transaction"):
        undo_universal_change(store, registry)
    assert _node(store, registry, root) is not None
