"""Court: the canvas page loads its fonts from this machine, never from Google.

Frontend brief task 10. The canvas head linked fonts.googleapis.com, so an
offline desktop drew in fallback faces and every open leaked a request to a
third party; it also pulled Architects Daughter, which no stylesheet names.
The canvas now carries the same @font-face block the website export writes
and serves the same woff2 files.
"""
from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from nodelang import application_server
from nodelang.site_export import FONT_FACES, FONTS_CSS

Server = application_server._CleanAuthorityHttpServer


def _page() -> str:
    return Server._clean_page(SimpleNamespace(clean_canvas_key="k"))


def test_the_canvas_page_names_no_remote_font_source():
    page = _page()
    for remote in ("fonts.googleapis.com", "fonts.gstatic.com", "Architects"):
        assert remote not in page, remote


def test_the_canvas_page_carries_the_website_font_faces():
    page = _page()
    assert FONTS_CSS in page
    head = page.split("</head>", 1)[0]
    assert FONTS_CSS in head


@pytest.mark.parametrize("name", [face[0] for face in FONT_FACES])
def test_every_face_the_page_names_is_served_as_woff2(name):
    body, kind = Server._clean_font_asset(SimpleNamespace(), name)
    assert body[:4] == b"wOF2"
    assert kind == "font/woff2"


@pytest.mark.parametrize("name", [
    "../application_server.py", "OFL-Inter.txt", "missing.woff2", "",
])
def test_nothing_but_a_named_face_is_served(name):
    with pytest.raises(FileNotFoundError):
        Server._clean_font_asset(SimpleNamespace(), name)


def test_the_canvas_server_routes_font_requests_without_the_page_key():
    source = inspect.getsource(Server)
    route = source.index('request_path.startswith("/assets/fonts/")')
    keyed = source.index("the canvas page requires the key this")
    assert route < keyed, "font requests must not need the canvas key"
    assert "owner._clean_font_asset(" in source
