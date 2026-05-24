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

from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from pydantic import BaseModel, EmailStr, Field

import auth
import billing
import companies
import config
import db
import marketplace
import proxy


app = FastAPI(
    title="ArchHub Cloud",
    version="1.0.0",
    description="Managed AI proxy for the ArchHub desktop client.",
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
    db.init_schema()


# Marketplace v1 routes — author upload, browse, install, review, report.
# Mounted at root (paths start /marketplace/...) so the desktop client's
# URL constants live next to /v1/* rather than under a separate prefix.
app.include_router(marketplace.router)

# Companies / multi-seat — POST /v1/companies, invites, members, switch.
app.include_router(companies.router)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class RegisterReq(BaseModel):
    email: EmailStr
    code_challenge: str = Field(min_length=20, max_length=200)
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
    code_verifier: str = Field(min_length=20, max_length=200)


class CheckoutReq(BaseModel):
    tier: str


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


@app.post("/v1/auth/exchange")
def exchange(req: ExchangeReq) -> dict:
    payload = auth.exchange_code(
        code=req.code, code_verifier=req.code_verifier,
    )
    if payload is None:
        raise HTTPException(status_code=400, detail="invalid_or_expired")
    return payload


@app.get("/v1/me")
def me(authorization: str | None = Header(None)) -> dict:
    user = _require_user(authorization)
    remaining = max(0, int(user["msg_limit"]) - int(user["msg_used"]))
    return {
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
    """Public plan catalog — used by the desktop app to render the
    pricing dialog without hardcoding tier metadata client-side.

    Returns whichever provider's tier IDs are configured. Both
    providers share the same tier names (solo / studio / firm) and
    quotas, so the desktop UI never needs to know which billing
    backend is in use.
    """
    tiers = []
    for tier_name in ("solo", "studio", "firm"):
        quota = config.PLAN_QUOTAS.get(tier_name, 0)
        seats = config.PLAN_SEATS.get(tier_name)
        if config.BILLING_PROVIDER == "polar":
            external_id = config.POLAR_PRODUCT_IDS.get(tier_name) or None
        else:
            external_id = config.PLAN_PRICE_IDS.get(tier_name) or None
        tiers.append({
            "tier": tier_name,
            "monthly_quota": quota,
            "seats": seats,
            # external_id is null when the price/product hasn't been
            # configured yet — the desktop UI shows "Coming soon".
            "external_id_configured": external_id is not None,
        })
    return {
        "provider": config.BILLING_PROVIDER,
        "tiers": tiers,
        "trial_messages": config.TRIAL_MESSAGES,
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
        user=user, tier=req.tier,
    )
    if not url:
        raise HTTPException(status_code=503,
                             detail="checkout_unavailable")
    return {"url": url}


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
def auth_return(code: str = "", redirect: str = "") -> HTMLResponse:
    """Lands here from the magic-link email. If a `redirect` was
    provided by the desktop client, forward to it with ?code=...
    so the desktop's loopback server catches it.

    For direct-browser flows (no redirect), the /signin page stashed
    a PKCE verifier in sessionStorage — finish the exchange here +
    drop a session token in localStorage so /dashboard, /upgrade,
    etc. can call authenticated endpoints."""
    if redirect:
        sep = "&" if "?" in redirect else "?"
        return RedirectResponse(
            url=f"{redirect}{sep}code={code}&state=archhub",
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
