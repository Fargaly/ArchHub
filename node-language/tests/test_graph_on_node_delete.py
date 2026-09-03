"""AgDR-0041 P4 — delete-with-auto-bridge analyzer.

The UI asks `graph_on_node_delete(node_id, graph)` BEFORE removing
a node. The tool returns one of:
  - silent_delete  — no incident wires, just drop the node
  - auto_bridge    — upstream type matches downstream, rewire silently
  - broken_wire    — type mismatch, show recovery dialog
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from tool_engine import ToolEngine  # noqa: E402


class _StubMgr:
    entries: list = []

    def active_families(self) -> set:
        return set()


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    return ToolEngine(manager=_StubMgr())


def _call(engine, node_id, graph):
    return engine._invoke_node_handler(
        "graph_on_node_delete",
        {"node_id": node_id, "graph": graph})


def _node(nid, ins=(), outs=()):
    return {"id": nid, "type": "x",
            "ins":  [{"id": n, "t": t} for n, t in ins],
            "outs": [{"id": n, "t": t} for n, t in outs]}


def _wire(src, sp, dst, dp):
    return {"src_node": src, "src_port": sp,
            "dst_node": dst, "dst_port": dp}


# ── silent_delete ──────────────────────────────────────────────────


def test_isolated_node_silent_delete(engine):
    g = {"nodes": [_node("a"), _node("b")], "wires": []}
    out = _call(engine, "a", g)
    assert out["action"] == "silent_delete"


# ── auto_bridge ────────────────────────────────────────────────────


def test_compatible_types_auto_bridge(engine):
    g = {
        "nodes": [
            _node("a", outs=[("v", "image")]),
            _node("m", ins=[("v", "image")], outs=[("v", "image")]),
            _node("b", ins=[("v", "image")]),
        ],
        "wires": [_wire("a", "v", "m", "v"), _wire("m", "v", "b", "v")],
    }
    out = _call(engine, "m", g)
    assert out["action"] == "auto_bridge"
    assert len(out["wires"]) == 1
    assert out["wires"][0]["from"] == ["a", "v"]
    assert out["wires"][0]["to"] == ["b", "v"]


def test_any_type_is_compatible(engine):
    g = {
        "nodes": [
            _node("a", outs=[("v", "image")]),
            _node("m", ins=[("v", "any")], outs=[("v", "any")]),
            _node("b", ins=[("v", "image")]),
        ],
        "wires": [_wire("a", "v", "m", "v"), _wire("m", "v", "b", "v")],
    }
    out = _call(engine, "m", g)
    assert out["action"] == "auto_bridge"


# ── broken_wire ────────────────────────────────────────────────────


def test_type_mismatch_broken_wire(engine):
    g = {
        "nodes": [
            _node("a", outs=[("v", "geometry")]),
            _node("m", ins=[("v", "geometry")], outs=[("v", "image")]),
            _node("b", ins=[("v", "image")]),  # incompatible w/ geometry
        ],
        "wires": [_wire("a", "v", "m", "v"), _wire("m", "v", "b", "v")],
    }
    out = _call(engine, "m", g)
    assert out["action"] == "broken_wire"
    assert len(out["broken"]) == 1
    assert out["broken"][0]["src"][2] == "geometry"
    assert out["broken"][0]["dst"][2] == "image"


# ── error cases ────────────────────────────────────────────────────


def test_missing_node_id_errors(engine):
    out = _call(engine, "", {"nodes": [], "wires": []})
    assert out["status"] == "error"


def test_unknown_node_errors(engine):
    out = _call(engine, "ghost", {"nodes": [_node("a")], "wires": []})
    assert out["status"] == "error"
    assert "ghost" in out["error"]
