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
from types import SimpleNamespace
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


def test_node_native_wire_graph_normalizes_to_runtime_edges():
    graph = {
        "nodes": [
            {"id": "c1", "kind": "constant",
             "params": [{"k": "value", "v": 42}]},
            {"id": "o1", "kind": "output",
             "params": [{"k": "name", "v": "result"}]},
            {"id": "param:c1:port-out-value", "kind": "param",
             "data": {"role": "parameter", "param_family": "port",
                      "owner": "c1", "port_direction": "out",
                      "port_id": "value"}},
            {"id": "param:o1:port-in-value", "kind": "param",
             "data": {"role": "parameter", "param_family": "port",
                      "owner": "o1", "port_direction": "in",
                      "port_id": "value"}},
            {"id": "wire:c1-o1", "kind": "wire", "data": {
                "role": "wire",
                "wire_family": "workflow_wire",
                "wire_id": "edge:c1-o1",
                "source_owner": "c1",
                "target_owner": "o1",
                "from_node": "c1",
                "from_port": "value",
                "to_node": "o1",
                "to_port": "value",
                "from_port_node": "param:c1:port-out-value",
                "to_port_node": "param:o1:port-in-value",
                "wire_layers": [
                    "type", "gate", "codec", "behavior",
                    "presentation", "provenance",
                ],
                "value_type": "number",
                "gate_policy": "type-compatible-and-enabled",
            }},
            {"id": "wire:c1-o1:layer:gate", "kind": "group", "data": {
                "role": "wire_layer",
                "wire_family": "workflow_wire",
                "owner": "wire:c1-o1",
                "layer": "gate",
                "value_key": "gate_policy",
                "value": "type-compatible-and-enabled",
            }},
            {"id": "param:wire:c1-o1:layer:gate:value", "kind": "param",
             "data": {"role": "parameter",
                      "owner": "wire:c1-o1:layer:gate",
                      "key": "value",
                      "value": "type-compatible-and-enabled"}},
        ],
        "wires": [
            {"id": "edge:c1-o1",
             "from": ["c1", "value"], "to": ["o1", "value"],
             "data": {"presentation_edge": True,
                      "relation_node": "wire:c1-o1"}},
            {"id": "w:param:c1->param:c1:port-out-value",
             "from": ["c1", "param:port-out-value"],
             "to": ["param:c1:port-out-value", "owner"]},
            {"id": "w:workflow-wire-endpoint:wire-c1-o1:from",
             "from": ["param:c1:port-out-value", "value"],
             "to": ["wire:c1-o1", "from"],
             "data": {"role": "wire_endpoint",
                      "wire_family": "workflow_wire"}},
            {"id": "w:workflow-wire-endpoint:wire-c1-o1:to",
             "from": ["wire:c1-o1", "to"],
             "to": ["param:o1:port-in-value", "owner"],
             "data": {"role": "wire_endpoint",
                      "wire_family": "workflow_wire"}},
            {"id": "w:workflow-wire-layer:wire-c1-o1:gate",
             "from": ["wire:c1-o1", "layer"],
             "to": ["wire:c1-o1:layer:gate", "owner"],
             "data": {"role": "wire_layer_link",
                      "wire_family": "workflow_wire",
                      "relation_node": "wire:c1-o1",
                      "layer_node": "wire:c1-o1:layer:gate"}},
        ],
    }

    norm = ng.normalize_canvas_graph(graph)

    assert {n["id"] for n in norm["nodes"]} == {"c1", "o1"}
    assert norm["wires"] == [
        {"id": "edge:c1-o1", "from": ["c1", "value"],
         "to": ["o1", "value"],
         "wire_node": "wire:c1-o1",
         "value_type": "number",
         "gate_policy": "type-compatible-and-enabled"}
    ]
    out = WorkflowRunner(norm).pull("o1")
    assert out.get("value") == 42


def test_node_native_wire_endpoint_port_nodes_are_runtime_authority():
    graph = {
        "nodes": [
            {"id": "c1", "kind": "constant",
             "params": [{"k": "value", "v": 42}]},
            {"id": "o1", "kind": "output",
             "params": [{"k": "name", "v": "result"}]},
            {"id": "param:c1:port-out-alt", "kind": "param",
             "data": {"role": "parameter", "param_family": "port",
                      "owner": "c1", "port_direction": "out",
                      "port_id": "alt"}},
            {"id": "param:o1:port-in-payload", "kind": "param",
             "data": {"role": "parameter", "param_family": "port",
                      "owner": "o1", "port_direction": "in",
                      "port_id": "payload"}},
            {"id": "wire:c1-o1", "kind": "wire", "data": {
                "role": "wire",
                "wire_family": "workflow_wire",
                "wire_id": "edge:c1-o1",
                "source_owner": "c1",
                "target_owner": "o1",
                "from_node": "c1",
                "from_port": "value",
                "to_node": "o1",
                "to_port": "value",
                "from_port_node": "param:c1:port-out-alt",
                "to_port_node": "param:o1:port-in-payload",
            }},
        ],
        "wires": [],
    }

    norm = ng.normalize_canvas_graph(graph)

    assert norm["wires"] == [
        {"id": "edge:c1-o1", "from": ["c1", "alt"],
         "to": ["o1", "payload"],
         "wire_node": "wire:c1-o1"}
    ]


def test_node_native_wire_gate_layer_blocks_runtime_flow():
    graph = {
        "nodes": [
            {"id": "c1", "kind": "constant",
             "params": [{"k": "value", "v": 42}]},
            {"id": "o1", "kind": "output",
             "params": [{"k": "name", "v": "result"}]},
            {"id": "wire:c1-o1", "kind": "wire", "data": {
                "role": "wire",
                "wire_family": "workflow_wire",
                "wire_id": "edge:c1-o1",
                "source_owner": "c1",
                "target_owner": "o1",
                "from_node": "c1",
                "from_port": "value",
                "to_node": "o1",
                "to_port": "value",
                "gate_policy": "type-compatible-and-enabled",
                "layer_nodes": {"gate": "wire:c1-o1:layer:gate"},
            }},
            {"id": "wire:c1-o1:layer:gate", "kind": "group", "data": {
                "role": "wire_layer",
                "wire_family": "workflow_wire",
                "owner": "wire:c1-o1",
                "layer": "gate",
                "value_key": "gate_policy",
                "value": "deny",
            }},
        ],
        "wires": [],
    }

    norm = ng.normalize_canvas_graph(graph)
    assert norm["wires"] == [
        {"id": "edge:c1-o1", "from": ["c1", "value"],
         "to": ["o1", "value"],
         "wire_node": "wire:c1-o1",
         "gate_policy": "deny"}
    ]
    runner = WorkflowRunner(norm)
    out = runner.pull("o1")

    assert out.get("value") is None
    assert runner.wire_state("edge:c1-o1") == "blocked"
    assert runner.wire_value("edge:c1-o1") is None


def test_node_native_wire_codec_and_encryption_layers_drive_runtime_transport():
    from cryptography.fernet import Fernet

    key = Fernet.generate_key()
    graph = {
        "nodes": [
            {"id": "c1", "kind": "constant",
             "params": [{"k": "value", "v": {"secret": "facade option"}}]},
            {"id": "o1", "kind": "output",
             "params": [{"k": "name", "v": "result"}]},
            {"id": "wire:c1-o1", "kind": "wire", "data": {
                "role": "wire",
                "wire_family": "workflow_wire",
                "wire_id": "edge:c1-o1",
                "source_owner": "c1",
                "target_owner": "o1",
                "from_node": "c1",
                "from_port": "value",
                "to_node": "o1",
                "to_port": "value",
                "layer_nodes": {
                    "codec": "wire:c1-o1:layer:codec",
                    "encryption": "wire:c1-o1:layer:encryption",
                },
            }},
            {"id": "wire:c1-o1:layer:codec", "kind": "group", "data": {
                "role": "wire_layer",
                "wire_family": "workflow_wire",
                "owner": "wire:c1-o1",
                "layer": "codec",
                "value_key": "codec",
                "value": "json",
            }},
            {"id": "wire:c1-o1:layer:encryption", "kind": "group", "data": {
                "role": "wire_layer",
                "wire_family": "workflow_wire",
                "owner": "wire:c1-o1",
                "layer": "encryption",
                "value_key": "encryption",
                "value": "fernet",
            }},
        ],
        "wires": [],
    }

    norm = ng.normalize_canvas_graph(graph)
    assert norm["wires"] == [
        {"id": "edge:c1-o1", "from": ["c1", "value"],
         "to": ["o1", "value"],
         "wire_node": "wire:c1-o1",
         "codec": "json",
         "encryption": "fernet"}
    ]
    runner = WorkflowRunner(norm, ctx=SimpleNamespace(wire_fernet_key=key))
    out = runner.pull("o1")
    carried = runner.wire_value("edge:c1-o1")

    assert out.get("value") == {"secret": "facade option"}
    assert carried["encrypted"] is True
    assert carried["codec"] == "json"
    assert "facade option" not in carried["token"]


def test_node_native_wire_behavior_layer_reaches_runtime_edge():
    graph = {
        "nodes": [
            {"id": "c1", "kind": "constant",
             "params": [{"k": "value", "v": 42}]},
            {"id": "o1", "kind": "output",
             "params": [{"k": "name", "v": "result"}]},
            {"id": "wire:c1-o1", "kind": "wire", "data": {
                "role": "wire",
                "wire_family": "workflow_wire",
                "wire_id": "edge:c1-o1",
                "source_owner": "c1",
                "target_owner": "o1",
                "from_node": "c1",
                "from_port": "value",
                "to_node": "o1",
                "to_port": "value",
                "layer_nodes": {
                    "behavior": "wire:c1-o1:layer:behavior",
                },
            }},
            {"id": "wire:c1-o1:layer:behavior", "kind": "group", "data": {
                "role": "wire_layer",
                "wire_family": "workflow_wire",
                "owner": "wire:c1-o1",
                "layer": "behavior",
                "value_key": "behavior",
                "value": "force-recook",
            }},
        ],
        "wires": [],
    }

    norm = ng.normalize_canvas_graph(graph)

    assert norm["wires"] == [
        {"id": "edge:c1-o1", "from": ["c1", "value"],
         "to": ["o1", "value"],
         "wire_node": "wire:c1-o1",
         "behavior": "force-recook"}
    ]


def test_node_native_wire_schema_layer_reaches_runtime_edge():
    graph = {
        "nodes": [
            {"id": "c1", "kind": "constant",
             "params": [{"k": "value", "v": {"mesh": "facade"}}]},
            {"id": "o1", "kind": "output",
             "params": [{"k": "name", "v": "result"}]},
            {"id": "wire:c1-o1", "kind": "wire", "data": {
                "role": "wire",
                "wire_family": "workflow_wire",
                "wire_id": "edge:c1-o1",
                "source_owner": "c1",
                "target_owner": "o1",
                "from_node": "c1",
                "from_port": "value",
                "to_node": "o1",
                "to_port": "value",
                "layer_nodes": {
                    "schema": "wire:c1-o1:layer:schema",
                },
            }},
            {"id": "wire:c1-o1:layer:schema", "kind": "group", "data": {
                "role": "wire_layer",
                "wire_family": "workflow_wire",
                "owner": "wire:c1-o1",
                "layer": "schema",
                "value_key": "schema_ref",
                "value": "archhub.geometry.mesh",
            }},
        ],
        "wires": [],
    }

    norm = ng.normalize_canvas_graph(graph)

    assert norm["wires"] == [
        {"id": "edge:c1-o1", "from": ["c1", "value"],
         "to": ["o1", "value"],
         "wire_node": "wire:c1-o1",
         "schema_ref": "archhub.geometry.mesh"}
    ]


def test_node_native_wire_port_and_field_layers_are_runtime_authority():
    graph = {
        "nodes": [
            {"id": "c1", "kind": "constant",
             "params": [{"k": "value", "v": {"items": [1, 2, 3]}}]},
            {"id": "o1", "kind": "output",
             "params": [{"k": "name", "v": "result"}]},
            {"id": "wire:c1-o1", "kind": "wire", "data": {
                "role": "wire",
                "wire_family": "workflow_wire",
                "wire_id": "edge:c1-o1",
                "source_owner": "c1",
                "target_owner": "o1",
                "from_node": "c1",
                "from_port": "value",
                "to_node": "o1",
                "to_port": "value",
                "layer_nodes": {
                    "source_port": "wire:c1-o1:layer:source-port",
                    "target_port": "wire:c1-o1:layer:target-port",
                    "source_field": "wire:c1-o1:layer:source-field",
                    "target_field": "wire:c1-o1:layer:target-field",
                },
            }},
            {"id": "wire:c1-o1:layer:source-port", "kind": "group", "data": {
                "role": "wire_layer",
                "wire_family": "workflow_wire",
                "owner": "wire:c1-o1",
                "layer": "source_port",
                "value_key": "from_port",
                "value": "alt",
            }},
            {"id": "wire:c1-o1:layer:target-port", "kind": "group", "data": {
                "role": "wire_layer",
                "wire_family": "workflow_wire",
                "owner": "wire:c1-o1",
                "layer": "target_port",
                "value_key": "to_port",
                "value": "payload",
            }},
            {"id": "wire:c1-o1:layer:source-field", "kind": "group", "data": {
                "role": "wire_layer",
                "wire_family": "workflow_wire",
                "owner": "wire:c1-o1",
                "layer": "source_field",
                "value_key": "src_field",
                "value": "items[0]",
            }},
            {"id": "wire:c1-o1:layer:target-field", "kind": "group", "data": {
                "role": "wire_layer",
                "wire_family": "workflow_wire",
                "owner": "wire:c1-o1",
                "layer": "target_field",
                "value_key": "dst_field",
                "value": "payload.first",
            }},
        ],
        "wires": [],
    }

    norm = ng.normalize_canvas_graph(graph)

    assert norm["wires"] == [
        {"id": "edge:c1-o1", "from": ["c1", "alt"],
         "to": ["o1", "payload"],
         "wire_node": "wire:c1-o1",
         "src_field": "items[0]",
         "dst_field": "payload.first"}
    ]


def test_node_native_wire_layer_parameter_nodes_are_runtime_authority():
    graph = {
        "nodes": [
            {"id": "c1", "kind": "constant",
             "params": [{"k": "value", "v": {"items": [1, 2, 3]}}]},
            {"id": "o1", "kind": "output",
             "params": [{"k": "name", "v": "result"}]},
            {"id": "wire:c1-o1", "kind": "wire", "data": {
                "role": "wire",
                "wire_family": "workflow_wire",
                "wire_id": "edge:c1-o1",
                "source_owner": "c1",
                "target_owner": "o1",
                "from_node": "c1",
                "from_port": "value",
                "to_node": "o1",
                "to_port": "value",
                "layer_nodes": {
                    "behavior": "wire:c1-o1:layer:behavior",
                    "source_port": "wire:c1-o1:layer:source-port",
                    "target_port": "wire:c1-o1:layer:target-port",
                    "source_field": "wire:c1-o1:layer:source-field",
                    "target_field": "wire:c1-o1:layer:target-field",
                },
            }},
            {"id": "wire:c1-o1:layer:behavior", "kind": "group", "data": {
                "role": "wire_layer",
                "wire_family": "workflow_wire",
                "owner": "wire:c1-o1",
                "layer": "behavior",
                "value_key": "behavior",
                "value": "data-flow",
            }},
            {"id": "wire:c1-o1:layer:source-port", "kind": "group", "data": {
                "role": "wire_layer",
                "wire_family": "workflow_wire",
                "owner": "wire:c1-o1",
                "layer": "source_port",
                "value_key": "from_port",
                "value": "value",
            }},
            {"id": "wire:c1-o1:layer:target-port", "kind": "group", "data": {
                "role": "wire_layer",
                "wire_family": "workflow_wire",
                "owner": "wire:c1-o1",
                "layer": "target_port",
                "value_key": "to_port",
                "value": "value",
            }},
            {"id": "wire:c1-o1:layer:source-field", "kind": "group", "data": {
                "role": "wire_layer",
                "wire_family": "workflow_wire",
                "owner": "wire:c1-o1",
                "layer": "source_field",
                "value_key": "src_field",
                "value": "stale.path",
            }},
            {"id": "wire:c1-o1:layer:target-field", "kind": "group", "data": {
                "role": "wire_layer",
                "wire_family": "workflow_wire",
                "owner": "wire:c1-o1",
                "layer": "target_field",
                "value_key": "dst_field",
                "value": "stale.target",
            }},
            {"id": "param:wire:c1-o1:layer:behavior:value", "kind": "param",
             "data": {"role": "parameter",
                      "owner": "wire:c1-o1:layer:behavior",
                      "key": "value",
                      "value": "force-recook"}},
            {"id": "param:wire:c1-o1:layer:source-port:value", "kind": "param",
             "data": {"role": "parameter",
                      "owner": "wire:c1-o1:layer:source-port",
                      "key": "value",
                      "value": "alt"}},
            {"id": "param:wire:c1-o1:layer:target-port:value", "kind": "param",
             "data": {"role": "parameter",
                      "owner": "wire:c1-o1:layer:target-port",
                      "key": "value",
                      "value": "payload"}},
            {"id": "param:wire:c1-o1:layer:source-field:value", "kind": "param",
             "data": {"role": "parameter",
                      "owner": "wire:c1-o1:layer:source-field",
                      "key": "value",
                      "value": "items[0]"}},
            {"id": "param:wire:c1-o1:layer:target-field:value", "kind": "param",
             "data": {"role": "parameter",
                      "owner": "wire:c1-o1:layer:target-field",
                      "key": "value",
                      "value": "payload.first"}},
        ],
        "wires": [],
    }

    norm = ng.normalize_canvas_graph(graph)

    assert norm["wires"] == [
        {"id": "edge:c1-o1", "from": ["c1", "alt"],
         "to": ["o1", "payload"],
         "wire_node": "wire:c1-o1",
         "src_field": "items[0]",
         "dst_field": "payload.first",
         "behavior": "force-recook"}
    ]


def test_node_native_wire_parameter_nodes_override_wire_body_values():
    graph = {
        "nodes": [
            {"id": "c1", "kind": "constant",
             "params": [{"k": "value", "v": 42}]},
            {"id": "o1", "kind": "output",
             "params": [{"k": "name", "v": "result"}]},
            {"id": "wire:c1-o1", "kind": "wire", "data": {
                "role": "wire",
                "wire_family": "workflow_wire",
                "wire_id": "edge:c1-o1",
                "source_owner": "c1",
                "target_owner": "o1",
                "from_node": "c1",
                "from_port": "value",
                "to_node": "o1",
                "to_port": "value",
                "behavior": "data-flow",
            }},
            {"id": "param:wire:c1-o1:from_port", "kind": "param",
             "data": {"role": "parameter",
                      "owner": "wire:c1-o1",
                      "key": "from_port",
                      "value": "alt"}},
            {"id": "param:wire:c1-o1:to_port", "kind": "param",
             "data": {"role": "parameter",
                      "owner": "wire:c1-o1",
                      "key": "to_port",
                      "value": "payload"}},
            {"id": "param:wire:c1-o1:behavior", "kind": "param",
             "data": {"role": "parameter",
                      "owner": "wire:c1-o1",
                      "key": "behavior",
                      "value": "force-recook"}},
        ],
        "wires": [],
    }

    norm = ng.normalize_canvas_graph(graph)

    assert norm["wires"] == [
        {"id": "edge:c1-o1", "from": ["c1", "alt"],
         "to": ["o1", "payload"],
         "wire_node": "wire:c1-o1",
         "behavior": "force-recook"}
    ]


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


def test_parameter_node_overrides_inline_node_config_at_runtime():
    graph = {
        "nodes": [
            {"id": "c1", "kind": "constant",
             "params": [{"k": "value", "v": 1}]},
            {"id": "param:c1:value", "kind": "param",
             "data": {"role": "parameter",
                      "owner": "c1",
                      "key": "value",
                      "value": 99}},
            {"id": "o1", "kind": "output",
             "params": [{"k": "name", "v": "result"}]},
        ],
        "wires": [{"from": ["c1", "value"], "to": ["o1", "value"]}],
    }

    norm = ng.normalize_canvas_graph(graph)

    assert {n["id"] for n in norm["nodes"]} == {"c1", "o1"}
    c1 = next(n for n in norm["nodes"] if n["id"] == "c1")
    assert c1["config"]["value"] == 99
    assert WorkflowRunner(norm).pull("o1")["value"] == 99


def test_parameter_node_overrides_engine_native_config_at_runtime():
    graph = {
        "nodes": [
            {"id": "c1", "type": "data.constant",
             "config": {"value": 1}},
            {"id": "param:c1:value", "kind": "param",
             "data": {"role": "parameter",
                      "owner": "c1",
                      "key": "value",
                      "value": 123}},
        ],
        "wires": [],
    }

    norm = ng.normalize_canvas_graph(graph)

    assert norm["nodes"] == [
        {"id": "c1", "type": "data.constant", "config": {"value": 123}}
    ]
    assert WorkflowRunner(norm).pull("c1")["value"] == 123


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
    to `match` on equality with `case`, else `default`.

    The bespoke ``_switch_executor`` was RETIRED in the wave-4 in-place
    stem-cell rebuild (control.switch is now ``impl.kind=graph`` — a
    passthrough + a ``data.coalesce`` config-fallback cell + ``code.expression``
    gates; see ``tests/test_rebuild_in_place_parity.py``). So this resolves the
    LIVE registered executor from the registry — the SAME
    ``(config, inputs, ctx) -> outputs`` callable the WorkflowRunner invokes —
    rather than importing the deleted function. The routing contract it asserts
    is unchanged (equality on `case` from config → `match`, else `default`)."""
    hit = workflows.get("control.switch")
    assert hit is not None          # registered + grammar-resolvable
    _spec, switch_exec = hit
    m = switch_exec({"case": "wall"}, {"value": "wall"}, None)
    assert m["match"] == "wall" and m["default"] is None and m["taken"] == "match"
    d = switch_exec({"case": "wall"}, {"value": "door"}, None)
    assert d["match"] is None and d["default"] == "door" and d["taken"] == "default"


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


# ── Slice B (AgDR-0002): disable verbs as graph rewriting ──────────────

def test_pinned_node_replaced_with_constant_snapshot():
    """A node with `pinned=True, pinned_value=X` is rewritten to a
    `data.constant` of X — the node returns the snapshot without
    dispatching to its original executor (AgDR-0002 §Engine semantics)."""
    graph = {"nodes": [
        {"id": "p1", "kind": "ai",
         "params": [{"k": "action", "v": "chat"}],
         "pinned": True, "pinned_value": "cached reply"},
    ], "wires": []}
    norm = ng.normalize_canvas_graph(graph)
    n = norm["nodes"][0]
    assert n["type"] == "data.constant"
    assert n["config"] == {"value": "cached reply"}


def test_pinned_node_cooks_snapshot_end_to_end():
    """End-to-end: pinned ai node → output → runner returns the pinned
    value (no LLM call, no network)."""
    graph = {"nodes": [
        {"id": "p1", "kind": "ai",
         "params": [{"k": "action", "v": "chat"}],
         "pinned": True, "pinned_value": "snapshot"},
        {"id": "o1", "kind": "output",
         "params": [{"k": "name", "v": "result"}]},
    ], "wires": [{"from": ["p1", "value"], "to": ["o1", "value"]}]}
    out = WorkflowRunner(ng.normalize_canvas_graph(graph)).pull("o1")
    assert out.get("value") == "snapshot"


def test_frozen_node_with_cooked_returns_cache():
    """A node with `frozen=True` and a cached `cooked.value` is
    rewritten to a `data.constant` of the cached value."""
    graph = {"nodes": [
        {"id": "f1", "kind": "ai",
         "params": [{"k": "action", "v": "chat"}],
         "frozen": True, "cooked": {"value": "from cache"}},
        {"id": "o1", "kind": "output",
         "params": [{"k": "name", "v": "result"}]},
    ], "wires": [{"from": ["f1", "value"], "to": ["o1", "value"]}]}
    norm = ng.normalize_canvas_graph(graph)
    assert norm["nodes"][0]["type"] == "data.constant"
    out = WorkflowRunner(norm).pull("o1")
    assert out.get("value") == "from cache"


def test_frozen_node_without_cooked_falls_through():
    """`frozen=True` with no cached value falls through to the node's
    normal type resolution (runs as if not frozen, until the first
    successful cook)."""
    graph = {"nodes": [
        {"id": "c1", "kind": "constant", "frozen": True,
         "params": [{"k": "value", "v": 42}]},
    ], "wires": []}
    norm = ng.normalize_canvas_graph(graph)
    # frozen-with-no-cooked is a no-op — type resolves to constant kind.
    assert norm["nodes"][0]["type"] == "data.constant"
    assert norm["nodes"][0]["config"] == {"value": 42}


def test_pin_wins_over_freeze():
    """When both pinned AND frozen are set on the same node, pinned
    wins — the pinned_value is used, not the cooked cache."""
    graph = {"nodes": [
        {"id": "n1", "kind": "ai",
         "params": [{"k": "action", "v": "chat"}],
         "pinned": True, "pinned_value": "pin",
         "frozen": True, "cooked": {"value": "cache"}},
    ], "wires": []}
    norm = ng.normalize_canvas_graph(graph)
    assert norm["nodes"][0]["config"] == {"value": "pin"}


def test_bypassed_node_is_dropped_and_wires_rewired():
    """A bypassed middle node is removed and the wire from its
    upstream is rewired directly to its downstream."""
    graph = {"nodes": [
        {"id": "c1", "kind": "constant",
         "params": [{"k": "value", "v": 7}]},
        {"id": "m1", "kind": "transform", "bypass": True,
         "params": [{"k": "op", "v": "identity"}]},
        {"id": "o1", "kind": "output",
         "params": [{"k": "name", "v": "result"}]},
    ], "wires": [
        {"from": ["c1", "value"], "to": ["m1", "value"]},
        {"from": ["m1", "value"], "to": ["o1", "value"]},
    ]}
    norm = ng.normalize_canvas_graph(graph)
    ids = {n["id"] for n in norm["nodes"]}
    assert "m1" not in ids
    assert ids == {"c1", "o1"}
    # A wire from c1 directly to o1 must exist after the rewrite.
    rewired = any(
        (w.get("from", [None, None])[0] == "c1"
         and w.get("to", [None, None])[0] == "o1")
        for w in norm["wires"])
    assert rewired


def test_bypassed_graph_cooks_end_to_end():
    """End-to-end: constant(7) → transform(bypass) → output cooks 7
    because the bypassed middle node is removed and the wire is
    rewired upstream-to-downstream."""
    graph = {"nodes": [
        {"id": "c1", "kind": "constant",
         "params": [{"k": "value", "v": 7}]},
        {"id": "m1", "kind": "transform", "bypass": True,
         "params": [{"k": "op", "v": "identity"}]},
        {"id": "o1", "kind": "output",
         "params": [{"k": "name", "v": "result"}]},
    ], "wires": [
        {"from": ["c1", "value"], "to": ["m1", "value"]},
        {"from": ["m1", "value"], "to": ["o1", "value"]},
    ]}
    out = WorkflowRunner(ng.normalize_canvas_graph(graph)).pull("o1")
    assert out.get("value") == 7


def test_disable_verbs_default_absent_is_no_op():
    """Nodes without any disable flag normalise exactly as before —
    backward-compatible with saved graphs predating slice B."""
    graph = {"nodes": [
        {"id": "c1", "kind": "constant",
         "params": [{"k": "value", "v": 1}]},
    ], "wires": []}
    norm = ng.normalize_canvas_graph(graph)
    assert norm["nodes"][0]["type"] == "data.constant"
    # No bypass/freeze/pin fields → still absent (we don't synthesise).
    assert "bypass" not in norm["nodes"][0]
    assert "frozen" not in norm["nodes"][0]
    assert "pinned" not in norm["nodes"][0]


def test_preview_off_is_engine_no_op():
    """`preview_off=True` is UI-only — the engine still runs the node.
    The normalised type/config are unchanged from the un-flagged case."""
    graph = {"nodes": [
        {"id": "c1", "kind": "constant", "preview_off": True,
         "params": [{"k": "value", "v": 9}]},
    ], "wires": []}
    norm = ng.normalize_canvas_graph(graph)
    assert norm["nodes"][0]["type"] == "data.constant"
    assert norm["nodes"][0]["config"] == {"value": 9}


def test_capabilities_are_open_ended_and_not_a_closed_kind_catalogue():
    node = {
        "id": "n1",
        "kind": "constant",
        "data": {
            "capabilities": [
                "relation",
                "geometry-carrier",
                "encrypted-transport",
                "founder-defined-later",
            ]
        },
    }

    assert ng.node_capabilities(node) == frozenset({
        "relation",
        "geometry-carrier",
        "encrypted-transport",
        "founder-defined-later",
    })


def test_any_node_with_relation_capability_drives_runtime_without_wire_role():
    graph = {
        "nodes": [
            {"id": "c1", "kind": "constant",
             "params": [{"k": "value", "v": 42}]},
            {"id": "o1", "kind": "output",
             "params": [{"k": "name", "v": "result"}]},
            {"id": "port:c1:out", "kind": "constant", "data": {
                "capabilities": ["parameter", "port"],
                "owner": "c1",
                "port_direction": "out",
                "port_id": "value",
            }},
            {"id": "port:o1:in", "kind": "constant", "data": {
                "capabilities": ["parameter", "port"],
                "owner": "o1",
                "port_direction": "in",
                "port_id": "value",
            }},
            {"id": "relation:c1-o1", "kind": "constant", "data": {
                "capabilities": [
                    "relation", "behavior", "presentation", "provenance"
                ],
                "relation_family": "workflow_wire",
                "wire_id": "edge:c1-o1",
                "from_port_node": "port:c1:out",
                "to_port_node": "port:o1:in",
                "behavior": "data-flow",
                "presentation": "bezier",
                "provenance": "test:capability-relation",
            }},
        ],
        "wires": [],
    }

    norm = ng.normalize_canvas_graph(graph)

    assert {node["id"] for node in norm["nodes"]} == {"c1", "o1"}
    assert norm["wires"] == [{
        "id": "edge:c1-o1",
        "from": ["c1", "value"],
        "to": ["o1", "value"],
        "wire_node": "relation:c1-o1",
        "behavior": "data-flow",
        "presentation": "bezier",
        "provenance": "test:capability-relation",
    }]
    assert norm["relations"] == norm["wires"]
    assert norm["relations"][0]["wire_node"] == "relation:c1-o1"
    runner = WorkflowRunner(graph)
    assert runner.relations is runner.edges
    assert runner.pull("o1")["value"] == 42


def test_encryption_stage_key_reference_parameter_drives_runtime_resolution():
    from cryptography.fernet import Fernet

    key = Fernet.generate_key()
    graph = {
        "nodes": [
            {"id": "c1", "kind": "constant",
             "params": [{"k": "value", "v": {"secret": "facade"}}]},
            {"id": "o1", "kind": "output",
             "params": [{"k": "name", "v": "result"}]},
            {"id": "relation:c1-o1", "kind": "constant", "data": {
                "capabilities": ["relation"],
                "relation_family": "workflow_wire",
                "wire_id": "edge:c1-o1",
                "from_node": "c1",
                "from_port": "value",
                "to_node": "o1",
                "to_port": "value",
                "layer_nodes": {
                    "codec": "relation:c1-o1:stage:codec",
                    "encryption": "relation:c1-o1:stage:encryption",
                },
            }},
            {"id": "relation:c1-o1:stage:codec", "kind": "constant", "data": {
                "capabilities": ["relation-stage"],
                "owner": "relation:c1-o1",
                "layer": "codec",
                "value_key": "codec",
                "value": "json",
            }},
            {"id": "relation:c1-o1:stage:encryption", "kind": "constant", "data": {
                "capabilities": ["relation-stage", "encrypt", "decrypt"],
                "owner": "relation:c1-o1",
                "layer": "encryption",
                "value_key": "encryption",
                "value": "fernet",
            }},
            {"id": "param:relation:c1-o1:stage:encryption:key-ref", "kind": "constant", "data": {
                "capabilities": ["parameter"],
                "owner": "relation:c1-o1:stage:encryption",
                "key": "encryption_key_ref",
                "value": "op://ArchHub/wires/facade",
            }},
        ],
        "wires": [],
    }

    norm = ng.normalize_canvas_graph(graph)

    assert norm["wires"][0]["encryption_key_ref"] == "op://ArchHub/wires/facade"
    ctx = SimpleNamespace(resolve_secret_ref=lambda ref: key)
    runner = WorkflowRunner(graph, ctx=ctx)
    assert runner.pull("o1")["value"] == {"secret": "facade"}
    assert runner.wire_value("edge:c1-o1")["encrypted"] is True


def test_ordered_relation_endpoint_nodes_project_fanout_at_runner_boundary():
    relation_id = "relation:fanout"
    graph = {
        "nodes": [
            {"id": "c1", "kind": "constant", "params": [{"k": "value", "v": 42}]},
            {"id": "o1", "kind": "output", "params": [{"k": "name", "v": "one"}]},
            {"id": "o2", "kind": "output", "params": [{"k": "name", "v": "two"}]},
            {"id": relation_id, "kind": "constant", "data": {
                "capabilities": ["relation"],
                "relation_family": "workflow_wire",
                "wire_id": "edge:fanout",
                "endpoint_authority": "ordered-parameter-set",
                "endpoint_node_ids": [
                    f"{relation_id}:endpoint:0",
                    f"{relation_id}:endpoint:1",
                    f"{relation_id}:endpoint:2",
                ],
            }},
            {"id": f"{relation_id}:endpoint:0", "kind": "param", "data": {
                "role": "parameter", "param_family": "relation_endpoint",
                "owner": relation_id, "endpoint_index": 0,
                "endpoint_role": "source", "direction": "out",
                "participant_node_id": "c1", "participant_port_id": "value",
            }},
            {"id": f"{relation_id}:endpoint:1", "kind": "param", "data": {
                "role": "parameter", "param_family": "relation_endpoint",
                "owner": relation_id, "endpoint_index": 1,
                "endpoint_role": "target", "direction": "in",
                "participant_node_id": "o1", "participant_port_id": "value",
            }},
            {"id": f"{relation_id}:endpoint:2", "kind": "param", "data": {
                "role": "parameter", "param_family": "relation_endpoint",
                "owner": relation_id, "endpoint_index": 2,
                "endpoint_role": "target", "direction": "in",
                "participant_node_id": "o2", "participant_port_id": "value",
            }},
        ],
        "wires": [],
    }

    norm = ng.normalize_canvas_graph(graph)

    assert [edge["id"] for edge in norm["relations"]] == [
        "edge:fanout:branch:0", "edge:fanout:branch:1"
    ]
    assert [edge["to"] for edge in norm["relations"]] == [
        ["o1", "value"], ["o2", "value"]
    ]
    assert all(edge["wire_node"] == relation_id for edge in norm["relations"])
    runner = WorkflowRunner(graph)
    assert runner.pull("o1")["value"] == 42
    assert runner.pull("o2")["value"] == 42


def test_ordered_relation_fanin_collects_only_for_many_target():
    relation_id = "relation:fanin"
    target_endpoint = {
        "id": f"{relation_id}:endpoint:2", "kind": "param", "data": {
            "role": "parameter", "param_family": "relation_endpoint",
            "owner": relation_id, "endpoint_index": 2,
            "endpoint_role": "target", "direction": "in",
            "participant_node_id": "o1", "participant_port_id": "value",
            "cardinality": "many",
        }
    }
    graph = {
        "nodes": [
            {"id": "c1", "kind": "constant", "params": [{"k": "value", "v": 10}]},
            {"id": "c2", "kind": "constant", "params": [{"k": "value", "v": 20}]},
            {"id": "o1", "kind": "output", "params": [{"k": "name", "v": "values"}]},
            {"id": relation_id, "kind": "constant", "data": {
                "capabilities": ["relation"],
                "relation_family": "workflow_wire",
                "wire_id": "edge:fanin",
                "endpoint_authority": "ordered-parameter-set",
                "endpoint_node_ids": [
                    f"{relation_id}:endpoint:0",
                    f"{relation_id}:endpoint:1",
                    f"{relation_id}:endpoint:2",
                ],
            }},
            {"id": f"{relation_id}:endpoint:0", "kind": "param", "data": {
                "role": "parameter", "param_family": "relation_endpoint",
                "owner": relation_id, "endpoint_index": 0,
                "endpoint_role": "source", "direction": "out",
                "participant_node_id": "c1", "participant_port_id": "value",
            }},
            {"id": f"{relation_id}:endpoint:1", "kind": "param", "data": {
                "role": "parameter", "param_family": "relation_endpoint",
                "owner": relation_id, "endpoint_index": 1,
                "endpoint_role": "source", "direction": "out",
                "participant_node_id": "c2", "participant_port_id": "value",
            }},
            target_endpoint,
        ],
        "wires": [],
    }

    norm = ng.normalize_canvas_graph(graph)
    assert [edge["fan_in_count"] for edge in norm["relations"]] == [2, 2]
    assert WorkflowRunner(graph).pull("o1")["value"] == [10, 20]

    target_endpoint["data"]["cardinality"] = "one"
    blocked_runner = WorkflowRunner(graph)
    assert blocked_runner.pull("o1").get("value") is None
    assert all(
        edge["state"] == "blocked" for edge in blocked_runner.relations
    )


def test_raw_projection_cannot_recreate_missing_relation_authority():
    graph = {
        "nodes": [
            {"id": "c1", "kind": "constant", "params": [{"k": "value", "v": 42}]},
            {"id": "o1", "kind": "output", "params": [{"k": "name", "v": "result"}]},
        ],
        "wires": [{
            "id": "edge:c1-o1",
            "from": ["c1", "value"],
            "to": ["o1", "value"],
            "data": {"relation_node": "relation:deleted"},
        }],
    }

    norm = ng.normalize_canvas_graph(graph)

    assert norm["relations"] == []
    assert WorkflowRunner(graph).pull("o1").get("value") is None


def test_live_graph_nodes_declare_structural_capabilities():
    jsx = (Path(__file__).resolve().parent.parent / "app" / "web_ui" / "studio-lm.jsx").read_text(
        encoding="utf-8"
    )

    assert "['application', 'container', 'runtime', 'presentation'" in jsx
    assert "['relation', 'behavior', 'presentation', 'provenance']" in jsx
    assert "['relation-stage'].concat(contextualCapabilities)" in jsx
    assert "'parameter',\n    'port'," in jsx
    assert "materializeGrandMapParamNode(encryptionLayer.id, 'key_ref', keyRef);" in jsx
