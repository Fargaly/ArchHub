"""Founder Cockpit — PRIVATE founder-only admin dashboard (PHASE 5).

This is the surface the FOUNDER uses to oversee the ArchHub business. It is
NOT a user feature and it does NOT live in the desktop app (app/). It lives
ONLY here in the cloud backend, reachable only by the founder.

Surfaces (all behind ONE founder-only gate — `require_founder`):
  GET /founder                  → a single self-contained HTML dashboard
  GET /founder/api/overview     → headline JSON the page renders
  GET /founder/api/users        → user count + recent signups + by-plan
  GET /founder/api/subscriptions→ active subs by tier + estimated MRR
  GET /founder/api/system       → brain replica status, /healthz, version/build
  GET /founder/api/errors       → most-recent server errors (ring buffer)

Gating (critical — founder-only, no bypass):
  Every route depends on `require_founder`, which resolves the caller via the
  SAME bearer-token path as main._require_user (db.user_for_token), then allows
  ONLY the user whose email == FOUNDER_EMAIL (env, default
  'ahmedfargale@gmail.com'). Any other user → 403. Unauthenticated → 403.
  No anonymous access, no second auth path, no toggle.

Real data: every number is read live from db.py / config.py / billing.py and
the brain replica filesystem. No fake/placeholder numbers. Where Stripe live
data is not reachable offline, MRR is DERIVED from the stored plan rows × the
canonical tier prices in config.PLANS and is clearly labelled as an estimate.
"""
from __future__ import annotations

import os
import time
from collections import deque
from typing import Optional

from fastapi import APIRouter, Cookie, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

import config
import db

# Name of the cookie the browser carries to authenticate the founder. It holds
# the SAME bearer token the API uses; it is set HttpOnly + Secure + SameSite=Lax
# by POST /founder/login and read as an alternate token source by
# require_founder (so a plain browser navigation to /founder works).
FOUNDER_COOKIE = "founder_session"


# ---------------------------------------------------------------------------
# Founder identity (the gate)
# ---------------------------------------------------------------------------
# The single owner email. Read from env so it is never hard-pinned in a way
# the founder can't rotate, but defaults to the founder's address so the
# cockpit is gated correctly even before any env is set. Compared
# case-insensitively + trimmed, matching how db stores emails (lower-cased).
DEFAULT_FOUNDER_EMAIL = "ahmedfargale@gmail.com"


def founder_email() -> str:
    """The configured founder email, lower-cased + trimmed. Read at call
    time (not import time) so a test / deploy can set FOUNDER_EMAIL and have
    it take effect without re-importing the module."""
    return (os.environ.get("FOUNDER_EMAIL") or DEFAULT_FOUNDER_EMAIL).strip().lower()


def _bearer(authorization: Optional[str]) -> Optional[str]:
    """Extract the bearer token, or None if absent/malformed. Unlike
    main._bearer this returns None instead of raising 401 — the cockpit
    collapses 'no token' and 'wrong user' into the SAME 403 so the
    founder surface never reveals whether a token was even presented."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    parts = authorization.split(None, 1)
    if len(parts) != 2:
        return None
    return parts[1].strip()


def _founder_user_for_token(token: Optional[str]) -> Optional[dict]:
    """Resolve a token to the FOUNDER user, or None. The single, shared
    validation path used by BOTH the route gate (require_founder) and the
    cookie-login POST: db.user_for_token -> email == founder_email. Returns
    None for a missing/invalid token OR a valid token belonging to any
    non-founder user — the caller decides how to surface that (403 / re-render).
    """
    if not token:
        return None
    user = db.user_for_token(token)
    if user is None:
        return None
    email = (user.get("email") or "").strip().lower()
    if not email or email != founder_email():
        return None
    return user


def require_founder(
    request: Request,
    authorization: Optional[str] = Header(None),
    founder_session: Optional[str] = Cookie(None),
) -> dict:
    """FastAPI dependency: resolve the caller via the SAME token/me() path
    the rest of the API uses (db.user_for_token), then allow ONLY the
    founder. Everyone else — any other authenticated user, OR an
    unauthenticated caller — gets 403.

    The founder token may arrive via EITHER source, validated identically:
      - `Authorization: Bearer <token>` header (API clients, curl), OR
      - the `founder_session` cookie (a browser navigating to /founder),
        set by POST /founder/login.
    The header wins when both are present. There is no other bypass: a
    missing token, an invalid token, and a valid token for a non-founder
    user ALL resolve to 403 founder_only.
    """
    token = _bearer(authorization) or (founder_session or "").strip() or None
    user = _founder_user_for_token(token)
    if user is None:
        raise HTTPException(status_code=403, detail="founder_only")
    return user


# ---------------------------------------------------------------------------
# Error ring buffer
# ---------------------------------------------------------------------------
# A tiny in-process ring of the most-recent unhandled server errors. main.py's
# exception handler appends to it; the cockpit /founder/api/errors surfaces it.
# Bounded (default 100) so it can never grow without limit. In-process only —
# it resets on restart, which is the correct/honest behaviour for an ephemeral
# Fly container; it is a live tail, not an audit log.
_ERROR_RING: "deque[dict]" = deque(maxlen=100)


def record_error(*, where: str, kind: str, message: str,
                 status: Optional[int] = None) -> None:
    """Append one error event to the ring. Best-effort + defensive: never
    raises (an error in the error recorder must not mask the real error)."""
    try:
        _ERROR_RING.append({
            "ts":      int(time.time()),
            "where":   str(where)[:200],
            "kind":    str(kind)[:120],
            "message": str(message)[:500],
            "status":  int(status) if status is not None else None,
        })
    except Exception:
        pass


def recent_errors(limit: int = 50) -> list[dict]:
    """Most-recent errors, newest first."""
    items = list(_ERROR_RING)[-int(limit):]
    items.reverse()
    return items


def clear_errors() -> None:
    """Reset the ring (used by tests for isolation)."""
    _ERROR_RING.clear()


# ---------------------------------------------------------------------------
# Data builders (all read LIVE tables / config — no placeholders)
# ---------------------------------------------------------------------------
def _users_panel(recent_n: int = 12) -> dict:
    now = int(time.time())
    return {
        "total":          db.count_users(),
        "paid":           db.count_paid_users(),
        "by_plan":        db.count_users_by_plan(),
        "signups_24h":    db.count_users_since(now - 86400),
        "signups_7d":     db.count_users_since(now - 7 * 86400),
        "recent":         db.recent_users(recent_n),
    }


def _subscriptions_panel() -> dict:
    """Active subs by tier + estimated MRR.

    Two revenue streams, both from REAL stored rows:
      - Individual (Solo) plans live on users.plan.
      - Company plans (Studio / Firm) live on the companies table, each with a
        seat_limit — MRR = seats × per-seat price for that tier.

    Stripe live invoice data is not reachable from an offline box, so MRR is
    DERIVED from these stored rows × config.PLANS per-seat prices. It is
    labelled `mrr_estimate` + `basis: "derived_from_stored_plans"` so the
    founder reads it as an estimate, not a billed figure.
    """
    by_plan = db.count_users_by_plan()
    plans = config.PLANS
    tiers = []
    mrr = 0.0

    # Individual (Solo) seats — one user = one seat.
    solo_count = int(by_plan.get("solo", 0))
    if solo_count:
        price = float(plans["solo"]["price_per_seat"])
        amount = solo_count * price
        mrr += amount
        tiers.append({
            "tier": "solo", "name": plans["solo"]["name"],
            "source": "users", "subscribers": solo_count,
            "seats": solo_count, "price_per_seat": price,
            "mrr": round(amount, 2),
        })

    # Company tiers (Studio / Firm) — seat_limit × per-seat price.
    companies = db.list_companies_billing()
    company_tier_rollup: dict[str, dict] = {}
    for c in companies:
        tier = (c.get("plan") or "").strip().lower()
        if tier not in plans or not plans[tier].get("is_company"):
            continue
        seats = int(c.get("seat_limit") or plans[tier].get("default_seats") or 0)
        price = float(plans[tier]["price_per_seat"])
        roll = company_tier_rollup.setdefault(
            tier, {"subscribers": 0, "seats": 0, "mrr": 0.0,
                   "name": plans[tier]["name"], "price_per_seat": price})
        roll["subscribers"] += 1
        roll["seats"] += seats
        roll["mrr"] += seats * price
    for tier, roll in company_tier_rollup.items():
        mrr += roll["mrr"]
        tiers.append({
            "tier": tier, "name": roll["name"], "source": "companies",
            "subscribers": roll["subscribers"], "seats": roll["seats"],
            "price_per_seat": roll["price_per_seat"],
            "mrr": round(roll["mrr"], 2),
        })

    paying_subscribers = sum(t["subscribers"] for t in tiers)
    return {
        "tiers":          tiers,
        "mrr_estimate":   round(mrr, 2),
        "arr_estimate":   round(mrr * 12, 2),
        "currency":       "USD",
        "basis":          "derived_from_stored_plans",
        "note": ("MRR derived from stored plan rows x config.PLANS per-seat "
                 "prices (Stripe live data not queried). Estimate."),
        "paying_subscribers": paying_subscribers,
        "trial_users":    int(by_plan.get("trial", 0)),
        "companies":      db.count_companies(),
    }


def _replica_count() -> Optional[int]:
    """Count per-user brain replica dirs on disk. None if the root is
    unreadable (e.g. not yet created on a fresh box)."""
    try:
        import brain_replica
        root = brain_replica.DEFAULT_REPLICAS_ROOT
        if not root.exists():
            return 0
        return sum(1 for p in root.iterdir()
                   if p.is_dir() and (p / "brain.db").exists())
    except Exception:
        return None


def _system_panel() -> dict:
    """Brain replica status, health, version/build, deploy info."""
    version = "unknown"
    try:
        # Repo VERSION file lives at the repo root (two levels up from this
        # module: cloud_backend/ -> repo root). Falls back to the FastAPI
        # app version when not found.
        from pathlib import Path
        vf = Path(__file__).resolve().parent.parent / "VERSION"
        if vf.exists():
            version = vf.read_text(encoding="utf-8").strip()
    except Exception:
        pass

    return {
        "healthz":          {"ok": True, "ts": int(time.time())},
        "version":          version,
        "env":              os.environ.get("ENV", "").strip().lower() or "dev",
        "billing_provider": config.BILLING_PROVIDER,
        "public_url":       config.PUBLIC_URL,
        "fly": {
            "app":     os.environ.get("FLY_APP_NAME") or None,
            "region":  os.environ.get("FLY_REGION") or None,
            "machine": os.environ.get("FLY_MACHINE_ID") or None,
        },
        "brain_replicas": {
            "count": _replica_count(),
            "root":  str(getattr(__import__("brain_replica"),
                                 "DEFAULT_REPLICAS_ROOT", "")),
        },
        "stripe_configured": bool(config.stripe_price_id("solo")),
        "marketplace_packs": db.count_marketplace_packs(),
    }


def _usage_panel() -> dict:
    """Usage / progress: chat completions + memory captures (real counters)."""
    now = int(time.time())
    usage = db.usage_totals()
    training = db.training_totals()
    return {
        "chat_completions_total": usage["chat_completions"],
        "chat_completions_24h":   db.usage_calls_since(now - 86400),
        "input_tokens":           usage["input_tokens"],
        "output_tokens":          usage["output_tokens"],
        "spend_usd_estimate":     round(usage["cost_micros"] / 1_000_000.0, 4),
        "memory_captures_total":  training["total"],
        "memory_captures_24h":    training["today"],
        "memory_by_stage":        training["by_stage"],
    }


def build_overview() -> dict:
    """The single roll-up the dashboard page hydrates from."""
    return {
        "generated_at":  int(time.time()),
        "users":         _users_panel(),
        "subscriptions": _subscriptions_panel(),
        "system":        _system_panel(),
        "usage":         _usage_panel(),
        "errors":        recent_errors(20),
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
from fastapi import Depends

router = APIRouter(prefix="/founder", tags=["founder-cockpit"])


@router.get("/api/overview")
def api_overview(_founder: dict = Depends(require_founder)) -> JSONResponse:
    return JSONResponse(build_overview())


@router.get("/api/users")
def api_users(_founder: dict = Depends(require_founder)) -> JSONResponse:
    return JSONResponse(_users_panel())


@router.get("/api/subscriptions")
def api_subscriptions(_founder: dict = Depends(require_founder)) -> JSONResponse:
    return JSONResponse(_subscriptions_panel())


@router.get("/api/system")
def api_system(_founder: dict = Depends(require_founder)) -> JSONResponse:
    return JSONResponse(_system_panel())


@router.get("/api/usage")
def api_usage(_founder: dict = Depends(require_founder)) -> JSONResponse:
    return JSONResponse(_usage_panel())


@router.get("/api/errors")
def api_errors(_founder: dict = Depends(require_founder)) -> JSONResponse:
    return JSONResponse({"errors": recent_errors(50)})


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def cockpit_page(_founder: dict = Depends(require_founder)) -> HTMLResponse:
    """The single self-contained on-brand HTML dashboard. It hydrates from
    the /founder/api/* endpoints (which share this route's founder gate) and
    auto-refreshes every 30s. All styling is inline so the page has zero
    external dependencies."""
    return HTMLResponse(_PAGE_HTML)


# --- Cookie login (the ONLY ungated cockpit routes) ------------------------
# A browser navigating to /founder sends no Authorization header, so without a
# session it 403s. These two routes let the founder mint a `founder_session`
# cookie (validated through the SAME token->founder path as the gate) so the
# browser carries it on every subsequent /founder* request. The login page +
# its POST are deliberately UNGATED; everything else stays founder-gated.

@router.get("/login", response_class=HTMLResponse)
def login_page() -> HTMLResponse:
    """Ungated, on-brand sign-in page: one token field -> POST /founder/login."""
    return HTMLResponse(_login_html())


@router.post("/login")
def login_submit(token: str = Form(default="")) -> Response:
    """Validate the submitted token via the SAME path the gate uses
    (db.user_for_token -> email == founder_email). On success: set the
    HttpOnly + Secure + SameSite=Lax `founder_session` cookie and 303 to
    /founder. On failure: re-render the login page with a generic error
    (HTTP 401) and NEVER echo the token back."""
    token = (token or "").strip()
    if _founder_user_for_token(token) is None:
        return HTMLResponse(
            _login_html(error="That token is not valid for the founder account."),
            status_code=401,
        )
    resp = RedirectResponse(url="/founder", status_code=303)
    resp.set_cookie(
        key=FOUNDER_COOKIE,
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/founder",
        max_age=90 * 86400,  # mirrors the token's 90-day server-side lifetime
    )
    return resp


@router.get("/logout")
def logout() -> Response:
    """Clear the founder_session cookie and bounce to the login page."""
    resp = RedirectResponse(url="/founder/login", status_code=303)
    resp.delete_cookie(key=FOUNDER_COOKIE, path="/founder")
    return resp


# ---------------------------------------------------------------------------
# The page (on-brand: terracotta #d97757, Instrument Serif headings, Inter
# body, no emoji, cards + small tables, auto-refresh ~30s).
# ---------------------------------------------------------------------------
_PAGE_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="robots" content="noindex, nofollow" />
<title>ArchHub - Founder Cockpit</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root{
    --bg:#0f0f12; --panel:#16161b; --panel-2:#1c1c22; --line:#2a2a33;
    --ink:#ece8e0; --ink-dim:#a39e93; --ink-faint:#6f6a60;
    --terracotta:#d97757; --terracotta-soft:rgba(217,119,87,.14);
    --good:#5fa777; --warn:#d9a657; --bad:#d96757;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
    font-family:'Inter',system-ui,-apple-system,sans-serif;
    font-size:14px;line-height:1.5;-webkit-font-smoothing:antialiased;}
  a{color:var(--terracotta);text-decoration:none}
  .wrap{max-width:1140px;margin:0 auto;padding:40px 28px 80px}
  header{display:flex;align-items:baseline;justify-content:space-between;
    gap:16px;flex-wrap:wrap;margin-bottom:8px}
  h1{font-family:'Instrument Serif',Georgia,serif;font-weight:400;
    font-size:42px;letter-spacing:.3px;margin:0;line-height:1.05}
  h1 .sub{color:var(--terracotta)}
  .meta{color:var(--ink-faint);font-size:12.5px}
  .meta b{color:var(--ink-dim);font-weight:500}
  .grid{display:grid;gap:16px;margin-top:24px}
  .kpis{grid-template-columns:repeat(auto-fit,minmax(180px,1fr))}
  .cards{grid-template-columns:repeat(auto-fit,minmax(330px,1fr))}
  .card{background:var(--panel);border:1px solid var(--line);
    border-radius:14px;padding:20px 22px}
  .card h2{font-family:'Instrument Serif',Georgia,serif;font-weight:400;
    font-size:23px;margin:0 0 14px;letter-spacing:.2px}
  .kpi{background:var(--panel);border:1px solid var(--line);
    border-radius:14px;padding:18px 20px}
  .kpi .label{color:var(--ink-faint);font-size:11.5px;text-transform:uppercase;
    letter-spacing:.8px;margin-bottom:8px}
  .kpi .value{font-family:'Instrument Serif',Georgia,serif;font-size:36px;
    line-height:1;color:var(--ink)}
  .kpi .value.accent{color:var(--terracotta)}
  .kpi .delta{color:var(--ink-dim);font-size:12px;margin-top:8px}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th{text-align:left;color:var(--ink-faint);font-weight:500;font-size:11px;
    text-transform:uppercase;letter-spacing:.6px;padding:6px 8px;
    border-bottom:1px solid var(--line)}
  td{padding:7px 8px;border-bottom:1px solid var(--panel-2);color:var(--ink-dim)}
  td.ink{color:var(--ink)}
  tr:last-child td{border-bottom:none}
  .pill{display:inline-block;padding:1px 9px;border-radius:999px;font-size:11px;
    background:var(--terracotta-soft);color:var(--terracotta);
    border:1px solid rgba(217,119,87,.3)}
  .pill.trial{background:rgba(163,158,147,.12);color:var(--ink-dim);
    border-color:var(--line)}
  .row{display:flex;justify-content:space-between;padding:6px 0;
    border-bottom:1px solid var(--panel-2)}
  .row:last-child{border-bottom:none}
  .row .k{color:var(--ink-faint)}
  .row .v{color:var(--ink);font-variant-numeric:tabular-nums}
  .dot{display:inline-block;width:8px;height:8px;border-radius:50%;
    margin-right:7px;vertical-align:middle}
  .dot.good{background:var(--good)} .dot.warn{background:var(--warn)}
  .dot.bad{background:var(--bad)}
  .empty{color:var(--ink-faint);font-style:italic;padding:10px 2px}
  .note{color:var(--ink-faint);font-size:11.5px;margin-top:12px;line-height:1.45}
  .err{font-size:12.5px;padding:8px 0;border-bottom:1px solid var(--panel-2)}
  .err:last-child{border-bottom:none}
  .err .t{color:var(--ink-faint);font-size:11px}
  .err .m{color:var(--ink);margin-top:2px}
  .err .w{color:var(--terracotta)}
  .refresh{color:var(--ink-faint);font-size:12px}
  .span2{grid-column:span 2}
  @media(max-width:740px){.span2{grid-column:auto}h1{font-size:34px}}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Founder <span class="sub">Cockpit</span></h1>
    <div class="meta">
      <span class="refresh">auto-refresh 30s</span> &nbsp;|&nbsp;
      <b id="version">-</b> &nbsp;|&nbsp;
      <span id="env">-</span> &nbsp;|&nbsp;
      updated <b id="updated">-</b> &nbsp;|&nbsp;
      <a href="/founder/logout">Sign out</a>
    </div>
  </header>
  <p class="meta">Private business oversight. Live numbers from the cloud
    database, billing config, and the brain replica store.</p>

  <div class="grid kpis" id="kpis"></div>

  <div class="grid cards">
    <div class="card">
      <h2>Subscriptions &amp; revenue</h2>
      <div id="subs"></div>
    </div>
    <div class="card">
      <h2>Users by plan</h2>
      <div id="byplan"></div>
    </div>
    <div class="card span2">
      <h2>Recent signups</h2>
      <div id="recent"></div>
    </div>
    <div class="card">
      <h2>System</h2>
      <div id="system"></div>
    </div>
    <div class="card">
      <h2>Usage &amp; progress</h2>
      <div id="usage"></div>
    </div>
    <div class="card span2">
      <h2>Recent errors</h2>
      <div id="errors"></div>
    </div>
  </div>
</div>

<script>
const $ = (id) => document.getElementById(id);
const fmt = (n) => (n==null?'-':Number(n).toLocaleString('en-US'));
const money = (n) => (n==null?'-':'$'+Number(n).toLocaleString('en-US',{minimumFractionDigits:0,maximumFractionDigits:2}));
const ago = (ts) => {
  if(!ts) return '-';
  const s = Math.max(0, Math.floor(Date.now()/1000 - ts));
  if(s<60) return s+'s ago';
  if(s<3600) return Math.floor(s/60)+'m ago';
  if(s<86400) return Math.floor(s/3600)+'h ago';
  return Math.floor(s/86400)+'d ago';
};
const esc = (s) => String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

function kpi(label, value, accent, delta){
  return `<div class="kpi"><div class="label">${esc(label)}</div>`+
    `<div class="value${accent?' accent':''}">${value}</div>`+
    (delta?`<div class="delta">${esc(delta)}</div>`:'')+`</div>`;
}

function render(d){
  const u=d.users, s=d.subscriptions, sys=d.system, us=d.usage;
  $('version').textContent = sys.version;
  $('env').textContent = sys.env;
  $('updated').textContent = ago(d.generated_at);

  $('kpis').innerHTML =
    kpi('Total users', fmt(u.total), false, fmt(u.signups_24h)+' new in 24h')+
    kpi('Paying', fmt(s.paying_subscribers), false, fmt(s.trial_users)+' on trial')+
    kpi('MRR (est.)', money(s.mrr_estimate), true, 'ARR '+money(s.arr_estimate))+
    kpi('Chat completions', fmt(us.chat_completions_total), false, fmt(us.chat_completions_24h)+' in 24h')+
    kpi('Memory captures', fmt(us.memory_captures_total), false, fmt(us.memory_captures_24h)+' in 24h');

  // Subscriptions table
  if(s.tiers && s.tiers.length){
    let t='<table><thead><tr><th>Tier</th><th>Subs</th><th>Seats</th><th>MRR</th></tr></thead><tbody>';
    s.tiers.forEach(x=>{ t+=`<tr><td class="ink">${esc(x.name)}</td>`+
      `<td>${fmt(x.subscribers)}</td><td>${fmt(x.seats)}</td>`+
      `<td class="ink">${money(x.mrr)}</td></tr>`; });
    t+='</tbody></table>';
    t+=`<div class="row" style="margin-top:10px"><span class="k">MRR estimate</span><span class="v">${money(s.mrr_estimate)}</span></div>`;
    t+=`<div class="row"><span class="k">Companies</span><span class="v">${fmt(s.companies)}</span></div>`;
    t+=`<div class="note">${esc(s.note)}</div>`;
    $('subs').innerHTML=t;
  } else {
    $('subs').innerHTML='<div class="empty">No paid subscriptions yet.</div>'+
      `<div class="note">${esc(s.note)}</div>`;
  }

  // By plan
  const bp=u.by_plan||{}; const keys=Object.keys(bp);
  if(keys.length){
    let t='';
    keys.sort((a,b)=>bp[b]-bp[a]).forEach(k=>{
      t+=`<div class="row"><span class="k">${esc(k)}</span><span class="v">${fmt(bp[k])}</span></div>`; });
    $('byplan').innerHTML=t;
  } else { $('byplan').innerHTML='<div class="empty">No users yet.</div>'; }

  // Recent signups
  if(u.recent && u.recent.length){
    let t='<table><thead><tr><th>Email</th><th>Plan</th><th>Used</th><th>Joined</th></tr></thead><tbody>';
    u.recent.forEach(r=>{
      const trial = r.plan==='trial';
      t+=`<tr><td class="ink">${esc(r.email)}</td>`+
        `<td><span class="pill${trial?' trial':''}">${esc(r.plan)}</span></td>`+
        `<td>${fmt(r.msg_used)}/${fmt(r.msg_limit)}</td>`+
        `<td>${ago(r.created_at)}</td></tr>`; });
    t+='</tbody></table>';
    $('recent').innerHTML=t;
  } else { $('recent').innerHTML='<div class="empty">No signups yet.</div>'; }

  // System
  const fly=sys.fly||{}; const br=sys.brain_replicas||{};
  const health=sys.healthz&&sys.healthz.ok;
  $('system').innerHTML =
    `<div class="row"><span class="k">Health</span><span class="v"><span class="dot ${health?'good':'bad'}"></span>${health?'ok':'down'}</span></div>`+
    `<div class="row"><span class="k">Version / build</span><span class="v">${esc(sys.version)}</span></div>`+
    `<div class="row"><span class="k">Environment</span><span class="v">${esc(sys.env)}</span></div>`+
    `<div class="row"><span class="k">Billing provider</span><span class="v">${esc(sys.billing_provider)}</span></div>`+
    `<div class="row"><span class="k">Stripe configured</span><span class="v"><span class="dot ${sys.stripe_configured?'good':'warn'}"></span>${sys.stripe_configured?'yes':'no'}</span></div>`+
    `<div class="row"><span class="k">Brain replicas</span><span class="v">${br.count==null?'n/a':fmt(br.count)}</span></div>`+
    `<div class="row"><span class="k">Marketplace packs</span><span class="v">${fmt(sys.marketplace_packs)}</span></div>`+
    `<div class="row"><span class="k">Fly app</span><span class="v">${esc(fly.app||'local')}${fly.region?(' / '+esc(fly.region)):''}</span></div>`;

  // Usage
  const st=us.memory_by_stage||{};
  let stageStr=Object.keys(st).map(k=>`${esc(k)} ${fmt(st[k])}`).join(', ')||'none';
  $('usage').innerHTML =
    `<div class="row"><span class="k">Chat completions (all)</span><span class="v">${fmt(us.chat_completions_total)}</span></div>`+
    `<div class="row"><span class="k">Chat completions (24h)</span><span class="v">${fmt(us.chat_completions_24h)}</span></div>`+
    `<div class="row"><span class="k">Input tokens</span><span class="v">${fmt(us.input_tokens)}</span></div>`+
    `<div class="row"><span class="k">Output tokens</span><span class="v">${fmt(us.output_tokens)}</span></div>`+
    `<div class="row"><span class="k">Proxy spend (est.)</span><span class="v">${money(us.spend_usd_estimate)}</span></div>`+
    `<div class="row"><span class="k">Memory captures</span><span class="v">${fmt(us.memory_captures_total)}</span></div>`+
    `<div class="note">Capture stages: ${stageStr}</div>`;

  // Errors
  if(d.errors && d.errors.length){
    let t='';
    d.errors.forEach(e=>{
      t+=`<div class="err"><div class="t">${ago(e.ts)} &middot; <span class="w">${esc(e.where)}</span>${e.status?(' &middot; '+esc(e.status)):''}</div>`+
        `<div class="m">${esc(e.kind)}: ${esc(e.message)}</div></div>`; });
    $('errors').innerHTML=t;
  } else { $('errors').innerHTML='<div class="empty">No server errors recorded since last restart.</div>'; }
}

async function load(){
  try{
    const r = await fetch('/founder/api/overview', {headers:{'Accept':'application/json'}});
    if(!r.ok){ $('updated').textContent='auth error '+r.status; return; }
    render(await r.json());
  }catch(e){ $('updated').textContent='load error'; }
}
load();
setInterval(load, 30000);
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# The login page (ungated). On-brand: terracotta #d97757, Instrument Serif
# heading, Inter body, no emoji. One password-type token field that POSTs to
# /founder/login. Optional error banner (escaped; the token is NEVER echoed).
# ---------------------------------------------------------------------------
import html as _html

_LOGIN_HTML_TMPL = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="robots" content="noindex, nofollow" />
<title>ArchHub - Founder Sign in</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root{
    --bg:#0f0f12; --panel:#16161b; --line:#2a2a33;
    --ink:#ece8e0; --ink-dim:#a39e93; --ink-faint:#6f6a60;
    --terracotta:#d97757; --terracotta-soft:rgba(217,119,87,.14);
    --bad:#d96757;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
    font-family:'Inter',system-ui,-apple-system,sans-serif;
    font-size:14px;line-height:1.5;-webkit-font-smoothing:antialiased;
    min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:16px;
    padding:34px 32px;width:100%;max-width:420px}
  h1{font-family:'Instrument Serif',Georgia,serif;font-weight:400;
    font-size:36px;letter-spacing:.3px;margin:0 0 6px;line-height:1.05}
  h1 .sub{color:var(--terracotta)}
  p.help{color:var(--ink-dim);font-size:13px;margin:0 0 22px}
  label{display:block;color:var(--ink-faint);font-size:11.5px;
    text-transform:uppercase;letter-spacing:.8px;margin-bottom:8px}
  input[type=password]{width:100%;background:#0f0f12;border:1px solid var(--line);
    border-radius:10px;color:var(--ink);font-family:inherit;font-size:14px;
    padding:11px 13px;outline:none}
  input[type=password]:focus{border-color:var(--terracotta)}
  button{margin-top:16px;width:100%;background:var(--terracotta);color:#16110e;
    border:none;border-radius:10px;font-family:inherit;font-size:14px;
    font-weight:600;padding:11px 13px;cursor:pointer}
  button:hover{filter:brightness(1.05)}
  .err{background:rgba(217,103,87,.12);border:1px solid rgba(217,103,87,.35);
    color:#e7a99a;border-radius:10px;padding:10px 12px;font-size:13px;margin-bottom:18px}
  .foot{color:var(--ink-faint);font-size:11.5px;margin-top:18px;line-height:1.45}
</style>
</head>
<body>
  <form class="card" method="post" action="/founder/login" autocomplete="off">
    <h1>Founder <span class="sub">Cockpit</span></h1>
    <p class="help">Private business oversight. Sign in to continue.</p>
    {error_block}
    <label for="token">ArchHub token</label>
    <input id="token" name="token" type="password" autofocus
           autocomplete="off" spellcheck="false" />
    <button type="submit">Sign in</button>
    <div class="foot">Paste your ArchHub account token (Settings -&gt; Account).</div>
  </form>
</body>
</html>
"""


def _login_html(error: Optional[str] = None) -> str:
    """Render the login page. `error`, if given, is HTML-escaped and shown in a
    banner; the submitted token is never reflected back into the page."""
    block = (f'<div class="err">{_html.escape(error)}</div>') if error else ""
    return _LOGIN_HTML_TMPL.replace("{error_block}", block)
