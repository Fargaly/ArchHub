# Cloud brain unify — ONE per-user store (2026-05-31)

> ONE-SYSTEM-PLAN-BEFORE-BUILD. The local repo already fought the two-brains
> mess (`docs/audits/brain-unify-design-2026-05-28.md`: graph.sqlite vs
> brain.db). The CLOUD had the SAME split one layer up. This closes it.
> Design reference — not the roadmap. See `docs/ROADMAP.md`.

## The duplicate (what was found)

The cloud had TWO per-user knowledge stores:

- **(a) replica `fragments`** — `brain_replica.py` → `data/replicas/<user_id>/brain.db`,
  table `fragments`. The `/v1/brain/sync` target; the dataset-export source;
  shaped to mirror the desktop `personal_brain` brain (id/kind/text/triple/
  scope/visibility/owner/provenance/valid_from/valid_until/extra/hlc).
- **(b) `memory_facts`** — the `memory_facts` table in `archhub_cloud.db`, the
  `/v1/memory/*` semantic API (list/add/forget/search + FTS5 + embedding col).

Finding: **redundant, not complementary.** Both store one user's atomic
knowledge ("a fact"). A fact added via `/v1/memory/facts` was invisible to
`/v1/brain/sync`, and a fragment synced from the desktop was invisible to
`/v1/memory`. Same divergence the local stores had. → UNIFY to one.

## Canonical store: replica `fragments`

`fragments` is the richer superset (matches the local brain shape, is the
sync target, the dataset-export source, carries hlc/provenance/owner/scope).
`memory_facts` is a strict subset of those columns plus an FTS index. So
**`fragments` absorbs `memory_facts`, never the reverse** — exactly mirroring
the local decision (brain.db absorbed graph.sqlite). `memory_facts` becomes a
**derived FTS/embedding index** over the canonical fragments, not a second
source of truth.

## How both APIs now share one store

- The `db.py` `memory_facts` DAO (`insert/get/list/search/update/delete_memory_fact`)
  is **rerouted to read/write the user's replica `fragments`**. A fact == a
  fragment (`kind='fact'`, memory-origin id `mf-<rowid>`). The DAO presents the
  fragment's integer `rowid` as the public `id` so the existing int-keyed
  `/v1/memory/facts/{id}` surface + every caller (memory_writer, memory_extractor,
  main.py, tests) keeps its exact request/response shape.
- `memory_facts_fts` stays in `archhub_cloud.db` as a **pure index** keyed on
  `(user_id, frag_rowid)` → text, rebuilt on every DAO write/delete. Search
  joins the index back to the canonical fragment. Soft-delete = the fragment's
  `valid_until` (the brain's own tombstone), so `/v1/memory` forget and the
  sync export agree.
- `/v1/brain/sync` is unchanged — it already used `fragments`. Now `/v1/memory`
  writes land in the SAME `fragments` table, so the two APIs agree by construction.

## One-time idempotent migration

`db.migrate_memory_facts_to_fragments()` (marker-guarded, run from
`init_schema`): for every live `memory_facts` row, upsert a fragment
`mf-<original_fact_id>` into that user's replica. Idempotent via stable ids +
a `meta.migrated_memory_facts` marker per replica AND a global
`schema_meta` marker row — a re-run is a no-op, no dups. Mirrors the
token/credit/graph backfills. Legacy rows stay in `memory_facts` for audit but
are no longer read by the DAO (the DAO reads fragments) — no data lost.

## Why `collective_memory` stays separate

`collective_memory` is the anonymised, redacted, cross-user community aggregate
(arXiv 2505.18279) — NOT a per-user store. It has no per-user owner dimension
(by design: contributor id is provenance-only, never queried). It is not a
duplicate of any user's brain, so it is out of scope for this per-user
unification and stays as-is. Only the per-user duplicate (`memory_facts`) was
folded into `fragments`.

## Verify

- both-APIs-agree test: add via `/v1/memory/facts` → present as a fragment via
  `/v1/brain/sync`; sync a fragment via `/v1/brain/sync` → listable via
  `/v1/memory/facts`. ONE store.
- migration test: pre-seed `memory_facts` → run migration → rows present as
  fragments; idempotent re-run = no-op, no dup.
- RED-without-fix: a both-APIs-agree assertion fails against the old
  two-store DAO.
- full cloud suite green (baseline 272 + new).
