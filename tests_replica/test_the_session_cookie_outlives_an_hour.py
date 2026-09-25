"""Leaving a graph for the home page and re-entering it reloads the Studio.

The desktop renews the server-side browser session in place every hour, but
it never re-sends the cookie. A cookie that carried Max-Age=3600 therefore
died in the window while its session still answered, and every reload after
the first hour showed "desktop bootstrap is required". The cookie must live
as long as the window; the server-side session is what decides.
"""
from email.message import Message
from io import BytesIO
from urllib.parse import parse_qs, urlsplit

from nodelang.application_server import ApplicationServer
from tests_replica.test_universal_workshop_assignments import _green_runtime_compliance


def _http_get(server, path, *, cookie=None):
    handler = object.__new__(server.httpd.RequestHandlerClass)
    handler.server = server.httpd
    handler.path, handler.command = path, "GET"
    handler.request_version = "HTTP/1.1"
    handler.requestline = "GET " + path + " HTTP/1.1"
    handler.headers = Message()
    handler.headers["Host"] = urlsplit(server.public_url).netloc
    if cookie is not None:
        handler.headers["Cookie"] = "ArchHub-Session=" + cookie
    handler.rfile, handler.wfile = BytesIO(), BytesIO()
    handler.do_GET()
    headers, body = handler.wfile.getvalue().split(b"\r\n\r\n", 1)
    return int(headers.split(b" ", 2)[1]), headers, body


def _cookie_line(headers: bytes) -> str:
    for line in headers.split(b"\r\n"):
        if line.lower().startswith(b"set-cookie: archhub-session="):
            return line.decode("ascii")
    raise AssertionError("no session cookie was set")


def test_the_session_cookie_has_no_lifetime_of_its_own_and_a_reload_is_admitted(tmp_path):
    server = ApplicationServer(
        universal_workspace_root=tmp_path,
        conversation_history_path=tmp_path / "content.sqlite3",
        runtime_compliance_runner=_green_runtime_compliance,
        enable_machine_transport=False, enable_machine_projection_prewarm=False,
    )
    try:
        token = server.browser_session_token
        bootstrap = parse_qs(urlsplit(server.bootstrap_url).query)["bootstrap"][0]
        status, headers, _ = _http_get(server, "/studio?bootstrap=" + bootstrap)
        assert status == 200
        cookie = _cookie_line(headers)
        attributes = [part.strip().lower() for part in cookie.split(";")[1:]]
        assert not any(a.startswith(("max-age", "expires")) for a in attributes), cookie
        assert {"httponly", "samesite=strict", "path=/"} <= set(attributes)
        # Re-entering the graph is a plain reload carrying only the cookie.
        assert _http_get(server, "/studio", cookie=token)[0] == 200
        assert _http_get(server, "/", cookie=token)[0] == 200
    finally:
        server.close()
