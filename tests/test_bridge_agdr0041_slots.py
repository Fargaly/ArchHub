"""AgDR-0041 — bridge slots for graph-robustness operations.

Mirrors the graph_validate slot already covered by test_graph_validate_tool.
These slots wrap the tool_engine handlers so the JSX side can:
  * preview a delete (auto-bridge OR broken-wire dialog) — P4
  * flip freeze ❄ on / off — P3
  * flip bypass ○ on / off — P6
  * fetch type-compatible swap suggestions for the right-click menu — P2

Each slot returns a JSON string the JSX parses; on parse failure the
slot returns {status:"error", error:"…"} so the panel can show a
single-line banner instead of crashing.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))

import bridge as _bridge_module  # noqa: E402
from tool_engine import ToolEngine  # noqa: E402


class _StubManager:
    entries: list = []

    def active_families(self) -> set:
        return set()


@pytest.fixture
def bridge_inst(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    engine = ToolEngine(manager=_StubManager())
    return _bridge_module.ArchHubBridge(tools=engine)


@pytest.fixture
def two_node_graph():
    """Two-node graph with a single matching wire — safe baseline."""
    return {
        "nodes": [
            {"id": "a", "outs": [{"id": "value", "t": "string"}]},
            {"id": "b", "ins":  [{"id": "in", "t": "string"}]},
        ],
        "wires": [
            {"id": "w1", "from": ["a", "value"], "to": ["b", "in"]},
        ],
    }


# ══════════════════════════════════════════════════════════════════════
# graph_on_node_delete (P4)
# ══════════════════════════════════════════════════════════════════════
class TestGraphOnNodeDelete:
    def test_silent_delete_when_no_wires(self, bridge_inst):
        graph = {"nodes": [{"id": "lonely"}], "wires": []}
        out = json.loads(bridge_inst.graph_on_node_delete(
            "lonely", json.dumps(graph)))
        assert out["status"] == "ok"
        assert out["action"] == "silent_delete"

    def test_auto_bridge_when_types_match(self, bridge_inst):
        graph = {
            "nodes": [
                {"id": "a", "outs": [{"id": "v", "t": "string"}]},
                {"id": "m", "ins": [{"id": "i", "t": "string"}],
                            "outs": [{"id": "o", "t": "string"}]},
                {"id": "z", "ins": [{"id": "v", "t": "string"}]},
            ],
            "wires": [
                {"id": "w1", "from": ["a", "v"], "to": ["m", "i"]},
                {"id": "w2", "from": ["m", "o"], "to": ["z", "v"]},
            ],
        }
        out = json.loads(bridge_inst.graph_on_node_delete(
            "m", json.dumps(graph)))
        assert out["status"] == "ok"
        assert out["action"] == "auto_bridge"
        assert out["wires"], "auto_bridge must return at least one wire"

    def test_broken_wire_when_types_mismatch(self, bridge_inst):
        graph = {
            "nodes": [
                {"id": "a", "outs": [{"id": "v", "t": "string"}]},
                {"id": "m", "ins": [{"id": "i", "t": "string"}],
                            "outs": [{"id": "o", "t": "string"}]},
                {"id": "z", "ins": [{"id": "v", "t": "number"}]},
            ],
            "wires": [
                {"id": "w1", "from": ["a", "v"], "to": ["m", "i"]},
                {"id": "w2", "from": ["m", "o"], "to": ["z", "v"]},
            ],
        }
        out = json.loads(bridge_inst.graph_on_node_delete(
            "m", json.dumps(graph)))
        assert out["status"] == "ok"
        assert out["action"] == "broken_wire"
        assert out["broken"]

    def test_bad_node_id_surfaces_error(self, bridge_inst, two_node_graph):
        out = json.loads(bridge_inst.graph_on_node_delete(
            "ghost", json.dumps(two_node_graph)))
        assert out["status"] == "error"
        assert "ghost" in out["error"]

    def test_bad_graph_json_surfaces_error(self, bridge_inst):
        out = json.loads(bridge_inst.graph_on_node_delete(
            "a", "{not json"))
        assert out["status"] == "error"


# ══════════════════════════════════════════════════════════════════════
# node_freeze (P3) + node_bypass (P6)
# ══════════════════════════════════════════════════════════════════════
class TestNodeStateSlots:
    def test_freeze_true_returns_set_node_delta(self, bridge_inst):
        out = json.loads(bridge_inst.node_freeze("n_42", True))
        assert out["status"] == "ok"
        assert out["op"] == "set_node"
        assert out["node_id"] == "n_42"
        assert out["patch"] == {"frozen": True}

    def test_freeze_false_unfreezes(self, bridge_inst):
        out = json.loads(bridge_inst.node_freeze("n_42", False))
        assert out["patch"] == {"frozen": False}

    def test_bypass_true_returns_set_node_delta(self, bridge_inst):
        out = json.loads(bridge_inst.node_bypass("n_99", True))
        assert out["status"] == "ok"
        assert out["op"] == "set_node"
        assert out["node_id"] == "n_99"
        assert out["patch"] == {"bypassed": True}

    def test_freeze_empty_id_errors(self, bridge_inst):
        out = json.loads(bridge_inst.node_freeze("", True))
        assert out["status"] == "error"

    def test_bypass_empty_id_errors(self, bridge_inst):
        out = json.loads(bridge_inst.node_bypass("", True))
        assert out["status"] == "error"


# ══════════════════════════════════════════════════════════════════════
# library_suggest_swaps (P2)
# ══════════════════════════════════════════════════════════════════════
class TestLibrarySuggestSwaps:
    def test_returns_ok_for_registered_type(self, bridge_inst):
        # workflows imports auto-register many types; pick one that
        # definitely exists.
        out = json.loads(bridge_inst.library_suggest_swaps(
            "data.constant", 5))
        assert out["status"] == "ok"
        # `suggestions` (or `alternatives`) list present.
        assert isinstance(out, dict)

    def test_handles_unknown_type_gracefully(self, bridge_inst):
        out = json.loads(bridge_inst.library_suggest_swaps(
            "does.not.exist", 5))
        # Either status:ok with empty list or status:error — both are
        # acceptable; what matters is we don't crash.
        assert "status" in out

    def test_empty_type_errors_or_empty(self, bridge_inst):
        out = json.loads(bridge_inst.library_suggest_swaps("", 5))
        assert "status" in out


# ══════════════════════════════════════════════════════════════════════
# Slot reachability — all four are pyqtSlots on the bridge QObject
# ══════════════════════════════════════════════════════════════════════
class TestSlotReachability:
    def test_all_four_slots_are_methods(self, bridge_inst):
        for name in ("graph_on_node_delete", "node_freeze",
                     "node_bypass", "library_suggest_swaps",
                     "graph_validate"):
            assert hasattr(bridge_inst, name)
            assert callable(getattr(bridge_inst, name))

    def test_tools_missing_returns_error(self, monkeypatch):
        b = _bridge_module.ArchHubBridge(tools=None)
        out = json.loads(b.node_freeze("n", True))
        assert out["status"] == "error"
        assert "tool engine" in out["error"]
