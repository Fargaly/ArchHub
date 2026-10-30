"""One title bar: the Studio header is the window's caption (Windows only).

Mechanism, as PyQt-Frameless-Window, melak47/BorderlessWindow and Windows Terminal do it: the frameless
Qt window gets WS_CAPTION | WS_THICKFRAME back, so Windows keeps snap, Snap Layouts, shadow, animations
and resize; WM_NCCALCSIZE makes the whole window client; WM_NCHITTEST answers resize edge, caption or the
minimize / maximize / close caption-button codes from the header layout the Studio page reports
(window_commands.titleBar), so Windows treats the header's buttons as its own: Snap Layouts on maximize.
"""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes as w

HTCLIENT, HTCAPTION, HTMINBUTTON, HTMAXBUTTON, HTCLOSE = 1, 2, 8, 9, 20
BUTTON_CODES = (HTMINBUTTON, HTMAXBUTTON, HTCLOSE)  # the order the page reports its window buttons in
HTLEFT, HTRIGHT, HTTOP, HTTOPLEFT, HTTOPRIGHT, HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT = 10, 11, 12, 13, 14, 15, 16, 17
WM_NCCALCSIZE, WM_NCHITTEST = 0x0083, 0x0084
WM_NCMOUSEMOVE, WM_NCLBUTTONDOWN, WM_NCLBUTTONUP, WM_NCLBUTTONDBLCLK, WM_NCMOUSELEAVE = 0x00A0, 0x00A1, 0x00A2, 0x00A3, 0x02A2
RESIZE_BORDER = 6  # CSS px inside the window edge that resize it
MAX_HOLES = 256


def hit_test(x, y, width, height, caption, holes, buttons, maximized, border=RESIZE_BORDER):
    """The Windows hit-test code for page point (x, y); every length is in CSS px of the Studio page."""
    inside = lambda box: box[0] <= x < box[0] + box[2] and box[1] <= y < box[1] + box[3]
    if not maximized:
        top, bottom, left, right = y < border, y >= height - border, x < border, x >= width - border
        if top or bottom or left or right:
            if top:
                return HTTOPLEFT if left else HTTOPRIGHT if right else HTTOP
            if bottom:
                return HTBOTTOMLEFT if left else HTBOTTOMRIGHT if right else HTBOTTOM
            return HTLEFT if left else HTRIGHT
    for code, box in zip(BUTTON_CODES, buttons or ()):
        if box and inside(box):
            return code
    if y < caption and not any(inside(hole) for hole in holes):
        return HTCAPTION
    return HTCLIENT


def clean_layout(caption, holes, buttons):
    """The page's report, bounded: a caption height and boxes of four finite numbers."""
    number = lambda n: isinstance(n, (int, float)) and not isinstance(n, bool) and abs(n) < 1e6  # NaN fails abs < 1e6

    def box(value):
        if not isinstance(value, (list, tuple)) or len(value) != 4 or not all(number(n) for n in value):
            return None
        return [float(n) for n in value]
    real = isinstance(caption, (int, float)) and not isinstance(caption, bool) and caption == caption  # NaN is no caption
    caption = min(max(float(caption), 0.0), 200.0) if real else 0.0
    boxes = [b for b in (box(h) for h in list(holes or [])[:MAX_HOLES]) if b]
    return caption, boxes, [box(b) for b in list(buttons or [])[:len(BUTTON_CODES)]]


class _RECT(ctypes.Structure):
    _fields_ = [('left', w.LONG), ('top', w.LONG), ('right', w.LONG), ('bottom', w.LONG)]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [('cbSize', w.DWORD), ('rcMonitor', _RECT), ('rcWork', _RECT), ('dwFlags', w.DWORD)]


class _TRACKMOUSEEVENT(ctypes.Structure):
    _fields_ = [('cbSize', w.DWORD), ('dwFlags', w.DWORD), ('hwndTrack', w.HWND), ('dwHoverTime', w.DWORD)]


class _MARGINS(ctypes.Structure):
    _fields_ = [('l', ctypes.c_int), ('r', ctypes.c_int), ('t', ctypes.c_int), ('b', ctypes.c_int)]


def install_one_title_bar(window, view):
    """Make the Studio header the window's only title bar; None where the native frame stays (not Windows)."""
    if os.name != 'nt':
        return None
    from PyQt6.QtCore import QAbstractNativeEventFilter, QEvent, QObject, Qt
    from PyQt6.QtWidgets import QApplication
    user32, dwmapi = ctypes.windll.user32, ctypes.windll.dwmapi
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.GetWindowLongPtrW.argtypes = [w.HWND, ctypes.c_int]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = [w.HWND, ctypes.c_int, ctypes.c_ssize_t]
    user32.MonitorFromWindow.restype = w.HMONITOR
    user32.MonitorFromWindow.argtypes = [w.HWND, w.DWORD]
    user32.GetMonitorInfoW.argtypes = [w.HMONITOR, ctypes.POINTER(_MONITORINFO)]
    user32.ScreenToClient.argtypes = [w.HWND, ctypes.POINTER(w.POINT)]
    user32.IsZoomed.argtypes = [w.HWND]
    user32.TrackMouseEvent.argtypes = [ctypes.POINTER(_TRACKMOUSEEVENT)]
    user32.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.UINT]
    dwmapi.DwmExtendFrameIntoClientArea.argtypes = [w.HWND, ctypes.POINTER(_MARGINS)]

    class TitleBar(QObject):
        def __init__(self):
            super().__init__(window)
            self.caption, self.holes, self.buttons, self._page_state, self.pressed = 0.0, [], [], {}, None
            window.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
            self.hwnd = None
            self.frame()
            self._filter = _Filter(self)
            QApplication.instance().installNativeEventFilter(self._filter)
            window.installEventFilter(self)
            view.loadFinished.connect(lambda _ok: self._push(force=True))

        def frame(self):
            # The web view's surface makes Qt recreate the native window, so this runs again on WinIdChange.
            self.hwnd = int(window.winId())
            # WS_CAPTION | WS_SYSMENU | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX: snap, Alt+Space, shadow, animations.
            style = user32.GetWindowLongPtrW(self.hwnd, -16) | 0x00C00000 | 0x00080000 | 0x00040000 | 0x00020000 | 0x00010000
            user32.SetWindowLongPtrW(self.hwnd, -16, style)
            dwmapi.DwmExtendFrameIntoClientArea(self.hwnd, ctypes.byref(_MARGINS(1, 1, 1, 1)))  # keeps the shadow
            user32.SetWindowPos(self.hwnd, None, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020)

        def layout(self, caption, holes, buttons):
            self.caption, self.holes, self.buttons = clean_layout(caption, holes, buttons)

        def press(self, code):
            if code == HTMINBUTTON:
                window.showMinimized()
            elif code == HTMAXBUTTON:
                window.showNormal() if window.isMaximized() else window.showMaximized()
            elif code == HTCLOSE:
                window.close()  # the same close the native caption button did

        def page_point(self, lparam):
            point = w.POINT(ctypes.c_short(lparam & 0xFFFF).value, ctypes.c_short((lparam >> 16) & 0xFFFF).value)
            user32.ScreenToClient(self.hwnd, ctypes.byref(point))
            scale = (window.windowHandle().devicePixelRatio() if window.windowHandle() else 1.0) * (view.zoomFactor() or 1.0)
            return point.x / scale, point.y / scale, view.width() / (view.zoomFactor() or 1.0), view.height() / (view.zoomFactor() or 1.0)

        def hit(self, lparam):
            x, y, width, height = self.page_point(lparam)
            return hit_test(x, y, width, height, self.caption, self.holes, self.buttons, bool(user32.IsZoomed(self.hwnd)))

        def _push(self, force=False, **state):
            state = {'windowMaximized': 'true' if window.isMaximized() else 'false',
                     'windowHover': self._page_state.get('windowHover', ''), **state}
            if force or state != self._page_state:
                # The Studio re-renders on this event, so the maximize button's name follows the window (Restore).
                rerender = force or state['windowMaximized'] != self._page_state.get('windowMaximized')
                self._page_state = state
                view.page().runJavaScript(''.join("document.documentElement.dataset.%s='%s';" % item for item in state.items())
                                          + ("window.dispatchEvent(new Event('archhub:capabilities'));" if rerender else ""))

        def hover(self, code):
            self._push(windowHover={HTMINBUTTON: 'minimize', HTMAXBUTTON: 'maximize', HTCLOSE: 'close'}.get(code, ''))

        def eventFilter(self, watched, event):
            if watched is window and event.type() == QEvent.Type.WindowStateChange:
                self._push()
            elif watched is window and event.type() == QEvent.Type.WinIdChange and window.testAttribute(Qt.WidgetAttribute.WA_WState_Created):
                self.frame()
            return False

        def fit_maximized(self, lparam):
            # A maximized thick-frame window overhangs its monitor by the frame; keep the client on the work area.
            rect = _RECT.from_address(lparam)
            info = _MONITORINFO(cbSize=ctypes.sizeof(_MONITORINFO))
            if user32.GetMonitorInfoW(user32.MonitorFromWindow(self.hwnd, 2), ctypes.byref(info)):
                work = info.rcWork
                rect.left, rect.top = max(rect.left, work.left), max(rect.top, work.top)
                rect.right, rect.bottom = min(rect.right, work.right), min(rect.bottom, work.bottom)

    class _Filter(QAbstractNativeEventFilter):
        def __init__(self, bar):
            super().__init__()
            self.bar = bar

        def nativeEventFilter(self, event_type, message):
            if event_type != b'windows_generic_MSG' or not message:
                return False, 0
            msg = w.MSG.from_address(int(message))
            bar = self.bar
            if int(msg.hWnd or 0) != bar.hwnd:
                return False, 0
            kind, lparam = msg.message, int(msg.lParam or 0)
            if kind == WM_NCCALCSIZE:
                if msg.wParam and user32.IsZoomed(bar.hwnd):
                    bar.fit_maximized(lparam)
                return True, 0  # the whole window is client: the Studio header is the caption
            if kind == WM_NCHITTEST:
                return True, bar.hit(lparam)
            code = int(msg.wParam or 0) if int(msg.wParam or 0) in BUTTON_CODES else None
            if kind == WM_NCMOUSEMOVE:
                bar.hover(code)
                if code:
                    track = _TRACKMOUSEEVENT(ctypes.sizeof(_TRACKMOUSEEVENT), 0x00000002 | 0x00000010, bar.hwnd, 0)
                    user32.TrackMouseEvent(ctypes.byref(track))
            elif kind == WM_NCMOUSELEAVE:
                bar.hover(None)
                bar.pressed = None
            elif kind in (WM_NCLBUTTONDOWN, WM_NCLBUTTONDBLCLK) and code:
                bar.pressed = code
                return True, 0  # Windows' own button tracking would paint an old caption button
            elif kind == WM_NCLBUTTONUP and code:
                pressed, bar.pressed = bar.pressed, None
                if pressed == code:
                    bar.press(code)
                return True, 0
            return False, 0

    return TitleBar()
