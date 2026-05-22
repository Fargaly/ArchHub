"""AgDR-0038 slice 3 — Composer Capability Node tools.

node_search / node_create on the ToolEngine — the surface the Composer
uses to mint + find Capability Nodes as data, with zero per-node dev.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from tool_engine import ToolEngine  # noqa: E402


class _StubManager:
    entries: list = []

    def active_families(self) -> set:
        return set()


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """custom_nodes.write_spec persists under %LOCALAPPDATA%/ArchHub —
    redirect it to tmp so the test never touches the real store. Both
    LOCALAPPDATA and XDG_DATA_HOME so Windows + POSIX runners isolate."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    yield


@pytest.fixture
def engine():
    return ToolEngine(manager=_StubManager())


def _cap_spec(type_name: str = "pdf.extract_revisions") -> dict:
    return {
        "type": type_name,
        "category": "document",
        "display_name": "PDF Revision Table",
        "description": "Extract a redline revision table from a drawing PDF.",
        "inputs": [{"name": "drawing_no", "type": "string"}],
        "outputs": [{"name": "revisions", "type": "object"}],
        "impl": {"kind": "passthrough"},
    }


# ─── node_create ────────────────────────────────────────────────────


def test_node_create_registers_capability(engine):
    out = engine._invoke_node_handler("node_create", {"spec": _cap_spec()})
    assert out["status"] == "ok"
    assert out["type"] == "pdf.extract_revisions"
    assert out["inputs"] == ["drawing_no"]
    assert out["outputs"] == ["revisions"]


def test_node_create_rejects_spec_without_type(engine):
    out = engine._invoke_node_handler(
        "node_create", {"spec": {"category": "x"}})
    assert out["status"] == "error"


def test_node_create_makes_node_executable(engine):
    """A node_create'd Capability registers a real executor in the
    workflow registry — it is immediately runnable + placeable."""
    engine._invoke_node_handler("node_create", {"spec": _cap_spec("cap.run")})
    import workflows.registry as _reg
    assert "cap.run" in _reg._REGISTRY


def test_node_create_persists_to_disk(engine):
    engine._invoke_node_handler("node_create", {"spec": _cap_spec("cap.disk")})
    import workflows.custom_nodes as _cn
    files = list(_cn.custom_nodes_dir().glob("*.json"))
    assert any(f.stem == "cap.disk" for f in files)


# ─── node_search ────────────────────────────────────────────────────


def test_node_search_finds_created_node(engine):
    engine._invoke_node_handler("node_create", {"spec": _cap_spec()})
    out = engine._invoke_node_handler(
        "node_search", {"intent": "revision table"})
    assert out["status"] == "ok"
    assert any(r["type"] == "pdf.extract_revisions" for r in out["results"])


def test_node_search_empty_intent_returns_nothing(engine):
    out = engine._invoke_node_handler("node_search", {"intent": "   "})
    assert out["status"] == "ok" and out["count"] == 0


def test_node_search_ranks_by_relevance(engine):
    engine._invoke_node_handler("node_create", {"spec": _cap_spec()})
    engine._invoke_node_handler("node_create", {"spec": {
        "type": "math.add", "category": "logic",
        "display_name": "Add", "description": "Sum two numbers together.",
        "outputs": [{"name": "sum", "type": "number"}],
        "impl": {"kind": "passthrough"},
    }})
    out = engine._invoke_node_handler("node_search", {"intent": "revision"})
    assert out["results"][0]["type"] == "pdf.extract_revisions"


# ─── search -> create round-trip (the Composer's LIBRARY-FIRST loop) ─


def test_search_then_create_then_search_round_trip(engine):
    # First search — nothing yet.
    assert engine._invoke_node_handler(
        "node_search", {"intent": "revision"})["count"] == 0
    # Mint it.
    engine._invoke_node_handler("node_create", {"spec": _cap_spec()})
    # Second search now finds it — reuse beats a duplicate next turn.
    again = engine._invoke_node_handler("node_search", {"intent": "revision"})
    assert again["count"] == 1


# ─── slice 3b — node_place ──────────────────────────────────────────


def test_node_place_emits_add_node_delta(engine):
    engine._invoke_node_handler("node_create", {"spec": _cap_spec("place.me")})
    out = engine._invoke_node_handler(
        "node_place", {"type": "place.me", "x": 120, "y": 340})
    assert out["status"] == "ok" and out["op"] == "add_node"
    node = out["node"]
    assert node["type"] == "place.me"
    assert node["id"] == out["node_id"] and node["id"].startswith("n_")
    assert node["x"] == 120 and node["y"] == 340
    assert [p["name"] for p in node["inputs"]] == ["drawing_no"]
    assert [p["name"] for p in node["outputs"]] == ["revisions"]


def test_node_place_unregistered_type_is_error(engine):
    out = engine._invoke_node_handler("node_place", {"type": "no.such.type"})
    assert out["status"] == "error" and "not registered" in out["error"]


def test_node_place_needs_a_type(engine):
    out = engine._invoke_node_handler("node_place", {})
    assert out["status"] == "error"


# ─── slice 3b — graph_wire ──────────────────────────────────────────


def test_graph_wire_emits_add_wire_delta(engine):
    out = engine._invoke_node_handler("graph_wire", {
        "src_node": "n_a", "src_port": "out",
        "dst_node": "n_b", "dst_port": "in"})
    assert out["status"] == "ok" and out["op"] == "add_wire"
    assert out["wire"] == {"from": ["n_a", "out"], "to": ["n_b", "in"]}


def test_graph_wire_missing_args_is_error(engine):
    out = engine._invoke_node_handler("graph_wire", {
        "src_node": "n_a", "src_port": "out", "dst_node": "n_b"})
    assert out["status"] == "error"


def test_graph_wire_rejects_self_wire(engine):
    out = engine._invoke_node_handler("graph_wire", {
        "src_node": "n_a", "src_port": "out",
        "dst_node": "n_a", "dst_port": "in"})
    assert out["status"] == "error" and "itself" in out["error"]
