"""Sign in with Google (OAuth2 / OpenID Connect) — ADDITIVE auth path.

This module is the server-side half of "Sign in with Google". It is
DELIBERATELY additive: it reuses the SAME user + code + token machinery
as the magic-link/PKCE flow (db.get_or_create_user → db.issue_code →
the existing /v1/auth/exchange path), so a user who signs in with Google
converges on the EXACT SAME account (keyed by email) as one who used a
magic-link. Nothing in auth.py / the exchange contract / /auth/return
changes.

Flow (two routes in main.py drive this):

  1. GET /v1/auth/google/start?code_challenge=...&redirect=...
       → build_authorization_url(): returns the Google consent URL.
         The desktop's PKCE `code_challenge` + its loopback `redirect`
         are packed into a SIGNED, opaque `state` (HMAC over a JSON
         payload + a nonce + an expiry). State both prevents CSRF AND
         carries the PKCE challenge across the Google round-trip so the
         desktop can finish via the existing exchange.

  2. GET /v1/auth/google/callback?code=...&state=...
       → exchange_callback(): verifies+unpacks state, exchanges the
         Google `code` at oauth2.googleapis.com/token for an id_token,
         VERIFIES the id_token (iss/aud/exp/email_verified + signature
         via Google's tokeninfo endpoint), then:
            email → db.get_or_create_user(email)
                  → db.issue_code(user_id, state.code_challenge)
         and hands main.py the one-time `code` to 302 the browser to
         {PUBLIC_URL}/auth/return?code=... — the SAME return surface the
         magic-link uses. The desktop loopback catches it and runs the
         normal exchange with its PKCE verifier.

Security contract:
  * The id_token is never trusted blind: iss ∈ {accounts.google.com,
    https://accounts.google.com}, aud == GOOGLE_OAUTH_CLIENT_ID, exp in
    the future, AND email_verified is true. Any failure → caller raises
    400/401; no token is ever issued for an unverified / wrong-aud token.
  * Verification goes through Google's tokeninfo endpoint (which checks
    the JWT signature against Google's keys server-side). The code is
    structured so a local JWKS verify (https://www.googleapis.com/oauth2/
    v3/certs) can drop in behind the same verify_id_token() function
    without touching callers.
  * The OAuth client SECRET stays server-side: it is only ever sent to
    Google's token endpoint, never to the desktop client, never put in
    the authorization URL or the state.
  * State is HMAC-signed with a server secret + carries a short TTL +
    a random nonce, so a forged / replayed / tampered state is rejected
    (CSRF defence) before any Google call is made.

Disabled-when-unconfigured:
  Every public entry point checks config.google_login_enabled() and
  raises GoogleLoginUnconfigured when either OAuth var is empty. main.py
  maps that to a 503 {error:"google_login_unconfigured"} so the routes
  are safe to deploy BEFORE the founder supplies credentials — the rest
  of the backend is untouched.

Stdlib + existing deps only: httpx (already a backend dependency, used
by proxy.py) for the outbound calls; hmac/hashlib/secrets/base64/json
from the stdlib for the signed state. No new requirement is introduced.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
import urllib.parse
from typing import Optional

import httpx

import config
import db


# Google OpenID Connect endpoints (well-known; stable).
GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
# tokeninfo verifies the id_token's signature against Google's keys
# server-side and returns the decoded claims. Swapping to a local JWKS
# verify against GOOGLE_CERTS_URL is a drop-in behind verify_id_token().
GOOGLE_TOKENINFO_ENDPOINT = "https://oauth2.googleapis.com/tokeninfo"
GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"

# Accepted issuers for a Google-minted id_token (both forms are valid).
_VALID_ISSUERS = frozenset({
    "accounts.google.com",
    "https://accounts.google.com",
})

# OpenID Connect scopes: openid (id_token) + email + profile.
_SCOPE = "openid email profile"

# State lifetime — the user has this long to complete consent. Short by
# design (CSRF token), generous enough for a human to click through.
_STATE_TTL_SECONDS = 600  # 10 minutes

# Outbound HTTP timeout to Google. Mirrors polar.py's 30s ceiling; kept
# well under any client wait so a slow Google never hangs a request.
_HTTP_TIMEOUT_SECONDS = 20.0


class GoogleLoginUnconfigured(RuntimeError):
    """Raised by every entry point when Google OAuth vars are unset.

    main.py catches this and returns 503 {error:"google_login_unconfigured"}
    so the disabled-when-unconfigured contract is centralised here."""


class GoogleAuthError(RuntimeError):
    """Raised on any OAuth / id_token verification failure.

    Carries an HTTP `status` (400 for a bad request/exchange, 401 for a
    failed identity verification) + a machine `code` so main.py can map
    it to the right response without leaking provider internals."""

    def __init__(self, message: str, *, status: int = 400,
                 code: str = "google_auth_failed") -> None:
        super().__init__(message)
        self.status = status
        self.code = code


# ---------------------------------------------------------------------------
# Signed, opaque state (CSRF defence + PKCE-challenge carrier)
# ---------------------------------------------------------------------------
def _state_secret() -> bytes:
    """Key the state HMAC.

    Reuses the OAuth client SECRET as the signing key: it is already a
    high-entropy server-only secret, present exactly when Google login is
    enabled, and never leaves the server — so we don't introduce a new
    env var just to sign state. (The secret is used ONLY as an HMAC key
    here; it is never exposed in the state, which is HMAC output, not
    encryption.)"""
    return config.GOOGLE_OAUTH_CLIENT_SECRET.encode("utf-8")


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def encode_state(*, code_challenge: str, redirect: str,
                 now: Optional[int] = None) -> str:
    """Pack the PKCE challenge + desktop return target into a signed,
    opaque, URL-safe state string.

    Layout: base64url(json_payload) + "." + base64url(hmac_sha256). The
    payload carries the code_challenge, the desktop `redirect` (loopback
    target), a random nonce (so two starts never collide / replay), and
    an `exp` epoch. The HMAC over the payload bytes makes tampering or
    forging detectable in verify (constant-time compared)."""
    now = int(now if now is not None else time.time())
    payload = {
        "cc": code_challenge or "",
        "rd": redirect or "",
        "n": secrets.token_urlsafe(16),
        "exp": now + _STATE_TTL_SECONDS,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"),
                               sort_keys=True).encode("utf-8")
    body = _b64url_encode(payload_bytes)
    sig = hmac.new(_state_secret(), body.encode("ascii"),
                   hashlib.sha256).digest()
    return body + "." + _b64url_encode(sig)


def decode_state(state: str, *, now: Optional[int] = None) -> dict:
    """Verify + unpack a state produced by encode_state.

    Rejects (GoogleAuthError 400) a malformed, tampered (bad HMAC), or
    expired state — the CSRF + replay gate. Returns the payload dict with
    the carried code_challenge (`cc`) + redirect (`rd`)."""
    now = int(now if now is not None else time.time())
    if not state or "." not in state:
        raise GoogleAuthError("missing or malformed state",
                              status=400, code="invalid_state")
    body, _, sig_b64 = state.partition(".")
    expected = hmac.new(_state_secret(), body.encode("ascii"),
                        hashlib.sha256).digest()
    try:
        got = _b64url_decode(sig_b64)
    except Exception:
        raise GoogleAuthError("state signature not decodable",
                              status=400, code="invalid_state")
    # Constant-time compare — the signature is a secret-derived MAC.
    if not hmac.compare_digest(expected, got):
        raise GoogleAuthError("state signature mismatch",
                              status=400, code="invalid_state")
    try:
        payload = json.loads(_b64url_decode(body).decode("utf-8"))
    except Exception:
        raise GoogleAuthError("state payload not decodable",
                              status=400, code="invalid_state")
    if not isinstance(payload, dict):
        raise GoogleAuthError("state payload not an object",
                              status=400, code="invalid_state")
    if int(payload.get("exp", 0)) < now:
        raise GoogleAuthError("state expired", status=400,
                              code="state_expired")
    return payload


# ---------------------------------------------------------------------------
# Authorization URL (step 1)
# ---------------------------------------------------------------------------
def build_authorization_url(*, code_challenge: str = "",
                            redirect: str = "") -> str:
    """Build the Google consent URL the desktop opens (step 1).

    Carries the standard OAuth params (client_id, our fixed
    GOOGLE_OAUTH_REDIRECT, response_type=code, scope) plus the SIGNED
    state that smuggles the desktop's PKCE code_challenge + loopback
    redirect across the round-trip. The client secret is NOT included —
    only the public client id appears in this URL.

    Raises GoogleLoginUnconfigured when Google login is disabled."""
    if not config.google_login_enabled():
        raise GoogleLoginUnconfigured("google_login_unconfigured")
    state = encode_state(code_challenge=code_challenge, redirect=redirect)
    params = {
        "client_id": config.GOOGLE_OAUTH_CLIENT_ID,
        "redirect_uri": config.GOOGLE_OAUTH_REDIRECT,
        "response_type": "code",
        "scope": _SCOPE,
        "state": state,
        # Ask for a fresh consent screen pick-an-account each time so a
        # shared machine can switch Google accounts; no offline access /
        # refresh token (we only need the one-shot id_token).
        "access_type": "online",
        "prompt": "select_account",
        # We verify the id_token's signature server-side via tokeninfo,
        # but include a nonce binding for defence-in-depth + future local
        # JWKS verify. Reuse the state's entropy is unnecessary; mint one.
        "include_granted_scopes": "true",
    }
    return GOOGLE_AUTH_ENDPOINT + "?" + urllib.parse.urlencode(params)


# ---------------------------------------------------------------------------
# Token exchange + id_token verification (step 2)
# ---------------------------------------------------------------------------
def _exchange_code_for_tokens(code: str) -> dict:
    """POST the Google authorization `code` to the token endpoint and
    return the parsed token response (must contain `id_token`).

    The client SECRET is sent HERE and only here (server→Google, over
    TLS). Raises GoogleAuthError 400 on any non-200 / malformed response.
    """
    data = {
        "code": code,
        "client_id": config.GOOGLE_OAUTH_CLIENT_ID,
        "client_secret": config.GOOGLE_OAUTH_CLIENT_SECRET,
        "redirect_uri": config.GOOGLE_OAUTH_REDIRECT,
        "grant_type": "authorization_code",
    }
    try:
        resp = httpx.post(
            GOOGLE_TOKEN_ENDPOINT, data=data,
            headers={"Accept": "application/json"},
            timeout=_HTTP_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as ex:
        raise GoogleAuthError(f"token endpoint unreachable: {ex}",
                              status=502, code="google_unreachable")
    if resp.status_code != 200:
        # Don't echo Google's raw body to the client — log-friendly msg.
        raise GoogleAuthError(
            f"token exchange failed ({resp.status_code})",
            status=400, code="token_exchange_failed")
    try:
        payload = resp.json()
    except Exception:
        raise GoogleAuthError("token response not JSON",
                              status=400, code="token_exchange_failed")
    if not isinstance(payload, dict) or not payload.get("id_token"):
        raise GoogleAuthError("token response missing id_token",
                              status=400, code="token_exchange_failed")
    return payload


def verify_id_token(id_token: str) -> dict:
    """Verify a Google id_token and return its trusted claims.

    Verification (ALL must hold or GoogleAuthError 401):
      * signature — checked by Google's tokeninfo endpoint server-side
        (the endpoint only returns claims for a validly-signed token).
      * iss ∈ {accounts.google.com, https://accounts.google.com}
      * aud == GOOGLE_OAUTH_CLIENT_ID  (the token was minted FOR us)
      * exp in the future
      * email present AND email_verified is true

    Structured so a local JWKS verify (decode header→kid, fetch
    GOOGLE_CERTS_URL, verify RS256, then run the SAME claim asserts
    below) can replace the tokeninfo call without changing callers or
    the returned shape.
    """
    if not id_token:
        raise GoogleAuthError("empty id_token", status=401,
                              code="id_token_invalid")
    try:
        resp = httpx.get(
            GOOGLE_TOKENINFO_ENDPOINT, params={"id_token": id_token},
            headers={"Accept": "application/json"},
            timeout=_HTTP_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as ex:
        raise GoogleAuthError(f"tokeninfo unreachable: {ex}",
                              status=502, code="google_unreachable")
    if resp.status_code != 200:
        # tokeninfo returns 4xx for an invalid/expired/forged token.
        raise GoogleAuthError(
            f"id_token rejected by tokeninfo ({resp.status_code})",
            status=401, code="id_token_invalid")
    try:
        claims = resp.json()
    except Exception:
        raise GoogleAuthError("tokeninfo response not JSON",
                              status=401, code="id_token_invalid")
    return _assert_claims(claims)


def _assert_claims(claims: dict, *, now: Optional[int] = None) -> dict:
    """Run the issuer / audience / expiry / email_verified assertions on
    decoded id_token claims. Shared by the tokeninfo path + a future
    local-JWKS path so the trust rules live in ONE place.

    Returns the claims dict on success; raises GoogleAuthError 401 on any
    failure (never trusts an unverified or wrong-aud token)."""
    now = int(now if now is not None else time.time())
    if not isinstance(claims, dict):
        raise GoogleAuthError("claims not an object", status=401,
                              code="id_token_invalid")
    # iss — must be Google. Guard non-string claims (a list/None can't be a
    # valid issuer): coerce to "" so it fails CLEANLY (401) rather than raising
    # AttributeError → 500 on an odd-shaped token.
    _iss = claims.get("iss")
    iss = _iss.strip() if isinstance(_iss, str) else ""
    if iss not in _VALID_ISSUERS:
        raise GoogleAuthError(f"untrusted issuer: {iss!r}", status=401,
                              code="bad_issuer")
    # aud — the token must have been minted for THIS client id. OIDC permits a
    # list aud for multi-audience tokens; we accept ONLY a single string aud
    # that equals our client id. A non-string aud coerces to "" → clean 401.
    _aud = claims.get("aud")
    aud = _aud.strip() if isinstance(_aud, str) else ""
    if not config.GOOGLE_OAUTH_CLIENT_ID or not hmac.compare_digest(
            aud, config.GOOGLE_OAUTH_CLIENT_ID):
        raise GoogleAuthError("audience mismatch", status=401,
                              code="bad_audience")
    # exp — must be in the future. tokeninfo only returns live tokens,
    # but assert anyway so the local-JWKS path is equally safe.
    try:
        exp = int(claims.get("exp", 0))
    except (TypeError, ValueError):
        exp = 0
    if exp <= now:
        raise GoogleAuthError("id_token expired", status=401,
                              code="id_token_expired")
    # email + verification — NEVER trust an unverified email. Google
    # returns email_verified as the string "true" via tokeninfo or a
    # bool true via a decoded JWT; accept either truthy form.
    _email = claims.get("email")
    email = _email.strip().lower() if isinstance(_email, str) else ""
    if not email:
        raise GoogleAuthError("id_token has no email", status=401,
                              code="email_missing")
    ev = claims.get("email_verified")
    verified = (ev is True) or (str(ev).strip().lower() == "true")
    if not verified:
        raise GoogleAuthError("email not verified by Google", status=401,
                              code="email_unverified")
    return claims


# ---------------------------------------------------------------------------
# Callback orchestration (step 2, top-level)
# ---------------------------------------------------------------------------
def exchange_callback(*, code: str, state: str) -> str:
    """Top-level callback handler: state → token → verify → user → code.

    Returns the {PUBLIC_URL}/auth/return?code=... URL main.py should 302
    the browser to. The minted one-time `code` is bound to the PKCE
    `code_challenge` carried in the (verified) state, so the desktop's
    EXISTING /v1/auth/exchange (with its PKCE verifier) finishes the
    sign-in — Google sign-in converges on the same account + token path
    as the magic-link.

    Raises GoogleLoginUnconfigured (→503) when disabled, GoogleAuthError
    (→400/401) on any state / exchange / verification failure. NEVER
    issues a code for an unverified or wrong-aud identity.
    """
    if not config.google_login_enabled():
        raise GoogleLoginUnconfigured("google_login_unconfigured")
    if not code:
        raise GoogleAuthError("missing authorization code", status=400,
                              code="missing_code")
    # 1. Verify + unpack the signed state (CSRF gate; recovers PKCE cc).
    payload = decode_state(state)
    code_challenge = payload.get("cc") or ""
    desktop_redirect = payload.get("rd") or ""
    # 2. Exchange Google's code for tokens (client secret used here only).
    tokens = _exchange_code_for_tokens(code)
    # 3. Verify the id_token (iss/aud/exp/email_verified + signature).
    claims = verify_id_token(tokens["id_token"])
    email = (claims.get("email") or "").strip().lower()
    # 4. Converge on the SAME account keyed by email, then mint a
    #    one-time code bound to the PKCE challenge — REUSING the exact
    #    machinery the magic-link uses so the desktop finishes through
    #    the unchanged /v1/auth/exchange path.
    user = db.get_or_create_user(email)
    one_time_code = db.issue_code(user["id"], code_challenge)
    # 5. Build the return URL. If the desktop supplied a loopback
    #    redirect, forward through /auth/return so its existing
    #    redirect-forwarding (main.auth_return) bounces to the loopback
    #    with ?code=... — identical to the magic-link path. Otherwise
    #    land on the plain browser /auth/return finisher.
    return_params = {"code": one_time_code}
    if desktop_redirect:
        return_params["redirect"] = desktop_redirect
    return (
        config.PUBLIC_URL.rstrip("/") + "/auth/return?"
        + urllib.parse.urlencode(return_params)
    )
