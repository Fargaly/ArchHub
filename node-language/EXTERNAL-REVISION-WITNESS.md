# External Revision Witness

Status: WIP design gate. Not deployed. No provider court has run yet.

## Macro

### What

The external revision witness is physical rollback protection for the one
Universal Cell journal. It records only:

- the physical authority identity;
- the last confirmed journal revision and revision-chain digest; and
- at most one pending next revision, digest, and opaque operation token.

It does not store Cells, application facts, users, domains, Work, policy, or
product behavior. PostgreSQL remains the one durable semantic graph.

### Why

An internally valid PostgreSQL point-in-time restore can be older than the last
revision ArchHub accepted. Journal integrity alone cannot distinguish that
legitimate restore from the current head. A witness in separate physical
custody supplies the missing monotonic comparison.

The current signed checkpoint cannot close this cloud crash window. It is
advanced by a post-commit listener, so the database can commit immediately
before the checkpoint update fails. The new witness must participate before
and after the journal commit.

### How

One storage-neutral journal wrapper implements a two-phase protocol:

1. Read the exact confirmed witness state with strong consistency.
2. Conditionally prepare only `confirmed head -> exact next head`.
3. Commit the exact Cell revision to the existing journal.
4. Conditionally confirm that exact pending operation.
5. Only then let `CellStore` publish the revision to interpreters.

No second CellStore, graph, semantic cache, schema, lifecycle, or application
API is introduced.

### Who

- `CellStore` remains the universal physical graph authority.
- The existing Cell journal remains the only Cell persistence provider.
- The journal wrapper coordinates the physical commit boundary.
- The witness provider performs bounded conditional physical reads/writes.
- The admitted runtime fence remains responsible for single active application
  ownership.
- Founder/release authority admits provider identity and infrastructure.

### When

- Reconcile before a durable graph is admitted at startup.
- Prepare immediately before the physical journal append.
- Confirm immediately after the journal append reports success.
- Resolve an ambiguous append by rereading the journal under the held runtime
  fence.
- Deny service when state cannot be proved exactly.

### Where

- Semantic graph: the admitted PostgreSQL Cell journal.
- Physical witness: a separate DynamoDB table and AWS custody boundary.
- Provider credentials: short-lived workload identity, not repository or
  environment-file secrets.
- Policy and evidence: Cells in the Universal Application graph.
- This document: WIP design evidence only, never runtime authority.

## Micro Contract

### Witness State

The physical record has one exact shape:

| Field | Meaning |
|---|---|
| `authority_id` | Stable non-secret identity of the Cell authority |
| `confirmed_revision` | Last externally confirmed journal revision |
| `confirmed_digest` | Chain digest through that revision |
| `pending_revision` | Optional, exactly `confirmed_revision + 1` |
| `pending_digest` | Optional digest of that exact next revision |
| `pending_token` | Optional opaque single-operation identity |

The three pending fields are either all absent or all present. Extra fields,
negative revisions, malformed digests, and non-adjacent pending revisions fail
closed.

### Digest

The witness commits to the existing
`ArchHub/universal-cell-revision-chain/v1` digest. It must not introduce a
second digest algorithm. A court compares every wrapper result to
`CellStore.revision_chain_digest()` at the same revision.

### Startup Reconciliation

| Witness | Journal | Decision |
|---|---|---|
| absent | revision 0, explicit provisioning | conditionally create genesis |
| absent | established or normal runtime | deny |
| confirmed exact | same revision and digest | admit |
| pending next | journal still at confirmed | abort exact pending, admit confirmed |
| pending next | journal at exact pending | confirm exact pending, admit |
| confirmed ahead | journal behind | deny rollback |
| confirmed same revision, different digest | split history | deny |
| journal ahead, no exact pending | unexplained forward state | deny |
| pending malformed or non-adjacent | invalid witness | deny |

Normal runtime never recreates a missing witness. Genesis creation is a
separate, explicit provisioning action and is legal only for revision 0.

### Commit and Crash Outcomes

| Last completed step | Durable result | Recovery |
|---|---|---|
| before prepare | confirmed old / journal old | retry normally |
| prepare only | pending next / journal old | abort pending |
| database commit only | pending next / journal next | confirm pending |
| witness confirm | confirmed next / journal next | admit |
| unknown provider/journal outcome | unknown | reread both; accept only an exact row above |

If confirmation fails after the database commit, the current process must not
publish the new revision. The wrapper enters a fatal state and all further
journal operations fail until a new runtime reconciles the exact pending state.

### Concurrency

Conditional writes must compare the complete confirmed head and the absence or
exact identity of pending state. A runtime fence remains required. The witness
does not replace PostgreSQL transaction conflicts or the application runtime
fence.

### Security

- Strongly consistent point reads are required.
- Eventual reads, indexes, streams, and caches are not admitted for decisions.
- Provider errors are secret-safe and do not render table names, credentials,
  request payloads, or connection strings.
- IAM permits only the exact witness item operations needed by the admitted
  runtime.
- The provider may not enumerate unrelated witness items.
- Unknown provider state and conditional conflicts fail closed.
- DynamoDB point-in-time restore is recovery material, not automatic authority.
  A restored witness table must itself pass a founder-authorized recovery court.

### Deletion

Deleting the wrapper or witness does not alter graph semantics. It removes a
required production safety capability, so cloud startup must deny rather than
silently fall back to an unwitnessed journal.

## Red Courts Before Implementation

The implementation may begin only after these courts exist and fail for the
missing mechanism:

1. The wrapper digest equals the canonical CellStore chain digest.
2. Prepare occurs before journal append; confirm occurs after it.
3. A pre-commit journal failure aborts the exact pending operation.
4. A post-commit ambiguous failure is resolved from actual journal history.
5. Confirmation failure publishes no CellStore revision and faults the wrapper.
6. Restart confirms an exact pending committed revision.
7. Restart aborts an exact pending uncommitted revision.
8. Rollback, same-revision split history, unexplained forward history, and
   malformed pending state are denied.
9. Missing witness is denied except explicit revision-zero provisioning.
10. Conditional conflicts cannot overwrite another pending operation.
11. DynamoDB reads set `ConsistentRead=True`.
12. DynamoDB writes contain exact condition expressions.
13. Provider errors disclose no configured secret or raw provider response.
14. Cloud bootstrap cannot construct a shared runtime without an admitted
    witness configuration.
15. Existing PostgreSQL, runtime-fence, Cell durability, and cloud bootstrap
    courts remain unchanged and green.

## Acceptance Boundary

Source-light fake-provider courts prove protocol mechanics only. Release still
requires:

- a real DynamoDB table with point-in-time recovery enabled;
- real conditional conflict, permission-denial, timeout, and recovery courts;
- real PostgreSQL commit interruption paired with the independent witness;
- workload-identity admission without static AWS credentials;
- an authorized restore rehearsal proving old PostgreSQL is denied;
- an authorized paired recovery rehearsal;
- monitoring, alarms, retention, cost, runbook, and founder acceptance.

Until those pass, this mechanism remains WIP and cloud activation remains
forbidden.

## Primary Sources Reviewed

- DynamoDB conditional expressions:
  https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Expressions.ConditionExpressions.html
- DynamoDB condition operators and functions:
  https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Expressions.OperatorsAndFunctions.html
- DynamoDB read consistency:
  https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/HowItWorks.ReadConsistency.html
- DynamoDB transactions:
  https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transactions.html
- DynamoDB point-in-time recovery:
  https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Point-in-time-recovery.html
- DynamoDB point-in-time restore:
  https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/PointInTimeRecovery.Tutorial.html
