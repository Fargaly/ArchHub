# MAINREL follow-up independent source review

Reviewer: review_mainrel; base `d89a50fd2304ea4cbda75e1313c08ed187404f2f`.
Observed HEAD `bd8f1ed24956f34d906eb60bd1dd5181ec67ee5a`, with uncommitted
additions. Source review only; no heavy jobs, installation or live-profile writes.
This report supersedes review.md for the additions named below, not artifact acceptance.

## Findings

| Priority | Source | Concrete failure and smallest correction |
|---|---|---|
| P1 | `native_agent_mcp.py:213-228,301` | The public `read` takes only numeric `since`; `_mailbox_call` silently switches between graph and file sequences when the desktop starts/stops. Offline messages become inaccessible through the tool once the app runs, and carrying either cursor into the other transport skips unrelated messages. `transport` in the response cannot prevent the next request switching. Bind read cursors to an explicitly selectable transport and retain access to the offline backlog while online, or retain the existing BOARD fallback instead of introducing this automatic second mailbox. Court both transition directions with nonmatching sequence numbers. |
| P1 | `installer/ArchHub.iss:451`; `colleague_setup.py:781-786` | A valid legacy connector passes preflight, but migration is skipped when `{app}\\.venv\\Scripts\\python.exe` does not exist. If `connectassistants` is unticked, the consent marker is deleted and first-boot setup returns without migration too. Thus a fresh/repaired install can leave a managed entry pointing at the deleted module. Run managed-entry migration after environment creation independently of permission to connect new assistants, with a pending marker or an unconditional managed-only setup step. Court missing venv + legacy config + unchecked checkbox. |
| P2 | `assistant_registration.py:680-684,803-804` | A custom same-name entry that does not mention the retired module passes preflight. Postinstall returns `conflict`, now causing exit 1 and an installer exception after replacement. Preserve/report unrelated custom entries as skipped; reserve failure for actual required migrations, or reject all such conflicts explicitly before replacement. |
| P2 | `native_agent_mcp.py:252-273` | The 16 MiB check tests current size, then accepts a write that crosses it. Subsequent reads also fail this check, making the accepted backlog unreadable through the tool. Check projected encoded size before append and continue bounded reads when sending is refused. A torn trailing JSON line also disables all reads; establish a conservative recovery rule that retains valid earlier records. |
| P2 | `native_agent_mcp.py:223`; `application_machine_transport.py:2038-2039` | `MachineNotSent` wraps every `verify_active_runtime` resolution error, including `legacy`, `pid-reused`, `generation-unverifiable`, and `superseded`. Catching it unconditionally bypasses the new stopped/dead/released whitelist. Inspect/preserve its cause before fallback; only pipe-not-sent and explicitly accepted desktop-off causes should choose the file route. This does not replay an uncertain request, but does hide non-offline owner-verification failures. |

## Source checks and limits

| Area | Observation |
|---|---|
| Prior P1 | CLI now returns nonzero for `migration_unconfirmed` and `config_unreadable`. The original unconditional-success finding is corrected in source. The newly broad conflict handling is separately listed above. |
| Preflight package | Three extracted modules plus an empty `nodelang/__init__.py` cover the observed top-level imports; preflight avoids calling `managed_entry`, so it does not accidentally bind install roots to the temporary extraction. `-E -s -B -m` uses that package's working directory. File-copy return values are unchecked, but missing package/imports should make preflight fail closed. Real Setup compilation/execution remains unproved. |
| Old runpy AST | Recognizes either absolute inline `sys.path.insert(0, PATH)` or `sys.argv.pop(1)` plus absolute trailing path; accepts import ordering/formatting differences; compares the final retired-module `run_module` AST and rejects extra statements/keywords. It never executes config code. File size is bounded to 4 MiB. The exact live founder config bytes were not read by this reviewer. |
| Actual install roots/custom environment | Postinstall module execution uses `{app}` as cwd and `install_roots` derives installation from its loaded file, so `/DIR` does not leave the extracted temp root in new entries. Existing `CODEX_HOME` is honored; Gemini remains `%USERPROFILE%/.gemini`. First-boot state honors `ARCHHUB_TEST_STATE_DIR`/`LOCALAPPDATA`. None of these environment substitutions isolates Inno KnownFolders/HKCU; real installer rehearsal still requires a VM/sandbox. |
| Locking | File cursor/append is inside a Windows byte-lock try/finally, with fsync before successful send return. Initial blank-line creation happens before locking; harmless duplicate blanks are ignored. No multiprocess/crash court was run. `_require_plain` rejects ancestor reparse points, but new mailbox open lacks a single-hardlink check and handle-identity revalidation; mirror the existing config writer's single-link protection before append. |
| Authority/security | Offline records explicitly carry `authority='none'` and successful send says `delivered=False`. Uncertain generic `MachineTransportError` is not replayed. The file is same-user, unsigned collaboration text and must never serve as Work/approval evidence. Sender metadata/environment are not new authorization. |
| Bounds | Current file read is capped at 16 MiB before parsing, with at most 200 returned messages, text <=12000 characters and target <=256 characters. Persisted records/sender values are not schema-validated; file cap is not a projected-byte cap. |
| One backup directory | Automatic app recovery copy is retired; one automatic owner is established. `application_recovery_files.py:215` still creates a backup root per source parent. If guard 8 means a single physical custody root, it remains unmet. A canonical `{profile}/ArchHub/backups` root also needs a source-relative identity in receipts and filtering of latest/pin selection by that identity; merely changing `parent` would mix same-named authority journals. Preserve legacy custody/readability while consolidating; do not delete old copies speculatively. |

## Reviewed blob identities

| File | Git blob |
|---|---|
| installer/ArchHub.iss | d422c836b4b57d8bbbb51f48c26dc30f516926e5 |
| nodelang/assistant_registration.py | 28f48bd48e13e20248e6fa29ed29533b9fe56694 |
| nodelang/native_agent_mcp.py | 4df2b938743e5b20f6dc3ca1dd48ce8af2ba54b5 |

Targeted behavior tests, multiprocess lock/crash tests, final ISCC compile,
built-app gate, measured 8.3 GiB migration and real0400 rollback remain separate
integration evidence. No acceptance verdict is issued here.
