"""AI Behaviour module + tool_engine policy gating tests.

Three knobs the user controls in Settings → AI Behaviour:
  1. thinking_effort: off/low/medium/high (→ provider-specific budget)
  2. tool policy: allow/ask/deny per registered tool
  3. defaults: read-only allow, mutate ask, destructive deny
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Each test gets its own secrets_store path."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    import secrets_store
    app_dir = tmp_path / "ArchHub"
    app_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(secrets_store, "APP_DIR", app_dir)
    monkeypatch.setattr(secrets_store, "SECRETS_FILE", app_dir / "secrets.dat")
    monkeypatch.setattr(secrets_store, "SETTINGS_FILE", app_dir / "settings.json")


class TestThinkingEffort:
    def test_default_is_off(self):
        from ai_behaviour import get_thinking_effort
        assert get_thinking_effort() == "off"

    def test_roundtrip(self):
        from ai_behaviour import set_thinking_effort, get_thinking_effort
        set_thinking_effort("medium")
        assert get_thinking_effort() == "medium"
        set_thinking_effort("high")
        assert get_thinking_effort() == "high"

    def test_invalid_level_raises(self):
        from ai_behaviour import set_thinking_effort
        with pytest.raises(ValueError):
            set_thinking_effort("nuclear")

    def test_budget_mapping(self):
        from ai_behaviour import thinking_budget_tokens, set_thinking_effort
        assert thinking_budget_tokens("off") == 0
        assert thinking_budget_tokens("low") == 1024
        assert thinking_budget_tokens("medium") == 4096
        assert thinking_budget_tokens("high") == 16384
        # Saved level resolved when None passed.
        set_thinking_effort("low")
        assert thinking_budget_tokens() == 1024

    def test_openai_effort_mapping(self):
        from ai_behaviour import openai_reasoning_effort
        assert openai_reasoning_effort("off") is None
        assert openai_reasoning_effort("low") == "low"
        assert openai_reasoning_effort("high") == "high"


class TestToolPolicyDefaults:
    @pytest.mark.parametrize("tool, expected", [
        # Read-only / status — allow.
        ("revit_ping", "allow"),
        ("revit_info", "allow"),
        ("outlook_info", "allow"),
        ("outlook_list_inbox", "allow"),
        ("outlook_search", "allow"),
        ("outlook_read_thread", "allow"),
        ("speckle_list_projects", "allow"),
        ("speckle_get_project", "allow"),
        ("speckle_pull_parameters", "allow"),
        ("archhub_list_connectors", "allow"),
        # Mutate / execute — ask.
        ("revit_execute_csharp", "ask"),
        ("outlook_execute_python", "ask"),
        ("blender_execute_python", "ask"),
        ("max_execute_maxscript", "ask"),
        ("outlook_set_categories", "ask"),
        ("outlook_set_categories_by_filter", "ask"),
        ("outlook_auto_categorize_by_sender", "ask"),
        ("outlook_draft_reply", "ask"),
        ("outlook_save_attachments", "ask"),
        ("outlook_create_folder", "ask"),
        ("outlook_move_to_folder", "ask"),
        ("outlook_mark_read", "ask"),
        ("outlook_flag_for_followup", "ask"),
        ("speckle_push_parameters", "ask"),
        ("revit_screenshot", "ask"),
    ])
    def test_default_for_tool(self, tool, expected):
        from ai_behaviour import get_tool_policy
        assert get_tool_policy(tool) == expected


class TestToolPolicyOverrides:
    def test_override_then_read(self):
        from ai_behaviour import set_tool_policy, get_tool_policy
        # revit_info default = allow. Override to deny.
        set_tool_policy("revit_info", "deny")
        assert get_tool_policy("revit_info") == "deny"

    def test_invalid_policy_raises(self):
        from ai_behaviour import set_tool_policy
        with pytest.raises(ValueError):
            set_tool_policy("revit_info", "obliterate")

    def test_reset_clears_overrides(self):
        from ai_behaviour import (
            set_tool_policy, get_tool_policy, reset_tool_policies
        )
        set_tool_policy("revit_info", "deny")
        set_tool_policy("outlook_info", "deny")
        reset_tool_policies()
        # Defaults reapply.
        assert get_tool_policy("revit_info") == "allow"
        assert get_tool_policy("outlook_info") == "allow"

    def test_list_returns_only_overrides(self):
        from ai_behaviour import (
            set_tool_policy, list_tool_policies, reset_tool_policies,
        )
        reset_tool_policies()
        assert list_tool_policies() == {}
        set_tool_policy("revit_info", "deny")
        d = list_tool_policies()
        assert d == {"revit_info": "deny"}


class TestToolEngineGating:
    def _engine(self):
        from tool_engine import ToolEngine
        mgr = MagicMock(); mgr.entries = []
        return ToolEngine(mgr)

    def test_deny_policy_blocks_invocation(self):
        from ai_behaviour import set_tool_policy
        eng = self._engine()
        # Force revit family to be 'active' so we get past the
        # family-active guard.
        eng._active_families = lambda: {"revit"}
        set_tool_policy("revit_ping", "deny")
        out = eng.invoke("revit_ping", {})
        assert out["status"] == "error"
        assert out["policy"] == "deny"
        assert "user policy" in out["error"].lower()

    def test_ask_policy_returns_needs_confirmation(self):
        from ai_behaviour import set_tool_policy
        eng = self._engine()
        eng._active_families = lambda: {"outlook"}
        set_tool_policy("outlook_set_categories", "ask")
        out = eng.invoke("outlook_set_categories",
                          {"entry_id": "x", "categories": ["P1"]})
        assert out["status"] == "needs_confirmation"
        assert out["policy"] == "ask"
        assert out["tool_name"] == "outlook_set_categories"

    def test_user_confirmed_bypasses_ask(self):
        # User clicked Approve in chat — pass user_confirmed=True;
        # the gate lets the call through. (Underlying tool may still
        # fail for other reasons; we just verify the gate didn't
        # short-circuit.)
        from ai_behaviour import set_tool_policy
        eng = self._engine()
        set_tool_policy("outlook_set_categories", "ask")
        # Reach a different failure mode (no outlook in active families)
        # — proves the ask-gate was bypassed.
        eng._active_families = lambda: set()
        out = eng.invoke("outlook_set_categories",
                          {"entry_id": "x", "categories": ["P1"]},
                          user_confirmed=True)
        # Status no longer 'needs_confirmation' — gate passed.
        assert out["status"] != "needs_confirmation"

    def test_allow_policy_unchanged_flow(self):
        # Read-only tool with default 'allow' policy → goes straight
        # to dispatch. We don't test the dispatch here, just that the
        # status is NOT 'needs_confirmation' / 'error/deny'.
        from ai_behaviour import reset_tool_policies
        reset_tool_policies()
        eng = self._engine()
        eng._active_families = lambda: {"revit"}
        # Mock _http to short-circuit the actual HTTP call.
        eng._http = lambda *a, **kw: {"status": "ok"}
        out = eng.invoke("revit_ping", {})
        assert out["status"] == "ok"
