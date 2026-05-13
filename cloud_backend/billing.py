"""Stripe billing — Checkout sessions + Customer Portal + webhook.

Three plans (Solo / Studio / Firm) map to Stripe price ids set via
env. Checkout creates a subscription; we capture the customer id on
checkout.session.completed + flip the user's plan + reset their
monthly quota.

The webhook is the source of truth — never trust client-side
"checkout finished" callbacks for plan upgrades.
"""
from __future__ import annotations

import time
from typing import Optional

try:
    import stripe  # type: ignore
except Exception:
    stripe = None  # noqa: N816

import config
import db


def _ensure_stripe() -> bool:
    if stripe is None:
        return False
    if not config.STRIPE_SECRET_KEY:
        return False
    stripe.api_key = config.STRIPE_SECRET_KEY
    return True


def create_checkout_url(*, user: dict, tier: str) -> Optional[str]:
    """Build a Stripe Checkout session for the given plan tier and
    return its `url`. None on misconfig / invalid tier."""
    if not _ensure_stripe():
        return None
    price = config.PLAN_PRICE_IDS.get(tier)
    if not price:
        return None
    success_url = f"{config.PUBLIC_URL.rstrip('/')}/billing/success"
    cancel_url = f"{config.PUBLIC_URL.rstrip('/')}/billing/cancel"
    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            customer=user.get("stripe_id") or None,
            customer_email=(None if user.get("stripe_id")
                            else user["email"]),
            line_items=[{"price": price, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            client_reference_id=user["id"],
            allow_promotion_codes=True,
            metadata={"user_id": user["id"], "tier": tier},
        )
    except Exception as ex:
        # Surface as None; the route returns 503.
        print(f"[stripe] checkout.create failed: {ex}", flush=True)
        return None
    return session.url


def create_company_checkout(*, company_id: str, plan: str,
                              billing_email: Optional[str] = None,
                              ) -> Optional[str]:
    """Stripe Checkout for the company seat-based plan. Metadata
    carries `company_id` so the webhook can route the resulting
    subscription back to the correct row."""
    if not _ensure_stripe():
        return None
    price = config.PLAN_PRICE_IDS.get(plan)
    if not price:
        return None
    success_url = f"{config.PUBLIC_URL.rstrip('/')}/billing/success"
    cancel_url = f"{config.PUBLIC_URL.rstrip('/')}/billing/cancel"
    seats = config.PLAN_SEATS.get(plan, 1)
    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            customer_email=billing_email or None,
            # quantity = seats so Stripe shows per-seat pricing on the
            # invoice; flip to `quantity=1` if the Stripe price already
            # encodes the bundle.
            line_items=[{"price": price, "quantity": seats}],
            success_url=success_url,
            cancel_url=cancel_url,
            client_reference_id=company_id,
            allow_promotion_codes=True,
            metadata={"company_id": company_id, "tier": plan,
                      "kind": "company"},
        )
    except Exception as ex:
        print(f"[stripe] company checkout.create failed: {ex}",
              flush=True)
        return None
    return session.url


def create_portal_url(*, user: dict) -> Optional[str]:
    """Stripe Customer Portal for plan changes / cancel / card update."""
    if not _ensure_stripe():
        return None
    if not user.get("stripe_id"):
        return None
    return_url = f"{config.PUBLIC_URL.rstrip('/')}/billing/portal_return"
    try:
        session = stripe.billing_portal.Session.create(
            customer=user["stripe_id"],
            return_url=return_url,
        )
    except Exception as ex:
        print(f"[stripe] portal.create failed: {ex}", flush=True)
        return None
    return session.url


# ---------------------------------------------------------------------------
def _tier_from_event(event: dict) -> Optional[str]:
    """Pull the tier label out of metadata / line items."""
    try:
        meta = (event["data"]["object"].get("metadata") or {})
        if meta.get("tier"):
            return meta["tier"]
    except Exception:
        pass
    return None


def _user_id_from_event(event: dict) -> Optional[str]:
    obj = event["data"]["object"]
    if obj.get("client_reference_id"):
        return obj["client_reference_id"]
    meta = obj.get("metadata") or {}
    if meta.get("user_id"):
        return meta["user_id"]
    customer = obj.get("customer") or ""
    if customer:
        u = db.get_user_by_stripe_id(customer)
        if u is not None:
            return u["id"]
    return None


def handle_webhook(*, payload: bytes, signature: str) -> dict:
    """Verify + dispatch a Stripe webhook. Returns a small status dict."""
    if not _ensure_stripe():
        return {"ok": False, "error": "stripe_not_configured"}
    try:
        event = stripe.Webhook.construct_event(
            payload, signature, config.STRIPE_WEBHOOK_SECRET,
        )
    except Exception as ex:
        return {"ok": False, "error": f"bad_signature: {ex}"}

    etype = event["type"]
    obj = event["data"]["object"]

    if etype == "checkout.session.completed":
        meta = obj.get("metadata") or {}
        # Company-scoped checkout (multi-seat plans). The router stamps
        # `company_id` + `kind=company` into the session metadata so we
        # can route the subscription update to the right table.
        if meta.get("company_id") or meta.get("kind") == "company":
            cid = meta.get("company_id") or obj.get("client_reference_id")
            tier = meta.get("tier") or "studio"
            stripe_customer = obj.get("customer")
            sub_id = obj.get("subscription")
            period_end = None
            if sub_id:
                try:
                    sub = stripe.Subscription.retrieve(sub_id)
                    period_end = int(sub.get("current_period_end") or 0)
                except Exception:
                    period_end = None
            seat_limit = config.PLAN_SEATS.get(tier, 5)
            if cid:
                db.update_company(
                    cid,
                    plan=tier,
                    seat_limit=seat_limit,
                    stripe_customer_id=stripe_customer,
                    stripe_subscription_id=sub_id,
                    period_end=period_end,
                )
            return {"ok": True, "handled": etype, "company_id": cid,
                    "tier": tier}

        # Legacy per-user flow (Solo plan).
        uid = _user_id_from_event(event)
        tier = _tier_from_event(event) or "solo"
        stripe_id = obj.get("customer")
        period_end = None
        sub_id = obj.get("subscription")
        if sub_id:
            try:
                sub = stripe.Subscription.retrieve(sub_id)
                period_end = int(sub.get("current_period_end") or 0)
            except Exception:
                period_end = None
        if uid:
            db.update_user_plan(uid, plan=tier, stripe_id=stripe_id,
                                  period_end=period_end)
        return {"ok": True, "handled": etype, "user_id": uid,
                "tier": tier}

    if etype == "customer.subscription.updated":
        uid = _user_id_from_event(event)
        # Plan name lives in items.data[0].price metadata or price id.
        tier = "solo"
        try:
            price_id = (obj["items"]["data"][0]["price"]["id"])
            for k, v in config.PLAN_PRICE_IDS.items():
                if v == price_id:
                    tier = k
                    break
        except Exception:
            pass
        period_end = int(obj.get("current_period_end") or 0)
        if uid:
            db.update_user_plan(uid, plan=tier,
                                  period_end=period_end)
        return {"ok": True, "handled": etype, "user_id": uid,
                "tier": tier}

    if etype == "customer.subscription.deleted":
        uid = _user_id_from_event(event)
        if uid:
            db.update_user_plan(uid, plan="trial", period_end=None)
        return {"ok": True, "handled": etype, "user_id": uid}

    if etype == "invoice.payment_failed":
        # Don't downgrade immediately — Stripe retries. Just log.
        uid = _user_id_from_event(event)
        print(f"[billing] payment_failed for user {uid}", flush=True)
        return {"ok": True, "handled": etype, "user_id": uid}

    return {"ok": True, "ignored": etype}
