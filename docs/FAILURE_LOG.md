# FAILURE_LOG

Current repository incidents. Earlier v1 incidents are historical evidence in
[the archive](archive/cleanup-2026-10-15/docs/FAILURE_LOG-v1.md).
Append an incident with its status, claim, gap and resolution; never rewrite history.

### 2026-09-08 · boot set the founder's graph aside on a refusal it did not understand
- **status**: closed
- **claim**: the launcher keeps the saved graph unless it is genuinely unreadable.
- **gap**: four times between 2026-09-01 and 2026-09-07 the launcher set the graph aside and opened an empty canvas, for four different reasons (`runtime descriptor signature is invalid`, `Cell database is held by another live process`, `disk I/O error`, `Application Agent Body catalog binding drifted`). The keep-in-place list named only two of them, so the rest fell through to the set-aside branch. The last reason is DERIVED state: every Cell underneath was intact. 15.34 GB sat in five abandoned copies he never saw.
- **resolution**: `b196313` inverted the list to name only UNREADABLE causes. `326b657` (2026-09-15) went further and removed the set-aside: "A startup failure never selects a replacement graph" (`launch_archhub_test.py:550`), and the refusal is printed with "the saved graph is KEPT IN PLACE". The binding court is now `tests_replica/test_launcher_saved_graph.py::test_refused_boot_keeps_the_saved_graph_and_never_creates_a_replacement`. The `b196313` court `tests_replica/test_a_refusal_never_costs_him_the_graph.py` asserts the removed `_UNREADABLE_MARKS` list and is 5/5 red at `fbd694a`; it is retired in the same change as this entry. **CLASS-OF-FAILURE: an allow-list of "safe to keep" causes fails open on every cause nobody anticipated. A boot that cannot open the graph stops and says so; recovery is a separate, visible operation.**

### 2026-09-08 · every boot paid ~51 s to rule out things the store cannot do
- **status**: closed
- **claim**: boot reads only what it needs.
- **gap**: measured on the live 3.9 M-row head. `count()` was called four times at 12.17 s each; `frozenset(snapshot.cells)` was built to test eight roots; and a connect-time `set(snapshot.cells).issubset(store.snapshot().cells)` guarded against deletion, although `CellStore.commit` has no delete parameter. The resumed head load also ended with `SELECT COUNT(*) FROM current_cells` compared to `len(current)`, which resolves to the SAME statement: about 24 s to prove 3921457 equals 3921457.
- **resolution**: `a2f8165` removed the deletion guards and replaced the whole-head sets with point reads (court: `tests_replica/test_the_boot_does_not_read_the_whole_head.py`). `326b657` replaced the head load with a streamed row-by-row audit that never counts the head, and added `idx_current_cells_revision` (a count on a copy fell from 12.68 s to 0.03 s). Courts: `tests_replica/test_the_head_load_never_counts_twice.py` (red against `326b657^`, green at `fbd694a`), and `tests_replica/test_journal_streamed_recovery.py` for the audit that must remain. **CLASS-OF-FAILURE: a guard against an operation the API cannot perform costs real time and checks nothing. Before paying a full scan to rule something out, prove the store can do it; and never compare a number to itself.**

### 2026-09-28 · a half-written legacy deliberation entry can no longer be replayed
- **status**: open
- **claim**: POST /api/universal/deliberation, now writing each payload as an indexed record (b2), replays every key written before it exactly as before.
- **gap**: found by the b2 adversarial review. A key whose payload ValueGraph root Cell exists does keep the old path. But an entry the pre-`326b657` Brain committed WITHOUT its payload tree -- its two-step write, the "entry exists, payload missing" case `append_deliberation_value_entry` repairs -- has no payload root Cell, so it takes the record path, and `prepare_deliberation_entry` refuses the replay ("reused for another payload") instead of repairing it. The refusal writes nothing.
- **resolution**: accepted 2026-09-28 by the coordinator (717): the Brain that wrote such entries is retired, and no caller has replayed one since. Open until a caller needs the repair. Fix then: send a key whose derived entry root exists with neither a payload root Cell nor a record down the legacy repair path. Also open and noted as follow-up: a shared-writer store (`supports_shared_writers`, no instance record table) still writes payloads as ValueGraph Cells. **CLASS-OF-FAILURE: moving a write to a new store splits its history in two; every replay of the old half needs its own route, including the half-written states the old path used to repair.**

### 2026-09-28 · deliberation payloads between 256 KiB and 1 MiB were refused with an opaque error
- **status**: closed
- **claim**: `dafbde1` moved deliberation payloads into indexed records with no change to what a caller may send.
- **gap**: the independent verifier of `dafbde1` caught it. Requests may be 1 MiB (`MAX_REQUEST_BODY_BYTES`), and the old ValueGraph path stored any payload under 1,500 Cells with scalars up to 64 KiB each. So a payload of a few large strings between 256 KiB and 1 MiB used to be stored, and after `dafbde1` it was refused by the record store's bound with "operational record payload exceeds its bound", a message that tells the caller nothing.
- **resolution**: the bound stays at 256 KiB, now one named constant (`OPERATIONAL_RECORD_PAYLOAD_BYTES`) that the store enforces and the route states. The route measures the exact canonical bytes the store will hold and refuses first: "deliberation payload is N bytes, over the 262144-byte bound; record a summary and a digest, and keep the full report where it is read from". Nothing is written. Raising the cap was rejected: GET projects any payload over 64 KiB (`_MACHINE_DELIBERATION_PAYLOAD_BYTES`), so no reader ever received those bytes, and 10,000 records of 1 MiB is 10 GB. Court: `test_a_deliberation_append_creates_no_payload_cells.py::test_a_payload_over_the_record_bound_is_refused_plainly` (red on `dafbde1`, memory and file stores). **CLASS-OF-FAILURE: moving a write to a new store moves its limits too. Compare the new store's bound with what the old path accepted, and refuse at the edge in words the caller can act on.**

### 2026-09-28 · a deliberation record naming another entry read as "expired"
- **status**: closed
- **claim**: `dafbde1` reports a retired payload as expired, never as null.
- **gap**: the same verifier caught it. GET reported `payload_expired` for every record that failed the owner/entry/space/category check, as well as for a missing one. A record PRESENT under the key but bound to someone else is a broken bond, not retention, and calling it expiry hides it.
- **resolution**: one identity check (`_deliberation_record_names`) serves the writer and the reader. Missing reads `payload_expired`; present-but-foreign reads `payload_integrity_failed`, and a replay against it is refused as an integrity failure, not as "reused". Court: `...::test_a_record_naming_another_entry_is_an_integrity_failure_not_expired` (red on `dafbde1`). **CLASS-OF-FAILURE: one "else" branch for two different failures; name each state the reader can actually be in.**

### 2026-10-15 · HOME3 diagnostic court handoff overlap
- **status**: closed
- **claim**: diagnostic source UI and template rerun were scheduled as sequential work.
- **gap**: crossing slot-release messages admitted both into the shared run-heavy queue, which permits two slots. No worker was stopped or replayed.
- **resolution**: root owns every subsequent slot grant; final artifact courts run sequentially. Diagnostic source runs are not final-build evidence. See RESULT-HOME3.md and evidence/HOME3-source-navigation.txt.
