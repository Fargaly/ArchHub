"""Court: the desktop Studio loads its fonts from this machine, never from Google.

The installed desktop opens ``/studio`` on the main ApplicationServer handler
(launch_archhub_test loads ``server.public_url + "/studio"``). Frontend task 10
moved the clean canvas page to local faces, but the Studio still linked
fonts.googleapis.com, its CSP only admitted fonts.gstatic.com, and this handler
had no font route: GET /assets/fonts/inter-variable.woff2 answered 404 on the
installed build. This court drives the real handler of a real ApplicationServer.
"""
from __future__ import annotations

from email.message import Message
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from nodelang.application_server import ApplicationServer
from nodelang.site_export import FONT_FACES, FONTS_CSS
from tests_replica.test_universal_workshop_assignments import _green_runtime_compliance

STUDIO = Path(__file__).resolve().parents[1] / "nodelang" / "studio"
REMOTE = ("fonts.googleapis.com", "fonts.gstatic.com")


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
    head, body = handler.wfile.getvalue().split(b"\r\n\r\n", 1)
    headers = {}
    for line in head.split(b"\r\n")[1:]:
        key, _, value = line.decode("latin-1").partition(":")
        headers[key.strip().lower()] = value.strip()
    return int(head.split(b" ", 2)[1]), headers, body


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    root = tmp_path_factory.mktemp("studio-fonts")
    running = ApplicationServer(
        universal_workspace_root=root,
        conversation_history_path=root / "content.sqlite3",
        runtime_compliance_runner=_green_runtime_compliance,
        enable_machine_transport=False, enable_machine_projection_prewarm=False,
    )
    try:
        yield running
    finally:
        running.close()


@pytest.mark.parametrize("name", [face[0] for face in FONT_FACES])
def test_every_face_is_served_by_the_desktop_server_without_a_session(server, name):
    status, headers, body = _http_get(server, "/assets/fonts/" + name)
    assert status == 200, body[:80]
    assert headers["content-type"] == "font/woff2"
    assert body[:4] == b"wOF2"


def test_the_font_stylesheet_is_the_website_block(server):
    status, headers, body = _http_get(server, "/assets/fonts.css")
    assert status == 200, body[:80]
    assert headers["content-type"].startswith("text/css")
    assert body.decode("utf-8") == FONTS_CSS


@pytest.mark.parametrize("name", ["../application_server.py", "OFL-Inter.txt", "missing.woff2"])
def test_nothing_but_a_named_face_is_served(server, name):
    assert _http_get(server, "/assets/fonts/" + name)[0] == 404


def test_the_served_studio_page_names_only_local_fonts_and_its_csp_admits_them(server):
    bootstrap = parse_qs(urlsplit(server.bootstrap_url).query)["bootstrap"][0]
    status, headers, body = _http_get(server, "/studio?bootstrap=" + bootstrap)
    assert status == 200
    page = body.decode("utf-8")
    head = page.split("</head>", 1)[0]
    assert '<link rel="stylesheet" href="/assets/fonts.css"/>' in head
    for remote in REMOTE:
        assert remote not in page, remote
    policy = headers["content-security-policy"]
    directives = {d.split()[0]: d.split()[1:] for d in policy.split(";") if d.strip()}
    assert directives["font-src"] == ["'self'"]
    assert "'self'" in directives["style-src"]
    for remote in REMOTE:
        assert remote not in policy, remote


@pytest.mark.parametrize("page", ["studio.html", "cockpit.html"])
def test_no_studio_page_links_a_remote_font_host(page):
    source = (STUDIO / page).read_text(encoding="utf-8")
    for remote in REMOTE:
        assert remote not in source, (page, remote)
