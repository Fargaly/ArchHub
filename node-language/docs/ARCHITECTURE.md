# ArchHub — Architecture / System Map

> **The canonical "what is built and how it fits together" entry point.**
> New contributor or auditing agent: start here. This is the single map of the
> system; the per-decision rationale lives in `docs/adr/ADR-*.md` and
> `docs/agdr/AgDR-*.md`, the live plan in `docs/ROADMAP.md` (the single source
> of truth), and the derived build-state ledger in `docs/BUILT_MAP.md`. This
> file is hand-maintained prose that points at the real code; its `## Artifacts`
> list is consumed by `tools/doc_freshness.py`, so when a named module changes
> after this doc, the freshness gate marks the map stale.

ArchHub is a **PyQt6 + QtWebEngine desktop AI workspace for AEC** (architecture,
engineering, construction) professionals. The interaction model is a
**graph-first canvas**: users wire nodes — design-tool hosts, AI conversations,
filters, connector operations, code, adapters — into runnable workflows, and an
AI **Composer** can drive and edit that graph in natural language.

---

## 1. The big picture — five layers

```
┌─────────────────────────────────────────────────────────────────────┐
│  UI layer        React/JSX in QtWebEngine                             │
│                  app/web_ui/studio-lm.jsx  (the whole UI, ~5k lines)  │
│                  app/web_ui/index.html     (Babel-standalone loader)  │
└───────────────▲──────────────────────────────────────┬──────────────┘
                │  QWebChannel  (async slots → Promises) │
┌───────────────┴──────────────────────────────────────▼──────────────┐
│  Bridge layer    app/bridge.py — every JS-facing @pyqtSlot + signal   │
│                  app/main.py   — process entry, window, web shell      │
└───────────────▲──────────────────────────────────────┬──────────────┘
                │                                        │
┌───────────────┴────────────┐  ┌──────────────────────▼──────────────┐
│  Engine layer              │  │  Connector layer                     │
│  app/tool_engine.py (LLM   │  │  app/connectors/base.py (contract)   │
│   tool surface, TOOLS)     │  │  app/connectors/registry.py          │
│  app/llm_router.py (chat,  │  │  16 per-host connectors, ~116 ops    │
│   pre-prompt, providers)   │  │  app/host_detector.py (reachability) │
│  app/workflows/* (graph,   │  │  Revit · AutoCAD · Rhino · Excel ·   │
│   runner, triggers, nodes) │  │  Blender · 3ds Max · Office · …       │
└───────────────▲────────────┘  └──────────────────────────────────────┘
                │
┌───────────────┴──────────────────────────────────────────────────────┐
│  Brain layer     personal-brain-mcp/  (ambient memory + skills MCP)    │
│                  app/memory/graph.py  (in-app knowledge graph)         │
│                  daemon on :8473 — context recall, skill mint, ROMA    │
└───────────────────────────────────────────────────────────────────────┘
```

## 2. Request flow — a Composer turn, end to end

1. **User types** in the Composer (UI: `app/web_ui/studio-lm.jsx`).
2. JS calls a **bridge slot** over QWebChannel. Slots are **async** — they
   return a Promise; the JS side (`index.html` `bridgeJson` /
   `studio-lm.jsx` `bridgeAsync`) awaits. Slow work (host probes, LLM calls,
   COM/HTTP) runs **off the Qt main thread** and emits a signal back, so the UI
   never freezes (the UI-freeze class killed by AgDR-0035/0036; guarded by
   `tests/test_no_blocking_slots.py`).
3. The bridge routes the turn into **`app/llm_router.py`**, which injects
   brain context (pre-prompt recall via the brain MCP), selects a provider
   (`app/llm_providers/*`), and runs the model with the **real tool surface**
   from **`app/tool_engine.py`** (`TOOLS`). Tools follow **host reachability**
   (`app/host_detector.py`), not a settings toggle — an LLM given no real tool
   fabricates calls, so the fix is real tools, not prompt-policing.
4. Tool calls that touch a design host go through the **connector layer**
   (`app/connectors/base.py` uniform contract → the per-host runner). Every
   connector reports **honest status** (`live` / `loaded_dead` / `missing` /
   `unauthorized`) and never fabricates data when a host is offline.
5. AI writes to a host are **approval-gated by default** (USER-AGENCY): the
   Composer's Plan / Auto / YOLO modes decide whether a write auto-applies.
6. The turn is persisted as an **`ai.plan` canvas node** (auditable + replayable
   per AgDR-0021), and the trajectory is written to the **brain** (PostToolUse →
   `brain.write`), where successful trajectories can mint reusable skills.

## 3. The canvas substrate (ARCHITECTURE LOCK — Direction X)

Locked by `docs/agdr/AgDR-0012-architecture-direction-x.md` and
`docs/agdr/AgDR-0048-*` (custom canvas supersedes the never-installed ReactFlow):

- **Composer is the primary IDE.** Chat drives + edits + runs the graph; the
  canvas is the materialised execution + inspection surface.
- **The custom canvas is the substrate** — `NodeView` + `WireLayer` + `LM_GRAPH`
  inside `app/web_ui/studio-lm.jsx`. It carries every shipped canvas feature.
- **Every wire is a Speckle `Operations.send/receive` segment.** Default
  `DiskTransport` at `.speckle/<project>/` — no server, no Docker, no account,
  fully offline (`app/speckle_client.py`, `app/speckle_wire.py`). Cloud Speckle
  is opt-in collaboration.
- **`ai.plan` is a real canvas node** (`app/workflows/nodes/ai_plan.py`):
  Composer ≡ `ai.plan` engine, two surfaces over one record.

The workflow engine (`app/workflows/graph.py` + `app/workflows/runner.py`) is a
lazy / dirty / cached cook: a node re-cooks only when its inputs change.
Library-First governs node creation (`app/library.py` + `app/library_gate.py` +
`app/library_validator.py`): `library.search` runs BEFORE `create_node_type`, so
the agent reuses an existing node instead of minting a duplicate.

## 4. The brain (ambient agent substrate — AgDR-0044)

`personal-brain-mcp/` is a standalone MCP daemon (HTTP/SSE on `:8473`) that is
the **shared memory + skills + setups + secrets-refs** layer for every AI client
(Claude Code, Codex, the ArchHub Composer, …). It is the moat: sessions that
bypass it accumulate context debt.

- **Store of record:** `brain.db` (SQLite + FTS5) —
  `personal-brain-mcp/src/personal_brain/storage.py`. Fragments + skills carry
  `scope` / `visibility` / `owner_user` / `project_id` / `firm_id`, half-life
  decay, and success/fail counts.
- **In-app graph twin:** `app/memory/graph.py` (the AgDR-0042 knowledge graph,
  `graph.sqlite`). Unifying the two stores is the named ONE-SYSTEM debt that
  AgDR-0054 addresses (build-pending).
- **Wiring:** UserPromptSubmit → `brain.context`, PostToolUse → `brain.write`,
  Stop → `brain.skill_mint` (`personal-brain-mcp/src/personal_brain/client_hook.py`,
  `installer.py`).
- **Verify gate (ROMA):** `requirement_tree.py` + `court_harness.py` + `roma.py`
  + `diligence.py` — a three-lens jury (artifact / diligence / independence)
  that must FAIL TO REFUTE a leaf on the real artifact before it goes green.
  `docs/BUILT_MAP.md`'s "verified-complete units" are this ledger's GREEN leaves.

ArchHub is exposed to Claude Code as an MCP server too —
`app/archhub_mcp_server.py` (see `docs/RUN-MCP.md`).

## 5. Where to look — by task

| You want to … | Start in |
|---|---|
| Add / change a JS-facing capability | `app/bridge.py` (slot) + `app/web_ui/studio-lm.jsx` (UI) |
| Change the LLM's tools | `app/tool_engine.py` (`TOOLS`) |
| Change chat / provider routing | `app/llm_router.py`, `app/llm_providers/` |
| Add / fix a design-host connector | `app/connectors/base.py` + the per-host `*_runner.py` |
| Touch the graph engine | `app/workflows/graph.py`, `app/workflows/runner.py` |
| Touch node behaviour | `app/workflows/nodes/` |
| Touch shared memory / skills | `personal-brain-mcp/src/personal_brain/`, `app/memory/graph.py` |
| Understand a past decision | `docs/agdr/AgDR-*.md`, `docs/adr/ADR-*.md` |
| See the live plan | `docs/ROADMAP.md` (single source of truth) |
| See what's built (derived) | `docs/BUILT_MAP.md` |

## 6. Cross-cutting rules baked into the code

- **No blocking the Qt main thread** in a slot — background thread + signal,
  always (`tests/test_no_blocking_slots.py` guards it).
- **Connectors report honest status**, never fabricate offline data
  (`app/connector_health.py`).
- **Every AI write is reversible + approval-gated by default** (USER-AGENCY;
  Speckle Versions are immutable, undo = receive previous Version).
- **Docs stay reconciled with reality** — `tools/doc_reconcile.py` (ROADMAP ↔
  AgDR ledger, R1–R4) and `tools/doc_freshness.py` (artifact-staleness index)
  are merge-time gates; `tools/build_map.py` derives `docs/BUILT_MAP.md` from
  AgDR frontmatter + the ROMA tree, never hand-typed.

## Artifacts

The code this map describes (consumed by `tools/doc_freshness.py` for
staleness). When any of these changes after this doc's commit, the freshness
gate flags `ARCHITECTURE.md` stale so the map is brought back into sync:

- `app/main.py`
- `app/bridge.py`
- `app/tool_engine.py`
- `app/llm_router.py`
- `app/host_detector.py`
- `app/connectors/base.py`
- `app/connectors/registry.py`
- `app/connector_health.py`
- `app/workflows/graph.py`
- `app/workflows/runner.py`
- `app/workflows/nodes/ai_plan.py`
- `app/library.py`
- `app/library_gate.py`
- `app/library_validator.py`
- `app/speckle_client.py`
- `app/speckle_wire.py`
- `app/memory/graph.py`
- `app/archhub_mcp_server.py`

Related design records: `docs/adr/ADR-001-cloud-hosting.md`,
`docs/adr/ADR-002-memory-architecture.md`,
`docs/adr/ADR-003-graph-first-architecture.md`,
`docs/agdr/AgDR-0012-architecture-direction-x.md`,
`docs/agdr/AgDR-0048-supersede-reactflow-lock.md`,
`docs/agdr/AgDR-0044-personal-brain-mcp.md`.
Live plan: `docs/ROADMAP.md`. Derived build state: `docs/BUILT_MAP.md`.
