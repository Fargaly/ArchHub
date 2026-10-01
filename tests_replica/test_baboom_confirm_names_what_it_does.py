"""BABOOM's confirm control names what it will do, and does exactly that.

Reviews 2026-09-29/30: the companion showed the fixed "Restart ArchHub to
install it?" whatever build the graph named, and pressing it re-sent the words
he typed. The confirm now shows the graph's own sentence (build id; the fact
with its length and digest) and, when pressed, executes the single-use
confirmation the graph handed back -- nothing else.
"""
from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtWidgets import QApplication

from nodelang.baboom_native_companion import (
    BaboomNativeCompanionController,
    create_baboom_native_companion_window,
)
from nodelang.baboom_native_host import BaboomNativeHost
from nodelang.baboom_visual_assets import BaboomSpriteAtlas

CATALOG = "app:baboom-command-catalog:v1"
NONCE = "c" * 32


def _companion_court_transport():
    """The companion courts' own recorded transport (one frame, one session)."""
    import importlib.util
    from pathlib import Path
    path = Path(__file__).with_name("test_baboom_native_companion.py")
    spec = importlib.util.spec_from_file_location("_baboom_companion_court", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._Transport()


@pytest.fixture
def companion(tmp_path):
    app = QApplication.instance() or QApplication([])
    image = QImage(1536, 2288, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(0, 0, 0, 0))
    path = tmp_path / "atlas.png"
    assert image.save(str(path))
    atlas = BaboomSpriteAtlas(path=path, width=1536, height=2288, columns=8, rows=11,
                              cell_width=192, cell_height=208)
    transport = _companion_court_transport()
    executed = []

    def execute_baboom_command(*, utterance):
        executed.append(utterance)
        return {"kind": "remembered", "summary": "Done.", "data": {},
                "command": {"catalog": CATALOG, "intent": "remember"}}

    transport.execute_baboom_command = execute_baboom_command
    host = BaboomNativeHost(transport, external_session_id="confirm-court",
                            device_credential_provider=lambda challenge: {"proof": "approved"})
    host.connect()
    window = create_baboom_native_companion_window(
        BaboomNativeCompanionController(host, atlas, occupied_provider=lambda: ()))
    yield app, window, executed
    window.close()
    window.deleteLater()
    app.processEvents()


def _press_confirm(app, window, executed):
    window._confirm.click()
    deadline = time.monotonic() + 5.0
    while not executed and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)
    app.processEvents()


def test_the_restart_confirm_names_the_build_and_executes_its_confirmation(companion):
    app, window, executed = companion
    window._submitted_utterance = "restart to update"
    window._apply_response({
        "command": {"catalog": CATALOG, "intent": "restart-to-update"},
        "response": {
            "kind": "update-ready",
            "summary": "Build b-2 is staged. Restart ArchHub to install it?",
            "data": {"build_id": "b-2", "requires": "explicit execute",
                     "confirm_utterance": "confirm " + NONCE},
        },
    })
    assert "b-2" in window._transient_report, window._transient_report
    _press_confirm(app, window, executed)
    assert executed == ["confirm " + NONCE], "pressing confirm must execute the graph's confirmation"


def test_the_remember_confirm_shows_the_fact_and_executes_its_confirmation(companion):
    app, window, executed = companion
    window._submitted_utterance = "remember: the riser is 172 mm"
    window._apply_response({
        "command": {"catalog": CATALOG, "intent": "remember"},
        "response": {
            "kind": "remember-ready",
            "summary": ("Remember this in your Brain (19 characters, sha256 0123456789ab)? "
                        "It stays sealed on this machine: the riser is 172 mm"),
            "data": {"text": "the riser is 172 mm", "requires": "explicit execute",
                     "confirm_utterance": "confirm " + NONCE},
        },
    })
    assert "the riser is 172 mm" in window._transient_report, window._transient_report
    assert "19 characters" in window._transient_report
    _press_confirm(app, window, executed)
    assert executed == ["confirm " + NONCE]
