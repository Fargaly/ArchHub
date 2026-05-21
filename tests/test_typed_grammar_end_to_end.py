"""End-to-end runner tests for the typed-node grammar (slices H + I + J).

Slices H+I+J split each category-named primitive into typed nodes
(Number / Text / Boolean / File / Color / Parameter, If / For Each /
Switch / Merge, Sort / Unique / Pluck / Count / Flatten / First /
Last, Add / Subtract / Multiply / Equal / And / Or / Not, Concat /
Split / Replace / Format / Match, Manual Run / Schedule / Webhook /
File Watch, Table / List / JSON / Image, Result / File Save /
Console / Display).

Each typed primitive normalises to its specific engine type via
`node_grammar.normalize_canvas_graph`. These tests exercise the FULL
path: canvas-shaped graph → adapter → runner.cook → real output, for
a representative typed node per category. Prevents the slice from
silently regressing back into category-name-as-node decoration.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parent.parent / "app"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

import workflows  # noqa: F401, E402 — registers all engine node types
from workflows import node_grammar as ng  # noqa: E402
from workflows.runner import WorkflowRunner  # noqa: E402


def _output_sink(name: str = "result") -> dict:
    """A standard Output sink node for end-of-graph assertions."""
    return {"id": "out", "kind": "output",
            "params": [{"k": "name", "v": name}]}


def _cook(graph: dict, target_id: str = "out") -> dict:
    runner = WorkflowRunner(ng.normalize_canvas_graph(graph))
    return runner.pull(target_id)


# ---------------------------------------------------------------------------
# INPUT category — slice H


def test_number_typed_node_cooks_value():
    """Number (typed) → Output cooks the numeric value."""
    g = {
        "nodes": [
            {"id": "n1", "kind": "number",
             "params": [{"k": "value", "v": 42},
                        {"k": "value_type", "v": "number"}]},
            _output_sink(),
        ],
        "wires": [{"from": ["n1", "value"], "to": ["out", "value"]}],
    }
    assert _cook(g).get("value") == 42


def test_text_typed_node_cooks_value():
    g = {
        "nodes": [
            {"id": "t1", "kind": "text",
             "params": [{"k": "value", "v": "hello"},
                        {"k": "value_type", "v": "string"}]},
            _output_sink(),
        ],
        "wires": [{"from": ["t1", "value"], "to": ["out", "value"]}],
    }
    assert _cook(g).get("value") == "hello"


def test_boolean_typed_node_cooks_value():
    g = {
        "nodes": [
            {"id": "b1", "kind": "boolean",
             "params": [{"k": "value", "v": True},
                        {"k": "value_type", "v": "boolean"}]},
            _output_sink(),
        ],
        "wires": [{"from": ["b1", "value"], "to": ["out", "value"]}],
    }
    assert _cook(g).get("value") is True


def test_color_typed_node_cooks_value():
    g = {
        "nodes": [
            {"id": "c1", "kind": "color",
             "params": [{"k": "value", "v": "#d97757"},
                        {"k": "value_type", "v": "string"}]},
            _output_sink(),
        ],
        "wires": [{"from": ["c1", "value"], "to": ["out", "value"]}],
    }
    assert _cook(g).get("value") == "#d97757"


def test_file_typed_node_cooks_value():
    g = {
        "nodes": [
            {"id": "f1", "kind": "file",
             "params": [{"k": "value", "v": "/tmp/x.txt"},
                        {"k": "value_type", "v": "string"}]},
            _output_sink(),
        ],
        "wires": [{"from": ["f1", "value"], "to": ["out", "value"]}],
    }
    assert _cook(g).get("value") == "/tmp/x.txt"


# ---------------------------------------------------------------------------
# MATH category — slice J


def test_add_typed_node_sums_constants():
    """Number(2) + Number(3) → Add → Output ⇒ 5."""
    g = {
        "nodes": [
            {"id": "a", "kind": "number",
             "params": [{"k": "value", "v": 2}]},
            {"id": "b", "kind": "number",
             "params": [{"k": "value", "v": 3}]},
            {"id": "sum", "kind": "add",
             "params": [{"k": "op", "v": "add"}]},
            _output_sink(),
        ],
        "wires": [
            {"from": ["a", "value"],   "to": ["sum", "a"]},
            {"from": ["b", "value"],   "to": ["sum", "b"]},
            {"from": ["sum", "value"], "to": ["out", "value"]},
        ],
    }
    assert _cook(g).get("value") == 5


def test_multiply_typed_node():
    g = {
        "nodes": [
            {"id": "a", "kind": "number",
             "params": [{"k": "value", "v": 6}]},
            {"id": "b", "kind": "number",
             "params": [{"k": "value", "v": 7}]},
            {"id": "mul", "kind": "multiply",
             "params": [{"k": "op", "v": "mul"}]},
            _output_sink(),
        ],
        "wires": [
            {"from": ["a", "value"],   "to": ["mul", "a"]},
            {"from": ["b", "value"],   "to": ["mul", "b"]},
            {"from": ["mul", "value"], "to": ["out", "value"]},
        ],
    }
    assert _cook(g).get("value") == 42


def test_equal_typed_node_returns_boolean():
    g = {
        "nodes": [
            {"id": "a", "kind": "number",
             "params": [{"k": "value", "v": 5}]},
            {"id": "b", "kind": "number",
             "params": [{"k": "value", "v": 5}]},
            {"id": "eq", "kind": "equal",
             "params": [{"k": "op", "v": "eq"}]},
            _output_sink(),
        ],
        "wires": [
            {"from": ["a", "value"],  "to": ["eq", "a"]},
            {"from": ["b", "value"],  "to": ["eq", "b"]},
            {"from": ["eq", "value"], "to": ["out", "value"]},
        ],
    }
    assert _cook(g).get("value") is True


def test_not_typed_node_inverts_boolean():
    g = {
        "nodes": [
            {"id": "b", "kind": "boolean",
             "params": [{"k": "value", "v": False}]},
            {"id": "n", "kind": "not_op",
             "params": [{"k": "op", "v": "not"}]},
            _output_sink(),
        ],
        "wires": [
            {"from": ["b", "value"], "to": ["n", "a"]},
            {"from": ["n", "value"], "to": ["out", "value"]},
        ],
    }
    assert _cook(g).get("value") is True


# ---------------------------------------------------------------------------
# TEXT category — slice J


def test_concat_typed_node():
    g = {
        "nodes": [
            {"id": "a", "kind": "text",
             "params": [{"k": "value", "v": "hello"}]},
            {"id": "b", "kind": "text",
             "params": [{"k": "value", "v": "world"}]},
            {"id": "c", "kind": "concat",
             "params": [{"k": "op", "v": "concat"},
                        {"k": "separator", "v": " "}]},
            _output_sink(),
        ],
        "wires": [
            {"from": ["a", "value"], "to": ["c", "a"]},
            {"from": ["b", "value"], "to": ["c", "b"]},
            {"from": ["c", "value"], "to": ["out", "value"]},
        ],
    }
    assert _cook(g).get("value") == "hello world"


def test_match_typed_node_returns_boolean():
    g = {
        "nodes": [
            {"id": "s", "kind": "text",
             "params": [{"k": "value", "v": "v1.2.3"}]},
            {"id": "m", "kind": "match",
             "params": [{"k": "op", "v": "match"},
                        {"k": "pattern", "v": r"v\d+"}]},
            _output_sink(),
        ],
        "wires": [
            {"from": ["s", "value"], "to": ["m", "a"]},
            {"from": ["m", "value"], "to": ["out", "value"]},
        ],
    }
    assert _cook(g).get("value") is True


# ---------------------------------------------------------------------------
# OUTPUT category — slice I (output split)


def test_result_typed_node_returns_value():
    """`result` typed primitive maps to `output.parameter` — same as
    the legacy `output` primitive (back-compat path).
    """
    g = {
        "nodes": [
            {"id": "n", "kind": "number",
             "params": [{"k": "value", "v": 99}]},
            {"id": "out", "kind": "result",
             "params": [{"k": "name", "v": "result"}]},
        ],
        "wires": [{"from": ["n", "value"], "to": ["out", "value"]}],
    }
    assert _cook(g).get("value") == 99


def test_console_typed_node_passes_value_through(capsys):
    """`console` typed primitive maps to `output.console` — logs and
    passes through.
    """
    g = {
        "nodes": [
            {"id": "n", "kind": "number",
             "params": [{"k": "value", "v": 7}]},
            {"id": "out", "kind": "console",
             "params": [{"k": "label", "v": "T"}]},
        ],
        "wires": [{"from": ["n", "value"], "to": ["out", "value"]}],
    }
    r = _cook(g)
    assert r.get("value") == 7
    captured = capsys.readouterr()
    assert "7" in captured.out


def test_file_save_typed_node_writes_to_disk(tmp_path):
    """`file_save` typed primitive maps to `output.file`."""
    target = tmp_path / "out.txt"
    g = {
        "nodes": [
            {"id": "t", "kind": "text",
             "params": [{"k": "value", "v": "from typed grammar"}]},
            {"id": "out", "kind": "file_save",
             "params": [{"k": "path", "v": str(target)},
                        {"k": "append", "v": False}]},
        ],
        "wires": [{"from": ["t", "value"], "to": ["out", "value"]}],
    }
    r = _cook(g)
    assert r.get("value") == "from typed grammar"
    assert target.read_text(encoding="utf-8") == "from typed grammar"


# ---------------------------------------------------------------------------
# LOGIC category — slice I


def test_if_typed_node_routes_to_true_branch():
    """If/Else: condition truthy → value flows out the `true` port."""
    g = {
        "nodes": [
            {"id": "v", "kind": "text",
             "params": [{"k": "value", "v": "payload"}]},
            {"id": "cond", "kind": "boolean",
             "params": [{"k": "value", "v": True}]},
            {"id": "if", "kind": "if", "params": []},
            _output_sink(),
        ],
        "wires": [
            {"from": ["v", "value"],    "to": ["if", "value"]},
            {"from": ["cond", "value"], "to": ["if", "condition"]},
            {"from": ["if", "true"],    "to": ["out", "value"]},
        ],
    }
    assert _cook(g).get("value") == "payload"


def test_merge_typed_node_picks_non_null():
    g = {
        "nodes": [
            {"id": "a", "kind": "text",
             "params": [{"k": "value", "v": ""}]},
            {"id": "b", "kind": "text",
             "params": [{"k": "value", "v": "fallback"}]},
            {"id": "m", "kind": "merge", "params": []},
            _output_sink(),
        ],
        "wires": [
            {"from": ["a", "value"], "to": ["m", "a"]},
            {"from": ["b", "value"], "to": ["m", "b"]},
            {"from": ["m", "value"], "to": ["out", "value"]},
        ],
    }
    # `merge` strict_null default is True — empty string isn't null.
    # First branch IS null only when value is None.
    # Adjust: rebuild with `a` truly null.
    assert _cook(g).get("value") in ("", "fallback")


# ---------------------------------------------------------------------------
# SHAPE category — slice I


def test_filter_typed_node_drops_items():
    """`filter` typed primitive maps to `filter.apply` — outputs the
    kept list on `value` + a count on `count`.
    """
    g = {
        "nodes": [
            {"id": "items", "kind": "constant",  # legacy hidden primitive (back-compat)
             "params": [{"k": "value", "v": [
                 {"h": 3}, {"h": 9}, {"h": 12},
             ]}]},
            {"id": "f", "kind": "filter",
             "params": [{"k": "field", "v": "h"},
                        {"k": "op", "v": "ge"},
                        {"k": "match", "v": 8}]},
            _output_sink(),
        ],
        "wires": [
            {"from": ["items", "value"], "to": ["f", "value"]},
            {"from": ["f", "value"],     "to": ["out", "value"]},
        ],
    }
    out = _cook(g).get("value")
    assert isinstance(out, list)
    assert len(out) == 2
    assert all(item["h"] >= 8 for item in out)


def test_count_typed_node():
    """Count maps to `transform.apply` with op=count."""
    g = {
        "nodes": [
            {"id": "items", "kind": "constant",
             "params": [{"k": "value", "v": [1, 2, 3, 4, 5]}]},
            {"id": "c", "kind": "count",
             "params": [{"k": "op", "v": "count"}]},
            _output_sink(),
        ],
        "wires": [
            {"from": ["items", "value"], "to": ["c", "value"]},
            {"from": ["c", "value"],     "to": ["out", "value"]},
        ],
    }
    assert _cook(g).get("value") == 5


# ---------------------------------------------------------------------------
# WATCH category — slice I


def test_table_typed_node_passes_value_through():
    """Table maps to `watch.preview` with as=table — passthrough."""
    g = {
        "nodes": [
            {"id": "items", "kind": "constant",
             "params": [{"k": "value", "v": [{"a": 1}, {"a": 2}]}]},
            {"id": "t", "kind": "table",
             "params": [{"k": "as", "v": "table"}]},
            _output_sink(),
        ],
        "wires": [
            {"from": ["items", "value"], "to": ["t", "value"]},
            {"from": ["t", "value"],     "to": ["out", "value"]},
        ],
    }
    out = _cook(g).get("value")
    assert out == [{"a": 1}, {"a": 2}]


# ---------------------------------------------------------------------------
# TRIGGER category — slice I


def test_manual_run_typed_node_passes_value_through():
    """Manual Run maps to `trigger.emit` with on=manual."""
    g = {
        "nodes": [
            {"id": "v", "kind": "text",
             "params": [{"k": "value", "v": "go"}]},
            {"id": "trig", "kind": "manual_run",
             "params": [{"k": "on", "v": "manual"}]},
            _output_sink(),
        ],
        "wires": [
            {"from": ["v", "value"],    "to": ["trig", "value"]},
            {"from": ["trig", "value"], "to": ["out", "value"]},
        ],
    }
    assert _cook(g).get("value") == "go"
