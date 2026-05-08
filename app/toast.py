"""Toast — quiet status banner for the Studio shell.

Replaces noisy QMessageBox.information popups for low-stakes confirms
("Skill installed.", "Workflow saved.", "Theme switched."). Modal
dialogs are reserved for actions that genuinely need a confirm/cancel.

Usage:
    from toast import show_toast
    show_toast(parent_widget, "Skill installed.", kind="ok")

Kinds: 'ok' (terra), 'warn' (warn), 'err' (err). Default 'ok'.

Brand voice (principle 07 — quiet motion): the toast slides up from
the bottom-centre over 200 ms, holds for 2.5 s, slides back out over
200 ms. Click anywhere on the toast to dismiss early.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import (
    Qt, QPoint, QPropertyAnimation, QEasingCurve, QTimer, QSize,
    pyqtProperty,
)
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

from design_tokens import COLOR as T, RADIUS, SPACE, TYPE


_KIND_COLOR = {
    "ok":   T["accent"],
    "warn": T["warn"],
    "err":  T["err"],
}


class _Toast(QFrame):
    def __init__(self, parent: QWidget, text: str, *, kind: str = "ok"):
        super().__init__(parent)
        self.setObjectName("studioToast")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents,
                          False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        accent = _KIND_COLOR.get(kind, T["accent"])
        self.setStyleSheet(
            f"QFrame#studioToast {{ "
            f"  background:{T['bgPanel']}; "
            f"  border:1px solid {accent}; "
            f"  border-radius:{RADIUS['lg']}px; "
            f"}}"
            f"QLabel#studioToastText {{ "
            f"  font-family:{TYPE['fontSans']}; font-size:13px; "
            f"  color:{T['ink']}; }}"
            f"QLabel#studioToastDot {{ "
            f"  color:{accent}; font-size:11px; }}"
        )
        h = QHBoxLayout(self)
        h.setContentsMargins(SPACE["md"]+2, SPACE["sm"],
                             SPACE["md"]+2, SPACE["sm"])
        h.setSpacing(SPACE["sm"])
        dot = QLabel("●")
        dot.setObjectName("studioToastDot")
        h.addWidget(dot)
        msg = QLabel(text)
        msg.setObjectName("studioToastText")
        h.addWidget(msg)
        self.adjustSize()

    def mousePressEvent(self, ev) -> None:
        # Click-anywhere to dismiss.
        self.hide()
        self.deleteLater()


def show_toast(parent: QWidget, text: str, *, kind: str = "ok",
               duration_ms: int = 2500) -> None:
    """Show a toast above `parent`. No-op if parent is None."""
    if parent is None or not text:
        return
    toast = _Toast(parent, text, kind=kind)
    # Position bottom-centre with 24 px clearance from the bottom edge.
    pw = parent.width()
    ph = parent.height()
    tw = toast.sizeHint().width()
    th = toast.sizeHint().height()
    final_x = max(24, (pw - tw) // 2)
    final_y = ph - th - 56     # leave room for the status rule above
    start_y = ph + 20          # off-screen below
    toast.setGeometry(final_x, start_y, tw, th)
    toast.show()
    toast.raise_()

    # Slide up.
    anim_in = QPropertyAnimation(toast, b"pos")
    anim_in.setDuration(200)
    anim_in.setStartValue(QPoint(final_x, start_y))
    anim_in.setEndValue(QPoint(final_x, final_y))
    anim_in.setEasingCurve(QEasingCurve.Type.OutCubic)
    anim_in.start()

    def _slide_out():
        if not toast.isVisible():
            return
        anim_out = QPropertyAnimation(toast, b"pos")
        anim_out.setDuration(200)
        anim_out.setStartValue(toast.pos())
        anim_out.setEndValue(QPoint(final_x, start_y))
        anim_out.setEasingCurve(QEasingCurve.Type.InCubic)
        anim_out.finished.connect(toast.deleteLater)
        anim_out.start()
        # Keep a reference so it isn't garbage-collected mid-animation.
        toast._anim_out = anim_out

    QTimer.singleShot(duration_ms, _slide_out)
    toast._anim_in = anim_in   # ditto
