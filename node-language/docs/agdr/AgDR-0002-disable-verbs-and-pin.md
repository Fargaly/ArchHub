---
id: AgDR-0002
timestamp: 2026-05-20T00:00:00Z
agent: claude-code (Sonnet)
session: node-redesign-loop
trigger: /loop slice B
status: executed
category: architecture
projects: [archhub]
---

# Disable Verbs + Pin Data — State Model + Execution Semantics

> In the context of slice B of the node-system redesign (AgDR-0001
> §7.5), implementing the four-verb disable model + Pin Data, I
> decided to store each verb as an independent boolean field on the
> node (`bypass`, `frozen`, `preview_off`, `pinned`) plus
> `pinned_value` / `pinned_at`, with engine semantics realised via
> `normalize_canvas_graph` graph-rewriting — pinned and frozen nodes
> replaced by a `data.constant` of the snapshot value, bypassed
> nodes wire-rewired (first input → first output, others dropped) —
> to deliver true effect (not decorative state), accepting the
> bypass-rewire simplification (single port-pair) which covers
> `transform` / `filter` / `watch` / `ai` cleanly and degrades
> honestly for multi-port nodes.

## Context

- AgDR-0001 §7.5 locked the four disable verbs as **independent and
  composable**. A node can be both Frozen and Preview-off.
- No engine-side state model existed for any of these verbs before
  this slice.
- Founder mandate (CLAUDE.md ENGINEERING MANDATE): a verb that
  doesn't actually affect execution = decorative = rejected. Slice B
  must ship the engine effect, not just the visual.

## Options Considered

### State storage

| Option | Pros | Cons |
|---|---|---|
| **Independent booleans on the node** (`node.bypass`, `node.frozen`, `node.preview_off`, `node.pinned`) (PICKED) | Composable; trivially serialised in the graph blob; renderer reads directly | Four fields per node — cheap |
| Single enum `node.disabled` | Compact | Not composable (Frozen + Preview-off must combine) |
| Separate state map keyed by node id | Decoupled from node data | Lifecycle complexity, serialisation overhead |

### Engine semantics

| Option | Pros | Cons |
|---|---|---|
| **Graph rewriting at normalize time** (PICKED) | Engine and every executor stay unchanged; one place to read the verb state; trivial to test in isolation | Multi-port bypass needs a port-pair convention |
| Per-executor branch on state | Distributed | Every executor must learn the four verbs — repeats forever |
| Wrapper executor per verb (`passthrough.bypass` etc.) | Generic | Adds a node-type per verb; runner gains four new types |

## Decision

### State model — fields on every canvas node

- `bypass: bool` — node = pass-through pipe; removed from execution.
- `frozen: bool` — node + downstream use cached output (`node.cooked`).
- `preview_off: bool` — UI-only flag; suppresses inline body and watch
  renders.
- `pinned: bool`, `pinned_value: any`, `pinned_at: int (ms epoch)` —
  return this snapshot instead of executing.

All default to absent / false. Backward-compatible with saved graphs.

### Keybindings (when a single node is focused on the canvas)

| Key | Action |
|---|---|
| `Ctrl+B` | toggle `bypass` |
| `Ctrl+F` | toggle `frozen` |
| `Ctrl+Shift+P` | toggle `preview_off` |
| `P` | toggle `pinned` (on enable: snapshot taken from current `cooked.value`) |

Implementation: a single document-level `keydown` handler in `StudioLM`
that ignores events from form inputs (`tagName in {INPUT, TEXTAREA,
SELECT}` or `isContentEditable`), reads `focusId`, mutates the focused
node in `LM_GRAPH`, calls `saveCurrentGraph()`, bumps the graph.

### Engine semantics — in `normalize_canvas_graph`

Three pre-passes, in this order:

1. **Pin**: for each `node.pinned && pinned_value !== undefined`,
   replace `type = 'data.constant'`, `config = {value: pinned_value}`.
2. **Freeze**: for each `node.frozen && node.cooked &&
   cooked.value !== undefined` (and not already pinned), replace
   `type = 'data.constant'`, `config = {value: cooked.value}`.
   Frozen-with-no-cooked = pass-through (runs normally) until first
   cook, then frozen on subsequent runs.
3. **Bypass**: for each `node.bypass` node B, find the first inbound
   wire `→(B, _)` and the first outbound wire `(B, _)→`. Add a new
   wire `(inbound.src, inbound.srcport)→(outbound.dst,
   outbound.dstport)`. Drop B and all wires touching B. Other ports
   on multi-port nodes are explicitly dropped (logged as a code
   comment; honest behaviour beats silent surprise).

Preview-off is not engine-touched. UI-only in `NodeBody` and watch
panels.

### Visuals (canvas node body / frame)

- **Bypass**: dashed grey border, ↦ icon, body dimmed.
- **Frozen**: blue tint, ❄ icon.
- **Preview-off**: body dimmed, ⊘ icon.
- **Pin**: purple badge `pinned @ HH:MM` top-right corner.

Composable — a node can show multiple state indicators at once.

### `lm-run-connector-op` per-node Run path

The per-node Run for connector nodes also respects the verbs:
- If `pinned` or `frozen` → return the snapshot/cached value
  immediately without dispatching to the host.
- If `bypass` → skip — Run is a no-op on a bypassed node (and we
  show a toast saying so).

## Consequences

- Five new fields on the canvas node schema (`bypass`, `frozen`,
  `preview_off`, `pinned`, `pinned_value`, `pinned_at`). Absent
  fields ⇒ false. Existing saved graphs unaffected.
- `normalize_canvas_graph` gains three pre-passes (~60 LOC total).
- Four new keyboard bindings on a single document-level keydown
  handler.
- Four new state indicators on the node body.
- `lm-run-connector-op` gains a short-circuit branch.
- Bypass with multi-port nodes only rewires the FIRST port pair —
  documented as a known simplification. Re-evaluable in a later AgDR
  if it bites.

## Artifacts

- This AgDR (`docs/agdr/AgDR-0002-disable-verbs-and-pin.md`).
- `app/workflows/node_grammar.py` — `normalize_canvas_graph`
  pre-passes (incoming).
- `app/web_ui/studio-lm.jsx` — keybinding handler + node body
  state indicators + Run short-circuit (incoming).
- Tests: `tests/test_canvas_adapter.py` — pin/freeze/bypass rewrite
  cases (incoming).
