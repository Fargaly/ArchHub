---
id: AgDR-0032
timestamp: 2026-05-21T20:30:00Z
agent: claude-code (Sonnet)
session: founder gripe 2026-05-21 — "attempted deletion... but nothing happened... composer still lagging"
trigger: Two production bugs reported from the v1.4 prototype screenshot.  Both AgDR-0028 follow-ons.
status: approved
category: bugfix
projects: [archhub]
extends:
  - AgDR-0028 — added the delete-saved-skill action this AgDR fixes
  - AgDR-0024 — Composer/streaming chat rail that this AgDR de-thrashes
---

# Composer stream-bump coalesce + delete-saved-skill store fix

> Founder report 2026-05-21:
>   1. Right-click on a saved skill → "Delete saved skill…" → confirm
>      → **nothing happened** (skill stayed in the list).
>   2. Composer (right-rail conversation) **lags during streaming**
>      to the point of "can't interact with it at all".
>
> Two distinct root causes; one AgDR because they share commit scope.

## Bug 1 — `delete_saved_skill` deleted from the wrong store

`bridge.delete_saved_skill(skill_id)` (v1, AgDR-0028) called
`skills.library.delete_skill(skill_id)`.  That function scans
**engine-format** `.skill.json` files in
`%LOCALAPPDATA%\ArchHub\skills.library\` and matches by Workflow id.

But `bridge.get_saved_skills()` reads **canvas-format**
`.archhub-skill.json` files via `_scan_canvas_skills()`, returning
`id == slug` (e.g. `"canvas"`, `"ping_outlook"`).  The two stores
never intersect → every delete returned `not_found` silently.

### Fix

`delete_saved_skill` now resolves through the SAME
`_scan_canvas_skills()` table `get_saved_skills` uses, then unlinks
the file at `match["path"]` IF the file lives under
`_user_skills_dir()` (the writable user store).  Shipped skills under
`app/skills/` return a typed `read_only` error instead of silently
failing.  `clear_all_saved_skills` gets the same treatment.

## Bug 2 — Composer re-renders on every streaming chunk

`onChunk` (handler for `bridge.chat_chunk`) mutates the streaming
assistant message and calls `bumpGraph()` after EVERY chunk.  A typical
40-chunk streamed assistant response = 40 full canvas + composer
re-renders in ~1-2 seconds → main thread saturated → input freezes.

### Fix

`AgDR-0024`'s `bumpGraph` exposes a coalesced sibling
`bumpGraphRaf()` that drops a duplicate bump if one is already
pending in the current animation frame.  Streaming handlers
(`onChunk`, `onReasoning`) route through `bumpGraphRaf()`; one
re-render per frame max regardless of chunk rate.  `onDone`
keeps the synchronous `bumpGraph()` so the "streaming" indicator
clears immediately.

### Why rAF coalescing, not setTimeout / debounce

- A 60 Hz frame is the natural redraw budget — coalescing inside
  rAF guarantees ≤1 React commit per paint regardless of chunk rate.
- No timing constant to tune.  No backlog risk (the user pays
  exactly one render every frame they could see it anyway).
- Falls back gracefully on slow hardware — fewer frames = fewer
  bumps = even less work.

## What ships in THIS commit

1. `app/bridge.py` — `delete_saved_skill` + `clear_all_saved_skills`
   rewritten to use `_scan_canvas_skills` + `_user_skills_dir`.
   Typed `not_found`, `read_only`, `unlink_failed`, `bad_args`,
   `exception` error codes returned to JSX.
2. `app/web_ui/studio-lm.jsx` —
   - `bumpGraphRaf` added (rAF-coalesced bump).
   - Exposed on `window.__archhubBumpGraphRaf` for parity with
     existing `__archhubBumpGraph`.
   - `onChunk` + `onReasoning` switched from `bumpGraph()` to
     `bumpGraphRaf()`.
3. `tests/test_delete_saved_skill.py` — new (10 tests).
4. `tests/test_bump_graph_raf.py` — new (4 tests).

## What does NOT ship

- Switching MORE bump call sites to rAF coalescing.  Only
  high-frequency streaming paths get the coalesce.  Drag, click,
  modal close, etc. still want the synchronous bumpGraph because
  the user's expectation is "immediate redraw on direct input".

## Acceptance

1. Right-click `canvas` (saved skill in screenshot) →
   "Delete saved skill…" → confirm → skill disappears from the
   library list within ~500 ms (bridge emits `skills_changed`).
2. Shipped seed skills under `app/skills/` show `read_only` error
   if delete is attempted; user-store skills delete fine.
3. During a streaming assistant reply (`autocad__get_documents` table
   rendering, multi-paragraph answers, etc.), input remains
   responsive.  CDP frame-rate sample ≥ 50 fps throughout streaming.
4. Suite green.

## Artifacts

- This AgDR.
- Pending: source edits + tests listed above.
