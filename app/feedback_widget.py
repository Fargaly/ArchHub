"""In-chat thumbs / feedback row.

Shown attached to the bottom of every assistant bubble. Two clicks:
  👍 — `feedback_thumb_up`
  👎 — opens a tiny inline text box → `feedback_thumb_down` event with
        free-text comment.

Events fire through `telemetry.track_event` so they obey the user's
opt-in. If telemetry is off, clicks still register as a local
in-memory "appreciated" / "complained" tally that the friction-report
script can read from `%LOCALAPPDATA%/ArchHub/feedback.json`.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLineEdit, QPushButton, QSizePolicy, QVBoxLayout,
    QWidget,
)


_FEEDBACK_PATH = (
    Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    / "ArchHub" / "feedback.json"
)


def _record_local(direction: str, *, comment: str | None = None,
                  message_id: str | None = None,
                  skill_id: str | None = None) -> None:
    """Append to local feedback log. Always runs — even when telemetry off."""
    _FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing = (
            json.loads(_FEEDBACK_PATH.read_text(encoding="utf-8"))
            if _FEEDBACK_PATH.exists() else []
        )
    except Exception:
        existing = []
    existing.append({
        "ts": datetime.now(timezone.utc).isoformat(),
        "direction": direction,           # "up" | "down"
        "comment": (comment or "")[:1000],
        "message_id": message_id,
        "skill_id": skill_id,
    })
    # Cap at 1000 entries — bounded log.
    if len(existing) > 1000:
        existing = existing[-1000:]
    _FEEDBACK_PATH.write_text(json.dumps(existing, indent=2), encoding="utf-8")


class FeedbackRow(QWidget):
    """Compact 👍 👎 row + inline comment box on thumb-down.

    Emits `submitted(str, str)` with (direction, comment).  message_id
    + skill_id let the friction-report join feedback to the run that
    earned it.
    """

    submitted = pyqtSignal(str, str)        # (direction, comment)

    def __init__(self, *, message_id: str | None = None,
                 skill_id: str | None = None, parent=None):
        super().__init__(parent)
        self._message_id = message_id
        self._skill_id = skill_id

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        row.addStretch(1)

        self._up = QPushButton("👍")
        self._down = QPushButton("👎")
        for b in (self._up, self._down):
            b.setObjectName("ghostButton")
            b.setFlat(True)
            b.setFixedSize(28, 22)
            b.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            b.setStyleSheet(
                "QPushButton { color: #6f6d65; font-size: 14px; "
                "background: transparent; border: none; padding: 0; }"
                "QPushButton:hover { color: #d97757; }"
                "QPushButton:checked { color: #788c5d; }"
            )
            b.setCheckable(True)
        self._up.clicked.connect(self._on_up)
        self._down.clicked.connect(self._on_down)
        row.addWidget(self._up)
        row.addWidget(self._down)
        outer.addLayout(row)

        # Inline comment box, hidden until thumbs-down.
        self._comment_frame = QFrame()
        cf = QHBoxLayout(self._comment_frame)
        cf.setContentsMargins(0, 4, 0, 0)
        cf.setSpacing(4)
        self._comment = QLineEdit()
        self._comment.setPlaceholderText("What went wrong? (optional, will be sent redacted)")
        self._comment.setStyleSheet(
            "QLineEdit { background: #232321; color: #f4efe8; "
            "border: 1px solid #2a2a28; border-radius: 8px; padding: 5px 8px; "
            "font-size: 12px; }"
        )
        self._comment.returnPressed.connect(self._submit_down)
        cf.addWidget(self._comment, 1)
        send = QPushButton("Send")
        send.setObjectName("ghostButton")
        send.clicked.connect(self._submit_down)
        cf.addWidget(send)
        self._comment_frame.hide()
        outer.addWidget(self._comment_frame)

    # ----- handlers -------------------------------------------------------
    def _on_up(self) -> None:
        if not self._up.isChecked():        # un-toggled
            return
        self._down.setChecked(False)
        self._comment_frame.hide()
        self._dispatch("up", "")

    def _on_down(self) -> None:
        if not self._down.isChecked():
            self._comment_frame.hide()
            return
        self._up.setChecked(False)
        self._comment_frame.show()
        self._comment.setFocus()

    def _submit_down(self) -> None:
        comment = (self._comment.text() or "").strip()
        self._comment_frame.hide()
        self._dispatch("down", comment)

    def _dispatch(self, direction: str, comment: str) -> None:
        # Local log always.
        try:
            _record_local(direction, comment=comment,
                          message_id=self._message_id,
                          skill_id=self._skill_id)
        except Exception:
            pass
        # Cloud telemetry (no-op if off).
        try:
            from telemetry import track_event
            track_event(
                "user_feedback",
                direction=direction,
                comment=comment,
                message_id=self._message_id,
                skill_id=self._skill_id,
            )
        except Exception:
            pass
        self.submitted.emit(direction, comment)
