"""PRESENCE1: real offscreen widgets, disposable transport, no desktop capture."""
import os
from pathlib import Path
import time

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PyQt6.QtWidgets import QApplication
from nodelang.baboom_native_companion import BaboomNativeCompanionController, create_baboom_native_companion_window
from nodelang.baboom_native_host import BaboomNativeHost
from nodelang.baboom_native_runtime import default_baboom_sprite_atlas_path
from nodelang.baboom_visual_assets import BaboomSpriteAtlas
from tests_replica.test_baboom_native_companion import _Transport


def make_companion():
    app = QApplication.instance() or QApplication([])
    atlas = BaboomSpriteAtlas(path=default_baboom_sprite_atlas_path(), width=1536,
        height=2288, columns=8, rows=11, cell_width=192, cell_height=208)
    host = BaboomNativeHost(_Transport(), external_session_id='presence1-isolated',
        device_credential_provider=lambda challenge: {'proof': 'test'})
    host.connect()
    controller = BaboomNativeCompanionController(host, atlas, occupied_provider=lambda: ())
    window = create_baboom_native_companion_window(controller)
    return app, host, window


def receipt(window, name):
    folder = Path('05.EVIDENCE/presence1')
    folder.mkdir(parents=True, exist_ok=True)
    # QWidget.grab renders only this test widget, never the founder's desktop.
    window.grab().save(str(folder / (os.environ.get('PRESENCE1_PHASE', 'green') + '-' + name + '.png')))


def test_fresh_profile_has_no_companion_window():
    app, host, window = make_companion()
    try:
        window.start_projection()
        app.processEvents()
        receipt(window, 'fresh')
        assert not window.isVisible(), 'fresh profile must start in Tray'
        assert window._tray.isVisible()
    finally:
        window.stop_projection()
        window.close()
        host.stop(timeout_seconds=.01)


def test_reconnect_never_opens_panel_or_button():
    app, host, window = make_companion()
    try:
        window.start_projection()
        for state in ('reconnecting', 'closed', 'live'):
            host.connection_state = state
            host._last_frame_received_at = time.monotonic() - 360
            window.refresh()
            app.processEvents()
            receipt(window, state)
            assert not window.isVisible(), 'connection changes must never open a window'
            assert not hasattr(window, "_open")
    finally:
        window.stop_projection()
        window.close()
        host.stop(timeout_seconds=.01)
