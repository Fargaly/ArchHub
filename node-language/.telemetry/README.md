# .telemetry/

Artifacts for ArchHub's product analytics pipeline. Inputs to and outputs of the
`product-tracking-skills:*` workflow chain — `model → audit → design → guide → implement`.

| File | What it is | Phase |
|------|-----------|-------|
| `product.md` | Product model — what ArchHub does, entities, value flow | model |
| `audits/current-state.yaml` | Snapshot of what's actually tracked today | audit |
| `tracking-plan.yaml` | Target tracking plan — desired event/trait surface | design |
| `delta.md` | Current → target diff. The implementation backlog | design |
| `implementation-guide.md` | SDK-specific instrumentation guidance | guide |

This folder is **not** a roadmap surface — `docs/ROADMAP.md` remains the single source of
truth per ROADMAP-MANDATE. Items here that need to land in product code get filed back
into the roadmap with a verifiable affordance + CDP proof gate per DEFINITION-OF-SHIPPED.

Re-run any skill with the same input set to refresh its artifact. Older audits are
archived under `audits/`; designs supersede in place with version bumps in the YAML
`meta:` block.
