"""Founder Cockpit (PHASE 5) — gating + real-data tests.

Locks the founder-only invariant:
  (a) a NON-founder authenticated user  -> 403 on every cockpit route
  (b) an UNAUTHENTICATED caller          -> 403 (no anonymous access)
  (c) the FOUNDER                        -> 200 + real keys present

Plus: the HTML page is gated + on-brand, and the data panels surface the
REAL stored numbers (a freshly-registered user shows up in the counts).
"""
from __future__ import annotations

import base64
import hashlib

import pytest


FOUNDER_EMAIL = "founder@archhub-cockpit-test.com"


@pytest.fixture(autouse=True)
def _set_founder(monkeypatch):
    # Pin a known founder email for the test so the gate is deterministic
    # regardless of the host env. require_founder reads this at call time.
    monkeypatch.setenv("FOUNDER_EMAIL", FOUNDER_EMAIL)
    import founder_cockpit
    founder_cockpit.clear_errors()
    yield


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app, raise_server_exceptions=False)


def _pkce_pair():
    import secrets
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def _sign_in(client, monkeypatch, email) -> str:
    """Register + exchange the magic-link flow and return a bearer token."""
    async def fake_send(**kw):
        return True
    import email_sender, db
    monkeypatch.setattr(email_sender, "send_magic_link", fake_send)
    verifier, challenge = _pkce_pair()
    r = client.post("/v1/auth/register",
                    json={"email": email, "code_challenge": challenge})
    assert r.status_code == 202, r.text
    u = db.get_user_by_email(email)
    assert u is not None
    with db.connect() as con:
        row = con.execute(
            "SELECT code FROM codes WHERE user_id = ?", (u["id"],)).fetchone()
    r2 = client.post("/v1/auth/exchange",
                     json={"code": row["code"], "code_verifier": verifier})
    assert r2.status_code == 200, r2.text
    return r2.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _cookie_client(value):
    """A TestClient that carries `founder_session=value` on every request.
    Driven over https:// so the Secure cookie is actually sent, and set on the
    client instance (not per-request) to avoid the ambiguous-persistence
    deprecation — this is the faithful real-browser shape."""
    from fastapi.testclient import TestClient
    import main
    c = TestClient(main.app, base_url="https://testserver",
                   raise_server_exceptions=False)
    c.cookies.set("founder_session", value)
    return c


COCKPIT_API = [
    "/founder/api/overview",
    "/founder/api/users",
    "/founder/api/subscriptions",
    "/founder/api/system",
    "/founder/api/usage",
    "/founder/api/errors",
]
COCKPIT_ALL = COCKPIT_API + ["/founder", "/founder/"]


# --- (b) unauthenticated -> 403 -------------------------------------------
class TestUnauthenticatedBlocked:
    @pytest.mark.parametrize("path", COCKPIT_ALL)
    def test_no_token_is_403(self, client, path):
        r = client.get(path)
        assert r.status_code == 403, (path, r.status_code)

    @pytest.mark.parametrize("path", COCKPIT_ALL)
    def test_garbage_token_is_403(self, client, path):
        r = client.get(path, headers=_auth("ah_live_not_a_real_token"))
        assert r.status_code == 403, (path, r.status_code)


# --- (a) non-founder authenticated -> 403 ---------------------------------
class TestNonFounderBlocked:
    @pytest.mark.parametrize("path", COCKPIT_ALL)
    def test_other_user_is_403(self, client, monkeypatch, path):
        token = _sign_in(client, monkeypatch, "someone.else@studio.com")
        # Sanity: this token works on a normal authed route.
        assert client.get("/v1/me", headers=_auth(token)).status_code == 200
        # But NOT on the cockpit.
        r = client.get(path, headers=_auth(token))
        assert r.status_code == 403, (path, r.status_code)


# --- (c) founder -> 200 + real keys present -------------------------------
class TestFounderAllowed:
    def test_overview_200_with_real_keys(self, client, monkeypatch):
        token = _sign_in(client, monkeypatch, FOUNDER_EMAIL)
        r = client.get("/founder/api/overview", headers=_auth(token))
        assert r.status_code == 200, r.text
        body = r.json()
        for key in ("users", "subscriptions", "system", "usage",
                    "errors", "generated_at"):
            assert key in body, key
        # Real numbers, not placeholders: the founder we just registered is
        # a real user, so total >= 1 and they appear in the by-plan counts.
        assert body["users"]["total"] >= 1
        assert isinstance(body["users"]["by_plan"], dict)
        assert sum(body["users"]["by_plan"].values()) == body["users"]["total"]
        # Subscriptions panel is the derived-MRR shape.
        subs = body["subscriptions"]
        assert subs["basis"] == "derived_from_stored_plans"
        assert subs["mrr_estimate"] >= 0
        # System panel surfaces version + health.
        assert body["system"]["healthz"]["ok"] is True
        assert body["system"]["version"]
        # Usage panel surfaces the real counters (zero is a real number).
        assert "chat_completions_total" in body["usage"]
        assert "memory_captures_total" in body["usage"]

    def test_users_panel_reflects_real_signup(self, client, monkeypatch):
        token = _sign_in(client, monkeypatch, FOUNDER_EMAIL)
        # Add another real user; the count must increase.
        _sign_in(client, monkeypatch, "extra.user@studio.com")
        r = client.get("/founder/api/users", headers=_auth(token))
        assert r.status_code == 200
        body = r.json()
        assert body["total"] >= 2
        emails = {u["email"] for u in body["recent"]}
        assert "extra.user@studio.com" in emails

    def test_subscriptions_mrr_from_paid_plan(self, client, monkeypatch):
        import db, config
        token = _sign_in(client, monkeypatch, FOUNDER_EMAIL)
        # Upgrade a real user to Solo -> MRR must reflect the Solo price.
        paid = db.get_user_by_email("paid@studio.com")
        if paid is None:
            _sign_in(client, monkeypatch, "paid@studio.com")
            paid = db.get_user_by_email("paid@studio.com")
        db.update_user_plan(paid["id"], plan="solo")
        r = client.get("/founder/api/subscriptions", headers=_auth(token))
        assert r.status_code == 200
        body = r.json()
        solo_price = float(config.PLANS["solo"]["price_per_seat"])
        assert body["mrr_estimate"] >= solo_price
        assert any(t["tier"] == "solo" for t in body["tiers"])

    def test_html_page_gated_and_onbrand(self, client, monkeypatch):
        # Unauth -> 403 on the HTML page (no anonymous dashboard).
        assert client.get("/founder").status_code == 403
        token = _sign_in(client, monkeypatch, FOUNDER_EMAIL)
        r = client.get("/founder", headers=_auth(token))
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        html = r.text
        # On-brand: terracotta accent + the two brand fonts, no emoji.
        assert "#d97757" in html
        assert "Instrument Serif" in html
        assert "Inter" in html
        assert "Founder" in html and "Cockpit" in html
        # Auto-refresh wired.
        assert "/founder/api/overview" in html
        assert "setInterval" in html


# --- cookie login (browser-openable cockpit) ------------------------------
class TestCookieLogin:
    """The browser path: GET /founder/login is ungated, POST /founder/login
    with a founder token mints a `founder_session` cookie, and that cookie
    then authenticates /founder exactly like the bearer header does."""

    def test_login_page_is_ungated_200(self, client):
        # (a) The login page must be reachable with NO auth at all.
        r = client.get("/founder/login")
        assert r.status_code == 200, r.text
        assert "text/html" in r.headers["content-type"]
        html = r.text
        # On-brand + the single token field + helper text, no token echoed.
        assert "#d97757" in html
        assert "Instrument Serif" in html and "Inter" in html
        assert 'type="password"' in html
        assert 'name="token"' in html
        assert "Settings -&gt; Account" in html or "Settings -> Account" in html

    def test_founder_post_sets_cookie_and_redirects(self, client, monkeypatch):
        # (b) POST with a FOUNDER token -> 303 + Set-Cookie founder_session.
        token = _sign_in(client, monkeypatch, FOUNDER_EMAIL)
        r = client.post("/founder/login", data={"token": token},
                        follow_redirects=False)
        assert r.status_code == 303, r.text
        assert r.headers.get("location") == "/founder"
        set_cookie = r.headers.get("set-cookie", "")
        assert "founder_session=" in set_cookie
        # Hardened cookie attributes.
        low = set_cookie.lower()
        assert "httponly" in low
        assert "secure" in low
        assert "samesite=lax" in low

    def test_founder_cookie_opens_cockpit_200(self, client, monkeypatch):
        # (c) With the founder cookie, GET /founder returns the real cockpit.
        token = _sign_in(client, monkeypatch, FOUNDER_EMAIL)
        bc = _cookie_client(token)
        r = bc.get("/founder")
        assert r.status_code == 200, r.text
        assert "text/html" in r.headers["content-type"]
        assert "Founder" in r.text and "Cockpit" in r.text
        # API routes share the same cookie gate.
        r2 = bc.get("/founder/api/overview")
        assert r2.status_code == 200, r2.text

    def test_full_browser_flow_post_then_get(self, client, monkeypatch):
        # End-to-end via the client's own cookie jar, exactly like a real
        # browser: POST login -> 303 -> GET /founder, then a fresh plain
        # GET /founder, all carrying the founder_session cookie automatically.
        # Driven over https:// because the cookie is Secure (as in production
        # behind Fly's TLS) — an http:// client would refuse to send it, which
        # is the correct hardening, not a bug.
        from fastapi.testclient import TestClient
        import main
        token = _sign_in(client, monkeypatch, FOUNDER_EMAIL)
        bc = TestClient(main.app, base_url="https://testserver",
                        raise_server_exceptions=False)
        rp = bc.post("/founder/login", data={"token": token})
        assert rp.status_code == 200  # followed 303 -> /founder
        assert "Cockpit" in rp.text
        rg = bc.get("/founder")  # cookie jar carries founder_session
        assert rg.status_code == 200
        assert "Cockpit" in rg.text

    def test_nonfounder_cookie_is_403(self, client, monkeypatch):
        # (d) A valid NON-founder token in the cookie -> still 403.
        token = _sign_in(client, monkeypatch, "intruder@studio.com")
        assert client.get("/v1/me", headers=_auth(token)).status_code == 200
        bc = _cookie_client(token)
        for path in ("/founder", "/founder/api/overview"):
            r = bc.get(path)
            assert r.status_code == 403, (path, r.status_code)

    def test_no_cookie_no_header_is_403(self, client):
        # (e) No cookie + no header -> 403 (the original bug must stay closed
        # for everything except the explicitly-ungated login routes).
        for path in ("/founder", "/founder/", "/founder/api/overview"):
            assert client.get(path).status_code == 403, path

    def test_header_auth_still_works(self, client, monkeypatch):
        # (f) The original Authorization: Bearer header path is unchanged.
        token = _sign_in(client, monkeypatch, FOUNDER_EMAIL)
        assert client.get("/founder", headers=_auth(token)).status_code == 200
        assert client.get("/founder/api/overview",
                          headers=_auth(token)).status_code == 200

    def test_garbage_cookie_is_403(self, client):
        # A bogus token in the cookie is treated identically to no token.
        r = _cookie_client("ah_live_garbage").get("/founder")
        assert r.status_code == 403

    def test_bad_post_token_rerenders_without_leak(self, client, monkeypatch):
        # POST with a non-founder/garbage token re-renders the login page (401)
        # and does NOT set a session cookie nor echo the token back.
        token = _sign_in(client, monkeypatch, "nope@studio.com")
        r = client.post("/founder/login", data={"token": token},
                        follow_redirects=False)
        assert r.status_code == 401, r.text
        assert "founder_session=" not in r.headers.get("set-cookie", "")
        assert token not in r.text  # never reflect the secret
        assert 'name="token"' in r.text  # but the form is shown again

    def test_logout_clears_cookie(self, client, monkeypatch):
        token = _sign_in(client, monkeypatch, FOUNDER_EMAIL)
        r = _cookie_client(token).get("/founder/logout", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers.get("location") == "/founder/login"
        # Cookie deletion is expressed as an expiry in the Set-Cookie header.
        sc = r.headers.get("set-cookie", "").lower()
        assert "founder_session=" in sc


# --- founder identity / gate internals ------------------------------------
class TestGateInternals:
    def test_default_founder_email_constant(self):
        import founder_cockpit
        assert founder_cockpit.DEFAULT_FOUNDER_EMAIL == "ahmedfargale@gmail.com"

    def test_founder_email_env_override(self, monkeypatch):
        import founder_cockpit
        monkeypatch.setenv("FOUNDER_EMAIL", "Override@Example.COM")
        assert founder_cockpit.founder_email() == "override@example.com"

    def test_error_ring_records_and_caps(self):
        import founder_cockpit
        founder_cockpit.clear_errors()
        for i in range(150):
            founder_cockpit.record_error(
                where="/x", kind="K", message=f"m{i}", status=500)
        errs = founder_cockpit.recent_errors(500)
        # Bounded ring (maxlen 100) + newest first.
        assert len(errs) == 100
        assert errs[0]["message"] == "m149"
