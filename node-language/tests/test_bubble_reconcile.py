"""Bubble reconciliation tests — fix the "empty assistant bubble"
race where 1-chunk responses don't render in the UI.

Bug: Some providers (Google Gemini, ArchHub Cloud) return the entire
response in a SINGLE chunk. The worker thread emits on_chunk(...)
via a queued Qt signal, then immediately emits `finished` with the
full response. If the main thread processes `finished` BEFORE the
chunk signal lands, the bubble never receives the text — even
though response.text has the full answer.

Fix in chat_window._on_finished: read the bubble's current rendered
length, compare to response.text length; if the bubble is behind,
force-set from the canonical text. Empty responses get a clear
placeholder so the user knows the LLM returned nothing (typically
out-of-credits / out-of-quota scenarios).

These tests verify the reconciliation logic at the data layer —
without spinning up the actual Qt threading. The behavior we lock
in: response.text is the source of truth on _on_finished; the
bubble's rendered state is reconciled to match.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))


@pytest.fixture(scope="session")
def qapp():
    from PyQt6.QtWidgets import QApplication
    import sys as _sys
    return QApplication.instance() or QApplication(_sys.argv)


class _Resp:
    """Stand-in for LLMResponse."""
    def __init__(self, text: str, model: str = "test:1", note: str = ""):
        self.text = text
        self.model = model
        self.routing_note = note
        self.tool_invocations = []


def _make_window_under_test(qapp):
    """Build the smallest ChatWindow-like object that exercises
    _on_finished without needing real router / manager / threads."""
    from chat_window import ChatWindow, ChatMessage, MessageBubble
    # Avoid touching real Studio infra — call __init__ minimally by
    # bypassing the full init. We need: _current_bubble, history,
    # status_left, _reset_input_state.
    win = ChatWindow.__new__(ChatWindow)
    win.history = []
    win._current_bubble = None
    win.send_btn = None
    win.stop_btn = None
    win.input = None
    win.worker = None
    win.worker_thread = None
    # status_left is just a label any QLabel works
    from PyQt6.QtWidgets import QLabel
    win.status_left = QLabel()
    # _reset_input_state pokes attributes — patch to no-op.
    win._reset_input_state = lambda: None
    return win


class TestOnFinishedReconcile:
    def test_bubble_repainted_when_behind_response_text(self, qapp):
        from chat_window import MessageBubble, ChatMessage
        win = _make_window_under_test(qapp)
        win.history.append(ChatMessage(role="assistant", content=""))
        bubble = MessageBubble("assistant")
        win._current_bubble = bubble
        # Simulate: chunk signal never delivered → bubble.text_view is empty
        assert bubble.text_view.toPlainText() == ""
        win._on_finished(_Resp("Hello, this is the full answer."))
        # After reconciliation: bubble should now show the canonical text.
        assert "Hello, this is the full answer." in bubble.text_view.toPlainText()
        # And history is reconciled too.
        assert win.history[-1].content == "Hello, this is the full answer."

    def test_bubble_left_alone_when_already_matches(self, qapp):
        from chat_window import MessageBubble, ChatMessage
        win = _make_window_under_test(qapp)
        win.history.append(ChatMessage(role="assistant",
                                          content="streamed answer"))
        bubble = MessageBubble("assistant")
        bubble.set_text("streamed answer")
        win._current_bubble = bubble
        win._on_finished(_Resp("streamed answer"))
        assert bubble.text_view.toPlainText() == "streamed answer"

    def test_empty_response_shows_placeholder(self, qapp):
        from chat_window import MessageBubble, ChatMessage
        win = _make_window_under_test(qapp)
        win.history.append(ChatMessage(role="assistant", content=""))
        bubble = MessageBubble("assistant")
        win._current_bubble = bubble
        win._on_finished(_Resp(""))
        # Bubble shows the empty-response placeholder so the user
        # doesn't stare at a blank rectangle.
        txt = bubble.text_view.toPlainText()
        assert "empty response" in txt.lower()
        # And the history mirrors the placeholder, NOT empty string,
        # so the session save guard rejects this as a stub later.
        assert win.history[-1].content   # non-empty

    def test_partially_streamed_bubble_gets_topped_up(self, qapp):
        # Chunk delivered some content but stream cut short. The
        # bubble has partial text; response.text is the canonical
        # full text. Reconciliation top-ups.
        from chat_window import MessageBubble, ChatMessage
        win = _make_window_under_test(qapp)
        win.history.append(ChatMessage(role="assistant", content="Hello"))
        bubble = MessageBubble("assistant")
        bubble.set_text("Hello")
        win._current_bubble = bubble
        win._on_finished(_Resp("Hello, this is the full answer."))
        assert "full answer" in bubble.text_view.toPlainText()


class TestUserOnlySessionFilter:
    """User-only sessions (assistant never responded) are now stubs."""

    @pytest.fixture
    def sessions_dir(self, tmp_path, monkeypatch):
        sd = tmp_path / "sessions"
        sd.mkdir(parents=True)
        import session_io
        monkeypatch.setattr(session_io, "SESSIONS_DIR", sd)
        return sd

    def test_user_only_hidden_from_rail(self, sessions_dir):
        import json
        p = sessions_dir / "x.archhub-session.json"
        p.write_text(json.dumps({
            "_name": "x", "_saved_at": "2026-05-11",
            "parameters": [], "chain": [],
            "_messages": [
                {"role": "user", "content": "ping"},
                {"role": "assistant", "content": ""},
            ],
        }), encoding="utf-8")
        from session_io import list_sessions
        assert list_sessions() == []

    def test_user_only_purged_by_cleanup(self, sessions_dir):
        import json
        p = sessions_dir / "x.archhub-session.json"
        p.write_text(json.dumps({
            "_name": "x", "_saved_at": "2026-05-11",
            "parameters": [], "chain": [],
            "_messages": [
                {"role": "user", "content": "ping"},
                {"role": "assistant", "content": ""},
            ],
        }), encoding="utf-8")
        from session_io import cleanup_empty_sessions
        assert cleanup_empty_sessions() == 1
        assert not p.exists()
