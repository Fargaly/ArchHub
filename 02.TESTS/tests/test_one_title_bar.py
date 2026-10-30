"""One title bar: the Studio header answers Windows' hit-test; its window buttons reach the Qt window."""
from types import SimpleNamespace

from PyQt6.QtCore import QCoreApplication, QObject, QUrl

from nodelang.window_chrome import (HTCAPTION, HTCLIENT, HTCLOSE, HTMAXBUTTON, HTMINBUTTON, HTRIGHT, HTTOP, HTTOPLEFT,
                                    clean_layout, hit_test)
from nodelang.window_commands import CloseToTray, WindowCommands

HOLES = [[12, 8, 32, 32], [1080, 8, 220, 32]]  # menu mark, search
BUTTONS = [[1302, 0, 46, 48], [1348, 0, 46, 48], [1394, 0, 46, 48]]  # minimize, maximize, close


def hit(x, y, maximized=False):
    return hit_test(x, y, 1440, 900, 48, HOLES, BUTTONS, maximized)


def test_header_background_drags_controls_click_and_window_buttons_are_windows_caption_buttons():
    assert hit(600, 24) == HTCAPTION
    assert hit(30, 24) == HTCLIENT
    assert hit(1100, 24) == HTCLIENT
    assert (hit(1320, 24), hit(1360, 24), hit(1410, 24)) == (HTMINBUTTON, HTMAXBUTTON, HTCLOSE)
    assert hit(600, 400) == HTCLIENT


def test_edges_resize_only_when_not_maximized():
    assert hit(600, 2) == HTTOP
    assert hit(2, 2) == HTTOPLEFT
    assert hit(1438, 400) == HTRIGHT
    assert hit(600, 2, maximized=True) == HTCAPTION
    assert hit(1438, 2, maximized=True) == HTCLOSE  # Fitts: the maximized corner closes


def test_no_header_means_no_caption():
    assert hit_test(600, 18, 1440, 900, 0, [], None, False) == HTCLIENT


def test_page_report_is_bounded():
    caption, holes, maximize = clean_layout(48, [[1, 2, 3, 4], ['x'], [1, 2], None] + [[0, 0, 1, 1]] * 400,
                                             [[1, 2, 3, 4], [], [5, 6, 7, 8], [9, 9, 9, 9]])
    assert caption == 48 and holes[0] == [1, 2, 3, 4] and len(holes) == 253
    assert maximize == [[1, 2, 3, 4], None, [5, 6, 7, 8]]
    assert clean_layout(float('nan'), None, None) == (0.0, [], [])
    assert clean_layout(1e9, [], [])[0] == 200 and clean_layout('48', [], [])[0] == 0.0


class Window:
    def __init__(self):
        self.calls, self.maximized = [], False

    def isMaximized(self):
        return self.maximized

    def showMaximized(self):
        self.calls.append('showMaximized')

    def showNormal(self):
        self.calls.append('showNormal')

    def close(self):
        self.calls.append('close')

    isVisible = lambda self: True
    isMinimized = lambda self: False


def commands(window, title_bar=None, path='/studio'):
    app = QCoreApplication.instance() or QCoreApplication([])
    page = QObject()
    view = SimpleNamespace(page=lambda: page, url=lambda: QUrl('http://127.0.0.1:1234' + path),
                           urlChanged=SimpleNamespace(connect=lambda _f: None))
    return WindowCommands(view, window, lambda: None, 'http://127.0.0.1:1234', title_bar), app


def test_maximize_toggles_and_close_is_the_native_close():
    window = Window()
    bridge, app = commands(window)
    assert bridge.perform('maximize')['ok']
    window.maximized = True
    bridge.perform('maximize')
    assert window.calls == ['showMaximized', 'showNormal']
    bridge.perform('close')
    app.processEvents()
    assert window.calls[-1] == 'close'


def test_header_layout_reaches_the_title_bar_only_from_the_studio():
    seen = []
    title_bar = SimpleNamespace(layout=lambda *a: seen.append(a))
    commands(Window(), title_bar)[0].titleBar(48.0, HOLES, BUTTONS)
    commands(Window(), title_bar, path='/elsewhere')[0].titleBar(48.0, [], [])
    assert seen == [(48.0, HOLES, BUTTONS)]


def test_closing_the_window_hides_it_to_the_tray_and_only_quit_ends_the_app(tmp_path):
    from PyQt6.QtGui import QCloseEvent
    app = QCoreApplication.instance() or QCoreApplication([])

    class Win(QObject):
        hidden = 0

        def hide(self):
            self.hidden += 1
    window, quits, notices = Win(), [], []
    tray = SimpleNamespace(icon=lambda: None, showMessage=lambda *a: notices.append(a[1]))
    stay = CloseToTray(window, tray, lambda: quits.append(1), tmp_path / 'tray-notice-shown')
    for _ in range(2):
        close = QCloseEvent()
        app.sendEvent(window, close)
        assert not close.isAccepted()
    assert window.hidden == 2 and quits == [] and notices == ['ArchHub keeps running in the tray']
    stay.quit()
    app.sendEvent(window, QCloseEvent())
    assert quits == [1] and window.hidden == 2
