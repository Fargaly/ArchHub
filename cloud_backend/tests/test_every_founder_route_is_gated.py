"""Every /founder route refuses anyone who is not a founder (Cockpit P0, 2026-09-29).

The routes are read from the app itself, so a route added later is covered
without editing this file. Only the sign-in pages are open: /founder/login (a
static page), /founder/claim (spends a one-time code, then applies the same
founder check) and /founder/logout. A browser page load may be redirected to
the login page instead of a bare 403; anything else a non-founder receives is
a hole.
"""
from __future__ import annotations

import re

import pytest

from tests.google_signin import google_sign_in

# Two configured founders, listed with spaces the gate must trim: both pass.
FOUNDERS = ("founder.one@archhub-cockpit-test.com", "founder.two@archhub-cockpit-test.com")
OPEN = {"/founder/login", "/founder/claim", "/founder/logout"}


@pytest.fixture(autouse=True)
def _founders(monkeypatch, tmp_path):
    for name in ("FOUNDER_EMAIL", "ARCHHUB_FOUNDER_EMAIL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FOUNDER_EMAILS", " %s , %s " % FOUNDERS)
    import config
    import founder_cockpit
    # A founder's POST /founder/map-state writes the map and its stamp: keep
    # both in the test (the module holds its own path, taken at import).
    monkeypatch.setattr(config, "FOUNDER_MAP_STATE", tmp_path / "founder-map.json")
    monkeypatch.setattr(founder_cockpit, "_MAP_STATE", tmp_path / "founder-map.json")
    monkeypatch.setattr(config, "FOUNDER_MAP_PUSHED_AT", tmp_path / "founder-map.pushed-at.json")


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app, raise_server_exceptions=False)


def _founder_routes():
    import main
    routes = []
    for route in main.app.routes:
        path = getattr(route, "path", "")
        if not (path == "/founder" or path.startswith("/founder/")) or path in OPEN:
            continue
        for method in sorted(getattr(route, "methods", None) or ()):
            if method not in ("HEAD", "OPTIONS"):
                routes.append((method, path))
    return routes


def _call(client, method, path, headers):
    concrete = re.sub(r"\{[^}]+\}", "court", path)
    body = {} if method in ("POST", "PUT", "PATCH", "DELETE") else None
    return client.request(method, concrete, headers=headers, json=body, follow_redirects=False)


def _refused(response) -> bool:
    if response.status_code == 403:
        return True
    return (response.status_code in (302, 303, 307)
            and "/founder/login" in response.headers.get("location", ""))


def _auth(token):
    return {"Authorization": "Bearer %s" % token}


def test_the_app_serves_the_founder_routes_this_court_walks():
    routes = _founder_routes()
    assert len(routes) >= 18, routes
    assert ("POST", "/founder/api/command") in routes


def test_no_token_is_refused_on_every_founder_route(client):
    holes = [(method, path, response.status_code) for method, path in _founder_routes()
             for response in [_call(client, method, path, {})] if not _refused(response)]
    assert holes == []


def test_a_signed_in_stranger_is_refused_on_every_founder_route(client, monkeypatch):
    token = google_sign_in(client, monkeypatch, "someone.else@studio.com")
    assert client.get("/v1/me", headers=_auth(token)).status_code == 200
    holes = [(method, path, response.status_code) for method, path in _founder_routes()
             for response in [_call(client, method, path, _auth(token))] if not _refused(response)]
    assert holes == []


@pytest.mark.parametrize("email", FOUNDERS)
def test_each_configured_founder_passes_the_gate_on_every_route(client, monkeypatch, email):
    import pathlib
    backend = pathlib.Path(__file__).resolve().parents[1]
    before = sorted(p.name for p in backend.glob("founder-map*.json"))
    token = google_sign_in(client, monkeypatch, email)
    refused = [(method, path, response.status_code) for method, path in _founder_routes()
               for response in [_call(client, method, path, _auth(token))]
               if response.status_code in (401, 403) or _refused(response)]
    assert refused == []
    # Nothing the walk did reached the working tree.
    assert sorted(p.name for p in backend.glob("founder-map*.json")) == before