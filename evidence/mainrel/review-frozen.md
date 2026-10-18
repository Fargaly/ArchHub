# MAINREL frozen source review

Independent reviewer: review_mainrel. **Source review: CLEAR** for the final
changes below; no remaining concrete P1/P2 identified. This extends
review-final-source.md at the updated SHA-256 bindings below. No tests, heavy
jobs, product edits, installs or live-profile operations were performed.

| Final change | Source finding |
|---|---|
| Metadata budget | Planned backup bytes now include the existing 64 KiB metadata allowance before byte-budget and free-space admission. |
| Concurrent disk use | After all candidate copies and retained-byte checks, Setup's backup owner rechecks that the backup volume still has at least 25 GiB; failure preserves source and verified copies and refuses success. This is a point-in-time check, not a reservation against future unrelated writes. |
| Selection race | Retention is imported once before the candidate loop; a selected source that disappears now refuses instead of being silently skipped. No empty-loop success is inferred for a vanished selected source. |
| Canonical state directory | Launcher's actual state assignment defaults to `%LOCALAPPDATA%/ArchHub`. Setup `_launcher_state_root`, AutoCAD registration state_root and assistant_registration.install_roots now match it. Each preserves explicit `ARCHHUB_TEST_STATE_DIR`. No legacy state directory is moved or deleted. |
| State-root court source | The added test extracts only the launcher's top-level `state_dir` AST assignment and evaluates that assignment in an isolated environment, then compares actual setup/registration functions for default and explicit-override cases. It does not import or run the desktop launcher. |
| Managed-only connector migration | Current wrapper invokes migrations only for preflight-classified retired entries. Other same-name entries are reported skipped; absent entries are not created. Required retired-migration failures still return nonzero. Ready-marker invalidation and success-only publication remain intact. |

## Acceptance remains separate

This review does not certify the active/earlier pytest result, a built payload,
representative six-million-Cell startup, or a real0400 rollback. Guard 5's built-app
gate and guard 7's isolated real-installer rehearsal remain unproved here.
Final measurements must bind to the frozen source/payload. Existing BOARD is
the retained desktop-off fallback; no new mailbox API ships. New installer
backups share one canonical root with per-source custody children; historical
backup locations remain readable and untouched.

## SHA-256 bindings

| File | SHA-256 |
|---|---|
| colleague_setup.py | 27E5F637090E20EC2FD944A7C65FFF2D9028A089CCCF8C862A4994F0B62BAE0D |
| nodelang/application_recovery_files.py | C571CFA20CEEA69C34D7FBA0539907C32668D4710B60616680F80986A5AB2B71 |
| nodelang/assistant_registration.py | A6ADB0FA9AD8E00143E172E4C354C49CB2E65FF68FED419B5624C59092565801 |
| nodelang/backup_retention.py | BB62C44DEBDB1C35D46FB3E21B161A6DD33AE1BB55E399D3297AA11356ED93AE |
| nodelang/persistence.py | 2858CA64F78074FB269DD85E1D4685197E66E99488C075F4997E4D058AD20C9F |
| nodelang/studio/studio-lm.jsx | F93142719B7AF4F56A0022D2A053FFB57CA26A624DC4EA40EC7F21467C227BA3 |

Model source review is evidence, not a Tier L artifact acceptance verdict.
