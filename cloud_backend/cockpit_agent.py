"""Founder Cockpit AGENT — a real reason->tool->observe loop (PHASE 5).

This is the brain behind POST /founder/api/command. A natural-language founder
instruction is handed to a tool-calling model; the model decides which REAL
admin tool to call; READ tools run immediately and their result is fed back to
the model; a money/destructive WRITE tool returns a PREVIEW CARD and only
executes after the founder explicitly confirms. The model loops (capped ~6
iterations) until it produces a final answer.

ONE-SYSTEM (founder steer): the model transport REUSES the same provider
knowledge as cloud_backend/proxy.py (OpenAI-compatible chat-completions over
httpx) — there is NO parallel LLM client. Every tool is a thin wrapper over an
EXISTING db.py / cockpit function — no new authority is minted here. Every
write is audited via db.log_founder_action, exactly like the keyword router.

Model selection (founder steer #1):
  * PREFER NVIDIA NIM (OpenAI-compatible: config.NVIDIA_BASE_URL, model
    config.NVIDIA_MODEL, key config.NVIDIA_API_KEY) — a strong FREE tool-use
    model.
  * FALL BACK to a reachable-now provider so the cockpit works live TODAY
    without the NVIDIA key: Gemini via its OpenAI-compat endpoint
    (https://generativelanguage.googleapis.com/v1beta/openai, model
    gemini-2.5-flash) using the already-deployed config.GOOGLE_API_KEY.
  * If NEITHER key is reachable (or the model errors mid-loop), the caller
    (founder_cockpit.api_command) falls back to the deterministic keyword
    router route_command — the offline fallback.

WITHHELD ENTIRELY (founder: "ALL of them"): impersonation, GDPR account
erasure, and Stripe refunds are NOT registered as executable tools. The agent
may DESCRIBE / preview them and state they are founder-hands-only, but there is
no code path here that performs them. See WITHHELD_ACTIONS + describe_withheld.
"""
from __future__ import annotations

import json
import os
import time
from typing import Callable, Optional

import httpx

import config
import db


# ---------------------------------------------------------------------------
# Model transport — OpenAI-compatible tool-calling, NVIDIA-preferred.
# ---------------------------------------------------------------------------
def _nvidia_key() -> str:
    """Resolve the NVIDIA key (raw or op://) at call time."""
    try:
        return config._resolve_op_ref(config.NVIDIA_API_KEY)
    except Exception:
        return (config.NVIDIA_API_KEY or "").strip()


def reachable_model() -> Optional[dict]:
    """Pick the agent model provider that can serve RIGHT NOW, or None.

    Order: NVIDIA (preferred, strong + free) -> Gemini OpenAI-compat
    (reachable today via the deployed GOOGLE_API_KEY). Returns a dict
    {provider, base_url, model, key} or None when no key is configured (the
    caller then uses the offline keyword router)."""
    nv = _nvidia_key()
    if nv:
        return {
            "provider": "nvidia",
            "base_url": config.NVIDIA_BASE_URL,
            "model":    config.NVIDIA_MODEL,
            "key":      nv,
        }
    gk = (config.GOOGLE_API_KEY or "").strip()
    if gk:
        return {
            "provider": "google",
            "base_url": ("https://generativelanguage.googleapis.com/"
                         "v1beta/openai"),
            "model":    os.environ.get("COCKPIT_AGENT_GEMINI_MODEL",
                                       "gemini-2.5-flash").strip(),
            "key":      gk,
        }
    return None


def model_available() -> bool:
    return reachable_model() is not None


class ModelError(RuntimeError):
    """Raised when the model transport fails — signals the caller to fall
    back to the offline keyword router."""


def _chat(model_cfg: dict, messages: list[dict], tools: list[dict],
          *, timeout: float = 40.0) -> dict:
    """One OpenAI-compatible /chat/completions call WITH tools (non-stream).

    Returns the first choice's `message` dict (may carry tool_calls). Raises
    ModelError on any transport / shape failure so the caller falls back."""
    url = f"{model_cfg['base_url'].rstrip('/')}/chat/completions"
    payload = {
        "model":       model_cfg["model"],
        "messages":    messages,
        "tools":       tools,
        "tool_choice": "auto",
        "temperature": 0.1,
        "stream":      False,
    }
    headers = {
        "Authorization": f"Bearer {model_cfg['key']}",
        "Content-Type":  "application/json",
    }
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout)) as client:
            resp = client.post(url, headers=headers, json=payload)
        if resp.status_code >= 400:
            raise ModelError(f"{model_cfg['provider']} {resp.status_code}: "
                             f"{resp.text[:300]}")
        data = resp.json()
        return data["choices"][0]["message"]
    except ModelError:
        raise
    except Exception as e:  # noqa: BLE001 — any failure → fall back
        raise ModelError(f"{model_cfg['provider']} transport: {e}") from e


# ---------------------------------------------------------------------------
# TOOL REGISTRY
# ---------------------------------------------------------------------------
# Each tool wraps an EXISTING real function. READ tools are run immediately and
# their result is fed back to the model. GATED-WRITE tools first return a
# preview card (needs_confirm) and only execute after an explicit confirm.
#
# Secrets are NEVER returned to the model: no tool reads a token / code / key,
# and the redactors below strip anything sensitive before a result is handed
# back. There is intentionally NO raw-SQL tool and NO secret-read tool.

# Plans the set_plan tool accepts (mirrors db.set_user_plan validation).
_PLANS = ("trial", "solo", "studio", "firm")

# Dollar cap on a single grant_credits call (blast-radius safety). messages ->
# dollars via the canonical credit-pack price. The agent can never grant more
# than this in one call; a larger ask is refused and returned to the founder.
GRANT_CREDITS_USD_CAP = float(os.environ.get(
    "COCKPIT_GRANT_USD_CAP", "200"))


def _credit_pack_price_per_msg() -> float:
    try:
        pack = config.CREDIT_PACK
        msgs = float(pack["messages"])
        return float(pack["price_usd"]) / msgs if msgs else 0.0
    except Exception:
        return 0.01


def _safe_user(u: Optional[dict]) -> Optional[dict]:
    """A user row stripped to non-secret display fields (never tokens)."""
    if not u:
        return None
    return {
        "id":         u.get("id"),
        "email":      u.get("email"),
        "plan":       u.get("plan"),
        "created_at": u.get("created_at"),
        "msg_used":   u.get("msg_used"),
        "msg_limit":  u.get("msg_limit"),
        "company_id": u.get("current_company_id"),
    }


# ---- READ tool implementations (run immediately) --------------------------
def _t_users_find(args: dict) -> dict:
    q = str(args.get("query") or "").strip()
    limit = int(args.get("limit") or 20)
    rows = db.find_users(q, limit=limit)
    return {"count": len(rows), "users": [_safe_user(r) for r in rows]}


def _t_users_get(args: dict) -> dict:
    key = str(args.get("email") or args.get("user_id") or "").strip()
    if not key:
        return {"error": "need_email_or_user_id"}
    u = (db.get_user_by_email(key) if "@" in key else db.get_user(key))
    if u is None:
        u = db.get_user(key) or db.get_user_by_email(key.lower())
    if u is None:
        return {"error": f"no_such_user:{key}"}
    safe = _safe_user(u)
    try:
        safe["credit_balance"] = db.credit_balance_for_actor(u)
    except Exception:
        pass
    return {"user": safe}


def _t_billing_overview(_args: dict) -> dict:
    import founder_cockpit
    return founder_cockpit._subscriptions_panel()


def _t_brain_inspect(_args: dict) -> dict:
    """Redacted counts only — never fact contents (no secret/PII leak)."""
    import founder_cockpit
    sysp = founder_cockpit._system_panel()
    return {
        "brain_replicas": sysp.get("brain_replicas"),
        "memory_captures": founder_cockpit._usage_panel().get(
            "memory_captures_total"),
        "note": "Redacted counts only — fact contents are never returned.",
    }


def _t_agents_queue_status(_args: dict) -> dict:
    return {
        "queued": db.count_agent_tasks("queued"),
        "total":  db.count_agent_tasks(),
        "recent": db.list_agent_tasks(10),
    }


def _t_system_metrics(_args: dict) -> dict:
    import founder_cockpit
    return {
        "users": founder_cockpit._users_panel(6),
        "usage": founder_cockpit._usage_panel(),
        "system": founder_cockpit._system_panel(),
    }


def _t_system_health(_args: dict) -> dict:
    import founder_cockpit
    sysp = founder_cockpit._system_panel()
    return {"healthz": sysp.get("healthz"), "version": sysp.get("version"),
            "env": sysp.get("env"), "fly": sysp.get("fly"),
            "free_default_available": _free_default_ok()}


def _free_default_ok() -> bool:
    try:
        return bool(config.free_default_available())
    except Exception:
        return False


def _t_audit_recent(args: dict) -> dict:
    limit = int(args.get("limit") or 20)
    return {"actions": db.recent_founder_actions(limit)}


# ---- GATED-WRITE preview + execute ----------------------------------------
def _w_set_plan_preview(args: dict) -> dict:
    email = str(args.get("email") or args.get("user_id") or "").strip()
    plan = str(args.get("plan") or "").strip().lower()
    if not email or plan not in _PLANS:
        return {"error": "need_email_and_valid_plan",
                "plans": list(_PLANS)}
    u = (db.get_user_by_email(email) if "@" in email else db.get_user(email))
    if u is None:
        u = db.get_user(email) or db.get_user_by_email(email.lower())
    if u is None:
        return {"error": f"no_such_user:{email}"}
    return {
        "target": {"user_id": u["id"], "email": u["email"]},
        "change": {"plan": {"from": u.get("plan"), "to": plan},
                   "msg_limit": config.PLAN_QUOTAS.get(plan)},
        "summary": f"Set {u['email']} from plan '{u.get('plan')}' to '{plan}'.",
    }


def _w_set_plan_execute(args: dict) -> dict:
    email = str(args.get("email") or args.get("user_id") or "").strip()
    plan = str(args.get("plan") or "").strip().lower()
    eff = db.set_user_plan(email, plan)
    return {**eff, "summary": f"Set {eff['email']} to plan '{eff['plan']}'."}


def _w_grant_credits_preview(args: dict) -> dict:
    email = str(args.get("email") or args.get("user_id") or "").strip()
    try:
        messages = int(args.get("messages"))
    except Exception:
        return {"error": "need_messages_int"}
    if messages <= 0:
        return {"error": "messages_must_be_positive"}
    dollars = round(messages * _credit_pack_price_per_msg(), 2)
    if dollars > GRANT_CREDITS_USD_CAP:
        return {"error": "exceeds_usd_cap",
                "requested_usd": dollars,
                "cap_usd": GRANT_CREDITS_USD_CAP,
                "summary": (f"Refused: {messages:,} messages "
                            f"(~${dollars}) exceeds the ${GRANT_CREDITS_USD_CAP} "
                            "per-grant safety cap. Ask the founder to raise the "
                            "cap or grant a smaller amount.")}
    u = (db.get_user_by_email(email) if "@" in email else db.get_user(email))
    if u is None:
        u = db.get_user(email) or db.get_user_by_email(email.lower())
    if u is None:
        return {"error": f"no_such_user:{email}"}
    return {
        "target": {"user_id": u["id"], "email": u["email"]},
        "change": {"grant_messages": messages, "approx_usd": dollars},
        "summary": (f"Grant {messages:,} hosted-AI credits "
                    f"(~${dollars}) to {u['email']}."),
    }


def _w_grant_credits_execute(args: dict) -> dict:
    email = str(args.get("email") or args.get("user_id") or "").strip()
    messages = int(args.get("messages"))
    dollars = round(messages * _credit_pack_price_per_msg(), 2)
    if dollars > GRANT_CREDITS_USD_CAP:
        raise ValueError(f"exceeds_usd_cap:{dollars}>{GRANT_CREDITS_USD_CAP}")
    u = (db.get_user_by_email(email) if "@" in email else db.get_user(email))
    if u is None:
        u = db.get_user(email) or db.get_user_by_email(email.lower())
    if u is None:
        raise ValueError(f"no_such_user:{email}")
    eff = db.grant_credits(messages=messages, user_id=u["id"],
                           source="founder_cockpit")
    return {**eff, "email": u["email"],
            "summary": f"Granted {messages:,} credits to {u['email']}."}


_PROFILE_OK = {"display_name", "name", "company", "title", "phone"}


def _w_edit_profile_preview(args: dict) -> dict:
    email = str(args.get("email") or args.get("user_id") or "").strip()
    fields = {k: v for k, v in (args.get("fields") or {}).items()
              if k in _PROFILE_OK and v is not None}
    if not email:
        return {"error": "need_email"}
    if not fields:
        return {"error": "no_editable_fields", "allowed": sorted(_PROFILE_OK)}
    u = (db.get_user_by_email(email) if "@" in email else db.get_user(email))
    if u is None:
        u = db.get_user(email) or db.get_user_by_email(email.lower())
    if u is None:
        return {"error": f"no_such_user:{email}"}
    return {
        "target": {"user_id": u["id"], "email": u["email"]},
        "change": {"fields": fields},
        "summary": f"Update profile of {u['email']}: {fields}.",
    }


def _w_edit_profile_execute(args: dict) -> dict:
    email = str(args.get("email") or args.get("user_id") or "").strip()
    fields = {k: v for k, v in (args.get("fields") or {}).items()
              if k in _PROFILE_OK and v is not None}
    u = (db.get_user_by_email(email) if "@" in email else db.get_user(email))
    if u is None:
        u = db.get_user(email) or db.get_user_by_email(email.lower())
    if u is None:
        raise ValueError(f"no_such_user:{email}")
    db.update_user_profile(u["id"], **fields)
    return {"ok": True, "email": u["email"], "fields": fields,
            "summary": f"Updated profile of {u['email']}."}


def _w_revoke_sessions_preview(args: dict) -> dict:
    email = str(args.get("email") or args.get("user_id") or "").strip()
    if not email:
        return {"error": "need_email"}
    u = (db.get_user_by_email(email) if "@" in email else db.get_user(email))
    if u is None:
        u = db.get_user(email) or db.get_user_by_email(email.lower())
    if u is None:
        return {"error": f"no_such_user:{email}"}
    return {
        "target": {"user_id": u["id"], "email": u["email"]},
        "change": {"action": "revoke_all_sessions"},
        "summary": (f"Sign {u['email']} out of ALL devices "
                    "(revoke every bearer token). They must sign in again."),
    }


def _w_revoke_sessions_execute(args: dict) -> dict:
    email = str(args.get("email") or args.get("user_id") or "").strip()
    u = (db.get_user_by_email(email) if "@" in email else db.get_user(email))
    if u is None:
        u = db.get_user(email) or db.get_user_by_email(email.lower())
    if u is None:
        raise ValueError(f"no_such_user:{email}")
    n = db.delete_tokens_for_user(u["id"])
    return {"ok": True, "email": u["email"], "revoked": n,
            "summary": f"Revoked {n} session(s) for {u['email']}."}


def _w_flags_set_preview(args: dict) -> dict:
    key = str(args.get("key") or "").strip()
    value = args.get("value")
    if not key or value is None:
        return {"error": "need_key_and_value"}
    cur = None
    try:
        cur = db.get_founder_flag(key)
    except Exception:
        pass
    return {
        "target": {"flag": key},
        "change": {"value": {"from": cur, "to": str(value)}},
        "summary": f"Set founder flag '{key}' = '{value}' (was '{cur}').",
    }


def _w_flags_set_execute(args: dict) -> dict:
    key = str(args.get("key") or "").strip()
    value = args.get("value")
    eff = db.set_founder_flag(key, str(value),
                             actor=args.get("_actor"))
    return {**eff, "summary": f"Set founder flag '{key}' = '{value}'."}


# Registry: name -> {kind, run|preview/execute, schema}.
# kind "read"  → run() immediately.
# kind "write" → preview() returns the card; execute() applies after confirm.
TOOLS: dict[str, dict] = {
    # ---- READ (run immediately) ----
    "users_find": {
        "kind": "read", "run": _t_users_find,
        "desc": "Search users by email substring or exact id (read-only).",
        "params": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "email substring or user id"},
                "limit": {"type": "integer"},
            },
        },
    },
    "users_get": {
        "kind": "read", "run": _t_users_get,
        "desc": "Get one user's plan/usage/credit balance (no secrets).",
        "params": {
            "type": "object",
            "properties": {
                "email":   {"type": "string"},
                "user_id": {"type": "string"},
            },
        },
    },
    "billing_overview": {
        "kind": "read", "run": _t_billing_overview,
        "desc": "Subscriptions by tier + estimated MRR/ARR (read-only).",
        "params": {"type": "object", "properties": {}},
    },
    "brain_inspect": {
        "kind": "read", "run": _t_brain_inspect,
        "desc": "Brain replica + memory-capture COUNTS only (redacted).",
        "params": {"type": "object", "properties": {}},
    },
    "agents_queue_status": {
        "kind": "read", "run": _t_agents_queue_status,
        "desc": "Agent task queue depth + recent tasks (read-only).",
        "params": {"type": "object", "properties": {}},
    },
    "system_metrics": {
        "kind": "read", "run": _t_system_metrics,
        "desc": "Users + usage + system roll-up (read-only).",
        "params": {"type": "object", "properties": {}},
    },
    "system_health": {
        "kind": "read", "run": _t_system_health,
        "desc": "Health, version, env, free-default availability (read-only).",
        "params": {"type": "object", "properties": {}},
    },
    "audit_recent": {
        "kind": "read", "run": _t_audit_recent,
        "desc": "Recent founder action audit log (read-only).",
        "params": {"type": "object",
                   "properties": {"limit": {"type": "integer"}}},
    },
    # ---- GATED WRITE (preview -> confirm -> execute + audit) ----
    "users_set_plan": {
        "kind": "write",
        "preview": _w_set_plan_preview, "execute": _w_set_plan_execute,
        "desc": "Change a user's plan/tier (trial|solo|studio|firm). "
                "Returns a preview; needs confirm to apply.",
        "params": {
            "type": "object",
            "properties": {
                "email": {"type": "string"},
                "plan":  {"type": "string", "enum": list(_PLANS)},
            },
            "required": ["email", "plan"],
        },
    },
    "users_grant_credits": {
        "kind": "write",
        "preview": _w_grant_credits_preview,
        "execute": _w_grant_credits_execute,
        "desc": ("Grant hosted-AI message credits to a user (dollar-capped). "
                 "Returns a preview; needs confirm to apply."),
        "params": {
            "type": "object",
            "properties": {
                "email":    {"type": "string"},
                "messages": {"type": "integer"},
            },
            "required": ["email", "messages"],
        },
    },
    "users_edit_profile": {
        "kind": "write",
        "preview": _w_edit_profile_preview,
        "execute": _w_edit_profile_execute,
        "desc": "Edit a user's profile fields. Preview; needs confirm.",
        "params": {
            "type": "object",
            "properties": {
                "email":  {"type": "string"},
                "fields": {"type": "object"},
            },
            "required": ["email", "fields"],
        },
    },
    "users_revoke_sessions": {
        "kind": "write",
        "preview": _w_revoke_sessions_preview,
        "execute": _w_revoke_sessions_execute,
        "desc": "Sign a user out of all devices (revoke every token). "
                "Preview; needs confirm.",
        "params": {
            "type": "object",
            "properties": {"email": {"type": "string"}},
            "required": ["email"],
        },
    },
    "system_flags_set": {
        "kind": "write",
        "preview": _w_flags_set_preview, "execute": _w_flags_set_execute,
        "desc": "Set a founder runtime flag (e.g. free_default=0/1). "
                "Preview; needs confirm.",
        "params": {
            "type": "object",
            "properties": {
                "key":   {"type": "string"},
                "value": {"type": "string"},
            },
            "required": ["key", "value"],
        },
    },
}


# ---------------------------------------------------------------------------
# WITHHELD ENTIRELY (founder: "ALL of them"). These are NOT tools. The agent
# can DESCRIBE / preview them but there is NO code path here that performs
# them — they are founder-hands-only.
# ---------------------------------------------------------------------------
WITHHELD_ACTIONS = {
    "impersonate": ("Logging in AS a user / minting a session token for them. "
                    "Founder-hands-only; the agent cannot do this."),
    "erase_account": ("GDPR account erasure / deleting a real customer's "
                      "account + data. Founder-hands-only; the agent cannot "
                      "do this."),
    "refund": ("Issuing a Stripe refund / moving money. Founder-hands-only; "
               "the agent cannot do this."),
}


def is_withheld(name: str) -> bool:
    n = (name or "").lower()
    return any(k in n for k in
               ("impersonat", "erase", "gdpr", "refund", "delete account",
                "delete_account"))


def describe_withheld() -> str:
    lines = ["These actions are WITHHELD — founder-hands-only, no agent "
             "code path exists for them:"]
    for k, v in WITHHELD_ACTIONS.items():
        lines.append(f"  - {k}: {v}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# OpenAI tool schema + system prompt
# ---------------------------------------------------------------------------
def openai_tools() -> list[dict]:
    """The TOOLS registry rendered as OpenAI/NVIDIA function-calling schema.
    Withheld actions are deliberately absent — the model literally cannot
    select them."""
    out = []
    for name, spec in TOOLS.items():
        out.append({
            "type": "function",
            "function": {
                "name": name,
                "description": spec["desc"],
                "parameters": spec.get("params",
                                       {"type": "object", "properties": {}}),
            },
        })
    return out


SYSTEM_PROMPT = (
    "You are the ArchHub Founder Cockpit agent — a private admin copilot for "
    "the founder ONLY. You help the founder oversee and run the ArchHub "
    "business by calling real admin tools.\n\n"
    "Rules:\n"
    "1. READ tools (users_find, users_get, billing_overview, brain_inspect, "
    "agents_queue_status, system_metrics, system_health, audit_recent) run "
    "immediately. Use them to answer questions with REAL data — never invent "
    "numbers.\n"
    "2. WRITE tools (users_set_plan, users_grant_credits, users_edit_profile, "
    "users_revoke_sessions, system_flags_set) change real state. When you call "
    "one, the system shows the founder a confirmation card and pauses — you do "
    "NOT need to ask for confirmation in text; just call the tool with the "
    "exact target and change.\n"
    "3. Some actions are WITHHELD entirely and you have NO tool for them: "
    "logging in as a user (impersonation), GDPR account erasure, and Stripe "
    "refunds. If asked, explain they are founder-hands-only and that you "
    "cannot perform them. Never claim to have done a withheld action.\n"
    "4. Never reveal secrets, tokens, API keys, or raw SQL. You have no tool "
    "for those.\n"
    "5. Be concise. Prefer doing the work over describing it."
)


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------
def _audit(actor: str, command: str, action: str, target: Optional[str],
           result: dict, ok: bool) -> None:
    try:
        db.log_founder_action(
            actor=actor, command=command, action=action, target=target,
            result=json.dumps(result)[:2000], ok=ok)
    except Exception:
        pass


def _target_of(preview: dict) -> Optional[str]:
    t = preview.get("target") if isinstance(preview, dict) else None
    if isinstance(t, dict):
        return t.get("email") or t.get("user_id") or t.get("flag")
    return None


def confirm_pending(*, actor: str, tool: str, args: dict,
                    command: str = "") -> dict:
    """Execute a previously-previewed gated WRITE after the founder confirms.

    Called by founder_cockpit.api_command when the UI sends back
    {confirm:true, pending:{tool,args}}. Re-validates the dollar cap inside
    execute(); writes the real change; audits. Returns the executed effect."""
    spec = TOOLS.get(tool)
    if spec is None or spec.get("kind") != "write":
        return {"ok": False, "action": tool, "error": "not_a_write_tool",
                "message": f"'{tool}' is not a confirmable write tool."}
    exec_args = dict(args or {})
    exec_args["_actor"] = actor
    try:
        eff = spec["execute"](exec_args)
    except ValueError as ve:
        out = {"ok": False, "action": tool, "error": str(ve),
               "message": f"Could not apply: {ve}"}
        _audit(actor, command or tool, tool, None, out, False)
        return out
    except Exception as e:  # noqa: BLE001
        out = {"ok": False, "action": tool, "error": str(e)[:200],
               "message": f"Write failed: {str(e)[:200]}"}
        _audit(actor, command or tool, tool, None, out, False)
        return out
    out = {"ok": True, "action": tool, "executed": True, "effect": eff,
           "message": eff.get("summary") or "Done."}
    _audit(actor, command or tool, tool,
           eff.get("email") or eff.get("key"), out, True)
    return out


def agent_command(text: str, *, actor: str, history: Optional[list] = None,
                  max_iters: int = 6,
                  model_cfg: Optional[dict] = None,
                  chat_fn: Optional[Callable] = None) -> dict:
    """Run the reason->tool->observe loop for ONE founder instruction.

    Returns a structured result the cockpit renders:
      * a final text answer (action="agent_answer"), OR
      * a gated-write preview card (needs_confirm=true, pending={tool,args}).

    READ tools execute immediately and feed back into the loop. The FIRST
    write tool the model calls is turned into a preview card and the loop
    STOPS (the founder confirms via a second request -> confirm_pending).

    `chat_fn`/`model_cfg` are injectable so tests can MOCK the model with no
    network. In production model_cfg comes from reachable_model() and chat_fn
    defaults to _chat. Raises ModelError when the model is unreachable/errs so
    the caller falls back to the deterministic keyword router."""
    model_cfg = model_cfg or reachable_model()
    if model_cfg is None:
        raise ModelError("no_model_key")
    chat_fn = chat_fn or _chat

    msgs: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for h in (history or [])[-8:]:
        role = h.get("role")
        content = h.get("content")
        if role in ("user", "assistant") and content:
            msgs.append({"role": role, "content": str(content)[:4000]})
    msgs.append({"role": "user", "content": str(text or "")})

    tools = openai_tools()
    tool_trace: list[dict] = []

    for _ in range(max(1, int(max_iters))):
        message = chat_fn(model_cfg, msgs, tools)
        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            answer = (message.get("content") or "").strip() or "(no answer)"
            out = {"ok": True, "action": "agent_answer", "message": answer,
                   "answer": answer, "tools_used": tool_trace,
                   "model": f"{model_cfg['provider']}:{model_cfg['model']}"}
            _audit(actor, text, "agent_answer", None, out, True)
            return out

        # Append the assistant tool-call turn so tool results can reference it.
        msgs.append({"role": "assistant", "content": message.get("content"),
                     "tool_calls": tool_calls})

        for tc in tool_calls:
            fn = (tc.get("function") or {})
            name = fn.get("name") or ""
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except Exception:
                args = {}
            if not isinstance(args, dict):
                args = {}

            if is_withheld(name) or name not in TOOLS:
                # The model tried a withheld / unknown tool. There is no code
                # path to perform it; tell the model so + keep looping.
                refusal = {"refused": True,
                           "reason": ("withheld_or_unknown"),
                           "note": describe_withheld()}
                tool_trace.append({"tool": name, "refused": True})
                msgs.append({"role": "tool",
                             "tool_call_id": tc.get("id"),
                             "name": name,
                             "content": json.dumps(refusal)})
                continue

            spec = TOOLS[name]
            if spec["kind"] == "read":
                try:
                    result = spec["run"](args)
                except Exception as e:  # noqa: BLE001
                    result = {"error": str(e)[:200]}
                tool_trace.append({"tool": name, "args": args})
                msgs.append({"role": "tool",
                             "tool_call_id": tc.get("id"),
                             "name": name,
                             "content": json.dumps(result)[:6000]})
                continue

            # WRITE → preview card; STOP the loop and ask the founder.
            preview = spec["preview"](args)
            if isinstance(preview, dict) and preview.get("error"):
                # Bad args: feed back so the model can correct, keep looping.
                tool_trace.append({"tool": name, "preview_error":
                                   preview.get("error")})
                msgs.append({"role": "tool",
                             "tool_call_id": tc.get("id"),
                             "name": name,
                             "content": json.dumps(preview)})
                continue
            out = {
                "ok": True,
                "action": name,
                "needs_confirm": True,
                "preview": preview,
                "pending": {"tool": name, "args": args},
                "message": preview.get("summary") or
                           f"Confirm to apply {name}.",
                "model": f"{model_cfg['provider']}:{model_cfg['model']}",
            }
            _audit(actor, text, f"{name}.preview",
                   _target_of(preview), out, True)
            return out

    # Hit the iteration cap without a final answer.
    out = {"ok": True, "action": "agent_answer",
           "message": ("I worked through several steps but didn't reach a "
                       "final answer within the step limit. Try narrowing "
                       "the request."),
           "tools_used": tool_trace,
           "model": f"{model_cfg['provider']}:{model_cfg['model']}"}
    _audit(actor, text, "agent_answer.capped", None, out, True)
    return out
