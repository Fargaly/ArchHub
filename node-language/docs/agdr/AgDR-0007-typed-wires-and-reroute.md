---
id: AgDR-0007
timestamp: 2026-05-20T00:00:00Z
agent: claude-code (Sonnet)
session: node-redesign-loop
trigger: /loop slice D
status: executed
category: architecture
projects: [archhub]
---

# Typed Wires — Colour Palette, Fancy-Wire Shape, Reroute Primitive

> In the context of slice D of the node-system redesign (AgDR-0001
> §7.3), implementing typed wires + reroute, I decided to keep the
> existing drag-time validation path (already enforced via
> `precheckWire` + `can_wire` bridge + the `hover.ok` gate in the
> wire `onUp`), expand the JSX `WIRE` colour map to cover every
> `PortType` engine enum value with the AgDR-0001 palette, encode
> "data shape" on the wire stroke from the **source node's
> `cooked.value`** at render time (scalar = thin, list = thick, tree
> = thick dashed), and add a first-party `reroute` grammar primitive
> backed by a new `data.passthrough` engine executor — to ship the
> remaining wire UX from §7.3 without rewriting the wire-commit
> pipeline. Skipping AgDR-0005 / -0006 IDs for now (reserved for
> slice C2 / C3 collapse + nesting AgDRs).

## Context
- Existing `precheckWire` (`studio-lm.jsx`) already calls the
  bridge's `can_wire(out_t, in_t, out_exec, in_exec)` and rejects
  incompatible types at drag time. The wire `onUp` only commits
  when `hover.ok === true`. Drag-time validation = already enforced.
- Existing `WIRE` colour map covers only ~14 app-specific types
  (`walls`, `doors`, etc.) — leaves engine `PortType` enum values
  (`STRING`, `NUMBER`, `BOOLEAN`, `LIST`, `GEOMETRY`, …) mapped to
  the fallback `LM.inkSoft` grey.
- Existing wire render at `studio-lm.jsx:4327` draws each wire as
  a curved path at a fixed `strokeWidth`. No data-shape encoding.
- Existing grammar has no `reroute` primitive — long wires must
  zig-zag across the canvas.

## Options Considered

| Decision | Picked | Why |
|---|---|---|
| Reroute primitive backing executor | **New `data.passthrough` executor (`inputs:[value], outputs:[value]`, identity)** | Tiny + explicit. Reusing `transform.apply` op=identity would conflate visual-routing with data-transform; the runner already pays the price of one extra node either way |
| Wire colour key | **Lowercased `PortType` enum name** | Matches what the canvas already stores in `socket.t` (line 599 in addNodeFromLibrary) |
| Wire shape source | **Source node's `cooked.value` at render time** | Honest — reflects actual data flowing, not just a static port type. Matches Grasshopper's fancy-wire intent (Scalar/List/Tree from data) |
| Reroute node visual | **24 × 24 round dot in `cat.col`** | ComfyUI / GH visual; fits in dense graphs without dominating |
| Reroute keyboard add | Defer (slice F's prefix-grammar handles `~` etc; reroute via palette) | Slice F is the right home for add-node prefix grammar |

## Decision

### `data.passthrough` executor
A new engine node type at `app/workflows/nodes/io_data.py`:

```python
def _passthrough_executor(config, inputs, ctx):
    return {"value": inputs.get("value")}
```

Registered as:
- `type="data.passthrough"`
- `category="data"`
- `inputs=[Port(name="value", type=PortType.ANY)]`
- `outputs=[Port(name="value", type=PortType.ANY)]`
- `display_name="Reroute"`

### `reroute` grammar primitive
A new `Primitive` in `app/workflows/node_grammar.py`:

```python
Primitive(
    "reroute", "Reroute", "note", "",
    {"": "data.passthrough"}, READY,
    "data.passthrough — wire-organisation dot; identity passthru",
    blurb="A wire-organising dot",
)
```

`cat="note"` borrows the grey style — reroute is visually a
non-data-shaping node. Grammar count: 12 → 13. Still ≤ 20.

### JSX wire palette (`WIRE` map)
Lowercased `PortType` enum keys added. Existing app-specific keys
kept for back-compat with legacy graphs:

| Type | Colour |
|---|---|
| `any` | `LM.inkSoft` (grey; rendered dashed in §Fancy-wire) |
| `string`, `text` | `LM.inkSoft` |
| `number` | `#e3b950` (yellow) |
| `boolean` | `LM.ok` (green) |
| `list` | `#6a9bcc` (blue — brand secondary) |
| `object` | `LM.inkSoft` |
| `geometry`, `walls`, `doors`, `sheets` | `LM.accent` (orange) |
| `element`, `selection`, `view`, `revit-element` | `#9b59b6` (purple) |
| `prompt`, `message`, `completion`, `conversation`, `intent`, `prediction`, `tool_result` | `LM.purple` (existing) |
| `file`, `path`, `image`, `ifc`, `csv` | `LM.cyan` |
| `host`, `document`, `model`, `project` | `LM.warn` |
| `exec`, `event` | `LM.warn` (exec is a special pin; kept) |

### Fancy-wire shape encoding
At render time, for each wire, read the source node's
`cooked.value` (if present). Compute shape:

- `undefined`/`null`/scalar (string/number/bool) → **thin**
  (`strokeWidth = 1.8`)
- `Array<scalar>` → **thick** (`strokeWidth = 3.6`)
- `Array<Array<…>>` or `{branches:…}` → **thick dashed**
  (`strokeWidth = 3.6`, `strokeDasharray = "8 5"`)

If the source has not cooked yet, fall back to **thin** (the
visual matches a "no data flowed yet" expectation).

Wires of type `any` always render dashed (per AgDR-0001).

### Reroute node visual
In `NodeRenderer`, when `n.kind === 'reroute'`, render a 24 × 24
round dot in `cat.col` instead of the full card. Sockets render
on the left/right of the dot. Drag the dot to reposition. No
title bar, no body.

## Consequences

- 1 new engine type (`data.passthrough`), 1 new grammar primitive
  (`reroute`).
- Grammar test asserts ≤ 20 primitives — 13 ≤ 20 ✓.
- Existing `precheckWire` path is unchanged — drag-time validation
  works as before.
- Wire render gains a per-wire `strokeWidth` + `strokeDasharray`
  computed from source `cooked.value`. Fallback is the existing
  fixed width.
- `WIRE` map gains ~25 keys; existing keys kept for back-compat.
- Reroute node skips most of the standard NodeRenderer chrome.
- Future: wire-typed colour can be enhanced post-run to reflect
  actual runtime value type, not declared port type.

## Artifacts
- This AgDR.
- `app/workflows/nodes/io_data.py` — `data.passthrough` executor.
- `app/workflows/node_grammar.py` — `reroute` primitive.
- `app/web_ui/studio-lm.jsx` — WIRE map expansion + wire shape
  encoding + Reroute visual.
- Tests: `tests/test_canvas_adapter.py` + `tests/test_node_grammar.py`
  (passthrough executor + primitive coverage).
