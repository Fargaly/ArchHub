# ArchHub Node Grammar — typed-node catalogue

> **Design reference — NOT the roadmap.** `docs/ROADMAP.md` is the single
> source of truth for plans, backlog, and milestones.
>
> Revised 2026-05-21 — replaces the category-named-as-node grammar with
> typed nodes per category. Founder mandate: "categories hold MULTIPLE
> typed nodes; the category name is never the node name." See conversation
> log + the host-node + composer-speckle prototypes for the source intent.

## The principle

> Every placeable node is a **typed**, **modular**, **specific** thing.
> Category names (Input, Output, Watch, Logic, Shape, …) are CONTAINERS
> in the palette — never node names. A node called "Input" with no type,
> no shape, no I/O is undefined and decorative.

What changed from the prior grammar: `input`, `constant`, `output`,
`watch`, `trigger`, `logic`, `filter`, `transform`, `note` were grammar
primitives. They are now CATEGORIES. Each holds typed nodes (Number,
Text, File, Table watcher, Schedule trigger, If/Else, Filter, …).

What stayed: `connector` (16 per-host masters — already typed), `ai`
(ONE master with action picker — per founder's earlier intent), `skill`
(user composition wrapper), `reroute` (wire-routing dot).

## The catalogue

Status legend: ✓ ships in slice H · ☐ ships in later slices · ⚙ ships
when its engine executor exists.

### INPUT — typed value sources

Outputs a typed value. Has a `value` config (the design-time default).
Bound at run-time if upstream wires in.

| Node | Engine `type` | Output port type | Config | Status |
|---|---|---|---|---|
| Number      | data.constant | number  | value, min, max, step | ✓ |
| Text        | data.constant | string  | value, multiline      | ✓ |
| Boolean     | data.constant | boolean | value                 | ✓ |
| File        | data.constant | string  | value, extensions     | ✓ |
| Color       | data.constant | string  | value (hex)           | ✓ |
| Date        | data.constant | string  | value (ISO)           | ☐ |
| Folder      | data.constant | string  | value                 | ☐ |
| Range       | data.constant | object  | min, max, step        | ☐ |
| List        | data.constant | list    | items                 | ☐ |
| JSON        | data.constant | object  | value                 | ☐ |
| Parameter (run-time bound) | input.parameter | any | name, type, description, default | ✓ |

### OUTPUT — typed sinks

Captures upstream value and writes / displays / sends.

| Node | Engine `type` | Input port | Config | Status |
|---|---|---|---|---|
| Result      | output.parameter | any    | name (result key) | ✓ |
| File Save   | output.file      | any    | path, format, overwrite | ⚙ |
| Console     | output.console   | any    | label             | ⚙ |
| Email Send  | output.email     | string | to, subject, via  | ⚙ via Outlook connector |
| Display     | output.display   | any    | none              | ⚙ |

### WATCH — passthrough viewers

Renders the incoming value AND passes it through unchanged. Sits
mid-graph for inspection. Body renderer = slice E (already shipped).

| Node | Engine `type` | Render `as` | Status |
|---|---|---|---|
| Table     | watch.preview | table | ✓ |
| List      | watch.preview | list  | ✓ |
| JSON      | watch.preview | json  | ✓ |
| Image     | watch.preview | image | ✓ |
| 3D Viewer | watch.preview | view  | ⚙ M2 Speckle viewer |
| Chart     | watch.preview | chart | ☐ |
| Log       | watch.preview | log   | ☐ |

### TRIGGER — typed event sources

Start the graph. Each typed trigger emits a specific event shape.

| Node | Engine `type` | Emits | Status |
|---|---|---|---|
| Manual Run    | trigger.emit | on=manual    | ✓ |
| Schedule      | trigger.emit | on=schedule  | ⚙ |
| Webhook       | trigger.emit | on=webhook   | ⚙ |
| File Watch    | trigger.emit | on=file      | ⚙ |
| Host Event    | trigger.emit | on=host      | ⚙ M2 Speckle subscription |
| Email Received| trigger.emit | on=email     | ⚙ via Outlook |

### LOGIC — control flow

| Node | Engine `type` | Inputs → Outputs | Status |
|---|---|---|---|
| If/Else     | control.if      | value, condition → true_out, false_out | ✓ |
| For Each    | control.foreach | items, body → results                  | ✓ |
| Switch      | control.switch  | value, key → case_n                    | ✓ |
| Merge       | control.merge   | a, b → value (first non-null)          | ✓ |
| Sequence    | control.sequence| a, b → out (a then b)                  | ☐ |
| Wait        | control.wait    | value, ms → value                      | ☐ |
| Retry       | control.retry   | value, body → result                   | ☐ |

### SHAPE — typed data transforms

Pure transforms — no side effects.

| Node | Engine `type` | Op | Status |
|---|---|---|---|
| Filter   | filter.apply    | predicate keep / drop  | ✓ |
| Map      | transform.apply | per-item expression    | ✓ |
| Sort     | transform.apply | by field, asc/desc     | ✓ |
| Group By | transform.apply | by field               | ✓ |
| Unique   | transform.apply | dedupe                 | ✓ |
| Pluck    | transform.apply | extract field          | ✓ |
| Count    | transform.apply | length                 | ✓ |
| Slice    | transform.apply | first N / last N       | ✓ |
| Flatten  | transform.apply | nested → flat          | ✓ |
| Concat   | transform.apply | join lists             | ✓ |

### MATH — arithmetic + comparison

| Node | Engine `type` | Op | Status |
|---|---|---|---|
| Add        | math.binary | a + b              | ⚙ |
| Subtract   | math.binary | a − b              | ⚙ |
| Multiply   | math.binary | a × b              | ⚙ |
| Divide     | math.binary | a ÷ b              | ⚙ |
| Modulo     | math.binary | a % b              | ⚙ |
| Round      | math.unary  | round(a)           | ⚙ |
| Equal      | math.compare| a == b → boolean   | ⚙ |
| Compare    | math.compare| a > b / < b / ≥ b  | ⚙ |
| And / Or / Not | math.logic | boolean ops    | ⚙ |

### TEXT — string ops

| Node | Engine `type` | Op | Status |
|---|---|---|---|
| Concat   | text.op | join two strings | ⚙ |
| Split    | text.op | delimiter        | ⚙ |
| Replace  | text.op | pattern → new    | ⚙ |
| Format   | text.op | template + args  | ⚙ |
| Match    | text.op | regex → boolean  | ⚙ |

### AI — one master, action picker

ONE node. Action param picks the concrete LLM op. Inputs + outputs
shape to the action.

| Action | Engine `type` | Inputs → Outputs |
|---|---|---|
| chat       | conversation.chat        | prompt, history → response, history |
| complete   | llm.complete             | prompt → text                       |
| classify   | llm.classify             | value → label, confidence           |
| with_tools | llm.complete_with_tools  | prompt → text, tool_calls           |
| vision     | llm.vision               | image, prompt → text                | (⚙)
| embed      | llm.embed                | text → vector                       | (⚙)
| plan       | ai.plan                  | goal → plan, history                | (⚙ M4)

### CONNECTOR — 16 host masters

ONE node per host. Host locked at palette time (slice A pattern).
The op picker is the primary surface on the node body — typed I/O
shapes to the selected op. Parameter widgets render inline; deep
config goes to the inspector.

revit · autocad · max · blender · rhino · excel · word · powerpoint ·
outlook · teams · notion · dropbox · photoshop · illustrator ·
indesign · speckle

### SKILL — user composition

Each saved skill becomes a typed node. Inputs + outputs promoted from
the wrapped subgraph's open ports. Modes: shared (reference) /
private (inline expand) — slice G locked.

### NOTE — annotation

| Node | Type | Status |
|---|---|---|
| Sticky Note | note    | ✓ |
| Reroute     | reroute | ✓ |

### GLUE — cross-host fallback

For the rare gap Speckle can't carry. Typed by intent, not by host.

| Node | Engine `type` | Status |
|---|---|---|
| Glue Script | glue.script | ⚙ (M3+) |

### ADAPTER — typed bridges

For unit conversion + port-type coercion when typed wiring needs
explicit reshaping.

| Node | Engine `type` | Status |
|---|---|---|
| Units      | adapter.units      | ⚙ |
| Reshape    | adapter.reshape    | ⚙ |

## Engine wiring rules

1. **One executor per engine `type`** — already enforced by the registry.
2. **Multiple grammar entries can share one engine type** — Number /
   Text / Boolean / File all map to `data.constant` with a different
   `value_type` pre-set. The grammar entry is the USER-FACING node;
   the engine type is the IMPLEMENTATION.
3. **`NEEDS_EXECUTOR`** marks grammar entries whose engine type isn't
   built yet. The palette can SHOW the node but placing it surfaces
   an honest "not yet implemented" error — never silent-fail.

## The stem-field layer — R1 → R5 (Phase-0 closure)

> The grammar above is the CATALOGUE (what nodes exist). The stem-field
> layer is the MACHINERY underneath: how a node's typed `config_schema`
> becomes editable knobs, how typed ports get promoted into a reusable
> cell, and how a composed/minted cell persists into the SAME registry
> the runner cooks from. These five rungs (R1–R5) were the open gaps in
> the "every node is a typed, modular stem cell" picture; Phase-0 closes
> them. Each rung names its real artifact so the claim is verifiable, not
> aspirational (ANTI-LIE).

The single source for a node's knobs is its `config_schema` on the
`NodeSpec` (`app/workflows/registry.py`). One schema, authored once next
to the executor, drives **both** the inspector UI **and** the engine —
there is no second hand-maintained widget list to drift. R1–R5 are the
five hops that carry that one schema from the executor to a running,
re-composable cell:

### R1 — ONE renderer: `config_schema` → typed knobs

A node's `config_schema` (JSON-Schema-ish: `{type, default, description,
enum, min, max, …}` per property) is rendered by a SINGLE generic
inspector renderer — never a per-node hand-built form. In the JSX
inspector, `_configSchemaFor(node)` pulls the placed node's schema from
the one grammar payload, and the renderer emits one editable `FullParam`
field per schema property (`app/web_ui/studio-lm.jsx`, the "stem-FIELD
gap" block, ~L15417). Each field seeds from `node.config` → `node.params`
→ `schema.default` and writes back through the SAME `onParamChange` path
as the legacy flat params (which mirrors into `node.params`; the engine
folds `params → config` via `_params_to_config`, contract unchanged). A
node with no `config_schema` falls back to its flat `node.params` —
additive and reversible. The schema is intentionally RICHER than the old
flat params (e.g. `assert`'s flat params were `mode/expr`; its schema
adds `safe_mode/op/expected/message`), so the renderer exposes the full
typed surface, not a hand-picked subset.

### R2 — the bridge EMITS `config_schema`

The renderer can only render what the backend hands it. `get_node_grammar`
(`app/bridge.py`, ~L1976) returns `grammar_payload()`
(`app/workflows/node_grammar.py`), and that payload now carries each
entry's `config_schema`, read straight off the registry `NodeSpec` by
`_config_schema_for(engine_type)` (`node_grammar.py`, ~L1149/L1197) — the
JSX keeps NO second copy of the grammar. The schema crosses the
QWebChannel bridge with the catalogue, so the inspector (R1) and the
engine see one identical schema. (`get_node_library` still emits the
lighter ports-only view for the palette list; the schema-bearing source
of truth for knobs is the grammar payload.)

### R3 — promote param ↔ input

A typed knob is not locked to the inspector: a node's `config_schema`
property can be PROMOTED to a wired input port (and a wired input can
fall back to a knob when unconnected) so the same typed value is editable
inline OR fed by a wire — the Blender "promote to Group Input" /
Substance "expose parameter" pattern. Promotion is what lets an inner
node's knob become a facade input when the node is wrapped into a cell
(R4/R5). Because the knob and the port share one typed `config_schema`
entry, promoting does not mint a second definition — it re-routes the one
that already exists.

### R4 — promote output / field-split

The output side of the same move. When a selection is composed into a
cell, each wire that crossed the selection boundary becomes ONE typed
facade port: inbound wires → facade **inputs**, outbound wires → facade
**outputs**, with multiple wires into the same inner port sharing one
facade port (`compose_subgraph` in `app/workflows/subgraph.py`,
`facade_inputs`/`facade_outputs`, ~L191–L224). "Field-split" is the
record-shaped case of an output promotion: a structured output row (e.g.
`fs.list`'s `{path, name, ext, size, is_dir, mtime}` rows, or any
record) can be promoted field-by-field into distinct typed downstream
ports rather than carrying one opaque blob — the same typed-port
discipline applied to the fields of a record. The promoted ports are
persisted as the composite's `inner_inputs` / `inner_outputs` and the
internal wires are rewritten onto the facade.

### R5 — persist through compose → mint, on the registry the runner reads

The closure rung. A cell that is **composed** (`subgraph.register` →
`subgraph.user`, dynamic ports off `inner_inputs`/`inner_outputs`) or
**minted** from the "Create node…" modal (`bridge.create_node_type` →
`custom_nodes.register_spec`, `app/workflows/custom_nodes.py` ~L433) is
registered into **`app/workflows/registry.py`'s `_REGISTRY`** — the exact
same dict the runner cooks from. The runner resolves every executor via
`registry.get(node_type)` (`app/workflows/runner.py` ~L545), which reads
`_REGISTRY`. So a freshly composed or minted cell COOKS immediately, no
relaunch, with no copy step.

**The dual-registry trap — CLOSED in this Phase-0.** The trap is the
class of bug where compose/mint persist a new cell into ONE registry
while the runner reads a DIFFERENT one — the minted node then shows in
the palette but `no executor for <type>` at run time (a silent
dead-node, the ANTI-LIE failure: "looks shipped, doesn't cook"). Phase-0
forecloses it structurally by having a SINGLE node-type registry:
`registry.register` / `custom_nodes.register_spec` (which does
`_REGISTRY.pop(...)` + `register(...)` to allow edits) / `subgraph.register`
ALL write `_REGISTRY`, and `runner.get` / `bridge.get_node_library` /
`bridge.get_node_grammar` ALL read that same `_REGISTRY`. There is no
second node-type registry for a cell to get stranded in; write-path and
read-path are the one dict, so compose→mint→cook is one continuous chain.

> NOTE — scope: "dual-registry" here means the NODE-TYPE registry
> (executors the runner cooks). It is a different concern from the
> separate, tracked LLM-tool-surface drift between `tool_engine.TOOLS`
> and `connectors.base` ops (`docs/ROADMAP.md`, "Tool-registry
> unification") — that is the AI's tool list, not the node executor
> registry, and is out of scope for this stem-field closure.

## `fs` is a CELL family, not a connector host (ONE-SYSTEM)

`fs.list` / `fs.read` / `fs.write` / `fs.move` (`app/workflows/nodes/fs.py`)
are **PURE STEM CELLS** — in-process executors registered into `_REGISTRY`
exactly like `data.join` (`relate.py`) and `aggregate.py`, with typed
ports + a `config_schema`. They are deliberately **NOT** a stateful
connector host, and **no `app/connectors/fs_connector.py` exists** (nor
should one).

The reason is ONE-SYSTEM + LIBRARY-FIRST. Every `app/connectors/` entry
is a stateful adapter to an *external running application* — it probes
reachability, holds a session, and surfaces "host unreachable" because
Revit / Excel / Rhino / etc. are out-of-process. The local filesystem is
none of that: `os.scandir` / `open` / `shutil.move` are in-process,
synchronous, always reachable, and need no probe / auth / session.
Wrapping a local read or write in a connector would mint ceremony with
zero payload — a parallel "host" system for something that is just a
function call. So the `fs` cells stay modeled 1:1 on the other pure data
cells: typed I/O, `config_schema`, total-tolerant (a bad path is a typed
error dict with every output present + empty, never a raise),
deterministic (sorted output → byte-stable cook). The read pair
(`fs.list` / `fs.read`) performs ZERO mutation; the write pair
(`fs.write` / `fs.move`) is side-effecting by design — it writes/moves
bytes the way any IO function does — and guards accidental clobber with
an explicit `overwrite` flag. Runtime safety of AI-driven writes is the
already-shipped plan-mode approval gate on the composer/agent path
(USER-AGENCY), not a connector wrapper.

## Library taxonomy (palette grouping)

Per AgDR-0014, the palette groups by category. Section order:

INPUT · CONNECTOR · AI · LOGIC · OUTPUT · SKILL · SHAPE · MATH · TEXT
· WATCH · TRIGGER · NOTE · GLUE · ADAPTER

## What this fixes vs. the prior grammar

| Prior | Now |
|---|---|
| "Input" node — no type, no shape | INPUT category holds Number, Text, Boolean, File, Color, … |
| "Output" node — no sink type | OUTPUT category holds File Save, Email Send, Display, Result |
| "Watch" node — no render mode | WATCH category holds Table, List, JSON, Image, 3D, Chart |
| "Trigger" node — no event type | TRIGGER category holds Manual Run, Schedule, Webhook, File Watch |
| "Logic" node with `kind` param | LOGIC category holds If/Else, For Each, Switch, Merge as distinct nodes |
| "Filter" / "Transform" as primitive | SHAPE category holds Filter, Map, Sort, Group, Unique, Pluck, … |
| Math + Text folded into "Transform" | MATH + TEXT as own categories with typed nodes |
| AI as primitive | AI as ONE master with action picker (per founder intent) |
| Connector as primitive | CONNECTOR as 16 per-host masters (slice A unchanged) |

## Build slices

Tracked in `docs/ROADMAP.md`. The first ship under this grammar is
**Slice H** — typed INPUT category (5 nodes: Number, Text, Boolean,
File, Color) replacing the bare `input` + `constant` primitives.
Subsequent slices roll out the remaining categories.
