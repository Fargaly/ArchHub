# Brain unify — ONE store design (2026-05-28)

> ONE-SYSTEM-PLAN-BEFORE-BUILD mandate. The founder never asked for two
> brains. Today `app/memory/graph.sqlite` (AgDR-0042) and
> `personal-brain-mcp/brain.db` (AgDR-0044) are separate stores, reconciled
> only by the manual band-aid `tools/brain_unify.py`. This unifies them.
> Design reference — not the roadmap. See `docs/ROADMAP.md`.

## Live state (measured 2026-05-30, both stores on disk)
- `graph.sqlite`: 204 nodes (153 capability · 48 decision · 3 skill), 565 edges.
- `brain.db`: 224 fragments (204 already `graph:`-imported by a prior
  brain_unify run · 18 user · 2 firm), 14 skills. Daemon `:8473` live.
- In-app brain view shows **204** (reads graph.sqlite via `memory_stats`).
  Daemon `brain.health` shows **222** facts (reads brain.db). They diverge —
  and the 204 graph nodes are DUPLICATED across both stores. That is the bug.

## Canonical store: `brain.db` (the daemon store)
Why brain.db, not graph.sqlite: it is the richer superset — fragments + skills
+ FTS5 + 5-scope ACL + provenance + multimodal columns; the daemon already
serves it on `:8473`; the cloud sync (`/v1/brain/sync`) already targets it;
`memory_gate.BrainClient` already reads it. graph.sqlite is a plain
nodes/edges table with no scope/provenance — a strict subset. So brain.db
absorbs graph.sqlite, never the reverse.

## One-time migration path
`tools/brain_migrate.py` (NEW; wraps the existing `brain_unify.unify()` core
so the proven idempotent mapping is reused, not rewritten):
1. Read every graph.sqlite node → upsert a Fragment id `graph:<node.id>`
   (capability→FACT, decision→DOCUMENT, skill→FACT; edges ride in
   `extra.graph_edges`). Idempotent: stable ids, content-precheck skip.
2. Stamp `brain_meta.migrated_from_graph = <iso ts + node count>` so a fresh
   run KNOWS the migration is already done and is a no-op.
3. Print before/after fragment counts + the parity check.
This is a MIGRATION (run once), not a sync (run forever). Step 2's marker is
what makes it one-time.

## Going-forward: both read/write ONE store
- **Read parity (the fix that retires the band-aid):** the in-app
  `bridge.memory_stats` slot stops reading graph.sqlite directly. It asks the
  daemon (`brain.health` via BrainClient) for the canonical fact/skill counts
  and renders THOSE, falling back to the local graph only if the daemon is
  down (honest degrade). Result: in-app view and daemon show the SAME number
  from the SAME store.
- **Write path:** extractors (AgDR-0042) still populate graph.sqlite as the
  raw-extraction staging table; `brain_migrate.py` folds it into brain.db.
  The canonical COUNT the user/daemon both see comes from brain.db only — so
  there is one source of truth even while the extractor staging table exists.
  (Full extractor-writes-brain.db-directly is the deeper follow-up; not
  needed for count parity, flagged below.)

## Retiring `brain_unify.py`
`tools/brain_unify.py` keeps its proven `unify()` function (imported by the
migration) but is no longer the ongoing reconciliation. The reconciliation is
gone: nothing needs periodic graph→brain copying because the in-app view now
reads the canonical store directly. On a fresh run, `brain_migrate.py` sees
the `migrated_from_graph` marker and does nothing. A header note redirects
callers to `brain_migrate.py`.

## Verify
Run `brain_migrate.py`; show ONE canonical store (brain.db); show in-app
`memory_stats` and daemon `brain.health` reporting the SAME fact count; show
re-running the migration is a no-op (marker present). 

## Honest remaining work (not count-parity blocking)
Extractors writing fragments DIRECTLY to brain.db (eliminating graph.sqlite as
even a staging table) is the deeper single-store end-state. This pass makes the
COUNTS one-store-true and kills the manual sync; the staging-table elimination
is the follow-up.
