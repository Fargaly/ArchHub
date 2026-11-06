"""Independent PRESENCE1 acceptance: isolated widgets, disposable graph, no desktop.

F277 supersedes the old activity-hides-presence rule (founder, 2026-11-06):
"هو بابوم مش ستيبل ليه وعمال يختفي أنا عاوز أشوفه طول الوقت"
(BABOOM must be visible all the time).

Win32 adapter assertions use a fake user32. These are deliberately not evidence
of a real Windows notification area, HWND hit testing, or foreground scheduling.
"""
import os
import time
from types import SimpleNamespace

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import pytest
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QColor, QCursor
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QWidget

import nodelang.baboom_native_companion as companion
from nodelang.baboom_companion_placement import Rect
from nodelang.baboom_native_host import BaboomNativeHost
from nodelang.baboom_native_runtime import default_baboom_sprite_atlas_path
from nodelang.baboom_visual_assets import BaboomSpriteAtlas
from tests_replica.test_baboom_native_companion import _Transport


class PresenceTransport(_Transport):
    mode = "Tray"

    def baboom_native_frame(self, **kwargs):
        frame = super().baboom_native_frame(**kwargs)
        frame["context"]["shows_as"] = self.mode
        return frame


@pytest.fixture
def presence(monkeypatch):
    app = QApplication.instance() or QApplication([])
    environment = {"idle": 10.0, "foreign": False, "occupied": []}
    calls = []
    # showEvent's native disown/DWM adapters also remain inside the fake world.
    monkeypatch.setattr(companion.ctypes, "windll", SimpleNamespace(), raising=False)
    monkeypatch.setattr(companion, "desktop_input_idle_seconds", lambda: environment["idle"])
    monkeypatch.setattr(companion, "foreign_foreground_window", lambda: environment["foreign"])
    monkeypatch.setattr(companion, "foreground_app_windows", lambda: None)
    monkeypatch.setattr(companion, "set_native_click_through", lambda handle, idle: calls.append((handle, idle)))
    monkeypatch.setattr(QCursor, "pos", lambda: QPoint(-10000, -10000))
    transport = PresenceTransport()
    host = BaboomNativeHost(transport, external_session_id="presence-review-isolated",
                            device_credential_provider=lambda challenge: {"proof": "test"})
    host.connect()
    atlas = BaboomSpriteAtlas(path=default_baboom_sprite_atlas_path(), width=1536,
                             height=2288, columns=8, rows=11, cell_width=192, cell_height=208)
    controller = companion.BaboomNativeCompanionController(
        host, atlas, occupied_provider=lambda: environment["occupied"])
    opened = []
    window = companion.create_baboom_native_companion_window(controller, on_open=lambda: opened.append(True))
    window._screen_rect = lambda: Rect(0, 0, 1280, 800)
    state = SimpleNamespace(app=app, host=host, window=window, transport=transport,
                            controller=controller, environment=environment, calls=calls, opened=opened)

    def refresh(mode=None):
        if mode is not None:
            transport.mode = mode
            host.poll()
        window.refresh()
        app.processEvents()

    state.refresh = refresh
    yield state
    window.stop_projection()
    window.hide()
    window.close()
    host.stop(timeout_seconds=.01)


@pytest.mark.parametrize("mode", ["Tray", "Hidden", "invalid"])
def test_background_modes_never_surface_on_report_or_reconnect(presence, mode):
    p = presence
    p.window.start_projection()
    p.refresh(mode)
    for connection in ("live", "reconnecting", "closed", "live"):
        p.host.connection_state = connection
        p.refresh()
        assert not p.window.isVisible()
        assert not p.window._report.isVisible()
        assert not hasattr(p.window, "_open")
        assert p.window._tray.isVisible() == (mode != "Hidden")
        assert not p.window._details_open


def test_screen_is_bounded_edge_docked_and_idle_clickthrough(presence):
    p = presence
    p.window.start_projection()
    p.refresh("Screen")
    bounds = p.window.geometry()
    assert p.window.isVisible()
    assert (bounds.x(), bounds.y(), bounds.width(), bounds.height()) == (1224, 744, 56, 56)
    assert p.calls[-1][1] is False
    assert p.window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert not p.window._report.isVisible()
    p.controller.pin_sprite_origin(4, 320)
    p.refresh()
    assert p.window.x() == 0 and p.window.y() == 320
    p.controller.pin_sprite_origin(400, 7)
    p.refresh()
    assert p.window.x() == 400 and p.window.y() == 0


@pytest.mark.parametrize("occupied", [[Rect(0, 0, 300, 300)], [Rect(-8, -8, 1296, 816)]])
def test_active_foreign_app_keeps_screen_visible_for_many_ticks(presence, monkeypatch, occupied):
    p = presence
    p.window.start_projection()
    p.refresh("Screen")
    assert p.window.isVisible()
    p.environment.update(idle=0.0, foreign=True, occupied=occupied)
    foreground = QWidget()
    foreground.show()
    QApplication.setActiveWindow(foreground)
    p.app.processEvents()
    activations = []
    monkeypatch.setattr(p.window, "activateWindow", lambda: activations.append(True))
    for _ in range(40):
        p.refresh()
        assert p.window.isVisible()
        assert p.window._projection_timer.isActive()
        assert p.window.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        assert not p.window.isActiveWindow()
    assert activations == []
    foreground.close()


def test_details_are_explicit_topmost_and_close_to_tray(presence):
    p = presence
    p.window.start_projection()
    assert not p.window.isVisible()
    p.window._tray.activated.emit(QSystemTrayIcon.ActivationReason.Trigger)
    p.app.processEvents()
    assert p.window._details_open and p.window.isVisible()
    assert p.window._input.isVisible()
    assert p.window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert p.calls[-1][1] is False
    for state in ("reconnecting", "closed"):
        p.host.connection_state = state
        p.refresh()
        assert not hasattr(p.window, "_open")
        assert "reconnect" not in p.window._report.text().lower()
    p.window._close_interaction()
    assert not p.window.isVisible() and not p.window._details_open
    assert p.window._tray.isVisible()
    p.window._tray_open.trigger()
    assert p.opened == [True]
    assert not p.window.isVisible()


def test_hidden_closes_previously_open_details(presence):
    p = presence
    p.window.start_projection()
    p.window._tray.activated.emit(QSystemTrayIcon.ActivationReason.Trigger)
    assert p.window.isVisible()
    p.refresh("Hidden")
    assert not p.window.isVisible()
    assert not p.window._tray.isVisible()
    assert not p.window._details_open


def test_outage_is_dot_tooltip_then_one_menu_line_at_five_minutes(presence, monkeypatch):
    p = presence
    p.window.start_projection()
    p.host.connection_state = "reconnecting"
    started = time.monotonic()
    monkeypatch.setattr(companion.time, "monotonic", lambda: started)
    p.refresh()
    assert "Reconnecting" in p.window._tray.toolTip()
    icon = p.window._tray.icon().pixmap(32, 32).toImage()
    assert icon.pixelColor(27, 27) == QColor(p.window._theme["warn"])
    assert p.window._tray_open.text() == "Open ArchHub"
    monkeypatch.setattr(companion.time, "monotonic", lambda: started + 299)
    p.refresh()
    assert p.window._tray_open.text() == "Open ArchHub"
    monkeypatch.setattr(companion.time, "monotonic", lambda: started + 301)
    p.refresh()
    assert [a.text() for a in p.window._tray_menu.actions()].count("ArchHub is closed · Open") == 1
    assert not p.window.isVisible() and not hasattr(p.window, "_open")
    p.host.poll()
    p.refresh()
    assert p.window._tray_open.text() == "Open ArchHub"


def test_idle_native_style_preserves_other_bits_and_clears_for_interaction(monkeypatch):
    style = [0x80000 | 0x80]

    def get_style(handle, index):
        assert handle.value == 123 and index == -20
        return style[0]

    def set_style(handle, index, value):
        assert handle.value == 123 and index == -20
        style[0] = value

    fake = SimpleNamespace(GetWindowLongW=get_style, SetWindowLongW=set_style)
    monkeypatch.setattr(companion.ctypes, "windll", SimpleNamespace(user32=fake), raising=False)
    companion.set_native_click_through(123, True)
    assert style[0] == (0x80000 | 0x80 | 0x20)
    companion.set_native_click_through(123, False)
    assert style[0] == (0x80000 | 0x80)


@pytest.mark.parametrize("mode", ["Screen", "Tray", "Hidden"])
def test_shows_as_file_owner_preserves_mode_and_startup_across_reload(tmp_path, mode):
    from nodelang.baboom_nograph import shows_as_choice, startup_choice
    from nodelang.nograph_server import JsonFile

    path = tmp_path / "settings" / "baboom.json"
    owner = JsonFile(path, {})
    owner.update({"startup": "off", "shows_as": mode})
    assert shows_as_choice(tmp_path) == mode
    assert startup_choice(tmp_path) == "off"
    reopened = JsonFile(path, {})
    assert reopened.read() == {"startup": "off", "shows_as": mode}
    reopened.update({"startup": "on"})
    assert shows_as_choice(tmp_path) == mode
    assert startup_choice(tmp_path) == "on"


@pytest.mark.parametrize("raw", ['{}', '{"shows_as":"invalid"}', 'invalid json'])
def test_unavailable_or_invalid_mode_defaults_to_visible_screen(tmp_path, raw):
    from nodelang.baboom_nograph import shows_as_choice

    path = tmp_path / "settings" / "baboom.json"
    assert shows_as_choice(tmp_path) == "Screen"
    path.parent.mkdir()
    path.write_text(raw, encoding="utf-8")
    assert shows_as_choice(tmp_path) == "Screen"


def test_maximized_foreign_foreground_is_visible_without_a_break(presence):
    p = presence
    p.environment.update(idle=0.0, foreign=True, occupied=[Rect(-8, -8, 1296, 816)])
    p.window.start_projection()
    p.refresh("Screen")
    assert p.window.isVisible()
    p.environment["idle"] = 2.1
    p.refresh()
    assert p.window.isVisible(), "maximized foreground must not suppress an idle Screen sprite"
    assert p.window._projection_timer.isActive()


def test_approaching_and_hovering_sprite_does_not_hide_it(presence, monkeypatch):
    p = presence
    p.window.start_projection()
    p.refresh("Screen")
    bounds = p.window.geometry()
    clock = [time.monotonic()]
    monkeypatch.setattr(companion.time, "monotonic", lambda: clock[0])
    p.environment.update(idle=0.0, foreign=True)
    for point in (QPoint(bounds.left() - 16, bounds.center().y()), bounds.center()):
        monkeypatch.setattr(QCursor, "pos", lambda: point)
        p.refresh()
        assert p.window.isVisible(), "approaching or hovering must keep the sprite reachable"
        clock[0] += .75
    p.refresh()
    assert p.calls[-1][1] is False, "hover must allow click without waiting for global input idle"
    from PyQt6.QtTest import QTest
    from tests_replica.test_baboom_native_companion import _sprite_points
    _, opaque = _sprite_points(p.window)
    QTest.mouseClick(p.window, Qt.MouseButton.LeftButton, pos=opaque)
    QTest.qWait(p.window._quiet_click.interval() + 50)
    assert p.window._input.isVisible()
    assert p.opened == []


def test_removed_face_offer_and_floating_button_have_no_widget_state(presence):
    p = presence
    p.window.start_projection()
    p.refresh("Screen")
    for field in ("_open", "_face_offer", "_face_showing"):
        assert not hasattr(p.window, field), field


def test_redundant_import_and_presence_argument_are_removed():
    import ast
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    tree = ast.parse((root / "01.APP/nodelang/universal_application.py").read_text(encoding="utf-8"))
    assert not any(isinstance(node, ast.ImportFrom) and node.module == "builtins"
                   and any(alias.name == "UnicodeDecodeError" for alias in node.names)
                   for node in tree.body)
    source = (root / "01.APP/nodelang/studio/studio-existing-workshop.js").read_text(encoding="utf-8")
    call = source.split("setBaboomShowsAs: mode => changeTheme(", 1)[1].split(")", 1)[0]
    assert call.split(",") == ["'baboom-presence'", " null", " mode"]


def test_screen_starts_and_stays_visible_under_active_pointer(presence, monkeypatch):
    p = presence
    point = [QPoint(1250, 770)]
    monkeypatch.setattr(QCursor, "pos", lambda: point[0])
    p.environment.update(idle=0.0, foreign=True)
    p.window.start_projection()
    p.refresh("Screen")
    for _ in range(3):
        p.refresh()
        assert p.window.isVisible()
    point[0] = QPoint(-10000, -10000)
    p.environment["idle"] = 2.1
    p.refresh()
    assert p.window.isVisible()
    point[0] = QPoint(p.window.x() - 16, p.window.geometry().center().y())
    p.environment["idle"] = 0.0
    p.refresh()
    assert p.window.isVisible()
    point[0] = QPoint(-10000, -10000)
    p.refresh()
    assert p.window.isVisible()


def test_tray_keeps_polling_and_recovers_to_screen(presence):
    p = presence
    p.window.start_projection()
    for _ in range(4):
        p.refresh("Tray")
        assert not p.window.isVisible()
        assert p.window._projection_timer.isActive()
    p.refresh("Screen")
    assert p.window.isVisible()


def test_incidental_hide_keeps_polling_and_recovers(presence):
    p = presence
    p.window.start_projection()
    p.refresh("Screen")
    p.window.hide()
    assert p.window._projection_timer.isActive()
    p.refresh()
    assert p.window.isVisible()


@pytest.mark.parametrize("missing_snapshot", [False, True])
def test_missing_frames_keep_last_sprite_and_polling(presence, monkeypatch, missing_snapshot):
    p = presence
    p.window.start_projection()
    p.refresh("Screen")
    sprite = p.window._sprite
    monkeypatch.setattr(p.controller, "next_frame", lambda screen: None)
    if missing_snapshot:
        monkeypatch.setattr(p.host, "_latest", None)
    for _ in range(4):
        p.refresh()
        assert p.window.isVisible()
        assert p.window._sprite == sprite
        assert p.window._projection_timer.isActive()


def test_missing_initial_frame_recovers_on_next_projection(presence, monkeypatch):
    p = presence
    next_frame = p.controller.next_frame
    monkeypatch.setattr(p.controller, "next_frame", lambda screen: None)
    p.window.start_projection()
    assert p.window._projection_timer.isActive()
    monkeypatch.setattr(p.controller, "next_frame", next_frame)
    p.refresh("Screen")
    assert p.window.isVisible()


@pytest.mark.parametrize("action", ["hide_until_next_launch", "stop_baboom"])
def test_explicit_hide_or_stop_stays_hidden_and_stops_timers(presence, action):
    p = presence
    p.window.start_projection()
    p.refresh("Screen")
    getattr(p.window, action)()
    for _ in range(4):
        p.refresh()
        assert not p.window.isVisible()
        assert not p.window._projection_timer.isActive()
        assert not p.window._animation_timer.isActive()
