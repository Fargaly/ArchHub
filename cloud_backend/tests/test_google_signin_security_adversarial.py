"""ADVERSARIAL security verification of Sign in with Google.

Monkeypatches Google's HTTP endpoints (token + tokeninfo) so we can mint
arbitrary id_token claims and forge / tamper the OAuth round-trip, then
drives the REAL FastAPI app via TestClient. Each test asserts a security
property MUST hold:

  (1) id_token with email_verified=false  → REJECTED (no code issued)
  (2) id_token with aud != client_id      → REJECTED
  (3) expired id_token                     → REJECTED
  (4) callback with missing/forged/mismatched state → REJECTED (CSRF)
  (5) client SECRET never in any client-facing response or start auth_url
  (6) the existing magic-link + exchange flow STILL works unchanged

These are written to FAIL if the implementation regresses (e.g. trusts an
unverified email, skips aud check, accepts a forged state, leaks secret).
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import urllib.parse

import pytest


# The fake OAuth client credentials used for the whole module. The SECRET
# is a recognisable sentinel so leak-detection is unambiguous.
_FAKE_CLIENT_ID = "test-client-id.apps.googleusercontent.com"
_FAKE_CLIENT_SECRET = "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182734650"


@pytest.fixture
def google_enabled(monkeypatch):
    """Turn Google login ON with fake creds. Patches config module-level
    constants (the live code reads config.GOOGLE_OAUTH_CLIENT_ID etc.) and
    google_login_enabled() returns True since both are set."""
    import config
    monkeypatch.setattr(config, "GOOGLE_OAUTH_CLIENT_ID", _FAKE_CLIENT_ID)
    monkeypatch.setattr(config, "GOOGLE_OAUTH_CLIENT_SECRET", _FAKE_CLIENT_SECRET)
    monkeypatch.setattr(config, "GOOGLE_OAUTH_REDIRECT",
                        "https://app.example.com/v1/auth/google/callback")
    monkeypatch.setattr(config, "PUBLIC_URL", "https://app.example.com")
    assert config.google_login_enabled() is True
    return config


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import main
    # Do not follow the 302 to /auth/return — we want to inspect the
    # redirect Location itself (it carries the one-time code).
    return TestClient(main.app, follow_redirects=False)


class FakeResp:
    """Minimal stand-in for an httpx.Response."""
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _install_fake_google(monkeypatch, *, token_payload, token_status=200,
                         tokeninfo_payload=None, tokeninfo_status=200):
    """Monkeypatch google_auth.httpx.post (token endpoint) and
    google_auth.httpx.get (tokeninfo) so NO real network call happens and
    we fully control what 'Google' returns.

    Records every outbound call (url, data/params) so leak tests can prove
    the secret only ever goes to the token endpoint."""
    import google_auth
    calls = {"post": [], "get": []}

    def fake_post(url, data=None, headers=None, timeout=None, **kw):
        calls["post"].append({"url": url, "data": data or {}})
        return FakeResp(token_status, token_payload)

    def fake_get(url, params=None, headers=None, timeout=None, **kw):
        calls["get"].append({"url": url, "params": params or {}})
        return FakeResp(tokeninfo_status, tokeninfo_payload)

    monkeypatch.setattr(google_auth.httpx, "post", fake_post)
    monkeypatch.setattr(google_auth.httpx, "get", fake_get)
    return calls


def _valid_claims(**over):
    """A claims dict that PASSES every assertion unless overridden."""
    base = {
        "iss": "https://accounts.google.com",
        "aud": _FAKE_CLIENT_ID,
        "exp": int(time.time()) + 3600,
        "email": "founder@studio.com",
        "email_verified": "true",
    }
    base.update(over)
    return base


def _good_state(monkeypatch=None, *, code_challenge="", redirect=""):
    """Build a genuine signed state via the real encode_state (uses the
    fake secret, since google_enabled patched config first)."""
    import google_auth
    return google_auth.encode_state(code_challenge=code_challenge,
                                    redirect=redirect)


def _pkce_pair():
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


# ===========================================================================
# (1) email_verified=false  → REJECTED
# ===========================================================================
class TestEmailVerifiedFalseRejected:
    def test_callback_rejects_unverified_email_bool_false(
            self, client, google_enabled, monkeypatch):
        calls = _install_fake_google(
            monkeypatch,
            token_payload={"id_token": "fake.jwt.token"},
            tokeninfo_payload=_valid_claims(email_verified=False),
        )
        state = _good_state()
        r = client.get("/v1/auth/google/callback",
                       params={"code": "g-auth-code", "state": state})
        # Must be 401 and NOT a 302 redirect carrying a code.
        assert r.status_code == 401, r.text
        assert r.json()["detail"]["error"] == "email_unverified"

    def test_callback_rejects_unverified_email_string_false(
            self, client, google_enabled, monkeypatch):
        _install_fake_google(
            monkeypatch,
            token_payload={"id_token": "fake.jwt.token"},
            tokeninfo_payload=_valid_claims(email_verified="false"),
        )
        r = client.get("/v1/auth/google/callback",
                       params={"code": "g-auth-code", "state": _good_state()})
        assert r.status_code == 401
        assert r.json()["detail"]["error"] == "email_unverified"

    def test_no_code_or_user_created_for_unverified(
            self, client, google_enabled, monkeypatch):
        """The deepest property: an unverified token mints NO one-time code
        and creates NO user row."""
        import db
        _install_fake_google(
            monkeypatch,
            token_payload={"id_token": "fake.jwt.token"},
            tokeninfo_payload=_valid_claims(
                email="attacker@evil.com", email_verified=False),
        )
        before = db.get_user_by_email("attacker@evil.com")
        r = client.get("/v1/auth/google/callback",
                       params={"code": "x", "state": _good_state()})
        assert r.status_code == 401
        # No user created.
        assert db.get_user_by_email("attacker@evil.com") is None
        assert before is None

    def test_verify_id_token_unit_raises_on_unverified(
            self, google_enabled, monkeypatch):
        import google_auth
        with pytest.raises(google_auth.GoogleAuthError) as exc:
            google_auth._assert_claims(_valid_claims(email_verified=False))
        assert exc.value.status == 401
        assert exc.value.code == "email_unverified"

    def test_missing_email_verified_key_rejected(
            self, client, google_enabled, monkeypatch):
        """Absent email_verified (not just false) must also be rejected —
        default-deny, never default-trust."""
        claims = _valid_claims()
        claims.pop("email_verified")
        _install_fake_google(
            monkeypatch,
            token_payload={"id_token": "fake.jwt.token"},
            tokeninfo_payload=claims,
        )
        r = client.get("/v1/auth/google/callback",
                       params={"code": "x", "state": _good_state()})
        assert r.status_code == 401
        assert r.json()["detail"]["error"] == "email_unverified"


# ===========================================================================
# (2) aud != GOOGLE_OAUTH_CLIENT_ID  → REJECTED
# ===========================================================================
class TestAudienceMismatchRejected:
    def test_callback_rejects_wrong_aud(
            self, client, google_enabled, monkeypatch):
        _install_fake_google(
            monkeypatch,
            token_payload={"id_token": "fake.jwt.token"},
            tokeninfo_payload=_valid_claims(
                aud="ATTACKER-other-client.apps.googleusercontent.com"),
        )
        r = client.get("/v1/auth/google/callback",
                       params={"code": "x", "state": _good_state()})
        assert r.status_code == 401, r.text
        assert r.json()["detail"]["error"] == "bad_audience"

    def test_empty_aud_rejected(self, google_enabled, monkeypatch):
        import google_auth
        with pytest.raises(google_auth.GoogleAuthError) as exc:
            google_auth._assert_claims(_valid_claims(aud=""))
        assert exc.value.code == "bad_audience"

    def test_aud_substring_not_accepted(self, google_enabled, monkeypatch):
        """A near-miss (prefix of the real id) must NOT pass — constant-time
        full compare, no startswith / substring acceptance."""
        import google_auth
        with pytest.raises(google_auth.GoogleAuthError) as exc:
            google_auth._assert_claims(
                _valid_claims(aud=_FAKE_CLIENT_ID[:-5]))
        assert exc.value.code == "bad_audience"

    def test_no_user_created_for_wrong_aud(
            self, client, google_enabled, monkeypatch):
        import db
        _install_fake_google(
            monkeypatch,
            token_payload={"id_token": "fake.jwt.token"},
            tokeninfo_payload=_valid_claims(
                email="wrongaud@evil.com", aud="someone-else.googleusercontent.com"),
        )
        client.get("/v1/auth/google/callback",
                   params={"code": "x", "state": _good_state()})
        assert db.get_user_by_email("wrongaud@evil.com") is None


# ===========================================================================
# (3) expired id_token  → REJECTED
# ===========================================================================
class TestExpiredTokenRejected:
    def test_callback_rejects_expired_token(
            self, client, google_enabled, monkeypatch):
        _install_fake_google(
            monkeypatch,
            token_payload={"id_token": "fake.jwt.token"},
            tokeninfo_payload=_valid_claims(exp=int(time.time()) - 60),
        )
        r = client.get("/v1/auth/google/callback",
                       params={"code": "x", "state": _good_state()})
        assert r.status_code == 401, r.text
        assert r.json()["detail"]["error"] == "id_token_expired"

    def test_exp_exactly_now_rejected(self, google_enabled, monkeypatch):
        """exp == now must fail (the check is exp <= now)."""
        import google_auth
        now = int(time.time())
        with pytest.raises(google_auth.GoogleAuthError) as exc:
            google_auth._assert_claims(_valid_claims(exp=now), now=now)
        assert exc.value.code == "id_token_expired"

    def test_missing_exp_rejected(self, google_enabled, monkeypatch):
        import google_auth
        claims = _valid_claims()
        claims.pop("exp")
        with pytest.raises(google_auth.GoogleAuthError) as exc:
            google_auth._assert_claims(claims)
        assert exc.value.code == "id_token_expired"

    def test_garbage_exp_rejected(self, google_enabled, monkeypatch):
        import google_auth
        with pytest.raises(google_auth.GoogleAuthError) as exc:
            google_auth._assert_claims(_valid_claims(exp="not-a-number"))
        assert exc.value.code == "id_token_expired"


# ===========================================================================
# (4) missing / forged / mismatched state  → REJECTED (CSRF)
# ===========================================================================
class TestStateCsrfRejected:
    def test_missing_state_rejected(
            self, client, google_enabled, monkeypatch):
        # token/tokeninfo would PASS if reached — proves state gate fires FIRST.
        _install_fake_google(
            monkeypatch,
            token_payload={"id_token": "fake.jwt.token"},
            tokeninfo_payload=_valid_claims(),
        )
        r = client.get("/v1/auth/google/callback",
                       params={"code": "x", "state": ""})
        assert r.status_code == 400, r.text
        assert r.json()["detail"]["error"] == "invalid_state"

    def test_forged_state_random_garbage_rejected(
            self, client, google_enabled, monkeypatch):
        _install_fake_google(
            monkeypatch,
            token_payload={"id_token": "fake.jwt.token"},
            tokeninfo_payload=_valid_claims(),
        )
        r = client.get("/v1/auth/google/callback",
                       params={"code": "x", "state": "totally.garbage"})
        assert r.status_code == 400
        assert r.json()["detail"]["error"] == "invalid_state"

    def test_tampered_payload_keeps_old_sig_rejected(
            self, client, google_enabled, monkeypatch):
        """Attacker takes a real state, swaps the payload (e.g. injects their
        own redirect) but keeps the signature → HMAC mismatch → reject."""
        import google_auth
        good = google_auth.encode_state(code_challenge="cc", redirect="r")
        body, _, sig = good.partition(".")
        # Forge a new payload, re-b64url it, keep the OLD signature.
        evil_payload = {"cc": "cc", "rd": "http://attacker.example",
                        "n": "x", "exp": int(time.time()) + 600}
        evil_body = base64.urlsafe_b64encode(
            json.dumps(evil_payload, separators=(",", ":"),
                       sort_keys=True).encode()).rstrip(b"=").decode()
        forged = evil_body + "." + sig
        r = client.get("/v1/auth/google/callback",
                       params={"code": "x", "state": forged})
        assert r.status_code == 400
        assert r.json()["detail"]["error"] == "invalid_state"

    def test_state_signed_with_wrong_key_rejected(
            self, client, google_enabled, monkeypatch):
        """A state HMAC'd with a DIFFERENT secret (attacker who doesn't know
        the server secret) must be rejected."""
        import hmac as _hmac, hashlib as _hashlib
        payload = {"cc": "", "rd": "", "n": "abc",
                   "exp": int(time.time()) + 600}
        body = base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":"),
                       sort_keys=True).encode()).rstrip(b"=").decode()
        wrong_sig = _hmac.new(b"attacker-guessed-key", body.encode("ascii"),
                              _hashlib.sha256).digest()
        forged = body + "." + base64.urlsafe_b64encode(
            wrong_sig).rstrip(b"=").decode()
        r = client.get("/v1/auth/google/callback",
                       params={"code": "x", "state": forged})
        assert r.status_code == 400
        assert r.json()["detail"]["error"] == "invalid_state"

    def test_expired_state_rejected(
            self, client, google_enabled, monkeypatch):
        """A genuinely-signed but EXPIRED state (replay after TTL) is
        rejected with state_expired."""
        import google_auth
        # Encode with a 'now' far in the past so exp is already elapsed.
        old = google_auth.encode_state(code_challenge="", redirect="",
                                       now=int(time.time()) - 10_000)
        r = client.get("/v1/auth/google/callback",
                       params={"code": "x", "state": old})
        assert r.status_code == 400
        assert r.json()["detail"]["error"] == "state_expired"

    def test_state_gate_fires_before_token_exchange(
            self, client, google_enabled, monkeypatch):
        """CSRF defence must happen BEFORE any Google token call — assert no
        outbound POST/GET happened on a forged state."""
        calls = _install_fake_google(
            monkeypatch,
            token_payload={"id_token": "fake.jwt.token"},
            tokeninfo_payload=_valid_claims(),
        )
        client.get("/v1/auth/google/callback",
                   params={"code": "x", "state": "bad.state"})
        assert calls["post"] == [], "token endpoint hit on a forged state!"
        assert calls["get"] == [], "tokeninfo hit on a forged state!"


# ===========================================================================
# (5) client SECRET never leaks (response bodies + start auth_url)
# ===========================================================================
class TestSecretNeverLeaks:
    def test_secret_not_in_start_auth_url(
            self, client, google_enabled, monkeypatch):
        _, challenge = _pkce_pair()
        r = client.get("/v1/auth/google/start",
                       params={"code_challenge": challenge,
                               "redirect": "http://127.0.0.1:53111/cb"})
        assert r.status_code == 200
        url = r.json()["auth_url"]
        assert _FAKE_CLIENT_SECRET not in url
        # And not hidden in a percent-encoded form either.
        assert _FAKE_CLIENT_SECRET not in urllib.parse.unquote(url)
        # The public client id SHOULD be present (it is public).
        assert _FAKE_CLIENT_ID in url
        # No client_secret query param at all.
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        assert "client_secret" not in q

    def test_secret_not_in_state(self, google_enabled, monkeypatch):
        """State is HMAC output, not encryption — the secret (used as the
        HMAC key) must not be recoverable from the opaque state."""
        import google_auth
        state = google_auth.encode_state(code_challenge="cc", redirect="rd")
        assert _FAKE_CLIENT_SECRET not in state
        # Decode the payload portion too — secret must not be embedded.
        body = state.partition(".")[0]
        pad = "=" * (-len(body) % 4)
        raw = base64.urlsafe_b64decode(body + pad).decode("utf-8", "replace")
        assert _FAKE_CLIENT_SECRET not in raw

    def test_secret_not_in_callback_error_bodies(
            self, client, google_enabled, monkeypatch):
        """Even on failure paths the response body must never echo the secret
        (or Google's raw token-endpoint body)."""
        # Token exchange fails (e.g. Google rejects the code).
        _install_fake_google(
            monkeypatch,
            token_payload={"error": "invalid_grant",
                           "leaked": _FAKE_CLIENT_SECRET},
            token_status=400,
            tokeninfo_payload=_valid_claims(),
        )
        r = client.get("/v1/auth/google/callback",
                       params={"code": "x", "state": _good_state()})
        assert _FAKE_CLIENT_SECRET not in r.text
        assert r.json()["detail"]["error"] == "token_exchange_failed"

    def test_secret_only_sent_to_google_token_endpoint(
            self, client, google_enabled, monkeypatch):
        """On a FULL successful flow, the secret must appear ONLY in the POST
        body to the token endpoint — never in tokeninfo params, never in the
        302 Location, never in any client-visible field."""
        calls = _install_fake_google(
            monkeypatch,
            token_payload={"id_token": "fake.jwt.token"},
            tokeninfo_payload=_valid_claims(email="leakcheck@studio.com"),
        )
        r = client.get("/v1/auth/google/callback",
                       params={"code": "good-code", "state": _good_state(
                           code_challenge="cc", redirect="http://127.0.0.1:9/cb")})
        # Successful → 302 to /auth/return with a one-time code.
        assert r.status_code == 302, r.text
        location = r.headers["location"]
        assert _FAKE_CLIENT_SECRET not in location
        assert _FAKE_CLIENT_SECRET not in urllib.parse.unquote(location)
        # Secret went to the token endpoint exactly.
        assert len(calls["post"]) == 1
        assert calls["post"][0]["url"].startswith("https://oauth2.googleapis.com/token")
        assert calls["post"][0]["data"].get("client_secret") == _FAKE_CLIENT_SECRET
        # tokeninfo (a GET) never carried the secret.
        for g in calls["get"]:
            assert _FAKE_CLIENT_SECRET not in json.dumps(g)

    def test_secret_not_in_unconfigured_503(self, client, monkeypatch):
        """With Google DISABLED, the 503 must not leak anything either."""
        import config
        monkeypatch.setattr(config, "GOOGLE_OAUTH_CLIENT_ID", "")
        monkeypatch.setattr(config, "GOOGLE_OAUTH_CLIENT_SECRET", "")
        r = client.get("/v1/auth/google/start")
        assert r.status_code == 503
        assert r.json()["detail"]["error"] == "google_login_unconfigured"


# ===========================================================================
# (6) the magic-link + exchange flow STILL works unchanged
# ===========================================================================
class TestMagicLinkStillWorks:
    def _stub_email(self, monkeypatch):
        async def fake_send(**kw):
            return True
        import email_sender
        monkeypatch.setattr(email_sender, "send_magic_link", fake_send)
        monkeypatch.setattr(email_sender, "send_welcome_email", fake_send)

    def _code_for(self, user_id):
        import db
        with db.connect() as con:
            row = con.execute(
                "SELECT code FROM codes WHERE user_id = ? "
                "ORDER BY rowid DESC LIMIT 1", (user_id,)).fetchone()
        return row["code"]

    def test_pkce_register_exchange_end_to_end(self, client, monkeypatch):
        """Desktop PKCE path: register → exchange → bearer token works,
        with Google login NOT configured (proves independence)."""
        self._stub_email(monkeypatch)
        import db
        verifier, challenge = _pkce_pair()
        r = client.post("/v1/auth/register",
                        json={"email": "magic-pkce@studio.com",
                              "code_challenge": challenge})
        assert r.status_code == 202
        u = db.get_user_by_email("magic-pkce@studio.com")
        code = self._code_for(u["id"])
        ex = client.post("/v1/auth/exchange",
                         json={"code": code, "code_verifier": verifier})
        assert ex.status_code == 200
        body = ex.json()
        assert body["token"].startswith("ah_live_")
        assert "plan" in body and "expires_at" in body
        # The token actually authenticates.
        me = client.get("/v1/me",
                        headers={"Authorization": f"Bearer {body['token']}"})
        assert me.status_code == 200
        assert me.json()["email"] == "magic-pkce@studio.com"

    def test_browser_direct_empty_challenge_still_works(
            self, client, monkeypatch):
        self._stub_email(monkeypatch)
        import db
        r = client.post("/v1/auth/register",
                        json={"email": "magic-browser@studio.com",
                              "code_challenge": ""})
        assert r.status_code == 202
        u = db.get_user_by_email("magic-browser@studio.com")
        code = self._code_for(u["id"])
        ex = client.post("/v1/auth/exchange",
                         json={"code": code, "code_verifier": ""})
        assert ex.status_code == 200
        assert ex.json()["token"].startswith("ah_live_")

    def test_pkce_still_enforced_wrong_verifier(self, client, monkeypatch):
        """The PKCE protection on the magic-link path is intact: a challenged
        code cannot be exchanged with the wrong verifier."""
        self._stub_email(monkeypatch)
        import db
        verifier, challenge = _pkce_pair()
        client.post("/v1/auth/register",
                    json={"email": "magic-pkce2@studio.com",
                          "code_challenge": challenge})
        u = db.get_user_by_email("magic-pkce2@studio.com")
        code = self._code_for(u["id"])
        wrong = secrets.token_urlsafe(48)
        ex = client.post("/v1/auth/exchange",
                         json={"code": code, "code_verifier": wrong})
        assert ex.status_code == 400
        assert "token" not in ex.json()

    def test_google_and_magiclink_converge_same_account(
            self, client, google_enabled, monkeypatch):
        """A Google sign-in for an email that already registered via
        magic-link converges on the SAME user row (keyed by email) — the
        additive contract."""
        self._stub_email(monkeypatch)
        import db
        # First: magic-link register creates the account.
        _, challenge = _pkce_pair()
        client.post("/v1/auth/register",
                    json={"email": "converge@studio.com",
                          "code_challenge": challenge})
        u1 = db.get_user_by_email("converge@studio.com")
        assert u1 is not None
        # Now: a valid Google sign-in for the same email.
        _install_fake_google(
            monkeypatch,
            token_payload={"id_token": "fake.jwt.token"},
            tokeninfo_payload=_valid_claims(email="converge@studio.com"),
        )
        r = client.get("/v1/auth/google/callback",
                       params={"code": "good", "state": _good_state()})
        assert r.status_code == 302
        u2 = db.get_user_by_email("converge@studio.com")
        assert u2["id"] == u1["id"], "Google login forked a new account!"


# ===========================================================================
# Positive control — a fully valid Google token DOES succeed (so the REJECT
# tests above are meaningful, not just rejecting everything).
# ===========================================================================
class TestValidGoogleTokenSucceeds:
    def test_valid_token_mints_one_time_code_and_redirects(
            self, client, google_enabled, monkeypatch):
        import db
        calls = _install_fake_google(
            monkeypatch,
            token_payload={"id_token": "fake.jwt.token"},
            tokeninfo_payload=_valid_claims(email="happy@studio.com"),
        )
        verifier, challenge = _pkce_pair()
        state = _good_state(code_challenge=challenge,
                            redirect="http://127.0.0.1:53111/cb")
        r = client.get("/v1/auth/google/callback",
                       params={"code": "good-code", "state": state})
        assert r.status_code == 302, r.text
        loc = r.headers["location"]
        # Lands on /auth/return with a one-time code + forwarded redirect.
        assert "/auth/return?" in loc
        q = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)
        one_time = q["code"][0]
        # The user now exists, and the issued code is bound to the PKCE
        # challenge → completes via the UNCHANGED exchange path.
        u = db.get_user_by_email("happy@studio.com")
        assert u is not None
        ex = client.post("/v1/auth/exchange",
                         json={"code": one_time, "code_verifier": verifier})
        assert ex.status_code == 200
        assert ex.json()["token"].startswith("ah_live_")

    def test_valid_token_with_wrong_pkce_verifier_still_blocked_at_exchange(
            self, client, google_enabled, monkeypatch):
        """Defence in depth: even after a valid Google identity, the one-time
        code is PKCE-bound — a thief of the code without the verifier fails."""
        import db
        _install_fake_google(
            monkeypatch,
            token_payload={"id_token": "fake.jwt.token"},
            tokeninfo_payload=_valid_claims(email="dd@studio.com"),
        )
        _, challenge = _pkce_pair()
        state = _good_state(code_challenge=challenge, redirect="http://127.0.0.1:9/cb")
        r = client.get("/v1/auth/google/callback",
                       params={"code": "good", "state": state})
        q = urllib.parse.parse_qs(urllib.parse.urlparse(r.headers["location"]).query)
        one_time = q["code"][0]
        ex = client.post("/v1/auth/exchange",
                         json={"code": one_time,
                               "code_verifier": secrets.token_urlsafe(48)})
        assert ex.status_code == 400
