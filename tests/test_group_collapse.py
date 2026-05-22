"""Slice C2 — group collapse + boundary-port auto-promotion.

Reference: AgDR-0005. Collapse is a PURE-VISUAL + WIRE-REWRITE
mechanism. The engine never sees groups — `expand_collapsed_groups`
rewrites every wire endpoint referencing a `<gid>:in|out:<i>` socket
back to the underlying member-port, so the runner cooks the same
flat graph whether collapsed or expanded.

These tests pin:
  1. Boundary detection (no wire / external wire / internal wire).
  2. Wire-rewrite idempotency on uncollapsed graphs.
  3. Wire-rewrite correctness on collapsed graphs.
  4. End-to-end cook equivalence (collapsed == expanded).
"""
from __future__ import annotations

import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from workflows.node_grammar import (  # noqa: E402
    _promoted_ports_for,
    expand_collapsed_groups,
    normalize_canvas_graph,
)


# ─── 1. boundary-port detection ──────────────────────────────────────


def test_promoted_ports_no_wires_promotes_every_port():
    """A 2-member group with NO wires — every member port is boundary."""
    nodes = [
        {"id": "n1", "kind": "number", "type": "data.constant",
         "config": {"value": 1, "value_type": "number"}},
        {"id": "n2", "kind": "number", "type": "data.constant",
         "config": {"value": 2, "value_type": "number"}},
    ]
    group = {"id": "g1", "nodeIds": ["n1", "n2"], "collapsed": True}
    promoted = _promoted_ports_for(group, nodes, [])
    # data.constant has 0 inputs + 1 output → 2 outs total, 0 ins.
    out_members = [p["memberId"] for p in promoted["outs"]]
    assert "n1" in out_members
    assert "n2" in out_members
    assert promoted["ins"] == []


def test_promoted_ports_internal_wire_hidden():
    """A wire between two group members is NOT a boundary — its ports
    don't promote. Verifies: internal-wire test = both endpoints in
    member set."""
    nodes = [
        {"id": "a", "kind": "number", "type": "data.constant",
         "config": {"value": 1, "value_type": "number"}},
        {"id": "b", "kind": "number", "type": "data.passthrough",
         "config": {}},
    ]
    wires = [{"from": ["a", "value"], "to": ["b", "value"]}]
    group = {"id": "g1", "nodeIds": ["a", "b"], "collapsed": True}
    promoted = _promoted_ports_for(group, nodes, wires)
    # a's output goes INTO b (internal). b's input comes from a (internal).
    # → No internal promotion for these. But data.passthrough has
    # 1 input + 1 output; its OUTPUT is unconnected → boundary out.
    # data.constant 'a' has 1 output going INSIDE → NOT promoted.
    out_members = [(p["memberId"], p["portName"]) for p in promoted["outs"]]
    in_members = [(p["memberId"], p["portName"]) for p in promoted["ins"]]
    assert ("b", "value") in out_members  # passthrough out → boundary
    assert ("a", "value") not in out_members  # constant out → INTERNAL
    assert ("b", "value") not in in_members  # passthrough in → INTERNAL


def test_promoted_ports_external_wire_endpoint_promotes():
    """A wire whose counter-end is OUTSIDE the group → that endpoint
    promotes. External-source feeding a group member: the member's
    input promotes."""
    nodes = [
        {"id": "ext", "kind": "number", "type": "data.constant",
         "config": {"value": 42, "value_type": "number"}},
        {"id": "m", "kind": "number", "type": "data.passthrough",
         "config": {}},
    ]
    wires = [{"from": ["ext", "value"], "to": ["m", "value"]}]
    # Group contains only `m`. The `ext→m` wire's counter-end (ext)
    # is OUTSIDE the group → m's `value` input is boundary.
    group = {"id": "g1", "nodeIds": ["m"], "collapsed": True}
    promoted = _promoted_ports_for(group, nodes, wires)
    in_members = [(p["memberId"], p["portName"]) for p in promoted["ins"]]
    assert ("m", "value") in in_members


def test_promoted_ports_socket_id_indexed():
    """Socket id encoding = `<groupId>:in:<idx>` / `:out:<idx>` with
    deterministic ordering."""
    nodes = [
        {"id": "n", "kind": "number", "type": "data.constant",
         "config": {"value": 1, "value_type": "number"}},
    ]
    group = {"id": "g42", "nodeIds": ["n"], "collapsed": True}
    promoted = _promoted_ports_for(group, nodes, [])
    assert promoted["outs"][0]["groupSocket"] == "g42:out:0"


# ─── 2. expand-on-uncollapsed = no-op ─────────────────────────────────


def test_expand_idempotent_when_no_group_collapsed():
    """No collapsed group → `expand_collapsed_groups` returns the input
    unchanged."""
    graph = {
        "nodes": [{"id": "x", "kind": "number"}],
        "wires": [],
        "groups": [{"id": "g1", "nodeIds": ["x"], "collapsed": False}],
    }
    out = expand_collapsed_groups(graph)
    assert out is graph  # exact same object — early return


def test_expand_idempotent_when_no_groups_field():
    """Graph without `groups` field — pre-pass is a no-op."""
    graph = {"nodes": [], "wires": []}
    out = expand_collapsed_groups(graph)
    assert out is graph


# ─── 3. wire-rewrite correctness ─────────────────────────────────────


def test_expand_rewrites_collapsed_socket_endpoints():
    """A wire targeting `<gid>:in:0` becomes a wire targeting the
    underlying `(memberId, portName)`."""
    # Setup: ext-source feeds the (collapsed) group's promoted input.
    # The group contains a single passthrough `m`; its input `value`
    # is boundary → promotes to `g1:in:0`.
    nodes = [
        {"id": "ext", "kind": "number", "type": "data.constant",
         "config": {"value": 99, "value_type": "number"}},
        {"id": "m", "kind": "number", "type": "data.passthrough",
         "config": {}},
    ]
    # Wire references the GROUP socket id (as the JSX render would emit
    # post-collapse when the user authors the canvas).
    wires = [{"from": ["ext", "value"], "to": ["g1:in:0", ""]}]
    groups = [{"id": "g1", "nodeIds": ["m"], "collapsed": True}]
    graph = {"nodes": nodes, "wires": wires, "groups": groups}
    out = expand_collapsed_groups(graph)
    rewired = out["wires"][0]
    assert rewired["to"] == ["m", "value"]


def test_expand_does_not_touch_non_group_wires():
    """Wires not referencing a group socket are passed through."""
    nodes = [
        {"id": "ext", "kind": "number", "type": "data.constant",
         "config": {"value": 1, "value_type": "number"}},
        {"id": "m", "kind": "number", "type": "data.passthrough",
         "config": {}},
        {"id": "y", "kind": "number", "type": "data.passthrough",
         "config": {}},
    ]
    wires = [
        # group socket → should rewrite to ("m", "value")
        {"from": ["ext", "value"], "to": ["g1:in:0", ""]},
        # un-related wire → must pass through unchanged
        {"from": ["m", "value"], "to": ["y", "value"]},
    ]
    groups = [{"id": "g1", "nodeIds": ["m"], "collapsed": True}]
    out = expand_collapsed_groups(
        {"nodes": nodes, "wires": wires, "groups": groups})
    assert out["wires"][1] == {"from": ["m", "value"], "to": ["y", "value"]}


# ─── 4. end-to-end cook equivalence ──────────────────────────────────


def test_collapsed_graph_cooks_same_as_expanded():
    """The same upstream input produces the same downstream cooked
    value whether the group is collapsed or expanded."""
    from workflows.runner import WorkflowRunner

    # ext (42) → m (passthrough) → out — value flows through.
    expanded = {
        "nodes": [
            {"id": "ext", "type": "data.constant",
             "config": {"value": 42}},
            {"id": "m", "type": "data.passthrough", "config": {}},
            {"id": "out", "type": "data.passthrough", "config": {}},
        ],
        "wires": [
            {"from": ["ext", "value"], "to": ["m", "value"]},
            {"from": ["m", "value"], "to": ["out", "value"]},
        ],
        "groups": [{"id": "g1", "nodeIds": ["m"], "collapsed": False}],
    }
    collapsed = {
        **expanded,
        # Same nodes, but the wires from ext + to out reference the
        # group sockets:
        "wires": [
            {"from": ["ext", "value"], "to": ["g1:in:0", ""]},
            {"from": ["g1:out:0", ""], "to": ["out", "value"]},
        ],
        "groups": [{"id": "g1", "nodeIds": ["m"], "collapsed": True}],
    }

    def cook(graph):
        g = normalize_canvas_graph(graph)
        r = WorkflowRunner(g)
        return r.run_all()

    ge = cook(expanded)
    gc = cook(collapsed)
    # `out` is the sink — pull returns its cooked envelope.
    assert ge["results"]["out"].get("value") == 42
    assert gc["results"]["out"].get("value") == 42
