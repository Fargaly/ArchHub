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


def _register_aumid_icon(aumid: str, ico_path: Path, display_name: str) -> None:
    """Register the AppUserModelID → icon mapping in the user's
    Software\\Classes registry hive on Windows. Without this Explorer
    and the taskbar can't look up which icon to draw for the AUMID we
    set with SetCurrentProcessExplicitAppUserModelID — they fall back
    to the launching binary's icon (pythonw.exe = Python snake).

    Writes:
      HKCU\\Software\\Classes\\AppUserModelId\\<aumid>
        DisplayName    REG_SZ  "ArchHub"
        IconResource   REG_SZ  "<ico_path>,0"

    Idempotent — overwrites only when the path or value drifted (e.g.
    user moved the install). HKCU = no admin needed. Best-effort: any
    failure is swallowed because a missing icon mapping is cosmetic,
    not a startup-blocker.
    """
    if sys.platform != "win32":
        return
    if not ico_path.exists():
        return
    try:
        import winreg
    except Exception:
        return
    key_path = rf"Software\Classes\AppUserModelId\{aumid}"
    icon_value = f"{str(ico_path)},0"
    try:
        existing_icon = ""
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as k:
                existing_icon, _ = winreg.QueryValueEx(k, "IconResource")
        except FileNotFoundError:
            pass
        except OSError:
            pass
        if existing_icon == icon_value:
            return  # already correct, no need to rewrite
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as k:
            winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ, display_name)
            winreg.SetValueEx(k, "IconResource", 0, winreg.REG_SZ, icon_value)
    except Exception:
        # Don't let a registry hiccup block app startup.
        pass


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

    # Tell Windows that this process is "ArchHub", not "pythonw.exe".
    # Without an AppUserModelID, the Windows taskbar groups our window
    # under pythonw and shows pythonw's generic Python icon. Setting an
    # AUMID before QApplication binds our windowIcon to the taskbar
    # entry as well — this is the only knob that actually affects the
    # taskbar / alt-tab thumbnail / pinned-shortcut icon.
    AUMID = "io.archhub.studio"
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(AUMID)
        except Exception:
            pass
        # Register AUMID → icon mapping in HKCU so Explorer/Taskbar can
        # resolve "io.archhub.studio" to archhub.ico instead of falling
        # back to the launching binary's icon (pythonw.exe → snake).
        # Idempotent — writes only if missing or stale. HKCU only, no
        # admin needed. SetCurrentProcessExplicitAppUserModelID alone
        # is NOT enough — Windows wants this registry entry too.
        try:
            _register_aumid_icon(AUMID, ASSETS / "archhub.ico", "ArchHub")
        except Exception:
            pass

    app = QApplication(sys.argv)
    # Force Fusion style + override the Windows accent palette so Qt
    # never fills "active" / "selected" roles on QComboBox / QLineEdit
    # with the system accent (default Windows accent is bright blue/
    # cyan — wildly off-brand). theme.qss + studio inline QSS handle
    # backgrounds; the palette override ensures Highlight + HighlightedText
    # match brand even on widget states our QSS doesn't reach.
    try:
        from PyQt6.QtGui import QPalette, QColor
        try:
            app.setStyle("Fusion")
        except Exception:
            pass
        try:
            from design_tokens import current as _palette
            from design_tokens import load_theme_pref as _load_pref
            _load_pref()
            p = _palette()
            qp = QPalette()
            qp.setColor(QPalette.ColorRole.Highlight, QColor(p["accent"]))
            qp.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
            qp.setColor(QPalette.ColorRole.Window, QColor(p["bg"]))
            qp.setColor(QPalette.ColorRole.WindowText, QColor(p["ink"]))
            qp.setColor(QPalette.ColorRole.Base, QColor(p["bgRaised"]))
            qp.setColor(QPalette.ColorRole.AlternateBase, QColor(p["bgPanel"]))
            qp.setColor(QPalette.ColorRole.Text, QColor(p["ink"]))
            qp.setColor(QPalette.ColorRole.Button, QColor(p["bgRaised"]))
            qp.setColor(QPalette.ColorRole.ButtonText, QColor(p["ink"]))
            qp.setColor(QPalette.ColorRole.PlaceholderText, QColor(p["inkCap"]))
            qp.setColor(QPalette.ColorRole.ToolTipBase, QColor(p["bgPanel"]))
            qp.setColor(QPalette.ColorRole.ToolTipText, QColor(p["ink"]))
            app.setPalette(qp)
        except Exception:
            pass
    except Exception:
        pass

    # Single-instance lock + summon. If another ArchHub is already
    # running, send 'SHOW' to it and exit 0 — fixes the 'click icon
    # does nothing' bug where the existing window stayed hidden.
    # Wired AFTER QApplication so we can post a Qt event back to the
    # main thread when we receive a SHOW request from a second
    # launcher.
    try:
        from single_instance import acquire_or_summon, release as _si_release
        from PyQt6.QtCore import QObject, pyqtSignal, QTimer

        class _Summoner(QObject):
            requested = pyqtSignal()
        summoner = _Summoner()
        # Bound on the main thread: when the worker fires .requested,
        # Qt queues the slot back to main thread automatically.
        def _on_summon():
            summoner.requested.emit()
        first_instance = acquire_or_summon(_on_summon)
        if not first_instance:
            return 0
        # The slot itself wires up after `window` is created below — we
        # stash a deferred connection here.
        app._archhub_summoner = summoner   # keep ref alive
        import atexit
        atexit.register(_si_release)
    except Exception:
        pass


    app.setApplicationName("ArchHub")
    app.setQuitOnLastWindowClosed(False)

    # Application icon — picked up by the Windows taskbar, alt-tab
    # thumbnails, and any frameless window we spawn. Without this the
    # title bar / taskbar shows the default pythonw.exe icon.
    try:
        ico_path = ASSETS / "archhub.ico"
        if ico_path.exists():
            app.setWindowIcon(QIcon(str(ico_path)))
        else:
            png_path = ASSETS / "archhub.png"
            if png_path.exists():
                app.setWindowIcon(QIcon(str(png_path)))
    except Exception:
        pass

    # Token-driven theme — substitutes the active palette into the
    # legacy theme.qss before applying. Picks up persisted theme_mode
    # (defaults to dark per brand principle 01).
    if THEME.exists():
        try:
            from design_tokens import load_theme_pref
            load_theme_pref()
            from theme_builder import build_global_qss
            app.setStyleSheet(build_global_qss(THEME))
        except Exception:
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

    # Connector health daemon — single source of truth for 'is the
    # listener actually responding'. Polls every 5s on a background
    # thread, surfaces 'live' / 'loaded_dead' / 'host_offline' /
    # 'inactive' / 'unknown'. Self-heals AutoCAD with NETLOAD via
    # COM with 5s/30s/5min backoff. Status bar + connector panel
    # + Reality Check + chat all consult this same instance.
    try:
        from connector_health import instance as _health_instance
        _health_instance()       # spawn the polling thread
    except Exception:
        pass

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

    # Main window — ChatWindow stays as the chat backend (workers,
    # callbacks, history). StudioShell wraps it as the visible chrome
    # (3-pane Studio direction from the Claude Design handoff).
    window = ChatWindow(router=router, manager=manager, tools=tools)

    # Studio shell — wraps `window` as the centre 'chat' page, adds
    # Home/Skills/Workflows/Marketplace/Telemetry/Settings pages,
    # left rail (brand · ⌘K · nav · hosts · threads · user), right
    # inspector (304px), bottom mono status rule (26px).
    surface = window
    try:
        from studio_shell import StudioShell
        shell = StudioShell(chat_widget=window, router=router,
                            manager=manager, tools=tools)
        # Tray + summon address the shell. The bare ChatWindow stays
        # alive as the backend but is never shown.
        surface = shell
    except Exception:
        # If the shell fails to build for any reason, fall back to
        # the legacy bare ChatWindow so the app still launches. Logs
        # the traceback to APP_ROOT/../boot.log so we can debug a
        # silent shell-build failure on a user's machine.
        surface = window
        try:
            import traceback as _tb
            with open(str(APP_ROOT.parent / "boot.log"), "a", encoding="utf-8") as _f:
                _f.write("StudioShell build failed — falling back to bare ChatWindow:\n")
                _tb.print_exc(file=_f)
        except Exception:
            pass

    # Wire the single-instance summon signal: when a second launch
    # asks us to come forward, surface the window.
    try:
        sm = getattr(app, "_archhub_summoner", None)
        if sm is not None:
            sm.requested.connect(lambda: surface.show_centered())
    except Exception:
        pass

    # Tray
    icon = QIcon(str(ASSETS / "archhub.png")) if (ASSETS / "archhub.png").exists() else QIcon()
    tray = ArchHubTray(icon, surface, manager)
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

    # HUD overlay chrome — opt-in via Settings → Appearance. Default
    # is OFF: chat opens as a normal window so it doesn't obstruct
    # Revit / AutoCAD work. The ambient layer is the pet strip
    # (small, bottom-right) — it stays out of the way.
    #
    # Overlay only applies when the bare ChatWindow is the surface.
    # When the Studio shell wraps it, the shell IS the chrome — overlay
    # would conflict (it grabs `window` as its host). Skip overlay if
    # `surface is not window`.
    overlay_controller = None
    if surface is window:
        try:
            from secrets_store import load_setting
            hud_on = bool(load_setting("hud_overlay_mode"))
            if hud_on and "--silent" not in sys.argv:
                from overlay_chrome import apply_overlay_chrome, install_global_hotkey
                overlay_controller = apply_overlay_chrome(window)
                combo = (load_setting("hud_hotkey") or "ctrl+space").lower()
                install_global_hotkey(overlay_controller, combo=combo)
                window._overlay_controller = overlay_controller
        except Exception:
            overlay_controller = None

    if "--silent" not in sys.argv:
        if overlay_controller is not None:
            overlay_controller.expand()
        else:
            # ALWAYS show the chosen surface (StudioShell when wrapped,
            # bare ChatWindow only as fallback). Previously this called
            # `window.show_centered()` unconditionally, which surfaced
            # an empty ChatWindow (its centralWidget had been re-parented
            # into the shell) — making external watchdogs report "alive
            # but hidden" and force-show the shell every time. Single
            # source of truth: `surface`.
            surface.show_centered()
        # Auto-update — fires 6s after launch on a daemon thread, so
        # the UI is responsive first. 24h cooldown by default. Mode
        # toggle in Settings → Updates: off / notify / auto.
        try:
            from release_updater import schedule_auto_check
            schedule_auto_check(delay_seconds=6.0)
        except Exception:
            pass
        # First-run telemetry consent — single question, before the
        # heavier 3-step onboarding. Returns immediately if already
        # answered.
        try:
            from telemetry_consent_dialog import maybe_prompt as _maybe_telemetry
            _maybe_telemetry(surface)
        except Exception:
            pass

        # Pet strip is opt-in — runnable via `pythonw -m app.company_pets`
        # for users who want a glanceable dept indicator. Auto-spawn was
        # decoration, not value. Removed.
        # First-run onboarding wizard. Shows once per device; the user can
        # re-run from the menu via Show onboarding again. Done after the
        # main window is on screen so the wizard floats above it.
        try:
            from onboarding import needs_onboarding, OnboardingWizard
            if needs_onboarding():
                OnboardingWizard(router=router, manager=manager,
                                 parent=surface).exec()
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

    # First-run onboarding for technophobe users — no provider keys
    # set, no Ollama installed. Show the friendly setup dialog BEFORE
    # the user lands on an empty Settings screen they don't understand.
    # The dialog runs the silent Ollama install + model pull, or the
    # user can dismiss to use their own keys via Settings.
    try:
        import first_run as _fr
        if _fr.needs_onboarding():
            from onboarding_dialog import OnboardingDialog
            dlg = OnboardingDialog()
            rc = dlg.exec()
            # rc == 2 → user clicked "I have a Claude/OpenAI account";
            # surface Settings so they can paste a key right away.
            if rc == 2 and 'window' in locals():
                try:
                    if hasattr(window, "_set_page"):
                        window._set_page("settings")
                except Exception:
                    pass
    except Exception:
        # Onboarding failing must NEVER block the app from starting.
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
