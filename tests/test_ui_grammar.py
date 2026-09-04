from __future__ import annotations

import sys
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parent.parent / "app"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

import workflows  # noqa: E402  importing registers built-in node types
from workflows.nodes import ui as legacy_ui  # noqa: E402
from workflows import node_grammar as ng  # noqa: E402
from workflows.runner import WorkflowRunner  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_secrets_store(monkeypatch):
    monkeypatch.setenv("ARCHHUB_NO_SELF_HEAL", "1")


@pytest.fixture(autouse=True)
def _isolate_brain_daemon(monkeypatch):
    monkeypatch.setenv("ARCHHUB_MEMORY_STANDALONE", "1")
    monkeypatch.setenv("BRAIN_HTTP_URL", "http://127.0.0.1:1")


def test_ui_element_resolves_to_first_class_ui_grammar_spec():
    by_kind = {entry["kind"]: entry for entry in ng.grammar_payload()}

    spec = by_kind["ui.element"]

    assert spec["kind"] == "ui.element"
    assert spec["display"] == "UI Element"
    assert spec["cat"] == "ui"
    assert spec["selector"] == ""
    assert spec["engine_types"] == {"": "ui.element"}
    assert spec["status"] == ng.READY
    assert spec["ports"]["in"] == [
        {"id": "parent", "type": "UI"},
        {"id": "children", "type": "UI"},
        {"id": "value", "type": "ANY"},
    ]
    assert spec["ports"]["out"] == [{"id": "child", "type": "UI"}]
    assert ng.engine_type("ui.element") == "ui.element"

    registered = workflows.get("ui.element")
    assert registered is not None
    node_spec = registered[0]
    assert node_spec.category == "ui"
    assert node_spec.inputs[0].name == "parent"
    assert node_spec.inputs[0].type.value == "ui"
    assert node_spec.inputs[1].name == "children"
    assert node_spec.inputs[1].type.value == "ui"
    assert node_spec.inputs[2].name == "value"
    assert node_spec.inputs[2].type.value == "any"
    assert node_spec.outputs[0].name == "child"
    assert node_spec.outputs[0].type.value == "ui"
    assert legacy_ui.LEGACY_MIGRATION_ONLY is True
    assert legacy_ui.AUTHORITY_STATUS == "superseded_by_universal_cell"
    assert "Legacy typed-runtime" in node_spec.description
    assert "Universal Cell authority" in node_spec.description


def test_ui_element_cooks_bound_value_and_wired_child_through_runner():
    graph = {
        "nodes": [
            {"id": "value", "kind": "text",
             "params": [{"k": "value", "v": "42"}]},
            {"id": "label", "kind": "ui.element",
             "params": [
                 {"k": "tag", "v": "span"},
                 {"k": "text", "v": "Count: "},
                 {"k": "bind", "v": "value"},
             ]},
            {"id": "root", "kind": "ui.element",
             "params": [
                 {"k": "tag", "v": "section"},
                 {"k": "cls", "v": "panel"},
             ]},
        ],
        "wires": [
            {"from": ["value", "value"], "to": ["label", "value"]},
            {"from": ["label", "child"], "to": ["root", "children"]},
        ],
    }

    out = WorkflowRunner(ng.normalize_canvas_graph(graph)).pull("root")

    assert out["child"] == {
        "tag": "section",
        "attrs": {"data-node": "root", "class": "panel"},
        "text": "",
        "children": [
            {
                "tag": "span",
                "attrs": {"data-node": "label"},
                "text": "Count: 42",
                "children": [],
            }
        ],
    }


def test_unknown_type_still_resolves_to_existing_none_fallback():
    assert ng.get_primitive("ui.missing") is None
    assert ng.engine_type("ui.missing") is None
