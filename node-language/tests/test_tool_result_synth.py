"""Tool-result synthesizer tests — _summarise_tool_result.

When the LLM finishes a turn with empty text but successful tool
calls, we synthesize a one-line summary from the most recent
invocation. This catches the "empty bubble after PING OUTLOOK"
failure mode where Gemini emitted the tool call but no follow-up
text.
"""
from __future__ import annotations

import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))


class _Inv:
    def __init__(self, tool_name, status, result):
        self.tool_name = tool_name
        self.status = status
        self.result = result


class TestSummariseToolResult:
    def test_outlook_info_renders_friendly_summary(self):
        from llm_router import _summarise_tool_result
        s = _summarise_tool_result(_Inv(
            "outlook_info", "ok",
            {"status": "ok", "inbox_total": 966, "inbox_unread": 3,
             "drafts_count": 0,
             "default_account_email": "alice@studio.com"},
        ))
        assert "alice@studio.com" in s
        assert "966" in s
        assert "3 unread" in s
        assert s.endswith(".")

    def test_revit_info_renders_summary(self):
        from llm_router import _summarise_tool_result
        s = _summarise_tool_result(_Inv(
            "revit_info", "ok",
            {"status": "ok", "title": "Tower-A.rvt",
             "active_view": "Level 02", "version": "2025"},
        ))
        assert "Tower-A.rvt" in s
        assert "Level 02" in s

    def test_tool_error_surfaces_reason(self):
        from llm_router import _summarise_tool_result
        s = _summarise_tool_result(_Inv(
            "outlook_info", "error",
            {"status": "error", "error": "COM dispatch failed"},
        ))
        assert "failed" in s.lower()
        assert "COM dispatch failed" in s

    def test_generic_ping_returns_reachable(self):
        from llm_router import _summarise_tool_result
        s = _summarise_tool_result(_Inv("revit_ping", "ok",
                                          {"status": "ok"}))
        assert "Revit" in s
        assert "reachable" in s.lower()

    def test_generic_ok_falls_back_to_keys(self):
        from llm_router import _summarise_tool_result
        s = _summarise_tool_result(_Inv(
            "speckle_list_projects", "ok",
            {"status": "ok", "count": 7, "first_name": "Tower-A"},
        ))
        # Generic fallback picks 2 scalar fields.
        assert "speckle_list_projects" in s
        assert "count=7" in s

    def test_returns_string_never_raises_on_weird_input(self):
        from llm_router import _summarise_tool_result
        s = _summarise_tool_result(_Inv("x", "ok", None))
        assert isinstance(s, str) and s
        s = _summarise_tool_result(_Inv("x", "ok", "raw string"))
        assert "raw string" in s

    def test_blender_info_summary(self):
        from llm_router import _summarise_tool_result
        s = _summarise_tool_result(_Inv(
            "blender_info", "ok",
            {"status": "ok", "filepath": "C:/proj/scene.blend",
             "scene": "Scene", "object_count": 14},
        ))
        assert "scene.blend" in s
        assert "14" in s
