"""WebShell — embeds the actual prototype HTML/JSX inside Qt.

Honest reset (2026-05-13): the previous WorkspaceShell shipped a
480-line Qt-native skeleton against a 2916-line JSX prototype, which
the founder correctly called out as "not even the same design". Qt-
translating 87 components pixel-perfect = weeks. Embedding the actual
prototype via QtWebEngine = pixel-perfect now.

The HTML at `app/web_ui/index.html` mounts <StudioLM /> at full
viewport — same component the design bundle ships. Every panel,
every node body renderer, every Settings tab, the canvas, the
minimap, the model picker, the conversation rail — all drawn by the
designer's own JSX.

The desktop side wraps that in a QWebEngineView so:
  • tray + summon contract is preserved (show_centered / windowTitle)
  • app launches under pythonw with no console
  • we can incrementally migrate components from JSX to Qt-native
    later (state-bridged via QWebChannel), without breaking the
    visible design today

When QtWebEngine isn't available (offscreen CI, headless test runs),
construction raises — main.py falls through to WorkspaceShell then
StudioShell then bare ChatWindow. Same reversibility chain.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QIcon, QKeySequence, QShortcut
from PyQt6.QtWidgets import QMainWindow, QVBoxLayout, QWidget


def _can_use_webengine() -> bool:
    """QtWebEngine ships separately. Import it here so missing dep
    fails construction loudly, falling through to WorkspaceShell."""
    try:
        from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
        return True
    except Exception:
        return False


class WebShell(QMainWindow):
    """Loads app/web_ui/index.html as the entire surface.

    Constructor matches StudioShell + WorkspaceShell so main.py can
    swap without branching: (chat_widget, router, manager, tools).
    The chat_widget is kept on the instance for state bridging in a
    later turn (QWebChannel hookup); for now it's unused.
    """

    def __init__(self, *, chat_widget: QWidget,
                  router=None, manager=None, tools=None,
                  parent=None):
        super().__init__(parent)
        if not _can_use_webengine():
            raise RuntimeError(
                "PyQt6-WebEngine isn't installed. WebShell requires it."
            )
        self.setWindowTitle("ArchHub")
        self.setObjectName("webShell")
        self.resize(1440, 900)

        # ArchHub icon on title bar / taskbar.
        try:
            ico = Path(__file__).resolve().parent / "assets" / "archhub.ico"
            if ico.exists():
                self.setWindowIcon(QIcon(str(ico)))
        except Exception:
            pass

        self.router = router
        self.manager = manager
        self.tools = tools
        self.chat_widget = chat_widget

        # ── QtWebEngine view loads the bundled prototype ──────
        from PyQt6.QtWebEngineWidgets import QWebEngineView
        from PyQt6.QtWebEngineCore import QWebEngineSettings
        self.view = QWebEngineView()
        # Allow JS clipboard, local-content URL access, and remote font CDN.
        settings = self.view.settings()
        for attr_name in (
            "JavascriptEnabled",
            "LocalContentCanAccessFileUrls",
            "LocalContentCanAccessRemoteUrls",
            "AllowRunningInsecureContent",
        ):
            try:
                attr = getattr(QWebEngineSettings.WebAttribute, attr_name)
                settings.setAttribute(attr, True)
            except Exception:
                pass

        html_path = Path(__file__).resolve().parent / "web_ui" / "index.html"
        if not html_path.exists():
            raise RuntimeError(f"web_ui/index.html missing at {html_path}")
        self.view.setUrl(QUrl.fromLocalFile(str(html_path)))

        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self.view)
        self.setCentralWidget(wrap)

        # ── Shortcuts: a couple of basics so the user has parity
        # with the prototype's keyboard hints while we're on QtWebEngine.
        QShortcut(QKeySequence("Ctrl+R"), self,
                   activated=lambda: self.view.reload())
        QShortcut(QKeySequence("F5"), self,
                   activated=lambda: self.view.reload())
        QShortcut(QKeySequence("F12"), self,
                   activated=self._toggle_devtools)

    # ────────────────────────────────────────────────────────────
    # Tray + summon contract (matches StudioShell + WorkspaceShell)
    # ────────────────────────────────────────────────────────────
    def show_centered(self) -> None:
        """Restore + centre on the primary screen. Same contract used
        by ArchHubTray and the single-instance summoner."""
        from PyQt6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        if screen is not None:
            geom = screen.availableGeometry()
            self.move(
                geom.x() + (geom.width()  - self.width())  // 2,
                geom.y() + (geom.height() - self.height()) // 2,
            )
        self.showNormal()
        self.raise_()
        self.activateWindow()

    # ────────────────────────────────────────────────────────────
    # Dev tools — F12 toggles a Chromium inspector window.
    # ────────────────────────────────────────────────────────────
    def _toggle_devtools(self) -> None:
        try:
            page = self.view.page()
            # Two windows: main view + inspector. Inspector is created
            # on first call and re-shown on subsequent calls.
            from PyQt6.QtWebEngineWidgets import QWebEngineView
            if not hasattr(self, "_devtools"):
                self._devtools = QWebEngineView()
                self._devtools.setWindowTitle("ArchHub · DevTools")
                self._devtools.resize(1000, 700)
                page.setDevToolsPage(self._devtools.page())
            if self._devtools.isVisible():
                self._devtools.hide()
            else:
                self._devtools.show()
                self._devtools.raise_()
        except Exception:
            pass
