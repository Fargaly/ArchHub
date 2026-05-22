---
id: AgDR-0033
timestamp: 2026-05-21T22:00:00Z
agent: claude-code (Sonnet)
session: founder gripe 2026-05-21 — "STILL NOT WORKING" (delete saved skill)
trigger: AgDR-0032 made delete_saved_skill resolve via the canvas-skill store but added a read_only gate that rejected shipped seeds.  The skills the founder actually wants to delete ("canvas", "ping-outlook-fork") live in app/skills/ — mis-saved there by the historical save_as_skill source-tree-write bug — so the gate blocked the real use case.
status: approved
category: architecture
projects: [archhub]
extends:
  - AgDR-0032 — delete_saved_skill canvas-store fix this AgDR completes
  - AgDR-0028 — original delete-saved-skill action
  - AgDR-0010 — Save-as-Skill envelope format
---

# Skill delete — tombstone shipped seeds instead of rejecting them

## Context

`app/skills/*.archhub-skill.json` (the "shipped" store) serves double
duty:
1. Genuine shipped starter seeds.
2. User skills mis-saved there by the historical `save_as_skill`
   bug (it used to write the source tree instead of
   `%LOCALAPPDATA%\ArchHub\skills\`).

AgDR-0032's `read_only` gate treated EVERYTHING under `app/skills/`
as an untouchable seed.  But the founder's `canvas` +
`ping-outlook-fork` skills live there — they're user content.  CDP
proof:

```
delete_saved_skill("canvas")
→ {"ok":false,"error_code":"read_only",
   "error":"'canvas' ships with ArchHub and cannot be deleted."}
```

The founder reasonably expects to delete their own skill.

## Decision

Replace the `read_only` rejection with a **tombstone**:

- **User-store skill** (`%LOCALAPPDATA%\ArchHub\skills\…`) → unlink
  the file (unchanged from AgDR-0032).
- **Shipped-store skill** (`app/skills/…`) → record its slug in a
  per-user tombstone file
  `%LOCALAPPDATA%\ArchHub\skills\_hidden-skills.json`.
  `_scan_canvas_skills()` filters tombstoned slugs out of every
  listing.

Why tombstone, not unlink-the-seed:
- An app update would restore an unlinked seed file.
- A read-only / Program-Files install would fail the unlink.
- The tombstone is per-user state — survives app updates, never
  needs write access to the app tree.

`save_as_skill` clears a slug's tombstone when the user saves a new
skill of that name — a fresh save should be visible again.

## Consequences

- Every skill the panel lists is now deletable.  No `read_only`
  dead end.
- `delete_saved_skill` returns `{"ok":true,"method":"unlinked"}`
  or `{"ok":true,"method":"tombstoned"}` — JSX toasts success
  either way.
- `clear_all_saved_skills` unlinks user files + tombstones shipped
  seeds.
- New per-user file `_hidden-skills.json`.  It is NOT a skill file
  (no `.archhub-skill.json` suffix) so the scan glob ignores it.
- AgDR-0032's `read_only` error code is retired from this path.

## Forks

- **Tombstone file location**: chosen `%LOCALAPPDATA%\ArchHub\skills\_hidden-skills.json`
  (next to the user skill store).  Alternative — a key in the
  global profile.json — rejected: keeps skill state co-located.
- **Re-save semantics**: a new save of a tombstoned slug clears the
  tombstone (chosen) vs. keeping it hidden until explicit un-hide
  (rejected — surprising).

## Acceptance

1. `delete_saved_skill("canvas")` → `{"ok":true,"method":"tombstoned"}`.
2. `get_saved_skills()` no longer lists `canvas`.
3. Re-saving a skill named `canvas` makes it reappear.
4. `clear_all_saved_skills` empties the panel list.
5. Suite green.  CDP-verified on the live app.

## Artifacts

- This AgDR.
- `app/bridge.py` — tombstone helpers + delete/clear rewrite +
  save_as_skill tombstone-clear.
- `tests/test_delete_saved_skill.py` — updated (read_only test →
  tombstone test).
