"""ArchHub Cloud backend — FastAPI app.

Endpoints (matches docs/BACKEND_SPEC.md):
  GET  /v1/auth/google/start    (the one human sign-in: Google)
  GET  /v1/auth/google/callback
  POST /v1/auth/exchange
  GET  /v1/me
  POST /v1/chat/completions
  POST /v1/billing/checkout
  GET  /v1/billing/portal
  POST /v1/webhooks/stripe
  GET  /healthz                 (Fly.io health check)
  GET  /signin                  (one "Continue with Google" button)

Auth model: bearer token in `Authorization: Bearer <token>`. Tokens
are minted by /v1/auth/exchange after the user signs in with Google.
The client-side PKCE pair binds the desktop instance to the auth-code
lookup. Google is the only human sign-in; email sign-in was removed
(founder 2026-09-28: one source, no magic link).

Run locally:
    pip install -r requirements.txt
    export ENV=development
    uvicorn main:app --reload --port 8000

Deploy:
    docker build -t archhub-cloud .
    flyctl deploy   # OR
    docker run -p 8000:8000 archhub-cloud
"""
from __future__ import annotations

import time
import urllib.parse

from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    HTMLResponse, RedirectResponse, JSONResponse, Response,
)
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

import auth
import billing
import companies
import config
import db
import founder_cockpit
import google_auth
import marketplace
import proxy
import readiness


# Hide the interactive API docs + OpenAPI schema in production / on Fly so
# the public endpoint map is not exposed to anonymous visitors (security
# audit 2026-06-22). Local dev keeps /docs for convenience.
_HIDE_API_DOCS = config.is_production() or config._on_fly()
app = FastAPI(
    title="ArchHub Cloud",
    version="1.0.0",
    description="Managed AI proxy for the ArchHub desktop client.",
    docs_url=None if _HIDE_API_DOCS else "/docs",
    redoc_url=None if _HIDE_API_DOCS else "/redoc",
    openapi_url=None if _HIDE_API_DOCS else "/openapi.json",
)


# Only the desktop client + the public website need to call this
# backend. CORS-allow our own origin so the public dashboard at
# archhub.io can fetch /v1/me from the browser.
_PROD_ORIGINS = ["https://archhub.io"]
_DEV_ORIGINS = ["http://localhost:5173", "http://localhost:3000"]


def _cors_origins() -> list[str]:
    """Dev origins only when NOT production and NOT on Fly (the same gate
    as the docs endpoints); a credentialed allowlist must not ship them."""
    if _HIDE_API_DOCS:
        return list(_PROD_ORIGINS)
    return _PROD_ORIGINS + _DEV_ORIGINS


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    # Fail loud BEFORE serving traffic if ENV=production but a required
    # secret (auth/email/billing) is unset. No-op when ENV is unset, so
    # the dev-tolerant boot + /healthz stay green pre-secrets. Runs first
    # so a misconfigured prod box never reaches init_schema / serving.
    config.assert_production_ready()
    db.init_schema()


# Marketplace v1 routes — author upload, browse, install, review, report.
# Mounted at root (paths start /marketplace/...) so the desktop client's
# URL constants live next to /v1/* rather than under a separate prefix.
app.include_router(marketplace.router)

# Companies / multi-seat — POST /v1/companies, invites, members, switch.
app.include_router(companies.router)

# Founder Cockpit (PHASE 5) — PRIVATE founder-only admin dashboard. Every
# route is behind founder_cockpit.require_founder (email == FOUNDER_EMAIL);
# everyone else (incl. unauthenticated) gets 403. Cloud-backend only — it is
# NOT part of the desktop user app.
app.include_router(founder_cockpit.router)


# Feed the cockpit's in-process error ring from unhandled server errors.
# This is the minimal error store the founder dashboard surfaces — it appends
# on every uncaught exception, then re-raises so FastAPI's normal 500 handling
# is unchanged. HTTPExceptions with 5xx status are recorded too (a 5xx is a
# server fault worth seeing); 4xx client errors are intentionally NOT recorded
# (they are not server faults and would drown the ring in routine auth misses).
@app.exception_handler(HTTPException)
async def _record_http_exc(request: Request, exc: HTTPException):
    from fastapi.exception_handlers import http_exception_handler
    if exc.status_code >= 500:
        founder_cockpit.record_error(
            where=str(request.url.path), kind="HTTPException",
            message=str(exc.detail), status=exc.status_code)
    return await http_exception_handler(request, exc)


# The email sign-in route is gone (founder 2026-09-28: Google only). A
# desktop install that still offers it gets a 404 that says so plainly
# instead of a bare "Not Found".
_REMOVED_SIGN_IN = {
    "/v1/auth/register": "Email sign-in was removed; use Continue with Google.",
}


@app.exception_handler(StarletteHTTPException)
async def _removed_sign_in_reads_plainly(request: Request,
                                         exc: StarletteHTTPException):
    from fastapi.exception_handlers import http_exception_handler
    removed = _REMOVED_SIGN_IN.get(str(request.url.path))
    if removed and exc.status_code in (404, 405):
        return JSONResponse(status_code=404, content={
            "error": "email_signin_removed", "detail": removed})
    return await http_exception_handler(request, exc)


@app.exception_handler(Exception)
async def _record_unhandled_exc(request: Request, exc: Exception):
    founder_cockpit.record_error(
        where=str(request.url.path), kind=type(exc).__name__,
        message=str(exc), status=500)
    return JSONResponse(status_code=500,
                        content={"detail": "internal_server_error"})


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class ExchangeReq(BaseModel):
    code: str = Field(min_length=10, max_length=200)
    # PKCE verifier. For a code issued WITH a non-empty challenge
    # (desktop client), the exchange MUST present a matching verifier —
    # main enforces a real min_length on that path (see `exchange`
    # below) so a challenged code can't be redeemed with an empty
    # verifier. Browser-direct codes are issued with an EMPTY challenge
    # (a Google sign-in begun in the browser, no desktop PKCE pair; the
    # one-time, 5-min code is the secret); those legitimately pass an
    # empty verifier, so the field default stays "".
    code_verifier: str = Field(default="", max_length=200)


class LogoutReq(BaseModel):
    # When true, revoke EVERY token the caller holds ("sign out of all
    # devices"). Default false = revoke only the current bearer token.
    all_sessions: bool = False


class CheckoutReq(BaseModel):
    tier: str
    # Model C: per-seat checkout. seats is clamped to the tier floor
    # server-side (Firm ≥ 10); annual selects the −20% price id.
    seats: int | None = Field(default=None, ge=1, le=100000)
    annual: bool = False


class AiModeReq(BaseModel):
    ai_mode: str = Field(pattern="^(byo_key|hosted)$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _bearer(authorization: str | None) -> str:
    """Extract the bearer token or raise 401."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401,
                             detail="missing_or_invalid_authorization")
    return authorization.split(None, 1)[1].strip()


def _require_user(authorization: str | None) -> dict:
    token = _bearer(authorization)
    user = db.user_for_token(token)
    if user is None:
        raise HTTPException(status_code=401, detail="invalid_token")
    return user


# Loopback hosts a desktop client's OAuth return server can legitimately
# bind to. The Google start route only forwards the minted one-time code
# to a redirect that resolves to one of these — never an arbitrary host.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})


def _is_loopback_redirect(redirect: str) -> bool:
    """True iff `redirect` is a syntactically-valid http(s) URL whose host
    is loopback (127.0.0.1 / localhost / ::1).

    This is the open-redirect guard for /v1/auth/google/start: the Google
    callback ends up 302-ing a freshly-minted one-time auth code to this
    target, so an attacker-supplied off-host redirect would leak the code.
    Restricting to loopback means the code can only ever bounce back to a
    server running on the user's OWN machine (the desktop client's
    `http://127.0.0.1:<port>/cb` loopback), never to a remote host.

    An empty redirect is NOT loopback (callers treat "" as "no redirect
    supplied" and keep the unchanged browser-finish behaviour); this
    helper only judges a non-empty value.
    """
    if not redirect:
        return False
    try:
        parsed = urllib.parse.urlparse(redirect)
    except ValueError:
        # urlparse raises on e.g. an out-of-range IPv6 zone — treat as
        # unparseable → not loopback (reject) rather than 500.
        return False
    # Scheme must be http/https — block javascript:, data:, file:, custom
    # app schemes, and scheme-relative ("//evil.com") or relative values
    # (which have no host and could be reinterpreted by the browser).
    if parsed.scheme not in ("http", "https"):
        return False
    # `hostname` is lower-cased + strips an IPv6 [...] bracket and any
    # :port / userinfo, so "127.0.0.1:8731" → "127.0.0.1" and credentials
    # like "user@evil.com" can't smuggle a fake host past the check.
    host = (parsed.hostname or "").lower()
    return host in _LOOPBACK_HOSTS


def _loopback_return_url(redirect: str, *, code: str, state: str) -> str:
    """Build the FINAL desktop-loopback return URL from VALIDATED, RECONSTRUCTED
    parts — never by interpolating the raw user-supplied `redirect` string.

    Returns "" when `redirect` is not a loopback http(s) URL (caller 400s).
    Otherwise returns `<scheme>://<loopback-host>[:port]<path>?code=..&state=..`
    rebuilt with urlunparse from the parsed components (scheme/host/port/path),
    with the host pinned to the loopback allowlist. Because the emitted value is
    assembled from re-validated parts (and the query is set by us from `code`/
    `state`, url-encoded), no tainted data flows into the redirect Location
    header (CodeQL py/url-redirection). Any query/fragment smuggled in the
    supplied redirect is dropped — the desktop loopback only ever needs
    code+state, matching the historical `?code=..&state=..` output."""
    if not redirect:
        return ""
    try:
        parsed = urllib.parse.urlparse(redirect)
    except ValueError:
        return ""
    if parsed.scheme not in ("http", "https"):
        return ""
    host = (parsed.hostname or "").lower()
    if host not in _LOOPBACK_HOSTS:
        return ""
    # Re-pin the netloc to the validated loopback host (+ original port). The
    # host is taken from the fixed _LOOPBACK_HOSTS membership we just proved, so
    # it is one of a closed set of constants, not arbitrary input.
    netloc = host
    if parsed.port:
        netloc = f"{host}:{parsed.port}"
    path = parsed.path or "/"
    query = urllib.parse.urlencode({"code": code, "state": state})
    return urllib.parse.urlunparse((parsed.scheme, netloc, path, "", query, ""))


def _website_return_origin(redirect: str) -> str:
    """If `redirect` is a URL whose ORIGIN is one of the FIXED, allowlisted
    website origins (config.WEBSITE_RETURN_ORIGINS), return that canonical
    origin (scheme://host[:port]); otherwise return "".

    This is the cross-domain counterpart of `_is_loopback_redirect`: it lets
    /auth/return bounce the one-time code back to the marketing site
    (archhub.io) so a Google sign-in finishes signed-in
    ON the website. It is NOT an open redirect — the origin must EXACTLY
    match an entry in the fixed allowlist (scheme + host + optional port),
    so an attacker host, a protocol-relative "//evil.com", a non-https
    scheme, or "https://archhub.io.evil.com" all return "" (rejected).

    Note we compare on the ORIGIN only (scheme/host/port), never the path —
    the redirect we ultimately emit uses our OWN fixed path
    ("{origin}/signin"), so a smuggled path in the supplied redirect can
    never steer where the code lands.
    """
    if not redirect:
        return ""
    try:
        parsed = urllib.parse.urlparse(redirect)
    except ValueError:
        return ""
    if parsed.scheme not in ("http", "https"):
        return ""
    host = (parsed.hostname or "").lower()
    if not host:
        # Scheme-relative ("//evil.com") or path-only values have no host —
        # reject so they can't be reinterpreted by the browser.
        return ""
    # Rebuild a canonical origin from the PARSED parts (never the raw string)
    # so userinfo / fragments / a smuggled path cannot ride along. This local
    # `origin` is used ONLY as an exact-match lookup key — the value we RETURN
    # comes from the fixed allowlist constant (config.canonical_website_return_
    # origin), not from the request, so no tainted data flows out to a redirect
    # Location header (CodeQL py/url-redirection).
    origin = f"{parsed.scheme.lower()}://{host}"
    if parsed.port:
        origin = f"{origin}:{parsed.port}"
    return config.canonical_website_return_origin(origin)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/", include_in_schema=False)
def root_door():
    """api.archhub.io/ is the cockpit's door, not a 404: browsers go to the
    founder surface (which sends the unsigned to /founder/login); the API
    itself lives under /v1."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/founder", status_code=307)


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "ts": int(time.time())}


@app.get("/readyz")
def readyz() -> dict:
    return readiness.capability_report()


# PKCE verifiers are 43-128 chars of unreserved-charset entropy
# (RFC 7636 §4.1). The desktop client sends a 32-byte urlsafe verifier
# (~43 chars). We re-impose this floor — lost when ExchangeReq.code_verifier
# dropped its min_length — but CONDITIONALLY: only a NON-EMPTY verifier is
# length-checked, so the browser-direct empty-verifier path (challenge was
# empty) still works. The db layer separately rejects an empty verifier
# against a CHALLENGED code, so the two together mean: a code issued with a
# challenge cannot be exchanged without a real, matching verifier.
_PKCE_VERIFIER_MIN_LEN = 43


@app.post("/v1/auth/exchange")
def exchange(req: ExchangeReq) -> dict:
    verifier = req.code_verifier or ""
    if verifier and len(verifier) < _PKCE_VERIFIER_MIN_LEN:
        # A verifier was supplied but is too short to be a real PKCE
        # secret — reject rather than let a weak/truncated value through.
        raise HTTPException(status_code=422,
                            detail="code_verifier_too_short")
    payload = auth.exchange_code(
        code=req.code, code_verifier=verifier,
    )
    if payload is None:
        raise HTTPException(status_code=400, detail="invalid_or_expired")
    return payload


# ── Sign in with Google (OAuth2 / OpenID Connect): THE human sign-in ──────────
# Two routes on the user + code + token machinery. They use
# db.get_or_create_user + db.issue_code + /auth/return so a Google
# sign-in lands on the account keyed by its email (accounts made before
# Google keep their data) and finishes through /v1/auth/exchange.
#
# Disabled-when-unconfigured: with the OAuth vars unset (the CURRENT
# deployment) both routes return a clean 503 {error:
# "google_login_unconfigured"} via the GoogleLoginUnconfigured guard —
# nothing else changes, so this is safe to deploy before the founder
# supplies credentials.
@app.get("/v1/auth/google/start")
def google_start(code_challenge: str = "", redirect: str = "",
                 state: str = "") -> dict:
    """Step 1: hand the desktop client the Google consent URL.

    The desktop generates a PKCE pair and
    passes its `code_challenge` + optional loopback `redirect` (its own
    `http://127.0.0.1:<port>/cb` return server). Both are packed into a
    signed, opaque state and returned as {auth_url}; the client opens it
    with webbrowser.open. After consent the callback 302s the minted
    one-time code to that loopback so the desktop finishes the existing
    /v1/auth/exchange. 503 when Google login isn't configured.

    ADDITIVE: `redirect` is OPTIONAL -- omit it and the flow lands on the
    plain browser /auth/return finisher exactly as before. `state` is the
    desktop client's own CSRF token (its loopback set it as
    expected_state); it is packed INTO the signed state and echoed back to
    the loopback on the final redirect. Optional -- a sign-in begun in the
    browser sends none.

    Open-redirect guard: a SUPPLIED redirect must be EITHER a loopback
    (127.0.0.1 / localhost / ::1) http(s) URL — the desktop client's own
    return server — OR one of the FIXED allowlisted website origins
    (archhub.io / archhub-web.fly.dev) so the marketing site's Google
    sign-in lands back ON the website. Because the callback ends up
    forwarding a freshly-minted auth code to this target via /auth/return,
    any OTHER host is rejected (400 google_redirect_not_allowed) so a code
    can never be bounced to an attacker-controlled URL. The website case
    carries the bare ORIGIN; /auth/return appends our own fixed "/signin".
    """
    if redirect and not (
            _is_loopback_redirect(redirect)
            or _website_return_origin(redirect)):
        raise HTTPException(
            status_code=400,
            detail={"error": "google_redirect_not_allowed"})
    try:
        url = google_auth.build_authorization_url(
            code_challenge=code_challenge, redirect=redirect,
            # Thread the desktop client's CSRF `state` INTO the signed
            # state so it survives the Google round-trip and is echoed back
            # to the loopback (fixes "Security state mismatch"). Optional.
            app_state=state,
        )
    except google_auth.GoogleLoginUnconfigured:
        raise HTTPException(status_code=503,
                            detail={"error": "google_login_unconfigured"})
    return {"auth_url": url}


@app.get("/v1/auth/google/callback")
def google_callback(code: str = "", state: str = "",
                    error: str = "") -> RedirectResponse:
    """Step 2: Google redirects here after consent.

    Verifies the signed state (CSRF), exchanges the Google `code` for an
    id_token, VERIFIES it (iss/aud/exp/email_verified + signature), then
    mints a one-time code bound to the state's PKCE challenge and 302s to
    {PUBLIC_URL}/auth/return?code=..., so the desktop loopback finishes
    via /v1/auth/exchange.

    503 when unconfigured; 400/401 on any state/exchange/verification
    failure (an unverified or wrong-aud token NEVER yields a code).
    """
    # The user denied consent (or Google returned an error) — surface it
    # cleanly rather than attempting an exchange with no code.
    if error:
        raise HTTPException(status_code=400,
                            detail={"error": "google_consent_failed",
                                    "reason": error})
    try:
        return_url = google_auth.exchange_callback(code=code, state=state)
    except google_auth.GoogleLoginUnconfigured:
        raise HTTPException(status_code=503,
                            detail={"error": "google_login_unconfigured"})
    except google_auth.GoogleAuthError as ex:
        # Log the FULL reason server-side (carries Google's error from
        # _exchange_code_for_tokens); the client gets ONLY the opaque code.
        import logging
        logging.getLogger("uvicorn.error").warning(
            "google_callback failed: %s (code=%s)", ex, ex.code)
        raise HTTPException(status_code=ex.status,
                            detail={"error": ex.code})
    return RedirectResponse(url=return_url, status_code=302)


@app.post("/v1/auth/logout")
async def logout(req: Request,
                 authorization: str | None = Header(None)) -> dict:
    """Revoke the caller's bearer token. Promised to users on
    web/.../security.astro; this is the real endpoint behind it.

    Contract (desktop client / browser):
      POST /v1/auth/logout
      Authorization: Bearer <token>
      body (optional): {"all_sessions": false}
      → 200 {"ok": true, "revoked": <n>}
    After this, reusing <token> on any authed endpoint returns 401.

    `all_sessions: true` revokes every token the user holds (sign out
    of all devices). The body is optional — an empty POST defaults to
    single-token revocation.
    """
    token = _bearer(authorization)
    all_sessions = False
    if await _has_body(req):
        try:
            body = await req.json()
        except Exception:
            body = {}
        if isinstance(body, dict):
            all_sessions = bool(body.get("all_sessions", False))
    return auth.logout(token=token, all_sessions=all_sessions)


class DeviceHeartbeatReq(BaseModel):
    device_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    name: str = Field(default="", max_length=120)


@app.post("/v1/devices/heartbeat")
def device_heartbeat(body: DeviceHeartbeatReq,
                     authorization: str | None = Header(None)) -> dict:
    """A signed-in device says it is alive (the founder cockpit lists it; a
    disconnect there revokes the session it spoke with)."""
    user = _require_user(authorization)
    return {"ok": True, **db.device_heartbeat(user["id"], body.device_id, body.name.strip(),
                                              _bearer(authorization))}


@app.get("/v1/me")
def me(authorization: str | None = Header(None)) -> dict:
    user = _require_user(authorization)
    remaining = max(0, int(user["msg_limit"]) - int(user["msg_used"]))
    return {
        # user_id (= users.id) lets the desktop bind its LOCAL brain to this
        # cloud account — the per-user replica dir is keyed on this id, so
        # the client uses it for /v1/brain/sync + to confirm which brain it
        # is syncing into. brain_id is the explicit account→brain link
        # (== user_id), surfaced so the client can assert the slot exists.
        "user_id": user["id"],
        "brain_id": user.get("brain_id") or user["id"],
        "email": user["email"],
        "plan": user["plan"],
        "remaining_messages": remaining,
        "period_end": user.get("period_end"),
        "can_upgrade": user["plan"] != "firm",
        # Whether this account owns the founder cockpit, so the desktop offers
        # "Open the cockpit" only to that account (same list the gate uses).
        "founder": (user.get("email") or "").strip().lower() in config.founder_emails(),
    }


@app.get("/v1/models")
def models(authorization: str | None = Header(None)) -> dict:
    """OpenAI-compatible model list. Advertises the FREE DEFAULT model to
    no-key / non-hosted workspaces so the client has a usable default
    without any configuration (founder 2026-06-22 — zero-config free)."""
    user = _require_user(authorization)
    return proxy.list_models(user=user)


@app.post("/v1/chat/completions")
async def chat(req: Request,
                authorization: str | None = Header(None)):
    user = _require_user(authorization)
    body = await req.json()
    return await proxy.chat_completions(user=user, body=body)


@app.post("/v1/memory/capture")
async def memory_capture(req: Request,
                         authorization: str | None = Header(None)) -> dict:
    """Desktop client posts one user-approved chat turn for training.

    Body: {role, content, tool_trace?, intent?}. The server stamps it
    `captured` and queues it for the redact/judge workers (worker
    daemon in agents/ does the actual stage advance).
    """
    user = _require_user(authorization)
    body = await req.json()
    role = (body.get("role") or "").strip().lower()
    if role not in ("user", "assistant", "tool"):
        raise HTTPException(status_code=400,
                             detail={"error": "role must be user|assistant|tool"})
    content = (body.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=400,
                             detail={"error": "content required"})
    tool_trace = body.get("tool_trace") or []
    if not isinstance(tool_trace, list):
        raise HTTPException(status_code=400,
                             detail={"error": "tool_trace must be a list"})
    sid = db.insert_training_sample(
        user_id=user["id"],
        role=role,
        content=content,
        tool_trace=tool_trace,
        intent=(body.get("intent") or "").strip(),
        company_id=user.get("current_company_id") or None,
    )
    return {"id": sid, "stage": "captured"}


@app.get("/v1/memory/stats")
def memory_stats(authorization: str | None = Header(None)) -> dict:
    """Counters for the 4-stage pipeline. Scoped to the caller."""
    user = _require_user(authorization)
    return db.memory_stats(user_id=user["id"])


# ── Semantic facts (ADR-002) ─────────────────────────────────────────
import memory_writer
import memory_extractor


@app.post("/v1/memory/facts")
async def memory_facts_create(req: Request,
                               authorization: str | None = Header(None)) -> dict:
    """Manual fact insertion. `/remember <fact>` from the desktop maps
    here; the chat composer can also call this directly."""
    user = _require_user(authorization)
    body = await req.json()
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400,
                             detail={"error": "text required"})
    scope = body.get("scope") or "user"
    if scope not in db.VALID_SCOPES:
        raise HTTPException(status_code=400,
                             detail={"error": f"scope must be one of {db.VALID_SCOPES}"})
    visibility = body.get("visibility") or "private"
    if visibility not in db.VALID_VISIBILITY:
        raise HTTPException(status_code=400,
                             detail={"error": f"visibility must be one of {db.VALID_VISIBILITY}"})
    res = memory_writer.apply_ops(
        user_id=user["id"],
        ops=[{"op": "ADD", "text": text, "scope": scope,
              "confidence": float(body.get("confidence") or 0.7),
              "subject": body.get("subject", ""),
              "predicate": body.get("predicate", ""),
              "object": body.get("object", ""),
              "project_id": body.get("project_id"),
              "company_id": user.get("current_company_id"),
              "rationale": body.get("rationale", "manual add")}],
    )
    if res["errors"] or not res["added"]:
        raise HTTPException(status_code=400,
                             detail={"error": "write failed",
                                     "details": res["errors"]})
    fid = res["added"][0]
    return {"id": fid, "stage": "added"}


@app.get("/v1/memory/facts")
def memory_facts_list(q: str | None = None,
                       scope: str | None = None,
                       limit: int = 50,
                       authorization: str | None = Header(None)) -> dict:
    """Search (q=) or list (q omitted). Always scoped to caller; shared
    facts are included when the caller asks."""
    user = _require_user(authorization)
    limit = max(1, min(int(limit), 200))
    if q:
        rows = db.search_memory_facts(
            user_id=user["id"], query=q,
            include_shared=True, limit=limit,
        )
        # Audit reads of shared facts (private ones don't trigger).
        for r in rows:
            if r.get("visibility") in ("shared_company", "shared_public"):
                db.log_memory_access(
                    reader_user_id=user["id"], fact_id=int(r["id"]),
                    purpose="search",
                )
        return {"results": rows, "query": q, "limit": limit}
    rows = db.list_memory_facts(
        user_id=user["id"], scope=scope, limit=limit,
    )
    return {"results": rows, "scope": scope, "limit": limit}


@app.put("/v1/memory/facts/{fact_id}")
async def memory_facts_update(fact_id: int, req: Request,
                               authorization: str | None = Header(None)) -> dict:
    user = _require_user(authorization)
    existing = db.get_memory_fact(fact_id)
    if not existing or existing["user_id"] != user["id"]:
        raise HTTPException(status_code=404,
                             detail={"error": "fact not found"})
    body = await req.json()
    res = memory_writer.apply_ops(
        user_id=user["id"],
        ops=[{"op": "UPDATE", "fact_id": fact_id,
              "text": (body.get("text") or existing["text"]),
              "confidence": body.get("confidence"),
              "rationale": body.get("rationale", "manual update")}],
    )
    if res["errors"]:
        raise HTTPException(status_code=400,
                             detail={"error": "update failed",
                                     "details": res["errors"]})
    return {"id": fact_id, "stage": "updated"}


@app.delete("/v1/memory/facts/{fact_id}")
def memory_facts_delete(fact_id: int,
                         authorization: str | None = Header(None)) -> dict:
    """Soft-delete (sets valid_until=now). The row remains for audit."""
    user = _require_user(authorization)
    existing = db.get_memory_fact(fact_id)
    if not existing or existing["user_id"] != user["id"]:
        raise HTTPException(status_code=404,
                             detail={"error": "fact not found"})
    res = memory_writer.apply_ops(
        user_id=user["id"],
        ops=[{"op": "DELETE", "fact_id": fact_id,
              "rationale": "manual forget"}],
    )
    if res["errors"]:
        raise HTTPException(status_code=400,
                             detail={"error": "delete failed",
                                     "details": res["errors"]})
    return {"id": fact_id, "stage": "deleted"}


_SHARE_PATH_RETIRED = {
    "error": "retired",
    "use": "Share a fact from the ArchHub app (Settings > Brain > share, POST "
           "/api/universal/brain-publish); the founder reviews it before members see it.",
}


@app.post("/v1/memory/facts/{fact_id}/promote")
async def memory_facts_promote(fact_id: int, req: Request,
                                 authorization: str | None = Header(None)) -> dict:
    """Retired (2026-09-29): this copied a fact into the collective table, which
    every signed-in user could read with no review. Sharing is the owner's
    publish in the app, and the founder reviews it (ADGR-0004)."""
    _require_user(authorization)
    raise HTTPException(status_code=410, detail=_SHARE_PATH_RETIRED)


@app.get("/v1/memory/collective")
def memory_collective_list(domain: str | None = None,
                             limit: int = 50,
                             authorization: str | None = Header(None)) -> dict:
    """Retired with /promote: community facts reach members only through the
    reviewed Community Brain (/v1/brain/sync, community_review)."""
    _require_user(authorization)
    raise HTTPException(status_code=410, detail=_SHARE_PATH_RETIRED)


@app.post("/v1/memory/extract")
async def memory_extract(req: Request,
                          authorization: str | None = Header(None)) -> dict:
    """Run the heuristic extractor on a chunk of chat text and apply
    the resulting ops. Returns the writer summary."""
    user = _require_user(authorization)
    body = await req.json()
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400,
                             detail={"error": "text required"})
    source_sample_id = body.get("source_sample_id")
    ops = memory_extractor.extract_ops(
        user_id=user["id"], text=text,
    )
    res = memory_writer.apply_ops(
        user_id=user["id"], ops=ops,
        source_sample_id=int(source_sample_id) if source_sample_id else None,
    )
    return {"ops_proposed": ops, "result": res}


@app.get("/v1/memory/ops")
def memory_ops_list(limit: int = 50,
                     authorization: str | None = Header(None)) -> dict:
    """Audit log for the calling user. Mem0-style op trace."""
    user = _require_user(authorization)
    rows = db.list_memory_ops(
        user_id=user["id"],
        limit=max(1, min(int(limit), 500)),
    )
    return {"results": rows}


# ── Brain replica sync (Track D · section 5 of CONTENT-ECOSYSTEM-2026-05-26) ──
# Per-user server-side brain.db mirror. Desktop client pushes deltas; the
# cloud merges via BrainReplica + returns the merged view + a new HLC. The
# privacy contract (BRAIN-FIRST · founder 2026-05-25): ZERO resolved secrets
# in the replica — bare credential-like strings are rejected at the boundary
# (brain_replica._fragment_has_secret), while `op://`, `wcm://`, `env://`,
# `inline:` REFERENCES pass through. Resolution stays on the user's machine.
import brain_replica


def _firm_keys_for_user(user: dict) -> list[str]:
    """The shared FIRM-replica keys this user may read (Slice-17 fanout).

    A firm == a cloud `company` the user is a member of. We key the shared
    firm replica on the company id, so every member of a company converges
    their FIRM-scope brain through the SAME shared replica. Resolved
    server-side from `company_members` — NEVER trusted from the wire — so a
    user can only ever read firm replicas they actually belong to. Solo users
    (no company) get an empty list and keep a pure per-user backup.
    """
    try:
        companies = db.list_companies_for_user(user["id"])
    except Exception:
        return []
    return [str(c["id"]) for c in companies if c.get("id")]


def _community_keys_for_user(user: dict) -> list[str]:
    """Community replica keys this user may read and write: the memberships
    the cloud recorded from verified join-codes. Never the wire."""
    return db.list_community_keys_for_user(user["id"])


@app.post("/v1/community/leave")
async def community_leave(req: Request, authorization: str | None = Header(None)) -> dict:
    """Leave a community: its shared replica is no longer read or written."""
    user = _require_user(authorization)
    body = await req.json() if await _has_body(req) else {}
    cid = str((body or {}).get("community_id") or "").strip()
    if not cid:
        raise HTTPException(status_code=400, detail={"error": "community_id is required"})
    left = db.remove_community_member(cid, user["id"])
    db.record_community_optout(cid, user["id"])
    return {"ok": True, "left": left}


@app.post("/v1/community/join")
async def community_join(req: Request,
                         authorization: str | None = Header(None)) -> dict:
    """Present a community join-code; the cloud verifies it against the owner
    key inside it and records the membership that gates the shared replica."""
    user = _require_user(authorization)
    body = await req.json() if await _has_body(req) else {}
    from community_join import verify_join_code
    payload, reason = verify_join_code(str((body or {}).get("envelope") or ""))
    if payload is None:
        raise HTTPException(status_code=400, detail={"error": reason})
    db.add_community_member(str(payload["community_id"]), user["id"],
                            role=str(payload.get("role") or "member"),
                            owner_pub=str(payload["owner_pub"]))
    # A verified join-code is the member's own act: it lifts an earlier opt-out.
    db.clear_community_optout(str(payload["community_id"]), user["id"])
    return {"joined": True, "community_id": str(payload["community_id"]),
            "community_keys": _community_keys_for_user(user)}


@app.post("/v1/brain/sync")
async def brain_sync(req: Request,
                      authorization: str | None = Header(None)) -> dict:
    """Push a delta from desktop brain → cloud replica, with Slice-17 scope
    fanout, and return the caller's MERGED delta + the cloud's new HLC.

    Body: {since_hlc?: str, delta: {fragments: [...], wiring: [...]}}

    Fanout (reuses the per-replica HLC/CRDT merge, no parallel sync):
      * USER/PROJECT fragments land in the caller's private per-user replica.
      * FIRM fragments converge through a SHARED replica keyed by the
        company id — every member of the company sees them.
      * COMMUNITY fragments converge through a SHARED replica keyed by the
        fragment's community_id (the cloud_relay community transport).
    The merged read unions the user's own replica with every firm replica
    they belong to + every community replica they just pushed into / are a
    member of — so device B pulls device A's firm/community facts, while
    USER scope stays private per user (per-user-isolation contract intact).
    """
    user = _require_user(authorization)
    body = await req.json() if await _has_body(req) else {}
    if not isinstance(body, dict):
        raise HTTPException(status_code=400,
                             detail={"error": "body must be a JSON object"})
    delta = body.get("delta") or {}
    if not isinstance(delta, dict):
        raise HTTPException(status_code=400,
                             detail={"error": "delta must be an object"})
    since_hlc = (body.get("since_hlc") or "").strip()

    # The contributing teammate is the AUTHENTICATED caller — the cloud knows
    # who is pushing, so it stamps owner_user authoritatively on every shared
    # (firm/community) fragment rather than trusting a wire-supplied owner.
    # This makes a firm fact attributable to the real member who added it,
    # and means a missing/forged owner_user can't masquerade as someone else.
    for _f in (delta.get("fragments") or []):
        if isinstance(_f, dict) and (_f.get("scope") or "").lower() in (
                "firm", "community"):
            _f["owner_user"] = user["id"]

    # Firm read-set: every company the user belongs to (server-resolved).
    firm_keys = _firm_keys_for_user(user)
    # Community read-set: the caller may name the communities it belongs to
    # (these are brain-side groups the cloud has no membership table for —
    # the join-code already authorised the device). We additionally union
    # whatever community keys this very delta contributed to (below), so a
    # first-ever push immediately round-trips. Keys are sanitised in the
    # replica layer; an unsafe one is skipped, never fatal.
    # A key the CALLER names is a claim, not a membership. The cloud has
    # no community membership table, so the only honest evidence it holds
    # is what this user has actually contributed to before -- naming a
    # community you never wrote to used to read every fact in it, which
    # made any guessed id a key.
    # Community read/write set: memberships the cloud recorded from a
    # verified join-code (POST /v1/community/join). Nothing named on the
    # wire, nothing earned by having written before.
    community_keys = _community_keys_for_user(user)

    try:
        replica = brain_replica.BrainReplica.open(
            user_id=user["id"],
            firm_keys=firm_keys,
            community_keys=community_keys,
        )
        merge_result = replica.apply_delta(delta)
        # Build the FULL read-set for the merged export, unioning:
        #  (a) company-membership firm keys (resolved server-side above),
        #  (b) firm/community keys this user has EVER contributed to (durable,
        #      so a later empty pull still round-trips device A's facts),
        #  (c) keys this very delta just touched, and
        #  (d) community keys the caller declared membership of this call.
        # (b) and (c) are history, not membership: re-check them against
        # (a) on every read, so a user removed from a company stops reading
        # that firm's shared replica once the company_members row is gone.
        replica.firm_keys = sorted(
            set(replica.firm_keys)
            | ((set(replica.contributed_firm_keys())
                | set(merge_result.get("firm_keys") or []))
               & set(firm_keys)))
        # Community read-set stays the membership list; contributions can
        # only have landed in member communities now.
        replica.community_keys = sorted(set(replica.community_keys))
        merged = replica.export_delta(since_hlc=since_hlc)
    except ValueError as ex:
        raise HTTPException(status_code=400, detail={"error": str(ex)})
    import community_review
    community_review.submit_versions(user["id"], delta, merge_result, community_keys)
    merged = community_review.hold_unreviewed(user["id"], merged)
    return {
        "accepted": merge_result["accepted"],
        "rejected": merge_result["rejected"],
        "new_hlc": merge_result["new_hlc"],
        "merged": merged,
        # Surfaced so the desktop can show which shared scopes converged.
        "firm_keys": replica.firm_keys,
        "community_keys": replica.community_keys,
    }


@app.delete("/v1/brain/sync")
def brain_sync_delete(authorization: str | None = Header(None)) -> dict:
    """GDPR right-to-erasure: drop this user's entire cloud replica.

    Caller is expected to also revoke their bearer tokens (handled at the
    Settings → Account level on the desktop). This endpoint only owns the
    replica filesystem."""
    user = _require_user(authorization)
    removed = brain_replica.BrainReplica.delete(user_id=user["id"])
    return {"deleted": bool(removed), "user_id": user["id"]}


# ---------------------------------------------------------------------------
# Brain READ + SEARCH (the genuine gap — /v1/brain/sync was write-only).
#
# These EXTEND the existing /v1/brain/* surface (same prefix, same
# brain_replica module) with owner-only, tier-gated reads of the caller's
# real per-user cloud replica — the SAME `replicas/<user_id>/brain.db` that
# /v1/brain/sync writes. No parallel store, no parallel API:
#   * Resolve the user from the bearer token (the existing `_require_user`).
#   * Open THAT user's replica (BrainReplica.open forces owner == caller, so
#     one user can never read another's USER-scope facts).
#   * studio/firm additionally union their firm/community shared replicas
#     (the Slice-17 read-set already wired into export_delta), gated by plan.
#   * Tier caps + search gating come from config (BRAIN_FACT_CAPS /
#     BRAIN_SEARCH_PLANS) — real enforcement, returning a typed 402 on the
#     trial search ceiling rather than a cosmetic block.
# ---------------------------------------------------------------------------
def _brain_read_replica(user: dict):
    """Open the caller's per-user replica with the tier-correct read-set.

    USER/PROJECT facts always come from the caller's own private replica.
    studio/firm (BRAIN_SHARED_SCOPE_PLANS) additionally union the firm
    shared replicas they belong to + any firm/community keys they have
    contributed to — exactly the export_delta fanout, never widened past
    the account's real memberships."""
    firm_keys: list[str] = []
    community_keys: list[str] = []
    if config.brain_can_shared_scope(user.get("plan")):
        firm_keys = _firm_keys_for_user(user)
    replica = brain_replica.BrainReplica.open(
        user_id=user["id"],
        firm_keys=firm_keys,
        community_keys=community_keys,
    )
    if config.brain_can_shared_scope(user.get("plan")):
        # Durable contributed keys (communities joined by code have no cloud
        # membership table) so a later read still unions device A's shares.
        # A contributed FIRM key is read only while company membership
        # (firm_keys above) still lists it: removal ends the read too.
        replica.firm_keys = sorted(
            set(replica.firm_keys)
            | (set(replica.contributed_firm_keys()) & set(firm_keys)))
        replica.community_keys = sorted(
            set(replica.community_keys)
            | set(replica.contributed_community_keys()))
    return replica


def _fact_view(frag: dict) -> dict:
    """Project a replica fragment to the portal's read shape (no internals
    like rowid; provenance/extra already decoded by list_fragments)."""
    return {
        "id":         frag.get("id"),
        "text":       frag.get("text") or "",
        "subject":    frag.get("subject"),
        "predicate":  frag.get("predicate"),
        "object":     frag.get("object"),
        "scope":      frag.get("scope") or "user",
        "visibility": frag.get("visibility") or "private",
        "confidence": frag.get("confidence") or "extracted",
        "project_id": frag.get("project_id"),
        "firm_id":    frag.get("firm_id"),
        "updated_at": frag.get("updated_at"),
        "created_at": frag.get("created_at"),
    }


@app.get("/v1/brain/facts")
def brain_facts(scope: str | None = None,
                limit: int = 200,
                authorization: str | None = Header(None)) -> dict:
    """List the caller's synced brain facts (kind='fact'), newest first.

    Owner-only: reads ONLY this user's replica (+ their firm/community shared
    replicas on studio/firm). `limit` is clamped to the per-tier cap from
    config.BRAIN_FACT_CAPS — a trial sees at most 100, paid tiers more. An
    optional `scope` filters to user/project/firm/community. Honest empty
    state: a user who has never synced gets `{results: [], count: 0}`.
    """
    user = _require_user(authorization)
    plan = user.get("plan")
    cap = config.brain_fact_cap(plan)
    want = max(1, min(int(limit), cap))
    replica = _brain_read_replica(user)
    # Fetch up to the cap (export_delta-style union for shared scopes; for the
    # USER-only tiers list_fragments reads the private replica directly).
    if config.brain_can_shared_scope(plan):
        import community_review
        merged = community_review.hold_unreviewed(user["id"], replica.export_delta(since_hlc=""))
        rows = [f for f in merged.get("fragments", [])
                if (f.get("kind") or "fact") == "fact"
                and not f.get("valid_until")]
        # export_delta returns hlc-asc; portal wants newest-updated first.
        rows.sort(key=lambda d: (d.get("updated_at") or ""), reverse=True)
    else:
        # Fetch one past the cap so we can honestly report whether facts were
        # withheld (the `capped` flag) without an extra COUNT query.
        rows = replica.list_fragments(kind="fact", limit=cap + 1)
    if scope:
        rows = [f for f in rows if (f.get("scope") or "user") == scope]
    total_available = len(rows)
    rows = rows[:want]
    return {
        "results": [_fact_view(f) for f in rows],
        "count":   len(rows),
        "plan":    plan,
        "cap":     cap,
        "scope":   scope,
        # True only when facts were actually withheld by the tier cap — an
        # empty/under-cap result is NOT "capped" (honest empty state).
        "capped":  total_available > len(rows),
    }


@app.get("/v1/brain/search")
def brain_search(q: str = "",
                 limit: int = 50,
                 authorization: str | None = Header(None)) -> dict:
    """Case-insensitive scored search over the caller's brain facts.

    Tier-gated (config.BRAIN_SEARCH_PLANS): trial is denied with a typed 402
    `upgrade_required` (a REAL limit, surfaced as an upgrade CTA), paid tiers
    search their full working set. Owner-only, same replica read-set as
    /v1/brain/facts. Scores text > subject/object substring hits.
    """
    user = _require_user(authorization)
    plan = user.get("plan")
    if not config.brain_can_search(plan):
        raise HTTPException(
            status_code=402,
            detail={
                "error": "upgrade_required",
                "feature": "brain_search",
                "plan": plan,
                "message": "Brain search is available on paid plans. "
                           "Upgrade to search your synced knowledge.",
            },
        )
    cap = config.brain_fact_cap(plan)
    want = max(1, min(int(limit), cap))
    needle = (q or "").strip().lower()
    replica = _brain_read_replica(user)
    if config.brain_can_shared_scope(plan):
        import community_review
        merged = community_review.hold_unreviewed(user["id"], replica.export_delta(since_hlc=""))
        pool = [f for f in merged.get("fragments", [])
                if (f.get("kind") or "fact") == "fact"
                and not f.get("valid_until")]
    else:
        pool = replica.list_fragments(kind="fact", limit=cap)
    if not needle:
        results = pool
    else:
        scored: list[tuple[int, dict]] = []
        for f in pool:
            text = (f.get("text") or "").lower()
            subj = (f.get("subject") or "").lower()
            obj = (f.get("object") or "").lower()
            pred = (f.get("predicate") or "").lower()
            score = 0
            if needle in text:
                score += 3
            if needle in subj or needle in obj:
                score += 2
            if needle in pred:
                score += 1
            if score:
                scored.append((score, f))
        scored.sort(key=lambda t: (t[0], t[1].get("updated_at") or ""),
                    reverse=True)
        results = [f for _, f in scored]
    results = results[:want]
    return {
        "results": [_fact_view(f) for f in results],
        "count":   len(results),
        "query":   q,
        "plan":    plan,
        "cap":     cap,
    }


@app.get("/v1/brain/stats")
def brain_stats(authorization: str | None = Header(None)) -> dict:
    """Portal header counters for the caller's brain: total facts, a
    per-scope breakdown, the last-sync HLC watermark, and the tier
    capabilities the UI uses to render caps + the upgrade CTA.

    Owner-only; honest zeros for a user who has never synced."""
    user = _require_user(authorization)
    plan = user.get("plan")
    replica = _brain_read_replica(user)
    if config.brain_can_shared_scope(plan):
        import community_review
        merged = community_review.hold_unreviewed(user["id"], replica.export_delta(since_hlc=""))
        facts = [f for f in merged.get("fragments", [])
                 if (f.get("kind") or "fact") == "fact"
                 and not f.get("valid_until")]
    else:
        facts = replica.list_fragments(
            kind="fact", limit=config.BRAIN_FACT_CAP_MAX)
    by_scope: dict[str, int] = {}
    for f in facts:
        s = (f.get("scope") or "user")
        by_scope[s] = by_scope.get(s, 0) + 1
    last_hlc = replica.last_hlc()
    zero_hlc = "0000000000000000.00000000"
    return {
        "total_facts":   len(facts),
        "by_scope":      by_scope,
        "last_sync_hlc": last_hlc,
        "ever_synced":   last_hlc != zero_hlc,
        "plan":          plan,
        "caps": {
            "fact_cap":     config.brain_fact_cap(plan),
            "can_search":   config.brain_can_search(plan),
            "shared_scope": config.brain_can_shared_scope(plan),
            "can_export":   config.brain_can_export(plan),
        },
        "can_upgrade":   plan != "firm",
    }


async def _has_body(req: Request) -> bool:
    """FastAPI lets you call .json() on an empty body; we want to
    distinguish that from a JSON object. Returns False when the
    Content-Length is 0 or absent."""
    cl = req.headers.get("content-length") or "0"
    try:
        return int(cl) > 0
    except Exception:
        return False


@app.get("/v1/offer")
def offer() -> dict:
    """The offer the application published, relayed verbatim.

    The cloud authors no offer of its own - no label, no availability text -
    it forwards the record from the map push and nothing else. With no push,
    no offer block, or a malformed one, the answer is CLOSED and pricing
    stays hidden, so a quiet backend can never announce an offer the product
    does not hold.
    """
    published = config.published_offer()
    return {
        "state":           "open" if published else "closed",
        "availability":    published.get("availability"),
        "public_label":    published.get("public_label"),
        "pricing_visible": config.pricing_is_public(),
        "revision":        published.get("revision"),
        "sha256":          published.get("sha256"),
        "published_at":    config.map_pushed_at(),
        "source":          "founder-map",
    }


@app.get("/v1/billing/plans")
def billing_plans() -> dict:
    """Public plan catalog (Model C) — used by the desktop app to render
    the pricing dialog without hardcoding tier metadata client-side.

    Surfaces the canonical config.public_pricing() snapshot (per-seat
    prices, annual −20% equivalents, min/max seats, the BYO/Hosted AI
    modes, the $10/1,000-msg credit pack) PLUS, per tier, whether the
    active billing provider has a configured price/product id (so the UI
    can show "Coming soon" until the founder wires the real ids).
    """
    pricing = config.public_pricing()
    if not config.pricing_is_public():
        # The published offer withholds pricing, so the catalogue is served
        # EMPTY rather than guessed, and checkout is refused by the same
        # gate. No price reaches the client while the offer is closed.
        return {
            "provider":        config.BILLING_PROVIDER,
            "model":           pricing["model"],
            "currency":        pricing["currency"],
            "annual_discount": pricing["annual_discount"],
            "ai_modes":        pricing["ai_modes"],
            "default_ai_mode": pricing["default_ai_mode"],
            "credit_pack":     None,
            "tiers":           [],
            "trial_messages":  config.TRIAL_MESSAGES,
            "pricing_visible": False,
        }
    tiers = []
    for t in pricing["tiers"]:
        tier_name = t["id"]
        if config.BILLING_PROVIDER == "polar":
            external_id = config.POLAR_PRODUCT_IDS.get(tier_name) or None
        else:
            external_id = config.stripe_price_id(tier_name) or None
        tiers.append({
            "tier":                  tier_name,
            "name":                  t["name"],
            "price_per_seat":        t["price_per_seat"],
            "price_per_seat_annual": t["price_per_seat_annual"],
            "min_seats":             t["min_seats"],
            "max_seats":             t["max_seats"],
            "is_company":            t["is_company"],
            "sso":                   t["sso"],
            "blurb":                 t["blurb"],
            # external_id is null when the price/product hasn't been
            # configured yet — the desktop UI shows "Coming soon".
            "external_id_configured": external_id is not None,
        })
    return {
        "provider":        config.BILLING_PROVIDER,
        "model":           pricing["model"],
        "currency":        pricing["currency"],
        "annual_discount": pricing["annual_discount"],
        "ai_modes":        pricing["ai_modes"],
        "default_ai_mode": pricing["default_ai_mode"],
        "credit_pack":     pricing["credit_pack"],
        "tiers":           tiers,
        "trial_messages":  config.TRIAL_MESSAGES,
        "pricing_visible": True,
    }


def _billing_provider_module():
    """Return the module that backs the current BILLING_PROVIDER.

    Defaults to Stripe. Set BILLING_PROVIDER=polar to swap to Polar.sh
    (Merchant of Record, ~10 min signup vs Stripe's KYC).
    """
    if config.BILLING_PROVIDER == "polar":
        import polar  # local import — avoids importing httpx on Stripe path
        return polar
    return billing  # default = Stripe


@app.post("/v1/billing/checkout")
def checkout(req: CheckoutReq,
              authorization: str | None = Header(None)) -> dict:
    user = _require_user(authorization)
    # Validate tier against whichever provider is configured. Both
    # provider dicts share the same tier keys.
    valid_tiers = (
        config.POLAR_PRODUCT_IDS
        if config.BILLING_PROVIDER == "polar"
        else config.PLAN_PRICE_IDS
    )
    if req.tier not in valid_tiers:
        raise HTTPException(status_code=400, detail="unknown_tier")
    if not config.pricing_is_public():
        # Same gate as /v1/billing/plans: while the published offer withholds
        # pricing there is nothing to sell, so no session is opened. A
        # malformed request is still answered as malformed first.
        raise HTTPException(status_code=403, detail="checkout_closed")
    url = _billing_provider_module().create_checkout_url(
        user=user, tier=req.tier, annual=req.annual,
    )
    if not url:
        raise HTTPException(status_code=503,
                             detail="checkout_unavailable")
    return {"url": url}


@app.get("/v1/billing/ai")
def billing_ai_status(authorization: str | None = Header(None)) -> dict:
    """Solo/per-user AI status (Model C): current mode + live hosted
    credit balance + the credit-pack terms. (Company workspaces use
    /v1/companies/{id}/ai.)"""
    user = _require_user(authorization)
    fresh = db.get_user(user["id"]) or user
    return {
        "ai_mode": db._ai_mode_norm(fresh.get("ai_mode")),
        "credit_balance": db.credit_balance(user_id=user["id"]),
        "credit_pack": dict(config.CREDIT_PACK),
        "ai_modes": list(config.AI_MODES),
    }


@app.post("/v1/billing/ai-mode")
def billing_set_ai_mode(req: AiModeReq,
                        authorization: str | None = Header(None)) -> dict:
    """Flip a solo/per-user workspace between byo_key and hosted AI."""
    user = _require_user(authorization)
    mode = db.set_user_ai_mode(user["id"], req.ai_mode)
    return {"ok": True, "ai_mode": mode}


@app.post("/v1/billing/credits/checkout")
def billing_buy_credits(authorization: str | None = Header(None)) -> dict:
    """One-time Stripe Checkout for a hosted-AI credit pack ($10 =
    1,000 messages), credited to the solo user's workspace on payment
    (60-day rollover)."""
    user = _require_user(authorization)
    url = billing.create_credit_pack_checkout(
        user_id=user["id"], billing_email=user.get("email"),
    )
    if not url:
        raise HTTPException(status_code=503,
                             detail="checkout_unavailable")
    return {"url": url, "credit_pack": dict(config.CREDIT_PACK)}


@app.get("/v1/billing/portal")
def portal(authorization: str | None = Header(None)) -> dict:
    user = _require_user(authorization)
    url = _billing_provider_module().create_portal_url(user=user)
    if not url:
        raise HTTPException(status_code=400,
                             detail="no_subscription")
    return {"url": url}


@app.post("/v1/webhooks/polar")
async def polar_webhook(req: Request) -> dict:
    """Polar.sh webhook receiver. Always present in main.py — selection
    happens at handler call time so a single deploy can serve either
    provider depending on BILLING_PROVIDER env."""
    import polar as polar_mod
    payload = await req.body()
    sig = req.headers.get("polar-webhook-signature", "")
    result = polar_mod.handle_webhook(payload=payload, signature=sig)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "bad"))
    return result


@app.post("/v1/webhooks/stripe")
async def stripe_webhook(req: Request) -> dict:
    payload = await req.body()
    sig = req.headers.get("stripe-signature", "")
    result = billing.handle_webhook(payload=payload, signature=sig)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result)
    return result


# ---------------------------------------------------------------------------
# Browser-facing convenience routes
# ---------------------------------------------------------------------------

# One sign-in button for every cloud page (/signin, /invite, /dashboard,
# /brain). It asks /v1/auth/google/start for the consent URL; after Google
# the plain /auth/return finisher stores the session and sends the browser
# back to the page that started (archhub_after_signin, same-origin paths
# only). A desktop that opened /signin with its PKCE challenge + loopback
# gets them threaded through, so it finishes on its own loopback.
_GOOGLE_SIGNIN_JS = """
function sessionToken() {
  try { return localStorage.getItem('archhub_session_token') || ''; }
  catch (e) { return ''; }
}
function forgetSession() {
  try { localStorage.removeItem('archhub_session_token'); } catch (e) {}
}
async function continueWithGoogle(desktop) {
  const out = document.getElementById('out');
  const btn = document.getElementById('google');
  if (btn) { btn.disabled = true; btn.textContent = 'Opening Google...'; }
  const q = new URLSearchParams();
  if (desktop && desktop.challenge) q.set('code_challenge', desktop.challenge);
  if (desktop && desktop.redirect) q.set('redirect', desktop.redirect);
  if (desktop && desktop.state) q.set('state', desktop.state);
  if (!(desktop && desktop.redirect)) {
    try { localStorage.setItem('archhub_after_signin',
            location.pathname + location.search); } catch (e) {}
  }
  try {
    const r = await fetch('/v1/auth/google/start?' + q.toString());
    const d = await r.json().catch(() => ({}));
    if (r.ok && d.auth_url) { location.href = d.auth_url; return false; }
    out.innerHTML = '<div class="err">Google sign-in is unavailable right '
      + 'now. Try again in a minute.</div>';
  } catch (e) {
    out.innerHTML = '<div class="err">Network error: ' + e + '</div>';
  }
  if (btn) { btn.disabled = false; btn.textContent = 'Continue with Google'; }
  return false;
}
"""

@app.get("/signin", response_class=HTMLResponse)
def signin_landing(challenge: str = "", redirect: str = "",
                    state: str = "", client: str = "") -> HTMLResponse:
    """The cloud's sign-in page: one "Continue with Google" button.

    A desktop that deep-links here with ?challenge=...&redirect=<loopback>
    &state=... has them threaded into /v1/auth/google/start, so the code
    comes back to its own loopback (older desktop installs opened this page
    for email sign-in; they now finish through Google). A plain browser
    visit signs in on this domain via /auth/return."""
    import json as _json
    desktop = _json.dumps({"challenge": challenge[:200],
                           "redirect": redirect[:500],
                           "state": state[:200]}).replace("<", "\\u003c")
    html = """<!doctype html><html><head><title>Sign in - ArchHub</title>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<style>
  :root { --bg:#0f0f12; --raised:#1d1d22; --ink:#ece8e0;
          --soft:#9b938a; --line:#26262d; --accent:#d97757; }
  body { margin:0; padding:60px 24px; background:var(--bg);
         color:var(--ink); font-family:system-ui,-apple-system,
         'Segoe UI',sans-serif; }
  .card { max-width:480px; margin:0 auto; padding:36px;
          background:var(--raised); border:1px solid var(--line);
          border-radius:14px; }
  h1 { margin:0 0 8px; font-family:Georgia,serif; font-style:italic;
       font-size:30px; letter-spacing:-0.02em; }
  p { color:var(--soft); line-height:1.55; font-size:14px; }
  button { width:100%; padding:14px; margin-top:14px;
           background:var(--accent); color:white; border:none;
           border-radius:10px; font-size:15px; font-weight:500;
           cursor:pointer; }
  button:hover { background:#a04832; }
  button:disabled { opacity:0.5; cursor:default; }
  .err { margin-top:18px; padding:14px; background:rgba(229,178,90,0.1);
         border:1px solid #e5b25a; border-radius:10px; color:#e5b25a; }
</style></head><body>
<div class='card'>
  <h1>Sign in to ArchHub Cloud</h1>
  <p>Sign in with the Google account for your email. Your ArchHub
     account is that email address.</p>
  <button type='button' id='google'
          onclick='return continueWithGoogle(DESKTOP)'>Continue with Google</button>
  <div id='out'></div>
</div>
<script>
const DESKTOP = __DESKTOP__;
""" + _GOOGLE_SIGNIN_JS + """
</script></body></html>"""
    return HTMLResponse(content=html.replace("__DESKTOP__", desktop))


@app.get("/auth/return", response_model=None)
def auth_return(code: str = "", redirect: str = "",
                state: str = "") -> HTMLResponse | RedirectResponse:
    """Lands here from the Google callback. The one-time `code` is
    forwarded to wherever sign-in began:

      * A WEBSITE origin (archhub.io / archhub-web.fly.dev) — 302 to
        {origin}/signin?code=... so auth.js on the website finishes the
        exchange and the user lands signed-in ON the website. This is
        the cross-domain fix (founder 2026-06-22): Google consent
        converges here and bounces home.
      * A desktop LOOPBACK URL (http://127.0.0.1:<port>/cb) — 302 with
        ?code=... so the desktop's loopback server catches it.
      * No redirect — the plain browser finisher below exchanges the
        code here + drops a session token in localStorage.

    SECURITY (open-redirect / CodeQL "URL redirection from remote
    source"): the only non-empty redirects ever honoured are (a) an
    EXACT-match entry in the FIXED website-origin allowlist, or (b) a
    loopback host. Anything else — an arbitrary host, a protocol-relative
    "//evil", a non-http(s) scheme — is rejected (400). The website case
    uses our OWN fixed "/signin" path, so a smuggled path can't steer the
    code; the loopback case reuses the unchanged _is_loopback_redirect
    guard."""
    if redirect:
        # 1) Cross-domain WEBSITE return — bounce the code to the marketing
        #    site's /signin so auth.js (inlineCode path) exchanges it there.
        website_origin = _website_return_origin(redirect)
        if website_origin:
            url = (website_origin + "/signin?code="
                   + urllib.parse.quote(code, safe=""))
            if state:
                url += "&state=" + urllib.parse.quote(state, safe="")
            return RedirectResponse(url=url, status_code=302)
        # 2) Desktop LOOPBACK return — only ever 302 to the desktop's OWN
        #    loopback URL, never an attacker-supplied external host. The final
        #    URL is rebuilt from VALIDATED parts by _loopback_return_url (host
        #    pinned to the loopback allowlist), so the raw user redirect string
        #    never reaches the Location header (open-redirect / CodeQL safe).
        #
        # Forward the desktop loopback's expected CSRF token: the client's
        # own `state`, recovered from the signed state in exchange_callback,
        # so the loopback's expected_state check passes.
        fwd_state = state
        loopback_url = _loopback_return_url(redirect, code=code, state=fwd_state)
        if not loopback_url:
            raise HTTPException(status_code=400,
                                detail={"error": "redirect_not_allowed"})
        return RedirectResponse(url=loopback_url, status_code=302)
    safe_code = "".join(c for c in code if c.isalnum() or c in "-_.")
    html = f"""<!doctype html><html><head><title>Signing you in — ArchHub</title>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<style>
  body {{ margin:0; padding:60px 24px; background:#0f0f12; color:#ece8e0;
          font-family:system-ui,-apple-system,'Segoe UI',sans-serif; }}
  .card {{ max-width:480px; margin:0 auto; padding:36px; background:#1d1d22;
           border:1px solid #26262d; border-radius:14px; }}
  h1 {{ margin:0 0 8px; font-family:Georgia,serif; font-style:italic;
        font-size:30px; letter-spacing:-0.02em; }}
  p {{ color:#9b938a; line-height:1.55; font-size:14px; }}
  .ok {{ margin-top:18px; padding:14px; background:rgba(126,193,142,0.1);
         border:1px solid #7ec18e; border-radius:10px; color:#7ec18e; }}
  .err {{ margin-top:18px; padding:14px; background:rgba(229,90,90,0.1);
          border:1px solid #e55a5a; border-radius:10px; color:#e55a5a; }}
  a.btn {{ display:inline-block; margin-top:14px; padding:12px 22px;
           background:#d97757; color:#fff; border-radius:10px;
           text-decoration:none; font-weight:500; }}
</style></head><body>
<div class='card' id='card'>
  <h1>Signing you in…</h1>
  <p>Hold on while we finish your Google sign-in.</p>
  <div id='out'></div>
</div>
<script>
// Browser-direct exchange. A Google sign-in begun in this browser
// carries no PKCE pair: the code row has an empty code_challenge and
// the one-time code is consumed without a verifier.
const code = "{safe_code}";
(async function() {{
  const card = document.getElementById('card');
  const out = document.getElementById('out');
  if (!code) {{
    card.querySelector('h1').textContent = 'Missing code';
    out.innerHTML = '<div class="err">No sign-in code in the address.</div>'
      + '<a class="btn" href="/signin">Back to sign-in</a>';
    return;
  }}
  try {{
    const r = await fetch('/v1/auth/exchange', {{
      method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{ code, code_verifier: '' }}),
    }});
    if (!r.ok) {{
      const d = await r.json().catch(()=>({{detail:'unknown'}}));
      let msg = d.detail; if (typeof msg === 'object') msg = JSON.stringify(msg);
      card.querySelector('h1').textContent = 'Exchange failed';
      out.innerHTML = '<div class="err">' + (msg||'unknown') + '</div>'
        + '<a class="btn" href="/signin">Try again</a>';
      return;
    }}
    const j = await r.json();
    const token = j.token || j.access_token || '';
    localStorage.setItem('archhub_session_token', token);
    // Back to the page that started the sign-in (same-origin paths only).
    let back = '';
    try {{ back = localStorage.getItem('archhub_after_signin') || '';
          localStorage.removeItem('archhub_after_signin'); }} catch (e) {{}}
    if (back.charAt(0) === '/' && back.charAt(1) !== '/'
        && back.indexOf(':') < 0) {{
      location.replace(back); return;
    }}
    card.querySelector('h1').textContent = "You're signed in.";
    out.innerHTML = '<div class="ok">Plan: <b>' + (j.plan||'trial') + '</b>. '
      + 'Session token stored locally.</div>'
      + '<a class="btn" href="/dashboard">Open dashboard →</a>'
      + ' &nbsp; <a class="btn" style="background:transparent;border:1px solid #26262d" href="/upgrade">Choose a plan</a>';
  }} catch(e) {{
    out.innerHTML = '<div class="err">Network error: ' + e + '</div>';
  }}
}})();
</script></body></html>"""
    return HTMLResponse(content=html)


@app.get("/invite", response_class=HTMLResponse)
def invite_landing(token: str = "") -> HTMLResponse:
    """Invite acceptance page (roadmap #P0). A teammate clicks the
    invite email's {PUBLIC_URL}/invite?token=... link and lands here.

    Self-contained client-side JS, no new API. Sign-in is the one Google
    button (/v1/auth/google/start -> /auth/return, which stores the session
    and comes back here); the page then POSTs /v1/companies/invites/accept
    with the bearer."""
    safe_token = "".join(c for c in token if c.isalnum() or c in "-_")
    html = f"""<!doctype html><html><head><title>Accept invite — ArchHub</title>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<style>
  :root {{ --bg:#0f0f12; --raised:#1d1d22; --ink:#ece8e0;
           --soft:#9b938a; --line:#26262d; --accent:#d97757; }}
  body {{ margin:0; padding:60px 24px; background:var(--bg);
          color:var(--ink); font-family:system-ui,-apple-system,
          'Segoe UI',sans-serif; }}
  .card {{ max-width:480px; margin:0 auto; padding:36px;
           background:var(--raised); border:1px solid var(--line);
           border-radius:14px; }}
  h1 {{ margin:0 0 8px; font-family:Georgia,serif; font-style:italic;
        font-size:30px; letter-spacing:-0.02em; }}
  p {{ color:var(--soft); line-height:1.55; font-size:14px; }}
  button {{ width:100%; padding:14px; margin-top:14px;
            background:var(--accent); color:white; border:none;
            border-radius:10px; font-size:15px; font-weight:500;
            cursor:pointer; }}
  button:hover {{ background:#a04832; }}
  button:disabled {{ opacity:0.5; cursor:default; }}
  .ok {{ margin-top:18px; padding:14px; background:rgba(126,193,142,0.1);
         border:1px solid #7ec18e; border-radius:10px; color:#7ec18e; }}
  .err {{ margin-top:18px; padding:14px; background:rgba(229,178,90,0.1);
          border:1px solid #e5b25a; border-radius:10px; color:#e5b25a; }}
</style></head><body>
<div class='card'>
  <h1>Join your team on ArchHub</h1>
  <p id='lead'>You've been invited to a company workspace. Continue
     with Google on the email address the invite was sent to, and the
     invite is accepted.</p>
  <button type='button' id='google' onclick='return continueWithGoogle()'>Continue with Google</button>
  <div id='out'></div>
</div>
<script>
const INVITE = "{safe_token}";
{_GOOGLE_SIGNIN_JS}
function show(cls, msg) {{
  document.getElementById('out').innerHTML =
    '<div class="' + cls + '">' + msg + '</div>';
}}
function signInAgain(msg) {{
  forgetSession();
  document.getElementById('google').style.display = '';
  show('err', msg);
}}
async function completeAccept() {{
  if (!INVITE) {{ show('err','This invite link is missing its token.');
                  return; }}
  const tok = sessionToken();
  if (!tok) return;
  document.getElementById('google').style.display = 'none';
  document.getElementById('lead').textContent =
    'Finishing up — accepting your invite…';
  try {{
    const ac = await fetch('/v1/companies/invites/accept', {{
      method:'POST',
      headers:{{'Content-Type':'application/json',
                'Authorization':'Bearer ' + tok}},
      body: JSON.stringify({{ invite_token:INVITE }}),
    }});
    if (ac.ok) {{
      const d = await ac.json();
      show('ok','You have joined the team as <b>'
        + (d.role||'member') + '</b>. Open ArchHub on your desktop — '
        + 'your shared workspace is ready.');
    }} else if (ac.status === 401) {{
      signInAgain('Your session ended. Continue with Google again.');
    }} else {{
      const d = await ac.json().catch(() => ({{detail:'unknown'}}));
      if (d.detail === 'invite_email_mismatch') {{
        signInAgain('This invite was sent to a different email address. '
          + 'Continue with Google on that address.');
        return;
      }}
      const msg = {{
        invite_not_found:'This invite no longer exists.',
        invite_already_used:'This invite was already accepted.',
        invite_expired:'This invite has expired — ask for a new one.',
      }};
      show('err', msg[d.detail] || ('Could not accept the invite: '
        + (d.detail||'error')));
    }}
  }} catch(e) {{
    show('err','Network error: ' + e);
  }}
}}
completeAccept();
</script></body></html>"""
    return HTMLResponse(content=html)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_landing() -> HTMLResponse:
    """Customer admin dashboard (roadmap #P2). A signed-in user sees
    their account — plan, message quota — plus every company they
    belong to and, for the active one, the team roster.

    Self-contained, like /invite: the one Google button signs in (the
    session comes back through /auth/return), then it reads the existing
    /v1/me + /v1/companies endpoints with the bearer and renders. No
    new API."""
    html = """<!doctype html><html><head>
<title>Account — ArchHub</title>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<style>
  :root { --bg:#0f0f12; --raised:#1d1d22; --ink:#ece8e0;
          --soft:#9b938a; --line:#26262d; --accent:#d97757;
          --ok:#7ec18e; }
  body { margin:0; padding:48px 24px; background:var(--bg);
         color:var(--ink); font-family:system-ui,-apple-system,
         'Segoe UI',sans-serif; }
  .wrap { max-width:680px; margin:0 auto; }
  h1 { margin:0 0 6px; font-family:Georgia,serif; font-style:italic;
       font-size:30px; letter-spacing:-0.02em; }
  .lead { color:var(--soft); font-size:14px; line-height:1.55;
          margin:0 0 24px; }
  .card { background:var(--raised); border:1px solid var(--line);
          border-radius:12px; padding:20px 22px; margin-bottom:16px; }
  .card h2 { margin:0 0 12px; font-size:13px; letter-spacing:0.12em;
             text-transform:uppercase; color:var(--soft); }
  .row { display:flex; justify-content:space-between; padding:7px 0;
         border-bottom:1px solid var(--line); font-size:14px; }
  .row:last-child { border-bottom:none; }
  .row .k { color:var(--soft); }
  .row .v { color:var(--ink); font-weight:500; }
  .pill { display:inline-block; padding:2px 9px; border-radius:20px;
          font-size:11px; background:var(--accent); color:#fff;
          letter-spacing:0.04em; }
  .pill.muted { background:var(--line); color:var(--soft); }
  button { width:100%; padding:13px; margin-top:12px;
           background:var(--accent); color:#fff; border:none;
           border-radius:10px; font-size:15px; font-weight:500;
           cursor:pointer; }
  .err { margin-top:16px; padding:13px; border-radius:10px;
         background:rgba(229,178,90,0.1); border:1px solid #e5b25a;
         color:#e5b25a; font-size:13px; }
  a { color:var(--accent); }
</style></head><body>
<div class='wrap'>
  <h1>Your ArchHub account</h1>
  <p class='lead' id='lead'>Sign in to see your account.</p>
  <button type='button' id='google' onclick='return continueWithGoogle()'>Continue with Google</button>
  <div id='out'></div>
  <div id='dash'></div>
</div>
<script>
""" + _GOOGLE_SIGNIN_JS + """
function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"]/g, c => (
    {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
}
function showErr(msg) {
  document.getElementById('out').innerHTML =
    '<div class="err">' + esc(msg) + '</div>';
}
function card(title, rows) {
  return '<div class="card"><h2>' + esc(title) + '</h2>'
    + rows.map(r => '<div class="row"><span class="k">' + esc(r[0])
        + '</span><span class="v">' + (r[2] ? r[1] : esc(r[1]))
        + '</span></div>').join('') + '</div>';
}
async function loadDashboard(token) {
  const H = { 'Authorization':'Bearer ' + token };
  const dash = document.getElementById('dash');
  try {
    const me = await (await fetch('/v1/me', {headers:H})).json();
    const mine = await (await fetch('/v1/companies/mine',
      {headers:H})).json();
    let html = card('Account', [
      ['Email', esc(me.email)],
      ['Plan', '<span class="pill">' + esc(me.plan) + '</span>', true],
      ['Messages remaining', String(me.remaining_messages)],
    ]);
    const companies = (mine.companies || []);
    if (companies.length) {
      html += '<div class="card"><h2>Companies</h2>'
        + companies.map(c => '<div class="row"><span class="k">'
            + esc(c.name) + (c.is_current
              ? ' <span class="pill">current</span>' : '')
            + '</span><span class="v">' + esc(c.role) + ' · '
            + esc(c.plan) + ' · ' + esc(c.seat_limit)
            + ' seats</span></div>').join('') + '</div>';
      const cur = companies.find(c => c.is_current) || companies[0];
      const detail = await (await fetch('/v1/companies/' + cur.id,
        {headers:H})).json();
      if (detail && detail.members) {
        html += '<div class="card"><h2>' + esc(cur.name)
          + ' — team (' + detail.members.length + ')</h2>'
          + detail.members.map(m => '<div class="row"><span class="k">'
              + esc(m.full_name || m.email) + '</span>'
              + '<span class="v">' + esc(m.role) + '</span></div>')
              .join('') + '</div>';
      }
    } else {
      html += card('Companies',
        [['No companies', 'Solo account', false]]);
    }
    dash.innerHTML = html;
  } catch(e) {
    showErr('Could not load your dashboard: ' + e);
  }
}
async function init() {
  const tok = sessionToken();
  if (!tok) return;
  document.getElementById('google').style.display = 'none';
  document.getElementById('lead').textContent = 'Loading your account…';
  const probe = await fetch('/v1/me', {headers:{'Authorization':'Bearer ' + tok}})
    .catch(() => null);
  if (!probe || probe.status === 401) {
    forgetSession();
    document.getElementById('google').style.display = '';
    document.getElementById('lead').textContent =
      'Your session ended. Continue with Google to sign in again.';
    return;
  }
  document.getElementById('lead').textContent =
    'Signed in. Here is your account.';
  await loadDashboard(tok);
}
init();
</script></body></html>"""
    return HTMLResponse(content=html)


@app.get("/brain", response_class=HTMLResponse)
def brain_portal() -> HTMLResponse:
    """Cloud brain portal — a signed-in user sees their REAL synced personal
    brain (the per-user replica /v1/brain/sync writes), searchable, with their
    tier badge + caps.

    Self-contained, mirroring /dashboard: the one Google button signs in
    (session back through /auth/return), then reads the EXISTING /v1/me +
    the new /v1/brain/stats + /v1/brain/facts + /v1/brain/search with the
    bearer and renders. No new auth, no new store — same-origin /v1 API."""
    html = """<!doctype html><html><head>
<title>Brain — ArchHub</title>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<style>
  :root { --bg:#0f0f12; --raised:#1d1d22; --ink:#ece8e0;
          --soft:#9b938a; --line:#26262d; --accent:#d97757;
          --ok:#7ec18e; --warn:#e5b25a; }
  body { margin:0; padding:48px 24px; background:var(--bg);
         color:var(--ink); font-family:system-ui,-apple-system,
         'Segoe UI',sans-serif; }
  .wrap { max-width:760px; margin:0 auto; }
  h1 { margin:0 0 6px; font-family:Georgia,serif; font-style:italic;
       font-size:30px; letter-spacing:-0.02em; }
  .lead { color:var(--soft); font-size:14px; line-height:1.55;
          margin:0 0 24px; }
  .card { background:var(--raised); border:1px solid var(--line);
          border-radius:12px; padding:20px 22px; margin-bottom:16px; }
  .card h2 { margin:0 0 12px; font-size:13px; letter-spacing:0.12em;
             text-transform:uppercase; color:var(--soft); }
  .row { display:flex; justify-content:space-between; padding:7px 0;
         border-bottom:1px solid var(--line); font-size:14px; }
  .row:last-child { border-bottom:none; }
  .row .k { color:var(--soft); }
  .row .v { color:var(--ink); font-weight:500; }
  .pill { display:inline-block; padding:2px 9px; border-radius:20px;
          font-size:11px; background:var(--accent); color:#fff;
          letter-spacing:0.04em; }
  .pill.muted { background:var(--line); color:var(--soft); }
  .pill.ok { background:rgba(126,193,142,0.16); color:var(--ok); }
  .fact { padding:12px 0; border-bottom:1px solid var(--line); }
  .fact:last-child { border-bottom:none; }
  .fact .t { font-size:14px; line-height:1.5; color:var(--ink); }
  .fact .m { margin-top:6px; display:flex; gap:8px; flex-wrap:wrap;
             font-size:11px; color:var(--soft); align-items:center; }
  .tag { display:inline-block; padding:1px 7px; border-radius:6px;
         background:var(--line); color:var(--soft); font-size:10px;
         letter-spacing:0.03em; }
  input { width:100%; padding:13px 15px; border-radius:10px;
          border:1px solid var(--line); background:var(--bg);
          color:var(--ink); font-size:15px; margin-top:16px;
          box-sizing:border-box; }
  #q { margin-top:0; }
  button { width:100%; padding:13px; margin-top:12px;
           background:var(--accent); color:#fff; border:none;
           border-radius:10px; font-size:15px; font-weight:500;
           cursor:pointer; }
  .err { margin-top:16px; padding:13px; border-radius:10px;
         background:rgba(229,178,90,0.1); border:1px solid #e5b25a;
         color:#e5b25a; font-size:13px; }
  .empty { color:var(--soft); font-size:13px; padding:8px 0; }
  .cta { display:inline-block; margin-top:10px; padding:8px 14px;
         border-radius:8px; background:var(--accent); color:#fff;
         font-size:13px; cursor:pointer; }
  a { color:var(--accent); }
</style></head><body>
<div class='wrap'>
  <h1>Your ArchHub brain</h1>
  <p class='lead' id='lead'>Sign in to open your synced knowledge.</p>
  <button type='button' id='google' onclick='return continueWithGoogle()'>Continue with Google</button>
  <div id='out'></div>
  <div id='portal'></div>
</div>
<script>
""" + _GOOGLE_SIGNIN_JS + """
function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"]/g, c => (
    {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
}
function showErr(msg) {
  document.getElementById('out').innerHTML =
    '<div class="err">' + esc(msg) + '</div>';
}
let TOKEN = null;
function factCard(f) {
  const tags = [];
  tags.push('<span class="tag">' + esc(f.scope || 'user') + '</span>');
  if (f.visibility && f.visibility !== 'private')
    tags.push('<span class="tag">' + esc(f.visibility) + '</span>');
  if (f.confidence)
    tags.push('<span class="tag">' + esc(f.confidence) + '</span>');
  if (f.updated_at)
    tags.push('<span>' + esc(String(f.updated_at).slice(0,10)) + '</span>');
  return '<div class="fact"><div class="t">' + esc(f.text)
    + '</div><div class="m">' + tags.join('') + '</div></div>';
}
function renderFacts(rows, capped) {
  if (!rows || !rows.length)
    return '<div class="empty">No facts yet. Open ArchHub and sync your '
      + 'brain — your synced knowledge appears here.</div>';
  let h = rows.map(factCard).join('');
  if (capped)
    h += '<div class="empty">Showing your most recent facts (tier cap). '
      + '<a href="/upgrade">Upgrade</a> to see more.</div>';
  return h;
}
async function doSearch() {
  const q = document.getElementById('q').value.trim();
  const list = document.getElementById('list');
  const H = { 'Authorization':'Bearer ' + TOKEN };
  list.innerHTML = '<div class="empty">Searching…</div>';
  try {
    const r = await fetch('/v1/brain/search?q=' + encodeURIComponent(q)
      + '&limit=200', {headers:H});
    if (r.status === 402) {
      list.innerHTML = '<div class="empty">Search is a paid feature. '
        + '<a href="/upgrade">Upgrade</a> to search your brain.</div>';
      return;
    }
    const d = await r.json();
    list.innerHTML = renderFacts(d.results, false);
  } catch(e) { list.innerHTML = '<div class="err">' + esc(''+e) + '</div>'; }
}
async function loadPortal(token) {
  TOKEN = token;
  const H = { 'Authorization':'Bearer ' + token };
  const portal = document.getElementById('portal');
  try {
    const me = await (await fetch('/v1/me', {headers:H})).json();
    const stats = await (await fetch('/v1/brain/stats',
      {headers:H})).json();
    const facts = await (await fetch('/v1/brain/facts?limit=200',
      {headers:H})).json();
    const caps = stats.caps || {};
    let html = '<div class="card"><h2>Account</h2>'
      + '<div class="row"><span class="k">Email</span><span class="v">'
      + esc(me.email) + '</span></div>'
      + '<div class="row"><span class="k">Plan</span><span class="v">'
      + '<span class="pill">' + esc(me.plan) + '</span></span></div>'
      + '<div class="row"><span class="k">Synced facts</span>'
      + '<span class="v">' + (stats.total_facts || 0) + '</span></div>'
      + '<div class="row"><span class="k">Last sync</span><span class="v">'
      + (stats.ever_synced
          ? '<span class="pill ok">synced</span>'
          : '<span class="pill muted">never synced</span>')
      + '</span></div></div>';
    // search box (gated)
    html += '<div class="card"><h2>Search your knowledge</h2>';
    if (caps.can_search) {
      html += '<input id="q" placeholder="Search facts…" '
        + 'oninput="if(window._t)clearTimeout(window._t);'
        + 'window._t=setTimeout(doSearch,250)">';
    } else {
      html += '<div class="empty">Search is available on paid plans. '
        + '<a class="cta" href="/upgrade">Upgrade to search</a></div>';
    }
    html += '<div id="list" style="margin-top:14px">'
      + renderFacts(facts.results, facts.capped) + '</div></div>';
    portal.innerHTML = html;
  } catch(e) {
    showErr('Could not load your brain: ' + e);
  }
}
async function init() {
  const tok = sessionToken();
  if (!tok) return;
  document.getElementById('google').style.display = 'none';
  document.getElementById('lead').textContent = 'Loading your brain…';
  const probe = await fetch('/v1/me', {headers:{'Authorization':'Bearer ' + tok}})
    .catch(() => null);
  if (!probe || probe.status === 401) {
    forgetSession();
    document.getElementById('google').style.display = '';
    document.getElementById('lead').textContent =
      'Your session ended. Continue with Google to sign in again.';
    return;
  }
  document.getElementById('lead').textContent =
    'Signed in. Here is your synced knowledge.';
  await loadPortal(tok);
}
init();
</script></body></html>"""
    return HTMLResponse(content=html)


# Stripe Customer-Portal / Checkout return landing pages — minimal.
@app.get("/billing/success")
def billing_success() -> HTMLResponse:
    return HTMLResponse(
        "<html><body style='font-family:system-ui;padding:60px;"
        "max-width:520px;margin:0 auto;color:#ece8e0;background:#0f0f12;'>"
        "<h1>Upgraded.</h1>"
        "<p>Open ArchHub — your new plan is live within a minute.</p>"
        "</body></html>"
    )


@app.get("/billing/cancel")
def billing_cancel() -> HTMLResponse:
    return HTMLResponse(
        "<html><body style='font-family:system-ui;padding:60px;"
        "max-width:520px;margin:0 auto;color:#ece8e0;background:#0f0f12;'>"
        "<h1>Cancelled.</h1>"
        "<p>No charge. Open ArchHub when you're ready.</p>"
        "</body></html>"
    )


@app.get("/billing/portal_return")
def billing_portal_return() -> HTMLResponse:
    return RedirectResponse(url="/billing/success", status_code=302)


# ---------------------------------------------------------------------------
# Top-level redirect: archhub.io/upgrade?tier=studio etc → checkout
# requires the user is already signed in (we don't accept anonymous
# checkout flows). Send them to /signin if not.
@app.get("/upgrade")
def upgrade(tier: str = "studio") -> HTMLResponse:
    return HTMLResponse(
        f"<html><body style='font-family:system-ui;padding:60px;"
        f"max-width:520px;margin:0 auto;color:#ece8e0;background:#0f0f12;'>"
        f"<h1>Upgrade to {tier.title()}</h1>"
        f"<p>Open ArchHub → Pricing → {tier.title()} to start "
        f"checkout. Or sign in <a href='/signin' style='color:#d97757'>"
        f"here</a> on the web.</p></body></html>"
    )


@app.get("/billing/credits")
def billing_credits_landing() -> HTMLResponse:
    """Hosted-AI credit-pack top-up landing (Model C). The proxy's
    out_of_credits 402 points users here. Numbers come from
    config.CREDIT_PACK so the page can't drift from billing."""
    pack = config.CREDIT_PACK
    return HTMLResponse(
        f"<html><body style='font-family:system-ui;padding:60px;"
        f"max-width:520px;margin:0 auto;color:#ece8e0;background:#0f0f12;'>"
        f"<h1>Top up hosted AI</h1>"
        f"<p>A credit pack is <b>${pack['price_usd']} = "
        f"{pack['messages']:,} messages</b>, and unused credits roll "
        f"over for {pack['rollover_days']} days. Open ArchHub → "
        f"Settings → Billing to buy a pack, or switch the workspace to "
        f"<b>BYO-key</b> mode to use your own provider key.</p>"
        f"</body></html>"
    )

# ── The founder's brain, over MCP, from any machine ──────────────────────
import json as json_module  # noqa: E402  (this module has no top-level json)
import brain_mcp  # noqa: E402  (module-local import style of this file)
from starlette.concurrency import run_in_threadpool  # noqa: E402


@app.post("/mcp")
async def brain_over_mcp(req: Request,
                         authorization: str | None = Header(None)) -> Response:
    """This account's brain, over MCP.

    Sessions speak MCP and this cloud served only REST, so Claude, Codex and
    Antigravity all pointed at a LOCAL daemon on 127.0.0.1:8473 -- the thing
    that has to be alive, hold a port and survive a wedge. The memory itself
    has been here all along (audit, 2026-09-07).

    Stateless: every POST is self-contained and no prior initialize is
    required, exactly like the local daemon, so a client only changes its
    URL. The identity is the ACCOUNT token, never a machine.
    """
    # req.json() rather than json.loads: this module has no module-level
    # `json`, so the bare name raised NameError, the except below swallowed
    # it, and EVERY request came back 400 with an empty body -- a swallowed
    # error that looked exactly like a malformed request (2026-09-07).
    try:
        message = await req.json()
    except Exception as unread:
        # Say WHY. A silent 400 with an empty body is indistinguishable from
        # a malformed request, and that is exactly how a NameError in this
        # very line hid for two deploys (2026-09-07).
        return Response(
            status_code=400,
            content=json_module.dumps({
                "error": "unreadable request body",
                "reason": type(unread).__name__,
            }).encode("utf-8"),
            media_type="application/json",
        )
    # In a worker thread: a live host read waits for the founder's app (up to
    # COCKPIT_APP_RELAY_WAIT_S), and that wait must not hold the event loop.
    status, body, media = await run_in_threadpool(
        brain_mcp.answer,
        message,
        resolve_user=lambda: _require_user(authorization),
        open_replica=_brain_read_replica,
        is_founder=_is_founder_account,
        host_read=_desktop_host_read,
        pushed_hosts=founder_cockpit.pushed_hosts,
    )
    return Response(status_code=status, content=body, media_type=media)


def _is_founder_account(user: dict) -> bool:
    return (user.get("email") or "").strip().lower() in config.founder_emails()


def _desktop_host_read(user: dict, tool: str, arguments: dict) -> object:
    """Queue one read for the founder's running application and wait for it."""
    import app_relay
    return app_relay.host_read(tool, arguments,
                               actor=(user.get("email") or "").strip().lower())
