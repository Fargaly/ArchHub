# ADR-003: Graph-First Architecture — sessions become DAGs, pages dissolve into nodes

**Status:** Proposed
**Date:** 2026-05-13
**Deciders:** Fargaly (founder) · Claude (implementation)
**Supersedes:** none. Extends ADR-001 (cloud hosting) and ADR-002 (memory architecture).

## Context

The Studio shell that shipped through v1.3.3 organises ArchHub around **pages**: Home / Chat / Skills / Memory / Workflows / Marketplace / Settings. A user wanting to chat about a Revit model switches to the Chat page; wanting to edit a workflow switches to the Workflows page; wanting to consult a doc switches somewhere else. The metaphor is *tabs in a browser*. The user is the navigator.

Founder direction (2026-05-13, verbatim): "*strabing everything into one graph or canvas with everything put into settings and treating hosts and conversations as nodes with logic, inputs, outputs, and connecting them together... a revit host node can define a version, a session, a document... in the same session maybe we can pull in more than one chat node and more than one document... allowing between documents workflows and data transfers, automations*".

This is not a UI polish. It is a **product-architecture pivot**. The product becomes:

> A canvas. Everything on the canvas is a node — a host, a conversation, a document, a skill, a tool. Nodes have typed inputs, typed outputs, and parameters. Wires connect outputs to inputs. The user composes by dropping nodes and connecting them. Re-running cascades down the graph automatically when a param changes upstream.

That sentence — and only that — is the v1.4 product. Everything else (pages, tabs, separate "chat mode", separate "workflow mode") collapses into properties of nodes on the canvas.

State of the art for this kind of system has been studied for decades:

- **Grasshopper** (Rhino, 2008–present) — every value is a **data tree**; components decide how to match inputs (1:1, list, branched). 1,500+ components, mature ecosystem. AEC industry-standard.
- **Dynamo** (Revit, 2014–present) — same shape, Revit-tuned. "Custom nodes" = subgraphs.
- **ComfyUI V3** (2024–2026) — declarative schema for nodes (`IO.Schema`), typed colour-coded sockets, stateless execution, async, process isolation, versioned APIs. 1,000+ community node packs in 2026.
- **Houdini** (1996–present) — cooking is a **data dependency graph**; param change dirties downstream; subnetworks encapsulate; parameter expressions reference other params by path.
- **Unreal Blueprints** — separates **execution pins** (white, arrow-shaped, "when") from **data pins** (typed, colour-coded, "what"). Wires are one or the other, never both.
- **TouchDesigner** — operator *families* (CHOP/SOP/TOP/DAT) with different rules per family but cross-family wiring.
- **n8n / Make.com / Zapier** — workflow automation. Triggers + actions + branches + error handling.

None of these alone fits ArchHub. ComfyUI's stateless model doesn't fit long-lived hosts. Grasshopper's data-tree-only model doesn't fit conversational state. Blueprint's exec/data split is gold but Unreal's editor is not what an architect wants to live in.

We synthesise.

## Decision

Adopt a **graph-first product architecture** with the following core model.

### Node model

Every node has:

```
Node {
  id          : string                 # graph-unique
  type        : registered type id     # "conversation.chat", "host.revit", etc.
  category    : palette grouping       # "host", "conversation", "document", "ai", ...
  label       : string (user-editable)
  position    : (x, y)                 # canvas coords, floats
  state       : idle | running | done | error | dirty
  params      : dict                   # type-specific config (sliders/values)
  body        : dict                   # type-specific state (chat history, doc ref)
  inputs      : list[Port]
  outputs     : list[Port]
  metadata    : {created_at, updated_at, last_run_at, tags[]}
}
```

`params` are user-tunable knobs (model, temperature, file path, version). `body` is the node's stateful contents that aren't knobs (the actual chat turns, the actual file). Inputs and outputs are typed ports.

### Port model

Borrowed from Unreal's exec/data split:

```
Port {
  name        : string
  direction   : in | out
  type        : PortType                # see type system below
  exec        : bool                    # true = execution pin; false = data pin
  optional    : bool
  multiple    : bool                    # accepts multiple incoming wires
  default     : any                     # used when input is unwired
  description : string                  # tooltip
}
```

Exec pins are how a Conversation node fires a Host action. Data pins are how a Document's contents flow into a Conversation. **Both flow on the same canvas, drawn distinctly**: data wires are coloured by type, exec wires are white with an arrowhead.

### Type system

Closed enum. Wires only connect ports whose types match or are coercible. Lookup table:

| Family | Types |
|---|---|
| **Primitives** | `STRING`, `NUMBER`, `BOOLEAN`, `OBJECT`, `LIST` (Grasshopper data tree), `ANY` |
| **AEC entities** | `ELEMENT`, `SELECTION`, `WALL`, `DOOR`, `WINDOW`, `SLAB`, `COLUMN`, `BEAM`, `SHEET`, `VIEW`, `SCHEDULE`, `ROOM`, `LEVEL`, `GRID` |
| **Bridge** | `HOST`, `DOCUMENT`, `MODEL`, `PROJECT` |
| **AI** | `PROMPT`, `MESSAGE`, `CONVERSATION`, `TOOL_RESULT`, `INTENT`, `COMPLETION` |
| **Geometry** | `POINT`, `LINE`, `CURVE`, `SURFACE`, `BREP`, `MESH`, `TRANSFORM` |
| **Files** | `FILE`, `PATH`, `IMAGE`, `PDF`, `DWG`, `IFC`, `CSV`, `JSON` |
| **Time/Trigger** | `CRON`, `TRIGGER`, `EVENT` |
| **Control** | `EXEC` (white pin) |

A `WALL` output can wire into a `SELECTION` input (one-of coercion). A `SELECTION` input can accept multiple `WALL` outputs (set union). An `ELEMENT` accepts anything in the AEC family. Coercion rules live in `app/workflows/typesystem.py` (new) — explicit table, not duck typing.

### Wire model

```
Wire {
  id          : string
  from        : (node_id, output_port_name)
  to          : (node_id, input_port_name)
  state       : idle | flowing | cached | stale
  cached_value: any   # last propagated value (for warm rerun)
}
```

### Graph (session) model

```
Graph {
  id              : string
  name            : string
  description     : string
  version         : int                # schema version
  nodes           : list[Node]
  wires           : list[Wire]
  viewport        : {x, y, zoom}
  tags            : list[string]
  permissions     : { visibility, edit, execute }   # ADR-002 access pattern
  created_at, updated_at, last_run_at
}
```

**A session IS a graph.** The current `Session.messages` field maps to a single `Conversation` node's body. Migration is "wrap each existing session in a single-node graph" — straightforward, dual-write-able, reversible.

### Execution model

Three coexisting modes:

1. **Lazy + dirty (Houdini)**. Default. Each node has a `dirty` flag. Changing a param marks the node dirty + propagates dirty to all downstream nodes via wires. The canvas shows dirty nodes with a subtle pulse. User clicks "run dirty" → engine cooks just the dirty subgraph in topo order.
2. **Auto-run-on-change**. Per-node opt-in flag `params.auto_run = true`. Dirty triggers immediate re-cook. Useful for cheap nodes (slider → preview).
3. **Trigger-driven (Unreal)**. Trigger nodes (cron, file-changed, host-event) fire down exec wires. Cron node has an output exec pin; an Action node has an input exec pin. Connect them = the action runs on cron.

The data and execution graphs are stored together but **rendered separately on the canvas** — data wires curved + coloured, exec wires straight + white-arrowed.

### Subgraphs (Skills = subgraphs)

Per Houdini's subnetworks and Dynamo's custom nodes:

- Any selection of N nodes can be **collapsed** into a single node of type `subgraph.user`. The collapsed node exposes the outer-touching inputs/outputs as its own ports.
- A subgraph node opens to reveal its inner canvas.
- "Save as Skill" = `subgraph.user → marketplace_pack` export. The Skill marketplace becomes a marketplace **of subgraph JSONs** (which is what they already are in v1.3.x — we just rename + canvas-ize the surface).

### Permissions + memory binding

Per ADR-002:
- Graph visibility: `private` (default) / `shared_company` / `shared_public`.
- Per-node visibility can override graph default (sensitive Document node stays private even if its graph is public).
- Each node gets attached `memory_facts` via `memory_facts.node_id` column (new, additive). Retrieval scope can be node-bound.
- Memory ops fire as a side-effect of node execution. A Conversation node's `apply_ops` hook turns approved turns into facts.

### Canvas affordances (UX layer)

Synthesised from the user's references (Notion, Claude Code, LM Studio, ComfyUI, Grasshopper) per chat2.md:

| Affordance | Source | Behaviour |
|---|---|---|
| `/` slash menu in composer | Notion | Inserts a node at cursor position; type filters the menu |
| Drag from sidebar library | ComfyUI / Grasshopper | Drop materialises a node at drop location |
| Double-click library item | ComfyUI | Inserts at canvas origin |
| Scroll wheel = zoom (cursor-anchored) | ComfyUI | No modifier; no Ctrl |
| Drag empty canvas = pan | All | Click-drag background |
| Right-click canvas = context menu | All | Add / Paste / Fit / Reset / Snap-to-grid / Auto-layout |
| Drag wire from output → input | All | Cubic Bezier; type-checked |
| Click node = focus + show params in right rail | All | Right rail is *only* for the focused node |
| Double-click node title = rename inline | Notion | Editable label |
| Cmd-G = group selection into a frame | ComfyUI groups / Houdini network boxes | Visual only, no execution semantics |
| Cmd-Shift-G = collapse to subgraph | Houdini / Dynamo | Real composition |
| `Tab` in composer = next param | Notion | Keyboard-first |
| Bottom-left chip | Comfy | "scroll → zoom · drag → pan · right-click → menu" |

### What dies

| Today | Tomorrow |
|---|---|
| `Home` page | Removed. Empty-graph onboarding instead |
| `Chat` page (full ChatWindow as page) | Conversation NODE — one type, one renderer |
| `Workflows` page | Removed. Canvas IS the workspace |
| `Marketplace` page | Modal/drawer opened from "+ Add node" → marketplace tab |
| `Skills` page | Same — modal/drawer with installed + browse |
| `Memory` page | Removed. Memory facts attach to nodes; gear → Memory tab still exists |
| `Telemetry` page | Removed. Status rule keeps the at-a-glance numbers; deeper telemetry = gear → Telemetry |
| `Settings` page | Becomes a modal opened from the gear icon |
| `Pricing` page | Modal from cog (already there) |
| NAV_ITEMS in Studio shell | Removed. Replaced by tabs (open graphs) + library sidebar |
| Per-page inspector dichotomy | Removed. One right rail, always shows the focused node's params |

### What survives unchanged

- ADR-001 (Fly cloud) — no change
- ADR-002 (memory architecture) — additive: `memory_facts.node_id` column. The 5 tiers and APIs unchanged
- Per-company quota actor (v1.3.3) — unchanged
- `app/workflows/graph.py` — Node/Port/Edge primitives stay; we add fields not break them
- AEC nodes registered in v1.3.3 (9 of them) — stay
- Tool engine — stays. Tool nodes auto-register from `tool_engine.TOOLS`
- LLM router — stays. Conversation nodes call through it
- Dev source sync (Codex pass) — stays. Critical for testing the pivot locally
- ChatWindow class — **stays as a renderer** for the Conversation node body. We do not throw away 6 months of polish; we re-host it inside the graph

## Options Considered

### Option A: Graph-first as described above (chosen)

| Dimension | Assessment |
|---|---|
| Vision alignment | **Highest** — matches founder's stated intent verbatim |
| Implementation cost | **High** — 14-18 sustained turns, multiple schema migrations |
| User learning curve | Medium — slash menu hides complexity; power-user can wire |
| Reversibility | Easy — graph JSON is back-portable; feature-flagged rollout |
| Differentiator | Strong — no AEC competitor has graph-first + AI-first |

**Pros**: matches the long-stated vision (VISION.md). Forces unification of memory + skills + sessions into one shape. Builds on existing workflows engine. Aligns with industry-standard tools architects already know (Grasshopper / Dynamo / ComfyUI).
**Cons**: large surface area. Every page touched. Risk of feature regression during pivot.

### Option B: Polish the Studio shell + add a "Graph" tab as 8th nav slot

| Dimension | Assessment |
|---|---|
| Vision alignment | Low — perpetuates page-as-primary model |
| Implementation cost | Low |
| User learning curve | Low |
| Reversibility | Trivial |
| Differentiator | Weak |

**Pros**: ships in 2-3 turns.
**Cons**: founder explicitly rejected this in chat2.md ("instead of having multiple shitty tabs open with a mess of wiring... we focus on what's realy important"). Postpones the pivot but does not avoid it. Tech debt compounds.

### Option C: Build a parallel "ArchHub v2" alongside v1.3.x

| Dimension | Assessment |
|---|---|
| Vision alignment | High |
| Implementation cost | Highest — two codebases |
| User learning curve | Forks |
| Reversibility | Hardest — community migration |
| Differentiator | Strong |

**Pros**: zero risk to v1.3.x stability.
**Cons**: doubles maintenance forever; user runs two apps. Common antipattern. Don't.

### Option D: Adopt a vendor framework (LangGraph + agno + LiteGraph.js)

| Dimension | Assessment |
|---|---|
| Vision alignment | Medium |
| Implementation cost | Lower upfront, vendor risk later |
| User learning curve | Same |
| Reversibility | Hard if persistence is in vendor schema |
| Differentiator | Weak |

**Pros**: skips writing the engine.
**Cons**: AEC type system + host adapters are 100% ours; the vendor adds glue cost without removing the hard parts. Lock-in on a UI library is not a fight we want.

## Trade-off Analysis

Two real axes:

| | Speed to first usable demo | Final-shape fidelity |
|---|---|---|
| **Option A** (chosen) | medium — phased | high |
| Option B | fast | low |
| Option C | slow | high |
| Option D | medium | medium |

Option A wins because we can phase it so that each phase ships *something working* and the founder can interact with progress every 1-2 turns, while still arriving at the actual desired shape.

## Phased Implementation Plan

Each phase is independent, commits, pushes, and leaves ArchHub launchable.

### Phase 0 — Vision lock (this commit)
- [x] Write ADR-003 (this file).
- [x] Get founder agreement on phased path.

### Phase 1 — Core node types (THIS TURN, in addition to Phase 0)
- [ ] Extend `PortType` enum with `HOST`, `DOCUMENT`, `CONVERSATION`, `ELEMENT`, `SELECTION`, `EXEC`.
- [ ] Extend `Port` dataclass with `exec`, `multiple` fields.
- [ ] New module `app/workflows/nodes/core.py` registers:
   - `host.revit`, `host.autocad`, `host.blender`, `host.rhino`, `host.max`, `host.speckle`, `host.outlook` (7 variants)
   - `conversation.chat` (carries chat turns as body; calls LLM router on execute)
   - `doc.revit`, `doc.dwg`, `doc.ifc`, `doc.blender`, `doc.3dm`, `doc.max`, `doc.csv`, `doc.pdf` (8 variants)
- [ ] Executors return well-typed stubs in v1.4 stage 1 (full wire-up arrives Phase 4); each obeys the existing executor signature `(config, inputs, ctx) -> dict`.
- [ ] Tests: registration, port shape, executor signature, type-coercion table.

### Phase 2 — Session = Graph migration (next 2-3 turns)
- [ ] Add `Graph` table (cloud_backend) — id, name, version, nodes JSON, wires JSON, owner, project, visibility.
- [ ] Add `Session.graph_id` foreign key. Dual-write: `Session.messages` continues to populate alongside `graph.Conversation.body`.
- [ ] Add `memory_facts.node_id` column (additive — per ADR-002 extension note).
- [ ] Migration: each existing session wraps as a single-`conversation.chat`-node graph. Reversible by reading `Session.messages` again.

### Phase 3 — Feature-flagged Graph page (next 2-3 turns)
- [ ] Add `graph` page to NAV_ITEMS, feature-flagged off behind `settings.show_graph_canvas` (off by default).
- [ ] When on, the Graph page renders the new canvas using the existing `WorkflowCanvas` scene with the new node types.
- [ ] Old Chat page still works. The feature flag lets the founder try the graph without committing.

### Phase 4 — Real executors (next 2-3 turns)
- [ ] `host.*` executors call into `app/connectors/` adapters (revit_runner, autocad_runner, etc.).
- [ ] `conversation.chat` executor calls `llm_router.complete()` with the conversation body + inputs as context.
- [ ] `doc.*` executors call into the host adapter for read access; emit `contents`, `selection`, `warnings` outputs.

### Phase 5 — Tabs above + slash menu (next 2 turns)
- [ ] Tabs at the top of the workspace show open graphs (closing a tab auto-saves).
- [ ] Composer at bottom-centre with `/` slash menu inserts nodes.
- [ ] Library sidebar (left) with 9 categories from the design bundle: Host / Read / Filter / Transform / Annotate / Compose / Logic / AI / Output. Drag-or-double-click to add.

### Phase 6 — Settings = modal (1 turn)
- [ ] Move Settings, Pricing, Telemetry, Marketplace, Skills, Memory pages into a single `SettingsModal` opened from the gear icon. 10 tabs per studio-lm.jsx: Memory / Profile / Permissions / Hosts / Providers / Models / Theme / Shortcuts / Storage / About.

### Phase 7 — Remove old pages (2 turns)
- [ ] Home / Chat / Workflows / Marketplace / Skills / Telemetry pages deleted from NAV_ITEMS. Bare-mode keeps the legacy ChatWindow for fallback when StudioShell construction fails.
- [ ] `_set_page` becomes `_open_graph(graph_id)`.

### Phase 8 — Cleanup + migration polish (2 turns)
- [ ] Session migration tool for in-place upgrade.
- [ ] Documentation pass: README, QUICKSTART, in-app onboarding flow.
- [ ] v1.4.0 release tag.

## Consequences

What becomes easier:
- One canvas to explain — drops the cognitive overhead of "which page am I on".
- Cross-document workflows are first-class (founder's explicit ask).
- Skills naturally become composable (subgraphs) instead of opaque saved chats.
- Memory facts get a natural binding (per-node retrieval scope).
- Multi-conversation in one session becomes a placement operation, not a feature.
- Power users (architects who already know Grasshopper) feel at home immediately.

What becomes harder:
- Onboarding the user who only wants to chat — solved by the slash-menu + empty-graph default that boots up a single Conversation node so chat works as if pages were never gone.
- Test surface grows — every node type needs unit tests + each cross-type wire needs integration tests.
- Schema versioning gets harder — graph JSON must be back-portable across versions. Mitigated by `Graph.version` + migration scripts shipped per release.

What we'll need to revisit:
- **Mobile companion** (currently a placeholder) needs a graph viewer + read-only mode.
- **Apprentice training** (ADR-001 Stack A pivot) needs to learn from graph executions, not just chat turns.
- **Marketplace** distribution model — graph snippets become a richer unit of trade than today's flat-JSON skills.

## Reversal Plan

The pivot is **feature-flagged** end-to-end:
- Phases 1-2 are additive (new tables, new node types). Zero user-visible change.
- Phase 3 hides the graph behind a Settings toggle. Founder can A/B internally before users see it.
- Phase 4 wires the real executors but still behind the flag.
- Phase 5-6 makes the graph the primary, but page-based NAV still works for the flag-off path.
- Phase 7 deletes old pages; the flag-off path goes through bare ChatWindow (which is unchanged).

If at Phase 5 we decide the pivot is wrong, the flag stays off, the new tables go unused, and we ship v1.4.0 as a memory-architecture + Fly-deploy release (still meaningful). The 8 already-built phases are not wasted — they sit beside ChatWindow as a viable v1.5 future.

## References

- [Grasshopper data trees — Rhino developer docs](https://developer.rhino3d.com/guides/grasshopper/the-why-and-how-of-data-trees/)
- [Unreal Blueprint nodes — execution vs data pins](https://docs.unrealengine.com/4.27/en-US/ProgrammingAndScripting/Blueprints/UserGuide/Nodes)
- [Houdini dependency-graph cooking](https://www.sidefx.com/docs/houdini/network/dependencies.html)
- [Houdini subnetworks + parameter expressions](https://www.sidefx.com/docs/houdini/network/expressions.html)
- [ComfyUI V3 schema — declarative typed sockets](https://docs.comfy.org/development/core-concepts/nodes)
- [ComfyUI V3 custom nodes 2026 — Apatero](https://apatero.com/blog/comfyui-v3-custom-node-schema-development-2026)
- [Grasshopper 3D — Wikipedia](https://en.wikipedia.org/wiki/Grasshopper_3D)
