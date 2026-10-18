# MAINREL read proof
## LANE-DISCIPLINE.md
SHA256 98CE9A8DE61D7859BCB383B9276765F36620F67AB14108FA8AD38BACC6427DA9
> # FIRST: load skill founder-intent (one source: ~/.claude/rules/intent-decoder.md). Build to his verbatim words and the reason behind them, never to a paraphrase.
> # ALSO FIRST: load skill archhub-prior-art (the distilled ADOPT / LEARN-ONLY decision per part + licence rules). STEP 0 cites it first; re-research only when a listed source is dead.
> # RULE 0.5, PRIOR ART BEFORE CODE: a HARD gate (founder: "I said from the start: research before building, see what was done, take it and adapt it")
Requires: implement and measure the eight guards and connector migration; do not install into founder profiles.
## C:\Users\fargaly\00.ARCHUB\70.HANDOFFS\archhub-integrated-repair-20260909\01.WIP\PREMORTEM-A-graphdoc-mainbuild-2026-10-18.md
SHA256 7A14F579DC4E25219602A3AA56A1AC30D126417A595F191C1CA2BF2C67C87A74
> # PRE-MORTEM A: GRAPHDOC and the main-HEAD build (2026-10-18)
> Asked by the founder: "عاوز الحاجات اللي هتتنفذ دي يتعدى عليها بعمق ونتأكد انها مش هتعمل مشاكل … زي القرارات اللي قبلها" (go over what is about to be executed in depth and make sure it will not cause problems, like the earlier decisions did).
> **Verdicts:** A) GRAPHDOC is **NO-GO**. B) The main-HEAD build is **NO-GO as it stands**. It becomes **GO-WITH-GUARDS** once the 8 guards in §B.5 are met.
Requires: implement and measure the eight guards and connector migration; do not install into founder profiles.
## C:\Users\fargaly\00.ARCHUB\70.HANDOFFS\archhub-integrated-repair-20260909\01.WIP\PREMORTEM-B-governance-compiler-gate-link-2026-10-18.md
SHA256 2C93669895F682F1D09A23B96251063A52FB6A1052F00557E5357B0F24B9B55D
> # PRE-MORTEM B: GOVSLIM, ACOMPILER3R, FOUNDERGATE, AGENTLINK2 and the product hook path (2026-10-18)
> Asked by the founder: "عاوز الحاجات اللي هتتنفذ دي يتعدى عليها بعمق ونتأكد انها مش هتعمل مشاكل … زي القرارات اللي قبلها" (go over what is about to be executed in depth and make sure it will not cause problems, like the earlier decisions did).
> **Verdicts:**
Requires: implement and measure the eight guards and connector migration; do not install into founder profiles.
## installer\build_release.ps1
SHA256 031634C6F6147C1885C9732831C9A85D5618E07927907E91F2D1BF034B1E6BB9
> [CmdletBinding()]
> param(
>     [Parameter(Mandatory = $true)]
Requires: implement and measure the eight guards and connector migration; do not install into founder profiles.
## installer\ArchHub.iss
SHA256 4434CF40DA1343116D3CEE3F8AB714208A5998ECD18371D54DBC2629BC927B58
> ; ArchHub installer -- one double-click for a colleague.
> ;
> ; It carries the application, fetches Python 3.14.7 from python.org (pinned
Requires: implement and measure the eight guards and connector migration; do not install into founder profiles.
## ..\foundergate1017\PROGRESS.md
SHA256 984FD6DE375A677669356271BA716D38CC0C6B22878AA20A84AAE4FCCC15734E
> # FOUNDERGATE progress
> - 997d944: first commit adds READ-PROOF and ledger.
> - a4affb9: pinned Playwright suite, hidden-desktop helper, release asset quarantine and blocking post-build hook (WIP verification).
Requires: implement and measure the eight guards and connector migration; do not install into founder profiles.

## Round2 dispatch and runtime boundaries
Input: BRIEF-MAINREL.md, SHA256 1e1966dceb0e670c6513e72d838987700739f28f2aa39fc3dca5e7cb010a9e74
> The timing/exit-status values and the 30 s migration deadline become declared parameters or typed constants where the compiler expects them.
> The two Home assertions: SCREENS3 is paused, so you own them for this packet.
> Built-payload gate: 717 builds from your final packet on main and the verifier runs it; you do not build.
Requires: current-main patch; typed evidence/constant fixes, retained assertions, ready parsed/dry-run Sandbox script; no release build/install. Parent ../../AGENTS.md is absent in this temporary clone; exact workspace contract supplied in task.
Primary source read: Microsoft Sandbox configuration, https://learn.microsoft.com/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-configure-using-wsb-file ; read-only release mappings and LogonCommand, no copied source.

## Round3 BRIEF-MAINREL.md
SHA256 eb95377769d238eb36db1b026a56afdf49656fab8245500f68fc0e07a5594d2b
> ## ROUND 3 (717, 2026-10-18 15:3x): independent review RETURN of MAINREL f4e814fe (patch 353c8f62). Fix all, one patch on current main.
> P1. Every update after the first is refused (application_recovery_files.py:313, :276-289, budget 10 GiB :164). The first main install pins an 8.3 GB copy ("retain until user deletes"). The next install adds a second 8.3 GB copy, and 8.3 + 8.3 > 10.7, so Setup refuses forever. Fix: the pin is replaced by the new verified copy, or excluded from the budget. Court with REAL-SIZE accounting (sparse/large fixture, not small files): install 1, install 2 and install 3 all pass.
> ## ROUND 3 ADDENDUM (717, founder 2026-10-18: "شوف حل تاني" then "Yes, go"): rehearse on GitHub's disposable Windows, not Windows Sandbox
Requires: Replace the pin; preserve real-size accounting; deliver the private Windows runner without uploading or executing it.

## Round3 C:\Users\fargaly\00.ARCHUB\00.GOVERNANCE\FOUNDER-FORBIDDEN.md
SHA256 dbbca4aa5e603931fe1fdbd28d5efaf169193513a2e0bb5cd0c56696b0a2248f
> | F15 | Leaving his own machine's disk or memory exhausted by our runs | a lane launched under 25 GB free on C: or 8 GB free commit | "فاشخين الريسورسيز" (you are wrecking the resources) |
> | F7 | Installing a build not from main as "the update", or installing without the full gate + design check | BUILD source revision not on main; install without a gate receipt | no-install-without-full-gate (10-15) |
> | F1 | Permissions, grants, locks or key prompts that STOP his own agents' work in his registered workspaces. The permission SYSTEM stays ("مبقولش نمسح البيرميشن سيستم", "I am not saying delete the permission system"); it applies at real boundaries (other people, client data, public) | a grant/permit/lock/key-prompt path on the founder's own agent → own workspace route; a "Grant access" step required of him | "البريميشنز وقفل الشغل … متتكررش" (permissions and work-locking … must not happen again) + "مبقولش نمسح البيرميشن سيستم" (I am not saying delete the permission system; 10-18) |
Requires: Keep resource headroom, do not install, preserve real owner/workspace boundaries. Record the F15 fixture incident without claiming an exception.
