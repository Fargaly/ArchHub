"""Cloud backend config — env-driven.

All knobs read from environment variables. Local dev: drop a `.env`
next to main.py and python-dotenv loads it on import. Production:
inject via Fly.io secrets / Cloudflare env / Docker.

Pricing = Model C (founder-approved 2026-05-31). The single canonical
source is the typed `PLANS` / `CREDIT_PACK` / `ANNUAL_DISCOUNT` /
`AI_MODES` structures further down — NOT this docstring. See
docs/prototypes/pricing-model-C-hybrid-2026-05-31.html for the spec.

Required for production:
  STRIPE_SECRET_KEY            — sk_live_... or sk_test_...
  STRIPE_WEBHOOK_SECRET        — whsec_...
  STRIPE_PRICE_SOLO            — price_...  (Solo $19/mo · monthly per-seat)
  STRIPE_PRICE_SOLO_ANNUAL     — price_...  (Solo annual, −20%)
  STRIPE_PRICE_STUDIO          — price_...  (Studio $39/seat/mo · monthly)
  STRIPE_PRICE_STUDIO_ANNUAL   — price_...  (Studio annual per-seat, −20%)
  STRIPE_PRICE_FIRM            — price_...  (Firm $29/seat/mo · monthly, 10+ seats)
  STRIPE_PRICE_FIRM_ANNUAL     — price_...  (Firm annual per-seat, −20%)
  STRIPE_PRICE_CREDIT_PACK     — price_...  ($10 = 1,000 hosted-AI messages, one-time)
  ANTHROPIC_API_KEY            — sk-ant-... (server's own; used in `hosted` AI mode)
  OPENAI_API_KEY           — sk-... (server's own)
  GOOGLE_API_KEY           — AIza... (server's own)
  RESEND_API_KEY           — re_... (magic-link email sender)
  FROM_EMAIL               — noreply@<your-domain> (default: archhub-cloud.fly.dev)
  PUBLIC_URL               — https://<your-host> (default: archhub-cloud.fly.dev)
  DESKTOP_REDIRECT_BASE    — http://127.0.0.1   (clients only ever use loopback)

Optional:
  DATABASE_URL             — sqlite path; defaults to ./archhub_cloud.db
  TRIAL_MESSAGES           — 30
  RATE_LIMIT_PER_MIN       — 30
  GOOGLE_OAUTH_CLIENT_ID     — Sign in with Google OAuth client id (empty → disabled)
  GOOGLE_OAUTH_CLIENT_SECRET — Sign in with Google OAuth client secret (server-side only)
  GOOGLE_OAUTH_REDIRECT      — OAuth callback URL (default {PUBLIC_URL}/v1/auth/google/callback)
  BILLING_PROVIDER         — "stripe" (default) | "polar"
  POLAR_ACCESS_TOKEN       — Polar.sh API key (when BILLING_PROVIDER=polar)
  POLAR_WEBHOOK_SECRET     — Polar.sh webhook signing key
  POLAR_PRODUCT_SOLO       — Polar.sh product UUID for Solo tier
  POLAR_PRODUCT_STUDIO     — Polar.sh product UUID for Studio tier
  POLAR_PRODUCT_FIRM       — Polar.sh product UUID for Firm tier
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:
    pass


_SENTINEL: object = object()


def _req(name: str, default = _SENTINEL) -> str:
    """Read an env var.

    - `_req("X")` — REQUIRED in production. Missing/empty raises at boot
      when ENV=production. Empty-string in dev.
    - `_req("X", "default")` — OPTIONAL with a default. Caller has
      explicitly said empty/missing is fine; production also tolerates.

    Bug 2026-05-24: the prior signature `_req(name, default=None)` made
    `_req("POLAR_*", "")` raise in prod because v=="" triggered the raise
    even though caller passed "" as default. The sentinel fix distinguishes
    "no default supplied" from "explicit empty default".
    """
    v = os.environ.get(name)
    if v is not None:
        # Tolerate a leading UTF-8 BOM + stray edge whitespace/newlines in
        # the value. `fly secrets set` via a piped/imported value can
        # prepend a BOM (this repo hit exactly that 2026-06-22 with an API
        # key), which silently corrupts an otherwise-correct secret — e.g.
        # a BOM on GOOGLE_OAUTH_CLIENT_SECRET makes Google reject the token
        # exchange with invalid_client. OAuth/API secrets, ids, URLs and
        # price ids never carry meaningful edge whitespace, so stripping is
        # purely corrective and fixes the whole class at the source.
        v = v.lstrip("﻿").strip()
    if v is None or v == "":
        if default is not _SENTINEL:
            return default  # type: ignore[return-value]
        if os.environ.get("ENV") == "production":
            raise RuntimeError(f"env var {name} required in production")
        return ""
    return v


# NOTE (gap 4, 2026-05-31): the auth/billing/email secrets below read as
# OPTIONAL-with-empty-default so `import config` NEVER raises at import time
# — even when ENV=production with a key missing. Enforcement moved to
# `assert_production_ready()` (called from main's startup hook), which fails
# loud naming EVERY missing key at once instead of a cryptic single-key
# import crash. This keeps /healthz reachable and import side-effect-free,
# while making a half-configured prod box refuse to finish booting. In dev
# (ENV unset) these were already "" — behavior there is unchanged.
STRIPE_SECRET_KEY     = _req("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = _req("STRIPE_WEBHOOK_SECRET", "")
# Model C price IDs. Per tier: a monthly per-seat price + an annual
# (−20%) per-seat price. PLACEHOLDERS until the founder creates the real
# Stripe Products/Prices and sets these via `fly secrets set` (see the
# REPORT's "founder's one step"). Empty in dev/tests — billing.py treats
# an empty price id as "checkout unavailable" rather than crashing.
STRIPE_PRICE_SOLO          = _req("STRIPE_PRICE_SOLO", "")
STRIPE_PRICE_SOLO_ANNUAL   = _req("STRIPE_PRICE_SOLO_ANNUAL", "")
STRIPE_PRICE_STUDIO        = _req("STRIPE_PRICE_STUDIO", "")
STRIPE_PRICE_STUDIO_ANNUAL = _req("STRIPE_PRICE_STUDIO_ANNUAL", "")
STRIPE_PRICE_FIRM          = _req("STRIPE_PRICE_FIRM", "")
STRIPE_PRICE_FIRM_ANNUAL   = _req("STRIPE_PRICE_FIRM_ANNUAL", "")
# One-time price for a hosted-AI credit pack ($10 → 1,000 messages).
STRIPE_PRICE_CREDIT_PACK   = _req("STRIPE_PRICE_CREDIT_PACK", "")

ANTHROPIC_API_KEY = _req("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY    = _req("OPENAI_API_KEY", "")
GOOGLE_API_KEY    = _req("GOOGLE_API_KEY", "")
# NVIDIA NIM (OpenAI-compatible) — a strong FREE tool-calling model. Used as
# (a) the founder-cockpit AGENT model and (b) the zero-config FREE_PROVIDER
# default for ALL users (#64) once NVIDIA_API_KEY is set. Accepts a raw key
# OR an `op://...` reference resolved at call time by the same shim every
# other secret uses — never inline a key in code.
NVIDIA_API_KEY    = _req("NVIDIA_API_KEY", "")
NVIDIA_BASE_URL   = _req("NVIDIA_BASE_URL",
                         "https://integrate.api.nvidia.com/v1").strip().rstrip("/")
NVIDIA_MODEL      = _req("NVIDIA_MODEL", "meta/llama-3.3-70b-instruct").strip()

RESEND_API_KEY = _req("RESEND_API_KEY", "")
# PUBLIC_URL defaults to the Fly.io subdomain so the backend works
# WITHOUT requiring a custom domain to be purchased/configured first.
# Override via `flyctl secrets set PUBLIC_URL=https://cloud.archhub.io`
# once the user's own DNS is wired up.
PUBLIC_URL     = _req("PUBLIC_URL", "https://archhub-cloud.fly.dev")
# FROM_EMAIL — Resend will reject sends from unverified domains. Fly's
# *.fly.dev subdomain isn't verifiable on Resend, so we keep the
# branded sender BUT require the user verify ownership of the parent
# domain in Resend's dashboard before live email goes out.
FROM_EMAIL     = _req("FROM_EMAIL", "noreply@archhub.io")

# ── Sign in with Google (OAuth2 / OpenID Connect) ─────────────────────
# OPTIONAL + ADDITIVE. These are the OAuth *client* credentials for the
# "Sign in with Google" flow — DISTINCT from GOOGLE_API_KEY above (that is
# the server's Gemini inference key, never reused for OAuth). When EITHER
# the client id OR the client secret is empty (the CURRENT deployment),
# Google login is DISABLED: the /v1/auth/google/* routes return a clean
# 503 {error:"google_login_unconfigured"} and nothing else changes. The
# founder enables it later with:
#   fly secrets set GOOGLE_OAUTH_CLIENT_ID=<id> \
#                   GOOGLE_OAUTH_CLIENT_SECRET=<secret> -a archhub-cloud
# The client SECRET is server-side only — it never reaches the desktop
# client and never appears in the authorization URL.
GOOGLE_OAUTH_CLIENT_ID     = _req("GOOGLE_OAUTH_CLIENT_ID", "")
GOOGLE_OAUTH_CLIENT_SECRET = _req("GOOGLE_OAUTH_CLIENT_SECRET", "")
# Redirect URI Google calls back after consent. MUST exactly match one of
# the "Authorized redirect URIs" registered on the OAuth client in the
# Google Cloud console. Defaults to this backend's own callback under
# PUBLIC_URL so the founder only has to register that one URL. (Defined
# AFTER PUBLIC_URL so the default can reference it.)
GOOGLE_OAUTH_REDIRECT      = _req(
    "GOOGLE_OAUTH_REDIRECT",
    PUBLIC_URL.rstrip("/") + "/v1/auth/google/callback",
)


def google_login_enabled() -> bool:
    """True only when BOTH OAuth client credentials are configured.

    Single source of truth for the disabled-when-unconfigured contract:
    google_auth + main's routes gate on this, so an unset id OR secret
    keeps Sign in with Google fully dark (503) without touching any other
    flow. Magic-link / PKCE are entirely independent of this."""
    return bool(GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET)


# ── Cross-domain website sign-in return (founder, 2026-06-22) ─────────
# The marketing site (archhub.io) signs users in by bouncing auth through
# THIS cloud backend (magic-link + Google both finish on a cloud route).
# To land the user back ON archhub.io signed-in, /auth/return must be
# allowed to 302 the one-time code to the WEBSITE origin — not only to the
# desktop's loopback. This is the FIXED allowlist of website origins it may
# return to. It is NOT an open redirect: only these exact, scheme+host
# matched origins are accepted; an arbitrary/attacker host, a path, a
# protocol-relative "//evil", or any non-https origin is rejected.
#
# Override per-deploy with WEBSITE_RETURN_ORIGINS (comma-separated full
# origins, e.g. "https://archhub.io,https://archhub-web.fly.dev"). The
# default carries the two known production website origins so cross-domain
# sign-in works out of the box.
def _origin_set(env_name: str, default: tuple[str, ...]) -> frozenset[str]:
    raw = _req(env_name, "").strip()
    if not raw:
        items = default
    else:
        items = tuple(p.strip() for p in raw.split(",") if p.strip())
    # Normalise: lower-case scheme+host, drop a trailing slash. We store the
    # canonical ORIGIN (scheme://host[:port]) so comparison is exact.
    out: set[str] = set()
    for it in items:
        out.add(it.rstrip("/").lower())
    return frozenset(out)


WEBSITE_RETURN_ORIGINS: frozenset[str] = _origin_set(
    "WEBSITE_RETURN_ORIGINS",
    ("https://archhub.io", "https://archhub-web.fly.dev"),
)


def is_allowed_website_return_origin(origin: str) -> bool:
    """True iff `origin` exactly matches one of the FIXED website origins
    allowed as a cross-domain sign-in return target.

    `origin` is the scheme://host[:port] form (no path). Comparison is
    case-insensitive on scheme+host and ignores a trailing slash, but is
    otherwise EXACT — there is no suffix/substring match, so
    "https://archhub.io.evil.com" or "https://evil.com" never passes."""
    if not origin:
        return False
    return origin.rstrip("/").lower() in WEBSITE_RETURN_ORIGINS


def canonical_website_return_origin(origin: str) -> str:
    """If `origin` matches an allowlisted website origin, return the FIXED
    canonical value FROM THE ALLOWLIST CONSTANT (WEBSITE_RETURN_ORIGINS) —
    never the caller's string. Otherwise return "".

    This is the open-redirect-safe resolver: the returned value's data flow
    originates in the fixed config set, not in the (user-supplied) `origin`
    argument, so a redirect built from it carries no tainted data into the
    Location header. `origin` is used only as a lookup key for an exact match.
    """
    if not origin:
        return ""
    key = origin.rstrip("/").lower()
    # Return the actual stored allowlist member (a constant), selected by exact
    # match — not the argument. WEBSITE_RETURN_ORIGINS is already normalised to
    # canonical lower-cased origins, so the stored member IS the value to emit.
    for allowed in WEBSITE_RETURN_ORIGINS:
        if allowed == key:
            return allowed
    return ""


# Billing provider — Stripe (direct, requires KYC) OR Polar.sh (MoR;
# they handle tax + chargebacks; ~4% + $0.40 vs Stripe's 2.9% + $0.30).
# Polar signup is ~10 min vs Stripe's 30-120 min KYC verification.
BILLING_PROVIDER = _req("BILLING_PROVIDER", "stripe").lower().strip()
POLAR_ACCESS_TOKEN   = _req("POLAR_ACCESS_TOKEN", "")
POLAR_WEBHOOK_SECRET = _req("POLAR_WEBHOOK_SECRET", "")
POLAR_PRODUCT_SOLO          = _req("POLAR_PRODUCT_SOLO", "")
POLAR_PRODUCT_SOLO_ANNUAL   = _req("POLAR_PRODUCT_SOLO_ANNUAL", "")
POLAR_PRODUCT_STUDIO        = _req("POLAR_PRODUCT_STUDIO", "")
POLAR_PRODUCT_STUDIO_ANNUAL = _req("POLAR_PRODUCT_STUDIO_ANNUAL", "")
POLAR_PRODUCT_FIRM          = _req("POLAR_PRODUCT_FIRM", "")
POLAR_PRODUCT_FIRM_ANNUAL   = _req("POLAR_PRODUCT_FIRM_ANNUAL", "")
POLAR_PRODUCT_CREDIT_PACK   = _req("POLAR_PRODUCT_CREDIT_PACK", "")

# ── Persistent data dir (Fly volume vs local) ─────────────────────────
# On Fly.io the app runs with a volume mounted at /data (see fly.toml
# `[[mounts]] destination = '/data'`). The SQLite DB + per-user brain
# replicas MUST live on that volume or they're wiped on every redeploy
# (the rest of the container filesystem is ephemeral). Locally (no Fly
# env) we keep the historical paths so dev + the test-suite are
# unaffected and existing local data is never moved.
#
# Resolution precedence (highest first):
#   1. explicit DATABASE_URL / REPLICAS_ROOT env  — operator override, always wins
#   2. DATA_DIR env                                — point the data dir anywhere
#   3. on Fly (FLY_APP_NAME / FLY_MACHINE_ID set)  — default to /data
#   4. local default                               — ./archhub_cloud.db +
#                                                     cloud_backend/data/replicas
# This is env-driven + safe both ways: a missing Fly env can never make
# the local box write to /data, and a present one can never make Fly
# write to the ephemeral ./ path.
_BACKEND_DIR = Path(__file__).resolve().parent


def _on_fly() -> bool:
    """True when running inside a Fly.io machine. Fly injects these env
    vars into every machine; we treat either as the signal."""
    return bool(os.environ.get("FLY_APP_NAME")
                or os.environ.get("FLY_MACHINE_ID"))


def _data_dir() -> Path:
    """The directory that holds persistent state (DB + replicas).

    Explicit DATA_DIR wins; else /data on Fly; else the local backend dir
    (so cloud_backend/data/replicas + ./archhub_cloud.db resolve as before)."""
    explicit = os.environ.get("DATA_DIR", "").strip()
    if explicit:
        return Path(explicit)
    if _on_fly():
        return Path("/data")
    return _BACKEND_DIR


DATA_DIR = _data_dir()


def _default_database_url() -> str:
    """SQLite path default. On Fly (or an explicit DATA_DIR) the DB lives
    under the persistent volume; locally it stays the historical
    ./archhub_cloud.db (CWD-relative, unchanged for dev + tests)."""
    if os.environ.get("DATA_DIR", "").strip() or _on_fly():
        return str(DATA_DIR / "archhub_cloud.db")
    return "./archhub_cloud.db"


# An explicit DATABASE_URL env always wins (the test-suite + operator
# overrides rely on this); otherwise we use the data-dir-aware default.
DATABASE_URL      = _req("DATABASE_URL", _default_database_url())

# Per-user brain replica root. On Fly (or explicit DATA_DIR) the replicas
# live under the persistent volume at <DATA_DIR>/replicas (e.g.
# /data/replicas) so they survive redeploys. Locally they stay at the
# historical cloud_backend/data/replicas. brain_replica reads this at
# import via config; an explicit REPLICAS_ROOT env always overrides.
def _default_replicas_root() -> str:
    if os.environ.get("DATA_DIR", "").strip() or _on_fly():
        return str(DATA_DIR / "replicas")
    return str(_BACKEND_DIR / "data" / "replicas")


REPLICAS_ROOT     = _req("REPLICAS_ROOT", _default_replicas_root())

TRIAL_MESSAGES    = int(_req("TRIAL_MESSAGES", "30"))
RATE_LIMIT_PER_MIN = int(_req("RATE_LIMIT_PER_MIN", "30"))

# Memory/training: number of approved samples before the Train stage
# unlocks. Default 100 — below that we don't waste GPU minutes training
# on too-small a dataset. Override per-deploy with TRAIN_READY_THRESHOLD.
TRAIN_READY_THRESHOLD = int(_req("TRAIN_READY_THRESHOLD", "100"))

# ══════════════════════════════════════════════════════════════════════
#  MODEL C — the canonical pricing source (founder-approved 2026-05-31)
# ══════════════════════════════════════════════════════════════════════
# Spec: docs/prototypes/pricing-model-C-hybrid-2026-05-31.html
#
#   • Per-seat base for the app + connectors + brain + sync.
#   • AI is DECOUPLED, chosen per workspace:
#       - byo_key  → user supplies their LLM key; our hosted AI cost = $0;
#                    NO hosted message quota.
#       - hosted   → we run the LLM; metered against credit packs.
#   • Tiers:
#       Solo   $19/mo,        exactly 1 seat.
#       Studio $39/seat/mo,   seats à la carte (min 1, add/remove anytime).
#       Firm   $29/seat/mo,   volume per-seat, minimum 10 seats, + SSO/audit.
#   • Annual billing: −20% on every tier (ANNUAL_DISCOUNT).
#   • Hosted credit packs: $10 = 1,000 messages, top-up anytime, roll
#     over 60 days (CREDIT_PACK).
#
# This typed structure is THE source. `PLAN_PRICE_IDS`, `PLAN_SEATS`,
# `PROXY_ENABLED_PLANS`, and `PLAN_QUOTAS` below are DERIVED from it (or
# kept as thin compatibility shims) so there is exactly one place a
# number lives. extract_pricing.py + the pricing page read `PLANS` via
# the `public_pricing()` accessor — never a scraped docstring.

# AI mode per workspace. Default byo_key keeps launch cost near zero.
AI_MODES: tuple[str, ...] = ("byo_key", "hosted")
DEFAULT_AI_MODE = "byo_key"

# Annual billing discount applied to every per-seat base price.
ANNUAL_DISCOUNT = 0.20   # −20%

# Hosted-AI credit pack. One purchase grants `messages` credits that
# decrement one-per-message in `hosted` mode and expire `rollover_days`
# after purchase.
CREDIT_PACK: dict[str, int] = {
    "price_usd":     10,
    "messages":      1000,
    "rollover_days": 60,
}

# The three tiers. `price_*` are USD/seat/month (Solo's single seat IS
# the whole price). `min_seats` enforces the FLOOR at checkout + every
# seat change (Firm = 10; Solo's max also pins it at 1). `default_seats`
# is what a NEW company of this tier is provisioned with (Studio ships a
# 5-seat team starter; Firm starts at its 10-seat minimum) — seats then
# move à la carte from there, never below min_seats. `max_seats` caps
# Solo at its single seat. `is_company` flags the per-seat / multi-member
# plans that get a `companies` row (Solo bills on the per-user path).
# `price_id` / `price_id_annual` resolve to the configured Stripe (or
# Polar) ids — empty until the founder sets them.
PLANS: dict[str, dict] = {
    "solo": {
        "name":            "Solo",
        "price_per_seat":  19,
        "min_seats":       1,
        "default_seats":   1,
        "max_seats":       1,
        "is_company":      False,
        "sso":             False,
        "blurb":           "Individual architect / freelancer.",
        "price_id":        STRIPE_PRICE_SOLO,
        "price_id_annual": STRIPE_PRICE_SOLO_ANNUAL,
    },
    "studio": {
        "name":            "Studio",
        "price_per_seat":  39,
        "min_seats":       1,
        "default_seats":   5,
        "max_seats":       None,
        "is_company":      True,
        "sso":             False,
        "blurb":           "A practice / project team — seats à la carte.",
        "price_id":        STRIPE_PRICE_STUDIO,
        "price_id_annual": STRIPE_PRICE_STUDIO_ANNUAL,
    },
    "firm": {
        "name":            "Firm",
        "price_per_seat":  29,
        "min_seats":       10,
        "default_seats":   10,
        "max_seats":       None,
        "is_company":      True,
        "sso":             True,
        "blurb":           "Large firm / enterprise — volume per-seat, 10+ seats, SSO + audit.",
        "price_id":        STRIPE_PRICE_FIRM,
        "price_id_annual": STRIPE_PRICE_FIRM_ANNUAL,
    },
}


def annual_price_per_seat(tier: str) -> float:
    """Per-seat MONTHLY-equivalent price on annual billing (−20%).

    e.g. Studio $39 → $31.20/seat/mo billed yearly. Rounded to cents.
    Single source for the annual maths so the page + tests agree.
    """
    base = PLANS[tier]["price_per_seat"]
    return round(base * (1.0 - ANNUAL_DISCOUNT), 2)


def annual_total_per_seat(tier: str) -> float:
    """Per-seat ANNUAL total on annual billing (12 × the discounted
    monthly-equivalent). e.g. Studio $31.20 × 12 = $374.40/seat/yr."""
    return round(annual_price_per_seat(tier) * 12, 2)


def stripe_price_id(tier: str, *, annual: bool = False) -> str:
    """Resolve the configured Stripe price id for a tier + cadence."""
    p = PLANS.get(tier)
    if not p:
        return ""
    return (p["price_id_annual"] if annual else p["price_id"]) or ""


def clamp_seats(tier: str, seats: int) -> int:
    """Clamp a requested seat count to the tier's [min_seats, max_seats].

    Firm's min of 10 + Solo's hard cap of 1 are enforced HERE so every
    caller (checkout, seat add/remove) shares one rule and can't drift."""
    p = PLANS.get(tier)
    if not p:
        return max(1, int(seats))
    s = int(seats)
    lo = int(p["min_seats"])
    hi = p["max_seats"]
    s = max(lo, s)
    if hi is not None:
        s = min(int(hi), s)
    return s


def public_pricing() -> dict:
    """Structured, env-secret-free snapshot of Model C for the marketing
    site + desktop pricing dialog. extract_pricing.py calls THIS — never
    parses a docstring. Contains only display data (no price-id secrets,
    no Stripe keys), so it's safe to serialise into a committed JSON."""
    tiers = []
    for tid, p in PLANS.items():
        tiers.append({
            "id":                    tid,
            "name":                  p["name"],
            "price_per_seat":        p["price_per_seat"],
            "price_per_seat_annual": annual_price_per_seat(tid),
            "min_seats":             p["min_seats"],
            "max_seats":             p["max_seats"],
            "is_company":            p["is_company"],
            "sso":                   p["sso"],
            "blurb":                 p["blurb"],
            "price_id_configured":   bool(stripe_price_id(tid)
                                          if BILLING_PROVIDER != "polar"
                                          else POLAR_PRODUCT_IDS.get(tid)),
        })
    return {
        "model":           "C",
        "currency":        "usd",
        "annual_discount": ANNUAL_DISCOUNT,
        "ai_modes":        list(AI_MODES),
        "default_ai_mode": DEFAULT_AI_MODE,
        "credit_pack":     dict(CREDIT_PACK),
        "tiers":           tiers,
    }


# ── Derived compatibility shims ───────────────────────────────────────
# Older code (db.py, companies.py, proxy.py, main.py) + the existing
# test-suite reference these dicts. They are now DERIVED from PLANS so
# Model C stays the single source — change a price in PLANS and these
# follow. Keeping them avoids a needless blast-radius rewrite (one
# canonical source, many readers — the LIBRARY-FIRST / one-system rule).

# Per-tier monthly Stripe price ids (monthly cadence). Used by the
# webhook's price-id → tier reverse lookup + per-user checkout.
PLAN_PRICE_IDS: dict[str, str] = {
    tid: PLANS[tid]["price_id"] for tid in PLANS
}

# Polar.sh product UUID per tier — populated when BILLING_PROVIDER=polar.
POLAR_PRODUCT_IDS: dict[str, str] = {
    "solo":   POLAR_PRODUCT_SOLO,
    "studio": POLAR_PRODUCT_STUDIO,
    "firm":   POLAR_PRODUCT_FIRM,
}

# Default seat count a company is provisioned with = the tier's
# `default_seats` (Studio 5-seat team starter, Firm 10 = its minimum).
# Solo is single-user and isn't a "company" plan, so it's excluded here
# (companies.py rejects a Solo company). Seats then move à la carte from
# this default, never below min_seats (config.clamp_seats enforces it).
PLAN_SEATS: dict[str, int] = {
    tid: int(PLANS[tid]["default_seats"])
    for tid in PLANS if PLANS[tid]["is_company"]
}

# ── Hosted-AI metering (Model C) ──────────────────────────────────────
# Hosted message allowance is no longer a per-tier monthly bucket — it's
# credit-pack-funded (CREDIT_PACK), tracked per workspace in
# db.credit_balance(). PLAN_QUOTAS is retained ONLY as the trial floor +
# a fair-use ceiling so the legacy per-user/company `msg_limit` columns
# (and their tests) keep working; real hosted billing flows through
# credits. A paid tier in `byo_key` mode (the default) has NO hosted
# limit at all — the user's own key carries it.
PLAN_QUOTAS: dict[str, int] = {
    "trial":  TRIAL_MESSAGES,
    "solo":   1_000_000,     # fair-use; hosted billing is credit-pack based
    "studio": 1_000_000,
    "firm":   1_000_000,
}

# ── FREE DEFAULT tier (founder, 2026-06-22 — zero-config, no 402) ─────
# THE default experience: a strong free/cheap model served BY OUR cloud
# to EVERY user with NO BYO key and NO paid plan — so the composer works
# the moment someone installs ArchHub, zero config. This replaces the old
# `byo_key_required` 402 for the no-key case (BYO + hosted-credit paths
# stay intact and still win when configured).
#
# How it works: we proxy to a free OpenAI-compatible endpoint (Groq's
# free tier by default — fast Llama/Qwen models; or any OpenAI-shape base
# such as OpenRouter ":free" models or Google AI Studio's free Gemini).
# The provider's free key lives SERVER-SIDE (this one key serves all
# users), never on the user's machine — that's what makes it zero-config.
#
# `FREE_DEFAULT_ENABLED` (default ON) is the master switch. When ON and a
# request arrives with no BYO key + not hosted, we serve `ARCHHUB_FREE_MODEL`
# via the free provider instead of returning 402. The free tier is metered
# against the legacy per-actor `msg_used` fair-use ceiling (so it can't be
# abused) but NEVER touches hosted credits — free is free.
#
# Secrets: `FREE_PROVIDER_API_KEY` accepts a raw key OR an `op://...`
# reference resolved at launch by the same op→keyring→env shim the rest of
# ArchHub uses — NEVER inline the key in code. If the chosen provider needs
# a (free-account) key and none is configured, the free tier degrades to
# an honest 402 `free_unavailable` (BYO still works) rather than crashing.
FREE_DEFAULT_ENABLED = _req("FREE_DEFAULT_ENABLED", "1").strip() in (
    "1", "true", "True", "yes")
# Provider id for the free tier. Any OpenAI-compatible chat-completions
# endpoint works: "groq" (default), "openrouter", "google", or "custom".
FREE_PROVIDER = _req("FREE_PROVIDER", "nvidia").strip().lower()
# The model id served for free. Sensible default per provider; override
# with ARCHHUB_FREE_MODEL. NVIDIA NIM's Llama-3.3-70B is strong + free +
# fast (founder steer #64); Groq's is the legacy fallback.
_FREE_MODEL_DEFAULTS = {
    "nvidia":     "meta/llama-3.3-70b-instruct",
    "groq":       "llama-3.3-70b-versatile",
    "openrouter": "meta-llama/llama-3.3-70b-instruct:free",
    "google":     "gemini-2.5-flash",
    "custom":     "llama-3.3-70b-versatile",
}
ARCHHUB_FREE_MODEL = _req(
    "ARCHHUB_FREE_MODEL",
    _FREE_MODEL_DEFAULTS.get(FREE_PROVIDER, "llama-3.3-70b-versatile"),
).strip()
# OpenAI-compatible base URL for the free provider. Defaulted per provider
# so the founder only needs to set the KEY, not the URL.
_FREE_BASE_DEFAULTS = {
    "nvidia":     "https://integrate.api.nvidia.com/v1",
    "groq":       "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "google":     "https://generativelanguage.googleapis.com/v1beta/openai",
    "custom":     "",
}
FREE_PROVIDER_BASE_URL = _req(
    "FREE_PROVIDER_BASE_URL",
    _FREE_BASE_DEFAULTS.get(FREE_PROVIDER, ""),
).strip().rstrip("/")
# Free provider API key — raw OR op:// reference (resolved at launch by the
# secret shim; see resolve_secret below). One server-side key serves every
# user. Empty → free tier returns an honest free_unavailable 402 (BYO
# still works) so a missing key never crashes the box.
FREE_PROVIDER_API_KEY = _req("FREE_PROVIDER_API_KEY", "")


# ── BRAIN PORTAL tier gating (founder, 2026-06-22 — per-tier read access) ──
# The cloud brain portal (`/brain` + GET /v1/brain/facts|search|stats) reads
# the caller's OWN per-user replica (cloud_backend/data/replicas/<user_id>/
# brain.db — the same store /v1/brain/sync writes). Access is gated by the
# user's `plan` (db.users.plan: trial/solo/studio/firm), mirroring the
# existing PROXY_ENABLED_PLANS "paid feature" gate rather than minting a new
# concept.
#
# Every tier may READ their own synced facts (owner-only — never another
# user's brain). What the tier changes is HOW MUCH + WHICH features:
#   * BRAIN_FACT_CAPS — max facts a `GET /v1/brain/facts` / search returns
#     for the tier (real enforcement: the endpoint clamps `limit` to this).
#   * BRAIN_SEARCH_PLANS — tiers allowed to run server-side search. trial is
#     excluded → search returns a typed 402 `upgrade_required` (a real
#     limit, not cosmetic; the desktop/web surfaces show the upgrade CTA).
#   * BRAIN_SHARED_SCOPE_PLANS — tiers that may union firm/community shared
#     replicas into their list (studio/firm); solo/trial see USER scope only.
#   * BRAIN_EXPORT_PLANS — tiers allowed dataset export of their brain.
# Tune via env (comma-separated plan ids / "tier:cap" pairs) so the caps
# live in config, never hardcoded in the endpoint.
def _plan_set(env_name: str, default: set[str]) -> set[str]:
    raw = _req(env_name, "").strip()
    if not raw:
        return set(default)
    return {p.strip().lower() for p in raw.split(",") if p.strip()}


def _cap_map(env_name: str, default: dict[str, int]) -> dict[str, int]:
    raw = _req(env_name, "").strip()
    if not raw:
        return dict(default)
    out = dict(default)
    for pair in raw.split(","):
        if ":" not in pair:
            continue
        tier, _, cap = pair.partition(":")
        try:
            out[tier.strip().lower()] = int(cap)
        except ValueError:
            continue
    return out


# Per-tier ceiling on how many facts a single read returns. Trial is a
# read-only taste (100 most-recent); paid tiers get the full working set.
BRAIN_FACT_CAPS: dict[str, int] = _cap_map("BRAIN_FACT_CAPS", {
    "trial":  100,
    "solo":   500,
    "studio": 1000,
    "firm":   2000,
})
# Absolute hard ceiling no tier (or env override) can exceed — defence so a
# misconfigured env can't ask the replica for an unbounded scan.
BRAIN_FACT_CAP_MAX: int = int(_req("BRAIN_FACT_CAP_MAX", "5000"))
# Tiers allowed to run server-side brain search (trial excluded → upgrade).
BRAIN_SEARCH_PLANS: set[str] = _plan_set(
    "BRAIN_SEARCH_PLANS", {"solo", "studio", "firm"})
# Tiers that may union firm/community shared replicas into their brain view.
BRAIN_SHARED_SCOPE_PLANS: set[str] = _plan_set(
    "BRAIN_SHARED_SCOPE_PLANS", {"studio", "firm"})
# Tiers allowed dataset export of their brain (paid only).
BRAIN_EXPORT_PLANS: set[str] = _plan_set(
    "BRAIN_EXPORT_PLANS", {"solo", "studio", "firm"})


def brain_fact_cap(plan: str | None) -> int:
    """Resolve the per-read fact cap for `plan`, clamped to the hard max.

    Unknown / missing plan falls back to the trial cap (the safe floor)."""
    cap = BRAIN_FACT_CAPS.get((plan or "trial").lower(),
                              BRAIN_FACT_CAPS.get("trial", 100))
    return max(1, min(int(cap), BRAIN_FACT_CAP_MAX))


def brain_can_search(plan: str | None) -> bool:
    return (plan or "trial").lower() in BRAIN_SEARCH_PLANS


def brain_can_shared_scope(plan: str | None) -> bool:
    return (plan or "trial").lower() in BRAIN_SHARED_SCOPE_PLANS


def brain_can_export(plan: str | None) -> bool:
    return (plan or "trial").lower() in BRAIN_EXPORT_PLANS


def _resolve_op_ref(value: str) -> str:
    """Resolve an `op://...` secret reference → plaintext at call time.

    Tries, in order: 1Password CLI (`op read`), Windows/keyring
    (`OP_<SANITISED>` cred or the same env name), then a sanitised env var.
    Returns the raw value unchanged when it is NOT an op:// reference.
    NEVER logs the resolved value. Mirrors the resolver pattern ArchHub's
    dashscope/MCP launch uses so secrets stay out of code + git.
    """
    if not value or not value.startswith("op://"):
        return value
    # 1) 1Password CLI
    try:
        import subprocess
        out = subprocess.run(
            ["op", "read", value],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    # 2) keyring (vault/item from the op path → archhub/<item>)
    try:
        import keyring  # type: ignore
        parts = value[len("op://"):].split("/")
        if len(parts) >= 2:
            svc, item = parts[0], parts[1]
            got = keyring.get_password(svc, item)
            if got:
                return got
    except Exception:
        pass
    # 3) env fallback: op://vault/item/field → OP_VAULT_ITEM_FIELD
    try:
        sanitised = (
            "OP_" + value[len("op://"):].upper()
            .replace("/", "_").replace("-", "_").replace(".", "_")
        )
        env_val = os.environ.get(sanitised)
        if env_val:
            return env_val
    except Exception:
        pass
    return ""   # unresolved op:// → treat as absent (free tier degrades)


def free_provider_key() -> str:
    """The resolved free-provider API key (op:// resolved at call time).

    Thin wrapper over `select_free_model()` so there is exactly ONE place
    that knows how the free key is sourced: the explicit FREE_PROVIDER_API_KEY
    when set, else the NVIDIA→Gemini fallback chain. Returns "" when no
    provider can serve. NEVER logs the key."""
    sel = select_free_model()
    return sel["key"] if sel else ""


# ── ONE-SYSTEM free-model selection (founder #64, 2026-06-22) ─────────
# THE single source of "which free provider can serve a no-key user RIGHT
# NOW". Both the user-facing free proxy path (proxy._serve_free_default /
# list_models / _stream_free, via free_provider_key/free_selected_*) AND the
# founder-cockpit agent (cockpit_agent.reachable_model) call THIS — there is
# no parallel provider-selection logic. Order mirrors the cockpit agent that
# is already proven live:
#   1. NVIDIA NIM  — preferred (strong + free tool-use) when NVIDIA_API_KEY
#      (or an explicit FREE_PROVIDER_API_KEY when FREE_PROVIDER=nvidia) is set.
#   2. Gemini free — reachable TODAY via the already-deployed GOOGLE_API_KEY
#      over its OpenAI-compatible endpoint (no new secret needed).
#   3. The explicitly-configured FREE_PROVIDER (groq/openrouter/custom/…) when
#      its own FREE_PROVIDER_API_KEY is set — so an operator override still
#      works exactly as before.
# Returns {provider, base_url, model, key} or None when NOTHING is reachable
# (callers then honestly degrade: proxy → byo_key_required 402; cockpit →
# offline keyword router). Secrets are resolved at call time via the op://
# shim and are NEVER logged.
def _gemini_free_base() -> str:
    return "https://generativelanguage.googleapis.com/v1beta/openai"


def select_free_model() -> dict | None:
    """Pick the free model provider that can serve a request now, or None.

    See the module note above for the order + the ONE-SYSTEM contract. This
    is the canonical selector reused by the cloud free path AND the cockpit
    agent."""
    # 1) Explicit free-provider key wins for the CONFIGURED provider — honours
    #    an operator override (e.g. FREE_PROVIDER=groq + a Groq key) without
    #    forcing the NVIDIA/Gemini chain. NVIDIA is handled in (2)/(3) so the
    #    key-fallback to NVIDIA_API_KEY stays available.
    explicit = _resolve_op_ref(FREE_PROVIDER_API_KEY)
    if explicit and FREE_PROVIDER != "nvidia":
        base = FREE_PROVIDER_BASE_URL or _FREE_BASE_DEFAULTS.get(FREE_PROVIDER, "")
        if base:
            return {"provider": FREE_PROVIDER,
                    "base_url": base.rstrip("/"),
                    "model":    ARCHHUB_FREE_MODEL,
                    "key":      explicit}
    # 2) NVIDIA preferred (the #64 default). Explicit FREE_PROVIDER_API_KEY (when
    #    FREE_PROVIDER=nvidia) OR NVIDIA_API_KEY — one secret lights it up.
    nvidia_key = explicit if FREE_PROVIDER == "nvidia" else ""
    if not nvidia_key:
        nvidia_key = _resolve_op_ref(NVIDIA_API_KEY)
    if nvidia_key:
        base = (FREE_PROVIDER_BASE_URL
                if FREE_PROVIDER == "nvidia" and FREE_PROVIDER_BASE_URL
                else NVIDIA_BASE_URL)
        model = (ARCHHUB_FREE_MODEL if FREE_PROVIDER == "nvidia"
                 else NVIDIA_MODEL)
        return {"provider": "nvidia",
                "base_url": (base or NVIDIA_BASE_URL).rstrip("/"),
                "model":    model,
                "key":      nvidia_key}
    # 3) Gemini free — reachable TODAY via the deployed GOOGLE_API_KEY, no new
    #    secret. This is what lights #64 up for real users right now.
    google_key = (GOOGLE_API_KEY or "").strip()
    if google_key:
        base = (FREE_PROVIDER_BASE_URL
                if FREE_PROVIDER == "google" and FREE_PROVIDER_BASE_URL
                else _gemini_free_base())
        model = (ARCHHUB_FREE_MODEL if FREE_PROVIDER == "google"
                 else _FREE_MODEL_DEFAULTS["google"])
        return {"provider": "google",
                "base_url": base.rstrip("/"),
                "model":    model,
                "key":      google_key}
    return None


def free_selected_base_url() -> str:
    """Base URL of the selected free provider (server-side), or ""."""
    sel = select_free_model()
    return sel["base_url"] if sel else ""


def free_selected_model() -> str:
    """Model id the free tier will actually serve. Falls back to the
    configured ARCHHUB_FREE_MODEL when nothing is reachable (display only)."""
    sel = select_free_model()
    return sel["model"] if sel else ARCHHUB_FREE_MODEL


def free_selected_provider() -> str:
    """Provider id the free tier will actually use (e.g. 'google' today,
    'nvidia' once keyed), or "" when nothing is reachable."""
    sel = select_free_model()
    return sel["provider"] if sel else ""


def free_default_available() -> bool:
    """True when the free default tier can actually serve a request.

    Requires the master switch ON + a reachable provider (NVIDIA or Gemini
    or an explicitly-keyed FREE_PROVIDER). With ONLY GOOGLE_API_KEY set this
    returns True via the Gemini free path — that's what makes #64 light up
    today with no new secret. When NOTHING is reachable it returns False and
    the proxy honestly degrades to the BYO path (never a fake).
    """
    # Founder runtime override (cockpit command surface). The founder can
    # toggle the free default ON/OFF live from the cockpit without a redeploy;
    # that persisted flag wins over the env default. ONE-SYSTEM: same flag the
    # cockpit writes via db.set_founder_flag('free_default', ...). Read
    # defensively so a missing table / import cycle never breaks serving.
    try:
        import db as _db
        _ov = _db.get_founder_flag("free_default")
        if _ov is not None:
            if str(_ov).strip().lower() in ("0", "false", "no", "off"):
                return False
            # explicit ON falls through to the capability checks below
    except Exception:
        pass
    if not FREE_DEFAULT_ENABLED:
        return False
    # A provider is reachable iff the canonical selector resolves one. This
    # covers NVIDIA (keyed), Gemini (GOOGLE_API_KEY), and an explicitly-keyed
    # FREE_PROVIDER — all through the ONE selector.
    if select_free_model() is not None:
        return True
    # Custom/keyless relay: a bare base URL with no key is enough (the selector
    # returns None for it since it has no key to carry).
    if FREE_PROVIDER == "custom" and FREE_PROVIDER_BASE_URL:
        return True
    return False


# ── Cloud LLM proxy gate (founder, 2026-05-24; Model C 2026-05-31) ────
# Hosted LLM access requires (a) a paid tier and (b) the workspace in
# `hosted` AI mode with credits. byo_key workspaces never hit the proxy
# for hosted inference — they paste their own key. All three paid tiers
# CAN run hosted (it's a per-workspace choice now, not a tier perk), so
# every non-trial plan is proxy-eligible.
PROXY_ENABLED_PLANS: set[str] = {"solo", "studio", "firm"}

# Master kill-switch. Until the founder funds prepaid balances on the
# upstream providers AND flips this to a truthy value, the proxy
# returns 402 BYO_REQUIRED for every request — so accidental traffic
# (or a leaked key) cannot burn down the dev balance. Flip live with
# `flyctl secrets set PROXY_LIVE=1 -a archhub-cloud` once the
# Anthropic / OpenAI / Google balances are loaded.
PROXY_LIVE = _req("PROXY_LIVE", "0").strip() in ("1", "true", "True", "yes")


# ── Production readiness gate (startup) ──────────────────────────────
# fly.toml + Dockerfile deliberately leave ENV unset so /healthz stays
# green before secrets are uploaded — `_req` therefore does NOT raise at
# import time in that window. The risk: someone sets ENV=production but
# forgets a key, and the app boots anyway with that secret defaulting to
# "" (silent auth/email/billing breakage). This gate closes that: it is
# called from the FastAPI startup hook and, when ENV=production, FAILS
# LOUD naming EVERY missing required secret at once. It does nothing when
# ENV is unset (the intended pre-secrets dev-tolerant boot).
def is_production() -> bool:
    return os.environ.get("ENV", "").strip().lower() == "production"


def _missing_required_keys() -> list[str]:
    """Return the names of required secrets that are unset/empty.

    Auth-critical + email keys are ALWAYS required in production. Billing
    keys depend on the configured provider (Stripe vs Polar) so we only
    demand the set that the live provider actually uses — never both.
    """
    # Auth + email: the registration/sign-in path cannot function without
    # these. RESEND_API_KEY gates magic-link delivery (gap 5); the LLM
    # proxy keys back /v1/chat for paid tiers.
    required = {
        "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
        "OPENAI_API_KEY": OPENAI_API_KEY,
        "GOOGLE_API_KEY": GOOGLE_API_KEY,
        "RESEND_API_KEY": RESEND_API_KEY,
    }
    if BILLING_PROVIDER == "polar":
        required.update({
            "POLAR_ACCESS_TOKEN": POLAR_ACCESS_TOKEN,
            "POLAR_WEBHOOK_SECRET": POLAR_WEBHOOK_SECRET,
            "POLAR_PRODUCT_SOLO": POLAR_PRODUCT_SOLO,
            "POLAR_PRODUCT_STUDIO": POLAR_PRODUCT_STUDIO,
            "POLAR_PRODUCT_FIRM": POLAR_PRODUCT_FIRM,
        })
    else:  # stripe (default)
        required.update({
            "STRIPE_SECRET_KEY": STRIPE_SECRET_KEY,
            "STRIPE_WEBHOOK_SECRET": STRIPE_WEBHOOK_SECRET,
            "STRIPE_PRICE_SOLO": STRIPE_PRICE_SOLO,
            "STRIPE_PRICE_STUDIO": STRIPE_PRICE_STUDIO,
            "STRIPE_PRICE_FIRM": STRIPE_PRICE_FIRM,
        })
    return sorted(name for name, val in required.items() if not val)


def assert_production_ready() -> None:
    """Raise RuntimeError naming every missing secret when ENV=production.

    No-op when ENV is unset (dev-tolerant boot). Safe to call on every
    startup; called from main's startup hook. Does NOT touch /healthz —
    if this raises, the process never finishes booting, which is the
    intended fail-loud behavior (a half-configured prod box should not
    serve auth/billing traffic).
    """
    if not is_production():
        return
    missing = _missing_required_keys()
    if missing:
        raise RuntimeError(
            "ENV=production but required secret(s) are unset/empty: "
            + ", ".join(missing)
            + ". Set them (e.g. `fly secrets set "
            + "=... ".join(missing) + "=...`) before promoting to "
            "production, or unset ENV to boot in dev-tolerant mode."
        )
