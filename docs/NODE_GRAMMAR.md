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
