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

## Up next — committed dates (compressed per CEO)

Sprint window: 2026-05-08 → 2026-05-10. Everything below ships within
48 hours of commit. Items that genuinely require external blockers
(NuGet downloads, dev-pack installs on user machines) are flagged.

### v0.29 — Workflows node canvas (target 2026-05-09, tomorrow)
- Replace Workflows list view with the Blueprint-style node canvas.
- Drag-to-connect node compose · LLM / tool / control node types.
- Node inspector in the right pane.
- "Save as Skill" from canvas.

### v0.30 — Marketplace (target 2026-05-09, tomorrow)
- Skills + Workflows store page — official + community.
- Install / share / version pinning. Local-cache backed.

### v0.31 — ⌘K palette overlay (target 2026-05-09, tomorrow)
- Global ⌘K opens search palette.
- Searches nav · skills · sessions · settings · running tasks.
- Keyboard-only navigation.

### v0.32 — ConnectorBirth motion (target 2026-05-10)
- Quiet motion (brand principle 07): toggle a host on, the row settles.
- Status dot pulse-to-live · self-heal hairline pulse.

### v0.33 — Parameters sidebar (target 2026-05-10)
- Right inspector becomes the live session parameters panel on Chat.
- Live re-run on slider drag.
- Replaces today's static KV rows with editable controls.

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
