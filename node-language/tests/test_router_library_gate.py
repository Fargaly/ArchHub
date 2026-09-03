"""Tests for the LLM router's LIBRARY-FIRST gate integration.

Reference: AgDR-0013 Layer 3. The gate runs BEFORE every ToolEngine
invocation in `llm_router._complete_once`. A gate denial returns a
synthetic tool_result with status:error + retry_hint instead of calling
ToolEngine, letting the LLM correct in the next iteration.

We can't easily exercise the full _complete_once loop without mocking
every provider client, so these tests target the gate-integration
specifically: import + behaviour proofs that the gate refuses
premature creates AND lets normal flow through.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))


# ---------------------------------------------------------------------------
# Gate state at router scope


def test_gate_module_imports_in_router_context():
    """The router imports the gate inside _complete_once. The import
    path must work from the same sys.path the router has at runtime."""
    from library_gate import LibraryGate, TurnState
    gate = LibraryGate()
    state = TurnState()
    assert state.library_searched is False
    # Gate is stateless wrt instance — state lives on TurnState.
    assert hasattr(gate, "check")
    assert hasattr(gate, "is_library_tool")


def test_gate_denies_premature_create_in_isolated_simulation():
    """Simulate what the router does: a tool_call sequence where the
    LLM tries library_create_node_type FIRST. Gate must deny."""
    from library_gate import LibraryGate, TurnState
    gate = LibraryGate()
    state = TurnState()

    bad_spec = {"type": "demo.x"}  # missing many required fields
    decision = gate.check("library_create_node_type",
                           {"spec": bad_spec}, state)
    assert decision.allow is False
    # The denial reason mentions library.search (the canonical name).
    assert "library.search" in decision.reason
    assert decision.retry_hint is not None
    # Retry hint should point at library.search.
    assert decision.retry_hint["call"] == "library.search"


def test_gate_allows_create_after_search_with_valid_spec():
    """Happy path after the LLM calls search first, then creates with
    a modular spec."""
    from library_gate import LibraryGate, TurnState
    gate = LibraryGate()
    state = TurnState()

    # Step 1 — search (marks state.library_searched=True).
    d1 = gate.check("library_search", {"intent": "tag walls"}, state)
    assert d1.allow is True
    assert state.library_searched is True

    # Step 2 — create_node_type with a modular spec.
    modular_spec = {
        "type": "demo.tag_walls",
        "display_name": "Tag Walls",
        "category": "shape",
        "inputs": [],
        "outputs": [{"name": "tags", "port_type": "any"}],
        "config_schema": {"properties": {"view_id": {"type": "string"}}},
        "description": ("Tags every wall in the input list with the room "
                         "it belongs to. Uses the configured tag family."),
        "examples": [{"input": {}, "output": {"value": "tag"}, "note": "happy"}],
        "side_effects": "pure",
    }
    d2 = gate.check("library_create_node_type",
                     {"spec": modular_spec}, state)
    assert d2.allow is True


def test_gate_denies_create_with_bad_spec_after_search():
    """Even after search, a non-modular spec must be denied — Layer 4
    validator is the second backstop."""
    from library_gate import LibraryGate, TurnState
    gate = LibraryGate()
    state = TurnState()
    gate.check("library_search", {"intent": "x"}, state)
    decision = gate.check("library_create_node_type",
                           {"spec": {"type": "x"}}, state)
    assert decision.allow is False
    assert "not modular" in decision.reason
    assert isinstance(decision.retry_hint, dict)
    # Violations enumerated so the LLM can fix in one retry pass.
    assert "fix" in decision.retry_hint
    assert len(decision.retry_hint["fix"]) >= 3


def test_gate_allows_other_tools_through():
    """Non-library tools must never be touched by the gate."""
    from library_gate import LibraryGate, TurnState
    gate = LibraryGate()
    state = TurnState()
    for tool_name in ("revit__list_walls", "speckle__send",
                       "graph_create_node", "ai_complete"):
        decision = gate.check(tool_name, {}, state)
        assert decision.allow is True
    assert state.library_searched is False  # untouched


# ---------------------------------------------------------------------------
# Router code-shape verification — the gate IS inserted at the right line


def test_router_imports_library_gate():
    """The router file must reference the LibraryGate import — guards
    against accidental deletion."""
    router_path = APP / "llm_router.py"
    src = router_path.read_text(encoding="utf-8")
    assert "from library_gate import LibraryGate" in src
    assert "TurnState" in src


def test_router_inserts_gate_check_in_tool_loop():
    """The gate.check() call must appear inside the tool-call loop,
    BEFORE ToolEngine.invoke."""
    router_path = APP / "llm_router.py"
    src = router_path.read_text(encoding="utf-8")
    # The gate.check line we added.
    assert "_lib_gate.check(" in src
    # The gate's denial path turns the result into a tool_result with
    # the typed `library_first_blocked` code.
    assert "library_first_blocked" in src
    # The denial path uses `continue` to skip ToolEngine.invoke.
    gate_idx = src.find("_lib_gate.check(")
    invoke_idx = src.find("self.tools.invoke(", gate_idx)
    # Gate check should come BEFORE the invoke call inside the same
    # for-loop iteration.
    assert gate_idx < invoke_idx
    # Continue statement between gate denial and invoke.
    continue_idx = src.find("continue   # skip ToolEngine.invoke", gate_idx)
    assert continue_idx > gate_idx
    assert continue_idx < invoke_idx
