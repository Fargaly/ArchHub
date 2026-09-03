"""Workflow canvas v2 — undo/redo + node ops.

These tests run against CanvasScene at the data-model level (no Qt
event loop). Qt signals/slots and paint operations are out of scope;
those are exercised manually via the running app.

Covers:
  * snapshot/restore roundtrip preserves the workflow exactly
  * undo() / redo() flip between the two states
  * undo cap drops oldest entry past _UNDO_CAP
  * pushing on a new mutation clears the redo stack
  * delete_selected pushes one undo entry per call (not per node)
  * duplicate_node clones config + offsets position
  * snapshot is a no-op when state hasn't changed (idempotent)
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))


# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def qapp():
    """Single QApplication for the whole test session — Qt won't allow
    instantiating widgets without one. Headless: no event loop spun."""
    from PyQt6.QtWidgets import QApplication
    import sys as _sys
    app = QApplication.instance() or QApplication(_sys.argv)
    return app


@pytest.fixture
def scene(qapp):
    from workflow_canvas import CanvasScene
    from workflows.graph import Workflow
    wf = Workflow(id="test", name="Test")
    return CanvasScene(workflow=wf)


# ---------------------------------------------------------------------------
class TestUndoRedo:
    def test_initial_stacks_empty(self, scene):
        assert scene._undo == []
        assert scene._redo == []

    def test_add_node_pushes_undo(self, scene):
        from PyQt6.QtCore import QPointF
        scene._add_node("user.prompt", QPointF(100, 100))
        assert len(scene._undo) == 1
        assert len(scene.workflow.nodes) == 1

    def test_undo_restores_prior_state(self, scene):
        from PyQt6.QtCore import QPointF
        scene._add_node("user.prompt", QPointF(0, 0))
        scene._add_node("llm.complete", QPointF(200, 0))
        assert len(scene.workflow.nodes) == 2
        assert scene.undo() is True
        assert len(scene.workflow.nodes) == 1
        assert scene.undo() is True
        assert len(scene.workflow.nodes) == 0

    def test_undo_when_empty_returns_false(self, scene):
        assert scene.undo() is False

    def test_redo_after_undo(self, scene):
        from PyQt6.QtCore import QPointF
        scene._add_node("user.prompt", QPointF(0, 0))
        scene.undo()
        assert len(scene.workflow.nodes) == 0
        assert scene.redo() is True
        assert len(scene.workflow.nodes) == 1

    def test_new_mutation_clears_redo(self, scene):
        from PyQt6.QtCore import QPointF
        scene._add_node("a", QPointF(0, 0))
        scene._add_node("b", QPointF(50, 0))
        scene.undo()
        assert scene._redo  # one entry waiting
        scene._add_node("c", QPointF(100, 0))
        assert scene._redo == []

    def test_undo_cap_drops_oldest(self, scene):
        from PyQt6.QtCore import QPointF
        scene._UNDO_CAP = 3
        for i in range(10):
            scene._add_node(f"n{i}", QPointF(i * 20, 0))
        assert len(scene._undo) == 3

    def test_snapshot_dedup_skips_repeat_push(self, scene):
        # Two _push_undo calls back-to-back without any mutation between
        # them produce ONE entry, not two. Guards against cascading UI
        # events (click + mouseRelease) both calling push.
        from PyQt6.QtCore import QPointF
        scene._add_node("a", QPointF(0, 0))     # push #1 (pre: empty)
        scene._push_undo()                       # push #2 (pre: [a])
        before = len(scene._undo)
        scene._push_undo()                       # dedupe → skip
        scene._push_undo()                       # dedupe → skip
        assert len(scene._undo) == before


# ---------------------------------------------------------------------------
class TestNodeOps:
    def test_duplicate_node_offsets_position(self, scene):
        from PyQt6.QtCore import QPointF
        scene._add_node("user.prompt", QPointF(100, 50))
        ni = list(scene._node_items.values())[0]
        ni.node.config = {"foo": "bar"}
        new = scene.duplicate_node(ni)
        assert new is not None
        assert len(scene.workflow.nodes) == 2
        assert new.node.position["x"] == 100 + 24
        assert new.node.position["y"] == 50 + 24
        assert new.node.config == {"foo": "bar"}
        assert new.node.id != ni.node.id

    def test_delete_selected_pushes_one_undo(self, scene):
        from PyQt6.QtCore import QPointF
        scene._add_node("a", QPointF(0, 0))
        scene._add_node("b", QPointF(100, 0))
        scene._undo.clear()
        for it in scene._node_items.values():
            it.setSelected(True)
        n = scene.delete_selected()
        assert n == 2
        assert len(scene._undo) == 1   # not 2
        assert scene.workflow.nodes == []

    def test_delete_selected_with_no_selection_is_noop(self, scene):
        from PyQt6.QtCore import QPointF
        scene._add_node("a", QPointF(0, 0))
        scene._undo.clear()
        n = scene.delete_selected()
        assert n == 0
        assert scene._undo == []

    def test_clear_pushes_undo_and_can_be_undone(self, scene):
        from PyQt6.QtCore import QPointF
        scene._add_node("a", QPointF(0, 0))
        scene._clear()
        assert scene.workflow.nodes == []
        assert scene.undo() is True
        assert len(scene.workflow.nodes) == 1


# ---------------------------------------------------------------------------
class TestSnapshotRoundtrip:
    def test_snapshot_text_is_stable(self, scene):
        from PyQt6.QtCore import QPointF
        scene._add_node("user.prompt", QPointF(10, 10))
        a = scene._snapshot_text()
        b = scene._snapshot_text()
        assert a == b

    def test_restore_recreates_nodes(self, scene):
        from PyQt6.QtCore import QPointF
        scene._add_node("a", QPointF(0, 0))
        scene._add_node("b", QPointF(100, 0))
        snap = scene._snapshot_text()
        scene._clear()
        assert len(scene.workflow.nodes) == 0
        scene._restore(snap)
        assert len(scene.workflow.nodes) == 2
