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

import json
import os
import re
import time
from collections import deque
from typing import Optional

from fastapi import APIRouter, Body, Cookie, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel

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
    """Real user metrics — synthetic smoke-probe accounts EXCLUDED from every
    headline number, but surfaced honestly as a separate `test_seed` block so
    nothing is hidden (MAKE-IT-REAL: exclude from the real count, never drop).

    The pollution this fixes: scripts/reality_smoke.py historically registered
    reality+smoketest<ts>@archhub.io against the live DB on a 30-min cron, so
    `total` / `signups` / `by_plan` were inflated by hundreds of fake rows.
    Every number below is now the REAL business state; `test_seed.count` is how
    many synthetic rows were set aside.
    """
    now = int(time.time())
    test_total = db.count_test_users()
    return {
        # Real (test/seed accounts excluded) — the headline numbers.
        "total":          db.count_users(exclude_test=True),
        "paid":           db.count_paid_users(exclude_test=True),
        "by_plan":        db.count_users_by_plan(exclude_test=True),
        "signups_24h":    db.count_users_since(now - 86400, exclude_test=True),
        "signups_7d":     db.count_users_since(now - 7 * 86400,
                                               exclude_test=True),
        "recent":         db.recent_users(recent_n, exclude_test=True),
        # Honest disclosure of what was set aside (NOT hidden).
        "total_incl_test": db.count_users(),
        "test_seed": {
            "count":   test_total,
            "note":   ("Synthetic smoke-test / seed accounts (e.g. "
                       "reality+smoketest<ts>@archhub.io) excluded from the "
                       "numbers above. Purge from the cockpit when ready."),
        },
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
    # Real plan counts — synthetic smoke-probe rows excluded so MRR and the
    # trial-user headline are never inflated by fake signups.
    by_plan = db.count_users_by_plan(exclude_test=True)
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
    # Real usage — drop rows owned by synthetic test accounts so spend/token
    # totals reflect genuine customers only.
    usage = db.usage_totals(exclude_test=True)
    training = db.training_totals()
    return {
        "chat_completions_total": usage["chat_completions"],
        "chat_completions_24h":   db.usage_calls_since(now - 86400,
                                                       exclude_test=True),
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
# COMMAND ENGINE — the cockpit's real authority (PHASE 5)
# ---------------------------------------------------------------------------
# A typed founder instruction is parsed into ONE real action, executed against
# real state, and the REAL effect is returned + audited. This is what turns the
# cockpit from a read-only display into an actor. Every action below mutates
# real rows (db.py write paths) or directs a real agent (the agent_tasks queue
# the app-side self-extension loop drains). Destructive actions require
# {confirm: true}; everything is gated by require_founder and logged via
# db.log_founder_action.

# Each entry: (action_id, list of keyword regexes that route to it).
# Kept a small deterministic intent map for v1 (LLM NL routing is an optional
# upgrade — see route_command). First matching rule wins.
_INTENTS = [
    ("purge_test_users", [r"\bpurge\b.*\btest\b", r"\bdelete\b.*\btest user",
                          r"\bclean(up)?\b.*\btest\b"]),
    ("set_plan",         [r"\bset\b.*\bplan\b", r"\b(set|make|move|upgrade|downgrade)\b.*\bto\s+(trial|solo|studio|firm)\b",
                          r"\b(plan|tier)\b.*\b(trial|solo|studio|firm)\b"]),
    ("toggle_free",      [r"\bfree[\s_-]?default\b", r"\bfree tier\b", r"\bfree\b.*\b(on|off|enable|disable)\b"]),
    ("direct_agent",     [r"\b(build|extend|create|implement|make|add)\b",
                          r"\bself[\s_-]?extend\b", r"\bagent\b", r"\bbuild me\b"]),
    ("help",             [r"\bhelp\b", r"\bwhat can you do\b", r"\bcommands\b"]),
]

_PLANS = ("trial", "solo", "studio", "firm")

# Fixed, server-controlled vocabulary of set_plan failure codes. db.set_user_plan
# raises ValueError("<code>:<detail>") with one of these codes; we classify the
# exception to one of THESE LITERALS and put only the literal in the HTTP
# response — the raw exception text (which CodeQL treats as stack-trace
# information) is logged server-side, never echoed to the client.
_SET_PLAN_ERROR_CODES = ("no_such_user", "unknown_plan", "missing_user")


def _classify_set_plan_error(exc: Exception) -> str:
    """Map a set_plan ValueError to one of the FIXED _SET_PLAN_ERROR_CODES
    literals (or 'invalid' as the safe catch-all). The returned value is a
    constant from our own code, NOT a substring of str(exc), so no
    exception-derived text reaches the response body."""
    head = str(exc).split(":", 1)[0].strip()
    for code in _SET_PLAN_ERROR_CODES:
        if head == code:
            return code
    return "invalid"


def _detect_action(text: str) -> str:
    t = (text or "").strip().lower()
    if not t:
        return "help"
    for action, pats in _INTENTS:
        for p in pats:
            if re.search(p, t):
                return action
    return "unknown"


# Linear-time e-mail matcher. The previous pattern
# (r"[\w.+\-]+@[\w\-]+\.[\w.\-]+") had overlapping quantifiers around the dot
# (the trailing "\.[\w.\-]+" lets a '.' be claimed by either the literal or the
# class), which CodeQL flagged as polynomial ReDoS on uncontrolled command text.
# This rewrite removes the ambiguity: the domain is one-or-more dot-separated
# labels, each label a single bounded run of [A-Za-z0-9-] with NO dot inside it,
# so the engine never has two ways to partition a run of dots. Every quantifier
# is bounded; there is no nested/overlapping repetition → strictly linear.
_EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9\-]{1,63}(?:\.[A-Za-z0-9\-]{1,63}){1,8}"
)
# Hard cap on how much text we ever scan, so even a degenerate input can't make
# the matcher (or anything downstream) chew through an unbounded string.
_EMAIL_SCAN_CAP = 2048


def _extract_email(text: str) -> Optional[str]:
    m = _EMAIL_RE.search((text or "")[:_EMAIL_SCAN_CAP])
    return m.group(0) if m else None


def _extract_plan(text: str) -> Optional[str]:
    t = (text or "").lower()
    for p in _PLANS:
        if re.search(rf"\b{p}\b", t):
            return p
    return None


def _extract_onoff(text: str) -> Optional[bool]:
    t = (text or "").lower()
    if re.search(r"\b(off|disable|disabled|false|no)\b", t):
        return False
    if re.search(r"\b(on|enable|enabled|true|yes)\b", t):
        return True
    return None


HELP_TEXT = (
    "Founder commands — type any of these:\n"
    "  purge test users            (destructive — needs Confirm)\n"
    "  set <email> to studio       (plans: trial | solo | studio | firm)\n"
    "  free default off            (toggle the zero-config free tier on/off)\n"
    "  build <something>           (directs an agent: queues a self-extension task)\n"
    "  help"
)


def _try_brain_self_extend(directive: str) -> Optional[dict]:
    """Best-effort: also fire the brain's ROMA self-extension loop if the
    daemon is reachable, so a 'build' command can kick REAL agent work beyond
    the durable queue row. Never blocks / never raises — the queued task row is
    the guaranteed effect; this is an extra real trigger when the brain is up.
    Returns a small status dict or None when unreachable."""
    url = os.environ.get("BRAIN_MCP_URL", "http://127.0.0.1:8473/mcp")
    try:
        import urllib.request
        payload = json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "brain.roma_atomize",
                       "arguments": {"vision": directive}},
        }).encode()
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json",
                     "Accept": "application/json, text/event-stream"})
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            return {"brain": "triggered", "status": resp.status}
    except Exception as e:
        # Log the real reason server-side; return only a fixed status string to
        # the caller (which surfaces it in the HTTP response) so no
        # exception-derived text is exposed (CodeQL py/stack-trace-exposure).
        record_error(where="founder._try_brain_self_extend",
                     kind=type(e).__name__, message=str(e))
        return {"brain": "unreachable"}


def route_command(text: str, *, actor: str, confirm: bool = False,
                  args: Optional[dict] = None) -> dict:
    """Parse + EXECUTE one founder instruction. Returns the REAL effect.

    actor   = founder email (already gated by require_founder upstream).
    confirm = required True for destructive actions.
    args    = optional explicit structured args (email/plan/value/directive)
              that override what the parser extracts from free text.
    """
    args = args or {}
    text = (text or "").strip()
    action = (args.get("action") or _detect_action(text)).strip().lower()
    target: Optional[str] = None
    result: dict
    ok = True

    if action == "help":
        result = {"action": "help", "message": HELP_TEXT}

    elif action == "purge_test_users":
        target = "test_users"
        if not confirm:
            preview = db.list_test_users()
            result = {
                "action": "purge_test_users",
                "needs_confirm": True,
                "would_delete": len(preview),
                "emails": [p["email"] for p in preview],
                "message": (f"This will permanently delete {len(preview)} test "
                            f"user(s). Re-run with Confirm to proceed."),
            }
            ok = True
            # Do NOT log a no-op preview as an action effect, but record intent.
            db.log_founder_action(
                actor=actor, command=text, action="purge_test_users.preview",
                target=target, result=json.dumps({"would_delete": len(preview)}),
                ok=True)
            return result
        # delete_test_users() returns the int row-count; capture the emails
        # from the preview list BEFORE deleting so the report still names them.
        victims = db.list_test_users()
        emails = [v["email"] for v in victims]
        deleted = db.delete_test_users()
        result = {
            "action": "purge_test_users", "deleted": deleted,
            "emails": emails,
            "message": f"Deleted {deleted} test user(s).",
        }

    elif action == "set_plan":
        email = (args.get("email") or _extract_email(text))
        plan = (args.get("plan") or _extract_plan(text))
        target = email
        if not email or not plan:
            ok = False
            result = {"action": "set_plan", "error": "need_email_and_plan",
                      "message": ("Usage: set <email> to <trial|solo|studio|firm>. "
                                  f"Got email={email!r} plan={plan!r}.")}
        else:
            try:
                eff = db.set_user_plan(email, plan)
                result = {"action": "set_plan", **eff,
                          "message": f"Set {eff['email']} to plan '{eff['plan']}'."}
            except ValueError as ve:
                ok = False
                # Classify to a FIXED code literal; never echo str(ve) (the
                # exception text) into the response — log the detail server-side
                # only (CodeQL py/stack-trace-exposure).
                code = _classify_set_plan_error(ve)
                record_error(where="founder.route_command.set_plan",
                             kind="ValueError", message=str(ve))
                _GENERIC_SET_PLAN_MSG = {
                    "no_such_user": "No user with that email.",
                    "unknown_plan": "Unknown plan (use trial|solo|studio|firm).",
                    "missing_user": "An email is required.",
                    "invalid":      "Could not set plan (invalid request).",
                }
                result = {"action": "set_plan", "error": code,
                          "message": _GENERIC_SET_PLAN_MSG[code]}

    elif action == "toggle_free":
        val = args.get("value")
        if val is None:
            val = _extract_onoff(text)
        if val is None:
            ok = False
            result = {"action": "toggle_free", "error": "need_on_or_off",
                      "message": "Say 'free default on' or 'free default off'."}
        else:
            target = "free_default"
            eff = db.set_founder_flag(
                "free_default", "1" if val else "0", actor=actor)
            # Reflect the real downstream effect on serving.
            available = False
            try:
                available = bool(config.free_default_available())
            except Exception:
                pass
            result = {"action": "toggle_free", "free_default": bool(val),
                      "flag": eff,
                      "serving_free_now": available,
                      "message": (f"Free default turned {'ON' if val else 'OFF'}. "
                                  f"Serving free now: {available}.")}

    elif action == "direct_agent":
        directive = (args.get("directive") or text).strip()
        if not directive:
            ok = False
            result = {"action": "direct_agent", "error": "empty_directive",
                      "message": "Tell the agent what to build."}
        else:
            task = db.enqueue_agent_task(
                directive=directive, created_by=actor,
                kind=(args.get("kind") or "self_extend"))
            target = task["id"]
            brain = _try_brain_self_extend(directive)
            result = {"action": "direct_agent", "task": task,
                      "queued": True, "task_id": task["id"],
                      "brain": brain,
                      "message": (f"Queued agent task {task['id']} "
                                  f"(status={task['status']}). The self-extension "
                                  f"loop will pick it up.")}

    else:  # unknown
        ok = False
        result = {"action": "unknown",
                  "message": ("I didn't recognise that command. Type 'help' "
                              "for the list."),
                  "help": HELP_TEXT}

    # Audit every executed command (success or handled failure).
    db.log_founder_action(
        actor=actor, command=text, action=result.get("action", action),
        target=target, result=json.dumps(result)[:2000], ok=ok)
    result["ok"] = ok
    return result


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


# --- ACTION routes (real authority) ----------------------------------------
@router.post("/api/command")
def api_command(payload: dict = Body(default={}),
                _founder: dict = Depends(require_founder)) -> JSONResponse:
    """Execute a founder instruction through the AGENT LOOP (reason -> tool ->
    observe), behind the unchanged require_founder gate.

    Flow:
      * A `pending` write the founder has confirmed ({confirm:true, pending:
        {tool,args}}) is executed directly via cockpit_agent.confirm_pending
        (the second half of the preview->confirm protocol) + audited.
      * Otherwise the natural-language command runs the agent loop: READ tools
        execute immediately, a gated WRITE returns a preview card
        (needs_confirm) the UI confirms.
      * If NO model key is reachable OR the model errors, we FALL BACK to the
        deterministic keyword router route_command (the offline fallback) —
        the cockpit always works, model or not.
    """
    actor = (_founder.get("email") or "").strip().lower()
    text = str(payload.get("command") or payload.get("text") or "")
    confirm = bool(payload.get("confirm"))
    args = payload.get("args") if isinstance(payload.get("args"), dict) else None
    history = payload.get("history") if isinstance(payload.get("history"),
                                                   list) else None
    pending = payload.get("pending") if isinstance(payload.get("pending"),
                                                   dict) else None

    import cockpit_agent

    # (1) Confirmed gated write from the agent path: execute + audit directly.
    if confirm and pending and pending.get("tool") in cockpit_agent.TOOLS:
        result = cockpit_agent.confirm_pending(
            actor=actor, tool=pending["tool"],
            args=pending.get("args") or {}, command=text)
        result.setdefault("mode", "agent")
        return JSONResponse(result)

    # (2) Explicit structured args OR a confirmed keyword action (e.g. the
    #     legacy 'purge test users' confirm) → keep the deterministic router.
    if args is not None or (confirm and not pending):
        result = route_command(text, actor=actor, confirm=confirm, args=args)
        result.setdefault("mode", "keyword")
        return JSONResponse(result)

    # (3) Natural-language → AGENT LOOP, with keyword router as offline fallback.
    try:
        result = cockpit_agent.agent_command(text, actor=actor,
                                             history=history)
        result.setdefault("mode", "agent")
        return JSONResponse(result)
    except cockpit_agent.ModelError:
        result = route_command(text, actor=actor, confirm=confirm, args=args)
        result.setdefault("mode", "keyword_fallback")
        return JSONResponse(result)


@router.get("/api/actions")
def api_actions(_founder: dict = Depends(require_founder)) -> JSONResponse:
    """The founder action audit log (most recent first)."""
    return JSONResponse({"actions": db.recent_founder_actions(40)})


@router.get("/api/agent-tasks")
def api_agent_tasks(_founder: dict = Depends(require_founder)) -> JSONResponse:
    """The agent task queue the cockpit fills + the app-side loop drains."""
    return JSONResponse({
        "tasks": db.list_agent_tasks(40),
        "queued": db.count_agent_tasks("queued"),
        "total": db.count_agent_tasks(),
    })


# --- Test-account purge (founder-gated, confirm-required) -------------------
class PurgeTestUsersReq(BaseModel):
    """Body for POST /founder/api/purge-test-users. `confirm` MUST be true —
    an unconfirmed call is a dry-run that reports the count WITHOUT deleting,
    so the founder can see exactly how many rows would go before committing."""
    confirm: bool = False


@router.post("/api/purge-test-users")
def api_purge_test_users(
    body: PurgeTestUsersReq = Body(default_factory=PurgeTestUsersReq),
    _founder: dict = Depends(require_founder),
) -> JSONResponse:
    """DELETE every synthetic test/seed account (rows matching
    db.is_test_account_email) — the one-click cleanup for the polluted
    production users table. Also reachable as the 'purge test users' command
    (which additionally writes the founder_action_log audit row).

    Two locks, both required:
      1. FOUNDER GATE — `require_founder` (same as every cockpit route): only
         the founder email passes; everyone else (incl. unauthenticated) → 403.
      2. EXPLICIT CONFIRM — the body must carry {"confirm": true}. Without it
         the call is a safe DRY-RUN: it reports the count that WOULD be deleted
         and deletes nothing, so the destructive action can never fire by
         accident.

    The response carries BOTH naming conventions the cockpit surfaces use, so
    the same endpoint serves the dashboard widget and the command alias:
      confirm=false → {"dry_run": true, "needs_confirm": true,
                       "would_purge": N, "would_delete": N, "purged": 0,
                       "emails": [...]}
      confirm=true  → {"dry_run": false, "purged": N, "deleted": N,
                       "remaining_test": 0, "emails": [...]}
    """
    if not body.confirm:
        preview = db.list_test_users()
        n = len(preview)
        return JSONResponse({
            "dry_run":       True,
            "needs_confirm": True,
            "would_purge":   n,
            "would_delete":  n,
            "purged":        0,
            "emails":        [p["email"] for p in preview],
            "note":          "confirm:true required to actually delete.",
        })
    victims = db.list_test_users()
    emails = [v["email"] for v in victims]
    purged = db.delete_test_users()
    return JSONResponse({
        "dry_run":        False,
        "purged":         purged,
        "deleted":        purged,
        "emails":         emails,
        "remaining_test": db.count_test_users(),
    })


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
    (db.user_for_token -> email == founder_email). On success: MINT A FRESH
    server-issued session token for the validated founder user and set THAT as
    the HttpOnly + Secure + SameSite=Lax `founder_session` cookie, then 303 to
    /founder. On failure: re-render the login page with a generic error
    (HTTP 401) and NEVER echo the token back.

    Security (CodeQL py/cookie-injection): the cookie value is NEVER the raw
    user-supplied `token` form field. We validate that field, then call
    db.issue_token(user.id) to generate a brand-new server-controlled token
    (`secrets.token_urlsafe`) and store only that in the cookie. The supplied
    token is used solely to authenticate the request, not to build the cookie,
    so no user-supplied input reaches Set-Cookie."""
    token = (token or "").strip()
    user = _founder_user_for_token(token)
    if user is None:
        return HTMLResponse(
            _login_html(error="That token is not valid for the founder account."),
            status_code=401,
        )
    # Server-controlled session token (NOT the submitted form value) → cookie.
    session_token = db.issue_token(user["id"])
    resp = RedirectResponse(url="/founder", status_code=303)
    resp.set_cookie(
        key=FOUNDER_COOKIE,
        value=session_token,
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
  .btn{background:var(--terracotta-soft);color:var(--terracotta);
    border:1px solid rgba(217,119,87,.4);border-radius:8px;
    padding:6px 12px;font-size:12.5px;font-family:inherit;cursor:pointer}
  .btn:hover{background:rgba(217,119,87,.22)}
  .btn:disabled{opacity:.5;cursor:default}
  .note{color:var(--ink-faint);font-size:11.5px;margin-top:12px;line-height:1.45}
  .err{font-size:12.5px;padding:8px 0;border-bottom:1px solid var(--panel-2)}
  .err:last-child{border-bottom:none}
  .err .t{color:var(--ink-faint);font-size:11px}
  .err .m{color:var(--ink);margin-top:2px}
  .err .w{color:var(--terracotta)}
  .refresh{color:var(--ink-faint);font-size:12px}
  .span2{grid-column:span 2}
  .cmdbar{display:flex;gap:10px;align-items:center;margin-top:22px;flex-wrap:wrap}
  .cmd-input{flex:1;min-width:280px;background:var(--panel-2);
    border:1px solid var(--line);border-radius:11px;color:var(--ink);
    font-family:'Inter',sans-serif;font-size:14px;padding:13px 15px;outline:none}
  .cmd-input:focus{border-color:var(--terracotta)}
  .cmd-input::placeholder{color:var(--ink-faint)}
  .cmd-confirm{color:var(--ink-dim);font-size:12.5px;display:flex;
    align-items:center;gap:6px;white-space:nowrap;cursor:pointer}
  .cmd-btn{background:var(--terracotta);color:#fff;border:none;
    border-radius:11px;font-family:'Inter',sans-serif;font-weight:600;
    font-size:14px;padding:13px 26px;cursor:pointer}
  .cmd-btn:disabled{opacity:.5;cursor:default}
  /* Chat transcript (scrolling) */
  .chat{margin-top:14px;border:1px solid var(--line);border-radius:14px;
    background:var(--panel);max-height:430px;overflow-y:auto;padding:14px 16px;
    display:flex;flex-direction:column;gap:12px}
  .chat:empty{display:none}
  .turn{display:flex;flex-direction:column;gap:4px;max-width:88%}
  .turn.me{align-self:flex-end;align-items:flex-end}
  .turn.agent{align-self:flex-start;align-items:flex-start}
  .turn .who{font-size:10.5px;text-transform:uppercase;letter-spacing:.7px;
    color:var(--ink-faint)}
  .bubble{border-radius:12px;padding:10px 14px;font-size:13.5px;line-height:1.5;
    white-space:pre-wrap;word-break:break-word}
  .turn.me .bubble{background:var(--terracotta-soft);color:var(--ink);
    border:1px solid rgba(217,119,87,.3)}
  .turn.agent .bubble{background:var(--panel-2);color:var(--ink);
    border:1px solid var(--line)}
  .turn.agent .bubble.bad{border-color:rgba(217,103,87,.45);
    background:rgba(217,103,87,.08)}
  .turn .model{font-size:10.5px;color:var(--ink-faint);margin-top:2px}
  /* Inline confirm card */
  .confirm-card{border:1px solid rgba(217,166,87,.5);background:rgba(217,166,87,.1);
    border-radius:12px;padding:13px 15px;font-size:13px;color:var(--ink);
    align-self:flex-start;max-width:88%}
  .confirm-card h3{margin:0 0 8px;font-family:'Instrument Serif',Georgia,serif;
    font-weight:400;font-size:18px;color:var(--warn)}
  .confirm-card .target{color:var(--ink);font-size:13px;margin:2px 0}
  .confirm-card .target b{color:var(--terracotta)}
  .confirm-card pre{margin:8px 0;white-space:pre-wrap;color:var(--ink-dim);
    font-size:12px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
  .confirm-card .acts{display:flex;gap:8px;margin-top:10px}
  .confirm-card .acts button{font-family:inherit;font-size:12.5px;font-weight:600;
    border-radius:8px;padding:7px 16px;cursor:pointer;border:none}
  .confirm-card .yes{background:var(--terracotta);color:#fff}
  .confirm-card .no{background:transparent;color:var(--ink-dim);
    border:1px solid var(--line)}
  .typing{color:var(--ink-faint);font-style:italic;font-size:12.5px;
    align-self:flex-start}
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
  <p class="meta">Private business oversight + control. Live numbers from the
    cloud database, billing config, and the brain replica store. Type a command
    below to ACT — purge test users, set a plan, toggle the free tier, or direct
    an agent.</p>

  <div id="chat" class="chat"></div>
  <div class="cmdbar">
    <input id="cmd" class="cmd-input" type="text" autocomplete="off"
      placeholder="Ask or instruct…  e.g.  how many users on studio?   ·   set someone@studio.com to studio   ·   grant 500 credits to x@y.com   ·   free default off" />
    <label class="cmd-confirm"><input type="checkbox" id="cmdConfirm" /> Confirm (destructive)</label>
    <button id="cmdRun" class="cmd-btn">Send</button>
  </div>

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
    <div class="card">
      <h2>Agent tasks</h2>
      <div id="agentTasks"></div>
    </div>
    <div class="card">
      <h2>Recent commands</h2>
      <div id="actions"></div>
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

  const testN = (u.test_seed && u.test_seed.count) || 0;
  const usersDelta = fmt(u.signups_24h)+' new in 24h'+
    (testN ? ' · '+fmt(testN)+' test/seed excluded' : '');
  $('kpis').innerHTML =
    kpi('Total users (real)', fmt(u.total), false, usersDelta)+
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

  // By plan (real users only)
  const bp=u.by_plan||{}; const keys=Object.keys(bp);
  let t='';
  if(keys.length){
    keys.sort((a,b)=>bp[b]-bp[a]).forEach(k=>{
      t+=`<div class="row"><span class="k">${esc(k)}</span><span class="v">${fmt(bp[k])}</span></div>`; });
  } else { t='<div class="empty">No real users yet.</div>'; }
  // Honest test/seed disclosure + one-click purge (founder-gated endpoint).
  t+=`<div class="row" style="margin-top:8px"><span class="k">test/seed (excluded)</span>`+
     `<span class="v">${fmt(testN)}</span></div>`;
  if(testN){
    t+=`<div style="margin-top:10px"><button id="purgeBtn" class="btn">Purge ${fmt(testN)} test accounts</button>`+
       `<span id="purgeMsg" class="note"></span></div>`;
  }
  $('byplan').innerHTML=t;
  const pb=$('purgeBtn');
  if(pb){ pb.onclick=()=>purgeTest(testN); }

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

function renderActions(d){
  const a=d.actions||[];
  if(!a.length){ $('actions').innerHTML='<div class="empty">No commands run yet.</div>'; return; }
  let t='';
  a.forEach(x=>{
    t+=`<div class="err"><div class="t">${ago(x.ts)} &middot; <span class="w">${esc(x.action)}</span>${x.target?(' &middot; '+esc(x.target)):''} &middot; ${x.ok?'ok':'fail'}</div>`+
       `<div class="m">${esc(x.command)}</div></div>`; });
  $('actions').innerHTML=t;
}
function renderAgentTasks(d){
  const a=d.tasks||[];
  let head=`<div class="row"><span class="k">Queued</span><span class="v">${fmt(d.queued)}</span></div>`+
           `<div class="row"><span class="k">Total</span><span class="v">${fmt(d.total)}</span></div>`;
  if(!a.length){ $('agentTasks').innerHTML=head+'<div class="empty">No agent tasks queued.</div>'; return; }
  let t=head;
  a.slice(0,8).forEach(x=>{
    t+=`<div class="err"><div class="t">${ago(x.created_at)} &middot; <span class="w">${esc(x.status)}</span> &middot; ${esc(x.kind)}</div>`+
       `<div class="m">${esc(x.directive)}</div></div>`; });
  $('agentTasks').innerHTML=t;
}
async function loadActions(){
  try{
    const [ra,rt] = await Promise.all([
      fetch('/founder/api/actions',{headers:{'Accept':'application/json'}}),
      fetch('/founder/api/agent-tasks',{headers:{'Accept':'application/json'}})]);
    if(ra.ok) renderActions(await ra.json());
    if(rt.ok) renderAgentTasks(await rt.json());
  }catch(e){}
}

// --- Chat transcript (founder turn + agent answer + inline confirm cards) --
const CHAT_HISTORY=[];   // {role, content} pairs sent back for context
function chatScroll(){ const c=$('chat'); c.scrollTop=c.scrollHeight; }
function addTurn(role, text, model){
  const c=$('chat');
  const div=document.createElement('div');
  div.className='turn '+(role==='me'?'me':'agent');
  const bad=(role==='agent' && model==='__bad__');
  div.innerHTML=`<div class="who">${role==='me'?'You':'Agent'}</div>`+
    `<div class="bubble${bad?' bad':''}">${esc(text)}</div>`+
    (model && model!=='__bad__'?`<div class="model">${esc(model)}</div>`:'');
  c.appendChild(div); chatScroll();
  return div;
}
function addTyping(){
  const c=$('chat');
  const d=document.createElement('div');
  d.className='typing'; d.id='typing'; d.textContent='Agent is thinking…';
  c.appendChild(d); chatScroll();
}
function clearTyping(){ const t=$('typing'); if(t) t.remove(); }

function addConfirmCard(d){
  const c=$('chat');
  const pv=d.preview||{}; const tgt=pv.target||{}; const chg=pv.change||{};
  const card=document.createElement('div');
  card.className='confirm-card';
  let tgtStr=Object.keys(tgt).map(k=>`${esc(k)}: <b>${esc(tgt[k])}</b>`).join(' · ');
  card.innerHTML=`<h3>Confirm: ${esc(d.action)}</h3>`+
    `<div class="target">${tgtStr||'—'}</div>`+
    `<pre>${esc(JSON.stringify(chg,null,2))}</pre>`+
    `<div class="acts"><button class="yes">Confirm &amp; apply</button>`+
    `<button class="no">Cancel</button></div>`;
  c.appendChild(card); chatScroll();
  card.querySelector('.yes').onclick=async()=>{
    card.querySelector('.acts').innerHTML='<span class="model">applying…</span>';
    try{
      const r=await fetch('/founder/api/command',{method:'POST',
        headers:{'Content-Type':'application/json','Accept':'application/json'},
        body:JSON.stringify({command:d.message||'', confirm:true,
                             pending:d.pending})});
      const res=await r.json();
      card.remove();
      addTurn('agent', res.message||(res.ok?'Done.':'Failed.'),
              res.ok?null:'__bad__');
      load(); loadActions();
    }catch(e){ addTurn('agent','Apply failed: '+e,'__bad__'); }
  };
  card.querySelector('.no').onclick=()=>{ card.remove();
    addTurn('agent','Cancelled — nothing was changed.'); };
}

async function runCommand(){
  const inp=$('cmd'), btn=$('cmdRun');
  const command=inp.value.trim();
  if(!command){ return; }
  const confirm=$('cmdConfirm').checked;
  addTurn('me', command);
  CHAT_HISTORY.push({role:'user', content:command});
  inp.value=''; btn.disabled=true; addTyping();
  try{
    const r=await fetch('/founder/api/command',{method:'POST',
      headers:{'Content-Type':'application/json','Accept':'application/json'},
      body:JSON.stringify({command, confirm, history:CHAT_HISTORY.slice(-8)})});
    const d=await r.json();
    clearTyping();
    if(d.needs_confirm){
      addTurn('agent', d.message||'Please confirm this change.',
              d.model||null);
      addConfirmCard(d);
    } else {
      addTurn('agent', d.message||(d.ok?'Done.':'Failed.'),
              d.ok?(d.model||null):'__bad__');
      CHAT_HISTORY.push({role:'assistant', content:d.message||''});
    }
    $('cmdConfirm').checked=false;
    load(); loadActions();
  }catch(e){ clearTyping(); addTurn('agent','Command failed: '+e,'__bad__'); }
  finally{ btn.disabled=false; }
}
$('cmdRun').addEventListener('click', runCommand);
$('cmd').addEventListener('keydown', (e)=>{ if(e.key==='Enter'){ runCommand(); }});

async function purgeTest(n){
  const msg=$('purgeMsg'); const btn=$('purgeBtn');
  if(!window.confirm('Permanently delete '+n+' synthetic test/seed accounts '+
    '(reality+smoketest@archhub.io etc.)? Real users are never touched.')) return;
  if(btn){ btn.disabled=true; btn.textContent='Purging...'; }
  try{
    const r=await fetch('/founder/api/purge-test-users',{
      method:'POST',
      headers:{'Content-Type':'application/json','Accept':'application/json'},
      body:JSON.stringify({confirm:true})});
    const j=await r.json();
    if(r.ok){ if(msg) msg.textContent=' purged '+fmt(j.purged)+'.'; load(); }
    else { if(msg) msg.textContent=' error '+r.status; if(btn) btn.disabled=false; }
  }catch(e){ if(msg) msg.textContent=' request failed'; if(btn) btn.disabled=false; }
}

async function load(){
  try{
    const r = await fetch('/founder/api/overview', {headers:{'Accept':'application/json'}});
    if(!r.ok){ $('updated').textContent='auth error '+r.status; return; }
    render(await r.json());
  }catch(e){ $('updated').textContent='load error'; }
}
load(); loadActions();
setInterval(()=>{ load(); loadActions(); }, 30000);
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
