"""Tests for the shape / observe node executors — filter, transform,
watch (node-system redesign slices 6-7, docs/NODE_GRAMMAR.md).

Proves the three executors run, error honestly on bad config, and cook
inside a real canvas graph through WorkflowRunner.
"""
from __future__ import annotations

import sys
from pathlib import Path

_APP = Path(__file__).resolve().parent.parent / "app"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

import workflows  # noqa: E402  importing registers the engine node types
from workflows import node_grammar as ng  # noqa: E402
from workflows.runner import WorkflowRunner  # noqa: E402
from workflows.nodes.shape import (  # noqa: E402
    _filter_executor, _transform_executor, _watch_executor,
)

WALLS = [{"type": "wall", "h": 3}, {"type": "door", "h": 2},
         {"type": "wall", "h": 4}]


class TestRegisteredAndReady:
    def test_executors_registered(self):
        for t in ("filter.apply", "transform.apply", "watch.preview"):
            assert workflows.get(t) is not None, t

    def test_grammar_primitives_now_ready(self):
        for kind in ("filter", "transform", "watch"):
            assert ng.get_primitive(kind).status == ng.READY, kind
        unbuilt = {p.kind for p in ng.PRIMITIVES
                   if p.status == ng.NEEDS_EXECUTOR}
        assert unbuilt == set()


class TestFilter:
    def test_keeps_matching_items(self):
        out = _filter_executor(
            {"field": "type", "op": "eq", "match": "wall"},
            {"value": WALLS}, None)
        assert out["count"] == 2
        assert all(it["type"] == "wall" for it in out["value"])

    def test_numeric_op(self):
        out = _filter_executor(
            {"field": "h", "op": "gt", "match": 2},
            {"value": WALLS}, None)
        assert out["count"] == 2   # h=3 and h=4

    def test_unknown_op_errors_honestly(self):
        out = _filter_executor({"op": "telepathy"}, {"value": WALLS}, None)
        assert out.get("status") == "error"


class TestTransform:
    def test_count(self):
        assert _transform_executor(
            {"op": "count"}, {"value": WALLS}, None)["value"] == 3

    def test_pick(self):
        out = _transform_executor({"op": "pick", "field": "type"},
                                  {"value": WALLS}, None)
        assert out["value"] == ["wall", "door", "wall"]

    def test_first_and_last(self):
        assert _transform_executor(
            {"op": "first"}, {"value": WALLS}, None)["value"]["type"] == "wall"
        assert _transform_executor(
            {"op": "last"}, {"value": WALLS}, None)["value"]["h"] == 4

    def test_unknown_op_errors_honestly(self):
        out = _transform_executor({"op": "nonsense"}, {"value": WALLS}, None)
        assert out.get("status") == "error"


class TestWatch:
    def test_passes_data_through_unchanged(self):
        out = _watch_executor({"as": "list"}, {"value": WALLS}, None)
        assert out["value"] is WALLS                 # identity — never altered
        assert isinstance(out["preview"], str) and out["preview"]


def test_constant_filter_output_graph_cooks_end_to_end():
    """A canvas graph constant(list) -> filter -> output cooks the
    filtered list through the real WorkflowRunner."""
    graph = {
        "nodes": [
            {"id": "c1", "kind": "constant",
             "params": [{"k": "value", "v": WALLS}]},
            {"id": "f1", "kind": "filter",
             "params": [{"k": "field", "v": "type"},
                        {"k": "op", "v": "eq"},
                        {"k": "match", "v": "wall"}]},
            {"id": "o1", "kind": "output",
             "params": [{"k": "name", "v": "result"}]},
        ],
        "wires": [
            {"from": ["c1", "value"], "to": ["f1", "value"]},
            {"from": ["f1", "value"], "to": ["o1", "value"]},
        ],
    }
    runner = WorkflowRunner(ng.normalize_canvas_graph(graph))
    out = runner.pull("o1")
    assert isinstance(out.get("value"), list)
    assert len(out["value"]) == 2
    assert all(it["type"] == "wall" for it in out["value"])
