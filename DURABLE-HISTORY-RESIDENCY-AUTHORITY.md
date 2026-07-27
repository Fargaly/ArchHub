# Durable History Residency Authority

Status: WIP implementation gate

This document controls the bounded-memory repair for durable Universal Cell
history. It explains the repair; it does not replace `AUTHORITY.md`, `SPEC.md`,
the founder Core Values, the Grand Map, or acceptance courts.

## 1. What

ArchHub preserves every accepted Cell revision in one append-only physical
journal. A running `CellStore` must not also retain the entire durable history
as Python objects.

The physical authority remains:

```text
one CellStore
  |
  +-- current immutable Cell mapping at accepted revision R
  +-- at most two disposable historical snapshots
  +-- one journal-owned history reader bound to R
        |
        +-- same SQLite or PostgreSQL Cell journal
        +-- exact historical queries capped at R
        +-- canonical revision-chain digest capped at R
```

No second graph, replay database, semantic cache, copied control plane, or
history-pruning mechanism is permitted.

## 2. Why

The current durable journals correctly preserve immutable history in database
rows, but `load()` also materializes every historical Cell version into
`CellStore._versions` and `CellStore._changes`. `cells_at()` can then create a
second all-history index in RAM. Process memory therefore grows with the number
of past transactions even when the current graph is bounded.

That is a release blocker because:

1. `SPEC.md` requires exact append-oriented revision history.
2. A long-lived product cannot let RAM scale with every past operation.
3. DPoP replay slots intentionally reuse bounded current Cells while retaining
   immutable evidence at prior revisions.
4. Pruning history would hide accepted facts and break recovery, migration,
   audit, and external rollback witnesses.

The repair changes physical residency only. It does not change Cell identity,
graph meaning, revision numbering, authorization, lifecycle, or public APIs.

## 3. How

### 3.1 Additive journal boundary

Built-in durable journals expose `load_head()`. It returns:

- the exact current Cell mapping;
- the captured accepted revision;
- the canonical revision-chain digest at that revision;
- one physical history reader bound to that same revision.

`load()` remains only as a compatibility adapter for explicitly injected legacy
test journals. Built-in SQLite, PostgreSQL, and witnessed journals must not use
the eager fallback.

### 3.2 Head-bound history reader

The reader provides:

- `revision_cells(revision)`;
- `snapshot_at(revision)`;
- `cells_at(revision, cell_ids)`;
- `created_revision(cell_id)`;
- `chain_digest(revision)`;
- `version_count()`.

Every method denies a request below zero or above its captured head. A reader
cannot silently follow a later writer. `refresh()` atomically adopts a newly
captured head and reader. A successful local append advances the local head.
A write conflict reloads the accepted durable head.

### 3.3 Startup integrity

Startup streams the canonical `(revision, cell_id)` history order. It validates:

- genesis is revision zero;
- revision numbers are contiguous;
- every revision contains changed Cells;
- every record is an exact four-field Cell;
- links resolve in the graph state produced by that revision;
- the canonical revision-chain digest covers every changed Cell.

Startup may perform O(history) database reads. It must retain only O(current
graph) Cell objects plus bounded working state. A trusted checkpoint is not part
of this repair.

### 3.4 Historical reads

SQLite and PostgreSQL answer a Cell-at-revision query with the newest version of
each requested Cell whose revision is less than or equal to the target. A full
historical snapshot uses the same rule across all identities.

The physical lookup index is:

```text
SQLite:    cell_versions(cell_id, revision DESC)
Postgres:  cell_versions(authority_id, cell_id, revision DESC)
```

These indexes are disposable physical accelerators. They contain no semantic
classification and do not include `atom` as copied authority.

### 3.5 Database consistency

SQLite historical reads execute inside one read transaction. SQLite documents
that an active read transaction continues to see its historical snapshot even
when another connection commits later changes.

PostgreSQL head loading and its reader execute against a Repeatable Read
snapshot. PostgreSQL documents that all statements in that transaction see the
same committed database view. Full-history validation and digest scans use
named server cursors so client RAM does not buffer the whole result. The reader
additionally caps every query at its captured ArchHub revision.

### 3.6 Canonical digest and witness

One canonical framing function must produce revision-chain digests for:

- in-memory history;
- SQLite streaming history;
- PostgreSQL streaming history;
- the external revision witness;
- migration equivalence courts.

The external witness must reconcile against the streamed digest at the captured
head. It must not trust current Cells, a mutable cached digest, or an unchecked
checkpoint.

### 3.7 Existing public behavior

These `CellStore` operations retain their meaning and results:

- `read`;
- `snapshot`;
- `at`;
- `revisions`;
- `revision_changes`;
- `cells_at`;
- `cell_created_revision`;
- `retention_stats`;
- `revision_chain_digest`;
- `refresh`;
- `migrate_cell_history`.

For an in-memory store, eager history remains the physical authority. For a
built-in durable store, the same answers come from its head-bound reader.

## 4. Who

- `CellStore` owns the accepted in-process head and bounded snapshots.
- `CellJournal` owns durable revision rows and exact historical reads.
- SQLite is an exclusive single-owner local authority.
- PostgreSQL is the admitted shared-writer cloud authority.
- `WitnessedCellJournal` verifies the physical head against the external
  rollback witness.
- Application, Brain, session, and DPoP code consume `CellStore`; they do not
  create parallel history or replay stores.
- Courts prove equivalence, bounded residency, concurrency, and recovery.

No agent may weaken these boundaries to satisfy a performance number.

## 5. When

- On open: load and validate one captured journal head.
- On read of current state: use the current immutable mapping.
- On historical read: query the bound physical journal and optionally retain
  the result in the existing two-snapshot cache.
- On successful append: publish the new current mapping and advance the reader
  head only after the journal accepts the revision.
- On shared-writer conflict: discard candidate state and refresh from a new
  captured head.
- On close: release journal, reader, transaction, cursor, and owner resources.
- On migration: copy every exact revision and prove the same final digest.

## 6. Where

Implementation authority:

- `nodelang/universal_cell.py`
- `nodelang/postgres_cell_journal.py`
- `nodelang/external_revision_witness.py`

Acceptance authority:

- `tests_replica/test_universal_cell_durability.py`
- `tests_replica/test_universal_cell_cloud_authority.py`
- `tests_replica/test_postgres_cell_journal.py`
- `tests_replica/test_external_revision_witness.py`
- `tests_replica/test_universal_authority_migration.py`
- `tests_replica/test_cell_federated_identity.py`

## 7. Evidence and courts

The repair is not accepted until all applicable courts are green.

### 7.1 SQLite bounded residency

Create many replacements of a fixed Cell set, close, reopen, and prove:

- current Cells, head revision, and digest are exact;
- old `at()`, `revision_changes()`, `cells_at()`, and creation revisions match
  the eager in-memory authority;
- the durable `CellStore` retains no all-version Python archive;
- historical snapshot residency remains at the existing bound;
- `refresh()` preserves the same guarantees.

### 7.2 PostgreSQL shared authority

Against real PostgreSQL, prove:

- startup streams history rather than `fetchall()` materialization;
- historical reads are exact and pinned to the captured head;
- a stale writer refreshes after conflict;
- later concurrent revisions are invisible until refresh;
- the new physical index exists without rewriting Cell history.

### 7.3 Witness and recovery

Prove rollback, split history, ambiguous append, failed witness confirmation,
and digest equality using the streamed head digest.

### 7.4 Migration

Across in-memory, SQLite, and PostgreSQL authorities, prove unchanged:

- revision count;
- exact changed identities per revision;
- selected and full historical snapshots;
- current graph;
- canonical revision-chain digest.

### 7.5 DPoP replay durability

Repeatedly reuse expired replay slots across SQLite close/reopen cycles and
prove:

- current replay Cell count remains capped;
- append-only version count increases;
- first-use evidence remains addressable by exact `(Cell identity, revision)`;
- reopened process residency does not scale with proof count.

### 7.6 Compatibility and anti-bypass

Prove:

- injected legacy test journals can use the eager adapter;
- built-in SQLite, PostgreSQL, and witnessed journals cannot select it;
- no public API, Cell schema, lifecycle, authorization, or graph meaning
  changed;
- deleting the lazy reader loses no accepted journal fact;
- deleting the journal cannot be hidden by resident history.

## 8. Research basis

Primary implementation references reviewed on 2026-07-26:

- SQLite transaction snapshots:
  https://www.sqlite.org/lang_transaction.html
- SQLite multi-column query planning:
  https://www.sqlite.org/queryplanner.html
- SQLite descending indexes:
  https://www.sqlite.org/lang_createindex.html
- PostgreSQL transaction isolation:
  https://www.postgresql.org/docs/current/transaction-iso.html
- PostgreSQL cursors:
  https://www.postgresql.org/docs/current/sql-declare.html

These sources justify physical query and transaction mechanics only. They do
not override ArchHub authority, privacy, lifecycle, or Universal Cell laws.

## 9. Non-goals

This repair does not:

- prune, compact, rewrite, or expire accepted Cell history;
- create a new history service, replay table, or semantic cache;
- introduce a trusted checkpoint;
- change the four-field Cell;
- change revision or conflict semantics;
- bypass global integrity, authorization, lifecycle, or external witness checks;
- claim the application, cloud product, or release complete.

## 10. Release condition

The replay repair remains unreleased until durable history residency is bounded
and every applicable court above proves exact semantic equivalence. Source
custody, independent review, commit, push, and Cell-native evidence recording
occur only after the final source state is green.
