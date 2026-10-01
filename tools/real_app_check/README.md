# Real-app check

The founder's rule: no ArchHub task is handed over or accepted without real-app evidence. That means
the installed build, run isolated on a hidden Windows desktop, with one screenshot per step showing
what was asked, what the real window did, and the screenshot. Courts are review evidence, never done
evidence. Every agent uses this one tool.

## Run

```
python -B tools/real_app_check/real_app_check.py --scenario tools/real_app_check/scenarios/smoke.mjs --out <new evidence dir>
```

Options:

- `--app <dir>`: the installed build (default `%LOCALAPPDATA%\ArchHub`). It is never modified. Its code
  is hashed before and after every run.
- `--overlay <dir>`: candidate files laid out like the app. Only files under the code allowlist
  (`nodelang`, `app`, `runtime`, `workflows`, `library`, `custom_nodes`, `ui_widgets`, `skills`,
  `launch_archhub_test.py`) are accepted. Each must be contained in the overlay folder and must not be a
  link; anything else is refused before any copy. The files are laid over a copy of the installed code
  in the run folder, and every report row is labelled `CANDIDATE OVERLAY`. If the overlay holds Studio
  `.jsx` files, the copy's compiled Studio is rebuilt with this repository's
  `packaging/compile_studio.cjs`. Re-run without an overlay once the change is installed.
- `--input <json>`: data handed to the scenario as `ctx.input`.
- `--winapp <exe>` or `ARCHHUB_WINAPP`: the winapp CLI that answers native Windows dialogs.
- `--boot-seconds` and `--probe-seconds`: bounds on app start and on the whole scenario.

Heavy runs go through the machine queue (`run-heavy.ps1`) like any test batch.

## Evidence

The `--out` folder must be new or empty. It receives:

- `steps.json`: one row per step, holding the label, what was asked, PASS or FAIL, what the window did,
  the data read, the HTTP errors, the expected refusals, and the screenshot path.
- One PNG per step.
- `native-folder-dialog.png`, when a step answers the Windows folder dialog.
- `launcher-stdout.log`.
- `report.json`, which holds:
  - the label, build and overlay files;
  - the run-unique desktop name and the app windows found on it;
  - the state files the app wrote in the run folder;
  - the boot time and the native dialog transcript;
  - the signing-key state before and after;
  - the installed-code digest before and after;
  - the overall result.

## Verdicts

A step passes only when its function returned `{pass: true}` with no failure reason, and every HTTP
error during the step is one it listed in `expected_http`. Any other return fails, including
`undefined`, `null` and `{}`.

A step this isolated run cannot honestly exercise returns `{not_exercised: '<why>'}` and is reported
as `NOT EXERCISED`, never as a pass. Such a run is `INCOMPLETE` (exit code 2).

Today smoke reports two such steps:

- **The Workspaces registry read.** It needs ArchHub's graph owner, which this run does not start.
- **Add.** It signs with the Windows user's protected key, which cannot be isolated, so it is never
  pressed.

The probe must finish. A scenario exports its step names as `steps`, and the harness prints them as
`DECLARED` before running. The run fails, whatever the step rows say, if any of these happen:

- the probe times out (`--probe-seconds`);
- it exits non-zero;
- it never prints `DONE`;
- the steps that ran differ from the declared ones.

The report is written on every path, including an exception, with the key state, the code digest and
the exception text.

The run passes only when all of these hold:

- every step passed;
- the app's window was on this run's own desktop;
- the app wrote its state in the run folder;
- the installed code is byte-identical before and after;
- the signing key is exactly and unchanged `absent` or `present:<hash>` (any other read fails).

## Guarantees

- **Hidden desktop.** `CreateDesktopW` creates a new desktop with a run-unique name; an existing name is
  refused. Nothing draws on the founder's screen. Native dialogs open there and winapp drives them
  there.
- **Isolated profile.** APPDATA, LOCALAPPDATA, USERPROFILE (with its shell folders), HOME, TEMP,
  CLAUDE_CONFIG_DIR and ARCHHUB_TEST_STATE_DIR all point into the run folder. The launch directory is
  the run folder too. Agent and session variables are dropped. The run gets its own lock port and its
  own CDP port. No bytecode is written.
- **One Job owns everything.**
  - A Windows Job object with kill-on-close owns the app, the scenario probe and every winapp helper,
    each assigned at creation.
  - Every wait is bounded.
  - The Job is terminated in `finally` on every exit path.
  - No process is ever killed by number.
- **No protected key.** The Workspaces signing key (`ArchHub-workspace-roots-v1`) lives in the Windows
  user's key store, which no environment variable isolates. Creating it shows a Windows prompt on the
  founder's desktop. The harness refuses to press Add, Remove, Republish and Stop governing
  (`guards.mjs`). The key is read silently (`NCRYPT_SILENT_FLAG`) before and after the run. Only
  `NTE_BAD_KEYSET` reads as absent; any other code is kept and fails the run.

## Scenarios

A scenario module exports `default async function (ctx)` and calls `ctx.step(asked, fn)` for each step.
`fn` returns `{pass: true|false, why, got, expected_http}`.

`ctx` provides:

- `js`: run an expression in the page.
- `mouse`, `rectOf` and `clickText`: real CDP mouse events at the element's centre.
- `until` and `sleep`.
- `native({kind: 'pick-folder', title, folder})`: answers a real Windows folder dialog. It types into
  the dialog's single Edit named `Folder:`, chosen by element type because a Text label shares that
  name. It verifies the typed path, then presses Enter until the dialog closes.
- `input` and `out`.

`scenarios/smoke.mjs` covers these steps:

1. Open the Studio.
2. Open each tab.
3. Place a library node.
4. Undo the placement.
5. Open Settings > Workspaces.
6. Browse: prove the chosen folder lands in the field.

## The run's own graph owner (designed, not yet launched)

Settings > Workspaces reads its registry from ArchHub's graph owner, the clean coordination service.
`graph_owner.py` plans the run's own owner, and courts prove the plan. `real_app_check` does not start
it until Ping has reviewed the plan.

The planned owner:

- **Provisioning.** The product's own `provision_clean_runtime` (`owner_provision.py`) runs under the
  run's environment. The runtime root, the authority DPAPI provider and the caller key store all
  resolve inside the run folder.
- **Pinned sources.** `SPEC.md` from this repository and `owner_grand_map.json` from this tool are
  pinned by sha256. A wrong pin refuses provisioning.
- **Ports.** Its own two free ports, never the live owner's 8474 or 8475. The desktop is pointed at it
  through `ARCHHUB_COORDINATION_ENDPOINT`, so no default endpoint is ever used.
- **Paths.** The owner's and the desktop's roots are resolved under the planned environment: the
  DPAPI stores, the runtime root, the runtime descriptor, Session Link state, assistant state and home.
  Every one must lie in the run folder.
- **Lifecycle.** It starts only through the run's hidden desktop, so the run's Job owns and ends it.

Workspaces **Add** stays `NOT EXERCISED` in real runs. It signs with the Windows user's protected key
(`CngSigner`, `ArchHub-workspace-roots-v1`), and the production signing boundary has no test seam by
design. Fixture signing belongs only in component courts, labelled `fixture-signing`.
