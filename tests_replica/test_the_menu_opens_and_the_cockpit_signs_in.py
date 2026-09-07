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
from nodelang import cloud_relay


def _menu_source() -> str:
    source = inspect.getsource(companion)
    start = source.index("def contextMenuEvent(self, event)")
    return source[start:source.index("def mousePressEvent", start)]


def test_the_companion_holds_still_while_its_menu_is_open():
    body = _menu_source()
    assert "self._projection_timer.stop()" in body
    assert "self._animation_timer.stop()" in body
    assert "menu.exec(event.globalPos())" in body
    stopped = body.index("self._projection_timer.stop()")
    shown = body.index("menu.exec(event.globalPos())")
    restarted = body.index("self._projection_timer.start()")
    assert stopped < shown < restarted, (
        "the timers must be stopped before the menu and started after it"
    )
    assert "finally:" in body, "a menu that raises must not freeze the companion"


def test_the_menu_asks_for_a_signed_in_cockpit_address():
    body = _menu_source()
    assert 'menu.addAction("Open the cockpit", self._open_cockpit)' in body
    assert "https://api.archhub.io/founder" not in body, (
        "the menu must not hard-code the signed-out cockpit address"
    )
    helper = inspect.getsource(companion).split("def _open_cockpit")[1]
    assert "cockpit_url" in helper


def test_a_signed_in_machine_gets_a_claim_link(monkeypatch, tmp_path):
    """The desktop spends its session once for a link the browser can open."""
    monkeypatch.setattr(
        cloud_relay, "load_cloud_session",
        lambda appdata: {"token": "founder-session", "base_url": "https://cloud.test"},
    )
    seen: dict = {}

    class _Answer:
        def read(self):
            return json.dumps(
                {"claim_url": "https://cloud.test/founder/claim?code=abc"}
            ).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def urlopen(request, timeout=None):
        seen["url"] = request.full_url
        seen["method"] = request.get_method()
        seen["auth"] = request.get_header("Authorization")
        return _Answer()

    monkeypatch.setattr(cloud_relay.urllib.request, "urlopen", urlopen)
    url = cloud_relay.cockpit_url(tmp_path)

    assert url == "https://cloud.test/founder/claim?code=abc"
    assert seen["url"] == "https://cloud.test/founder/api/browser-code"
    assert seen["method"] == "POST"
    assert seen["auth"] == "Bearer founder-session"


def test_a_signed_out_machine_still_gets_a_live_address(monkeypatch, tmp_path):
    monkeypatch.setattr(cloud_relay, "load_cloud_session", lambda appdata: None)

    def urlopen(request, timeout=None):
        raise AssertionError("a signed-out machine must not call the cockpit")

    monkeypatch.setattr(cloud_relay.urllib.request, "urlopen", urlopen)
    assert cloud_relay.cockpit_url(tmp_path) == cloud_relay.DEFAULT_BASE + "/founder"


def test_a_refused_handoff_falls_back_rather_than_opening_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(
        cloud_relay, "load_cloud_session",
        lambda appdata: {"token": "t", "base_url": "https://cloud.test"},
    )

    def urlopen(request, timeout=None):
        raise OSError("cloud is unreachable")

    monkeypatch.setattr(cloud_relay.urllib.request, "urlopen", urlopen)
    assert cloud_relay.cockpit_url(tmp_path) == "https://cloud.test/founder"


@pytest.mark.parametrize(
    "claim", ["http://cloud.test/founder/claim?code=a", "", None, 7]
)
def test_only_an_https_claim_link_is_opened(monkeypatch, tmp_path, claim):
    """A hand-off link is opened in a browser; it never leaves https."""
    monkeypatch.setattr(
        cloud_relay, "load_cloud_session",
        lambda appdata: {"token": "t", "base_url": "https://cloud.test"},
    )

    class _Answer:
        def read(self):
            return json.dumps({"claim_url": claim}).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(
        cloud_relay.urllib.request, "urlopen",
        lambda request, timeout=None: _Answer(),
    )
    assert cloud_relay.cockpit_url(tmp_path) == "https://cloud.test/founder"
