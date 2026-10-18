# MAINREL: make the FULL main build safe to install today. The 8 PREMORTEM-A guards, measured.

Founder 2026-10-18 (via c91e): "يسطا أنا عاوز الابليكيشن يخلص هو ايه اللي عامل العطلة كل ده؟" (I want the app finished; what is causing all this delay?) and "عاوز الحاجات اللي هتتنفذ دي يتعدى عليها بعمق ونتأكد انها مش هتعمل مشاكل … زي القرارات اللي قبلها" (go over these in depth so they don't cause problems like the earlier decisions).
Main (>= d89a50fd: ADOPT + AGENTLINK2 + PRESENCE1 + DEADCODE + PRIVGRANT) has never been installed; the founder runs the 0400 hotfix line. The pre-mortem says the main build is GO only after 8 guards. You make every guard true and MEASURED, so 717 can build, gate and install. You do not install.

Tree = THIS lane (a fresh clone of product main; record its HEAD sha at start).

## INPUTS
- LANE-DISCIPLINE.md
- C:\Users\fargaly\00.ARCHUB\70.HANDOFFS\archhub-integrated-repair-20260909\01.WIP\PREMORTEM-A-graphdoc-mainbuild-2026-10-18.md
- C:\Users\fargaly\00.ARCHUB\70.HANDOFFS\archhub-integrated-repair-20260909\01.WIP\PREMORTEM-B-governance-compiler-gate-link-2026-10-18.md
- installer/build_release.ps1
- C:\Users\fargaly\AppData\Local\Temp\claude\C--Users-fargaly-00-ARCHUB\71743447-6dd5-4050-bc4f-d228f7a1d91e\scratchpad\foundergate1017\PROGRESS.md

## The 8 guards (PREMORTEM-A, verbatim intent)
1. Install backups go off C: (or Setup refuses unless >= 25 GB stays free after the copies) and Setup shows "over budget" plainly. Today each install writes 8.3 GB and C: had 22 GB.
2. Measure Setup backup time and startup migration on an 8 GB fixture journal: startup migration <= 30 s.
3. Setup shows visible progress for every long step.
4. DONE by 717: PRIVGRANT landed d89a50fd; the build runs from a CLEAN checkout (no staged files).
5. Land the Chats "New chat" fix from FOUNDERGATE run30 (read foundergate1017/PROGRESS.md; adopt its fix, credit it); release gate green on the BUILT app.
6. Fix the `shows_as` check named in PREMORTEM-A.
7. Rehearse rollback with the real installed 0400 installer (C:\Users\fargaly\00.ARCHUB\70.HANDOFFS\claude-codex-link-20260914\release-20261018-0400-fd62cb8\ArchHub-Setup-0.exe), record its sha256, on an isolated profile: main installs over 0400, then 0400 reinstalls and opens the journal main left.
8. One backup directory with one owner (installer vs app today): keep the installer's, retire the app's duplicate (replaced = gone).
AGENTLINK2 guards from PREMORTEM-B ride the same install script: migrate the Codex and Gemini connector configs (Gemini points at a deleted module), keep a file fallback while the desktop app is off.

## STEP 0
- WHY: the founder's installed app is 3 releases behind main; every safe, measured guard brings one install closer; a guard that only exists on paper fails him again.
- SOURCES: skill archhub-prior-art; PREMORTEM-A + PREMORTEM-B; installer/build_release.ps1 + the Inno script; foundergate1017 run30
- REVERSE: Squirrel.Windows → versioned app dirs with a delta rollback and an install log; Chrome updater → disk-space check before download, staged swap, last-known-good kept; Inno Setup [Code] → ProgressPage for long steps and a disk-space refusal before files are copied
- FIT: each guard = one change in the existing installer/app owners + one measured court; no second installer, no second backup owner.
- DROPPED: installing; touching %LOCALAPPDATA%\ArchHub or ArchHub-Test (isolated profiles only); paper guards.

## Courts
Targeted only, BelowNormal, one heavy job at a time (the founder works on this machine; Revit is open). Per guard: RED before, GREEN after, the measurement verbatim (seconds, GB). strict_check --changed PASS; zero-idle 2/2.

## Finish
MAINREL.patch against the recorded main sha + SHA-256; RESULT-MAINREL.md: one row per guard (DONE + evidence, or the exact blocker), measurements verbatim, REVERSE table. Commit.

## ROUND 2 (717, 2026-10-18 12:5x): answers to your HOLD rows; finish them
1. GRANTRECEIPT reconciliation: CLOSED, nothing for you to do. Main d89a50fd already contains the whole hotfix 4535ff53 receipt (record_grant_event in private_root_grants.py and application_server.py). The installed 1030 build and main carry the same change. Rebase onto current main HEAD (git fetch the product repo) before the final packet.
2. Compiler: the 9 new E0007 findings are yours. Fix them in the product, not by renaming or excluding. The timing/exit-status values and the 30 s migration deadline become declared parameters or typed constants where the compiler expects them. Use the ACOMPILER3R BOARD 20-22 diagnostics. strict_check --changed must PASS on your exact staged set.
3. The two Home assertions: SCREENS3 is paused, so you own them for this packet. Make the built main payload's Home courts GREEN without weakening any assertion. Post a NEED to SCREENS3 only if they truly belong to its design change.
4. Guard 3 (visible wizard) and guard 7 (real 0400 rollback): no disposable Windows exists. Windows Sandbox needs a founder system change plus a reboot, and 717 is asking him. Do not wait for that. Deliver a runnable script, rollback-rehearsal.ps1, that performs 0400 -> main -> 0400 inside Windows Sandbox (.wsb mapping read-only the release folders), records the screenshots and hashes, and exits non-zero on any failed step. Prove it parses and dry-runs; mark the two rows BLOCKED(sandbox) with the script ready.
5. Built-payload gate: 717 builds from your final packet on main and the verifier runs it; you do not build.
Finish: new MAINREL.patch against current main + SHA, RESULT row per guard updated, strict PASS.

## ROUND 3 (717, 2026-10-18 15:3x): independent review RETURN of MAINREL f4e814fe (patch 353c8f62). Fix all, one patch on current main.
P1. Every update after the first is refused (application_recovery_files.py:313, :276-289, budget 10 GiB :164). The first main install pins an 8.3 GB copy ("retain until user deletes"). The next install adds a second 8.3 GB copy, and 8.3 + 8.3 > 10.7, so Setup refuses forever. Fix: the pin is replaced by the new verified copy, or excluded from the budget. Court with REAL-SIZE accounting (sparse/large fixture, not small files): install 1, install 2 and install 3 all pass.
P2a. Backups must be able to go OFF C: (guard 1's actual intent; the founder's C: is ~29 GB free and each backup is 8.3 GB). Add one backup-location parameter (a visible Settings/node parameter, not a hidden constant). By default it picks the local fixed drive with the most free space when C: would drop below 25 GiB. The installer owns it, and the app reads the same value. Adopt existing 0400 copies under ArchHub-Test\backups into retention (an owner, so they are pruned by the same rules; never deleted before a newer verified copy exists).
P2b. The quiet updater (quiet_update.py:528, /VERYSILENT, 600 s) hides "over budget" and can time out mid-backup, leaving an 8 GB -pending copy. The timeout must cover the measured backup with margin, or the updater waits on setup.tmp. A Setup refusal reason reaches the user verbatim. A partial -pending copy is cleaned on the next run.
P2c. Connector preflight (assistant_registration.py:693, ArchHub.iss:599): an unknown shape of an old entry must not block the whole install. Leave it untouched, log it, and name the file and the reason in the Setup message.
P3. Move the connector migration BEFORE files are replaced (ArchHub.iss:457), or make it non-fatal after. Do not prune older copies when the budget check will refuse anyway (:276 vs :283). Do not refuse at :343 when nothing new was written. Make 0400's retention (backup_retention.py:141) tolerate the new marker, or write the marker so 0400 can read it (rollback must not crash). Prove Gemini receives GEMINI_SESSION_ID in a real process, or record it as an open row. rollback-rehearsal.ps1: networking off; wait for the real Sandbox process; size the guest disk check correctly.
Finish: new MAINREL.patch + SHA, RESULT rows, strict PASS, the real-size retention court GREEN.

## ROUND 3 ADDENDUM (717, founder 2026-10-18: "شوف حل تاني" then "Yes, go"): rehearse on GitHub's disposable Windows, not Windows Sandbox
Windows Sandbox will not be enabled on this machine. The founder approved a PRIVATE repo, https://github.com/Fargaly/archhub-rehearsal (created, empty), whose GitHub-hosted windows-latest runner is the disposable Windows.
Deliver installer/rollback-rehearsal-ci/ in this lane:
(a) .github/workflows/rollback-rehearsal.yml (workflow_dispatch with inputs base_tag and candidate_tag). It downloads ArchHub-Setup-0.exe for both from that repo's Releases (gh release download), verifies the sha256 of each against the release notes, and runs your existing rollback-rehearsal.ps1 logic in guest mode on the runner: install base (0400) -> create the synthetic 8 GB fixture journal -> install candidate (main) -> reopen -> reinstall base -> base opens the journal main left. Each step has a screenshot and timing, and the run exits non-zero on any failure. Upload results/screens/logs as the run artifact.
(b) Make the script's guest guard accept the GitHub runner (the RUNNER_OS/GITHUB_ACTIONS env plus a runneradmin profile) the same way it accepts the Sandbox account. It still refuses on any other machine.
(c) Any hosted-runner limits you find (disk ~14 GB free on D:/C:, 6 h job cap): size the fixture and backup location to fit and document them. If 8 GB cannot fit, use the largest size that fits plus the 8.94 GB local measurement already taken, and say so plainly.
You do NOT push and do NOT create releases. 717 uploads the installers and runs the workflow. Return the workflow + script paths in RESULT.
