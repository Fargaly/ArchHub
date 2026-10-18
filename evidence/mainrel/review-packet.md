# MAINREL packet/report review

Independent reviewer: review_mainrel. Read-only source/evidence checks only;
no courts, heavy jobs, compiler polling, product edits or installation.
**No P1 release/installation overclaim identified. Report corrections below.**

## Packet binding

- MAINREL.patch: **80072 bytes**, SHA-256
  `F996459293147B1E253BC1BA87A5624BE21FE4DED0B7D571B9BD20410D93D42C`.
- Patch parses as 23 changed paths using `git apply --numstat`; paths match the
  supplied patch-paths inventory. This is not a clean-apply-to-current-main test.
- Read-back of frozen-source.json: **23 paths, 0 SHA-256 mismatches** against
  current disk. Existing intent records are retained; the diff adds MAINREL.
- Original claimed lazy-boot harness is absent from the main patch. Its repair
  remains a separately hashed proposal. Restored mail API/baseline AGENTLINK2
  files are also absent from the patch.

## Report issues / corrections

| Priority | Current RESULT claim | Required precision |
|---|---|---|
| P2 | Guard 5 row says nine mounted cases await test-file repair, while the final receipt records 138 PASS / 2 FAIL on the temporary repaired harness. | Put the current two remaining assertions in the guard row: entire admitted catalogue overlay, and rail aria-current `page` versus expected `true`. Separately state the original claimed extraction harness still has nine failures and was not edited. Do not characterize both remaining assertions as merely a boundary-repair blocker. |
| P2 | Guard 2 calls the 4.34308580000652 s value “startup”. | Name it `persistence.prepare_application_database` migration/adoption elapsed time. The driver times that API, not desktop launch/render. This supports the bounded synthetic migration criterion; it does not measure complete app startup or six-million-Cell semantics. |
| P2 | Initial process-wide isolation gap is documented in the packet's FAILURE_LOG addition but omitted from RESULT's limitations. | Include one explicit result limitation: the first broad targeted batch lacked established process-wide profile isolation; absence of live-profile effects was not independently proved. Later isolated courts do not retroactively establish that earlier absence. This need not imply an observed live-profile write. |

## Evidence/claim boundaries checked

| Area | Review result |
|---|---|
| Installation | RESULT leads with installation HOLD and says the real0400 executable was hashed, never run. The exact real0400/main/real0400 reopening rehearsal remains blocked. |
| Large fixture | big-measurement.json explicitly labels a valid small graph plus SQLite padding; 8937168896 bytes, backup 227.70879669999704 s, migration 4.34308580000652 s. Wrong-candidate 0.7602302999584936 s result is rejected. No representative six-million-Cell claim is made. |
| Inno | local-checks.txt contains `Successful compile (2.360 sec)` and names MAINREL-code-only-NOT-A-RELEASE.exe. Driver extracts the production [Code] into a small compile fixture; it is not a full release build or executed progress wizard. RESULT makes that distinction. |
| Targeted courts | guards-final43PASS, shows-as1PASS, updater22PASS, zero-idle2PASS and transport87PASS receipts exist. The report also retains failed/incomplete earlier runs and does not waive the remaining Python/JS failures. No all-green statement is appropriate. |
| Rendered candidate | js-proposed-harness.txt reports 140 tests,138 pass,2 fail,duration_ms20996.2785, with the exact two assertions above. This is a temporary JSDOM harness/source-components result; it is not the built-main gate. |
| GRANTRECEIPT | RESULT identifies installation status as BOARD-reported and explicitly says live installation was not inspected. Its reconciliation is a coordinator/integrator requirement, not a verified installed fact. |
| Compiler | strict-changed.txt currently contains only `STAGED_PATH_COUNT=84`. Compiler completion, strict PASS and final metadata/index/commit cleanliness are not certified by this review. They must be filled from actual final receipts. |
| Guard 8 | New copies have one root with per-source child custody; historical founder custody is not claimed consolidated or deleted. Final installed behavior remains separate. |

This review supports packaging the source as a **HOLD repair packet**, subject
to the report precisions and actual final compiler/commit receipts. It does not
authorize or certify promotion, built-main acceptance, real0400 rehearsal or installation.

## Current binding and report closure

The packet was refreshed after replacing the connector test's imported fixture
alias with standard `pytest_plugins` registration; existing behavior assertions
remain. No product-source change is claimed from that test-only correction.

- Current MAINREL.patch: **80063 bytes**, SHA-256
  `473711F8819EE15DE11C942904DAC98410E1692EC2DF38882A217A24E11462DA`.
- Refreshed frozen-source.json: **23 paths, 0 SHA-256 mismatches** on read-back.
- guards-final-plugin.txt records `43 passed, 1 warning in 40.05s`.
- All three P2 report precision items above are now closed: guard 5 distinguishes
  original harness9RED from proposed harness138PASS/2actual assertion failures;
  guard 2 names `persistence.prepare_application_database` elapsed migration,
  not complete desktop boot; RESULT explicitly discloses the initial inherited
  process-profile environment and unproved absence of live-profile effects.

**Compiler HOLD remains active.** strict-changed.txt ends with
`ACOMPILER FAIL` and `STRICT_SECONDS=143.1046594`; read-back counted **9 E0007**
diagnostics. The initial authored ledger/fixture/parser diagnostics are absent
from that final receipt; remaining diagnostics concern measurement JSON and
the measurement driver's deadline/result literals. Compiler-owner diagnosis is
not a waiver or a PASS. RESULT's pending-replay placeholder still needs the
completed receipt/status inserted before final handoff.

The two rendered Home assertion failures, built-main payload gate and isolated
real0400 rollback remain open. Final apply/commit/cleanup receipts were not
certified by this read-only update. No tests, compiler runs, installations or
product edits were performed by this reviewer.
