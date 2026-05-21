---
id: AgDR-0006
timestamp: 2026-05-21T00:00:00Z
agent: claude-code (Sonnet)
session: m1-shipping · founder /loop till finalize
trigger: /loop slice C3 — group nesting
status: proposed
category: architecture
projects: [archhub]
extends:
  - AgDR-0004 §"Deferred" line 129 — C3 deferred to own AgDR
  - AgDR-0005 — boundary-port promotion (extended to recursive
    member-set when a group contains nested groups)
---

# Group Nesting — Recursive Bbox · Recursive Member-Set · Drag Cascades · Nesting Cycle Guard

> In the context of slice C3 of the node-system redesign (deferred
> from AgDR-0004), I decided to ship **a SECOND field on
> `LM_GRAPH.groups[]` — `childGroupIds: string[]`** — instead of
> overloading `nodeIds` with group ids. Nesting is a tree: a
> parent group references child groups by id, child groups
> reference their member nodes (and possibly more children). For
> rendering, `expandedMembers(g)` walks the tree to the leaves and
> returns the FULL recursive node-id set (used for bbox + drag +
> promotion). For collapse, the boundary-port algorithm from
> AgDR-0005 uses the recursive member-set — a wire is internal if
> both endpoints are in `expandedMembers(g)`. Cycle guard: a group
> cannot reference itself or any of its ancestors as a child.
> Accepting: no UI for nesting yet beyond a context-menu "Add to
> group →"; drag still moves only the topmost selected group +
> its full subtree; per-level collapse (a parent collapsed while
> a child expanded) is OUT of scope — collapse cascades down.

## Context

AgDR-0005 shipped Group Collapse with boundary-port promotion. It
explicitly assumed groups are flat. Founders that lay out
production graphs (Dynamo, Grasshopper) end up with sub-regions
inside sub-regions ("the loop body", "the input prep", "the
output formatting"). The C3 slice closes this.

Three primary forces:
1. **Data model** — overload `nodeIds` (lets nodes + groups
   coexist in the same list) or split into `nodeIds` + `childGroupIds`.
2. **Bbox geometry** — needs to be recursive (a child group's bbox
   counts as a member bbox).
3. **Drag cascades** — moving a parent should move every nested
   group AND every nested node.

## Options Considered

### Fork 1 — Data model

| Option | Picked | Why |
|---|---|---|
| Overload `nodeIds: string[]` with both node ids + group ids | no | Ambiguous at every callsite; needs `nodeById.has(id) ? node : group` branching everywhere |
| **Separate fields: `nodeIds: string[]` + `childGroupIds: string[]`** | **YES** | Clear at every callsite · child-group set is small (typically 1-3) · backward-compatible (legacy groups have no `childGroupIds`) |
| Generic `members: {id, kind}[]` with `kind:'node'|'group'` | no | Over-engineered for the MVP; both other options are simpler |

**Pick: Separate `childGroupIds`.**

### Fork 2 — Recursive expansion

| Option | Picked | Why |
|---|---|---|
| **Compute `expandedMembers(g, allGroups, depth=0)` on demand** — walks the tree, returns flat set of LEAF node ids | **YES** | Deterministic · pure · cheap (groups are typically shallow) · cycle-detectable via visited-set + depth cap |
| Materialise + cache the expansion on every mutation | no | Drift risk · invalidation pain · YAGNI for ~10-deep trees |
| Hybrid (cache the deepest expansion + invalidate on group edit) | no | Premature opt; recursion is O(group-tree-size) per call |

**Pick: On-demand recursion.**

### Fork 3 — Collapse semantics with nesting

| Option | Picked | Why |
|---|---|---|
| **Collapse CASCADES** — when a parent collapses, every nested group + node hides; the parent's collapsed-node shows the full set's promoted boundary ports | **YES** | One mental model: collapse = "hide this whole subtree." Boundary-port algorithm just uses `expandedMembers(parent)`. Promoted ports are correct (a child-group's INTERNAL nodes have no external wires; only the parent's outer boundary does) |
| Per-level collapse — parent collapsed, child can stay expanded | no | Three-state rendering (parent rect + child rect + collapsed-parent-node) creates visual conflict; the founder's Dynamo expectation is the cascade model |
| Per-level visibility flag (children render inside the parent's collapsed-node body) | no | Recursive embedded canvas; nice future feature, out of MVP scope |

**Pick: Cascade collapse.**

### Fork 4 — Drag cascades

| Option | Picked | Why |
|---|---|---|
| **Drag the topmost selected group → multi-drag includes every descendant node AND every descendant group's `anchor`** | **YES** | Matches user mental model of nesting · existing `onGroupDragStart` is reused with the expanded id list · child groups' anchors only matter when they are collapsed |
| Drag only nodes (descendant groups recompute their bbox post-drag) | no | When a child is collapsed, its anchor must move OR its position lags behind the parent |
| Treat nested groups as immovable when parent moves | no | Strange UX; breaks the "drag this region" affordance |

**Pick: Drag cascades.**

### Fork 5 — Cycle guard

| Option | Picked | Why |
|---|---|---|
| **Refuse mutation (UI + API) that would create a cycle**, detected by walking `childGroupIds` graph + visited-set | **YES** | Single point of enforcement · easy to test · safe |
| Accept cycles + cap recursion depth | no | Silent failure mode; the user just sees a "max-depth reached" toast for an action they intended |

**Pick: Refuse cycles.**

## Decision

### Data model

```
LM_GRAPH.groups[g] = {
  id, title, description, style, nodeIds[],
  collapsed: boolean,
  childGroupIds: string[],  // NEW (default [])
}
```

Cycle invariant: for any `g`, `g.id ∉ ancestors(g)` where
`ancestors(g) = parents(g) ∪ ancestors(parents(g))`.

### Algorithms

```python
def expand_group_members(group_id: str, all_groups: list,
                          _visited: set = None,
                          _depth: int = 0) -> set[str]:
    """Recursive node-id set for a group — walks childGroupIds,
    returns the flat union of all leaf node ids. Cycle-safe:
    once a group is visited, it is not entered again. Depth cap
    of 16 levels — deeper than that is almost certainly a cycle
    we missed, surfaces as an empty add (with a console.warn)."""
    _visited = _visited or set()
    if group_id in _visited or _depth > 16:
        return set()
    _visited = _visited | {group_id}
    g = next((x for x in all_groups if x.get("id") == group_id), None)
    if not g:
        return set()
    out = set(g.get("nodeIds") or [])
    for cid in (g.get("childGroupIds") or []):
        out |= expand_group_members(cid, all_groups, _visited,
                                     _depth + 1)
    return out


def would_create_cycle(parent_id: str, candidate_child_id: str,
                        all_groups: list) -> bool:
    """True iff adding `candidate_child_id` to `parent_id`'s
    `childGroupIds` would close a cycle."""
    if parent_id == candidate_child_id:
        return True
    # Walk the candidate's ancestors. If any ancestor IS the parent,
    # the candidate is already above the parent in the tree.
    seen = set()
    stack = [candidate_child_id]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        if cur == parent_id:
            return True
        for g in all_groups:
            if candidate_child_id in (g.get("childGroupIds") or []):
                stack.append(g["id"])
    return False
```

`_promoted_ports_for` (AgDR-0005) takes the group's `nodeIds`
directly. With nesting, it switches to `expand_group_members(g.id, ...)`
so the recursive node set drives boundary detection.

### Engine-time wire rewrite

`expand_collapsed_groups()` already iterates collapsed groups and
collects promoted-port → member-port rewrites. The only change for
C3: the promotion now uses the recursive member-set. If a child
group is itself collapsed, its boundary ports promote to the
parent (correctly — a descendant's boundary is also the parent's
boundary).

### JSX surface

- `LM_GRAPH.groups[g].childGroupIds` field round-trips through
  `save_graph` (no Python schema change).
- `expandedMembersJS(groupId, allGroups, depth=0, visited)` JS
  helper mirrors `expand_group_members`.
- Group bbox: when computing the visual rect (expanded mode), the
  child groups' bboxes count as additional bbox contributors.
- Drag cascades: `onGroupDragStart` collects every descendant
  node + every descendant group anchor (collapsed only) before
  starting the multi-drag.
- Node context-menu gains "Add to group ▶" submenu listing the
  user's groups. Group context-menu (header right-click) gains
  "Group inside ▶" submenu. Both go through `wouldCreateCycle`.
- Promotion render: same algorithm, but with the recursive
  member-set on `expandedMembersJS`.

### Save

No new fields in `save_graph` — `childGroupIds` rides along on
the same `groups[]` array.

## Consequences

### What ships (this slice)

- `app/workflows/node_grammar.py` — `expand_group_members()`,
  `would_create_cycle()`, plus `_promoted_ports_for` switch to
  the recursive set when `childGroupIds` is non-empty.
- `app/web_ui/studio-lm.jsx` — JS mirrors + drag-cascade +
  context-menu add-to-group + bbox extension.
- Tests: recursion correctness, cycle detection, drag cascade
  invariant, nested-collapse boundary promotion.

### What collapses

- Nothing — additive.

### What's reinforced

- The invariant: the FLAT engine graph cooks the same regardless
  of grouping or nesting state — `expand_collapsed_groups()` is
  the one rewrite step, agnostic to depth.

### Risks

- A user explicitly editing the saved JSON could introduce a
  cycle the UI rejected. Mitigation: `expand_group_members` is
  cycle-safe (visited-set + depth-cap), so the worst case is
  silent truncation (with a console.warn).
- Deeply nested groups (>5 levels) are a UX wart — bbox margins
  + nested header stack get visually noisy. Mitigation: out of
  scope for this MVP; if it bites users, ship a "collapse all
  descendants" shortcut.

### Tests

| Test | What it proves |
|---|---|
| `test_expand_group_members_flat` | A group with only `nodeIds` (no children) → returns its `nodeIds` as a set |
| `test_expand_group_members_one_level` | Parent with one child group → returns parent.nodeIds ∪ child.nodeIds |
| `test_expand_group_members_two_levels` | A→B→C nesting → returns the leaves of C |
| `test_expand_group_members_cycle_safe` | Group references itself → returns set without infinite recursion |
| `test_would_create_cycle_direct` | Adding `g` as its own child returns True |
| `test_would_create_cycle_indirect` | Adding ancestor as a child returns True |
| `test_promoted_ports_with_nested_member` | Wire from a nested grandchild to outside → still promotes to the outer group's boundary |
| `test_collapsed_nested_graph_cooks_same` | Cooking a graph with a 2-level nest, parent collapsed, gives the same value as the fully-expanded form |

## Implementation order

1. ✓ This AgDR (done).
2. Python: `expand_group_members` + `would_create_cycle` + hook
   into `_promoted_ports_for` + 8 unit tests.
3. JSX: JS mirrors + drag cascade + context-menu add-to-group +
   bbox extension.
4. CDP verify: create 2 groups, add one as child of the other,
   collapse parent → child + all members hide; expand → restored.
5. Founder sign-off → flip status to `executed`.

## Open forks for founder

1. **Per-level collapse.** Want a child group to be able to stay
   expanded inside a collapsed parent (i.e. render the child's
   collapsed-node nested INSIDE the parent's collapsed-node body)?
   The MVP says no — collapse cascades. A future slice can lift
   this.
2. **Nesting UI.** This slice adds the data + algorithms but only
   a minimal context-menu entry-point. A proper "Move group into
   group" drag affordance is a future slice (D3 likely).
3. **Visualising the tree.** Should the right-panel show a
   "Groups" tree view? Out of MVP scope; layer in if useful.

## Artifacts

- This AgDR.
- Pending: `app/workflows/node_grammar.py` edits, `app/web_ui/studio-lm.jsx`
  edits, `tests/test_group_nesting.py` (new).
