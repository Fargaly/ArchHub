"""Courts: Google is the one human sign-in (founder 2026-09-28).

"ONE source for everything ... no more million sign-ins, and no idiotic
magic link. I want Google authentication, straight away."

  1. The removed email sign-in route answers 404 with a plain message.
  2. Google sign-in creates the account on first use and reuses it by
     email after, including an account made before Google was the only
     sign-in (its data and session are untouched).
  3. Every auth-shaped route on the app is classified; exactly one starts
     a human sign-in: Google. A new sign-in route fails this court until
     someone decides what it is.
  4. Every cloud page offers the one Google button and no email form.
"""
from __future__ import annotations

import pytest

from tests.google_signin import google_sign_in


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app)


# 1 ---------------------------------------------------------------------------
def test_the_email_sign_in_route_is_gone(client):
    r = client.post("/v1/auth/register",
                    json={"email": "someone@studio.com",
                          "code_challenge": "c" * 43})
    assert r.status_code == 404
    assert r.json() == {
        "error": "email_signin_removed",
        "detail": "Email sign-in was removed; use Continue with Google.",
    }


# 2 ---------------------------------------------------------------------------
def test_google_sign_in_creates_then_reuses_the_account_by_email(client, monkeypatch):
    import db
    assert db.get_user_by_email("new@studio.com") is None
    first = google_sign_in(client, monkeypatch, "new@studio.com")
    created = db.user_for_token(first)
    assert created["email"] == "new@studio.com"
    second = google_sign_in(client, monkeypatch, "New@Studio.com")
    assert db.user_for_token(second)["id"] == created["id"]
    with db.connect() as con:
        rows = con.execute("SELECT COUNT(*) AS n FROM users WHERE email = ?",
                           ("new@studio.com",)).fetchone()["n"]
    assert rows == 1


def test_an_account_made_before_google_keeps_its_data(client, monkeypatch):
    import db
    old = db.get_or_create_user("longtime@studio.com")
    db.update_user_profile(old["id"], full_name="Long Time", firm_name="Old Firm")
    old_session = db.issue_token(old["id"])
    token = google_sign_in(client, monkeypatch, "longtime@studio.com",
                           name="Google Name")
    now = db.user_for_token(token)
    assert now["id"] == old["id"]
    kept = db.get_user(old["id"])
    assert kept["full_name"] == "Long Time" and kept["firm_name"] == "Old Firm"
    assert db.user_for_token(old_session)["id"] == old["id"]


# 3 ---------------------------------------------------------------------------
# Every route whose path looks like authentication, and what it is.
HUMAN_SIGN_IN = "human sign-in (Google)"
NOT_SIGN_IN = "not a sign-in: spends or ends a session Google already made"
AUTH_ROUTES = {
    "/v1/auth/google/start": HUMAN_SIGN_IN,
    "/v1/auth/google/callback": HUMAN_SIGN_IN,
    "/signin": "page: one Continue with Google button",
    "/v1/auth/exchange": NOT_SIGN_IN,       # finishes the Google code (PKCE)
    "/auth/return": NOT_SIGN_IN,            # forwards the Google code
    "/v1/auth/logout": NOT_SIGN_IN,
    "/founder/login": "page: no form, says the cockpit opens from the app",
    "/founder/api/browser-code": NOT_SIGN_IN,  # founder's existing session -> one-time link
    "/founder/claim": NOT_SIGN_IN,             # spends that link for the cookie
    "/founder/logout": NOT_SIGN_IN,
}
_AUTH_SHAPED = ("auth", "login", "logout", "signin", "sign-in", "sign_in",
                "register", "magic", "claim", "browser-code", "password",
                "otp", "passcode", "verify", "session", "pair", "device")
_NOT_AUTH = {"/docs/oauth2-redirect",          # FastAPI's docs page
             "/founder/api/agent-tasks/claim"}  # task queue, not identity


def _auth_shaped_paths():
    import main
    found = set()
    for route in main.app.routes:
        path = getattr(route, "path", "") or ""
        if path in _NOT_AUTH:
            continue
        if any(word in path.lower() for word in _AUTH_SHAPED):
            found.add(path)
    return found


def test_every_auth_route_is_classified_and_only_google_signs_a_person_in():
    assert _auth_shaped_paths() == set(AUTH_ROUTES)
    human = {path for path, kind in AUTH_ROUTES.items() if kind == HUMAN_SIGN_IN}
    assert human == {"/v1/auth/google/start", "/v1/auth/google/callback"}


# 4 ---------------------------------------------------------------------------
@pytest.mark.parametrize("page", ["/signin", "/invite?token=t", "/dashboard", "/brain"])
def test_every_cloud_page_offers_only_google(client, page):
    r = client.get(page)
    assert r.status_code == 200
    assert "Continue with Google" in r.text
    assert "/v1/auth/google/start" in r.text
    assert "/v1/auth/register" not in r.text
    assert "type='email'" not in r.text
    assert "magic" not in r.text.lower()