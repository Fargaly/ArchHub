---
id: AgDR-0005
timestamp: 2026-05-21T00:00:00Z
agent: claude-code (Sonnet)
session: m1-shipping · founder /loop till finalize
trigger: /loop slice C2 — group collapse to giant-node
status: executed
founder-signoff: 2026-05-25 — bulk-flip per D4·A pick on docs/prototypes/four-decisions-2026-05-25.html (shipped weeks ago, status drift)
category: architecture
projects: [archhub]
extends:
  - AgDR-0004 §"Deferred" lines 128-129 — C2 / C3 split out as own AgDRs
---

# Group Collapse to Giant-Node — Boundary-Port Auto-Promotion · Visual Replacement · Engine-Side Wire Rewrite

> In the context of slice C2 of the node-system redesign (deferred
> from AgDR-0004), I decided to ship **collapse as a pure-visual +
> wire-rewrite mechanism, NOT a subgraph executor**. When the user
> hits the group header chevron, members hide, the group renders as
> a single oversize node, and **boundary ports** (member-node ports
> whose connected counter-end is OUTSIDE the group, OR which carry
> no wire at all) **auto-promote** to sockets on the collapsed
> group-node. External wires re-target the collapsed node's sockets
> on display. At engine time, `normalize_canvas_graph` rewrites
> wires whose endpoint is a `<groupId>:in|out:<idx>` socket back to
> the underlying member-port — so the runner cooks the same graph
> whether collapsed or expanded. Accepting: a member's INTERNAL
> wires (both ends inside the group) stay hidden and continue to
> cook normally; the collapsed-node body is non-interactive (no
> param edit on the giant node); to edit a member's params the
> user expands first.

## Context

AgDR-0004 shipped Groups MVP — header, style, drag-with-members,
auto-bbox. It explicitly deferred collapse "because external-socket
auto-promotion has its own design contract."

The contract is: **when a group is collapsed, the canvas + engine
must keep cooking the underlying graph correctly**. The user's
mental model: "this whole subassembly is now ONE node." So the
collapsed node needs:
1. The right sockets exposed (= boundary ports of the member set).
2. External wires re-anchoring to those sockets (visual only).
3. Engine-time wire rewriting so existing executors don't need to
   know groups exist.

Dynamo, ComfyUI and n8n all do this. ComfyUI auto-promotes
"orphan" ports; Dynamo lets the user explicitly promote; n8n
collapses workflows-as-subworkflows with explicit input/output
schemas. The right MVP for ArchHub: **auto-promote boundary ports**
(zero-config, matches ComfyUI), edge-case adjustable later.

## Options Considered

### Fork 1 — Collapse mechanism

| Option | Picked | Why |
|---|---|---|
| **Visual collapse + engine-time wire rewrite** — group node is just a chrome wrapper; runner never sees it | **YES** | Engine stays trivial · no new executor · zero risk of subgraph cooking divergence · expand/collapse is purely UI state |
| Subgraph executor — collapsed group becomes a `subgraph.user`-style node with bundled wires | no | Doubles execution paths · engine needs to know group state · invariant: same graph cooks same regardless of UI state would break |
| Hybrid — visual collapse for groups with only 1 boundary in / 1 boundary out, subgraph for multi-port | no | Two code paths means two bug classes; YAGNI on the multi-port edge until shown |

**Pick: Visual collapse + engine-time wire rewrite.**

### Fork 2 — Port promotion policy

| Option | Picked | Why |
|---|---|---|
| **Auto-promote every BOUNDARY port** — a member port is boundary if (a) no wire OR (b) wire's counter-end is outside the group | **YES** | Zero-config · matches ComfyUI · obvious mental model · order = traversal order over members in `groups[g].nodeIds` |
| Manual promote — user picks which to expose | no | Friction · usually wrong default · adjustable later via a small toggle |
| Hybrid — auto-promote by default + manual override list | no | YAGNI for the MVP; ship auto, layer manual later if needed |

**Pick: Auto-promote boundary ports.**

### Fork 3 — Socket-id encoding

| Option | Picked | Why |
|---|---|---|
| **`<groupId>:in:<idx>` / `<groupId>:out:<idx>`** stable across expand/collapse via the order of promoted ports | **YES** | Stable · serialisable · normalize_canvas_graph can resolve back to `(memberId, portName)` via a cached promotion map |
| Synthesised socket id using the wrapped port's name (`<groupId>:in:level`) | no | Collides when two members both have a `level` boundary port |
| UUID per promoted port | no | Non-deterministic across re-collapses; harder to debug |

**Pick: Indexed socket-id.**

### Fork 4 — Persistence

| Option | Picked | Why |
|---|---|---|
| **`groups[].collapsed: bool` only — promoted-ports list recomputed on each collapse** | **YES** | Single source of truth (the member set) · no drift risk · cheap recompute (O(members × ports), tiny) |
| Persist the full `promoted_in[]`/`promoted_out[]` arrays | no | Risk of drift if members are added/removed while collapsed; the policy is deterministic so it can be derived |
| Persist a `promotedPorts[]` overrides list (user reorderings) | no | YAGNI; add when a user requests it |

**Pick: Derive promoted-ports from member set on collapse.**

## Decision

### Data model

```
LM_GRAPH.groups[g] = {
  id, title, description, style, nodeIds[],
  collapsed: boolean,         // NEW · default false
}
```

No `promotedPorts` field — derived deterministically.

### Promotion algorithm

```
function promotedPortsFor(group, allNodes, allWires) {
  const memberSet = new Set(group.nodeIds)
  const ins = []   // [{groupSocket, memberId, portName, portType}]
  const outs = []
  for (const memberId of group.nodeIds) {
    const node = allNodes.find(n => n.id === memberId)
    if (!node) continue
    // For each input port:
    for (const portName of inputPortNames(node)) {
      const incoming = allWires.find(w =>
        w.to.id === memberId && w.to.port === portName)
      if (!incoming || !memberSet.has(incoming.from.id)) {
        // boundary input
        ins.push({groupSocket: `${group.id}:in:${ins.length}`,
                  memberId, portName,
                  portType: portTypeOf(node, portName, 'in')})
      }
    }
    // For each output port:
    for (const portName of outputPortNames(node)) {
      const outgoing = allWires.filter(w =>
        w.from.id === memberId && w.from.port === portName)
      const hasExternal = outgoing.length === 0 ||
        outgoing.some(w => !memberSet.has(w.to.id))
      if (hasExternal) {
        outs.push({groupSocket: `${group.id}:out:${outs.length}`,
                   memberId, portName,
                   portType: portTypeOf(node, portName, 'out')})
      }
    }
  }
  return {ins, outs}
}
```

Deterministic order = traversal over `group.nodeIds` × port order on each node.

### Render

When `group.collapsed === true`:
- Members are NOT rendered (skip in `NodeCanvas` map).
- Group renders as an oversize NODE-style wrapper at the bbox the
  expanded group occupied (anchor preserved). Width 240, height
  `max(120, 28 + 18 * max(ins.length, outs.length))`.
- Title bar: style stripe + chevron (▾ when collapsed → click to
  expand) + title + member count.
- Body shows: 2-line description (italic muted) + "↩ Expand" hint.
- Promoted sockets render at left (ins) / right (outs) with the
  promoted port's color (per Slice D wire-color palette).
- Wires whose endpoint matches a member port get RE-ANCHORED on
  display: source/target replaced with the group socket id.

When `group.collapsed === false`:
- Members render as today (AgDR-0004 path unchanged).
- Group rect renders behind (AgDR-0004 path unchanged).
- Header chevron is ▸ (click to collapse).

### Engine-time wire rewrite

`app/workflows/node_grammar.py:normalize_canvas_graph(graph)`
already rewrites canvas-shape graphs to engine-shape. The collapse
step is one ADDITIONAL pre-pass:

```python
def expand_collapsed_groups(graph: dict) -> dict:
    """Pre-process: rewrite wires whose endpoint references a
    collapsed-group socket ('<gid>:in:<i>' / ':out:<i>') back to
    the underlying member port. Engine sees the flat graph."""
    groups = graph.get("groups", [])
    if not any(g.get("collapsed") for g in groups):
        return graph
    nodes = graph.get("nodes", [])
    wires = graph.get("wires", [])
    rewrite_map = {}  # group_socket_id -> (member_id, port_name)
    for g in groups:
        if not g.get("collapsed"):
            continue
        promoted = _promoted_ports_for(g, nodes, wires)
        for p in promoted["ins"]:
            rewrite_map[p["groupSocket"]] = (p["memberId"], p["portName"])
        for p in promoted["outs"]:
            rewrite_map[p["groupSocket"]] = (p["memberId"], p["portName"])
    out_wires = []
    for w in wires:
        nw = dict(w)
        # Rewrite from-side
        from_id = (nw.get("from") or {}).get("id") or nw.get("from_node")
        if from_id in rewrite_map:
            mid, port = rewrite_map[from_id]
            if "from" in nw:
                nw["from"] = {**nw["from"], "id": mid, "port": port}
            else:
                nw["from_node"], nw["from_port"] = mid, port
        # Rewrite to-side
        to_id = (nw.get("to") or {}).get("id") or nw.get("to_node")
        if to_id in rewrite_map:
            mid, port = rewrite_map[to_id]
            if "to" in nw:
                nw["to"] = {**nw["to"], "id": mid, "port": port}
            else:
                nw["to_node"], nw["to_port"] = mid, port
        out_wires.append(nw)
    return {**graph, "wires": out_wires}
```

Called BEFORE existing `normalize_canvas_graph` body. The runner
sees a flat graph identical to the expanded case.

### JSX surface

Slice C2 adds:
- `groups[].collapsed` toggle via the group header chevron.
- New `promotedPortsForGroup(group)` helper (mirrors Python algorithm).
- `CollapsedGroupNode` component rendering a node-shaped wrapper at
  the group's anchor with the promoted sockets exposed.
- `NodeCanvas` skips member nodes whose group is collapsed.
- Wire rendering re-anchors collapsed-group wires (lookup in
  the promotion map).
- New keybind `Ctrl+Shift+G` toggles collapse on focused group OR
  focused-node's containing group (no-op if not in any group).

### Save

`groups[].collapsed` round-trips through the existing `save_graph`
payload (whole `groups` array stored).

## Consequences

### What ships (this slice)

- `app/workflows/node_grammar.py` — `expand_collapsed_groups()` +
  hook in `normalize_canvas_graph`.
- `app/web_ui/studio-lm.jsx` — `groups[].collapsed`, promotion
  helper, `CollapsedGroupNode`, wire re-anchor at render, member-
  hide gate, `Ctrl+Shift+G` keybind, header chevron interaction.
- Tests: promotion algorithm symmetry (Python/JSX agree on the same
  input), engine-side wire rewrite leaves expanded graphs untouched,
  full collapse→cook→same-result invariant for a known small graph.

### What collapses

- Nothing — purely additive.

### What's reinforced

- The invariant "the underlying graph cooks the same regardless of
  UI state." Collapse is a VIEW, not a computation.
- Boundary-port detection is a pure function of `nodes`+`wires`+
  `group.nodeIds` — deterministic + testable.

### Risks

- A member can carry a port whose `portType` differs in
  expanded-vs-collapsed view if a primitive changes its IO schema.
  Mitigation: promotion runs at render time + at engine time, both
  derive the same way; no persisted snapshot to go stale.
- Two members with same boundary port name produce two indexed
  promoted sockets — visually distinct (`level`, `level`), order-
  stable via `nodeIds` order. Acceptable for the MVP.
- A wire whose endpoint targets a collapsed group socket but whose
  group has since been ungrouped is orphaned. Mitigation: on
  ungroup, expand the group first (so wires re-anchor to member
  ports first), THEN drop the group.

### Tests

| Test | What it proves |
|---|---|
| `test_promoted_ports_no_wires` | A 2-member group with no wires → every member port becomes a promoted socket |
| `test_promoted_ports_internal_wires_hidden` | A wire between two group members is NOT a boundary; its ports do not promote |
| `test_promoted_ports_external_wires_promoted` | A wire whose counter-end is outside the group → that endpoint promotes |
| `test_expand_collapsed_groups_idempotent_when_expanded` | If no group is collapsed, the rewrite is a no-op |
| `test_expand_collapsed_groups_rewrites_endpoints` | A wire to `<gid>:in:0` becomes a wire to the right member-port |
| `test_collapsed_graph_cooks_same_as_expanded` | The runner produces the same `cooked.value` for a known small graph in both collapsed and expanded form |

## Implementation order

1. ✓ This AgDR (done).
2. Python: `_promoted_ports_for` + `expand_collapsed_groups` + hook
   in `normalize_canvas_graph` + 6 unit tests.
3. JSX: `promotedPortsForGroup` + `CollapsedGroupNode` + member-
   hide-on-collapse + wire re-anchor + chevron + keybind.
4. CDP verify: place 2 wired nodes, group them, click chevron →
   collapse → collapsed-node renders with the right sockets;
   external wires re-anchor; cook still emits the same value.
5. Open fork (founder sign-off after this lands): flip AgDR to
   `executed`.

## Open forks for founder

1. **Promoted-port naming.** Right now they are indexed
   (`in:0`, `in:1`, …). Show the wrapped name as a TOOLTIP on the
   socket? Yes (planned).
2. **Manual re-promote.** Slice C2 ships AUTO only. A future
   slice can add a "promoted ports" panel where the user reorders
   / hides / renames. Out of scope here.
3. **Persisting collapsed bbox.** Anchor preserved at the topleft
   of the expanded bbox. Should the collapsed node also remember
   the bbox so re-expanding it doesn't surprise the user? Yes —
   `groups[].anchor: {x,y}` stamped on FIRST collapse, used as the
   expand re-origin. Already in the plan.

## Artifacts

- This AgDR.
- Pending: `app/workflows/node_grammar.py` edits, `app/web_ui/studio-lm.jsx` edits,
  `tests/test_group_collapse.py` (new).
