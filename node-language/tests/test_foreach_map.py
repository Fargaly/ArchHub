"""control.foreach — real `map` fan-out, grounded in the real engine.

The phase-1 `control.foreach` only INSPECTED a list (items/count/first/last).
This suite pins the ADDITIVE real map: given a list + a `body` sub-graph, the
body cooks ONCE per item (the item bound as `item`), and the per-item outputs
are collected into `results` in input order.

What's pinned:
  * the body cooks exactly once per item (a call-counter proves it);
  * `results` collects each item's primary output, in input order;
  * the item binds to the body's entry port named `item` (seed convention);
  * the legacy inspect outputs (items/count/first/last) still work — both
    with a body wired and with no body (pure inspect, `results: []`);
  * parallel=True keeps `results` deterministic (re-sorted to input order);
  * halt_on_error=True returns a typed error + partial results + failed_index;
  * halt_on_error=False appends a per-item error marker and continues;
  * the map runs through a real outer WorkflowRunner (not just the executor),
    so the canvas cook path is exercised end-to-end.

The body cook reuses the EXISTING nested-WorkflowRunner machinery
(`_subgraph_executor` + `_derive_graph_io`) — these tests assert the reuse
produces real per-item results, never a fabricated value.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))

# Importing workflows.nodes registers control.foreach + the built-ins;
# workflows.subgraph registers subgraph.user + the internal seed node.
from workflows import nodes as _nodes_pkg  # noqa: F401
from workflows import subgraph  # noqa: F401  triggers register_subgraph_executor
from workflows.runner import WorkflowRunner
from workflows.registry import register, NodeSpec, get as _get_spec
from workflows.graph import Port, PortType
from workflows.nodes import control as _control


# ── Test body node — single `item` input → `out` output ──────────────
# A purpose-built node so the body has exactly ONE open input (named
# `item`, exercising the seed binding convention) and ONE open output.
# It counts every cook so the test can prove "once per item".
_CALLS: list = []          # records the item value seen on each cook
_CALLS_LOCK = threading.Lock()


def _item_double_exec(config, inputs, ctx):
    item = inputs.get("item")
    with _CALLS_LOCK:
        _CALLS.append(item)
    try:
        return {"status": "ok", "out": item * 2}
    except Exception as ex:           # non-numeric → honest typed error
        return {"status": "error", "error": f"{type(ex).__name__}: {ex}"}


def _item_explode_exec(config, inputs, ctx):
    """Errors when the item is the configured 'bad' value; else doubles."""
    item = inputs.get("item")
    if item == config.get("bad"):
        return {"status": "error", "error": f"bad item {item!r}"}
    return {"status": "ok", "out": item * 2}


def _ensure_test_nodes():
    if _get_spec("_test.item_double") is None:
        register(NodeSpec(
            type="_test.item_double", category="_test",
            display_name="Test Item Double",
            description="Doubles `item` → `out`; counts every cook.",
            inputs=[Port(name="item", type=PortType.ANY)],
            outputs=[Port(name="out", type=PortType.ANY)],
            config_schema={}, icon="x",
        ), _item_double_exec)
    if _get_spec("_test.item_explode") is None:
        register(NodeSpec(
            type="_test.item_explode", category="_test",
            display_name="Test Item Explode",
            description="Errors on the configured bad item, else doubles.",
            inputs=[Port(name="item", type=PortType.ANY)],
            outputs=[Port(name="out", type=PortType.ANY)],
            config_schema={}, icon="!",
        ), _item_explode_exec)


@pytest.fixture(autouse=True)
def _setup():
    _ensure_test_nodes()
    _ensure_const_nodes()
    with _CALLS_LOCK:
        _CALLS.clear()
    yield


def _double_body():
    """A one-node body graph: `item` → ×2 → `out`. Its `item` input and
    `out` output are both OPEN, so `_derive_graph_io` lifts them as the
    entry/exit ports."""
    return {
        "nodes": [
            {"id": "dbl", "type": "_test.item_double", "config": {},
             "ins":  [{"id": "item", "t": "any"}],
             "outs": [{"id": "out", "label": "out", "t": "any"}]},
        ],
        "wires": [],
    }


# ── the headline: real fan-out, body cooks once per item, ordered ────
def test_foreach_maps_body_once_per_item_in_order():
    """A list → map(body) → assert the body cooked once per item + results
    collected in order. Driven through a real outer WorkflowRunner so the
    canvas cook path is exercised, not just the executor."""
    items = [1, 2, 3, 4]
    graph = {
        "nodes": [
            {"id": "src", "type": "_test.const_list", "config": {"value": items},
             "outs": [{"id": "value", "t": "list"}]},
            {"id": "map", "type": "control.foreach", "config": {},
             "ins":  [{"id": "items", "t": "list"},
                       {"id": "body", "t": "any"}],
             "outs": [{"id": "results", "t": "list"}]},
            {"id": "bodysrc", "type": "_test.const_any",
             "config": {"value": _double_body()},
             "outs": [{"id": "value", "t": "any"}]},
        ],
        "wires": [
            {"from": ["src", "value"], "to": ["map", "items"]},
            {"from": ["bodysrc", "value"], "to": ["map", "body"]},
        ],
    }
    runner = WorkflowRunner(graph)
    out = runner.pull("map")

    assert out.get("status") == "ok"
    # Each item cooked the body exactly once → 4 cooks, in input order.
    assert _CALLS == [1, 2, 3, 4]
    # Per-item primary output collected into results, in input order.
    assert out.get("results") == [2, 4, 6, 8]


def test_foreach_results_match_executor_directly():
    """The executor (called directly, like the runner does) returns the
    mapped list — the body's `out` doubled per item."""
    out = _control._foreach_executor(
        {}, {"items": [5, 6, 7], "body": _double_body()}, _ctx())
    assert out["status"] == "ok"
    assert out["results"] == [10, 12, 14]
    assert _CALLS == [5, 6, 7]


# ── back-compat: inspect outputs still work ──────────────────────────
def test_foreach_inspect_outputs_preserved_with_body():
    """Even when mapping, the legacy inspect outputs are emitted alongside
    `results` — the contract is a SUPERSET, nothing removed."""
    out = _control._foreach_executor(
        {}, {"items": [10, 20, 30], "body": _double_body()}, _ctx())
    assert out["items"] == [10, 20, 30]
    assert out["count"] == 3
    assert out["first"] == 10
    assert out["last"] == 30
    assert out["results"] == [20, 40, 60]


def test_foreach_pure_inspect_when_no_body():
    """No `body` wired → the phase-1 inspect behaviour is unchanged:
    items/count/first/last emitted, `results` is an empty list, no cook."""
    out = _control._foreach_executor(
        {}, {"items": ["a", "b", "c"]}, _ctx())
    assert out["items"] == ["a", "b", "c"]
    assert out["count"] == 3
    assert out["first"] == "a"
    assert out["last"] == "c"
    assert out["results"] == []
    assert _CALLS == []            # nothing cooked — pure inspect


def test_foreach_non_list_items_coerced_like_phase1():
    """A scalar `items` is wrapped to a single-element list, exactly as the
    phase-1 executor did — back-compat for that edge case too."""
    out = _control._foreach_executor({}, {"items": 42}, _ctx())
    assert out["items"] == [42]
    assert out["count"] == 1
    assert out["first"] == 42
    assert out["last"] == 42


def test_foreach_empty_list_is_empty_results():
    out = _control._foreach_executor(
        {}, {"items": [], "body": _double_body()}, _ctx())
    assert out["status"] == "ok"
    assert out["results"] == []
    assert out["count"] == 0
    assert _CALLS == []


# ── binding convention: item binds to the `item` entry port ──────────
def test_foreach_binds_item_to_named_item_port():
    """The body's open input is named `item`; the seed convention binds the
    current item there. The body sees the raw item value (proven by the
    recorded cook values matching the input list)."""
    _control._foreach_executor(
        {}, {"items": [7, 8, 9], "body": _double_body()}, _ctx())
    assert _CALLS == [7, 8, 9]


# ── parallel keeps results ordered ───────────────────────────────────
def test_foreach_parallel_preserves_input_order():
    """parallel=True runs iterations concurrently but `results` is re-sorted
    to input order — deterministic regardless of completion order."""
    items = list(range(12))
    out = _control._foreach_executor(
        {"parallel": True}, {"items": items, "body": _double_body()}, _ctx())
    assert out["status"] == "ok"
    assert out["results"] == [i * 2 for i in items]
    # Every item cooked exactly once (order of _CALLS is non-deterministic
    # under threads, so compare as multisets).
    assert sorted(_CALLS) == items


# ── error handling: halt vs continue ─────────────────────────────────
def _explode_body(bad):
    return {
        "nodes": [
            {"id": "boom", "type": "_test.item_explode",
             "config": {"bad": bad},
             "ins":  [{"id": "item", "t": "any"}],
             "outs": [{"id": "out", "label": "out", "t": "any"}]},
        ],
        "wires": [],
    }


def test_foreach_halt_on_error_returns_typed_error_and_partial():
    """halt_on_error=True (default): stop at the first failing item, return a
    typed error with the partial results + the failed index — never a
    fabricated value for the failed slot."""
    out = _control._foreach_executor(
        {}, {"items": [1, 2, 3, 4], "body": _explode_body(3)}, _ctx())
    assert out["status"] == "error"
    assert out["failed_index"] == 2          # item value 3 is at index 2
    assert out["error"] == "bad item 3"
    assert out["results"] == [2, 4]          # only items before the failure


def test_foreach_continue_on_error_marks_slot_and_proceeds():
    """halt_on_error=False: append an `{error: ...}` marker for the failed
    item, continue, and surface an `errors` list. Final status ok."""
    out = _control._foreach_executor(
        {"halt_on_error": False},
        {"items": [1, 3, 5], "body": _explode_body(3)}, _ctx())
    assert out["status"] == "ok"
    assert out["results"][0] == 2
    assert out["results"][2] == 10
    assert isinstance(out["results"][1], dict)
    assert "error" in out["results"][1]
    assert out["errors"] == [{"index": 1, "error": "bad item 3"}]


# ── helpers ──────────────────────────────────────────────────────────
def _ctx():
    from types import SimpleNamespace
    return SimpleNamespace(router=None, tool_engine=None, manager=None)


def _ensure_const_nodes():
    """Minimal constant nodes used to feed the outer runner test (a list
    source + an any source for the body payload)."""
    if _get_spec("_test.const_list") is None:
        register(NodeSpec(
            type="_test.const_list", category="_test",
            display_name="Test Const List",
            description="Emits config.value on `value`.",
            inputs=[], outputs=[Port(name="value", type=PortType.LIST)],
            config_schema={}, icon="[",
        ), lambda c, i, x: {"status": "ok", "value": c.get("value")})
    if _get_spec("_test.const_any") is None:
        register(NodeSpec(
            type="_test.const_any", category="_test",
            display_name="Test Const Any",
            description="Emits config.value on `value`.",
            inputs=[], outputs=[Port(name="value", type=PortType.ANY)],
            config_schema={}, icon="*",
        ), lambda c, i, x: {"status": "ok", "value": c.get("value")})
