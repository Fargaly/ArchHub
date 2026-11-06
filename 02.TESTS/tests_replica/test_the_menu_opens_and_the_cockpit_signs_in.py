"""The companion menu opens its rows, and the cockpit link is signed in.

Two defects the founder reported on 2026-09-07:

  * Right-click rows never opened. refresh() runs every 750ms and moves,
    reshapes and repaints the companion window, which is
    WindowStaysOnTopHint; every submenu opened on hover was immediately
    restacked underneath it.

  * "Open the cockpit" opened https://api.archhub.io/founder in a browser
    that carries none of the desktop's sign-in, so it landed on a token
    form he has no token for.
"""
from __future__ import annotations

import inspect
import json
import types
from pathlib import Path

import pytest

from nodelang import baboom_native_companion as companion
from nodelang import cloud_relay, cloud_signin


def _menu_source() -> str:
    source = inspect.getsource(companion)
    start = source.index("def contextMenuEvent(self, event)")
    return source[start:source.index("def mousePressEvent", start)]


def test_the_companion_holds_still_while_its_menu_is_open(tmp_path, monkeypatch):
    from PyQt6.QtCore import QTimer, Qt
    from PyQt6.QtGui import QContextMenuEvent
    from PyQt6.QtWidgets import QMenu
    from tests_replica.test_baboom_native_companion import _screen_companion

    app, window, _ = _screen_companion(tmp_path, monkeypatch, "menu.png")
    original_exec = QMenu.exec
    observed = []

    def execute(menu, point):
        geometry = window.geometry()
        submenu = next(action.menu() for action in menu.actions() if action.menu())

        def open_submenu():
            submenu.popup(menu.mapToGlobal(menu.actionGeometry(submenu.menuAction()).topRight()))

        def observe_and_close():
            observed.append((menu.isVisible(), submenu.isVisible(),
                             window.geometry() == geometry,
                             window._projection_timer.isActive(),
                             window._animation_timer.isActive()))
            submenu.close()
            menu.close()

        QTimer.singleShot(0, open_submenu)
        QTimer.singleShot(1100, observe_and_close)
        return original_exec(menu, point)

    monkeypatch.setattr(QMenu, "exec", execute)
    try:
        assert window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
        window.contextMenuEvent(QContextMenuEvent(
            QContextMenuEvent.Reason.Mouse, window.rect().center(), window.geometry().center()))
        assert observed == [(True, True, True, False, False)]
        assert window._projection_timer.isActive()
    finally:
        window.hide_until_next_launch()
        window.close()
        window.deleteLater()
        app.processEvents()


def test_a_menu_error_does_not_freeze_projection(tmp_path, monkeypatch):
    from PyQt6.QtGui import QContextMenuEvent
    from PyQt6.QtWidgets import QMenu
    from tests_replica.test_baboom_native_companion import _screen_companion

    app, window, _ = _screen_companion(tmp_path, monkeypatch, "menu-error.png")

    def refuse(*args):
        raise RuntimeError("menu failed")

    monkeypatch.setattr(QMenu, "exec", refuse)
    try:
        with pytest.raises(RuntimeError, match="menu failed"):
            window.contextMenuEvent(QContextMenuEvent(
                QContextMenuEvent.Reason.Mouse, window.rect().center(), window.geometry().center()))
        assert window._projection_timer.isActive()
    finally:
        window.hide_until_next_launch()
        window.close()
        window.deleteLater()
        app.processEvents()


def test_the_menu_asks_for_a_signed_in_cockpit_address():
    body = _menu_source()
    assert 'menu.addAction("Open the cockpit", self._open_cockpit)' in body
    assert "https://api.archhub.io/founder" not in body, (
        "the menu must not hard-code the signed-out cockpit address"
    )
    helper = inspect.getsource(companion).split("def _open_cockpit")[1]
    assert "cockpit_url" in helper


def _session(appdata: Path, **fields) -> None:
    record = appdata / "ArchHub" / "brain" / "cloud.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    held = {"token": "founder-session", "email": "founder@example.com",
            "cloud_base_url": "https://api.archhub.io", "expires_at": 4_000_000_000}
    held.update(fields)
    record.write_text(json.dumps(held), encoding="utf-8")


def _cloud(monkeypatch, answer):
    seen: list = []

    def http(method, url, *, body=None, headers=None, timeout=15.0):
        seen.append({"method": method, "url": url, "auth": (headers or {}).get("Authorization")})
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(cloud_signin, "http_json", http)
    return seen


def test_a_signed_in_machine_gets_a_claim_link(monkeypatch, tmp_path):
    """The desktop spends its session once for a link the browser can open."""
    _session(tmp_path)
    seen = _cloud(monkeypatch, (200, {"claim_url": "https://api.archhub.io/founder/claim?code=abc"}))
    url = cloud_relay.cockpit_url(tmp_path)

    assert url == "https://api.archhub.io/founder/claim?code=abc"
    assert seen == [{"method": "POST", "url": "https://api.archhub.io/founder/api/browser-code",
                     "auth": "Bearer founder-session"}]


def test_a_signed_out_machine_still_gets_a_live_address(monkeypatch, tmp_path):
    seen = _cloud(monkeypatch, AssertionError("a signed-out machine must not call the cockpit"))
    assert cloud_relay.cockpit_url(tmp_path) == cloud_relay.DEFAULT_BASE + "/founder"
    assert seen == []


def test_a_refused_handoff_falls_back_rather_than_opening_nothing(monkeypatch, tmp_path):
    _session(tmp_path)
    _cloud(monkeypatch, OSError("cloud is unreachable"))
    assert cloud_relay.cockpit_url(tmp_path) == "https://api.archhub.io/founder"


@pytest.mark.parametrize(
    "claim", ["http://cloud.test/founder/claim?code=a", "", None, 7]
)
def test_only_an_https_claim_link_is_opened(monkeypatch, tmp_path, claim):
    """A hand-off link is opened in a browser; it never leaves https."""
    _session(tmp_path)
    _cloud(monkeypatch, (200, {"claim_url": claim}))
    assert cloud_relay.cockpit_url(tmp_path) == "https://api.archhub.io/founder"
