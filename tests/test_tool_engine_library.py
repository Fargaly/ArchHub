"""Tests for tool_engine.py — library_* tool integration.

Five library tools are wired into ToolEngine via the `_local` family.
This test file proves:
- TOOLS list contains all 5 library entries with correct shapes.
- ToolEngine._invoke_library_handler routes each handler to library.py.
- RegistrationError / DuplicateTypeError / UnknownTypeError surface as
  structured tool results (status:error + violations / code).
- A mocked ConnectorManager is all the integration needs — no real host
  connectors required to exercise the library family.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parents[1] / "app"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))


@pytest.fixture
def fresh_library():
    """Reset the library registry between tests so order is free."""
    import library  # noqa: WPS433
    library.reset_registry()
    yield
    library.reset_registry()


@pytest.fixture
def engine():
    """ToolEngine wired against a stub ConnectorManager — library handlers
    don't touch the manager, so the stub is enough.
    """
    from tool_engine import ToolEngine

    class _StubManager:
        entries: list = []

        def active_families(self) -> set:
            return set()

    return ToolEngine(manager=_StubManager())


# ---------------------------------------------------------------------------
# TOOLS list registration


def test_tools_list_contains_five_library_tools():
    from tool_engine import TOOLS

    names = {t["name"] for t in TOOLS if t["family"] == "_local"}
    for required in (
        "library_search",
        "library_list_node_types",
        "library_inspect",
        "library_create_node_type",
        "library_delete_node_type",
    ):
        assert required in names, f"missing library tool: {required}"


def test_library_search_tool_shape():
    from tool_engine import TOOLS
    t = next(t for t in TOOLS if t["name"] == "library_search")
    assert t["family"] == "_local"
    assert t["endpoint"] == ("_local", "library_search")
    props = t["input_schema"]["properties"]
    assert "intent" in props
    assert "category" in props
    assert "limit" in props
    assert t["input_schema"]["required"] == ["intent"]


def test_library_create_tool_shape():
    from tool_engine import TOOLS
    t = next(t for t in TOOLS if t["name"] == "library_create_node_type")
    assert t["family"] == "_local"
    assert t["endpoint"] == ("_local", "library_create_node_type")
    props = t["input_schema"]["properties"]
    assert "spec" in props
    assert t["input_schema"]["required"] == ["spec"]


# ---------------------------------------------------------------------------
# _invoke_library_handler — dispatcher


def test_invoke_library_search_returns_results(engine, fresh_library):
    from library_seeds import seed_library
    seed_library()
    r = engine._invoke_library_handler(
        "library_search",
        {"intent": "constant"},
    )
    assert r["status"] == "ok"
    assert "results" in r
    assert r["count"] >= 1
    assert any(item["type"] == "data.constant" for item in r["results"])


def test_invoke_library_search_no_match_returns_empty(engine, fresh_library):
    from library_seeds import seed_library
    seed_library()
    r = engine._invoke_library_handler(
        "library_search",
        {"intent": "octopus-tentacle-protocol"},
    )
    assert r["status"] == "ok"
    assert r["results"] == []
    assert r["count"] == 0


def test_invoke_library_list_returns_summaries(engine, fresh_library):
    from library_seeds import seed_library
    seed_library()
    r = engine._invoke_library_handler("library_list_node_types", {})
    assert r["status"] == "ok"
    assert r["count"] >= 5
    # Filtered list.
    r2 = engine._invoke_library_handler(
        "library_list_node_types",
        {"category": "input"},
    )
    assert all(item["category"] == "input" for item in r2["items"])


def test_invoke_library_inspect_returns_spec(engine, fresh_library):
    from library_seeds import seed_library
    seed_library()
    r = engine._invoke_library_handler(
        "library_inspect",
        {"node_type": "connector.run"},
    )
    assert r["status"] == "ok"
    assert r["spec"]["type"] == "connector.run"
    assert r["spec"]["side_effects"] == "host_write"


def test_invoke_library_inspect_unknown_type_errors(engine, fresh_library):
    r = engine._invoke_library_handler(
        "library_inspect",
        {"node_type": "never.registered"},
    )
    assert r["status"] == "error"
    assert r["code"] == "unknown_type"


def test_invoke_library_create_node_type_succeeds(engine, fresh_library):
    spec = {
        "type": "demo.created",
        "display_name": "Demo Created",
        "category": "shape",
        "inputs": [],
        "outputs": [{"name": "value", "port_type": "any"}],
        "config_schema": {"properties": {"x": {"type": "string"}}},
        "description": (
            "A demo node created via the tool-engine integration tests. "
            "Has one output and a simple config schema."
        ),
        "examples": [
            {"input": {}, "output": {"value": "x"}, "note": "happy"},
        ],
        "side_effects": "pure",
    }
    r = engine._invoke_library_handler(
        "library_create_node_type",
        {"spec": spec},
    )
    assert r["status"] == "ok"
    assert r["id"] == "demo.created"
    assert r["registered"] is True


def test_invoke_library_create_node_type_validator_fail_surfaces_violations(
    engine, fresh_library
):
    r = engine._invoke_library_handler(
        "library_create_node_type",
        {"spec": {"type": "x"}},  # missing required fields
    )
    assert r["status"] == "error"
    assert "violations" in r
    assert len(r["violations"]) >= 3
    # The LLM-readable error string includes the prefix from the
    # RegistrationError exception.
    assert "fix the violations and retry" in r["error"]


def test_invoke_library_create_node_type_duplicate_surfaces_code(
    engine, fresh_library
):
    spec = {
        "type": "demo.dup",
        "display_name": "Demo Dup",
        "category": "shape",
        "inputs": [],
        "outputs": [{"name": "value", "port_type": "any"}],
        "config_schema": {"properties": {"x": {"type": "string"}}},
        "description": (
            "A demo node used to test the duplicate-registration error "
            "path through the tool engine integration."
        ),
        "examples": [{"input": {}, "output": {"value": "x"}}],
        "side_effects": "pure",
    }
    r1 = engine._invoke_library_handler(
        "library_create_node_type", {"spec": spec},
    )
    assert r1["status"] == "ok"
    r2 = engine._invoke_library_handler(
        "library_create_node_type", {"spec": spec},
    )
    assert r2["status"] == "error"
    assert r2["code"] == "duplicate_type"


def test_invoke_library_delete_node_type_succeeds(engine, fresh_library):
    from library_seeds import seed_library
    seed_library()
    r = engine._invoke_library_handler(
        "library_delete_node_type",
        {"node_type": "watch.preview"},
    )
    assert r["status"] == "ok"
    assert r["ok"] is True


def test_invoke_library_delete_unknown_type_errors(engine, fresh_library):
    r = engine._invoke_library_handler(
        "library_delete_node_type",
        {"node_type": "never.registered"},
    )
    assert r["status"] == "error"
    assert r["code"] == "unknown_type"


def test_invoke_unknown_library_handler_errors(engine):
    r = engine._invoke_library_handler("library_nope", {})
    assert r["status"] == "error"
    assert "Unknown library handler" in r["error"]
