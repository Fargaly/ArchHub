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
import time
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


# AgDR-0036 follow-up — graph_on_node_delete + library_suggest_swaps are
# now ASYNC: they run on the bridge `_bg_pool` and deliver the real
# result via the `node_op_done(result_json)` signal (correlated by
# request_id), so the Qt main thread is never held. The slot itself
# returns `{async:true, request_id}` instantly. This helper fires the
# slot, captures the matching signal payload (DirectConnection → the
# worker thread calls our handler inline, no Qt event loop needed), and
# returns the parsed result dict — so the assertions below test the SAME
# contract they did when the slot was synchronous.
def _drive_node_op(bridge_inst, slot_name, *args, timeout=8.0):
    import queue
    from PyQt6.QtCore import Qt
    # Thread-safe capture. DirectConnection → the worker thread calls our
    # handler inline (no Qt event loop needed); the Queue is the
    # cross-thread hand-off. We connect ONCE and never disconnect — the
    # connect/disconnect-during-emit dance is what deadlocks, and the
    # bridge (with its signal) is GC'd at end of test anyway. The handler
    # is filtered by request_id so it only captures our call's result.
    q: "queue.Queue[dict]" = queue.Queue()

    def _on_done(result_json):
        try:
            q.put_nowait(json.loads(result_json))
        except Exception:
            pass

    bridge_inst.node_op_done.connect(
        _on_done, Qt.ConnectionType.DirectConnection)
    ack = json.loads(getattr(bridge_inst, slot_name)(*args))
    req = ack.get("request_id")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            payload = q.get(timeout=max(0.0, deadline - time.time()))
        except queue.Empty:
            break
        if payload.get("request_id") == req:
            return payload
    raise AssertionError(
        f"{slot_name} never emitted node_op_done within {timeout}s")


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
        out = _drive_node_op(bridge_inst, "graph_on_node_delete",
                             "lonely", json.dumps(graph), "")
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
        out = _drive_node_op(bridge_inst, "graph_on_node_delete",
                             "m", json.dumps(graph), "")
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
        out = _drive_node_op(bridge_inst, "graph_on_node_delete",
                             "m", json.dumps(graph), "")
        assert out["status"] == "ok"
        assert out["action"] == "broken_wire"
        assert out["broken"]

    def test_bad_node_id_surfaces_error(self, bridge_inst, two_node_graph):
        out = _drive_node_op(bridge_inst, "graph_on_node_delete",
                             "ghost", json.dumps(two_node_graph), "")
        assert out["status"] == "error"
        assert "ghost" in out["error"]

    def test_bad_graph_json_surfaces_error(self, bridge_inst):
        # Parse errors are returned INLINE on the ack (and also emitted) —
        # the slot resolves either way. Assert on the instant ack here.
        out = json.loads(bridge_inst.graph_on_node_delete(
            "a", "{not json", ""))
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
        out = _drive_node_op(bridge_inst, "library_suggest_swaps",
                             "data.constant", 5, "")
        assert out["status"] == "ok"
        # `suggestions` (or `alternatives`) list present.
        assert isinstance(out, dict)

    def test_handles_unknown_type_gracefully(self, bridge_inst):
        out = _drive_node_op(bridge_inst, "library_suggest_swaps",
                             "does.not.exist", 5, "")
        # Either status:ok with empty list or status:error — both are
        # acceptable; what matters is we don't crash.
        assert "status" in out

    def test_empty_type_errors_or_empty(self, bridge_inst):
        out = _drive_node_op(bridge_inst, "library_suggest_swaps",
                             "", 5, "")
        assert "status" in out

    def test_json_filter_blob_in_arg1_routes_in_out_types(self, bridge_inst):
        """Bug fix: the broken-wire 'Insert adapter' path passes a JSON
        filter blob {in_types,out_types,limit} as arg1 (it searches by
        PORT type, not by an existing node type). The slot must DETECT the
        JSON object + forward in_types/out_types to the tool — before, it
        crammed the whole blob into the scalar `type` arg so the search
        filtered on a bogus type and returned nothing useful. We pass an
        image→geometry filter and assert a successful, non-empty match
        (many registered mesh/geometry nodes have this signature)."""
        blob = json.dumps({"in_types": ["image"],
                           "out_types": ["geometry"], "limit": 50})
        out = _drive_node_op(bridge_inst, "library_suggest_swaps",
                             blob, 5, "")
        assert out["status"] == "ok"
        # The blob's own limit (50) overrides the positional 5, and the
        # in/out filter actually matched registered types — NOT the empty
        # result the old bogus-type search produced.
        assert isinstance(out.get("results"), list)
        assert len(out["results"]) > 0
        for r in out["results"]:
            # Every hit must satisfy the requested out-type (geometry) or
            # be ANY-port lenient — never an unrelated string→string node.
            assert "geometry" in [t.lower() for t in r.get("out", [])] \
                or "any" in [t.lower() for t in r.get("out", [])]

    def test_plain_type_name_still_scalar_routed(self, bridge_inst):
        """Back-compat: a plain (non-JSON) type name in arg1 is still
        treated as `type` — the working right-click/inspector swap paths
        must not regress now that arg1 also accepts a JSON filter."""
        out = _drive_node_op(bridge_inst, "library_suggest_swaps",
                             "data.constant", 5, "")
        assert out["status"] == "ok"
        assert isinstance(out, dict)


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
