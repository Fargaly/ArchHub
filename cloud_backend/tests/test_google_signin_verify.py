"""VERIFICATION (correctness) of Sign in with Google — end-to-end.

This is the adversarial verification harness requested for the just-built
Google OAuth path. It drives the REAL routes via FastAPI TestClient with
GOOGLE_OAUTH_CLIENT_ID/SECRET set to test values, and MONKEYPATCHES only the
two outbound-to-Google calls (token exchange + id_token verification) so the
test runs offline while STILL exercising the real:
  * /v1/auth/google/start  → authorization URL assembly + signed state.
  * /v1/auth/google/callback → state verify, code mint, 302 to /auth/return.
  * google_auth._assert_claims → the actual aud/iss/exp/email_verified gate
    (the monkeypatched verify_id_token routes through it, NOT around it).
  * /v1/auth/exchange → the unchanged PKCE code-exchange that issues the token.
  * db.get_or_create_user keying → Google sign-in converges on the SAME row
    as an email sign-in for the same address.

PASS criterion: Google sign-in yields a working ArchHub bearer token that
maps (via db.user_for_token) to the SAME user id as db.get_or_create_user
for ahmed.fargaly98@gmail.com.

The conftest.py autouse fixture isolates the DB per test.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
import urllib.parse

import pytest
from fastapi.testclient import TestClient

TEST_CLIENT_ID = "test-client-id.apps.googleusercontent.com"
TEST_CLIENT_SECRET = "test-oauth-client-secret-value"
EMAIL = "ahmed.fargaly98@gmail.com"
REDIRECT_BASE = "https://archhub-cloud.fly.dev"
REDIRECT_URI = REDIRECT_BASE + "/v1/auth/google/callback"


def _pkce_pair():
    """RFC 7636 S256 pair, identical construction to db.consume_code's check."""
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


@pytest.fixture()
def google_env(monkeypatch):
    """Set GOOGLE_OAUTH_CLIENT_ID/SECRET to test values + a stable redirect.

    config.google_login_enabled() and google_auth read these at call time
    via the module namespace, so patching the module globals is sufficient
    to flip the flow ON without touching the real environment.
    """
    import config
    monkeypatch.setattr(config, "GOOGLE_OAUTH_CLIENT_ID", TEST_CLIENT_ID)
    monkeypatch.setattr(config, "GOOGLE_OAUTH_CLIENT_SECRET", TEST_CLIENT_SECRET)
    monkeypatch.setattr(config, "GOOGLE_OAUTH_REDIRECT", REDIRECT_URI)
    monkeypatch.setattr(config, "PUBLIC_URL", REDIRECT_BASE)
    assert config.google_login_enabled() is True
    return config


@pytest.fixture()
def patched_google(monkeypatch, google_env):
    """MONKEYPATCH the two outbound-to-Google calls to a VALID token.

    - _exchange_code_for_tokens: return a token blob carrying a sentinel
      id_token (no real HTTP to oauth2.googleapis.com/token).
    - verify_id_token: build the claims Google WOULD return for a verified
      account (aud == our test client id, iss == accounts.google.com,
      email_verified true, exp in the future) and run them through the REAL
      google_auth._assert_claims so the genuine trust gate is exercised.
    """
    import google_auth

    captured = {}

    def fake_exchange(code: str) -> dict:
        captured["exchanged_code"] = code
        return {"id_token": "FAKE.VALID.IDTOKEN", "token_type": "Bearer"}

    def fake_verify(id_token: str) -> dict:
        captured["verified_id_token"] = id_token
        claims = {
            "iss": "https://accounts.google.com",
            "aud": TEST_CLIENT_ID,            # minted FOR our client id
            "sub": "1234567890",
            "email": EMAIL,
            "email_verified": "true",          # tokeninfo string form
            "exp": int(time.time()) + 3600,
        }
        # Route through the REAL claim assertions — do NOT bypass the gate.
        return google_auth._assert_claims(claims)

    monkeypatch.setattr(google_auth, "_exchange_code_for_tokens", fake_exchange)
    monkeypatch.setattr(google_auth, "verify_id_token", fake_verify)
    return captured


@pytest.fixture()
def client(google_env):
    import main
    return TestClient(main.app)


def _decode_state_payload(state: str) -> dict:
    body = state.partition(".")[0]
    pad = "=" * (-len(body) % 4)
    return __import__("json").loads(
        base64.urlsafe_b64decode(body + pad).decode("utf-8"))


# ---------------------------------------------------------------------------
# The full drive, as one end-to-end test (the PASS/FAIL decision).
# ---------------------------------------------------------------------------
def test_google_signin_end_to_end_yields_token_for_email_user(
        client, patched_google):
    import db
    import google_auth

    verifier, challenge = _pkce_pair()
    desktop_redirect = "http://127.0.0.1:53682/callback"

    # ── Step 1: /v1/auth/google/start → auth_url ─────────────────────────
    r1 = client.get("/v1/auth/google/start", params={
        "code_challenge": challenge,
        "redirect": desktop_redirect,
    })
    assert r1.status_code == 200, r1.text
    auth_url = r1.json()["auth_url"]

    parsed = urllib.parse.urlparse(auth_url)
    qs = urllib.parse.parse_qs(parsed.query)
    # accounts.google.com consent endpoint.
    assert parsed.scheme == "https"
    assert parsed.netloc == "accounts.google.com"
    assert parsed.path == "/o/oauth2/v2/auth"
    # right client_id + redirect + scope.
    assert qs["client_id"] == [TEST_CLIENT_ID]
    assert qs["redirect_uri"] == [REDIRECT_URI]
    assert qs["response_type"] == ["code"]
    assert qs["scope"] == ["openid email profile"]
    # state present + carries the PKCE challenge + desktop redirect, signed.
    assert "state" in qs and qs["state"][0]
    state = qs["state"][0]
    payload = _decode_state_payload(state)
    assert payload["cc"] == challenge        # PKCE challenge smuggled across
    assert payload["rd"] == desktop_redirect
    # state must verify under the real HMAC gate (tamper/forge defence).
    assert google_auth.decode_state(state)["cc"] == challenge

    # ── Step 2: simulate Google redirect → /v1/auth/google/callback ──────
    google_code = "google-auth-code-abc123"
    r2 = client.get("/v1/auth/google/callback", params={
        "code": google_code,
        "state": state,
    }, follow_redirects=False)

    # 302 to /auth/return?code=...
    assert r2.status_code == 302, r2.text
    location = r2.headers["location"]
    loc = urllib.parse.urlparse(location)
    assert loc.path == "/auth/return", location
    ret_qs = urllib.parse.parse_qs(loc.query)
    one_time_code = ret_qs["code"][0]
    assert one_time_code
    # desktop loopback redirect forwarded through (magic-link parity).
    assert ret_qs.get("redirect") == [desktop_redirect]
    # the monkeypatched exchange actually received Google's code + id_token.
    assert patched_google["exchanged_code"] == google_code
    assert patched_google["verified_id_token"] == "FAKE.VALID.IDTOKEN"

    # ── Step 3: run the EXISTING exchange with the PKCE verifier ─────────
    r3 = client.post("/v1/auth/exchange", json={
        "code": one_time_code,
        "code_verifier": verifier,
    })
    assert r3.status_code == 200, r3.text
    body = r3.json()
    token = body["token"]
    # A real ArchHub bearer token was issued.
    assert token.startswith("ah_live_"), token
    assert body["plan"] == "trial"
    assert body["expires_at"] > int(time.time())

    # ── Step 4: token maps to the SAME user as email sign-in ─────────────
    # get_or_create_user is idempotent on email → returns the SAME row the
    # Google callback created. The token must resolve to THAT user id.
    email_user = db.get_or_create_user(EMAIL)
    token_user = db.user_for_token(token)
    assert token_user is not None, "issued token did not authenticate"
    assert token_user["id"] == email_user["id"], (
        "Google sign-in did not converge on the email-keyed user")
    assert token_user["email"] == EMAIL

    # PASS: a working ArchHub token, bound to the email-keyed user, via Google.
    # The token works against a real authenticated endpoint too:
    me = client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200, me.text
    assert me.json()["email"] == EMAIL


# ---------------------------------------------------------------------------
# Convergence: Google sign-in lands on the SAME row a prior EMAIL sign-in made.
# ---------------------------------------------------------------------------
def test_google_converges_on_preexisting_email_user(client, patched_google):
    """If the user already exists (created via the email/magic-link path),
    Google sign-in must reuse that exact row — not mint a duplicate."""
    import db

    # Pre-create the user as the email path would (get_or_create_user is the
    # shared keying primitive register_via_email uses).
    pre = db.get_or_create_user(EMAIL)
    pre_id = pre["id"]

    verifier, challenge = _pkce_pair()
    r1 = client.get("/v1/auth/google/start",
                    params={"code_challenge": challenge})
    state = urllib.parse.parse_qs(
        urllib.parse.urlparse(r1.json()["auth_url"]).query)["state"][0]
    r2 = client.get("/v1/auth/google/callback",
                    params={"code": "code-xyz", "state": state},
                    follow_redirects=False)
    code = urllib.parse.parse_qs(
        urllib.parse.urlparse(r2.headers["location"]).query)["code"][0]
    r3 = client.post("/v1/auth/exchange",
                     json={"code": code, "code_verifier": verifier})
    token = r3.json()["token"]

    assert db.user_for_token(token)["id"] == pre_id
    # No duplicate row minted for the same email.
    with db.connect() as con:
        n = con.execute("SELECT COUNT(*) c FROM users WHERE email = ?",
                        (EMAIL,)).fetchone()["c"]
    assert n == 1


# ---------------------------------------------------------------------------
# Negative controls — prove the verification GATE actually bites, so a PASS
# above isn't a rubber stamp.
# ---------------------------------------------------------------------------
def test_wrong_aud_id_token_is_rejected(monkeypatch, client, google_env):
    """An id_token minted for a DIFFERENT client id must be refused (401)
    and NO code/token issued — the aud check is real."""
    import google_auth

    def bad_aud_verify(id_token: str) -> dict:
        return google_auth._assert_claims({
            "iss": "https://accounts.google.com",
            "aud": "some-OTHER-client.apps.googleusercontent.com",
            "email": EMAIL,
            "email_verified": True,
            "exp": int(time.time()) + 3600,
        })

    monkeypatch.setattr(google_auth, "_exchange_code_for_tokens",
                        lambda code: {"id_token": "x"})
    monkeypatch.setattr(google_auth, "verify_id_token", bad_aud_verify)

    _, challenge = _pkce_pair()
    r1 = client.get("/v1/auth/google/start",
                    params={"code_challenge": challenge})
    state = urllib.parse.parse_qs(
        urllib.parse.urlparse(r1.json()["auth_url"]).query)["state"][0]
    r2 = client.get("/v1/auth/google/callback",
                    params={"code": "c", "state": state},
                    follow_redirects=False)
    assert r2.status_code == 401, r2.text
    assert r2.json()["detail"]["error"] == "bad_audience"


def test_unverified_email_is_rejected(monkeypatch, client, google_env):
    """email_verified=false → 401 email_unverified, never a token."""
    import google_auth

    def unverified(id_token: str) -> dict:
        return google_auth._assert_claims({
            "iss": "https://accounts.google.com",
            "aud": TEST_CLIENT_ID,
            "email": EMAIL,
            "email_verified": False,
            "exp": int(time.time()) + 3600,
        })

    monkeypatch.setattr(google_auth, "_exchange_code_for_tokens",
                        lambda code: {"id_token": "x"})
    monkeypatch.setattr(google_auth, "verify_id_token", unverified)

    _, challenge = _pkce_pair()
    r1 = client.get("/v1/auth/google/start",
                    params={"code_challenge": challenge})
    state = urllib.parse.parse_qs(
        urllib.parse.urlparse(r1.json()["auth_url"]).query)["state"][0]
    r2 = client.get("/v1/auth/google/callback",
                    params={"code": "c", "state": state},
                    follow_redirects=False)
    assert r2.status_code == 401, r2.text
    assert r2.json()["detail"]["error"] == "email_unverified"


def test_tampered_state_is_rejected(client, patched_google):
    """A forged/tampered state fails the HMAC gate (400 invalid_state)
    BEFORE any Google call — CSRF defence holds."""
    _, challenge = _pkce_pair()
    r1 = client.get("/v1/auth/google/start",
                    params={"code_challenge": challenge})
    state = urllib.parse.parse_qs(
        urllib.parse.urlparse(r1.json()["auth_url"]).query)["state"][0]
    # Flip the FIRST payload char (NOT the trailing signature char): a flipped
    # base64url *signature* char decodes to identical bytes ~6% of the time,
    # which made this test flaky. Mutating the payload changes the HMAC-signed
    # bytes, so the signature deterministically mismatches.
    tampered = ("B" if state[0] == "A" else "A") + state[1:]
    r2 = client.get("/v1/auth/google/callback",
                    params={"code": "c", "state": tampered},
                    follow_redirects=False)
    assert r2.status_code == 400, r2.text
    assert r2.json()["detail"]["error"] == "invalid_state"


def test_pkce_verifier_must_match_challenge(client, patched_google):
    """The minted code is bound to the state's PKCE challenge: exchanging
    it with the WRONG verifier fails (400), proving the challenge really
    crossed the Google round-trip and is enforced at exchange."""
    verifier, challenge = _pkce_pair()
    r1 = client.get("/v1/auth/google/start",
                    params={"code_challenge": challenge})
    state = urllib.parse.parse_qs(
        urllib.parse.urlparse(r1.json()["auth_url"]).query)["state"][0]
    r2 = client.get("/v1/auth/google/callback",
                    params={"code": "c", "state": state},
                    follow_redirects=False)
    code = urllib.parse.parse_qs(
        urllib.parse.urlparse(r2.headers["location"]).query)["code"][0]
    # A different, valid-length verifier that does NOT match the challenge.
    wrong = secrets.token_urlsafe(48)
    assert wrong != verifier
    r3 = client.post("/v1/auth/exchange",
                     json={"code": code, "code_verifier": wrong})
    assert r3.status_code == 400, r3.text
    assert "token" not in r3.json()


def test_unconfigured_returns_503(monkeypatch):
    """Sanity: with the OAuth vars EMPTY (the current deployment), start +
    callback both return 503 google_login_unconfigured — the additive
    flow is dark until credentials are supplied."""
    import config
    import main
    monkeypatch.setattr(config, "GOOGLE_OAUTH_CLIENT_ID", "")
    monkeypatch.setattr(config, "GOOGLE_OAUTH_CLIENT_SECRET", "")
    assert config.google_login_enabled() is False
    c = TestClient(main.app)
    r = c.get("/v1/auth/google/start", params={"code_challenge": "x"})
    assert r.status_code == 503
    assert r.json()["detail"]["error"] == "google_login_unconfigured"


def test_assert_claims_rejects_non_string_aud_cleanly(google_env):
    """A list (multi-audience) aud is OIDC-legal but not OURS; it must fail
    CLEANLY (401 bad_audience), never raise AttributeError -> 500. Guards the
    isinstance hardening of _assert_claims (founder 2026-06-02 verify nit)."""
    import google_auth
    claims = {
        "iss": "https://accounts.google.com",
        "aud": [TEST_CLIENT_ID, "some-other-app.apps.googleusercontent.com"],
        "exp": int(time.time()) + 3600,
        "email": EMAIL,
        "email_verified": True,
    }
    with pytest.raises(google_auth.GoogleAuthError) as ei:
        google_auth._assert_claims(claims)
    assert ei.value.status == 401
    assert ei.value.code == "bad_audience"
