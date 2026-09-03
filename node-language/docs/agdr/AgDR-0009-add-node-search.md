---
id: AgDR-0009
timestamp: 2026-05-20T00:00:00Z
agent: claude-code (Sonnet)
session: node-redesign-loop
trigger: /loop slice F
status: executed
category: architecture
projects: [archhub]
---

# Add-Node Search Overlay — Double-Click + Tab + Wire-Promote + Prefix Grammar

> In the context of slice F of the node-system redesign (AgDR-0001
> §7.2), implementing the four layered add-node patterns, I decided
> to ship one unified `AddNodeSearch` overlay invoked from four
> entry points (double-click empty canvas, `Tab` global, drag-wire-
> into-empty, "+ add node" toolbar), with Grasshopper-style prefix
> grammar (`~text` → Note, `"text"` → Constant string,
> `=expr` → Constant expression, `0<5<10` → Input with default 5)
> and predictive autocomplete that ranks by (1) type-compatibility
> with the wire-promote source if present, (2) recent-use count
> persisted in `localStorage`, (3) alphabetical — to compress four
> entry points into one consistent UI without scattering palette
> code across the canvas. Accepting: slider range syntax spawns a
> plain Input (no actual slider primitive yet — separate slice).

## Context
- AgDR-0001 §7.2 locked four layered patterns. The first one
  (double-click search) and the prefix grammar are missing. The
  second (drag-wire-to-empty) already works via
  `WirePromotePalette` + the `lm-wire-promote` event but is a
  separate component. The Tab shortcut isn't bound. Predictive
  autocomplete isn't ranked.
- Multiple add-node entry points exist today (`+ add node` button,
  library modal, `Tab` unbound, double-click unbound, wire-promote
  palette). Unifying into ONE overlay is the cleanest fix.
- `WirePromotePalette` already filters grammar primitives by
  type-compat with the dragged output. We absorb its logic.

## Options Considered

| Decision | Picked | Why |
|---|---|---|
| Overlay placement | New `AddNodeSearch` at the StudioLM root | Outlives any canvas state; works from anywhere |
| Event protocol | `lm-add-node-search` custom event with `detail:{ x, y, from?, anchor? }` | Decouples invocation site from rendering |
| Tab handling | Global `keydown` in StudioLM; ignored when focus is in INPUT/TEXTAREA/SELECT | Matches n8n + matches our other keyboard handlers' contract |
| Double-click empty canvas | New `onDoubleClick` on the canvas wrap that fires the event with cursor coords | Discoverable; matches Grasshopper |
| Prefix grammar precedence | `~` Note > `=` Constant expression > `"…"` Constant string > `N<M<N` Input range > otherwise fuzzy search | Each prefix is unique; first-match-wins |
| Slider range | Spawn Input with default = middle of the range | No slider primitive exists; the value is honest, the UI isn't gold-plated |
| Recent-use storage | `localStorage` key `__archhub_recent_node_use` — object `{kind: count}` | Tiny; survives relaunch; merges across sessions |
| Result item kinds | Grammar primitives, the 16 per-host connectors (specialisations of `connector`), saved Skills | Mirrors the palette; covers what users can actually add |
| Wire-promote integration | Reuses the same overlay; replaces `WirePromotePalette` | One UI to maintain |

## Decision

### State + invocation
In `StudioLM`:
- New state `addNodeSearch: {x, y, from?} | null`. `x`/`y` are
  screen coords (the overlay clamps itself to viewport). `from`
  is the wire-promote source `{nodeId, sockId, type}` when fired
  from wire-drop.
- Event listener for `lm-add-node-search` sets it.
- The existing `lm-wire-promote` listener now ALSO sets
  `addNodeSearch` (replaces `wirePromote` state — old palette is
  retired).
- New global `keydown`: `Tab` (no modifier, no form-input focus)
  prevents default and dispatches `lm-add-node-search` at the
  centre of the viewport.

### Canvas double-click
`NodeCanvas` adds `onDoubleClick` to the canvas wrap. When the
click target is NOT inside `.lm-node`, dispatch
`lm-add-node-search` with the cursor coords.

### Overlay
A new component `AddNodeSearch({state, onClose, onPick})`:
- Floating panel positioned at `state.x, state.y` (clamped to
  viewport bounds).
- Autofocus a search input.
- Below the input, a scrollable list of result items.
- Footer hint: "Prefix: `~note` `"text"` `=expr` `0<5<10` …".

### Prefix grammar (parsed at Enter)
Order:
1. `~(.+)` → Note with `text=$1`.
2. `=(.+)` → Constant with `value=$1` (string).
3. `"(.+)"` → Constant with `value=$1`.
4. `(\d+)<(\d+)<(\d+)` → Input with `default=$2`, `min=$1`, `max=$3`.
5. otherwise → use the highlighted result row (or the first).

### Ranking
Each result has a `score`:
- `+100` if `from.type` provided AND the item's first input type
  matches `from.type` (or either is `any`/`ANY`).
- `+ Math.min(20, recentCount * 2)` for recent-use bumps.
- `- name.toLowerCase().indexOf(query.toLowerCase())` for query
  prefix-match bonus.
- Ties broken alphabetically by display name.

Top 12 shown.

### Recent-use
`localStorage.__archhub_recent_node_use` is `{ [kind|hostId]: count }`.
On pick, increment. Persist.

### Placement
The picked item is spawned via `addNodeFromLibrary(libItem,
canvasX, canvasY)` where the canvas coords are converted from
the screen coords carried in `state.x/y`.

For wire-promote (`state.from` present), after spawn, auto-wire
the source socket to the new node's first compatible input. The
existing `WirePromotePalette` `onPick` had this logic at
`studio-lm.jsx:1487` — port verbatim to the new flow.

### Retirement
`WirePromotePalette` component definition + its `wirePromote`
state in StudioLM are deleted. The `lm-wire-promote` event is
kept as an INPUT (handler now sets `addNodeSearch`).

## Consequences

- 1 new component (`AddNodeSearch`), 1 new state field
  (`addNodeSearch`), 1 new global Tab binding, 1 new canvas
  double-click binding.
- `WirePromotePalette` component deleted (~70 LOC).
- `wirePromote` state in StudioLM deleted.
- The "+ add node" toolbar button now dispatches
  `lm-add-node-search` at the toolbar position instead of opening
  the legacy library modal. (Library modal stays for the AI Node
  Smith entry only.)
- LocalStorage gains one tiny key.
- No engine changes, no Python changes.

## Artifacts
- This AgDR.
- `app/web_ui/studio-lm.jsx` edits.
- CDP verification: Tab → overlay opens; `~hello` → spawns Note;
  `"foo"` → spawns Constant `foo`; type a name → picks correct node.
