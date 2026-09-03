---
id: AgDR-0003
timestamp: 2026-05-20T00:00:00Z
agent: claude-code (Sonnet)
session: node-redesign-loop
trigger: /loop slice B2
status: executed
category: architecture
projects: [archhub]
---

# Multi-Select, Rubber-Band, Upstream/Downstream Traversal, Alt+Drag Push-Neighbours

> In the context of slice B2 of the node-system redesign (AgDR-0001
> §7.6), implementing multi-select + canvas ergonomics, I decided
> to keep `selectedIds` as a `Set<string>` local to `NodeCanvas`
> alongside `focusId`, trigger rubber-band selection on
> `Shift+empty-canvas-drag` (pan stays the default), multi-drag
> the entire selection when the user drags any selected node,
> push-neighbours-aside when `Alt` is held during a node drag, and
> walk `LM_GRAPH.wires` via BFS for `Ctrl+Shift+U` (Select Upstream)
> / `Ctrl+Shift+D` (Select Downstream) — to deliver
> Grasshopper-grade canvas ergonomics without breaking the existing
> pan-as-default gesture, accepting that selection state lives in
> the canvas component (not lifted to root) because nothing outside
> the canvas needs it yet.

## Context
- AgDR-0001 §7.6 locked: rubber band + Shift/Ctrl-click + Select
  Upstream / Select Downstream + Alt+drag push-neighbours.
- Existing `NodeCanvas` has `focusId` (single node, drives rail),
  `positions` (per-node x/y), `dragRef` (`mode='pan'|'node'`).
- Existing empty-canvas mousedown starts a pan drag — keeping that
  gesture is a non-negotiable for the founder's muscle memory.

## Options Considered

| Decision | Picked | Why |
|---|---|---|
| Selection state location | NodeCanvas-local (`selectedIds: Set<string>`) | Canvas-only feature today; lift later if groups/copy need root access |
| Band trigger | `Shift + empty-canvas-drag` | Preserves pan-default; matches Figma/most node editors |
| Multi-drag semantics | Drag any selected node moves ALL selected (delta-locked) | Standard convention; no surprise |
| Push-neighbours trigger | Hold `Alt` during node drag | Matches Grasshopper |
| Push direction | Displace by overlap amount in the drag delta direction | Simple, predictable, no jitter |
| Upstream/Downstream keys | `Ctrl+Shift+U` / `Ctrl+Shift+D` | Discoverable mnemonics; no conflict with existing bindings |
| Traversal algorithm | BFS on `LM_GRAPH.wires` (`to→from` for upstream, `from→to` for downstream) | One pass, terminates on visited |
| Selected visual | 2px accent outline on each selected node | Already a stroke convention; no layout shift |

## Decision

State:
- `selectedIds: Set<string>` in `NodeCanvas`. Always includes
  `focusId` (the canvas guarantees this on every selection mutation).
- `bandRect: {x0,y0,x1,y1} | null` while a band drag is active.
- `dragRef.current.mode` extended from `'pan'|'node'` to
  `'pan'|'node'|'band'`.

Interaction:
- **Empty-canvas mousedown without shift** → pan (existing).
- **Empty-canvas mousedown with shift** → `mode='band'`,
  `bandRect = {sx,sy → sx,sy}` (canvas-space).
- **Node mousedown with shift OR ctrl/meta** → toggle id in
  `selectedIds` (no drag started).
- **Node mousedown plain, id in selectedIds** → multi-drag
  (`mode='node'`, dragRef tracks all selected positions).
- **Node mousedown plain, id NOT in selectedIds** → reset
  `selectedIds = {id}`, single-drag (existing).
- **Alt held during node drag** → on each mousemove, for every
  non-selected node whose bbox overlaps the dragged node's new bbox,
  push that node by the overlap amount in the drag-delta direction.

Mouse move:
- `mode='pan'`: existing pan logic.
- `mode='band'`: update `bandRect` to current cursor.
- `mode='node'`: apply the cursor delta to EVERY id in
  `dragRef.current.allIds` (one element for single drag, N for
  multi-drag). If `alt`, run the push-neighbours pass.

Mouse up:
- `mode='band'`: compute selection from nodes whose bbox intersects
  the band rect; merge with `selectedIds` if shift was held at
  mousedown, else replace. Clear `bandRect`.
- `mode='node'`: persist final positions (existing path,
  extended to N nodes).

Keyboard (in NodeCanvas's existing keydown effect):
- `Ctrl+Shift+U` → expand `selectedIds` upstream via BFS on
  `LM_GRAPH.wires` (`to[0] in selected → add from[0]`).
- `Ctrl+Shift+D` → expand downstream (`from[0] in selected → add
  to[0]`).
- `Escape` → clear `selectedIds` (in addition to existing wireDrag
  cancel).

Visual:
- Each node whose id ∈ selectedIds renders a 2px accent outline.
- During band drag, the band rect renders as a dashed accent
  rectangle overlay.

## Consequences
- `NodeCanvas` gains two pieces of state.
- Existing drag effect (`onMove` / `onUp`) extended with band +
  multi + alt-push branches.
- Existing keydown effect extends for Ctrl+Shift+U/D + Escape clear.
- Node frame style extended with a selected-outline mode.
- No engine changes.
- Future: groups (slice C) consume `selectedIds` directly to scope
  a Ctrl+G operation.

## Artifacts
- This AgDR.
- `app/web_ui/studio-lm.jsx` `NodeCanvas` edits (incoming).
- CDP verification: band-drag selects N nodes; multi-drag moves N;
  alt-drag pushes a neighbour; Ctrl+Shift+U expands selection
  upstream.
