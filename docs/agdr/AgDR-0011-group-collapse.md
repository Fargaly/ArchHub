---
id: AgDR-0011
timestamp: 2026-05-20T00:00:00Z
agent: claude-code (Sonnet)
session: node-redesign-loop
trigger: /loop slice C2
status: executed
category: architecture
projects: [archhub]
---

# Group Collapse to Giant-Node — Auto-Promoted Sockets

> In the context of slice C2 of the node-system redesign (AgDR-0001
> §7.7 + AgDR-0004 deferred), implementing collapse-to-giant-node, I
> decided to treat collapse as a PURE-VISUAL operation
> (`group.collapsed:bool`), auto-compute "promoted sockets" at
> render time from each member's externally-wired ports (any port
> with at least one wire whose other end is NOT a member), render
> the collapsed group as a single oversize node-like rect with
> those promoted sockets, hide the member nodes + internal wires
> from the canvas while collapsed, and redirect the external ends
> of cross-boundary wires to the giant-node's socket positions —
> to deliver Dynamo-2.13 collapse semantics without touching the
> engine. Accepting: collapsed groups don't expose `data-lm-socket`
> attrs on the promoted sockets yet (drag-to-rewire on a collapsed
> group is C2.next), and the visual remains rect-shaped (not the
> Dynamo "giant node" header gradient).

## Context
- AgDR-0001 §7.7 + AgDR-0004 deferred this from slice C as its own
  problem.
- Slice C shipped Groups MVP — title + description + style +
  drag-with-members. `LM_GRAPH.groups` is `[{id, title,
  description, style, nodeIds[]}]`.
- The engine is untouched by groups today and should stay that
  way — groups are a canvas-side concept.

## Options Considered

| Decision | Picked | Why |
|---|---|---|
| Collapse storage | `group.collapsed:bool` (default false) | One bool; serialises with the group |
| Member visibility | Skip render at NodeCanvas level when member is in a collapsed group | Engine still has the nodes; only the canvas hides them |
| Internal-wire visibility | Skip wire render when BOTH endpoints are hidden | Cleanest "looks like one node" |
| Cross-boundary wire | Redirect the hidden endpoint to the group's promoted-socket position | Standard giant-node convention |
| Promoted socket computation | At render time, walk wires: any wire where exactly one endpoint is a hidden member exposes that member's port as a promoted socket on the in/out side | Cheap; no separate index to keep in sync |
| Socket dedup | Promote each `(member_id, port_id)` ONCE per group side | Many external wires can share one promoted socket |
| Giant-node geometry | Width 280, height grows with max(promoted_in, promoted_out) × 24 + 56 | Predictable; doesn't pretend to be a real node |
| Collapse toggle | Small chevron button on the group header (▾ / ▸) | Discoverable; sits next to the existing ✕ ungroup |
| Engine effect | None — collapse is visual only | Engine sees the inner graph as-is |

## Decision

### Data model
- `group.collapsed: bool` (default false). Round-trips through
  `LM_GRAPH.groups` already.

### Compute (per render)
For each group:
- `hidden(memberId)`: true if the member is in a collapsed group.
- `promoted_in[group_id]`:
  set of `(member_id, port_id)` where some wire
  `(src, _) → (member_id, port_id)` has `src` not a member of this
  group. Type from the member's `ins` port.
- `promoted_out[group_id]`:
  set of `(member_id, port_id)` where some wire
  `(member_id, port_id) → (dst, _)` has `dst` not a member.

### Render (collapsed group)
- Replace the existing "rectangle behind members" render with a
  giant-node rect at the same bbox position (snapped to the
  group's centre when collapsed):
  - Width 280, height = `Math.max(promoted_in.size,
    promoted_out.size) * 24 + 56`.
  - Style-coloured header (existing styling), title + description
    summary, ▸ expand button (replaces the ▾ collapse button when
    collapsed), ✕ ungroup button.
  - In sockets on the left, out sockets on the right, vertically
    stacked, labelled with `member.label || member.title`.

### Skip member render
In the `(allNodes || []).map(n => ...)` block, if `n.id` is in any
collapsed group, return null.

### Wire redirect
At wire-coords build time, when computing each wire's `(x1,y1)` /
`(x2,y2)`:
- If source member is hidden, replace source point with the group's
  promoted-out socket position.
- If dest member is hidden, replace dest point with the group's
  promoted-in socket position.
- If BOTH endpoints are hidden in the same group → skip the wire
  entirely (purely internal).
- If both hidden in DIFFERENT collapsed groups → both endpoints
  redirected.

### Toggle
Add a `▾` (collapsed → `▸`) button to the group header. Click toggles
`group.collapsed`, calls `saveCurrentGraph` + `bumpGraph`.

## Consequences

- New `collapsed` field on the group blob (backward-compatible).
- Canvas render gains: hidden-members set computation, promoted-
  sockets computation, giant-node render path, wire-redirect at
  coord time.
- No engine changes; whole-graph `run_workflow` cooks the inner
  members as before.
- A collapsed group blocks drag-to-rewire to/from a promoted
  socket (data-lm-socket attributes not exposed yet — C2.next).
- Saved graphs round-trip the collapsed state through the existing
  `LM_GRAPH.groups` serialisation.

## Artifacts
- This AgDR.
- `app/web_ui/studio-lm.jsx` edits: render group, wire redirect,
  collapse toggle.
- CDP verification: create a group of 2-3 nodes wired through, click
  ▾ → collapsed view shows promoted sockets at the boundary, wires
  redirect.
