"""Profound wires — edge field selectors (founder direction 2026-05-14).

A wire isn't a single-value hose anymore. It carries two optional path
selectors:

  • `src_field` — picks a sub-value out of the source node's output
    BEFORE the value flows into the destination's input slot
    (e.g. `"selection.walls"` to peel walls out of a selection dict).

  • `dst_field` — wraps the incoming value into a nested dict under the
    given key path BEFORE writing it into the destination input slot
    (e.g. `"messages[-1].content"`).

These let the canvas carve one structured output into many downstream
inputs without inserting helper "pick / unpack" nodes everywhere — and
the same machinery moves a Revit selection into a Speckle commit, or an
LLM completion into the prompt of the next LLM, without an explicit
"adapter" step.

Pins:
  - Dotted-path resolves dict / list / nested objects
  - src_field on edge picks a substring of upstream output
  - dst_field wraps incoming value into the right input slot
  - Bridge `wire_transform` (pure Python helper) round-trips
  - Bridge `list_wire_fields` (pure Python helper) enumerates paths
  - Missing field → returns None, doesn't raise
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))

# Importing workflows.nodes triggers registration; do it once.
from workflows import nodes as _nodes_pkg  # noqa: F401
from workflows.graph import Edge, Workflow, Node, Port, PortType
from workflows.runner import (
    WorkflowRunner,
    _resolve_field,
    _wrap_field,
    _enumerate_paths,
)
from workflows.registry import register, NodeSpec, get as _get_spec


# ── Test-only nodes ─────────────────────────────────────────────────
def _struct_exec(config, inputs, ctx):
    """Emits a structured selection-like value. The output port
    `selection` carries the whole nested dict (walls + doors +
    messages) so src_field can pick sub-keys off it."""
    return {
        "status": "ok",
        "selection": {
            "walls": [{"id": "w1"}, {"id": "w2"}],
            "doors": [{"id": "d1"}],
            "messages": [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello world"},
            ],
        },
    }


def _passthrough_exec(config, inputs, ctx):
    """Echoes its `value` input back so we can inspect what landed
    in inputs["value"] after src_field/dst_field were applied."""
    return {"status": "ok", "echo": inputs.get("value")}


def _ensure_test_nodes():
    if _get_spec("_test.struct") is None:
        register(NodeSpec(
            type="_test.struct", category="_test",
            display_name="Test Struct", description="Emits structured",
            inputs=[],
            outputs=[Port(name="selection", type=PortType.OBJECT)],
            config_schema={}, icon="{}"
        ), _struct_exec)
    if _get_spec("_test.passthrough") is None:
        register(NodeSpec(
            type="_test.passthrough", category="_test",
            display_name="Test Passthrough", description="Echo value",
            inputs=[Port(name="value", type=PortType.ANY)],
            outputs=[Port(name="echo", type=PortType.ANY)],
            config_schema={}, icon="="
        ), _passthrough_exec)


@pytest.fixture(autouse=True)
def _setup():
    _ensure_test_nodes()


# ── Dotted-path resolver ────────────────────────────────────────────
class TestResolveField:
    def test_empty_path_returns_value_as_is(self):
        assert _resolve_field({"a": 1}, "") == {"a": 1}

    def test_simple_dict_key(self):
        assert _resolve_field({"name": "wall1"}, "name") == "wall1"

    def test_nested_dict_keys(self):
        v = {"selection": {"walls": [{"id": "w1"}]}}
        assert _resolve_field(v, "selection.walls") == [{"id": "w1"}]

    def test_list_index(self):
        v = {"items": ["a", "b", "c"]}
        assert _resolve_field(v, "items[1]") == "b"

    def test_negative_list_index(self):
        v = {"messages": [{"content": "hi"}, {"content": "bye"}]}
        assert _resolve_field(v, "messages[-1].content") == "bye"

    def test_chained_list_and_dict(self):
        v = {"selection": {"walls": [{"id": "w1"},
                                        {"id": "w2"}]}}
        assert _resolve_field(v, "selection.walls[0].id") == "w1"

    def test_attribute_access_on_object(self):
        class Thing:
            def __init__(self):
                self.name = "bob"
        assert _resolve_field(Thing(), "name") == "bob"

    def test_bracketed_quoted_key(self):
        v = {"a b": {"id": "x"}}
        assert _resolve_field(v, "['a b'].id") == "x"

    def test_missing_key_returns_none(self):
        assert _resolve_field({"a": 1}, "b") is None
        assert _resolve_field({"a": 1}, "a.b.c") is None

    def test_missing_index_returns_none(self):
        assert _resolve_field({"items": [1, 2]}, "items[9]") is None

    def test_none_value_returns_none(self):
        assert _resolve_field(None, "anything") is None


# ── _wrap_field (inverse) ───────────────────────────────────────────
class TestWrapField:
    def test_empty_path_returns_value(self):
        assert _wrap_field(42, "") == 42

    def test_simple_key(self):
        assert _wrap_field("walls", "key") == {"key": "walls"}

    def test_nested_key(self):
        assert _wrap_field("v", "a.b.c") == {"a": {"b": {"c": "v"}}}

    def test_index_segment(self):
        assert _wrap_field("v", "items[0]") == {"items": {0: "v"}}

    def test_resolve_unwraps_wrap(self):
        v = {"x": [1, 2, 3]}
        wrapped = _wrap_field(v, "payload.data")
        assert _resolve_field(wrapped, "payload.data") == v


# ── Edge dataclass round-trip ──────────────────────────────────────
class TestEdgeRoundTrip:
    def test_edge_to_dict_includes_fields(self):
        e = Edge(id="e1", src_node="a", src_port="o",
                  dst_node="b", dst_port="i",
                  src_field="selection.walls",
                  dst_field="messages[-1]")
        d = e.to_dict()
        assert d["src_field"] == "selection.walls"
        assert d["dst_field"] == "messages[-1]"

    def test_edge_from_dict_round_trips_fields(self):
        d = {"id": "e1", "src_node": "a", "src_port": "o",
             "dst_node": "b", "dst_port": "i",
             "src_field": "selection.walls",
             "dst_field": "messages[-1]"}
        e = Edge.from_dict(d)
        assert e.src_field == "selection.walls"
        assert e.dst_field == "messages[-1]"

    def test_edge_from_dict_missing_fields_defaults_empty(self):
        d = {"id": "e1", "src_node": "a", "src_port": "o",
             "dst_node": "b", "dst_port": "i"}
        e = Edge.from_dict(d)
        assert e.src_field == ""
        assert e.dst_field == ""

    def test_workflow_round_trip_preserves_edge_fields(self):
        wf = Workflow.new("test")
        wf.add_node(Node(id="a", type="_test.struct",
                          outputs=[Port(name="selection",
                                          type=PortType.OBJECT)]))
        wf.add_node(Node(id="b", type="_test.passthrough",
                          inputs=[Port(name="value",
                                         type=PortType.ANY)]))
        wf.add_edge(Edge(id="e1", src_node="a", src_port="selection",
                          dst_node="b", dst_port="value",
                          src_field="walls[0].id",
                          dst_field="payload"))
        wf2 = Workflow.from_json(wf.to_json())
        assert wf2.edges[0].src_field == "walls[0].id"
        assert wf2.edges[0].dst_field == "payload"


# ── Runner honours src_field ────────────────────────────────────────
class TestRunnerSrcField:
    def _g(self, src_field=""):
        return {
            "nodes": [
                {"id": "src", "type": "_test.struct", "config": {},
                 "ins": [], "outs": [{"id": "selection", "t": "object"}]},
                {"id": "dst", "type": "_test.passthrough", "config": {},
                 "ins": [{"id": "value", "t": "any"}],
                 "outs": [{"id": "echo", "t": "any"}]},
            ],
            "wires": [
                {"id": "w1", "from": ["src", "selection"],
                 "to": ["dst", "value"],
                 "src_field": src_field},
            ],
        }

    def test_no_field_passes_whole_value(self):
        r = WorkflowRunner(self._g())
        out = r.pull("dst")
        assert out["status"] == "ok"
        echoed = out["echo"]
        # The whole "selection" value-of-port flows through unchanged.
        assert "walls" in echoed
        assert echoed["walls"][0]["id"] == "w1"

    def test_src_field_picks_substring(self):
        # src_field operates on the value of the src_port, not the
        # whole node-output dict — so "walls", not "selection.walls".
        r = WorkflowRunner(self._g(src_field="walls"))
        out = r.pull("dst")
        assert out["echo"] == [{"id": "w1"}, {"id": "w2"}]

    def test_src_field_deep_index(self):
        r = WorkflowRunner(self._g(src_field="walls[0].id"))
        out = r.pull("dst")
        assert out["echo"] == "w1"

    def test_src_field_negative_index(self):
        r = WorkflowRunner(
            self._g(src_field="messages[-1].content"))
        out = r.pull("dst")
        assert out["echo"] == "hello world"

    def test_missing_src_field_yields_none(self):
        r = WorkflowRunner(self._g(src_field="nope"))
        out = r.pull("dst")
        # Soft-miss: input becomes None, node still runs.
        assert out["status"] == "ok"
        assert out["echo"] is None


# ── Runner honours dst_field ────────────────────────────────────────
class TestRunnerDstField:
    def test_dst_field_wraps_into_input_slot(self):
        graph = {
            "nodes": [
                {"id": "src", "type": "_test.struct", "config": {},
                 "ins": [], "outs": [{"id": "selection", "t": "object"}]},
                {"id": "dst", "type": "_test.passthrough", "config": {},
                 "ins": [{"id": "value", "t": "any"}],
                 "outs": [{"id": "echo", "t": "any"}]},
            ],
            "wires": [
                {"id": "w1", "from": ["src", "selection"],
                 "to": ["dst", "value"],
                 "src_field": "walls",
                 "dst_field": "payload.data"},
            ],
        }
        r = WorkflowRunner(graph)
        out = r.pull("dst")
        # Wrapped: payload.data → walls list
        assert out["echo"] == {"payload":
                                {"data": [{"id": "w1"}, {"id": "w2"}]}}


# ── Cache key invalidates on selector change ────────────────────────
class TestCacheKeyOnSelectorChange:
    def test_changing_src_field_invalidates_cache(self):
        graph = {
            "nodes": [
                {"id": "src", "type": "_test.struct", "config": {},
                 "ins": [], "outs": [{"id": "selection", "t": "object"}]},
                {"id": "dst", "type": "_test.passthrough", "config": {},
                 "ins": [{"id": "value", "t": "any"}],
                 "outs": [{"id": "echo", "t": "any"}]},
            ],
            "wires": [{"id": "w1", "from": ["src", "selection"],
                        "to": ["dst", "value"],
                        "src_field": "walls"}],
        }
        r = WorkflowRunner(graph)
        r.pull("dst")
        key_before = r.node_cache_keys["dst"]
        # Mutate the selector — cache key should change.
        r.edges[0]["src_field"] = "doors"
        r.mark_dirty("dst")
        r.pull("dst")
        key_after = r.node_cache_keys["dst"]
        assert key_before != key_after


# ── _enumerate_paths ────────────────────────────────────────────────
class TestEnumeratePaths:
    def test_dict_paths(self):
        v = {"a": 1, "b": {"c": 2}}
        paths = _enumerate_paths(v)
        assert "a" in paths
        assert "b" in paths
        assert "b.c" in paths

    def test_list_paths(self):
        v = {"items": [{"id": 1}, {"id": 2}]}
        paths = _enumerate_paths(v)
        assert "items" in paths
        assert "items[0]" in paths
        assert "items[0].id" in paths
        # Negative index is also enumerated (useful for "last message").
        assert "items[-1]" in paths

    def test_bounded_size(self):
        # 1000 keys shouldn't enumerate forever.
        v = {f"k{i}": i for i in range(1000)}
        paths = _enumerate_paths(v, max_items=50)
        assert len(paths) <= 50


# ── Bridge helpers (importable without PyQt) ────────────────────────
class TestBridgeWireTransformHelper:
    """We avoid importing the QObject; the helpers themselves are the
    bits the bridge slots delegate to and they live in runner.py."""

    def test_wire_transform_src_only(self):
        payload = {"selection": {"walls": [{"id": "w1"}]}}
        # Manually replay what the bridge slot does.
        value = _resolve_field(payload, "selection.walls")
        assert value == [{"id": "w1"}]

    def test_wire_transform_dst_only(self):
        value = _wrap_field("walls", "payload.data")
        assert value == {"payload": {"data": "walls"}}

    def test_wire_transform_round_trip(self):
        payload = {"selection": {"walls": [{"id": "w1"}]}}
        v = _resolve_field(payload, "selection.walls")
        v = _wrap_field(v, "input.data")
        assert v == {"input": {"data": [{"id": "w1"}]}}

    def test_list_wire_fields_helper(self):
        sample = {"selection": {"walls": [{"id": "w1"}, {"id": "w2"}]}}
        paths = _enumerate_paths(sample)
        # User expects "selection.walls" + "selection.walls[0].id" etc.
        assert "selection" in paths
        assert "selection.walls" in paths
        assert any(p.startswith("selection.walls[") for p in paths)

    def test_list_wire_fields_empty_sample(self):
        # No sample = no paths, doesn't blow up.
        assert _enumerate_paths(None) == []
        assert _enumerate_paths({}) == []
        assert _enumerate_paths([]) == []


# ── Edge case: malformed / partial paths ────────────────────────────
class TestEdgeCases:
    def test_partial_path_into_scalar_returns_none(self):
        # Trying to descend into an int.
        assert _resolve_field(5, "a.b") is None

    def test_index_on_dict_returns_none(self):
        # `[0]` only makes sense for lists; on a dict it misses.
        assert _resolve_field({"a": 1}, "[0]") is None

    def test_runner_does_not_raise_on_bad_field(self):
        graph = {
            "nodes": [
                {"id": "src", "type": "_test.struct", "config": {},
                 "ins": [], "outs": [{"id": "selection", "t": "object"}]},
                {"id": "dst", "type": "_test.passthrough", "config": {},
                 "ins": [{"id": "value", "t": "any"}],
                 "outs": [{"id": "echo", "t": "any"}]},
            ],
            "wires": [{"id": "w1", "from": ["src", "selection"],
                        "to": ["dst", "value"],
                        "src_field": "totally.does.not.exist"}],
        }
        r = WorkflowRunner(graph)
        out = r.pull("dst")
        assert out["status"] == "ok"
        assert out["echo"] is None
