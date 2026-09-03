"""Chat input + bubble regression tests.

Bug: chat input was QLineEdit → no Shift+Enter support, single-line only.
Bug: long message bodies appeared truncated because _adjust_height
     measured against viewport().width()=0 on first paint, clamping
     setFixedHeight to 20px.
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


# ---------------------------------------------------------------------------
class TestPasteInput:
    def test_is_plain_text_edit(self, qapp):
        # Was QLineEdit (single-line); now QPlainTextEdit (multi-line).
        from chat_window import _PasteInput
        from PyQt6.QtWidgets import QPlainTextEdit
        assert issubclass(_PasteInput, QPlainTextEdit)

    def test_lineedit_compat_api(self, qapp):
        # Existing call sites use text() / setText() / clear() /
        # setCursorPosition() / setEnabled() / setFocus() / setPlaceholderText()
        from chat_window import _PasteInput
        inp = _PasteInput()
        for fn in ("text", "setText", "clear", "setCursorPosition",
                    "setEnabled", "setFocus", "setPlaceholderText"):
            assert hasattr(inp, fn), f"missing {fn}"
        # roundtrip
        inp.setText("hello")
        assert inp.text() == "hello"
        inp.clear()
        assert inp.text() == ""

    def test_signals_present(self, qapp):
        from chat_window import _PasteInput
        inp = _PasteInput()
        assert hasattr(inp, "returnPressed")
        assert hasattr(inp, "image_pasted")

    def test_plain_enter_emits_returnpressed(self, qapp):
        from chat_window import _PasteInput
        from PyQt6.QtCore import Qt, QEvent
        from PyQt6.QtGui import QKeyEvent
        inp = _PasteInput()
        inp.setText("hello")
        sent = []
        inp.returnPressed.connect(lambda: sent.append(True))
        ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return,
                       Qt.KeyboardModifier.NoModifier)
        inp.keyPressEvent(ev)
        assert sent == [True]
        # Text was NOT mutated by Enter.
        assert inp.text() == "hello"

    def test_shift_enter_inserts_newline(self, qapp):
        from chat_window import _PasteInput
        from PyQt6.QtCore import Qt, QEvent
        from PyQt6.QtGui import QKeyEvent
        inp = _PasteInput()
        inp.setText("line1")
        # Move cursor to end so newline appends.
        inp.setCursorPosition(len(inp.text()))
        sent = []
        inp.returnPressed.connect(lambda: sent.append(True))
        ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return,
                       Qt.KeyboardModifier.ShiftModifier)
        inp.keyPressEvent(ev)
        assert sent == []                  # did NOT submit
        assert "\n" in inp.text()           # newline inserted
        assert inp.text().startswith("line1")

    def test_ctrl_enter_also_inserts_newline(self, qapp):
        # Slack/Discord convention — keep both Shift+Enter AND Ctrl+Enter
        # as newline inserters so muscle memory works either way.
        from chat_window import _PasteInput
        from PyQt6.QtCore import Qt, QEvent
        from PyQt6.QtGui import QKeyEvent
        inp = _PasteInput()
        inp.setText("a")
        inp.setCursorPosition(len(inp.text()))
        sent = []
        inp.returnPressed.connect(lambda: sent.append(True))
        ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return,
                       Qt.KeyboardModifier.ControlModifier)
        inp.keyPressEvent(ev)
        assert sent == []
        assert "\n" in inp.text()


# ---------------------------------------------------------------------------
class TestBubbleHeight:
    def test_long_message_grows_height(self, qapp):
        # 500-char message should produce a height >> 20px (the old
        # truncated-bug clamp). After fix: bubble grows to fit content.
        from chat_window import MessageBubble
        b = MessageBubble("user")
        b.set_text("X" * 500)
        b.resize(720, 200)
        b._adjust_height()
        assert b.text_view.height() > 60   # would be 20 with the bug

    def test_zero_width_fallback_does_not_clamp_to_20(self, qapp):
        # Simulate first-paint: width is 0. Old code set height=20 because
        # doc.setTextWidth(0) collapsed the document. Fix: fall back to
        # maximumWidth() / sensible default.
        from chat_window import MessageBubble
        b = MessageBubble("assistant")
        b.set_text("Once upon a time " * 30)   # ~480 chars
        # Don't resize → width may be 0 here.
        b._adjust_height()
        assert b.text_view.height() > 40

    def test_short_message_stays_small(self, qapp):
        from chat_window import MessageBubble
        b = MessageBubble("user")
        b.set_text("hi")
        b.resize(720, 200)
        b._adjust_height()
        # Single line should still be modest height — not bloated.
        assert b.text_view.height() < 80
