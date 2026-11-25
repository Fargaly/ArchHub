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
MCP_CLIENT = "not a sign-in: an MCP client's OAuth step around the Google sign-in"
DEVICE = "not a sign-in: a device of a session Google already made"
SOCIAL = "not a sign-in: connects a publishing account to a user Google already signed in"
AUTH_ROUTES = {
    "/v1/auth/google/start": HUMAN_SIGN_IN,
    "/v1/auth/google/callback": HUMAN_SIGN_IN,
    "/signin": "page: one Continue with Google button",
    "/v1/auth/exchange": NOT_SIGN_IN,       # finishes the Google code (PKCE)
    "/auth/return": NOT_SIGN_IN,            # forwards the Google code
    "/v1/auth/logout": NOT_SIGN_IN,
    "/v1/auth/refresh": NOT_SIGN_IN,        # extends the bearer session Google already made
    "/founder/login": "page: no form, says the cockpit opens from the app",
    "/founder/api/browser-code": NOT_SIGN_IN,  # founder's existing session -> one-time link
    "/founder/claim": NOT_SIGN_IN,             # spends that link for the cookie
    "/founder/logout": NOT_SIGN_IN,
    # The public MCP door's OAuth (oauth_mcp). None signs a person in: the one
    # human step inside it is the Google sign-in above.
    "/.well-known/oauth-protected-resource": MCP_CLIENT,        # discovery metadata
    "/.well-known/oauth-protected-resource/mcp": MCP_CLIENT,    # discovery metadata
    "/.well-known/oauth-authorization-server": MCP_CLIENT,      # discovery metadata
    "/oauth/register": MCP_CLIENT,    # registers a client application, not a person
    "/oauth/authorize": MCP_CLIENT,   # shows the consent page naming the client
    "/oauth/consent": MCP_CLIENT,     # Approve sends the person to Google sign-in
    "/oauth/continue": NOT_SIGN_IN,   # spends the Google-verified sign-in once
    "/oauth/token": MCP_CLIENT,       # exchanges a code minted after Google (PKCE)
    "/oauth/email-link": MCP_CLIENT,  # owner addresses only: the inbox approves one MCP client, no cloud session
    "/oauth/bearer": NOT_SIGN_IN,     # the founder's existing session mints an MCP connector bearer
    # Devices: a signed-in desktop reports itself; the founder sees and ends them.
    "/v1/devices/heartbeat": DEVICE,                                  # needs a Google-made session
    "/founder/api/devices": DEVICE,                                   # founder session only
    "/founder/api/devices/{user_key}/{device_id}/disconnect": DEVICE,  # ends a device session
    # Social publishing (social_oauth): a signed-in user links LinkedIn/Meta/WhatsApp for posting.
    "/oauth/{provider}/status": SOCIAL,     # needs the user's bearer session
    "/oauth/{provider}/start": SOCIAL,      # needs the user's bearer session
    "/oauth/whatsapp/embedded": SOCIAL,     # renders only for signed state minted by /start
    "/oauth/{provider}/callback": SOCIAL,   # spends that signed state once
    "/oauth/{provider}/consume": SOCIAL,    # needs the user's bearer session and a signed grant
    "/oauth/whatsapp/messages": SOCIAL,     # reads the bearer's own WhatsApp messages; signs no one in
}
_AUTH_SHAPED = ("auth", "login", "logout", "signin", "sign-in", "sign_in",
                "register", "magic", "claim", "browser-code", "password",
                "otp", "passcode", "verify", "session", "pair", "device")
_NOT_AUTH = {"/docs/oauth2-redirect",          # FastAPI's docs page
             "/founder/api/agent-tasks/claim"}  # task queue, not identity


def _auth_shaped_paths():
    from tests.test_one_signin_one_cloud_address import registered_routes

    found = set()
    for route in registered_routes():
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

# Codex 2026-11-20: /oauth/email-link is MCP client authorization only. What it yields must not work as an account.
from tests.test_mcp_email_link import _ask_for_link  # noqa: E402


@pytest.fixture
def mail(monkeypatch):
    """The emails the flow sends, captured instead of sent (the email-link court's own shape)."""
    import email_sender
    sent = []

    async def capture(*, to, subject, text, html):
        sent.append({"to": to, "subject": subject, "text": text})
        return True

    monkeypatch.setattr(email_sender, "_send", capture)
    return sent


def _email_link_flow(mail):
    """Run the owner's emailed-link approval for one MCP client, as the email-link court does; return what it left."""
    from tests.test_mcp_oauth import REDIRECT, _browser, _token
    browser = _browser()
    client_id, verifier, _pending, links = _ask_for_link(browser, mail)
    back = browser.get(links["founder.desktop@example.test"])
    done = browser.get(back.headers["location"].replace("https://api.archhub.io", ""))
    import urllib.parse
    code = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(done.headers["location"]).query))["code"]
    answer = _token(browser, grant_type="authorization_code", code=code, redirect_uri=REDIRECT,
                    client_id=client_id, code_verifier=verifier, resource="https://api.archhub.io/mcp")
    assert answer.status_code == 200, answer.text
    return browser, answer.json()["access_token"]


def test_the_email_link_token_is_no_account_token(mail):
    from tests.test_mcp_oauth import _browser
    import db
    _, token = _email_link_flow(mail)
    assert db.user_for_token(token) is None, "the ordinary account-token validator refuses the MCP client token"
    account = _browser()  # a client holding nothing but that token
    for method, path in (("GET", "/v1/me"), ("POST", "/v1/auth/refresh")):
        answer = account.request(method, path, headers={"Authorization": "Bearer " + token})
        assert answer.status_code == 401, (path, answer.status_code, answer.text)
    # Logout is idempotent for anyone; with this token it finds no account session to end.
    ended = account.post("/v1/auth/logout", headers={"Authorization": "Bearer " + token})
    assert ended.json().get("revoked") == 0, ended.text


def test_the_email_link_flow_leaves_no_account_session_in_the_browser(mail):
    import db
    browser, _ = _email_link_flow(mail)
    names = set(browser.cookies.keys())
    assert names <= {"__Host-archhub_mcp_founder"}, names  # only the signed MCP request-capacity lane, if any
    for value in browser.cookies.values():
        assert all(db.user_for_token(part) is None for part in [value, *value.split(".")]), "no cookie is an account token"
    assert browser.get("/v1/me").status_code == 401, "the browser it leaves is not signed in to an account"
    assert browser.get("/founder/api/actions").status_code in (302, 303, 401, 403), "nor to the founder cockpit"