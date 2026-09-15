"""User lifecycle controls, using disposable transports and offscreen widgets."""
from dataclasses import replace
import os
from pathlib import Path
import threading
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QImage
from PyQt6.QtCore import Qt
from nodelang.baboom_native_host import BaboomNativeHost
from nodelang.baboom_native_companion import BaboomNativeCompanionController, create_baboom_native_companion_window, baboom_face_line
from nodelang.baboom_visual_assets import BaboomSpriteAtlas
from test_baboom_native_companion import _Transport


@pytest.fixture
def companion(tmp_path):
    app = QApplication.instance() or QApplication([])
    path = tmp_path / 'atlas.png'
    image = QImage(1536, 2288, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    assert image.save(str(path))
    atlas = BaboomSpriteAtlas(path=path, width=1536, height=2288, columns=8, rows=11, cell_width=192, cell_height=208)
    host = BaboomNativeHost(_Transport(), external_session_id='isolated-user', device_credential_provider=lambda c: {'proof':'test'})
    host.connect()
    controller = BaboomNativeCompanionController(host, atlas, occupied_provider=lambda: ())
    stopped = []
    window = create_baboom_native_companion_window(controller, on_stop=lambda: stopped.append(True))
    window.start_projection()
    yield app, host, window, stopped
    window.stop_projection()
    window.close()
    host.stop(timeout_seconds=.01)


def test_hidden_companion_stays_hidden_on_refresh_and_late_reply(companion):
    app, host, window, _ = companion
    window.hide_until_next_launch()
    for _ in range(3):
        window.refresh()
        window._apply_response({'late':'ignored'})
        app.processEvents()
    assert not window.isVisible()
    assert not window._projection_timer.isActive()
    assert not host._stop.is_set(), 'hide is not a host stop'


def test_stop_blocks_new_requests_and_cancels_voice_without_replay(companion):
    _, host, window, stopped = companion
    cancellation = threading.Event()
    window._voice_cancel = cancellation
    window.stop_baboom()
    assert cancellation.is_set() and stopped == [True]
    for request in (host.resolve_input, host.respond_input, host.execute_input):
        with pytest.raises(RuntimeError, match='stopped'):
            request('status')
    window.start_projection()
    assert not window._projection_timer.isActive()


def test_stale_actionable_report_and_offer_are_suppressed(companion):
    _, host, window, _ = companion
    host._latest = replace(host.latest_snapshot, frame_expires_at=time.time()-3600)
    window._transient_report = 'Old unrelated task status'
    window._pending_task_utterance = 'old action'
    window.refresh()
    assert 'Live state unavailable' in window._report.text()
    assert window._pending_task_utterance is None
    assert not window._confirm.isVisible()
    assert window._frame.brain_state == 'unknown'
    line, offer = baboom_face_line({'host_silent_seconds':3600, 'brain':{'ok':True,'facts':9999}}, ('Revit','revit.read','Read walls'))
    assert '9999' not in line and 'Revit' not in line and offer is None

