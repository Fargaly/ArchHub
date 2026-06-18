"""Desktop cloud sign-in loopback callback contract."""
from __future__ import annotations

import sys
import threading
import urllib.request
from http.server import HTTPServer
from pathlib import Path

import pytest

pytest.importorskip("PyQt6.QtCore")

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


def test_loopback_accepts_live_backend_return_state():
    """The deployed /auth/return hop sends state=archhub to the loopback."""
    import cloud_auth

    httpd = HTTPServer(("127.0.0.1", 0), cloud_auth._CallbackHandler)
    httpd.expected_state = "desktop-random-state"
    httpd.received_code = None
    httpd.timeout = 2.0
    port = httpd.server_address[1]

    thread = threading.Thread(target=httpd.handle_request, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/cb?code=code-123&state=archhub",
            timeout=5.0,
        ) as resp:
            body = resp.read().decode("utf-8")
            status = resp.status
    finally:
        httpd.server_close()
        thread.join(timeout=5.0)

    assert status == 200
    assert "signed in" in body.lower()
    assert httpd.received_code == "code-123"
