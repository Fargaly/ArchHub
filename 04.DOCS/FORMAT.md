# .archhub session format v1

A UTF-8 JSON document with `format: "archhub"`, `version: 1`, stable `id`, `title`, `nodes`, `wires`, `groups`, `notes`, and `viewport`. The document is the in-memory Canvas state; Open never executes it.

Each node has `id`, engine `type`, `params` and `position: {x,y}`. Optional `item` selects the existing Library card; otherwise the engine's declared Library sockets are used. Optional title, parent, children, presentation, frozen/pinned flags and JSON result retain editor and output state. Unknown engines survive opening and produce a clear missing-engine refusal on Run.

Each wire has a stable `id`, `from: {node,socket}`, `to: {node,socket}`, and optional `rule` using the existing stem wire condition grammar. One wire per input; cycles refuse before engine effects. Named socket values are delivered in topological order. A failed node retains its error and downstream nodes show Blocked. Effects use existing Enforce and engine-local approval boundaries.

Save validates first, writes and fsyncs one temporary file in the destination directory, then uses atomic replacement. A failed write preserves the old destination. Recent paths and per-session recovery files are local metadata under `%LOCALAPPDATA%/ArchHub/sessions-files/`; the portable document contains no account identity, local recent paths, tokens or secrets. No execution occurs on file drop or Open.

## Session model (ONE BUILD 1, 2026-11-16)

One session file is one piece of work. These optional `properties` keys hold the rest of it; a missing key is its default, so older files open unchanged and opening never writes. A value with another owner is referenced, never copied.

| Key | Holds | Default | Owner / route |
|---|---|---|---|
| `project` | registered workspace `root_id`; the label is read live from `settings/workspaces.json` | `taskContext.workspace`, else the task's project label mapped to its root, else none | `session_files.set_session_fields` |
| `state` | `open`, `done` or `archived`; finished leaves Home unless pinned | the linked task row (archived, done), else `open` | task completion, archive and board moves write it |
| `pinned` | keeps the session on Home | legacy `taskContext.homePinned`, else false | `set_session_fields`, `workshop_tasks.update_session(homePinned)` |
| `doneCheck` | `{command}` (runs in the project's registered workspace) or `{node}` (a check node on this canvas), plus `tries`, `blocked`, `lastError` | none: Done on the agent's word | `workshop_tasks.complete()` runs it; a failure is a failed step, three failures block Done |
| `settings` | per-session values keyed by Settings row id, resolved above the global value | none: every value global | `set_session_fields`, `resolve_setting` |
| `inputLinks` | `[{source:{path,id}, output, input, rule?}]`: path relative to the workspace root plus the source document id (D-038); no value, state or hash | none | link state (waiting, ready, failed, source missing) is read live; a cycle is refused |

Trigger nodes (`trigger.*`) carry two switches in their params: `armed` (default true; an unarmed trigger is never timed) and `ask_before_running` (default true; a fire becomes an "asking" run until approved). Triggers are timed only while the app is open; the list reports `armed` (stored) and `live` (timed now) separately. Plan and handover stay in `taskContext.plan` / `taskContext.handover`; members and leases stay in the Workshop task row.

**Run history** is one append-only UTF-8 JSON-lines file beside the session, `<document id>.runs.jsonl` (so a rename keeps it). Each line is the newest state of one run: `id`, `trigger` (`manual` or the trigger node id), `kind`, `reason`, `state` (`running`, `asking`, `approved`, `queued`, `skipped`, `succeeded`, `failed`, `waiting-for-approval`), `start`, `end`, `failedNode`, `approvalId`, `error`. The run engine reports the outcome; this file only keeps it. Route: `POST /api/session-model` with `action` = `list`, `get`, `set`, `links`, `runs`, `setting`, `approve-run`.

Limits: 8 MiB UTF-8 document, 10,000 nodes, 50,000 wires. The JSON schema is `ARCHHUB.schema.json`; runtime validation additionally checks identity uniqueness, group membership, wire endpoints and finite numbers. File association and a native Save As picker are installer/launcher integration hooks and must be admitted with that owner.
