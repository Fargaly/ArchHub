"""Court: the BABOOM pet shows on the desktop by default.

NOGRAPH's companion frames carried no "shows_as", so the companion fell back to "Tray" and
hid its on-screen sprite every frame (installed 20261030-1200-5520a6f: hwnd 56x56, hidden).
"""
from __future__ import annotations

import json

from nodelang import baboom_nograph


def test_frames_say_screen_unless_the_founder_chose_otherwise(tmp_path, monkeypatch):
    monkeypatch.setitem(baboom_nograph._STATE, 'state_dir', tmp_path)
    frame = lambda: baboom_nograph.NoGraphTransport().baboom_native_frame()['context']['shows_as']
    assert frame() == 'Screen'
    (tmp_path / 'settings').mkdir()
    (tmp_path / 'settings' / 'baboom.json').write_text(json.dumps({'startup': 'on', 'shows_as': 'Tray'}))
    assert frame() == 'Tray'


def test_the_pet_steps_aside_while_settings_is_open(tmp_path, monkeypatch):
    """SETTINGSMATCH: the board has no wizard over Settings; the Studio reports its open screen."""
    from types import SimpleNamespace
    from nodelang.nograph_server import r_studio_surface
    monkeypatch.setitem(baboom_nograph._STATE, 'state_dir', tmp_path)
    monkeypatch.setitem(baboom_nograph._STATE, 'studio_surface', '')
    frame = lambda: baboom_nograph.NoGraphTransport().baboom_native_frame()['context']['shows_as']
    post = lambda surface: r_studio_surface(None, SimpleNamespace(method='POST', body={'surface': surface}))
    assert post('settings/Account') == {'ok': True, 'surface': 'settings/Account'}
    assert frame() == 'Tray'
    post('home')
    assert frame() == 'Screen'
    post('')
    assert frame() == 'Screen'
    (tmp_path / 'settings').mkdir()
    (tmp_path / 'settings' / 'baboom.json').write_text(json.dumps({'startup': 'on', 'shows_as': 'Hidden'}))
    post('settings/Account')
    assert frame() == 'Hidden'
    import pytest
    with pytest.raises(ValueError):
        post(['settings'])


def test_the_pet_returns_when_the_studio_is_gone(tmp_path, monkeypatch):
    """Settings left open, then the window hides to the tray, minimises or its renderer dies: the pet comes back."""
    import os
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PyQt6.QtCore import QObject, pyqtSignal
    from PyQt6.QtWidgets import QApplication, QWidget
    from nodelang.window_commands import StudioGone
    app = QApplication.instance() or QApplication([])

    class Page(QObject):
        renderProcessTerminated = pyqtSignal(object, int)

    monkeypatch.setitem(baboom_nograph._STATE, 'state_dir', tmp_path)
    frame = lambda: baboom_nograph.NoGraphTransport().baboom_native_frame()['context']['shows_as']
    window, page = QWidget(), Page()
    gone = StudioGone(window, page, baboom_nograph.set_studio_surface)
    for leave in (window.hide, window.showMinimized, lambda: page.renderProcessTerminated.emit(None, 1)):
        window.show()
        app.processEvents()
        baboom_nograph.set_studio_surface('settings/Account')
        assert frame() == 'Tray'
        leave()
        app.processEvents()
        assert baboom_nograph.studio_surface() == ''
        assert frame() == 'Screen'
    del gone
    window.close()
