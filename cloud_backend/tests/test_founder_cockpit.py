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
