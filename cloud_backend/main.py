"""ArchHub Cloud backend — FastAPI app.

Endpoints (matches docs/BACKEND_SPEC.md):
  POST /v1/auth/register
  POST /v1/auth/exchange
  GET  /v1/me
  POST /v1/chat/completions
  POST /v1/billing/checkout
  GET  /v1/billing/portal
  POST /v1/webhooks/stripe
  GET  /healthz                 (Fly.io health check)
  GET  /signin                  (server-rendered redirect page for the
                                  PKCE flow desktop initiates)

Auth model: bearer token in `Authorization: Bearer <token>`. Tokens
are minted by /v1/auth/exchange after the user clicks their
magic-link. The client-side PKCE pair binds the desktop instance to
the auth-code lookup.

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
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from pydantic import BaseModel, EmailStr, Field

import auth
import billing
import companies
import config
import db
import founder_cockpit
import google_auth
import marketplace
import proxy


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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://archhub.io", "http://localhost:5173",
                    "http://localhost:3000"],
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
class RegisterReq(BaseModel):
    email: EmailStr
    # Allow empty challenge for browser-direct flows (see
    # db.consume_code 2026-05-24 — code-only auth, no PKCE).
    # Desktop client still sends a real 20+ char challenge.
    code_challenge: str = Field(default="", max_length=200)
    redirect: str = ""
    # Optional customer-profile fields captured by the landing form.
    # All optional — magic-link sign-in still works without them.
    full_name: str | None = None
    firm_name: str | None = None
    aec_role: str | None = None
    aec_discipline: str | None = None
    firm_size: str | None = None
    country: str | None = None
    signup_source: str | None = None
    landing_variant: str | None = None


class ExchangeReq(BaseModel):
    code: str = Field(min_length=10, max_length=200)
    # PKCE verifier. For a code issued WITH a non-empty challenge
    # (desktop client), the exchange MUST present a matching verifier —
    # main enforces a real min_length on that path (see `exchange`
    # below) so a challenged code can't be redeemed with an empty
    # verifier. Browser-direct codes are issued with an EMPTY challenge
    # (magic-link is the one-time, 5-min secret); those legitimately
    # pass an empty verifier, so the field default stays "".
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


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "ts": int(time.time())}


@app.post("/v1/auth/register", status_code=202)
async def register(req: RegisterReq) -> dict:
    """Trigger the magic-link email + capture the PKCE challenge.

    Optional profile fields on the request body (full_name, firm_name,
    aec_role, …) are written to the users table before the email goes
    out so marketing has attribution data even if the user never clicks
    the magic-link.
    """
    ok = await auth.register_via_email(
        email=req.email,
        code_challenge=req.code_challenge,
        redirect=req.redirect,
    )
    if not ok:
        raise HTTPException(status_code=502,
                             detail="email_send_failed")
    # User row was created inside register_via_email — write profile
    # fields onto it. db.update_user_profile drops unknown keys so
    # this is safe to call with the full request dict.
    user = db.get_user_by_email(str(req.email))
    if user is not None:
        profile = req.model_dump(exclude={"email", "code_challenge",
                                          "redirect"}, exclude_none=True)
        if profile:
            db.update_user_profile(user["id"], **profile)
    return {"status": "accepted"}


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


# ── Sign in with Google (OAuth2 / OpenID Connect) — ADDITIVE ──────────
# Two routes that bolt Google sign-in onto the EXISTING user + code +
# token machinery. They reuse db.get_or_create_user + db.issue_code +
# /auth/return so a Google sign-in converges on the SAME account (keyed
# by email) and finishes through the UNCHANGED /v1/auth/exchange path.
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

    The desktop generates a PKCE pair (same as the magic-link path) and
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
    the loopback on the final redirect. Optional -- the browser/magic-link
    path sends none and is unaffected.

    Open-redirect guard: a SUPPLIED redirect must be a loopback
    (127.0.0.1 / localhost / ::1) http(s) URL. Because the callback ends
    up forwarding a freshly-minted auth code to this target, any other
    host is rejected (400 google_redirect_not_loopback) so a code can
    never be bounced to an attacker-controlled URL.
    """
    if redirect and not _is_loopback_redirect(redirect):
        raise HTTPException(
            status_code=400,
            detail={"error": "google_redirect_not_loopback"})
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
    {PUBLIC_URL}/auth/return?code=... — the SAME surface the magic-link
    uses, so the desktop loopback finishes via /v1/auth/exchange.

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
    }


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


@app.post("/v1/memory/facts/{fact_id}/promote")
async def memory_facts_promote(fact_id: int, req: Request,
                                 authorization: str | None = Header(None)) -> dict:
    """Private → collective. Redacts via transform policy first."""
    user = _require_user(authorization)
    body = await req.json() if await _has_body(req) else {}
    try:
        cid = memory_writer.promote_to_shared(
            fact_id=fact_id, user_id=user["id"],
            access_policy=body.get("access_policy", "public"),
            domain=body.get("domain", "aec.general"),
        )
    except ValueError as ex:
        raise HTTPException(status_code=400,
                             detail={"error": str(ex)})
    return {"collective_id": cid, "stage": "promoted"}


@app.get("/v1/memory/collective")
def memory_collective_list(domain: str | None = None,
                             limit: int = 50,
                             authorization: str | None = Header(None)) -> dict:
    """Browse community-shared facts. Reads are audited for any user
    other than the contributor."""
    user = _require_user(authorization)
    rows = db.list_collective_memory(domain=domain,
                                       limit=max(1, min(int(limit), 200)))
    for r in rows:
        db.log_memory_access(
            reader_user_id=user["id"], collective_id=int(r["id"]),
            purpose="browse",
        )
    return {"results": rows}


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
    community_keys = body.get("community_keys") or []
    if not isinstance(community_keys, list):
        community_keys = []
    community_keys = [str(k) for k in community_keys if k]

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
        replica.firm_keys = sorted(
            set(replica.firm_keys)
            | set(replica.contributed_firm_keys())
            | set(merge_result.get("firm_keys") or []))
        replica.community_keys = sorted(
            set(replica.community_keys)
            | set(replica.contributed_community_keys())
            | set(merge_result.get("community_keys") or []))
        merged = replica.export_delta(since_hlc=since_hlc)
    except ValueError as ex:
        raise HTTPException(status_code=400, detail={"error": str(ex)})
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


async def _has_body(req: Request) -> bool:
    """FastAPI lets you call .json() on an empty body; we want to
    distinguish that from a JSON object. Returns False when the
    Content-Length is 0 or absent."""
    cl = req.headers.get("content-length") or "0"
    try:
        return int(cl) > 0
    except Exception:
        return False


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
@app.get("/signin", response_class=HTMLResponse)
def signin_landing(challenge: str = "", redirect: str = "",
                    state: str = "", client: str = "") -> HTMLResponse:
    """Server-rendered page the desktop client opens when starting
    PKCE. Asks the user for an email + POSTs /v1/auth/register so
    the magic-link goes out."""
    safe_redirect = redirect.replace('"', "")
    safe_challenge = challenge.replace('"', "")
    safe_state = state.replace('"', "")
    html = f"""<!doctype html><html><head><title>Sign in — ArchHub</title>
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
  input {{ width:100%; padding:14px 16px; border-radius:10px;
           border:1px solid var(--line); background:var(--bg);
           color:var(--ink); font-size:15px; margin-top:18px;
           box-sizing:border-box; }}
  input:focus {{ outline:none; border-color:var(--accent); }}
  button {{ width:100%; padding:14px; margin-top:14px;
            background:var(--accent); color:white; border:none;
            border-radius:10px; font-size:15px; font-weight:500;
            cursor:pointer; }}
  button:hover {{ background:#a04832; }}
  .ok {{ margin-top:18px; padding:14px; background:rgba(126,193,142,0.1);
         border:1px solid #7ec18e; border-radius:10px; color:#7ec18e; }}
  .err {{ margin-top:18px; padding:14px; background:rgba(229,178,90,0.1);
          border:1px solid #e5b25a; border-radius:10px; color:#e5b25a; }}
</style></head><body>
<div class='card'>
  <h1>Sign in to ArchHub Cloud</h1>
  <p>Enter your email. We'll send a magic-link — click it and
     ArchHub on your desktop signs you in automatically.</p>
  <form id='f' onsubmit='return submitEmail(event)'>
    <input id='email' type='email' placeholder='you@studio.com'
            required autofocus>
    <button type='submit' id='b'>Email me the sign-in link</button>
  </form>
  <div id='out'></div>
</div>
<script>
// Server-injected PKCE — set when desktop client deep-links here with
// ?challenge=...&redirect=loopback. For direct browser visits these
// are empty and we use the browser-direct flow (magic-link is the
// secret, no PKCE — fine because the code is one-time, 5-min TTL,
// and only delivered to the email-owner's inbox). See db.consume_code
// for the server-side gate.
let challenge = "{safe_challenge}";
let redirect = "{safe_redirect}";
const state = "{safe_state}";

async function submitEmail(ev) {{
  ev.preventDefault();
  const email = document.getElementById('email').value.trim();
  const btn = document.getElementById('b');
  const out = document.getElementById('out');
  btn.disabled = true; btn.textContent = 'Sending…';
  try {{
    // Browser-direct mode: leave challenge empty + default redirect
    // to /auth/return so the magic-link lands back on this domain.
    // No need to stash anything in sessionStorage — the magic-link
    // works from any browser the user opens it in.
    if (!challenge && !redirect) {{
      redirect = window.location.origin + '/auth/return';
    }}
    const r = await fetch('/v1/auth/register', {{
      method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{ email, code_challenge: challenge,
                              redirect: redirect }}),
    }});
    if (r.ok) {{
      out.innerHTML = '<div class="ok">Check your inbox at <b>'
        + email + '</b>. Click the link to finish signing in.</div>';
    }} else {{
      const d = await r.json().catch(()=>({{detail:'unknown'}}));
      let msg = d.detail;
      // pydantic 422 detail is an array of objects — render nicely
      if (Array.isArray(msg)) {{
        msg = msg.map(e => (e.loc||[]).join('.') + ': ' + (e.msg||e.type)).join(' · ');
      }} else if (typeof msg === 'object') {{
        msg = JSON.stringify(msg);
      }}
      out.innerHTML = '<div class="err">Sign-up failed: '
        + (msg||'unknown error') + '</div>';
      btn.disabled = false;
      btn.textContent = 'Email me the sign-in link';
    }}
  }} catch(e) {{
    out.innerHTML = '<div class="err">Network error: ' + e + '</div>';
    btn.disabled = false;
    btn.textContent = 'Email me the sign-in link';
  }}
  return false;
}}
</script></body></html>"""
    return HTMLResponse(content=html)


@app.get("/auth/return")
def auth_return(code: str = "", redirect: str = "",
                state: str = "") -> HTMLResponse:
    """Lands here from the magic-link email. If a `redirect` was
    provided by the desktop client, forward to it with ?code=...
    so the desktop's loopback server catches it.

    For direct-browser flows (no redirect), the /signin page stashed
    a PKCE verifier in sessionStorage — finish the exchange here +
    drop a session token in localStorage so /dashboard, /upgrade,
    etc. can call authenticated endpoints."""
    if redirect:
        # SECURITY (open-redirect / CodeQL "URL redirection from remote source"):
        # only ever 302 to the desktop's OWN loopback URL — never an attacker-
        # supplied external host. Reuses the SAME _is_loopback_redirect guard
        # that /v1/auth/google/start already applies, so /auth/return cannot be
        # turned into an open redirect that leaks the one-time code off-box.
        if not _is_loopback_redirect(redirect):
            raise HTTPException(status_code=400,
                                detail={"error": "redirect_not_loopback"})
        sep = "&" if "?" in redirect else "?"
        # Forward the desktop loopback's expected CSRF token. The Google
        # flow passes the client's own `state` (recovered from the signed
        # state in exchange_callback) so the loopback's expected_state
        # check passes. The magic-link path sends no `state`, so we keep
        # the historical "archhub" default -- byte-for-byte unchanged.
        fwd_state = state or "archhub"
        return RedirectResponse(
            url=f"{redirect}{sep}code={code}&state="
                + urllib.parse.quote(fwd_state, safe=""),
            status_code=302,
        )
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
  <p>Hold on while we exchange your magic-link code for a session.</p>
  <div id='out'></div>
</div>
<script>
// Browser-direct exchange. The magic-link landed here in ANY browser —
// no per-browser verifier needed. Server already validated the code
// row has empty code_challenge (issued by /signin in browser mode)
// and consumes the code without PKCE.
const code = "{safe_code}";
(async function() {{
  const card = document.getElementById('card');
  const out = document.getElementById('out');
  if (!code) {{
    card.querySelector('h1').textContent = 'Missing code';
    out.innerHTML = '<div class="err">No code in URL. Use the link from '
      + 'your sign-in email.</div>'
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

    Self-contained — all client-side JS, no new API. It runs the
    existing magic-link PKCE flow (register → /auth/return → exchange)
    then POSTs /v1/companies/invites/accept with the bearer. On return
    from the magic-link the URL carries ?code=... and the JS finishes
    automatically."""
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
  input {{ width:100%; padding:14px 16px; border-radius:10px;
           border:1px solid var(--line); background:var(--bg);
           color:var(--ink); font-size:15px; margin-top:18px;
           box-sizing:border-box; }}
  input:focus {{ outline:none; border-color:var(--accent); }}
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
  <p id='lead'>You've been invited to a company workspace. Sign in with
     your email to accept — we'll send a one-time magic-link.</p>
  <form id='f' onsubmit='return submitEmail(event)'>
    <input id='email' type='email' placeholder='you@studio.com'
            required autofocus>
    <button type='submit' id='b'>Email me the sign-in link</button>
  </form>
  <div id='out'></div>
</div>
<script>
const INVITE = "{safe_token}";
const b64url = (buf) => btoa(String.fromCharCode.apply(null,
  new Uint8Array(buf))).replace(/\\+/g,'-').replace(/\\//g,'_')
  .replace(/=+$/,'');
async function pkce() {{
  const v = b64url(crypto.getRandomValues(new Uint8Array(32)).buffer);
  const h = await crypto.subtle.digest('SHA-256',
    new TextEncoder().encode(v));
  return {{ verifier:v, challenge:b64url(h) }};
}}
function show(cls, msg) {{
  document.getElementById('out').innerHTML =
    '<div class="' + cls + '">' + msg + '</div>';
}}
async function submitEmail(ev) {{
  ev.preventDefault();
  if (!INVITE) {{ show('err','This invite link is missing its token.');
                  return false; }}
  const email = document.getElementById('email').value.trim();
  const btn = document.getElementById('b');
  btn.disabled = true; btn.textContent = 'Sending…';
  try {{
    const p = await pkce();
    sessionStorage.setItem('archhub_pkce_verifier', p.verifier);
    const r = await fetch('/v1/auth/register', {{
      method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{ email, code_challenge:p.challenge,
        redirect:'/invite?token=' + encodeURIComponent(INVITE) }}),
    }});
    if (r.ok) {{
      show('ok','Check your inbox — click the magic-link and your '
        + 'invite is accepted automatically.');
    }} else {{
      const d = await r.json().catch(() => ({{detail:'unknown'}}));
      show('err','Could not send the link: ' + (d.detail||'error'));
      btn.disabled = false;
      btn.textContent = 'Email me the sign-in link';
    }}
  }} catch(e) {{
    show('err','Network error: ' + e);
    btn.disabled = false;
    btn.textContent = 'Email me the sign-in link';
  }}
  return false;
}}
async function completeAccept() {{
  const code = new URLSearchParams(location.search).get('code');
  if (!code) return;
  document.getElementById('f').style.display = 'none';
  document.getElementById('lead').textContent =
    'Finishing up — accepting your invite…';
  const verifier = sessionStorage.getItem('archhub_pkce_verifier');
  if (!verifier) {{
    show('err','Sign-in session was lost. Re-open the invite link '
      + 'from your email.');
    return;
  }}
  try {{
    const ex = await fetch('/v1/auth/exchange', {{
      method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{ code, code_verifier:verifier }}),
    }});
    if (!ex.ok) {{
      show('err','Sign-in failed — the magic-link may have expired. '
        + 'Re-open the invite link.');
      return;
    }}
    const tok = (await ex.json()).token;
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
    }} else {{
      const d = await ac.json().catch(() => ({{detail:'unknown'}}));
      const msg = {{
        invite_not_found:'This invite no longer exists.',
        invite_already_used:'This invite was already accepted.',
        invite_expired:'This invite has expired — ask for a new one.',
        invite_email_mismatch:'This invite was sent to a different '
          + 'email address. Sign in with the exact address it was '
          + 'sent to, then re-open the invite link.',
      }};
      show('err', msg[d.detail] || ('Could not accept the invite: '
        + (d.detail||'error')));
    }}
  }} catch(e) {{
    show('err','Network error: ' + e);
  }}
  sessionStorage.removeItem('archhub_pkce_verifier');
}}
completeAccept();
</script></body></html>"""
    return HTMLResponse(content=html)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_landing() -> HTMLResponse:
    """Customer admin dashboard (roadmap #P2). A signed-in user sees
    their account — plan, message quota — plus every company they
    belong to and, for the active one, the team roster.

    Self-contained, like /invite: client-side magic-link PKCE
    (register → /auth/return → exchange), then it reads the existing
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
  input { width:100%; padding:13px 15px; border-radius:10px;
          border:1px solid var(--line); background:var(--bg);
          color:var(--ink); font-size:15px; margin-top:16px;
          box-sizing:border-box; }
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
  <p class='lead' id='lead'>Sign in with your email — we'll send a
     magic-link.</p>
  <form id='f' onsubmit='return submitEmail(event)'>
    <input id='email' type='email' placeholder='you@studio.com'
            required autofocus>
    <button type='submit' id='b'>Email me the sign-in link</button>
  </form>
  <div id='out'></div>
  <div id='dash'></div>
</div>
<script>
const b64url = (buf) => btoa(String.fromCharCode.apply(null,
  new Uint8Array(buf))).replace(/\\+/g,'-').replace(/\\//g,'_')
  .replace(/=+$/,'');
async function pkce() {
  const v = b64url(crypto.getRandomValues(new Uint8Array(32)).buffer);
  const h = await crypto.subtle.digest('SHA-256',
    new TextEncoder().encode(v));
  return { verifier:v, challenge:b64url(h) };
}
function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"]/g, c => (
    {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
}
function showErr(msg) {
  document.getElementById('out').innerHTML =
    '<div class="err">' + esc(msg) + '</div>';
}
async function submitEmail(ev) {
  ev.preventDefault();
  const email = document.getElementById('email').value.trim();
  const btn = document.getElementById('b');
  btn.disabled = true; btn.textContent = 'Sending…';
  try {
    const p = await pkce();
    sessionStorage.setItem('archhub_pkce_verifier', p.verifier);
    const r = await fetch('/v1/auth/register', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ email, code_challenge:p.challenge,
        redirect:'/dashboard' }),
    });
    if (r.ok) {
      document.getElementById('out').innerHTML =
        '<div class="err" style="background:rgba(126,193,142,0.1);'
        + 'border-color:#7ec18e;color:#7ec18e;">Check your inbox — '
        + 'click the magic-link to open your dashboard.</div>';
    } else {
      showErr('Could not send the link.');
      btn.disabled = false; btn.textContent = 'Email me the sign-in link';
    }
  } catch(e) {
    showErr('Network error: ' + e);
    btn.disabled = false; btn.textContent = 'Email me the sign-in link';
  }
  return false;
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
  const code = new URLSearchParams(location.search).get('code');
  if (!code) return;
  document.getElementById('f').style.display = 'none';
  document.getElementById('lead').textContent = 'Loading your account…';
  const verifier = sessionStorage.getItem('archhub_pkce_verifier');
  if (!verifier) {
    showErr('Sign-in session lost — reload /dashboard to retry.');
    return;
  }
  try {
    const ex = await fetch('/v1/auth/exchange', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ code, code_verifier:verifier }),
    });
    if (!ex.ok) { showErr('Sign-in failed — the link may have expired.');
                  return; }
    const tok = (await ex.json()).token;
    sessionStorage.removeItem('archhub_pkce_verifier');
    document.getElementById('lead').textContent =
      'Signed in. Here is your account.';
    await loadDashboard(tok);
  } catch(e) { showErr('Network error: ' + e); }
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
