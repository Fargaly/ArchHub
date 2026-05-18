# ArchHub — Cloud Revival Plan

> **Design reference — not the roadmap.** The single roadmap / source of
> truth is [`docs/ROADMAP.md`](ROADMAP.md). This document is kept for
> architecture & decision rationale only.

> 2026-05-15 · Decision document for Ahmed Fargaly. Supersedes the Fly stack destroyed 2026-05-13.

## Executive summary

Fly died because it cost money serving zero paying users. The revival inverts that: every cloud component is tied to a billing line that covers it. Build a thin **Cloudflare Workers + R2 + Neon Postgres** control plane (≈$0 at 0 users, ≈$140/mo at 100, ≈$1,400/mo at 1,000), spawn **Hetzner CX22 agent boxes per-firm only** (not per-user, not always-on), and make **BYO-key inference the default** so token costs never sit on ArchHub's books. Two paid tiers — **Pro $19/mo** (sync, marketplace, web viewer) and **Studio $59/seat/mo, 3-seat min** (firm canvas, SSO, audit log, agent runner, 5M shared tokens metered after). 90-day rollout ships auth+Stripe first, sync second, marketplace third, multi-tenancy fourth, gating every phase on the prior one producing revenue. No outside capital needed — break-even ~30 paying seats vs ~$80/mo infra, reachable month 4–6. **First action this week: stand up `api.archhub.io` on Cloudflare Workers + Neon with one working endpoint — `GET /v1/me` behind magic-link auth. Nothing else gets built until that exists.**

---

## 1. Cloud architecture (revived)

### What lives where, and why each piece earns its keep

| Layer | Component | Why | Pays for itself via |
|---|---|---|---|
| Desktop | PyQt6 + QtWebEngine binary | Already built | Acquisition surface |
| Edge identity | CF Workers (Hono) at `api.archhub.io` | Auth, JWT, plan, license tokens | Pro / Studio |
| Object store | Cloudflare R2 | Encrypted blob sync, zero egress | Pro |
| Relational store | Neon Postgres (free → Launch $19) | Users, plans, audit, marketplace | Studio |
| Agent runners | Hetzner CX22 ($4.50/mo) **per firm** | Long-running scheduled agents | Bundled in Studio |
| Inference | Anthropic / OpenAI / OpenRouter, **BYO default** | Customer's own bill | Never on our books |
| Inference (managed, opt-in) | Anthropic at-cost + 20% | One-bill convenience | Metered Stripe |
| Stripe | Subs + metered | Revenue | N/A |
| Email | Resend ($0–$20) | Magic-link + receipts | Pro / Studio |
| Errors | Sentry + PostHog free tiers | Observability | N/A |

### Why Cloudflare + Hetzner (not Fly / Modal / Vercel)

Fly bills per-hour for always-on machines an HTTP app idles 95% of. Workers bills per-request (10M free, then $5/10M); R2 has zero egress; Neon autosuspends to $0. Control-plane baseline **$0**. Hetzner CX22 beats Fly shared-cpu ($4.50 vs $7–10/mo) for stateful per-firm boxes. Modal is for spiky GPU; pointless for CPU-bound text agents. Vercel and Render fail the same cost test as Fly.

### Concrete monthly spend

| Component | 0 | 100 | 1,000 | 10,000 |
|---|---|---|---|---|
| CF Workers | $0 | $0 | $5 | $50 |
| R2 (100MB/user) | $0 | $0 | $1.50 | $15 |
| Neon | $0 | $0 | $19 | $69 |
| Hetzner control | $4.50 | $4.50 | $4.50 | $4.50 |
| Hetzner per-firm | $0 | $45 (10) | $450 (100) | $2,250 (500) |
| Resend | $0 | $0 | $20 | $20 |
| Sentry/PostHog | $0 | $0 | $26 | $80 |
| Stripe (~3%) | $0 | $60 | $600 | $6,000 |
| Anthropic (30% opt-in) | $0 | $30 | $300 | $3,000 |
| **Total** | **$4.50** | **~$140** | **~$1,425** | **~$11,500** |
| Revenue (typical mix) | $0 | ~$2K MRR | ~$25K | ~$280K |
| Gross margin | — | 93% | 94% | 96% |

Works only because agent runners are **per-firm** and tokens are **opt-in**.

---

## 2. Identity / profile / settings (cloud-side)

### Schema (8 tables — AEC tool, not a social network)

```
users(id, email, full_name, firm_id, role, stripe_customer_id, plan, period_end)
firms(id, name, stripe_subscription_id, plan, seats_purchased, sso_provider)
firm_members(firm_id, user_id, role, joined_at)
profiles(user_id, aec_role, aec_discipline, country, avatar_url, default_model)
sync_blobs(user_id, kind, blob_key, sha256, size_bytes, updated_at)
audit_log(firm_id, actor_user_id, action, target, ts, ip, ua)
marketplace_skills(id, author_user_id, name, price_cents, blob_key, status)
license_tokens(user_id, token_jwt, plan, expires_at, signing_kid)
```

No followers, DMs, or posts. Architects don't want a social product.

### Sign-up flow — reuses the existing native SettingsDialog

Add **one tab to the existing 5-tab dialog: "Account"** (merges Profile into it). Flow: Sign in → PyQt opens browser → email → Resend magic-link → click → Worker → loopback → JWT stored via existing `secrets_store` (Windows Credential Manager). Account tab shows email, plan, seats, Manage billing, Sign out. No new dialog; cloud features become Qt slots on the existing bridge.

### BYO-key vs platform-key split

| Mode | Pays | When |
|---|---|---|
| BYO (default, all tiers) | Customer | Has corporate API access or IP-sensitive context |
| Managed (opt-in, metered) | ArchHub bills at cost + 20% | No key, wants one bill |
| Pooled platform key | **NEVER** | — |

The hard rule: **ArchHub never owns inference cost it can't bill back with margin on the next Stripe invoice.** This was the Fly mistake's lurking second act; killed.

### Sync model — what crosses the wire

| Data | Synced? |
|---|---|
| Sessions, Skills, custom nodes | Yes, Pro+ |
| Memory facts | Yes, encrypted, Studio+ |
| Audit log | Yes, Studio+ |
| Profile fields | Yes, all tiers |
| Provider API keys | **NEVER** — Credential Manager only |
| Host detection results | NEVER — per-machine; would lie |
| Workflow run cache | NEVER — big, ephemeral, leak-prone |

Content-addressable: client SHA256 → Worker checks → upload on miss only. Per-user key from JWT does client-side encryption; server proxies opaque blobs.

---

## 3. Billing — agenda + strategy

### Tiers (3 paid, not 5 — fewer choices, faster decisions)

| Tier | Price | What | Limits |
|---|---|---|---|
| Free | $0 | Desktop, BYO keys, all 18 hosts, all 80 nodes, local | No cloud, no publish |
| Pro | $19/user/mo or $190/yr | Free + sync (sessions/skills/memory), marketplace, web viewer, 1GB R2 | 1GB; managed inference metered |
| Studio | $59/seat/mo or $590/yr, 3-seat min | Pro + firm canvas, SSO, audit log, agent runner, 10GB/seat, 5M shared tokens | Token overage at cost+20% |
| Enterprise | $20K floor | Self-hosted plane, BAA, on-prem agents, CSM | Negotiated |

**Pro = individual; Studio = firm; Enterprise = procurement budget.** Tiers between Pro and Studio in the prior draft were fiction nobody asked for.

### Metered signals

| Signal | Bill |
|---|---|
| Seats | Flat per-seat |
| R2 above quota | $0.05/GB/mo (passthrough + thin margin) |
| Managed Anthropic tokens | Cost + 20% |
| Agent runner | Bundled in Studio (one shared box per firm) |
| Marketplace purchase | 70/30 author/ArchHub |

### Stripe integration plan

Stripe MCP for setup (3 products, 6 prices, 1 metered). Runtime hits Stripe SDK from the Worker. Endpoints `/v1/billing/checkout`, `/v1/billing/portal`, `/v1/webhooks/stripe` already designed in the destroyed `cloud_backend/main.py` — port them. Webhooks update `users.plan` and `firms.seats_purchased` on `customer.subscription.*` and `invoice.paid`. License JWT re-issued on plan change. Fees: 2.9% + $0.30 = 3.4% effective on a $59 seat. Polar.sh fallback (~4% MoR, no KYC) already coded; keep as one-day DR option.

### 12-month revenue projection

| Mo | Pess. MRR | Real. | Opt. |
|---|---|---|---|
| 2 | $0 | $19 | $57 |
| 3 | $19 | $76 | $254 |
| 6 | $190 | $700 | $2,360 |
| 9 | $570 | $1,800 | $5,800 |
| 12 | $1,200 | $3,500 | $12,000 |

**Realistic Y1 ARR $42K. Pessimistic $14K. Optimistic $144K.** Earlier $197K projection assumed 37 firms in 12 months — Hopium. Realistic case: ~50 Pro + 1–2 small Studio firms.

### Killer-question — outside capital?

**No.** Y1 infra ~$300/mo by month 12. Founder draw deferred until $5K MRR. Break-even ~30 paying seats (~$900 MRR vs ~$140/mo infra), month 4–6 realistic. Raise only when (a) $10K MRR sustained 3 months **and** (b) 2 reference firms named publicly **and** (c) a specific dollar line item the cash funds. Until then, raising dilutes a fragile thesis. Fly tuition cost ~$300; recurring bills will not recur because the new stack scales with revenue not optimism.

---

## 4. Community management

### Honest first: AEC is not Discord

Architects live on LinkedIn, Speckle Community, /r/Revit, BIMforum, and conferences (AU, BILT). **Do not build a community platform.** Borrow rooms that exist. What ArchHub needs:

### Skill marketplace

- **Browse**: public, SEO-indexable, `archhub.io/skills/<slug>`.
- **Install**: Pro+; desktop pulls JSON, schema-validates, drops into Skills sidebar.
- **Publish**: Pro+; submit via desktop UI; manual 48h review queue (first 6 mo).
- **Pricing**: author picks free / $5 / $15 / $49 / $99. No arbitrary prices.
- **Split**: 70/30 author/ArchHub via Stripe Connect Express.
- **Anti-abuse**: JSON sandboxed; nodes touching fs/net beyond declared `requires` block at runtime. Author identity = verified email + Stripe Connect bank account. No anonymous republishing.
- **Discoverability**: host / category / author. **No star ratings v1** (gameable). Use install count + verified badge + last-updated.

### Per-firm Notion-like internal hub

Studio only. Not a separate app — a `cloud.archhub.io/firm/<slug>` page on CF Pages reading Neon, opened in a QtWebEngine tab. Surfaces firm-shared Skills, canvas templates, audit log, member management. Invite: admin types email → Worker writes `firm_members(joined_at=NULL)` → Resend magic-link → click flips `joined_at` → next `/v1/me` picks up membership.

### Support

| Tier | Support |
|---|---|
| Free | Docs + GitHub Issues, community-answered |
| Pro | `support@archhub.io`, 48h target, no SLA |
| Studio | Priority queue, 1-BD target, optional Slack Connect |
| Enterprise | Dedicated CSM, 4h P1 SLA, post-mortems, roadmap input |

Founder absorbs Y1 (~5 hrs/wk). Hire around $20K MRR.

---

## 5. What we have NOT built that we need

| Gap | Scope | Wks | Deps |
|---|---|---|---|
| Auth (magic-link) | Worker + desktop loopback + Credential Manager | 1 | — |
| Profile cloud | Neon table + 4 endpoints + Account tab | 1 | Auth |
| Settings cloud | Sync provider choices (not keys), shortcuts, theme | 0.5 | Profile |
| Stripe billing | Products + checkout + portal + webhook + plan enforcement | 1.5 | Auth |
| Sync engine | Content-addressable, client-side encryption, LWW + conflict-copy | 2 | Auth |
| Marketplace v1 | CF Pages browse + install endpoint | 1.5 | Sync |
| Marketplace v2 (paid) | Stripe Connect + payouts + review queue | 2 | M1 + Stripe |
| Multi-tenancy | Firms + roles + invite + firm hub page | 2 | Auth |
| Audit logging | Append-only table + emitter + viewer | 1 | Multi-tenancy |
| Agent runner | Per-firm Hetzner provisioner + cron + R2 state | 2 | Multi-tenancy |
| Web viewer | CF Pages + React reading Neon | 1.5 | Sync |
| SOC2 Type I | Close 8 gaps in `docs/SOC2_READINESS.md` + Drata | 4 cal (1.5 eng) | Audit |

**Total ~20 founder-weeks, or ~10 with a part-time second engineer after W4.**

---

## 6. 90-day rollout sequence

Each phase has a revenue/data gate. If the gate fails, the next phase does not fire.

### Phase 1 (W1–3) — IDENTITY + BILLING

- W1: CF Workers, Neon schema, magic-link auth, `/v1/me`.
- W2: Stripe products via MCP; checkout + portal + webhook; Account tab.
- W3: Free→Pro upgrade works for founder. Public `archhub.io/pricing`.

**Gate: founder pays himself $19 from a separate Stripe customer; desktop reflects "Pro".**

### Phase 2 (W4–6) — SYNC

- W4: R2 bucket, content-addressable API, client-side encryption.
- W5: Desktop sync of sessions + skills.
- W6: LWW + conflict-copy, sync status indicator.

**Gate: ≥3 paying Pro OR founder uses sync across 2 machines 7 days without data loss.**

### Phase 3 (W7–9) — MARKETPLACE v1

- W7: `archhub.io/skills` browse page.
- W8: Install + submission flow with manual review queue (no payments yet).
- W9: 5 founder-authored launch Skills published.

**Gate: ≥10 Skill installs in W9.**

### Phase 4 (W10–12) — FIRMS + STUDIO

- W10: Firms schema + invite flow + firm hub page.
- W11: Audit log emitter on every state-changing endpoint.
- W12: Studio Stripe price live; first Studio firm onboarded (beg one from network).

**Gate: 1 paying Studio firm OR pilot agreement (free 3-month trial → paid).**

### Deferred (phase 5+)

Agent runner Hetzner box — only when first Studio firm asks. Paid marketplace — only after 50+ free Skills with active installs. SOC2 audit — only when an enterprise prospect blocks on it. Web viewer — only when Pro retention drops attributably. **Don't build phase N until N−1 proved demand.**

---

## 7. Risks

| # | Risk | Mitigation |
|---|---|---|
| 1 | LLM costs explode if we platform-key | Never bundle inference. BYO default. Managed is opt-in metered. Hard per-user per-day spend cap. |
| 2 | AEC firms have IT/IP rules | SOC2 Type I track in parallel with Studio. Publish `archhub.io/security`. Data-flow PDF on file. |
| 3 | Founder ran out of money on Fly once | Workers/R2/Neon baseline $0. Hetzner spawns only for paid Studio firms. CF spend alert $50/mo. Weekly payouts-vs-spend dashboard. |
| 4 | Marketplace becomes graveyard | Founder hand-ports 30 useful Dynamo/Grasshopper graphs as launch. Recruit 5 Speckle power users with revenue-share guarantees. |
| 5 | Sync conflicts corrupt data | v1 LWW with conflict-copy save (nothing lost). CRDT/Yjs deferred. |
| 6 | Stripe locks founder | Complete Stripe verification before W3. Polar.sh fallback already coded, redeployable <1 day. |
| 7 | Cloudflare incident | Desktop runs fully offline when cloud unreachable. License JWT cached 30 days. Sync queues locally, replays on reconnect. |
| 8 | Leaked JWT | Token rotation every 24h via refresh tokens (Credential Manager only). Server invalidates on downgrade. |

---

## 8. Recommended first action (this week)

**Stand up `api.archhub.io` on Cloudflare Workers + Neon with one endpoint: `GET /v1/me` behind magic-link auth.** Five working days:

1. **D1**: `npm create cloudflare@latest archhub-api --type=hono`. Custom domain. Resend + from-address.
2. **D2**: Neon free-tier project; `users` schema. Hono routes `POST /v1/auth/register` and `GET /auth/return`.
3. **D3**: PKCE desktop side: `bridge.start_signin()` opens browser, spawns loopback, awaits code. Token via existing `secrets_store`.
4. **D4**: `GET /v1/me` returns `{email, plan:'free'}`. Add Account tab to `SettingsDialog`. Email + Sign out.
5. **D5**: Founder signs in on his Windows desktop. Account tab shows his email. Done.

Week spend: **$0** (free tiers). Time: ~15–20 founder-hours. Output: a signed-in user — prerequisite for **every other thing in this document**. Billing in W2 is then a 2-day Stripe-MCP exercise; sync in W4–6 is mechanical once auth is solid. The Fly mistake was building cloud surface before customer surface. The rule is now inverted: **ship the customer surface (sign in, pay) first, then the cloud that serves them**. If nobody signs in, nothing else gets built. Kill-switch is automatic.
