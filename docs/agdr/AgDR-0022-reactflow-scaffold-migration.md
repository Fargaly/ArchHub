---
id: AgDR-0022
timestamp: 2026-05-21T00:00:00Z
agent: claude-code (Sonnet)
session: m1-shipping · founder /loop "till you finalize" · "don't sleep"
trigger: AgDR-0015 §"Phase 2 — ReactFlow scaffold uses tokens from day 1 (M1.a)" + AgDR-0012 §"WHAT COLLAPSES" — "Custom canvas → replaced by ReactFlow"
status: proposed
category: architecture
projects: [archhub]
extends:
  - AgDR-0012 §"WHAT COLLAPSES" — custom NodeCanvas → ReactFlow
  - AgDR-0015 §"Phase 2 — ReactFlow scaffold uses tokens from day 1"
---

# ReactFlow scaffold — coexistence migration · feature-flagged toggle · LM-token-first styling · port-the-typed-grammar-first ordering

> In the context of AgDR-0012's Direction X lock ("Custom canvas
> (NodeCanvas, sockets, drag, pan, zoom) → replaced by ReactFlow
> (`@xyflow/react`, MIT)") and AgDR-0015's Phase 2 ("ReactFlow
> scaffold uses tokens from day 1"), I decided to ship the
> ReactFlow migration via a **feature-flagged COEXISTENCE model**:
> a `localStorage` toggle (`archhub.canvas = 'custom' | 'reactflow'`)
> selects which canvas the user sees, both built from the same
> `LM_GRAPH` source-of-truth so wire-level identity is preserved.
> Ship the scaffold in 4 sub-slices: P2.a token bindings + minimal
> "hello world" RF instance with ONE typed primitive, P2.b all 67
> visible primitives ported to RF custom-node renderers, P2.c
> Slice-D wire palette / dashed-on-`any` reproduced + Slice-A
> connector op picker port, P2.d Groups + Collapse + Nesting
> (cascade from C2/C3) on the RF substrate. Accepting: the custom
> canvas stays as the default until P2.d ships + founder confirms
> parity; legacy saved graphs round-trip through `LM_GRAPH` (RF
> never owns the persistence model — it consumes `LM_GRAPH.nodes`
> + `LM_GRAPH.wires` + `LM_GRAPH.groups` and emits the same
> shape back).

## Context

AgDR-0012 §"WHAT COLLAPSES" locked the substrate replacement:
> Custom canvas (NodeCanvas, sockets, drag, pan, zoom) → replaced
> by ReactFlow (`@xyflow/react`, MIT).

AgDR-0015 §"Phase 2" locked the styling constraint:
> Every ReactFlow node + edge + handle styled via `LM.*` tokens.
> No magic numbers in the new ReactFlow code.

Neither locked the MIGRATION STRATEGY — how to get from today's
custom NodeCanvas to a working ReactFlow surface without breaking
the founder's daily workflow. This AgDR locks the strategy.

Today's `NodeCanvas` (lines ~4137-5300 in `studio-lm.jsx`):
- ~1200 LOC custom React component
- Owns: pan/zoom transforms, drag + multi-drag (slice B2), socket
  rendering + snap (slice D), wire path + colour palette (slice D),
  Groups + Collapse + Nesting (slices C/C2/C3), node selection,
  rubber-band, context menus, Tab autocomplete (slice F)
- Reads `LM_GRAPH.nodes` + `LM_GRAPH.wires` + `LM_GRAPH.groups`
- Writes the same shape back on every mutation

The ReactFlow library (`@xyflow/react`):
- Provides pan / zoom / drag / connection-line / handle primitives
- Node types REGISTERED via `nodeTypes` map — each gets a custom
  React component for the body
- Edge types REGISTERED via `edgeTypes` — for our typed wire
  palette (per Slice D)
- Persistence is BYO — RF gives `useReactFlow().getNodes()` +
  `getEdges()` but doesn't own storage

## Options Considered

### Fork 1 — Replace vs coexist

| Option | Picked | Why |
|---|---|---|
| **Hot replace — delete NodeCanvas + ship RF as the only canvas** | no | Single-PR ship of ~1200 LOC of slice C/C2/C3/D/F functionality is high risk; founder loses canvas mid-day during regression hunts |
| **Coexistence — localStorage toggle picks `custom` vs `reactflow`; both consume `LM_GRAPH`** | **YES** | Founder can switch back instantly if RF lacks parity · regression tests can target either substrate · code paths don't fight |
| Ship RF as a SEPARATE canvas tab next to NodeCanvas | no | Confusing UX (which one is real?) · two persistence paths |

**Pick: Coexistence toggle.**

### Fork 2 — Migration order

| Option | Picked | Why |
|---|---|---|
| Port the engine layer first (wire/socket model) | no | Engine is already host-agnostic (`workflows/runner.py`); ReactFlow is purely a render+input concern |
| **Port the TYPED PRIMITIVES first** (P2.b — 67 visible primitives become RF custom-node components), THEN edges/wires (P2.c), THEN groups (P2.d) | **YES** | Each primitive port is an isolated unit · founder gets visible progress each sub-slice · partial ports still work because the LM_GRAPH shape stays the same · matches the Slice-A/B/C order the redesign already exercised |
| Drag/pan/zoom first (the substrate mechanics) | no | RF handles drag/pan/zoom natively — no porting needed; that's the WHY of using RF |

**Pick: Typed primitives → edges → groups order.**

### Fork 3 — Token binding

| Option | Picked | Why |
|---|---|---|
| **`LM.*` tokens drive a CSS-in-JS object (`reactFlowStyle`) passed to every RF prop** | **YES** | AgDR-0015 mandate · readable · the existing `LM` object is the source of truth |
| Compile `LM.*` tokens to a CSS variable file at build time | no | We have no build step; everything runs through Babel-standalone |
| Hardcode RF defaults + override per-component | no | Magic numbers, the very anti-pattern Phase 2 forbids |

**Pick: LM-driven inline objects.**

### Fork 4 — Persistence contract

| Option | Picked | Why |
|---|---|---|
| Let ReactFlow own the graph (`useNodesState` / `useEdgesState`) | no | Persistence + LM_GRAPH compatibility break; saved graphs become unreadable |
| **`LM_GRAPH` stays the single source. RF receives `nodes`/`edges` as PROPS + emits change-events that mutate `LM_GRAPH` then call `bumpGraph()`** | **YES** | Identical to today's NodeCanvas contract · zero persistence churn · feature-flag flip is instant |

**Pick: LM_GRAPH-as-source.**

### Fork 5 — Library loading

| Option | Picked | Why |
|---|---|---|
| Ship a vendored `@xyflow/react` build alongside `studio-lm.jsx` (~120 KB UMD) | partial | Works offline; bigger app bundle; download once |
| **Babel-standalone fetches @xyflow/react from a CDN at first launch** | **YES (with vendored fallback)** | Faster initial install; if CDN blocks, fall back to vendored copy. JSX guard: `window.ReactFlow ||= window.__archhubVendored.ReactFlow` |
| Compile RF into a single-file Webpack bundle | no | No build step; defeats the whole "Babel-standalone" architecture |

**Pick: CDN with vendored fallback.**

## Decision

### Coexistence toggle

```js
// studio-lm.jsx — read at module load.
const _canvasFlavor = (() => {
  try { return localStorage.getItem('archhub.canvas') || 'custom'; }
  catch { return 'custom'; }
})();

// At render time:
{_canvasFlavor === 'reactflow' ? <NodeCanvasRF .../> : <NodeCanvas .../>}
```

Settings → Canvas tab gains a radio:
- **Custom (default)** — today's NodeCanvas
- **ReactFlow (preview)** — the migration target

Switching is INSTANT (no reload — the toggle reads on the next
re-render).

### Sub-slice scope

**P2.a — RF substrate + hello world (1 tick)**
- Add `<script>` tag for `@xyflow/react` UMD + provider context.
- New `NodeCanvasRF` component skeleton.
- Render exactly ONE typed primitive (`number`) as an RF custom
  node. Drag works (RF native). Pan + zoom work (RF native).
- Tests: RF module loads, toggle reads/writes localStorage,
  `NodeCanvasRF` mounts without crash.

**P2.b — All 67 typed primitives ported (3-4 ticks)**
- A `_RFNodeBody` component dispatches by `node.kind` → typed
  per-primitive body (number, text, boolean, …, ai_chat,
  ai_plan, code_expr, code_py, adapter.*, share.*).
- Re-use the existing `GrammarBody` rendering path — wrap it
  inside an RF `<Handle>` shell.
- Each primitive's existing `params` array drives the right-panel
  inspector (unchanged from custom canvas).
- Tests: every typed primitive has a registered RF node-type;
  Babel-parse green; CDP audit confirms each primitive renders.

**P2.c — Edges + Slice-D wire palette + Slice-A connector port (2 ticks)**
- Custom RF `edgeTypes` map per `PortType` enum: `number` yellow,
  `boolean` green, `list` blue, … (mirror Slice D palette).
- Dashed dasharray for `any` + tree shape (Slice D wire-shape).
- Slice-A ConnectorRail port: connector master node renders inside
  the RF node body with the per-host badge + op picker.
- Tests: typed wire colours present, dashed strokes for `any`,
  connector op picker works.

**P2.d — Groups + Collapse + Nesting (2 ticks)**
- Implement Group rendering as a special RF node-type (RF supports
  this via `parentNode` + `extent: 'parent'`).
- Reuse `expand_collapsed_groups` engine pre-pass — RF doesn't know
  about groups, the engine resolves them before cook.
- Tests: collapse/expand toggles work, nesting depth works.

### LM token binding contract

Every RF prop that takes a hex / size / radius / shadow / font-size
MUST reference `LM.*`:

```js
const reactFlowStyle = {
  // Node defaults
  node: {
    background:   LM.bgPanel,
    border:       `1px solid ${LM.line}`,
    borderRadius: LM.radius.md || 8,
    fontSize:     LM.font.body || 12,
    color:        LM.ink,
    padding:      LM.size[2] || 8,
    boxShadow:    LM.shadow.md || '0 2px 6px rgba(0,0,0,.4)',
  },
  // Handles (RF's term for sockets)
  handle: {
    width:        LM.size[2] || 8,
    height:       LM.size[2] || 8,
    border:       `1.5px solid ${LM.bgPanel}`,
  },
  // Connection line (drag-in-flight wire)
  connectionLine: {
    stroke:       LM.accent,
    strokeWidth:  2,
  },
};
```

A grep over the new `node_canvas_rf.jsx` for hex literals
(`#[0-9a-f]{3,6}`) MUST return zero matches — guard test enforces.

### Out of scope for this AgDR

- ReactFlow's built-in MiniMap — defer until P2.d ships
- Touch gestures — out of phase 2
- Multi-canvas (multiple RF instances) — single instance only

## Consequences

### What ships per sub-slice

| Sub-slice | LOC delta (est) | Tests | Visible founder change |
|---|---|---|---|
| P2.a substrate | +150 JSX, +50 LOC test | +5 | Settings → Canvas → ReactFlow shows a working canvas with one number node |
| P2.b all primitives | +400 JSX, +100 LOC test | +30 | Every typed primitive renders under RF |
| P2.c edges + Slice A | +250 JSX, +80 LOC test | +20 | Wires + connector op picker work under RF |
| P2.d groups + collapse | +200 JSX, +60 LOC test | +15 | Full parity with NodeCanvas — founder can flip the default |

### What collapses

- Magic numbers in RF rendering (forbidden via guard test).

### What's reinforced

- The `LM_GRAPH`-as-source contract — RF never owns persistence.
- Token-first styling (AgDR-0015 Phase 2 binding).
- Founder agency — toggle is one click, no app restart.

### Risks

- **RF version drift.** `@xyflow/react` ships frequent updates.
  Mitigation: pin a specific UMD version (e.g. 12.3.5).
- **CDN blocked behind enterprise firewalls.** Mitigation: vendor
  a UMD fallback in `vendor/xyflow.umd.js` (~120 KB).
- **Babel-standalone parse cost.** RF adds ~12 K LOC. Mitigation:
  the existing JSX is already ~9 K LOC parsed at startup; an
  additional 12 K is +30% — measure, accept, or compile if it
  exceeds 500 ms on a typical laptop.
- **Founder regression hunt.** During the migration, the founder
  may flip to RF, hit a parity gap, and lose work. Mitigation:
  every mutation still goes through `LM_GRAPH` → flipping back to
  Custom restores the same state.

### Tests per sub-slice

**P2.a guard tests:**
- `archhub.canvas` localStorage key reads + writes
- `NodeCanvasRF` mounts without crash
- Toggle in Settings flips canvas without reload
- No hex literals in `node_canvas_rf.jsx` body

**P2.b guard tests:**
- Every visible primitive has an RF node-type registered
- `_RFNodeBody` dispatches by `node.kind`
- A placed `number` / `code_expr` / `ai_chat` renders the right body

**P2.c guard tests:**
- Typed wire colours match the Slice-D palette
- Dashed dasharray on `any` / tree wires
- Slice-A connector op picker still renders inside the RF node

**P2.d guard tests:**
- Group collapse toggles + cascade
- Nested group expansion preserves recursive bbox
- Engine cook-equivalence (collapsed RF graph cooks same as expanded)

## Implementation order

1. ✓ This AgDR.
2. **P2.a** sub-slice (next 1-2 ticks): substrate + one primitive.
3. **P2.b** sub-slice (3-4 ticks after P2.a): all primitives ported.
4. **P2.c** sub-slice (2 ticks after P2.b): edges + connector op.
5. **P2.d** sub-slice (2 ticks after P2.c): groups + collapse + nesting.
6. Founder confirms parity → flip the localStorage default to
   `reactflow` → delete NodeCanvas (covered by a separate AgDR).

## Open forks for founder

1. **Default canvas.** Today's default: `custom`. The flip to
   `reactflow` happens after P2.d ships + founder confirms. OK?
2. **CDN vs vendored.** I default to CDN-first with vendored
   fallback. If founder's environment requires offline-first,
   flip to vendored-default.
3. **NodeCanvas removal timing.** Keep around as fallback for 1
   release after RF becomes default (allow rollback) — or rip
   immediately to keep one canvas in the codebase?

## Artifacts

- This AgDR.
- Pending: `app/web_ui/studio-lm.jsx` (toggle wiring),
  `app/web_ui/node_canvas_rf.jsx` (new), `vendor/xyflow.umd.js`
  (new vendored fallback), `tests/test_reactflow_p2a*.py` (new).
