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
| v0.27.5 | 2026-05-08 | Revit multi-session — each instance binds its own port [48884..48899], publishes a session file with heartbeat. Closing one Revit session no longer kills others. Studio HOSTS row shows live session count + per-session tooltip. New `app/revit_broker.py`. RevitMCP.dll bumped to v0.3.0 (2025/net8 rebuilt; 2023/2024 net48 rebuild blocked on missing .NET Framework 4.8 dev pack — auto_build will rebuild at next activation when the SDK is present). |

## Up next — committed dates

### v0.28 — Add Host wizard (target 2026-05-15)
- Bespoke Add Host panel — drop-in replacement for the onboarding wizard fall-through.
- Auto-build wizard for Revit 2023/2024/2025/2026 · AutoCAD 2024-2026 · Blender · 3ds Max · Speckle.
- Live "Detected hosts" pane on the Add Host page.
- Per-host build progress with last-build timestamps.
- Surface inside `Hosts` rail entry-point AND the existing onboarding flow.

### v0.29 — Workflows node canvas (target 2026-05-22)
- Replace Workflows list view with a Blueprint-style node canvas (matches `blueprint.jsx`).
- Drag-to-connect node compose · LLM/tool/control node types.
- Node inspector (right pane) for selected node parameters.
- Live re-run when sliders move (matches `studio-vision.jsx::Parameters`).
- "Save as Skill" from canvas.

### v0.30 — Marketplace (target 2026-05-29)
- Skills + Workflows store — official + community.
- Install / share / version pinning.
- Backed by the `Skills` registry already in production.

### v0.31 — ⌘K palette overlay (target 2026-06-05)
- Global ⌘K shortcut opens a search palette.
- Searches: nav · skills · sessions · settings · running tasks.
- Recent items pinned to top.
- Keyboard-only navigation (matches `cockpit.jsx`).

### v0.32 — ConnectorBirth motion (target 2026-06-12)
- Quiet motion (brand principle 07): toggle a host on, the row "settles".
- Status dot pulse-to-live · port number animates in.
- Self-heal animation: row hairline pulses warn → ok on reconnect.

### v0.33 — Parameters sidebar (target 2026-06-19)
- Right inspector becomes session parameters panel when on Chat page.
- Live re-run when a slider/value changes.
- Replaces today's static KV rows with live editable controls.

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
