# DESIGNV22G branch evidence

## Version 47 evening continuation, 2026-11-11

Founder: "بس حلو الديزاين ده أنا عاوز أشوفه نفسه في الريليس الجاي على الابليكيشن اللي شغال" (this design is good; I want to see this same design in the next release on the running app).
This run is branch-only preparation, not installed or release acceptance. Origin was fetched and the lane rebased onto f6dc2d1d. Intent conflicts retained main's Workshop/guard registrations and DESIGNV22G; no hook or rule changed.

Prior art: approved archhub-directions index.html/app.js and CHANGES.md from Home study through version 47; res-031; existing ds_workshop3.jsx splitter, ds_home2.jsx task files/composer, ds_screens.jsx Canvas and ui.jsx approval owner. The supplied res-033 filename currently contains JournalClub episodes 763–766, not a session/layout brief. The current founder scope and the approved Home study control this implementation.

Part 1 adapts those components: one floating composer on every page; work extends to the bottom with no band; status is in the header; Home/Canvas rail, Docs/Settings above the account. Canvas uses the existing resizable-panels dependency, collapsible rails and peeks. Tab overflow preserves the active tab and +; folded Thread remains in More. Composer, Thread and Inspector answer to their own containers. A stale rail height that added the retired footer's 24 px was removed. Toast content lets pointer events through; Dismiss remains clickable.

Not in this release:
- Invite/collaboration: no verified collaborative-session owner; no Invite control added.
- Packages browser: no verified package-catalogue owner; no Packages control added. The existing reviewed local mod manager remains.
- Layout presets: no implemented preset owner; the dead disabled toolbar control is removed. Existing Arrange remains in More; its behavior and fixed-node layout are unchanged.
- Home direction 2, fixed-node lane redesign, auto-arrange changes and rail + picker: outside this run's ordered Resume slice; existing behavior retained.

Validation and commits for each part are appended here after the checks finish. Earlier evidence below belongs to the earlier dated implementation.

### Part 1 isolated acceptance

Compiled Studio manifest: `3c507f50bf9f7fa6ad8c5c83794f3c58cd7c7c6a27e547421142c8d8e91e4add` (40 files, 2046612 output bytes). Existing designbuild suite, `-k fluid_shell`, through the supplied run-heavy.ps1 and Python. One headless browser, synthetic profile; actual Studio/server/file owners, no replacement APIs. Home, Canvas, Docs and Settings at 1009x940, 1366x768 and 1864x949 each report `cut=0 opaqueStrip=0 floatingComposer=true`. Inspector/Thread peeks and actual tab-overflow selection pass. Captures: ignored `.cache/designv22g-shell-{1009,1366,1864}.png`.

```text
PASS fluid shell: narrow Thread and Inspector peek over Canvas; one floating composer
PASS fluid shell: tabs fold into n more; active tab and + stay visible; hidden tab opens
TESTISO final profile leaks: []; protected write attempts: 0
1 passed, 6 deselected, 1 warning in 31.02s
```

Focused existing Canvas regression file, same serialized runner and isolated server:
```text
ℹ tests 25
ℹ pass 25
ℹ fail 0
ℹ skipped 0
```

The dead Layout assertion now checks absence; the other Canvas cases retain real Run/Approve, undo, wire, edit, split, save/restart and file readback coverage. Their wide inspector cases use 1864x949; narrow behavior is exercised in designbuild. A new executable RED found the retired footer's extra rail height before removal. Subsequent checks found collapsed-content and toast hit-target problems, which were corrected in the final bytes. Earlier startup timeouts are not counted as RED. The warning is the existing cache_dir/cacheprovider configuration warning. No full suites or benchmarks ran; no installed/live-profile acceptance is claimed.

Current continuation: [Resume closeout 2026-11-11](#resume-closeout-2026-11-11). Earlier sections are dated evidence, not current completion claims.

Status: implementation committed; isolated behaviour checks pass; visual match remains incomplete. This is not installation or release evidence.

Prior art reused: the installed Studio `ds_*.jsx`, ArchMark, AHIcon, Node/Socket/Wire, TaskComposer, ContextMenu, ApprovalCard, Canvas file adapter, Workshop task/mailbox owners and settings JSON owner. No new store, dependency, logo, palette or parallel runtime was added.

## Revision and artifact

- Branch: `lane/design-v22g`, base `c4577fe61c9c7b0f5ee70b2aca48f9809112c987`.
- Scope registrations: `fcdbea71`, `e777cf07`, `4271d890`, `6d9b608f`.
- Existing-owner backend: `ae864bd8`.
- Linked approval continuation: `a66c4540`.
- Canvas implementation: `502e9614`.
- Measured Canvas corrections and shared settings coordination: `cb8a204d`.
- Unbound Canvas regression: `81e2c498`.
- Workshop Rules/Inspector and menu keyboard focus: `ac76cf12`.
- Collapsed Inspector separator geometry: `accfc97a`.
- Compiled manifest SHA256: `e82cface2dd7c4fbc54a6d1cfd2fbecac072d73ebbac9192778011beb85764d5` (40 files, 1945515 output bytes, Babel 7.29.0).
- Executing CLI versions measured in the isolated environment: Node `v24.13.0`, Python `3.14.3`.
- All heavy runs used the existing `run-heavy.ps1`, sequentially, with disposable USERPROFILE/LOCALAPPDATA/APPDATA/HOME. The permitted Python executable was used with `-E -s -B` for the UI fixture.

## Existing owners used

| Requested capability | Owner and persisted result |
|---|---|
| Keep/reorder/restore tabs and collapse pinned group | Settings owner's `canvasTabs` key in its existing JSON file |
| Tab Rename | `workshop_tasks` row and bound `.archhub` title; failed file writes roll back the task row |
| Show on Home | Existing task context `homePinned` |
| New task Workspace | `workshop_tasks.create_session`, existing workspace registry and session file |
| Four fixed nodes | `session_files`; You resolves the current settings profile, Workshop resolves the existing task thread |
| Bell | Existing pending task/mailbox/approval outcomes; read identities in the settings owner |
| Message Pin | Existing task context stores references to real message IDs |
| Attach Meeting notes | Existing `workshop_mailbox` task thread; attaching does not dispatch an agent |
| Canvas approval and resume | Existing approval owner/card plus `session_files.run_document`; validates the source snapshot, resumes the admitted effect and re-reads its real result |

No requested group-a backend control is disabled for lack of a lawful owner. Layout presets belong to group d in CHANGES.md; the visible Layout control is disabled with that reason in this intermediate build. Its incorrect link to More was removed; this is not a shipped disabled feature. Invalid context remains explicit: for example, Show on canvas is unavailable when a message names no node, with its reason in the menu. A second approval is required for a later effect; one approval does not grant the rest of the document.

## Isolated behaviour checks

Compiled Studio, real NoGraphServer and real owner files, private headless Chrome page:

```text
tests 14
pass 14
fail 0
cancelled 0
skipped 0
todo 0
duration_ms 14992.2277
```

These cover creation/open without execution, Workspace, tab keep/reorder/server-restart restore, Rename/Home, preview-to-kept edit, one shared Canvas/thread composer, Rules selecting a visible Workshop inspector, editing the existing task-file rules and observing the pure output update, menu focus and arrow navigation past unavailable actions, real meeting notes and Pin, pinned-group collapse, Open beside, selection/pointer capture/drag/wheel zoom/middle pan/wiring/keyboard, real Run results, Bell and one approval card/resume, and tab drop as one linked node followed by explicit Detach. Detach proves the source bytes stay unchanged and the copied file has a new document identity.

Owner regression command:

```text
python -B -m pytest -q 02.TESTS/tests_replica/test_designv22g.py 02.TESTS/tests_replica/test_canvas_parametric.py 02.TESTS/tests_replica/test_file_path_links.py 02.TESTS/tests/test_onetask.py 02.TESTS/tests/test_agentwork.py
TESTISO final profile leaks: []; protected write attempts: 0
PROFILE-WRITE-GUARD: protected write attempts=0
65 passed in 94.24s (0:01:34)
```

The settings regression exercises both file owners with Windows errors 5/32/33 and permanent refusal 13, preserving unrelated settings and original bytes on refusal. Two JsonFile instances also perform competing updates without losing either page's value. The real UI reproduced the earlier sharing failure before this correction.

## Visual comparison

Report: `selector-overlay/compare-git-accfc97a-1440x900-Dark.md` and `.json`.

The original external `design_compare.js` SHA256 is `e24c6c2394f1d59c9d6e00e54361a33ed9144e3d3bc9a105d5b8335c18507b1a`. It still calls the stale Create task label. The recorded five-line patch has SHA256 `64babef650b55abbbcc37dfd9d6622120908b027252191eb39f9081fa8c5d10d`: four callers use the existing `newtask.create` element ID and the Python fixture adds `-B`. The diagnostic run applied those lines in memory to the exact original file; the external source was not edited. No tolerance, state data, expected geometry or comparison rule changed. This remains diagnostic until the canonical tool/fixture is reconciled.

```text
design v22g index.html b758d55509f3 app.js a978580e161a
build git-accfc97a manifest e82cface2dd7
viewport 1440x900 Dark, tolerance 4px / 6 rgb
totals {"states reached":10,"present":197,"geometry ok":150,"colour ok":194,"type ok":197,"geometry diff":47,"colour diff":3,"interaction ok":5}
page errors design 0, build 0
```

All ten group-a states are reached, with no missing compared element. Remaining differences are not waived:

- 19 tab geometry differences: the frozen design starts with Details library and resets its tab preconditions between state loads; the build is seeded with Room data sheets and correctly retains the kept tabs created earlier by the same run.
- 25 node geometry differences: the comparison seeds real Math/gate runs, while the frozen example contains different operators, parameter/port/result content and camera framing. Several width differences are exactly the example's 90% camera versus the built fixture's 100%; content-dependent heights also differ. Equivalent fixtures are still needed before calling these matches or defects.
- Approval panel height: 335 versus 324 pixels, with real approval content.
- Thread: first-message height 42 versus 94; attachment-button y 500 versus 581. The build fixture has one short Compare seed message, unlike the frozen thread's content. The close-button offset was corrected by using v22g's one-pixel collapsed separator (six pixels when open), and that element now matches.
- Colours: Rename and Copy text backgrounds differ at the sampled pointer position; Close other tabs is enabled in the retained multi-tab build fixture but unavailable in the frozen single-tab precondition.

The designer and coordinator were sent these measured differences through the existing Workshop, with the exact report and prepared caller patch. No reply had reconciled the fixtures at the time of this record. Applying the exact five-line patch to the canonical tool outside this worktree was asked through a pending approval question; no approval was inferred from silence and no external source write was made.

## Existing Studio suite

The initial full run reported `tests 427; pass 325; fail 96; skipped 6; duration_ms 623743.3233`. It was not green, and all failures are not claimed to be pre-existing. One completed node-placement test process retained timers and was stopped after more than three minutes; this was recorded in the run notes.

The interrupted corrected-build run exposed an introduced regression: ordinary unbound cards read task state before checking whether they were fixed nodes. It was stopped rather than treated as a complete suite. The unchanged rendered STUDIOFIX saved-coordinate check failed against cb8a204d (0 pass, 1 fail, duration_ms 7753.1345) and passed after the one-line fix (1 pass, 0 fail, duration_ms 1992.6837); the prior revision was read from git in memory, with no source overwrite. Final corrected-build command: Node --test --test-force-exit --test-concurrency=1 --test-timeout=180000 over every studio_*.test.cjs file, followed sequentially by the owner regression command above. Its exact totals were:

```text
ℹ tests 431
ℹ pass 331
ℹ fail 94
ℹ skipped 6
ℹ duration_ms 369858.4595
```

These 94 failures remain open; they are not all classified as inherited or intentional. Full raw diagnostics are retained at .cache/designv22g-existing-studio-final.log. The command exited 1; the owner batch exited 0. The compiled manifest was re-read after that batch and still has the exact SHA256 above. The combined validation attempt hit run-heavy's 20-minute budget at 03:15:41 after the placement fixture retained polling timers; every process in that job was stopped by the wrapper. The final existing-suite run uses Node's completion-exit option, after each file's cases finish, plus a 180-second per-test bound. A focused containment check reported all nine placement cases (1 pass, 8 fail) and exited in 13 seconds with the job empty. This contains the existing fixture lifecycle leak without converting its failures to passes. Existing source/mocked assertions are not used as proof of visual acceptance.

## Hooks and remaining boundary

Product commits kept hooks enabled. Latest product hook:

```text
publication-scan PASS paths=3 blobs=3 custody=public-or-unknown
ACOMPILER PASS
```

No push, installation, release, founder screen or client/personal read was performed. Product tests used isolated profiles; coordination used the existing Workshop. Groups b/c/d are outside this run.

Automatic approval review rejected removal of the exact disposable `.cache/testiso-designv22g-ui-JNzQUA` profile with `blocked by policy`. That folder was left in place; deletion was not attempted through another tool. After validation, automatic approval review also rejected removal of the two verified temporary junctions (01.APP/.venv and .cache/testiso-designv22g/LOCAL/ms-playwright) with blocked by policy. Those links remain; no alternate removal was attempted. The links reference the permitted existing runtime/browser cache and do not copy their bytes. New owned UI fixtures shut down their server and browser before cleanup.

## Final existing-suite failing cases

- the existing Task used by Workshop and Board renders runtime facts and honest flags
- BABOOM5 native HTML mounts the actual shared Approve card and awaits its channel receipt
- 02.TESTS\tests_js\studio_boot38.test.cjs
- 12 nodes in 3 groups open without overlaps, fitted at each scope; groups show members
- Library is present on open and a real drag adds the selected definition at its drop point
- flat overlapping ordinary nodes use the canvas build spec operation anatomy and 2px wires
- saving a drag keeps untouched cards at their repaired display positions
- actual adapter preserves declared types, cardinality, units and real endpoint IDs
- every wire terminates at the real socket centers
- logical type mismatch never writes a wire; compatible socket activation writes the real IDs
- real shell gives canvas all height below top bar, floats composer and fills Library to bottom
- explicit Settings system navigation preserves and restores the last admitted user graph
- a slow System canvas response cannot overwrite newer explicit user navigation
- desktop assembly objects and library_ports metadata render real typed interfaces without a clean-only schema
- fast Settings-to-Canvas refresh cancels the old System read and restores the admitted user graph
- plain box selection, Shift-click add, Escape and empty click give visible selection
- node body drag and selected group drag persist through the real move adapter without snapping back
- non-interface parameters remain editable widgets without fabricated socket IDs
- Settings hosts the grouped system graph in the actual shell
- System graph exposes a refused read and retries the same owner
- CARDPOLISH bounds human rows while retaining internal parameters and every socket
- CARDPOLISH declared editable text remains reachable regardless of key or value shape
- the bundled xyflow loads on the Studio React and exposes the canvas pieces
- no studio CSS rule carries a colour of its own
- each DESIGNSYS-050 4.9 building block maps to one Penpot design and exists once in code
- Home hydrates stored zero-run starters and saved skills from their existing owners
- a failed or malformed starter read never blocks the existing Canvas or saved skills
- library Start and Schedule enter the existing composition before evaluating executable nodes
- failed graph navigation clears the new declaration projection immediately
- template scheduling resolves the stored template before a same-title collapsed card
- opening a hidden composition uses its existing scope control and keeps the saved project
- current interaction acknowledgement hydrates the existing canvas without replaying its write
- a completed template run never restores over a later deliberate graph navigation
- DS-PORT Toggle and changed Row match plate geometry and invoke the owner
- nested Canvas move saves through the real adapter with one mutation and no graph re-read
- parameter and wire acknowledgements update the graph without a full GET
- overlapping first Canvas opens share one graph request
- overlapping moves each confirm once without adopting an older acknowledgement
- parameter and move share one authority queue and both acknowledgements confirm
- concurrent parameter and move deltas merge against the queued authority revision
- saved graph opens once even while background graph discovery is pending
- a refused parameter remains refused without automatically replaying the write
- native typed wire uses its current graph interaction in one mutation
- a no-longer-editable parameter retains its explicit refusal without a graph read
- same-scope bootstrap does not cancel an explicit graph switch or reread its acknowledgement
- native wire resolves the exact dropped socket from the shared scoped target table
- visible Canvas combines scheduling and conditional freshness in one timer request
- 30 shell tab returns preserve the actual Canvas, viewport, selection and draft without graph requests
- boot timeout is neutral and the next successful automatic read clears the rendered footer
- failed reads back off at 5s, 15s, 60s, then 5min; hidden pauses reads
- ready pushes bypass backoff without update actions
- successful status reads preserve another owners connection failure
- a good status after a boot timeout removes the stale rendered error
- hiding during an owner refresh prevents a new background status read
- background reads share pending work and a success resets failure backoff
- DS-FOUNDATIONS P9 text below 13px does not use inkMuted
- 02.TESTS\tests_js\studio_hidden_work.test.cjs
- LIBRARY-64 p4 row ports equal the served canonical interface for every row
- NODEPLACE wide graph inserts in visible viewport, not past the last node
- NODEPLACE actual Canvas centres, avoids occupied/repaired cards, follows selection and current pan/zoom
- NODEPLACE explicit drops bypass placement and failed creation releases the reservation
- NODEPLACE real API plus Canvas: concurrent and same-turn adds, tall card, explicit drop and unmount
- NODEPLACE concurrent revision-root creations return their own selected node
- NODEPLACE bounded rendering wait does not move a node after navigation
- NODEPLACE actual-height overflow keeps the new node and reports direction without deleting
- NODEPLACE full viewport still creates through real API and Canvas without removal or camera movement
- a: first screen and Studio shell never expose internal host-probe or unknown text
- Settings failure stays visible and retries the actual owner
- Home composer admits one chat request and restores a refused draft only when nothing newer is typed
- idle Studio needs no update timer and a native ready push reads once
- a read that never answers times out and a native status refresh recovers
- up to date draws no notice; a ready build shows one relaunch notification
- a refused restart reports its reason and a native status refresh recovers
- native ready refresh and toolbar update use one lifecycle owner
- STUDIOTESTS a late successful send preserves a newer unsent Composer draft
- STUDIOFIX a retyped identical draft survives a late send and navigation
- STUDIOFIX a successful send clears only its unchanged draft
- STUDIOTESTS Undo and Redo ignore editable targets and use the current graph owner
- STUDIOFIX an auxiliary Composer edits and sends without replacing the primary draft
- STUDIOFIX Home and Workshop reply drafts are separate across navigation
- STUDIOFIX task replies own separate drafts and late replies preserve newer text
- the File menu is file-only and Workshop leads with the thread
- Workshop plan steps are cards beside the conversation and review rows keep Evidence
- Settings search shows values and Advanced rows, then reveals the control in place
- rules and agents round-trip without splitting on periods
- home canvas at 1440 keeps fitted nodes off the plan pane
- a 1440 canvas fit keeps canonical nodes inside the graph and off the plan pane
- a step shows only the status the progress dict recorded
- workshop and canvas routes open that face of the selected task on Home
- the workshop face shows task-file messages and refreshes them when the task opens
- home at 1440 keeps the conversation dominant and says an empty task once
- server: the participant host comes from the runtime catalog; revoke is a workflow action of the one route
- Workshop renders each real projected delivery state alongside its message
- Workshop room renders real mailbox projection even with no Work tasks

## Exact dedicated UI output

```text
▶ DESIGNV22G Canvas behaviours on compiled Studio and real file owners
  ✔ New task creates one file with four fixed nodes and never runs on open (1093.428ms)
  ✔ New task Workspace is stored by the real task file owner (1055.5951ms)
  ✔ Tabs keep open, reorder and restore after server restart (2054.162ms)
  ✔ Tab Rename and Show on Home use the existing task owner (960.6719ms)
  ✔ Plus opens a closed task as a preview and editing keeps it open (698.594ms)
  ✔ Thread split keeps the Canvas and shares one composer draft (694.0264ms)
  ✔ Meeting notes attach to the thread and Pin persists (731.9136ms)
  ✔ Pinned-node collapse changes view metadata and retains all four nodes (188.5524ms)
  ✔ Open beside reads a different task file and keeps the active file selected (281.1321ms)
  ✔ Canvas selection, pointer capture, wheel zoom, middle pan, wiring and keyboard stay live (1313.8009ms)
  ✔ Canvas Run keeps the task open and reports its actual node results (232.4905ms)
  ✔ A real Canvas gate waits, appears in Bell and resumes through one Approve card (1282.1201ms)
  ✔ Dropping another task creates one linked node and Detach copies explicitly (524.9623ms)
✔ DESIGNV22G Canvas behaviours on compiled Studio and real file owners (14496.6372ms)
ℹ tests 14
ℹ suites 0
ℹ pass 14
ℹ fail 0
ℹ cancelled 0
ℹ skipped 0
ℹ todo 0
ℹ duration_ms 14992.2277
```

## Resume closeout 2026-11-11

This section supersedes the earlier mutable results above. Scope: finish group-b behaviour and affected owners on `lane/design-v22g`; preserve step width 268 and the frozen v22g comparison target. No v26 Home, Workshop page, Automate page, pinned/avatar/profile styling or Canvas header Save/Automate work was added. No push, installation or release.

- `dd710006`: Script Python engine, pure/effect classification, saved node types and public parameters, wire rules/disable/bypass, owner validation; ordinary linked-task Run history is preserved and pure saved definitions are read-only during solve.
- `5f8edb25`: node/wire/socket/selection menus, safe group/frame/ungroup and undo, Inspector Script editor, Add parameter on steps and agent sessions, node type scan/retry, find/add/note/rename, existing action bindings, save-before-Run ordering. Agent-step parameters, Run and History remain reachable in the Inspector. The fixed nodes cannot be grouped or deleted.
- Heavy jobs ran sequentially through `run-heavy.ps1` using `.cache/testiso-designv22g` for USERPROFILE, HOME, LOCALAPPDATA, APPDATA and application state. UI fixtures use private headless browser pages and real NoGraphServer/file owners. Test cleanup closes browser and server; no watchers.

### Exact focused results

```text
1..1
# tests 25
# suites 0
# pass 25
# fail 0
# cancelled 0
# skipped 0
# todo 0
# duration_ms 27273.9468
```

Node owners:
```text
...........................TESTISO final profile leaks: []; protected write attempts: 0
                                                                         [100%]
PROFILE-WRITE-GUARD: protected write attempts=0
27 passed in 28.99s
```

Linked task Run history:
```text
.TESTISO final profile leaks: []; protected write attempts: 0
                                                                         [100%]
1 passed, 14 deselected in 27.34s
```

Reopen without effects:
```text
.TESTISO final profile leaks: []; protected write attempts: 0
                                                                         [100%]
PROFILE-WRITE-GUARD: protected write attempts=0
1 passed, 11 deselected in 34.22s
```

File/path links:
```text
..TESTISO final profile leaks: []; protected write attempts: 0
                                                                         [100%]
PROFILE-WRITE-GUARD: protected write attempts=0
2 passed in 37.93s
```

Native-format agent-step UI:
```text
.TESTISO final profile leaks: []; protected write attempts: 0
                                                                         [100%]
1 passed, 13 deselected in 54.16s
```

### Saved suite comparison, not rerun during this closeout

The completed comparison used main snapshot `c4577fe61c9c7b0f5ee70b2aca48f9809112c987`. Current origin/main is `f6dc2d1ded546a8a6e6e51c81a37c7d00a3e889d`; the saved comparison is not represented as a check of that newer revision. The resume instruction says Part 2 is done and forbids a full Studio suite rerun.

```text
main snapshot
# tests 376
# pass 297
# fail 73
# skipped 6
# duration_ms 457540.2059
branch snapshot
# tests 391
# pass 310
# fail 75
# skipped 6
# duration_ms 552743.6704
```

The added snapshot failures were Ungroup preservation and its parent test. Both now pass in the focused compiled UI file. The snapshot has 73 failures shared with main, no failures unique to main. This is not a full-suite pass for the current branch.

Baseline failures shared with the branch, generated from the saved TAP logs:

- the existing Task used by Workshop and Board renders runtime facts and honest flags
- BABOOM5 native HTML mounts the actual shared Approve card and awaits its channel receipt
- 02.TESTS\\tests_js\\studio_boot38.test.cjs
- 12 nodes in 3 groups open without overlaps, fitted at each scope; groups show members
- Library is present on open and a real drag adds the selected definition at its drop point
- flat overlapping ordinary nodes use the canvas build spec operation anatomy and 2px wires
- saving a drag keeps untouched cards at their repaired display positions
- actual adapter preserves declared types, cardinality, units and real endpoint IDs
- every wire terminates at the real socket centers
- logical type mismatch never writes a wire; compatible socket activation writes the real IDs
- real shell gives canvas all height below top bar, floats composer and fills Library to bottom
- explicit Settings system navigation preserves and restores the last admitted user graph
- a slow System canvas response cannot overwrite newer explicit user navigation
- desktop assembly objects and library_ports metadata render real typed interfaces without a clean-only schema
- fast Settings-to-Canvas refresh cancels the old System read and restores the admitted user graph
- plain box selection, Shift-click add, Escape and empty click give visible selection
- node body drag and selected group drag persist through the real move adapter without snapping back
- non-interface parameters remain editable widgets without fabricated socket IDs
- Settings hosts the grouped system graph in the actual shell
- System graph exposes a refused read and retries the same owner
- CARDPOLISH bounds human rows while retaining internal parameters and every socket
- CARDPOLISH declared editable text remains reachable regardless of key or value shape
- the bundled xyflow loads on the Studio React and exposes the canvas pieces
- no studio CSS rule carries a colour of its own
- each DESIGNSYS-050 4.9 building block maps to one Penpot design and exists once in code
- 02.TESTS\\tests_js\\studio_designmatch.test.cjs
- DS-PORT plate button snapshots and native disabled/focus behavior
- DS-PORT native button refs work with the actual shipped React 18 runtime
- DS-PORT Toggle and changed Row match plate geometry and invoke the owner
- DS-PORT typed Socket and Node anatomy snapshots match ds.jsx and ds_node.jsx
- DS-PORT live theme mutation recolours typed sockets and shared muted text
- DS-PORT Card, Rail, Composer and actionable EmptyState share plate shells
- DS-PORT error copy hides internal roots, paths, addresses and tokens while retaining ordinary errors
- DS-PORT compact EmptyState ports the dashed empty-session plate shell
- nested Canvas move saves through the real adapter with one mutation and no graph re-read
- parameter and wire acknowledgements update the graph without a full GET
- overlapping first Canvas opens share one graph request
- overlapping moves each confirm once without adopting an older acknowledgement
- parameter and move share one authority queue and both acknowledgements confirm
- concurrent parameter and move deltas merge against the queued authority revision
- saved graph opens once even while background graph discovery is pending
- a refused parameter remains refused without automatically replaying the write
- native typed wire uses its current graph interaction in one mutation
- a no-longer-editable parameter retains its explicit refusal without a graph read
- same-scope bootstrap does not cancel an explicit graph switch or reread its acknowledgement
- native wire resolves the exact dropped socket from the shared scoped target table
- visible Canvas combines scheduling and conditional freshness in one timer request
- 30 shell tab returns preserve the actual Canvas, viewport, selection and draft without graph requests
- 02.TESTS\\tests_js\\studio_footerretry.test.cjs
- DS-FOUNDATIONS P9 text below 13px does not use inkMuted
- 02.TESTS\\tests_js\\studio_hidden_work.test.cjs
- LIBRARY-64 p4 row ports equal the served canonical interface for every row
- NODEPLACE wide graph inserts in visible viewport, not past the last node
- NODEPLACE actual Canvas centres, avoids occupied/repaired cards, follows selection and current pan/zoom
- NODEPLACE explicit drops bypass placement and failed creation releases the reservation
- NODEPLACE real API plus Canvas: concurrent and same-turn adds, tall card, explicit drop and unmount
- NODEPLACE concurrent revision-root creations return their own selected node
- NODEPLACE bounded rendering wait does not move a node after navigation
- NODEPLACE actual-height overflow keeps the new node and reports direction without deleting
- NODEPLACE full viewport still creates through real API and Canvas without removal or camera movement
- a: first screen and Studio shell never expose internal host-probe or unknown text
- 02.TESTS\\tests_js\\studio_update_notice.test.cjs
- rules and agents round-trip without splitting on periods
- home canvas at 1440 keeps fitted nodes off the plan pane
- a 1440 canvas fit keeps canonical nodes inside the graph and off the plan pane
- a step shows only the status the progress dict recorded
- workshop and canvas routes open that face of the selected task on Home
- the workshop face shows task-file messages and refreshes them when the task opens
- home at 1440 keeps the conversation dominant and says an empty task once
- server: the participant host comes from the runtime catalog; revoke is a workflow action of the one route
- Workshop renders each real projected delivery state alongside its message
- Workshop discards an older page that arrives after a graph or account switch
- Workshop room renders real mailbox projection even with no Work tasks

### Remaining acceptance boundary

Comparison results will be recorded below. Layout presets remain disabled because they belong to group d. Revit and AutoCAD inside the Python Script editor are labelled unavailable there; the existing Run in program node owns those host brokers. Invalid context actions retain their explicit reasons. No installation, release, live profile or founder-screen check was performed.

Automatic approval review rejected deletion of the stopped run's disposable .cache/agentwork-pzfy2yyt profile with blocked by policy. It was left in place; no alternative deletion was attempted.

### Built-byte visual reports

Frozen target: v22g `index.html b758d55509f3`, `app.js a978580e161a`. Comparison tool SHA256 `1f3a687264edcd67f8b31a4c35d304fc902e12e4c0ec3dcaf9eef0ef7a2eca43`; the design owner corrected the fixed-node selectors. The tool itself was not edited here. All reports use 1440x900 Dark, tolerance 4 px / 6 RGB.

Full group reports, source commit `5f8edb25`, manifest `b86b6cf800ffa5ef61207944c04f19bb49ac9c9766d1a220985e90de79b25979`:

Group a: [per-state report](resume-a-final/compare-git-5f8edb25-1440x900-Dark.md).
```text
{"states reached":10,"present":168,"geometry ok":153,"colour ok":166,"type ok":168,"geometry diff":15,"colour diff":2,"missing":29,"interaction ok":5}
page errors design 0, build 0
```

Group b: [per-state report](resume-b-final/compare-git-5f8edb25-1440x900-Dark.md).
```text
{"states reached":13,"present":57,"geometry ok":54,"colour ok":51,"type ok":53,"colour diff":6,"type diff":4,"states not reachable":9,"geometry diff":3,"missing":15,"interaction diff":2}
page errors design 0, build 0
```

These are raw results, not visual acceptance. Group a includes the paused pinned-card dimensions and a route/state mismatch with missing Canvas elements. Group b leaves 9 states unreachable and 15 missing elements; the tool reuses seeded nodes after collapsing them, and calls matchTabs after opening non-menu states. Those are fixture hypotheses routed to the design owner through the coordinator (Workshop sequence 12607); they are not adjudicated as all fixture-only. The 2 interaction differences in that batch remain recorded, alongside the real UI grouping/ungrouping/undo proof.

Follow-up source corrections: collapsed groups use 224 px while steps stay 268; group frame/title/Open match the measured typography; the command palette uses the raised surface and correct input/row sizing. Its grid permits content to shrink and the filter row wraps. Empty clipboard Paste is disabled with “Copy nodes first.”. No pinned-node sizing/styling was changed.

Final compiled bytes: manifest `5b0d5be79617892877812d4dc9df10787cbfecbbb4ad978e3d8755b0c6fd641d`, 40 files, 2036534 output bytes, Babel 7.29.0. The follow-up report labels HEAD `5f8edb25` because the correction commit had not yet run; its manifest binds the actual corrected bytes. Compiled outputs and generated compare reports remain gitignored; this checked-in result records their identities and exact totals.

Final single UI file output, including the empty clipboard assertion and scan failure/retry:

```text
1..1
# tests 25
# suites 0
# pass 25
# fail 0
# cancelled 0
# skipped 0
# todo 0
# duration_ms 38808.9942
```

Final scoped comparison: [group, group.collapsed, palette](resume-b-corrections-final/compare-git-5f8edb25-1440x900-Dark.md).
```text
{"states reached":3,"present":7,"geometry ok":7,"colour ok":7,"type ok":7}
page errors design 0, build 0
```

This rechecks the measured corrections only; it does not replace the full group-b totals or resolve its unvisited states. Hooks stayed enabled. The owner and main UI commits both ended with ACOMPILER PASS; the correction commit runs the same hook. Full Studio suites and full multi-group comparisons were not rerun.

### Part 2 Resume and zero-session acceptance, 2026-11-12

Existing Home is now direction 1 Resume: one waiting-first session list, pin marks from the existing task-file homePinned flag, real agent avatars, actual workflow steps (or the task's recorded plan), current-step approval, and recent thread lines. The Settings owner validates and saves homeLayout (resumed session, width, collapse, order and hidden rows) in its existing settings file. Changing Inspector width removes only the legacy inner layout, preserving current Home metadata under the same lock.

The New session composer creates through createTask and opens that file's Canvas; it does not call a model or Run. Zero sessions has three starter prompts which fill that composer. Existing ApprovalCard handles Approve and Reject through answerApproval; Ask why opens the real task thread with its question draft. A real gate is run, rejected, and a second gate approved and re-read in the isolated UI proof. Width, fold, hide/restore and reset/undo round-trip through homeLayout. Pins use the existing task owner rather than a second preference.

Replaced-screen coverage was migrated, not disabled: Home's old Properties preview is now Resume; properties remain editable on its Canvas. Workshop-view assertions now exercise the Thread pane. Fixed inspector coordinates are replaced by adaptive rails/peeks and stable bounds; the old 256 px card fixture uses the current 268 px card with a clear wire gap. Scope, rules, folders, references, plan progress, typed inputs, linked-source visibility, undo/redo, custom header contrast, theme mutation, Library, native open/error routing, Settings/back navigation, width drag, file/browser reopen and appearance reset checks remain executable. Obsolete Penpot capture coordinates were replaced by current built-UI checks at the three requested sizes. The 25-case Canvas regression file retains its cases and changes only the replaced Open task label and the omitted dead Layout control assertion.

That retained coverage exposed two real UI defects: selecting the same wire after a node did not notify the external Inspector again; Canvas surfaces held dark literals instead of the theme token. Both now use their existing owner path. Home clears shared inspection context when entered; flow import navigates to the actual Canvas instead of the removed Home face event. No fixed-node positions, arrange algorithm or rail picker changed.

Compiled manifest: dfc5931a1b76a498fc407c13eeda0587042622d374ed106a9ab2c9f5f7b4d67e; 2058827 output bytes, 40 files. One queued BelowNormal job at a time, one headless browser at a time, isolated profile and real Studio/files. All servers and browsers close in finally. The two deliberately stopped diagnostic jobs were closed through their own job-object runner, including their descendants.

Final focused current-source output:
```text
6 passed, 3 deselected, 1 warning in 58.25s
# tests 25
# pass 25
# fail 0
# skipped 0
TESTISO final profile leaks: []; protected write attempts: 0
```

The six cases are Canvas, canvas_fit, fluid_shell, resume, zero_home and appearance_owner. The migrated Home, Thread, Settings and fit/save/reopen cases also passed in the preceding focused run; its one Canvas-selection failure was repaired and the Canvas case repeated above. Resume and all four shell routes pass at 1009x940, 1366x768 and 1864x949, with zero cut controls and no opaque bottom strip. Current captures remain in ignored .cache/designv22g-resume-{1009,1366,1864}.png. The existing cache_dir warning remains. Full suites, benchmarks, installed acceptance, push and release were not run.

The Settings layout read now drives the existing request state through waiting, loaded/empty and error with Retry; the zero-session section is its rendered empty branch. UI input reuses this suite's original CDP session helpers, confined to its launched headless browser. No desktop pointer call or fabricated idle/away guard is used. The hook and its R100 rule were not changed.

### Part 3 opening view acceptance, 2026-11-12

Prior art: reused Canvas's existing fitCanvasViewport, ResizeObserver, persisted viewport and userViewport flag; both task-bound and standalone Canvas use the same framing effect. Automatic framing fits the whole session when the resulting scale is at least 62%; otherwise it opens at 80% from the left edge, with the top node fully visible. Thread/Inspector peeks reserve their visible width and keep the session node readable. Automatic framing does not save a viewport or move any node. A saved/manual view retains precedence, including after pane/window resize. Explicit Fit remains the existing user action. Fixed-node positions, arrange/layout rules and rail + are unchanged.

The existing designbuild suite adds normal and very wide task-file fixtures which retain the real fixed nodes. The normal fixture exercises both outcomes: 1009x940 opens at 80%; 1366x768 fits at 71.0688%; 1864x949 fits at 84.6437%. The wide fixture opens at 80% at all three sizes. Each checks every actual node's top, document membership and unchanged stored positions. Both also open Thread and Inspector peeks and prove manual zoom/pan survives resize. An actual standalone .archhub file opens through openSession at each size with the same 80% left-edge fallback and zero top clipping. All files and profiles are synthetic and isolated.

Compiled manifest: b626f521301da12cbdced1751eb24cca81cdcafe4581fc845964265d5e87d9f7; 2057014 output bytes, 40 files; Babel 7.29.0. Focused proof on that compiled Studio:
```text
4 passed, 7 deselected, 1 warning in 40.28s
1 passed, 10 deselected, 1 warning in 23.49s
# tests 25
# pass 25
# fail 0
# skipped 0
TESTISO final profile leaks: []; protected write attempts: 0
```

The four cases are canvas_fit, fluid_shell, canvas_open and canvas_reading. The final single-case run adds the standalone-file proof to canvas_reading. The 25 Canvas regression cases also pass. At 1009x940, 1366x768 and 1864x949, Home, Canvas, Docs and Settings each report cut=0, opaqueStrip=0, floatingComposer=true. Opening captures and exact command output remain in ignored .cache/designv22g-{canvas_open,canvas_reading}-*.png and designv22g-{opening-ui,standalone-ui,opening-regressions}.log/.tap. git diff --check passes. Existing pytest cache_dir warning remains.

Not in this release: Invite/collaboration, because no verified collaboration-session owner is available; no dead Invite control was added. Not in this release: Packages browser, because no verified catalogue owner is available; the existing local mod manager remains. Not in this release: Layout presets, because the drawn disabled control had no working owner; the existing Arrange action remains. Not in this release: Home direction 2, deferred after completing the requested Resume direction. The fixed-node lane redesign, auto-arrange/layout rules and rail + picker remain outside this run by explicit instruction.

These are branch/build proofs only. No push, install or release was performed, and installed appearance is untested. Full suites and benchmarks were not run. One BelowNormal job and one headless browser ran at a time; each successful test closes its server and browser.
