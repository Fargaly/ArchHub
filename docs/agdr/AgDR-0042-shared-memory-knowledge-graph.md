---
id: AgDR-0042
timestamp: 2026-05-24
status: executing
founder-signoff: 2026-05-25 — picked D1·C (ship ALL 6 slices) on docs/prototypes/four-decisions-2026-05-25.html + reaffirmed on docs/prototypes/scope-reality-2026-05-25.html (committed to 7-25d realistic spread)
category: architecture
supersedes: none
builds-on: [AgDR-0038, AgDR-0040, AgDR-0041]
slices-shipped:
  - "slice 1/6 — app/memory/graph.py core data model + SQLite store (2026-05-25)"
slices-remaining: [2, 3, 4, 5, 6]
---

# AgDR-0042 — Shared-memory knowledge graph (graphify-style data model)

> **Proposed 2026-05-24.** Founder reviewed the graphify run on the
> ArchHub repo itself (12 491 nodes, 25 440 edges, 0 LLM tokens) and
> proposed extending the primitive beyond dev tooling into the
> product's shared-memory layer. **Ships v1.5** (after the 4-week
> AgDR-0041 + ComfyUI/Alibaba build).

## Context

Today ArchHub has four memory surfaces, each a separate store:

| Surface | Today | Search method |
|---------|-------|---------------|
| **Library** | `app/library.py` SQLite | `node_search` Jaccard on intent + name |
| **Project history** | `.archhub/plans/*.json`, Speckle Versions | none (file-by-file) |
| **Composer turns** | `app/conversation/*` | last-N transcript scan |
| **User Skills** | `~/.archhub/skills/` | name match |

Founder, 2026-05-24: *"I think it would be good for the shared
memory systems that we discussed before not only for the dev work."*

Graphify proved the data model works on code (12 491 nodes / 25 440
edges from 543 files, zero LLM tokens via tree-sitter AST). The
**same primitive** applied to AEC + Composer + Library data unifies
all four memory surfaces into one queryable graph.

This is the *shared-memory* substrate the founder discussed earlier
in 2026 — multiple Composer turns + multiple sessions + multiple
seats in a firm all writing to / reading from a single graph.

## Options considered

| # | Option | Verdict |
|---|--------|---------|
| 1 | Keep four separate stores, add cross-link table | ✗ glue code grows linearly with surfaces; no community detection; no path queries |
| 2 | Fork graphify, run on ArchHub data | ✗ heavyweight; graphify is dev-tool-shaped (CLI, file-watcher) |
| 3 | Adopt graphify's data model + community-detection algos, build into ArchHub natively | ✓ **chosen** — same JSON shape, our extractors, our search |
| 4 | Use Neo4j as backing store | ✗ +1 process to ship; graph fits in SQLite at our scale |

## Decision

Build a unified **MemoryGraph** in `app/memory/` with the graphify
data model (nodes + typed edges + EXTRACTED / INFERRED confidence).
Four extractors feed it, one search tool reads it.

### Data model

```jsonc
{
  "nodes": [
    {"id": "lib:cap:revit.read_walls", "kind": "capability", "label": "…"},
    {"id": "lib:skill:hero_render",    "kind": "skill",      "label": "…"},
    {"id": "proj:tower2:wall_134",     "kind": "design",     "label": "…"},
    {"id": "turn:2026-05-24:14:22",    "kind": "turn",       "label": "…"},
    {"id": "agdr:0040",                "kind": "decision",   "label": "…"}
  ],
  "edges": [
    {"source": "lib:skill:hero_render", "target": "lib:cap:revit.read_walls",
     "relation": "contains", "confidence": "EXTRACTED"},
    {"source": "turn:2026-05-24:14:22", "target": "lib:skill:hero_render",
     "relation": "used", "confidence": "EXTRACTED"},
    {"source": "proj:tower2:wall_134", "target": "lib:skill:hero_render",
     "relation": "rationale_for", "confidence": "INFERRED"}
  ]
}
```

### Four extractors

1. **`memory.extract_library()`** — Capability Nodes + Skills → `lib:*` nodes,
   subgraph members → `contains` edges, port-type compatibility → `wires_with`.
2. **`memory.extract_project()`** — Speckle Versions, Revit families,
   AutoCAD blocks, drawing PDFs → `proj:*` nodes.
3. **`memory.extract_turns()`** — Composer turns from `ai.plan` cache →
   `turn:*` nodes, tools used → `called` edges, nodes placed → `used` edges.
4. **`memory.extract_decisions()`** — `docs/agdr/*.md` frontmatter →
   `agdr:*` nodes, `builds-on:` → `builds_on` edges, code paths in
   Artifacts section → `rationale_for` edges back to `lib:*`.

### One search tool

`memory.query(question)` — replaces `node_search`. Uses BFS traversal
from candidate seeds (token overlap, port-type match), ranks results
by community + edge weight + recency. Returns Skills / Capabilities /
prior turns ordered by relevance.

Composer prompt: *"find me a Skill that takes a Revit wall list and
emits a costed schedule"* → traversal walks
`turn:*` (past attempts) → `lib:skill:*` (with matching I/O) →
`lib:cap:*` (composing them). Returns top-3 Skills + the turn that
created each.

### Multi-seat sharing (Firm tier)

Firm-tier seats share one MemoryGraph per company (per AgDR-0001
LIBRARY-FIRST mandate). New seat joins → inherits firm's collective
graph instantly. Founder's mental model: "every architect's
Composer turn writes back to the firm's shared memory; next month
the new hire's first session already knows the firm's typical
wall-takeoff Skill."

### Validator + community detection

- Run **Louvain** community detection on every write (incremental,
  background). Surfaces "god nodes" — most-reused Capabilities.
- These auto-promote in `node_search` ranking.
- Communities visible in the Library UI as collapsible sections
  ("Your wall workflows", "Your QTO workflows", etc.) without manual
  tagging.

## Consequences

- **One memory, four entry points** — no more glue code between
  Library / Project / Turns / Decisions.
- **Composer gets context for free** — `ai.plan` queries the graph
  to find prior turns that solved similar problems. Replay-aware.
- **Firm shared library becomes real** — multi-seat plans (Studio / Firm)
  gain a single shared brain. New seat inherits everything.
- **Cost** — graph builds and queries are local + AST-only by
  default (graphify proved zero LLM tokens on 543 files). LLM
  semantic merge is optional (off by default, on for INFERRED edges
  when user opts in).
- **Storage** — SQLite + JSON cache. ~12 MB per 10k nodes (measured
  on ArchHub's own graph today). Scales to ~100k nodes per firm
  before considering Neo4j upgrade.
- **Privacy** — local-first preserved. Firm-shared graph syncs via
  Speckle Versions (already content-addressed + auditable).

## Build slices (v1.5 — after AgDR-0041 + 4-week Comfy/Alibaba)

1. **Slice 1** — `app/memory/graph.py` core data model + SQLite store.
2. **Slice 2** — Library extractor + Composer-turn extractor (the two
   highest-value entry points).
3. **Slice 3** — `memory.query()` BFS search; integrate into
   `tool_engine` as a `library_search_v2` tool (back-compat shim
   keeps `node_search` working).
4. **Slice 4** — Project + Decision extractors; cross-source linking.
5. **Slice 5** — Louvain community detection + Library UI sections.
6. **Slice 6** — Firm shared-graph sync over Speckle.

## Artifacts

- This AgDR.
- `graphify-out/` — initial graphify pass on ArchHub repo as proof
  (12 491 nodes / 25 440 edges, 0 LLM tokens).
- `app/memory/` (new package) — graph store + extractors + query.
- `app/library.py` — back-compat shim around `memory.query`.
- `app/tool_engine.py` — `memory_query` tool.
- `app/web_ui/studio-lm.jsx · LibraryPanel` — community-grouped sections.
- `tests/test_memory_graph.py` — ~30 tests across extractors + query.

## Not in scope

- Graphify itself as a runtime dependency (we adopt its data model + algos,
  not the package; their package is dev-tool-shaped).
- Cross-firm graphs (multi-tenant federation — defer to v1.6+).
- LLM-semantic INFERRED edges by default (opt-in only — keeps cost story).
