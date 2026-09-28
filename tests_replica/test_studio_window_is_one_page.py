"""The desktop window holds one page: the Studio (UI audit 2026-09-28, 08-back-navigation).

A right-click offered Chromium's native Back / Reload menu, and the window history still
carried the bootstrap document at ``/``: Back, Alt+Left or the mouse's Back button left the
Studio. These courts drive a real offscreen QWebEngineView through the same two calls the
launcher makes, and check the launcher makes them where the Studio lands.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = (ROOT / "launch_archhub_test.py").read_text(encoding="utf-8")


def test_the_launcher_locks_the_view_and_forgets_what_is_behind_the_studio():
    created = LAUNCHER.index("view = QWebEngineView(window)")
    locked = LAUNCHER.index("lock_studio_navigation(view)")
    assert created < locked < LAUNCHER.index("view.load(QUrl(server.bootstrap_url))")
    landing = re.search(r"def _to_studio\(ok\):(.*?)\nview\.loadFinished", LAUNCHER, re.S).group(1)
    studio_branch = landing.split('elif ok and view.url().path().startswith("/studio"):', 1)[1]
    assert "forget_pages_behind_studio(view)" in studio_branch


# A QtWebEngine view is driven in its own interpreter: the web engine owns process-wide state
# that pytest's interpreter cannot tear down cleanly, and a crash there must not hide a result.
PROBE = r"""
import json, os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu"
sys.path.insert(0, sys.argv[1])
from PyQt6.QtCore import Qt, QCoreApplication, QEventLoop, QTimer, QUrl
from PyQt6.QtWidgets import QApplication
QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from nodelang.studio_window import forget_pages_behind_studio, lock_studio_navigation
app = QApplication(["archhub-court"])
view = QWebEngineView()
lock_studio_navigation(view)
def load(html, path):
    loop = QEventLoop(); view.loadFinished.connect(loop.quit); QTimer.singleShot(20000, loop.quit)
    view.setHtml(html, QUrl("http://127.0.0.1/" + path)); loop.exec(); view.loadFinished.disconnect(loop.quit)
load("<p>bootstrap document</p>", "")
load("<p>studio</p>", "studio")
seen = {"no_menu": view.contextMenuPolicy() == Qt.ContextMenuPolicy.NoContextMenu,
        "back_before": view.history().canGoBack()}
forget_pages_behind_studio(view)
seen.update(back_after=view.history().canGoBack(), entries=view.history().count())
print("RESULT " + json.dumps(seen), flush=True)
"""


def test_a_real_view_has_no_native_menu_and_nothing_to_go_back_to():
    pytest.importorskip("PyQt6.QtWebEngineWidgets")
    import json
    import subprocess
    import sys

    done = subprocess.run([sys.executable, "-c", PROBE, str(ROOT)], capture_output=True, text=True, timeout=120,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    line = next((row for row in done.stdout.splitlines() if row.startswith("RESULT ")), None)
    assert line, done.stdout[-2000:] + done.stderr[-2000:]
    seen = json.loads(line[len("RESULT "):])
    assert seen["no_menu"] is True, "no native Back / Reload menu"
    assert seen["back_before"] is True, "the fixture reproduces the audited history"
    assert seen["back_after"] is False, "nothing behind the Studio"
    assert seen["entries"] <= 1