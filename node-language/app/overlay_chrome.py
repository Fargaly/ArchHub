"""HUD overlay chrome — turns ArchHub from a regular window into a
translucent always-on-top sidecar that floats over whatever the
architect is doing in Revit / AutoCAD / Blender.

Three states:
  * collapsed — only the pet strip visible (bottom-right). Mouse-
    through (clicks pass to Revit underneath). Opacity = 70 %.
  * docked    — chat panel slides in from the right edge, ~38 % of
    screen width, frameless. Pet strip stays visible at bottom.
    Opacity = 92 % so the architect can still read drawings behind.
  * floating  — old fullscreen behaviour for users who prefer it.
                Toggle in Settings → Appearance.

Activation:
  * Hotkey:  Ctrl + Space  (global, registered via Win32 RegisterHotKey)
  * Click any pet → expand to docked
  * Esc / click outside → collapse to pet strip

Auto-fade: after 8 s of mouse-idle on the panel, opacity ramps
70 % → 50 %. Mouse move on the panel → back to 92 %. Lets the
architect see drawings underneath when not actively chatting.

Drop-in: wraps an existing ChatWindow without code changes. Old
fullscreen mode stays available via a setting flag.
"""
from __future__ import annotations

import sys
from typing import Optional

from PyQt6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve, QRect, QPoint,
    pyqtSignal, QEvent,
)
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QWidget


# ---------------------------------------------------------------------------
def apply_overlay_chrome(window: QWidget, *,
                         dock_width_ratio: float = 0.38,
                         opacity_active: float = 0.92,
                         opacity_idle: float = 0.55,
                         idle_delay_ms: int = 8000) -> "OverlayController":
    """Mutate `window` in place to use the HUD overlay chrome.
    Returns an OverlayController the caller can use to expand /
    collapse / register hotkeys."""
    flags = (
        Qt.WindowType.FramelessWindowHint
        | Qt.WindowType.WindowStaysOnTopHint
        | Qt.WindowType.Tool
    )
    window.setWindowFlags(flags)
    window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
    window.setWindowOpacity(opacity_active)

    screen = QGuiApplication.primaryScreen()
    geo = screen.availableGeometry() if screen else QRect(0, 0, 1280, 800)
    width = max(420, int(geo.width() * dock_width_ratio))
    height = geo.height() - 24
    window.setGeometry(QRect(geo.right() - width - 12, geo.top() + 12,
                             width, height))

    return OverlayController(
        window,
        opacity_active=opacity_active,
        opacity_idle=opacity_idle,
        idle_delay_ms=idle_delay_ms,
    )


# ---------------------------------------------------------------------------
class OverlayController:
    """Owns the docked/collapsed state machine + opacity fade.

    Lifetime is the host window's lifetime; pass `parent=window` if
    you want it cleaned up automatically.
    """

    def __init__(self, window: QWidget, *,
                 opacity_active: float, opacity_idle: float,
                 idle_delay_ms: int):
        self.window = window
        self.opacity_active = opacity_active
        self.opacity_idle = opacity_idle
        self._opacity_anim: Optional[QPropertyAnimation] = None

        # Idle timer: every move on the panel resets it; on timeout we
        # fade to opacity_idle. Mouse move events bubble up through Qt
        # so a single eventFilter on the window catches everything.
        self._idle_timer = QTimer(window)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._fade_to_idle)
        self._idle_delay_ms = idle_delay_ms
        window.installEventFilter(_IdleResetFilter(self))

        # Esc collapses → minimise to bottom-right (back to pet strip).
        # We implement collapse via window.hide() so the pet strip
        # (a separate top-level window) remains visible.
        window.installEventFilter(_EscCloseFilter(self))

    # ----- public state ---------------------------------------------------
    def expand(self) -> None:
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()
        self._fade_to_active()

    def collapse(self) -> None:
        self.window.hide()

    def toggle(self) -> None:
        if self.window.isVisible():
            self.collapse()
        else:
            self.expand()

    # ----- opacity --------------------------------------------------------
    def _fade_to(self, target: float, ms: int = 250) -> None:
        if self._opacity_anim is not None:
            self._opacity_anim.stop()
        anim = QPropertyAnimation(self.window, b"windowOpacity")
        anim.setDuration(ms)
        anim.setStartValue(self.window.windowOpacity())
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()
        self._opacity_anim = anim

    def _fade_to_active(self) -> None:
        self._fade_to(self.opacity_active)
        self._idle_timer.start(self._idle_delay_ms)

    def _fade_to_idle(self) -> None:
        self._fade_to(self.opacity_idle, ms=600)

    def reset_idle(self) -> None:
        # Called by IdleResetFilter on every mouse movement.
        if self.window.windowOpacity() < self.opacity_active - 0.01:
            self._fade_to_active()
        else:
            self._idle_timer.start(self._idle_delay_ms)


# ---------------------------------------------------------------------------
class _IdleResetFilter:
    def __init__(self, controller: OverlayController):
        self.controller = controller

    def eventFilter(self, obj, ev):       # noqa: N802 — Qt API
        if ev.type() in (QEvent.Type.MouseMove, QEvent.Type.KeyPress,
                         QEvent.Type.Wheel, QEvent.Type.MouseButtonPress):
            self.controller.reset_idle()
        return False


class _EscCloseFilter:
    def __init__(self, controller: OverlayController):
        self.controller = controller

    def eventFilter(self, obj, ev):       # noqa: N802
        if ev.type() == QEvent.Type.KeyPress and ev.key() == Qt.Key.Key_Escape:
            self.controller.collapse()
            return True
        return False


# ---------------------------------------------------------------------------
def install_global_hotkey(controller: OverlayController, *,
                          combo: str = "ctrl+space") -> bool:
    """Register a Win32 global hotkey that toggles the overlay.

    Uses ctypes against user32.RegisterHotKey so we don't pull a
    dependency. Returns True if the registration succeeded.
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        import ctypes.wintypes as wt
        from PyQt6.QtCore import QAbstractNativeEventFilter
    except Exception:
        return False

    MOD = {"alt": 0x1, "ctrl": 0x2, "shift": 0x4, "win": 0x8}
    VK = {
        "space": 0x20, "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73,
        "f5": 0x74, "f6": 0x75, "f7": 0x76, "f8": 0x77, "f9": 0x78,
        "a": 0x41, "z": 0x5A,
    }

    parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
    mods = 0
    key = 0
    for p in parts:
        if p in MOD:
            mods |= MOD[p]
        elif p in VK:
            key = VK[p]
    if not key:
        return False

    HOTKEY_ID = 0xC0FE        # arbitrary; anything < 0xC000 is reserved
    user32 = ctypes.windll.user32
    if not user32.RegisterHotKey(None, HOTKEY_ID, mods, key):
        return False

    class _Filter(QAbstractNativeEventFilter):
        def nativeEventFilter(self, eventType, message):  # noqa: N802
            if eventType != "windows_generic_MSG":
                return False, 0
            msg = wt.MSG.from_address(int(message))
            if msg.message == 0x0312 and msg.wParam == HOTKEY_ID:
                controller.toggle()
            return False, 0

    flt = _Filter()
    from PyQt6.QtWidgets import QApplication
    QApplication.instance().installNativeEventFilter(flt)
    # Keep ref so GC doesn't drop the filter.
    controller._native_filter = flt
    return True
