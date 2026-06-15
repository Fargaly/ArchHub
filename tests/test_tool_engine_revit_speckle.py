"""Tool-engine integration — Revit↔Speckle ops via LLM tool path.

References: AgDR-0017 + AgDR-0018. The 3 new ops
(`revit.send_to_speckle`, `revit.receive_from_speckle`,
`revit.batch_set_parameters`) flow through `tool_engine.invoke`
when an LLM calls them as `revit__send_to_speckle` etc.

Tests prove:
  1. The ops surface in `_connector_tool_specs` (LLM sees them).
  2. Tool names use `__` (dot-name workaround for providers that
     reject `.` in tool names).
  3. `invoke()` routes a `revit__send_to_speckle` call to the
     real connector op + returns the connector's result.
  4. Destructive ops (`receive`, `batch_set_parameters`) trigger
     the `ask` policy gate when the user has set it.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

# Force connector module imports (registers the ops).
import connectors.revit_connector  # noqa: F401, E402


class _StubManager:
    """Minimal ConnectorManager stand-in — the new ops don't reach
    into the manager so a stub is enough."""
    entries: list = []

    def active_families(self) -> set:
        return set()


def _engine():
    from tool_engine import ToolEngine
    return ToolEngine(manager=_StubManager())


# ─── 1. tool surface ──────────────────────────────────────────────────


def test_revit_speckle_ops_appear_in_tool_specs():
    """The connector tool-spec list (what `list_tools` returns) MUST
    include the 3 new Revit↔Speckle ops with the `__` name shape."""
    engine = _engine()
    specs = engine._connector_tool_specs()
    names = {s["name"] for s in specs}
    assert "revit__send_to_speckle" in names
    assert "revit__receive_from_speckle" in names
    assert "revit__batch_set_parameters" in names


def test_destructive_ops_flag_mutates_in_description():
    """Destructive ops get a side-effect hint in their LLM-visible
    description — the model knows the op has a consequence + is gated.
    CON-02: the hint is HONEST about which side effect it is.

    * receive + batch_set MUTATE the Revit host → "[MUTATES THE HOST]".
    * send WRITES OUT to disk/remote (it does not touch Revit) →
      "[WRITES TO DISK/REMOTE]". It must still be flagged (it is a
      destructive write, approval-gated) — just not as a host mutation."""
    engine = _engine()
    specs = engine._connector_tool_specs()
    by_name = {s["name"]: s for s in specs}

    # receive + batch_set mutate the host.
    assert "[MUTATES THE HOST]" in by_name["revit__receive_from_speckle"]["description"]
    assert "[MUTATES THE HOST]" in by_name["revit__batch_set_parameters"]["description"]
    # send writes outward — flagged as a disk/remote write, NOT a host
    # mutation. The CON-02 root: it IS a side-effecting write (so it is
    # gated), it just doesn't mutate Revit.
    send_desc = by_name["revit__send_to_speckle"]["description"]
    assert "[WRITES TO DISK/REMOTE]" in send_desc
    assert "[MUTATES THE HOST]" not in send_desc


# ─── 2. invoke routing ────────────────────────────────────────────────


def test_invoke_routes_send_to_speckle_through_connector(tmp_path,
                                                            monkeypatch):
    """An LLM `revit__send_to_speckle` invocation routes to the
    real connector op + returns the connector's value."""
    from tool_engine import ToolEngine

    # Override the tool-policy to 'allow' for this op so the gate
    # doesn't intercept.
    monkeypatch.setattr(
        "ai_behaviour.get_tool_policy", lambda n: "allow", raising=False)
    # Redirect SpeckleWire's default project dir to tmp_path so the
    # op writes to a sandbox, not the user's real
    # %LOCALAPPDATA%/ArchHub/...
    import speckle_wire
    monkeypatch.setattr(speckle_wire, "default_project_dir",
                         lambda: str(tmp_path))

    engine = _engine()
    result = engine.invoke(
        "revit__send_to_speckle",
        {"value": {"hello": "world"},
         "model_name": "tool-engine-test"},
    )
    assert result["status"] == "ok", result
    inner = result["result"]
    assert isinstance(inner, dict)
    assert inner["url"].startswith("speckle://local/")
    assert inner["item_count"] == 1


def test_invoke_send_to_speckle_ask_policy_returns_needs_confirmation(
        tmp_path, monkeypatch):
    """If the user has set the op to 'ask', invoke returns
    needs_confirmation without firing the op. Unless
    user_confirmed=True."""
    from tool_engine import ToolEngine

    monkeypatch.setattr(
        "ai_behaviour.get_tool_policy", lambda n: "ask", raising=False)
    import speckle_wire
    monkeypatch.setattr(speckle_wire, "default_project_dir",
                         lambda: str(tmp_path))
    engine = _engine()

    result = engine.invoke(
        "revit__send_to_speckle",
        {"value": {"x": 1}},
        user_confirmed=False,
    )
    assert result["status"] == "needs_confirmation"
    assert result["tool_name"] == "revit__send_to_speckle"
    assert result["policy"] == "ask"

    # user_confirmed=True bypasses the gate.
    result2 = engine.invoke(
        "revit__send_to_speckle",
        {"value": {"x": 1}},
        user_confirmed=True,
    )
    assert result2["status"] == "ok", result2


def test_invoke_send_to_speckle_deny_policy_blocks(tmp_path, monkeypatch):
    """`deny` policy is NOT bypassable — even user_confirmed=True
    must not fire the op."""
    from tool_engine import ToolEngine

    monkeypatch.setattr(
        "ai_behaviour.get_tool_policy", lambda n: "deny", raising=False)
    engine = _engine()

    result = engine.invoke(
        "revit__send_to_speckle",
        {"value": {"x": 1}},
        user_confirmed=True,
    )
    assert result["status"] == "error"
    assert result["policy"] == "deny"


def test_invoke_receive_returns_typed_error_when_broker_offline(monkeypatch):
    """A LLM-triggered receive against a dead Revit broker surfaces
    the typed not_running error — never a fake create_count."""
    from tool_engine import ToolEngine

    monkeypatch.setattr(
        "ai_behaviour.get_tool_policy", lambda n: "allow", raising=False)
    # Force broker to report not-running.
    monkeypatch.setattr(
        "revit_broker.is_any_alive", lambda: False, raising=False)
    engine = _engine()
    result = engine.invoke(
        "revit__receive_from_speckle",
        {"source_url": "speckle://local/deadbeef"},
    )
    assert result["status"] == "error"
    assert "revit" in result["error"].lower()


def test_invoke_batch_set_parameters_routes_when_broker_offline(monkeypatch):
    """Same broker-offline guard for batch_set_parameters."""
    from tool_engine import ToolEngine

    monkeypatch.setattr(
        "ai_behaviour.get_tool_policy", lambda n: "allow", raising=False)
    monkeypatch.setattr(
        "revit_broker.is_any_alive", lambda: False, raising=False)
    engine = _engine()
    result = engine.invoke(
        "revit__batch_set_parameters",
        {"source_url": "speckle://local/deadbeef"},
    )
    assert result["status"] == "error"
    assert "revit" in result["error"].lower()


# ─── 3. input schema ──────────────────────────────────────────────────


def test_send_to_speckle_schema_has_value_and_model_name():
    """The LLM-visible input schema must list every parameter the op
    accepts, with their JSON types."""
    engine = _engine()
    specs = engine._connector_tool_specs()
    by_name = {s["name"]: s for s in specs}
    spec = by_name["revit__send_to_speckle"]
    schema = spec["input_schema"]
    assert "value" in schema["properties"]
    assert "model_name" in schema["properties"]
    assert "server_push" in schema["properties"]
    assert "server_url" in schema["properties"]


def test_batch_set_parameters_schema_requires_source_url():
    engine = _engine()
    specs = engine._connector_tool_specs()
    by_name = {s["name"]: s for s in specs}
    spec = by_name["revit__batch_set_parameters"]
    schema = spec["input_schema"]
    assert "source_url" in schema["properties"]
    # `required` lives at the schema root; source_url is REQUIRED.
    required = schema.get("required", [])
    assert "source_url" in required
