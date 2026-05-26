---
id: AgDR-0012
timestamp: 2026-05-20T00:00:00Z
agent: claude-code (Sonnet)
session: node-redesign-loop · founder-driven
trigger: founder commit after 3-prototype review
status: partially_superseded
category: architecture
projects: [archhub]
supersedes:
  - AgDR-0001 §3 ("one node model" port-type vocab → replaced by Speckle Base)
  - AgDR-0001 §6 (typed-socket coercion → replaced by Speckle speckle_type)
  - AgDR-0001 §7.2 (add-node UX as primary entry → demoted to fallback; composer becomes primary)
  - AgDR-0007 §"Wire colour key" (PortType lowercased keys → replaced by Speckle-type colour mapping)
superseded_sections:
  - "ReactFlow is the canvas substrate" → superseded by AgDR-0048 (custom canvas is the substrate of record; ReactFlow never installed — renumber chain 0045→0046→0048)
  - "LIBRARY-FIRST mandate" enforcement details → details refined by AgDR-0013 / AgDR-0014 (library-first gate + library design system)
  - "Speckle wire transport" details → refined by AgDR-0016 (speckle-share-adapter-router-gate)
---

> **DOC BANNER — partial supersede 2026-05-25:**
> The "ReactFlow is the canvas substrate" line below is no longer
> the architecture lock — see `AgDR-0048-supersede-reactflow-lock.md`
> (renumber chain 0045→0046→0048; founder's AgDR-0046 is the brain
> settings rebuild workshop, not this one).
> Custom canvas (`NodeView` + `WireLayer`) is the substrate of record.
> Other sections of this AgDR remain in force.

# Architecture lock — Direction X: Composer-as-IDE + Speckle Wires + AI Plan, governed by Library-First and User-Always-In-Control

> In the context of the founder's commit (2026-05-20) after reviewing three
> grounded prototype files (host-node-designs.html, cross-host-paths.html,
> composer-speckle-architecture.html), I decided to lock ArchHub's
> architecture as **Direction X**: the Composer (chat) is the primary IDE,
> the canvas is the materialised execution + inspection surface, every wire
> is a Speckle `Operations.send/receive` segment (default `SQLiteTransport`,
> no server, no Docker, no account, fully offline), and `ai.plan` survives
> as a real canvas node so chat turns persist as auditable, replayable
> artefacts — governed by two non-negotiable mandates: **LIBRARY FIRST**
> (the agent searches the library before composing new nodes; never
> duplicates what exists) and **USER ALWAYS IN CONTROL** (every AI action
> is reversible, overridable, and browsable; the library and canvas are
> never auto-pilot-only surfaces). Accepting: ~12–16 weeks of focused work
> to ship M1–M6; ArchHub `PortType` enum collapses into Speckle
> `speckle_type`; the existing custom-canvas slices A–G survive (engine +
> bodies + rails) but the wire layer migrates from custom serialization to
> Speckle.

## Context

- AgDR-0001 (the original NODE-SYSTEM REDESIGN spec, 2026-05-18) defined a
  ~12-primitive grammar, custom typed sockets, and a custom wire engine.
- AgDR-0002 / 0003 / 0004 / 0007 / 0008 / 0009 / 0010 / 0011 shipped seven
  slices A–G plus deferred C2/C3/G2 — all built on the custom canvas
  foundation.
- Founder review (2026-05-20) surfaced THREE deeper concerns the slice
  work had not addressed:
  - **Cross-host data flow.** Can the AI take CAD lines from a layer and
    stream to a Revit view using these ops? Today's primitives cannot —
    the adapter gap is real.
  - **Composer-as-IDE.** The user should drive everything through chat.
    Canvas-clicking is a power-user fallback, not the primary loop.
  - **Don't build from scratch.** Use Speckle (Apache-2.0, 16+ AEC host
    connectors already exist) as the wire transport. Use ReactFlow for
    the canvas substrate (already committed in an earlier session).
- Three grounded research passes + three prototype HTML files were
  produced over the design session. The founder reviewed all three and
  committed to Direction X with explicit refinements:
  1. "User stays in control."
  2. "Don't get rid of the nodes library."
  3. "Don't compromise on modularity."
  4. "AI when composing new nodes should search the library first."
  5. "Whatever new it adds must be modular and generally usable, with
     parameters and logic."

This AgDR formalises the commit and adds the two governing mandates.

## Options Considered

(See the three prototype HTML files for the full per-direction visualisation;
the AgDR records the decision, not the full trade-space.)

| Option | Picked | Why |
|---|---|---|
| **Direction X — Composer-as-IDE + Speckle wires + ai.plan node** (with library-first + user-control mandates) | YES | Founder commit. Solves cross-host adapter problem at the protocol layer. Composer is the primary user surface. Library + modularity preserved as agent rules. |
| Direction Y — Speckle wires + canvas-primary + composer as Cmd-K | no | Founder's framing wanted chat gravity, not chat availability |
| Direction Z — opt-in Speckle (two wire types) | no | "Two mental models, neither is the product" — founder rejects "wrap without committing" |
| Stay custom (no Speckle) | no | Reinvents 15+ years of AEC interop work; doesn't unblock cross-host |
| Stay custom canvas (no ReactFlow) | no | Already committed to ReactFlow migration earlier in session |

## Decision

### Architecture, in one paragraph

**ArchHub is a chat-first AEC node-graph IDE.** The Composer is a docked left-rail
chat panel; the Canvas is a ReactFlow surface materialised by streaming
Anthropic tool-use deltas; the Inspector is a right rail showing the focused
node's params, the focused wire's Speckle Version (with a `@speckle/viewer`
preview), and the library browser. Every wire is a Speckle Base graph,
content-addressed and stored in a per-project `SQLiteTransport` (`.speckle/`
folder local to the project) — no Speckle Server is required to operate,
ever. Cross-host data flow uses Speckle's existing connector ecosystem
(Apache-2.0, AutoCAD / Revit / Rhino / ArchiCAD / Tekla / Blender /
SketchUp / Power BI / IFC drop). The user can drive everything through chat,
through the library, or through direct canvas manipulation — the three are
co-equal entry points to the same underlying graph state. AI never
auto-pilots: writes to host applications require explicit approval; the
agent always searches the library before proposing a new node; every node
the agent mints is registered as a typed, parameterised, library-discoverable
artefact.

### Mandate 1 — LIBRARY FIRST (non-negotiable)

The library is the inventory of every placeable + composable artefact in
ArchHub:
- **Primitive grammar** (the ~13 kinds: `input`, `constant`, `connector`,
  `ai`, `logic`, `output`, `skill`, `filter`, `transform`, `watch`,
  `trigger`, `note`, `reroute`).
- **Per-host master nodes** (16 specialisations of `connector`).
- **Speckle Send/Receive nodes per host** (added during M2/M5 — one
  `send_to_speckle` + one `receive_from_speckle` per supported host).
- **Adapter ops** (cross-host helpers that survived the Speckle migration
  — e.g. semantic mappings, lossy aggregations Speckle can't carry).
- **User-saved Skills** (Shared + Private modes per AgDR-0010).
- **AI-minted custom nodes** (Python ops written by `node_smith` + the
  composer's `library.create_node_type` tool — see §"Modularity").
- **Glue.script nodes** (the rare cross-host gap Speckle can't carry).

Rules the agent obeys when composing:

1. **`library.search(intent, input_schema, output_schema)` is called BEFORE
   `library.create_node_type(...)`.** Hard rule, enforced in the system
   prompt + tool-use schema (Anthropic `strict: true`).
2. **If a match is found ≥ 0.75 cosine similarity on intent + structural
   match on I/O schemas, the agent USES the existing node** (with a brief
   one-line justification to the user: "I'll use `excel.read_range` —
   already in your library"). It does not propose creating a duplicate.
3. **If no match is found**, the agent proposes a new node via
   `library.create_node_type(spec)` and the spec MUST satisfy the
   Modularity Rules below.
4. **Newly minted nodes are registered to the library on creation**, not
   on save. The library grows by use, not by curation. The user can prune.

### Mandate 2 — USER ALWAYS IN CONTROL (non-negotiable)

- **Library is always browsable.** Cmd-K opens it. Add-node search (slice F's
  WirePromotePalette) stays. The library tab in the side panel stays.
  Composer never replaces these — it complements them.
- **Canvas is always editable.** Right-click a node → edit config, disconnect,
  delete. Drag-rewire stays. Direct canvas manipulation is a peer entry
  point to chat-driven manipulation.
- **Every AI write to a host is approval-gated by default.** The composer
  has three modes: **Plan** (default — propose, never execute writes
  without approval), **Auto** (auto-approve reads; writes still gated),
  **YOLO** (Cline-style; auto-approve everything; explicit opt-in,
  reversible via undo).
- **Every action is reversible.** Speckle Versions are immutable and
  content-addressed; undo = receive the previous Version. Composer turns
  are checkpointed; revert restores the canvas to a prior turn.
- **Approval surfaces are typed errors, not freeform retries.** A failed
  adapter raises a typed error pointing the user to the recovery node
  (insert `glue.script`, change config, choose alternate adapter), not a
  chat reprompt.

### Mandate 3 — MODULARITY (non-negotiable)

Every node — primitive, host master, adapter, skill, AI-minted, glue.script —
satisfies:

1. **Typed inputs** declared as Speckle `Base` schemas or `PortType`
   primitives (string / number / boolean / list / object), with named
   ports.
2. **Typed outputs** same.
3. **Parameterised config** declared in a JSON `config_schema` (the
   existing `NodeSpec.config_schema` field). Hard-coded literal values
   inside the body are a code smell — refactor to config.
4. **Documented intent** — `display_name`, `description`, and an
   `examples: [{input, output}]` field. The `examples` are used by
   `library.search` for similarity matching.
5. **Reusable across graphs** — no node references a graph-specific node
   id; all dependencies are passed via wires.
6. **Composable** — every node can be wrapped in a Skill or referenced
   from `ai.plan`. No node is special-cased to be uncomposable.

The agent enforces this when minting. The library validation rejects
non-modular specs (no inputs, no outputs, no config, no description = no
register).

### Composer tool surface

The Anthropic tool-use schemas the Composer agent sees, ordered by
intended call frequency:

```
library.search(intent: string, input_schema?: JsonSchema,
               output_schema?: JsonSchema) -> [{id, name, type, score}]
library.list_node_types(category?: string) -> [NodeSpec]
library.inspect(node_type: string) -> NodeSpec
library.create_node_type(spec: NodeSpec) -> {id, registered}
library.delete_node_type(node_type: string) -> {ok}  # user-confirmed

graph.create_node(type: string, at: [x, y], config?: dict) -> node_id
graph.connect(src: "n_<id>.<port>", dst: "n_<id>.<port>") -> wire_id
graph.set_param(node: string, key: string, value: any) -> {ok}
graph.delete_node(node: string) -> {ok}
graph.delete_wire(wire: string) -> {ok}
graph.run(scope: "node"|"downstream"|"all", from?: string) -> RunResult
graph.list_node_types(host?: string) -> [string]   # current placed nodes
graph.inspect(node: string) -> {config, ports, last_run}

speckle.send(base: Base, transport?: "sqlite"|"memory"|"server",
             model?: string) -> hash
speckle.receive(hash: string, transport?: "sqlite"|"memory"|"server") -> Base
speckle.list_versions(model: string) -> [{hash, created_at, objects}]

node.inspect(id: string) -> {config, last_result}
node.read_props(id: string, path: string) -> any   # dotted-path drill

skill.save_as(name: string, mode: "shared"|"private",
              from_node: string, description: string) -> skill_id
skill.list() -> [{id, name, mode, last_used}]
skill.expand(skill_id: string, at: [x, y]) -> [node_id]
```

The `library.search` tool is called automatically by the system prompt
before any `library.create_node_type` — enforced as Anthropic `strict: true`.

### Wire substrate — Speckle

- **Default transport:** `DiskTransport` at `.speckle/<project>/` (project-
  local, copy/paste-portable, scoped). `SQLiteTransport` per-user fallback.
- **Memory transport** for ephemeral in-session wires (e.g. debugging an
  `ai.plan` proposal before committing).
- **ServerTransport** opt-in for collaboration / cloud sync. Cloud
  Speckle (`app.speckle.systems`) or self-hosted.
- **Wire payload:** Speckle `Base` subtree, content-addressed by `id`.
  Every node fire writes a new Version under a per-wire Model (named
  after the wire's stable id).
- **Units:** every Base carries `units`. Cross-host unit conversion is
  handled by the per-host Speckle connector (`ScalingServiceToSpeckle` +
  inverse). ArchHub never hand-writes unit math.
- **Typed sockets:** drag-time validation uses Speckle `speckle_type` (e.g.
  `Objects.Geometry.Line`, `Objects.Data.DataObject`) instead of ArchHub's
  current `PortType`. The `PortType` enum is deprecated — kept only for
  back-compat on saved graphs that pre-date M1.

### Canvas substrate — ReactFlow

Already committed in an earlier session turn. Migration order:
- **M1.a** (parallel with M1): scaffold ReactFlow component, port one
  primitive node (`constant`) and verify the engine integration.
- **M2.a**: port `connector` master node (16 hosts) onto ReactFlow.
- **M3.a**: port the host node design from `host-node-designs.html`
  Direction A (op grid + Houdini flags) — the most assertive
  "nothing-hidden" form, with the founder's library + modularity
  constraints expressed as visible tabs + searchable params.
- **M4.a–M6.a**: incremental migration of remaining slices A–G onto
  ReactFlow.

Surviving slices A–G:
- A — per-host master connectors → SURVIVES, gets Speckle Send/Receive
  variants alongside.
- B — 4-verb disable + Pin → SURVIVES, unchanged.
- B2 — multi-select + rubber band → SURVIVES via ReactFlow primitives
  (it has marquee built in; less code for us).
- C — Groups MVP → SURVIVES.
- C2/C3 — Group collapse / nesting → DEFERRED, will be cheaper on
  ReactFlow.
- D — typed wires → REPLACED by Speckle `speckle_type` colouring.
- E — watch + note bodies → SURVIVES, unchanged.
- F — add-node search (WirePromotePalette) → SURVIVES alongside
  the Composer; both are entry points to the same library.
- G — skill-as-node hybrid → SURVIVES, expanded with Composer-driven
  `skill.save_as` tool.

### Engine layer

- The existing `WorkflowRunner` keeps running ops on threads, but the
  wire serialization swaps from custom JSON to Speckle `Operations.send`.
- `node_grammar.normalize_canvas_graph` keeps the bypass / freeze / pin
  graph rewriting (slice B). The output of each non-bypassed node passes
  through `Operations.send` to produce a Speckle hash; downstream nodes
  read via `Operations.receive`. Hash equality is the dirty-tracking
  mechanism (auto-incremental: identical input hash → cached output
  hash, no re-execute).
- `subgraph.user` (Skill execution) reads the saved `.archskill` →
  Operations.receive → expands inline.

## Consequences

### What ships

- `specklepy` embedded in the Python side (Apache-2.0, v3.2.6+, Python
  3.10+).
- `@speckle/viewer` (three.js) embedded in the JSX side for the wire
  inspector preview.
- ReactFlow canvas (`@xyflow/react`, MIT) replacing the custom canvas.
- Composer Qt panel (left-docked) with Anthropic tool-use loop.
- Per-project `.speckle/` directory for the local transport.
- New nodes: `autocad.send_to_speckle`, `autocad.receive_from_speckle`,
  `revit.send_to_speckle`, `revit.receive_from_speckle`, etc., one
  Send/Receive pair per supported host (rolling out per host).
- `ai.plan` canvas node carrying the Composer's prompt + tool-call
  history.

### What collapses

- `geometry.cad_to_revit` adapter op (planned in AgDR-0007, never built)
  → replaced by `autocad.send_to_speckle` → Speckle wire →
  `revit.receive_from_speckle`. The conversion is the host connectors'
  job.
- `ArchHub.PortType` enum (~25 values) → replaced by Speckle
  `speckle_type`. Deprecation path: keep parsing the old enum for legacy
  saved graphs; never emit it for new wires.
- `glue.script` as cross-host adapter → demoted to fallback ("Speckle
  can't carry this") and visible in the library under `Glue`.
- The custom add-node search modal (`NodeLibrary`) and `WirePromotePalette`
  → KEPT (founder mandate "don't get rid of the library"). They are
  alternative entry points; Composer is the primary one, but the user
  can always Cmd-K the library.

### What's reinforced

- The **library is the user's living inventory**. Every primitive,
  master node, adapter, Skill, AI-minted node, and glue.script lives
  in it. Search-first is an agent contract; browse-anytime is a user
  right.
- **Modularity** is enforced at registration time. The validator rejects
  non-modular specs.
- **User agency** is engineered, not honour-system. Plan mode, approval
  gates, undo via Speckle Versions, library browse, canvas direct
  manipulation — all are first-class.

### Tests / acceptance

- M1 acceptance: a `constant → output` graph cooks via Speckle wires;
  the cached hash matches across runs; second run returns instantly.
- M2 acceptance: a Revit Send → Receive round-trip preserves geometry
  fidelity (DirectShape fallback documented + surfaced on hover).
- M3 acceptance: the Composer can build the litmus graph
  (CAD A-WALL → Revit Level 1) from natural-language prompt; the agent
  calls `library.search` BEFORE proposing new nodes (logged + asserted
  in the test).
- M4 acceptance: `ai.plan` node persists the chat turn + tool calls;
  re-running it reproduces the same graph deterministically (modulo
  LLM nondeterminism — pin via Anthropic `temperature=0` + cache).
- M5 acceptance: AutoCAD → Revit cross-host wire works; lossy
  conversions (custom properties, textures) surface as a Warning panel
  before commit.
- M6 acceptance: opt-in ServerTransport publishes a wire to
  `app.speckle.systems`; a second ArchHub instance can `receive` from
  the same Model.

### Risks (carried over from research)

- DirectShape fallback erodes Revit roundtrip fidelity (Speckle-
  documented). Mitigate: "Receive Blocks as Families" setting; document
  on hover.
- Speckle schema evolves under us (Stream→Project rename happened
  2024). Pin versions; track upstream in CI.
- Composer slow on 100-node graphs. Use Anthropic parallel tool calls +
  `graph.batch_create_nodes` + prompt caching for project context.
- Local SQLite cache grows shared across Speckle apps. Ship per-project
  `.speckle/` DiskTransport so cache is scoped per project.
- Agent hallucinates node types. Bias system prompt toward
  `library.search` and `library.list_node_types` first. Use Anthropic
  `strict: true` tool use.
- No single-binary Speckle Server if user opts into self-host. Lean on
  `app.speckle.systems` for 95%; ship a self-host doc page.
- ReactFlow migration is ~1.5–2 weeks before any new feature work
  resumes. Founder accepts the freeze.

## Implementation order — 6 milestones

1. **M1 — Speckle as local wire** (1–2 wks). Embed `specklepy`. New
   `SpeckleWire` class wrapping `Operations.send/receive` with
   `DiskTransport` to `.speckle/<project>/`. Replace
   `WorkflowRunner` wire serialization for new graphs. Legacy graphs
   continue on the old serializer until they're re-saved.
   PARALLEL: M1.a ReactFlow scaffold, one node ported.
2. **M2 — Revit Speckle connector** (3–5 wks). Bundle the existing
   Speckle Revit connector or call it via IPC. Two nodes:
   `revit.send_to_speckle(file, selection) -> base_hash` and
   `revit.receive_from_speckle(hash, target_file, ...)`. Includes
   `@speckle/viewer` integration in the inspector.
3. **M3 — Composer v1 + Library tools** (6–8 wks). Qt panel left.
   Anthropic tool-use loop. Tool surface as defined above. Stream
   `input_json_delta` events to ReactFlow canvas; nodes materialise
   tentatively then commit. Plan / Auto / YOLO modes. Per-project
   `ARCHHUB.md` as persistent memory. **`library.search` enforced via
   system prompt + strict tool use.**
4. **M4 — `ai.plan` as a canvas node** (9–10 wks). One node type.
   Inputs: Bases. Config: prompt + model + temperature + tool
   allowlist. Outputs: Bases the agent emitted. Plan-mode preview.
5. **M5 — Cross-host wire AutoCAD → Revit** (11–12 wks). Bundle Speckle
   AutoCAD connector. Wire validation, lossiness preview, DirectShape
   fallback explanation.
6. **M6 — Optional ServerTransport** (13–14 wks). Cloud / self-hosted
   Speckle Server as collaborator. "Publish this wire" creates a remote
   Model. Speckle Automate webhooks for live cross-machine wires.

Plus continuous:
- **Library validation hardening** — reject non-modular specs at
  registration time.
- **Skill dependency-graph warnings** in `SaveSkillDialog` (deferred
  G2).

**First valuable shippable: M1 + M2 (5 wks)** — closes the litmus
scenario end-to-end on a human-driven canvas, with Speckle wires. The
Composer arrives in M3.

## Artifacts

- This AgDR.
- `docs/prototypes/host-node-designs.html` — three node-body directions
  (op grid / stacked / Houdini multi-tab).
- `docs/prototypes/cross-host-paths.html` — three cross-host paths
  (AI Plan / glue.script / explicit adapter).
- `docs/prototypes/composer-speckle-architecture.html` — **the
  committed composite**.
- Supersedes the architectural sections of AgDR-0001, -0007 as noted.
