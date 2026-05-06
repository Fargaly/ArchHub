# ArchHub

**Talk to your AEC stack. Drive Revit, Blender, AutoCAD, 3ds Max, and
Speckle from one chat. Save what works as a Skill — copy-paste shareable
JSON your firm owns.**

[![Release](https://img.shields.io/github/v/release/Fargaly/ArchHub?include_prereleases)](https://github.com/Fargaly/ArchHub/releases/latest)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Built with Claude](https://img.shields.io/badge/built%20with-Claude-cc785c)](https://claude.com)

---

## What it does

- **Type, don't script.** "Dimension all walls in the active view" runs
  in Revit. "Build this sketch as a 6 m gabled mass" runs in Blender.
  ArchHub generates the API code, executes it live, shows you the
  result.
- **Vision input.** Paste a hand sketch into chat. Claude / GPT-4o /
  Gemini reads it and drives the modelling tools to build it.
- **Skills.** Save any useful conversation as a reusable Skill —
  intent-tagged JSON the matcher finds next time you ask for the same
  thing. Skills are copy-paste shareable, like ComfyUI workflows.
- **End-to-end pipeline.** The flagship `Sketch to production` Skill
  chains six LLM stages: extract mass → push to Speckle → set up
  Revit project → build walls → place doors and windows → generate
  production sheets. One click; six tools coordinated.
- **Multi-LLM, BYO-key.** OpenRouter (real OAuth, ~300 models),
  Anthropic, OpenAI, Google, or local Ollama. Your choice; your keys;
  your data.
- **Cloud-synced Skills.** A private GitHub repo (auto-created by
  ArchHub) syncs your Skill library across devices. Save on laptop,
  open on workstation.
- **Click-only setup.** No terminal. Run the installer; sign in via
  browser; pick a Skill.

---

## Quick start

### Install (Windows)

1. Download the latest `ArchHub-Setup-x.y.z.exe` from
   [Releases](https://github.com/Fargaly/ArchHub/releases/latest).
2. Double-click the installer. Desktop icon, Start menu shortcut, and
   optional sign-in-on-startup are added.
3. Launch ArchHub. The first-run wizard signs you in to a cloud LLM
   and shows what AEC tools are detected.

### Install (from source, any OS)

```bash
git clone https://github.com/Fargaly/ArchHub
cd ArchHub
pip install -r app/requirements.txt
python app/main.py
```

### First Skill to try

In chat, type:

```
Dimension all the walls in the active view
```

ArchHub matches the saved `Dimension walls in active view` Skill,
proposes it, and runs it through Revit. ~5 seconds end-to-end.

---

## Pricing

| Tier | $/seat/mo | What's in it |
|---|---:|---|
| **Free** | $0 | Up to 3 saved Skills · local Ollama only · single device |
| **Pro** | $39 | Unlimited Skills · cloud sync · BYO API keys · 5 devices |
| **Studio** | $79 | Pro + cloud LLM relay · firm Skill library · cost dashboard · phone support |
| **Enterprise** | custom | Studio + self-hosted relay · custom Skills · dedicated support |

Pro tier ships with v1.0 (target Q3 2026). Until then, **everything is
free** — install, use, give feedback.

---

## Architecture

```
                ┌──────────────────────────┐
                │   ArchHub desktop (PyQt6) │
                │   - chat                  │
                │   - Skill library         │
                │   - parametric sidebar    │
                └──────────┬───────────────┘
                           │
              ┌────────────▼────────────┐
              │     LLMRouter            │
              │  Anthropic · OpenAI ·    │
              │  Google · OpenRouter ·   │
              │  Ollama · firm relay     │
              └────────────┬────────────┘
                           │
              ┌────────────▼────────────┐
              │     ToolEngine           │
              │  exposes connectors as   │
              │  schema'd tools          │
              └────────────┬────────────┘
                           │
   ┌───────────┬───────────┼───────────┬───────────┐
   ▼           ▼           ▼           ▼           ▼
 :48884     :48885     :48886       :9876     Speckle GraphQL
 RevitMCP   AcadMCP    3ds Max      Blender   (cloud or self-host)
```

Skills live as JSON files in a private GitHub repo synced from
`%LOCALAPPDATA%\ArchHub\data_repo\`. Each Skill is a workflow graph:
input → template → llm.complete_with_tools → output. Multi-stage Skills
chain those nodes. The actual API code (Revit C#, Blender Python, etc.)
is generated fresh per project by the LLM at run time — Skills carry
intent and constraints, not implementation, so smarter models make
Skills more valuable, not less.

---

## Why ArchHub vs the alternatives

| | **ArchHub** | Hypar | Autodesk Forma | TestFit | ChatGPT Desktop |
|---|---|---|---|---|---|
| Chat-driven UX | ✓ | partial | – | – | ✓ |
| Drives Revit natively | ✓ | partial | ✓ | – | – |
| Drives Blender natively | ✓ | – | – | – | – |
| Skills (saved, shareable) | ✓ | – | – | – | partial |
| Local LLM option (IP) | ✓ | – | – | – | – |
| Multi-LLM router | ✓ | – | – | – | – |
| Open source | ✓ | – | – | – | – |
| Self-hostable | ✓ | – | – | – | – |
| Free tier | ✓ | – | – | – | (chat only) |

---

## Documentation

- **[STRATEGY.md](STRATEGY.md)** — pricing, GTM, moats, financial model.
- **[docs/SKILLS.md](docs/SKILLS.md)** — Skill architecture: metadata, matcher, capture, sharing.
- **[docs/MULTI_DEVICE.md](docs/MULTI_DEVICE.md)** — running ArchHub on multiple machines.
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

See [CONTRIBUTING.md](CONTRIBUTING.md) (to be written) or open an issue
to discuss before starting on something large.

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
