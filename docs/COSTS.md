# ArchHub — cost ledger

> **Design reference — not the roadmap.** The single roadmap is
> [`docs/ROADMAP.md`](ROADMAP.md). This file is the standing record of what
> ArchHub *spends*: every paid service, its purpose, amount, billing cadence,
> next renewal, and last-known balance — with **at-risk** items flagged so a
> lapse or an empty prepaid wallet is seen *before* it breaks production.

**Why this doc exists (FIN-07).** Until now no single artifact listed ArchHub's
subscriptions / renewals / balances — `Financial_Plan.xlsx` is the founder's
*personal* budget, not the project's burn. The 2026-06-15 deep dive had to
reconstruct spend from Gmail + live probes every time. This ledger is that
reconstruction, committed to the repo and kept current, so the answer to "what
are we paying for and when does it renew?" is one file away.

**How balances are kept honest.** A figure here is either a **captured** live
reading (with its source + date) or explicitly marked **unconfirmed** /
**estimate**. We never write a precise number we did not read. For DashScope,
run `python tools/rotate_dashscope.py --balance` (the real
`dashscope.balance` BSS probe, FIN-05) and paste the figure into the row.

**Last reconciled:** 2026-06-17 · Currencies: USD unless noted · AED→USD ≈ 0.272.

---

## Ledger

Legend — **Status:** ✅ healthy · ⚠️ at-risk (lapse/empty/unknown soon) ·
🔴 broken/blocking now · 💤 dormant/optional.

| Service | Purpose | Amount | Cadence | Next renewal | Last-known balance | Status |
|---|---|---|---|---|---|---|
| **Fly.io — `archhub-cloud`** | Production API (`api.archhub.io`, ord region) — auth, billing, provider proxy | Usage-based (~$5–15/mo at idle, shared-cpu-1x) | Monthly (postpaid, card) | Rolling monthly | Unconfirmed — read at fly.io/dashboard → Billing | ✅ |
| **Fly.io — `archhub-web`** | Landing site (`archhub.io`, Astro static) | Usage-based (~$0–5/mo, scales to zero) | Monthly (postpaid, card) | Rolling monthly | Same Fly account as above | ✅ |
| **Namecheap — `archhub.io` domain** | Domain registration (`.io` TLD) | ~$35–40/yr (`.io` renewal) | Annual | **Confirm exact date in Namecheap → Domain List** | n/a (registered, paid) | ⚠️ confirm renewal date — `.io` lapse kills the brand domain |
| **Namecheap — cPanel hosting** | Legacy shared hosting (old DNS zone) | Prepaid term | Annual | **2026-06-17 (today)** | n/a | 💤 **DEFUSED** — DNS migrated to free Namecheap BasicDNS 2026-06-11; hosting may lapse harmlessly. Do NOT renew unless the old cPanel mailbox is still needed. |
| **Namecheap — Private Email** | `@archhub.io` inbound mailbox (founder's) | Trial → paid (~$10–12/yr/mailbox) | Annual after trial | **~2026-06-18 (trial end)** | n/a | ⚠️ **trial ends ~Jun-18** — decide keep-or-drop; dropping it changes the `@` MX (see [`GO_LIVE_CHECKLIST.md`](GO_LIVE_CHECKLIST.md)) |
| **Anthropic API** | Claude models behind the cloud provider-proxy (`PROXY_LIVE=1`) | Prepaid credit (pay-as-you-go) | Top-up | When balance hits 0 | Unconfirmed — console.anthropic.com → Billing | ⚠️ prepaid — **must stay funded or the proxy 4xx's live users** |
| **OpenAI API** | GPT models behind the provider-proxy | Prepaid credit (pay-as-you-go) | Top-up | When balance hits 0 | Unconfirmed — platform.openai.com → Billing | ⚠️ prepaid — fund before relying on it in production |
| **Google AI (Gemini) API** | Gemini models behind the provider-proxy (`GOOGLE_API_KEY`) | Pay-as-you-go (free tier + paid) | Monthly (postpaid) | Rolling monthly | Unconfirmed — aistudio/Cloud Console → Billing | ✅ free tier covers dev; watch paid tier if traffic grows |
| **Alibaba DashScope / Model Studio** | Qwen / Qwen-VL / Wan image+video gen MCP (intl, Singapore region) | Prepaid (pay-as-you-go; Wan i2v ~$0.035/clip, Qwen-Image ~$0.02/img) | Top-up | When balance hits 0 | **Unknown — key DEAD (401), rotation pending-founder.** Probe: `tools/rotate_dashscope.py --balance` | 🔴 **key invalid** — image-gen MCP can't bill; rotate the key + fund, then capture balance (FIN-05) |
| **Resend** | Transactional email (`send.archhub.io`, e.g. auth + receipts) | Free tier (≤3k emails/mo) | Monthly | n/a (free) | Within free tier | ✅ send-only restricted key; bounce-MX on `send.*` not carried (cosmetic) |
| **Stripe** | Payment processing for ArchHub subscriptions (revenue, not a cost) | 2.9% + $0.30 per charge | Per-transaction | n/a | n/a | ✅ live keys + 3 price ids (SOLO/STUDIO/FIRM) + webhook secret set on Fly; never self-purchased |
| **Hostinger VPS `srv748061`** | The Lubb / brain box (`72.61.182.53`, Ubuntu 24.04 KVM2) — separate from Fly | VPS plan (~$5–12/mo equiv, prepaid term) | Monthly/annual term | **Confirm in Hostinger → VPS billing** | n/a (running, ~15 GB used) | ⚠️ confirm renewal — founder-confirmed NOT redundant with Fly |
| **Higgsfield** | Image-gen fallback (`nano_banana_pro`, proven Missoni renders) | Credit/subscription tier | Per credits | n/a | Unconfirmed | 💤 used ad-hoc; not load-bearing for the product |
| **Freepik (incl. Magnific upscale)** | Image upscale + gen fallback (Magnific engine via Freepik MCP) | Credit/subscription tier | Per credits | n/a | Unconfirmed | 💤 used ad-hoc |
| **Magnific (direct)** | Upscale (OAuth MCP) | Subscription | — | n/a | n/a | 💤 OAuth unauthenticated; Freepik path used instead |

---

## At-risk summary (read this first)

These are the rows that bite if ignored. Ordered by urgency:

1. 🔴 **DashScope key is DEAD (401).** The image-gen MCP cannot bill or run.
   Founder regenerates the key in the Model Studio console → store it
   (`python tools/rotate_dashscope.py`) → fund the prepaid balance → capture
   the figure (`python tools/rotate_dashscope.py --balance`). The balance is
   genuinely unreadable until the AccessKey pair is configured (FIN-05).
2. ⚠️ **Namecheap Private Email trial ends ~2026-06-18.** Decide keep-or-drop;
   dropping changes the `@archhub.io` inbound MX.
3. ⚠️ **Prepaid API wallets (Anthropic / OpenAI / DashScope) must stay funded.**
   `PROXY_LIVE=1` means live users hit these — an empty balance is a production
   outage, not a dev annoyance.
4. ⚠️ **Confirm annual renewal dates** for the `.io` domain and the Hostinger
   VPS so neither lapses silently. (cPanel hosting renewal is intentionally
   *not* on this list — its expiry today is defused.)

## Founder-only actions (true boundaries — everything else is automated)

The only cost items that require the founder personally (per the
EXHAUSTIVE-DELIVERY mandate's true-boundary carve-out): **funding prepaid API
balances**, **regenerating the DashScope key**, **the keep/drop call on Private
Email**, and **confirming/renewing** the `.io` domain + Hostinger VPS. Reading
the figures is automated where an API exists (DashScope via `dashscope.balance`);
the rest are console reads behind the founder's own sign-in.

## Capturing the DashScope balance (FIN-05 receipt)

```
# Honest probe — prints the live AvailableAmount + Currency, or the exact
# reason it can't (never a fabricated number):
python tools/rotate_dashscope.py --balance

# It calls the real dashscope.balance connector op, which performs the
# Alibaba BSS OpenAPI QueryAccountBalance call (HMAC-SHA1 signed with a RAM
# AccessKey pair resolved via op://archhub/aliyun/access_key_id +
# access_key_secret). DashScope's own sk- key has NO billing endpoint, so the
# AccessKey pair is required to read spend.
```

When you capture a real figure, paste it into the DashScope row's
*Last-known balance* cell with the date, and flip the Status from 🔴 once the
key is live + funded.
