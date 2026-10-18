# Lazy-boot extraction proposal review

Independent source-only review. **CLEAR** for the corrected proposal bytes
below. No execution, heavy job, product edit or claimed-test-path edit performed.

## Initial issue rejected before execution, then corrected

The initially proposed endpoint at authenticated `const graphIndex = await jget(...)`
also captures the preceding executable statement:

```js
const {nodes, wires} = window.ARCHHUB_EXISTING_WORKSHOP.getSnapshot().topology.graph;
```

`mountStudio` evaluates `bootstrap` at test line 100, before constructing its
stub `ARCHHUB_EXISTING_WORKSHOP` later in the function. Thus the wider extracted
slice accesses an owner not initialized at that execution point. This is a
harness failure, not proof of a product failure.

The corrected patch and driver now both use that exact `const {nodes, wires}
= ...` statement as the exclusive end of the declaration slice, and assert
the boundary exists after projectStudioCanvas. This excludes the premature
owner read. The existing index-bootstrap evaluator at test line 147 supplies
`nodes,wires` locally, so no assertion or tested behavior needs removal.
The initial graphIndex proposal was rejected before execution; no result from
it is claimed. No remaining concrete source issue identified in the correction.

## Driver/source limits

| Item | Source review |
|---|---|
| Claimed path | Driver reads the original test and refuses unless the old extraction boundary occurs exactly once. It writes only a new tmp-base file and refuses an existing target. Original claimed test is untouched. This does not constitute a grant to land the repair in SCREENS3's owned file. |
| Same product root | Both tests_js and tmp-base are one directory below product root; the test's `path.resolve(__dirname,'..')` and module dependency search retain the same product root. |
| Behaviors | String replacement changes only the boundary plus a boundary assertion. All original tests/assertions remain in the copied file. All three named JS files are passed to Node with concurrency 1. |
| Cleanup | finally removes only the exact temporary test file with Remove-Item -LiteralPath. It leaves original source, products, evidence and unrelated tmp-base contents untouched. |
| Execution | Driver does not compile Studio or run itself through run-heavy; caller must retain the existing sequential BelowNormal admission. No execution is authorized by this review. |
| Artifact provenance | The existing test reads compiled/manifest.json and compiled files, but studio-lm.jsx is specially transpiled from current source with Babel inside the harness. A passing result is a JSDOM source/compiled-components court, not a full-built-app or installed-app verdict. Requests remain fakes. |
| Profile | Driver redirects process environment to an isolated evidence profile. It runs no desktop launcher/installer. This is not KnownFolders/HKCU isolation for a real installer. |

## SHA-256 reviewed

| File | SHA-256 |
|---|---|
| evidence/mainrel/lazyboot-harness-proposal.patch | BCF90BBDB1C6D0CD958785B9D0E9A270B5BF8B86CA241C458F3A941C16EE942A |
| evidence/mainrel/run_lazyboot_proposal.ps1 | 0B2D7EB67BE87AC151BBAB82D3612DD25607F12C00911E479BA8D1768907D2C3 |
| tests_js/studio_lazyboot_home.test.cjs (read-only original) | 965B0893E73E5348463A909692C39441A74A1CA37B838C58120E821A597BDE43 |
| nodelang/studio/studio.html | 41B1F8E103F3015085D62E11A501BEB4B615FBCFB2FCC87D57FD49EA6D00FCA7 |
