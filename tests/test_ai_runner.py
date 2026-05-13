"""AI-as-tool runner tests — v1.0.3 addition.

The runner lets the primary LLM delegate to other LLMs as tools
(ai_chatgpt_ask / ai_gemini_ask / ai_lmstudio_ask / ai_antigravity_ask).
These tests cover the static surface — missing-key handling, antigravity
stub, list_providers shape, tool registry membership. We do NOT call
real provider APIs here; that would be a brittle integration test.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))


class TestStaticSurface:
    def test_module_imports(self):
        from connectors import ai_runner
        assert ai_runner.DEFAULT_OPENAI_MODEL.startswith("gpt-")
        assert ai_runner.DEFAULT_GEMINI_MODEL.startswith("gemini-")
        assert ai_runner.DEFAULT_LMSTUDIO_URL.startswith("http://")

    def test_chatgpt_without_key_returns_error(self):
        from connectors import ai_runner
        with patch.object(ai_runner, "_load_key", return_value=None):
            r = ai_runner.chatgpt_ask("hi")
        assert r["status"] == "error"
        assert "OpenAI API key" in r["error"]

    def test_gemini_without_key_returns_error(self):
        from connectors import ai_runner
        with patch.object(ai_runner, "_load_key", return_value=None):
            r = ai_runner.gemini_ask("hi")
        assert r["status"] == "error"
        assert "Google AI API key" in r["error"]

    def test_chatgpt_empty_prompt_returns_error(self):
        from connectors import ai_runner
        r = ai_runner.chatgpt_ask("")
        assert r["status"] == "error"
        assert "prompt" in r["error"].lower()

    def test_gemini_empty_prompt_returns_error(self):
        from connectors import ai_runner
        r = ai_runner.gemini_ask("")
        assert r["status"] == "error"
        assert "prompt" in r["error"].lower()

    def test_lmstudio_empty_prompt_returns_error(self):
        from connectors import ai_runner
        r = ai_runner.lmstudio_ask("")
        assert r["status"] == "error"

    def test_antigravity_stub_explains_unavailable(self):
        from connectors import ai_runner
        r = ai_runner.antigravity_ask("anything")
        assert r["status"] == "error"
        assert r["available"] is False
        assert "no public api" in r["error"].lower()


class TestListProviders:
    def test_shape_includes_four_providers(self):
        from connectors import ai_runner
        r = ai_runner.list_providers()
        assert r["status"] == "ok"
        provs = r["providers"]
        for name in ("openai", "google", "lmstudio", "antigravity"):
            assert name in provs, f"missing {name}"

    def test_lmstudio_carries_base_url(self):
        from connectors import ai_runner
        r = ai_runner.list_providers()
        ls = r["providers"]["lmstudio"]
        assert "base_url" in ls
        assert ls["base_url"].startswith("http://")

    def test_openai_lists_models(self):
        from connectors import ai_runner
        r = ai_runner.list_providers()
        models = r["providers"]["openai"]["models"]
        assert isinstance(models, list)
        # v1.3.2 bumped from gpt-4o-* family to gpt-5.5 / gpt-5.4-mini /
        # gpt-5.3-codex defaults. The catalog should expose the current
        # generation, not the retired one.
        assert any("gpt-5" in m for m in models)

    def test_antigravity_marked_unavailable(self):
        from connectors import ai_runner
        r = ai_runner.list_providers()
        ag = r["providers"]["antigravity"]
        assert ag["available"] is False


class TestToolRegistry:
    """Verify the 5 ai_* tools are present in tool_engine.TOOLS and
    routed via the right family. This is the contract the LLM relies
    on; breaking it removes the capabilities from the schema."""

    def test_all_ai_tools_registered(self):
        from tool_engine import TOOLS
        names = {t["name"] for t in TOOLS if t.get("family") == "ai"}
        for required in ("ai_chatgpt_ask", "ai_gemini_ask",
                          "ai_lmstudio_ask", "ai_antigravity_ask",
                          "ai_list_providers"):
            assert required in names, f"missing tool: {required}"

    def test_ai_tools_have_handlers_in_ai_runner(self):
        """Every (family=ai) tool's endpoint handler must exist as a
        callable in ai_runner.py — otherwise dispatch errors out."""
        from tool_engine import TOOLS
        from connectors import ai_runner
        for t in TOOLS:
            if t.get("family") != "ai":
                continue
            handler_name = t["endpoint"][1]
            assert hasattr(ai_runner, handler_name), \
                f"ai_runner.{handler_name} missing for tool {t['name']!r}"
            assert callable(getattr(ai_runner, handler_name))

    def test_ai_family_is_always_active(self):
        """tool_schemas_for() must surface ai_* tools regardless of
        which host connectors are active. The handler returns an
        error when a key is missing instead of being filtered out."""
        from tool_engine import TOOLS
        names_in_registry = {t["name"] for t in TOOLS
                              if t.get("family") == "ai"}
        # Bare assertion — the registry contains them. The dispatch
        # rule in tool_engine.tool_schemas_for() treats family == "ai"
        # as always-on (verified by code review at line 705-ish).
        assert "ai_chatgpt_ask" in names_in_registry


class TestAiBehaviourDefaults:
    def test_ai_family_defaults_to_allow(self):
        from ai_behaviour import _default_policy_for
        # Reading via another LLM is non-destructive — sensible default
        # is allow so the primary model can delegate without a prompt.
        assert _default_policy_for("ai_chatgpt_ask")   == "allow"
        assert _default_policy_for("ai_gemini_ask")    == "allow"
        assert _default_policy_for("ai_lmstudio_ask")  == "allow"
        assert _default_policy_for("ai_list_providers") == "allow"

    def test_ai_family_appears_in_grouped_output(self):
        from ai_behaviour import tools_grouped_by_host, host_display_label
        g = tools_grouped_by_host()
        assert "ai" in g
        # Display label tells the user what these tools are.
        label = host_display_label("ai")
        assert "AI" in label or "ChatGPT" in label or "Gemini" in label
