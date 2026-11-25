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

## D-023 Scope Goose session scrub to data/sessions/sessions.db, archhub-hosts, and exact whole-value reference check (2026-11-19, Antigravity coordinator / Codex e988)
Request: F20
Prior art: Goose 1.54 layout -> data/sessions/sessions.db; scoped header scrubber -> strip only archhub-hosts non-exact-reference headers while preserving unrelated MCP headers and exact ${ARCHHUB_HOSTS_TOKEN} references
Replaces: D-021 legacy-only sessions.sqlite3 path and substring check (opens existing Goose DB via contextlib.closing; no new store)

## D-024 Decode DWG database tables before publishing reviewed exports (2026-11-21, Codex)

Request: F20. Apply the selected Projects export setup and DWG version to the reviewed Revit export. A matching six-byte version header alone previously allowed a truncated drawing to be published.
Prior art: ezdwg 0.21.3 -> decodes header variables and layouts in the Python process. GNU LibreDWG 0.14 dwgread -> independently opened the same 2013 and 2018 drawings on Windows, reporting some unsupported fields. Use ezdwg through the existing offline Python installer. Its MIT-licensed CPython 3.10+ ABI Windows x64 wheel is 1,854,853 bytes. The alternative Windows x64 CLI distribution is 12,084,779 bytes and requires a separate executable.
Replaces: six-byte-only DWG validation. Check each staged drawing's version, decode its header variables and require a readable layout table before publishing. Compare the complete file inventory and SHA-256 digests after moving the directory.
Evidence: LibreDWG's 30,782-byte 2013 Polyline and Autodesk's 65,888-byte 2018 Structural - Metric sample passed. Header-only and half-truncated fixtures were refused. These checks establish table readability and file-set integrity. Native Revit export, embedded reference resolution after relocation and installed execution require separate evidence.

## D-051 Connections: social and connector grants follow the ArchHub account (2026-11-25, Claude socialconnect builder)
Request: F426 (NEWPC-PORTABILITY, connections section) and founder 2026-11-25 "كل الكيز دي المفروض تبقى مربوطة بكسم الأكونت بتاعي أصلا أنا مش فاهم ليه كل مرة بنقعد نزيد ونعيد" + "الأكونت بتاعي في اركهب" (every key bound to his ArchHub account; never re-entered after a reinstall, new profile or new PC). Connections section of D-051 (everything moves to another PC with nothing lost).
Prior art: Zapier connections -> OAuth grants held per account on the server, refreshed there, usable from any device; n8n Cloud credentials -> encrypted at rest with an instance key, listed without secrets, decrypted only at execution; Make connections -> one connection per account reused by every scenario, removed once for all.
Replaces: machine-only custody of social tokens in this PC's DPAPI secrets.dat (social_custody.py); secrets.dat stays as cache and offline fallback. New store: the one D-051 account-sync owner (06.CLOUD/cloud_backend/account_sync.py, per account under the replica volume) with namespace connections/ encrypted at rest under a random key the cloud makes at first use (account_sync.key on the data volume, owner-only; never derived from or wrapped with an OAuth secret, never in env or logs). If the volume loses the key, each connection reads "needs reconnect": a PC still holding it re-uploads it, otherwise Settings > Social asks to reconnect. Refresh tokens stay on the cloud.
Budgets: one manifest read per sign-in or Settings > Social open; one POST per credential resolve (5 s timeout, falls back to cache); each connection record is under 1 KB.
