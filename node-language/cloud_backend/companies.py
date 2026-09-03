"""ArchHub Cloud — Companies / multi-seat router.

A "company" represents the billing + membership unit for a firm. Studio
($79/mo) ships 5 seats; Firm ($299/mo) ships 25. Owners create the
company, invite teammates by email, and pay one subscription that covers
the whole roster.

Endpoints (mounted at root, paths under /v1/companies):

  POST   /v1/companies                          create + start checkout
  GET    /v1/companies/mine                     list memberships (with role)
  GET    /v1/companies/{cid}                    company detail + members
  PATCH  /v1/companies/{cid}                    rename / update billing email
  POST   /v1/companies/{cid}/invites            invite a teammate by email
  POST   /v1/companies/invites/accept           accept an invite
  DELETE /v1/companies/{cid}/members/{user_id}  remove a member (owner only)
  POST   /v1/companies/{cid}/switch             pin the user's active company

Auth: bearer token in `Authorization: Bearer <token>` — same as the rest
of the API. Anonymous calls are rejected with 401.

Roles: owner > admin > member.
  - owner   : exactly one per company. Can transfer (Phase 2).
  - admin   : can invite + remove non-owner members.
  - member  : read-only on company; full quota access in the desktop app.
"""
from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, EmailStr, Field

import billing
import config
import db
import email_sender


router = APIRouter()


# ---------------------------------------------------------------------------
# Auth helpers (mirror main.py / marketplace.py)
# ---------------------------------------------------------------------------
def _bearer(authorization: str | None) -> str:
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


def _require_membership(company_id: str, user_id: str,
                         *, roles: tuple[str, ...] = ("owner", "admin",
                                                       "member"),
                         ) -> dict:
    """Return the membership row if the user belongs to the company with
    one of the accepted roles, else raise 403/404."""
    company = db.get_company(company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="company_not_found")
    m = db.get_membership(company_id, user_id)
    if m is None:
        raise HTTPException(status_code=403, detail="not_a_member")
    if m["role"] not in roles:
        raise HTTPException(status_code=403,
                            detail=f"requires_role:{'|'.join(roles)}")
    return m


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class CreateCompanyReq(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    plan: str = Field(default="studio")
    slug: Optional[str] = Field(default=None, max_length=80)
    billing_email: Optional[EmailStr] = None


class UpdateCompanyReq(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    billing_email: Optional[EmailStr] = None


class InviteReq(BaseModel):
    email: EmailStr
    role: str = Field(default="member")


class AcceptInviteReq(BaseModel):
    invite_token: str = Field(min_length=10, max_length=200)


class TransferOwnershipReq(BaseModel):
    new_owner_user_id: str = Field(min_length=1, max_length=200)


class AiModeReq(BaseModel):
    # Model C: per-workspace AI mode. byo_key (user's own key, no hosted
    # limit) or hosted (we run the LLM, metered against credits).
    ai_mode: str = Field(pattern="^(byo_key|hosted)$")


class SeatsReq(BaseModel):
    # Absolute target seat count. Clamped to the tier floor server-side
    # (Firm can't drop below 10). Studio adds/removes à la carte.
    seats: int = Field(ge=1, le=100000)


class CreditPackReq(BaseModel):
    # Annual billing toggle is irrelevant for a one-time credit pack —
    # this body is intentionally empty for now (kept for forward-compat
    # so the client can POST {} and the route stays stable).
    pass


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/v1/companies")
def create_company(req: CreateCompanyReq,
                    authorization: str | None = Header(None)) -> dict:
    user = _require_user(authorization)
    if req.plan not in config.PLAN_SEATS:
        # Solo isn't a "company" plan — it's a per-user subscription.
        raise HTTPException(status_code=400, detail="unsupported_plan")
    seat_limit = config.PLAN_SEATS[req.plan]
    company = db.create_company(
        name=req.name,
        owner_user_id=user["id"],
        plan=req.plan,
        seat_limit=seat_limit,
        billing_email=(req.billing_email or user["email"]),
        slug=req.slug,
    )
    # Best-effort Stripe Checkout. Returns None if Stripe is not
    # configured (local dev / tests) — that's fine, the company row
    # still exists and an admin can upgrade later via the dashboard.
    checkout_url = billing.create_company_checkout(
        company_id=company["id"], plan=req.plan,
        billing_email=company["billing_email"],
    )
    return {
        "id": company["id"],
        "slug": company["slug"],
        "name": company["name"],
        "plan": company["plan"],
        "seat_limit": company["seat_limit"],
        "checkout_url": checkout_url,
    }


@router.get("/v1/companies/mine")
def list_my_companies(authorization: str | None = Header(None)) -> dict:
    user = _require_user(authorization)
    rows = db.list_companies_for_user(user["id"])
    return {
        "companies": [
            {
                "id": r["id"],
                "name": r["name"],
                "slug": r["slug"],
                "plan": r["plan"],
                "seat_limit": r["seat_limit"],
                "role": r["member_role"],
                "is_current": (user.get("current_company_id") == r["id"]),
            }
            for r in rows
        ],
    }


@router.get("/v1/companies/{company_id}")
def get_company_detail(company_id: str,
                        authorization: str | None = Header(None)) -> dict:
    user = _require_user(authorization)
    # Members can view; only owner/admin see billing metadata. For v1
    # we let any member view the basic detail.
    m = _require_membership(company_id, user["id"])
    company = db.get_company(company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="company_not_found")
    members = db.list_company_members(company_id)
    return {
        "id": company["id"],
        "name": company["name"],
        "slug": company["slug"],
        "plan": company["plan"],
        "seat_limit": company["seat_limit"],
        "billing_email": company["billing_email"],
        "period_end": company.get("period_end"),
        "your_role": m["role"],
        "members": [
            {
                "user_id": x["user_id"],
                "email": x["email"],
                "full_name": x.get("full_name"),
                "role": x["role"],
                "joined_at": x["joined_at"],
            }
            for x in members
        ],
    }


@router.patch("/v1/companies/{company_id}")
def update_company(company_id: str, req: UpdateCompanyReq,
                    authorization: str | None = Header(None)) -> dict:
    user = _require_user(authorization)
    _require_membership(company_id, user["id"], roles=("owner",))
    fields: dict = {}
    if req.name is not None:
        fields["name"] = req.name
    if req.billing_email is not None:
        fields["billing_email"] = str(req.billing_email)
    if fields:
        db.update_company(company_id, **fields)
    return {"ok": True, "company": db.get_company(company_id)}


@router.post("/v1/companies/{company_id}/invites")
async def invite_member(company_id: str, req: InviteReq,
                         authorization: str | None = Header(None)) -> dict:
    user = _require_user(authorization)
    _require_membership(company_id, user["id"], roles=("owner", "admin"))
    if req.role not in ("admin", "member"):
        raise HTTPException(status_code=400, detail="invalid_role")
    # Seat-limit check — count existing members + outstanding invites.
    # Outstanding (un-accepted, un-expired) invites each reserve a seat;
    # counting only members let a company over-invite past seat_limit
    # (N pending invites all pass the check, then all accept).
    current = (db.count_company_members(company_id)
               + db.count_outstanding_invites(company_id))
    company = db.get_company(company_id)
    if current >= int(company["seat_limit"]):
        raise HTTPException(status_code=400, detail="seat_limit_reached")
    invite = db.create_company_invite(
        company_id=company_id,
        email=str(req.email),
        role=req.role,
        invited_by_user_id=user["id"],
    )
    # Best-effort email. We still return the token in the response so
    # the dashboard can show a copy-able link if email is unconfigured.
    link = (
        f"{config.PUBLIC_URL.rstrip('/')}/invite?token={invite['token']}"
    )
    try:
        await email_sender.send_magic_link(to=str(req.email), link=link)
    except Exception as ex:  # noqa: BLE001
        print(f"[companies] invite email failed: {ex}", flush=True)
    return {
        "token": invite["token"],
        "email": invite["email"],
        "role": invite["role"],
        "expires_at": invite["expires_at"],
        "invite_url": link,
    }


@router.post("/v1/companies/invites/accept")
def accept_invite(req: AcceptInviteReq,
                   authorization: str | None = Header(None)) -> dict:
    user = _require_user(authorization)
    invite = db.get_company_invite(req.invite_token)
    if invite is None:
        raise HTTPException(status_code=404, detail="invite_not_found")
    if invite.get("accepted_at"):
        raise HTTPException(status_code=400, detail="invite_already_used")
    if int(invite["expires_at"]) < int(time.time()):
        raise HTTPException(status_code=400, detail="invite_expired")
    # Email match (roadmap #P2). An invite is bound to the address the
    # owner typed. Token possession alone must NOT grant a seat — a
    # forwarded link, a screenshot, or a leaked log would otherwise let
    # a stranger join the firm and burn a paid seat. Require the signed-
    # in user's address to equal the invited address. Both sides are
    # stored .strip().lower()-normalized (db.get_or_create_user /
    # db.create_company_invite); we re-normalize here so the gate holds
    # even for rows a future caller might write un-normalized.
    invited_email = (invite.get("email") or "").strip().lower()
    user_email = (user.get("email") or "").strip().lower()
    if not invited_email or invited_email != user_email:
        raise HTTPException(status_code=403,
                            detail="invite_email_mismatch")
    db.add_company_member(
        company_id=invite["company_id"],
        user_id=user["id"],
        role=invite["role"],
        invited_by_user_id=invite["invited_by_user_id"],
    )
    db.mark_invite_accepted(req.invite_token)
    return {
        "ok": True,
        "company_id": invite["company_id"],
        "role": invite["role"],
    }


@router.delete("/v1/companies/{company_id}/members/{user_id}")
def remove_member(company_id: str, user_id: str,
                   authorization: str | None = Header(None)) -> dict:
    actor = _require_user(authorization)
    _require_membership(company_id, actor["id"], roles=("owner",))
    if user_id == actor["id"]:
        # Owners can't kick themselves — they'd orphan the company.
        # Transfer-ownership flow is Phase 2.
        raise HTTPException(status_code=400, detail="cannot_remove_self")
    if db.get_membership(company_id, user_id) is None:
        raise HTTPException(status_code=404, detail="member_not_found")
    db.remove_company_member(company_id, user_id)
    return {"ok": True}


@router.post("/v1/companies/{company_id}/transfer-ownership")
def transfer_ownership(company_id: str, req: TransferOwnershipReq,
                       authorization: str | None = Header(None)) -> dict:
    """Hand the company to another member (roadmap #P1). Only the
    current owner may transfer. The new owner must already be a
    member; the previous owner stays on as 'admin' (never orphaned).
    Unblocks owner-leave: transfer first, then remove yourself."""
    actor = _require_user(authorization)
    _require_membership(company_id, actor["id"], roles=("owner",))
    if req.new_owner_user_id == actor["id"]:
        raise HTTPException(status_code=400, detail="already_owner")
    if db.get_membership(company_id, req.new_owner_user_id) is None:
        raise HTTPException(status_code=404, detail="member_not_found")
    db.transfer_company_ownership(company_id, actor["id"],
                                  req.new_owner_user_id)
    return {
        "ok": True,
        "company_id": company_id,
        "owner_user_id": req.new_owner_user_id,
    }


@router.get("/v1/companies/{company_id}/ai")
def get_company_ai(company_id: str,
                   authorization: str | None = Header(None)) -> dict:
    """Workspace AI status (Model C): current mode + live hosted-credit
    balance + the credit-pack terms. Any member can read it."""
    user = _require_user(authorization)
    _require_membership(company_id, user["id"])
    company = db.get_company(company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="company_not_found")
    return {
        "company_id": company_id,
        "ai_mode": db._ai_mode_norm(company.get("ai_mode")),
        "credit_balance": db.credit_balance(company_id=company_id),
        "credit_pack": dict(config.CREDIT_PACK),
        "ai_modes": list(config.AI_MODES),
    }


@router.post("/v1/companies/{company_id}/ai-mode")
def set_company_ai_mode(company_id: str, req: AiModeReq,
                        authorization: str | None = Header(None)) -> dict:
    """Flip the workspace between byo_key and hosted AI (Model C).
    Owner/admin only. byo_key → no hosted limit (user's own key);
    hosted → metered against credit packs."""
    user = _require_user(authorization)
    _require_membership(company_id, user["id"], roles=("owner", "admin"))
    if db.get_company(company_id) is None:
        raise HTTPException(status_code=404, detail="company_not_found")
    mode = db.set_company_ai_mode(company_id, req.ai_mode)
    return {"ok": True, "company_id": company_id, "ai_mode": mode}


@router.post("/v1/companies/{company_id}/seats")
def set_company_seats(company_id: str, req: SeatsReq,
                      authorization: str | None = Header(None)) -> dict:
    """À-la-carte seats (Model C). Owner/admin sets the target seat
    count; the request is clamped to the tier floor (Firm ≥ 10), the
    Stripe subscription quantity is updated (Stripe prorates), and the
    company's seat_limit is updated to match.

    If the company has no live Stripe subscription yet (local dev / not
    yet checked out), we still update seat_limit so the roster cap is
    correct — the next checkout will bill the right quantity.
    """
    user = _require_user(authorization)
    _require_membership(company_id, user["id"], roles=("owner", "admin"))
    company = db.get_company(company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="company_not_found")
    plan = company["plan"]
    target = config.clamp_seats(plan, req.seats)
    # Can't drop below the current member count — that would orphan
    # seated teammates.
    members = db.count_company_members(company_id)
    if target < members:
        raise HTTPException(
            status_code=400,
            detail={"error": "seats_below_member_count",
                    "members": members, "requested": target})
    sub_id = company.get("stripe_subscription_id")
    stripe_result = None
    if sub_id:
        stripe_result = billing.update_subscription_quantity(
            subscription_id=sub_id, plan=plan, seats=target)
        if not stripe_result.get("ok"):
            raise HTTPException(status_code=503,
                                detail={"error": "seat_update_failed",
                                        "stripe": stripe_result})
    db.update_company(company_id, seat_limit=target)
    return {"ok": True, "company_id": company_id, "seat_limit": target,
            "stripe": stripe_result}


@router.post("/v1/companies/{company_id}/credits/checkout")
def buy_company_credits(company_id: str, req: CreditPackReq,
                        authorization: str | None = Header(None)) -> dict:
    """Start a one-time Stripe Checkout for a hosted-AI credit pack
    ($10 = 1,000 messages). Owner/admin only. The webhook grants the
    messages to the company on payment (60-day rollover)."""
    user = _require_user(authorization)
    _require_membership(company_id, user["id"], roles=("owner", "admin"))
    company = db.get_company(company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="company_not_found")
    url = billing.create_credit_pack_checkout(
        company_id=company_id,
        billing_email=company.get("billing_email"),
    )
    if not url:
        raise HTTPException(status_code=503, detail="checkout_unavailable")
    return {"url": url, "credit_pack": dict(config.CREDIT_PACK)}


@router.post("/v1/companies/{company_id}/switch")
def switch_company(company_id: str,
                    authorization: str | None = Header(None)) -> dict:
    user = _require_user(authorization)
    # Membership is the gate — you can't switch to a company you're not
    # in. Returns 403 in that case.
    _require_membership(company_id, user["id"])
    db.set_current_company(user["id"], company_id)
    return {"ok": True, "current_company_id": company_id}
