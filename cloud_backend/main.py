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
# archhub.app can fetch /v1/me from the browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://archhub.app", "http://localhost:5173",
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


@app.post("/v1/billing/checkout")
def checkout(req: CheckoutReq,
              authorization: str | None = Header(None)) -> dict:
    user = _require_user(authorization)
    if req.tier not in config.PLAN_PRICE_IDS:
        raise HTTPException(status_code=400, detail="unknown_tier")
    url = billing.create_checkout_url(user=user, tier=req.tier)
    if not url:
        raise HTTPException(status_code=503,
                             detail="checkout_unavailable")
    return {"url": url}


@app.get("/v1/billing/portal")
def portal(authorization: str | None = Header(None)) -> dict:
    user = _require_user(authorization)
    url = billing.create_portal_url(user=user)
    if not url:
        raise HTTPException(status_code=400,
                             detail="no_subscription")
    return {"url": url}


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
const challenge = "{safe_challenge}";
const redirect = "{safe_redirect}";
const state = "{safe_state}";
async function submitEmail(ev) {{
  ev.preventDefault();
  const email = document.getElementById('email').value.trim();
  const btn = document.getElementById('b');
  const out = document.getElementById('out');
  btn.disabled = true; btn.textContent = 'Sending…';
  try {{
    const r = await fetch('/v1/auth/register', {{
      method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{ email, code_challenge: challenge,
                              redirect: redirect }}),
    }});
    if (r.ok) {{
      out.innerHTML = '<div class="ok">Check your inbox. Click '
        + 'the link to finish signing in.</div>';
    }} else {{
      const d = await r.json().catch(()=>({{detail:'unknown'}}));
      out.innerHTML = '<div class="err">Sign-up failed: '
        + (d.detail||'unknown error') + '</div>';
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
    so the desktop's loopback server catches it. Otherwise show a
    confirmation page."""
    if redirect:
        sep = "&" if "?" in redirect else "?"
        return RedirectResponse(
            url=f"{redirect}{sep}code={code}&state=archhub",
            status_code=302,
        )
    return HTMLResponse(
        "<html><body style='font-family:system-ui;padding:60px;"
        "max-width:520px;margin:0 auto;color:#ece8e0;background:#0f0f12;'>"
        "<h1 style='font-style:italic;'>You're signed in.</h1>"
        "<p>You can close this tab and return to ArchHub.</p>"
        "</body></html>"
    )


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
# Top-level redirect: archhub.app/upgrade?tier=studio etc → checkout
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
