"""Tests for app/library_gate.py — Layer 3 of the LIBRARY-FIRST enforcement.

The gate is model-agnostic structural enforcement. It runs in the LLM router
BETWEEN tool-call extraction and ToolEngine.invoke(). These tests prove:

- search marks state, always allowed.
- create_node_type denied without prior search this turn.
- create_node_type denied with non-modular spec.
- create_node_type allowed with search + modular spec.
- Other tools always allowed (gate doesn't interfere).
- TurnState resets cleanly per user turn.
- retry_hint payloads point the LLM at the right recovery.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parents[1] / "app"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from library_gate import (  # noqa: E402
    GateDecision,
    LibraryGate,
    TurnState,
)


def _modular_spec() -> dict:
    """A spec that passes the validator — happy-path tier."""
    return {
        "type": "data.constant",
        "display_name": "Constant Value",
        "category": "input",
        "inputs": [],
        "outputs": [
            {"name": "value", "port_type": "any", "description": "The fixed value"},
        ],
        "config_schema": {
            "properties": {
                "value": {"type": "string"},
                "value_type": {"type": "string", "default": "string"},
            }
        },
        "description": (
            "Emits a fixed literal value. Use this when a downstream node "
            "needs a constant input that the user pins at design time."
        ),
        "examples": [
            {"input": {}, "output": {"value": "hello"}, "note": "string literal"},
        ],
        "side_effects": "pure",
    }


# ---------------------------------------------------------------------------
# TurnState


def test_turn_state_defaults():
    ts = TurnState()
    assert ts.library_searched is False
    assert ts.invocations == []


def test_turn_state_reset_clears_flag():
    ts = TurnState()
    ts.library_searched = True
    ts.invocations.append({"tool": "x", "args_keys": []})
    ts.reset()
    assert ts.library_searched is False
    assert ts.invocations == []


# ---------------------------------------------------------------------------
# Rule 2 — library.search


def test_search_always_allowed():
    gate = LibraryGate()
    ts = TurnState()
    d = gate.check("library.search", {"intent": "tag walls"}, ts)
    assert d.allow is True


def test_search_marks_state():
    gate = LibraryGate()
    ts = TurnState()
    assert ts.library_searched is False
    gate.check("library.search", {"intent": "tag walls"}, ts)
    assert ts.library_searched is True


def test_search_allowed_even_when_state_already_set():
    # Multiple searches in one turn should not flip the flag off.
    gate = LibraryGate()
    ts = TurnState(library_searched=True)
    d = gate.check("library.search", {"intent": "refine"}, ts)
    assert d.allow is True
    assert ts.library_searched is True


# ---------------------------------------------------------------------------
# Rule 1 — library.create_node_type


def test_create_node_type_denied_without_prior_search():
    gate = LibraryGate()
    ts = TurnState()  # library_searched=False
    d = gate.check(
        "library.create_node_type",
        {"spec": _modular_spec()},
        ts,
    )
    assert d.allow is False
    assert "library.search" in d.reason
    assert d.retry_hint is not None
    assert d.retry_hint["call"] == "library.search"


def test_create_node_type_denied_with_non_modular_spec():
    gate = LibraryGate()
    ts = TurnState(library_searched=True)
    bad_spec = {"type": "x"}  # missing nearly everything
    d = gate.check(
        "library.create_node_type",
        {"spec": bad_spec},
        ts,
    )
    assert d.allow is False
    assert "not modular" in d.reason
    assert d.retry_hint is not None
    assert d.retry_hint["call"] == "library.create_node_type"
    assert isinstance(d.retry_hint["fix"], list)
    assert len(d.retry_hint["fix"]) >= 3  # multiple violations surfaced


def test_create_node_type_allowed_with_search_and_modular_spec():
    gate = LibraryGate()
    ts = TurnState(library_searched=True)
    d = gate.check(
        "library.create_node_type",
        {"spec": _modular_spec()},
        ts,
    )
    assert d.allow is True


def test_create_node_type_retry_hint_includes_intent_guess():
    """When denied for missing prior search, the retry_hint should help the
    LLM construct a sensible library.search call rather than guess blindly.
    """
    gate = LibraryGate()
    ts = TurnState()
    spec = _modular_spec()
    d = gate.check("library.create_node_type", {"spec": spec}, ts)
    assert d.allow is False
    assert d.retry_hint is not None
    # The hint pulls display_name as the intent guess.
    assert d.retry_hint["with_args"]["intent"] == spec["display_name"]


def test_create_node_type_with_missing_spec_argument():
    gate = LibraryGate()
    ts = TurnState(library_searched=True)
    d = gate.check("library.create_node_type", {}, ts)
    assert d.allow is False
    assert "not modular" in d.reason


def test_create_node_type_with_none_spec():
    gate = LibraryGate()
    ts = TurnState(library_searched=True)
    d = gate.check("library.create_node_type", {"spec": None}, ts)
    assert d.allow is False
    assert "not modular" in d.reason


# ---------------------------------------------------------------------------
# Rule 3 — other tools always pass


@pytest.mark.parametrize("other_tool", [
    "graph.create_node",
    "graph.connect",
    "graph.run",
    "graph.set_param",
    "speckle.send",
    "speckle.receive",
    "node.inspect",
    "skill.save_as",
    "library.list_node_types",
    "library.inspect",
])
def test_other_tools_always_allowed(other_tool: str):
    gate = LibraryGate()
    ts = TurnState()
    d = gate.check(other_tool, {}, ts)
    assert d.allow is True
    # Non-library tools never flip the search flag.
    if other_tool != "library.search":
        assert ts.library_searched is False


def test_unknown_tool_allowed():
    # Forward-compatibility: a tool the gate doesn't recognise passes through.
    # The router will surface "no such tool" elsewhere.
    gate = LibraryGate()
    ts = TurnState()
    d = gate.check("custom.future_tool", {}, ts)
    assert d.allow is True


# ---------------------------------------------------------------------------
# Invocation logging


def test_gate_logs_every_invocation_to_turn_state():
    gate = LibraryGate()
    ts = TurnState()
    gate.check("library.search", {"intent": "x"}, ts)
    gate.check("graph.create_node", {"type": "data.constant"}, ts)
    gate.check("library.create_node_type", {"spec": _modular_spec()}, ts)
    assert len(ts.invocations) == 3
    assert ts.invocations[0]["tool"] == "library.search"
    assert ts.invocations[1]["tool"] == "graph.create_node"
    assert ts.invocations[2]["tool"] == "library.create_node_type"


def test_gate_logs_invocations_for_denied_calls_too():
    gate = LibraryGate()
    ts = TurnState()  # no search yet
    d = gate.check("library.create_node_type", {"spec": {"type": "x"}}, ts)
    assert d.allow is False
    # Even denied calls are logged — diagnostic.
    assert len(ts.invocations) == 1
    assert ts.invocations[0]["tool"] == "library.create_node_type"


# ---------------------------------------------------------------------------
# Full-turn integration scenarios


def test_full_happy_path_search_then_create():
    gate = LibraryGate()
    ts = TurnState()
    # Step 1 — search runs, marks state.
    d1 = gate.check("library.search", {"intent": "constant value"}, ts)
    assert d1.allow is True
    # Step 2 — create_node_type now passes (state + modular spec).
    d2 = gate.check(
        "library.create_node_type",
        {"spec": _modular_spec()},
        ts,
    )
    assert d2.allow is True


def test_full_recovery_path_deny_then_search_then_retry_succeeds():
    """The prototype scenario: LLM tries create_node_type first, gets
    denied, then runs search, then retries create_node_type with the
    same modular spec — passes.
    """
    gate = LibraryGate()
    ts = TurnState()
    spec = _modular_spec()
    # Step 1 — premature create — DENIED.
    d1 = gate.check("library.create_node_type", {"spec": spec}, ts)
    assert d1.allow is False
    # Step 2 — LLM follows retry_hint, calls search — ALLOWED.
    d2 = gate.check("library.search", d1.retry_hint["with_args"], ts)
    assert d2.allow is True
    # Step 3 — same spec, retried — now ALLOWED.
    d3 = gate.check("library.create_node_type", {"spec": spec}, ts)
    assert d3.allow is True


def test_full_recovery_path_validator_fail_then_fix_then_succeed():
    """LLM submits a bad spec → gate surfaces violations → LLM corrects →
    gate accepts. Critical: the LLM must see ALL violations at once so it
    can fix in one retry, not loop.
    """
    gate = LibraryGate()
    ts = TurnState()
    gate.check("library.search", {"intent": "value"}, ts)
    # Bad spec — missing many required fields. Provide config_schema={}
    # explicitly so the model validator also surfaces (otherwise Pydantic
    # uses the default and field_validator on default is skipped).
    bad = {"type": "data.constant", "config_schema": {}}
    d1 = gate.check("library.create_node_type", {"spec": bad}, ts)
    assert d1.allow is False
    # Violations enumerate every gap — not just the first. The LLM must
    # see them all so it can fix in ONE retry, not loop.
    fixes = d1.retry_hint["fix"]
    assert len(fixes) >= 4
    # LLM corrects, resubmits.
    d2 = gate.check("library.create_node_type", {"spec": _modular_spec()}, ts)
    assert d2.allow is True


# ---------------------------------------------------------------------------
# Misc


def test_is_library_tool_recognises_all_five():
    gate = LibraryGate()
    for t in ("library.search", "library.list_node_types",
              "library.inspect", "library.create_node_type",
              "library.delete_node_type"):
        assert gate.is_library_tool(t) is True


def test_is_library_tool_rejects_others():
    gate = LibraryGate()
    for t in ("graph.create_node", "speckle.send", "library", "library."):
        assert gate.is_library_tool(t) is False


def test_gate_decision_default_allow_no_reason():
    d = GateDecision(allow=True)
    assert d.allow is True
    assert d.reason == ""
    assert d.retry_hint is None


# ---------------------------------------------------------------------------
# Wire-format name canonicalisation
# ToolEngine registers tool names with underscores (`library_search`)
# because some providers reject dots in tool-name validation. The gate's
# logic uses canonical dot names internally; canonicalise_name() bridges.


def test_canonicalise_underscore_name():
    from library_gate import _canonicalise_name
    assert _canonicalise_name("library_search") == "library.search"
    assert _canonicalise_name("library_create_node_type") == "library.create_node_type"


def test_canonicalise_double_underscore_name():
    from library_gate import _canonicalise_name
    assert _canonicalise_name("library__search") == "library.search"
    assert _canonicalise_name("library__create_node_type") == "library.create_node_type"


def test_canonicalise_dot_name_passthrough():
    from library_gate import _canonicalise_name
    assert _canonicalise_name("library.search") == "library.search"


def test_canonicalise_non_library_name_passthrough():
    from library_gate import _canonicalise_name
    assert _canonicalise_name("graph.create_node") == "graph.create_node"
    assert _canonicalise_name("speckle__send") == "speckle__send"


def test_gate_accepts_underscore_search_name():
    gate = LibraryGate()
    ts = TurnState()
    d = gate.check("library_search", {"intent": "x"}, ts)
    assert d.allow is True
    assert ts.library_searched is True


def test_gate_denies_underscore_create_without_search():
    gate = LibraryGate()
    ts = TurnState()
    d = gate.check(
        "library_create_node_type",
        {"spec": _modular_spec()},
        ts,
    )
    assert d.allow is False
    assert "library.search" in d.reason


def test_gate_logs_canonical_name():
    gate = LibraryGate()
    ts = TurnState()
    gate.check("library_search", {"intent": "x"}, ts)
    # Even though wire-format name was passed in, the log records the
    # canonical dot form.
    assert ts.invocations[0]["tool"] == "library.search"


def test_is_library_tool_accepts_underscore_names():
    gate = LibraryGate()
    for t in ("library_search", "library__search",
              "library_create_node_type"):
        assert gate.is_library_tool(t) is True
