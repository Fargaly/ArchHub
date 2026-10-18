# MAINREL independent source review

Reviewer: review_mainrel (not the builder). Scope: current source diff against
`d89a50fd2304ea4cbda75e1313c08ed187404f2f`; observed HEAD
`bd8f1ed24956f34d906eb60bd1dd5181ec67ee5a` with uncommitted source edits.
This is source-review evidence, not a Tier L acceptance verdict.

## Findings

| Priority | Location | Finding and required correction |
|---|---|---|
| P1 | `nodelang/assistant_registration.py:742-745`; `installer/ArchHub.iss:447-453` | `migrate-connectors` always returns 0 after printing result states. `migrate_codex` can return `migration_unconfirmed` after a refused concurrent-write check, failed rewrite verification or readback. It also returns `config_unreadable` instead of raising. Setup sees success and finishes despite leaving the required connector on the deleted module. Return nonzero for required migration failures and preserve/report each failure; test the CLI exit status and Setup caller, including a `migration_unconfirmed` result. Unknown/user-owned conflicting entries must remain untouched and be reported distinctly. |

## Checked source routes

| Area | Observation | Remaining limit |
|---|---|---|
| Disk budget | Before creating a copy stage, `application_recovery_files.py:269-277` checks retained closed receipts plus planned bytes against the configured budget, then refuses if the source volume would retain less than 25 GiB. Source journals are not deleted by this check. | No actual 8 GB backup or low-space installer run performed by this reviewer. Budget/freespace refusal occurs after hashing and logical journal comparison; first-time refusal can therefore still incur a long read. |
| Progress API | `OnBackupLog` has the documented `TOnLog` signature; `ExecAndLogOutput` uses `ewWaitUntilTerminated`. Marquee creation and `Animate` use match Inno documentation. Copy loops report bytes at 0.5 s intervals. | This is API/source conformance, not an ISCC compile result or visible UI proof. Long hash/readback/row-identity phases provide a phase label, not byte/row updates. |
| Single automatic backup owner | Launcher close/update flow no longer requests `server.close(recovery_directory=...)` or calls `_prune_backups`. New marker format 2 carries source identities; old format 1 remains readable. Installer preserves before copying installed files. | Manual recovery APIs remain, intentionally. Installer still derives a `backups` directory per source parent; this review does not establish the literal one-directory requirement across multiple legacy profiles/generations. Existing backup directories are not consolidated by this patch. |
| Connector preservation | Gemini changes only `mcpServers[SERVER_NAME]`, uses bounded reads, expected SHA, atomic write/readback and a DPAPI-protected prior-file backup. Codex uses existing semantic preservation checks. | Connector migration is at `ssPostInstall`, after payload replacement/deletion; a failure there needs real-installer rollback proof. Setup's “prior settings were kept” message is not independently established for a partial two-client migration. |
| Chat | Adopted workshop initialization handles deferred canvas and obtains live authorization. The callback maps the application graph/scope onto an existing visible canvas tab before opening it. | Mounted source tests and a built-payload New chat path remain required; this review does not replace them. |
| shows_as | Adopted parser accepts only optional `Screen`, `Tray`, `Hidden`; other unknown keys remain rejected. | Transport behavioral court remains builder/integrator evidence. |
| Mail fallback | No diff removes the shared BOARD fallback. | This patch supplies no desktop-off mailbox implementation; retain BOARD until that route is measured. |

## Snapshot bindings

Git blob identities at review time:

| File | Blob |
|---|---|
| installer/ArchHub.iss | db99e5451df3425934406d599b47dedb1a131eb1 |
| nodelang/application_recovery_files.py | aedf25f66eba3122adf7d086e19db8a3911032cf |
| nodelang/application_update_recovery.py | 990f6e10b445bea287257b12f39c2f56d11d2d09 |
| launch_archhub_test.py | b5a1d2114fa44154be333c93b3512b58c6f4c327 |
| nodelang/assistant_registration.py | 25177e4d32e34c0e5a91ade8ee969a384044303f |
| nodelang/studio/studio-lm.jsx | cf18178bfdd481759a1e9df0fde8f9a3e206e62b |

## Safe real-installer isolation

Do not run the real 0400 installer with environment-variable redirection alone:
Inno resolves `{localappdata}` and `{userappdata}` via Windows KnownFolders and
writes the real user's uninstall registry/tasks/registrations. `/DIR` changes
the payload directory, not all those effects. A hidden desktop isolates UI only.

Use a disposable Windows VM with its own user hive/KnownFolders, no host profile
mapping and a snapshot. Install the exact hashed 0400 package there, seed only
the isolated fixture, install main, then reinstall the same 0400 and open its
journal. A sandbox with equivalent persistent-within-session isolation could
also work. `Get-Command WindowsSandbox.exe,vmrun.exe,VBoxManage.exe,Get-VM`
returned no available commands in this session; no usable isolation host was
established. Do not infer that none exists elsewhere.

No heavy jobs, installation, live profile writes or source edits were performed.

API references checked live:
- https://jrsoftware.org/ishelp/topic_isxfunc_execandlogoutput.htm
- https://jrsoftware.org/ishelp/topic_isxfunc_createoutputmarqueeprogresspage.htm
