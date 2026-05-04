# ArchHub — Development Log

A running record of architectural decisions, pivots, and rationale.
Newest entries at top.

---

## v0.2 — 2026-05-04 — Standalone product with multi-LLM brain

**Pivot:** ArchHub is no longer a Claude Desktop helper. It's its own
desktop application with built-in chat, multi-LLM router, tool execution
engine, and Speckle integration. Claude Desktop is no longer required for
end users.

**Why:** A connector toggle UI alone forces every user to also install
Claude Desktop and configure it. That's two products, two installations,
two failure surfaces. ArchHub becomes the product instead.

**What changed:**
- New: `chat_window.py` — main UI, streaming responses, inline tool-call cards
- New: `llm_router.py` — auto-routes to Claude/OpenAI/Gemini based on task signal
- New: `llm_providers/{anthropic,openai,google}_client.py` — per-provider clients
- New: `tool_engine.py` — single tool catalogue, dispatches to host HTTP servers
- New: `speckle_client.py` — Speckle GraphQL client (list_projects, get_project)
- New: `secrets_store.py` — Windows Credential Manager via keyring with file fallback
- New: `settings_dialog.py` — manage API keys per provider
- New: `agents/` — pluggable agent framework, `DimensionsAgent` skeleton
- Updated: `main.py` boots ChatWindow instead of ConnectorPanel
- Updated: installer bundles anthropic, openai, keyring SDKs

**Tool-use loop lives in LLMRouter.** When a model emits a tool call, the
router runs it through ToolEngine, packages the result, and feeds it back.
Up to 12 iterations per turn (safety cap on runaway agents).

**Auto-routing heuristics (v0):**
- Modeling signals (revit/autocad/3ds max/blender/wall/extrude/...) → Claude Opus
- Analysis signals (schedule/quantity/audit/explain/...) → Claude Sonnet
- Quick chat → Claude Haiku
- Default → Claude Sonnet
- Fallback chain when Anthropic key missing: OpenAI → Google

This is keyword-based and crude. Upgrade path: small classifier model
(GPT-4o-mini or Haiku) does intent classification, then routes.

---

## v0.1 — 2026-05-04 — Connector toggle product (superseded)

First attempt: a tray app + connector toggle panel that registered a
unified MCP server in Claude Desktop's config. Worked but dependent on
Claude Desktop being installed and running.

**Components built that survived into v0.2:**
- `manager.py` — ConnectorManager with state persistence
- `detection.py` — Detect installed Autodesk/Blender/Rhino/SketchUp
- `connectors/registry.py` — Per-family activate/deactivate (Revit addin
  install, AutoCAD HKCU registry, 3ds Max startup script, Blender addon)
- `tray.py` — System tray icon
- Inno Setup installer (`installer/setup.iss` + `build.bat`)
- Theme stylesheet (`theme.qss`)

---

## Pre-ArchHub — Earlier sessions

- Built `AutodeskMCP/` as a comprehensive C# add-in suite for Revit and
  AutoCAD with Roslyn live scripting, plus a 3ds Max pymxs HTTP server.
  These are the "payload" binaries ArchHub installs into the host
  applications.
- Designed the original Blender → Fusion → Revit interop chain.
- Researched Speckle: $19.2M Series A, 20+ connectors, Apache 2.0
  license. Decision: build ON TOP of Speckle, not against it. Speckle
  becomes ArchHub's data spine for cross-tool interop.

---

## Open questions / next milestones

- **Agent execution path.** `DimensionsAgent.run()` is a skeleton. Need
  to implement the LLM-with-restricted-tools pattern: run the router
  with a tool whitelist (e.g. only `revit_*`), capture invocations,
  return AgentResult.
- **Speckle round-trip.** Push geometry from Revit → Speckle → Blender
  in one prompt. ToolEngine has `speckle_list_projects` and
  `speckle_get_project`; needs `speckle_create_version` and
  `speckle_pull_to_<host>` tools.
- **Connector payload binaries.** Revit/AutoCAD DLLs need to be built
  per-version (2024, 2025, 2026) from the C# source in `AutodeskMCP/`
  and dropped into `payload/{revit,autocad}/<year>/`. One-time per
  Autodesk release.
- **Icons.** `app/assets/archhub.ico` and `archhub.png` need to be
  designed before shipping the polished installer.
- **Image input in chat.** Drop a screenshot, ArchHub uses multimodal
  Claude/GPT-4o to interpret it.
- **Project memory.** Per-project conversation history + Speckle metadata
  for continuity across sessions.
- **Council mode.** Run multiple LLMs in parallel on hard prompts, pick
  the best answer. Requires a judge model and a UX for when two
  responses differ meaningfully.

---

## Architectural principles (so far)

1. **Bring-your-own keys.** No hosted relay in v0; users provide their
   own Anthropic/OpenAI/Google/Speckle credentials. Stored in OS
   keyring. Future commercial path: optional managed relay with
   subscription.

2. **Local-first.** All host application servers run on localhost. No
   user model data leaves the machine without an explicit Speckle push
   or LLM tool call.

3. **Speckle is the interop spine.** We don't reinvent BIM
   serialization. Speckle's object graph + connectors carry the data.

4. **The LLM is replaceable.** Every provider implements the same
   `stream_completion(...)` interface. New providers slot in without
   touching the router or tool engine.

5. **Connectors stay sovereign.** Toggling on Revit installs an addin
   into Revit; toggling off removes it cleanly. No vendor lock-in.

---
