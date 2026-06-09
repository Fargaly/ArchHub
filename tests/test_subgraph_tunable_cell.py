"""#5 stem-cell DIFFERENTIATION — a composed cell is a TUNABLE cell.

WHY this exists (founder, 2026-06-09)
-------------------------------------
The stem-cell vision: a user composes a few generic cells and SAVES the
assembly as ONE reusable cell whose inner knobs become its own editable
fields — "a stem cell whose knobs are exposed." Before this, `compose_subgraph`
built a composite with `inner_graph`/`inner_inputs`/`inner_outputs` but NO
`config_schema` and NO knob plumbing, so a composed cell's inner sliders were
baked frozen — a wirable shell, not a differentiable cell (the jury's #5 gap).

THE BUILD (two coordinated halves, both in app/workflows/subgraph.py)
--------------------------------------------------------------------
1. `compose_subgraph` re-surfaces each inner node's SCALAR config as a composite
   knob namespaced ``<innerId>__<key>``: it stamps a top-level ``config_schema``
   (rendered by the rail via `_configSchemaFor` → node.config_schema, the #1
   fix) + a ``config.inner_params`` descriptor list + seeds the knob defaults.
2. `_subgraph_executor` reads ``config.inner_params`` and, when the composite's
   runtime config carries a knob value, pushes it into the matching inner node's
   config BEFORE cooking (deepcopying only the patched inner nodes, so the stored
   inner_graph is never mutated across cooks).

These tests cook REAL composites through the REAL `WorkflowRunner` and assert
the knob actually drives the inner cell — and that the change is additive
(composites with no scalar inner config, and every pre-#5 composite/foreach
body with no `inner_params`, are untouched).
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))

from workflows import nodes as _nodes_pkg  # noqa: F401  registers built-ins
from workflows import subgraph  # noqa: F401  registers subgraph executors
from workflows.runner import WorkflowRunner
from workflows.subgraph import compose_subgraph


# ── helpers ──────────────────────────────────────────────────────────────────
def _const_expr_sink_graph(value=5, expr="a*2"):
    """k(constant=value) → e(expr) → sink(passthrough). Composing {k,e} leaves
    `sink` outside, so e's output crosses the boundary → a real facade output."""
    return {
        "nodes": [
            {"id": "k", "type": "data.constant",
             "config": {"value": value, "value_type": "number"},
             "outs": [{"id": "value"}]},
            {"id": "e", "type": "code.expression", "config": {"expr": expr},
             "ins": [{"id": "a"}], "outs": [{"id": "value"}]},
            {"id": "sink", "type": "data.passthrough",
             "ins": [{"id": "value"}], "outs": [{"id": "value"}]},
        ],
        "wires": [
            {"from": ["k", "value"], "to": ["e", "a"]},
            {"from": ["e", "value"], "to": ["sink", "value"]},
        ],
    }


def _composite_of(graph, ids):
    newg = compose_subgraph(graph, ids)
    comp = next(n for n in newg["nodes"] if n["type"] == "subgraph.user")
    return newg, comp


def _cook_sink(newg, comp_id, knob=None, knob_val=None):
    g = copy.deepcopy(newg)
    comp = next(n for n in g["nodes"] if n["id"] == comp_id)
    if knob is not None:
        comp["config"][knob] = knob_val
    return WorkflowRunner(g).pull("sink")


# ── 1. compose re-surfaces inner scalar config as composite knobs ────────────
def test_compose_derives_config_schema_and_inner_params():
    newg, comp = _composite_of(_const_expr_sink_graph(), ["k", "e"])
    schema = comp.get("config_schema") or {}
    # the constant's `value` + the expression's `expr` are now composite knobs
    assert "k__value" in schema
    assert "e__expr" in schema
    # the knob carries its inferred widget type + seeded default
    assert schema["k__value"]["type"] == "number"
    assert schema["k__value"]["default"] == 5
    # the knob → inner-config descriptor is present + correct
    ips = comp["config"].get("inner_params") or []
    by_param = {ip["param"]: ip for ip in ips}
    assert by_param["k__value"]["inner_node"] == "k"
    assert by_param["k__value"]["inner_key"] == "value"
    # the default value is seeded onto the composite config so the rail shows it
    assert comp["config"]["k__value"] == 5


# ── 2. turning the knob re-cooks the inner cell ──────────────────────────────
def test_knob_drives_inner_cell_on_cook():
    newg, comp = _composite_of(_const_expr_sink_graph(), ["k", "e"])
    cid = comp["id"]
    # default knob (5) → 5*2 = 10
    assert _cook_sink(newg, cid).get("value") == 10
    # turn it → the inner constant re-cooks
    assert _cook_sink(newg, cid, "k__value", 20).get("value") == 40
    assert _cook_sink(newg, cid, "k__value", 7).get("value") == 14


def test_knob_override_does_not_mutate_stored_inner_graph():
    """Cooking with an override must not bleed into the stored inner_graph —
    a second cook at the default must still see the ORIGINAL inner value."""
    newg, comp = _composite_of(_const_expr_sink_graph(), ["k", "e"])
    cid = comp["id"]
    assert _cook_sink(newg, cid, "k__value", 99).get("value") == 198
    # back to default — if the override had mutated inner_graph, this would be 198
    assert _cook_sink(newg, cid).get("value") == 10
    # and the stored inner constant config is still the original 5
    inner = comp["config"]["inner_graph"]["nodes"]
    kconst = next(n for n in inner if n["id"] == "k")
    assert kconst["config"]["value"] == 5


# ── 3. additive: no scalar inner config → no knobs, behaves as before ────────
def test_composite_with_no_scalar_config_has_empty_schema():
    """Two cells with no scalar config produce a composite with an empty
    config_schema + empty inner_params — identical to pre-#5 behaviour."""
    g = {
        "nodes": [
            {"id": "p1", "type": "data.passthrough",
             "ins": [{"id": "value"}], "outs": [{"id": "value"}]},
            {"id": "p2", "type": "data.passthrough",
             "ins": [{"id": "value"}], "outs": [{"id": "value"}]},
            {"id": "snk", "type": "data.passthrough",
             "ins": [{"id": "value"}], "outs": [{"id": "value"}]},
        ],
        "wires": [
            {"from": ["p1", "value"], "to": ["p2", "value"]},
            {"from": ["p2", "value"], "to": ["snk", "value"]},
        ],
    }
    _newg, comp = _composite_of(g, ["p1", "p2"])
    assert (comp.get("config_schema") or {}) == {}
    assert (comp["config"].get("inner_params") or []) == []


def test_pre_existing_composite_without_inner_params_is_unaffected():
    """A subgraph.user node with NO inner_params (every pre-#5 composite + every
    control.foreach body) cooks exactly as before — the override block is a
    no-op when inner_params is absent."""
    newg, comp = _composite_of(_const_expr_sink_graph(), ["k", "e"])
    cid = comp["id"]
    # strip the #5 plumbing to simulate a legacy composite
    g = copy.deepcopy(newg)
    legacy = next(n for n in g["nodes"] if n["id"] == cid)
    legacy["config"].pop("inner_params", None)
    legacy.pop("config_schema", None)
    # even with a stray knob key in config, no inner_params means no override
    legacy["config"]["k__value"] = 999
    out = WorkflowRunner(g).pull("sink")
    assert out.get("value") == 10  # inner constant's ORIGINAL 5 → 5*2, knob ignored


# ── 4. params-only inner nodes: the canvas's real shape (Copilot review #90) ──
def _params_only_graph(kval=5, expr="a*2"):
    """The shape a freshly-placed canvas node actually has: scalar values live
    in `params` (the flat rail); `config` is unset until a cook materialises it.
    The composite must still surface those params as knobs."""
    return {
        "nodes": [
            {"id": "k", "type": "data.constant",
             # NO config key — untouched/just-placed node
             "params": [{"k": "value", "v": kval, "type": "number"},
                        {"k": "value_type", "v": "number", "type": "text"}],
             "outs": [{"id": "value"}]},
            {"id": "e", "type": "code.expression",
             "params": [{"k": "expr", "v": expr, "type": "text"}],
             "ins": [{"id": "a"}], "outs": [{"id": "value"}]},
            {"id": "sink", "type": "data.passthrough",
             "ins": [{"id": "value"}], "outs": [{"id": "value"}]},
        ],
        "wires": [
            {"from": ["k", "value"], "to": ["e", "a"]},
            {"from": ["e", "value"], "to": ["sink", "value"]},
        ],
    }


def test_compose_derives_knobs_from_params_only_nodes():
    """An UNTOUCHED node keeps its default in `params`, not `config` — the
    composite must still derive its `config_schema` knobs (the real-canvas case
    Copilot flagged: deriving from config-only surfaced ZERO knobs)."""
    _newg, comp = _composite_of(_params_only_graph(kval=5), ["k", "e"])
    schema = comp.get("config_schema") or {}
    assert "k__value" in schema, schema          # surfaced from params, no config
    assert schema["k__value"]["type"] == "number"
    assert schema["k__value"]["default"] == 5
    assert "e__expr" in schema
    # seeded default surfaced on the composite config so the rail shows it
    assert comp["config"]["k__value"] == 5


def test_compose_tolerates_non_dict_inner_config():
    """A malformed inner node whose `config` is NOT a dict must not crash knob
    derivation (Copilot: `.items()` on a non-dict raises) — it's ignored and the
    params still surface the knob."""
    g = _params_only_graph(kval=9)
    g["nodes"][0]["config"] = "oops-not-a-dict"   # malformed config on `k`
    _newg, comp = _composite_of(g, ["k", "e"])    # must not raise
    schema = comp.get("config_schema") or {}
    assert "k__value" in schema                   # params still read despite bad config
    assert schema["k__value"]["default"] == 9
