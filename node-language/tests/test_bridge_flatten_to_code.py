"""Bridge slot `flatten_chain_to_code` — SLICE L (AgDR-0020) JSX
entry-point.

The JSX context-menu calls this slot with (graph_json, node_ids_json).
Slot returns JSON: success → `{graph, new_node_id, expression}`;
failure → `{error}`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

# Import the bridge module + a helper to construct a stub bridge that
# doesn't need a Qt event loop.
import workflows.nodes  # noqa: F401, E402 — register engines


@pytest.fixture
def bridge():
    # Import lazily so PyQt isn't required just to load this file.
    from bridge import ArchHubBridge
    return ArchHubBridge()


def test_flatten_bridge_slot_returns_rewritten_graph(bridge):
    """Happy path: an add op selected → bridge returns the new graph
    with one code.expression node + the externals re-wired."""
    graph = {
        "nodes": [
            {"id": "x", "type": "data.constant", "config": {"value": 5}},
            {"id": "y", "type": "data.constant", "config": {"value": 3}},
            {"id": "add", "type": "math.op", "config": {"op": "add"}},
        ],
        "wires": [
            {"from": ["x", "value"], "to": ["add", "a"]},
            {"from": ["y", "value"], "to": ["add", "b"]},
        ],
    }
    raw = bridge.flatten_chain_to_code(
        json.dumps(graph), json.dumps(["add"]))
    result = json.loads(raw)
    assert "error" not in result, result
    assert result["new_node_id"]
    assert "+" in result["expression"]
    # The new graph has the code node + the two constants.
    new_ids = {n["id"] for n in result["graph"]["nodes"]}
    assert result["new_node_id"] in new_ids
    assert "add" not in new_ids
    assert {"x", "y"} <= new_ids


def test_flatten_bridge_slot_returns_error_on_empty_selection(bridge):
    raw = bridge.flatten_chain_to_code(json.dumps({"nodes": [], "wires": []}),
                                          json.dumps([]))
    assert "error" in json.loads(raw)


def test_flatten_bridge_slot_returns_error_on_bad_json(bridge):
    raw = bridge.flatten_chain_to_code("not valid json", "[]")
    result = json.loads(raw)
    assert "error" in result
    # JSON parse error surfaces as the typed error.
    assert any(token in result["error"].lower()
                for token in ("json", "expecting", "parse"))


def test_flatten_bridge_slot_returns_error_on_non_list_ids(bridge):
    raw = bridge.flatten_chain_to_code(
        json.dumps({"nodes": [], "wires": []}),
        json.dumps({"not": "a list"}))
    result = json.loads(raw)
    assert "error" in result
    assert "array" in result["error"].lower()


def test_flatten_bridge_slot_returns_error_on_non_object_graph(bridge):
    raw = bridge.flatten_chain_to_code(json.dumps([1, 2, 3]),
                                          json.dumps([]))
    result = json.loads(raw)
    assert "error" in result
    assert "object" in result["error"].lower()


def test_flatten_bridge_slot_unflattenable_type_surfaces_error(bridge):
    """An unflattenable type → error from the underlying util."""
    graph = {
        "nodes": [
            {"id": "chat", "type": "conversation.chat", "config": {}},
        ],
        "wires": [],
    }
    raw = bridge.flatten_chain_to_code(
        json.dumps(graph), json.dumps(["chat"]))
    result = json.loads(raw)
    assert "error" in result
    assert "flattenable" in result["error"]


def test_flatten_bridge_slot_runner_equivalence(bridge):
    """Bridge result graph cooks to the same value as the original
    chain — end-to-end through bridge + runner."""
    from workflows.runner import WorkflowRunner
    from workflows.node_grammar import normalize_canvas_graph

    original = {
        "nodes": [
            {"id": "a", "type": "data.constant", "config": {"value": 8}},
            {"id": "b", "type": "data.constant", "config": {"value": 2}},
            {"id": "k3", "type": "data.constant", "config": {"value": 3}},
            {"id": "mul", "type": "math.op", "config": {"op": "mul"}},
            {"id": "add", "type": "math.op", "config": {"op": "add"}},
            {"id": "out", "type": "data.passthrough", "config": {}},
        ],
        "wires": [
            {"from": ["a", "value"], "to": ["mul", "a"]},
            {"from": ["b", "value"], "to": ["mul", "b"]},
            {"from": ["mul", "value"], "to": ["add", "a"]},
            {"from": ["k3", "value"], "to": ["add", "b"]},
            {"from": ["add", "value"], "to": ["out", "value"]},
        ],
    }
    raw = bridge.flatten_chain_to_code(
        json.dumps(original), json.dumps(["mul", "add", "k3"]))
    result = json.loads(raw)
    assert "error" not in result, result
    new_graph = result["graph"]

    def cook(g):
        return WorkflowRunner(normalize_canvas_graph(g)).run_all()

    # (8 * 2) + 3 = 19
    assert cook(original)["results"]["out"]["value"] == 19
    assert cook(new_graph)["results"]["out"]["value"] == 19
