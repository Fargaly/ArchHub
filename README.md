# ArchHub (v1.4.0-alpha)

**A graph-first AI workspace for AEC.** Every entity — a host (Revit,
AutoCAD, 3ds Max, Blender, Rhino, Speckle, Outlook, Teams, Notion,
LM Studio, Antigravity, Photoshop, Illustrator, InDesign, Word,
Excel, PowerPoint, Dropbox — **18 host families**), a conversation
with Claude, a document, a tool call — lives as a **typed node** on
a **canvas**. Wire them together with typed bridges. Save the canvas
as a **Skill** — copy-paste shareable JSON your firm owns.

[![Release](https://img.shields.io/github/v/release/Fargaly/ArchHub?include_prereleases)](https://github.com/Fargaly/ArchHub/releases/latest)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Built with Claude](https://img.shields.io/badge/built%20with-Claude-cc785c)](https://claude.com)

---

## What it does (v1.4)

- **Canvas, don't script.** Drag a Revit host, a "list_walls" reader,
  a "where exterior" filter, and a "create_dimensions" annotator onto
  the canvas. Wire them. Press ▶. The wall list flows through the
  filter, dimensions land in Revit. 80 node types across 10
  categories — host / read / filter / transform / annotate /
  compose / logic / AI / output / trigger (see
  [`docs/NODE_LIBRARY_v2.md`](docs/NODE_LIBRARY_v2.md)).
- **AI-agent composer.** Type "ping outlook" in free text and the
  agent spawns the Outlook host + a conversation node and wires them
  for you. Seven tools (`spawn_host` / `spawn_node` / `wire` /
  `focus` / `rename` / `delete` / `run`) lifted from natural
  language. You confirm per-chip; nothing mutates without consent.
- **Vision input.** Paste a hand sketch onto a `vision` node. Claude
  / GPT-4o / Gemini reads it and drives the modelling tools to build
  it downstream.
- **Skills are subgraphs.** Cmd-G compresses a selection into a
  composite. Right-click → Save as Skill. It drops onto any other
  canvas as a single composite node. The matcher finds it by intent
  for chat-style invocation.
- **Multi-LLM, BYO-key.** OpenRouter (real OAuth, ~300 models),
  Anthropic, OpenAI, Google, or local LM Studio. Your choice; your
  keys; your data. Native PyQt SettingsDialog → Providers tab.
- **Native session storage.** Each session is one JSON file in
  `%LOCALAPPDATA%\ArchHub\sessions\`. Autosaved on every change.
  Optional firm sync via OneDrive symlink or a self-hosted relay.
- **Click-only setup.** No terminal. Run the installer; sign in via
  browser; the host-pill row tells you which apps are live.

---

## Quick start

### Install (Windows)

**Easiest** — via package manager (no SmartScreen warning, signed by
the package transport):

```cmd
winget install Fargaly.ArchHub
```

or

```cmd
scoop install https://raw.githubusercontent.com/Fargaly/ArchHub/main/installer/scoop/archhub.json
```

or

```cmd
choco install archhub
```

**Direct download** — installer .exe, double-click to install:

1. Download the latest `ArchHub-Setup-x.y.z.exe` from
   [Releases](https://github.com/Fargaly/ArchHub/releases/latest).
2. Double-click the installer. Desktop icon, Start menu shortcut, and
   optional sign-in-on-startup are added.
3. Launch ArchHub. The first-run wizard signs you in to a cloud LLM
   and shows what AEC tools are detected.

The direct-download path will show a Windows SmartScreen warning until
the SignPath OSS Authenticode application clears (in progress). The
package-manager paths sidestep this entirely because the package
manager itself is signed.

### Install (from source, any OS)

```bash
git clone https://github.com/Fargaly/ArchHub
cd ArchHub
pip install -r app/requirements.txt
python app/main.py
```

### First canvas to try

Type into the composer:

```
list walls in the active view, then dimension the exterior ones
```

The agent composer spawns four nodes and wires them — `h_revit`,
`r_walls`, `f_pred` (`is_exterior`), `a_dims`. Confirm the chip
chain, press **▶ Run Workflow**. Dimensions land in Revit; the saved
canvas is your first Skill candidate.

Cmd-G the four nodes → right-click composite → **Save as Skill** →
fill name / intent / keywords. Next time you type "dimension exterior
walls" the matcher proposes the saved Skill.

---

## Pricing

ArchHub is currently in open beta and all shipped features are free.
See `docs/PRICING_STATUS.md` for the canonical pricing state.

- **Free (today)** — everything that works: unlimited Skills, local
  Ollama or BYO cloud key, cloud sync via your own private GitHub repo,
  vision input, sketch → production pipeline, auto-update. MIT-licensed.
- **Studio (coming soon)** — managed cloud relay for firms. Provider
  keys live on the relay, not on architect laptops; per-architect rate
  limits, audit logs, firm-shared Skill library, centralised billing.
  No price set until the relay is deployed and verified.
  [Join the waitlist](https://github.com/Fargaly/ArchHub/issues/new?labels=studio-waitlist&title=Studio+waitlist).
- **Enterprise (coming soon)** — self-hosted relay so traffic never
  leaves your infrastructure, plus custom Skill development against
  firm standards.
  [Open an enquiry](https://github.com/Fargaly/ArchHub/issues/new?labels=enterprise&title=Enterprise+enquiry).

---

## Architecture (v1.4)

```
                ┌────────────────────────────────────────┐
                │   ArchHub desktop (PyQt6 + QWebEngine) │
                │                                        │
                │   web_ui/studio-lm.jsx  (React canvas) │
                │     ▲                                  │
                │     │  QWebChannel · 115+ slots        │
                │     ▼                                  │
                │   app/bridge.py  (PyQt6 QObject)       │
                │     sessions · graph · wires · agent   │
                │     hosts · skills · memory · mcp      │
                └──────────┬─────────────────────────────┘
                           │
              ┌────────────▼─────────────┐
              │     LLMRouter            │
              │  Anthropic · OpenAI ·    │
              │  Google · OpenRouter ·   │
              │  LM Studio · firm relay  │
              └────────────┬─────────────┘
                           │
              ┌────────────▼─────────────┐
              │     ToolEngine           │
              │  exposes connectors as   │
              │  schema'd tools          │
              └────────────┬─────────────┘
                           │
   ┌─────────────┬─────────┴──────┬─────────────────┬─────────────┐
   ▼             ▼                ▼                 ▼             ▼
 :48884       :48885           :48886           runners       Graph APIs
 RevitMCP     AcadMCP          3ds Max MCP      Blender,      Speckle,
 (2020,                                          Rhino,        Outlook,
  2023,                                          Procore       Teams,
  2024,                                                        Notion,
  2025)                                                        Dropbox
```

Hosts surface as the canvas **host-pill row** — `app/host_detector.py`
probes 18 families (process / COM / HTTP / token) and the JSX re-polls
`bridge.get_all_hosts` every 25 s.

Sessions live as JSON files in `%LOCALAPPDATA%\ArchHub\sessions\<slug>.archhub-session.json`.
Each session is one canvas. Each canvas can be saved as a Skill —
intent-tagged JSON synced via OneDrive symlink or a firm-shared
network path. Skills carry intent and constraints, not implementation
— so smarter models make Skills more valuable, not less.

---

## What makes ArchHub different

Six commitments built into the product — none of them optional.

- **Open source you can audit.** MIT-licensed, every line on GitHub.
  Read it, fork it, run it offline. Your firm's IT team verifies what
  the binary does before it touches a project file.
- **Local LLM option for IP-sensitive work.** Plug in Ollama and the
  entire chat runs on your machine — no model traffic leaves the
  laptop. Switch to a cloud provider only when you choose.
- **Skills you own and edit.** Every saved Skill is a JSON file.
  Copy, paste, version, fork, delete. No marketplace lock-in.
- **Multi-tool, multi-LLM, multi-host.** Revit, Blender, AutoCAD,
  3ds Max, Speckle — driven from one chat. Anthropic, OpenAI, Google,
  OpenRouter, local — your choice of model.
- **BYO key, BYO firm relay.** Bring your own API keys, or point
  ArchHub at a self-hosted firm relay so provider keys never sit on
  architects' laptops. Both paths are first-class.
- **Free tier with no credit card.** Download, install, use. No trial
  countdown, no upsell modal, no payment method required.

---

## Documentation

**Browseable docs site:** https://www.notion.so/358f57b4e72f81f99f50ffaa2cdea4be (publishing as `archhub.notion.site` shortly)

Source of truth in this repo:

- **[STRATEGY.md](STRATEGY.md)** — pricing, GTM, moats, financial model.
- **[docs/USER_GUIDE.md](docs/USER_GUIDE.md)** — v1.4 user-facing walkthrough.
- **[docs/AUDIT_2026-05-14.md](docs/AUDIT_2026-05-14.md)** — current state audit, surface-by-surface.
- **[docs/NODE_LIBRARY_v2.md](docs/NODE_LIBRARY_v2.md)** — 80-node canvas taxonomy.
- **[docs/CANVAS_PLAN.md](docs/CANVAS_PLAN.md)** — canvas architecture (current v1.4 + historical v0.18 plan).
- **[docs/SKILLS.md](docs/SKILLS.md)** — Skill architecture: metadata, matcher, capture, sharing.
- **[docs/MULTI_DEVICE.md](docs/MULTI_DEVICE.md)** — running ArchHub on multiple machines.
- **[docs/RELIABILITY.md](docs/RELIABILITY.md)** — reliability expectations, known limits, and failure modes.
- **[SECURITY.md](SECURITY.md)** — threat model + responsible disclosure.
- **[DEVELOPMENT_LOG.md](DEVELOPMENT_LOG.md)** — running record of decisions and pivots.
- **[VISION.md](VISION.md)** — north-star product principles.

---

## Contributing

Open-source under MIT. Contributions welcome — especially:

- New Skill JSONs covering host-specific workflows (drop them under
  `app/skills/seeds/` or save via `/skill save` in chat and PR the
  resulting file)
- Connector adapters for hosts ArchHub doesn't speak yet (Rhino,
  SketchUp, Fusion 360)
- Provider clients (Mistral, Cohere, local self-hosted endpoints)

See [CONTRIBUTING.md](CONTRIBUTING.md) or open an issue to discuss
before starting on something large.

---

## License

MIT. See [LICENSE](LICENSE).

The ArchHub Cloud Relay (commercial offering for Studio / Enterprise)
runs on closed infrastructure and is not part of this repo. The desktop
client and all Skill primitives are MIT and always will be.

---

## Status

Active development. Production-ready for solo use; multi-firm rollout in
private pilot. v1.0 ship target: Q3 2026.

[![GitHub stars](https://img.shields.io/github/stars/Fargaly/ArchHub?style=social)](https://github.com/Fargaly/ArchHub)

If you build something with ArchHub, post a screenshot — we love it.


<!-- archhub-auto:changelog:start -->
### Last 24 hours

<!-- auto-updated daily by agents/publish.py -->

- `ebccff7` feat(autonomy): CEO routine â€” hourly diagnose+plan+act + daily brief
- `3d73285` feat(autonomy): auto-update + kill remaining CMD-flash sources â€” v0.27.0
- `8001f43` feat(ui): apply Anthropic brand-guidelines palette + Poppins/Lora typography
- `fc06dbf` feat(connector): Outlook (classic) â€” read inbox, search, draft replies â€” v0.26.0
- `c84176f` fix(chat): differentiate 'host not running' vs 'host running, addin not loaded'
- `480aaf5` fix(skill): tighten Construction Doc Sprint Stage 2 prompt with C# scaffold + smoke tests
- `6d5a707` fix(ux): kill pet auto-spawn + trim recurring jobs to ones that produce daily new signal â€” v0.25.2
- `4333851` fix(ux): HUD overlay default OFF â€” pets stay the only ambient layer â€” v0.25.1
- `b414348` feat(hud): configurable toggle hotkey â€” Settings â†’ Appearance
- `2c94972` feat(ux): HUD overlay chrome â€” frameless, translucent, always-on-top â€” v0.25.0
- `abbe6c3` feat(notify): no-auth status channels â€” desktop file + Win toast + Discord webhook â€” v0.24.1
- `15f2747` feat(autonomy): pet overlay + hourly cron + meta-skills â€” v0.24.0
- `6a4c6f2` fix(llm): wire Gemini provider + auto-fallback when Anthropic/OpenAI dead â€” v0.23.2
- `b03cf54` fix(connectors): tolerate locked DLL â€” keep loaded version, write addin anyway
- `1a601ce` feat(skills): Construction Doc Sprint Pack â€” flagship paid Skill â€” v0.23.0
- `c43d911` feat(agents): Sprint 2 â€” TelemetryAgent + BacklogAgent + WatcherAgent + feedback widget â€” v0.22.0
- `fba885a` fix(telemetry): use eu.i.posthog.com ingest host (events were 404'ing silently)
- `bb0be53` feat(settings): Privacy panel â€” paste PostHog/Sentry keys + test send
- `dc80787` feat(telemetry): Sprint 1 â€” opt-in PostHog + Sentry + retry signal â€” v0.21.0
<!-- archhub-auto:changelog:end -->
