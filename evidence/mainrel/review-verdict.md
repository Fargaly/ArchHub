# MAINREL source-review verdict

Reviewer: review_mainrel (independent of builder). Observed HEAD:
`bd8f1ed24956f34d906eb60bd1dd5181ec67ee5a`, plus working-tree edits against
`d89a50fd2304ea4cbda75e1313c08ed187404f2f`.
Source verdict: CHANGES REQUIRED at the blob identities below.
This supersedes prior source-review findings where explicitly resolved below.

## Remaining concrete issues

| Priority | Location | Trigger, effect, correction |
|---|---|---|
| P1 | `colleague_setup.py:902-921`; `installer/ArchHub.bat:19-24`; `installer/ArchHub.vbs:81` | Setup publishes `.archhub-ready` before required connector migration. A refused migration returns 8 but leaves that marker valid. Next launch's `--check-ready` returns success and skips the migration, despite the required guard failing. Run required migration before `_write_ready`, and ensure an already-present same-build marker is invalidated when required migration fails. Court failure followed by a second real `--check-ready`. |
| P2 | `nodelang/native_agent_mcp.py:269,287` | A process exit/disk error during JSONL append can leave a partial final record. Every later read parses all nonblank lines with `json.loads`, so one interrupted unacknowledged send makes all earlier acknowledged messages unavailable. Preserve earlier valid records and explicitly quarantine/refuse the incomplete tail under the same lock; never silently treat it as delivered. A crash-tail fixture and subsequent read/send should exercise this. |
| P2 | `nodelang/native_agent_mcp.py:252-255` | `_require_plain` checks reparse points, but accepts hardlinks. An existing hardlinked `agent-mail-offline.jsonl` is appended without an `st_nlink == 1` check, potentially modifying another same-user file. Match `session_link_config.write_with_backup`'s single-link safeguard and validate the opened handle before append. No adversarial process is needed for this path collision. |

## Corrections verified in source

| Earlier finding | Current source |
|---|---|
| Unbound graph/file cursors | Public read accepts explicit `auto`, `workshop`, `offline-file`; nonzero auto cursor refuses; explicit offline read remains available when desktop returns; workshop response includes transport. |
| MachineNotSent hides verification failure | Cause kinds other than stopped/dead/released are re-raised; explicit workshop requests do not fall back; generic uncertain transport errors remain unreplayed. |
| File crosses configured cap | Encoded record length is checked against projected total before writing. Normal accepted writes no longer create an over-budget unreadable file. |
| Custom same-name config fails install | Preflight ownership classifies unrelated entries; their conflict becomes `skipped_unmanaged`. Managed migration failures still return nonzero. |
| Missing venv + unchecked new-connections option | colleague_setup now calls managed migrations regardless of the optional new-connection flow, after environment creation. The readiness ordering issue above remains. |
| Unconditional CLI success | Required failure states return nonzero. |

## Guard limits, separate from source defects

- Guard 8 establishes one automatic backup owner: the installer. It does **not**
  establish one physical backup root across all candidate journals:
  `application_recovery_files.py:215` still uses `source.parent / 'backups'`.
  If the literal requirement is globally one directory, it is unfulfilled.
  Changing that parent alone is unsafe because latest/pin selection also needs
  source identity for same-named journals. Preserve legacy custody during any consolidation.
- Guard 5 requires green evidence on the built app; guard 7 requires the real
  0400 installer rollback rehearsal. Neither is certified by this source review.
  Their artifact/isolation blockers do not prevent a source-review CLEAR once
  the concrete defects above are corrected.
- No new heavy jobs, tests, installer runs, live profiles or product edits were
  performed by this reviewer. Active builder tests are not claimed as review evidence.

## Reviewed Git blobs

| File | Blob |
|---|---|
| nodelang/native_agent_mcp.py | 21220293623226f3e1707488db204a91b3db6575 |
| nodelang/assistant_registration.py | 345b59549c941f40f3a1eaaee08931d7a26b5211 |
| colleague_setup.py | fbed8ad8518d4a8f6fb06f0c9057c8b994958157 |
