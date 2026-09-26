# CLAUDE.md — the node-language repository

**Read `docs/FOUNDER_MANDATES.md` before your first edit.** The founder's
thirty standing mandates live there (carried from the retired 12.PRODUCTION): ALWAYS-UTILIZE-WORKFLOWS,
SHOW-THE-WORKFLOW, EXHAUSTIVE-DELIVERY, PROTOTYPE-FIRST-NEVER-ASK, ANTI-LIE,
DEFINITION-OF-SHIPPED, SESSION-CLOSE, ROLLBACK-PROTOCOL, ROMA. A session that
never opens a file in that repository loads none of them.

This file exists because that happened. On 2026-09-08 a session worked here for
hours — the graph, the boot, the courts, the installed app — with the whole
contract invisible, and wrote no FAILURE_LOG entry, no AgDR and no audit table
until the founder asked why. `docs/FAILURE_LOG.md` in this repository is where
the incidents go (its earlier entries were carried from 12.PRODUCTION).

## The law this repository is measured against

`SPEC.md` §1 and §3.1. One graph; every part a lens over it, never a separate
product exchanging copied status reports. One persisted record — `Cell{id,
link0, link1, atom}`. A semantic side table is forbidden; accelerators are
disposable and deleting one may not change meaning.

`AUTHORITY.md` and the applicable specification come before product work.

## Traps that have cost real hours here

- **Never read the founder's live sqlite with `immutable=1`.** The application
  writes it, so an immutable read returns a torn view and reports "database disk
  image is malformed" on a perfectly healthy file. Use `mode=ro`, which reads
  the WAL. Two wrong reports to the founder came from this in one session.
- **`%LOCALAPPDATA%` is virtualised for agents in an MSIX container.** One `ls`
  can return the container's stale copy of one file and the real machine's copy
  of another, in the same listing, with nothing marking which is which. Read
  through `\localhost\c$\...` when the number matters.
- **The installed app is not this repo.** `%LOCALAPPDATA%\ArchHub\nodelang\` is
  its own copy. A fix committed here reaches the founder only through a build,
  and the two drift per-file. Check before claiming a boot fix landed.
- **`current_cells` has no append-only trigger; `cell_versions` and `revisions`
  do.** That does not make the head disposable — it is the journal, not an
  accelerator file. Pruning reachable cells from it breaks §3.1 invariant 7.
- **The court files bound to the scoreboard are named in
  `evidence/court_bindings.json` AND `evidence/grandmap_bindings.json`.** Run
  only the first and 51 files never execute, which reads as a PASS drop.
- **A court must be shown RED against the code it forbids before it counts.**
  Four courts in this repository were green while the thing they named was
  broken: one compared `SELECT COUNT(*)` to itself, one asserted a refusal
  string no source produces, one pinned an adapter bug as expected behaviour,
  one asserted a code that exists in no file.

## The founder's machine is not a build server

He works on it, with Revit open. No test batch at normal priority while he is
there — `BelowNormal`, one batch, and only on his word or clear absence. The
full bound-court run is 31 minutes.
