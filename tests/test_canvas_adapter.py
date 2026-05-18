"""End-to-end test for the canvas->engine node adapter — slice 1B of
the node-system redesign (docs/NODE_GRAMMAR.md, the "one node model").

`node_grammar.normalize_canvas_graph` stamps the engine `type` +
`config` onto canvas-shaped nodes so `WorkflowRunner` can dispatch them.

The OLD model: canvas nodes carried `cat`, the runner dispatched on
`type` — 0 of 80 library nodes ever cooked. These tests prove a
canvas-shaped graph of new-grammar nodes now cooks a real value through
the REAL WorkflowRunner.
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


def test_normalize_stamps_type_and_config():
    graph = {
        "nodes": [
            {"id": "c1", "kind": "constant",
             "params": [{"k": "value", "v": 42}]},
            {"id": "o1", "kind": "output",
             "params": [{"k": "name", "v": "result"}]},
        ],
        "wires": [{"from": ["c1", "value"], "to": ["o1", "value"]}],
    }
    norm = ng.normalize_canvas_graph(graph)
    by_id = {n["id"]: n for n in norm["nodes"]}
    assert by_id["c1"]["type"] == "data.constant"
    assert by_id["c1"]["config"] == {"value": 42}
    assert by_id["o1"]["type"] == "output.parameter"
    assert by_id["o1"]["config"] == {"name": "result"}


def test_constant_to_output_graph_cooks_end_to_end():
    """THE proof: a canvas-shaped graph of new-grammar nodes cooks a
    real value through the real WorkflowRunner."""
    graph = {
        "nodes": [
            {"id": "c1", "kind": "constant",
             "params": [{"k": "value", "v": 42}]},
            {"id": "o1", "kind": "output",
             "params": [{"k": "name", "v": "result"}]},
        ],
        "wires": [{"from": ["c1", "value"], "to": ["o1", "value"]}],
    }
    runner = WorkflowRunner(ng.normalize_canvas_graph(graph))
    out = runner.pull("o1")
    assert out.get("value") == 42


def test_legacy_cat_node_resolves_when_category_matches_a_primitive():
    """A legacy node carrying `cat` (not `kind`) still resolves when its
    category name matches a grammar primitive."""
    graph = {"nodes": [{"id": "o1", "cat": "output", "params": []}],
             "wires": []}
    norm = ng.normalize_canvas_graph(graph)
    assert norm["nodes"][0]["type"] == "output.parameter"


def test_unmapped_node_left_typeless_and_runner_errors_honestly():
    """A node whose kind does not resolve is left without a `type`; the
    runner returns an honest error — never a fabricated result."""
    graph = {"nodes": [{"id": "x1", "kind": "nonsense", "params": []}],
             "wires": []}
    norm = ng.normalize_canvas_graph(graph)
    assert not norm["nodes"][0].get("type")
    out = WorkflowRunner(norm).pull("x1")
    assert out.get("status") == "error"
    assert "no executor" in out.get("error", "")


def test_selector_primitive_stamps_the_right_engine_type():
    """An `ai` node with action=chat resolves to conversation.chat; a
    `logic` node with kind=if resolves to control.if."""
    graph = {"nodes": [
        {"id": "a1", "kind": "ai",
         "params": [{"k": "action", "v": "chat"}]},
        {"id": "l1", "kind": "logic",
         "params": [{"k": "kind", "v": "if"}]},
    ], "wires": []}
    norm = ng.normalize_canvas_graph(graph)
    by_id = {n["id"]: n for n in norm["nodes"]}
    assert by_id["a1"]["type"] == "conversation.chat"
    assert by_id["l1"]["type"] == "control.if"


def test_engine_native_node_with_type_is_left_untouched():
    """A node already carrying a real engine `type` passes through."""
    graph = {"nodes": [{"id": "n1", "type": "data.constant",
                         "config": {"value": 7}}], "wires": []}
    norm = ng.normalize_canvas_graph(graph)
    assert norm["nodes"][0]["type"] == "data.constant"
    assert norm["nodes"][0]["config"] == {"value": 7}


def test_normalize_does_not_mutate_input():
    graph = {"nodes": [{"id": "c1", "kind": "constant",
                         "params": [{"k": "value", "v": 1}]}],
             "wires": []}
    ng.normalize_canvas_graph(graph)
    assert "type" not in graph["nodes"][0]    # original untouched


def test_trigger_executor_emits_event():
    """trigger.emit — the graph entry-point node: emits a fire event
    (kind + timestamp), passes `value` through."""
    from workflows.nodes.trigger import _trigger_executor
    out = _trigger_executor({"on": "manual"}, {"value": 7}, None)
    assert out["event"]["on"] == "manual"
    assert isinstance(out["event"]["ts"], int)
    assert out["value"] == 7
    assert workflows.get("trigger.emit") is not None


def test_switch_executor_routes_by_equality():
    """control.switch — the `logic` primitive's switch op: routes value
    to `match` on equality with `case`, else `default`."""
    from workflows.nodes.control import _switch_executor
    m = _switch_executor({"case": "wall"}, {"value": "wall"}, None)
    assert m["match"] == "wall" and m["default"] is None and m["taken"] == "match"
    d = _switch_executor({"case": "wall"}, {"value": "door"}, None)
    assert d["match"] is None and d["default"] == "door" and d["taken"] == "default"
    # registered + grammar-resolvable
    assert workflows.get("control.switch") is not None


def test_params_to_config_handles_list_and_dict():
    assert ng._params_to_config(
        [{"k": "a", "v": 1}, {"k": "b", "v": 2}]) == {"a": 1, "b": 2}
    assert ng._params_to_config({"a": 1}) == {"a": 1}
    assert ng._params_to_config(None) == {}


def test_connector_node_cooks_and_reports_honestly():
    """A `connector` node resolves to connector.run and runs through the
    connector contract. With no host process reachable the op returns an
    honest failure — never a crash, never a fabricated value (slice 2)."""
    graph = {"nodes": [
        {"id": "k1", "kind": "connector",
         "params": [{"k": "host", "v": "excel"},
                    {"k": "op", "v": "excel.read_range"}]},
    ], "wires": []}
    norm = ng.normalize_canvas_graph(graph)
    assert norm["nodes"][0]["type"] == "connector.run"
    out = WorkflowRunner(norm).pull("k1")
    assert isinstance(out, dict)
    # Either it ran (value present) or it failed honestly — never a crash.
    assert "value" in out or out.get("status") == "error"
