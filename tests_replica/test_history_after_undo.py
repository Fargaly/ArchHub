"""A change after an undo truncates the redo tail, and the canvas stays readable.

History is linear: a new original change after an undo discards the redo
tail. Those undone originals stay in the record; before, the canvas's
history projection found them neither applied nor redoable and refused the
whole canvas ("action history transaction has no derived state") -- one
move, undo, move made the founder's graph unreadable. Every original now has
exactly one derived state (applied, undone, discarded), and each sequence
below stays readable and byte-equal to the un-accelerated build.
"""
from __future__ import annotations

import json

import pytest

import nodelang.universal_application as ua
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    build_universal_application,
    clear_canvas_accelerator,
    project_universal_canvas,
)
from nodelang.universal_cell import Conflict


def _generic(store, registry, monkeypatch):
    with monkeypatch.context() as scoped:
        scoped.setenv("ARCHHUB_CANVAS_ACCELERATOR", "0")
        return json.dumps(project_universal_canvas(store, registry))


def _readable(store, registry, monkeypatch):
    accelerated = project_universal_canvas(store, registry)
    assert json.dumps(accelerated) == _generic(store, registry, monkeypatch)
    return accelerated


def _setup(monkeypatch):
    store, registry = build_universal_application(resolve_map_path())
    clear_canvas_accelerator(store)
    answer = _readable(store, registry, monkeypatch)
    node = next(
        item for item in answer["nodes"] if item["id"] != answer.get("selected")
    )
    return store, registry, node


def _move(store, registry, node, dx):
    return ua.move_universal_root(
        store, registry, node["id"], float(node["x"]) + dx, float(node["y"])
    )


def _states(answer):
    return [row["state"] for row in answer["action_history"]["transactions"]]


def test_move_undo_move_keeps_the_canvas_readable(monkeypatch):
    store, registry, node = _setup(monkeypatch)
    _move(store, registry, node, 10)
    _move(store, registry, node, 20)
    ua.undo_universal_change(store, registry)
    _readable(store, registry, monkeypatch)
    _move(store, registry, node, 30)
    answer = _readable(store, registry, monkeypatch)
    moved = next(item for item in answer["nodes"] if item["id"] == node["id"])
    assert moved["x"] == float(node["x"]) + 30
    assert _states(answer)[:3] == ["applied", "undo", "discarded"]
    assert answer["action_history"]["can_redo"] is False
    assert answer["action_history"]["can_undo"] is True


def test_undo_twice_then_move_discards_both(monkeypatch):
    store, registry, node = _setup(monkeypatch)
    _move(store, registry, node, 10)
    _move(store, registry, node, 20)
    ua.undo_universal_change(store, registry)
    ua.undo_universal_change(store, registry)
    _readable(store, registry, monkeypatch)
    _move(store, registry, node, 40)
    answer = _readable(store, registry, monkeypatch)
    assert _states(answer)[:5] == ["applied", "undo", "undo", "discarded", "discarded"]
    # The truncated tail is gone for good; undo still walks the live line.
    ua.undo_universal_change(store, registry)
    answer = _readable(store, registry, monkeypatch)
    moved = next(item for item in answer["nodes"] if item["id"] == node["id"])
    assert moved["x"] == float(node["x"])


def test_redo_after_a_new_move_is_refused_and_changes_nothing(monkeypatch):
    store, registry, node = _setup(monkeypatch)
    _move(store, registry, node, 10)
    ua.undo_universal_change(store, registry)
    _move(store, registry, node, 50)
    before = store.revision
    with pytest.raises(Conflict, match="nothing to redo"):
        ua.redo_universal_change(store, registry)
    assert store.revision == before
    answer = _readable(store, registry, monkeypatch)
    moved = next(item for item in answer["nodes"] if item["id"] == node["id"])
    assert moved["x"] == float(node["x"]) + 50
    # Undo then redo on the live line still round-trips.
    ua.undo_universal_change(store, registry)
    _readable(store, registry, monkeypatch)
    ua.redo_universal_change(store, registry)
    answer = _readable(store, registry, monkeypatch)
    moved = next(item for item in answer["nodes"] if item["id"] == node["id"])
    assert moved["x"] == float(node["x"]) + 50
