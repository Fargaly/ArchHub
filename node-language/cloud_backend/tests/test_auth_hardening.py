"""Auth/registration security hardening — real behavior tests.

One test (or cluster) per confirmed gap, asserting the ACTUAL security
property, not just that code imports:

  Gap 1  token-expiry-401  — a token past expires_at fails /v1/me with 401.
  Gap 2  logout-revokes    — POST /v1/auth/logout kills the token (then 401).
  Gap 3  pkce-challenged-requires-verifier — a code issued WITH a challenge
                              cannot be exchanged with an empty/wrong verifier;
                              browser-direct (empty challenge) still works.
  Gap 4  env-prod-fails-loud — ENV=production + a missing key → startup raises
                              naming the key; /healthz design preserved.
  Gap 5  email-fail-loud   — ENV=production + no RESEND_API_KEY → send returns
                              False (→ /register 502), never a silent 202.

Gap 6 (stop committing the live DB) is a git-tracking change, not a runtime
behavior — verified out-of-band (see the task report); nothing to assert here.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import secrets
import time

import pytest


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app)


def _pkce_pair():
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def _stub_email(monkeypatch):
    async def fake_send(**kw):
        return True
    import email_sender
    monkeypatch.setattr(email_sender, "send_magic_link", fake_send)


def _code_for(user_id: str) -> str:
    import db
    with db.connect() as con:
        row = con.execute(
            "SELECT code FROM codes WHERE user_id = ? "
            "ORDER BY rowid DESC LIMIT 1",
            (user_id,),
        ).fetchone()
    return row["code"]


def _register_and_token(client, monkeypatch, email):
    """Full register→exchange via the PKCE (desktop) path. Returns token."""
    _stub_email(monkeypatch)
    import db
    verifier, challenge = _pkce_pair()
    r = client.post("/v1/auth/register",
                    json={"email": email, "code_challenge": challenge})
    assert r.status_code == 202
    u = db.get_user_by_email(email)
    code = _code_for(u["id"])
    r2 = client.post("/v1/auth/exchange",
                     json={"code": code, "code_verifier": verifier})
    assert r2.status_code == 200
    return r2.json()["token"]


# ===========================================================================
# Gap 1 — Server-side token expiry (immortal tokens closed)
# ===========================================================================
class TestTokenExpiry:
    def test_schema_has_expires_at(self):
        import db
        with db.connect() as con:
            cols = {r["name"] for r in con.execute(
                "PRAGMA table_info(tokens)").fetchall()}
        assert "expires_at" in cols

    def test_issue_token_sets_real_future_expiry(self):
        import db
        u = db.get_or_create_user("exp-issue@studio.com")
        before = int(time.time())
        token = db.issue_token(u["id"])
        with db.connect() as con:
            row = con.execute(
                "SELECT expires_at FROM tokens WHERE token = ?",
                (token,)).fetchone()
        assert row["expires_at"] is not None
        # ~90 days out (allow a few seconds of test drift).
        assert row["expires_at"] >= before + db.TOKEN_TTL_SECONDS - 5

    def test_fresh_token_authenticates(self):
        import db
        u = db.get_or_create_user("exp-fresh@studio.com")
        token = db.issue_token(u["id"])
        found = db.user_for_token(token)
        assert found is not None and found["id"] == u["id"]

    def test_expired_token_fails_user_for_token(self):
        """Simulate a token already past expiry → user_for_token returns
        None (the JOIN's expires_at>now clause drops it)."""
        import db
        u = db.get_or_create_user("exp-dead@studio.com")
        token = db.issue_token(u["id"])
        # Force the row into the past.
        with db.connect() as con:
            con.execute(
                "UPDATE tokens SET expires_at = ? WHERE token = ?",
                (int(time.time()) - 1, token))
        assert db.user_for_token(token) is None

    def test_expired_token_401_on_me(self, client, monkeypatch):
        """End-to-end: a real signed-in token, expired, → /v1/me 401."""
        import db
        token = _register_and_token(client, monkeypatch, "exp-e2e@studio.com")
        # Valid right now.
        ok = client.get("/v1/me",
                        headers={"Authorization": f"Bearer {token}"})
        assert ok.status_code == 200
        # Push expiry into the past → must now 401.
        with db.connect() as con:
            con.execute("UPDATE tokens SET expires_at = ? WHERE token = ?",
                        (int(time.time()) - 10, token))
        dead = client.get("/v1/me",
                          headers={"Authorization": f"Bearer {token}"})
        assert dead.status_code == 401

    def test_backfill_gives_null_expiry_a_real_one(self):
        """A legacy row with NULL expires_at (pre-migration immortal token)
        is backfilled to created_at + TTL by init_schema, and meanwhile a
        NULL-expiry row does NOT authenticate."""
        import db
        u = db.get_or_create_user("exp-legacy@studio.com")
        token = db.issue_token(u["id"])
        created = int(time.time()) - 1000
        with db.connect() as con:
            con.execute(
                "UPDATE tokens SET expires_at = NULL, created_at = ? "
                "WHERE token = ?", (created, token))
        # Defensive: a NULL-expiry row must not authenticate.
        assert db.user_for_token(token) is None
        # Re-running the migration backfills it.
        db.init_schema()
        with db.connect() as con:
            row = con.execute(
                "SELECT expires_at FROM tokens WHERE token = ?",
                (token,)).fetchone()
        assert row["expires_at"] == created + db.TOKEN_TTL_SECONDS

    def test_client_expiry_matches_server_ttl(self, client, monkeypatch):
        """auth payload's expires_at agrees with the server-enforced TTL —
        no drift between client cache and server gate."""
        import db
        _stub_email(monkeypatch)
        verifier, challenge = _pkce_pair()
        client.post("/v1/auth/register",
                    json={"email": "exp-agree@studio.com",
                          "code_challenge": challenge})
        u = db.get_user_by_email("exp-agree@studio.com")
        code = _code_for(u["id"])
        now = int(time.time())
        body = client.post("/v1/auth/exchange",
                           json={"code": code,
                                 "code_verifier": verifier}).json()
        # Payload horizon within a few seconds of now+TTL.
        assert abs(body["expires_at"] - (now + db.TOKEN_TTL_SECONDS)) <= 5


# ===========================================================================
# Gap 2 — Revocation + /v1/auth/logout
# ===========================================================================
class TestLogoutRevocation:
    def test_delete_token_dao(self):
        import db
        u = db.get_or_create_user("rev-one@studio.com")
        t = db.issue_token(u["id"])
        assert db.user_for_token(t) is not None
        assert db.delete_token(t) is True
        assert db.user_for_token(t) is None
        # Idempotent: deleting an already-gone token returns False.
        assert db.delete_token(t) is False

    def test_delete_tokens_for_user_dao(self):
        import db
        u = db.get_or_create_user("rev-all@studio.com")
        t1, t2, t3 = (db.issue_token(u["id"]) for _ in range(3))
        removed = db.delete_tokens_for_user(u["id"])
        assert removed == 3
        for t in (t1, t2, t3):
            assert db.user_for_token(t) is None

    def test_logout_endpoint_revokes_current_token(self, client, monkeypatch):
        token = _register_and_token(client, monkeypatch, "rev-ep@studio.com")
        # Works before logout.
        assert client.get(
            "/v1/me", headers={"Authorization": f"Bearer {token}"}
        ).status_code == 200
        # Logout → 200 {ok:true}.
        out = client.post("/v1/auth/logout",
                          headers={"Authorization": f"Bearer {token}"})
        assert out.status_code == 200
        assert out.json()["ok"] is True
        assert out.json()["revoked"] == 1
        # Token is now dead → 401.
        assert client.get(
            "/v1/me", headers={"Authorization": f"Bearer {token}"}
        ).status_code == 401

    def test_logout_requires_bearer(self, client):
        r = client.post("/v1/auth/logout")
        assert r.status_code == 401

    def test_logout_all_sessions_revokes_every_token(self, client, monkeypatch):
        """all_sessions:true kills sibling tokens too."""
        import db
        token = _register_and_token(client, monkeypatch, "rev-multi@studio.com")
        u = db.get_user_by_email("rev-multi@studio.com")
        sibling = db.issue_token(u["id"])  # a second device
        out = client.post("/v1/auth/logout",
                          headers={"Authorization": f"Bearer {token}"},
                          json={"all_sessions": True})
        assert out.status_code == 200
        assert out.json()["revoked"] >= 2
        # Both the caller token and the sibling are dead.
        assert db.user_for_token(token) is None
        assert db.user_for_token(sibling) is None

    def test_logout_single_does_not_touch_other_sessions(self, client, monkeypatch):
        import db
        token = _register_and_token(client, monkeypatch, "rev-keep@studio.com")
        u = db.get_user_by_email("rev-keep@studio.com")
        sibling = db.issue_token(u["id"])
        # Default logout (no body) revokes only the caller token.
        client.post("/v1/auth/logout",
                    headers={"Authorization": f"Bearer {token}"})
        assert db.user_for_token(token) is None
        # Sibling still valid.
        assert db.user_for_token(sibling) is not None


# ===========================================================================
# Gap 3 — PKCE bypass closed for the desktop client
# ===========================================================================
class TestPkceEnforcement:
    def test_challenged_code_rejects_empty_verifier_dao(self):
        """db.consume_code: a code issued WITH a challenge cannot be
        consumed with an empty verifier."""
        import db
        u = db.get_or_create_user("pkce-empty@studio.com")
        _, challenge = _pkce_pair()
        code = db.issue_code(u["id"], challenge)
        assert db.consume_code(code, "") is None
        # And the code was burned (single attempt).
        assert db.consume_code(code, "anything-at-all") is None

    def test_challenged_code_rejects_wrong_verifier_dao(self):
        import db
        u = db.get_or_create_user("pkce-wrong@studio.com")
        _, challenge = _pkce_pair()
        code = db.issue_code(u["id"], challenge)
        assert db.consume_code(code, "x" * 50) is None

    def test_challenged_code_accepts_matching_verifier_dao(self):
        import db
        u = db.get_or_create_user("pkce-ok@studio.com")
        verifier, challenge = _pkce_pair()
        code = db.issue_code(u["id"], challenge)
        assert db.consume_code(code, verifier) == u["id"]

    def test_exchange_endpoint_rejects_challenged_code_empty_verifier(
            self, client, monkeypatch):
        """End-to-end: a challenged code + empty verifier → 400, no token."""
        import db
        _stub_email(monkeypatch)
        _, challenge = _pkce_pair()
        client.post("/v1/auth/register",
                    json={"email": "pkce-ep@studio.com",
                          "code_challenge": challenge})
        u = db.get_user_by_email("pkce-ep@studio.com")
        code = _code_for(u["id"])
        r = client.post("/v1/auth/exchange",
                        json={"code": code, "code_verifier": ""})
        assert r.status_code == 400
        assert "token" not in r.json()

    def test_exchange_rejects_short_verifier_422(self, client, monkeypatch):
        """A supplied-but-too-short verifier is rejected (restored
        min_length floor) before even hitting the code lookup."""
        import db
        _stub_email(monkeypatch)
        _, challenge = _pkce_pair()
        client.post("/v1/auth/register",
                    json={"email": "pkce-short@studio.com",
                          "code_challenge": challenge})
        u = db.get_user_by_email("pkce-short@studio.com")
        code = _code_for(u["id"])
        r = client.post("/v1/auth/exchange",
                        json={"code": code, "code_verifier": "tooshort"})
        assert r.status_code == 422

    def test_browser_direct_empty_challenge_still_works_dao(self):
        """The deliberately-preserved magic-link floor: a code issued with
        an EMPTY challenge consumes fine with an empty verifier."""
        import db
        u = db.get_or_create_user("browser-direct@studio.com")
        code = db.issue_code(u["id"], "")   # browser-direct: no PKCE
        assert db.consume_code(code, "") == u["id"]

    def test_browser_direct_exchange_endpoint_works(self, client, monkeypatch):
        """End-to-end browser-direct: register with empty challenge, then
        exchange with empty verifier → 200 + token."""
        import db
        _stub_email(monkeypatch)
        r = client.post("/v1/auth/register",
                        json={"email": "browser-ep@studio.com",
                              "code_challenge": ""})
        assert r.status_code == 202
        u = db.get_user_by_email("browser-ep@studio.com")
        code = _code_for(u["id"])
        ex = client.post("/v1/auth/exchange",
                         json={"code": code, "code_verifier": ""})
        assert ex.status_code == 200
        assert ex.json()["token"].startswith("ah_live_")

    def test_expired_code_rejected(self):
        import db
        u = db.get_or_create_user("pkce-expired@studio.com")
        verifier, challenge = _pkce_pair()
        code = db.issue_code(u["id"], challenge, ttl_seconds=300)
        with db.connect() as con:
            con.execute("UPDATE codes SET expires_at = ? WHERE code = ?",
                        (int(time.time()) - 1, code))
        assert db.consume_code(code, verifier) is None


# ===========================================================================
# Gap 4 — ENV=production key enforcement fails loud
# ===========================================================================
class TestProductionReadinessGate:
    def test_no_env_is_noop(self, monkeypatch):
        """ENV unset → gate does nothing even with all keys empty."""
        monkeypatch.delenv("ENV", raising=False)
        import importlib
        import config
        importlib.reload(config)
        # Should NOT raise.
        config.assert_production_ready()

    def test_production_missing_keys_raises_naming_them(self, monkeypatch):
        monkeypatch.setenv("ENV", "production")
        # Ensure the auth-critical key is unset.
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("RESEND_API_KEY", raising=False)
        monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
        import importlib
        import config
        importlib.reload(config)
        with pytest.raises(RuntimeError) as exc:
            config.assert_production_ready()
        msg = str(exc.value)
        # The error names the actual missing keys (not a generic message).
        assert "ANTHROPIC_API_KEY" in msg
        assert "RESEND_API_KEY" in msg
        assert "STRIPE_SECRET_KEY" in msg

    def test_production_all_keys_present_passes(self, monkeypatch):
        monkeypatch.setenv("ENV", "production")
        for k in ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET",
                  "STRIPE_PRICE_SOLO", "STRIPE_PRICE_STUDIO",
                  "STRIPE_PRICE_FIRM", "ANTHROPIC_API_KEY",
                  "OPENAI_API_KEY", "GOOGLE_API_KEY", "RESEND_API_KEY"):
            monkeypatch.setenv(k, "set-for-test")
        import importlib
        import config
        importlib.reload(config)
        # All required present → no raise.
        config.assert_production_ready()

    def test_import_never_raises_even_in_production(self, monkeypatch):
        """The gate, not import, is the failure point — `import config`
        must succeed in production with missing keys so /healthz stays
        reachable. (Regression guard for the import-time-crash failure.)"""
        monkeypatch.setenv("ENV", "production")
        monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
        import importlib
        import config
        # Reload must not raise despite ENV=production + missing key.
        importlib.reload(config)
        assert config.is_production() is True

    def test_polar_provider_requires_polar_keys(self, monkeypatch):
        """When BILLING_PROVIDER=polar, the gate demands the Polar keys,
        not the Stripe ones."""
        monkeypatch.setenv("ENV", "production")
        monkeypatch.setenv("BILLING_PROVIDER", "polar")
        # Provide auth/email so only billing is missing.
        for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY",
                  "GOOGLE_API_KEY", "RESEND_API_KEY"):
            monkeypatch.setenv(k, "x")
        for k in ("POLAR_ACCESS_TOKEN", "POLAR_WEBHOOK_SECRET",
                  "POLAR_PRODUCT_SOLO", "POLAR_PRODUCT_STUDIO",
                  "POLAR_PRODUCT_FIRM"):
            monkeypatch.delenv(k, raising=False)
        import importlib
        import config
        importlib.reload(config)
        with pytest.raises(RuntimeError) as exc:
            config.assert_production_ready()
        assert "POLAR_ACCESS_TOKEN" in str(exc.value)


# ===========================================================================
# Gap 5 — Magic-link delivery fails loud in production
# ===========================================================================
class TestEmailFailsLoud:
    def test_dev_no_key_logs_and_returns_true(self, monkeypatch, capsys):
        """Dev (ENV unset) with no key → stdout stub, returns True so
        local sign-in flows. Log is tagged so it's unmistakable."""
        monkeypatch.delenv("ENV", raising=False)
        import importlib
        import config
        import email_sender
        importlib.reload(config)
        importlib.reload(email_sender)
        monkeypatch.setattr(config, "RESEND_API_KEY", "")
        ok = asyncio.run(email_sender._send(
            to="dev@studio.com", subject="hi", text="t", html="<p>t</p>"))
        assert ok is True
        out = capsys.readouterr().out
        assert "NOT actually sent" in out

    def test_production_no_key_returns_false(self, monkeypatch, capsys):
        """Production with no RESEND_API_KEY → send returns FALSE (never a
        silent success)."""
        monkeypatch.setenv("ENV", "production")
        import importlib
        import config
        import email_sender
        importlib.reload(config)
        importlib.reload(email_sender)
        monkeypatch.setattr(config, "RESEND_API_KEY", "")
        ok = asyncio.run(email_sender._send(
            to="prod@studio.com", subject="hi", text="t", html="<p>t</p>"))
        assert ok is False
        out = capsys.readouterr().out
        assert "ABORTED" in out

    def test_register_502_when_email_undeliverable_in_prod(
            self, client, monkeypatch):
        """End-to-end: ENV=production + no key → /register is NOT a silent
        202; the False from _send becomes a 502 email_send_failed."""
        import importlib
        import config
        import email_sender
        monkeypatch.setenv("ENV", "production")
        importlib.reload(config)
        importlib.reload(email_sender)
        monkeypatch.setattr(config, "RESEND_API_KEY", "")
        _, challenge = _pkce_pair()
        r = client.post("/v1/auth/register",
                        json={"email": "undeliv@studio.com",
                              "code_challenge": challenge})
        assert r.status_code == 502
        assert r.json()["detail"] == "email_send_failed"
