"""ArchHub Company Pets — always-on-top desktop overlay.

Tiny strip of 5 pet sprites (one per Ollama dept). Each pet animates
between idle / thinking / shipping based on the dept's task state on
disk. Click a pet → pops the latest output Markdown in a small viewer.

Design choices:
  * No external assets — pets are emoji + label so the file ships zero
    binary deps.
  * State refresh every 5s by walking agents/tasks/<dept>/ +
    agents/logs/token_meter.json. No daemon dependency — works even
    if the daemon is down (shows everyone idle).
  * Frameless + always-on-top + draggable. Lives in the bottom-right
    corner by default.
  * Right-click the strip → menu with Hide, Move, "Open dashboard",
    "Run scheduler tick now".

Drop into any Python that has PyQt6. Imports stay inside guards so
the file imports cleanly in headless tests.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# Where the daemon writes — same paths as agents/queue.py.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_TASKS_DIR = _REPO_ROOT / "agents" / "tasks"
_OUTPUTS_DIR = _REPO_ROOT / "agents" / "outputs"
_LOGS_DIR = _REPO_ROOT / "agents" / "logs"


# ---------------------------------------------------------------------------
@dataclass
class PetState:
    dept: str
    label: str
    emoji_idle: str
    emoji_busy: str
    emoji_done: str
    state: str = "idle"          # idle | busy | done | failed
    last_summary: str = ""


_PET_DEFS: list[PetState] = [
    PetState("docs",       "Docs",       "📝", "✏️", "📄"),
    PetState("qa",         "QA",         "🐛", "🔍", "✅"),
    PetState("rnd",        "R&D",        "🧪", "⚗️", "🔬"),
    PetState("eng",        "Eng",        "🔧", "⚙️", "🚀"),
    PetState("ops",        "Ops",        "📦", "🛠️", "📦"),
    PetState("telemetry",  "Telemetry",  "📊", "📈", "📊"),
    PetState("backlog",    "Backlog",    "📋", "📥", "📋"),
    PetState("watcher",    "Watcher",    "👀", "🔭", "👁️"),
]


# ---------------------------------------------------------------------------
def _scan_dept_state(dept: str) -> tuple[str, str]:
    """Return (state, last_summary) for a dept by walking task files."""
    d = _TASKS_DIR / dept
    if not d.exists():
        return "idle", ""

    # Live lock = currently working.
    locks = list(d.glob("*.lock"))
    if locks:
        # Pull the title from the .yaml twin so we can show what it's
        # working on.
        latest = max(locks, key=lambda p: p.stat().st_mtime)
        yaml = latest.with_suffix(".yaml")
        if yaml.exists():
            try:
                data = json.loads(yaml.read_text(encoding="utf-8"))
                return "busy", (data.get("title") or "")[:60]
            except Exception:
                pass
        return "busy", "running"

    # Recent failed (within 24h) → red dot.
    fails = list(d.glob("*.failed"))
    if fails:
        latest = max(fails, key=lambda p: p.stat().st_mtime)
        age_h = (datetime.now().timestamp() - latest.stat().st_mtime) / 3600
        if age_h < 24:
            return "failed", "last task failed"

    # Latest done → green pulse for 1h then back to idle.
    dones = list(d.glob("*.done"))
    if dones:
        latest = max(dones, key=lambda p: p.stat().st_mtime)
        age_h = (datetime.now().timestamp() - latest.stat().st_mtime) / 3600
        if age_h < 1:
            return "done", "just shipped"

    return "idle", ""


def _pet_emoji(p: PetState) -> str:
    if p.state == "busy":   return p.emoji_busy
    if p.state == "done":   return p.emoji_done
    if p.state == "failed": return "💢"
    return p.emoji_idle


# ---------------------------------------------------------------------------
def main() -> int:
    """Entry point — `python -m app.company_pets`."""
    from PyQt6.QtCore import (
        Qt, QTimer, QPoint, pyqtSignal,
    )
    from PyQt6.QtGui import QAction, QFont, QPalette, QColor, QCursor
    from PyQt6.QtWidgets import (
        QApplication, QFrame, QHBoxLayout, QLabel, QMenu, QSystemTrayIcon,
        QVBoxLayout, QWidget, QPushButton, QSizePolicy,
    )

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # ----- one PetWidget per dept -------------------------------------------
    class PetWidget(QFrame):
        clicked = pyqtSignal(str)         # dept

        def __init__(self, pet: PetState):
            super().__init__()
            self.pet = pet
            self.setObjectName("petCard")
            self.setFixedSize(74, 64)
            self.setStyleSheet(
                "QFrame#petCard { background: rgba(28,28,26,200); "
                "border: 1px solid rgba(80,80,76,180); border-radius: 10px; }"
                "QFrame#petCard:hover { border: 1px solid #d97757; }"
            )
            v = QVBoxLayout(self)
            v.setContentsMargins(2, 2, 2, 2)
            v.setSpacing(0)
            self.face = QLabel(_pet_emoji(pet))
            self.face.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.face.setStyleSheet("font-size: 26px;")
            v.addWidget(self.face)
            self.label = QLabel(pet.label)
            self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.label.setStyleSheet("color: #b0aea5; font-size: 10px;")
            v.addWidget(self.label)
            self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            self.setToolTip(f"{pet.label}: idle")

        def mousePressEvent(self, ev):
            if ev.button() == Qt.MouseButton.LeftButton:
                self.clicked.emit(self.pet.dept)
            super().mousePressEvent(ev)

        def update_state(self, state: str, summary: str) -> None:
            self.pet.state = state
            self.pet.last_summary = summary
            self.face.setText(_pet_emoji(self.pet))
            tip = f"{self.pet.label}: {state}"
            if summary:
                tip += f"\n{summary}"
            self.setToolTip(tip)

    # ----- container strip ---------------------------------------------------
    class CompanyStrip(QWidget):
        def __init__(self):
            super().__init__()
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.Tool
                | Qt.WindowType.WindowStaysOnTopHint
            )
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self._drag_offset = QPoint()

            outer = QHBoxLayout(self)
            outer.setContentsMargins(8, 6, 8, 6)
            outer.setSpacing(4)

            self.pets: dict[str, PetWidget] = {}
            for p in _PET_DEFS:
                w = PetWidget(p)
                w.clicked.connect(self._on_pet_clicked)
                outer.addWidget(w)
                self.pets[p.dept] = w

            # Place bottom-right of primary screen.
            self.adjustSize()
            screen = app.primaryScreen()
            if screen is not None:
                geo = screen.availableGeometry()
                self.move(geo.right() - self.width() - 24,
                          geo.bottom() - self.height() - 24)

            # Refresh timer.
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._refresh)
            self._timer.start(5000)
            self._refresh()

        def mousePressEvent(self, ev):
            if ev.button() == Qt.MouseButton.LeftButton:
                self._drag_offset = ev.globalPosition().toPoint() - self.pos()
            elif ev.button() == Qt.MouseButton.RightButton:
                self._show_menu(ev.globalPosition().toPoint())

        def mouseMoveEvent(self, ev):
            if ev.buttons() & Qt.MouseButton.LeftButton:
                self.move(ev.globalPosition().toPoint() - self._drag_offset)

        def _refresh(self):
            for dept, widget in self.pets.items():
                state, summary = _scan_dept_state(dept)
                widget.update_state(state, summary)

        def _on_pet_clicked(self, dept: str):
            # Open the latest output Markdown in the OS default viewer.
            out_root = _OUTPUTS_DIR / dept
            if not out_root.exists():
                return
            mds = list(out_root.rglob("completion.md"))
            if not mds:
                return
            latest = max(mds, key=lambda p: p.stat().st_mtime)
            try:
                os.startfile(str(latest))     # Windows-only; fine.
            except Exception:
                pass

        def _show_menu(self, pos):
            menu = QMenu(self)
            act_tick = QAction("Run scheduler tick now", self)
            act_tick.triggered.connect(self._run_tick)
            menu.addAction(act_tick)

            act_dash = QAction("Open dashboard", self)
            act_dash.triggered.connect(self._open_dashboard)
            menu.addAction(act_dash)

            act_hide = QAction("Hide", self)
            act_hide.triggered.connect(self.hide)
            menu.addAction(act_hide)

            menu.addSeparator()
            act_quit = QAction("Quit pets", self)
            act_quit.triggered.connect(app.quit)
            menu.addAction(act_quit)

            menu.exec(pos)

        def _run_tick(self):
            try:
                subprocess.Popen(
                    [sys.executable, "-m", "agents.run", "--once"],
                    cwd=str(_REPO_ROOT),
                    creationflags=subprocess.CREATE_NO_WINDOW
                    if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
                )
            except Exception:
                pass

        def _open_dashboard(self):
            d = _REPO_ROOT / "agents" / "dashboard.html"
            if d.exists():
                try:
                    os.startfile(str(d))
                except Exception:
                    pass

    strip = CompanyStrip()
    strip.show()

    # System-tray icon so the user can re-show the strip after Hide.
    if QSystemTrayIcon.isSystemTrayAvailable():
        from PyQt6.QtGui import QIcon
        tray = QSystemTrayIcon(QIcon(), parent=app)
        tray.setToolTip("ArchHub — Company Pets")
        tray_menu = QMenu()
        a_show = QAction("Show pets", tray_menu)
        a_show.triggered.connect(strip.show)
        tray_menu.addAction(a_show)
        a_quit = QAction("Quit", tray_menu)
        a_quit.triggered.connect(app.quit)
        tray_menu.addAction(a_quit)
        tray.setContextMenu(tray_menu)
        tray.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
