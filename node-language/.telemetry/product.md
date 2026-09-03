# Product: ArchHub

**Last updated:** 2026-05-26
**Method:** codebase scan + maintainer context (no live user interview — caveman main session, NEVER-ASK-PICK-ONE mandate)

## Product Identity

- **One-liner:** Architects drop hosts (Revit, Blender, AutoCAD, Outlook, …), readers, filters, and AI nodes onto a canvas, wire them together, press Run — the wires carry Speckle-typed data between nodes and the result lands in the right tool. Save the canvas as a Skill — a JSON subgraph the firm copies, pastes, edits, and shares.
- **Category:** hybrid `ai-ml-tool` + `developer-tools` + `b2b-saas` — graph-first AI workspace for AEC professionals, open-source desktop client with a commercial cloud relay.
- **Product type:** **Hybrid.** Single-architect at the desktop client level (B2C-shape acquisition); multi-seat firm at the relay/Studio level (B2B-shape billing). Entity model needs both user-level *and* account-level tracking.
- **Collaboration:** **Hybrid.** Canvas itself is single-player (one user's session). Skills are the collaboration unit — saved as JSON, shared via OneDrive symlink, GitHub, or the firm-shared Skill library (Studio relay).

## Business Model

- **Monetization:** **Open-core.** MIT-licensed desktop client. Closed, paid Cloud Relay (Studio + Enterprise tiers).
- **Pricing tiers** (from `STRATEGY.md`):
  - **Free** — $0. Up to 3 saved Skills, local Ollama only, single device, "ArchHub Free" branding.
  - **Pro** — $39/seat/mo. Unlimited Skills, cloud sync via GitHub, BYO API keys, 5-device sync.
  - **Studio** — $79/seat/mo. Pro + managed cloud LLM relay (provider keys held by us), firm-shared Skill library, cost dashboard, priority Skills, firm SSO.
  - **Enterprise** — custom. Studio + self-hosted relay, custom Skills, IP isolation, annual billing.
  - **Token packs** (Studio+ only): $25 / $50 / $100 prepaid, ~20% margin over OpenRouter passthrough.
- **Billing integration:** **Stripe** (active) + **Polar** (wired, gated for company-level subscriptions). Both live in `cloud_backend/`. `billing.py` + `polar.py` + Stripe-webhook test surface present. Per `docs/ROADMAP.md`, `polar` is company-blind today (open backlog item).

## Tech Stack

- **Primary language:** Python (desktop + cloud backend).
- **Framework:** **Desktop** = PyQt6 + `QWebEngineView` shell loading a React/JSX UI (`app/web_ui/studio-lm.jsx`, ~5k lines, Babel-standalone — no Node build). **Cloud backend** = FastAPI on Fly.io (`cloud_backend/main.py`).
- **UI bridge:** `app/bridge.py` exposes 115+ `@pyqtSlot` methods over QWebChannel — the contract between JSX and Python.
- **Database:** SQLite. Desktop: brain DB at `%APPDATA%\ArchHub\brain\brain.db` + Speckle SQLiteTransport per-project at `<project>/Objects.db`. Cloud backend: SQLite at `cloud_backend/archhub_cloud.db` on encrypted Fly volume.
- **Background jobs:** Per-Qt async pool (`run_connector_op` / `_cached_async`); native `threading.Thread` for daemons (autoupdate, CEO routine hourly cron, scheduled triggers).
- **HTTP client patterns:** `requests` for sync calls, `httpx` for the LLM router and brain MCP client; native `urllib` for installer probes. MCP transport over Streamable HTTP + SSE.
- **Module organization:** `app/` = desktop client (flat, ~90 modules). `app/connectors/` = 16 host adapters on a uniform `base.py` contract. `app/workflows/` = graph + runner + node executors. `app/llm_providers/` = per-provider clients. `cloud_backend/` = the closed relay. `personal-brain-mcp/` = shared-memory daemon (port 8473).
- **AEC connectors:** RevitMCP (C# add-in, brokers on ports 48884–48899 across Revit 2020/2023/2024/2025), AcadMCP, 3ds Max MCP, plus Python-driven Blender / Rhino runners. Office-side: Outlook (COM), Excel/Word/PowerPoint, Teams. Adobe: Photoshop/Illustrator/InDesign. Plus Speckle, Notion, Dropbox.
- **LLM providers:** Anthropic, OpenAI, Google, OpenRouter (real OAuth, ~300 models), local LM Studio / Ollama, firm relay. Router in `app/llm_router.py`.

## Value Mapping

### Primary Value Action

**Run a canvas Skill that drives a real host.** A user opens a canvas, places nodes (input → connector → AI → output), wires them, presses Run, and observable state changes inside Revit / AutoCAD / Outlook / etc. (e.g., dimensions land on a Revit sheet, an email gets drafted, a wall list lands in a Watch panel). If this drops to zero, the product has failed — every other feature (Composer, Skill capture, marketplace, relay billing) exists to make this happen more often, more cheaply, and across more hosts.

### Core Features (directly deliver value)

1. **Canvas + workflow runner** — place / wire / run typed nodes. `app/web_ui/studio-lm.jsx` + `app/workflows/runner.py`. The substrate of every other feature.
2. **AI Composer chat** — natural-language → graph mutation. Free-text "ping outlook" spawns + wires the right nodes. Seven primitive agent tools (`spawn_host` / `spawn_node` / `wire` / `focus` / `rename` / `delete` / `run`). Plan / Auto / YOLO modes.
3. **Host connectors** — 16 connectors covering 18 host families with 116 ops on the uniform `OpResult` contract. The reason a workflow does work in the real world.
4. **Save as Skill** — Cmd-G compresses a selection into a composite, saved as JSON. Right-click → Save as Skill. Loads onto any other canvas, intent-tagged, matchable by Composer.
5. **Speckle wires** — every wire is a typed Speckle `Operations.send/receive` segment with `DiskTransport` default. Cross-host data flow with content-addressed versioning + free local undo via Speckle Versions.
6. **Vision input** — paste a hand sketch on a `vision` node; the multimodal LLM reads it and drives downstream modelling.
7. **Multi-LLM router with BYO key** — choice of model + key location is part of the value, not friction. Includes local LM Studio / Ollama path for IP-sensitive work.

### Supporting Features (enable core actions)

1. **First-run wizard + sign-in dialog** — gate to first canvas placement.
2. **Connector Manager + host detector** — keeps the host-pill row honest (`live` / `loaded_dead` / `missing` / `unauthorized`). The reason a user trusts the canvas hasn't gone stale.
3. **Settings dialog (Providers tab, Privacy panel, Appearance)** — where keys, telemetry consent, theme, and update channel live.
4. **Skills panel + skill matcher** — surface and invoke saved Skills from chat (intent + keywords).
5. **Marketplace** — browse + install third-party Skill packs (Ed25519-signed).
6. **Personal-brain-mcp daemon** — shared memory + skills + setups + wiring across sessions (port 8473). Every session probes brain.health at start (BRAIN-FIRST mandate).
7. **Auto-update + installer + updater** — winget / scoop / choco / direct `.exe` paths; release_updater.
8. **Cloud backend (relay)** — companies, multi-seat, Stripe checkout, per-company quota, admin dashboard, invite email-match, magic-link auth.
9. **Telemetry consent + PostHog wrapper + Sentry init + PII redactor** — already in place, gated on explicit opt-in.
10. **Feedback widget** — in-app NPS-style capture; already fires one telemetry event.
11. **HUD overlay + pet** — ambient autonomy chrome (v0.24+); produces no analytical signal worth tracking today.

## Entity Model

### Users

- **ID format:** UUID (`distinct_id` for telemetry, generated via `uuid.uuid4()` and persisted in Windows Credential Manager-backed settings — see `app/telemetry.py`). Cloud backend additionally assigns `usr_*` IDs at sign-up.
- **Roles:** `member`, `admin`, `owner` (cloud-side, per company). Desktop-only users have no role.
- **Multi-account:** Yes — a user can be invited to multiple companies (cloud-side). Desktop-only users belong to no company.

### Accounts (Companies)

- **ID format:** Cloud-backend integer or `company_*` prefixed string (verify in `cloud_backend/db.py`). Desktop-only users do not have an account.
- **Hierarchy:** Flat — company has many users, no nested orgs.

### Sessions (Canvases)

- **ID format:** Slugified filename — `<slug>.archhub-session.json` under `%LOCALAPPDATA%\ArchHub\sessions\`.
- **Why it matters:** Where 90% of in-product actions actually happen. Not a group in the telemetry sense (over-engineering — events carry `session_id` as a property), but the natural unit of work.

### Skills

- **ID format:** `<slug>.archhub-skill.json` envelope file with `skill_id` slug inside.
- **Modes:** `private` (each placement independent) vs `shared` (canvas-side wrapper points at the source file, edits propagate via `subgraph.user` keyed on `config.skill_id`).

## Group Hierarchy

```
Account (Company)
└── User
    └── (Session, Skill — property-level only, not separate groups)
```

| Group Type | Parent | Where Actions Happen |
|------------|--------|---------------------|
| account    | —      | Billing, plan upgrades, seat invites, firm-shared Skill library |
| user       | account | All in-canvas actions, AI completions, host runs, skill saves |

**Default event level:** `user` for every canvas/composer/connector/AI action. `account` only for plan changes, seat invites, quota events, marketplace purchases.
**Admin actions at:** `account` (seat management, billing, firm library).

**Note on session/skill as groups:** considered and rejected. Session is short-lived, frequently switched, and a high-cardinality identifier — carrying it as a property (`session_id`) on each event gives the same analytical reach without `group()` calls every canvas swap. Skill is similarly a property (`skill_id`, `skill_mode`), not a group level.

## Current State

- **Existing tracking:** **PostHog** (opt-in) + **Sentry** (crash + error). Wrapper in `app/telemetry.py`. Consent dialog at `app/telemetry_consent_dialog.py`. PII redactor at `app/pii_redactor.py`. Settings UI for keys at `app/settings_dialog.py` Privacy panel.
- **Documentation:** Partial — design contract in `app/telemetry.py` docstring + privacy commitments in `landing/security.html`.
- **Live events (5 total):**
  1. `app_started` — fired in `main.py:625` / `:631`. Property: `silent` (bool).
  2. `provider_blocked` — fired in `llm_router.py:537`. Properties: `provider`, `reason[:120]`.
  3. Telemetry-consent event — `telemetry_consent_dialog.py:92`.
  4. Skill-usage event — `app/skills/usage.py:77`.
  5. Feedback-widget event — `feedback_widget.py:172`.
- **Known issues:**
  - **Zero JSX events.** The entire React canvas (node placement, wiring, Composer turns, AI chat, Skill save/load, Run-workflow) emits nothing — confirmed by grep over `app/web_ui/`. The product's primary value action is invisible to analytics.
  - **Zero landing-page analytics.** Neither the legacy static `landing/index.html` + `landing/security.html` NOR the new Astro site at `web/` (track-A, 2026-05-28 — 6 pages under `web/src/pages/`, shared `web/src/layouts/Base.astro`) carry any analytics snippet. Acquisition funnel is invisible. Instrument the Astro layout; the static files are superseded.
  - **No `user.signed_up` / lifecycle events.** Cloud-backend issues tokens (`db.issue_token`) but no telemetry fires on signup. Conversion → activation → retention path is unmeasurable.
  - **No billing events.** Stripe + Polar webhooks land in the cloud backend but never call `track_event`. Trial events, plan changes, MRR signals are absent.
  - **No connector / host events.** Every run of a Revit / Excel / Blender op fires no telemetry — feature adoption per connector is unknown.
  - **Identity not yet bound.** `distinct_id` is anonymous per install. `identify()` is never called to bind to a cloud user_id when the user signs in. Cross-device tracking impossible without an explicit alias step.

## Integration Targets

| Destination | Purpose                                                           | Priority |
|-------------|-------------------------------------------------------------------|----------|
| PostHog     | Product analytics — events + traits + feature flags. Already wired desktop-side; needs JSX + landing extension. EU host (`eu.i.posthog.com`) for GDPR. Committed publicly in `landing/security.html`. | P0 |
| Sentry      | Crash + error telemetry. Already wired (`app/sentry_init.py`). Continues as-is. Committed publicly. | P0 |
| Segment-style CDP | Not currently wired. Could route to PostHog + a warehouse later; not required at this volume. | P2, defer |
| Accoil      | Not committed. Skip unless a B2B-CSAT motion is opened. | skip |

**Destination constraints note:**
- **PostHog** stores event properties as JSON, supports `group()` for account-level segmentation, supports feature flags. Use `object.action` snake_case event names + property-rich events (one event for `node.placed`, distinguish by `node_type` property).
- **Sentry** is for errors/crashes only — no product events here. Continue with `sentry_init` + breadcrumbs.
- **Public privacy commitment** (`landing/security.html`): never transmit prompts, model responses, project file paths, project names, API keys. Tracking plan must inherit this rule — no `prompt_text`, no `file_path`, no `project_name`, no key material in any event property. Hash or bucket if a derivative signal is wanted (e.g., `prompt_length_bucket: short|medium|long`).

## Codebase Observations

- **Feature areas inferred:**
  - Canvas + workflow: `app/web_ui/studio-lm.jsx`, `app/workflows/{graph,runner,nodes}.py`, `app/run_workflow.py`, `app/workflow_canvas.py`.
  - Composer (AI chat): `app/chat_window.py`, `app/ai_behaviour.py`, `app/tool_engine.py`, `app/llm_router.py`.
  - Connectors: `app/connectors/{base,*}.py` (16 hosts), `app/revit_broker.py`, `app/outlook_broker.py`, `app/acad_broker.py`, `app/max_broker.py`.
  - Skills: `app/skills/`, `app/library*.py`, `app/skills_panel.py`, `app/skills_grid_panel.py`.
  - Marketplace: `app/marketplace_*.py` (client, panel, signing, meta).
  - Cloud: `cloud_backend/{main,auth,billing,companies,polar,proxy,marketplace}.py`.
  - Telemetry: `app/telemetry.py`, `app/sentry_init.py`, `app/pii_redactor.py`, `app/telemetry_consent_dialog.py`.
  - First-run / onboarding: `app/first_run.py`, `app/onboarding{,_dialog}.py`, `app/sign_in{,_dialog}.py`.
  - Settings: `app/settings_dialog.py`, `app/settings_page.py`.
  - Auto-update: `app/release_updater.py`, `app/updater.py`, `app/update_dialog.py`.
  - Memory / brain: `app/memory_gate.py`, `personal-brain-mcp/`.
- **Entity model inferred:** User (desktop install with anonymous `distinct_id` + optional cloud sign-in), Company (cloud-side billing entity, multi-seat), Session (canvas instance, file-backed), Skill (saved subgraph JSON), Marketplace Pack (signed Skill bundle). The first two are entities for telemetry; the last three are best modelled as event properties.
- **Roles inferred (cloud-side):** `owner`, `admin`, `member` per company invite (from `cloud_backend/companies.py invite_member`).
- **Identity bridge gap:** Desktop `telemetry.distinct_id()` is install-scoped UUID. Cloud `user_id` is issued at sign-in. No code path currently calls `identify()` to alias the install UUID to the cloud user_id — required for cross-device + landing→app attribution. Filed for the design phase.
