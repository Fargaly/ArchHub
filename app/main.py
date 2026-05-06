"""ArchHub — entry point.

Boots the chat window, system tray, LLM router, tool engine, and workflow
trigger scheduler. Tool-typed workflow nodes are registered once at startup,
after the tool engine is available.
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
from workflows.nodes import register_tool_nodes
from workflows import WorkflowExecutor
from workflows.triggers import TriggerScheduler
from skills import ensure_starter_skills
import cloud_sync
import threading

APP_ROOT = Path(__file__).resolve().parent
ASSETS = APP_ROOT / "assets"
THEME = APP_ROOT / "theme.qss"


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("ArchHub")
    app.setQuitOnLastWindowClosed(False)
    if THEME.exists():
        app.setStyleSheet(THEME.read_text(encoding="utf-8"))

    # Core services
    manager = ConnectorManager()
    manager.refresh()
    tools = ToolEngine(manager)
    router = LLMRouter(tools)

    # Register tool.* node types now that the tool engine is alive
    register_tool_nodes()

    # Cloud sync — silent bootstrap + pull on launch. Runs on a worker
    # thread so a slow network never delays the chat window appearing.
    def _bootstrap_cloud() -> None:
        try:
            if cloud_sync.is_signed_in():
                cloud_sync.bootstrap()
                cloud_sync.pull()
        except Exception:
            pass
    threading.Thread(target=_bootstrap_cloud, daemon=True).start()

    # Materialise the starter Skills library if it's empty (idempotent).
    try:
        ensure_starter_skills()
    except Exception:
        # Non-fatal: chat works without seeds, just no auto-suggestions.
        pass

    # Main window
    window = ChatWindow(router=router, manager=manager, tools=tools)

    # Tray
    icon = QIcon(str(ASSETS / "archhub.png")) if (ASSETS / "archhub.png").exists() else QIcon()
    tray = ArchHubTray(icon, window, manager)
    tray.show()

    # Workflow trigger scheduler — fires saved workflows on cron / file_watch / etc.
    executor = WorkflowExecutor(router, tools, manager)

    def _on_trigger_fire(workflow, trigger):
        # Run on the trigger thread; surface result through the chat window's
        # workflow handler. Phase 1: fire-and-forget; results land in the
        # workflow's run history (future addition).
        try:
            executor.run(workflow, inputs={p.name: p.default for p in workflow.inputs})
        except Exception:
            pass

    scheduler = TriggerScheduler(on_fire=_on_trigger_fire, tick_seconds=30.0)
    scheduler.start()

    if "--silent" not in sys.argv:
        window.show_centered()

    rc = app.exec()
    scheduler.stop()
    return rc


if __name__ == "__main__":
    sys.exit(main())
