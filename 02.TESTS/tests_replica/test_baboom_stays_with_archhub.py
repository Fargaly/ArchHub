"""ONEBABOOM: BABOOM is the character that comes with ArchHub, not a separate thing.

Founder, 2026-11-17: "Why is BABOOM still not merged with ArchHub, as if ArchHub is one
thing and BABOOM another ... like a pet or a companion: he is the one who runs everything
with you." Measured on his installed app that evening: the companion sat at [-1592, 946],
the bottom of his LEFT monitor, 131 x 86 px, while ArchHub was on the right one at
[240, 66, 1440 x 900], because a saved spot from an earlier drag outranked the app.

F277 (2026-11-06, "I want to see it all the time") still holds: with ArchHub minimised or in
the tray he stays on the desktop, as he did.

Every window here is on Qt's offscreen platform; the screens are plain rectangles.
"""
from __future__ import annotations

import html
import json
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEvent, QObject, QPoint, QPointF, Qt, QUrl
from PyQt6.QtGui import QColor, QImage, QMouseEvent, QPainter
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLineEdit, QPlainTextEdit, QTextEdit, QWidget

import nodelang.baboom_native_companion as native
from nodelang.baboom_companion_placement import Rect
from nodelang.baboom_native_companion import BaboomNativeCompanionController, create_baboom_native_companion_window
from nodelang.baboom_native_host import BaboomNativeHost
from nodelang.baboom_visual_assets import BaboomSpriteAtlas
from nodelang.nograph_server import JsonFile
from test_baboom_native_companion import _ScreenTransport, _sprite_points

LEFT, RIGHT = Rect(-1920, 0, 1920, 1040), Rect(0, 0, 1920, 1040)   # his two monitors' work areas
APP = Rect(240, 66, 1440, 900)                                     # ArchHub, on the right one
STALE = '{"x": -1592, "y": 954}'                                   # his baboom-position.json, as found


def _composer(app):
    """The composer strip along the bottom of the window, as the Studio page reports it."""
    return Rect(app.x + 280, app.bottom - 96, app.width - 320, 72)


def _stands(window):
    """Where the character is on the desktop (the window may also hold his bubble)."""
    box = window._sprite_rect
    return Rect(window.x() + box.x(), window.y() + box.y(), box.width(), box.height())


def _beside(app):
    # The design's place (archhub-directions .baboom): beside the rail, 76 px from the left, 16 px above the bottom.
    return Rect(app.x + 76, app.bottom - 16 - 87, 80, 87)


class _BrainUp(_ScreenTransport):
    """The app's frame while BABOOM's brain is up, as baboom_nograph.NoGraphTransport reports it."""

    def baboom_native_frame(self, **kwargs):
        frame = super().baboom_native_frame(**kwargs)
        frame["context"] = dict(frame["context"], brain={"ok": True, "facts": 1})
        return frame


def _with_archhub(tmp_path, *, saved=None, pinned=False, app_rect=APP, transport=None):
    """The companion as the launcher wires it: standing with an ArchHub window, the real pin setting file."""
    app = QApplication.instance() or QApplication([])
    image = QImage(1536, 2288, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    for row in range(11):
        for column in range(8):
            painter.fillRect(column * 192 + 48, row * 208 + 50, 96, 120, QColor(28, 187, 171, 255))
    painter.end()
    atlas_path = tmp_path / "atlas.png"
    assert image.save(str(atlas_path))
    atlas = BaboomSpriteAtlas(path=atlas_path, width=1536, height=2288, columns=8, rows=11, cell_width=192, cell_height=208)
    host = BaboomNativeHost(transport or _ScreenTransport(), external_session_id="with-archhub-court",
                            device_credential_provider=lambda challenge: {"proof": "approved"})
    host.connect()
    position_path = tmp_path / "baboom-position.json"
    if saved is not None:
        position_path.write_text(saved, encoding="utf-8")
    pin = JsonFile(tmp_path / "settings" / "companion.json", {"mode": "idle", "x": None, "y": None, "pinned": False})
    if pinned:
        pin.update({"pinned": True})
    owner = QWidget()
    owner.show()
    seen = SimpleNamespace(asked=[], opened=[], stolen=[])
    window = create_baboom_native_companion_window(
        BaboomNativeCompanionController(host, atlas, occupied_provider=lambda: ()),
        position_path=position_path, on_open=lambda: seen.opened.append("archhub"))
    # Anything that would take the keyboard from the program he is working in is recorded.
    window.activateWindow = lambda: seen.stolen.append("activate")
    window.raise_ = lambda: seen.stolen.append("raise")
    window.stand_with(owner, pin, lambda words="": seen.asked.append(words or "composer"))
    window.follow_app(app_rect, _composer(app_rect), (), (LEFT, RIGHT))
    window.start_projection()
    app.processEvents()
    return SimpleNamespace(app=app, window=window, owner=owner, pin=pin, position_path=position_path, seen=seen)


def _close(court):
    court.window.stop_projection()
    court.window.close()
    court.owner.close()
    court.window.deleteLater()
    court.app.processEvents()


def test_a_stale_spot_on_the_left_monitor_ends_beside_the_composer_on_the_right(tmp_path):
    """The measured fault: first start after the update, his saved file untouched, no step for him."""
    court = _with_archhub(tmp_path, saved=STALE)
    try:
        stood = _stands(court.window)
        assert court.window.isVisible()
        assert stood == _beside(APP), "BABOOM stands beside the rail at the design's place"
        assert (stood.width, stood.height) == (80, 87), "the website's figure at the website's size"
        assert stood.contained_by(RIGHT) and stood.contained_by(APP)
        assert stood.intersection_area(_composer(APP)) == 0, "never on the composer's controls"
        assert court.position_path.read_text(encoding="utf-8") == STALE, "his file is left exactly as it was"
        assert court.pin.read()["pinned"] is False
    finally:
        _close(court)


def test_baboom_goes_where_the_archhub_window_goes(tmp_path):
    court = _with_archhub(tmp_path)
    window = court.window
    try:
        projections = []
        project = window.refresh
        window.refresh = lambda: (projections.append(1), project())[1]
        for app in (Rect(340, 106, 1440, 900),        # moved
                    Rect(340, 106, 1009, 700),        # snapped to half a screen
                    Rect(-1800, 80, 1440, 900),       # dragged to the other monitor
                    Rect(1200, 200, 1440, 900)):      # hanging off the right edge of the screen
            window.follow_app(app, _composer(app), (), (LEFT, RIGHT))
            stood = _stands(window)
            screen = LEFT if app.x < 0 else RIGHT
            assert stood.contained_by(screen), (app, stood)
            assert stood.intersection_area(_composer(app)) == 0 and stood.x >= app.x, (app, stood)
            if _beside(app).contained_by(screen):
                assert stood == _beside(app), app
        assert projections == [], "a move goes along at once, with no projection per step of a drag"
        # A control where he would stand (the canvas zoom control): he steps off it, by 48 px at most.
        zoom_control = Rect(_beside(APP).x + 10, _beside(APP).bottom - 30, 60, 28)
        window.follow_app(APP, _composer(APP), (zoom_control,), (LEFT, RIGHT))
        stood = _stands(window)
        assert stood.intersection_area(zoom_control) == 0
        assert abs(stood.x - _beside(APP).x) <= 48 and abs(stood.y - _beside(APP).y) <= 48
    finally:
        _close(court)


def test_baboom_stays_on_the_desktop_when_archhub_is_minimised_or_in_the_tray(tmp_path):
    """F277 holds ("I want to see it all the time"): a pet stays on the desktop when its window is put away.

    He waits small in the bottom right corner of the work area of the monitor ArchHub was last on, on top as
    before, takes no focus and does not move by himself; a click brings ArchHub back with the composer on him.
    """
    court = _with_archhub(tmp_path, saved=STALE)
    window = court.window
    try:
        for app, screen in ((APP, RIGHT), (Rect(-1800, 80, 1440, 900), LEFT)):
            window.follow_app(app, _composer(app), (), (LEFT, RIGHT))
            window.follow_app(None, None, (), (LEFT, RIGHT))        # minimised, or closed to the tray
            court.app.processEvents()
            waits = _stands(window)
            assert window.isVisible(), "BABOOM stays on screen"
            assert (waits.width, waits.height) == (56, 56), "small, as before"
            assert (waits.right, waits.bottom) == (screen.right, screen.bottom), "the corner of the screen ArchHub was on"
            assert window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint, "the desktop companion F277 had"
            assert window.windowHandle().transientParent() is None
            for _ in range(3):
                window.refresh()
                court.app.processEvents()
                assert _stands(window) == waits, "he does not move by himself while he works elsewhere"
        _transparent, opaque = _sprite_points(window)
        QTest.mouseClick(window, Qt.MouseButton.LeftButton, pos=opaque)
        QTest.qWait(window._quiet_click.interval() + 80)
        assert court.seen.asked == ["composer"], "a click brings ArchHub back with its composer on BABOOM"
        window.follow_app(APP, _composer(APP), (), (LEFT, RIGHT))    # ArchHub is shown again
        court.app.processEvents()
        assert window.isVisible() and _stands(window) == _beside(APP)
        assert not window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
        assert window.windowHandle().transientParent() is court.owner.windowHandle()
        assert court.seen.stolen == [], "none of it took the keyboard or raised him over his work"
        assert court.position_path.read_text(encoding="utf-8") == STALE
    finally:
        _close(court)


def test_baboom_never_takes_the_keyboard_or_the_top_of_the_window_stack(tmp_path):
    court = _with_archhub(tmp_path)
    window = court.window
    try:
        assert not window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint, "not above his other programs"
        assert window.windowHandle().transientParent() is court.owner.windowHandle(), "ArchHub's own place in the stack"
        assert window.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        for app in (Rect(300, 90, 1440, 900), None, APP):
            window.follow_app(app, app and _composer(app), (), (LEFT, RIGHT))
            window.refresh()
            court.app.processEvents()
        assert court.seen.stolen == []
        assert window.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    finally:
        _close(court)


def test_a_spot_of_his_own_holds_only_while_pinned_on_a_screen_and_archhub_stays_shown(tmp_path):
    court = _with_archhub(tmp_path, saved=STALE, pinned=True)
    window = court.window
    try:
        stood = _stands(window)
        assert stood.contained_by(LEFT) and stood.x == -1592, "un-pinned from ArchHub, his spot is kept"
        window.follow_app(Rect(340, 106, 1440, 900), _composer(Rect(340, 106, 1440, 900)), (), (LEFT, RIGHT))
        assert _stands(window) == stood, "ArchHub moving does not drag a pinned BABOOM along"
        window.follow_app(None, None, (), (LEFT, RIGHT))
        court.app.processEvents()
        assert window.isVisible() and _stands(window).contained_by(LEFT), "ArchHub put away: still on his spot"
        window.follow_app(APP, _composer(APP), (), (LEFT, RIGHT))     # ArchHub is shown again
        court.app.processEvents()
        assert _stands(window) == _beside(APP), "shown again, he is home"
        assert court.pin.read()["pinned"] is False
    finally:
        _close(court)


def test_a_pinned_spot_on_no_screen_comes_home(tmp_path):
    """The monitor his spot was on is gone: never stranded where no screen shows him."""
    court = _with_archhub(tmp_path, saved='{"x": 5000, "y": 5000}', pinned=True)
    try:
        assert _stands(court.window) == _beside(APP)
        assert court.pin.read()["pinned"] is False
        assert json.loads(court.position_path.read_text(encoding="utf-8")) == {"x": 5000, "y": 5000}
    finally:
        _close(court)


def _drag(court, by):
    window = court.window
    _transparent, opaque = _sprite_points(window)
    held = Qt.MouseButton.LeftButton
    for kind, point in ((QEvent.Type.MouseButtonPress, opaque), (QEvent.Type.MouseMove, opaque + by),
                        (QEvent.Type.MouseButtonRelease, opaque + by)):
        court.app.sendEvent(window, QMouseEvent(kind, QPointF(point), QPointF(window.mapToGlobal(point)),
                                                held, held, Qt.KeyboardModifier.NoModifier))
    court.app.processEvents()
    window._position_jobs.submit(lambda: None).result(timeout=4)


def test_a_drag_springs_home_unless_he_unpinned_baboom_from_archhub(tmp_path):
    court = _with_archhub(tmp_path)
    try:
        _drag(court, QPoint(-300, -200))
        assert _stands(court.window) == _beside(APP), "with ArchHub a stray drag does not strand him"
        assert not court.position_path.exists()
        court.pin.update({"pinned": True})          # the existing companion setting, turned on
        court.window.refresh()
        _drag(court, QPoint(-300, -200))
        saved = json.loads(court.position_path.read_text(encoding="utf-8"))
        assert saved["x"] == _beside(APP).x - 300
        assert _stands(court.window) != _beside(APP) and _stands(court.window).contained_by(RIGHT)
    finally:
        _close(court)


def test_a_click_points_the_one_composer_at_baboom_and_opens_no_second_input(tmp_path):
    court = _with_archhub(tmp_path)
    window = court.window
    try:
        _transparent, opaque = _sprite_points(window)
        QTest.mouseClick(window, Qt.MouseButton.LeftButton, pos=opaque)
        QTest.qWait(window._quiet_click.interval() + 80)
        court.app.processEvents()
        assert court.seen.asked == ["composer"]
        assert not window.findChildren((QLineEdit, QTextEdit, QPlainTextEdit)), "no input row of his own, shown or hidden"
        assert not window._report.isVisible()
        assert court.seen.opened == []
        QTest.mouseDClick(window, Qt.MouseButton.LeftButton, pos=opaque)
        QTest.qWait(window._quiet_click.interval() + 80)
        court.app.processEvents()
        assert court.seen.opened == ["archhub"] and court.seen.asked == ["composer"]
    finally:
        _close(court)


def test_baboom_greets_once_a_visit_and_never_again(tmp_path, monkeypatch):
    monkeypatch.setitem(native.GREETING_NODE["params"], "after_ms", 30)
    monkeypatch.setitem(native.GREETING_NODE["params"], "for_ms", 400)
    now = 10.0
    monkeypatch.setattr(native, "time", SimpleNamespace(
        monotonic=lambda: now, time=native.time.time, localtime=native.time.localtime))
    court = _with_archhub(tmp_path)
    window = court.window
    try:
        assert _stands(window) == _beside(APP)
        assert not window._state_bubble.isVisible(), "the greeting waits after arrival"
        now += 0.120
        window.refresh()
        assert window._state_bubble.isVisible()
        assert window._state_bubble.text() == html.escape(native.GREETING_NODE["params"]["text"])
        assert window._frame.motion == "wave" or window._transition_left > 0
        assert _stands(window) == _beside(APP), "the bubble opens beside him; he does not move for it"
        now += 0.450
        window.refresh()
        assert not window._state_bubble.isVisible(), "it goes by itself"
        window.follow_app(None, None, (), (LEFT, RIGHT))
        window.follow_app(APP, _composer(APP), (), (LEFT, RIGHT))
        now += 0.120
        window.refresh()
        assert not window._state_bubble.isVisible(), "one greeting a visit, never repeated"
        assert court.seen.stolen == []
    finally:
        _close(court)


def test_asking_baboom_goes_to_the_one_composer_and_no_reshow_takes_the_keyboard(tmp_path):
    """Ask BABOOM (the tray line, a line of his menu) goes to ArchHub's composer: he never turns activation on.

    ArchHub put away or restored hides and re-shows BABOOM. That re-show is for ArchHub's sake, so it must
    not activate either: he may be typing in another program.
    """
    court = _with_archhub(tmp_path)
    window = court.window
    try:
        window._open_interaction()                      # the tray's "Ask BABOOM"
        window._prefill("remember: ")                   # a line of his menu he finishes in his own words
        court.app.processEvents()
        assert court.seen.asked == ["composer", "remember: "], "the one composer, starting with the line's words"
        assert window.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        shows = []
        show = window.show
        window.show = lambda: (shows.append(window.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)), show())[1]
        window.follow_app(None, None, (), (LEFT, RIGHT))                  # ArchHub minimised
        court.app.processEvents()
        window.follow_app(APP, _composer(APP), (), (LEFT, RIGHT))         # and restored
        court.app.processEvents()
        assert shows and all(shows), "every re-show was without activation"
        assert window.isVisible()
        assert court.seen.stolen == []
    finally:
        _close(court)


def _clock(monkeypatch):
    """The companion's clock, held by the test: his float and pulses are read off it, never off a sleep.

    Windows' "Show animations" reads as on, whatever this machine is set to.
    """
    now = [0.0]
    monkeypatch.setattr("nodelang.baboom_work_presence.windows_show_animations", lambda: True)
    monkeypatch.setattr(native, "time", SimpleNamespace(
        monotonic=lambda: now[0], time=native.time.time, localtime=native.time.localtime))
    return now


def _drawn(window, point):
    """The pixel he is drawn with at this spot of his box right now (the box floats; the spot floats with it)."""
    window._advance_look()
    return window.grab().toImage().pixelColor(point + QPoint(0, window._look_phase()["float"]))


def _is(colour, token, strength):
    """This drawn pixel is the THEME colour (black for None) at this strength."""
    wanted = QColor(native.THEME[token]) if token else QColor(0, 0, 0)
    return (abs(colour.alphaF() - strength) <= 0.04
            and all(abs(a - b) <= 6 for a, b in zip(colour.getRgb()[:3], wanted.getRgb()[:3])))


def test_the_ground_under_baboom_is_his_state_and_the_badge_is_homes_own_count(tmp_path, monkeypatch):
    """Design row 20: rest, listening (cyan), working (accent, 1.4 s pulse), needs you (warn, 0.9 s pulse, count).

    Every state is read from the app: the page's own count of what needs him and his open panel (follow_app,
    as window_commands reports them), and the Workshop rows the companion already reads. None is a constant.
    """
    now = _clock(monkeypatch)
    court = _with_archhub(tmp_path)
    window, look = court.window, native.LOOK_NODE["params"]
    badge = window._state_badge
    ground = lambda: _drawn(window, window._look_rects()[0].center())
    try:
        window._greeting = False
        window.refresh()
        assert window._look == "rest" and _is(ground(), None, 0.45), "rest: the neutral shadow"
        assert not badge.isVisible()

        window.follow_app(APP, _composer(APP), (), (LEFT, RIGHT), 0, True)       # the page: his panel is open
        assert window._look == "listening" and _is(ground(), "cyan", 0.75)

        window.follow_app(APP, _composer(APP), (), (LEFT, RIGHT), 0, False)
        window._work_rows = lambda: [{"id": "t1", "status": "WIP", "title": "Index the sheets"}]   # an agent works
        window.refresh()
        assert window._look == "working" and _is(ground(), "accent", 0.7)
        now[0] = 0.7                                                             # half of the 1.4 s pulse
        assert look["pulse_ms"]["working"] == 1400 and _is(ground(), "accent", 0.7 * 0.45)

        now[0] = 0.0
        window.follow_app(APP, _composer(APP), (), (LEFT, RIGHT), 3, False)      # Home counts three that need him
        assert window._look == "needs" and _is(ground(), "warn", 0.8), "what needs him outranks the work"
        now[0] = 0.45                                                            # half of the 0.9 s pulse
        assert look["pulse_ms"]["needs"] == 900 and _is(ground(), "warn", 0.8 * 0.45)
        now[0] = 0.0
        window._advance_look()
        box, ring = window._sprite_rect, look["badge_ring_px"]
        assert badge.isVisible() and badge.text() == "3"
        assert badge.accessibleName() == "BABOOM needs you (3)"
        assert (badge.width() - 2 * ring, badge.height() - 2 * ring) == (18, 18)
        assert badge.y() + ring == box.y() + box.height() - 100 + 4, "4 px from the top of his 80 x 100 box"
        assert badge.x() + badge.width() - ring == box.x() + box.width() - 6, "6 px from its right"
        assert native.THEME["warn"] in badge.styleSheet()

        window._work_rows = lambda: []
        window.follow_app(APP, _composer(APP), (), (LEFT, RIGHT), 0, False)
        assert window._look == "rest" and not badge.isVisible(), "nothing waits: no badge, no glow"
        assert badge.accessibleName() == "BABOOM needs you"
        assert _stands(window) == _beside(APP), "he stood where he stands through every state"
        assert court.seen.stolen == []
    finally:
        _close(court)


def test_baboom_floats_three_pixels_and_carries_the_live_dot_while_he_can_answer(tmp_path, monkeypatch):
    """Design row 20: the 8 px cyan live dot with its 2 s pulse, the 3 px 3.6 s float, in the 80 x 100 box."""
    now = _clock(monkeypatch)
    court = _with_archhub(tmp_path, transport=_BrainUp())
    window, look = court.window, native.LOOK_NODE["params"]
    try:
        window._greeting = False
        window.refresh()
        box, (ground, dot) = window._sprite_rect, window._look_rects()
        foot = box.y() + box.height()
        # His box: 80 x 100 with the figure at its foot; the 46 x 9 glow is centred and reaches 2 px under his feet.
        assert (window.width(), window.height(), box.y()) == (80, 100 + 2, 100 - 87)
        assert (ground.width(), ground.height(), ground.y() + ground.height()) == (46, 9, foot + 2)
        assert ground.x() - box.x() == box.x() + box.width() - (ground.x() + ground.width())
        frame = window.geometry()
        assert _stands(window) == _beside(APP), "at the design place"
        assert Rect(frame.x(), frame.y(), frame.width(), frame.height()).intersection_area(_composer(APP)) == 0, "clear of the composer"

        # The live dot: 8 px, cyan, 10 px from the top and 8 px from the right of his box.
        assert window._dot_shown(), "his brain is up and his panel is closed"
        centre = dot.center()
        assert _is(_drawn(window, centre), "cyan", 1.0)
        image = window.grab().toImage()
        across = [x for x in range(dot.left(), dot.right() + 1) if image.pixelColor(x, centre.y()).alphaF() > 0.5]
        assert len(across) == look["dot_px"] == 8
        assert (across[0], across[-1] + 1) == (box.x() + box.width() - 8 - 8, box.x() + box.width() - 8)
        down = [y for y in range(dot.top(), dot.bottom() + 1) if image.pixelColor(centre.x(), y).alphaF() > 0.5]
        assert down[0] == foot - 100 + 10
        # Its ring grows to 6 px and fades over 70 % of 2 s, then returns.
        assert look["dot_pulse_ms"] == 2000
        assert [native.baboom_look_phase(ms, "rest")["ring_px"] for ms in (0, 1400, 2000)] == [0, 6, 0]
        now[0] = 0.7
        assert 0.2 < _drawn(window, centre + QPoint(6, 0)).alphaF() < 0.4, "the ring, half grown, half faded"

        # The float: 3 px up and back in 3.6 s, read off the clock; the badge and the dot ride with him.
        floats = [native.baboom_look_phase(ms, "rest")["float"] for ms in range(0, 3601, 100)]
        assert (min(floats), max(floats), floats[0], floats[-1], floats[18]) == (-3, 0, 0, 0, -3)
        column = box.x() + box.width() // 2
        top = lambda picture: next(y for y in range(picture.height()) if picture.pixelColor(column, y).alpha() == 255)
        now[0] = 0.0
        window._advance_look()
        standing = top(window.grab().toImage())
        now[0] = 1.8
        window._advance_look()
        assert standing - top(window.grab().toImage()) == look["float_px"] == 3
        assert _stands(window) == _beside(APP), "the float is drawn; where he stands does not change"
        mask = window.mask()
        assert mask.contains(ground.center()) and mask.contains(centre) and mask.contains(QPoint(column, standing - 3)), \
            "the glow, the dot and the reach of his float are inside what the window shows"

        # It runs on the companion's own Qt timer, and not at all when motion is reduced or ArchHub is away.
        assert window._look_timer.isActive() and window._look_timer.interval() == look["frame_ms"]
        assert look["frame_ms"] >= 200, "decorative motion needs at most five ticks per second"
        dirty = []
        with monkeypatch.context() as motion:
            motion.setattr(window, "update", lambda *rects: dirty.append(rects))
            now[0] = 1.81   # same integer sprite position, only the live dot changed
            window._advance_look()
        assert dirty == [(dot.translated(0, -3),)]
        window._reduced_motion = True
        window.refresh()
        assert not window._look_timer.isActive() and window._look == "rest"
        assert window._look_phase()["float"] == 0, "reduced motion: his state, drawn still"
        window._reduced_motion = None
        window.follow_app(APP, _composer(APP), (), (LEFT, RIGHT), 0, True)      # his panel is open
        assert not window._dot_shown(), "the dot hides while his panel is open"
        window.follow_app(None, None, (), (LEFT, RIGHT))                        # ArchHub put away
        court.app.processEvents()
        assert window._look is None and not window._look_timer.isActive()
        assert (window.width(), window.height()) == (56, 56), "the small desktop glyph is as it was"
    finally:
        _close(court)


def test_the_dot_stays_off_while_his_brain_is_not_answering(tmp_path):
    """No brain state in the app's frame: he does not claim he can answer."""
    court = _with_archhub(tmp_path)
    try:
        assert court.window._look == "rest" and not court.window._dot_shown()
    finally:
        _close(court)


def test_a_broken_companion_setting_never_costs_him_baboom(tmp_path, monkeypatch):
    """settings/companion.json malformed at start or mid-run, or not writable: BABOOM stands, nothing is raised."""
    (tmp_path / "settings").mkdir()
    (tmp_path / "settings" / "companion.json").write_text("{not json", encoding="utf-8")
    court = _with_archhub(tmp_path, saved=STALE)        # malformed at start
    window = court.window
    try:
        assert window.isVisible() and _stands(window) == _beside(APP), "broken reads as not pinned: home"
        court.pin.path.write_text('["a list, not a setting"]', encoding="utf-8")   # broken another way, mid-run
        for _ in range(3):
            window.refresh()
        assert window.isVisible() and _stands(window) == _beside(APP)
        # Pinned to a spot on no screen, and the file cannot be written: he still comes home.
        court.pin.path.write_text('{"pinned": true}', encoding="utf-8")
        native_origin = window.controller
        native_origin.pin_sprite_origin(5000, 5000)

        def locked(_changes):
            raise PermissionError("settings file is locked")
        monkeypatch.setattr(court.pin, "update", locked)
        window.refresh()
        assert window.isVisible() and _stands(window) == _beside(APP)
    finally:
        _close(court)


def test_the_follower_tells_baboom_of_every_move_hide_and_page_report(tmp_path):
    """window_commands.CompanionFollows: the real window events and the Studio page's report, as desktop rectangles."""
    from nodelang.window_commands import CompanionFollows, WindowCommands
    app = QApplication.instance() or QApplication([])
    window = QWidget()
    window.setGeometry(240, 66, 1440, 900)
    window.show()
    app.processEvents()
    page = QObject()

    def commands(path):
        view = SimpleNamespace(page=lambda: page, url=lambda: QUrl("http://127.0.0.1:1234" + path),
                               urlChanged=SimpleNamespace(connect=lambda _f: None),
                               mapToGlobal=window.mapToGlobal, zoomFactor=lambda: 1.25)
        return view, WindowCommands(view, window, lambda: None, "http://127.0.0.1:1234")

    view, studio = commands("/studio")
    told = []
    companion = SimpleNamespace(follow_app=lambda *state: told.append(state), isVisible=lambda: False)
    follows = CompanionFollows(window, view, studio, companion)
    try:
        frame = window.geometry()
        here = Rect(frame.x(), frame.y(), frame.width(), frame.height())
        assert told[-1][0] == here and told[-1][1] is None, "before the page reports: the window alone"
        assert told[-1][3], "the screens' work areas come along"
        # The page reports in its own pixels; a malformed box is dropped, never trusted.
        studio.companionHome([400.0, 600.0, 640.0, 60.0], [[900.0, 500.0, 40.0, 40.0], ["x", 1, 2, 3], [1.0, 2.0, 3.0]])
        assert told[-1][1] == Rect(here.x + 500, here.y + 750, 800, 75), "page pixels times the page zoom, from the window's corner"
        assert told[-1][2] == [Rect(here.x + 1125, here.y + 625, 50, 50)]
        assert told[-1][4:] == (0, False), "before the page counts: nothing needs him, his panel is closed"
        studio.companionSees(3, True)
        assert told[-1][4:] == (3, True), "Home's own count of what needs him and his open panel come along"
        window.move(300, 100)
        app.processEvents()
        assert (told[-1][0].x, told[-1][0].y) == (window.geometry().x(), window.geometry().y()) != (here.x, here.y)
        window.showMinimized()
        app.processEvents()
        assert told[-1][:3] == (None, None, ()) and told[-1][3], "minimised: he is told, with the screens to wait on"
        window.showNormal()
        app.processEvents()
        assert told[-1][0] is not None
        window.hide()
        app.processEvents()
        assert told[-1][:3] == (None, None, ()) and told[-1][3], "hidden to the tray: the same"
        # Another page in the same view cannot move him.
        before = len(told)
        commands("/elsewhere")[1].companionHome([1.0, 1.0, 10.0, 10.0], [])
        commands("/elsewhere")[1].companionSees(9, True)
        assert len(told) == before
    finally:
        del follows
        window.close()
