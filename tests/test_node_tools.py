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
    import library
    library.reset_registry()
    yield
    library.reset_registry()


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


def _modular_spec(type_name: str = "demo.modular_cap") -> dict:
    """A spec that satisfies the strict library modularity contract —
    long description, an example, typed I/O — so node_create promotes
    it into the library inventory."""
    return {
        "type": type_name,
        "display_name": "Demo Modular Capability",
        "category": "shape",
        "inputs": [],
        "outputs": [{"name": "value", "port_type": "any"}],
        "config_schema": {"properties": {"x": {"type": "string"}}},
        "description": ("A modular Capability Node used to prove node_create "
                        "auto-promotes a well-formed spec into the library "
                        "inventory so future turns can reuse it."),
        "examples": [{"input": {}, "output": {"value": "x"}, "note": "happy"}],
        "side_effects": "pure",
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


# ─── slice 4 — search-first refusal + library auto-promotion ────────


def test_node_create_refuses_near_duplicate(engine):
    """LIBRARY-FIRST — a near-identical Capability Node (same intent,
    different type) is refused; the Composer must reuse the original."""
    engine._invoke_node_handler("node_create", {"spec": _cap_spec("pdf.rev_a")})
    out = engine._invoke_node_handler("node_create", {"spec": _cap_spec("pdf.rev_b")})
    assert out["status"] == "error" and out["code"] == "duplicate"
    assert out["reuse"] == "pdf.rev_a"


def test_node_create_same_type_is_an_update_not_a_dup(engine):
    engine._invoke_node_handler("node_create", {"spec": _cap_spec("pdf.same")})
    again = engine._invoke_node_handler(
        "node_create", {"spec": _cap_spec("pdf.same")})
    assert again["status"] == "ok"   # same type = update, allowed


def test_node_create_promotes_modular_spec_to_library(engine):
    """A well-formed Capability spec auto-registers into the library —
    the library grows by use (AgDR-0038 Delta 3)."""
    out = engine._invoke_node_handler(
        "node_create", {"spec": _modular_spec()})
    assert out["status"] == "ok"
    assert out["library_promoted"] is True
    import library as _lib
    assert any(r["type"] == "demo.modular_cap"
               for r in _lib.search("modular capability"))


def test_node_create_nonmodular_spec_still_works_unpromoted(engine):
    """A thin spec is still a working, executable node — it just is not
    library-promoted until it meets the modularity bar."""
    out = engine._invoke_node_handler(
        "node_create", {"spec": _cap_spec("c.thin")})
    assert out["status"] == "ok"
    assert out["library_promoted"] is False


# ─── AgDR-0039 slice 4 — node_create steers toward graph ────────────


def test_node_create_python_gets_graph_hint(engine):
    """A python node still mints, but the result nudges toward graph."""
    spec = {"type": "py.leaf", "category": "logic",
            "display_name": "Py Leaf", "outputs": [{"name": "value"}],
            "impl": {"kind": "python",
                     "code": "def execute(c, i, x):\n    return {'value': 1}"}}
    out = engine._invoke_node_handler("node_create", {"spec": spec})
    assert out["status"] == "ok"
    assert "hint" in out and "graph" in out["hint"]


def test_node_create_graph_has_no_hint(engine):
    """A graph node — the preferred kind — gets no steering hint."""
    spec = {"type": "g.composed", "category": "logic",
            "display_name": "Composed", "outputs": [{"name": "value"}],
            "impl": {"kind": "graph", "graph": {"nodes": [], "wires": []}}}
    out = engine._invoke_node_handler("node_create", {"spec": spec})
    assert out["status"] == "ok"
    assert "hint" not in out
