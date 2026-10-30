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
