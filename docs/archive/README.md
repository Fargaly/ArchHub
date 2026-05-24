# docs/archive

Historical snapshots. Not the roadmap, not the spec — kept for context
on how a decision was reached.

The single source of truth for active work is `docs/ROADMAP.md`
(per the ROADMAP MANDATE in `CLAUDE.md`). Architectural decisions live
in `docs/agdr/`.

## What's here

### `audits/`
Point-in-time audits of the codebase / surface state. Each is dated;
each was true on its date, but the code has moved past them. Cited
from `CHANGELOG.md` for the patch they justified.

- `AUDIT_2026-05-14.md` — first surface-by-surface state audit
- `BRUTAL_AUDIT_2026-05-14.md` — uncompromising follow-up pass
- `SHADOW_AUDIT.md` — shadow-vs-real surface inventory
- `SCOPE-AUDIT-2026-05-21.md` — scope-creep correction trigger
- `PERF_AUDIT.md` — performance hotspot audit
- `UI_AUDIT_v1.2.md` — brand-drift forensic
- `UI_DEAD_SURFACE_AUDIT.md` — first dead-UI surface sweep
- `UI_DEAD_SURFACE_AUDIT_v2.md` — second pass after the first round of cuts

### `node-rnd-2026-05-15/`
R&D session from 2026-05-15 on the node-grammar redesign. Designs
landed in `docs/agdr/AgDR-0001-node-system-redesign.md` and the
subsequent AgDR-002x series — these are the source materials, not the
spec.

- `NODE_RND_2026-05-15.md`, `NODE_RND_REFRAME_2026-05-15.md`
- `NODE_BODY_VS_PANEL_RND_2026-05-15.md`
- `NODE_INTERACTION_UX_PRINCIPLES_2026-05-15.md`
- `HOST_NODE_UI_GRAMMAR_2026-05-15.md`
- `AI_REASONING_VISUALIZATION_RND_2026-05-15.md`

### Loose files
- `CODEX_UI_HANDOFF.md` — handoff doc to an earlier coding-agent run
- `UI_FIX_NOTES.md` — interim fix notes during the UI dead-surface pass

## A note on internal links

Some archived files contain links to other docs written as
`docs/X.md` — relative to the repo root at the time. After this
archive move those paths now resolve to `docs/archive/audits/X.md` or
`docs/archive/node-rnd-2026-05-15/X.md`. Internal links inside
archived files are intentionally **not** rewritten — these documents
are snapshots and should read as they did the day they were written.
For the current location, check the file lists above.
