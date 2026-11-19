# Decision log

Every architecture-class change (store, runtime, launcher, dependency, gate, top-level package, file over 3,000 lines) adds one entry here in the same commit. `.githooks/pre-commit` → `tools/pipeline/decision_check.py` refuses the commit otherwise.

Entry format:

```
## D-<nnn> <title> (<date>, <agent>)
Request: F<n>
Prior art: <product> -> <mechanism>; <product> -> <mechanism>
Replaces: <what is replaced and deleted in this patch> | nothing exists
```

Open RED decisions (taken before this gate; to reverse or fix): see `70.COMPANY/72.HANDOFFS/72.03-ARCHHUB-INTEGRATED-REPAIR/01.WIP/ARCH-DECISIONS-AUDIT-2026-10-17.md`.

## D-001 Restore the product pre-commit gate and refuse unrecorded decisions (2026-10-17, Claude c91e research)
Request: F76
Prior art: ArchUnit -> architecture rules fail the build; MADR/Nygard ADR -> one record per decision
Replaces: the .githooks/pre-commit deleted in 458fb512 (2026-07-27); this interim check is replaced by compiler E0600 (ACOMPILER3R) and then deleted

## D-021 Scrub retained ArchHub host bearers from Goose sessions.sqlite3 on startup (2026-11-19, Antigravity coordinator / Codex e988)
Request: F12
Prior art: Chromium/VS Code Credential Manager -> keep bearer tokens in process env/memory only; SQLite in-place header scrub -> sanitize legacy rows without touching user messages
Replaces: inline Authorization headers persisted in Goose sessions.sqlite3 extension_data (no new store is created; opens existing Goose sessions.sqlite3 strictly to scrub retained headers)

## D-022 Add highspy (HiGHS) solver dependency for Optimize and Schedule pure nodes (2026-11-19, Antigravity coordinator / Codex e988)
Request: F19
Prior art: SciPy linprog/milp (HiGHS backend) -> open-source MIT linear/MIP solver; OR-Tools -> bounded optimization nodes
Replaces: nothing exists (adds bounded MIT-licensed HiGHS wheel for pure Optimize and Schedule nodes)
