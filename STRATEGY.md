> ⚠️ **INTERNAL DOCUMENT.** Pricing rationale, competitive positioning,
> and financial model. Useful as institutional memory for maintainers
> and contributors. **Not customer-facing copy** — for that, see the
> public landing page or the Notion site. Direct comparisons to other
> tools live here intentionally; do not copy them into marketing.

# ArchHub — Strategy

_Internal company doc. Living document. Last update: 2026-05-06._

---

## One-line product

**Talk to your AEC stack. ArchHub drives Revit, Blender, AutoCAD, 3ds Max,
and Speckle natively from a single chat — and saves your patterns as
copy-paste shareable Skills.**

## Vision

The architect never types code, never copies snippets between
applications, never re-runs the same five-step setup ritual. They speak;
ArchHub executes; the work shows up in the right tool.

The product is a **Skill execution layer** sitting between the architect's
chat and a multi-LLM backend. Skills are JSON (workflow graph + intent
metadata) — portable, copy-pasteable, learnable, ownable. ArchHub itself
ships as a thin desktop app (PyQt6) on top of an open node-graph engine.

## Wedge

The **chat-as-front for parametric DAG**. No competitor owns it:

- Hypar has the parametric core, no chat.
- Forma has Autodesk distribution, no AI cockpit.
- Grasshopper has the graph, no chat, Rhino-locked.
- ChatGPT/Claude Desktop have chat, no AEC connectors.

ArchHub sits in the unclaimed middle.

---

## Pricing

| Tier | $/seat/mo | What's in it |
|---|---:|---|
| **Free** | $0 | Up to 3 saved Skills · local Ollama only · single device · community support · "ArchHub Free" branding |
| **Pro** | $39 | Unlimited Skills · cloud sync via GitHub · BYO API keys · 5-device sync · email support |
| **Studio** | $79 | Pro + ArchHub cloud LLM relay (we hold provider keys) · firm-shared Skill library · priority Skills (we publish vetted Skills monthly) · cost dashboard · phone+email support · firm SSO |
| **Enterprise** | custom | Studio + self-hosted relay · custom Skill development · IP isolation · dedicated support · annual billing |

### Add-ons

- **Token packs** (Studio+ only). $25 / $50 / $100 prepaid bundles. ~20%
  margin over OpenRouter passthrough. Only revenue lever we have on
  tokens themselves; everything else is seat-licence economics.

### Pricing rationale

| Anchor | $/mo | ArchHub move |
|---|---:|---|
| Hypar | $25 | Pro is **above** at $39 — we deliver more (multi-host, vision, skills, sync) |
| Speckle Workspace | £15-£60 | Studio overlaps and includes Speckle hosted |
| TestFit Urban | $100 | Studio is **below** at $79; we span more verticals |
| Forma standalone | $185 | Pro/Studio are **below**; we are open + multi-tool |
| AEC Collection bundle | $430 | Out of scope; we coexist |

### Pricing principles

1. **Free tier is generous enough to drive adoption** but constrained
   enough to push serious users to Pro within ~2 weeks.
2. **Pro lands a solo architect or 2-5 person studio** for the cost of one
   coffee per workday.
3. **Studio is sized for a 50-architect firm to upgrade without a board
   approval cycle** (under the typical $4k/mo discretionary IT line).
4. **Enterprise opens at $X annual** based on a 30% premium over
   Studio × seat count, plus a one-time custom-skill engagement fee.

---

## Open core

The desktop app source is **public** under MIT or Apache 2.0:

- Workflow engine (graph / executor / nodes)
- Skill primitives + library + matcher
- Tool engine + connectors
- Multi-LLM router
- All UI

The following are **closed and operated by us**:

- ArchHub Cloud LLM Relay (Studio/Enterprise) — server holds provider
  keys, applies firm rate limits + audit logging
- Skill Registry web app (browse + install Skills firmly)
- Telemetry pipeline + cost dashboard
- Authentication / billing service

This mirrors Speckle's model exactly: open-source server + commercial
hosted offering. Speckle raised a Series A on this bet; the AEC
community already trusts the pattern.

---

## Go-to-market

### Year-1 funnel

```
                ┌────── direct site (archhub.io) ─┐
                │                                   ▼
   AEC          │      ┌────► Free download ──► Onboarding wizard
   community ───┼──────┤                              ▼
   channels     │      └────► Pro / Studio upgrade in-app
                │                                   ▼
                │                            Stripe checkout
                ▼
       Skill registry browse + share (free, drives sign-ups)
```

### Channels (priority order)

1. **Speckle Discord + Speckle Community** — highest-conversion AEC ICP
2. **r/architecture + r/Revit + r/Blender + r/cad** — content marketing
3. **AEC Magazine + Architosh + AEC+Tech** — earned coverage (Hypar got
   featured this way; same playbook)
4. **Twitter/X + LinkedIn AEC influencers** — once revenue exists
5. **Autodesk App Store** — distribution + legitimacy (revenue share TBD)
6. **Direct partner pilot** — your 50-arch firm = first paying Studio
   customer, public case study after 90 days

### Content cadence (when ready)

- Twice-weekly demo video on Twitter/LinkedIn (vision-input → real Revit
  output is the headliner)
- Monthly long-form post on the blog (technical deep-dive on a Skill
  pattern, AEC workflow, or architectural principle implemented as code)
- Quarterly Speckle / community AMA

---

## Moats (from competitive brief)

| Threat | Moat |
|---|---|
| Anthropic / OpenAI ship native AEC MCP | ArchHub is **execution layer**, not catalogue. Skills + DAG memory + multi-LLM router stay ours |
| Autodesk Forma equivalent | Open-source, multi-tool, local-LLM, ownership of Skills the user forks |
| Hypar adds chat layer | Already shipped. Native Revit C#. Cloud-synced personal library |
| Grasshopper "AI assistant" plugin | Coexist via Speckle. Span 4 hosts not 1. Skills are the asset |
| Foundation models 10× better at Revit C# | Skills capture intent + constraints. Smarter models run Skills better |

---

## Financial model — Year 1 sketch

### Costs (lean)

| Item | One-time | Monthly | Annual |
|---|---:|---:|---:|
| Domain `archhub.io` | $25 | — | $25 |
| Microsoft Trusted Signing (installer) | — | $10 | $120 |
| Stripe (no fixed; only takes %) | — | — | $0 |
| GitHub Pages (landing) | — | — | $0 |
| GitHub Actions CI | — | — | $0 |
| Cloud relay (Vercel + Supabase free tier) | — | $0–25 | $0–300 |
| Marketing budget | — | $0 | $0 |
| **Year-1 fixed cost** | **$25** | **$10–35** | **$145–445** |

Founder time only (you covering capital). No employees Year 1.

### Revenue scenarios — when does this break even?

Break-even = $445/yr fixed costs, ignoring time. Stripe takes 2.9% +
$0.30/txn ≈ ~3.5% all-in.

**Conservative:** 1 Pro user pays $39/mo × 12 = $468/yr → break-even at month 12.
**Realistic (your firm pilots Studio after 60 days):** 50 seats × $79/mo
× ~2 mo = **$7,900 first 60 days post-pilot**.
**Optimistic (Hacker News + 1 AEC Magazine feature):** 100-200 Pro signups
× ~5% paid conversion = 5-10 paying × $39/mo = $195-390/mo MRR within
first quarter.

### When to hire / spend more

- **First $5k MRR**: keep going solo, add code-signing + relay infra
- **First $15k MRR**: hire one part-time AEC SME for Skill curation
- **First $50k MRR**: full-time engineer #2 + dedicated marketing
- **First $250k MRR**: Series Seed pitch makes sense

---

## Roadmap (engineering)

### Q2 2026 (now → Aug)

- [x] v0.10–0.14 product foundation (Skills, vision, glass UI, installer, OAuth, cloud sync, onboarding)
- [ ] **v0.15** — Pricing dialog + Stripe checkout URL + open repo
- [ ] **v0.16** — ArchHub Cloud Relay v0 (Vercel function + Supabase auth)
- [ ] **v0.17** — Skill Registry web app (browse + install)
- [ ] **v0.18** — Visual canvas (ComfyUI-style power user mode)
- [ ] **v0.19** — Telemetry / cost dashboard inside the app
- [ ] **v0.20** — Real Revit dogfood at your firm; case study post

### Q3-Q4 2026

- v1.0 launch with paid Pro / Studio tiers active
- Hacker News + AEC Magazine feature
- First non-pilot Studio customer (firm ≠ yours)

---

## Brand

- **Name**: ArchHub (keep — testing well, no trademark conflicts found)
- **Domain**: archhub.io (established tech-product TLD; HTTPS enforced via HSTS at the edge — `.io` is not on the preload list, so set the header)
- **Logo / icon**: current PNG/ICO is a placeholder; redesign in Q2
- **Voice**: terse, technical, no fluff (matches the architect / dev
  customer; avoids the "AI marketing-slop" voice that's losing trust in
  2026)
- **Colours**: warm dark canvas + terracotta accent (Claude-adjacent,
  intentional — signals "AI tool" without being purple)

---

## What this strategy kills

- "Sell to enterprises directly via cold outbound." Wrong shape this early.
- "VC fundraise before $5k MRR." Premature.
- "Build a marketplace before users want to share." Build copy-paste first.
- "Per-project pricing." Adds friction; seat licences scale better with usage.
- "Free forever for everyone." Free tier capped at 3 Skills creates the
  upgrade pressure.

## What this strategy preserves

- Open-core authenticity (the entire moat for AEC trust)
- Local-LLM option for IP-sensitive firms
- Multi-LLM router (lock-in resistance)
- Speckle integration as the cross-tool spine
