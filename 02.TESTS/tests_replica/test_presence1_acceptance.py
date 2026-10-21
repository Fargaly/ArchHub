"""Independent PRESENCE1 acceptance: isolated widgets, disposable graph, no desktop.

Win32 adapter assertions use a fake user32. These are deliberately not evidence
of a real Windows notification area, HWND hit testing, or foreground scheduling.
"""
import json
import os
import time
from types import SimpleNamespace

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import pytest
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QColor, QCursor
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon

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
    assert p.calls[-1][1] is True
    assert not p.window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert not p.window._report.isVisible()
    p.controller.pin_sprite_origin(4, 320)
    p.refresh()
    assert p.window.x() == 0 and p.window.y() == 320
    p.controller.pin_sprite_origin(400, 7)
    p.refresh()
    assert p.window.x() == 400 and p.window.y() == 0


def test_active_unknown_foreign_app_hides_then_returns_at_break(presence):
    p = presence
    p.window.start_projection()
    p.refresh("Screen")
    assert p.window.isVisible()
    # No named host adapter, and no overlap: activity alone must hide it.
    p.environment.update(idle=0.0, foreign=True, occupied=[Rect(0, 0, 300, 300)])
    p.refresh()
    assert not p.window.isVisible()
    assert p.window._projection_timer.interval() <= 2000
    p.environment["idle"] = 2.1
    p.refresh()
    assert p.window.isVisible()
    # Active foreign work remains protected even if its bounds overlap.
    p.environment["idle"] = 0.0
    p.environment["occupied"] = [Rect(1200, 720, 80, 80)]
    p.refresh()
    assert not p.window.isVisible()
    p.environment["idle"] = 2.1
    p.refresh()
    assert p.window.isVisible()


def test_details_are_explicit_non_topmost_and_close_to_tray(presence):
    p = presence
    p.window.start_projection()
    assert not p.window.isVisible()
    p.window._tray.activated.emit(QSystemTrayIcon.ActivationReason.Trigger)
    p.app.processEvents()
    assert p.window._details_open and p.window.isVisible()
    assert p.window._input.isVisible()
    assert not p.window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
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


def test_shows_as_graph_restart_preserves_startup_and_rejects_stale_or_foreign(tmp_path):
    from nodelang.application_server import ApplicationServer
    from nodelang.cell_authorization import AuthorizationDenied
    from nodelang.cell_lifecycle import append_wip_revision
    from nodelang.map_import import resolve_map_path
    from nodelang.universal_application import (
        build_universal_application, project_universal_canvas, provision_universal_view_session,
        read_universal_baboom_startup, restore_universal_application, set_universal_baboom_startup,
    )
    from nodelang.universal_cell import Cell, CellStore, InvalidCell, NULL_CELL_ID
    from tests_replica.test_baboom_startup_setting import _provider
    from tests_replica.test_application_server_governance import _interaction_request, _json

    path = tmp_path / "presence-review.sqlite3"
    provider = _provider()
    store, registry = build_universal_application(resolve_map_path(), CellStore(path), key_provider=provider)
    server = None
    try:
        initial = read_universal_baboom_startup(store.snapshot(), registry)
        assert initial.get("shows_as", "Tray") == "Tray"
        first = set_universal_baboom_startup(store, registry, "on", shows_as="Screen")
        # Exercise the real Settings caller's JSON fact and admitted HTTP route,
        # not a writer-only reconstruction of that path.
        server = ApplicationServer(universal_store=store, universal_registry=registry).start()
        token = server.browser_session_token
        status, canvas = _json(server.url, "/api/universal/canvas", token=token)
        assert status == 200
        setting = canvas["configuration"]["baboom_startup"]
        request = _interaction_request(canvas, setting["control"])
        request["event_facts"] = [{"input": setting["event_fact_input"],
                                   "value": json.dumps({"value": "on", "shows_as": "Tray"})}]
        status, delta = _json(server.url, "/api/universal/interaction", request, token=token)
        assert status == 200, delta
        saved = delta["configuration_state"]["baboom_startup"]
        assert saved["value"] == "on" and saved["shows_as"] == "Tray"
        assert saved["source"] == "graph"
        after_http = read_universal_baboom_startup(store.snapshot(), registry)
        assert after_http["revision"] == saved["revision"]
        assert after_http["shows_as"] == "Tray"
        second = set_universal_baboom_startup(store, registry, "off", shows_as="Hidden",
                                            base_revision_root=after_http["revision"])
        before = store.revision
        with pytest.raises(InvalidCell, match="changed"):
            set_universal_baboom_startup(store, registry, "on", shows_as="Tray", base_revision_root=first)
        with pytest.raises(InvalidCell):
            set_universal_baboom_startup(store, registry, "off", shows_as="floating", base_revision_root=second)
        assert store.revision == before
        member = "test:presence-review:member"
        store.commit(store.revision, create=(Cell(member, NULL_CELL_ID, NULL_CELL_ID, b"Member"),))
        provision_universal_view_session(store, registry, member, visible_roots=(registry.visible_roots[0],))
        authority = registry.authorization
        context = authority.broker.mint_authenticated_context(
            member, tenant_root=authority.tenant_root, assurance_root=authority.assurance_root, lifetime_seconds=120)
        before = store.revision
        with pytest.raises(AuthorizationDenied):
            set_universal_baboom_startup(store, registry, "on", shows_as="Tray",
                                        base_revision_root=second, authentication_context=context)
        assert store.revision == before
    finally:
        if server is not None:
            server.close()
        store.close()
    reopened = CellStore(path)
    try:
        reopened, restored = restore_universal_application(resolve_map_path(), reopened, key_provider=provider)
        current = read_universal_baboom_startup(reopened.snapshot(), restored)
        assert current["value"] == "off" and current["shows_as"] == "Hidden"
        assert current["revision"] == second
        assert current["actor"] == restored.authorization.subject_root
        projected = project_universal_canvas(reopened, restored)["configuration"]["baboom_startup"]
        assert projected["shows_as"] == "Hidden" and projected["value"] == "off"
        assert projected["control"] and projected["event_fact_input"]
        append_wip_revision(reopened, restored.assembly_protocol,
                            restored.standard_library.lifecycle_protocol, current["asset"],
                            content=b"\xff", actor_root=restored.authorization.subject_root,
                            base_revision_root=second, reason="court: malformed UTF-8 preference")
        before = reopened.revision
        with pytest.raises(InvalidCell, match="value is invalid"):
            read_universal_baboom_startup(reopened.snapshot(), restored)
        unavailable = project_universal_canvas(reopened, restored)["configuration"]["baboom_startup"]
        assert unavailable["source"] == "unreadable" and unavailable["available"] is False
        assert unavailable["error"] == "InvalidCell"
        assert reopened.revision == before
    finally:
        reopened.close()


def test_maximized_foreign_foreground_returns_at_natural_break(presence):
    p = presence
    p.environment.update(idle=0.0, foreign=True, occupied=[Rect(-8, -8, 1296, 816)])
    p.window.start_projection()
    p.refresh("Screen")
    assert not p.window.isVisible()
    p.environment["idle"] = 2.1
    p.refresh()
    assert p.window.isVisible(), "maximized foreground must not suppress an idle Screen sprite"
    assert p.window._projection_timer.interval() == 750


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
    QTest.mouseClick(p.window, Qt.MouseButton.LeftButton, pos=p.window.rect().center())
    assert p.opened == [True]


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


def test_hidden_sprite_does_not_wake_under_active_pointer(presence, monkeypatch):
    p = presence
    point = [QPoint(1250, 770)]
    monkeypatch.setattr(QCursor, "pos", lambda: point[0])
    p.environment.update(idle=0.0, foreign=True)
    p.window.start_projection()
    p.refresh("Screen")
    for _ in range(3):
        p.refresh()
        assert not p.window.isVisible()
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
    assert not p.window.isVisible()
