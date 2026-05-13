"""Cloud backend config — env-driven.

All knobs read from environment variables. Local dev: drop a `.env`
next to main.py and python-dotenv loads it on import. Production:
inject via Fly.io secrets / Cloudflare env / Docker.

Required for production:
  STRIPE_SECRET_KEY        — sk_live_... or sk_test_...
  STRIPE_WEBHOOK_SECRET    — whsec_...
  STRIPE_PRICE_SOLO        — price_...  (Solo $19/mo Stripe price id)
  STRIPE_PRICE_STUDIO      — price_...  (Studio $79/mo)
  STRIPE_PRICE_FIRM        — price_...  (Firm $299/mo)
  ANTHROPIC_API_KEY        — sk-ant-... (server's own; users don't have one)
  OPENAI_API_KEY           — sk-... (server's own)
  GOOGLE_API_KEY           — AIza... (server's own)
  RESEND_API_KEY           — re_... (magic-link email sender)
  FROM_EMAIL               — noreply@archhub.app
  PUBLIC_URL               — https://cloud.archhub.app
  DESKTOP_REDIRECT_BASE    — http://127.0.0.1   (clients only ever use loopback)

Optional:
  DATABASE_URL             — sqlite path; defaults to ./archhub_cloud.db
  TRIAL_MESSAGES           — 30
  RATE_LIMIT_PER_MIN       — 30
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:
    pass


def _req(name: str, default: str | None = None) -> str:
    v = os.environ.get(name, default)
    if v is None or v == "":
        # In dev we tolerate missing keys (the relevant endpoint will
        # 503 at call time). Production deploys should fail loudly —
        # set ENV=production and the start-up check below raises.
        if os.environ.get("ENV") == "production":
            raise RuntimeError(f"env var {name} required in production")
        return ""
    return v


STRIPE_SECRET_KEY     = _req("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = _req("STRIPE_WEBHOOK_SECRET")
STRIPE_PRICE_SOLO     = _req("STRIPE_PRICE_SOLO")
STRIPE_PRICE_STUDIO   = _req("STRIPE_PRICE_STUDIO")
STRIPE_PRICE_FIRM     = _req("STRIPE_PRICE_FIRM")

ANTHROPIC_API_KEY = _req("ANTHROPIC_API_KEY")
OPENAI_API_KEY    = _req("OPENAI_API_KEY")
GOOGLE_API_KEY    = _req("GOOGLE_API_KEY")

RESEND_API_KEY = _req("RESEND_API_KEY")
FROM_EMAIL     = _req("FROM_EMAIL", "noreply@archhub.app")
PUBLIC_URL     = _req("PUBLIC_URL", "http://localhost:8000")

DATABASE_URL      = _req("DATABASE_URL", "./archhub_cloud.db")
TRIAL_MESSAGES    = int(_req("TRIAL_MESSAGES", "30"))
RATE_LIMIT_PER_MIN = int(_req("RATE_LIMIT_PER_MIN", "30"))

# Quotas per plan. Keys match Stripe tier ids in /v1/billing/checkout.
PLAN_QUOTAS: dict[str, int] = {
    "trial":  TRIAL_MESSAGES,
    "solo":   500,
    "studio": 2000,
    "firm":   1_000_000,    # fair-use; throttled by RATE_LIMIT_PER_MIN
}

PLAN_PRICE_IDS: dict[str, str] = {
    "solo":   STRIPE_PRICE_SOLO,
    "studio": STRIPE_PRICE_STUDIO,
    "firm":   STRIPE_PRICE_FIRM,
}

# Seats per paid company plan. Studio = 5, Firm = 25. Companies created
# on `solo` are rejected at the router (solo is a single-user plan).
PLAN_SEATS: dict[str, int] = {
    "studio": 5,
    "firm":   25,
}
