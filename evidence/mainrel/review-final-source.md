# MAINREL final source review

Reviewer: review_mainrel, independent of builder. Base:
`d89a50fd2304ea4cbda75e1313c08ed187404f2f`.
**Source review: CLEAR for the final checkpoint additions reviewed below.**
No remaining concrete P1/P2 was identified in those additions. This supersedes
the earlier source findings; it is not a test, built-app or installation verdict.

| Final change | Source verification |
|---|---|
| Desktop-off fallback simplification | `git diff d89a50fd --quiet -- nodelang/native_agent_mcp.py tests/test_agentlink2.py` returned exit 0. The extra mailbox/cursor API is gone; existing BOARD is retained under PREMORTEM-B's explicit allowance. Earlier offline-file API findings are therefore withdrawn from the shipping scope. No baseline behavior test was removed by this simplification. |
| Required migration/readiness | colleague_setup invalidates even an existing same-build ready marker inside the required migration try; migration failure returns 8; `_write_ready` follows successful migration. The reviewed next-launch bypass is closed in source. A targeted existing-marker success/failure test is written, not executed by this reviewer. |
| Single backup container | `installer_backup_directory(profile, source)` derives `{profile}/ArchHub/backups/journal-<full source-relative SHA256>`. All new candidate custody is beneath that root; per-source children distinguish same-named authority journals. New receipts carry `source_relative_path`. Container-wide byte inventory is checked before each copy and after completion. Historical backup locations are preserved, not silently moved/deleted. |
| Startup locator compatibility | persistence searches the new derived custody directory first, then the existing `source.parent/backups` and `root/backups` fallbacks. Existing receipt identity, file-size/hardlink, expected-name and journal-head checks remain. New receipt metadata does not invalidate old readable receipts. Actual startup/rollback measurements remain separate. |
| Installer-only marker 2 | protected_update_backups accepts only integer format 2 with the exact installer owner/pending-state recovery object, returning no protected app-copy path. Malformed format 2 and unknown explicit formats refuse; format 1 and older absent-format path receipts retain their existing behavior. The source search found no other production consumer still indexing the new marker's absent recovery.path. |
| New chat tab/scope | Tab selection and workspaceSelection.scope[0] both use `graphTab.id`; this agrees with viewScope's `session.id` and addresses FOUNDERGATE's reset-to-canvas finding. Scope stamp assertions were added. Built/rendered New chat evidence remains required. |

## Limits and required acceptance evidence

- No tests or heavy jobs were run by this reviewer. The builder's active broad
  pytest was reported RED from earlier bytes; no green result is inferred.
- Guard 5 still needs the release gate green on the built app.
- Guard 7 still needs the exact real0400/main/real0400 isolated installer rehearsal.
- Guard 8 now has one canonical root for **new installer backups**, containing
  per-source child custody. Existing legacy custody directories remain for safe
  compatibility. Do not claim historical directory consolidation or deletion.
- Guard 2 and all time/disk claims need measurements bound to the final source
  and resulting payload; earlier fixtures/locations are not automatically final proof.
- The installer/connector/backup changes remain Tier L and need an independent
  artifact-bound court; this model review is source evidence only.

## Reviewed SHA-256 bindings

| File | SHA-256 |
|---|---|
| colleague_setup.py | A5B2DDB887535714749D75E7A74A05E3D5F248CE1E545DEF83C00A1AF55C9C86 |
| nodelang/application_recovery_files.py | 17F3A088B86A0CE0218FCB4A4B06DFB8E19E2E9D1535164E38AA57AD3A642D58 |
| nodelang/backup_retention.py | BB62C44DEBDB1C35D46FB3E21B161A6DD33AE1BB55E399D3297AA11356ED93AE |
| nodelang/persistence.py | 2858CA64F78074FB269DD85E1D4685197E66E99488C075F4997E4D058AD20C9F |
| nodelang/studio/studio-lm.jsx | F93142719B7AF4F56A0022D2A053FFB57CA26A624DC4EA40EC7F21467C227BA3 |
| nodelang/native_agent_mcp.py (restored baseline) | 5509F93A6779FA872946C7D8B74726F9E5BBF7ECC2DFC90DC790A2C0D021A127 |
| tests/test_agentlink2.py (restored baseline) | 76A46E4FF43E8C19B09D3FAE3E7E6A5C6D629496FFF2447D007F44B4A3EF2288 |

No product edits, installs, live profiles, or heavy jobs were performed.
