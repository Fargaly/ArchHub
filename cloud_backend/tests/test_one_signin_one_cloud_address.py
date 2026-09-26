"""One sign-in, one cloud address (founder, 2026-09-24).

(a) The cockpit has no sign-in of its own. The desktop app is the one door:
    it spends its session at POST /founder/api/browser-code for a one-time
    claim link. A browser without the cockpit cookie lands on a page that
    says so and offers no form.
(c) The cloud names itself https://api.archhub.io everywhere it builds a
    link; the Fly host name is only Fly's own name for the app.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
FLY_HOST = "archhub-cloud.fly.dev"
FOUNDER_EMAIL = "founder@archhub-one-door-test.com"


@pytest.fixture(autouse=True)
def _set_founder(monkeypatch):
    monkeypatch.setenv("FOUNDER_EMAIL", FOUNDER_EMAIL)
    yield


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app, base_url="https://testserver",
                      raise_server_exceptions=False)


def _routes():
    import main
    return {(method, route.path) for route in main.app.routes
            for method in (getattr(route, "methods", None) or ())}


def test_a_the_cockpit_has_no_sign_in_route_of_its_own():
    routes = _routes()
    for gone in (("POST", "/founder/login"), ("POST", "/founder/login/email"),
                 ("GET", "/founder/login/google")):
        assert gone not in routes, gone
    for kept in (("POST", "/founder/api/browser-code"), ("GET", "/founder/claim"),
                 ("GET", "/founder/login"), ("GET", "/founder/logout")):
        assert kept in routes, kept


def test_a_a_browser_without_the_app_session_is_sent_to_the_app(client):
    landed = client.get("/founder", headers={"Accept": "text/html"}, follow_redirects=False)
    assert landed.status_code == 307
    assert landed.headers["location"].startswith("/founder/login")
    page = client.get(landed.headers["location"]).text
    assert "<form" not in page and "<input" not in page
    assert "Open the cockpit" in page and "Link for another device" in page


def test_a_the_app_session_opens_the_cockpit_without_a_second_sign_in(client):
    import db
    user = db.get_or_create_user(FOUNDER_EMAIL)
    session = db.issue_token(user["id"])
    claim = client.post("/founder/api/browser-code",
                        headers={"Authorization": "Bearer " + session}).json()["claim_url"]
    landed = client.get("/founder/claim?code=" + claim.split("code=", 1)[1])
    assert landed.status_code == 200 and "Cockpit" in landed.text
    assert "/founder/login" not in str(landed.url)


def test_c_the_deployed_public_url_is_the_one_address():
    toml = (BACKEND / "fly.toml").read_text(encoding="utf-8")
    assert re.search(r"^\s*PUBLIC_URL\s*=\s*'https://api\.archhub\.io'\s*$", toml, re.M)
    import config
    assert re.search(r'_req\("PUBLIC_URL", "https://api\.archhub\.io"\)',
                     (BACKEND / "config.py").read_text(encoding="utf-8"))
    assert config.GOOGLE_OAUTH_REDIRECT.startswith(config.PUBLIC_URL.rstrip("/"))


def test_c_no_cloud_code_path_names_the_fly_host():
    hits = []
    for path in BACKEND.rglob("*"):
        if "tests" in path.parts or "__pycache__" in path.parts or not path.is_file():
            continue
        if path.suffix in {".py", ".toml", ".ps1", ".js", ".html"} or path.name == "Dockerfile":
            if FLY_HOST in path.read_text(encoding="utf-8", errors="replace"):
                hits.append(str(path.relative_to(BACKEND)))
    assert hits == [], hits


def test_a_the_cloud_tells_the_app_who_owns_the_cockpit(client):
    """The app offers "Open the cockpit" only when /v1/me says founder."""
    import db
    for address, owns in ((FOUNDER_EMAIL, True), ("someone.else@studio.example", False)):
        user = db.get_or_create_user(address)
        session = db.issue_token(user["id"])
        me = client.get("/v1/me", headers={"Authorization": "Bearer " + session})
        assert me.status_code == 200 and me.json()["founder"] is owns, address


def test_c_deploy_refuses_until_the_one_address_answers_over_tls():
    script = (BACKEND / "deploy.ps1").read_text(encoding="utf-8")
    gate = script.index('$publicHealth = "https://api.archhub.io/healthz"')
    assert gate < script.index("flyctl deploy") and gate < script.index("flyctl secrets")
    check = script[gate:script.index("# ----- 1. Ensure flyctl")]
    assert "exit 1" in check and "-ne 200" in check
    assert "SkipCertificateCheck" not in script, "a live certificate is the point of the check"
