"""ArchHub Cloud HTTP client — talks to cloud.archhub.app.

Open-core monetization spine. The desktop app stays open-source under
AGPL; users who don't want to bring their own provider keys or
manage a local Ollama can pay a monthly subscription and route every
LLM call through our managed proxy. Same UI, no install friction,
recurring revenue.

This module is the thin HTTP wrapper. It does NOT contain any
provider-specific logic — the proxy at cloud.archhub.app exposes an
OpenAI-compatible Chat Completions endpoint, so the archhub_cloud
LLM client reuses the existing OpenAI wire format.

Endpoints (see docs/BACKEND_SPEC.md for the full contract):

    POST /v1/auth/register        { email } -> 202 (magic link sent)
    POST /v1/auth/exchange        { code, code_verifier } -> { token, expires_at, plan }
    GET  /v1/me                   Authorization: Bearer <token>
                                  -> { email, plan, remaining_messages,
                                       period_end, can_upgrade }
    POST /v1/chat/completions     OpenAI-compatible streaming
    POST /v1/billing/checkout     { tier } -> { url }
    GET  /v1/billing/portal       -> { url }

Token storage uses the existing secrets_store so the credential is
encrypted at rest the same way provider keys are.

Public API
----------
    base_url() -> str
    is_signed_in() -> bool
    current_token() -> str | None
    set_token(token: str, expires_at: float | None = None) -> None
    clear_token() -> None
    me() -> dict | None
    register(email: str) -> tuple[bool, str]
    exchange(code: str, verifier: str) -> tuple[bool, dict]
    checkout(tier: str) -> str | None
    portal_url() -> str | None
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Optional


# Override via env var for staging / local backend during development.
# Backend doesn't have to exist for the client to ship — the UI surfaces
# clear "couldn't reach cloud" errors when calls fail.
DEFAULT_BASE = os.environ.get(
    "ARCHHUB_CLOUD_BASE_URL", "https://cloud.archhub.app"
)

# Secrets-store keys.
_TOKEN_KEY = "archhub_cloud_token"
_EXPIRY_KEY = "archhub_cloud_token_expires_at"


def base_url() -> str:
    return DEFAULT_BASE.rstrip("/")


# ---------------------------------------------------------------------------
def current_token() -> Optional[str]:
    """Return the persisted bearer token if present + not expired."""
    try:
        from secrets_store import load_setting
        token = load_setting(_TOKEN_KEY)
        exp = load_setting(_EXPIRY_KEY)
    except Exception:
        return None
    if not token:
        return None
    try:
        if exp and float(exp) > 0 and time.time() >= float(exp):
            return None   # expired
    except (TypeError, ValueError):
        pass
    return str(token) or None


def is_signed_in() -> bool:
    return bool(current_token())


def set_token(token: str, expires_at: Optional[float] = None) -> None:
    try:
        from secrets_store import save_setting
        save_setting(_TOKEN_KEY, token)
        save_setting(_EXPIRY_KEY, float(expires_at) if expires_at else 0.0)
    except Exception:
        pass


def clear_token() -> None:
    try:
        from secrets_store import save_setting
        save_setting(_TOKEN_KEY, "")
        save_setting(_EXPIRY_KEY, 0.0)
    except Exception:
        pass


# ---------------------------------------------------------------------------
def _request(method: str, path: str, body: Optional[dict] = None,
              auth: bool = True, timeout: float = 15.0) -> dict:
    """Internal request helper. Returns {status, json|error}."""
    url = f"{base_url()}{path}"
    headers = {"Accept": "application/json",
               "User-Agent": "ArchHub-desktop/1.0"}
    if auth:
        token = current_token()
        if not token:
            return {"status": "error", "error": "not_signed_in"}
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers,
                                    method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw) if raw else {}
            except Exception:
                payload = {"raw": raw}
            return {"status": "ok", "json": payload,
                     "http_status": resp.status}
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="replace")
            err_json = json.loads(err_body) if err_body else {}
        except Exception:
            err_json = {}
        return {"status": "error",
                 "error": f"http_{e.code}",
                 "json": err_json}
    except urllib.error.URLError as e:
        return {"status": "error", "error": "unreachable",
                 "detail": str(e.reason)}
    except Exception as e:
        return {"status": "error", "error": f"{type(e).__name__}",
                 "detail": str(e)}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def register(email: str) -> tuple[bool, str]:
    """Trigger a magic-link / OTP send. Returns (ok, human_message)."""
    if not email or "@" not in email:
        return False, "Enter a valid email."
    r = _request("POST", "/v1/auth/register",
                  body={"email": email}, auth=False)
    if r["status"] == "ok":
        return True, "Check your inbox for the sign-in link."
    if r["error"] == "unreachable":
        return False, "Couldn't reach ArchHub Cloud — check your internet."
    return False, "Sign-up failed. Try again in a moment."


def exchange(code: str, code_verifier: str) -> tuple[bool, dict]:
    """Exchange a one-time code (from the magic link or browser flow)
    for a bearer token. Returns (ok, payload_or_error_dict)."""
    r = _request("POST", "/v1/auth/exchange", body={
        "code": code, "code_verifier": code_verifier,
    }, auth=False)
    if r["status"] != "ok":
        return False, r
    j = r.get("json") or {}
    token = j.get("token")
    if not token:
        return False, {"error": "no_token_returned"}
    set_token(token, expires_at=j.get("expires_at"))
    return True, j


# ---------------------------------------------------------------------------
# Account info
# ---------------------------------------------------------------------------
def me() -> Optional[dict]:
    """Fetch current user state: plan, remaining quota, period_end.

    Returns the JSON payload on success, or None when not signed in /
    backend unreachable. Callers handle None as "show sign-in CTA".
    """
    r = _request("GET", "/v1/me")
    if r["status"] != "ok":
        return None
    return r.get("json") or None


# ---------------------------------------------------------------------------
# Billing
# ---------------------------------------------------------------------------
def checkout(tier: str) -> Optional[str]:
    """Create a Stripe Checkout session for the chosen tier and
    return the checkout URL. Caller opens the URL in the user's
    default browser."""
    r = _request("POST", "/v1/billing/checkout", body={"tier": tier})
    if r["status"] != "ok":
        return None
    j = r.get("json") or {}
    return j.get("url")


def portal_url() -> Optional[str]:
    """Stripe Customer Portal URL — for plan changes / cancel."""
    r = _request("GET", "/v1/billing/portal")
    if r["status"] != "ok":
        return None
    j = r.get("json") or {}
    return j.get("url")


# ---------------------------------------------------------------------------
# Memory / training pipeline (v1.3.3+)
# ---------------------------------------------------------------------------
def memory_capture(*, role: str, content: str, tool_trace: list,
                    intent: Optional[str] = None) -> Optional[dict]:
    """Send one approved chat turn to the training data store.

    The desktop calls this when the user clicks 'Approve for training'
    on an assistant message. The backend stamps it pending-redact and
    queues it for the Judge stage. Returns the persisted row or None
    on auth/network failure (caller can retry from local queue).
    """
    body = {"role": role, "content": content,
            "tool_trace": tool_trace,
            "intent": intent or ""}
    r = _request("POST", "/v1/memory/capture", body=body)
    if r["status"] != "ok":
        return None
    return r.get("json") or None


def memory_stats() -> Optional[dict]:
    """Pull counters for the 4 pipeline stages.

    Shape: {capture_today, redact_clean, judge_queued, train_ready}.
    Returns None when not signed in OR cloud unreachable so the UI
    can render '—' without crashing.
    """
    r = _request("GET", "/v1/memory/stats")
    if r["status"] != "ok":
        return None
    return r.get("json") or None
