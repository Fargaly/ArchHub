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

from fastapi import APIRouter, Body, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

import config
import db


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


def require_founder(authorization: Optional[str] = Header(None)) -> dict:
    """FastAPI dependency: resolve the caller via the SAME token/me() path
    the rest of the API uses (db.user_for_token), then allow ONLY the
    founder. Everyone else — any other authenticated user, OR an
    unauthenticated caller — gets 403.

    This is the one and only gate for every cockpit route. There is no
    bypass: a missing token, an invalid token, and a valid token for a
    non-founder user ALL resolve to 403 founder_only.
    """
    token = _bearer(authorization)
    if not token:
        raise HTTPException(status_code=403, detail="founder_only")
    user = db.user_for_token(token)
    if user is None:
        raise HTTPException(status_code=403, detail="founder_only")
    email = (user.get("email") or "").strip().lower()
    if not email or email != founder_email():
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


def _detect_action(text: str) -> str:
    t = (text or "").strip().lower()
    if not t:
        return "help"
    for action, pats in _INTENTS:
        for p in pats:
            if re.search(p, t):
                return action
    return "unknown"


def _extract_email(text: str) -> Optional[str]:
    m = re.search(r"[\w.+\-]+@[\w\-]+\.[\w.\-]+", text or "")
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
        return {"brain": "unreachable", "error": str(e)[:120]}


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
        eff = db.delete_test_users()
        result = {
            "action": "purge_test_users", "deleted": eff["deleted"],
            "emails": eff["emails"],
            "message": f"Deleted {eff['deleted']} test user(s).",
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
                result = {"action": "set_plan", "error": str(ve),
                          "message": f"Could not set plan: {ve}"}

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
    """Execute a typed founder instruction. Behind require_founder; destructive
    actions require {"confirm": true}. Returns the REAL effect, audited."""
    actor = (_founder.get("email") or "").strip().lower()
    text = str(payload.get("command") or payload.get("text") or "")
    confirm = bool(payload.get("confirm"))
    args = payload.get("args") if isinstance(payload.get("args"), dict) else None
    result = route_command(text, actor=actor, confirm=confirm, args=args)
    # 200 for executed/handled; the body carries ok + needs_confirm flags.
    return JSONResponse(result)


@router.post("/api/purge-test-users")
def api_purge_test_users(payload: dict = Body(default={}),
                         _founder: dict = Depends(require_founder)) -> JSONResponse:
    """Direct destructive route (also reachable as the 'purge test users'
    command). Requires {"confirm": true} or returns a preview with
    needs_confirm=true and HTTP 200 (nothing deleted)."""
    actor = (_founder.get("email") or "").strip().lower()
    confirm = bool(payload.get("confirm"))
    result = route_command("purge test users", actor=actor, confirm=confirm,
                           args={"action": "purge_test_users"})
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


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def cockpit_page(_founder: dict = Depends(require_founder)) -> HTMLResponse:
    """The single self-contained on-brand HTML dashboard. It hydrates from
    the /founder/api/* endpoints (which share this route's founder gate) and
    auto-refreshes every 30s. All styling is inline so the page has zero
    external dependencies."""
    return HTMLResponse(_PAGE_HTML)


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
  .cmd-out{margin-top:12px;font-size:13px;min-height:0}
  .cmd-out .ok{border:1px solid rgba(95,167,119,.4);background:rgba(95,167,119,.08);
    border-radius:11px;padding:12px 15px;color:var(--ink)}
  .cmd-out .bad{border:1px solid rgba(217,103,87,.45);background:rgba(217,103,87,.08);
    border-radius:11px;padding:12px 15px;color:var(--ink)}
  .cmd-out .confirm{border:1px solid rgba(217,166,87,.5);background:rgba(217,166,87,.1);
    border-radius:11px;padding:12px 15px;color:var(--ink)}
  .cmd-out pre{margin:8px 0 0;white-space:pre-wrap;color:var(--ink-dim);
    font-size:12px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
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
      updated <b id="updated">-</b>
    </div>
  </header>
  <p class="meta">Private business oversight + control. Live numbers from the
    cloud database, billing config, and the brain replica store. Type a command
    below to ACT — purge test users, set a plan, toggle the free tier, or direct
    an agent.</p>

  <div class="cmdbar">
    <input id="cmd" class="cmd-input" type="text" autocomplete="off"
      placeholder="e.g.  set someone@studio.com to studio   ·   purge test users   ·   build a Notion connector   ·   free default off" />
    <label class="cmd-confirm"><input type="checkbox" id="cmdConfirm" /> Confirm (destructive)</label>
    <button id="cmdRun" class="cmd-btn">Run</button>
  </div>
  <div id="cmdOut" class="cmd-out"></div>

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

async function runCommand(){
  const inp=$('cmd'), btn=$('cmdRun'), out=$('cmdOut');
  const command=inp.value.trim();
  if(!command){ return; }
  const confirm=$('cmdConfirm').checked;
  btn.disabled=true;
  out.innerHTML='<div class="ok">Running…</div>';
  try{
    const r=await fetch('/founder/api/command',{method:'POST',
      headers:{'Content-Type':'application/json','Accept':'application/json'},
      body:JSON.stringify({command, confirm})});
    const d=await r.json();
    let cls = d.needs_confirm ? 'confirm' : (d.ok ? 'ok' : 'bad');
    let body=`<div class="${cls}"><b>${esc(d.message||(d.ok?'Done.':'Failed.'))}</b>`+
      `<pre>${esc(JSON.stringify(d,null,2))}</pre></div>`;
    out.innerHTML=body;
    if(d.needs_confirm){ $('cmdConfirm').checked=true; }
    else if(d.ok){ inp.value=''; $('cmdConfirm').checked=false; }
    load(); loadActions();
  }catch(e){ out.innerHTML='<div class="bad">Command failed: '+esc(e)+'</div>'; }
  finally{ btn.disabled=false; }
}
$('cmdRun').addEventListener('click', runCommand);
$('cmd').addEventListener('keydown', (e)=>{ if(e.key==='Enter'){ runCommand(); }});

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
