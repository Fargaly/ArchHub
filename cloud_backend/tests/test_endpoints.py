"""End-to-end HTTP tests via FastAPI TestClient."""
from __future__ import annotations

import base64
import hashlib

import pytest


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app)


def _pkce_pair():
    import secrets
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


class TestHealthCheck:
    def test_healthz(self, client):
        r = client.get("/healthz")
        assert r.status_code == 200
        assert r.json()["ok"] is True


class TestAuthFlow:
    def test_register_accepts_valid_email(self, client, monkeypatch):
        # Stub the email send so we don't need RESEND_API_KEY.
        async def fake_send(**kw):
            return True
        import email_sender
        monkeypatch.setattr(email_sender, "send_magic_link", fake_send)
        _, challenge = _pkce_pair()
        r = client.post("/v1/auth/register", json={
            "email": "test@studio.com",
            "code_challenge": challenge,
        })
        assert r.status_code == 202

    def test_register_rejects_bad_email(self, client):
        r = client.post("/v1/auth/register", json={
            "email": "not-an-email",
            "code_challenge": "x" * 30,
        })
        assert r.status_code == 422   # pydantic EmailStr fail

    def test_full_register_then_exchange(self, client, monkeypatch):
        async def fake_send(**kw):
            return True
        import email_sender, db
        monkeypatch.setattr(email_sender, "send_magic_link", fake_send)
        verifier, challenge = _pkce_pair()
        r = client.post("/v1/auth/register", json={
            "email": "flow@studio.com",
            "code_challenge": challenge,
        })
        assert r.status_code == 202
        # Pull the freshly-issued code out of the DB (simulates the
        # magic-link click).
        u = db.get_user_by_email("flow@studio.com")
        assert u is not None
        with db.connect() as con:
            row = con.execute(
                "SELECT code FROM codes WHERE user_id = ?",
                (u["id"],)
            ).fetchone()
        assert row is not None
        r2 = client.post("/v1/auth/exchange", json={
            "code": row["code"],
            "code_verifier": verifier,
        })
        assert r2.status_code == 200
        body = r2.json()
        assert body["token"].startswith("ah_live_")
        assert body["plan"] == "trial"
        assert body["expires_at"] > 0

    def test_exchange_with_bad_verifier_rejected(self, client, monkeypatch):
        async def fake_send(**kw):
            return True
        import email_sender, db
        monkeypatch.setattr(email_sender, "send_magic_link", fake_send)
        _, challenge = _pkce_pair()
        client.post("/v1/auth/register", json={
            "email": "badverifier@studio.com",
            "code_challenge": challenge,
        })
        u = db.get_user_by_email("badverifier@studio.com")
        with db.connect() as con:
            row = con.execute(
                "SELECT code FROM codes WHERE user_id = ?",
                (u["id"],)
            ).fetchone()
        r = client.post("/v1/auth/exchange", json={
            "code": row["code"],
            "code_verifier": "completely-wrong-verifier-value-but-long-enough",
        })
        assert r.status_code == 400


class TestMeEndpoint:
    def _signed_in(self, client, monkeypatch, email):
        async def fake_send(**kw):
            return True
        import email_sender, db
        monkeypatch.setattr(email_sender, "send_magic_link", fake_send)
        verifier, challenge = _pkce_pair()
        client.post("/v1/auth/register",
                     json={"email": email, "code_challenge": challenge})
        u = db.get_user_by_email(email)
        with db.connect() as con:
            row = con.execute(
                "SELECT code FROM codes WHERE user_id = ?",
                (u["id"],)
            ).fetchone()
        r = client.post("/v1/auth/exchange", json={
            "code": row["code"],
            "code_verifier": verifier,
        })
        return r.json()["token"]

    def test_me_requires_auth(self, client):
        r = client.get("/v1/me")
        assert r.status_code == 401

    def test_me_with_invalid_token(self, client):
        r = client.get("/v1/me",
                        headers={"Authorization": "Bearer wrong"})
        assert r.status_code == 401

    def test_me_returns_plan_and_quota(self, client, monkeypatch):
        token = self._signed_in(client, monkeypatch, "me@studio.com")
        r = client.get("/v1/me",
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        body = r.json()
        assert body["email"] == "me@studio.com"
        assert body["plan"] == "trial"
        assert body["remaining_messages"] > 0


class TestBilling:
    def test_checkout_requires_auth(self, client):
        r = client.post("/v1/billing/checkout", json={"tier": "solo"})
        assert r.status_code == 401

    def test_checkout_unknown_tier_rejected(self, client, monkeypatch):
        async def fake_send(**kw): return True
        import email_sender, db
        monkeypatch.setattr(email_sender, "send_magic_link", fake_send)
        verifier, challenge = _pkce_pair()
        client.post("/v1/auth/register",
                     json={"email": "bill@studio.com", "code_challenge": challenge})
        u = db.get_user_by_email("bill@studio.com")
        with db.connect() as con:
            row = con.execute(
                "SELECT code FROM codes WHERE user_id = ?",
                (u["id"],)
            ).fetchone()
        token = client.post("/v1/auth/exchange", json={
            "code": row["code"], "code_verifier": verifier,
        }).json()["token"]
        r = client.post("/v1/billing/checkout", json={"tier": "enterprise"},
                          headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 400


class TestSigninLanding:
    def test_signin_page_renders(self, client):
        r = client.get("/signin?challenge=abc123&redirect=http://127.0.0.1:5555/cb")
        assert r.status_code == 200
        assert "Sign in" in r.text
        assert "abc123" in r.text
        assert "127.0.0.1:5555" in r.text


class TestAuthReturn:
    def test_redirects_to_desktop_with_code(self, client):
        r = client.get(
            "/auth/return?code=test_code&redirect=http://127.0.0.1:5555/cb",
            follow_redirects=False,
        )
        assert r.status_code == 302
        assert "127.0.0.1:5555/cb" in r.headers["location"]
        assert "code=test_code" in r.headers["location"]

    def test_no_redirect_shows_confirmation(self, client):
        r = client.get("/auth/return?code=test_code")
        assert r.status_code == 200
        assert "signed in" in r.text.lower()


class TestDashboardPage:
    """Customer admin dashboard — GET /dashboard (roadmap #P2)."""

    def test_dashboard_renders(self, client):
        r = client.get("/dashboard")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "Your ArchHub account" in r.text

    def test_dashboard_reads_account_endpoints(self, client):
        # The page is self-contained — it drives the existing account
        # APIs client-side rather than adding new ones.
        r = client.get("/dashboard")
        for endpoint in ("/v1/auth/exchange", "/v1/me",
                          "/v1/companies/mine"):
            assert endpoint in r.text
