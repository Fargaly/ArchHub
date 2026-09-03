"""AgDR-0041 P5 — tool_engine.graph_validate.

The Composer + the canvas UI both call the live validator. Tests cover
the dict-native handler accepting the JSX-style graph snapshot
({nodes:[{id, ins, outs}], wires:[{from, to}]}).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from tool_engine import ToolEngine, TOOLS  # noqa: E402


class _StubManager:
    entries: list = []

    def active_families(self) -> set:
        return set()


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    return ToolEngine(manager=_StubManager())


# ── tool registration ─────────────────────────────────────────────────


def test_graph_validate_tool_registered():
    """LLM must see graph_validate in the tool surface."""
    names = {t["name"] for t in TOOLS}
    assert "graph_validate" in names


def test_graph_validate_routes_through_node_handler(engine):
    """Dispatch should route handler='graph_validate' to node handler."""
    out = engine._invoke_node_handler("graph_validate", {"graph": {
        "nodes": [], "wires": []}})
    assert out["status"] == "ok"
    assert out["valid"] is True
    assert out["errors"] == 0


# ── empty + happy-path ────────────────────────────────────────────────


def test_validate_empty_graph_is_valid(engine):
    out = engine._invoke_node_handler("graph_validate", {"graph": {}})
    assert out["status"] == "ok"
    assert out["issues"] == []
    assert out["errors"] == 0
    assert out["valid"] is True


def test_validate_clean_jsx_graph_passes(engine):
    """One wire string→string between two nodes — no issues."""
    graph = {
        "nodes": [
            {"id": "a", "outs": [{"id": "out", "t": "string"}]},
            {"id": "b", "ins":  [{"id": "in",  "t": "string"}]},
        ],
        "wires": [
            {"id": "w1", "from": ["a", "out"], "to": ["b", "in"]},
        ],
    }
    out = engine._invoke_node_handler("graph_validate", {"graph": graph})
    assert out["status"] == "ok"
    assert out["valid"] is True
    assert out["issues"] == []


# ── individual issue codes ────────────────────────────────────────────


def test_duplicate_node_id_flagged(engine):
    graph = {
        "nodes": [{"id": "a"}, {"id": "a"}],
        "wires": [],
    }
    out = engine._invoke_node_handler("graph_validate", {"graph": graph})
    codes = {iss["code"] for iss in out["issues"]}
    assert "duplicate_id" in codes
    assert out["valid"] is False


def test_missing_src_node_flagged(engine):
    graph = {
        "nodes": [{"id": "b", "ins": [{"id": "in", "t": "string"}]}],
        "wires": [{"id": "w1", "from": ["ghost", "out"], "to": ["b", "in"]}],
    }
    out = engine._invoke_node_handler("graph_validate", {"graph": graph})
    codes = {iss["code"] for iss in out["issues"]}
    assert "missing_src" in codes
    assert out["valid"] is False


def test_missing_dst_node_flagged(engine):
    graph = {
        "nodes": [{"id": "a", "outs": [{"id": "out", "t": "string"}]}],
        "wires": [{"id": "w1", "from": ["a", "out"], "to": ["ghost", "in"]}],
    }
    out = engine._invoke_node_handler("graph_validate", {"graph": graph})
    codes = {iss["code"] for iss in out["issues"]}
    assert "missing_dst" in codes


def test_unknown_src_port_flagged(engine):
    graph = {
        "nodes": [
            {"id": "a", "outs": [{"id": "out", "t": "string"}]},
            {"id": "b", "ins":  [{"id": "in",  "t": "string"}]},
        ],
        "wires": [{"id": "w1", "from": ["a", "ghost"], "to": ["b", "in"]}],
    }
    out = engine._invoke_node_handler("graph_validate", {"graph": graph})
    codes = {iss["code"] for iss in out["issues"]}
    assert "unknown_src_port" in codes


def test_unknown_dst_port_flagged(engine):
    graph = {
        "nodes": [
            {"id": "a", "outs": [{"id": "out", "t": "string"}]},
            {"id": "b", "ins":  [{"id": "in",  "t": "string"}]},
        ],
        "wires": [{"id": "w1", "from": ["a", "out"], "to": ["b", "ghost"]}],
    }
    out = engine._invoke_node_handler("graph_validate", {"graph": graph})
    codes = {iss["code"] for iss in out["issues"]}
    assert "unknown_dst_port" in codes


def test_type_mismatch_flagged(engine):
    """string → number is an error; both sides typed, neither 'any'."""
    graph = {
        "nodes": [
            {"id": "a", "outs": [{"id": "out", "t": "string"}]},
            {"id": "b", "ins":  [{"id": "in",  "t": "number"}]},
        ],
        "wires": [{"id": "w1", "from": ["a", "out"], "to": ["b", "in"]}],
    }
    out = engine._invoke_node_handler("graph_validate", {"graph": graph})
    codes = {iss["code"] for iss in out["issues"]}
    assert "type_mismatch" in codes
    assert out["valid"] is False
    assert out["errors"] >= 1


def test_any_port_skips_type_mismatch(engine):
    """'any' on either end accepts anything — no mismatch flagged."""
    graph = {
        "nodes": [
            {"id": "a", "outs": [{"id": "out", "t": "string"}]},
            {"id": "b", "ins":  [{"id": "in",  "t": "any"}]},
        ],
        "wires": [{"id": "w1", "from": ["a", "out"], "to": ["b", "in"]}],
    }
    out = engine._invoke_node_handler("graph_validate", {"graph": graph})
    assert out["valid"] is True


def test_required_unset_input_is_warn_not_err(engine):
    """Required input with no incoming wire → warn (cook may proceed)."""
    graph = {
        "nodes": [
            {"id": "a", "ins": [{"id": "in", "t": "string", "required": True}]},
        ],
        "wires": [],
    }
    out = engine._invoke_node_handler("graph_validate", {"graph": graph})
    codes = {iss["code"] for iss in out["issues"]}
    assert "unset_input" in codes
    assert out["valid"] is True  # warn-only does NOT block cook
    assert out["warnings"] >= 1
    assert out["errors"] == 0


# ── shape compatibility (Workflow-style edges) ────────────────────────


def test_workflow_style_edges_also_accepted(engine):
    """Edges with {src_node,src_port,dst_node,dst_port} also work."""
    graph = {
        "nodes": [
            {"id": "a", "outs": [{"id": "out", "t": "string"}]},
            {"id": "b", "ins":  [{"id": "in",  "t": "string"}]},
        ],
        "edges": [
            {"id": "w1",
              "src_node": "a", "src_port": "out",
              "dst_node": "b", "dst_port": "in"},
        ],
    }
    out = engine._invoke_node_handler("graph_validate", {"graph": graph})
    assert out["valid"] is True


def test_workflow_style_inputs_outputs_also_accepted(engine):
    """Ports as {name, type} (Workflow) also work alongside JSX ids."""
    graph = {
        "nodes": [
            {"id": "a", "outputs": [{"name": "out", "type": "string"}]},
            {"id": "b", "inputs":  [{"name": "in",  "type": "string"}]},
        ],
        "edges": [
            {"id": "w1",
              "src_node": "a", "src_port": "out",
              "dst_node": "b", "dst_port": "in"},
        ],
    }
    out = engine._invoke_node_handler("graph_validate", {"graph": graph})
    assert out["valid"] is True
    assert out["issues"] == []
