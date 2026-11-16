# 02.TESTS

Targeted product and host courts.

## Baseline 60dc0f8e — 2026-11-16

Branch-only baseline investigation. No push, installation, release, deployment, user screen, live host model, or live application profile was used.

The original release selection is the coordinator script's 11 fixed arguments plus 42 existing Python files changed from f222fc38 to 60dc0f8e: 53 arguments, including duplicates. Seven batches used the canonical run-heavy.ps1. Get-CimInstance Win32_Process and C: free space were checked before each run; each batch waited while another pytest/cargo process existed. Every test job ran BelowNormal. The modified compiler file was added to the final after-batch.

Python: 3.14.3; pytest: 9.0.3. Studio was compiled from unchanged product sources before the baseline. The Python entry wrapper isolated USERPROFILE/HOME/LOCALAPPDATA/APPDATA before collection and redirected profile-discovery registry queries to disposable state, so the existing snapshot code did not read live profiles. Existing host and secret-store fixtures remained active.

The reported 14 design-board failures were not reproduced: the unchanged-main designbuild boards and appearance-owner check passed. These tests do not read the designer's WIP folder. The separate legacy designsplit proof did read WIP and now uses the frozen reference setting.

### Verbatim summaries

| Batch | Before | After |
|---|---|---|
| 0 | `5 failed, 121 passed, 1 warning in 166.76s (0:02:46)` | `126 passed, 1 warning in 211.81s (0:03:31)` |
| 8 | `7 failed, 106 passed, 1 warning in 160.16s (0:02:40)` | `113 passed, 1 warning in 229.99s (0:03:49)` |
| 16 | `7 failed, 180 passed, 1 warning, 10 errors in 52.70s` | `197 passed, 1 warning in 82.10s (0:01:22)` |
| 24 | `2 failed, 123 passed, 1 warning in 46.38s` | `125 passed, 1 warning in 38.47s` |
| 32 | `17 failed, 168 passed, 1 warning in 109.97s (0:01:49)` | `6 failed, 179 passed, 1 warning in 121.02s (0:02:01)` |
| 40 | `1 failed, 154 passed, 1 skipped, 1 warning in 104.70s (0:01:44)` | `155 passed, 1 skipped, 1 warning in 91.74s (0:01:31)` |
| 48 | `1 failed, 64 passed, 1 warning in 133.56s (0:02:13)` | `3 failed, 144 passed, 3 skipped, 1 warning in 171.83s (0:02:51)` |

Supplemental final reruns close the six missing-Cedar failures and the three compiler-fixture failures visible in the intermediate after summaries. The added classifier regression is included in the final compiler-file result.

| Check | Verbatim final summary |
|---|---|
| Real policy/scratch module after installing the declared Cedar dependency | `28 passed, 1 warning in 3.39s` |
| Complete compiler test file | `83 passed, 3 skipped, 1 warning in 51.53s` |
| Explicit fd-capture reproduction | `1 failed, 1 passed in 0.13s` |
| Explicit sys-capture comparison | `2 passed in 0.07s` |

The fd probe measured native stdin `valid=0 error=6`; the sys probe measured `valid=1 error=0`. Assertions, skip conditions, and xfail conditions were not removed or relaxed. Existing skips remain visible: one absent pinned native driver and three coordinator-supplied compiler/artifact boundaries.

### Every original failing Python test

Repeated arguments are listed once below. The ten setup errors belong to test_baboom_site_fit.py. All listed Python failures have passing batch or focused-rerun evidence.

| Test | Original error, one line | Class | Repair / final evidence |
|---|---|---|---|
| `tests/test_agentcanvas.py::test_rendered_agents_and_task_steps` | WinError 6 / WinError 50 while duplicating inherited native stdin | b | Default pytest capture=sys; affected after batches passed |
| `tests/test_agentwork.py::test_rendered_agentwork` | WinError 6 / WinError 50 while duplicating inherited native stdin | b | Default pytest capture=sys; affected after batches passed |
| `tests/test_preflight_imports.py::test_generated_extraction_imports_every_preflight_entry_in_isolation` | WinError 6 / WinError 50 while duplicating inherited native stdin | b | Default pytest capture=sys; affected after batches passed |
| `tests/test_preflight_imports.py::test_generated_inno_includes_compile` | WinError 6 / WinError 50 while duplicating inherited native stdin | b | Default pytest capture=sys; affected after batches passed |
| `tests/test_state_isolation.py::test_child_with_explicit_environment_keeps_marker` | WinError 6 / WinError 50 while duplicating inherited native stdin | b | Default pytest capture=sys; affected after batches passed |
| `tests/test_state_isolation.py::test_installed_guard_refuses_mixed_case_environment_root` | WinError 6 / WinError 50 while duplicating inherited native stdin | b | Default pytest capture=sys; affected after batches passed |
| `tests/test_state_isolation.py::test_state_override_isolates_owners` | WinError 6 / WinError 50 while duplicating inherited native stdin | b | Default pytest capture=sys; affected after batches passed |
| `tests/test_task_session_roundtrip.py::test_rendered_checkpoint_and_width` | WinError 6 / WinError 50 while duplicating inherited native stdin | b | Default pytest capture=sys; affected after batches passed |
| `tests_replica/test_app_folder_tidy.py::test_linked_staging_is_refused_without_touching_target` | WinError 6 / WinError 50 while duplicating inherited native stdin | b | Default pytest capture=sys; affected after batches passed |
| `tests_replica/test_app_folder_tidy.py::test_rendered_library_opens_the_real_session_and_exports_archhub` | WinError 6 / WinError 50 while duplicating inherited native stdin | b | Default pytest capture=sys; affected after batches passed |
| `tests_replica/test_baboom_native_runtime.py::test_second_launch_opens_existing_companion_and_plain_launch_opens_home` | WinError 6 / WinError 50 while duplicating inherited native stdin | b | Default pytest capture=sys; affected after batches passed |
| `tests_replica/test_baboom_native_runtime.py::test_task_callback_focuses_same_window_and_dispatches_one_id` | WinError 6 / WinError 50 while duplicating inherited native stdin | b | Default pytest capture=sys; affected after batches passed |
| `tests_replica/test_baboom_persona_standard_reactions.py::test_release_admits_the_persona_without_widening_json_admission` | WinError 6 / WinError 50 while duplicating inherited native stdin | b | Default pytest capture=sys; affected after batches passed |
| `tests_replica/test_colleague_install.py::test_window_icon_is_the_one_the_installer_ships` | ModuleNotFoundError: PyQt6.QtGui | b | Keep the interpreter user-package base when isolating profiles; after batch 24 passed |
| `tests_replica/test_file_path_links.py::test_file_path_links_compiled_studio` | ERR_MODULE_NOT_FOUND: playwright (ES module resolution) | b | Provide lane-local node_modules resolution to the existing pinned dependency tree; affected after batches passed |
| `tests_replica/test_fresh_machine_host_brokers.py::test_reload_hands_the_loader_the_bytes_it_hashed_and_pins_every_dependency` | WinError 6 / WinError 50 while duplicating inherited native stdin | b | Default pytest capture=sys; affected after batches passed |
| `tests_replica/test_fresh_machine_host_brokers.py::test_revit_reload_loads_only_the_installed_core_matching_its_reviewed_pin` | WinError 6 / WinError 50 while duplicating inherited native stdin | b | Default pytest capture=sys; affected after batches passed |
| `tests_replica/test_fresh_machine_host_brokers.py::test_the_release_check_fails_when_any_shipped_year_is_unreviewed` | WinError 6 / WinError 50 while duplicating inherited native stdin | b | Default pytest capture=sys; affected after batches passed |
| `tests_replica/test_fresh_machine_host_brokers.py::test_the_release_check_refuses_a_review_that_does_not_cover_a_shipped_host` | WinError 6 / WinError 50 while duplicating inherited native stdin | b | Default pytest capture=sys; affected after batches passed |
| `tests_replica/test_fresh_machine_host_brokers.py::test_uninstall_never_follows_a_junction_inside_the_bundle` | WinError 6 / WinError 50 while duplicating inherited native stdin | b | Default pytest capture=sys; affected after batches passed |
| `tests_replica/test_fresh_machine_host_brokers.py::test_uninstall_removes_only_the_autocad_files_this_install_placed` | WinError 6 / WinError 50 while duplicating inherited native stdin | b | Default pytest capture=sys; affected after batches passed |
| `tests_replica/test_graphout.py::test_boot_entries_import_no_retired_modules[arguments0]` | WinError 6 / WinError 50 while duplicating inherited native stdin | b | Default pytest capture=sys; affected after batches passed |
| `tests_replica/test_graphout.py::test_boot_entries_import_no_retired_modules[arguments1]` | WinError 6 / WinError 50 while duplicating inherited native stdin | b | Default pytest capture=sys; affected after batches passed |
| `tests_replica/test_graphout.py::test_release_tree_has_no_retired_runtime` | WinError 6 / WinError 50 while duplicating inherited native stdin | b | Default pytest capture=sys; affected after batches passed |
| `tests_replica/test_guard_own_scratch.py::test_changed_scratch_invalidates_trace_without_changing_generic_temp_policy[False]` | policy scanner: 'unavailable' != 'ok' | b | Install already-pinned cedarpy 4.12.2; full module 28 passed |
| `tests_replica/test_guard_own_scratch.py::test_changed_scratch_invalidates_trace_without_changing_generic_temp_policy[True]` | policy scanner: 'unavailable' != 'ok' | b | Install already-pinned cedarpy 4.12.2; full module 28 passed |
| `tests_replica/test_guard_own_scratch.py::test_forged_transcript_cannot_authorize_workspace_file` | policy scanner: 'unavailable' != 'ok' | b | Install already-pinned cedarpy 4.12.2; full module 28 passed |
| `tests_replica/test_guard_own_scratch.py::test_nested_junction_is_not_a_trace_exception_but_lane_cleanup_is_allowed` | policy scanner: 'unavailable' != 'ok' | b | Install already-pinned cedarpy 4.12.2; full module 28 passed |
| `tests_replica/test_guard_own_scratch.py::test_shared_and_ordinary_temp_are_not_trace_exceptions[lane-shared]` | policy scanner: 'unavailable' != 'ok' | b | Install already-pinned cedarpy 4.12.2; full module 28 passed |
| `tests_replica/test_guard_own_scratch.py::test_shared_and_ordinary_temp_are_not_trace_exceptions[shared-build]` | policy scanner: 'unavailable' != 'ok' | b | Install already-pinned cedarpy 4.12.2; full module 28 passed |
| `tests_replica/test_multidelete.py::test_multidelete_one_rendered_undo` | WinError 6 / WinError 50 while duplicating inherited native stdin | b | Default pytest capture=sys; affected after batches passed |
| `tests_replica/test_ng_workshop.py::WorkshopCourt::test_concurrent_10_processes_100_messages` | WinError 6 / WinError 50 while duplicating inherited native stdin | b | Default pytest capture=sys; affected after batches passed |
| `tests_replica/test_ng_workshop.py::WorkshopCourt::test_four_senders_200_messages_with_concurrent_readers` | WinError 6 / WinError 50 while duplicating inherited native stdin | b | Default pytest capture=sys; affected after batches passed |
| `tests_replica/test_node_params.py::test_parameter_types_in_compiled_studio` | WinError 6 / WinError 50 while duplicating inherited native stdin | b | Default pytest capture=sys; affected after batches passed |
| `tests_replica/test_raildoors.py::test_rendered_raildoors` | WinError 6 / WinError 50 while duplicating inherited native stdin | b | Default pytest capture=sys; affected after batches passed |
| `tests_replica/test_real_app_check_tool.py::test_raw_cdp_driver_uses_a_disposable_headless_browser` | ERR_MODULE_NOT_FOUND: playwright (ES module resolution) | b | Provide lane-local node_modules resolution to the existing pinned dependency tree; affected after batches passed |
| `tests_replica/test_settings_node_bridge.py::test_settings_binding_after_reopen` | ERR_MODULE_NOT_FOUND: playwright (ES module resolution) | b | Provide lane-local node_modules resolution to the existing pinned dependency tree; affected after batches passed |
| `tests_replica/test_baboom_site_fit.py::test_prepared_signed_out_matches_real_site_without_models[project folders-/folders with spaces.html?x=1&y=2]` | WinError 6 in setup subprocess | b | Default capture=sys; after batch 16 passed |
| `tests_replica/test_baboom_site_fit.py::test_prepared_signed_out_matches_real_site_without_models[project obscure-//elsewhere.example]` | WinError 6 in setup subprocess | b | Default capture=sys; after batch 16 passed |
| `tests_replica/test_baboom_site_fit.py::test_prepared_signed_out_matches_real_site_without_models[standard-https://elsewhere.example]` | WinError 6 in setup subprocess | b | Default capture=sys; after batch 16 passed |
| `tests_replica/test_baboom_site_fit.py::test_prepared_signed_out_matches_real_site_without_models[interstellar quantum-/]` | WinError 6 in setup subprocess | b | Default capture=sys; after batch 16 passed |
| `tests_replica/test_baboom_site_fit.py::test_prepared_signed_out_matches_real_site_without_models[who are you?-/]` | WinError 6 in setup subprocess | b | Default capture=sys; after batch 16 passed |
| `tests_replica/test_baboom_site_fit.py::test_prepared_signed_out_matches_real_site_without_models[\u0641\u064a\u0646 \u0627\u0644\u0634\u064a\u062a\u061f-/]` | WinError 6 in setup subprocess | b | Default capture=sys; after batch 16 passed |
| `tests_replica/test_baboom_site_fit.py::test_prepared_signed_in_keeps_router_and_expired_token_fallback` | WinError 6 in setup subprocess | b | Default capture=sys; after batch 16 passed |
| `tests_replica/test_baboom_site_fit.py::test_desktop_rejects_prepared_signin_prose_even_with_a_citation` | WinError 6 in setup subprocess | b | Default capture=sys; after batch 16 passed |
| `tests_replica/test_baboom_site_fit.py::test_desktop_cookie_reaches_existing_site_validation[401]` | WinError 6 in setup subprocess | b | Default capture=sys; after batch 16 passed |
| `tests_replica/test_baboom_site_fit.py::test_desktop_cookie_reaches_existing_site_validation[403]` | WinError 6 in setup subprocess | b | Default capture=sys; after batch 16 passed |

### Every original failing JS check

The unchanged-main five-file run reported `tests 41`, `pass 9`, `fail 32`, `cancelled 0`, `skipped 0`, `duration_ms 616054.4549`. Its wsadd child was stopped only after all four tests had emitted their failures, because failed mounts leaked timers. The helper now closes its window on setup failure.

The full five-file rerun reported `tests 41`, `pass 13`, `fail 28`, `cancelled 0`, `skipped 0`, `duration_ms 208724.9964`. The latest focused run of Workshop, Settings Add, and the new frozen-reference checks reported `tests 18`, `pass 11`, `fail 7`, `cancelled 0`, `skipped 0`, `duration_ms 4916.0339`.

A contract conflict is not forced into class c: an obsolete source-shape assertion or an incomplete legacy fixture does not prove a product defect. The no-assertion-change instruction prevents silently replacing those contracts. Their exact errors and source anchors remain below for the coordinator.

| Test | Original error, one line | Class | What changed / latest result |
|---|---|---|---|
| `tests_js/studio_canvasold.test.cjs`: actual adapter preserves declared types, cardinality, units and real endpoint IDs | locator.waitFor: Timeout 30000ms exceeded. | legacy contract | Panels/action dependencies repaired; remaining fixture assumes graph-open/universal Canvas state instead of a .archhub document; assertions preserved |
| `tests_js/studio_canvasold.test.cjs`: every wire terminates at the real socket centers | locator.waitFor: Timeout 30000ms exceeded. | legacy contract | Panels/action dependencies repaired; remaining fixture assumes graph-open/universal Canvas state instead of a .archhub document; assertions preserved |
| `tests_js/studio_canvasold.test.cjs`: clicking a wire inspects its type, both sockets and its value | locator.waitFor: Timeout 30000ms exceeded. | legacy contract | Panels/action dependencies repaired; remaining fixture assumes graph-open/universal Canvas state instead of a .archhub document; assertions preserved |
| `tests_js/studio_canvasold.test.cjs`: logical type mismatch never writes a wire; compatible socket activation writes the real IDs | locator.waitFor: Timeout 30000ms exceeded. | legacy contract | Panels/action dependencies repaired; remaining fixture assumes graph-open/universal Canvas state instead of a .archhub document; assertions preserved |
| `tests_js/studio_canvasold.test.cjs`: real shell gives canvas all height below top bar, floats composer and fills Library to bottom | locator.waitFor: Timeout 30000ms exceeded. | legacy contract | Panels/action dependencies repaired; remaining fixture assumes graph-open/universal Canvas state instead of a .archhub document; assertions preserved |
| `tests_js/studio_canvasold.test.cjs`: system nodes are absent from Canvas; Settings System graph groups actual system nodes | locator.waitFor: Timeout 30000ms exceeded. | b | PASS — load production dependencies / explicit DOM fixture inputs; js-after.log |
| `tests_js/studio_canvasold.test.cjs`: explicit Settings system navigation preserves and restores the last admitted user graph | TypeError: Cannot read properties of undefined (reading 'properties') | legacy contract | Panels/action dependencies repaired; remaining fixture assumes graph-open/universal Canvas state instead of a .archhub document; assertions preserved |
| `tests_js/studio_canvasold.test.cjs`: a slow System canvas response cannot overwrite newer explicit user navigation | TypeError: Cannot read properties of undefined (reading 'properties') | legacy contract | Panels/action dependencies repaired; remaining fixture assumes graph-open/universal Canvas state instead of a .archhub document; assertions preserved |
| `tests_js/studio_canvasold.test.cjs`: desktop assembly objects and library_ports metadata render real typed interfaces without a clean-only schema | locator.waitFor: Timeout 30000ms exceeded. | legacy contract | Panels/action dependencies repaired; remaining fixture assumes graph-open/universal Canvas state instead of a .archhub document; assertions preserved |
| `tests_js/studio_canvasold.test.cjs`: fast Settings-to-Canvas refresh cancels the old System read and restores the admitted user graph | TypeError: Cannot read properties of undefined (reading 'properties') | legacy contract | Panels/action dependencies repaired; remaining fixture assumes graph-open/universal Canvas state instead of a .archhub document; assertions preserved |
| `tests_js/studio_canvasold.test.cjs`: plain box selection, Shift-click add, Escape and empty click give visible selection | locator.waitFor: Timeout 30000ms exceeded. | legacy contract | Panels/action dependencies repaired; remaining fixture assumes graph-open/universal Canvas state instead of a .archhub document; assertions preserved |
| `tests_js/studio_canvasold.test.cjs`: node body drag and selected group drag persist through the real move adapter without snapping back | locator.waitFor: Timeout 30000ms exceeded. | legacy contract | Panels/action dependencies repaired; remaining fixture assumes graph-open/universal Canvas state instead of a .archhub document; assertions preserved |
| `tests_js/studio_canvasold.test.cjs`: no selected user graph leaves an empty canvas even when System contains child compositions | locator.waitFor: Timeout 30000ms exceeded. | b | PASS — load production dependencies / explicit DOM fixture inputs; js-after.log |
| `tests_js/studio_canvasold.test.cjs`: non-interface parameters remain editable widgets without fabricated socket IDs | locator.waitFor: Timeout 30000ms exceeded. | legacy contract | Panels/action dependencies repaired; remaining fixture assumes graph-open/universal Canvas state instead of a .archhub document; assertions preserved |
| `tests_js/studio_canvasold.test.cjs`: Settings hosts the grouped system graph in the actual shell | locator.waitFor: Timeout 30000ms exceeded. | legacy contract | Panels/action dependencies repaired; remaining fixture assumes graph-open/universal Canvas state instead of a .archhub document; assertions preserved |
| `tests_js/studio_canvasold.test.cjs`: System graph exposes a refused read and retries the same owner | locator.waitFor: Timeout 30000ms exceeded. | legacy contract | Panels/action dependencies repaired; remaining fixture assumes graph-open/universal Canvas state instead of a .archhub document; assertions preserved |
| `tests_js/studio_canvasold.test.cjs`: CARDPOLISH bounds human rows while retaining internal parameters and every socket | locator.waitFor: Timeout 30000ms exceeded. | legacy contract | Panels/action dependencies repaired; remaining fixture assumes graph-open/universal Canvas state instead of a .archhub document; assertions preserved |
| `tests_js/studio_canvasold.test.cjs`: CARDPOLISH declared editable text remains reachable regardless of key or value shape | locator.waitFor: Timeout 30000ms exceeded. | legacy contract | Panels/action dependencies repaired; remaining fixture assumes graph-open/universal Canvas state instead of a .archhub document; assertions preserved |
| `tests_js/studio_fixcanvas_rendered.test.cjs`: 30 shell tab returns preserve the actual Canvas, viewport, selection and draft without graph requests | locator.waitFor: Timeout 30000ms exceeded. | legacy contract | Panels/action dependencies repaired; remaining fixture assumes graph-open/universal Canvas state instead of a .archhub document; assertions preserved |
| `tests_js/studio_foundations_tokens.test.cjs`: DS-FOUNDATIONS P9 text below 13px does not use inkMuted | AssertionError [ERR_ASSERTION]: Expected values to be strictly deep-equal: | source-only finding | Preserved; ds_screens.jsx:233 has 11px inkMuted. No rendered defect is claimed |
| `tests_js/studio_workshop_detail.test.cjs`: rules and agents round-trip without splitting on periods | AssertionError [ERR_ASSERTION]: The input did not match the regular expression /ItemList label="Assigned agents"/. Input: | source/fixture contract | Required icons/panels/document/state inputs repaired; remaining old source text, status label or missing Home child context is preserved |
| `tests_js/studio_workshop_detail.test.cjs`: task rows hide unsupported blocked-by and show interrupted and limit reached, and the picker shows gate and breaches | Error: Element type is invalid: expected a string (for built-in components) or a class/function (for composite components) but got: undefined. You likely forgot to export your component from the file it's defined in, or you might have mixed up default and named imports. | b | PASS — load production dependencies / explicit DOM fixture inputs; js-fixtures-final.log |
| `tests_js/studio_workshop_detail.test.cjs`: home canvas at 1440 keeps fitted nodes off the plan pane | AssertionError [ERR_ASSERTION]: The input did not match the regular expression /<window\.UI\.Canvas active embedded \/>/. Input: | source/fixture contract | Required icons/panels/document/state inputs repaired; remaining old source text, status label or missing Home child context is preserved |
| `tests_js/studio_workshop_detail.test.cjs`: a 1440 canvas fit keeps canonical nodes inside the graph and off the plan pane | evalmachine.<anonymous>:527 | b | PASS — load production dependencies / explicit DOM fixture inputs; js-fixtures-final.log |
| `tests_js/studio_workshop_detail.test.cjs`: a step shows only the status the progress dict recorded | AssertionError [ERR_ASSERTION]: Expected values to be strictly equal: | source/fixture contract | Required icons/panels/document/state inputs repaired; remaining old source text, status label or missing Home child context is preserved |
| `tests_js/studio_workshop_detail.test.cjs`: workshop and canvas routes open that face of the selected task on Home | TypeError: Cannot read properties of undefined (reading 'find') | source/fixture contract | Required icons/panels/document/state inputs repaired; remaining old source text, status label or missing Home child context is preserved |
| `tests_js/studio_workshop_detail.test.cjs`: the workshop face shows task-file messages and refreshes them when the task opens | TypeError: Cannot read properties of undefined (reading 'find') | source/fixture contract | Required icons/panels/document/state inputs repaired; remaining old source text, status label or missing Home child context is preserved |
| `tests_js/studio_workshop_detail.test.cjs`: home at 1440 keeps the conversation dominant and says an empty task once | TypeError: Cannot read properties of undefined (reading 'find') | source/fixture contract | Required icons/panels/document/state inputs repaired; remaining old source text, status label or missing Home child context is preserved |
| `tests_js/wsadd.test.cjs`: Add picks, registers and refreshes the rendered list | AssertionError [ERR_ASSERTION]: real Settings Add rendered | b | PASS — load production dependencies / explicit DOM fixture inputs; js-fixtures-final.log |
| `tests_js/wsadd.test.cjs`: cancel says cancelled and never registers | AssertionError [ERR_ASSERTION]: real Settings Add rendered | b | PASS — load production dependencies / explicit DOM fixture inputs; js-fixtures-final.log |
| `tests_js/wsadd.test.cjs`: register refusal reaches the Settings status unchanged | AssertionError [ERR_ASSERTION]: real Settings Add rendered | b | PASS — load production dependencies / explicit DOM fixture inputs; js-fixtures-final.log |
| `tests_js/wsadd.test.cjs`: verified recovery keeps the existing workspace controls and truthful row states | AssertionError [ERR_ASSERTION]: real Settings Add rendered | legacy contract | Add/cancel/refusal now pass; recovery still requires Source: Application graph. No assertion changed |

### Additional tooling failures and repairs

| Failure | Class | Cause and repair |
|---|---|---|
| Compiler lookup resolves Temp/rust; Cargo absent; lane MSVC absent | b | strict_check resolves the primary checkout through Git common-dir for toolchain inputs. Actual probe: governed Rust root, cargo_exists=True, shared_msvc=True, lane_msvc_exists=False. Compiler sources remain in this lane |
| Heavy runner stalls probing bare python | b | Select ARCHHUB_PYTHON or the unpackaged Python-manager shim before probing; applied to the existing shared run-heavy.ps1; exact delta recorded in tools/run-heavy-python.patch |
| precommit fixture returns 1 instead of expected 2 | a | Caller ARCHHUB_INTENT_CONTEXT leaked into the test. Repository fixture now removes that inherited input; assertions unchanged |
| Stop-hook patch appears to apply but fourth check returns 0 | a | git apply discovered the outer worktree and skipped fixture paths. The fixture now has its own Git root, pins the two external source hashes, and applies a rebased version of the existing patch. No live hook was patched |
| Pytest-only pyproject change called a dependency decision | b | Existing decision checker now compares parsed TOML outside tool.pytest. Real staged-Git regression accepts capture-only changes and still identifies a dependency change. Shared checker updated; exact delta recorded in decision-pytest.patch |
| Legacy design proof reads 01.WIP | a | One setting in design-reference.json selects frozen v53. One loader rejects WIP and missing folders. Both frozen-reference tests passed. The full legacy SVG proof is not a release test and was not run: v53 contains HTML/JS plates rather than its old SVG filenames |

### Proven compiler defect left for the coordinator (c)

R100 alias provenance uses bindings from the entire module, so unrelated functions sharing a local variable name are conflated. The observed gated commit rejected a pure string replacement in the new test because another function assigns `original = subprocess.run`. The diagnostic was `R100: foreground effect has no dominating idle/away guard`, at the staged test file line 1059. The new fixture uses the descriptive name decision_manifest; the compiler scoping defect is not claimed fixed.

Source anchors: `03.TOOLS/tools/archhub-compiler/src/intent.rs:331` builds conduct bindings from the root syntax tree; `intent.rs:671` resolves each foreground call with that module-wide binding set. Product code was not changed. This is a real compiler false refusal; the remaining JS source checks are not presented as verified app defects.

### Residual boundaries

- No full-repository sweep, application build/install, release, deploy, push, user desktop interaction, or live host exercise.
- No three-solo-run flake claim: failures were deterministic input/environment/contract cases; no failure was accepted merely because a solo rerun passed.
- Existing coordinator-only artifact skips remain; no skip/xfail was added.
- Settings Add is a DOM fixture, not a resize or installed-app acceptance court. Real rendered release courts remain separate.
- Frozen design path is updated only in `02.TESTS/design-reference.json` at a reviewed designer freeze; it never falls back to WIP.
- Logs and the exact selected release arguments remain under `.cache/baseline/` for local review. Commits contain the source fixes and reviewable external-tool deltas, not generated build outputs.

### Latest per-test JS map

The latest result for each of the 41 original test identities, combining the full rerun with the focused fixture follow-up, is 16 passed / 25 failed. This is a per-test result map, not a newly invented single-run summary.

### Cause commits

| Commit | Change |
|---|---|
| `86e1b5a2` | Register baseline test and tooling scope |
| `0ee0422e` | Register frozen governance patch input repair |
| `2a023894` | Register pytest-only decision classifier repair |
| `4df2ef3b` | Distinguish pytest settings from dependency decisions |
| `0dcf0f3c` | Keep Windows subprocess stdin valid under pytest capture |
| `26bbfa8e` | Preserve installed Python dependencies across test profile isolation |
| `60bfdcf9` | Resolve worktree compiler toolchains through the primary checkout |
| `aba057be` | Isolate compiler fixture context and pin the rebased hook input |
| `c5b30e2d` | Select unpackaged Python before the heavy runner probes an alias |
| `0459aebc` | Pin design proof input to one frozen archive setting |
| `92e5e45a` | Load current browser dependencies in the existing UI fixtures |

Shared external source changes: run-heavy.ps1 and decision_check.py were updated in place under their existing owners. Their exact deltas are committed as the two .patch files under 03.TOOLS/tools; the private source directories are outside this Git branch. Their existing REGISTER.md files were regenerated from disk. No live stop hook was changed.
