"""Court: the desktop window goes from the boot page straight to the Studio.

The launcher loaded server.bootstrap_url ("/?bootstrap=..."), which renders the
"/" universal document (HOME / SEARCH / SHARE / SETTINGS / ArchHub Operating
Graph ...) for about a second before the window moved on to /studio. The
founder must never see "/". /studio consumes the same one-time bootstrap and
mints the session cookie, so the window enters there directly.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from nodelang.application_server import ApplicationServer
from tests_replica.test_the_session_cookie_outlives_an_hour import _cookie_line, _http_get
from tests_replica.test_universal_workshop_assignments import _green_runtime_compliance

LAUNCHER = Path(__file__).resolve().parents[1] / "launch_archhub_test.py"


def test_the_window_never_loads_the_universal_document():
    source = LAUNCHER.read_text(encoding="utf-8")
    assert "view.load(QUrl(server.bootstrap_url))" not in source
    assert "view.load(QUrl(_studio_entry_url()))" in source
    assert 'server.public_url + "/studio" + ("?bootstrap=" + token if token else "")' in source


def test_the_studio_entry_consumes_the_bootstrap_and_mints_the_session(tmp_path):
    server = ApplicationServer(
        universal_workspace_root=tmp_path,
        conversation_history_path=tmp_path / "content.sqlite3",
        runtime_compliance_runner=_green_runtime_compliance,
        enable_machine_transport=False, enable_machine_projection_prewarm=False,
    )
    try:
        token = server.browser_bootstrap_token
        entry = server.public_url + "/studio?bootstrap=" + token
        status, headers, body = _http_get(server, urlsplit(entry).path + "?" + urlsplit(entry).query)
        assert status == 200
        assert _cookie_line(headers)
        assert b"ARCHHUB_BOOT" in body or b"<html" in body.lower()
        # The same bootstrap cannot be spent twice.
        assert _http_get(server, "/studio?bootstrap=" + token)[0] == 403
        # The session it minted keeps the Studio open without it.
        assert _http_get(server, "/studio", cookie=server.browser_session_token)[0] == 200
    finally:
        server.close()
