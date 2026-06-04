"""ArchHub — entry point.

Boots the chat window, system tray, LLM router, tool engine, and workflow
trigger scheduler. Tool-typed workflow nodes are registered once at startup,
after the tool engine is available.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Make QtWebEngine opt INTO real GPU acceleration. MUST run before any
# QtWebEngine import/initialization (the eager-import block below) and before
# QApplication is constructed, because QtWebEngine reads QTWEBENGINE_CHROMIUM_FLAGS
# only at process startup. Measured: with no flags, QtWebEngine's GPU process
# fails to launch and the canvas composites on the CPU (SwiftShader/software) —
# the cause of pan/scroll/paint lag. --ignore-gpu-blocklist is the key flag:
# QtWebEngine often blocklists the GPU and silently falls back to software, so
# this forces it to use the real GPU. setdefault() lets a deliberate override win.
#
# These flags are the CORRECT, proven production set — keep them (verified
# 2026-06-01: hardware ANGLE/D3D11 + 60fps canvas, the lag fix). An isolation
# study (throwaway venv, app's exact PyQt6 6.11.0 / Qt 6.11.0 build, never the
# app interpreter) confirmed they do NOT impair the app's real UI<->Python
# bridge: QWebChannel — the transport WebShell uses (web_shell.py setWebChannel)
# — round-tripped 40/40 JS->slot->return->callback with these flags ON, and
# page.runJavaScript callbacks themselves fired 40/40 under all 8 flag combos
# tested (zero timeouts). So there is NO flag-induced callback wedge to fix here.
# The only GPU-related accommodation is a VERIFICATION-ONLY, opt-in toggle
# (ARCHHUB_VERIFY_NO_GPU, applied below) that NEVER affects a production launch.
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--ignore-gpu-blocklist --enable-gpu-rasterization --enable-zero-copy")


def _maybe_disable_gpu_for_verification() -> None:
    """Verification-only, opt-in GPU disable — production is NEVER affected.

    Why this exists (tooling-only finding, isolation-tested 2026-06-01)
    -------------------------------------------------------------------
    ArchHub's shipped Chromium flags above (--ignore-gpu-blocklist
    --enable-gpu-rasterization --enable-zero-copy) are the proven lag fix and
    are CORRECT for production: they give hardware ANGLE/D3D11 acceleration +
    a 60fps canvas. They are deliberately left untouched.

    The isolation study also settled the long-suspected "do the GPU raster
    flags wedge page.runJavaScript callbacks?" question: they do NOT. With the
    full production flag set ON, both the app's real QWebChannel bridge
    (40/40 round-trips) AND raw page.runJavaScript callbacks (40/40, across all
    8 flag combinations, including all-three) ran with zero timeouts on real
    hardware. There is therefore no callback wedge to fix, and the production
    flags are a strict win — adopted as-is.

    This toggle is consequently a DEFENSE-IN-DEPTH affordance for
    verification/debug-bridge runs, not a fix for an observed bug: a verifier
    that drives dom_query through ``debug_bridge.py`` (worker thread ->
    *queued* fire-and-forget ``QMetaObject.invokeMethod`` onto the GUI thread ->
    ``page.runJavaScript(js, callback)`` whose later callback signals the
    worker through a ``threading.Event`` — NOT a BlockingQueuedConnection and
    NOT a nested QEventLoop; the GUI thread never blocks, see the module
    docstring + ``_GuiProxy.dom_query`` in debug_bridge.py) can set
    ``ARCHHUB_VERIFY_NO_GPU=1`` to force the software path and remove the
    GPU/compositor as a variable entirely, without ever changing what
    production ships. (The other zero-GPU-dependency proof paths remain
    ``/screenshot`` and CDP — see debug_bridge.py.)

    Mechanics: APPENDS ``--disable-gpu`` to QTWEBENGINE_CHROMIUM_FLAGS only when
    ``ARCHHUB_VERIFY_NO_GPU`` is set to a truthy value (1/true). A normal
    production launch never sets that env var, so the flag is never added and
    the production string is byte-for-byte unchanged. Idempotent + additive: it
    keeps every existing flag and never duplicates ``--disable-gpu``. MUST run
    before QtWebEngine initialises (same constraint as the flags above) —
    Chromium reads QTWEBENGINE_CHROMIUM_FLAGS once at process startup.
    """
    if (os.environ.get("ARCHHUB_VERIFY_NO_GPU") or "").strip().lower() not in ("1", "true"):
        return  # production / normal launch -> add nothing, GPU flags intact.
    existing = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    if "--disable-gpu" not in existing:
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
            f"{existing} --disable-gpu".strip() if existing else "--disable-gpu"
        )


_maybe_disable_gpu_for_verification()


def _dev_verify_requested() -> bool:
    """True when this launch opted into the reopen=latest dev-verify mode,
    via env ``ARCHHUB_DEV_VERIFY=1`` or the ``--dev-verify`` argv flag.

    Dev-verify is the founder+Claude "prove the running app is HEAD" launch:
    it (a) FORCES a dev-source sync ignoring the marker, and (b) turns on
    QtWebEngine remote debugging so CDP verification is reliable. Off by
    default — a production launch sets neither and behaves exactly as before."""
    if (os.environ.get("ARCHHUB_DEV_VERIFY") or "").strip().lower() in ("1", "true"):
        return True
    try:
        return "--dev-verify" in sys.argv[1:]
    except Exception:
        return False


def _maybe_enable_dev_verify_cdp() -> None:
    """When dev-verify is requested, ensure remote debugging is ON so CDP
    works. Sets QTWEBENGINE_REMOTE_DEBUGGING (default 9223) if unset, BEFORE
    _enable_cdp_remote_origins() reads it below. setdefault semantics: an
    explicit port the launcher already chose wins. No-op when dev-verify is
    off, so production never enables remote debugging."""
    if not _dev_verify_requested():
        return
    try:
        if not (os.environ.get("QTWEBENGINE_REMOTE_DEBUGGING") or "").strip():
            os.environ["QTWEBENGINE_REMOTE_DEBUGGING"] = "9223"
    except Exception:
        pass


_maybe_enable_dev_verify_cdp()


def _enable_cdp_remote_origins() -> None:
    """When remote debugging is opted IN, allow the DevTools websocket upgrade.

    Root cause of the long-standing "CDP/DevTools websocket stalls on this
    QtWebEngine build" symptom (isolation-tested on Qt 6.11.0 AND 6.11.1 —
    NOT a Qt bug): Chromium 111+ added an Origin check to the remote-debugging
    endpoint. When a websocket client sends an ``Origin`` header (most do), the
    server rejects the upgrade with HTTP 403 unless that origin is on an
    allow-list — so ``websocket.create_connection`` hangs/aborts the handshake.
    ``--remote-allow-origins`` is the allow-list. The DevTools ws + runJavaScript
    work fine once it is set (the other half of the old symptom was the verifier
    calling urlopen/ws ON the Qt GUI thread, which is fixed in the verifier, not
    here).

    Scoped tightly: this flag is APPENDED to QTWEBENGINE_CHROMIUM_FLAGS only when
    ``QTWEBENGINE_REMOTE_DEBUGGING`` is set/non-empty (remote debugging is opt-in).
    A normal production launch never sets that env var, so the flag is never added
    and production behaviour is unchanged. The GPU flags above are preserved — we
    only append. We allow both the localhost and 127.0.0.1 debug origins on the
    actual debug port (loopback only); if a client still 403s with a differently
    shaped Origin, ``ARCHHUB_CDP_ALLOW_ANY_ORIGIN=1`` falls back to ``=*`` (still
    safe: remote-debugging is opt-in and binds loopback only).

    MUST run before QtWebEngine initialises (same constraint as the GPU flags) —
    Chromium reads QTWEBENGINE_CHROMIUM_FLAGS once at process startup.
    """
    port = (os.environ.get("QTWEBENGINE_REMOTE_DEBUGGING") or "").strip()
    if not port:
        return  # remote debugging OFF -> production launch, add nothing.
    if os.environ.get("ARCHHUB_CDP_ALLOW_ANY_ORIGIN") == "1":
        allow = "--remote-allow-origins=*"
    else:
        # The env value is usually a bare port ("9223"); it can also be a
        # host:port. Derive the bare port for the loopback origins, else *.
        bare = port.rsplit(":", 1)[-1]
        if bare.isdigit():
            allow = (f"--remote-allow-origins=http://localhost:{bare},"
                     f"http://127.0.0.1:{bare}")
        else:
            allow = "--remote-allow-origins=*"
    existing = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    # Idempotent + additive: never duplicate the flag, always keep GPU flags.
    if "--remote-allow-origins" not in existing:
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
            f"{existing} {allow}".strip() if existing else allow
        )


_enable_cdp_remote_origins()

APP_ROOT = Path(__file__).resolve().parent
ASSETS = APP_ROOT / "assets"
THEME = APP_ROOT / "theme.qss"


def _maybe_sync_dev_source_at_startup() -> None:
    """Let an installed AppData launch refresh from a configured checkout.

    Dev-verify launches (ARCHHUB_DEV_VERIFY=1 / --dev-verify) FORCE a sync
    that ignores the marker, so the running app is guaranteed to reflect HEAD
    before CDP verification — even if the marker already matches. A normal
    launch keeps the marker-gated, relaunch-once behaviour unchanged."""
    try:
        if _dev_verify_requested():
            from dev_source_sync import force_sync_now
            force_sync_now(APP_ROOT.parent, sys.argv)
            # Fall through to the normal path too: it is a marker no-op after
            # the force-sync wrote the marker, and it preserves the existing
            # relaunch guard semantics for any edge case.
        from dev_source_sync import maybe_sync_and_relaunch
        maybe_sync_and_relaunch(APP_ROOT.parent, sys.argv)
    except Exception:
        # Startup sync is a convenience path. If it fails, the normal launch
        # should continue so release updates and diagnostics remain available.
        pass


_maybe_sync_dev_source_at_startup()


def _precompile_jsx_at_startup() -> None:
    """Pre-launch hook (founder, 2026-06-01 — boot-lag root fix).

    Refresh the on-disk precompiled JSX artifacts
    (app/web_ui/studio-lm.compiled.js + app-boot.compiled.js) so the embedded
    artifact is ALWAYS current with the live .jsx before QtWebEngine loads the
    page. The loader (jsx-boot.js) then loads them directly — no in-browser
    Babel, no 3 MB babel.min.js parse on a normal launch.

    Idempotent + fast: tools/build_jsx.build_all() hashes each source and skips
    any artifact whose embedded sha already matches (a sub-second no-op when
    nothing changed). It recompiles ONLY a .jsx that actually changed, so the
    founder never hits an in-browser recompile — yet an edit is picked up on
    the next launch automatically.

    Never fatal: if Node is missing or a transform fails, the artifacts are
    left as-is (or absent) and the loader gracefully falls back to in-browser
    Babel. The app must always launch.
    """
    try:
        tools_dir = APP_ROOT.parent / "tools"
        if str(tools_dir) not in sys.path:
            sys.path.insert(0, str(tools_dir))
        import build_jsx
        summary = build_jsx.build_all(quiet=True)
        if summary.get("any_built"):
            built = [r["file"] for r in summary.get("results", [])
                     if r.get("status") == "built"]
            try:
                import logging as _logging
                _logging.getLogger("archhub.boot").info(
                    "[build_jsx] recompiled JSX artifacts: " + ", ".join(built))
            except Exception:
                pass
    except Exception:
        # Precompile is a perf accelerator, never a launch gate. On any
        # failure the in-browser Babel fallback in jsx-boot.js still renders.
        pass


_precompile_jsx_at_startup()

# AgDR-0047 §B2: central logging init. Must run BEFORE any other app
# import that might call `logging.getLogger(__name__)`, so the root
# RotatingFileHandler is registered before the first log record fires.
# Idempotent — safe to re-call from subprocess / test contexts.
try:
    from logging_config import init_logging
    init_logging()
except Exception:
    # Logging-init failure must never block the app boot.
    pass

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

# Eagerly import QtWebEngine BEFORE QApplication is constructed in
# main(). QtWebEngine on Windows refuses to initialize when the
# QApplication already exists, which made WebShell fall through to
# WorkspaceShell on every cold start. Catching ImportError here means
# the rest of the app stays launchable when WebEngine is missing.
try:
    from PyQt6.QtCore import Qt as _Qt, QCoreApplication as _QCA
    try:
        _QCA.setAttribute(_Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    except Exception:
        pass
    from PyQt6.QtWebEngineWidgets import QWebEngineView as _WEV  # noqa: F401
    _WEBENGINE_OK = True
except Exception:
    _WEBENGINE_OK = False


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


def _safe_self_test() -> None:
    """AgDR-0036 — daemon-thread wrapper for `_startup_self_test`.
    Swallows everything; the self-test is diagnostic-only."""
    try:
        _startup_self_test()
    except Exception:
        pass


def _startup_self_test() -> None:
    """Probe every host broker + runner at startup, log results.

    Writes one block to `boot.log` per launch:

        === ArchHub startup self-test · 2026-05-13T14:02:08 ===
        revit_broker    : 0 session(s)            [ok]
        acad_broker     : 0 session(s)            [ok]
        max_broker      : 1 session(s)            [ok]
        outlook_broker  : 0 session(s)            [ok]
        outlook_runner  : COM reachable           [ok]
        revit installs  : 2024 → C:\\Program Files\\…
        autocad installs: (none)
        max installs    : (none)
        dotnet sdk      : 8.0.300                 [ok]
        tools registered: 37 (revit:4 acad:3 max:5 outlook:18 blender:5 archhub:2)

    Diagnosing 'nothing works' becomes a one-file lookup. The block is
    silent on success — the user only opens boot.log when something
    feels off.
    """
    import datetime as _dt
    from pathlib import Path as _P
    lines: list[str] = []
    lines.append("")
    lines.append(f"=== ArchHub startup self-test · "
                 f"{_dt.datetime.now().isoformat(timespec='seconds')} ===")

    def _probe(label: str, fn) -> None:
        try:
            result = fn()
            lines.append(f"{label:<16}: {result}")
        except Exception as ex:
            lines.append(f"{label:<16}: ERR — {type(ex).__name__}: {ex}")

    # Brokers
    for mod_name in ("revit_broker", "acad_broker", "max_broker",
                      "outlook_broker"):
        def _go(m=mod_name):
            mod = __import__(m)
            sess = list(mod.list_sessions() or [])
            if not sess:
                return "0 session(s)"
            # Session shapes vary per broker — revit/acad/max use
            # `session_id`, outlook keys on `smtp_address`. Try the
            # likely fields, fall back to repr() so the self-test
            # never crashes the launch sequence.
            ids = []
            for s in sess:
                for attr in ("session_id", "smtp_address", "doc_title",
                              "token", "name"):
                    val = getattr(s, attr, None)
                    if val:
                        ids.append(str(val)); break
                else:
                    ids.append(repr(s)[:40])
            return f"{len(sess)} session(s) [{','.join(ids)}]"
        _probe(mod_name, _go)

    # Outlook COM
    def _probe_outlook_com():
        from connectors import outlook_runner
        return "COM reachable" if outlook_runner.is_reachable() else "COM unreachable"
    _probe("outlook_runner", _probe_outlook_com)

    # Installed hosts (detection only, no build).
    try:
        import auto_build as _ab
        revit_yrs = [y for y in (2020, 2021, 2022, 2023, 2024, 2025)
                     if _ab.find_revit_install(y)]
        acad_yrs = [y for y in (2024, 2025, 2026)
                    if _ab.find_autocad_install(y)]
        max_yrs = [y for y in (2025, 2026)
                   if _ab.find_max_install(y)]
        lines.append(f"{'revit installs':<16}: {revit_yrs or '(none)'}")
        lines.append(f"{'autocad installs':<16}: {acad_yrs or '(none)'}")
        lines.append(f"{'max installs':<16}: {max_yrs or '(none)'}")
        sdk = None
        try:
            sdk = _ab.detect_dotnet_sdk()
        except Exception:
            sdk = None
        lines.append(f"{'dotnet sdk':<16}: {sdk or '(not detected)'}")
    except Exception as ex:
        lines.append(f"{'detection':<16}: ERR — {type(ex).__name__}: {ex}")

    # Tool registry summary.
    try:
        from tool_engine import TOOLS as _T
        fams: dict[str, int] = {}
        for t in _T:
            fam = (t.get("family") or "?").lower()
            fams[fam] = fams.get(fam, 0) + 1
        breakdown = " ".join(f"{k}:{v}" for k, v in sorted(fams.items()))
        lines.append(f"{'tools registered':<16}: {len(_T)} ({breakdown})")
    except Exception as ex:
        lines.append(f"{'tools registered':<16}: ERR — {ex}")

    # AgDR-0047 §B1 + §B2: route boot diagnostics through the central
    # logger. Handler is registered in `app/logging_config.py` at
    # `%LOCALAPPDATA%/ArchHub/logs/boot.log` with rotation (5 MB × 5).
    # Readers (`agents/status_report.py` + `scripts/reality_smoke.py`)
    # tolerate both the LOCALAPPDATA path AND the legacy repo-root
    # path via mtime fallback.
    try:
        import logging as _logging
        _boot_log = _logging.getLogger("archhub.boot")
        for _ln in lines:
            _boot_log.info(_ln)
    except Exception:
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
    #
    # reopen=latest (founder, 2026-06-04): the plain summon above strands
    # new code — the running install never re-syncs (it's the
    # --no-dev-source-sync child) and a second launch just foregrounds it.
    # So we pass `should_supersede` = "is there new code to load?"
    # (dev_source_sync.has_new_source). When an instance is running AND that
    # is True, acquire_or_summon QUITs the old instance, waits (bounded) for
    # the lock to free, then this launch becomes the listener and continues
    # into startup — where _maybe_sync_dev_source_at_startup already ran the
    # sync. `on_quit` lets a FUTURE newer launch quit US gracefully (Qt
    # main-thread app.quit() so the clean-shutdown tail + atexit release()
    # run). Both are gated + graceful-degrade to today's summon on any error.
    try:
        from single_instance import acquire_or_summon, release as _si_release
        from PyQt6.QtCore import QObject, pyqtSignal, QTimer

        class _Summoner(QObject):
            requested = pyqtSignal()
            quit_requested = pyqtSignal()
        summoner = _Summoner()
        # Bound on the main thread: when the worker fires a signal,
        # Qt queues the slot back to main thread automatically.
        def _on_summon():
            summoner.requested.emit()
        def _on_quit():
            summoner.quit_requested.emit()
        # Graceful quit on the Qt main thread: release the lock first (so a
        # superseding launch's bounded poll sees it free promptly), then ask
        # the app to quit so app.exec() returns and the clean-shutdown tail
        # runs. atexit-registered release() is a belt-and-braces backstop.
        def _do_graceful_quit():
            try:
                _si_release()
            except Exception:
                pass
            try:
                app.quit()
            except Exception:
                pass
        summoner.quit_requested.connect(_do_graceful_quit)

        def _should_supersede() -> bool:
            # "Is there new code to load?" — gated + graceful (False on any
            # error / git-checkout install / no configured source).
            try:
                from dev_source_sync import has_new_source
                return bool(has_new_source(APP_ROOT.parent))
            except Exception:
                return False

        first_instance = acquire_or_summon(
            _on_summon,
            should_supersede=_should_supersede,
            on_quit=_on_quit,
        )
        if not first_instance:
            return 0
        # The summon slot wires up after `window` is created below — we
        # stash a deferred connection here.
        app._archhub_summoner = summoner   # keep ref alive
        import atexit
        atexit.register(_si_release)
    except Exception:
        pass


    app.setApplicationName("ArchHub")
    app.setQuitOnLastWindowClosed(False)

    # Sweep stub session files from the rail on every launch. Catches
    # files that the previous run wrote with an empty assistant
    # response (provider returned nothing — out of credits / quota /
    # streaming race). Safe to run unconditionally — only deletes
    # files with NO real chat AND no params AND no chain.
    try:
        from session_io import cleanup_empty_sessions
        cleanup_empty_sessions()
    except Exception:
        pass

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
    # v1.4.0-alpha (ADR-003 pivot): the actual designer's prototype is
    # the surface. WebShell embeds web_ui/index.html (which mounts
    # <StudioLM /> from the design bundle) via QtWebEngine. That gets
    # pixel-perfect fidelity to the prototype while we migrate state
    # bridges across QWebChannel. Fallback chain:
    #     WebShell (prototype) → WorkspaceShell (Qt-native skeleton)
    #                          → StudioShell (legacy pages)
    #                          → bare ChatWindow
    # v1.5: committed to WebShell. PyQt6-WebEngine is a hard runtime
    # requirement — no silent fallback to WorkspaceShell / StudioShell /
    # ChatWindow. If WebShell fails to construct, surface the underlying
    # error to the user instead of silently degrading.
    if not _WEBENGINE_OK:
        raise RuntimeError(
            "PyQt6-WebEngine required — install with `pip install PyQt6-WebEngine`. "
            "ArchHub's UI is rendered through the embedded WebShell."
        )
    try:
        from web_shell import WebShell
        shell = WebShell(chat_widget=window, router=router,
                          manager=manager, tools=tools)
        surface = shell
    except Exception as _shell_ex:
        try:
            import traceback as _tb
            with open(str(APP_ROOT.parent / "boot.log"), "a", encoding="utf-8") as _f:
                _f.write("WebShell build failed:\n")
                _tb.print_exc(file=_f)
        except Exception:
            pass
        raise RuntimeError(
            f"PyQt6-WebEngine required — WebShell failed to build: {_shell_ex}"
        ) from _shell_ex

    # Wire the single-instance summon signal: when a second launch
    # asks us to come forward, surface the window.
    try:
        sm = getattr(app, "_archhub_summoner", None)
        if sm is not None:
            sm.requested.connect(lambda: surface.show_centered())
    except Exception:
        pass

    # Startup self-test — probe every broker + host and write a one-line
    # summary to boot.log. v1.0.2 addition: makes "stagnant / nothing
    # alive" diagnosable from the user's own log without us asking them
    # to run anything. Non-fatal — any probe that raises gets logged as
    # "err" and the next host is probed.
    #
    # AgDR-0036 — runs on a DAEMON THREAD, not inline.  It does broker
    # HTTP probes + parallel port scans + Outlook COM + auto_build
    # filesystem walks — multi-second.  Inline (before surface.show)
    # it hung the boot splash for that whole time.  Nothing in the UI
    # depends on its result (it only writes boot.log), so background it.
    try:
        import threading as _th
        _th.Thread(target=lambda: _safe_self_test(), daemon=True,
                   name="archhub-self-test").start()
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

    # HUD overlay chrome — power-user only. Default OFF: chat opens as
    # a normal window so it doesn't obstruct Revit / AutoCAD work.
    #
    # Overlay only applies when the bare ChatWindow is the surface.
    # When the Studio shell wraps it, the shell IS the chrome — overlay
    # would conflict (it grabs `window` as its host). Skip overlay if
    # `surface is not window`.
    #
    # AgDR-0047 §C11 audit (2026-05-26): the prior shadow-audit TODO
    # warned the Settings → Appearance row was "shown to every user but
    # only honoured when StudioShell construction fails." Re-audit
    # confirms NO Settings UI row exists today (verified by grep across
    # settings_dialog.py, settings_page.py, studio-lm.jsx — zero
    # references to `hud_overlay_mode`). The setting is therefore a
    # power-user knob set externally via secrets_store, never via the
    # standard UI. The "disconnected toggle" class of failure is closed.
    # When a power user does enable `hud_overlay_mode` but Studio is the
    # surface, we log a one-time WARNING so the silent suppression is
    # discoverable from the central log (`archhub.log`).
    overlay_controller = None
    try:
        from secrets_store import load_setting
        _hud_setting = bool(load_setting("hud_overlay_mode"))
    except Exception:
        _hud_setting = False
    if _hud_setting and surface is not window:
        try:
            import logging as _logging
            _logging.getLogger("archhub.boot").warning(
                "hud_overlay_mode=True but surface is Studio shell — "
                "overlay suppressed (overlay only applies to bare "
                "ChatWindow surface; see app/main.py)."
            )
        except Exception:
            pass
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
        # Auto-update — fires 6s after launch + every 6h after that,
        # on a daemon thread. UI stays responsive at launch. Modes
        # (Settings → Updates):
        #   off     — never check
        #   notify  — Windows toast only (legacy)
        #   prompt  — download silently, show in-app banner asking the
        #             user to restart. Claude-Desktop pattern. Default.
        #   silent  — install + force-restart with no prompt. Opt-in.
        try:
            from release_updater import schedule_auto_check
            # ChatWindow is always the real backend (even when wrapped
            # by StudioShell). It owns the banner widget + signal.
            on_ready = getattr(window, "_on_update_ready", None)
            schedule_auto_check(delay_seconds=6.0, on_ready=on_ready)
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
            # Route through `surface` (the StudioShell when wrapped),
            # not `window` (the bare ChatWindow which has no _set_page).
            if rc == 2:
                try:
                    target = surface if 'surface' in locals() else window
                    if hasattr(target, "_set_page"):
                        target._set_page("settings")
                    elif hasattr(target, "_open_settings"):
                        target._open_settings()
                except Exception:
                    pass
    except Exception:
        # Onboarding failing must NEVER block the app from starting.
        pass

    rc = app.exec()
    scheduler.stop()
    # Stop + join the connector-health poll thread on clean exit. The daemon
    # was started at launch (instance() above) and polls loopback ports every
    # 5s; main.py never halted it. It's daemon=True so it dies with the
    # process either way, but stopping it explicitly honors the same
    # clean-stop contract the test suite enforces (conftest
    # _stop_leaked_background_threads) — the production side of closing the
    # leaked-poller class, not just the test side.
    try:
        import connector_health as _ch
        _ch.shutdown()
    except Exception:
        pass
    # Flush in-flight telemetry events on clean exit.
    try:
        import telemetry as _t
        _t.shutdown()
    except Exception:
        pass
    return rc


if __name__ == "__main__":
    sys.exit(main())
