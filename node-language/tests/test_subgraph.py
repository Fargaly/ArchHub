"""Subgraph-as-node: compose, expand, executor — and the Python-side
wire-add helper that mirrors the JSX `/wire` composer command.

Pins:
  * compose_subgraph collapses N selected nodes into one composite,
    with dangling external ports lifted onto a facade.
  * expand_subgraph is the exact inverse — composing then expanding
    returns the original topology (node ids preserved).
  * The `subgraph.user` executor cooks the inner graph via a nested
    WorkflowRunner and maps outer inputs to inner entry points.
  * `add_wire` (the composer `/wire` path) idempotently appends a
    canvas-shape wire dict.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))

# Importing workflows.nodes + workflows.subgraph registers everything.
from workflows import nodes as _nodes_pkg  # noqa: F401
from workflows import subgraph  # noqa: F401  triggers register_subgraph_executor
from workflows.runner import WorkflowRunner
from workflows.registry import register, NodeSpec, get as _get_spec
from workflows.graph import Port, PortType


# ── Test-only adder + constant nodes (mirror test_workflow_runner.py) ──
def _adder_exec(config, inputs, ctx):
    a = float(inputs.get("a", 0) or 0)
    b = float(inputs.get("b", 0) or 0)
    return {"status": "ok", "sum": a + b}


def _constant_exec(config, inputs, ctx):
    return {"status": "ok", "value": config.get("value", 0)}


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
            display_name="Test Constant",
            description="Returns config.value on port `value`",
            inputs=[],
            outputs=[Port(name="value", type=PortType.NUMBER)],
            config_schema={}, icon="·",
        ), _constant_exec)


@pytest.fixture(autouse=True)
def _setup():
    _ensure_test_nodes()
    yield


# ── compose_subgraph ─────────────────────────────────────────────────
def _three_node_graph():
    """const A → adder + B → adder → sum. Selecting {A, adder, B} should
    leave a single composite with the `sum` output dangling."""
    return {
        "nodes": [
            {"id": "A", "type": "_test.constant",
              "config": {"value": 3},
              "outs": [{"id": "value", "label": "value", "t": "number"}]},
            {"id": "B", "type": "_test.constant",
              "config": {"value": 4},
              "outs": [{"id": "value", "label": "value", "t": "number"}]},
            {"id": "adder", "type": "_test.adder",
              "config": {},
              "ins":  [{"id": "a", "label": "a", "t": "number"},
                        {"id": "b", "label": "b", "t": "number"}],
              "outs": [{"id": "sum", "label": "sum", "t": "number"}]},
        ],
        "wires": [
            {"from": ["A", "value"], "to": ["adder", "a"]},
            {"from": ["B", "value"], "to": ["adder", "b"]},
        ],
    }


def test_compose_subgraph_collapses_three_connected_nodes():
    graph = _three_node_graph()
    new = subgraph.compose_subgraph(graph, ["A", "B", "adder"])

    # Exactly one node remains, and it's a subgraph.user.
    assert len(new["nodes"]) == 1
    assert new["nodes"][0]["type"] == "subgraph.user"
    # No outer wires — every original wire was wholly-inside the
    # selection, so they all migrate into inner_graph.
    assert new["wires"] == []
    cfg = new["nodes"][0]["config"]
    inner = cfg["inner_graph"]
    assert len(inner["nodes"]) == 3
    assert len(inner["wires"]) == 2
    # No outer dangling ports (all source nodes were captured too).
    assert cfg["inner_inputs"] == []
    assert cfg["inner_outputs"] == []


def test_compose_subgraph_lifts_dangling_ports():
    """If a non-selected node feeds into the selection, that wire's
    inner endpoint must appear as a composite facade input port."""
    g = _three_node_graph()
    # Add an outside source feeding `adder.a`.
    g["nodes"].append({
        "id": "outside_src", "type": "_test.constant",
        "config": {"value": 9},
        "outs": [{"id": "value", "label": "value", "t": "number"}],
    })
    g["wires"][0] = {"from": ["outside_src", "value"], "to": ["adder", "a"]}
    # Also wire adder.sum out to a non-selected consumer.
    g["nodes"].append({
        "id": "downstream", "type": "_test.adder", "config": {},
        "ins":  [{"id": "a", "t": "number"}, {"id": "b", "t": "number"}],
        "outs": [{"id": "sum", "t": "number"}],
    })
    g["wires"].append({"from": ["adder", "sum"], "to": ["downstream", "a"]})

    new = subgraph.compose_subgraph(g, ["B", "adder"])
    composite = next(n for n in new["nodes"]
                       if n["type"] == "subgraph.user")
    cfg = composite["config"]

    # One input lifted (outside_src → adder.a), one output lifted
    # (adder.sum → downstream.a).
    assert len(cfg["inner_inputs"]) == 1
    assert cfg["inner_inputs"][0]["inner_node"] == "adder"
    assert cfg["inner_inputs"][0]["inner_port"] == "a"
    assert len(cfg["inner_outputs"]) == 1
    assert cfg["inner_outputs"][0]["inner_node"] == "adder"
    assert cfg["inner_outputs"][0]["inner_port"] == "sum"

    # Outer wires rewritten to terminate on the facade ports.
    facade_in  = cfg["inner_inputs"][0]["port"]
    facade_out = cfg["inner_outputs"][0]["port"]
    outer_wires = new["wires"]
    assert any(w for w in outer_wires
                 if w["from"] == ["outside_src", "value"]
                 and w["to"][0] == composite["id"]
                 and w["to"][1] == facade_in)
    assert any(w for w in outer_wires
                 if w["from"][0] == composite["id"]
                 and w["from"][1] == facade_out
                 and w["to"]   == ["downstream", "a"])


def test_compose_subgraph_rejects_empty_or_unknown_ids():
    g = _three_node_graph()
    with pytest.raises(ValueError):
        subgraph.compose_subgraph(g, [])
    with pytest.raises(ValueError):
        subgraph.compose_subgraph(g, ["A", "ghost"])


# ── expand_subgraph (inverse) ───────────────────────────────────────
def test_expand_subgraph_restores_inner_graph():
    g = _three_node_graph()
    composed = subgraph.compose_subgraph(g, ["A", "B", "adder"])
    composite_id = composed["nodes"][0]["id"]
    expanded = subgraph.expand_subgraph(composed, composite_id)

    # Same node count and same wire count.
    assert sorted(n["id"] for n in expanded["nodes"]) == ["A", "B", "adder"]
    wire_pairs = sorted([(w["from"][0], w["from"][1],
                           w["to"][0],   w["to"][1])
                          for w in expanded["wires"]])
    original_pairs = sorted([(w["from"][0], w["from"][1],
                                w["to"][0],   w["to"][1])
                              for w in g["wires"]])
    assert wire_pairs == original_pairs


def test_expand_subgraph_reconnects_outer_wires():
    g = _three_node_graph()
    g["nodes"].append({
        "id": "outside_src", "type": "_test.constant",
        "config": {"value": 9},
        "outs": [{"id": "value", "label": "value", "t": "number"}],
    })
    g["wires"][0] = {"from": ["outside_src", "value"], "to": ["adder", "a"]}
    composed = subgraph.compose_subgraph(g, ["B", "adder"])
    composite_id = next(n["id"] for n in composed["nodes"]
                         if n["type"] == "subgraph.user")
    expanded = subgraph.expand_subgraph(composed, composite_id)

    # The outer→inner wire should be reconnected to its original
    # destination, not to the composite.
    assert any(w["from"] == ["outside_src", "value"]
                 and w["to"] == ["adder", "a"]
                 for w in expanded["wires"])
    # No wire should reference the (now-gone) composite node.
    for w in expanded["wires"]:
        assert w["from"][0] != composite_id
        assert w["to"][0]   != composite_id


def test_expand_subgraph_rejects_non_subgraph_node():
    g = _three_node_graph()
    with pytest.raises(ValueError):
        subgraph.expand_subgraph(g, "A")
    with pytest.raises(ValueError):
        subgraph.expand_subgraph(g, "no_such_node")


# ── subgraph.user executor ──────────────────────────────────────────
def test_subgraph_user_executor_cooks_inner_graph():
    """A composite wrapping (B + adder) — A feeds the composite from
    outside, so the composite has one facade input + one facade output.
    Running the outer WorkflowRunner should yield 3 + 4 = 7."""
    g = _three_node_graph()
    g["nodes"].append({
        "id": "outside_src", "type": "_test.constant",
        "config": {"value": 3},
        "outs": [{"id": "value", "label": "value", "t": "number"}],
    })
    # Rewire A's role to be the outside source for adder.a; keep B as inner.
    g["wires"][0] = {"from": ["outside_src", "value"], "to": ["adder", "a"]}
    # Drop the now-redundant A node so the test stays focused.
    g["nodes"] = [n for n in g["nodes"] if n["id"] != "A"]
    # Also wire adder.sum out to a no-op sink so the composite has an
    # output port the test can assert against.
    g["nodes"].append({
        "id": "sink", "type": "_test.constant",
        "config": {"value": 0},
        "ins":  [{"id": "in", "t": "number"}],
        "outs": [{"id": "value", "label": "value", "t": "number"}],
    })
    g["wires"].append({"from": ["adder", "sum"], "to": ["sink", "in"]})

    composed = subgraph.compose_subgraph(g, ["B", "adder"])
    composite = next(n for n in composed["nodes"]
                       if n["type"] == "subgraph.user")

    runner = WorkflowRunner(composed)
    out = runner.pull(composite["id"])
    # The single facade output port maps to adder.sum.
    facade_out = composite["config"]["inner_outputs"][0]["port"]
    assert out.get("status") == "ok"
    assert out.get(facade_out) == 7.0


# ── add_wire (composer /wire equivalent) ────────────────────────────
def test_add_wire_appends_canvas_shape_wire():
    g = _three_node_graph()
    out = subgraph.add_wire(g, "A", "value", "adder", "b")
    # Original graph not mutated.
    assert len(g["wires"]) == 2
    # New wire appended.
    assert any(w["from"] == ["A", "value"] and w["to"] == ["adder", "b"]
                 for w in out["wires"])


def test_add_wire_is_idempotent():
    g = _three_node_graph()
    once = subgraph.add_wire(g, "A", "value", "adder", "a")
    twice = subgraph.add_wire(once, "A", "value", "adder", "a")
    assert len(once["wires"]) == len(twice["wires"])


def test_add_wire_rejects_unknown_node():
    g = _three_node_graph()
    with pytest.raises(ValueError):
        subgraph.add_wire(g, "ghost", "value", "adder", "a")


def test_parse_wire_endpoint_basic():
    assert subgraph.parse_wire_endpoint("host.revit.opened_doc") is None
    assert subgraph.parse_wire_endpoint("host_revit.opened_doc") == (
        "host_revit", "opened_doc")
    assert subgraph.parse_wire_endpoint("") is None
