"""ArchHub window on the clean engine.

The launcher's WebShell embeds the superseded studio-lm bundle; the clean
graph canvas lived only in a browser tab, which is a localhost page, not
the founder's application. This window is the SPEC section 12 bridge:
the same Qt shell -- icon, title, taskbar identity, persistent profile --
pointed at the clean owner's canvas. It adds a file and changes none, so
the existing launcher keeps working untouched and rollback is deleting
this file.

It waits for the owner honestly: the canvas takes minutes to stand after
a cold start, and a white rectangle with no explanation is how today's
distrust was earned. Until the port answers, the window says what it is
waiting for and which boot phase the owner has reached, straight from
boot-timing.log.
"""
from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

# This machine's GPU collapses QtWebEngine to a blank rectangle (the
# documented ArchHub blank-canvas failure). Software rendering is slower
# and always draws; set BEFORE Qt loads, as QtWebEngine reads it at
# import time.
# The shipped app proved this machine's GPU broken (its own marker,
# %LOCALAPPDATA%/ArchHub/use_software_render, dropped by its crash handler)
# and its recipe for a window that paints here is the PRODUCTION flag set
# plus --disable-gpu -- nothing more, nothing less. Anything else I tried
# (software Qt GL, no compositing, in-process GPU) left Chromium unable to
# create a shared context and the window never appeared.
os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    "--ignore-gpu-blocklist --enable-gpu-rasterization --enable-zero-copy "
    "--disable-gpu",
)

CANVAS = ("127.0.0.1", 8475)
BOOT_LOG = Path(os.environ.get("LOCALAPPDATA", "")) / "ArchHub" / \
    "unified-authority" / "boot-timing.log"


def _canvas_answers() -> bool:
    try:
        with socket.create_connection(CANVAS, timeout=0.5):
            return True
    except OSError:
        return False


def _boot_line() -> str:
    try:
        lines = BOOT_LOG.read_text(encoding="utf-8").strip().splitlines()
        return lines[-1] if lines else "no boot record yet"
    except OSError:
        return "no boot record yet"


def main() -> int:
    from PyQt6.QtCore import QTimer, QUrl
    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import (
        QApplication, QLabel, QMainWindow, QVBoxLayout, QWidget,
    )
    from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
    from PyQt6.QtWebEngineWidgets import QWebEngineView

    app = QApplication(sys.argv)
    window = QMainWindow()
    window.setWindowTitle("ArchHub")
    window.resize(1440, 900)
    icon = Path(__file__).resolve().parent / "assets" / "archhub.ico"
    if icon.exists():
        window.setWindowIcon(QIcon(str(icon)))

    storage = Path(os.environ.get("LOCALAPPDATA", ".")) / "ArchHub" / \
        "webengine-clean"
    storage.mkdir(parents=True, exist_ok=True)
    profile = QWebEngineProfile("archhub-clean", window)
    profile.setPersistentStoragePath(str(storage))
    profile.setCachePath(str(storage))
    profile.setPersistentCookiesPolicy(
        QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies
    )

    view = QWebEngineView()
    view.setPage(QWebEnginePage(profile, view))

    # ponytail: the owner now serves its own boot screen on this port
    # from the first second, so the shell has nothing to wait for and
    # nothing to narrate. Load the window and let the page speak.
    window.setCentralWidget(view)
    view.load(QUrl("http://127.0.0.1:8475/"))

    # The owner restarts -- on purpose, or because it was upgraded -- and
    # while its port is down the view loads Chromium's "site can't be
    # reached". Nothing brought it back: this timer reloaded while the
    # port was DOWN (which is the only way to guarantee that error page)
    # and did nothing once it answered again. So the window sat on an
    # error until the founder closed and reopened it.
    #
    # What it does now: remember whether the last load actually
    # succeeded, and reload when the port answers and the view is not
    # showing the canvas.
    loaded = {"ok": False}

    def _remember(ok: bool) -> None:
        loaded["ok"] = bool(ok)

    view.loadFinished.connect(_remember)

    def _retry() -> None:
        answering = _canvas_answers()
        if not answering:
            # It went away; whatever is on screen is stale.
            loaded["ok"] = False
            return
        if not loaded["ok"]:
            view.load(QUrl("http://127.0.0.1:8475/"))

    timer = QTimer(window)
    timer.timeout.connect(_retry)
    timer.start(2000)

    # A window that shows as a 160x28 sliver is not a window anyone can
    # use, and that is what this one measured as after show(). Size it to
    # the primary screen's available area and maximize explicitly.
    from PyQt6.QtGui import QGuiApplication
    screen = QGuiApplication.primaryScreen()
    if screen is not None:
        area = screen.availableGeometry()
        window.setGeometry(area)
    window.setMinimumSize(960, 600)
    window.showMaximized()
    window.raise_()
    window.activateWindow()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
