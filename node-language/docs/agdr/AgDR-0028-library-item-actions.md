---
id: AgDR-0028
timestamp: 2026-05-21T15:00:00Z
agent: claude-code (Sonnet)
session: founder gripe 2026-05-21 — "THE LIBRARY ACTIONS... FILTERS... CLEARING CUSTOM NODES... DELETING THOSE SAVED SKILLS?... WHY ISN'T IT POSSIBLE?"
trigger: NodesPanel context menu only had Expand all / Collapse all / Clear most-used.  No way to delete a custom node or a saved skill from the library.
status: executed
category: ux
projects: [archhub]
extends:
  - AgDR-0010 — Save-as-Skill (the producer of saved skills)
  - AgDR-0013 — LIBRARY-FIRST gate (the producer of custom nodes)
---

# Library item actions — delete a custom node · delete a saved skill · bulk clear both

> Founder pain: the NodesPanel had no per-item or bulk actions for
> the two USER-OWNED collections (MY NODES + SKILLS).  The only
> menu items were Expand all, Collapse all, Clear most-used — none
> of which touch the items themselves.  This AgDR adds the missing
> CRUD verbs.

## Constraints (signed)

1. **Right-click on a MY NODES row** opens a per-custom-node menu
   with Delete + Pin/Unpin.
2. **Right-click on a SKILLS row** opens a per-saved-skill menu
   with Delete.
3. **Right-click on empty panel space** keeps showing the existing
   menu (Expand/Collapse/Clear most-used) PLUS new bulk actions:
   Clear all custom nodes, Clear all saved skills.
4. **Confirm before destructive action.** Native `confirm()` is
   acceptable for v1 (faster than building a styled modal).  The
   prompt names the item + count.
5. **Shipped skills are protected.** `delete_skill` already returns
   False for read-only entries; the clear-all loop relies on this.
6. **Bridge slots emit `skills_changed`** so the JSX library
   re-renders without manual refresh.
7. **No silent failures.** Bridge slots return
   `{ok: bool, error?: str}`; JSX toasts the error.

## Surface added

### Bridge slots (`app/bridge.py`)

```python
@pyqtSlot(str, result=str)
def delete_saved_skill(self, skill_id) -> str: ...

@pyqtSlot(str, result=str)
def delete_custom_node(self, type_id) -> str: ...

@pyqtSlot(result=str)
def clear_all_custom_nodes(self) -> str: ...

@pyqtSlot(result=str)
def clear_all_saved_skills(self) -> str: ...
```

All four emit `skills_changed` on success.

### `workflows/custom_nodes.delete_spec(type_id)` (new)

Unregisters the type from the live `_REGISTRY` AND removes the
spec file under `%APPDATA%\ArchHub\custom_nodes\`.  Returns True
when a file was deleted.

### JSX (`app/web_ui/studio-lm.jsx`)

- The single `ctxMenu` dispatcher in `NodesPanel` now branches on
  `ctxMenu.kind`:
  - `undefined` → panel menu (existing + 2 new bulk items)
  - `'custom-node'` → Delete + Pin/Unpin for one MY NODES row
  - `'saved-skill'` → Delete for one SKILLS row
- MY NODES + SKILLS rows wrap in `<div onContextMenu>` that sets
  `ctxMenu.kind` + `payload`.
- Delete actions call the new bridge slot, toast success/failure,
  and rely on `skills_changed` to refresh the list.

## What does NOT ship

- Styled confirmation modal (native `confirm()` for v1).
- Category filter pills (the existing search box already filters
  by text; a dedicated category filter is a follow-up slice).
- Multi-select + bulk delete from selection (founder demand left
  open).

## Acceptance

1. Right-click a MY NODES row → menu shows Delete custom node…
2. Confirm → bridge.delete_custom_node fires → row vanishes (via
   `skills_changed` re-pull).
3. Right-click a SKILLS row → menu shows Delete saved skill…
4. Confirm → row vanishes.
5. Right-click empty panel → menu also has Clear all custom
   nodes… and Clear all saved skills….
6. Shipped/read-only skills survive the clear-all.
7. Tests green.  Founder confirms via CDP demo.

## Artifacts

- This AgDR.
- `app/bridge.py` (4 new slots).
- `app/workflows/custom_nodes.py` (`delete_spec`).
- `app/web_ui/studio-lm.jsx` (ctxMenu refactor + row wrappers).
- `tests/test_library_item_actions.py`.
