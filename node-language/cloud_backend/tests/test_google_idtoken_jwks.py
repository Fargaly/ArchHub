"""ADVERSARIAL verification of the LOCAL JWKS id_token signature path.

The Google sign-in verifier now checks the id_token's RS256 signature LOCALLY
against Google's published RSA keys (cached), and only degrades to the
tokeninfo endpoint when those keys cannot be fetched. Hand-rolled JWT
verification is a classic source of bypasses, so these tests mint REAL RSA
keypairs, sign REAL JWTs, and assert the security properties on the actual
google_auth.verify_id_token():

  * a validly-signed token is accepted with NO tokeninfo call (local path)
  * a tampered payload / wrong signing key      → REJECTED, no fallback
  * `alg:none`                                  → REJECTED (alg pinned)
  * HS256 key-confusion (HMAC w/ the public key)→ REJECTED (alg pinned)
  * an unknown kid                              → REJECTED after one refetch
  * the SAME _assert_claims gate still bites (email_verified / aud / exp)
    AFTER a valid signature — signature OK never means claims trusted
  * keys cached → second verify makes no network call (latency win is real)
  * key rotation → one forced refetch recovers
  * certs unreachable → graceful tokeninfo FALLBACK (availability preserved)
  * a recent certs failure → cooldown skips re-hitting certs every sign-in

A REJECT here is GoogleAuthError(401); a present-but-invalid token must NEVER
reach the tokeninfo fallback (that's reserved for 'keys unavailable').

conftest.py resets google_auth._JWKS_CACHE per test, so these and the
tokeninfo-fallback suites are mutually isolated.
"""
from __future__ import annotations

import base64
import hashlib
import hmac as _hmac
import json
import time

import pytest

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


TEST_CLIENT_ID = "test-client-id.apps.googleusercontent.com"
EMAIL = "ahmed.fargaly98@gmail.com"


# ---------------------------------------------------------------------------
# JWT / JWK helpers built on real keys (so the crypto is genuinely exercised)
# ---------------------------------------------------------------------------
def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _gen_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwk_from_public(pub, kid: str) -> dict:
    nums = pub.public_numbers()
    n = nums.n.to_bytes((nums.n.bit_length() + 7) // 8, "big")
    e = nums.e.to_bytes((nums.e.bit_length() + 7) // 8, "big")
    return {"kty": "RSA", "use": "sig", "alg": "RS256", "kid": kid,
            "n": _b64url(n), "e": _b64url(e)}


def _seg(obj: dict) -> str:
    return _b64url(json.dumps(obj, separators=(",", ":")).encode("utf-8"))


def _sign_rs256(priv, kid: str, claims: dict) -> str:
    header = {"alg": "RS256", "kid": kid, "typ": "JWT"}
    h, p = _seg(header), _seg(claims)
    sig = priv.sign((h + "." + p).encode("ascii"),
                    padding.PKCS1v15(), hashes.SHA256())
    return h + "." + p + "." + _b64url(sig)


def _forge_alg_none(kid: str, claims: dict) -> str:
    header = {"alg": "none", "kid": kid, "typ": "JWT"}
    return _seg(header) + "." + _seg(claims) + "."          # empty signature


def _forge_hs256_with_pubkey(pub, kid: str, claims: dict) -> str:
    """The classic alg-confusion forgery: declare HS256 and 'sign' with an
    HMAC keyed by the RSA PUBLIC key (which the attacker can read from the
    JWKS). A verifier that trusts the token's alg would accept this."""
    pem = pub.public_bytes(serialization.Encoding.PEM,
                           serialization.PublicFormat.SubjectPublicKeyInfo)
    header = {"alg": "HS256", "kid": kid, "typ": "JWT"}
    h, p = _seg(header), _seg(claims)
    sig = _hmac.new(pem, (h + "." + p).encode("ascii"), hashlib.sha256).digest()
    return h + "." + p + "." + _b64url(sig)


def _claims(**over) -> dict:
    base = {
        "iss": "https://accounts.google.com",
        "aud": TEST_CLIENT_ID,
        "sub": "1234567890",
        "email": EMAIL,
        "email_verified": True,
        "exp": int(time.time()) + 3600,
    }
    base.update(over)
    return base


class FakeResp:
    def __init__(self, status_code, payload, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _install_google(monkeypatch, *, certs_payload=None, certs_status=200,
                    certs_headers=None, certs_raises=False,
                    tokeninfo_payload=None, tokeninfo_status=200):
    """Fake google_auth.httpx.get so the JWKS endpoint and tokeninfo are
    fully controlled + counted. No real network. Records hit counts so a test
    can prove the local path made NO tokeninfo call (or vice-versa)."""
    import google_auth
    calls = {"certs": 0, "tokeninfo": 0, "urls": []}

    def fake_get(url, params=None, headers=None, timeout=None, **kw):
        calls["urls"].append(url)
        if url == google_auth.GOOGLE_CERTS_URL:
            calls["certs"] += 1
            if certs_raises:
                raise google_auth.httpx.HTTPError("certs boom")
            return FakeResp(certs_status, certs_payload, certs_headers)
        if url == google_auth.GOOGLE_TOKENINFO_ENDPOINT:
            calls["tokeninfo"] += 1
            return FakeResp(tokeninfo_status, tokeninfo_payload)
        return FakeResp(404, {})

    monkeypatch.setattr(google_auth.httpx, "get", fake_get)
    return calls


@pytest.fixture
def google_cfg(monkeypatch):
    import config
    monkeypatch.setattr(config, "GOOGLE_OAUTH_CLIENT_ID", TEST_CLIENT_ID)
    monkeypatch.setattr(config, "GOOGLE_OAUTH_CLIENT_SECRET", "test-secret-x")
    return config


def _jwks_for(priv, kid="k1"):
    return {"keys": [_jwk_from_public(priv.public_key(), kid)]}


# ===========================================================================
# Positive: a real signed token verifies LOCALLY (no tokeninfo round-trip)
# ===========================================================================
def test_valid_signed_token_accepted_locally(google_cfg, monkeypatch):
    import google_auth
    priv = _gen_key()
    calls = _install_google(monkeypatch, certs_payload=_jwks_for(priv),
                            tokeninfo_payload=_claims())
    tok = _sign_rs256(priv, "k1", _claims(email="happy@studio.com"))
    claims = google_auth.verify_id_token(tok)
    assert claims["email"] == "happy@studio.com"
    # Verified against local keys — tokeninfo NOT consulted.
    assert calls["certs"] == 1
    assert calls["tokeninfo"] == 0


# ===========================================================================
# Signature integrity — bad tokens REJECTED and never bounced to the fallback
# ===========================================================================
def test_tampered_payload_rejected_no_fallback(google_cfg, monkeypatch):
    import google_auth
    priv = _gen_key()
    calls = _install_google(monkeypatch, certs_payload=_jwks_for(priv),
                            # tokeninfo WOULD pass if (wrongly) consulted.
                            tokeninfo_payload=_claims(email="attacker@evil.com"))
    tok = _sign_rs256(priv, "k1", _claims())
    h, _p, s = tok.split(".")
    evil = _seg(_claims(email="attacker@evil.com"))
    forged = h + "." + evil + "." + s            # swapped payload, old sig
    with pytest.raises(google_auth.GoogleAuthError) as ei:
        google_auth.verify_id_token(forged)
    assert ei.value.status == 401
    assert ei.value.code == "id_token_invalid"
    assert calls["tokeninfo"] == 0, "a bad signature must NOT fall back"


def test_wrong_signing_key_rejected(google_cfg, monkeypatch):
    import google_auth
    published = _gen_key()
    attacker = _gen_key()                         # signs with the wrong key
    calls = _install_google(monkeypatch,
                            certs_payload=_jwks_for(published),
                            tokeninfo_payload=_claims())
    tok = _sign_rs256(attacker, "k1", _claims())
    with pytest.raises(google_auth.GoogleAuthError) as ei:
        google_auth.verify_id_token(tok)
    assert ei.value.code == "id_token_invalid"
    assert calls["tokeninfo"] == 0


def test_alg_none_rejected(google_cfg, monkeypatch):
    import google_auth
    priv = _gen_key()
    calls = _install_google(monkeypatch, certs_payload=_jwks_for(priv),
                            tokeninfo_payload=_claims())
    tok = _forge_alg_none("k1", _claims())
    with pytest.raises(google_auth.GoogleAuthError) as ei:
        google_auth.verify_id_token(tok)
    assert ei.value.code == "id_token_invalid"
    assert calls["tokeninfo"] == 0


def test_hs256_key_confusion_rejected(google_cfg, monkeypatch):
    import google_auth
    priv = _gen_key()
    pub = priv.public_key()
    calls = _install_google(monkeypatch,
                            certs_payload={"keys": [_jwk_from_public(pub, "k1")]},
                            tokeninfo_payload=_claims())
    tok = _forge_hs256_with_pubkey(pub, "k1", _claims())
    with pytest.raises(google_auth.GoogleAuthError) as ei:
        google_auth.verify_id_token(tok)
    assert ei.value.code == "id_token_invalid"
    assert calls["tokeninfo"] == 0


def test_non_jwt_rejected_when_certs_available(google_cfg, monkeypatch):
    """A structurally-broken token must be REJECTED (not routed to tokeninfo)
    when keys ARE available — the fallback is only for keys-unavailable."""
    import google_auth
    priv = _gen_key()
    calls = _install_google(monkeypatch, certs_payload=_jwks_for(priv),
                            tokeninfo_payload=_claims())
    with pytest.raises(google_auth.GoogleAuthError) as ei:
        google_auth.verify_id_token("not-a-jwt")
    assert ei.value.code == "id_token_invalid"
    assert calls["tokeninfo"] == 0


def test_unknown_kid_rejected(google_cfg, monkeypatch):
    import google_auth
    priv = _gen_key()
    calls = _install_google(monkeypatch, certs_payload=_jwks_for(priv, "k1"),
                            tokeninfo_payload=_claims())
    tok = _sign_rs256(priv, "kid-not-published", _claims())
    with pytest.raises(google_auth.GoogleAuthError) as ei:
        google_auth.verify_id_token(tok)
    assert ei.value.code == "id_token_invalid"
    # A kid-miss forces one refetch; still absent → reject, no fallback.
    assert calls["certs"] >= 1
    assert calls["tokeninfo"] == 0


# ===========================================================================
# The SHARED claim gate still bites AFTER a valid signature (local path)
# ===========================================================================
def test_local_path_still_rejects_unverified_email(google_cfg, monkeypatch):
    import google_auth
    priv = _gen_key()
    _install_google(monkeypatch, certs_payload=_jwks_for(priv))
    tok = _sign_rs256(priv, "k1", _claims(email_verified=False))
    with pytest.raises(google_auth.GoogleAuthError) as ei:
        google_auth.verify_id_token(tok)
    assert ei.value.code == "email_unverified"


def test_local_path_still_rejects_wrong_aud(google_cfg, monkeypatch):
    import google_auth
    priv = _gen_key()
    _install_google(monkeypatch, certs_payload=_jwks_for(priv))
    tok = _sign_rs256(priv, "k1",
                      _claims(aud="someone-else.apps.googleusercontent.com"))
    with pytest.raises(google_auth.GoogleAuthError) as ei:
        google_auth.verify_id_token(tok)
    assert ei.value.code == "bad_audience"


def test_local_path_still_rejects_expired(google_cfg, monkeypatch):
    import google_auth
    priv = _gen_key()
    _install_google(monkeypatch, certs_payload=_jwks_for(priv))
    tok = _sign_rs256(priv, "k1", _claims(exp=int(time.time()) - 60))
    with pytest.raises(google_auth.GoogleAuthError) as ei:
        google_auth.verify_id_token(tok)
    assert ei.value.code == "id_token_expired"


def test_local_path_still_rejects_bad_issuer(google_cfg, monkeypatch):
    import google_auth
    priv = _gen_key()
    _install_google(monkeypatch, certs_payload=_jwks_for(priv))
    tok = _sign_rs256(priv, "k1", _claims(iss="https://evil.example.com"))
    with pytest.raises(google_auth.GoogleAuthError) as ei:
        google_auth.verify_id_token(tok)
    assert ei.value.code == "bad_issuer"


# ===========================================================================
# Caching / rotation — the latency win is real, and rotation recovers
# ===========================================================================
def test_warm_cache_second_verify_makes_no_network_call(google_cfg, monkeypatch):
    import google_auth
    priv = _gen_key()
    calls = _install_google(
        monkeypatch, certs_payload=_jwks_for(priv),
        certs_headers={"Cache-Control": "public, max-age=3600"})
    t1 = _sign_rs256(priv, "k1", _claims(email="a@studio.com"))
    t2 = _sign_rs256(priv, "k1", _claims(email="b@studio.com"))
    assert google_auth.verify_id_token(t1)["email"] == "a@studio.com"
    assert google_auth.verify_id_token(t2)["email"] == "b@studio.com"
    # Keys cached from the first call → second sign-in hits no network.
    assert calls["certs"] == 1
    assert calls["tokeninfo"] == 0


def test_key_rotation_forces_one_refetch(google_cfg, monkeypatch):
    import google_auth
    old = _gen_key()
    new = _gen_key()
    # Pre-warm the cache with the OLD key (far-future expiry).
    google_auth._JWKS_CACHE.update(
        keys={"old-kid": old.public_key()},
        exp=int(time.time()) + 9999, retry_after=0)
    # The certs endpoint now serves the ROTATED key set.
    calls = _install_google(
        monkeypatch, certs_payload={"keys": [_jwk_from_public(new.public_key(),
                                                              "new-kid")]})
    tok = _sign_rs256(new, "new-kid", _claims(email="rotated@studio.com"))
    claims = google_auth.verify_id_token(tok)
    assert claims["email"] == "rotated@studio.com"
    # Warm cache skipped the proactive fetch; the kid-miss forced exactly one.
    assert calls["certs"] == 1
    assert calls["tokeninfo"] == 0


def test_unknown_kid_flood_does_not_hammer_certs(google_cfg, monkeypatch):
    """Anti-DoS: a flood of attacker-chosen bogus kids must NOT trigger an
    outbound certs fetch per request. The kid-miss refetch is rate-limited, so
    two bogus-kid sign-ins hit Google's certs endpoint at most once total after
    the cache is warm — not once per request. Each is still REJECTED (an
    unknown kid never falls back to tokeninfo)."""
    import google_auth
    priv = _gen_key()
    calls = _install_google(monkeypatch, certs_payload=_jwks_for(priv, "k1"),
                            tokeninfo_payload=_claims())
    t1 = _sign_rs256(priv, "bogus-kid-1", _claims())
    t2 = _sign_rs256(priv, "bogus-kid-2", _claims())
    for tok in (t1, t2):
        with pytest.raises(google_auth.GoogleAuthError) as ei:
            google_auth.verify_id_token(tok)
        assert ei.value.code == "id_token_invalid"
    # First call: ensure-load (1) + one kid-miss refetch (1) = 2. Second call:
    # warm cache → no ensure fetch, and the refetch is rate-limited → 0 more.
    assert calls["certs"] == 2, "bogus-kid flood hit certs more than once warm"
    assert calls["tokeninfo"] == 0


# ===========================================================================
# Availability — graceful tokeninfo fallback ONLY when keys are unreachable
# ===========================================================================
def test_fallback_to_tokeninfo_when_certs_unreachable(google_cfg, monkeypatch):
    import google_auth
    calls = _install_google(monkeypatch, certs_raises=True,
                            tokeninfo_payload=_claims(email="fb@studio.com"))
    # The token content is irrelevant — keys can't be fetched, so the verifier
    # degrades to tokeninfo (which returns verified claims).
    claims = google_auth.verify_id_token("any.jwt.token")
    assert claims["email"] == "fb@studio.com"
    assert calls["certs"] == 1
    assert calls["tokeninfo"] == 1


def test_fallback_path_still_runs_assert_claims(google_cfg, monkeypatch):
    """Even on the tokeninfo fallback, the trust gate bites — an unverified
    email from tokeninfo is rejected just like on the local path."""
    import google_auth
    calls = _install_google(monkeypatch, certs_status=500,
                            tokeninfo_payload=_claims(email_verified="false"))
    with pytest.raises(google_auth.GoogleAuthError) as ei:
        google_auth.verify_id_token("any.jwt.token")
    assert ei.value.code == "email_unverified"
    assert calls["tokeninfo"] == 1


def test_negative_cache_skips_certs_during_cooldown(google_cfg, monkeypatch):
    """A certs outage must not add a failed round-trip to EVERY sign-in: after
    one failure the verifier skips certs (cooldown) and goes straight to the
    tokeninfo fallback."""
    import google_auth
    calls = _install_google(monkeypatch, certs_raises=True,
                            tokeninfo_payload=_claims())
    google_auth.verify_id_token("a.b.c")          # certs fail → cooldown armed
    google_auth.verify_id_token("d.e.f")          # within cooldown → skip certs
    assert calls["certs"] == 1                    # only the first hit certs
    assert calls["tokeninfo"] == 2                # both fell back


# ===========================================================================
# End-to-end: a real signed token through the actual /callback mints a code
# ===========================================================================
def test_end_to_end_callback_with_real_signed_token(google_cfg, monkeypatch):
    from fastapi.testclient import TestClient
    import config
    import db
    import google_auth
    import main

    priv = _gen_key()
    monkeypatch.setattr(config, "GOOGLE_OAUTH_REDIRECT",
                        "https://app.example.com/v1/auth/google/callback")
    monkeypatch.setattr(config, "PUBLIC_URL", "https://app.example.com")
    # Real signed id_token comes back from the (faked) token exchange; certs
    # are served so the callback verifies it on the LOCAL path.
    monkeypatch.setattr(
        google_auth, "_exchange_code_for_tokens",
        lambda code: {"id_token": _sign_rs256(priv, "k1",
                                              _claims(email="e2e@studio.com"))})
    _install_google(monkeypatch, certs_payload=_jwks_for(priv))

    c = TestClient(main.app, follow_redirects=False)
    state = google_auth.encode_state(code_challenge="", redirect="")
    r = c.get("/v1/auth/google/callback",
              params={"code": "g-code", "state": state})
    assert r.status_code == 302, r.text
    assert "/auth/return?" in r.headers["location"]
    assert db.get_user_by_email("e2e@studio.com") is not None
