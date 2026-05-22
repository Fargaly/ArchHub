---
id: AgDR-0039
timestamp: 2026-05-22
status: approved
founder-signoff: 2026-05-22 — reviewed via docs/prototypes/modular-logic-nodes.html; recommended trio adopted
category: architecture
supersedes: none
builds-on: [AgDR-0038, AgDR-0001, AgDR-0020]
---

# AgDR-0039 — Modular logic nodes: a node's logic IS a graph

> **Approved 2026-05-22.** Founder reviewed the visual prototype
> (`docs/prototypes/modular-logic-nodes.html`) — the design + the three
> forks. Recommended trio adopted. Build follows.

## Context

AgDR-0038 made *workflow* composition modular — the Composer mints + wires
typed Capability Nodes as data. But it left a non-modular hole **inside**
the node: `impl.kind = "python"` is a raw code blob.

Founder, 2026-05-22: *"node isn't just data… also logic… logic is code…
it should still be built from modular elements so it's easy to manipulate
and scale."* Correct. An AI emitting a python body per node is bespoke
per-node logic again — just relocated. A blob can't be rewired, diffed,
recomposed, or reused fragment-by-fragment.

The unification: **spec, logic, and wires are one substrate — a typed
graph.** Data is the graph. Logic is the graph. Relations are the wires.
Recursively. Every serious node system reached this (Houdini HDA, Blender
node groups, Unreal Blueprints, LabVIEW subVIs, n8n sub-workflows,
ComfyUI group nodes) — none ship a code-blob node as the primary unit.

## Options considered

| # | Option | Verdict |
|---|--------|---------|
| 1 | Keep `impl.python` as the way to express real logic | ✗ the non-modular hole this AgDR exists to close |
| 2 | A node's logic is itself a typed sub-graph (`impl.kind=graph`) | ✓ **chosen** — one substrate, recursive, the prior-art answer |
| 3 | A DSL between blob and graph | ✗ a third language to learn; graph already IS the language |

## Decision

**`impl.kind = "graph"`** — a Capability Node whose behaviour is a typed
sub-graph built from modular elements: the grammar primitives, connector
ops, and other Capability Nodes. The four `impl` kinds then mean exactly
one thing each:

- **`graph`** — composite. The default for any real logic.
- **`connector`** — irreducible leaf: one host op.
- **`ai`** — irreducible leaf: one LLM call.
- **`python`** — sealed escape hatch (see Fork 2).

### Fork 1 — logic vocabulary: **Extended**

The ~12 grammar primitives plus four aggregate operators real logic keeps
needing: **`reduce`, `accumulate`, `sort`, `group_by`**. ~16 total —
still a grammar, capped, not a catalogue.

### Fork 2 — python: **sealed leaf**

Keep `python`, but: sandboxed (AgDR-0038 Delta 4 contract), **leaf-only**
(never composite), and `node_create` steers the Composer to `graph`
first. The hatch exists for genuinely irreducible computation; it is the
rare exception, not the habit.

### Fork 3 — composite I/O: **auto-derived**

A `graph` node's typed inputs/outputs ARE the open ports of its inner
graph. Wire the inside; the outer contract appears. One source of truth,
nothing to keep in sync (the Blender node-group model). Optional
rename/reorder of the derived ports is a later polish.

## Consequences

- **Manipulate** — rewire one inner node, never rewrite a blob.
- **Scale** — every logic-fragment is itself a library node, reused.
- **Inspect** — typed + diffable, zero opacity.
- **One mental model** — the AI (and the user) composes logic the same
  way it composes a workflow. Wiring. That is the whole skill.
- Builds on shipped work: `subgraph.py` (graph→node), group-collapse,
  typed `PortType` wires already exist — the substrate is half-built.

## Build slices

1. `impl.kind=graph` executor — runs the inner graph via the
   `subgraph.py` machinery; back-compat for the other three kinds.
2. Extended vocabulary — `reduce` / `accumulate` / `sort` / `group_by`
   primitives in `node_grammar.py`.
3. Auto-derived composite I/O — derive a `graph` node's `Port`s from its
   inner graph's open ends.
4. `node_create` prefers `graph`; the python path is gated + discouraged.

## Artifacts

- This AgDR + `docs/prototypes/modular-logic-nodes.html` (the visual
  design the founder reviewed).
- `app/workflows/custom_nodes.py` — `impl.kind=graph` dispatch.
- `app/workflows/node_grammar.py` — the 4 aggregate primitives.
- `app/workflows/subgraph.py` — composite executor + I/O derivation.
- `app/tool_engine.py` — `node_create` graph-first steering.
- `tests/test_capability_nodes.py` + `tests/test_node_tools.py`.
