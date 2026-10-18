# MAINREL concrete-fix closure review

Independent reviewer: review_mainrel. Source only; no tests, heavy jobs,
installation, or product edits. Base remains
`d89a50fd2304ea4cbda75e1313c08ed187404f2f`.

| Reviewed issue | Source result |
|---|---|
| Ready publication before migration | Corrected for fresh/new-build setup: mandatory migration now precedes `_write_ready`. Residual same-build marker case below. |
| Torn final JSONL record hides acknowledged history | Corrected: only newline-complete records are parsed, reads return `repair_required=True`, sends refuse without altering the tail. This preserves earlier acknowledged records; it does not repair the interrupted send or claim delivery. |
| Hardlink append corrupts another file | Corrected for an already-existing hardlink: `os.fstat(opened_handle).st_nlink != 1` refuses before initialization/append. |

## Remaining concrete P1

`colleague_setup.py:859-860,903-911`: a pre-existing **valid same-build**
`.archhub-ready` survives when packages are already present. If the now-required
connector migration fails, setup returns 8 without removing that old marker.
The next `--check-ready` still succeeds and skips the refused migration.
Invalidate the marker before mandatory migration (or in every failure path),
then publish it only on successful migration. Include the existing-ready-marker
case in the court, not only the initially absent-marker case.

## Static explanation for agentlink2 test failures

These are source-predicted incompatibilities, not observed test output:

| Test source | Current contract mismatch |
|---|---|
| `tests/test_agentlink2.py:25` | Asserts read schema properties equal `{'since'}`. The new optional `transport` property makes this assertion false. Assert the new exact public schema. |
| `tests/test_agentlink2.py:93,143,144,156` | Incremental nonzero cursors omit explicit transport, so `_mailbox_call` now raises before dispatch. Carry `transport` from the corresponding response, with those existing private-message, backlog, sender and unchanged-graph assertions retained. Line 89 can also fail if the computed cursor is nonzero. |

The tests should exercise explicit workshop/offline cursor continuation and both
desktop transitions; do not restore silent cross-transport cursor interpretation
to satisfy the older caller shape.

## Acceptance blockers retained

- Guard 5: built-app gate has not been certified by this source review.
- Guard 7: real0400/main/real0400 rollback remains unproved here.
- Guard 8: one automatic owner is established; one global physical backup
  directory remains unfulfilled because each source parent has its own backups.
- Active builder tests are not claimed as green or as independent evidence.

## SHA bindings

Git blob SHA-1 identities of exactly reviewed bytes:

| File | Blob |
|---|---|
| colleague_setup.py | 23a01a9f0b7d9014ab4163cf0c92548f3037fdf3 |
| nodelang/native_agent_mcp.py | c3b7872f238c4f2bfcd22acbec5829de2e5ea49b |
| tests/test_agentlink2.py | 0cb20a92e1effad7d38046cc01fabc1de2023a5b |
