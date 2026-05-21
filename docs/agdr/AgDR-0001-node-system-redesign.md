---
id: AgDR-0001
timestamp: 2026-05-20T00:00:00Z
agent: claude-code (Sonnet)
session: node-redesign-brainstorm
trigger: founder brainstorm — 2026-05-20 (/brainstorm)
status: executed
category: architecture
projects: [archhub]
---

# Node-System Redesign — One Grammar, 16 Per-Host Connector Master Nodes, Hybrid Skill-as-Node, 4-Verb Disable, Dynamo-Style Groups

> In the context of redesigning ArchHub's node system after the
> original 80-node `LM_LIBRARY` catalogue shipped decorative (0 of 80
> ran), facing the founder's intent of "one master node per host"
> plus a "modular nodes that create more nodes" principle, I decided
> to lock the architecture as a ~12-primitive engine grammar plus 16
> per-host connector master nodes (specialisations of the `connector`
> primitive) plus hybrid skill-as-node semantics plus a 4-verb disable
> model plus Dynamo-2.13-style groups — sourced from grounded research
> into Grasshopper, Dynamo, ComfyUI, and n8n — to deliver an
> AEC-correct, type-safe, composable canvas, accepting the
> implementation cost of three independent disable verbs and the
> richness of full-fat groups.

## Context

- 2026-05-18 investigation against the real code: canvas and engine
  were two disconnected node systems. 0 of 80 `LM_LIBRARY` nodes ran
  — every one resolved to `type → undefined → "no executor for ''"`.
  Only ~118 connector ops worked, via a separate `run_connector_op`
  path. `LM_LIBRARY` was an aspirational catalogue the engine never
  caught up to.
- SLICES 1–3 brought a one-node model (`normalize_canvas_graph`), a
  `connector.run` master executor, an `ai` master executor.
- SLICE 4 shipped the **wrong** connector shape: ONE universal
  connector node with a host dropdown, because
  `docs/NODE_GRAMMAR.md` §4 was internally contradictory
  ("master host node — one per host" vs "collapses into one node,
  pick host"), and Claude resolved the contradiction silently
  instead of surfacing it. Founder rage, justified.
- 2026-05-20 founder reissued the intent: 16 hosts → 16 corresponding
  connector master nodes, each its own params/inputs/outputs. Plus
  "modular nodes that from them we can create more nodes and expand
  on them." Plus design node BEHAVIOURS (multi-select, group, …).
  Plus do **real** research on Grasshopper / Dynamo / ComfyUI / n8n
  before designing.
- Real research executed (foreground agent, ~3000 words, grounded in
  primary docs + community references for each system).
- Three remaining forks resolved by the founder via
  AskUserQuestion, 2026-05-20: 3-verb disable + Pin; hybrid skill
  semantics; full Dynamo 2.13 groups.

## Options Considered

### Master connector architecture

| Option | Pros | Cons |
|--------|------|------|
| One universal `connector` node, host as dropdown param | One palette entry; minimum grammar | No host identity on canvas; doesn't match founder intent; canvas reads "Connector" not "Revit" |
| **16 host master nodes as specialisations of one `connector` primitive** (PICKED) | Grammar stays ~12 kinds; palette shows 16 named host nodes; one engine executor; matches founder intent; demonstrates the "primitives → derived nodes" modular principle | Palette generates 16 entries from one primitive — implementation detail in the palette emitter |
| 16 standalone host primitives in `node_grammar.py` | Most explicit on paper | Grammar grows to ~27; drifts back toward enumerated catalogue; breaks `test_grammar_is_small_a_grammar_not_a_catalogue` (`assert len(PRIMITIVES) <= 20`) |

### Skill-as-node reference semantics

| Option | Pros | Cons |
|--------|------|------|
| True reference (Dynamo `.dyf`): edit definition once, every placed instance updates | Powerful library effect; firm-wide fixes propagate | "Edit one, accidentally break thirty"; rigid for one-off customisation |
| Fork-on-placement (ComfyUI Subgraph Blueprint): each placement independent | Safe against unwanted propagation | Drift between instances; manual push-update pain |
| **Hybrid — pick at save time** (PICKED) | User chooses Shared (reference) or Private (copy) per skill; opt-in for propagation | Two mental models; slight UI overhead in the save dialog |

### Disable model

| Option | Pros | Cons |
|--------|------|------|
| One verb (Disable) | Simplest | Too coarse; AEC ops cost API quota / hit live host docs |
| Two verbs (Disable + Preview-off) | Better; matches GH | Loses bypass-as-pipe; no dev snapshot |
| **Three verbs + Pin** (PICKED): Bypass + Freeze + Preview-off + Pin Data | Best-of-class behaviour from ComfyUI + Dynamo + n8n combined; orthogonal verbs; Pin closes the dev-vs-live-host loop | Higher implementation cost; three visuals, three shortcuts |

### Group model

| Option | Pros | Cons |
|--------|------|------|
| No formal groups, sticky-notes only (n8n) | Simplest | No formal scope; can't collapse a region |
| Coloured region + title (Grasshopper) | Light, familiar | No description, no collapse, no styles |
| **Full Dynamo 2.13** (PICKED) | Title + description + nestable + collapse-to-giant-node + predefined Group Styles serialised with the graph — strongest org-wide visual grammar | Higher implementation cost |

## Decision

Chosen: the architecture spec below.

1. **Engine grammar — ~12 primitive kinds** (unchanged):
   `input`, `constant`, `connector`, `ai`, `logic`, `output`,
   `skill`, `filter`, `transform`, `watch`, `trigger`, `note`.
2. **Palette emits 16 host master nodes** as specialisations of the
   `connector` primitive — each pre-locks `host` (Revit / Excel /
   AutoCAD / Outlook / Notion / …). Engine path: one `connector.run`.
   Placement of "Revit" → a node with `kind:'connector'`, `host:'revit'`,
   `op:''` ready to be picked.
3. **Connector inspector** — n8n `Resource → Operation → typed-params`
   morphing form. Declarative `displayOptions.show/hide` rules drive
   field visibility. Static main I/O sockets. Dynamic param form.
   Host is locked per node (not picked); only the op + its params are
   chosen in the inspector.
4. **Node behaviours — full slate**:
   - **3-verb disable + Pin**: Bypass (`Ctrl+B`, pass-through pipe);
     Freeze (`Ctrl+F`, node + downstream stop, use cached); Preview-off
     (`Ctrl+Shift+P`, run but suppress render); Pin Data (`P`, snapshot
     last successful output, purple badge). Independent state per
     verb; composable.
   - **Multi-select**: rubber band + `Shift/Ctrl+Click` + Select
     Upstream / Select Downstream commands. `Alt+drag` =
     push-neighbours-aside (Grasshopper).
   - **Groups (Dynamo 2.13)**: `Ctrl+G` → dialog (title, description,
     style). Nestable. Collapsible to giant-node form with
     auto-promoted external sockets. Predefined Group Styles serialise
     with the graph: INPUT / CONNECTOR / AI / TRANSFORM / OUTPUT /
     WATCH+NOTE. User-extendable in Settings.
   - **Add-node UX (4 layers)**: (1) double-click empty canvas →
     fuzzy search; (2) prefix grammar in the search bar
     (`~comment` → Note, `"text"` → Constant string,
     `0<1<10` → Slider with range, `=expr` → Expression);
     (3) drag-wire-to-empty-canvas → palette filtered to
     type-compatible nodes (ComfyUI); (4) predictive autocomplete
     ranked by the connected port type (Dynamo). `Tab` opens the
     palette globally (n8n).
   - **Wire + type system**: strict typed sockets, drag-time
     validation (reject mismatched connections before they land),
     type-coloured wires (e.g. `revit-element` purple, `geometry`
     orange, `data-row` blue, `text` grey, `boolean` green, `number`
     yellow, `any` dashed white). Grasshopper fancy-wire shape
     encoding ON TOP of colour: thin = scalar, thick = list, thick
     dashed = tree. First-party Reroute primitive.
   - **Annotation — two primitives**:
     `watch` (data panel — receives a wire and shows the value;
     renderers: list / table / view / model / image / json) and
     `note` (pure markdown, no I/O, free-floating, optional
     anchor-to-node, supports images).
   - **Inspector model**: right-side panel for the focused node, n8n
     morphing form. Inline body editing only for trivial primitives
     (`constant`, `note`). Type hints on hover. Per-port right-click
     menu (Grasshopper): Insert Filter / Insert Transform / Pin
     Output / Disconnect / Flatten / Graft.
5. **Skill-as-node — Hybrid (save-time toggle)**:
   - Save dialog: name + description + category + **Mode: Shared
     (reference) | Private (copy)**.
   - **Shared** — `.archskill` file in a watched folder; every placed
     instance points to the file; edit propagates on next run
     (Dynamo `.dyf` semantics).
   - **Private** — snapshot stamp; each placement independent
     (ComfyUI Subgraph Blueprint semantics).
   - **Disentangle** verb — fork a Shared instance into Private for
     one-off customisation (Grasshopper Disentangle).
   - User can promote Private → Shared later.
6. **Deferred (separate spec)**: Dynamo's "Node to Code" — select a
   transform chain → flatten to a single text expression. Worth its
   own AgDR when scoped.

## Consequences

- `docs/NODE_GRAMMAR.md` §4 connector row + §7 behaviours section
  rewritten to match this AgDR; the contradiction is fixed.
- `docs/ROADMAP.md` SLICE 4 entry updated to flag the wrong-shape
  ship; SLICES A–G appended.
- SLICE 4's `ConnectorRail` reshaped: host LOCKED per node (no host
  picker on placed nodes); palette emits 16 host entries; the
  existing `connector.run` executor unchanged.
- New work needed for: 4-verb disable state + visuals; Dynamo-2.13
  groups; reroute primitive; type-coloured wires + drag-validation;
  Skill-as-node hybrid save flow; per-port right-click menu;
  prefix-grammar add-node search; drag-wire-to-empty palette filter.
- Test surface: `test_node_grammar.py` unchanged (still ~12 kinds);
  add tests for the palette emitter expanding `connector` to 16
  entries and for the wire-type drag-validation contract.
- Process: this is AgDR-0001. Subsequent architecture-shaped
  decisions get their own AgDR before any code (CLAUDE.md mandate
  amended).

## Artifacts

- Research report — foreground research agent, this session,
  ~3000 words, grounded in primary docs (n8n Resource/Op,
  Dynamo Primer, Grasshopper Primer, ComfyUI Subgraph release).
- This AgDR (`docs/agdr/AgDR-0001-node-system-redesign.md`).
- `docs/NODE_GRAMMAR.md` revisions (this commit / next commits).
- `docs/ROADMAP.md` slice appends (this commit / next commits).
- Implementation slices A–G — incoming commits.
