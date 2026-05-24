"""AgDR-0041 Property 5 — live validator (structured issues).

validate_v2 returns [{level, code, node_id, edge_id, msg}] so the
canvas can colour wires + nodes green / yellow / red on every edit
without waiting for a cook.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from workflows.graph import (  # noqa: E402
    Workflow, Node, Edge, Port, PortType,
)


def _wf(nodes, edges):
    return Workflow(id="t", name="t", nodes=nodes, edges=edges)


def _node(nid, ins=None, outs=None):
    return Node(id=nid, type="x",
                inputs=ins or [], outputs=outs or [],
                config={})


def _port(name, t=PortType.ANY, required=False):
    return Port(name=name, type=t, required=required)


def _edge(eid, src, sp, dst, dp):
    return Edge(id=eid, src_node=src, src_port=sp,
                dst_node=dst, dst_port=dp)


# ── happy path ─────────────────────────────────────────────────────


def test_clean_graph_has_no_issues():
    wf = _wf(
        nodes=[
            _node("a", outs=[_port("v", PortType.NUMBER)]),
            _node("b", ins=[_port("v", PortType.NUMBER)]),
        ],
        edges=[_edge("e1", "a", "v", "b", "v")],
    )
    assert wf.validate_v2() == []


# ── err: type mismatch ─────────────────────────────────────────────


def test_type_mismatch_is_err():
    wf = _wf(
        nodes=[
            _node("a", outs=[_port("v", PortType.GEOMETRY)]),
            _node("b", ins=[_port("v", PortType.IMAGE)]),
        ],
        edges=[_edge("e1", "a", "v", "b", "v")],
    )
    issues = wf.validate_v2()
    assert any(i["code"] == "type_mismatch" and i["level"] == "err"
               for i in issues)


def test_any_type_is_compatible_with_anything():
    wf = _wf(
        nodes=[
            _node("a", outs=[_port("v", PortType.ANY)]),
            _node("b", ins=[_port("v", PortType.IMAGE)]),
        ],
        edges=[_edge("e1", "a", "v", "b", "v")],
    )
    assert wf.validate_v2() == []


# ── warn: required input unset ─────────────────────────────────────


def test_required_input_unset_is_warn():
    wf = _wf(
        nodes=[
            _node("b", ins=[_port("v", PortType.NUMBER, required=True)]),
        ],
        edges=[],
    )
    issues = wf.validate_v2()
    assert any(i["code"] == "unset_input" and i["level"] == "warn"
               for i in issues)


def test_optional_input_unset_is_silent():
    wf = _wf(
        nodes=[_node("b", ins=[_port("v", PortType.NUMBER)])],
        edges=[],
    )
    assert wf.validate_v2() == []


# ── err: unknown ports / missing nodes ─────────────────────────────


def test_unknown_dst_port_is_err():
    wf = _wf(
        nodes=[
            _node("a", outs=[_port("v")]),
            _node("b", ins=[_port("v")]),
        ],
        edges=[_edge("e1", "a", "v", "b", "wrong")],
    )
    issues = wf.validate_v2()
    assert any(i["code"] == "unknown_dst_port" for i in issues)


def test_missing_node_is_err():
    wf = _wf(
        nodes=[_node("a", outs=[_port("v")])],
        edges=[_edge("e1", "a", "v", "ghost", "v")],
    )
    issues = wf.validate_v2()
    assert any(i["code"] == "missing_dst" for i in issues)


# ── back-compat ────────────────────────────────────────────────────


def test_validate_returns_only_err_strings():
    """Old callers expect list[str] of errors. validate_v2 warns are
    suppressed from validate() so partial-input nodes still cook."""
    wf = _wf(
        nodes=[
            _node("a", outs=[_port("v", PortType.NUMBER)]),
            _node("b", ins=[_port("v", PortType.NUMBER, required=True)]),
        ],
        edges=[],  # unset required input → warn only
    )
    assert wf.validate() == []
    # but issues are present
    issues = wf.validate_v2()
    assert len(issues) >= 1
    assert issues[0]["level"] == "warn"
