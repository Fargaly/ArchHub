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
  * The id_token signature is verified LOCALLY against Google's published
    RSA public keys (the JWKS at GOOGLE_CERTS_URL), with the algorithm
    PINNED to RS256, and the keys cached so the common path makes NO
    per-sign-in network call. If those keys cannot be fetched the verifier
    degrades to Google's tokeninfo endpoint (which checks the signature
    server-side) — a present-but-invalid token is REJECTED locally, never
    bounced to the fallback. Both paths run the SAME _assert_claims trust
    gate (iss/aud/exp/email_verified), so the rules live in one place.
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
import re
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
# Primary verification is LOCAL: the id_token's RS256 signature is checked
# against Google's published RSA public keys (the JWKS at GOOGLE_CERTS_URL),
# cached so the hot path makes no per-sign-in network call. tokeninfo remains
# a graceful fallback used ONLY when those keys cannot be fetched — it
# verifies the signature server-side and returns the decoded claims.
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

# Google rotates its id_token signing keys; the JWKS response carries a
# Cache-Control max-age (hours). We cache the parsed {kid: RSAPublicKey} until
# that deadline so the steady state makes NO network call per sign-in, and
# refetch once on a kid-miss (a rotation). On a fetch FAILURE we set a short
# cooldown so a certs outage doesn't add a failed round-trip to every sign-in
# (we go straight to the tokeninfo fallback during the cooldown).
_JWKS_CACHE: dict = {"keys": {}, "exp": 0, "retry_after": 0, "last_refetch": 0}
_JWKS_DEFAULT_TTL_SECONDS = 3600   # used when the response omits max-age
_JWKS_MIN_TTL_SECONDS = 300        # floor so a tiny max-age can't thrash us
_JWKS_FAILURE_COOLDOWN_SECONDS = 30
# A kid-miss forces a refetch (key rotation); rate-limit it so a flood of
# attacker-chosen bogus kids can't make us hit Google's certs endpoint once
# per request — the very rate-limit/latency pressure local verify removes.
_JWKS_MIN_REFETCH_INTERVAL_SECONDS = 60


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
                 app_state: str = "",
                 now: Optional[int] = None) -> str:
    """Pack the PKCE challenge + desktop return target into a signed,
    opaque, URL-safe state string.

    Layout: base64url(json_payload) + "." + base64url(hmac_sha256). The
    payload carries the code_challenge, the desktop `redirect` (loopback
    target), an optional `app_state` (key `as`) -- the DESKTOP CLIENT's
    own CSRF token, which its loopback server set as `expected_state` and
    must see echoed on the final redirect -- a random nonce (so two starts
    never collide / replay), and an `exp` epoch. The HMAC over the payload
    bytes makes tampering or forging detectable in verify (constant-time
    compared), so the app_state riding INSIDE the payload is tamper-proof:
    it is only ever trusted after decode_state's signature check passes.
    `app_state` is OPTIONAL (defaults "") so the magic-link / no-client-
    state path is unchanged -- a missing `as` simply decodes back to ""."""
    now = int(now if now is not None else time.time())
    payload = {
        "cc": code_challenge or "",
        "rd": redirect or "",
        "as": app_state or "",
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
    expired state -- the CSRF + replay gate. Returns the FULL verified
    payload dict: the carried code_challenge (`cc`), redirect (`rd`), and
    the optional desktop client CSRF token `app_state` (key `as`). A state
    minted without an app_state simply has no `as` key, so callers read it
    as payload.get("as", "") (backward-compatible with older states)."""
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
                            redirect: str = "",
                            app_state: str = "") -> str:
    """Build the Google consent URL the desktop opens (step 1).

    Carries the standard OAuth params (client_id, our fixed
    GOOGLE_OAUTH_REDIRECT, response_type=code, scope) plus the SIGNED
    state that smuggles the desktop's PKCE code_challenge + loopback
    redirect -- and the optional `app_state` (the desktop client's own
    CSRF token) -- across the round-trip. The client secret is NOT
    included; only the public client id appears in this URL.

    Raises GoogleLoginUnconfigured when Google login is disabled."""
    if not config.google_login_enabled():
        raise GoogleLoginUnconfigured("google_login_unconfigured")
    # Google's own `state` param stays the backend's SIGNED state. The
    # desktop client's CSRF token rides INSIDE that signed payload as
    # `app_state` (so it is tamper-proof and echoed back to the loopback
    # unchanged) -- it is NOT a second cleartext param.
    state = encode_state(code_challenge=code_challenge, redirect=redirect,
                         app_state=app_state)
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
        # Fold in any scopes the user already granted this client on a prior
        # consent, so a re-auth doesn't re-prompt for the same access.
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
      * signature — verified LOCALLY against Google's published RSA public
        keys (the JWKS at GOOGLE_CERTS_URL), with the algorithm PINNED to
        RS256 so an `alg:none` or an HS256 key-confusion token is refused.
        The keys are cached, so the steady state makes NO network call here.
      * iss ∈ {accounts.google.com, https://accounts.google.com}
      * aud == GOOGLE_OAUTH_CLIENT_ID  (the token was minted FOR us)
      * exp in the future
      * email present AND email_verified is true

    The signature step degrades to Google's tokeninfo endpoint ONLY when the
    signing keys cannot be fetched (network/parse failure) — a token that is
    present but fails the local signature/structure checks is REJECTED, never
    bounced to the fallback. Either signature path then funnels the decoded
    claims through the SAME _assert_claims gate, so the trust rules live in
    exactly one place regardless of how the signature was checked.
    """
    if not id_token:
        raise GoogleAuthError("empty id_token", status=401,
                              code="id_token_invalid")
    try:
        claims = _verify_signature_local(id_token)
    except _JWKSUnavailable:
        # Google's signing keys are unreachable — fall back to tokeninfo so
        # sign-in availability is never worse than the original implementation.
        claims = _verify_signature_tokeninfo(id_token)
    return _assert_claims(claims)


# ---------------------------------------------------------------------------
# Local JWKS signature verification (primary) + tokeninfo fallback
# ---------------------------------------------------------------------------
class _JWKSUnavailable(RuntimeError):
    """Internal signal: Google's id_token signing keys could not be OBTAINED
    (network / parse failure / cooldown). Distinct from GoogleAuthError — it
    means 'fall back to tokeninfo', NEVER 'reject this token'. A token that is
    present but malformed / wrong-alg / bad-signature raises GoogleAuthError
    (a reject) and is never routed to the fallback."""


def _fetch_google_certs() -> tuple[dict, int]:
    """Fetch + parse Google's JWKS into {kid: RSAPublicKey} and compute a
    cache-expiry epoch from the response Cache-Control max-age.

    Raises _JWKSUnavailable on any network / HTTP / parse failure (so the
    caller degrades to tokeninfo rather than rejecting a token)."""
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
    try:
        resp = httpx.get(
            GOOGLE_CERTS_URL, headers={"Accept": "application/json"},
            timeout=_HTTP_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as ex:
        raise _JWKSUnavailable(f"certs unreachable: {ex}")
    if resp.status_code != 200:
        raise _JWKSUnavailable(f"certs HTTP {resp.status_code}")
    try:
        doc = resp.json()
        jwks = doc["keys"]
    except Exception as ex:
        raise _JWKSUnavailable(f"certs not parseable: {ex}")
    keys: dict = {}
    for jwk in jwks:
        try:
            # Only RSA signing keys; skip anything else (e.g. a future EC key
            # we don't pin for). use="sig" or absent is a signing key.
            if jwk.get("kty") != "RSA" or jwk.get("use") not in (None, "sig"):
                continue
            kid = jwk["kid"]
            n = int.from_bytes(_b64url_decode(jwk["n"]), "big")
            e = int.from_bytes(_b64url_decode(jwk["e"]), "big")
            keys[kid] = RSAPublicNumbers(e, n).public_key()
        except Exception:
            # Skip a single malformed key, keep the rest.
            continue
    if not keys:
        raise _JWKSUnavailable("no usable RSA signing keys in certs")
    ttl = _JWKS_DEFAULT_TTL_SECONDS
    m = re.search(r"max-age=(\d+)", resp.headers.get("Cache-Control", ""))
    if m:
        ttl = max(_JWKS_MIN_TTL_SECONDS, int(m.group(1)))
    return keys, int(time.time()) + ttl


def _ensure_certs_loaded(*, now: Optional[int] = None) -> None:
    """Ensure _JWKS_CACHE holds fresh Google keys. No-op when the cache is
    warm. Honours a short post-failure cooldown so a certs outage doesn't add
    a failed round-trip to every sign-in. Raises _JWKSUnavailable when keys
    cannot be (re)loaded."""
    now = int(now if now is not None else time.time())
    if _JWKS_CACHE["keys"] and now < _JWKS_CACHE["exp"]:
        return
    if now < _JWKS_CACHE["retry_after"]:
        raise _JWKSUnavailable("certs in post-failure cooldown")
    try:
        keys, exp = _fetch_google_certs()
    except _JWKSUnavailable:
        _JWKS_CACHE["retry_after"] = now + _JWKS_FAILURE_COOLDOWN_SECONDS
        raise
    _JWKS_CACHE["keys"] = keys
    _JWKS_CACHE["exp"] = exp
    _JWKS_CACHE["retry_after"] = 0


def _key_for_kid(kid: str, *, now: Optional[int] = None):
    """Return the cached RSAPublicKey for `kid`, forcing a refetch if the kid
    is absent (a key rotation). Returns None when the kid is genuinely unknown
    (→ caller REJECTS the token). May raise _JWKSUnavailable if that refetch
    itself fails.

    The kid-miss refetch is RATE-LIMITED (_JWKS_MIN_REFETCH_INTERVAL_SECONDS):
    a flood of attacker-chosen bogus kids must NOT turn each request into an
    outbound certs fetch — that would re-introduce the very rate-limit/latency
    pressure local verification exists to remove. Within the interval an
    unknown kid is simply unknown (→ reject); a genuine rotation is still
    picked up on the next allowed refetch (and always within the cache TTL)."""
    now = int(now if now is not None else time.time())
    keys = _JWKS_CACHE["keys"]
    if kid in keys:
        return keys[kid]
    if now - _JWKS_CACHE.get("last_refetch", 0) < _JWKS_MIN_REFETCH_INTERVAL_SECONDS:
        return None   # refetched recently → treat an unknown kid as unknown
    fresh, exp = _fetch_google_certs()   # rotation → one rate-limited refetch
    _JWKS_CACHE["keys"] = fresh
    _JWKS_CACHE["exp"] = exp
    _JWKS_CACHE["retry_after"] = 0
    _JWKS_CACHE["last_refetch"] = now
    return fresh.get(kid)


def _verify_signature_local(id_token: str, *, now: Optional[int] = None) -> dict:
    """Verify the id_token's RS256 signature against Google's JWKS LOCALLY and
    return the decoded (but not yet trust-checked) claims. The caller runs
    _assert_claims on the result.

    Rejects (GoogleAuthError 401) a token that is not a JWT, whose alg isn't
    RS256 (so `none` / HS256-confusion are refused), whose kid is unknown, or
    whose signature does not verify. Raises _JWKSUnavailable ONLY when the
    signing keys can't be obtained (→ tokeninfo fallback)."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.exceptions import InvalidSignature

    # Obtain Google's keys BEFORE inspecting the token, so a pure
    # keys-unavailable condition degrades to tokeninfo rather than being
    # masked by a structural rejection of the token.
    _ensure_certs_loaded(now=now)

    parts = id_token.split(".")
    if len(parts) != 3:
        raise GoogleAuthError("id_token is not a JWT", status=401,
                              code="id_token_invalid")
    header_b64, payload_b64, sig_b64 = parts
    try:
        header = json.loads(_b64url_decode(header_b64).decode("utf-8"))
    except Exception:
        raise GoogleAuthError("id_token header not decodable", status=401,
                              code="id_token_invalid")
    if not isinstance(header, dict):
        raise GoogleAuthError("id_token header not an object", status=401,
                              code="id_token_invalid")
    # PIN the algorithm. Google signs id_tokens with RS256. Pinning REJECTS an
    # `alg:none` (unsigned) token and the HS256 key-confusion attack (an
    # attacker HMAC-ing with the RSA public key as the shared secret) — both
    # classic JWT bypasses — instead of trusting the token's self-declared alg.
    if header.get("alg") != "RS256":
        raise GoogleAuthError(
            f"unsupported id_token alg: {header.get('alg')!r}",
            status=401, code="id_token_invalid")
    kid = header.get("kid")
    if not isinstance(kid, str) or not kid:
        raise GoogleAuthError("id_token missing kid", status=401,
                              code="id_token_invalid")
    pub = _key_for_kid(kid, now=now)   # _JWKSUnavailable here → caller's fallback
    if pub is None:
        raise GoogleAuthError("id_token signed by an unknown key",
                              status=401, code="id_token_invalid")
    try:
        signature = _b64url_decode(sig_b64)
    except Exception:
        raise GoogleAuthError("id_token signature not decodable", status=401,
                              code="id_token_invalid")
    # Verify over the EXACT received signing input bytes (header.payload), not
    # a re-encoding — re-serialising the JSON could change the bytes.
    signing_input = (header_b64 + "." + payload_b64).encode("ascii")
    try:
        pub.verify(signature, signing_input, padding.PKCS1v15(),
                   hashes.SHA256())
    except InvalidSignature:
        raise GoogleAuthError("id_token signature does not verify",
                              status=401, code="id_token_invalid")
    # Signature is Google's — NOW decode the claims (trust-gated downstream).
    try:
        claims = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except Exception:
        raise GoogleAuthError("id_token payload not decodable", status=401,
                              code="id_token_invalid")
    if not isinstance(claims, dict):
        raise GoogleAuthError("id_token payload not an object", status=401,
                              code="id_token_invalid")
    return claims


def _verify_signature_tokeninfo(id_token: str) -> dict:
    """Fallback signature check via Google's tokeninfo endpoint, used ONLY when
    the local JWKS keys are unreachable. Returns the decoded claims (the caller
    runs _assert_claims). Keeps sign-in availability no worse than the original
    tokeninfo-only implementation."""
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
        return resp.json()
    except Exception:
        raise GoogleAuthError("tokeninfo response not JSON",
                              status=401, code="id_token_invalid")


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
    # Compare on bytes: hmac.compare_digest over two str raises TypeError if
    # either holds a non-ASCII char; encoding first keeps the constant-time
    # compare and fails CLEANLY (401) on any odd input instead of a 500.
    if not config.GOOGLE_OAUTH_CLIENT_ID or not hmac.compare_digest(
            aud.encode("utf-8"),
            config.GOOGLE_OAUTH_CLIENT_ID.encode("utf-8")):
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
    # The desktop client's own CSRF token, recovered from the now-VERIFIED
    # signed payload (decode_state already checked the HMAC + expiry). It is
    # echoed back UNCHANGED on the final loopback redirect so the client's
    # _CallbackHandler.expected_state check passes. Empty for the magic-link
    # / no-client-state path (the `as` key is then absent).
    app_state = payload.get("as") or ""
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
    # Echo the client's CSRF token so /auth/return forwards it to the
    # loopback as `state=<app_state>` -- satisfying the desktop's
    # expected_state check (the SECOND CSRF layer, client <-> loopback).
    # Omitted when absent so the magic-link path is byte-for-byte unchanged.
    if app_state:
        return_params["state"] = app_state
    return (
        config.PUBLIC_URL.rstrip("/") + "/auth/return?"
        + urllib.parse.urlencode(return_params)
    )
