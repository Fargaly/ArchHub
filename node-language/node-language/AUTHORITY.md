# Node Language authority index

Date: 2026-07-16
Status: active precedence and supersession index

This index prevents research notes, implementation comments, stale counts, and
legacy screens from becoming accidental product authority.

## Precedence

When two sources conflict, the higher source controls. A lower source remains
evidence and MUST NOT silently override the higher source.

| Order | Authority | Controls | Does not control |
|---:|---|---|---|
| 1 | Current explicit founder decision and founder Core Values source | Product intent, constitutional priorities, acceptance/rejection | Physical implementation details by itself |
| 2 | `SPEC.md` | Universal Cell product architecture, normative requirements, courts, migration conformance | Mutable progress or release status |
| 3 | `00.GOVERNANCE/WORKSPACE-STANDARD.md` | Workspace placement, privacy tiers, CDE custody, generated agent contract | A second node ontology or product completion |
| 4 | Released protocol/design/security decisions explicitly incorporated by `SPEC.md` | Detailed protocol contracts inside their stated scope | Requirements outside that scope |
| 5 | Grand Map source graph | Product requirements, dependencies, parameters, domain scope | Physical kernel semantics or hand-written progress counts |
| 6 | Revision-bound implementation evidence | What exact code/artifact passed exact courts in an exact environment | Target architecture or untested completion |
| 7 | Research, model-room transcripts, audits, legacy code, screenshots, comments | Evidence, alternatives, failures, visual/behavior reference | Active authority unless promoted through levels 1-4 |

## Active sources

### Constitution

- Founder Core Values source, snapshot and translation recorded by
  `30.KNOWLEDGE/strategy/core-values-governance-authority-2026-07-16.md`.
- Translation status is WIP until founder-reviewed and released. Partial coverage
  MUST NOT render compliant.

### Normative product target

- `10.PRODUCT/13.NODE-LANGUAGE/SPEC.md`

There is one active Node Language product specification. It contains no mutable
test count, percentage, deployment, or completion claim.

### Workspace and information governance

- `00.GOVERNANCE/WORKSPACE-STANDARD.md`
- Generated agent contracts derived from that source.

Generated files never outrank their source. The Workspace Standard governs
information handling; it cannot introduce Cell kinds or separate product truth.

### Detailed accepted decisions

- `30.KNOWLEDGE/strategy/node-native-design-system-visibility-interaction-architecture-2026-07-16.md`
- `30.KNOWLEDGE/strategy/node-language-versioned-state-security-authority-2026-07-15.md`
- `30.KNOWLEDGE/strategy/core-values-governance-authority-2026-07-16.md`

These control only the detail explicitly delegated by `SPEC.md`. Their WIP and
gap statements remain binding honesty constraints.

### Requirement graph

- `30.KNOWLEDGE/grand-map/data/grand_domains.json`

Counts and summaries MUST be generated from this source. README prose and old
counts are not authority.

### Revision-bound implementation evidence

- `10.PRODUCT/13.NODE-LANGUAGE/evidence/current-evidence.json`

This generated record binds scoped test results to exact source hashes and names
the required boundaries it did not execute. A green local check cannot make its
explicitly open product or release requirements green.

### Research and adversarial evidence

- `10.PRODUCT/13.NODE-LANGUAGE/RESEARCH-UNIVERSAL-CELL.md`
- `30.KNOWLEDGE/strategy/persistent-graph-attention-reconciliation-2026-07-16.md`
- `30.KNOWLEDGE/strategy/universal-visual-authority-adversarial-audit-2026-07-16.md`
- founder screenshots and real-browser court artifacts

These sources explain why decisions were accepted or rejected. They do not create
a second specification.

## Superseded sources

The previous contradictory Node Language specification is preserved unchanged at:

`90.ARCHIVE/node-language-authority/2026-07-16/SPEC-legacy-before-universal-cell-consolidation.md`

Its SHA-256 and reason are recorded in the adjacent `MANIFEST.md`. It is historical
evidence, not active authority.

The typed-node runtime, old Studio, separate Brain/Cockpit pages, hand-built
renderers, and model-room proposals are comparison evidence until consumed by a
replacement that passes the courts in `SPEC.md`.

## Change protocol

An authority change requires:

1. exact founder requirement or accepted problem statement;
2. current primary-source research where the claim can change or is externally
   standardized;
3. contradiction and security/failure analysis;
4. proposed wording and affected roots/files;
5. red executable courts before behavior implementation;
6. WIP revision and explicit review at the required authority level;
7. updated supersession relation and evidence ledger;
8. regeneration of derived contracts only after source authority is coherent.

No agent may resolve a contradiction by choosing the most convenient document.
It must stop the affected write, record the contradiction, and repair or obtain a
decision at the controlling level.

## Mutable truth

Implementation status, test output, browser evidence, performance, security
coverage, Grand Map counts, and deployment state belong in generated or
revision-bound evidence. They MUST NOT be copied into `SPEC.md` or hand-maintained
in several dashboards.
