# REPOLAYOUT decision and Phase 1 measurement

Status: Phase 1 inventory; NO MOVES. Phase 2 requires coordinator 717's explicit go after in-flight lanes land. No installation, no push to main. Intent: NOGRAPH.

## Request and outcome

Founder, 2026-11-04, verbatim: "الفكرة إني بفتح كسم الاب حتى كمان مبفهمش حاجة" (when I open the app folder I don't understand anything). Earlier: "I want to open every folder and find its work inside, not register and readme files". Chosen answer: "Yes, one folder per part".

One Git repository and source rooted at `C:/Users/fargaly/00.ARCHUB/10.PRODUCT`, with real work directly inside each named part. This serves founder faces 1 (one source) and 10 (find everything in one place). Architecture-class, explicitly founder-approved. This record is the requested existing evidence location, not a second product plan.

## Prior art and fit

- Turborepo: application packages under `apps/*`, shared packages under `packages/*`; shallow part boundaries make ownership visible. https://turborepo.dev/docs/crafting-your-repository/structuring-a-repository
- Nx: flat or grouped project folders; project identity can remain independent of directory names. https://nx.dev/docs/kb/folder-structure

ADAPT the shallow, real-project boundary; KEEP one Git history, existing build/installer, exporter, compiler and hooks. Numbered parts fit the founder's workspace navigation and avoid another abstract apps/packages layer. No Turbo/Nx dependency, new orchestrator, runtime, store, or duplicate implementation is proposed.

## Replacement map (Phase 2 only)

| Actual source | Single destination |
|---|---|
| `01.APP` desktop application | `11.APP` |
| `06.CLOUD/public_site`, website deployment code in `03.TOOLS/packaging/website`, output of `01.APP/nodelang/site_export.py` | `12.WEBSITE` |
| `06.CLOUD/cloud_backend` and its Fly config; cloud deployment code | `13.CLOUD` |
| `04.DOCS` and canonical Book | `14.DOCS` |
| `03.TOOLS/installer`, release packaging scripts, release notes | `15.RELEASES` |
| `02.TESTS` | `16.TESTS` |
| remaining `03.TOOLS` build/compiler tools | `17.BUILD-TOOLS` |
| `05.EVIDENCE` | `18.EVIDENCE` |

The old outer `12.WEBSITE`, `13.COCKPIT-CLOUD`, `14.DOCS`, `15.RELEASES` each currently contains only README.md (286, 298, 281, 361 bytes). Remove their superseded pointer contents when real folders replace them; do not retain duplicate trees. Retire old 01-06 part names and the wrapper directory `11.ARCHHUB-APP`; Git history remains the history. Root repository metadata/configuration remains at the Git root.

Book source: `70.COMPANY/72.HANDOFFS/72.03-ARCHHUB-INTEGRATED-REPAIR/01.WIP/ARCHHUB-BOOK-target-product-2026-10-19.md`. Move the canonical copy into `14.DOCS` and leave one pointer at the old address, as explicitly requested. Before public tracking, inspect it for internal/private content; preserve the single canonical source and route any actual privacy conflict to 717. No Book bytes were copied during Phase 1.

The exporter imports sibling `nodelang` modules and currently defaults output to `01.APP/public_site` (site_export.py:1385), separate from `06.CLOUD/public_site`. Phase 2 must make `12.WEBSITE` the one output owner without breaking `nodelang.site_export` imports or duplicating source. Move deployment assets by ownership; classify shared packaging helpers individually.

## Baseline and scan method

Base: `8866b397f29f88cb005852618cc700c0ecd8aa0c`, clean on resume, equals fetched origin/main on 2026-11-04. Remote ref `lane/repolayout` created at this base through `gh api repos/Fargaly/ArchHub/git/refs`.

Read repository authority at actual `04.DOCS/{AUTHORITY,SPEC,FOUNDER_MANDATES,FAILURE_LOG}.md`; the generated AGENTS.md still points to nonexistent `docs/` paths. Fix generated links at their generating authority during Phase 2, never hand-edit generated AGENTS.md. The source layout itself reproduces the founder's problem: the real work is below 11.ARCHHUB-APP/01-06 while sibling part folders are README-only.

Scanned 1,775 repository text files, 45 hook files, 12 operation files, 76 lane briefs, and the release wrapper: 1,909 text files, no file-read errors. Exact file/line locators and per-scope counts are in `repo-layout-references.json`. Scope is tracked repository files plus text under the named hooks/operations and BRIEF-* files; caches/binaries/PROOF outputs are excluded. Counts are lexical candidates, not a claim that every occurrence breaks or that dynamic paths are statically decidable. ACOMPILER registry path strings, archived documentation and tests contribute many counts. Classify active paths versus historical prose before edits; no blind global replacement of installed/native paths.

| Reference token | Repository occurrences / files | External occurrences / files |
|---|---:|---:|
| `01.APP` | 1805 / 276 | 143 / 50 |
| `02.TESTS` | 1540 / 33 | 28 / 22 |
| `03.TOOLS` | 406 / 74 | 46 / 25 |
| `04.DOCS` | 101 / 28 | 16 / 12 |
| `05.EVIDENCE` | 150 / 32 | 16 / 14 |
| `06.CLOUD` | 158 / 17 | 4 / 3 |
| `old_repo_root` | 109 / 45 | 255 / 83 |

Other repo candidate counts: 725 implicit Python/path-depth references in 371 files; 96 website/exporter references in 19 files; 473 backend/Fly references in 48 files; 134 release-builder references in 42 files. The inventory records every matched line without copying source text, command arguments or secrets.

## Required fixes after go

1. Python/config: `pyproject.toml` pyright/pytest paths, `.vscode`, `package.json`, scripts, test conftest/bootstrap sys.path, imports of `tools`/`cloud_backend`, `parents[n]` and repository-root discovery. Preserve installed flat/native import fallbacks.
2. Packaging: `03.TOOLS/installer/build_release.ps1` already owns `$repositoryAreas`, `Get-RepositoryPath` and `Get-PayloadPath`. Update these for split app/tools/docs/releases and preserve native staging. Its tracked-input scopes, compiler toolchain root and selected snapshot must follow the moves. Inno `ArchHub.iss` currently fixes `{localappdata}/ArchHub` and native `{app}/nodelang`, `app`, `bridges`, `tools`, `docs`, `packed`, `runtime`, `licenses`, `wheelhouse`. Do not replace these with numbered source parts.
3. External release wrapper `%TEMP%/nograph-release/build.ps1`: hardcodes shared `%TEMP%/nograph-build` and `03.TOOLS/installer/build_release.ps1`. Phase 1 does not invoke that wrapper because it fetches/checks out the shared build tree. Use its existing release builder directly in this isolated lane; Phase 2 update wrapper and 717's invocation without creating a second release mechanism.
4. `.github/workflows`: selected checkout build path, compiler root, artifact and cloud/site Docker build contexts, COPY paths, Fly config and publish paths.
5. Compiler: `05.EVIDENCE/acompiler-intents.json` scopes, compiler `rules.json`, Rust/Python root detection, strict_check/runtime closure, ratchet and baseline/evidence discovery. Register both old and new paths during rename commit, then remove superseded paths consistently. Never bypass hooks or lower findings.
6. Hooks outside repo: active references in `agent_scope_gate.py`, `cde_gate.py`, `decision_check.py`, `domain_gate.py`, `native_workshop_launch.py`, `pretooluse_validate.py`, `validate_path.py`, `product-hooks/pre-commit`, its publication allowlist, plus generated instructions/README references. Their exact lines are in the inventory. Changes outside the public Git tree need 717's coordinated landing, not inclusion of internal hook content in the public repo.
7. Scheduled tasks: read-only `Get-ScheduledTask` found `\ArchHub Universal Desktop OneShot` with an action referencing `11.ARCHHUB-APP`; update the source path after root relocation, preserve all other action properties. No task was run or changed. `repo-layout-tasks.json` retains only task name/state/reference tokens.
8. `run-heavy.ps1`: 50.TOOLING owner stays in place; scan found no old product-area references in that script. `ledger_page.py` has a legacy root reference. Lane briefs have 209 old-root occurrences across 74 files plus per-area counts above. Update active lane paths after in-flight lanes land; preserve explicitly historical evidence.
9. Root relocation: 717 coordinates the main checkout root change to `10.PRODUCT`, Git common-directory/worktree administration and existing metadata, without moving any unrelated folder into public history. Reconcile WORKSPACE-STANDARD/generators, canonical Book pointers and registered source roots in the same rollout. This isolated builder never touches `ArchHub-Test` or `~/.archhub` and never uses the founder's screen.

## Measured payload and fitness budget

The unchanged release script's exact read-only `Read-ReleaseSnapshotManifest` was reused before runtime packing, not substituted with a new payload selector. `repo-layout-measure-source.ps1` records the script boundary and prerequisite initialization. No acceptance/admission was bypassed; this operation reads and hashes committed source only.

- Source snapshot: 578 files, 22,180,710 bytes, 11.4374151 seconds.
- Raw manifest SHA-256: `79fce07d66ff353dde3d2d550b54c8880a05b4809351938b9b75e3f73a6cde38`.
- Sorted native payload rows SHA-256: `8d9a57ef13309840c87bcaf6a046414ee96e3770d9842ac647a1d18e05b6465e`.
- Release script SHA-256: `fad1fa417e1d56b7029c20fdcf5474fd5d79683b50f0a814e779dc41014d5066`.

`repo-layout-source-manifest.txt` includes selected root/revision/build ID headers, which necessarily change after source relocation. Compare `repo-layout-payload-rows.txt` (source, native relative path, byte count, SHA) for stable file-list/content identity. Generated compiler/runtime/provenance outputs require their own completed-build comparison; source rows alone are insufficient. Relocated scripts whose contents change must be reconciled explicitly; a full byte-identical payload cannot be claimed if changed scripts themselves ship. No timestamp or provenance differences may be silently filtered into an equality claim.

Budget: zero changes to installed destination paths; identical native relative file inventory; identical file hashes for unchanged payload sources; every changed/generated shipped byte explicitly accounted for before asserting the founder's stronger byte-identical condition. Measure baseline and after elapsed time on the same queued build command; no after-move timing exists in Phase 1. No additional multi-GB working-tree copies.

Read-only installed directory presence is recorded in `repo-layout-installed.json`; it inspects only release directory names, never live stores/settings/secrets. Native installed layout must stay unchanged. This is presence evidence, not acceptance of installed behavior.

## Full-build result and hold

Baseline release build is measured separately by `repo-layout-baseline.ps1`, via `run-heavy.ps1 -Label "codex-repolayout baseline release build" -TimeoutMinutes 20`, same `build_release.ps1` and pinned Goose archive as the existing wrapper, no installer execution. See `repo-layout-baseline.json` / `.log` for actual elapsed time and outcome. The expected revision-bound broker review for 8866b397 is absent; requested from 717. The actual build attempt failed after 177.6878578 seconds with exit 1 at the required broker-review check; no output installer or source-manifest was produced by the full build. Runtime packing also printed an upstream olefile2.py Python 2 syntax warning. This is a failed-attempt duration, not a successful build time. Until a full build completes, there is no full installed-payload SHA or successful build-time claim.

Workshop sends addressed to `717` were recorded but returned "No live agent matches 717" on readback (messages 8ee3d3b1b1b74b669e3c1a5122331014 and f836884516004a1bb5cd626c13bf9207). Room note 3673875d97b9499bbe30821102dc39b5 requests current exact coordinator routing. Recorded is not delivered. Phase 2 remains stopped until an explicit go from the coordinator is observed, even if this Phase 1 evidence commit lands remotely.

Validation is limited to evidence/data consistency, PowerShell parsing and the mandatory pre-commit compiler; no app behavior was changed, no runtime test suite or installed acceptance is claimed. Phase 2 must run all tests at `16.TESTS`, the same release builder, before/after payload manifest comparison and independent review. No push to main, no installation.

Evidence representation: tab-delimited manifest bytes are retained as supported text evidence (.txt), unchanged from the release generator. JSON observed_wall_clock_s records a measurement, not a runtime behavior setting. The compiler resolves scope from committed HEAD; register these exact paths in a preliminary registry-only commit before admitting the evidence commit. No hook bypass or compiler rule changes.
