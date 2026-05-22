"""Polar.sh billing provider — Merchant-of-Record alternative to Stripe.

Why Polar exists in this codebase:

  * Stripe direct requires a real-business KYC (10-30 min + verification
    waits ranging from minutes to days). Solo founders without a
    registered business can hit walls.
  * Polar is a Merchant of Record (MoR): Polar becomes the legal
    seller, we are the SaaS provider. They handle EU VAT, US sales
    tax, UK VAT, chargebacks, and PCI scope.
  * Polar accepts solo-founder signups in ~10 minutes with just an
    email + bank routing. They take ~4% + $0.40 per transaction vs
    Stripe's 2.9% + $0.30 — premium covers tax + compliance.
  * Stripe acquired LemonSqueezy in 2024 — same MoR model. Polar is
    the developer-friendly alternative still backed by independent VC.

Switching providers
-------------------
Set env var `BILLING_PROVIDER=polar` (default `stripe`).
Both implementations expose the same surface:

    create_checkout_url(*, user, tier) -> Optional[str]
    create_portal_url(*, user) -> Optional[str]
    handle_webhook(*, payload: bytes, signature: str) -> dict

The router (`main.py /v1/billing/checkout`, `/v1/webhooks/<provider>`)
dispatches based on `config.BILLING_PROVIDER`. Both webhook handlers
end with the same `db.update_user_plan(...)` call so the DB-side
plan/quota machinery is provider-agnostic.

API reference: https://docs.polar.sh/api-reference
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.request
import urllib.error
from typing import Optional

import config
import db


POLAR_API_BASE = "https://api.polar.sh/v1"
DEFAULT_TIMEOUT_SECONDS = 30


# ---------------------------------------------------------------------------
def _request(method: str, path: str, *,
              body: Optional[dict] = None,
              timeout: int = DEFAULT_TIMEOUT_SECONDS) -> dict:
    """Thin POST/GET helper. Raises on non-2xx; caller wraps as needed."""
    url = f"{POLAR_API_BASE}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {config.POLAR_ACCESS_TOKEN}",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")[:400] if e.fp else ""
        raise RuntimeError(f"polar {e.code}: {err_body}") from e
    return json.loads(payload or "{}")


# ---------------------------------------------------------------------------
def _ensure_configured() -> bool:
    """Polar requires an access token at minimum. Tier-specific product
    UUIDs are checked per checkout call."""
    return bool(config.POLAR_ACCESS_TOKEN)


def create_checkout_url(*, user: dict, tier: str) -> Optional[str]:
    """Build a Polar Checkout session for a tier and return the URL."""
    if not _ensure_configured():
        return None
    product_id = config.POLAR_PRODUCT_IDS.get(tier)
    if not product_id:
        return None

    success_url = f"{config.PUBLIC_URL.rstrip('/')}/billing/success"
    cancel_url  = f"{config.PUBLIC_URL.rstrip('/')}/billing/cancel"

    body = {
        # Polar accepts an array of product IDs; one per checkout.
        "product_id": product_id,
        "success_url": success_url,
        "customer_email": user.get("email") or None,
        # Polar mirrors our user_id back in webhooks via metadata.
        "metadata": {
            "user_id":      user.get("id") or "",
            "tier":         tier,
            "archhub_kind": "user",  # company checkouts use "company"
        },
    }
    try:
        result = _request("POST", "/checkouts/", body=body)
    except Exception as ex:
        print(f"[polar] checkout.create failed: {ex}", flush=True)
        return None
    return result.get("url")


def create_portal_url(*, user: dict) -> Optional[str]:
    """Polar customer portal — manage subscription / cancel / update card."""
    if not _ensure_configured():
        return None
    polar_customer_id = user.get("stripe_id")  # column re-used; Polar id stored there
    if not polar_customer_id:
        return None
    return_url = f"{config.PUBLIC_URL.rstrip('/')}/billing/portal_return"
    body = {
        "customer_id": polar_customer_id,
        "success_url": return_url,
    }
    try:
        result = _request("POST", "/customer-portal/sessions", body=body)
    except Exception as ex:
        print(f"[polar] portal.create failed: {ex}", flush=True)
        return None
    return result.get("customer_portal_url")


# ---------------------------------------------------------------------------
def _verify_signature(payload: bytes, signature_header: str) -> bool:
    """Polar uses HMAC-SHA256 signing (header `polar-webhook-signature`).
    Same construction as Stripe. Returns True on match, False otherwise.
    Reject if secret isn't configured (fail-safe)."""
    if not config.POLAR_WEBHOOK_SECRET:
        return False
    expected = hmac.new(
        config.POLAR_WEBHOOK_SECRET.encode("utf-8"),
        msg=payload, digestmod=hashlib.sha256,
    ).hexdigest()
    # Polar sends "sha256=<hex>" or raw hex. Accept both shapes.
    candidate = signature_header.split("=", 1)[-1].strip()
    return hmac.compare_digest(expected, candidate)


def _user_from_event(event: dict) -> Optional[str]:
    """Extract user_id from event metadata or fall back to customer lookup."""
    data = event.get("data") or {}
    meta = data.get("metadata") or {}
    if meta.get("user_id"):
        return meta["user_id"]
    cust = data.get("customer_id") or ""
    if cust:
        u = db.get_user_by_stripe_id(cust)  # same column re-use
        if u is not None:
            return u["id"]
    return None


def _tier_from_event(event: dict) -> Optional[str]:
    meta = (event.get("data") or {}).get("metadata") or {}
    return meta.get("tier") or None


# ---------------------------------------------------------------------------
def handle_webhook(*, payload: bytes, signature: str) -> dict:
    """Verify + dispatch a Polar webhook. Returns a small status dict.

    Polar event types we care about:
      - subscription.created  -> upgrade plan + reset quota + store customer
      - subscription.updated  -> change tier
      - subscription.canceled -> downgrade to trial
      - order.paid            -> log only (subscription event is the source)
    """
    if not _ensure_configured():
        return {"ok": False, "error": "polar_not_configured"}
    if not _verify_signature(payload, signature):
        return {"ok": False, "error": "bad_signature"}
    try:
        event = json.loads(payload.decode("utf-8"))
    except Exception as ex:
        return {"ok": False, "error": f"bad_json: {ex}"}

    etype = event.get("type") or ""
    data = event.get("data") or {}

    if etype in ("subscription.created", "subscription.updated"):
        uid = _user_from_event(event)
        tier = _tier_from_event(event) or "solo"
        customer_id = data.get("customer_id")
        # Polar returns RFC-3339 timestamps; convert to epoch.
        period_end = _parse_iso_to_epoch(data.get("current_period_end"))
        if uid:
            db.update_user_plan(uid, plan=tier,
                                  stripe_id=customer_id,
                                  period_end=period_end)
        return {"ok": True, "handled": etype, "user_id": uid, "tier": tier}

    if etype in ("subscription.canceled", "subscription.revoked"):
        uid = _user_from_event(event)
        if uid:
            db.update_user_plan(uid, plan="trial", period_end=None)
        return {"ok": True, "handled": etype, "user_id": uid}

    if etype == "order.paid":
        # Subscription events are the source of truth; just log.
        uid = _user_from_event(event)
        print(f"[polar] order.paid for user {uid}", flush=True)
        return {"ok": True, "handled": etype, "user_id": uid}

    return {"ok": True, "ignored": etype}


def _parse_iso_to_epoch(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    try:
        from datetime import datetime
        # Polar emits ...Z; strip + parse.
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return int(dt.timestamp())
    except Exception:
        return None
