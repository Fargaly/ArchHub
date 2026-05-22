"""Refusal-detector tests.

Live trace from running app:
  google:gemini-2.5-flash  tool_schemas=12  iter0 ← type=final
  text_len=186  tool_calls=[]

Even with the AUTHORITY grant in the system prompt, Gemini Flash
and Pro still refuse to use outlook tools for data-access actions:
'I cannot read the content of your emails or automatically create
categories based on their content.' The tools are available; the
model just won't call them.

Fix: detect refusal text in the response → block the provider for
the standard window + re-route. Eventually reaches Ollama
command-r7b (tool-use specialist, no refusal training) or Claude
(when credits are topped up).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))


class TestRefusalDetector:
    @pytest.mark.parametrize("text", [
        "I cannot read the content of your emails or automatically "
        "create categories based on their content.",
        "I can only provide a summary of your Outlook inbox, "
        "such as the total number of emails and unread messages.",
        "My capabilities are limited to providing a summary of your "
        "inbox.",
        "I'm not able to access individual messages directly.",
        "I do not have the ability to read your emails.",
    ])
    def test_classic_gemini_refusals_flagged(self, text):
        from llm_router import _looks_like_refusal
        assert _looks_like_refusal(text, had_tools=True,
                                    tool_call_count=0) is True

    def test_short_text_not_flagged(self):
        # "I cannot." alone is too short — could be mid-stream chunk
        # or some other context. Need at least 30 chars to commit.
        from llm_router import _looks_like_refusal
        assert _looks_like_refusal("I cannot.", had_tools=True,
                                    tool_call_count=0) is False

    def test_tool_call_made_not_flagged(self):
        # If the model called a tool, we never flag — regardless of
        # text. The model is working as intended.
        from llm_router import _looks_like_refusal
        text = ("I cannot read the content of your emails directly, "
                "but I called outlook_info for a summary.")
        assert _looks_like_refusal(text, had_tools=True,
                                    tool_call_count=1) is False

    def test_no_tools_offered_not_flagged(self):
        # If tools weren't offered, refusal text doesn't matter —
        # the model legitimately can't act.
        from llm_router import _looks_like_refusal
        text = "I cannot read your emails right now since I don't "\
               "have access to your email."
        assert _looks_like_refusal(text, had_tools=False,
                                    tool_call_count=0) is False

    def test_action_text_not_flagged(self):
        from llm_router import _looks_like_refusal
        text = ("Outlook is active for ahmed@studio.com with 966 "
                "total messages and 3 unread.")
        assert _looks_like_refusal(text, had_tools=True,
                                    tool_call_count=0) is False

    def test_clarifying_question_not_flagged(self):
        # Asking a clarifying question is fine. Filter only catches
        # the 'I cannot / I am not able' refusal class.
        from llm_router import _looks_like_refusal
        text = ("Which view did you want the dimensions added to? "
                "Level 1 or Level 2?")
        assert _looks_like_refusal(text, had_tools=True,
                                    tool_call_count=0) is False
