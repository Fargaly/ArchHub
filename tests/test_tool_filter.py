"""Gemini-overwhelm fix tests — _filter_tools_by_relevance.

Diagnosis from live trace log: Gemini Flash refuses to choose when
given 33 tool schemas at once. Returns type=final, text='', no
tool_calls. The user sees an empty bubble.

Fix: per-request trim to <=12 tools, scored by keyword overlap with
the user's last message, plus an always-keep set of cheap info/ping
tools for every host. Anthropic and OpenAI handle large lists fine
so the filter only fires for Gemini above 16 tools.
"""
from __future__ import annotations

import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))


def _t(name):
    return {"name": name}


THIRTY_THREE = [
    "archhub_list_connectors",
    "revit_ping", "revit_info", "revit_execute_csharp", "revit_screenshot",
    "acad_ping", "acad_info", "acad_execute_csharp",
    "max_ping", "max_info", "max_execute_python", "max_execute_maxscript",
    "blender_ping", "blender_info", "blender_save", "blender_render",
    "blender_execute_python",
    "speckle_list_projects", "speckle_get_project",
    "speckle_push_parameters", "speckle_pull_parameters",
    "outlook_info", "outlook_list_inbox", "outlook_search",
    "outlook_read_thread", "outlook_draft_reply", "outlook_save_attachments",
    "outlook_set_categories", "outlook_list_folders", "outlook_create_folder",
    "outlook_move_to_folder", "outlook_mark_read", "outlook_flag_for_followup",
]


class TestRelevanceFilter:
    def test_no_op_when_under_cap(self):
        from llm_router import _filter_tools_by_relevance
        small = [_t("revit_info"), _t("outlook_info")]
        out = _filter_tools_by_relevance(small, [], cap=12)
        assert out == small

    def test_caps_at_target_size(self):
        from llm_router import _filter_tools_by_relevance
        tools = [_t(n) for n in THIRTY_THREE]
        out = _filter_tools_by_relevance(
            tools, [{"role": "user", "content": "PING OUTLOOK"}],
            cap=12,
        )
        assert len(out) == 12

    def test_keyword_match_promotes_outlook_tools(self):
        from llm_router import _filter_tools_by_relevance
        tools = [_t(n) for n in THIRTY_THREE]
        out = _filter_tools_by_relevance(
            tools, [{"role": "user", "content": "PING OUTLOOK"}],
            cap=12,
        )
        names = {t["name"] for t in out}
        # Some outlook tools made it in due to keyword match.
        assert any("outlook" in n for n in names)

    def test_info_and_ping_tools_always_kept(self):
        from llm_router import _filter_tools_by_relevance
        tools = [_t(n) for n in THIRTY_THREE]
        out = _filter_tools_by_relevance(
            tools, [{"role": "user", "content": "say hi"}],
            cap=12,
        )
        names = {t["name"] for t in out}
        # No keyword matches — fill with the always-keep set.
        for must in ("revit_info", "outlook_info", "blender_info"):
            assert must in names

    def test_revit_query_pulls_revit_tools(self):
        from llm_router import _filter_tools_by_relevance
        tools = [_t(n) for n in THIRTY_THREE]
        out = _filter_tools_by_relevance(
            tools, [{"role": "user",
                      "content": "create a wall in revit"}],
            cap=12,
        )
        names = {t["name"] for t in out}
        assert "revit_info" in names
        # The wall-creation use case should keep revit_execute_csharp.
        assert "revit_execute_csharp" in names

    def test_function_wrapped_schema_form(self):
        # OpenAI-style {"type":"function","function":{"name":...}}
        from llm_router import _filter_tools_by_relevance
        wrapped = [
            {"type": "function", "function": {"name": n}}
            for n in THIRTY_THREE
        ]
        out = _filter_tools_by_relevance(
            wrapped, [{"role": "user", "content": "PING OUTLOOK"}],
            cap=12,
        )
        assert len(out) == 12

    def test_empty_history_falls_back_to_keep_set(self):
        from llm_router import _filter_tools_by_relevance
        tools = [_t(n) for n in THIRTY_THREE]
        out = _filter_tools_by_relevance(tools, [], cap=12)
        # With no keywords + 33 tools, just the always-keep set fills.
        names = {t["name"] for t in out}
        assert "outlook_info" in names
        assert "revit_info" in names


class TestRouterIntegratesFilter:
    """End-to-end: when 33 tools are active + Gemini routed, the
    schemas the client actually sees are filtered."""

    def test_running_gemini_route_gets_filtered_schemas(self,
                                                          monkeypatch):
        # This is a structural test — we substitute the google client
        # with one that records the tools= it received, then assert
        # the recorded count is <=12 instead of 33.
        from unittest.mock import MagicMock
        from manager import ConnectorState
        import llm_router as r
        from tool_engine import ToolEngine

        class FakeEntry:
            def __init__(self, fid, fam):
                self.id = fid; self.family = fam
                self.display_name = fid; self.state = ConnectorState.ACTIVE
        mgr = MagicMock()
        mgr.entries = [
            FakeEntry("revit-2025", "revit"),
            FakeEntry("acad-2026", "autocad"),
            FakeEntry("max-2026", "max"),
            FakeEntry("blender", "blender"),
            FakeEntry("outlook", "outlook"),
        ]
        tools = ToolEngine(mgr)
        # tool_schemas_for('google') will return ~30+ in this state.
        assert len(tools.tool_schemas_for("google")) >= 16

        router = r.LLMRouter(tools)
        captured = {}

        class FakeGoogle:
            def stream_completion(self, *, model, system, messages,
                                    tools, on_chunk, **kw):
                captured["tools_count"] = len(tools)
                captured["names"] = [t.get("name") for t in tools]
                return {"type": "final", "text": "Outlook ok."}

        # Pre-populate the client cache + skip the live key path.
        router._clients["google"] = FakeGoogle()
        # Force the route by blocking competing providers.
        router.block_provider("anthropic", "")
        router.block_provider("openai", "")
        router.complete(
            [{"role": "user", "content": "PING OUTLOOK"}],
            model="google:gemini-2.5-flash",
            on_chunk=lambda c: None,
        )
        assert captured["tools_count"] <= 12
        assert "outlook_info" in captured["names"]
