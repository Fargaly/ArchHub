"""Founder Cockpit — PRIVATE founder-only admin dashboard (PHASE 5).

This is the surface the FOUNDER uses to oversee the ArchHub business. It is
NOT a user feature and it does NOT live in the desktop app (app/). It lives
ONLY here in the cloud backend, reachable only by the founder.

Surfaces (all behind ONE founder-only gate — `require_founder`):
  GET /founder                  → the admin panel (cockpit_assets/admin.html)
  GET /founder/map              → the system graph the founder's app publishes
  GET /founder/api/inbox        → everything waiting on the founder, one list
  GET /founder/api/overview     → headline JSON the status strip renders
  GET /founder/api/users        → user count + recent signups + by-plan
  GET /founder/api/subscriptions→ active subs by tier + estimated MRR
  GET /founder/api/system       → brain replica status, /healthz, version/build
  GET /founder/api/errors       → most-recent server errors (ring buffer)

Gating (critical — founder-only, no bypass):
  Every route depends on `require_founder`, which resolves the caller via the
  SAME bearer-token path as main._require_user (db.user_for_token), then allows
  ONLY a user whose email is one of config.founder_emails() (env
  the FOUNDER_EMAIL deployment secret; unset admits nobody). Any other
  user → 403. Unauthenticated → 403.
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

from urllib.parse import quote as _urlquote

from datetime import datetime, timezone

from fastapi import APIRouter, Body, Cookie, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel

from pathlib import Path

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
# Admission uses config.founder_emails(): the FOUNDER_EMAIL deployment
# secret is the only source; no address lives in code.


def founder_email() -> str:
    """The configured founder email, lower-cased + trimmed. Read at call
    time (not import time) so a test / deploy can set FOUNDER_EMAIL and have
    it take effect without re-importing the module."""
    owners = sorted(config.founder_emails())
    return owners[0] if owners else ""


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
    if not email or email not in config.founder_emails():
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
        # A browser that navigated here without a session is sent to sign in;
        # an API client keeps the exact 403. The founder opened
        # api.archhub.io/founder in a fresh browser and read {"detail":
        # "founder_only"} (2026-09-05) -- that is a door, not a wall.
        accept = str(request.headers.get("accept") or "")
        if "text/html" in accept and authorization is None and request.method == "GET":
            from urllib.parse import quote
            raise HTTPException(
                status_code=307,
                headers={"Location": "/founder/login?next=" + quote(str(request.url.path))},
                detail="sign in",
            )
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
    try:
        # Kept across restarts; the ring above only answers when the db cannot.
        db.log_cockpit_error(at=str(where)[:200], kind=str(kind)[:120],
                             message=str(message)[:500],
                             status=int(status) if status is not None else None)
    except Exception:
        pass


def recent_errors(limit: int = 50) -> list[dict]:
    """Most-recent errors, newest first: the durable log, else the ring."""
    try:
        return db.recent_cockpit_errors(limit)
    except Exception:
        pass
    items = list(_ERROR_RING)[-int(limit):]
    items.reverse()
    return items


def clear_errors() -> None:
    """Reset the ring and the durable log (used by tests for isolation)."""
    _ERROR_RING.clear()
    try:
        db.clear_cockpit_errors()
    except Exception:
        pass


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
    if not config.pricing_is_public():
        # Pricing is hidden, so this panel carries no price source: real
        # subscriber and seat counts only, and no MRR derived from a
        # catalogue the product is not currently offering.
        return {
            "tiers": [{"tier": t["tier"], "name": t["name"],
                       "source": t["source"], "subscribers": t["subscribers"],
                       "seats": t["seats"]} for t in tiers],
            "mrr_estimate":   None,
            "arr_estimate":   None,
            "currency":       "USD",
            "basis":          "counts_only_pricing_hidden",
            "note": ("Pricing is hidden while the published offer withholds "
                     "it, so no per-seat price or MRR is derived. The "
                     "subscriber and seat counts are real."),
            "paying_subscribers": paying_subscribers,
            "trial_users":    int(by_plan.get("trial", 0)),
            "companies":      db.count_companies(),
        }
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


def _health_probe() -> dict:
    """Measured health: the database answers, the replica store can be
    written, and the data volume has room. Each check says why it failed."""
    import shutil
    checks: dict = {}
    try:
        checks["database"] = db.database_health()
    except Exception as exc:
        checks["database"] = {"ok": False, "reason": type(exc).__name__}
    try:
        import brain_replica
        root = Path(str(getattr(brain_replica, "DEFAULT_REPLICAS_ROOT", "") or config.DATA_DIR))
        target = root if root.exists() else root.parent
        checks["replicas_root"] = {"ok": os.access(target, os.W_OK), "exists": root.exists()}
    except Exception as exc:
        checks["replicas_root"] = {"ok": False, "reason": type(exc).__name__}
    try:
        usage = shutil.disk_usage(str(config.DATA_DIR))
        checks["data_volume"] = {"ok": usage.free > 256 * 1024 * 1024,
                                 "free_bytes": usage.free, "total_bytes": usage.total}
    except Exception as exc:
        checks["data_volume"] = {"ok": False, "reason": type(exc).__name__}
    return {"ok": all(check.get("ok") for check in checks.values()),
            "ts": int(time.time()), "checks": checks}


_FLY_CACHE: dict = {}


def _fetch_fly_machines(app: str, token: str) -> list:
    import urllib.request
    auth = token if token.startswith("FlyV1 ") else "Bearer " + token
    request = urllib.request.Request(
        "https://api.machines.dev/v1/apps/%s/machines" % _urlquote(app, safe=""),
        headers={"Authorization": auth})
    with urllib.request.urlopen(request, timeout=4) as response:
        return json.loads(response.read().decode("utf-8"))


def _fly_machines(fetch=None) -> dict:
    """This app's Fly machines, read with a read-only token (cached 30 s).

    The token is a secret reference and never leaves this function."""
    app = (os.environ.get("FLY_APP_NAME") or "").strip()
    if not app:
        return {"available": False, "reason": "not running on Fly"}
    raw = (config.FLY_MACHINES_READ_TOKEN or "").strip()
    token = (config._resolve_op_ref(raw) or "").strip() if raw else ""
    if not token:
        return {"available": False,
                "reason": "no read-only Fly token (secret FLY_MACHINES_READ_TOKEN)"}
    cached = _FLY_CACHE.get(app)
    if cached and time.time() - cached[0] < 30:
        return cached[1]
    try:
        rows = (fetch or _fetch_fly_machines)(app, token)
    except Exception as exc:
        record_error(where="founder.fly_machines", kind=type(exc).__name__,
                     message="the Fly Machines API did not answer")
        return {"available": False, "reason": "Fly Machines API: %s" % type(exc).__name__}
    answer = {"available": True, "machines": [
        {"id": m.get("id"), "name": m.get("name"), "state": m.get("state"),
         "region": m.get("region"), "updated_at": m.get("updated_at"),
         "image": ((m.get("config") or {}).get("image"))}
        for m in rows if isinstance(m, dict)]}
    _FLY_CACHE[app] = (time.time(), answer)
    return answer


def _system_panel() -> dict:
    """Brain replica status, health, version/build, deploy info."""
    # The image is built from cloud_backend/ alone, so the repo-root VERSION
    # file is not inside it: the deploy declares ARCHHUB_VERSION (fly.toml
    # [env]); the VERSION file serves a local checkout; "unknown" is honest.
    version = os.environ.get("ARCHHUB_VERSION", "").strip() or "unknown"
    if version == "unknown":
        try:
            from pathlib import Path
            vf = Path(__file__).resolve().parent.parent / "VERSION"
            if vf.exists():
                version = vf.read_text(encoding="utf-8").strip() or "unknown"
        except Exception:
            pass
    image = os.environ.get("FLY_IMAGE_REF", "").rsplit(":", 1)[-1][-14:]
    if image and version != "unknown":
        version = "%s (%s)" % (version, image)

    return {
        "healthz":          _health_probe(),
        "version":          version,
        "env":              os.environ.get("ENV", "").strip().lower() or "dev",
        "billing_provider": config.BILLING_PROVIDER,
        "public_url":       config.PUBLIC_URL,
        "fly": {
            "app":     os.environ.get("FLY_APP_NAME") or None,
            "region":  os.environ.get("FLY_REGION") or None,
            "machine": os.environ.get("FLY_MACHINE_ID") or None,
            "machines": _fly_machines(),
        },
        "brain_replicas": {
            "count": _replica_count(),
            # The replicas were fed by the local personal Brain daemon's sync,
            # retired with that daemon: each replica holds its last synced
            # state and nothing refreshes it until the application Brain syncs.
            "sync": "stopped: the local Brain daemon that synced these replicas is retired",
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
    ("help",             [r"\bhelp\b", r"\bwhat can you do\b", r"\bcommands\b"]),
    # Anything about the founder's RUNNING application -- its graph, BABOOM,
    # the agents on his machine, hosts/brokers, brain, engines, work -- is
    # answered by that application through the relay, never by the cloud.
    ("app",              [r"^\s*(app|baboom)\b",
                          r"\b(agents?|baboom|graph|engines?|hosts?|brokers?|brain|blocked|focus|meetings?|map|update|restart|canvas|nodes?|wires?|work)\b",
                          r"^\s*(tell|interrupt|run|check|show|what|who|which|where|is|are|how|claim|plan|draft)\b",
                          r"^\s*(open|launch|start|connect)\s+(excel|word|powerpoint|outlook|rhino|blender|max|3ds\s*max)\b"]),
    ("direct_agent",     [r"\b(build|extend|create|implement|make|add)\b",
                          r"\bself[\s_-]?extend\b", r"\bagent\b", r"\bbuild me\b"]),
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

    elif action == "app":
        import app_relay
        spoken = re.sub(r"^\s*(?:app|baboom)\s*[:,-]?\s*", "", text, flags=re.IGNORECASE).strip() or text
        result = app_relay.relay(spoken, actor=actor, execute=bool(confirm))
        ok = bool(result.get("ok"))
        target = result.get("task_id")

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
            # The queued row is the one effect. The best-effort trigger that
            # dialed the retired personal Brain daemon is gone with it;
            # nothing here dials a local port.
            result = {"action": "direct_agent", "task": task,
                      "queued": True, "task_id": task["id"],
                      "message": (f"Queued agent task {task['id']} "
                                  f"(status={task['status']}). The self-extension "
                                  f"loop will pick it up.")}

    else:  # not a cloud verb -> the founder's application is the authority
        import app_relay
        result = app_relay.relay(text, actor=actor, execute=bool(confirm))
        ok = bool(result.get("ok"))
        target = result.get("task_id")

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
def api_overview(founder: dict = Depends(require_founder)) -> JSONResponse:
    me = db.get_user(founder["id"]) or founder
    return JSONResponse(dict(build_overview(), me={"email": me.get("email"),
                                                   "name": me.get("full_name") or ""}))


@router.get("/api/users")
def api_users(_founder: dict = Depends(require_founder)) -> JSONResponse:
    return JSONResponse(_users_panel())


# The profile a user gave at sign-up or on the dashboard (cloud columns only).
_PROFILE_FIELDS = ("full_name", "firm_name", "aec_role", "aec_discipline", "firm_size",
                   "country", "signup_source")


@router.get("/api/users/find")
def api_users_find(q: str = "", limit: int = 50, only: str = "",
                   _founder: dict = Depends(require_founder)) -> JSONResponse:
    """The Users list: accounts by email or name substring or exact id, newest
    first, narrowed by `only` (paying, trial, test, suspended), with how many
    accounts each filter holds (read-only).

    The same db.find_users the cockpit agent's users_find tool runs."""
    rows = db.find_users(q, limit=max(1, min(limit, 200)), only=only or None)
    presence = db.user_presence([row["id"] for row in rows])
    for row in rows:
        row.update(presence.get(row["id"], {"last_seen": None, "devices": 0}))
        row["company_id"] = row.pop("current_company_id")
        row["test"] = db.is_test_account_email(row["email"])
        row["founder"] = row["email"] in config.founder_emails()
    return JSONResponse({"count": len(rows), "users": rows, "counts": db.user_filter_counts()})


@router.get("/api/users/{key}")
def api_user_detail(key: str, _founder: dict = Depends(require_founder)) -> JSONResponse:
    """One account: plan and quota, profile, sessions and usage (read-only).

    Cloud-side data only; a user's local graph never reaches the cloud."""
    import cockpit_agent
    found = cockpit_agent._t_users_get({"email" if "@" in key else "user_id": key})
    if "user" not in found:
        return JSONResponse({"ok": False, "error": "no such user"}, status_code=404)
    user = found["user"]
    row = db.get_user_with_profile(user["id"]) or {}
    user["profile"] = {field: row.get(field) for field in _PROFILE_FIELDS}
    user["stripe_customer"] = bool(row.get("stripe_id"))
    user["period_end"] = row.get("period_end")
    user["devices"] = db.list_devices(user["id"])
    user["suspended_at"] = row.get("suspended_at")
    user["suspended_reason"] = row.get("suspended_reason")
    user["deleted_at"] = row.get("deleted_at")
    user["founder"] = user["email"] in config.founder_emails()   # cannot be suspended
    user.update(db.user_activity(user["id"]))
    return JSONResponse({"ok": True, "user": user})


def _account(key: str) -> Optional[dict]:
    return db.get_user_by_email(key.strip().lower()) if "@" in key else db.get_user(key)


def _typed(value, word: str) -> bool:
    """The server's half of a typed confirmation: the founder typed the
    action's word. Without it a destructive route changes nothing."""
    return str(value or "").strip().upper() == word


@router.post("/api/users/{key}/suspend")
def api_user_suspend(key: str, payload: dict = Body(default={}),
                     founder: dict = Depends(require_founder)) -> JSONResponse:
    """Suspend an account: every session it holds stops working, everywhere.
    Needs {"typed": "SUSPEND"}."""
    account = _account(key)
    if account is None:
        return JSONResponse({"ok": False, "error": "no such user"}, status_code=404)
    if (account.get("email") or "").strip().lower() in config.founder_emails():
        # Suspending a founder would lock the cockpit itself.
        return JSONResponse({"ok": False, "error": "a founder account cannot be suspended"},
                            status_code=409)
    if not _typed(payload.get("typed"), "SUSPEND"):
        return JSONResponse({"ok": False, "error": "type SUSPEND to confirm"}, status_code=400)
    reason = str(payload.get("reason") or "").strip() or "suspended by the founder"
    row = db.set_user_suspended(account["id"], reason)
    _audit(founder, "POST /founder/api/users/{key}/suspend", "user.suspend",
           target=account["email"], result={"reason": reason})
    return JSONResponse({"ok": True, "user": {"email": row["email"],
                                              "suspended_at": row.get("suspended_at"),
                                              "suspended_reason": row.get("suspended_reason")}})


@router.post("/api/users/{key}/plan")
def api_user_plan(key: str, payload: dict = Body(default={}),
                  founder: dict = Depends(require_founder)) -> JSONResponse:
    """Change an account's tier; its message quota moves with it.

    The same set_plan the cockpit command runs (route_command), so the error
    vocabulary and the founder_action_log row are that path's own."""
    account = _account(key)
    if account is None:
        return JSONResponse({"ok": False, "error": "no such user"}, status_code=404)
    plan = str(payload.get("plan") or "").strip().lower()
    result = route_command(
        "set %s to %s" % (account["email"], plan),
        actor=(founder.get("email") or "").strip().lower(),
        args={"action": "set_plan", "email": account["email"], "plan": plan})
    return JSONResponse(result, status_code=200 if result.get("ok") else 400)

@router.post("/api/users/{key}/restore")
def api_user_restore(key: str, founder: dict = Depends(require_founder)) -> JSONResponse:
    """Restore a suspended account; its unexpired sessions work again."""
    account = _account(key)
    if account is None:
        return JSONResponse({"ok": False, "error": "no such user"}, status_code=404)
    deleted = bool(account.get("deleted_at"))
    row = (db.set_user_deleted if deleted else db.set_user_suspended)(account["id"], None)
    _audit(founder, "POST /founder/api/users/{key}/restore", "user.restore",
           target=account["email"], result={"reopened": deleted} if deleted else None)
    # a suspension set before a delete survives the reopen; say so
    return JSONResponse({"ok": True, "user": {"email": row["email"], "deleted_at": row.get("deleted_at"),
                                              "suspended_at": row.get("suspended_at"),
                                              "suspended_reason": row.get("suspended_reason")}})
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


@router.get("/api/companies")
def api_companies(_founder: dict = Depends(require_founder)) -> JSONResponse:
    """Every company: plan, seats in use and bought, owner, AI mode, credits (read-only)."""
    return JSONResponse({"companies": db.list_companies_billing()})


def _company_or_404(company_id: str):
    company = db.get_company(company_id)
    if company is None:
        return None, JSONResponse({"ok": False, "error": "no such company"}, status_code=404)
    return company, None


@router.get("/api/companies/{company_id}")
def api_company_detail(company_id: str, _founder: dict = Depends(require_founder)) -> JSONResponse:
    """One company and its people, for the company panel (read-only)."""
    company, missing = _company_or_404(company_id)
    if missing:
        return missing
    row = next((c for c in db.list_companies_billing() if c["id"] == company_id), company)
    return JSONResponse({"ok": True, "company": row,
                         "members": [{"user_id": m["user_id"], "email": m["email"],
                                      "full_name": m.get("full_name"), "role": m["role"]}
                                     for m in db.list_company_members(company_id)]})


@router.post("/api/companies/{company_id}/ai-mode")
def api_company_ai_mode(company_id: str, payload: dict = Body(default={}),
                        founder: dict = Depends(require_founder)) -> JSONResponse:
    """Switch a company between its own keys and ArchHub models."""
    company, missing = _company_or_404(company_id)
    if missing:
        return missing
    wanted = str(payload.get("ai_mode") or "").strip().lower()
    if wanted not in config.AI_MODES:
        return JSONResponse({"ok": False, "error": "ai_mode must be one of %s" % ", ".join(config.AI_MODES)},
                            status_code=400)
    mode = db.set_company_ai_mode(company_id, wanted)
    _audit(founder, "POST /founder/api/companies/{id}/ai-mode", "company.ai_mode",
           target=company["name"], result={"from": company.get("ai_mode"), "to": mode})
    return JSONResponse({"ok": True, "company_id": company_id, "ai_mode": mode})


@router.post("/api/companies/{company_id}/owner")
def api_company_owner(company_id: str, payload: dict = Body(default={}),
                      founder: dict = Depends(require_founder)) -> JSONResponse:
    """Hand a company to another of its members; the old owner stays as admin."""
    company, missing = _company_or_404(company_id)
    if missing:
        return missing
    new_owner = str(payload.get("user_id") or "").strip()
    if new_owner == company.get("owner_user_id"):
        return JSONResponse({"ok": False, "error": "already the owner"}, status_code=400)
    member = db.get_membership(company_id, new_owner) if new_owner else None
    if member is None:
        return JSONResponse({"ok": False, "error": "not a member of this company"}, status_code=404)
    db.transfer_company_ownership(company_id, company.get("owner_user_id"), new_owner)
    email = (db.get_user(new_owner) or {}).get("email")
    _audit(founder, "POST /founder/api/companies/{id}/owner", "company.owner",
           target=company["name"], result={"owner": email})
    return JSONResponse({"ok": True, "company_id": company_id, "owner_email": email})


async def _api_company_invite_effect(company_id: str, payload: dict = Body(default={}),
                             founder: dict = Depends(require_founder)) -> JSONResponse:
    """Invite someone into a company: the owner's own invite (companies.py),
    seat check and emailed link included. The audit row never keeps the token."""
    import companies
    company, missing = _company_or_404(company_id)
    if missing:
        return missing
    email = str(payload.get("email") or "").strip().lower()
    role = str(payload.get("role") or "member").strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return JSONResponse({"ok": False, "error": "a valid email is required"}, status_code=400)
    try:
        invite = await companies.send_company_invite(company_id, email, role, founder["id"], with_outcome=True)
    except HTTPException as refused:
        code = refused.detail if isinstance(refused.detail, str) else ""
        if code == "seat_limit_reached":
            detail = "every seat is taken; add a seat first"
        elif code == "invalid_role":
            detail = "the role is admin or member"
        else:
            detail = code
        _audit(founder, "POST /founder/api/companies/{id}/invite", "company.invite",
               target=company["name"], result={"email": email, "refused": detail}, ok=False)
        return JSONResponse({"ok": False, "error": detail}, status_code=refused.status_code)
    import email_sender
    outcome = invite["email_outcome"]
    _audit(founder, "POST /founder/api/companies/{id}/invite", "company.invite",
           target=company["name"], result={"email": email, "role": role, "outcome": outcome},
           ok=outcome == email_sender.ACCEPTED)
    return _mail_answer(outcome, {"role": role, "expires_at": invite["expires_at"]},
                        "the invite was created but the email was refused; send it again for the same invite",
                        created=True, email=email)


async def _api_company_invite_resend_effect(company_id: str, payload: dict, founder: dict) -> JSONResponse:
    """Email an existing outstanding invite again: the same token and the same
    seat; never a second invite."""
    import companies
    import email_sender
    company, missing = _company_or_404(company_id)
    if missing:
        return missing
    email = str(payload.get("email") or "").strip().lower()
    again = await companies.resend_company_invite(company_id, email) if email else None
    if again is None:
        return JSONResponse({"ok": False, "error": "no outstanding invite for that address"}, status_code=404)
    outcome = again["email_outcome"]
    _audit(founder, "POST /founder/api/companies/{id}/invite/resend", "company.invite.resend",
           target=company["name"], result={"email": email, "outcome": outcome}, ok=outcome == email_sender.ACCEPTED)
    return _mail_answer(outcome, {"expires_at": again["expires_at"]},
                        "the email was refused again; the invite still holds its seat",
                        created=True, resent=True, email=email)


UNCERTAIN_TEXT = "may have been sent; check before sending again"


async def _outcome_of(send) -> str:
    """The mailer's three-valued outcome; anything raised on the way is UNKNOWN."""
    import email_sender
    try:
        outcome = await send
    except Exception:
        return email_sender.UNKNOWN
    return outcome if outcome in (email_sender.ACCEPTED, email_sender.REFUSED) else email_sender.UNKNOWN


def _mail_answer(outcome: str, accepted: dict, refused_text: str, **known) -> JSONResponse:
    """ACCEPTED -> sent. REFUSED -> definitely not sent, a new send may follow.
    UNKNOWN -> uncertain: held until the founder checks, never retried by itself."""
    import email_sender
    if outcome == email_sender.ACCEPTED:
        return JSONResponse({"ok": True, "emailed": True, **known, **accepted})
    if outcome == email_sender.REFUSED:
        return JSONResponse({"ok": False, "emailed": False, "refused": True, "retryable": True,
                             "error": refused_text, **known}, status_code=502)
    return JSONResponse({"ok": False, "emailed": None, "state": "uncertain", "error": UNCERTAIN_TEXT, **known},
                        status_code=202)


async def _api_user_email_effect(key: str, payload: dict = Body(default={}),
                         founder: dict = Depends(require_founder)) -> JSONResponse:
    """Email one account from the founder, through the one sender
    (email_sender). The audit row keeps the subject and the length, not the body."""
    import email_sender
    account = _account(key)
    if account is None:
        return JSONResponse({"ok": False, "error": "no such user"}, status_code=404)
    subject = str(payload.get("subject") or "").strip()[:200]
    text = str(payload.get("text") or "").strip()[:20000]
    if not subject or not text:
        return JSONResponse({"ok": False, "error": "a subject and a message are required"},
                            status_code=400)
    body_html = "<p>" + "</p><p>".join(_html.escape(p) for p in text.split("\n\n")).replace("\n", "<br>") + "</p>"
    outcome = await _outcome_of(email_sender.send_outcome(to=account["email"], subject=subject, text=text,
                                                          html=email_sender._wrap(body_html)))
    _audit(founder, "POST /founder/api/users/{key}/email", "user.email", target=account["email"],
           result={"subject": subject, "chars": len(text), "outcome": outcome},
           ok=outcome == email_sender.ACCEPTED)
    return _mail_answer(outcome, {"email": account["email"], "subject": subject},
                        "the mail provider refused it; nothing was delivered")


# --- Feedback (F48.4; the store is feedback.py) -----------------------------
def _feedback_or_404(feedback_id: str):
    import feedback
    row = feedback.get(feedback_id)
    if row is None:
        return None, JSONResponse({"ok": False, "error": "no such feedback"}, status_code=404)
    return row, None


@router.get("/api/feedback")
def api_feedback(status: str = "", _founder: dict = Depends(require_founder)) -> JSONResponse:
    """Feedback rows newest first, narrowed by status, with each status's count."""
    import feedback
    return JSONResponse({"ok": True, **feedback.listing(status.strip().lower())})


@router.get("/api/feedback/{feedback_id}")
def api_feedback_one(feedback_id: str, _founder: dict = Depends(require_founder)) -> JSONResponse:
    row, missing = _feedback_or_404(feedback_id)
    return missing or JSONResponse({"ok": True, "feedback": row})


@router.post("/api/feedback/{feedback_id}/status")
def api_feedback_status(feedback_id: str, payload: dict = Body(default={}),
                        founder: dict = Depends(require_founder)) -> JSONResponse:
    """Move one row: new, planned, doing, shipped (handled) or declined."""
    import feedback
    row, missing = _feedback_or_404(feedback_id)
    if missing:
        return missing
    status = str(payload.get("status") or "").strip().lower()
    if status not in feedback.STATUSES:
        return JSONResponse({"ok": False, "error": "status is one of %s" % ", ".join(feedback.STATUSES)},
                            status_code=400)
    done = feedback.set_status(feedback_id, status)
    _audit(founder, "POST /founder/api/feedback/{id}/status", "feedback.status",
           target=feedback_id, result={"from": row["status"], "to": status, "who": row.get("email")})
    return JSONResponse({"ok": True, "feedback": done})


@router.post("/api/feedback/{feedback_id}/plan")
def api_feedback_plan(feedback_id: str, payload: dict = Body(default={}),
                      founder: dict = Depends(require_founder)) -> JSONResponse:
    """Link one row to a plan row (a REQUESTS row id such as R238); empty unlinks."""
    import feedback
    row, missing = _feedback_or_404(feedback_id)
    if missing:
        return missing
    plan_row = str(payload.get("plan_row") or "").strip()
    if plan_row and not re.fullmatch(r"[A-Za-z]{1,4}\d{1,6}(\.\d{1,3})?", plan_row):
        return JSONResponse({"ok": False, "error": "a plan row looks like R238 or F48.4"}, status_code=400)
    done = feedback.set_plan(feedback_id, plan_row)
    _audit(founder, "POST /founder/api/feedback/{id}/plan", "feedback.plan",
           target=feedback_id, result={"from": row["plan_row"], "to": plan_row})
    return JSONResponse({"ok": True, "feedback": done})


@router.post("/api/feedback/{feedback_id}/merge")
def api_feedback_merge(feedback_id: str, payload: dict = Body(default={}),
                       founder: dict = Depends(require_founder)) -> JSONResponse:
    """Fold a duplicate into another row."""
    import feedback
    _, missing = _feedback_or_404(feedback_id)
    if missing:
        return missing
    into = str(payload.get("into") or "").strip()
    try:
        feedback.merge(feedback_id, into)
    except ValueError:
        return JSONResponse({"ok": False, "error": "merge into another open row"}, status_code=400)
    _audit(founder, "POST /founder/api/feedback/{id}/merge", "feedback.merge",
           target=feedback_id, result={"into": into})
    return JSONResponse({"ok": True, "feedback": feedback.get(into)})


async def _api_feedback_reply_effect(feedback_id: str, payload: dict = Body(default={}),
                             founder: dict = Depends(require_founder)) -> JSONResponse:
    """Answer the person by email (the one sender); the answer is kept on the row."""
    import email_sender
    import feedback
    row, missing = _feedback_or_404(feedback_id)
    if missing:
        return missing
    text = str(payload.get("text") or "").strip()[:20000]
    subject = str(payload.get("subject") or "").strip()[:200] or "About your ArchHub feedback"
    if not text:
        return JSONResponse({"ok": False, "error": "write the answer first"}, status_code=400)
    if not row.get("email"):
        return JSONResponse({"ok": False, "error": "the account behind this feedback is gone"},
                            status_code=409)
    body_html = "<p>" + "</p><p>".join(_html.escape(p) for p in text.split("\n\n")).replace("\n", "<br>") + "</p>"
    outcome = await _outcome_of(email_sender.send_outcome(to=row["email"], subject=subject, text=text,
                                                          html=email_sender._wrap(body_html)))
    _audit(founder, "POST /founder/api/feedback/{id}/reply", "feedback.reply", target=feedback_id,
           result={"to": row["email"], "subject": subject, "chars": len(text), "outcome": outcome},
           ok=outcome == email_sender.ACCEPTED)
    if outcome != email_sender.ACCEPTED:          # the row keeps only answers known to have gone out
        return _mail_answer(outcome, {}, "the mail provider refused it; nothing was delivered",
                            replay={"kind": "reply", "feedback_id": feedback_id, "subject": subject, "text": text})
    done = feedback.add_reply(feedback_id, by=(founder.get("email") or "").lower(),
                              subject=subject, text=text)
    return _mail_answer(outcome, {"feedback": done}, "")


# --- Community: bans and marketplace packs (F48.3) ---------------------------
@router.get("/api/community/bans")
def api_community_bans(_founder: dict = Depends(require_founder)) -> JSONResponse:
    return JSONResponse({"ok": True, "bans": db.community_bans()})


@router.post("/api/community/ban")
def api_community_ban(payload: dict = Body(default={}),
                      founder: dict = Depends(require_founder)) -> JSONResponse:
    """Stop one member's community shares: nothing they share reaches review
    until they are allowed again. Needs {"typed": "BAN"} and a reason."""
    account = _account(str(payload.get("user") or ""))
    if account is None:
        return JSONResponse({"ok": False, "error": "no such user"}, status_code=404)
    if account["email"].strip().lower() in config.founder_emails():
        return JSONResponse({"ok": False, "error": "a founder account cannot be banned"}, status_code=409)
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        return JSONResponse({"ok": False, "error": "a reason is required"}, status_code=400)
    if not _typed(payload.get("typed"), "BAN"):
        return JSONResponse({"ok": False, "error": "type BAN to confirm"}, status_code=400)
    changed = db.community_ban(account["id"], reason, (founder.get("email") or "").lower())
    _audit(founder, "POST /founder/api/community/ban", "community.ban", target=account["email"],
           result={"reason": reason, "changed": changed})
    return JSONResponse({"ok": True, "email": account["email"], "banned": True})


@router.post("/api/community/unban")
def api_community_unban(payload: dict = Body(default={}),
                        founder: dict = Depends(require_founder)) -> JSONResponse:
    account = _account(str(payload.get("user") or ""))
    if account is None:
        return JSONResponse({"ok": False, "error": "no such user"}, status_code=404)
    changed = db.community_ban(account["id"], None)
    _audit(founder, "POST /founder/api/community/unban", "community.unban", target=account["email"],
           result={"changed": changed})
    return JSONResponse({"ok": True, "email": account["email"], "banned": False})


@router.post("/api/community/{community_id}/owner")
def api_community_owner_recovery(community_id: str, payload: dict = Body(default={}),
                                 founder: dict = Depends(require_founder)) -> JSONResponse:
    """Recover the owner of an existing community that has none enrolled: the founder binds it to a registered
    account whose Ed25519 key signed this exact community and account. Never re-binds an enrolled owner. Needs
    {"typed": "RECOVER"}. Every attempt, refused or not, is one audit row. A recovery and its audit row are one
    transaction (no owner without its audit row); a refusal writes its audit row and nothing else."""
    route = "POST /founder/api/community/%s/owner" % community_id
    account = _account(str(payload.get("owner") or ""))
    owner_pub = str(payload.get("owner_pub") or "")

    def record(error: str = "") -> dict:
        return {"owner": account["email"] if account else None, "owner_pub": owner_pub[:64],
                **({"refused": error} if error else {"enrolled": True})}

    def refuse(status: int, error: str) -> JSONResponse:
        _audit(founder, route, "community.owner.recover", target=community_id, ok=False, result=record(error))
        return JSONResponse({"ok": False, "error": error}, status_code=status)

    if not _typed(payload.get("typed"), "RECOVER"):
        return refuse(400, "type RECOVER to confirm")
    if account is None:
        return refuse(404, "no such user")
    audit = {"actor": (founder.get("email") or "").strip().lower(), "command": route,
             "action": "community.owner.recover", "target": community_id, "result": json.dumps(record())[:2000], "ok": True}
    try:
        enrolled = db.recover_community_owner(community_id, owner_user_id=account["id"], owner_pub=owner_pub,
                                              signature=str(payload.get("signature") or ""), audit=audit)
    except ValueError as refused:
        return refuse(400, str(refused))
    if not enrolled:
        return refuse(409, "this community already has an enrolled owner")
    return JSONResponse({"ok": True, "community_id": community_id, "owner": account["email"]})


_TAKEN_DOWN = "taken_down"


@router.get("/api/packs")
def api_packs(_founder: dict = Depends(require_founder)) -> JSONResponse:
    """Every marketplace pack with its author, numbers, state and reports."""
    with db.connect() as con:
        rows = con.execute(
            "SELECT p.id, p.slug, p.title, p.version, p.status, p.source, p.download_count, "
            "p.up_votes, p.down_votes, p.created_at, p.rejected_reason, u.email AS author_email, "
            "u.full_name AS author_name FROM marketplace_packs p "
            "LEFT JOIN users u ON u.id = p.author_user_id ORDER BY p.created_at DESC").fetchall()
        reports = {}
        for r in con.execute("SELECT pack_id, reason, created_at FROM marketplace_reports "
                             "ORDER BY created_at DESC"):
            reports.setdefault(r["pack_id"], []).append({"reason": r["reason"], "at": r["created_at"]})
    packs = [dict(r, reports=reports.get(r["id"], [])) for r in rows]
    return JSONResponse({"ok": True, "packs": packs})


def _pack_status(pack_id: str) -> Optional[str]:
    with db.connect() as con:
        row = con.execute("SELECT status FROM marketplace_packs WHERE id = ?", (pack_id,)).fetchone()
    return row["status"] if row else None


@router.post("/api/packs/{pack_id}/takedown")
def api_pack_takedown(pack_id: str, payload: dict = Body(default={}),
                      founder: dict = Depends(require_founder)) -> JSONResponse:
    """Take an approved pack off the marketplace: listings, the pack page and
    downloads stop serving it to members (they serve approved packs only).
    Reversible with /restore. Needs {"typed": "TAKEDOWN"} and a reason."""
    import marketplace
    status = _pack_status(pack_id)
    if status is None:
        return JSONResponse({"ok": False, "error": "no such pack"}, status_code=404)
    if status != marketplace.STATUS_APPROVED:
        return JSONResponse({"ok": False, "error": "only a pack on the marketplace can be taken down"},
                            status_code=409)
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        return JSONResponse({"ok": False, "error": "a reason is required"}, status_code=400)
    if not _typed(payload.get("typed"), "TAKEDOWN"):
        return JSONResponse({"ok": False, "error": "type TAKEDOWN to confirm"}, status_code=400)
    with db.connect() as con:
        con.execute("UPDATE marketplace_packs SET status = ?, rejected_reason = ?, updated_at = ? "
                    "WHERE id = ?", (_TAKEN_DOWN, reason[:500], int(time.time()), pack_id))
    _audit(founder, "POST /founder/api/packs/{id}/takedown", "pack.takedown", target=pack_id,
           result={"reason": reason})
    return JSONResponse({"ok": True, "pack_id": pack_id, "status": _TAKEN_DOWN})


@router.post("/api/packs/{pack_id}/restore")
def api_pack_restore(pack_id: str, founder: dict = Depends(require_founder)) -> JSONResponse:
    """Put a taken-down pack back on the marketplace."""
    import marketplace
    status = _pack_status(pack_id)
    if status is None:
        return JSONResponse({"ok": False, "error": "no such pack"}, status_code=404)
    if status != _TAKEN_DOWN:
        return JSONResponse({"ok": False, "error": "this pack was not taken down"}, status_code=409)
    with db.connect() as con:
        con.execute("UPDATE marketplace_packs SET status = ?, rejected_reason = NULL, updated_at = ? "
                    "WHERE id = ?", (marketplace.STATUS_APPROVED, int(time.time()), pack_id))
    _audit(founder, "POST /founder/api/packs/{id}/restore", "pack.restore", target=pack_id)
    return JSONResponse({"ok": True, "pack_id": pack_id, "status": marketplace.STATUS_APPROVED})



# --- One confirmed action, once (every Cockpit route with an outside effect) ---
# The page makes one key when the founder confirms (Send, the typed word) and
# reuses it on every retry of that submission; a new deliberate submission gets
# a fresh key. The key is claimed durably BEFORE the effect, the result is kept
# after it, and a repeat returns that truth instead of acting again.
ACTION_IN_FLIGHT_S = 120


def _body_hash(route: str, target: str, payload: dict) -> str:
    import hashlib
    body = {k: v for k, v in payload.items() if k != "action_key"}
    return hashlib.sha256(json.dumps([route, target, body], sort_keys=True, default=str).encode("utf-8")).hexdigest()


async def _guarded(founder: dict, route: str, target, payload: dict, effect,
                   hold: Optional[str] = None) -> JSONResponse:
    import inspect
    key = payload.get("action_key")
    if not isinstance(key, str) or not 8 <= len(key) <= 100:
        return JSONResponse({"ok": False, "error": "action_key (one per confirmed action) is required"},
                            status_code=400)
    who = (founder.get("email") or "").strip().lower()
    digest = _body_hash(route, str(target), payload)
    now = int(time.time())
    if hold is None and db.get_action_key(key) is None and db.unresolved_action_keys(
            who, stale_before=now - ACTION_IN_FLIGHT_S, money_stale_before=now - REFUND_IN_FLIGHT_S,
            route=route, body_hash=digest):
        return JSONResponse({"ok": False, "state": "held",
                             "error": "an earlier send of this is unresolved; check it or resolve it first"},
                            status_code=409)
    held = db.claim_action_key(key=key, founder=who, route=route, target=str(target)[:200], body_hash=digest,
                               hold=hold)
    if held is db.HELD:          # the database refused a second unresolved action on this payment
        return JSONResponse({"ok": False, "state": "held",
                             "error": "This payment has a refund whose result is unknown or still running. "
                     "Look at it in Stripe; the panel will not refund this payment again."},
                            status_code=409)
    if held is not None:
        if held["founder"] != who or held["body_hash"] != digest:
            return JSONResponse({"ok": False, "state": "refused",
                                 "error": "this key belongs to a different request"}, status_code=409)
        if held["state"] == "done":
            recorded = json.loads(held["result"] or "{}")
            recorded["repeat"] = True        # the recorded truth; nothing was done again
            return JSONResponse(recorded, status_code=int(held["status"] or 200))
        if held["state"].startswith("resolved_"):
            arrived = held["state"] == "resolved_sent"
            return JSONResponse({"ok": arrived, "state": held["state"], "repeat": True,
                                 "error": None if arrived else "you confirmed it did not arrive"}, status_code=200)
        if held["state"] == "uncertain":
            return JSONResponse({"ok": False, "state": "uncertain", "repeat": True, "error": UNCERTAIN_TEXT},
                                status_code=202)
        if int(time.time()) - int(held["claimed_at"]) < (REFUND_IN_FLIGHT_S if held.get("hold") else ACTION_IN_FLIGHT_S):
            return JSONResponse({"ok": False, "state": "in_flight",
                                 "error": "this action is still running; ask again in a moment"}, status_code=409)
        return JSONResponse({"ok": False, "state": "uncertain",
                             "error": "may have been sent; check before sending again"}, status_code=409)
    answer = effect(dict(payload))
    if inspect.isawaitable(answer):
        answer = await answer
    text = answer.body.decode("utf-8")
    db.finish_action_key(key, status=answer.status_code, result=text,
                         state="uncertain" if '"state":"uncertain"' in text.replace(" ", "") else "done")
    return answer


_ROUTE_WORDS = {
    "POST /founder/api/users/{key}/email": "Email",
    "POST /founder/api/feedback/{feedback_id}/reply": "Feedback answer",
    "POST /founder/api/companies/{company_id}/invite": "Company invite",
    "POST /founder/api/companies/{company_id}/invite/resend": "Invite email again",
    "POST /founder/api/stripe/refund": "Refund",
}


def _action_view(row: dict) -> dict:
    """One journal row as the page shows it (never the request body)."""
    window = REFUND_IN_FLIGHT_S if row.get("hold") else ACTION_IN_FLIGHT_S
    state = row["state"]
    if state == "claimed":
        state = "uncertain" if row["claimed_at"] < int(time.time()) - window else "in_flight"
    target = row["target"]
    if "/users/" in row["route"] and "@" not in target:          # a person by id: show who
        target = (db.get_user(target) or {}).get("email") or target
    return {"key": row["key"], "what": _ROUTE_WORDS.get(row["route"], row["route"]), "route": row["route"],
            "target": target, "state": state, "claimed_at": row["claimed_at"],
            "finished_at": row["finished_at"], "detail": _replay_of(row).get("detail", ""),
            "money": bool(row.get("hold")), **_refund_view(row)}


def _refund_view(row: dict) -> dict:
    """For a refund: amount, customer, payment and the Stripe link; nothing that acts."""
    if not row.get("hold"):
        return {}
    try:      # the server-derived context written before the Stripe call; missing stays missing
        context = json.loads(row.get("context") or "{}") or {}
    except ValueError:
        context = {}
    payment = context.get("payment") or row["target"]
    return {"payment_intent": payment, "amount": context.get("amount"), "currency": context.get("currency"),
            "customer": context.get("customer"), "stripe_url": stripe_payment_url(payment),
            "message": REFUND_UNKNOWN_TEXT}


def _customer_of(read: dict) -> dict:
    """The customer part of a refund's stored context: the email, or why it is missing."""
    return {"customer": read.get("email"), "customer_error": read.get("error")}


def _refund_route() -> str:
    """The refund route's journal name, read from the registered route (one source)."""
    return "POST " + next(r.path for r in router.routes if getattr(r, "name", "") == "api_stripe_refund")


REFUND_IN_FLIGHT_S = 600       # a refund holds its payment this long before it can count as lost


def _stale() -> dict:
    now = int(time.time())
    return {"stale_before": now - ACTION_IN_FLIGHT_S, "money_stale_before": now - REFUND_IN_FLIGHT_S}


def _money_uncertain(replay: dict) -> JSONResponse:
    """Stripe may have refunded. Held; Check reads Stripe to find out."""
    return JSONResponse({"ok": False, "state": "uncertain", "error": UNCERTAIN_TEXT, "replay": replay},
                        status_code=202)


def _replay_of(row: dict) -> dict:
    try:
        return (json.loads(row.get("result") or "{}") or {}).get("replay") or {}
    except ValueError:
        return {}


def stripe_payment_url(payment_intent: str) -> str:
    """A plain link to one payment in the Stripe dashboard. The mode comes from
    the configured secret key; when it cannot be told, the dashboard search."""
    from urllib.parse import quote
    key = config.STRIPE_SECRET_KEY or ""
    if key.startswith(("sk_test_", "rk_test_")):
        return "https://dashboard.stripe.com/test/payments/" + quote(payment_intent, safe="")
    if key.startswith(("sk_live_", "rk_live_")):
        return "https://dashboard.stripe.com/payments/" + quote(payment_intent, safe="")
    return "https://dashboard.stripe.com/search?query=" + quote(payment_intent, safe="")


REFUND_UNKNOWN_TEXT = ("The refund's result is unknown. Look at this payment in Stripe. "
                       "The panel will not refund this payment again.")


@router.post("/api/actions/key/{key}/check")
def api_action_check_record(key: str, founder: dict = Depends(require_founder)) -> JSONResponse:
    """Check an unresolved email action: a read of our own record, nothing is
    sent. A refund has no Check here; its result is looked at in Stripe."""
    who = (founder.get("email") or "").strip().lower()
    row = db.get_action_key(key)
    if row is None or row["founder"] != who:
        return JSONResponse({"ok": False, "error": "no such action"}, status_code=404)
    if row.get("hold"):
        return JSONResponse({"ok": False, "error": REFUND_UNKNOWN_TEXT, "action": _action_view(row)},
                            status_code=409)
    _audit(founder, "POST /founder/api/actions/key/{key}/check", "action.check", target=row["target"],
           result={"what": _ROUTE_WORDS.get(row["route"], row["route"]), "state": _action_view(row)["state"]})
    return JSONResponse({"ok": True, "settled": False, "action": _action_view(row)})


@router.get("/api/actions/unresolved")
def api_actions_unresolved(founder: dict = Depends(require_founder)) -> JSONResponse:
    """Actions nobody can vouch for yet, read from the journal itself."""
    who = (founder.get("email") or "").strip().lower()
    rows = db.unresolved_action_keys(who, **_stale())
    return JSONResponse({"ok": True, "actions": [_action_view(r) for r in rows]})


@router.post("/api/actions/key/{key}/resolve")
def api_action_resolve(key: str, payload: dict = Body(default={}),
                       founder: dict = Depends(require_founder)) -> JSONResponse:
    """The founder checked an unresolved action: {"arrived": true} closes it as
    sent, {"arrived": false} as not sent (only then can it be sent anew)."""
    arrived = payload.get("arrived")
    if not isinstance(arrived, bool):
        return JSONResponse({"ok": False, "error": "say whether it arrived (true or false)"}, status_code=400)
    row = db.get_action_key(key)
    if row is None or row["founder"] != (founder.get("email") or "").strip().lower():
        return JSONResponse({"ok": False, "error": "no such action"}, status_code=404)
    if row.get("hold"):              # a refund: never closed by the panel, its payment stays held
        return JSONResponse({"ok": False, "error": REFUND_UNKNOWN_TEXT}, status_code=409)
    if not db.resolve_action_key(key, arrived=arrived, **_stale()):
        return JSONResponse({"ok": False, "error": "this action is not unresolved"}, status_code=409)
    replay = _replay_of(row)
    if arrived and replay.get("kind") == "reply":    # it did reach the person: the answer belongs on the row
        import feedback
        feedback.add_reply(replay["feedback_id"], by=row["founder"], subject=replay.get("subject") or "",
                           text=replay.get("text") or "")
    _audit(founder, "POST /founder/api/actions/key/{key}/resolve", "action.resolve", target=row["target"],
           result={"what": _ROUTE_WORDS.get(row["route"], row["route"]), "arrived": arrived, "key": key[:12]})
    return JSONResponse({"ok": True, "action": _action_view(db.get_action_key(key))})


@router.post("/api/companies/{company_id}/invite/resend")
async def api_company_invite_resend(company_id: str, payload: dict = Body(default={}),
                                    founder: dict = Depends(require_founder)) -> JSONResponse:
    return await _guarded(founder, "POST /founder/api/companies/{company_id}/invite/resend", company_id, payload,
                          lambda body: _api_company_invite_resend_effect(company_id, body, founder))


@router.post("/api/users/{key}/email")
async def api_user_email(key: str, payload: dict = Body(default={}), founder: dict = Depends(require_founder)) -> JSONResponse:
    return await _guarded(founder, "POST /founder/api/users/{key}/email", key, payload,
                          lambda body: _api_user_email_effect(key, body, founder))

@router.post("/api/feedback/{feedback_id}/reply")
async def api_feedback_reply(feedback_id: str, payload: dict = Body(default={}), founder: dict = Depends(require_founder)) -> JSONResponse:
    return await _guarded(founder, "POST /founder/api/feedback/{feedback_id}/reply", feedback_id, payload,
                          lambda body: _api_feedback_reply_effect(feedback_id, body, founder))

@router.post("/api/companies/{company_id}/invite")
async def api_company_invite(company_id: str, payload: dict = Body(default={}), founder: dict = Depends(require_founder)) -> JSONResponse:
    return await _guarded(founder, "POST /founder/api/companies/{company_id}/invite", company_id, payload,
                          lambda body: _api_company_invite_effect(company_id, body, founder))

@router.post("/api/stripe/refund")
async def api_stripe_refund(payload: dict = Body(default={}), founder: dict = Depends(require_founder)) -> JSONResponse:
    token = str(payload.get("confirm_token") or "").strip()
    if token:   # the confirm step: the payment comes from the held confirmation, never from the page
        payment = db.refund_confirmation_payment(token, founder_id=founder["id"])
        return await _guarded(founder, _refund_route(), payment or "unknown-confirmation", payload,
                              lambda body: _api_stripe_refund_effect(body, founder),
                              hold=("refund:" + payment) if payment else None)
    return await _guarded(founder, _refund_route(), str(payload.get("payment_intent") or "")[:80], payload,
                          lambda body: _api_stripe_refund_effect(body, founder))


# --- Leftovers: delete account, errors, usage ------------------
@router.post("/api/users/{key}/delete")
def api_user_delete(key: str, payload: dict = Body(default={}),
                    founder: dict = Depends(require_founder)) -> JSONResponse:
    """Delete an account the way spec 35.08 app-002 section 9 defines it: a typed
    confirm, and it never touches Stripe. The account is closed (every session
    stops, sign-in is refused); no row of the person's data is removed, and
    Restore reopens it. Needs {"typed": "DELETE"}."""
    account = _account(key)
    if account is None:
        return JSONResponse({"ok": False, "error": "no such user"}, status_code=404)
    if account["email"].strip().lower() in config.founder_emails():
        return JSONResponse({"ok": False, "error": "a founder account cannot be deleted"},
                            status_code=409)
    if not _typed(payload.get("typed"), "DELETE"):
        return JSONResponse({"ok": False, "error": "type DELETE to confirm"}, status_code=400)
    reason = str(payload.get("reason") or "").strip() or "deleted by the founder"
    row = db.set_user_deleted(account["id"], reason)
    _audit(founder, "POST /founder/api/users/{key}/delete", "user.delete", target=account["email"],
           result={"reason": reason, "data_removed": False})
    return JSONResponse({"ok": True, "user": {"email": row["email"], "deleted_at": row["deleted_at"]}})


@router.post("/api/errors/resolve")
def api_errors_resolve(payload: dict = Body(default={}),
                       founder: dict = Depends(require_founder)) -> JSONResponse:
    """Mark one failure fixed: every recorded repeat of it (same place, same kind) leaves the log."""
    where, kind = str(payload.get("where") or ""), str(payload.get("kind") or "")
    if not where or not kind:
        return JSONResponse({"ok": False, "error": "where and kind are required"}, status_code=400)
    gone = db.resolve_cockpit_errors(at=where, kind=kind)
    for item in [e for e in _ERROR_RING if e["where"] == where and e["kind"] == kind]:
        _ERROR_RING.remove(item)
    _audit(founder, "POST /founder/api/errors/resolve", "errors.resolve", target=where,
           result={"kind": kind, "removed": gone})
    return JSONResponse({"ok": True, "removed": gone})


@router.get("/api/usage/daily")
def api_usage_daily(_founder: dict = Depends(require_founder)) -> JSONResponse:
    """Messages a day by model family and the top spenders, last 30 days (test accounts excluded)."""
    return JSONResponse({"ok": True, "days": db.usage_by_day(30), "top": db.top_spenders(30, 6)})


@router.get("/api/inbox")
def api_inbox(_founder: dict = Depends(require_founder)) -> JSONResponse:
    """Everything waiting on the founder, newest first: one read over the
    queues that already exist. Each item carries the keys its action route
    needs; nothing is stored here."""
    now = int(time.time())
    emails: dict = {}

    def email_of(user_id) -> Optional[str]:
        if user_id not in emails:
            emails[user_id] = (db.get_user(str(user_id or "")) or {}).get("email")
        return emails[user_id]

    items = [{"kind": "community", "at": row["submitted_at"], "who": email_of(row["contributor"]),
              "text": row["text"], "community_id": row["community_id"],
              "id": row["fragment_id"], "hlc": row["hlc"]}
             for row in db.pending_community_versions()]
    items += [{"kind": "payment_failed", "at": event["ts"], "who": event["email"],
               "amount": event["amount"], "currency": event["currency"],
               "text": event["detail"], "id": event["stripe_object"]}
              for event in db.recent_payment_events("payment_failed", 20)
              if now - int(event["ts"]) <= 14 * 86400]
    items += [{"kind": "relay_failed", "at": task.get("finished_at") or task["created_at"],
               "title": str(task.get("directive") or "")[:300],
               "text": str(task.get("result") or "")[:300], "id": task["id"]}
              for task in db.list_agent_tasks(20, "failed")]
    items += [{"kind": "error", "at": error["ts"], "title": error["kind"],
               "text": error["message"], "where": error["where"]}
              for error in recent_errors(50) if now - int(error["ts"]) <= 86400]
    import feedback
    items += [{"kind": "feedback", "at": row["created_at"], "who": row.get("email"),
               "text": row["text"], "id": row["id"], "type": row["type"]}
              for row in feedback.listing("new", 50)["feedback"]]
    with db.connect() as con:
        reported = con.execute(
            "SELECT p.id, p.title, u.email, COUNT(r.id) AS n, MAX(r.created_at) AS at, "
            "GROUP_CONCAT(r.reason, ' · ') AS reasons FROM marketplace_reports r "
            "JOIN marketplace_packs p ON p.id = r.pack_id LEFT JOIN users u ON u.id = p.author_user_id "
            "WHERE p.status = 'approved' GROUP BY p.id").fetchall()
    items += [{"kind": "pack_reported", "at": row["at"], "who": row["email"], "title": row["title"],
               "text": "%d report%s: %s" % (row["n"], "" if row["n"] == 1 else "s", row["reasons"]),
               "id": row["id"]} for row in reported]
    who = (_founder.get("email") or "").strip().lower()
    items += [{"kind": "unresolved", "at": view["claimed_at"], "who": view["target"] if "@" in view["target"] else None,
               "title": view["what"] + " · " + view["target"], "id": view["key"],
               "text": view.get("message") or UNCERTAIN_TEXT, "stripe_url": view.get("stripe_url"),
               "amount": view.get("amount"), "currency": view.get("currency"), "customer": view.get("customer")}
              for view in (_action_view(r) for r in db.unresolved_action_keys(who, **_stale()))]
    items.sort(key=lambda item: int(item["at"] or 0), reverse=True)
    return JSONResponse({"count": len(items), "items": items})


# --- Community Brain moderation (ADGR-0004) --------------------------------
# The founder review of what members share with the Community Brain. Members
# never pull a version until it is admitted here (community_review.py). This is
# the one review surface; the Cockpit calls it.
@router.get("/api/community/members")
def api_community_members(_founder: dict = Depends(require_founder)) -> JSONResponse:
    """Who belongs to each community, and how many left (read-only)."""
    return JSONResponse({"communities": db.community_membership_view()})


def _admitted_state(community_id: str, fragment_id: str, hlc: str, opened: dict) -> str:
    """What became of an admitted version, read from the shared replica
    without printing its text: current, superseded (a newer version exists)
    or withdrawn. The replica is never created here."""
    import brain_replica
    import community_review
    path = (Path(brain_replica.DEFAULT_REPLICAS_ROOT) / brain_replica._COMMUNITY_SUBDIR
            / brain_replica._safe_key(community_id) / "brain.db")
    if not path.is_file():
        return "unknown"
    if community_id not in opened:
        opened[community_id] = brain_replica.BrainReplica.open_shared("community", community_id)
    row = opened[community_id].get_fragment(fragment_id)
    if row is None:
        return "unknown"
    text = str(row.get("text") or "").strip()
    if row.get("hlc") == hlc and text:
        return "current"
    if not text and community_review._expired(row.get("valid_until")):
        return "withdrawn"
    return "superseded"


@router.get("/api/community/facts")
def api_community_facts(community: str = "", limit: int = 200,
                        _founder: dict = Depends(require_founder)) -> JSONResponse:
    """What members shared and the founder admitted: the admitted text of each
    version, labelled current / superseded / withdrawn. Nothing pending and
    nothing from a private replica is shown."""
    opened: dict = {}
    facts = db.admitted_community_facts(community.strip() or None, limit=limit)
    for fact in facts:
        fact["state"] = _admitted_state(fact["community_id"], fact["fragment_id"],
                                        fact["hlc"], opened)
    return JSONResponse({"facts": facts})


@router.get("/api/community/pending")
def api_community_pending(_founder: dict = Depends(require_founder)) -> JSONResponse:
    import db
    return JSONResponse({"pending": db.pending_community_versions()})


@router.post("/api/community/judge")
def api_community_judge(payload: dict = Body(default={}),
                        founder: dict = Depends(require_founder)) -> JSONResponse:
    import db
    cid = str(payload.get("community_id") or "").strip()
    fid = str(payload.get("id") or "").strip()
    hlc = str(payload.get("hlc") or "").strip()
    admit = payload.get("admit")
    if not cid or not fid or not hlc or not isinstance(admit, bool):
        raise HTTPException(status_code=400, detail="community_id, id, hlc and admit (true/false) are required")
    judged = db.judge_community_version(cid, fid, hlc, admit=admit, decided_by=founder["id"])
    _audit(founder, "/founder/api/community/judge", "community.judge", target="%s/%s@%s" % (cid, fid, hlc),
           result={"admit": admit, "judged": judged,
                   "reason": str(payload.get("reason") or "").strip()[:300]}, ok=judged)
    if not judged:
        raise HTTPException(status_code=409, detail="no pending version with that id and hlc")
    return JSONResponse({"ok": True, "status": "admitted" if admit else "rejected"})


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


def _audit(founder: dict, route: str, action: str, *, target: Optional[str] = None,
           result: Optional[dict] = None, ok: bool = True) -> None:
    """One founder_action_log row for a route that acts outside /api/command.

    Every cockpit route that changes something records who, what and the real
    effect, like the command path does. Nothing secret goes in: a minted
    sign-in code is never written, only that one was minted."""
    db.log_founder_action(
        actor=(founder.get("email") or "").strip().lower(), command=route,
        action=action, target=target, result=json.dumps(result or {})[:2000], ok=ok)


@router.get("/api/actions")
def api_actions(_founder: dict = Depends(require_founder)) -> JSONResponse:
    """The founder action audit log (most recent first)."""
    return JSONResponse({"actions": db.recent_founder_actions(40)})


@router.post("/api/browser-code")
def api_browser_code(founder: dict = Depends(require_founder)) -> JSONResponse:
    """Mint one short-lived, single-use code that opens the cockpit signed in.

    The desktop already holds the founder session; the browser does not, so
    the cockpit link dropped him on a token form he has no token for. This
    is the hand-off every CLI-to-browser sign-in uses: the caller proves it
    is the founder here, over the Authorization header, and receives a code
    that GET /founder/claim spends exactly once for a real cookie.

    The code is not a session. It expires in five minutes, it is deleted the
    first time it is spent, and it is minted only for the founder account,
    so the value that travels in the opened URL is worth nothing afterwards.
    """
    code = db.issue_code(founder["id"], "")
    _audit(founder, "POST /founder/api/browser-code", "browser_code",
           target=founder.get("email"), result={"expires_in_s": 300})
    return JSONResponse({
        "claim_url": "%s/founder/claim?code=%s" % (
            config.PUBLIC_URL.rstrip("/"), _urlquote(code, safe=""),
        ),
    })


@router.get("/api/devices")
def api_devices(user: str = "", _founder: dict = Depends(require_founder)) -> JSONResponse:
    """Signed-in devices, newest heartbeat first; ?user=<email|id> narrows it."""
    account = _account(user) if user else None
    if user and account is None:
        return JSONResponse({"ok": False, "error": "no such user"}, status_code=404)
    return JSONResponse({"ok": True, "devices": db.list_devices(account["id"] if account else None)})


@router.post("/api/devices/{user_key}/{device_id}/disconnect")
def api_device_disconnect(user_key: str, device_id: str,
                          founder: dict = Depends(require_founder)) -> JSONResponse:
    """Disconnect one device: the session it last spoke with stops working."""
    account = _account(user_key)
    done = db.disconnect_device(account["id"], device_id) if account else None
    if done is None:
        return JSONResponse({"ok": False, "error": "no such device"}, status_code=404)
    _audit(founder, "POST /founder/api/devices/{user}/{device}/disconnect",
           "device.disconnect", target="%s/%s" % (account["email"], device_id),
           result={"sessions_revoked": done["sessions_revoked"]})
    return JSONResponse({"ok": True, **done})


@router.get("/api/stripe")
def api_stripe(_founder: dict = Depends(require_founder)) -> JSONResponse:
    """Payments: live Stripe (subscriptions, MRR from real prices, invoices) and
    the failed payments and refunds the webhook recorded."""
    import billing
    return JSONResponse({"live": billing.founder_stripe_view(),
                         "failed_payments": db.recent_payment_events("payment_failed"),
                         "refunds": db.recent_payment_events("refund")})


def _api_stripe_refund_effect(payload: dict = Body(default={}),
                      founder: dict = Depends(require_founder)) -> JSONResponse:
    """A refund the founder clicks, in two steps.

    Without confirm_token: a preview of the payment and a single-use token
    (five minutes, bound to this founder, payment and amount). With it: the
    refund, sent once under an idempotency key derived from the token, and
    audited. Both steps need a reason, which the audit rows keep. Nothing else
    in the cockpit (the agent included) can refund."""
    import billing
    actor = (founder.get("email") or "").strip().lower()
    token = str(payload.get("confirm_token") or "").strip()
    reason = str(payload.get("reason") or "").strip()[:300]
    if not reason:
        return JSONResponse({"ok": False, "error": "a reason is required"}, status_code=400)
    if not token:
        intent = str(payload.get("payment_intent") or "").strip()
        if not intent.startswith("pi_"):
            return JSONResponse({"ok": False, "error": "payment_intent (pi_...) is required"},
                                status_code=400)
        try:
            preview = billing.refund_preview(intent)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": "Stripe: %s" % type(exc).__name__},
                                status_code=502)
        amount = payload.get("amount")
        amount = preview["amount_received"] if amount in (None, "") else int(amount)
        if amount <= 0 or amount > preview["amount_received"]:
            return JSONResponse({"ok": False, "error": "amount must be 1..amount received"},
                                status_code=400)
        confirm = db.issue_refund_confirmation(founder_id=founder["id"], payment_intent=intent,
                                               amount=amount, currency=preview["currency"])
        _audit(founder, "POST /founder/api/stripe/refund", "stripe.refund.preview",
               target=intent, result={"amount": amount, "currency": preview["currency"],
                                      "reason": reason})
        return JSONResponse({"ok": True, "needs_confirm": True, "confirm_token": confirm,
                             "payment_intent": intent, "amount": amount,
                             "currency": preview["currency"], "expires_in_s": 300})
    if not _typed(payload.get("typed"), "REFUND"):
        # The money moves only with the founder's typed word, checked here, not in the page.
        return JSONResponse({"ok": False, "error": "type REFUND to confirm"}, status_code=400)
    held = db.claim_refund_confirmation(token, founder_id=founder["id"])
    if held is None:
        return JSONResponse({"ok": False, "error": "this confirmation is used, expired or not yours"},
                            status_code=409)
    # Stripe's idempotency key comes from the one-time confirmation, as it always has.
    key = "archhub-refund-" + held["token_digest"][:40]
    # A non-secret correlation for a later reconciliation, stored on the action row before the
    # call and sent as metadata. Derived from the confirmation's key, so a retry of the same
    # confirmation sends the very same request body under the very same idempotency key.
    import hashlib
    correlation = "act_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    context = {"payment": held["payment_intent"], "amount": int(held["amount"]),
               "currency": held.get("currency") or None,
               **_customer_of(billing.payment_customer(held["payment_intent"]))}   # the server's records only
    db.set_action_context(str(payload.get("action_key") or ""), correlation=correlation, context=context)
    try:
        refund = billing.refund_payment(payment_intent=held["payment_intent"], amount=held["amount"],
                                        idempotency_key=key, founder=actor, correlation=correlation)
    except Exception as exc:
        outcome = billing.refund_outcome(exc)
        _audit(founder, "POST /founder/api/stripe/refund", "stripe.refund",
               target=held["payment_intent"],
               result={"error": type(exc).__name__, "reason": reason, "outcome": outcome}, ok=False)
        if outcome == billing.UNKNOWN:                  # the confirmation stays used: nothing new can start
            return _money_uncertain({"kind": "refund", "payment_intent": context["payment"],
                                     "amount": context["amount"], "currency": context["currency"],
                                     "founder_email": actor, "reason": reason, "correlation": correlation,
                                     "customer": context["customer"],
                                     "stripe_url": stripe_payment_url(held["payment_intent"]),
                                     "message": REFUND_UNKNOWN_TEXT,
                                     "detail": "refund %s %s of %s to %s" % (
                                         held["amount"], held.get("currency") or "", held["payment_intent"],
                                         context["customer"] or "customer not recorded")})
        db.release_refund_confirmation(token)       # only a definite card or request error gets here
        return JSONResponse({"ok": False, "refused": True, "retryable": True,
                             "error": "Stripe refused it: %s" % type(exc).__name__}, status_code=502)
    _audit(founder, "POST /founder/api/stripe/refund", "stripe.refund",
           target=held["payment_intent"], result={**refund, "reason": reason})
    return JSONResponse({"ok": True, "refund": refund})


@router.post("/api/db/query")
def api_db_query(payload: dict = Body(default={}),
                 founder: dict = Depends(require_founder)) -> JSONResponse:
    """One read-only SELECT over the cloud database (cockpit_query enforces it)."""
    import cockpit_query
    sql = str(payload.get("sql") or "")
    try:
        answer = cockpit_query.run(sql)
    except cockpit_query.QueryRefused as refused:
        _audit(founder, "POST /founder/api/db/query", "db.query", result={
            "sql": sql[:1000], "refused": str(refused)[:300]}, ok=False)
        return JSONResponse({"ok": False, "error": str(refused)[:300]}, status_code=400)
    _audit(founder, "POST /founder/api/db/query", "db.query", result={
        "sql": sql[:1000], "rows": len(answer["rows"]), "truncated": answer["truncated"]})
    return JSONResponse({"ok": True, **answer})


@router.get("/api/relay")
def api_relay(_founder: dict = Depends(require_founder)) -> JSONResponse:
    """The cloud relay: its queue in each status, the oldest wait, whether the
    founder's application is publishing, and the latest failures."""
    status = db.relay_status()
    failed = [{key: task.get(key) for key in
               ("id", "kind", "created_by", "created_at", "finished_at", "claimed_by")}
              | {"directive": str(task.get("directive") or "")[:300],
                 "result": str(task.get("result") or "")[:300]}
              for task in db.list_agent_tasks(20, "failed")]
    return JSONResponse({**status, "failed": failed,
                         "application": {"pushed_at": config.map_pushed_at(),
                                         "live": config.map_is_fresh()}})


@router.post("/api/relay/tasks/{task_id}/retry")
def api_relay_retry(task_id: str, founder: dict = Depends(require_founder)) -> JSONResponse:
    """Put one failed relay task back in the queue."""
    row = db.retry_agent_task(task_id)
    if row is None:
        return JSONResponse({"ok": False, "error": "no failed task with that id"},
                            status_code=404)
    _audit(founder, "POST /founder/api/relay/tasks/{id}/retry", "relay.retry",
           target=task_id, result={"kind": row.get("kind")})
    return JSONResponse({"ok": True, "task": row})


@router.post("/api/relay/drain")
def api_relay_drain(payload: dict = Body(default={}),
                    founder: dict = Depends(require_founder)) -> JSONResponse:
    """Close every queued relay task; none of them runs later. Needs {"typed": "DRAIN"}."""
    if not _typed(payload.get("typed"), "DRAIN"):
        return JSONResponse({"ok": False, "error": "type DRAIN to confirm"}, status_code=400)
    reason ="drained by the founder: %s" % (
        str(payload.get("reason") or "").strip() or "no reason given")
    ids = db.drain_agent_tasks(reason)
    _audit(founder, "POST /founder/api/relay/drain", "relay.drain",
           result={"drained": len(ids), "reason": reason})
    return JSONResponse({"ok": True, "drained": len(ids), "ids": ids})


@router.get("/api/agent-tasks")
def api_agent_tasks(_founder: dict = Depends(require_founder)) -> JSONResponse:
    """The agent task queue the cockpit fills + the app-side loop drains."""
    return JSONResponse({
        "tasks": db.list_agent_tasks(40),
        "queued": db.count_agent_tasks("queued"),
        "total": db.count_agent_tasks(),
    })


# --- The founder's application drains the cockpit -----------------------------
class AgentTaskClaimReq(BaseModel):
    claimed_by: str = "archhub-app"
    kinds: list[str] = ["app", "app-execute"]


class AgentTaskResultReq(BaseModel):
    ok: bool = True
    result: str = ""


@router.post("/api/agent-tasks/claim")
def api_agent_task_claim(body: Optional[AgentTaskClaimReq] = None,
                         founder: dict = Depends(require_founder)) -> JSONResponse:
    """The founder's running application claims the oldest instruction
    addressed to it (kind app / app-execute). {task: null} when idle."""
    import app_relay
    body = body or AgentTaskClaimReq()
    # A Workshop step is claimed only by an app that names it: an app that
    # predates it would read its JSON as a BABOOM instruction.
    kinds = (tuple(k for k in body.kinds if k in app_relay.APP_KINDS)
             or tuple(k for k in app_relay.APP_KINDS if k != app_relay.WORKSHOP_CALL))
    # Only what this signed-in app account queued reaches this desktop. A
    # multi-founder deployment is not a shared session namespace.
    account = (founder.get("email") or "").strip().lower()
    task = db.claim_next_agent_task(
        claimed_by=str(body.claimed_by or "archhub-app")[:120], kinds=kinds,
        creators=(account,))
    if task is not None:
        # An idle poll ({task: null}) changes nothing and is not an action.
        _audit(founder, "POST /founder/api/agent-tasks/claim", "agent_task.claim",
               target=str(task.get("id")), result={"claimed_by": task.get("claimed_by"),
                                                   "kind": task.get("kind")})
    return JSONResponse({"ok": True, "task": task})


@router.post("/api/agent-tasks/{task_id}/result")
def api_agent_task_result(task_id: str, body: AgentTaskResultReq,
                          founder: dict = Depends(require_founder)) -> JSONResponse:
    """The application posts BABOOM's answer for a task it claimed."""
    row = db.finish_agent_task(task_id, ok=bool(body.ok), result=body.result)
    _audit(founder, "POST /founder/api/agent-tasks/{id}/result", "agent_task.result",
           target=task_id, result={"task_ok": bool(body.ok), "chars": len(body.result or ""),
                                   "finished": row is not None}, ok=row is not None)
    if row is None:
        return JSONResponse({"ok": False, "error": "task is not claimed"},
                            status_code=409)
    return JSONResponse({"ok": True, "task": row})


@router.get("/api/agent-tasks/{task_id}")
def api_agent_task_get(task_id: str,
                       _founder: dict = Depends(require_founder)) -> JSONResponse:
    row = db.get_agent_task(task_id)
    if row is None:
        return JSONResponse({"ok": False, "error": "unknown task"}, status_code=404)
    return JSONResponse({"ok": True, "task": row})


# --- Test-account purge (founder-gated, confirm-required) -------------------
class PurgeTestUsersReq(BaseModel):
    """Body for POST /founder/api/purge-test-users. `confirm` MUST be true —
    an unconfirmed call is a dry-run that reports the count WITHOUT deleting,
    so the founder can see exactly how many rows would go before committing.
    A confirmed call must also carry the typed word DELETE."""
    confirm: bool = False
    typed: str = ""


@router.post("/api/purge-test-users")
def api_purge_test_users(
    body: PurgeTestUsersReq = Body(default_factory=PurgeTestUsersReq),
    founder: dict = Depends(require_founder),
) -> JSONResponse:
    """DELETE every synthetic test/seed account (rows matching
    db.is_test_account_email) — the one-click cleanup for the polluted
    production users table. Also reachable as the 'purge test users' command;
    both paths write the founder_action_log audit row.

    Three locks, all required:
      1. FOUNDER GATE — `require_founder` (same as every cockpit route): only
         the founder email passes; everyone else (incl. unauthenticated) → 403.
      2. EXPLICIT CONFIRM — the body must carry {"confirm": true}. Without it
         the call is a safe DRY-RUN: it reports the count that WOULD be deleted
         and deletes nothing, so the destructive action can never fire by
         accident.
      3. TYPED WORD — a confirmed call must carry {"typed": "DELETE"}; without
         it the call is refused (400) and deletes nothing.

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
        # A preview deletes nothing; its row records the intent, as the
        # command path does (purge_test_users.preview).
        _audit(founder, "POST /founder/api/purge-test-users", "purge_test_users.preview",
               result={"would_delete": n})
        return JSONResponse({
            "dry_run":       True,
            "needs_confirm": True,
            "would_purge":   n,
            "would_delete":  n,
            "purged":        0,
            "emails":        [p["email"] for p in preview],
            "note":          "confirm:true and typed:DELETE required to actually delete.",
        })
    if not _typed(body.typed, "DELETE"):
        return JSONResponse({"ok": False, "error": "type DELETE to confirm"}, status_code=400)
    victims = db.list_test_users()
    emails = [v["email"] for v in victims]
    purged = db.delete_test_users()
    _audit(founder, "POST /founder/api/purge-test-users", "purge_test_users",
           result={"deleted": purged, "emails": emails[:50]})
    return JSONResponse({
        "dry_run":        False,
        "purged":         purged,
        "deleted":        purged,
        "emails":         emails,
        "remaining_test": db.count_test_users(),
    })


_COCKPIT_ASSETS = Path(__file__).resolve().parent / "cockpit_assets"
_ASSET_SUFFIXES = frozenset({"js", "jsx", "html", "css", "json", "png", "svg", "woff2", "map"})


# On the durable data volume (config.DATA_DIR = /data on Fly): a deploy replaces the
# machine and its code directory, and the founder's pushed map must outlive that.
_MAP_STATE = Path(config.DATA_DIR) / "founder-map.json"


def _pushed_model(body: Optional[bytes]) -> Optional[dict]:
    try:
        model = json.loads(body.decode("utf-8")) if body is not None else None
    except Exception:
        return None
    return model if isinstance(model, dict) else None


def _wire_params_script(body: Optional[bytes]) -> bytes:
    """window.WIRE_PARAMS for the Wire panel, from the rows the application pushed.

    The one list is the engine's (universal_pipeline.WIRE_PARAMETER_SPECS); the
    desktop publishes it beside its map (cloud_relay._with_control), so the cloud
    keeps no copy. Without it the panel says why instead of drawing no rows.
    """
    model = _pushed_model(body)
    rows = model.get("wire_params") if model is not None else None
    if isinstance(rows, list) and rows and all(
            isinstance(row, dict) and isinstance(row.get("k"), str) for row in rows):
        served, error = rows, ""
    elif body is None:
        served, error = [], "your ArchHub app has not published its map yet"
    else:
        served, error = [], "your ArchHub app has not published its wire parameters yet"
    return (b"window.WIRE_PARAMS = " + json.dumps(served).encode("utf-8")
            + b"; window.WIRE_PARAMS_ERROR = " + json.dumps(error).encode("utf-8") + b";")


def pushed_hosts() -> dict:
    """The hosts the founder's application last published, and how old that is.

    hosts.state over MCP answers from here without waking the desktop; the live
    read is hosts.status. A snapshot of unknown age is never called live.
    """
    model = _pushed_model(_MAP_STATE.read_bytes()) if _MAP_STATE.is_file() else None
    control = model.get("control") if model is not None else None
    hosts = control.get("hosts") if isinstance(control, dict) else None
    if not isinstance(hosts, list):
        return {"ok": False, "hosts": [], "pushed_at": config.map_pushed_at(), "live": False,
                "reason": "your ArchHub app has not published its hosts yet"}
    return {"ok": True, "hosts": hosts[:40], "pushed_at": config.map_pushed_at(),
            "live": config.map_is_fresh()}


@router.post("/map-state")
async def cockpit_map_state(request: Request,
                            _founder: dict = Depends(require_founder)):
    """The founder's desktop publishes its live graph projection here.

    The cockpit is the map and the map is the graph, so the cloud serves
    what the founder's running application actually holds. When no push
    has arrived the authored model remains the fallback -- the surface is
    never blank and never invents state.
    """
    payload = await request.body()
    if len(payload) > 4_000_000:
        return JSONResponse({"ok": False, "error": "map state too large"},
                            status_code=413)
    try:
        json.loads(payload.decode("utf-8"))
    except Exception:
        return JSONResponse({"ok": False, "error": "map state is not JSON"},
                            status_code=400)
    _MAP_STATE.parent.mkdir(parents=True, exist_ok=True)
    # Atomic: readers see the previous complete state or the new one, never
    # a half-written file served as the cockpit map.
    tmp = _MAP_STATE.with_suffix(_MAP_STATE.suffix + ".tmp")
    tmp.write_bytes(payload)
    os.replace(tmp, _MAP_STATE)
    # Record WHEN this body arrived, beside it, so the cockpit can show the
    # age of the map and never label a stale map live. The body file itself
    # stays byte-compatible for map-data.js.
    now = time.time()
    pushed_at = datetime.fromtimestamp(now, timezone.utc).isoformat()
    stamp = config.FOUNDER_MAP_PUSHED_AT
    stamp_tmp = stamp.with_suffix(stamp.suffix + ".tmp")
    stamp_tmp.write_text(json.dumps({"pushed_at": pushed_at,
                                     "epoch": int(now)}), encoding="utf-8")
    os.replace(stamp_tmp, stamp)
    return {"ok": True, "bytes": len(payload), "pushed_at": pushed_at}


@router.get("/map-assets/{asset:path}")
def cockpit_asset(asset: str,
                  _founder: dict = Depends(require_founder)) -> Response:
    """One cockpit module, behind the founder gate like every other route."""
    if asset == "map-data.js":
        if _MAP_STATE.is_file():
            # The founder's LIVE graph, as pushed by his running application.
            # ATLAS_LIVE claims this is the running application graph, so
            # it holds only while the push is recent. An old or unknown-age
            # map is still served - it is the real graph - but it is never
            # labelled live.
            body = _MAP_STATE.read_bytes()
            return Response(
                b"window.ATLAS_MAP = " + body
                + b"; window.ATLAS_MAP_PUSHED_AT = "
                + json.dumps(config.map_pushed_at()).encode("utf-8")
                + b"; window.ATLAS_LIVE = "
                + (b"true" if config.map_is_fresh() else b"false") + b"; "
                + _wire_params_script(body),
                media_type="text/javascript; charset=utf-8",
            )
        # NO PUSH, SO NO MAP. This fell through to a checked-in, hand-authored
        # map-data.js -- 142 KB of authored domains and hand-written prose --
        # served as if it were his graph. An absent application has to be
        # VISIBLE, not papered over with a fixture he cannot tell apart from
        # the real thing (audit, 2026-09-07). ATLAS_LIVE stays false, so the
        # page says so instead of drawing someone else's map.
        return Response(
            b"window.ATLAS_MAP = null; window.ATLAS_LIVE = false; "
            + _wire_params_script(None),
            media_type="text/javascript; charset=utf-8",
        )
    # The asset name comes off the URL: normalise it, refuse anything that
    # climbs out or names a drive, and only then touch the filesystem.
    relative = os.path.normpath(asset).replace(chr(92), "/")
    if (relative.startswith(("..", "/")) or os.path.isabs(relative) or ":" in relative
            or relative.rsplit(".", 1)[-1].lower() not in _ASSET_SUFFIXES):
        return Response(status_code=404)
    base = os.path.realpath(str(_COCKPIT_ASSETS))
    full = os.path.realpath(os.path.join(base, relative))
    if not full.startswith(base + os.sep) or not os.path.isfile(full):
        return Response(status_code=404)
    target = Path(full)
    kind = (
        "text/javascript; charset=utf-8"
        if target.suffix in (".js", ".jsx")
        else "text/html; charset=utf-8" if target.suffix == ".html"
        else "application/octet-stream"
    )
    return Response(target.read_bytes(), media_type=kind)


@router.get("/map", response_class=HTMLResponse)
def cockpit_map(_founder: dict = Depends(require_founder)) -> HTMLResponse:
    """The System map's honest state. The page that drew the app's pushed projection
    (cockpit_assets/map.html, kept and still served as a file by /map-assets, with the /map-state route) can never
    fill: the app stopped sending that projection when the universal graph was retired
    (D-014 NOGRAPH; the app's relay starts with no map source). So this says that, and
    asks the founder to do nothing."""
    return HTMLResponse((_COCKPIT_ASSETS / "map-retired.html").read_text(encoding="utf-8"))


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def cockpit_page(_founder: dict = Depends(require_founder)) -> HTMLResponse:
    """The Cockpit: the founder's admin panel (founder 2026-11-17: "an admin
    panel to manage the application from, not a dashboard"). One static page;
    every list and action on it calls the /founder/api/* routes, which share
    this route's founder gate, and every action lands in the founder audit log."""
    return HTMLResponse((_COCKPIT_ASSETS / "admin.html").read_text(encoding="utf-8"))


# --- The door (the ONLY ungated cockpit routes) -------------------------------
# One sign-in: the desktop app (Settings, Account). The cockpit is a lens of
# the app, so it has no sign-in of its own: the app spends its session at
# POST /founder/api/browser-code for a one-time link that GET /founder/claim
# turns into the cockpit cookie, on this machine or on another device. The
# token form, the emailed cockpit link and the cockpit's own Google button
# were three more doors into the same account (removed 2026-09-24, founder:
# "how many places do we sign in to the cloud and the cockpit?").

@router.get("/login", response_class=HTMLResponse)
def login_page() -> HTMLResponse:
    """Ungated page a browser without the cockpit cookie lands on: it says
    where the cockpit opens from, and offers no sign-in."""
    return HTMLResponse(_login_html())


@router.get("/claim")
def login_claim(code: str = "") -> Response:
    """Finish the emailed sign-in: spend the code, set the cockpit cookie.

    The cookie value is a server-minted token (db.issue_token via
    auth.exchange_code), never anything the visitor typed. A code that is
    expired, already spent, or belongs to any account other than the founder's
    lands back on the door page with one generic message."""
    import auth as _auth
    payload = _auth.exchange_code(code=(code or "").strip(), code_verifier="")
    token = (payload or {}).get("token") if isinstance(payload, dict) else None
    user = _founder_user_for_token(str(token)) if token else None
    if user is None:
        return HTMLResponse(
            _login_html(error="That cockpit link is used, expired or not for this cockpit. "
                              "Open a new one from ArchHub."),
            status_code=401)
    resp = RedirectResponse(url="/founder", status_code=303)
    resp.set_cookie(
        key=FOUNDER_COOKIE,
        value=str(token),
        httponly=True,
        secure=True,
        samesite="lax",
        path="/founder",
        max_age=90 * 86400,
    )
    return resp


@router.get("/logout")
def logout() -> Response:
    """Clear the founder_session cookie and bounce to the login page."""
    resp = RedirectResponse(url="/founder/login", status_code=303)
    resp.delete_cookie(key=FOUNDER_COOKIE, path="/founder")
    return resp


# ---------------------------------------------------------------------------
# The door page (ungated). On-brand: terracotta #d97757, Instrument Serif
# heading, Inter body, no emoji. No form: it says the cockpit opens from the
# app. Optional error banner (escaped).
# ---------------------------------------------------------------------------
import html as _html

_LOGIN_HTML_TMPL = """<!doctype html>
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
  details{margin-top:20px;border-top:1px solid var(--line);padding-top:14px}
  summary{color:var(--ink-faint);font-size:12px;cursor:pointer;list-style:none}
  summary::-webkit-details-marker{display:none}
  summary:hover{color:var(--ink-dim)}
  details label{margin-top:14px}
  .ok{background:rgba(126,193,142,.10);border:1px solid #7ec18e;color:#7ec18e;
    border-radius:10px;padding:12px 14px;font-size:13px;margin:0 0 16px;line-height:1.45}
  input[type=email],input[type=password]{width:100%;background:#0f0f12;border:1px solid var(--line);
    border-radius:10px;color:var(--ink);font-family:inherit;font-size:14px;
    padding:11px 13px;outline:none}
  input[type=email]:focus,input[type=password]:focus{border-color:var(--terracotta)}
  button{margin-top:16px;width:100%;background:var(--terracotta);color:#16110e;
    border:none;border-radius:10px;font-family:inherit;font-size:14px;
    font-weight:600;padding:11px 13px;cursor:pointer}
  button:hover{filter:brightness(1.05)}
  .err{background:rgba(217,103,87,.12);border:1px solid rgba(217,103,87,.35);
    color:#e7a99a;border-radius:10px;padding:10px 12px;font-size:13px;margin-bottom:18px}
  .foot{color:var(--ink-faint);font-size:11.5px;margin-top:18px;line-height:1.45}
  .google{display:block;text-align:center;text-decoration:none;padding:11px 0;
    border-radius:10px;background:#fff;color:#1f1f1f;font-weight:600;font-size:14px;
    border:1px solid rgba(0,0,0,.16)}
  .google:hover{filter:brightness(.97)}
  .or{text-align:center;color:var(--ink-faint);font-size:11.5px;margin:14px 0 10px;
    letter-spacing:.12em;text-transform:uppercase}
</style>
</head>
<body>
  <div class="card">
    <h1>Founder <span class="sub">Cockpit</span></h1>
    <p class="help">Private business oversight.</p>
    {error_block}
    {notice_block}
    <p>The cockpit opens from the ArchHub app, on the account you are signed in with there.</p>
    <p class="help">In ArchHub: Settings, Account, Open the cockpit.
    On another device: Settings, Account, Link for another device, then open that link here.</p>
    <div class="foot">If the app says the sign-in expired, sign in again there first.</div>
  </div>
</body>
</html>
"""


def _login_html(error: Optional[str] = None, notice: Optional[str] = None) -> str:
    """Render the login page. `error` / `notice`, if given, are HTML-escaped and
    shown in a banner; neither the submitted token nor the submitted email is
    ever reflected back into the page."""
    block = (f'<div class="err">{_html.escape(error)}</div>') if error else ""
    good = (f'<div class="ok">{_html.escape(notice)}</div>') if notice else ""
    return (_LOGIN_HTML_TMPL
            .replace("{error_block}", block)
            .replace("{notice_block}", good))
