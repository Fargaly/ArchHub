"""R149: a link the Studio opens in a new window goes to his Chrome, never nowhere.

QtWebEngine drops window.open silently unless newWindowRequested is handled; these
checks drive the handler with fakes (no browser, no Qt engine).
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / '01.APP'))

from nodelang import studio_window  # noqa: E402
from nodelang.studio_window import open_outside  # noqa: E402


def _record():
    seen = []
    return seen, (lambda argv, **kw: seen.append(('chrome', argv))), (lambda url: seen.append(('default', url)) or True)


def test_chrome_wins_when_installed():
    seen, launch, fallback = _record()
    assert open_outside('https://checkout.example.com/pay?x=1', chrome_path=lambda: r'C:\Chrome\chrome.exe',
                        launch=launch, fallback=fallback)
    assert seen == [('chrome', [r'C:\Chrome\chrome.exe', 'https://checkout.example.com/pay?x=1'])]


def test_default_browser_when_no_chrome():
    seen, launch, fallback = _record()
    assert open_outside('https://www.notion.so/profile/connections', chrome_path=lambda: None,
                        launch=launch, fallback=fallback)
    assert seen == [('default', 'https://www.notion.so/profile/connections')]


def test_default_browser_when_chrome_will_not_start():
    seen, _launch, fallback = _record()

    def broken(argv, **kw):
        raise FileNotFoundError(argv[0])

    assert open_outside('https://example.com/', chrome_path=lambda: r'C:\Gone\chrome.exe',
                        launch=broken, fallback=fallback)
    assert seen == [('default', 'https://example.com/')]


def test_a_stale_registry_path_falls_through_to_the_next_hive(tmp_path, monkeypatch):
    real = tmp_path / 'chrome.exe'
    real.write_bytes(b'')
    values = {'HKCU': str(tmp_path / 'removed' / 'chrome.exe'), 'HKLM': '"%s"' % real}

    class Key:
        def __init__(self, hive):
            self.hive = hive

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    fake = types.SimpleNamespace(HKEY_CURRENT_USER='HKCU', HKEY_LOCAL_MACHINE='HKLM',
                                 OpenKey=lambda hive, path: Key(hive), QueryValue=lambda key, name: values[key.hive])
    monkeypatch.setitem(sys.modules, 'winreg', fake)
    assert studio_window._chrome_path() == str(real)


def test_unsafe_addresses_are_refused():
    seen, launch, fallback = _record()
    for url in ('file:///C:/Windows/System32/cmd.exe', 'javascript:alert(1)', 'https://user:pw@example.com/',
                '', 'https://', 'ms-settings:privacy'):
        assert open_outside(url, chrome_path=lambda: 'chrome.exe', launch=launch, fallback=fallback) is False
    assert seen == []


def test_the_window_lock_wires_new_window_requests(monkeypatch):
    # A stub QtCore keeps this behavioural on any runner, with or without PyQt6 installed.
    qtcore = types.ModuleType('PyQt6.QtCore')
    qtcore.Qt = types.SimpleNamespace(ContextMenuPolicy=types.SimpleNamespace(NoContextMenu='no-menu'))
    package = types.ModuleType('PyQt6')
    package.QtCore = qtcore
    monkeypatch.setitem(sys.modules, 'PyQt6', package)
    monkeypatch.setitem(sys.modules, 'PyQt6.QtCore', qtcore)

    class Signal:
        def __init__(self):
            self.slots = []

        def connect(self, slot):
            self.slots.append(slot)

    page = types.SimpleNamespace(newWindowRequested=Signal())

    class View:
        policy = None

        def setContextMenuPolicy(self, policy):
            self.policy = policy

        def page(self):
            return page

    opened = []
    monkeypatch.setattr(studio_window, 'open_outside', lambda url: opened.append(url) or True)
    view = View()
    studio_window.lock_studio_navigation(view)
    request = types.SimpleNamespace(requestedUrl=lambda: types.SimpleNamespace(toString=lambda: 'https://example.com/billing'))
    page.newWindowRequested.slots[0](request)
    assert view.policy == 'no-menu'
    assert opened == ['https://example.com/billing']
