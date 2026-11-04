# App folder allowlist

Owner: installed first-run code in `01.APP/nodelang/quiet_update.py` (`APP_FOLDER_OWNERS`).

Scope: `%LOCALAPPDATA%/ArchHub` only. The builder inventoried names and source; it never moved or deleted installed state. Source baseline: `539f4c3e8bee7d62b907eb8587e4ddc7a3dfef4c`. This is source-derived ownership, not a claim that every optional feature was exercised on the installed app.

| Root path (descendants stay with their owner) | Owner / read-write reason | Rule |
|---|---|---|
| `.archhub-ready` | installer payload | Current payload / runtime owner |
| `.venv` | installer payload | Current payload / runtime owner |
| `agents` | installed agent work files | Current payload / runtime owner |
| `app` | installer payload | Current payload / runtime owner |
| `ArchHub.bat` | installer payload | Current payload / runtime owner |
| `archhub.ico` | installer payload | Current payload / runtime owner |
| `ArchHub.vbs` | installer payload | Current payload / runtime owner |
| `assistant-hooks.json` | assistant_registration consent | Current payload / runtime owner |
| `assistant-integration.json` | assistant_registration consent | Current payload / runtime owner |
| `AutoCAD` | host_brokers session records | Current payload / runtime owner |
| `BABOOM` | user companion assets | Protected user data or credential custody; not proof of an active reader |
| `baboom-position.json` | baboom_native_runtime window position | Current payload / runtime owner |
| `bin` | colleague_setup._setup_compiler_candidates host compiler discovery | Current payload / runtime owner |
| `bridge` | host_brokers runtime | Current payload / runtime owner |
| `bridges` | installer host adapters | Current payload / runtime owner |
| `browser-session-v1.dpapi` | browser_admission protected session | Current payload / runtime owner |
| `BUILD_ID` | installer payload | Current payload / runtime owner |
| `BUILD_METADATA.json` | installer payload | Current payload / runtime owner |
| `colleague_setup.py` | installer payload | Current payload / runtime owner |
| `custom_nodes` | selfext runtime user mods | Current payload / runtime owner |
| `daily-work` | daily_work_nodes results | Current payload / runtime owner |
| `data` | session_files recent/current metadata | Current payload / runtime owner |
| `deployment-evidence.json` | deployment_evidence installed build provenance | Current payload / runtime owner |
| `docs` | installer payload | Current payload / runtime owner |
| `exports` | user exported files | Protected user data or credential custody; not proof of an active reader |
| `goose` | goose_runtime work files | Current payload / runtime owner |
| `HOST_ARTIFACTS.json` | installer payload | Current payload / runtime owner |
| `keys` | existing credential custody; never cleanup input | Protected user data or credential custody; not proof of an active reader |
| `library` | user imported host connectors | Protected user data or credential custody; not proof of an active reader |
| `licenses` | installer payload | Current payload / runtime owner |
| `logs` | log_rotation / cleanup removal manifest | Current payload / runtime owner |
| `memory` | user knowledge | Protected user data or credential custody; not proof of an active reader |
| `native-launch-configs` | native_agent_session configuration | Current payload / runtime owner |
| `native-workshop` | native_workshop_profile isolated assistant configuration | Current payload / runtime owner |
| `nodelang` | installer payload | Current payload / runtime owner |
| `nograph-http-port` | nograph_server discovery | Current payload / runtime owner |
| `NOTICE` | installer payload | Current payload / runtime owner |
| `packed` | installer payload | Current payload / runtime owner |
| `payload` | host_exec compiled connector payloads | Current payload / runtime owner |
| `personal_brain` | user knowledge | Protected user data or credential custody; not proof of an active reader |
| `private-client-backups` | user client data | Protected user data or credential custody; not proof of an active reader |
| `profile.json` | user profile | Protected user data or credential custody; not proof of an active reader |
| `projects` | user project files | Protected user data or credential custody; not proof of an active reader |
| `relay-descriptor.json` | nograph_server cloud relay | Current payload / runtime owner |
| `renders` | user render outputs | Protected user data or credential custody; not proof of an active reader |
| `requirements.txt` | installer payload | Current payload / runtime owner |
| `Revit` | host_brokers session records | Current payload / runtime owner |
| `rhino.active` | host_brokers | Current payload / runtime owner |
| `runtime` | installer runtimes / runtime_credentials browser session | Current payload / runtime owner |
| `runtime-context` | hook_decision / native_stop_hook | Current payload / runtime owner |
| `runtimes` | daily_work_nodes installed tools | Current payload / runtime owner |
| `session-link` | existing Workshop connection records | Current payload / runtime owner |
| `sessions` | host_brokers / pipeline_engines | Current payload / runtime owner |
| `sessions-files` | legacy Canvas migration; unknown user files retained | Protected user data or credential custody; not proof of an active reader |
| `settings` | nograph_server.JsonFile / settings_owner | Current payload / runtime owner |
| `settings.json` | existing user preferences | Protected user data or credential custody; not proof of an active reader |
| `skills` | user supplied workflows | Protected user data or credential custody; not proof of an active reader |
| `speckle.active` | host_brokers | Current payload / runtime owner |
| `terminal` | terminal_sessions working directory | Current payload / runtime owner |
| `theme.json` | existing user theme | Protected user data or credential custody; not proof of an active reader |
| `tools` | installer payload | Current payload / runtime owner |
| `tray-notice-shown` | window_commands close-to-tray preference | Current payload / runtime owner |
| `unins000.dat` | installer payload | Current payload / runtime owner |
| `unins000.exe` | installer payload | Current payload / runtime owner |
| `updates` | quiet_update release handoff | Current payload / runtime owner |
| `use_software_render` | desktop renderer compatibility | Current payload / runtime owner |
| `web-profile` | nograph_launcher Qt browser profile | Current payload / runtime owner |
| `wheelhouse` | installer payload | Current payload / runtime owner |
| `workflows` | user Canvas documents | Protected user data or credential custody; not proof of an active reader |
| `workshop` | workshop_mailbox / Workshop Session Link | Current payload / runtime owner |

## Traced reads and writes

| Path | Code entry point | Why |
|---|---|---|
| `nodelang/**`, `app/**`, `packed/**`, `tools/**`, `bridges/**`, `runtime/**`, `licenses/**`, `docs/**`, `wheelhouse/**`, root setup/launch/build files | `03.TOOLS/installer/ArchHub.iss` `[Files]`; `01.APP/colleague_setup.py`; `launcher.py` | Installed Python modules, frozen assets, pinned runtimes, bridge adapters, offline setup and build identity. Installer-owned folders remain obvious code/runtime folders; no new launcher or store. |
| `settings/*.json`, `settings/*.sqlite*` | `nograph_server.NoGraphServer.__init__`, `JsonFile.read/write`; `settings_owner.router_settings_path`; `agent_budget`; `brain_files` | Actual page-owner settings, routing/budget and Brain files, kept in place. |
| `workshop/messages.sqlite3` and SQLite sidecars; `workshop/**` | `workshop_mailbox.profile_database`, `History`; `workshop/paths.mjs`, `native.mjs` | One Workshop DB, messages, declarations and native Session Link transport. |
| `native-workshop/**` | `native_workshop_profile.prepare_native_workshop_profile` | Per-session native assistant settings and process cwd. |
| `sessions/**` | `host_brokers.broker_sessions` | Broker session discovery and signed host connection records. |
| `data/sessions/{recent,current}.json`, `data/sessions/locks/**`, temporary `data/sessions/folder-move.json` | `session_files.SessionFiles`; `canvas_documents._lock_path` | Local pointers and shared edit exclusion; not a document store. |
| `logs/launcher.log`, `.1` through `.3`; `logs/updates.log`, `logs/removals.jsonl`, `logs/free-chat-trace.jsonl` | `launcher.py`; `quiet_update.append_update_log`, `finish_app_folder`; `model_router._append_free_chat_trace_line`; `log_rotation.RotatingLog` | Size-capped logs: default 2 MiB per file, three rotated copies. Removal records contain relative path, size and removing/removed status. |
| `logs/cleanup-pending.json`, `_cleanup-staging/**` | `quiet_update.stage_app_folder`, `restore_app_folder`, `finish_app_folder` | Temporary transaction state only. A failed/interrupted boot restores the staged set; healthy boot deletes it without an archive copy. Locked or linked entries stay untouched. |
| `updates/{staged.json,ArchHub-Setup-0.exe,setup.log,update.lock}` | `quiet_update._locked`, `stage_if_newer`, `apply_staged`, `_status` | Existing update handoff and installer integrity/ordering validation; no retired graph snapshot is required. |
| `web-profile/**`, `baboom-position.json`, `tray-notice-shown` | `nograph_launcher.run`; `window_commands.CloseToTray` | Current Qt browser profile, companion position and tray notice. |
| `runtime/browser-session-v1.dpapi`, `runtime-context/**` | `runtime_credentials`; `hook_decision`; `native_stop_hook` | DPAPI browser credentials and native hook context. |
| `goose/**`, `runtimes/**`, `daily-work/**` | `goose_runtime.GooseRuntime`; `daily_work_nodes` | Current agent work and explicitly run tool/result directories. |
| `nograph-http-port`, `relay-descriptor.json` | `nograph_server.start/close`, `ensure_cloud_relay`; `launcher._holder_answers` | Current local discovery and cloud relay state. |

## One Canvas folder

`session_files.sessions_directory()` reads `settings/settings.json:sessionsFolder`, defaulting to `%USERPROFILE%/Documents/ArchHub`. All `.archhub` workflows use that folder, the same Canvas open/edit/save implementation and the same file export/import. There is no `skills_directory()` or separate Skills setting/category. Existing `skill` engine identifiers remain compatible with files already saved by users.

`migrate_sessions()` moves legacy `.archhub` files from `sessions-files` and its `skills` subfolder with readable title filenames, preserving raw bytes and resolving name collisions. Unknown/invalid user files remain protected. The exact founder-identified verification titles are staged as junk. Settings folder changes move the same documents and update recent/current pointers in a journaled transaction. A failed or interrupted folder change restores the previous files and pointers before the next reader selects a folder. Save As chooses any local `.archhub` path.

## Removed inputs and stopped writers

All other root entries are staged, except user `.archhub` documents, credential files, linked paths and data-protected folders. Candidate/live build logs, `*.bak_*`, `_syncrung_backup*`, `_deploy_backup*`, `_config_backup*`, `sessions_backup*`, `.retired-v1-docs`, `.stem_surface_backup`, `authority-recovery-*`, obsolete graph stores and empty retired folders have no current owner and are removal candidates. A directory containing unrecognised Canvas data or credential files is skipped wholesale.

Source search: `candidate-`, `live-*.log`, `bak_` in shipped Python/PowerShell/VBS/installer writers found no current root writer for those historical names. The current installer no longer calls `ArchiveLegacyDocs` or `SweepLegacyV1`, and no longer extracts/runs the closed-profile graph backup before replacing code. Cleanup happens only after first-run health. The current launcher and quit updater no longer select/read legacy graph databases merely to authorize an update.

## Validation and limits

Tests run only against disposable profiles. Actual health uses the HTTP `/api/alive` response, live server thread, parseable settings, selected sessions folder and Workshop SQLite `PRAGMA quick_check`. The cleanup court covers success, failure, interrupted boot, a real Windows sharing violation, junction refusal, new user data appearing after staging, byte-identical migration, in-place migration, folder changes, readable title renames and a forced cross-volume branch with write exclusion.

The product installer has not been built or installed by this lane. Installed root state, release packaging, external host applications and the founder desktop remain unmodified. Protected user data and credentials are explicit exceptions to removal; protection is not represented as an active-code usage claim.

Final scoped run (existing product Python dependencies, bytecode writes disabled; Qt offscreen and an isolated cached headless browser):

```text
42 passed, 2 warnings in 72.58s (0:01:12)
PROFILE-WRITE-GUARD: protected write attempts=0
```

Studio compile:

```json
{"ok":true,"action":"compile","files":40,"output_bytes":1796116,"manifest_sha256":"ae25789242ce2faed50285d87d02244dbcffcb44e12d1e69fcdd2f310bb296bd","babel_version":"7.29.0"}
```

The rendered test serves the actual compiled Studio from NoGraphServer against disposable .archhub files. It opens Library -> Sessions -> the saved document on Canvas and verifies .archhub export content. Folder rollback tests include a pointer-write fault and an interrupted move recovered by the next reader. Provider trace assertions compare emitted steps to the independent fake HTTP requests, so a cold dependency import consuming the existing routing budget does not require an unattempted model to appear in the log.

The exploratory legacy updater run reported `7 failed, 45 passed`; four filename/server/path cases were adapted to current owners. Three assertions against removed private launcher functions remain outside the final scoped run (`test_the_app_has_one_close_owner_and_optional_tray`, `test_the_launcher_keeps_the_one_brain_owner_and_no_retired_daemon`, `test_build22_slow_graph_never_rolls_back_a_booted_studio`). This lane does not claim a full-suite or installer/installed-app PASS. The provider SDK emitted two deprecation warnings in the final run.
