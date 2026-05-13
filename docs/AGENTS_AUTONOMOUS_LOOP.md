# Agents — autonomous roadmap loop

> The departments already chip away at the queue every 30 s. This doc
> covers the layer ABOVE that: how new work LANDS in the queue
> automatically, without anyone manually filing a `.yaml` task.

## The loop in one paragraph

Every `ARCHHUB_ROADMAP_INTERVAL_MIN` minutes (default 30) the cloud
daemon runs `agents.roadmap_dispatcher.tick()`. The dispatcher scans
five sources for open backlog items, dedupes them by stable id, and
enqueues anything new as a department-scoped Task. When a department
finishes a roadmap-sourced task, the existing dispatcher writes the
item's id to `agents/state/completed_roadmap_ids.txt`. The next tick
skips items already on that list. The result: open the roadmap doc,
add a `- [ ]` bullet, and within 30 minutes the right department has
started producing a patch / memo / test plan in
`agents/outputs/<dept>/<task-id>/`.

## Sources

| # | Source                          | How it's read                                          |
|---|---------------------------------|--------------------------------------------------------|
| 1 | `docs/ROADMAP.md`               | Every `- [ ]` bullet outside the "Done" section        |
| 2 | `CHANGELOG.md`                  | Bullets under "Roadmap" / "Limitations" / "Phase 2"    |
| 3 | GitHub issues `roadmap`         | `gh issue list --label roadmap --state open`           |
| 4 | Open draft PRs                  | `- [ ]` checklist items inside the PR body             |
| 5 | `# ROADMAP:` source comments    | Grepped from `app/main.py` by default                  |

Sources 3 + 4 are silent if `gh` is missing or unauthenticated — the
loop never crashes when it can't reach GitHub. Sources 1, 2, 5 always
work because they're plain repo files.

## Tags inside a bullet

```
- [ ] #P0 Frontend invite acceptance page (eng)
       └┬┘  └────────── title ──────────┘  └─┬─┘
        │                                     │
        └─ priority tag                       └─ department hint
```

- **`#P0` / `#P1` / `#P2`** → `priority = high | med | low`. Omitting
  the tag defaults to `med`. The dispatcher rewrites these to integer
  `priority` values (10 / 30 / 70) so the existing queue's
  ascending-priority sort runs P0 work first.
- **`(eng)` / `(qa)` / `(docs)` / `(ops)` / `(rnd)`** at the end of the
  line routes the item to that department. Omit the annotation and the
  loop guesses from keywords ("frontend / api / fix" → eng,
  "doc / page / template" → docs, etc.).

## Adding a roadmap item

```bash
# Open the seed roadmap
vim docs/ROADMAP.md
```

Add a bullet under the right horizon section:

```markdown
## NEXT 7 DAYS

- [ ] #P0 Wire the password-reset email to Resend templates (eng)
```

Commit and push. The next tick picks it up automatically — no
restart, no manual queue file.

## Marking an item complete

Three equivalent ways:

1. **The agent finishes the task** — the dispatcher writes the id to
   `agents/state/completed_roadmap_ids.txt` for you.
2. **Move the bullet to the "Done — last 7 days" section** of
   `docs/ROADMAP.md`. The loop ignores Done-section bullets.
3. **Manually append the 12-char id** to
   `agents/state/completed_roadmap_ids.txt`. Useful if the work
   shipped via a non-agent path.

To find an item's id without running the loop:

```python
from agents import roadmap_source
for it in roadmap_source.fetch_pending(include_github=False):
    print(it.id, it.title)
```

## Pausing

Two knobs:

```bash
# Stop processing new items entirely. The cloud daemon keeps running
# the recurring scheduler; only the roadmap layer goes quiet.
export ARCHHUB_ROADMAP_DISABLED=1

# Slow the cadence — back-to-back deploys, conservative billing.
export ARCHHUB_ROADMAP_INTERVAL_MIN=180   # tick every 3 h
```

Both are picked up at the next tick (no daemon restart needed).

## Concurrency safety

`agents/state/lock.txt` is exclusive-created at the start of each
tick and removed at the end. A second tick that starts while the
first is mid-flight sees the lock and bails out with
`TickResult(locked=True, enqueued=0)`. This matters when the cloud
runner's 60-s scheduler tick overlaps with a long fetch of GitHub
issues.

## State files (per machine — NEVER commit)

| Path                                          | Purpose                                     |
|-----------------------------------------------|---------------------------------------------|
| `agents/state/completed_roadmap_ids.txt`      | One id per line; items already shipped.     |
| `agents/state/lock.txt`                       | Exclusive-create lock during a tick.        |
| `agents/state/last_tick.txt`                  | ISO timestamp of last successful tick.      |

All three are git-ignored under `agents/state/*` (plus a tracked
`.gitkeep` to preserve the dir).

## Safety contract (unchanged from the rest of `agents/`)

- Agents NEVER auto-modify code on disk.
- All output lands in `agents/outputs/<dept>/<task-id>/`.
- A human reviews + applies the patch (or merges the doc).
- `mark_complete` runs ONLY after the dispatcher confirms a
  `.done` file was written — never on `.failed` tasks.
