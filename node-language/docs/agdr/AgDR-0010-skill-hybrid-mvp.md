---
id: AgDR-0010
timestamp: 2026-05-20T00:00:00Z
agent: claude-code (Sonnet)
session: node-redesign-loop
trigger: /loop slice G
status: executed
category: architecture
projects: [archhub]
---

# Skill-as-Node — Hybrid Save Dialog + Mode-Driven Spawn Semantics (MVP)

> In the context of slice G of the node-system redesign (AgDR-0001
> §5), implementing the hybrid skill-as-node, I decided to ship a
> save-time `Mode: Shared | Private` toggle that drives spawn-time
> semantics (Shared → a `skill` node with `skill_id` referencing
> the file; Private → the subgraph inlined directly into the
> current graph), plus description + category metadata persisted
> alongside the envelope, plus a `Disentangle` action on the node
> menu that converts a Shared `skill` node into its inline Private
> form — to land the user-visible hybrid contract this iteration,
> accepting: the engine's `subgraph.user` reference-resolution at
> whole-graph run time is already in place but its end-to-end
> shape is verified by spawn-time tests only; deeper engine work
> + Promote-Private-to-Shared belong to a follow-up AgDR-0011.

## Context
- AgDR-0001 §5 locked the hybrid model:
  - Save dialog with `Mode: Shared (reference) | Private (copy)`.
  - Shared → `.archskill` file referenced by every placement;
    edits propagate.
  - Private → snapshot stamp; each placement independent.
  - `Disentangle` action forks a Shared instance to Private.
  - Promote Private → Shared later.
- Existing pipeline:
  - JSX `save_as_skill(name, payload_json)` Python slot already
    persists a `{kind:"archhub.skill", name, slug, graph}`
    envelope to `%LOCALAPPDATA%/ArchHub/skills/<slug>.archhub-skill.json`.
  - JSX dispatches `lm-spawn-skill` with the skill blob; current
    behaviour inlines the subgraph (Private semantics by
    coincidence).
  - The `skill` grammar primitive resolves to engine
    `subgraph.user` — exists, READY.
- What's missing:
  - Save dialog (currently saves with default name only).
  - Mode toggle + persistence.
  - Spawn-time branch on Mode.
  - Disentangle action.

## Options Considered

| Decision | Picked | Why |
|---|---|---|
| Metadata transport | Extend `save_as_skill`'s `payload_json` with a `meta:{mode, description, category}` block | No bridge-signature churn; envelope absorbs the meta |
| Save dialog trigger | Node-menu "★ Save as Skill" already exists — open the dialog from there | Reuses the existing entry point |
| Shared spawn | Place ONE `skill` node carrying `skill_id`, `skill_name`, `skill_mode:'shared'` | Engine `subgraph.user` already keys off `config.skill_id`; this lets edits propagate |
| Private spawn | Inline-expand the subgraph nodes into `LM_GRAPH.nodes` + wires (offset to drop point); no wrapper node | Matches the founder's "stamp" mental model; existing flow does this |
| Disentangle | On a `kind:'skill'` node, add a menu item that fetches the source skill via `load_skill`, expands its graph inline, deletes the Shared wrapper node | Mirrors Grasshopper "Disentangle" |
| Promote Private→Shared | Deferred — needs reverse engineering (gather the inlined nodes back into a subgraph). AgDR-0011 territory | Out of scope for slice G MVP |

## Decision

### Save dialog
A new `SaveSkillDialog` opens when the node-menu action fires.
Fields:
- **Name** (text, autofocus). Defaults to current node title.
- **Description** (textarea, optional).
- **Category** (text, optional; freeform tag).
- **Mode** (pill pair):
  - **Shared (reference)** — recommended (default for libraries).
    "Edit once, every placement updates."
  - **Private (copy)** — recommended for one-offs. "A snapshot
    stamped at save time. Independent placements."
- **Save** + **Cancel**.

On submit, JSX:
1. Build the subgraph payload (existing logic — the focused node
   + reachable downstream + connecting wires).
2. Attach `payload.meta = { mode, description, category }`.
3. Call `bridge.save_as_skill(name, JSON.stringify(payload))`.

### Python `save_as_skill`
Extended to read `payload.meta` and write it into the envelope:
```json
{
  "kind": "archhub.skill",
  "name": "...",
  "slug": "...",
  "meta": { "mode": "shared", "description": "...", "category": "..." },
  "graph": { "nodes": [...], "wires": [...] }
}
```
Backward-compatible: absent `meta` defaults to `{mode:'private'}`
on read.

### Spawn (`lm-spawn-skill` handler in JSX)
On dispatch with the skill blob `{id, name, mode, graph}`:
- If `mode === 'shared'`:
  - Place a single `skill` grammar node at the drop point.
  - `node.skill_id = blob.id`, `node.skill_name = blob.name`,
    `node.skill_mode = 'shared'`, `node.config = {skill_id: blob.id}`.
  - Engine sees `kind:'skill'` → `subgraph.user` executor → loads
    the subgraph by id.
- If `mode === 'private'` (or absent):
  - Expand the subgraph inline: copy each node from `blob.graph.nodes`
    with a fresh id + offset position; copy each wire rewriting
    endpoints to the new ids; push into `LM_GRAPH.nodes` / `.wires`.

### Disentangle (node menu action)
For nodes with `kind:'skill'` AND `skill_mode === 'shared'`:
- Menu item "Disentangle (snapshot)".
- On click: fetch the source skill via `bridge.load_skill(skill_id)`,
  inline-expand the graph (private semantics), delete the
  Shared wrapper node.
- Already in `NodeMenu`, just need a new branch.

## Consequences

- `bridge.save_as_skill` now reads `payload.meta` (3 new fields:
  `mode`, `description`, `category`). Backward-compatible.
- New `SaveSkillDialog` JSX component.
- New menu item on `skill` nodes ("Disentangle").
- Two distinct spawn paths inside the existing `lm-spawn-skill`
  handler.
- Deferred to AgDR-0011: Promote Private→Shared, deeper engine
  reference-resolution end-to-end tests.

## Artifacts
- This AgDR.
- `app/bridge.py` — `save_as_skill` meta absorption.
- `app/web_ui/studio-lm.jsx` — SaveSkillDialog + spawn branch +
  Disentangle action.
- CDP verification: open Save-as-Skill on a focused node → dialog
  shows; pick Shared → spawn places a `skill` node with
  `skill_mode:'shared'`; pick Private → spawn inlines the graph.
