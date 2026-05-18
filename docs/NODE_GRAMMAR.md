# ArchHub Node Grammar — design memo

> **Design reference — NOT the roadmap.** `docs/ROADMAP.md` is the single
> source of truth for plans, backlog, and milestones. This memo is the
> rationale + detailed design behind the `#P0 NODE-SYSTEM REDESIGN`
> roadmap item. Build slices are tracked as `- [ ]` lines in the
> roadmap, never here.
>
> Seeded 2026-05-18 from founder intent + research into ComfyUI, n8n,
> Grasshopper, and Dynamo. Supersedes `docs/NODE_LIBRARY_v2.md`.

## 1. Why — the current node system is broken

Investigation 2026-05-18 (against the real code):

- `LM_LIBRARY` (`studio-lm.jsx:425`) ships **80 node types in 10 categories**.
- Canvas nodes carry `cat` (`"filter"`, `"read"`, …). `WorkflowRunner`
  dispatches on `node.type` (`runner.py:425`). `run_workflow` passes the
  raw canvas graph to the runner with **zero translation**.
- Result: **0 of 80 library nodes run.** Every one resolves to
  `type → undefined → "no executor for ''"`. Drag, wire, Run → error.
- The only nodes that work are the ~118 connector ops — and those are
  spawned **one node per op**, scattered, on a separate code path
  (`run_connector_op`), not in `LM_LIBRARY` at all.
- The engine is **healthy**: ~39 real dotted-type executors
  (`input.parameter`, `llm.*`, `control.if/merge/foreach`,
  `conversation.chat`, `aec.*`, `subgraph.*`, …), a working lazy/dirty/
  cached cook, typed wires.

Two failures, one class: (a) the canvas and the engine are **two
disconnected node systems** with two port-type vocabularies and two
param shapes; (b) `LM_LIBRARY` / `NODE_LIBRARY_v2.md` is an
**aspirational catalogue** — 80 nodes enumerated before the executors
existed. Decorative by construction.

## 2. Principle — a grammar, not a catalogue

A **grammar**: a small set of primitive node *kinds*, each heavily
parameterized, that **compose**. Users build everything from primitives
+ skills. We never again enumerate 80 nodes the engine must chase.

Rules:
- **Every node that can be placed can run.** No decorative nodes. If a
  kind has no executor, it does not ship.
- **One node model.** The thing the canvas renders *is* the thing the
  engine executes — same object, same `type`, same ports, same params.
- **The library is ~12 kinds, not 80.** Specialization is by parameter,
  not by a new node type.
- **Skills are how the library grows.** A user composes primitives,
  saves the group as a Skill, and the Skill is itself a placeable node.
  The library expands by use, not by us pre-enumerating it.

## 3. The one node model

A node is one object, canvas-side and engine-side identical:

```
{
  id:     "n_ab12",            # unique in graph
  type:   "connector",         # THE registry key — dispatch + render
  pos:    {x, y},
  params: { host:"revit", op:"list_walls", level:"L2" },
  ports:  { in:[...], out:[...] }   # DERIVED from type+params, see below
}
```

- `type` is the single identity. The canvas `cat` (display grouping,
  colour) is **derived** from `type`, never stored as a parallel id.
- `params` is one flat dict — the same dict the engine reads as
  `config`. No `{k,v}`-vs-`config` split.
- **Ports are derived, not hand-authored.** A node kind declares a
  `ports(params) → {in,out}` function. A `connector` node with
  `op=list_walls` exposes the ports `list_walls` declares; change `op`
  and the ports change. This is the ComfyUI/n8n "node morphs to its
  config" pattern and it is what lets ~12 kinds cover everything.
- **One port-type vocabulary** — the engine `PortType` enum
  (`graph.py`). The canvas's invented vocab (`t:'walls'`, `t:'dims'`)
  is deleted. Typed connections, enforced at drag time.

## 4. The primitives

~12 kinds. Each row is real — it maps to an executor that **exists** or
is explicitly marked to build. Nothing aspirational ships.

| Kind | Role | Key params | Ports | Engine executor | Status |
|---|---|---|---|---|---|
| `input` | a graph input / source | `kind`: value·file·pick | out: 1 (typed) | `input.parameter` | exists |
| `constant` | a literal typed value | `value`, `type` | out: 1 | `data.constant` | exists |
| `connector` | **master host node** — one per host | `host`, `op`, + op's params | derived from `op` | connector `run_op` | exists |
| `ai` | **master AI node** — one per graph need | `action`: chat·complete·classify·extract·vision·embed·tools | derived from `action` | `llm.*` / `conversation.chat` | exists |
| `logic` | branch / flow | `kind`: if·merge·foreach·switch | derived from `kind` | `control.if/merge/foreach` | exists; `switch` to build |
| `filter` | keep / drop items by predicate | `predicate` | in 1, out 1 | **build** (1 executor) | to build |
| `transform` | map / reshape data | `op` | in 1, out 1 | **build** (1 executor) | to build |
| `watch` | watcher / preview | `as`: list·table·view·model·image·json | in 1, out 1 (passthru) | **build** (light) | to build |
| `trigger` | fire the graph | `on`: manual·schedule·file·host-event | out: event | `workflows/` triggers | exists; wire as node |
| `output` | a graph output / sink | `kind`: result·write·preview | in 1 | `output.parameter` | exists |
| `skill` | a saved Skill graph as one node | `skill_id` | promoted ports | `subgraph.*` | exists |
| `note` | comment / sticky — never executes | `text` | none | n/a (UX only) | trivial |

**`connector` collapses 18 host nodes + 118 op-nodes into one node.**
You drop a Connector, pick `host` (Revit/AutoCAD/Outlook/…), pick `op`
from that host's operations; the right panel renders that op's
parameters from its existing `ConnectorOp.inputs` ParamSpecs. The
connector contract already carries everything needed (`kind`,
`destructive`, typed `inputs`, `output_type`). No new model — just one
node surfacing it.

**`ai` collapses the 8 `ai` nodes into one.** Pick `action`; the right
panel shows that action's params (model, system prompt, schema for
`classify`/`extract`, tool set for `tools`).

Everything else a user wants is **composed** from these + saved as a
Skill.

## 5. Skill-as-node (the recursion)

A Skill is a saved subgraph that is itself a placeable node — the
ComfyUI subgraph / Dynamo `.dyf` pattern, adapted.

- **Save:** select nodes → *Save as Skill*. Unconnected inputs become
  the Skill's input ports; unconnected outputs become its output ports
  (auto-promoted; the user can rename/retype them).
- **Place:** a Skill node (`type:"skill"`, `skill_id`) shows those
  promoted ports. Double-click → open the subgraph to view/edit.
- **Reference semantics** (Dynamo `.dyf`, *not* Grasshopper clusters):
  a Skill node is a *reference* to the skill, not a splice-copy. Edit
  the Skill once → every instance updates. (Today's `save_as_skill`
  splices a copy — the redesign makes it a reference via the engine's
  `subgraph.*` executor.)
- This is how the library grows without us enumerating it.

## 6. Type system

- One vocabulary: the engine `PortType` enum. Delete the canvas vocab.
- Typed sockets, **colour-coded** (ComfyUI). A connection is rejected
  at drag time if the types don't match — errors never reach Run.
- A `*`/`any` wildcard for genuinely generic ports.
- After a run, a wire shows a **type-coloured preview chip** of the
  value that flowed (Dynamo preview-bubble idea — cheap, high signal).

## 7. UI / UX — ComfyUI/n8n/Grasshopper-grade

- **Right-side panel = the node's parameters.** The panel already
  exists (`NodeRail` / `ConnectorOpRail` / `ConversationRail`).
  `ConnectorOpRail` is already the deepest, best UI — tabbed, typed
  `ParamField`s, a Run button, live results. **Generalise that one
  pattern to every node kind.** One inspector, type-aware.
- **Inline on the node:** only the 1–2 defining params (e.g. the
  `connector`'s `host`+`op`, the `ai`'s `action`). Everything else
  lives in the panel — keeps the canvas clean (n8n), keeps the common
  case fast (ComfyUI).
- **Add a node:** double-click the canvas → fuzzy search (Grasshopper).
  Drag a wire into empty space → search filtered to compatible types
  (ComfyUI).
- **Run feedback on the node:** idle / running (spinner) / done (green)
  / error (red + message) — drawn from the executor's real status, not
  the fake `result`/`progress` strings the demo graph fakes today.
- **Watchers** render inline: `watch as=list` → a list; `as=model` →
  a 3D preview; `as=image` → the image. Dynamo's Watch/Watch3D.
- Smooth pan/zoom, snapping, reroute dots, a mini-map.

## 8. What dies

- The 80-entry `LM_LIBRARY` + `LM_NODE_TEMPLATES` (`studio-lm.jsx`).
- The canvas-invented port-type vocab.
- One-node-per-connector-op spawning.
- `docs/NODE_LIBRARY_v2.md` — superseded by this memo.
- The dead `_LM_GRAPH_DEMO_DEAD` fake-result demo graph.

## 9. Build plan (→ roadmap slices)

Ordered. Each slice ends with placeable nodes that **actually run** —
no slice ships decoration.

1. **One node model** — canvas nodes carry registry `type`; one
   port-type vocab; `params`≡`config`; `run_workflow` cooks a real
   graph end-to-end. (Folds in the old canvas-Run `#P0`.)
2. **`connector` master node** — collapse 18 host + 118 op nodes into
   one host node; `op` param; dynamic right-panel params.
3. **`ai` master node** — one node, `action` param.
4. **`input` / `constant` / `output`** — wire to the existing engine
   executors; promotion + the typed inspector.
5. **`logic`** — if/merge/foreach surfaced as one parameterised node;
   build `switch`.
6. **`watch` + `trigger`** — build the `watch` executor + inline
   renderers; wire `trigger` as a node.
7. **`filter` + `transform`** — build the two executors.
8. **Skill-as-node** — subgraph reference semantics, promoted ports,
   double-click-to-edit.
9. **UI/UX pass** — typed-socket colours + drag enforcement, add-node
   search, run-state feedback, mini-map.
10. **Delete** the old `LM_LIBRARY` / `LM_NODE_TEMPLATES` /
    `NODE_LIBRARY_v2.md` / dead demo graph.

A slice is "done" only when its nodes can be dragged, wired, and Run
with a real result against the running app.
