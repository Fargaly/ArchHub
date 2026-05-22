# ArchHub — Go-to-Market Strategy

> Drafted 2026-05-14 · Status: working draft

## 1. Positioning

**ArchHub is the canvas-first AI workspace for AEC firms that already
own Revit, AutoCAD, 3ds Max, Rhino, Blender, and Outlook.**

We don't replace BIM. We orchestrate it. One canvas, every tool, real
data flowing through typed wires. No scripting, no Dynamo block-and-
node trees buried in a project file — a workspace the architect, not
the BIM manager, drives.

### What we are vs what we aren't

| We are | We aren't |
|---|---|
| A graph-first AI workspace that drives BIM hosts | A new BIM authoring tool |
| LLM-agnostic (Claude / GPT / Gemini / local) | Locked into one model vendor |
| Local-first with optional cloud memory | A SaaS where your model lives in someone's cloud |
| Per-tool permissions (AUTO / ASK / BLOCK) | A blanket "approve everything" agent |
| Auditable — every tool call is logged + skill-able | An opaque copilot you can't replay |

## 2. Target buyer

### Beachhead segment

**Mid-size architecture firms (15–150 people)** that:

- Use Revit as primary BIM authoring (highest pain).
- Have at least one BIM lead / computational design role.
- Run multi-tool workflows (Revit + Rhino + Blender + Speckle).
- Have already failed at adopting Dynamo / Grasshopper at scale
  because the learning curve excluded everyone but specialists.
- Are spending on enterprise AI subscriptions (ChatGPT Team, Copilot)
  but can't connect them to their actual files.

### Personas

| Persona | Pain | Buying trigger |
|---|---|---|
| **BIM Manager** | Repetitive cleanup tasks across projects. Dynamo scripts that only they understand. Inconsistent standards. | Sees a peer demo Sketch-to-Production skill at a conference. |
| **Project Architect** | Same boilerplate work every project — sheet sets, schedules, dimensioning, naming. Wants AI in their tools without learning Python. | Senior architect colleague says "I do this in 30 seconds now." |
| **Computational Designer** | Built useful tools, but team can't reuse them. Knowledge dies with the script. | Wants tools that ship as portable Skills, not project-bound `.dyn` files. |
| **Principal / CTO** | Compliance and IT pressure. Can't put proprietary models in OpenAI. | Hears about ArchHub's local-first, BYO-key, on-prem-capable story. |

## 3. Acquisition channels

Ordered by predicted CAC + speed-to-revenue:

### Tier 1 — Direct & community (months 1–3)

1. **AEC computational design Discord / forums**  
   Speckle Community, Dynamo BIM, Grasshopper3D, /r/Revit,
   /r/Architecture, BIM Coordinator. High-signal users; most have
   been waiting for a non-script tool. Share Skills as native posts.

2. **LinkedIn AEC tech operators**  
   Direct outreach to BIM managers + computational designers at
   firms with 15–150 staff. Hook: a 90-second loom of the
   Sketch-to-Production skill driving Revit live.

3. **YouTube + Tutorial-First Content**  
   The product sells itself only on video. Build a series:
   - Episode 1: *Dimension a whole Revit view in one prompt*
   - Episode 2: *Sketch → Speckle → Revit mass in three steps*
   - Episode 3: *Outlook triage that knows your projects*
   - Episode 4: *Save any conversation as a reusable Skill*
   - Episode 5: *Multi-host wiring — push Rhino curves into Revit walls*
   
   Distribute on YouTube, X, LinkedIn, BIM forums.

### Tier 2 — Partnership (months 2–6)

4. **Speckle ecosystem**  
   Speckle is the open AEC interop layer. ArchHub already has
   Speckle as a first-class host. Co-marketing makes sense — every
   Speckle user can use ArchHub Skills as a higher-leverage layer on
   top of the streams they already manage.

5. **Autodesk Partner Program**  
   Once the Revit add-in is signed + has 100+ active installs, apply
   for Autodesk Partner status. Gets listing in Autodesk App Store,
   credibility halo, optional integration with Construction Cloud.

6. **AEC vendor reseller deals**  
   Resellers who already sell Revit / Rhino / Speckle to firms in
   Middle East, Europe, India. Offer a 20-30 % reseller margin on
   annual subscriptions.

### Tier 3 — Education (months 4–9)

7. **University BIM courses**  
   Free for students + educators. The university plan is a Trojan
   horse — graduates who learn ArchHub bring it into firms they
   join.

8. **Workshops at AEC conferences**  
   AU (Autodesk University), BILT, AEC Hackathon, EduTech.

## 4. Pricing & packaging

> See [REVENUE_MODEL.md](REVENUE_MODEL.md) for the full pricing table.

Shape:

- **Solo** — free for one user, BYO-key only, local-only memory, no
  team Skills.
- **Studio** — $39 / user / month, includes cloud-synced Skills,
  cloud memory, team library, Revit / AutoCAD / Max plugins.
- **Firm** — $79 / user / month with role-based permissions, SSO,
  audit log export, on-prem deployment option.
- **Enterprise** — custom. Self-hosted control plane, dedicated
  support, custom integrations.

## 5. Proof points needed (in priority order)

To make this real, we need:

1. **Three reference customers** with shippable case studies. Target:
   one Middle East firm (existing relationships in Bayaty Architects
   network), one European firm, one US firm. Each gets free Studio
   for 12 months in exchange for a published case study.

2. **A signed Revit add-in** so Autodesk Partner status is reachable.
   Code-signing infra already documented in `docs/CODE_SIGNING.md`;
   sign it.

3. **A 10-minute pitch video** that opens with the
   Sketch-to-Production skill. No talking heads. Show the canvas.

4. **A SOC2 readiness page** for compliance-sensitive firms.
   Already exist in `docs/SOC2_READINESS.md`; expose publicly.

5. **A working free trial** without credit card. 14 days of full
   Studio, gated to a single user / device. Today this is technically
   blocked on Fly cloud trial expiry — adding payment to Fly is the
   unblocker.

## 6. Competitive landscape

| Competitor | What they do | Where we win |
|---|---|---|
| **GitHub Copilot for AEC (rumoured)** | Code completion in IDE | We drive the model directly, not the code that drives the model. |
| **Hypar** | Web-first parametric building | Cloud-only; can't touch existing Revit files. |
| **Speckle alone** | Streaming geometry interchange | Speckle is a layer below us. We use it. |
| **Autodesk AI / Construction Cloud AI** | Vertical AI inside ACC | Locked to Autodesk stack, no multi-vendor LLM choice, no local-first. |
| **In-house Dynamo / Grasshopper libraries** | Free, infinite flexibility | Requires a scripter. Doesn't scale across the team. |
| **ChatGPT / Claude desktop apps** | Strong general AI | Can't drive Revit. No graph. No multi-tool wiring. |

## 7. 90-day plan

| Week | Milestone |
|---|---|
| 1–2 | Ship v1.4 stable (zero black-screen crashes for a week). Sign Revit add-in. Add Fly card; cloud back up. |
| 3–4 | Launch landing page with embed of Sketch-to-Production demo. Open free Solo tier. |
| 5–6 | Record + publish 5-episode tutorial series. Share on LinkedIn + AEC forums. |
| 7–8 | First three lighthouse customers signed for Studio (free year, case study commit). |
| 9–10 | Submit Autodesk Partner application. Open paid Studio tier. |
| 11–12 | First paid customer ($39 × 5 = $195 MRR). Publish first case study. |

By day 90 the target is **$2K MRR from 3 paying firms** — small in
absolute terms but enough to validate every pricing assumption and
trigger Series A conversations on the back of unit economics, not
projections.

## 8. Risks

| Risk | Mitigation |
|---|---|
| Autodesk locks the Revit add-in API | We multi-host Revit + AutoCAD + Max + Blender + Rhino. Diversification is the moat. |
| LLM vendors race to native AEC features | We're the canvas layer; we run on top of whichever model is best each quarter. |
| Cloud trial expiry stalls demos | Pay the Fly subscription. $50/mo unlocks the public surface. |
| Black-screen / crash bugs | ErrorBoundary now surfaces stacks; ship the 1.4.1 stability patch before public outreach. |
| Pricing too aggressive for solo architects | Solo tier is forever-free; Studio targets firms with budget. |
