"""End-to-end integration tests across the library stack.

Each layer has its own focused tests (validator, gate, library module,
persistence, ToolEngine, bridge slots). These tests prove the layers SHARE
ONE source of truth — a node created via one surface is visible to every
other surface, and the disk is the single durable store.

Scenarios exercised here:
1. Bridge bootstrap → seeds appear via ToolEngine search (cross-surface read).
2. Bridge creates a node → LLM ToolEngine sees it on next search.
3. LLM ToolEngine creates a node → Bridge inspect returns it.
4. Layer-3 gate denies pre-search create → recovery sequence succeeds.
5. Validator violations surface identically through gate AND ToolEngine.
6. Cold restart: disk-loaded node is searchable through both surfaces.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))

import bridge as _bridge_module  # noqa: E402
import library as _lib  # noqa: E402
import library_gate as _gate_module  # noqa: E402
from tool_engine import ToolEngine  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """Redirect the persistence root so writes go to tmp. Reset the
    in-process library before + after each test.

    library_persistence.default_registry_path() reads LOCALAPPDATA on
    Windows but XDG_DATA_HOME / ~/.local/share on POSIX — BOTH must be
    monkeypatched, or the CI Linux/macOS runners fall back to one real
    shared registry file and node-types leak across tests (the
    data.constant-missing + cross-test-pollution failure).
    """
    appdata = tmp_path / "appdata"
    appdata.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LOCALAPPDATA", str(appdata))
    monkeypatch.setenv("XDG_DATA_HOME", str(appdata))
    _lib.reset_registry()
    yield
    _lib.reset_registry()


@pytest.fixture
def bridge_inst():
    b = _bridge_module.ArchHubBridge()
    if hasattr(b, "_lib_booted"):
        delattr(b, "_lib_booted")
    return b


@pytest.fixture
def engine():
    class _StubManager:
        entries: list = []

        def active_families(self) -> set:
            return set()

    return ToolEngine(manager=_StubManager())


def _modular_spec(type_name: str = "demo.cross_surface") -> dict:
    return {
        "type": type_name,
        "display_name": "Demo Cross Surface",
        "category": "shape",
        "inputs": [],
        "outputs": [{"name": "value", "port_type": "any"}],
        "config_schema": {"properties": {"x": {"type": "string"}}},
        "description": (
            "A modular node that flows across the library bridge + the "
            "ToolEngine to prove they share a single registry of truth."
        ),
        "examples": [
            {"input": {}, "output": {"value": "x"}, "note": "happy"},
        ],
        "side_effects": "pure",
    }


# ---------------------------------------------------------------------------
# Scenario 1 — Bridge bootstrap → ToolEngine sees seeds


def test_bridge_bootstrap_seeds_visible_via_tool_engine(
    bridge_inst, engine
):
    # Triggering ANY bridge library call seeds the registry.
    bridge_inst.library_list_node_types("")

    # ToolEngine reads the SAME in-process registry.
    res = engine._invoke_library_handler(
        "library_search",
        {"intent": "constant"},
    )
    assert res["status"] == "ok"
    assert any(r["type"] == "data.constant" for r in res["results"])


# ---------------------------------------------------------------------------
# Scenario 2 — Bridge writes → LLM reads


def test_bridge_create_node_then_llm_search_finds_it(bridge_inst, engine):
    # JSX side registers a new node via bridge.
    spec = _modular_spec("demo.from_bridge")
    spec["display_name"] = "From Bridge"
    raw = bridge_inst.library_create_node_type(json.dumps(spec))
    assert json.loads(raw)["ok"] is True

    # LLM side searches via ToolEngine — finds it.
    res = engine._invoke_library_handler(
        "library_search",
        {"intent": "From Bridge"},
    )
    assert res["status"] == "ok"
    assert any(r["type"] == "demo.from_bridge" for r in res["results"])


# ---------------------------------------------------------------------------
# Scenario 3 — LLM writes → Bridge reads


def test_llm_create_node_then_bridge_inspect_finds_it(
    bridge_inst, engine
):
    # Bridge bootstraps once so the registry is alive.
    bridge_inst.library_list_node_types("")

    # LLM side registers via ToolEngine.
    spec = _modular_spec("demo.from_llm")
    res = engine._invoke_library_handler(
        "library_create_node_type",
        {"spec": spec},
    )
    assert res["status"] == "ok"

    # JSX side inspects via bridge — finds it.
    raw = bridge_inst.library_inspect("demo.from_llm")
    payload = json.loads(raw)
    assert "spec" in payload
    assert payload["spec"]["type"] == "demo.from_llm"


# ---------------------------------------------------------------------------
# Scenario 4 — Gate enforces LIBRARY-FIRST across the recovery sequence


def test_gate_denies_then_allows_recovery_sequence(bridge_inst, engine):
    """Gate logic is independent of ToolEngine wiring (router integration
    still ahead), but the gate decision flow should match what ToolEngine
    DOES on a valid spec — proving the contract aligns.
    """
    bridge_inst.library_list_node_types("")  # bootstrap

    gate = _gate_module.LibraryGate()
    ts = _gate_module.TurnState()

    spec = _modular_spec("demo.recovery")

    # Step 1 — premature create — gate DENIES (no prior search).
    d1 = gate.check("library_create_node_type", {"spec": spec}, ts)
    assert d1.allow is False
    assert d1.retry_hint["call"] == "library.search"
    # Confirm ToolEngine would have ALSO refused — but ToolEngine has no
    # gate today, it would CREATE the node. The gate is a structural
    # guard ABOVE ToolEngine; the router (M3) wires them together.
    # This test asserts the gate's contract; router integration test
    # arrives with M3 router wiring.

    # Step 2 — LLM follows retry_hint, calls search — gate ALLOWS.
    d2 = gate.check("library_search", {"intent": "demo recovery"}, ts)
    assert d2.allow is True

    # Step 3 — retried create — gate ALLOWS, then ToolEngine registers.
    d3 = gate.check("library_create_node_type", {"spec": spec}, ts)
    assert d3.allow is True
    res = engine._invoke_library_handler(
        "library_create_node_type",
        {"spec": spec},
    )
    assert res["status"] == "ok"

    # Step 4 — bridge sees it.
    raw = bridge_inst.library_inspect("demo.recovery")
    assert json.loads(raw)["spec"]["type"] == "demo.recovery"


# ---------------------------------------------------------------------------
# Scenario 5 — Validator violations surface uniformly across surfaces


def test_validator_violations_uniform_across_surfaces(bridge_inst, engine):
    """A bad spec produces the SAME violation set whether the caller is
    JSX (bridge) or LLM (ToolEngine). Critical for the "fix in one
    retry" promise — the LLM and the human see identical errors.
    """
    bad = {"type": "demo.bad_spec"}  # missing many required fields
    bridge_inst.library_list_node_types("")  # bootstrap

    # Through ToolEngine.
    llm_res = engine._invoke_library_handler(
        "library_create_node_type",
        {"spec": bad},
    )
    assert llm_res["status"] == "error"
    llm_violations = set(llm_res["violations"])

    # Through Bridge.
    bridge_raw = bridge_inst.library_create_node_type(json.dumps(bad))
    bridge_res = json.loads(bridge_raw)
    bridge_violations = set(bridge_res["violations"])

    # Both surfaces produce identical violation sets.
    assert llm_violations == bridge_violations
    assert len(llm_violations) >= 3


# ---------------------------------------------------------------------------
# Scenario 6 — Cold restart picks up disk-persisted nodes


def test_cold_restart_loads_persisted_nodes(bridge_inst, engine):
    """Write a node via the bridge → it persists → simulate cold restart
    (reset in-process registry + new bridge instance) → next library
    operation hydrates from disk via _library_bootstrap.
    """
    # Warm-boot the bridge, create a node (auto-persists to disk).
    bridge_inst.library_list_node_types("")  # seed
    spec = _modular_spec("demo.persisted")
    bridge_inst.library_create_node_type(json.dumps(spec))

    # Simulate cold restart: wipe in-process; rehydrate via library
    # bootstrap on the new bridge.
    _lib.reset_registry()
    assert _lib.registry_size() == 0
    new_bridge = _bridge_module.ArchHubBridge()
    if hasattr(new_bridge, "_lib_booted"):
        delattr(new_bridge, "_lib_booted")

    # First call triggers bootstrap — which detects the disk file and
    # loads it (no re-seeding).
    raw = new_bridge.library_inspect("demo.persisted")
    payload = json.loads(raw)
    assert "spec" in payload
    assert payload["spec"]["type"] == "demo.persisted"

    # Disk-load includes EVERYTHING persisted — the seed primitives were
    # auto-persisted on the warm boot's create_node_type call, so they
    # come back too. Seed step (re-call seed_library) is skipped because
    # disk wasn't empty; the seeded primitives reach the new instance
    # via the disk file, not via re-seeding.
    raw_list = new_bridge.library_list_node_types("")
    types = {item["type"] for item in json.loads(raw_list)["items"]}
    assert "demo.persisted" in types
    assert "data.constant" in types  # came back via disk (not re-seed)


# ---------------------------------------------------------------------------
# Scenario 7 — Search ranking is stable across surfaces


def test_search_ranking_identical_across_surfaces(bridge_inst, engine):
    bridge_inst.library_list_node_types("")  # bootstrap with seeds

    # Same intent through both surfaces.
    intent = "connector"
    llm_res = engine._invoke_library_handler(
        "library_search",
        {"intent": intent, "limit": 8},
    )
    bridge_raw = bridge_inst.library_search(intent, "", 8)
    bridge_res = json.loads(bridge_raw)

    # Same registry → same ranking. The id+type+score tuples line up.
    def _keys(items):
        return [(r["id"], r["type"], r["score"]) for r in items]

    assert _keys(llm_res["results"]) == _keys(bridge_res["results"])
