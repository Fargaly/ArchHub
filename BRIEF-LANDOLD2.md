# LANDOLD round 2: make the companion patch pass on current main 62680818. Fresh worker; continue from the ledger.

Round 1 (3ceb453): LANDOLD.patch passes on 4acdc054, but LANDOLD-current-main.patch on 62680818 is HOLD (31 JS failures, 3 compiler diagnostics, ratchet failures) because SCREENS1 (Workshop/Library on ds/) and GROUP3 landed meanwhile.
Read LANE-DISCIPLINE.md + the ledger + RESULT-LANDOLD.md. Do not redo dispositions.

## INPUTS
- LANE-DISCIPLINE.md
- RESULT-LANDOLD.md
- PROGRESS.md
- notes.md
- LANDOLD-current-main.patch

## STEP 0
- WHY: finished accepted work must reach main (RULE 1) without breaking what just landed.
- SOURCES: skill archhub-prior-art; RESULT-LANDOLD.md (per-patch dispositions + courts); main 62680818 SCREENS1/GROUP3 code (the new owners; adapt the old patches to them, never revert them)
- FIT: rebase onto 62680818. Where SCREENS1 replaced the Workshop board and GROUP3 replaced grouping UI, port the RUNFORK2 / HISTORY-NODE / BOARD-ARCHIVE behaviour onto the NEW owners with ds/ components. If a behaviour is already provided by the new owner, mark it superseded with evidence. Fix the 31 JS failures at their cause; clear the 3 compiler diagnostics (tools/pipeline/strict_check.py --changed); bring the ratchet to PASS (delete replaced code).
- DROPPED: reverting SCREENS1/GROUP3; disabling tests.

## Courts
- strict_check --changed PASS; ratchet PASS; JS affected courts 0 fail; backend 15/15; zero-idle 2/2.

## Finish
LANDOLD.patch against 62680818 + SHA-256; RESULT-LANDOLD.md updated. Commit.
