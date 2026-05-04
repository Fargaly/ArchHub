"""ArchHub — entry point.

Boots the main chat window. ArchHub is a standalone desktop app:
its own chat UI, its own LLM router, its own tool execution engine.
Claude Desktop is no longer required.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from chat_window import ChatWindow
from llm_router import LLMRouter
from manager import ConnectorManager
from tool_engine import ToolEngine
from tray import ArchHubTray

APP_ROOT = Path(__file__).resolve().parent
ASSETS = APP_ROOT / "assets"
THEME = APP_ROOT / "theme.qss"


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("ArchHub")
    app.setQuitOnLastWindowClosed(False)
    if THEME.exists():
        app.setStyleSheet(THEME.read_text(encoding="utf-8"))

    manager = ConnectorManager()
    manager.refresh()

    tools = ToolEngine(manager)
    router = LLMRouter(tools)

    window = ChatWindow(router=router, manager=manager, tools=tools)

    icon = QIcon(str(ASSETS / "archhub.png")) if (ASSETS / "archhub.png").exists() else QIcon()
    tray = ArchHubTray(icon, window, manager)
    tray.show()

    if "--silent" not in sys.argv:
        window.show_centered()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
