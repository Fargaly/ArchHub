# MAINREL disposable Windows rehearsal

Owner:717. Public test harness; use only the founder-approved PRIVATE Fargaly/archhub-rehearsal repository. Source code and synthetic data only. No client files, account exports or live-profile copies.

Copy this folder's `rollback-rehearsal.ps1` (to `installer/rollback-rehearsal.ps1`) and this folder's `prepare-rehearsal.ps1` into the same relative `installer/` paths in that repository. Copy `.github/workflows/rollback-rehearsal.yml` from this folder to its repository-root `.github/workflows/`. MAINREL neither pushes nor publishes releases or starts a workflow.

717 publishes the real0400 and clean-built candidate installers as two private Releases, each with asset `ArchHub-Setup-0.exe` and exactly these note lines (actual values):

```
BUILD_ID: <build id>
SHA256 ArchHub-Setup-0.exe: <64 hex> (<bytes> bytes)
```

Dispatch `rollback-rehearsal` with `base_tag` and `candidate_tag`. Contents permission is read-only. Checkout/upload actions are pinned to verified v7 tag commits. Release hashes are checked against notes; real execution additionally requires the pinned0400 hash and Setup's Python3.14.7 hash. The workflow downloads Python before running the installed application. Checkout credentials are not persisted; token environment variables are removed from the application step.

The native Windows account/profile must be runneradmin/C:\Users\runneradmin, with the expected hosted-runner metadata, repository and run id. Spoofed environment variables on the founder's account fail before any installer or app effect. Sandbox mode remains available and disables its guest network; hosted Actions needs networking for release/prerequisite staging and artifact upload. The GitHub branch never shuts down the runner before upload.

The shared script installs0400, opens and seeds its actual journal, closes it, pads that SQLite journal, installs main, opens/writes through main, reinstalls0400, and reopens the SAME physical journal and main-only marker. Setup screenshots are captured every5s; app screenshots, installer hashes, per-step seconds, Setup logs and result.json are uploaded even on failure. A missing desktop/screenshot, wrong build/hash, missing marker, failed close or timeout is failure.717 independently inspects wizard screenshots; script availability alone closes neither guard3 nor7.

Disk sizing uses actual fixed-drive free bytes. A distinct backup drive is preferred for the fixture; the script sets the ONE installer-owned backup_location preference. It reserves6GiB for remaining payload work,256MiB on a separate backup drive (25GiB on the system drive), plus64MiB growth headroom. The requested journal is8,937,168,896bytes; after the first real boot the largest MiB-aligned size within those budgets is chosen. The result records requested/target/actual bytes and reduced_for_capacity. If it cannot fit at least the existing journal or256MiB, it fails; no smaller fixture is described as8GB. The prior dense local8,937,168,896-byte calibration remains in the MAINREL packet (`evidence/mainrel/big-measurement.json`: backup227.70879669999704s, migration4.34308580000652s); it is not a remote installed result or a six-million-cell benchmark.

GitHub documents private standard Windows runners as2CPU/8GBRAM/14GBSSD and a6-hour job execution cap. The workflow uses windows-latest and timeout360minutes; these specifications do not establish actual free space or desktop availability. Sources checked2026-10-18: [runner hardware](https://docs.github.com/en/actions/reference/runners/github-hosted-runners), [job limits](https://docs.github.com/en/actions/reference/limits). A low-capacity or noninteractive runner remains a recorded blocker; no founder Windows feature change is required.

Local dry-run uses inert fixtures and an explicit lane-owned WorkRoot:

```powershell
.\installer\rollback-rehearsal-ci\prepare-rehearsal.ps1 -DryRun -WorkRoot '<new isolated folder>' -BaseInstaller '<inert0400>' -CandidateInstaller '<inert main>' -BaseNotes '<matching note text>' -CandidateNotes '<matching note text>' -PythonInstaller '<inert prerequisite>'
```

Dry-run writes mode DRY-RUN; the guest guard refuses it. It performs no downloads or installation and cannot generate PASS. Existing plan evidence is never overwritten.
