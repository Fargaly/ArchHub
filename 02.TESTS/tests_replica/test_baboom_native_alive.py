"""Courts for BABOOM native desktop companion aliveness, drag, and edge-safe placement.

Proves:
- Click vs drag separation using Qt startDragDistance().
- Free movement and soft-landing settle across screen geometry without snapping back.
- No snap-back to bottom-right or composer on refresh, bubble open, or bubble close.
- Edge-safe dynamic speech bubble flipping on left, right, and bottom screen boundaries.
- F13-safe autonomous gentle roaming/perching near active work.
- Autonomous roaming pause when dragging, hovering, bubble open, or Stay put (DND).
"""
from __future__ import annotations

import json
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QColor, QImage, QPainter, QMouseEvent
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt

from nodelang.baboom_companion_placement import Rect
from nodelang.baboom_native_companion import (
    ALIVE_NODE,
    BaboomNativeCompanionController,
    create_baboom_native_companion_window,
)
from nodelang.baboom_native_host import BaboomNativeHost
from nodelang.baboom_visual_assets import BaboomSpriteAtlas
from tests_replica.test_baboom_native_companion import _ScreenTransport


def _create_alive_companion(tmp_path, monkeypatch, name="alive_test.png"):
    import nodelang.baboom_native_companion as companion

    monkeypatch.setattr(companion, "foreign_foreground_window", lambda: False)
    monkeypatch.setattr(companion, "desktop_input_idle_seconds", lambda: 30.0)

    app = QApplication.instance() or QApplication([])
    atlas_image = QImage(1536, 2288, QImage.Format.Format_ARGB32_Premultiplied)
    atlas_image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(atlas_image)
    for row in range(11):
        for col in range(8):
            painter.fillRect(col * 192 + 48, row * 208 + 50, 96, 120, QColor(28, 187, 171, 255))
    painter.end()

    atlas_path = tmp_path / name
    assert atlas_image.save(str(atlas_path))

    atlas = BaboomSpriteAtlas(
        path=atlas_path, width=1536, height=2288, columns=8, rows=11,
        cell_width=192, cell_height=208,
    )
    host = BaboomNativeHost(
        _ScreenTransport(),
        external_session_id="companion-alive-court",
        device_credential_provider=lambda challenge: {"proof": "approved"},
    )
    host.connect()

    controller = BaboomNativeCompanionController(host, atlas, occupied_provider=lambda: ())
    position_path = tmp_path / "baboom-position.json"
    window = create_baboom_native_companion_window(controller, position_path=position_path)
    window.start_projection()
    app.processEvents()
    window.refresh()
    app.processEvents()

    return app, window, controller, position_path


def _send_mouse(app, window, kind, point, button=Qt.MouseButton.LeftButton):
    event = QMouseEvent(
        kind, QPointF(point), QPointF(window.mapToGlobal(point)),
        button, button, Qt.KeyboardModifier.NoModifier,
    )
    app.sendEvent(window, event)
    app.processEvents()


def test_click_vs_drag_separation(tmp_path, monkeypatch):
    """Small movement under drag threshold is a click; movement exceeding threshold drags."""
    app, window, _controller, position_path = _create_alive_companion(tmp_path, monkeypatch, "click_drag.png")
    try:
        opaque = window._sprite_rect.center()

        # 1. Move below drag threshold (2px)
        _send_mouse(app, window, QEvent.Type.MouseButtonPress, opaque)
        _send_mouse(app, window, QEvent.Type.MouseMove, opaque + QPoint(2, 0))
        assert not window._dragged, "2px movement must not be recognized as drag"
        _send_mouse(app, window, QEvent.Type.MouseButtonRelease, opaque + QPoint(2, 0))

        # 2. Move above drag threshold (threshold is QApplication.startDragDistance(), >= 10px)
        threshold = QApplication.startDragDistance()
        initial_pos = window.pos()
        _send_mouse(app, window, QEvent.Type.MouseButtonPress, opaque)
        _send_mouse(app, window, QEvent.Type.MouseMove, opaque + QPoint(threshold + 10, 5))
        assert window._dragged, "Movement exceeding startDragDistance() must trigger drag"
        assert window.pos() != initial_pos, "Window must move during drag"

        _send_mouse(app, window, QEvent.Type.MouseButtonRelease, opaque + QPoint(threshold + 10, 5))
        assert not window._dragged
        assert window._pinned is True

        # Wait for async position save job to write to disk
        window._position_jobs.submit(lambda: None).result(timeout=4)
        assert position_path.is_file()
        saved = json.loads(position_path.read_text(encoding="utf-8"))
        assert "x" in saved and "y" in saved
    finally:
        window.stop_projection()
        window.close()


def test_no_snap_back_on_refresh_and_state_change(tmp_path, monkeypatch):
    """Dragging to a screen location persists across multiple refreshes and state changes."""
    app, window, controller, _ = _create_alive_companion(tmp_path, monkeypatch, "no_snap.png")
    try:
        # Place BABOOM at an interior screen point
        target_x, target_y = 350, 280
        controller.pin_sprite_origin(target_x, target_y)
        window._pin_here(True)
        window.refresh()
        app.processEvents()

        current_origin = window.pos() + window._sprite_rect.topLeft()
        assert current_origin == QPoint(target_x, target_y), "Must not snap to perimeter or corner"

        # Refresh multiple times - must hold position firmly
        for _ in range(5):
            window.refresh()
            app.processEvents()
            assert (window.pos() + window._sprite_rect.topLeft()) == QPoint(target_x, target_y)

        # Open state bubble - must not snap back
        window._work_rows = lambda: [{"id": "approval", "status": "IN REVIEW", "title": "Review the tags"}]
        window.refresh()
        app.processEvents()
        assert window._state_bubble.isVisible()
        assert (window.pos() + window._sprite_rect.topLeft()) == QPoint(target_x, target_y)

        # Close state bubble - must still not snap back
        window._work_rows = lambda: []
        window.refresh()
        app.processEvents()
        assert not window._state_bubble.isVisible()
        assert (window.pos() + window._sprite_rect.topLeft()) == QPoint(target_x, target_y)
    finally:
        window.stop_projection()
        window.close()


def test_edge_safe_bubble_positioning(tmp_path, monkeypatch):
    """Speech bubble flips dynamically near screen edges to prevent off-screen clipping."""
    app, window, controller, _ = _create_alive_companion(tmp_path, monkeypatch, "edge_bubble.png")
    screen = Rect(0, 0, 1920, 1080)
    window._screen_rect = lambda: screen
    try:
        window._work_rows = lambda: [{"id": "approval", "status": "IN REVIEW", "title": "Long status message for test"}]

        # 1. BABOOM near right edge: bubble must flip to the LEFT of sprite
        controller.pin_sprite_origin(1820, 400)
        window.refresh()
        app.processEvents()
        assert window._state_bubble.isVisible()
        assert window._state_bubble.x() < window._sprite_rect.x(), "Bubble must flip to left of sprite"
        assert window.x() + window.width() <= screen.right, "Window must not clip off right edge"

        # 2. BABOOM near left edge: bubble must flip to the RIGHT of sprite
        controller.pin_sprite_origin(20, 400)
        window.refresh()
        app.processEvents()
        assert window._state_bubble.isVisible()
        assert window._state_bubble.x() > window._sprite_rect.x(), "Bubble must flip to right of sprite"
        assert window.x() >= screen.x, "Window must not clip off left edge"

        # 3. BABOOM near bottom edge: bubble must sit above sprite
        controller.pin_sprite_origin(500, 1000)
        window.refresh()
        app.processEvents()
        assert window._state_bubble.isVisible()
        assert window.y() >= screen.y
        assert window.y() + window.height() <= screen.bottom + 20
    finally:
        window.stop_projection()
        window.close()


def test_autonomous_roaming_and_pausing(tmp_path, monkeypatch):
    """F13-safe autonomous roaming perches near active work and pauses when busy or stay_put."""
    import nodelang.baboom_native_companion as companion

    app, window, controller, _ = _create_alive_companion(tmp_path, monkeypatch, "roam.png")
    screen = Rect(0, 0, 1920, 1080)
    window._screen_rect = lambda: screen
    try:
        # Initial position
        controller.pin_sprite_origin(500, 500)
        window.refresh()
        app.processEvents()

        # Mock an active foreground window
        active_rect = Rect(200, 150, 700, 500)
        monkeypatch.setattr(companion, "foreground_window_rect_windows", lambda: active_rect)

        # 1. Normal roam tick when idle moves gently towards active work
        window._roam_tick()
        app.processEvents()
        new_origin = window.pos() + window._sprite_rect.topLeft()
        assert new_origin != QPoint(500, 500), "Roam tick must step towards active work"
        assert abs(new_origin.x() - 500) <= ALIVE_NODE["params"]["step_px"]
        assert abs(new_origin.y() - 500) <= ALIVE_NODE["params"]["step_px"]

        # 2. Pauses when dragging
        cur_pos = new_origin
        window._dragged = True
        window._roam_tick()
        assert (window.pos() + window._sprite_rect.topLeft()) == cur_pos
        window._dragged = False

        # 3. Pauses when hovering
        window._hover_since = time.monotonic()
        window._roam_tick()
        assert (window.pos() + window._sprite_rect.topLeft()) == cur_pos
        window._hover_since = None

        # 4. Pauses when bubble is visible
        window._work_rows = lambda: [{"id": "approval", "status": "IN REVIEW", "title": "Action needed"}]
        window.refresh()
        app.processEvents()
        cur_pos = window.pos() + window._sprite_rect.topLeft()
        window._roam_tick()
        assert (window.pos() + window._sprite_rect.topLeft()) == cur_pos
        window._work_rows = lambda: []
        window.refresh()
        app.processEvents()

        # 5. Pauses when Stay put is toggled
        window._stay_put = True
        cur_pos = window.pos() + window._sprite_rect.topLeft()
        window._roam_tick()
        assert (window.pos() + window._sprite_rect.topLeft()) == cur_pos
    finally:
        window.stop_projection()
        window.close()
