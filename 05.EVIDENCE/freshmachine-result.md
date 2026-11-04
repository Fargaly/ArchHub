# FRESHMACHINE — candidate, not release acceptance

Coordinator: 717. Intent: NOGRAPH.
Base: a88f97525e726d021bc75a39e6e5c8050dd841ea.

## Resumed verification (Codex running the assigned Gemini lane)

- Resumed HEAD: `4662bb04074452e8d35489879774fadbbc5c9599`; remote lane
  already existed at that SHA. No reset or recreation of the remote ref.
- Current GitHub Latest was downloaded again with gh and matched the release
  identity and SHA-256 below. Receipt: `freshmachine/resume-latest/release.json`.
- The guarded installer court again refused before executing the installer;
  `freshmachine/resume-latest/result.json` records `ok: false`.
- Inventory regenerated: `4615` reference rows. Matches include optional tools,
  comments and examples; this number is not a runtime dependency count.
- Focused resumed courts: `58 passed in 208.53s (0:03:28)` and
  `PROFILE-WRITE-GUARD: protected write attempts=0`.
  JUnit: `freshmachine/resume.xml`.
- Intent author follows the assignment: `gemini-freshmachine`; executor is Codex.
- Resumed implementation compiler admission: `ACOMPILER PASS` through
  `run-heavy.ps1`; commit hooks are retained and run again for the final index.
- This remains an incomplete lane candidate, not a working released-installer
  claim. Full installer execution needs an isolated Windows account or VM,
  because profile environment overrides cannot isolate the production installer.

## Latest release observation

```text
LATEST: build-20261104-1059-b9c88da ArchHub-Setup-0.exe sha256=2212dca282e109f290c7e6e468314aea2e8555e74e34b5fb0ec5ca7626248ce3
CLEAN PROFILE: FAIL: REFUSED: Windows account contains protected ArchHub state; environment variables do not isolate installer HKCU/shell folders/tasks
```

Downloaded with gh. Installer was NOT executed. No claim is made about actual
missing-module, first-run, or Workshop failures in that release.

ArchHub.iss uses the original AppId (line 69), Windows shell localappdata
constants, task End/Delete calls (RemoveRetiredRuntimeTask), and a closed-profile
backup before files install. /DIR plus redirected environment variables does
not isolate those effects. Existing behavioural installer courts compile an
isolated harness specifically because the production installer has these effects.
A disposable Windows account or VM is required to execute the release safely.
No founder app, Workshop DB, ArchHub-Test, ~/.archhub, or screen was used.

## Candidate repair

The gateway previously required workspace-only .rulesync files before it could
stamp governance; the regression reproduced that missing path. It now defaults to the shipped product onboarder on every PC; only an explicit governance override selects an external source. Product rules are generated from shipped
SPEC.md rather than hand-copying private founder governance; hooks use the
existing installed registration/rendering owner. Release manifest validation
requires those sources. Consent, foreign-gate conflicts and native trust remain
under the existing owner; saved configuration is not native activation proof.

## Open acceptance items

- Whole installer execution, first-run and headless installed shortcut have not
  been observed. The new automated court refuses this protected Windows account.
- OpenCode's external pre-tool governance gate is still absent. Other external
  agents without a product adapter remain unsupported; no successful enforcement
  is asserted for them.
- Workspace-only filer/persist/rulesync governance has not been made portable in
  its entirety. Product specification rules are not represented as the private
  founder ledger.
- Python still bootstraps from the pinned python.org download when absent; the
  payload is not entirely offline on a PC without Python.
- Source inventory rows include comments/examples; they are a reference list,
  not proof that every mentioned dependency executes at runtime.

## Checks

Initial gateway regression: 1 failed, 1 passed; protected write attempts=0.
Final lane courts: 59 passed in 231.08s (0:03:51); protected write attempts=0. Implementation admission is enforced by the product pre-commit compiler; exact admitted revision is the implementation commit in git log.

## Broader diagnostic run

```text
4 failed, 113 passed, 17 errors in 336.13s (0:05:36)
PROFILE-WRITE-GUARD: protected write attempts=0
```

Raw JUnit: `freshmachine/focused.xml`.
- Seventeen assistant-registration fixture errors: `profile.mkdir()` encounters
  the profile already created by the shared court isolation fixture.
- Workshop Cursor expectations differ from current queued-hook delivery and
  admitted discovery behaviour; those production behaviours were not changed here.
- The colleague desktop boot import list still names the absent retired module
  `nodelang.baboom_attach`.
- The window-icon court asserts source text in launcher.py; the window now lives
  in nograph_launcher.py. It is not an installed visual check.

These remain recorded failures, not passing release evidence. This lane does
not change unrelated Workshop delivery or substitute those assertions for the
requested clean installed-app test.
