# MAINREL Round 2 independent source review

Verdict: CHANGES REQUESTED (two P2 findings); no P1 identified in this bounded source review. This is model source-review evidence only, never a Tier-L runtime/installed verdict.

Reviewed working tree at HEAD `10e40982b28d5e11c4f332112f37a36759a2ca14`; uncommitted Sandbox script SHA-256 `96D3F205D433E842CD380AA545874970607D1D1B6C8DBD10314CA83BF8D8B051`.

## Findings

| Priority | Exact source | Defect and trigger | Minimal fix |
|---|---|---|---|
| P2 | `installer/rollback-rehearsal.ps1:29-30,81-86,238` | Guest creates final `result.json` directly with WriteAllText. Host waits only for path existence, then immediately parses it. During guest publication the path can exist before its complete JSON arrives through the mapped directory; a successful rehearsal is spuriously rejected as malformed/empty evidence. | Publish the complete receipt to a temporary sibling, flush/close it, then rename to the final receipt name. Host polls only that final name. Do not retry effectful probes. |
| P2 | `installer/rollback-rehearsal.ps1:78-93,129,191-215,234-240` | The owned Sandbox is never closed. A host deadline throws while guest Setup/probe/app can continue; a guest step timeout records failure without stopping its owned Setup/app, and the Sandbox remains running after host return. This defeats the intended bounded single-job rehearsal and can keep consuming memory/disk and writing screenshots after a failed result. | Wrap the host Sandbox lifetime in try/finally and close only the Sandbox instance this invocation owns, with a bounded wait and explicit cleanup-failure receipt. Ensure the guest stops its own timed-out children or relies on confirmed disposal of that owned Sandbox; preserve result evidence and never target unrelated instances. |

## Reviewed constraints

- Three input mappings are read-only; only `results` is writable. Guest checks mapped plan plus WDAGUtilityAccount/profile and a different machine name before installer/app effects. Host refuses current ArchHub/ArchHub-Test and input-release output locations. No production profile access or installer execution was performed by this review.
- Host and guest verify real0400 digest `AB968ABE5B78DB0BE4C51C0321A2F1F5F6DA58B74914503A3AC3A9902C90F258`; main is bound to caller SHA and installed BUILD_ID. No fresh hash of the original installer was taken by this reviewer.
- `/SILENT` retains the progress wizard; setup polling captures screenshots. Automated screenshot count/hash checks do not establish that every long step visibly reports progress. Guard3 remains BLOCKED(sandbox) pending actual image/log inspection.
- Authenticated CDP probe reads readiness repeatedly but invokes seed/main/rollback effectful probes once only. Main writes a distinct graph marker; rollback must see it, open it, and use the same selected journal path. The inspected server routes/headers and launcher quit marker agree with current source. Real0400 behavior remains unexecuted.
- Typed measurement records preserve original observed numbers/booleans; Final migration deadline retains 30 seconds. This review makes no strict/compiler PASS claim.
- Home changes preserve assertions; admitted groups default open and remain collapsible. Rail respects an explicit current-state value while keeping its page default; workshop gets its Chats item. The harness stops before the authenticated owner read. No source defect found in these slices.
- Existing dry-run court receipt says `7 passed, 1 warning in 4.37s`; this reviewer did not execute tests, launch Sandbox/app/Setup, inspect installed profiles, or build. Test coverage presently exercises host/dry-run refusal and measurement preservation, not actual guest execution/receipt publication/cleanup.

WHY: bring the full-main install one measured guard closer while keeping the founder's active machine/profile untouched.
SOURCES: original RESULT-MAINREL.md, Round2 request, current diff/script/court; current application_server/universal_graphs/persistence/launcher/installer source checked against the probe.
FIT: retain one installer and one backup owner; isolated source review only.
DROPPED: installed acceptance, broad runtime verdict, build/install/process launches.
## Follow-up resolution review

Current source-only verdict: CLEAR for the two reported source defects; no remaining concrete P1/P2 found in this bounded follow-up. Script re-read SHA-256 `3C2574D9A5EFCFF0A629738CFA7AF623601713505CB874F4B5A2C16BCA0DA6A5`.

- Atomic receipt: lines30-33 write/close a unique same-directory pending file and move it to the final name. Guest final publication at265 now uses that helper; host polls only final result.json. The partial-publication P2 is resolved in source.
- Owned lifetime: lines81-114 retain exact process StartTime and use finally to close/wait on that process, with exact-PID plus StartTime verification before any forced exit. No process-name cleanup is introduced. Disposal metadata is retained separately; no receipt/delegation or unconfirmed termination exits nonzero. The missing-cleanup P2 is resolved in source.
- Screenshot capture now runs every5000ms while deadline checks remain every500ms; screenshot filenames are constrained to a flat PNG name before host hashing. Effectful probes remain single-attempt; journal path continuity and marker-open assertions remain intact.
- Runtime limitation remains explicit: the actual WindowsSandbox.exe instance/delegation lifecycle, guest Setup, visible progress and real0400 downgrade are unexecuted. A client process exit plus receipt is source-level custody logic, not independently measured proof that the guest VM was disposed. The Sandbox court must inspect `sandbox-disposal.json` and confirm guest disposal; guard3/guard7 remain BLOCKED(sandbox) until execution.

No tests, builds, launches, installed-profile reads, or product edits were performed in either review. Initial findings above are preserved as history; this follow-up supersedes their CHANGES REQUESTED verdict for the named script hash only. Current compiler and host-court reruns remain the builder/verifier's responsibility.

## Final source hash binding

Final source-only verdict: CLEAR, bound to `installer/rollback-rehearsal.ps1` SHA-256 `BB70096651D158DD8396F5573A6D0B2A742998FFB2BE0FE9B93CBB96ABDCAD56` read back in this review.

Compared with the prior reviewed script, the only additional edits are explicit Add-Type assembly-name array syntax and recording transient CDP readiness exceptions in `receipt.last_readiness_error`. No new effect, retry, isolation or acceptance behavior is introduced. The measurement driver's annotations changed from Final[float]/Final[bool] to float/bool and removed the Final import; deadline30.0 and initialFalse values and their uses remain unchanged. No concrete P1/P2 found in these final edits.

Compiler PASS, updated host dry-run receipts and actual Sandbox/runtime acceptance remain outside this source verdict. Guards3/7 remain BLOCKED(sandbox). No tests, builds, launches or installed-profile access performed by the reviewer.

## Desktop recovery composition follow-up

Source-only verdict: CLEAR for the explicit desktop re-export and real launcher call wiring. Reviewed exact file hashes:

- `nodelang/desktop.py`: `DE2AA7730C0576B2ED2E5439859B8A64C58A7E12C029799A7E4DB3B64BA3EB89`.
- `launch_archhub_test.py`: `F5FC0B0BC8BF382F2140F009D24F1ADF08FDBB255989EB4B9A8D13BE003F19D5`.

`desktop.py:13` exports the existing application_update_recovery module object; `_finish_application_shutdown` at launcher2363/2374 imports that object and calls its existing arm_update function. Args, close-before-arm order, rollback branch, instance fencing and failure handling are unchanged. This is an exercised production composition seam, not a second recovery owner or an unused import. Standard Python import caching retains module/monkeypatch identity.

Read the new import's transitive module headers: application_update_recovery imports recovery-files and recovery-restore-files; restore-files imports universal_cell. No reverse desktop/launcher import was found in these import paths and no file/database/window/worker construction was found at their module tops. The only earlier import work is loading function/class definitions, constants and regex patterns. No concrete P1/P2 found.

Required affected-court checks remain the builder's queued work: desktop import/entrypoint delegation, full affected shutdown tests, and update arming/refusal ordering. A useful direct assertion is that desktop.application_update_recovery is the canonical module and a monkeypatched canonical arm_update is called once after server.close with unchanged expected_build/source args; close refusal must prevent arming. No runtime/compiler PASS is granted by this review. Reviewer performed no tests, builds or launches.

## Final lazy desktop composition (supersedes transparent re-export)

Source-only verdict: CLEAR; no concrete P1/P2 in the replacement composition. Exact hashes read back:

- `nodelang/desktop.py`: `5A167B37DC00BF417BB64543B0D9D6C03B3B69A27017E50C3CC632517696107E`.
- `launch_archhub_test.py`: `F071EAA1A8092035BE39E61B885BA62B87B8B91E5E892CF32854F68C7D9E146F`.
- `tests_replica/test_mainrel_update.py`: `20B3F2E8900CDD01E150F1E494D77A8DB5DFA0BB424EFD86A306996DFF06CA82`.

The eager module re-export is gone. `desktop.arm_update` lazily resolves the canonical recovery.arm_update and forwards all four positional values plus expected_build once, returning its result. The real launcher imports this desktop composition function at the same point and invokes it after successful server.close. No backup/validation logic, second owner, new side effect, retry or import cycle is introduced; canonical monkeypatching remains effective because the function is resolved at invocation.

Read the added real callback court: it extracts `_finish_application_shutdown`, patches canonical recovery.arm_update, and checks successful quiesce/close/one-arm order with exact args. Its refusal parameter checks close refusal yields False and no arm. No assertion weakening found. This is suitable focused evidence for the changed composition; actual queued court/compiler results remain outside this review, which performs no runtime work. Sandbox guards remain BLOCKED(sandbox).

## Final native guest identity binding

Source-only verdict remains CLEAR at script SHA-256 `1534D640BF0FA72507BEE0C0A0256ECC02B53246C9390399F2B487C75D37BE9A`. Host output exclusions now use native LocalApplicationData. Guest mode first checks the exact mapped-plan name, actual WindowsIdentity account and native UserProfile; only after those guards does it set process LOCALAPPDATA from the native known folder and read the plan. Spoofing USERNAME/USERPROFILE no longer admits the host. Read the new host-spoof refusal test with the valid guest plan pathname; it preserves the refusal assertion. No new effectful retry, mapping, installer ownership or acceptance logic found; no concrete P1/P2. No reviewer runtime work. Actual Sandbox progress/rollback/disposal acceptance remains unexecuted and BLOCKED(sandbox); compiler/court receipts are separate builder/verifier evidence.

## Final parser-compatible known-folder binding

Source-only CLEAR at script SHA-256 `D35354F7FB930B3167C42C346B0D4E9E8C002DB2BEAA24FF969A176F1C50ECDA`. Exact diff contains only three GetFolderPath argument substitutions: enum-member syntax becomes the corresponding literal enum names LocalApplicationData/UserProfile, which PowerShell converts for the same native API call. Token check, ordering, known-folder selection and effects remain unchanged. No concrete P1/P2 found; no runtime/parser/compiler execution performed by reviewer. Sandbox acceptance remains BLOCKED(sandbox).
