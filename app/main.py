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
from skills import ensure_starter_skills, ensure_production_skills
import cloud_sync
import threading

APP_ROOT = Path(__file__).resolve().parent
ASSETS = APP_ROOT / "assets"
THEME = APP_ROOT / "theme.qss"


def main() -> int:
    # Sentry init must happen BEFORE QApplication so import-time crashes
    # in Qt code get captured. No-op if user opted out / no DSN.
    try:
        import sentry_init
        version_path = APP_ROOT.parent / "VERSION"
        version = version_path.read_text(encoding="utf-8").strip() if version_path.exists() else None
        sentry_init.init(release=f"archhub@{version}" if version else None)
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setApplicationName("ArchHub")
    app.setQuitOnLastWindowClosed(False)
    if THEME.exists():
        app.setStyleSheet(THEME.read_text(encoding="utf-8"))

    # Hook PyQt's silent-exception-swallowing behaviour.
    try:
        import sentry_init as _si
        _si.install_qt_excepthook()
    except Exception:
        pass

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
        ensure_production_skills()
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

    # HUD overlay chrome — frameless, translucent, always-on-top.
    # Toggled by setting 'hud_overlay_mode' (default ON for new
    # installs). Old fullscreen behaviour stays available by
    # un-ticking the setting in Settings → Appearance.
    overlay_controller = None
    try:
        from secrets_store import load_setting
        hud_on = load_setting("hud_overlay_mode")
        if hud_on is None:
            hud_on = True            # default ON
        if hud_on and "--silent" not in sys.argv:
            from overlay_chrome import apply_overlay_chrome, install_global_hotkey
            overlay_controller = apply_overlay_chrome(window)
            # Hotkey configurable via Settings → Appearance.
            # Default Ctrl+Space; common conflict-free fallback F8.
            combo = (load_setting("hud_hotkey") or "ctrl+space").lower()
            install_global_hotkey(overlay_controller, combo=combo)
            # Keep a ref on the window so GC doesn't drop it.
            window._overlay_controller = overlay_controller
    except Exception:
        overlay_controller = None

    if "--silent" not in sys.argv:
        if overlay_controller is not None:
            overlay_controller.expand()
        else:
            window.show_centered()
        # First-run telemetry consent — single question, before the
        # heavier 3-step onboarding. Returns immediately if already
        # answered.
        try:
            from telemetry_consent_dialog import maybe_prompt as _maybe_telemetry
            _maybe_telemetry(window)
        except Exception:
            pass

        # Auto-launch pet strip alongside the chat panel — pets are a
        # subprocess so the chat process can crash without taking the
        # status indicator with it.
        try:
            import subprocess as _sp
            from pathlib import Path as _P
            _pets = _P(__file__).resolve().parent / "company_pets.py"
            if _pets.exists():
                _sp.Popen(
                    [sys.executable.replace("python.exe", "pythonw.exe"), str(_pets)],
                    cwd=str(APP_ROOT.parent),
                    creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0),
                )
        except Exception:
            pass
        # First-run onboarding wizard. Shows once per device; the user can
        # re-run from the menu via Show onboarding again. Done after the
        # main window is on screen so the wizard floats above it.
        try:
            from onboarding import needs_onboarding, OnboardingWizard
            if needs_onboarding():
                OnboardingWizard(router=router, manager=manager,
                                 parent=window).exec()
        except Exception:
            pass
        # Re-init Sentry if the user just opted in — first init was
        # before the dialog so it'll have been a no-op then.
        try:
            import sentry_init as _si
            _si.init()
            _si.install_qt_excepthook()
        except Exception:
            pass
        # Fire one app_started event for cohort tracking.
        try:
            import telemetry as _t
            _t.track_event("app_started", silent=False)
        except Exception:
            pass
    else:
        try:
            import telemetry as _t
            _t.track_event("app_started", silent=True)
        except Exception:
            pass

    rc = app.exec()
    scheduler.stop()
    # Flush in-flight telemetry events on clean exit.
    try:
        import telemetry as _t
        _t.shutdown()
    except Exception:
        pass
    return rc


if __name__ == "__main__":
    sys.exit(main())
