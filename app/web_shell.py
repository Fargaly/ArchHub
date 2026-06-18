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
        from PyQt6.QtWebEngineCore import (
            QWebEngineSettings, QWebEngineProfile, QWebEnginePage,
        )

        # AgDR-0026 Phase 2 — persistent QWebEngineProfile so the JSX
        # cache (localStorage 'jsx_cache_v1_*') survives across launches.
        # Default profile is off-the-record → localStorage cleared on
        # every restart → Babel re-transpiles the 9 675-line studio-lm.jsx
        # every cold start (~5-6 s wasted).  Naming the profile + setting
        # a persistent storage path under %LOCALAPPDATA% gives us
        # disk-backed storage.
        import os
        storage_root = os.path.join(
            os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
            "ArchHub", "webengine")
        os.makedirs(storage_root, exist_ok=True)
        self._wprofile = QWebEngineProfile("archhub", self)
        self._wprofile.setPersistentStoragePath(storage_root)
        self._wprofile.setCachePath(storage_root)
        self._wprofile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies)

        self.view = QWebEngineView()
        # Bind the persistent profile to this view by replacing the
        # default off-the-record page with a profile-backed one.
        _page = QWebEnginePage(self._wprofile, self.view)
        self.view.setPage(_page)
        # Suppress QtWebEngine's native browser context menu (Back / Forward /
        # Reload / Save page / View source). ArchHub is a desktop app — the
        # React canvas owns right-click via DOM 'contextmenu' events
        # (CanvasMenu, WireMenu, port-disconnect), and the chromium menu is
        # wrong/confusing for native-app surface. NoContextMenu makes Qt skip
        # building/showing its menu while leaving the DOM contextmenu event
        # path intact, so the custom React menus continue to work.
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
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

        # ── QWebChannel bridge — expose Python ArchHubBridge as
        # window.archhub in the embedded React tree. The JS side reads
        # real hosts/sessions/models/memory + fires real actions
        # (send_chat, open_settings, ...).
        from PyQt6.QtWebChannel import QWebChannel
        from bridge import ArchHubBridge
        self.bridge = ArchHubBridge(
            router=router, manager=manager, tools=tools,
            chat_widget=chat_widget, parent=self,
        )
        self.channel = QWebChannel(self.view.page())
        self.channel.registerObject("archhub", self.bridge)
        self.view.page().setWebChannel(self.channel)

        html_path = Path(__file__).resolve().parent / "web_ui" / "index.html"
        if not html_path.exists():
            raise RuntimeError(f"web_ui/index.html missing at {html_path}")
        self._html_path = html_path

        # ── GPU-RESILIENCE: the surface is NEVER left blank ───────────────────
        # Root cause this closes: the line below USED to be a bare setUrl with no
        # recovery, and there was NO renderProcessTerminated / loadFinished(False)
        # handler anywhere. So when the GPU renderer crashed (the founder's
        # machine wedges on GPU under real load) or the page failed to load, the
        # QWebEngineView went WHITE and stayed white — a dead app. Now:
        #   • renderProcessTerminated(Abnormal/Crashed/Killed) -> reload ONCE; a
        #     SECOND crash within ~8s -> persist the per-machine software-render
        #     marker and relaunch the surface with --disable-gpu (a slow canvas
        #     beats a blank one), instead of crash-looping on the bad GPU.
        #   • loadFinished(False) -> reload ONCE (transient load failure).
        # Counters are reset on a healthy load so normal Ctrl-R reloads and
        # later unrelated failures each get a fresh single retry.
        self._render_crash_count = 0
        self._first_crash_ts = 0.0
        self._load_fail_reloaded = False
        self._gpu_recovery_done = False
        try:
            _page = self.view.page()
            _page.renderProcessTerminated.connect(self._on_render_process_terminated)
            _page.loadFinished.connect(self._on_load_finished)
        except Exception:
            # Wiring the resilience handlers must never break construction; a
            # build where the signals are unavailable still shows the surface.
            pass

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

        # ── In-app debug bridge (founder-approved, 2026-06-01) — a
        # COMPLEMENTARY zero-DevTools proof path, NOT a CDP replacement.
        # CDP/remote-debugging works on this QtWebEngine build (see
        # tests/test_ui_cdp_smoke.py); the earlier "the remote-debugging
        # websocket handshake stalls on this build" note was wrong — the real
        # causes were a missing --remote-allow-origins Chromium flag (now
        # added in app/main.py when remote debugging is opt-in) and a verifier
        # that ran the ws client on the Qt GUI thread. This bridge is still
        # valuable because it needs NO remote-debugging port: it starts a tiny
        # loopback HTTP server with a narrow read-only surface (/health,
        # /screenshot, /dom_query) so an external verifier can observe the live
        # window with curl alone. It runs ONLY when ARCHHUB_DEBUG_BRIDGE=1 —
        # a normal launch opens no port and is completely unaffected. Never
        # raises; a debug aid must not be able to break the app launch.
        self._debug_bridge = None
        try:
            import debug_bridge
            self._debug_bridge = debug_bridge.maybe_start(
                view=self.view, page=self.view.page(), window=self,
            )
        except Exception:
            self._debug_bridge = None

    # ────────────────────────────────────────────────────────────
    # GPU-RESILIENCE: never-blank recovery handlers
    # ────────────────────────────────────────────────────────────
    def _on_load_finished(self, ok: bool) -> None:
        """``QWebEnginePage.loadFinished(bool)``. On a HEALTHY load, reset the
        recovery counters so future failures each get a fresh single retry. On a
        FAILED load (``ok == False``), reload exactly ONCE — a transient
        local-file/load hiccup shouldn't leave the surface blank, but we must not
        spin in a reload loop if the page genuinely can't load."""
        try:
            if ok:
                self._render_crash_count = 0
                self._first_crash_ts = 0.0
                self._load_fail_reloaded = False
                return
            if self._load_fail_reloaded:
                return  # already gave it one retry; don't loop.
            self._load_fail_reloaded = True
            try:
                import logging as _logging
                _logging.getLogger("archhub.boot").warning(
                    "[gpu-resilience] loadFinished(False) -> reloading surface once")
            except Exception:
                pass
            self.view.reload()
        except Exception:
            pass

    def _on_render_process_terminated(self, status, exit_code: int = 0) -> None:
        """``QWebEnginePage.renderProcessTerminated(status, exitCode)``.

        A NORMAL termination (clean shutdown) is ignored. An ABNORMAL / CRASHED /
        KILLED termination is the blank-canvas symptom: the renderer (and the GPU
        compositor it drives) died. Recovery:
          1st crash  -> reload the page ONCE (record the time).
          2nd crash within ~8s -> the GPU is genuinely bad on this machine, not a
            fluke: persist the per-machine software-render marker and relaunch the
            app with --disable-gpu so the user gets a working (software) surface
            instead of a crash loop. Beyond that, do nothing (avoid thrash).
        Never raises — a recovery handler that throws would defeat its purpose."""
        try:
            import time as _time
            from PyQt6.QtWebEngineCore import QWebEnginePage

            normal = getattr(QWebEnginePage.RenderProcessTerminationStatus,
                             "NormalTerminationStatus", None)
            if normal is not None and status == normal:
                return  # clean exit (e.g. our own teardown) — not a crash.

            now = _time.monotonic()
            self._render_crash_count += 1
            try:
                import logging as _logging
                _logging.getLogger("archhub.boot").warning(
                    "[gpu-resilience] renderProcessTerminated status=%r exit=%r "
                    "(crash #%d)", status, exit_code, self._render_crash_count)
            except Exception:
                pass

            if self._render_crash_count == 1:
                self._first_crash_ts = now
                self.view.reload()
                return

            # Second (or later) crash. If it came fast on the heels of the first,
            # the GPU path is the culprit — pin software + relaunch on software.
            within_window = (now - self._first_crash_ts) <= 8.0
            if within_window and not self._gpu_recovery_done:
                self._gpu_recovery_done = True
                self._engage_software_render_recovery()
            else:
                # Slow repeat or already recovered: one more reload, no thrash.
                self.view.reload()
        except Exception:
            pass

    def _engage_software_render_recovery(self) -> None:
        """Persist the per-machine software-render marker, then relaunch the app
        with ``--disable-gpu`` appended so the user lands on a working software
        surface immediately (Chromium reads its GPU flags only once per process,
        so an in-process flag flip cannot fix a wedged GPU — a relaunch is the
        honest mechanism). Marker-first so that even if the relaunch is blocked,
        the NEXT manual launch is already software. Best-effort + never raises."""
        # 1) Persist the marker (the real, durable mechanism).
        try:
            import main as _main
            _main.persist_software_render_marker(
                reason="web_shell: render process crashed twice -> software render")
        except Exception:
            # Fall back to writing the marker directly if main isn't importable.
            try:
                import os as _os
                from pathlib import Path as _Path
                base = _os.environ.get("LOCALAPPDATA") or _os.path.expanduser("~")
                p = _Path(base) / "ArchHub" / "use_software_render"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("software-render pinned (web_shell crash fallback)\n",
                             encoding="utf-8")
            except Exception:
                pass

        try:
            import logging as _logging
            _logging.getLogger("archhub.boot").error(
                "[gpu-resilience] renderer crashed twice within 8s -> pinned "
                "software render + relaunching with --disable-gpu")
        except Exception:
            pass

        # 2) Relaunch this app with --disable-gpu so the user gets a working
        #    surface now, not after a manual restart. Append the flag to the
        #    child's QTWEBENGINE_CHROMIUM_FLAGS (idempotent), then quit ourselves.
        try:
            import os as _os
            import sys as _sys
            import subprocess as _subprocess
            env = dict(_os.environ)
            existing = env.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
            if "--disable-gpu" not in existing:
                env["QTWEBENGINE_CHROMIUM_FLAGS"] = (
                    f"{existing} --disable-gpu".strip() if existing else "--disable-gpu")
            # Belt-and-braces: also force the marker path for the child so its
            # boot applies software render even before it reads the file.
            env["ARCHHUB_FORCE_SOFTWARE_RENDER"] = "1"
            creationflags = 0
            if _sys.platform == "win32":
                creationflags = (getattr(_subprocess, "DETACHED_PROCESS", 0)
                                 | getattr(_subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
            argv = list(_sys.argv)
            # Strip a stale single-instance/no-sync wrapper arg duplication is
            # unnecessary here; reuse the same argv the user launched with.
            _subprocess.Popen([_sys.executable, *argv], env=env,
                              creationflags=creationflags, close_fds=True)
        except Exception:
            pass

        # 3) Quit this (crashing) instance so the fresh software instance owns
        #    the single-instance lock. Best-effort; if quit fails the relaunched
        #    child still summons.
        try:
            from PyQt6.QtWidgets import QApplication
            _app = QApplication.instance()
            if _app is not None:
                _app.quit()
        except Exception:
            pass

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
            from PyQt6.QtWebEngineWidgets import QWebEngineView
            if getattr(self, "_devtools", None) is not None \
                    and self._devtools.isVisible():
                # Hiding — fully dispose.  Bug fix 2026-05-22: the
                # inspector was only hide()/show()n, never deleted, so
                # each F12 session left a Chromium render process alive
                # until app exit.  Detach + deleteLater frees it.
                try: page.setDevToolsPage(None)
                except Exception: pass  # audit: deliberate-fail-soft — best-effort devtools page detach during dispose
                self._devtools.deleteLater()
                self._devtools = None
                return
            # Showing — create fresh.
            self._devtools = QWebEngineView()
            self._devtools.setWindowTitle("ArchHub · DevTools")
            self._devtools.resize(1000, 700)
            page.setDevToolsPage(self._devtools.page())
            self._devtools.show()
            self._devtools.raise_()
        except Exception:
            pass
