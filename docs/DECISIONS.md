# Decision log

Every architecture-class change (store, runtime, launcher, dependency, gate, top-level package, file over 3,000 lines) adds one entry here in the same commit. `.githooks/pre-commit` → `tools/pipeline/decision_check.py` refuses the commit otherwise.

Entry format:

```
## D-<nnn> <title> (<date>, <agent>)
Request: F<n>
Prior art: <product> -> <mechanism>; <product> -> <mechanism>
Replaces: <what is replaced and deleted in this patch> | nothing exists
```

Open RED decisions (taken before this gate; to reverse or fix): see `70.HANDOFFS/archhub-integrated-repair-20260909/01.WIP/ARCH-DECISIONS-AUDIT-2026-10-17.md`.

## D-001 Restore the product pre-commit gate and refuse unrecorded decisions (2026-10-17, Claude c91e research)
Request: F76
Prior art: ArchUnit -> architecture rules fail the build; MADR/Nygard ADR -> one record per decision
Replaces: the .githooks/pre-commit deleted in 458fb512 (2026-07-27); this interim check is replaced by compiler E0600 (ACOMPILER3R) and then deleted

## D-002 BABOOM presence defaults to the tray; no new store (2026-10-18, Claude 717)
Request: F31
Prior art: Windows notification area -> status as a tray badge and tooltip, details on click; Discord/Slack tray presence -> background agents live in the tray, never float over other apps
Replaces: the always-on-top BABOOM companion window and its floating "Reconnecting to ArchHub…" panel and "Open ArchHub" button (removed in this patch). The "new store" flagged by decision_check is a test fixture opening a scratch SQLite file inside tests_replica/test_presence1_acceptance.py; no product store is added.
