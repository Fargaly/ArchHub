---
id: AgDR-0004
timestamp: 2026-05-20T00:00:00Z
agent: claude-code (Sonnet)
session: node-redesign-loop
trigger: /loop slice C
status: executed
category: architecture
projects: [archhub]
---

# Groups MVP — Data Model + Auto-BBox Render + Drag-With-Members + Style Palette

> In the context of slice C of the node-system redesign (AgDR-0001
> §7.7), implementing Dynamo-2.13-style groups, I decided to ship
> a focused MVP this slice — `LM_GRAPH.groups: Group[]` with auto-
> computed bbox, six predefined Group Styles, `Ctrl+G` opening a
> small dialog over the selection, drag-the-header moving the group
> AND its members — and to split off **Collapse-to-giant-node**
> (slice C2) and **Nesting** (slice C3) as their own AgDRs because
> each is its own non-trivial design problem (external-socket
> auto-promotion for collapse, recursive geometry for nesting).
> This delivers a real, visible, persistent group primitive now
> without ballooning the slice. Accepting: no collapse yet, no
> nesting yet — to be done in C2 / C3.

## Context
- AgDR-0001 §7.7 locked the full Dynamo-2.13 feature set (title +
  description + nesting + collapse + predefined styles).
- That feature set is honestly ~3 slices' worth of work; one slice
  to ship all of it would either be sloppy or take a week.
- Slice C2 (Collapse) depends on external-socket auto-promotion
  which has its own design contract; AgDR forthcoming.
- Slice C3 (Nesting) requires recursive bbox geometry + drag-with-
  parent semantics; AgDR forthcoming.
- Founder mandate: no half-shipped features. The MVP must be a
  complete feature — just narrower scope than the full Dynamo
  2.13 vision.

## Options Considered

| Decision | Picked | Why |
|---|---|---|
| Group geometry | **Auto-computed from member bbox + padding** | Matches Dynamo (resize-to-fit); zero state to keep in sync |
| Group geometry state | Not persisted (recomputed each render) | Members move → bbox recomputes naturally |
| Member reference | `nodeIds: string[]` | Trivial, JSON-safe, matches existing wire-by-id pattern |
| Group ID | `group_<base36-time>` | Matches existing node-id convention |
| Style palette | 6 predefined styles serialised as a name (`input`/`connector`/`ai`/`transform`/`output`/`note`) | Names travel with the graph; the colour table lives in JSX |
| Ctrl+G UX | Small modal over the canvas, title + style picker, Create/Cancel | Quick + reversible |
| Drag UX | Drag the group's header to multi-drag all members; click body to select all members | Standard convention |
| Persistence | `LM_GRAPH.groups` added to the `save_graph` payload | Already round-trips through `session.graph` |
| Z-order | Group rectangle BEHIND nodes (z-index lower) | Header overlay floats above |

## Decision

### Data model
```
LM_GRAPH.groups: [{
  id: 'group_<base36>',
  title: 'Group title',
  description: '',          // optional, used by C2 collapse
  style: 'input'|'connector'|'ai'|'transform'|'output'|'note',
  nodeIds: ['n1', 'n2', …], // member node ids
}]
```

Geometry (bbox) is **computed at render time** from the member
nodes' positions + sizes, with a 16px padding (24px top for the
header).

### Style palette
| Style | Colour token |
|---|---|
| `input` | LM.warn (pink-orange) |
| `connector` | LM.accent (orange) |
| `ai` | `#9b59b6` (purple) |
| `transform` | LM.cyan |
| `output` | LM.ok (green) |
| `note` | LM.inkSoft (grey) |

Used for the group's title-bar background tint and the dashed
border.

### Ctrl+G
Captured in `NodeCanvas`'s existing keydown effect. Requires
`selectedIds.size > 0` (no selection ⇒ no-op + toast). Opens a
small `GroupDialog` modal in the canvas wrapper centred on the
selection. Dialog shows: title text input (autofocus), style
button row (six pills), Create + Cancel. On Create: push a new
`Group` to `LM_GRAPH.groups`, `saveCurrentGraph`, `bumpGraph`,
clear selection, close dialog.

### Render
For each group, render a div positioned at the auto-bbox
(canvas-space) with `zIndex` BELOW the node z-index. Header bar at
the top with the title + style stripe; body is just background
tint. The div is full-width over its bbox so it looks like a
"region around the members" — the founder's Dynamo expectation.

### Drag-with-members
The group's header has `onMouseDown` that starts a multi-drag with
`dragRef.current.ids = group.nodeIds`. The cursor delta applies
to every member node position. Existing multi-drag infra (slice
B2) is reused.

### Click group body
`onClick` on the group body (not the header) selects all member
node ids — convenient for "edit this region" workflow.

### Save
`saveCurrentGraph` payload extended:
```js
merged = { nodes, wires, groups: LM_GRAPH.groups || [] }
```

The bridge `save_graph` slot already stores arbitrary fields via
`session.graph = graph`, so no Python change.

## Consequences

- New `LM_GRAPH.groups` array — backward-compatible (absent ⇒
  `[]`).
- New `GroupDialog` modal component.
- New `GroupRect` render in `NodeCanvas`.
- `saveCurrentGraph` payload gains a `groups` field.
- `NodeCanvas` keydown effect gains `Ctrl+G` branch.
- No engine changes (groups are pure canvas).
- Deferred: collapse (slice C2 / AgDR-0005), nesting (slice C3 /
  AgDR-0006), edit-existing-group dialog (slice C2 likely).
- Multi-drag from slice B2 is exercised here — no new drag code.

## Artifacts
- This AgDR.
- `app/web_ui/studio-lm.jsx` edits.
- CDP verification: place 3 nodes, multi-select them, `Ctrl+G`,
  pick a style, Create — group renders behind them; drag group
  header → all members move.
