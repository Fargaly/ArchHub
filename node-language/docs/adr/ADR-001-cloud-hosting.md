# ADR-001: ArchHub cloud backend hosting choice

**Status:** Proposed
**Date:** 2026-05-13
**Deciders:** Fargaly (founder) · Claude (backend) · Codex (UI)

## Context

ArchHub has two server-side workloads:

1. **`cloud_backend/`** — FastAPI proxy. OpenAI-compatible `/v1/chat/completions` endpoint that bills against per-company quota (v1.3.3), forwards to Anthropic / OpenAI / Google, exposes `/healthz`, `/billing/*`, `/users/*`, `/companies/*`, `/teams/*`. SQLite on a mounted volume.
2. **`agents/`** — autonomous worker daemon. Drains a task queue, calls Anthropic, posts GitHub Issue comments for status reports. Exposes `/healthz`, `/status`. Same SQLite.

Both are written; both have `fly.toml` configs (`archhub-cloud` + `archhub-agents`). Neither is deployed. DNS for `archhub-cloud.fly.dev` + `archhub-agents.fly.dev` returns NXDOMAIN. Reality smoke (`*/30 min` cron) probes them on every push → 6/11 checks RED → opens tracking issue → emails founder.

State today (2026-05-13):
- 14 unique CI-failure emails in last 7 days, ~50% trace to undeployed cloud
- GitHub Actions cron for status reports works (posts to Issue #20 hourly), but reports backend/agents both **RED**
- Fly killed free tier 2024 — every option below costs **at least** a few dollars/month
- Founder explicitly chose "install flyctl, then I deploy" minutes ago, but the architectural commit deserves a written record before card-on-file

Forces:
- **Cost sensitivity** — solo founder, no funding stated. Every $/mo matters.
- **Operational simplicity** — founder shouldn't be paged for cloud ops. Auto-stop / auto-scale-to-zero is mandatory.
- **Existing investment** — `fly.toml` configs already match the FastAPI app shape (Dockerfile in repo, volumes for SQLite, HTTPS termination).
- **Geographic latency** — ArchHub users are AEC pros; primary user is in UAE. Provider needs MENA/EU edge or low-RTT to Dubai.
- **Vendor lock-in tolerance** — moderate. We control the source. As long as backend is a vanilla container with stdlib + FastAPI, swaps are days not weeks.
- **Quota gating already in code** — `quota_remaining_for_actor` is hosting-agnostic. Decision is purely where the container runs.

## Decision

**Deploy to Fly.io. Single region `ord` initially. Migrate to `cdg` (Paris) or `bom` (Mumbai) once user count > 0 and latency telemetry justifies it.**

This is a **revert-cheap** decision. Container is stdlib + FastAPI; the entire `cloud_backend/` dir runs on any container host without code change. Treat Fly as the runtime, not a partner.

## Options Considered

### Option A: Fly.io (chosen)

Ready to ship. `fly.toml` + Dockerfile already in repo. CLI is one binary. Anycast edge.

| Dimension | Assessment |
|-----------|------------|
| Complexity | **Low** — `fly launch && fly deploy` end-to-end |
| Cost | ~$3–10/mo (2× shared-cpu-1x · 256MB · auto-stop) |
| Scalability | Per-region machine scaling; per-app concurrency limits in toml |
| Team familiarity | Highest — config already authored |
| Geo coverage | 35+ regions incl. `cdg` (Paris), `bom` (Mumbai). Good for UAE |
| Cold start | ~250ms wake from stop. Acceptable for chat workload |
| Volumes | First-class, $0.15/GB/mo |

**Pros**
- Zero rewrite. Deploy today.
- Auto-stop drops idle cost to volume-only (~$0.15/mo)
- Single binary CLI, no dashboard hopping
- Region picker not a redeploy event

**Cons**
- Card required (Fly free tier dead Oct 2024)
- Single-vendor risk (mitigated by container portability)
- Volumes don't replicate across regions — single point of failure for SQLite until we go Postgres

### Option B: Railway

Similar shape to Fly. Drag-drop GitHub repo, automatic Dockerfile detection.

| Dimension | Assessment |
|-----------|------------|
| Complexity | **Low** — connect repo, auto-deploys on push |
| Cost | $5/mo minimum (Hobby), then usage-based. Effective ~$8–12/mo for both apps |
| Scalability | Vertical only on Hobby. Pro plan for horizontal |
| Team familiarity | None |
| Geo coverage | 4 regions (US east/west, EU, Singapore). No Middle East |
| Cold start | None — pay for always-on |
| Volumes | Persistent volumes available, but no cross-region replication |

**Pros**
- Auto-deploy from GitHub push (no separate `fly deploy` step)
- Web UI nice for non-engineers (irrelevant here — founder is engineer)

**Cons**
- ~$3/mo more than Fly equivalent
- No MENA edge → +100–200ms RTT to UAE users
- Always-on pricing means idle waste
- Would discard the existing `fly.toml`

### Option C: Cloudflare Workers + D1

Radical alternative. Rewrite FastAPI as TypeScript request handlers. D1 (SQLite-on-edge) replaces volume.

| Dimension | Assessment |
|-----------|------------|
| Complexity | **High** — 100% rewrite of cloud_backend |
| Cost | $0 free tier covers 100K req/day. ~$5/mo at scale |
| Scalability | Best-in-class. Edge global. |
| Team familiarity | None for backend; Python-native team |
| Geo coverage | 300+ PoPs incl. Dubai |
| Cold start | None |
| Volumes | D1 only (no arbitrary file storage); blob = R2 |

**Pros**
- True edge perf — single-digit ms TTFB anywhere
- Cheapest at scale
- Free tier covers MVP indefinitely

**Cons**
- Rewrite cost: ~2 weeks. Loses Python testing, FastAPI deps (httpx for upstream LLMs OK on Workers, but pyright/mypy gone)
- Stripe webhook handling needs adapter
- Forks the agents/ daemon (long-running tasks = Durable Objects ≠ FastAPI handler shape)
- v1.3.3 quota tests assume FastAPI test client → discarded

### Option D: GitHub Actions only (no backend)

Keep the proxy out of the architecture entirely. Desktop calls Anthropic/OpenAI direct with user-supplied keys. Agents run as `*/30` workflow.

| Dimension | Assessment |
|-----------|------------|
| Complexity | **Lowest** — delete cloud_backend, keep agents as workflow |
| Cost | **$0** — Actions cron free on public repo |
| Scalability | Per-user (user pays Anthropic direct) |
| Team familiarity | High — already using Actions for status reports |
| Geo coverage | N/A |
| Cold start | N/A |
| Volumes | N/A |

**Pros**
- Truly zero ops, zero cost
- No PII/PCI surface area at ArchHub
- Aligns with "BYO key" mode already in Settings
- Stripe replaced by Polar.sh (per session decision) — billing already external

**Cons**
- Kills the managed-proxy revenue stream entirely (Studio $19/mo, Firm $49/mo plans depend on `/v1/chat/completions` proxy)
- Per-company quota work shipped 2 commits ago is wasted (still useful for desktop-side soft quota, but the actor wiring assumes server-side enforcement)
- No central usage telemetry → marketing/analytics blind
- Future enterprise SSO needs a backend somewhere

## Trade-off Analysis

The real axes are **revenue model** and **rewrite cost**, not vendor:

| | Keep backend | Drop backend |
|---|---|---|
| **Day-1 cost** | $3–10/mo | $0 |
| **Revenue model** | Managed proxy (Studio/Firm tier) viable | BYO only — Polar.sh handles seat licensing, not per-message |
| **Rewrite needed** | None | Delete cloud_backend, refactor desktop to drop Cloud connector |
| **PII surface** | Email + Stripe customer ID + company billing | None |

**Fly vs Railway vs CF Workers** is a tier-1 question only after we commit to "keep backend." Within "keep backend":

- **Fly wins on existing investment** — config authored, region picker covers UAE.
- **Railway wins on PR-deploy ergonomics**, irrelevant for solo dev who already has `fly deploy` muscle memory.
- **Workers wins long-term** but the rewrite blocks v1.3.3 ship by 1–2 weeks. Not worth the trade today.

**Drop-backend (Option D)** is the disruptive choice. It would erase ~40% of the codebase (cloud_backend/, tests/test_cloud.py, half of agents/). The session's recent work on per-company quota (committed `dc8fa7a`) becomes ornamental. Honest assessment: this option is real, founder hasn't ruled it out, and if the answer to "what does the proxy buy us?" is "central billing + central telemetry," and Polar handles billing while desktop can post telemetry to PostHog direct, then the proxy buys very little. But it does buy:

- **Future enterprise contracts** that demand a vendor endpoint, not "everyone brings their own Anthropic key"
- **Rate-limit absorption** — protects users from Anthropic 429s by load-balancing across multiple ArchHub-owned keys
- **Audit log** — single source of truth for who-ran-what

We accept the $5–10/mo to preserve those. **Decision stands: Fly.**

## Consequences

What becomes easier:
- Reality smoke goes green within one cron cycle (≤30 min after deploy)
- Status report bot reports actual production health, not a constant RED
- Founder unblocked from triggering desktop signup flow (cloud register endpoint resolvable)
- ANTHROPIC_API_KEY etc. live in Fly secrets, not on the dev machine — small but real security upgrade

What becomes harder:
- Card-on-file with Fly (Fly already has reasonable spend caps; suggest setting hard limit at $25/mo)
- SQLite-on-volume means **single-region availability**. A regional outage = ArchHub Cloud down for the duration. Acceptable at MVP; mandatory Postgres migration before we sell to anyone whose contract specifies multi-region.
- Need to rotate Fly auth token if it leaks
- One more thing for the founder to learn (`fly logs`, `fly status`, `fly ssh console`)

What we'll need to revisit:
- **Postgres migration** when volume size exceeds 1 GB OR when we need multi-region read replicas (whichever first)
- **Move to Workers** if/when usage hits a tier where edge perf delta is felt by users (estimate: > 500 concurrent users on the proxy)
- **Re-evaluate Polar.sh vs Stripe** independently of hosting; orthogonal
- **Sign in with Apple / Google SSO** would either require Fly app, or shift to Auth0/Clerk and keep backend stateless — defer this when we know which enterprise channel matters first

## Action Items

1. [ ] Founder runs `fly auth signup` in normal PowerShell window, adds card, sets `$25/mo` hard cap in Fly billing.
2. [ ] Founder runs `fly auth whoami` and pastes output → I take over.
3. [ ] Claude: `fly launch --no-deploy --copy-config --name archhub-cloud` from `cloud_backend/`, then `fly deploy`.
4. [ ] Claude: same for `agents/` with `--name archhub-agents`.
5. [ ] Claude: `fly volumes create archhub_data --size 1 --region ord` on cloud_backend app.
6. [ ] Claude: set non-secret env (`PUBLIC_URL=https://archhub-cloud.fly.dev`); leave `STRIPE_*`/`ANTHROPIC_API_KEY` empty for now (healthz returns 200 without them; per-feature tests cover absent-key paths).
7. [ ] Claude: wait one cron cycle, verify `https://archhub-cloud.fly.dev/healthz` returns 200.
8. [ ] Claude: re-run `scripts/reality_smoke.py --json`. Expect 9–10 green of 11 (Stripe + LLM probes still skip-gated by flag).
9. [ ] Claude: post comment to GH Issue #20 announcing cloud live.
10. [ ] Founder: add `ANTHROPIC_API_KEY` to Fly secrets when ready to enable managed proxy (Studio/Firm tier).
11. [ ] Founder: when ready, add `STRIPE_SECRET_KEY` + `STRIPE_WEBHOOK_SECRET` + `STRIPE_PRICE_*` (or Polar equivalents) to enable billing webhooks.
12. [ ] Revisit ADR-001 at v1.5.0 or 500 users (whichever first) to decide on Postgres migration + multi-region.

## Reversal Plan

If Fly costs spike beyond expectation or operational pain emerges in first 30 days:

- **30-day exit**: containerize is already a thing. `cloud_backend/Dockerfile` ships to any container host. Migration to Railway or Render is hours, not days.
- **Drop-backend pivot**: documented as Option D above. If the proxy isn't producing revenue by v1.5.0, delete it. v1.3.3 quota work becomes desktop-side soft-quota helper functions — still useful, not wasted.
