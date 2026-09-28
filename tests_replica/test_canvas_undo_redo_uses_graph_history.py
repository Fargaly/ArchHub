"""Canvas Undo / Redo run the graph's own history (07a1364) -- what the Studio's Ctrl+Z calls.

The Studio sends Undo and Redo through the history Interaction the server issues for the
canvas controls app:control:canvas:undo|redo (POST /api/universal/interaction ->
submit_universal_history_interaction -> undo_universal_change / redo_universal_change).
These courts drive those same functions on a real graph:

- a hand move (POST /api/universal/gesture) is taken back by Undo and put back by Redo;
- a node added through the library route (POST /api/universal/node-create) is NOT taken back:
  create_engine_node writes its interfaces and rows after the recorded Instantiate, and the
  history refuses ("created Cell gained references after the recorded transaction");
- a node deleted through POST /api/universal/retract is NOT brought back by Undo: retract commits
  outside the action history, and no recorded node-removal route exists. That court is held
  strict-xfail so it turns red-to-green the day retract is recorded, and cannot pass silently now.
"""
from __future__ import annotations

import pytest

from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    apply_universal_canvas_gesture,
    build_universal_application,
    project_universal_canvas,
    redo_universal_change,
    undo_universal_change,
)
from nodelang.universal_pipeline import create_engine_node, retract_universal_node


@pytest.fixture()
def graph():
    store, registry = build_universal_application(resolve_map_path())
    try:
        yield store, registry
    finally:
        store.close()


def _on_canvas(store, registry, root):
    return any(node["id"] == root for node in project_universal_canvas(store, registry)["nodes"])


def _history(store, registry):
    return project_universal_canvas(store, registry)["action_history"]


def _at(store, registry, root):
    node = next(node for node in project_universal_canvas(store, registry)["nodes"] if node["id"] == root)
    return (node["x"], node["y"])


def test_undo_takes_back_a_move_and_redo_puts_it_back(graph):
    store, registry = graph
    root = project_universal_canvas(store, registry)["nodes"][0]["id"]
    start = _at(store, registry, root)
    moved = {"x": start[0] + 160.0, "y": start[1] + 80.0}
    apply_universal_canvas_gesture(store, registry, positions={root: moved})
    assert _at(store, registry, root) == (moved["x"], moved["y"])
    assert _history(store, registry)["can_undo"] is True
    undo_universal_change(store, registry)
    assert _at(store, registry, root) == start, "undo puts the card back"
    assert _history(store, registry)["can_redo"] is True
    redo_universal_change(store, registry)
    assert _at(store, registry, root) == (moved["x"], moved["y"]), "redo moves it again"


@pytest.mark.xfail(strict=True, raises=Exception, reason=(
    "blocker: create_engine_node (POST /api/universal/node-create) writes interfaces and rows as raw "
    "commits after the recorded Instantiate; the history refuses: created Cell gained references"))
def test_undo_takes_back_an_added_node_and_redo_puts_it_back(graph):
    store, registry = graph
    root = create_engine_node(store, registry, title="Undo Probe", engine="lines.watch")["root"]
    for _ in range(3):
        if not _on_canvas(store, registry, root):
            break
        undo_universal_change(store, registry)
    assert not _on_canvas(store, registry, root), "undo takes the added node back"
    redo_universal_change(store, registry)
    assert _on_canvas(store, registry, root)

@pytest.mark.xfail(strict=True, reason=(
    "blocker: POST /api/universal/retract (universal_pipeline.retract_universal_node) commits "
    "outside the action history, so Undo cannot bring a deleted node back"))
def test_undo_brings_back_a_deleted_node_and_redo_removes_it_again(graph):
    store, registry = graph
    root = create_engine_node(store, registry, title="Delete Probe", engine="lines.watch")["root"]
    retract_universal_node(store, registry, root)
    assert not _on_canvas(store, registry, root)
    undo_universal_change(store, registry)
    assert _on_canvas(store, registry, root), "undo brings the deleted node back"
    redo_universal_change(store, registry)
    assert not _on_canvas(store, registry, root), "redo removes it again"