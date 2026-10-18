# MAINREL Home fixture review

Independent source review: **CLEAR** for the final test-only fixture correction.
No tests/heavy jobs, product edits, installation or live-profile actions run.

The changed fixture adds `authorization:{subject:'owner-a',session}` to its
`workshop_scope`, using exactly the same subject/session as the fixture's
admitted topology. Production `activeAuthorization` selects the explicit
canvas authorization when known; its topology fallback requires matching
application graph/scope. This fixture uses `application-a` versus `graph-a`,
so the topology fallback cannot establish its active canvas identity. Supplying
the scope's explicit identity makes the fixture represent an admitted request;
it does not relax production authorization checks.

All existing request, idempotency, receipt rejection, double-submit and stale
authorization assertions remain. `identity('session-b')` now rotates both
fixture projections together, retaining the authorization-change refusal court.
The previously reviewed tab/scope assertions also remain. No existing behavior
test/assertion was removed or weakened by this fixture correction.

SHA-256 bindings:

| File | SHA-256 |
|---|---|
| tests_js/studio_home_session.test.cjs | D3BE016705849A90F8BA7C198B23B3308C9C46949EB59E0F2AD2B7B903CB2450 |
| nodelang/studio/studio-existing-workshop.js | 54E66F71BD173E26593CBD08657A91430AEF575AA1CECFBA75A094465E569C94 |

Reported timings/build results and the active three-file court were not run or
independently verified by this reviewer. Built-app/real0400 acceptance remains
separate from this source review.
