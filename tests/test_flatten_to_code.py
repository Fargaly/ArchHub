"""SLICE L follow-up — flatten chain to code (pure Python utility).

Tests:
  1. Trivial chains (constant only, single math op).
  2. Multi-step linear chains (a + b * 2).
  3. Branched / multi-input chains.
  4. Wire rewriting (external upstreams → code node, code → downstream).
  5. Engine equivalence (the flattened code cooks to the same value
     as the original chain).
  6. Error paths: cycle, unflattenable type, empty selection,
     unknown op, multiple tails.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import workflows.nodes  # noqa: F401, E402  — register engines
from workflows.flatten_to_code import (  # noqa: E402
    chain_to_expression,
    flatten_chain,
    FLATTENABLE_TYPES,
)


# ─── 1. trivial chains ───────────────────────────────────────────────


def test_chain_with_just_a_constant():
    g = {"nodes": [
        {"id": "k", "type": "data.constant", "config": {"value": 42}},
    ], "wires": []}
    r = chain_to_expression(g, ["k"])
    assert r["expression"] == "42"
    assert r["external_inputs"] == []


def test_chain_with_one_add_op_two_externals():
    g = {
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
    # Only `add` is selected — x + y stay external.
    r = chain_to_expression(g, ["add"])
    assert "+" in r["expression"]
    # Two external inputs allocated as 'a', 'b'.
    symbols = [e["symbol"] for e in r["external_inputs"]]
    assert "a" in symbols
    assert "b" in symbols


def test_chain_with_all_selected_collapses_to_literal_expr():
    """Constants + add, all selected → expression `(5 + 3)`, no externals."""
    g = {
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
    r = chain_to_expression(g, ["x", "y", "add"])
    assert r["expression"] == "(5 + 3)"
    assert r["external_inputs"] == []


# ─── 2. multi-step linear chain ──────────────────────────────────────


def test_chain_a_plus_b_times_2():
    """ext → add → mul (2 constant) → tail. Selected: add + mul."""
    g = {
        "nodes": [
            {"id": "ext_a", "type": "data.constant", "config": {"value": 10}},
            {"id": "ext_b", "type": "data.constant", "config": {"value": 4}},
            {"id": "k2", "type": "data.constant", "config": {"value": 2}},
            {"id": "add", "type": "math.op", "config": {"op": "add"}},
            {"id": "mul", "type": "math.op", "config": {"op": "mul"}},
        ],
        "wires": [
            {"from": ["ext_a", "value"], "to": ["add", "a"]},
            {"from": ["ext_b", "value"], "to": ["add", "b"]},
            {"from": ["add", "value"], "to": ["mul", "a"]},
            {"from": ["k2", "value"], "to": ["mul", "b"]},
        ],
    }
    # Selecting add + mul + k2 (the constant 2 is in the chain).
    # ext_a + ext_b stay external.
    r = chain_to_expression(g, ["add", "mul", "k2"])
    # Expression: ((a + b) * 2)
    assert "+" in r["expression"]
    assert "*" in r["expression"]
    assert "2" in r["expression"]
    symbols = [e["symbol"] for e in r["external_inputs"]]
    assert len(symbols) == 2


# ─── 3. text ops ─────────────────────────────────────────────────────


def test_chain_text_concat_upper():
    g = {
        "nodes": [
            {"id": "ext", "type": "data.constant",
             "config": {"value": "hello"}},
            {"id": "k_world", "type": "data.constant",
             "config": {"value": " world"}},
            {"id": "concat", "type": "text.op",
             "config": {"op": "concat"}},
            {"id": "up", "type": "text.op",
             "config": {"op": "upper"}},
        ],
        "wires": [
            {"from": ["ext", "value"], "to": ["concat", "a"]},
            {"from": ["k_world", "value"], "to": ["concat", "b"]},
            {"from": ["concat", "value"], "to": ["up", "a"]},
        ],
    }
    r = chain_to_expression(g, ["concat", "up", "k_world"])
    assert ".upper()" in r["expression"]
    assert "+ str" in r["expression"]


# ─── 4. wire rewriting via flatten_chain ─────────────────────────────


def test_flatten_chain_rewires_externals_and_downstream():
    g = {
        "nodes": [
            {"id": "ext_a", "type": "data.constant", "config": {"value": 1}},
            {"id": "ext_b", "type": "data.constant", "config": {"value": 2}},
            {"id": "add", "type": "math.op", "config": {"op": "add"}},
            {"id": "sink", "type": "data.passthrough", "config": {}},
        ],
        "wires": [
            {"from": ["ext_a", "value"], "to": ["add", "a"]},
            {"from": ["ext_b", "value"], "to": ["add", "b"]},
            {"from": ["add", "value"], "to": ["sink", "value"]},
        ],
    }
    result = flatten_chain(g, ["add"])
    assert "error" not in result, result.get("error")
    new_g = result["graph"]

    # `add` removed, code node inserted.
    node_ids = {n["id"] for n in new_g["nodes"]}
    assert "add" not in node_ids
    assert result["new_node_id"] in node_ids
    # ext_a + ext_b + sink survive.
    assert {"ext_a", "ext_b", "sink"} <= node_ids

    # Wires re-pointed.
    code_id = result["new_node_id"]
    src_to_code = [w for w in new_g["wires"]
                    if w["to"][0] == code_id]
    assert len(src_to_code) == 2  # ext_a + ext_b
    code_to_sink = [w for w in new_g["wires"]
                     if w["from"][0] == code_id and w["to"][0] == "sink"]
    assert len(code_to_sink) == 1
    assert code_to_sink[0]["from"] == [code_id, "value"]


def test_flatten_chain_drops_internal_wires():
    """A wire whose endpoints are BOTH selected should be removed."""
    g = {
        "nodes": [
            {"id": "k1", "type": "data.constant", "config": {"value": 1}},
            {"id": "k2", "type": "data.constant", "config": {"value": 2}},
            {"id": "add", "type": "math.op", "config": {"op": "add"}},
        ],
        "wires": [
            {"from": ["k1", "value"], "to": ["add", "a"]},
            {"from": ["k2", "value"], "to": ["add", "b"]},
        ],
    }
    result = flatten_chain(g, ["k1", "k2", "add"])
    assert "error" not in result
    new_g = result["graph"]
    # No wires at all — every wire was internal to the selection.
    assert new_g["wires"] == []


# ─── 5. engine equivalence ───────────────────────────────────────────


def test_flattened_chain_cooks_to_same_value_as_original():
    """The whole point: flattened chain produces the same value
    when cooked through the runner."""
    from workflows.runner import WorkflowRunner
    from workflows.node_grammar import normalize_canvas_graph

    original = {
        "nodes": [
            {"id": "a", "type": "data.constant", "config": {"value": 10}},
            {"id": "b", "type": "data.constant", "config": {"value": 4}},
            {"id": "k2", "type": "data.constant", "config": {"value": 2}},
            {"id": "add", "type": "math.op", "config": {"op": "add"}},
            {"id": "mul", "type": "math.op", "config": {"op": "mul"}},
            {"id": "out", "type": "data.passthrough", "config": {}},
        ],
        "wires": [
            {"from": ["a", "value"], "to": ["add", "a"]},
            {"from": ["b", "value"], "to": ["add", "b"]},
            {"from": ["add", "value"], "to": ["mul", "a"]},
            {"from": ["k2", "value"], "to": ["mul", "b"]},
            {"from": ["mul", "value"], "to": ["out", "value"]},
        ],
    }
    result = flatten_chain(original, ["add", "mul", "k2"])
    flat_g = result["graph"]

    def cook(graph):
        g = normalize_canvas_graph(graph)
        return WorkflowRunner(g).run_all()

    # (10 + 4) * 2 = 28
    assert cook(original)["results"]["out"]["value"] == 28
    assert cook(flat_g)["results"]["out"]["value"] == 28


def test_flattened_text_chain_cooks_to_same_string():
    from workflows.runner import WorkflowRunner
    from workflows.node_grammar import normalize_canvas_graph

    original = {
        "nodes": [
            {"id": "a", "type": "data.constant",
             "config": {"value": "hello"}},
            {"id": "b", "type": "data.constant",
             "config": {"value": "WORLD"}},
            {"id": "concat", "type": "text.op",
             "config": {"op": "concat"}},
            {"id": "lo", "type": "text.op",
             "config": {"op": "lower"}},
            {"id": "out", "type": "data.passthrough", "config": {}},
        ],
        "wires": [
            {"from": ["a", "value"], "to": ["concat", "a"]},
            {"from": ["b", "value"], "to": ["concat", "b"]},
            {"from": ["concat", "value"], "to": ["lo", "a"]},
            {"from": ["lo", "value"], "to": ["out", "value"]},
        ],
    }
    result = flatten_chain(original, ["concat", "lo"])
    flat_g = result["graph"]

    def cook(graph):
        g = normalize_canvas_graph(graph)
        return WorkflowRunner(g).run_all()

    assert cook(original)["results"]["out"]["value"] == "helloworld"
    assert cook(flat_g)["results"]["out"]["value"] == "helloworld"


# ─── 6. error paths ──────────────────────────────────────────────────


def test_flatten_empty_selection_errors():
    g = {"nodes": [], "wires": []}
    r = chain_to_expression(g, [])
    assert "error" in r


def test_flatten_unknown_node_errors():
    g = {"nodes": [
        {"id": "k", "type": "data.constant", "config": {"value": 1}},
    ], "wires": []}
    r = chain_to_expression(g, ["nonexistent"])
    assert "error" in r
    assert "not in graph" in r["error"]


def test_flatten_unflattenable_type_errors():
    g = {"nodes": [
        {"id": "x", "type": "conversation.chat", "config": {}},
    ], "wires": []}
    r = chain_to_expression(g, ["x"])
    assert "error" in r
    assert "flattenable" in r["error"]


def test_flatten_unknown_op_errors():
    g = {"nodes": [
        {"id": "weird", "type": "math.op", "config": {"op": "wibble"}},
    ], "wires": []}
    r = chain_to_expression(g, ["weird"])
    assert "error" in r
    assert "wibble" in r["error"]


def test_flatten_multiple_tails_errors():
    """Two selected nodes both output to external → 2 tails → not
    flattenable in this MVP."""
    g = {
        "nodes": [
            {"id": "a", "type": "data.constant", "config": {"value": 1}},
            {"id": "b", "type": "data.constant", "config": {"value": 2}},
            {"id": "out_a", "type": "data.passthrough", "config": {}},
            {"id": "out_b", "type": "data.passthrough", "config": {}},
        ],
        "wires": [
            {"from": ["a", "value"], "to": ["out_a", "value"]},
            {"from": ["b", "value"], "to": ["out_b", "value"]},
        ],
    }
    r = chain_to_expression(g, ["a", "b"])
    assert "error" in r
    assert "tails" in r["error"]


def test_flattenable_types_set():
    """Document the set: math.op, text.op, data.constant, data.passthrough."""
    assert FLATTENABLE_TYPES == {
        "math.op", "text.op", "data.constant", "data.passthrough",
    }
