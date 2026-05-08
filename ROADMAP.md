# ArchHub roadmap

> Truth-only roadmap. If a date slips, this file gets updated the same day.
> Brand v0.1 from `archhub/project/brand.jsx` is the north star.

Current ship: **v0.27.x** — Studio shell wired to live ArchHub data
(connectors · sessions · skills · settings).

## Shipped

| Ver | Date | What |
|---|---|---|
| v0.25 | 2026-04-30 | Connector self-heal daemon · Outlook COM via `com_thread()` · single-instance summon · CMD-window flash kill · auto-update on launch |
| v0.26 | 2026-05-06 | Studio palette + Instrument Serif + JetBrains Mono shipped via `theme.qss` |
| v0.27.0 | 2026-05-07 | Studio 3-pane shell — rail · centre · inspector · status rule · 7 nav pages |
| v0.27.1 | 2026-05-08 | Win32 SW_SHOW fix — window never launches hidden under pythonw |
| v0.27.2 | 2026-05-08 | All fake data ripped — every surface live-wired (manager / sessions / skills / health) |
| v0.27.3 | 2026-05-08 | Design tokens single source · WCAG-AA contrast · focus rings · 36×24 toggle hits |
| v0.27.4 | 2026-05-08 | Brand v0.1 integration — ArchMark SVG · "Arch" + italic "Hub" · tagline · dark mode (graphite, not black) · theme toggle · responsive collapse · Settings page layout fix · "+ Add host" button |
| v0.27.5 | 2026-05-08 | Revit multi-session — each instance binds its own port [48884..48899], publishes a session file with heartbeat. Closing one Revit session no longer kills others. Studio HOSTS row shows live session count + per-session tooltip. New `app/revit_broker.py`. RevitMCP.dll v0.3.0 rebuilt for 2025 (net8). |
| v0.27.6 | 2026-05-08 | RevitMCP.dll v0.3.0 rebuilt for 2023 + 2024 (net48) using `Microsoft.NETFramework.ReferenceAssemblies.net48` package. All three Revit versions now have multi-session DLLs. Dark theme is the new default. theme.qss made token-driven via `app/theme_builder.py` so dark mode reaches every surface (chat included). |
| v0.28 | 2026-05-08 | Add Host wizard — Studio-native panel replaces the modal onboarding fall-through. 11-row host catalog (Revit 2023/2024/2025 · AutoCAD 2024/2025/2026 · 3ds Max 2025/2026 · Blender · Speckle · Outlook). Per-row state probe (detection · build status · active), Build/Activate buttons run `auto_build` on a worker thread and stream live progress + percent to each row's progress bar. New `app/add_host_panel.py`. Triggered by the "+ Add" button on the HOSTS rail header. |
| v0.29 | 2026-05-08 | Workflows node canvas — Blueprint-style QGraphicsScene replaces the legacy WorkflowsPanel list view. 12-px minor / 60-px major drafting grid. Rounded-card NodeItem with kind ribbon, italic-serif title, in/out slots; right-angle elbow EdgeItem with arrow head. Drag-from-output to drop-on-input creates an edge. Right-click empty space opens a 6-type palette. Right-click a node opens edit-config / delete. Toolbar: Rename · Save · Open · Run. Same Workflow JSON format as the list view. New `app/workflow_canvas.py`. |
| v0.30 | 2026-05-08 | Marketplace — official catalog of Skills + Workflows (5-item seed shipped at `payload/marketplace/catalog.json`). Two-tab page (Skills · Workflows), live filter by name/tag/host, 3-column card grid with terra Install button. Skill installs via `skills.library.add_skill`; Workflow installs via `workflows.save_workflow`. New `app/marketplace_panel.py`. |
| v0.31 | 2026-05-08 | ⌘K command palette — frameless overlay reachable via Ctrl+K or the rail's command box. Live-ranked search across 5 providers: Page (nav + addhost) · Action (theme toggle, refresh, add host) · Skill (skills.library) · Session (session_io) · Market (catalog). Up/Down navigate, Enter invokes, Esc closes. New `app/command_palette.py`. |
| v0.32 | 2026-05-08 | ConnectorBirth motion (brand principle 07: quiet motion). New `_PulseDot` QLabel subclass uses QPropertyAnimation with OutCubic easing for a 600 ms two-phase intensity pulse — no bounce, no overshoot. Triggered on host-state transitions INTO live or loaded_dead so the dot "settles" when a host wakes up or is healing. The hosts rail tracks per-family previous state in `_host_prev_state` so we only animate genuine transitions. |
| v0.33 | 2026-05-08 | Parameters sidebar — right inspector now swaps between static CONTEXT KV rows and the live ParametersPanel bound to the chat session when the user is on the Chat page. Parameter edits route through the existing `_on_parameter_edited` handler so downstream steps re-run the same way they would from the legacy split-pane sidebar. Inspector caption flips to "PARAMETERS · LIVE" + "Session parameters" title on Chat. |

## Up next — committed dates (compressed per CEO)

Sprint window: 2026-05-08 → 2026-05-10. Everything below ships within
48 hours of commit. Items that genuinely require external blockers
(NuGet downloads, dev-pack installs on user machines) are flagged.

All sprint items v0.28–v0.33 shipped 2026-05-08 in a single day window
per CEO directive.

### v0.34 series — UX polish + chat reasoning + multi-host (shipped 2026-05-08)

| Ver | What |
|---|---|
| v0.34 | Voice via Win+H system dictation hand-off |
| v0.34.1 | Telemetry KPI cards · Marketplace cloud sync · Pet-strip relaunch · Outlook broker · Settings sub-line |
| v0.34.2 | theme_builder regex bug — stray Win-cyan bleed killed |
| v0.34.3 | Force Fusion + override Highlight palette + selection-color QSS |
| v0.34.4 | Chat hang fix: visible error when bubble null + startup no-LLM banner |
| v0.34.5 | Picker shows blocked providers ("out of credit") + fallback toast on auto-route |
| v0.34.6 | iOS-style toggle + sun/moon theme button + status rule matches handoff |
| v0.34.7 | Visible reasoning + status line (Anthropic extended-thinking enabled) |
| v0.34.8 | AppUserModelID + ArchMark .ico regenerated from brand path geometry |
| v0.34.9 | Real chat bubble bg (not transparent) + Ollama always shown by default |
| v0.34.10 | Studio panels read live palette via _LivePalette + dotnet detect picks Program Files |
| v0.34.11 | Outlook broker wired into HOSTS rail + marketplace cache bust + autosave session |
| v0.34.12 | Revit 2020/2021/2022 supported (net47 build) + DLL deployed |
| v0.34.13 | 👍👎 emoji feedback replaced with quiet "Helpful? yes/no" on hover |
| v0.34.14 | 3ds Max install path fix (per-user LOCALAPPDATA, was admin-only Program Files) |
| v0.34.15 | Picker dropdown contrast: enabled rows full ink, disabled inkCap |

### v0.35 — Multi-instance MCP routing (target 2026-05-10)
The biggest gap left in the multi-session story. Today the broker
DETECTS multiple Revit / Outlook sessions, but tool calls always pick
the most-recent healthy one. v0.35 makes routing first-class:

- `revit_broker.pick_session(prefer=...)` already accepts a hint —
  exposed in tool calls via `?session=<pid>` or `?doc=<title>`.
- Chat layer adds an `@<host-instance>` mention syntax: typing
  `@Tower-A` in chat scopes ALL subsequent tool calls in that turn to
  the Revit instance with that doc title.
- Tool engine respects the active session pin so multi-stage skills
  (sketch → production) bind to ONE Revit session for the whole run.
- HOSTS rail rows expand on click into a per-session sub-list (Revit
  · 3 sess → click → Tower-A · Bridge-B · Pavilion-C, each
  individually toggleable).
- Same pattern lifts to AutoCAD + 3ds Max once those connectors get
  the session-file heartbeat (v0.27.5 brought it to Revit only).

### v0.36 — OpenAI / Gemini reasoning surfacing (target 2026-05-11)
v0.34.7 added Anthropic extended-thinking. Other providers next:
- OpenAI o1 / o3 / GPT-5 reasoning_effort + reasoning summary
- Gemini 2.5 Pro / Flash thinking + thought summary
- Ollama models that emit `<think>...</think>` tagged content (DeepSeek
  R1 etc.) — already streams the tags; just needs the chat-side parser
  to route into the reasoning view instead of the answer.

### v0.37 — AutoCAD multi-session (target 2026-05-13)
Same pattern as Revit v0.27.5:
- AcadMCP.dll writes `%LOCALAPPDATA%\ArchHub\sessions\autocad-<pid>.json`
- Heartbeat every 10 s; deleted on shutdown.
- Port range [48885..48899] first-free wins.
- New `app/acad_broker.py` mirrors revit_broker API.
- HOSTS rail surfaces "AutoCAD · 2 sess" + tooltip.

### v0.38 — 3ds Max multi-session + send queue (target 2026-05-15)
- max_mcp_startup writes session file like Revit; binds first-free
  port [48886..48899].
- Tool calls into Max get queued via the existing pymxs runtime queue
  but tagged by session_id so concurrent runs don't collide.
- Outlook broker gets the same surface (already wired in v0.34.11).

### v0.39 — Marketplace remote registry (target 2026-05-17)
- `cloud_sync` already pulls from a per-firm git remote. Add an
  authoritative `marketplace.archhub.io` registry source (or whatever
  domain we land on) seeded with the ArchHub-curated catalog.
- Sign installs with the firm's GPG key (cloud_sync setup already
  generates one) so locally-installed Skills carry provenance.
- Versioning: pin Skills/Workflows by semver, surface a "1 update
  available" badge in the marketplace card.

### v0.40 — Workflow canvas v2 (target 2026-05-20)
- Right inspector pane replaces toolbar Run for selected node — live
  parameter sliders re-run the node + downstream nodes (matches
  studio-vision.jsx::Parameters).
- Node mini-map + zoom slider.
- Undo / redo on canvas edits.
- Keyboard navigation (arrow keys move selected node, Tab cycles).

### v0.41 — Settings sectioned chrome (target 2026-05-22)
- Replace the embedded SettingsDialog with native Studio sections:
  General · Sign-ins · Connectors · Cloud sync · Telemetry · Updates.
- Each section is a Studio page with header / sub / KV grid.
- Sign-ins section calls the v0.34 paste-key dialog inline.

### v0.42 — Reality Check rebuild (target 2026-05-24)
- Diagnostic panel currently uses the legacy ChatWindow popup.
- New Telemetry-tab subroute: per-host health timeline (24-hour
  uptime sparklines), recent tool errors, last-update timestamps.

### v1.0 — Public beta cut (target 2026-06-01)
- Sign installer (Inno Setup) so Defender stops complaining.
- Public landing/index.html refresh with brand v0.1 art direction.
- 30-day free trial → BYO-key tier ($0/month) → Studio firm tier
  ($199/seat/month).
- ProductHunt launch + a curated first-100 architect outreach list.

Next sprint planning starts 2026-05-09.

## Brand alignment

These are not nice-to-haves. They are the brand.

| Principle (brand.jsx §02) | Status |
|---|---|
| 01 Paper-first — even dark mode is graphite, never black | ✅ shipped v0.27.4 |
| 02 Drafted, not designed — show gridlines | ⏳ v0.29 (canvas) |
| 03 One warm color — terracotta only | ✅ shipped v0.27.4 |
| 04 Calm density — info-rich without noise | ✅ shipped v0.27.x |
| 05 Italic for soul — italic serif | ✅ shipped v0.26 |
| 06 No stock photos | ✅ enforced in Marketplace v0.30 |
| 07 Quiet motion — settle, dimension, heal | ⏳ v0.32 |

## Voice rules

These show up in error/status strings. Reviewer rejects copy that breaks them.

- ✅ "Dimensioned 47 walls in active view."
- ❌ "Successfully completed your task! 🎉"
- ✅ "Revit dropped — reconnecting on :7331."
- ❌ "Oops! Something went wrong."
- No emoji. No exclamation points. No stock-SaaS chirpiness.

## Tagline architecture

- **Primary:** "Talk to your AEC stack."
- **Short:** "Drafting table for AI." · "One chat. Every host." · "Skills, not prompts."
- **Long:** "ArchHub is a parametric design environment for architects. Chat is the input. Drawings, models, and renders are the output. Connectors self-heal. Skills are yours."
