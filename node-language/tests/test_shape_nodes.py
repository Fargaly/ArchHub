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

    def test_existing_ops_unchanged_no_regression(self):
        # Belt-and-braces: the pre-pluck ops must behave byte-for-byte.
        assert _transform_executor(
            {"op": "identity"}, {"value": WALLS}, None)["value"] is WALLS
        assert _transform_executor(
            {"op": "count"}, {"value": WALLS}, None)["value"] == 3
        assert _transform_executor(
            {"op": "pick", "field": "h"}, {"value": WALLS}, None
        )["value"] == [3, 2, 4]
        assert _transform_executor(
            {"op": "first"}, {"value": WALLS}, None)["value"] == WALLS[0]
        assert _transform_executor(
            {"op": "last"}, {"value": WALLS}, None)["value"] == WALLS[-1]
        assert _transform_executor(
            {"op": "unique"}, {"value": [1, 1, 2, 3, 3]}, None
        )["value"] == [1, 2, 3]
        assert _transform_executor(
            {"op": "flatten"}, {"value": [[1, 2], [3]]}, None
        )["value"] == [1, 2, 3]


ROWS = [
    {"id": 1, "name": "Alpha", "h": 3, "extra": "x"},
    {"id": 2, "name": "Beta", "h": 2},            # no "extra"
    {"id": 3, "name": "Gamma", "h": 4, "extra": "z"},
]


class TestTransformPluck:
    """UPGRADE 2: op=pluck projects a SUBSET of fields per dict row into a
    NEW list of dicts (distinct from `pick`'s single-field flat list)."""

    def test_subset_projection(self):
        out = _transform_executor(
            {"op": "pluck", "fields": ["id", "name"]},
            {"value": ROWS}, None)
        assert out["value"] == [
            {"id": 1, "name": "Alpha"},
            {"id": 2, "name": "Beta"},
            {"id": 3, "name": "Gamma"},
        ]
        assert out["count"] == 3

    def test_pluck_is_distinct_from_pick(self):
        # pick -> flat list of one field's values; pluck -> list of dicts.
        pick = _transform_executor(
            {"op": "pick", "field": "name"}, {"value": ROWS}, None)["value"]
        pluck = _transform_executor(
            {"op": "pluck", "fields": ["name"]}, {"value": ROWS}, None)["value"]
        assert pick == ["Alpha", "Beta", "Gamma"]
        assert pluck == [{"name": "Alpha"}, {"name": "Beta"},
                         {"name": "Gamma"}]

    def test_rename_maps_old_to_new(self):
        out = _transform_executor(
            {"op": "pluck", "fields": ["id", "name"],
             "rename": {"name": "label"}},
            {"value": ROWS}, None)
        assert out["value"] == [
            {"id": 1, "label": "Alpha"},
            {"id": 2, "label": "Beta"},
            {"id": 3, "label": "Gamma"},
        ]

    def test_missing_field_is_omitted_tolerantly(self):
        # Row 2 has no "extra" -> that key is simply omitted, not None.
        out = _transform_executor(
            {"op": "pluck", "fields": ["id", "extra"]},
            {"value": ROWS}, None)
        assert out["value"] == [
            {"id": 1, "extra": "x"},
            {"id": 2},                 # "extra" omitted, not present
            {"id": 3, "extra": "z"},
        ]

    def test_non_dict_row_is_skipped(self):
        out = _transform_executor(
            {"op": "pluck", "fields": ["id"]},
            {"value": [{"id": 1}, 42, "str", {"id": 2}]}, None)
        # Non-dict rows (42, "str") are skipped — they have no fields.
        assert out["value"] == [{"id": 1}, {"id": 2}]
        assert out["count"] == 2

    def test_non_list_input_typed_error_no_raise(self):
        out = _transform_executor(
            {"op": "pluck", "fields": ["id"]},
            {"value": {"id": 1}}, None)   # a bare dict, not a list
        assert out.get("status") == "error"
        assert "value" not in out

    def test_empty_fields_typed_error(self):
        out = _transform_executor(
            {"op": "pluck", "fields": []}, {"value": ROWS}, None)
        assert out.get("status") == "error"

    def test_missing_fields_key_typed_error(self):
        out = _transform_executor(
            {"op": "pluck"}, {"value": ROWS}, None)
        assert out.get("status") == "error"

    def test_pluck_in_op_enum_and_documented(self):
        import workflows as _wf
        spec, _ = _wf.get("transform.apply")
        assert "pluck" in spec.config_schema["op"]["enum"]
        # Originals preserved (no enum regression).
        for op in ("identity", "count", "first", "last", "pick",
                   "unique", "sort", "flatten"):
            assert op in spec.config_schema["op"]["enum"]
        assert "fields" in spec.config_schema
        assert "rename" in spec.config_schema


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
