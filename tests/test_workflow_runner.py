"""WorkflowRunner — wires-as-real-data-bridges (v1.4).

Pins:
  - Topo-sort via lazy pull walks upstream
  - Dirty mark cascades to all descendants
  - cache_key changes when params or upstream cache_keys change
  - Cache hit on second pull (no upstream change) skips re-execution
  - Cycle detection refuses src→dst when a path dst→src exists
  - WireBus stores values in-process, not persisted
  - on_wire_state callback fires for every state transition
  - Errors propagate as upstream_error on downstream edges

Workflow registry must be importable (registers AEC + io_data + control
nodes). The tests don't need PyQt — runner.py is pure Python.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))

# Importing workflows.nodes triggers registration; do it once.
from workflows import nodes as _nodes_pkg  # noqa: F401
from workflows.runner import WorkflowRunner, CycleDetected
from workflows.registry import register, NodeSpec, get as _get_spec
from workflows.graph import Port, PortType


# ── Test-only nodes ─────────────────────────────────────────────────
# We register a tiny adder + a no-op for unit testing the runner
# without depending on AEC executors that may have side effects.

def _adder_exec(config, inputs, ctx):
    a = float(inputs.get("a", 0) or 0)
    b = float(inputs.get("b", 0) or 0)
    return {"status": "ok", "sum": a + b}


def _constant_exec(config, inputs, ctx):
    return {"status": "ok", "value": config.get("value", 0)}


def _error_exec(config, inputs, ctx):
    return {"status": "error", "error": "boom"}


# Register only once per test session (re-register raises).
def _ensure_test_nodes():
    if _get_spec("_test.adder") is None:
        register(NodeSpec(
            type="_test.adder", category="_test",
            display_name="Test Adder", description="Adds a + b",
            inputs=[Port(name="a", type=PortType.NUMBER),
                     Port(name="b", type=PortType.NUMBER)],
            outputs=[Port(name="sum", type=PortType.NUMBER)],
            config_schema={}, icon="+",
        ), _adder_exec)
    if _get_spec("_test.constant") is None:
        register(NodeSpec(
            type="_test.constant", category="_test",
            display_name="Test Constant", description="Emits a constant",
            inputs=[],
            outputs=[Port(name="value", type=PortType.NUMBER)],
            config_schema={"value": {"type": "number"}}, icon="·",
        ), _constant_exec)
    if _get_spec("_test.error") is None:
        register(NodeSpec(
            type="_test.error", category="_test",
            display_name="Always Errors", description="error",
            inputs=[],
            outputs=[Port(name="out", type=PortType.NUMBER)],
            config_schema={}, icon="!",
        ), _error_exec)


@pytest.fixture(autouse=True)
def _setup():
    _ensure_test_nodes()


def _g(nodes, wires):
    """Helper to build a graph dict."""
    return {"nodes": nodes, "wires": wires}


def _const(node_id, value):
    return {"id": node_id, "type": "_test.constant",
            "config": {"value": value}, "ins": [],
            "outs": [{"id": "value", "t": "number"}]}


def _add(node_id):
    return {"id": node_id, "type": "_test.adder",
            "config": {},
            "ins":  [{"id": "a", "t": "number"},
                      {"id": "b", "t": "number"}],
            "outs": [{"id": "sum", "t": "number"}]}


def _wire(from_node, from_port, to_node, to_port):
    return {"from": [from_node, from_port],
            "to":   [to_node, to_port]}


# ── Topology ────────────────────────────────────────────────────────
class TestTopology:
    def test_pull_walks_upstream(self):
        """5 + 7 should land at the adder via two upstream pulls."""
        graph = _g(
            [_const("a", 5), _const("b", 7), _add("sum")],
            [_wire("a", "value", "sum", "a"),
             _wire("b", "value", "sum", "b")],
        )
        r = WorkflowRunner(graph)
        out = r.pull("sum")
        assert out["status"] == "ok"
        assert out["sum"] == 12

    def test_pull_for_leaf_node_with_no_upstream(self):
        graph = _g([_const("a", 99)], [])
        r = WorkflowRunner(graph)
        out = r.pull("a")
        assert out["value"] == 99

    def test_unknown_node_returns_error(self):
        graph = _g([_const("a", 1)], [])
        r = WorkflowRunner(graph)
        out = r.pull("nope")
        assert out["status"] == "error"

    def test_unknown_node_type_returns_error(self):
        graph = _g([{"id": "x", "type": "_does_not_exist",
                       "config": {}, "ins": [], "outs": []}], [])
        r = WorkflowRunner(graph)
        out = r.pull("x")
        assert out["status"] == "error"
        assert "executor" in out["error"]


# ── Caching ─────────────────────────────────────────────────────────
class TestCaching:
    def test_second_pull_hits_cache(self):
        graph = _g(
            [_const("a", 2), _const("b", 3), _add("sum")],
            [_wire("a", "value", "sum", "a"),
             _wire("b", "value", "sum", "b")],
        )
        r = WorkflowRunner(graph)
        r.pull("sum")
        # Replace the executor with a flag to detect re-cook.
        called = {"n": 0}
        _, original = _get_spec("_test.adder")
        def spy(c, i, x):
            called["n"] += 1
            return original(c, i, x)
        from workflows import registry as _reg
        _reg._REGISTRY["_test.adder"] = (
            _reg._REGISTRY["_test.adder"][0], spy)
        try:
            r.pull("sum")
            assert called["n"] == 0, "should hit cache, not re-cook"
        finally:
            _reg._REGISTRY["_test.adder"] = (
                _reg._REGISTRY["_test.adder"][0], original)

    def test_mark_dirty_invalidates_cache(self):
        graph = _g(
            [_const("a", 2), _const("b", 3), _add("sum")],
            [_wire("a", "value", "sum", "a"),
             _wire("b", "value", "sum", "b")],
        )
        r = WorkflowRunner(graph)
        r.pull("sum")
        r.mark_dirty("sum")
        # After dirty, pull must re-run.
        called = {"n": 0}
        _, original = _get_spec("_test.adder")
        def spy(c, i, x):
            called["n"] += 1
            return original(c, i, x)
        from workflows import registry as _reg
        _reg._REGISTRY["_test.adder"] = (
            _reg._REGISTRY["_test.adder"][0], spy)
        try:
            r.pull("sum")
            assert called["n"] == 1
        finally:
            _reg._REGISTRY["_test.adder"] = (
                _reg._REGISTRY["_test.adder"][0], original)

    def test_mark_dirty_cascades_downstream(self):
        # Chain: a → mid → sum. Dirtying `a` should also dirty `mid` + `sum`.
        graph = _g(
            [_const("a", 1), _const("b", 2),
             _add("mid"), _const("c", 0), _add("sum")],
            [_wire("a", "value", "mid", "a"),
             _wire("b", "value", "mid", "b"),
             _wire("mid", "sum", "sum", "a"),
             _wire("c", "value", "sum", "b")],
        )
        r = WorkflowRunner(graph)
        r.pull("sum")
        touched = r.mark_dirty("a")
        assert "a" in touched
        assert "mid" in touched
        assert "sum" in touched


# ── Cycle detection ─────────────────────────────────────────────────
class TestCycleDetection:
    def test_no_cycle_for_simple_chain(self):
        graph = _g(
            [_const("a", 1), _const("b", 2), _add("sum")],
            [_wire("a", "value", "sum", "a")],
        )
        r = WorkflowRunner(graph)
        assert r.would_create_cycle("b", "sum") is False

    def test_cycle_detected_through_back_edge(self):
        # a → b → c; adding c → a would loop.
        graph = _g(
            [_const("a", 1), _const("b", 2), _const("c", 3)],
            [_wire("a", "value", "b", "a"),
             _wire("b", "value", "c", "a")],
        )
        r = WorkflowRunner(graph)
        assert r.would_create_cycle("c", "a") is True

    def test_self_loop_refused(self):
        graph = _g([_const("a", 1)], [])
        r = WorkflowRunner(graph)
        assert r.would_create_cycle("a", "a") is True


# ── Wire state callbacks ────────────────────────────────────────────
class TestWireStateCallbacks:
    def test_on_wire_state_fires_for_each_transition(self):
        graph = _g(
            [_const("a", 7), _add("sum")],
            [_wire("a", "value", "sum", "a")],
        )
        r = WorkflowRunner(graph)
        seen: list = []
        r.on_wire_state(lambda eid, st, prev:
                          seen.append((eid, st)))
        r.pull("sum")
        # Should see at least: flowing then cached for the edge.
        states = [s for _, s in seen]
        assert "flowing" in states
        assert "cached" in states

    def test_wire_value_lives_in_bus(self):
        graph = _g(
            [_const("a", 42), _add("sum")],
            [_wire("a", "value", "sum", "a")],
        )
        r = WorkflowRunner(graph)
        r.pull("sum")
        # The edge id is derived from from/to nodes + ports.
        eid = "a.value-sum.a"
        assert r.wire_value(eid) == 42

    def test_persistable_state_drops_values(self):
        graph = _g(
            [_const("a", 9), _add("sum")],
            [_wire("a", "value", "sum", "a")],
        )
        r = WorkflowRunner(graph)
        r.pull("sum")
        snap = r.persistable_state()
        # Only metadata is serialized.
        assert "edges" in snap
        assert "node_cache_keys" in snap
        # Values are NOT in the snapshot — they live only in wire_bus.
        for e in snap["edges"]:
            assert "value" not in e


# ── Error propagation ──────────────────────────────────────────────
class TestErrorPropagation:
    def test_upstream_error_marks_downstream_state(self):
        graph = _g(
            [{"id": "boom", "type": "_test.error",
              "config": {}, "ins": [],
              "outs": [{"id": "out", "t": "number"}]},
             _add("sum")],
            [_wire("boom", "out", "sum", "a")],
        )
        r = WorkflowRunner(graph)
        out = r.pull("sum")
        assert out["status"] == "upstream_error"
        # The edge state should reflect this.
        e = next(e for e in r.edges if e["src_node"] == "boom")
        assert e["state"] == "upstream_error"
