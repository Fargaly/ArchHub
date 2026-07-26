# ArchHub Universal Cell Specification

Version: 0.1 WIP
Date: 2026-07-16
Status: normative implementation target; not a completion claim

This document defines what ArchHub must become. It does not report mutable
progress, test counts, percentages, deployments, or release status. Those belong
in revision-bound evidence.

The words MUST, MUST NOT, REQUIRED, SHALL, SHALL NOT, SHOULD, SHOULD NOT, and MAY
are normative.

## 1. Product invariant

ArchHub is one persistent, governed, visual graph computer.

The application, Brain, Cockpit, Grand Map, website, governance, design system,
data, users, sessions, AI work, repository evidence, and every domain are regions
and lenses of the same graph. They are not separate products that exchange copied
status reports.

Every persisted semantic fact MUST be represented by compositions of one physical
record:

```text
Cell {
  id: CellId
  link0: CellId
  link1: CellId
  atom: Bytes
}
```

There are no persisted `kind`, `type`, `body`, `params`, `ports`, `group`,
`session`, `wire`, `ui`, `secret_ref`, or product-specific record classes. A Cell
may participate in several roles at once. Roles are graph protocols, not engine
enums.

## 2. Terms

- **Cell:** the only persisted semantic record.
- **Root:** a stable Cell identity selected as the entry to a reachable region.
- **Composition:** a reachable arrangement of Cells interpreted through a
  released graph protocol.
- **Protocol:** an inspectable graph definition that states structural roles,
  constraints, behavior, presentation, authority, and evidence requirements.
- **Relation:** a composition that has its own identity and relates any number of
  participants through explicit incidence identities.
- **Interface:** a public boundary composition exposing permitted relations,
  contracts, direction/polarity, policy, and presentation.
- **Assembly:** a reusable, versioned composition definition in the catalogue.
- **Lens:** an authorised projection of the same roots for a purpose and audience.
- **Revision:** one atomic committed graph state with predecessor and evidence.
- **Court:** an executable acceptance predicate bound to an exact artifact,
  revision, environment, and evidence set.
- **Adapter:** the narrow admitted bridge to a physical host capability.

Familiar names such as List, Watcher, Logic, Session, Database, BIM Asset, AI
Worker, Properties, Brain, or Application name assemblies and lenses. They do not
extend the physical schema or native dispatch table.

## 3. Physical floor

### 3.1 Cell invariants

1. `id` is stable identity. Revisions replace Cell content while preserving
   identity when the semantic root continues.
2. `link0` and `link1` are raw incidence only. The kernel assigns no semantic
   meaning, order, direction, ownership, or type to either position.
3. `atom` is opaque bytes. The kernel compares and stores it but does not dispatch
   on its decoded content.
4. A distinguished immutable null Cell terminates physical links.
5. Every non-null physical link MUST resolve in the same committed snapshot.
6. A semantic side table is forbidden. Search indexes, caches, GPU buffers, and
   projections MAY exist only as disposable, revision-bound acceleration.
7. Deleting an accelerator MUST NOT change meaning. A generic graph path MUST
   produce the same result at the same snapshot.

### 3.2 Native boundary

The trusted floor is deliberately small:

```text
read(cell_id, snapshot)
match(pattern_root, target_root, snapshot, budget)
commit(expected_snapshot, creates, replacements)
rewrite(rule_root, target_root, expected_snapshot, budget)
observe(committed_revision)
invoke(capability_handle, request_root, authority_root, budget)
```

- `read` reads only an immutable snapshot.
- `match` performs bounded structural matching and returns explicit bindings.
- `commit` atomically publishes a complete valid next revision or publishes
  nothing. Stale expected snapshots fail.
- `rewrite` resolves an editable graph-held rule and commits its replacement
  atomically. Product operation names are forbidden at this boundary.
- `observe` announces a completed durable commit. Durable subscriptions, cursors,
  obligations, and reactions remain Cells; an in-memory callback is disposable.
- `invoke` is the only effect boundary. Requests, grants, denials, outcomes,
  receipts, and reconciliation are Cells. Live capability handles are unforgeable
  host state and MUST NOT be serialized into `atom`.

Every traversal, match, rewrite, reaction round, query, and invocation MUST have
an explicit resource budget and deterministic failure state.

### 3.3 Honest boundary

Not every implementation byte is a user-editable Cell. Pixels, DOM nodes, GPU
buffers, database pages, OS handles, network sockets, cryptographic key bytes,
and process stacks are physical machinery. Their semantic contracts, policies,
references, versions, requests, and observable outcomes MUST be Cells.

This boundary prevents two opposite failures: hiding product meaning in host code,
and materialising disposable machine details as millions of misleading nodes.

## 4. Meaning and computation

### 4.1 No hidden interpreter

Meaning MUST resolve from released protocol definitions in the graph. The kernel,
renderer, server, agent, or adapter MUST NOT select behavior from a product label,
protocol name string, JavaScript branch, Python class, database table name, or
hard-coded node catalogue.

A host fast path MAY accelerate a released protocol only when an equivalence court
proves the generic graph path and fast path produce the same result at the same
snapshot. Removing the fast path may reduce speed; it MUST NOT change behavior.

### 4.2 Relations and wires

A relation is a selectable, editable composition with:

- its own stable root identity;
- explicit incidence identity for every participant;
- graph-held participant roles;
- optional ordering, direction/polarity, data contract, gate, transform,
  encryption policy, provenance, lifecycle, and presentation;
- arbitrary arity, including relations that participate in other relations.

A visible wire is a lens over an actual relation and its incidences. A renderer
MUST NOT invent ports, infer authority from a line, collapse an n-ary relation into
a false binary edge, or hide intermediate gates and transforms as decoration.

### 4.3 Properties and parameters

A property or parameter is not an inline field. It is a composition relating at
least an owner, name, value root, constraints, editor/presentation, authority,
lifecycle, and history where applicable. The value may be text, number, logic,
function/rule, reference, structured data, geometry metadata, image metadata, or
another composition.

Editing a visible field MUST commit the authoritative value Cell or relation. The
right Properties rail MUST discover applicable panels and editors through graph
relations; it MUST NOT be a product-specific report over copied JSON.

### 4.4 Composition and scale

Grouping is not a primitive Cell class. Grouping creates a WIP composition
boundary and public interfaces while preserving the identities and relations of
its contents. Ungrouping removes that boundary without destroying internal
identities or external connectivity.

Opening a composition changes scope. It does not create a second graph. The
application itself is the top composition. A domain, session, database, Brain,
Cockpit, and the application are the same mechanism at different scales.

### 4.5 Reusable catalogue

The left catalogue contains reviewed, released assemblies built from Cells. It is
not a list of physical node kinds and not a domain index.

An assembly definition MUST expose its parts, interfaces, rules, parameters,
presentation, required capabilities, lifecycle, courts, provenance, version, and
digest. Instances retain a relation to the exact definition revision. Editing a
definition creates a new WIP revision; it does not mutate released instances.

Catalogue membership, category, display order, icon, documentation, search
terms, favourites, and interface summaries MUST be graph relations rooted in the
exact assembly definition revision. A renderer MAY build a disposable search
index from the authorised projection, but it MUST NOT maintain a second catalogue
or infer metadata from product-specific code. Hidden or unauthorised definitions
MUST NOT affect results, counts, ordering, or suggestions.

The ordinary Build lens MUST support category browsing and keyword search over
the graph-projected name, category, documentation, and interface contracts.
Click, drag, and keyboard placement MUST invoke the same governed instantiation
interaction and create an instance of the exact selected definition revision.
Filtering alone is local projection state and MUST NOT mutate the graph.

Agents and users compose through admitted assemblies and graph-visible commands.
Raw Cell construction is a Floor privilege, not the ordinary composer API.

## 5. Persistent graph attention

ArchHub uses transformer ideas only as an analogy for authorised selection. It is
not a neural transformer and MUST NOT hide policy in learned weights or model
context.

- The durable graph is memory and authority.
- A **Signal** records an observed committed change with source revision,
  provenance, trust, audience, time, and deduplication identity.
- **Attention** relates an observer to an authorised candidate, source snapshot,
  explicit reasons, ordering policy revision, expiry, and evidence.
- **Focus** records the bounded current working set for an actor/view session,
  including scope, reason, origin, interruption state, and recovery history.
- An **Obligation** unifies requirements, Grand Map leaves, Core Value gaps,
  failing courts, security findings, accepted work, dependencies, evidence, and
  resolution history.
- **Decision** and **Outcome** compositions preserve the selected action, actor,
  authority, evidence, effect receipt, reconciliation, and reversal/compensation.

These are standard compositions, not Cell kinds.

The first ordering policy MUST be a visible partial order: safety and data-loss
risk, explicit user/founder pin, blocking dependency, failed active court,
accepted due work and fairness, then optional model-proposed relevance. Every
ordering edge has an inspectable reason. Model output is untrusted proposal
evidence and cannot broaden scope or authority.

Candidate roots MUST be authorised before ranking. Hidden roots MUST NOT influence
visible counts, order, explanation, embeddings, or model context.

Signals, attention, focus, obligations, cursors, decisions, and outcomes MUST
survive process close, session reopen, and machine-restart simulation. In-memory
queues, DOM state, caches, and model contexts are disposable.

## 6. One application, many lawful lenses

The same semantic root MUST be traversable, subject to authority, from every
applicable lens. No lens may own a duplicate truth field.

The default application provides four progressive visibility layers:

1. **Use:** ordinary work, clear names, status, direct manipulation, and safe
   actions. No hashes, raw Cells, protocol internals, or JSON.
2. **Build:** assemblies, real interfaces, relations, parameters, composition,
   behavior, and presentation authoring.
3. **Govern:** authority, lifecycle, provenance, courts, decisions, attention,
   history, impact, and release evidence.
4. **Floor:** physical Cells, raw links/atoms, digests, capability diagnostics,
   and kernel evidence for authorised experts.

Visibility is not cosmetic hiding. Each lens is an authorised graph projection.

Brain is the memory, attention, obligation, evidence, and governance lens.
Cockpit is the founder operating lens. Grand Map is the requirement and dependency
lens. They MUST open inside the same application composition and address the same
roots. Separate static dashboards are non-conforming.

## 7. Visual language and interaction

The visual application is the primary language, not a report about the language.

1. The first screen is the usable graph workspace.
2. Domains and compositions are enterable by double-click/Enter, with breadcrumbs
   and a reversible return path.
3. Wheel zoom is cursor-centred. Pan, drag, wire, and resize use pointer capture
   and remain stable under zoom.
4. Selection follows mature AEC behavior: click, Ctrl additive toggle, Shift
   removal/range where applicable, left-to-right containing window, and
   right-to-left crossing window.
5. Multi-selection and focus are graph-held view-session state after commit.
   Its Properties lens exposes only unambiguous properties common to every
   selected root. Mixed values are explicit, and editing one common field is
   one atomic, undoable transaction over the exact participating value roots.
6. Every visible socket resolves to a real public interface root. Every cable
   resolves to exact relation and incidence roots.
7. Selecting any root, interface, relation, incidence, attention reason, rule, or
   presentation opens the applicable Properties composition.
8. Properties tabs are graph-defined and appear only when applicable. Empty,
   dead, or decorative tabs are forbidden.
9. Users can edit permitted labels, icons, colors/token bindings, parameters,
   interfaces, presentation, and rules without editing CSS or code.
10. Personal design changes begin as WIP preview and never broadcast silently.
11. The design system, tokens, components, panel definitions, icon assignments,
    interaction rules, and accessibility metadata are versioned graph regions.
12. Technical identity and hashes are available in Govern/Floor, not forced into
    ordinary Properties.

The reference interaction courts use real browsers and the actual artifact.
Source-string assertions and backend-only tests cannot release visible behavior.

## 8. History, lifecycle, and concurrent work

ArchHub is append-oriented. Undo, restore, rejection, compensation, and merge add
new revisions; they do not erase history.

The following independent axes MUST NOT be collapsed into one status string:

- information authoring/review: WIP, Shared, Published, Archived;
- canonical product source: WIP or Production;
- deployment selection: candidate, Deployed, retired;
- operational state: pending, running, succeeded, failed, denied, reconciled;
- visibility/trust: private, team, public, confidentiality tier, approval state;
- external outcome: requested, accepted, settled/issued, rejected, reversed.

WIP, Shared, and Published are immutable revision views, not three mutable copies
kept in a fragile bidirectional sync. Promotion refers to exact content revisions,
actors, approval, evidence, and policy. Later WIP does not alter Shared or
Published history.

Concurrent users work on explicit branches/heads. Conflicts are preserved and
made visible; last-write-wins MUST NOT silently discard work. Merge and selection
are governed decisions with provenance.

Database writes, monetary transactions, BIM exchanges, geometry/image revisions,
AI actions, and deployments MUST separate request, authorization, attempt,
provider/host outcome, reconciliation, and current projection. A label such as
`done` is never proof of an external effect.

Large geometry, image, model, media, and document bytes MAY live in admitted
content-addressed storage. Their hash, format, coordinate/reference system,
metadata, lineage, access, revisions, transforms, previews, and lifecycle are
graph compositions.

## 9. Security and external capabilities

Security is default-deny and relationship-aware at every scale.

1. Every read, projection, proposal, mutation, composition, release, and effect
   evaluates actor, action, object, relationship, audience, scope, policy revision,
   time/budget, and relevant data classification.
2. Network or process location grants no implicit trust.
3. Secret bytes, private keys, bearer tokens, and live capability handles MUST NOT
   enter ordinary Cells, logs, model prompts, URLs, command lines, or client
   bundles.
4. Cells may hold opaque references, policy, public fingerprints, requests, and
   redacted evidence. Secret custody remains in an admitted OS/cloud key store.
5. Adapters are fingerprinted, versioned, allowlisted, least-privilege, revocable,
   budgeted, and audited. Unknown adapters and unknown actions fail closed.
6. An adapter translates an exact physical operation. Product workflow, domain
   decisions, lifecycle, presentation, and policy MUST remain graph assemblies.
7. AI sessions and agents are graph compositions with identity, model/provider,
   scope, capabilities, focus, obligations, context sources, proposals, costs,
   evidence, and lifecycle. They cannot mint their own authority.
8. Untrusted content and model output cannot modify released policy or execute an
   effect without the required proposal, review, and capability path.
9. Security controls apply before attention/ranking so hidden information cannot
   leak through priority, counts, timing, or explanation.

## 10. Governance and Core Values

The founder Core Values are constitutional input. Their software translation
remains WIP until founder-reviewed and released; partial coverage cannot be shown
as compliant.

Every released slice MUST map the ten values to exact controls or explicit gaps:

- Security is Sacred Trust -> threat model, least privilege, secret handling,
  privacy, incident and recovery evidence.
- Truth Over Comfort -> honest status, residual risk, and no false completion.
- You Build It, You Own It -> named owner, operation, observability, maintenance,
  and decommission path.
- Respect Every Second -> measured latency, bounded work, direct manipulation,
  and no needless user ceremony.
- Architect Review Mandatory -> founder/architect review at the defined authority
  threshold.
- Solve Real Pain -> traced founder/user requirement and outcome evidence.
- Simplicity Conquers Complexity -> one physical model, progressive disclosure,
  and justified assemblies.
- Test What You Ship -> courts on the real packaged artifact.
- Break It Down, Iterate Fast -> bounded WIP slices without partial-green claims.
- Fix Root Causes -> contradiction and recurrence analysis, not cosmetic patches.

The workspace BIM/CDE standard governs placement, privacy, evidence handling, and
release custody. It does not define a second node ontology.

## 11. Required acceptance courts

A slice is complete only when all applicable courts pass against its exact
revision and artifact:

1. Uniform Cell: no second persisted semantic shape or side authority.
2. Authority coherence: no active contradiction; mutable facts are generated.
3. No hidden interpreter: graph path and any fast path are equivalent; deleting
   the fast path does not alter meaning.
4. One identity: every lens resolves the same roots and facts.
5. Explicit causality: rewiring authority changes behavior; deleting projection
   does not.
6. Persistent attention: signals, reasons, focus, obligations, and cursors recover
   after restart.
7. Replay: graph state reconstructs deterministically and effects do not repeat.
8. Attention security: hidden roots cannot influence visible output or context.
9. User control: a nontechnical user can understand cause, edit permitted state,
   undo, and recover without Floor knowledge.
10. Real interfaces: sockets, cables, relations, incidences, and n-ary cases are
    exact.
11. Properties: panels/editors are graph-projected and no tab is dead.
12. Composition: group, enter, breadcrumb, ungroup, and undo preserve identity and
    connectivity.
13. Interaction: selection, zoom, pan, drag, wire, keyboard, focus, and pointer
    capture pass in a real browser.
14. Performance: pointer frame p95 <= 16.7 ms, same-frame selection feedback,
    local mutation acknowledgement <= 100 ms, bounded scope entry <= 150 ms, and
    no steady-state long task over 50 ms on the reference machine.
15. Lifecycle/effect: independent states, receipts, reconciliation, conflicts,
    recovery, and compensation are proven.
16. Core Values: each value maps to a passing control or visible gap; no partial
    row is green.
17. No false done: report exact revision, environment, evidence, open requirement,
    residual risk, and untested boundary.

Security, privacy, data-loss, authority-coherence, and one-identity failures are
release blockers. A local visual demo, test count, or completion percentage cannot
override a red court.

## 12. Migration and conformance

The previous typed-node runtime, old Studio, separate Brain/Cockpit pages, and
hand-built projections are migration evidence only. They remain available for
behavior and visual comparison until graph-native replacements pass intentionally
superseding courts.

Migration MUST proceed capability by capability:

1. trace the founder requirement and accepted source;
2. identify the current authoritative and copied paths;
3. define the graph protocol and red courts;
4. implement on the Universal Cell floor;
5. verify security, restart, causality, usability, and performance;
6. switch the authoritative path;
7. prove no fallback recreates or bypasses it;
8. then archive/remove the consumed legacy path with evidence.

No old source is deleted merely because a replacement looks similar. No new UI
patch, backend protocol, assembly, or adapter may claim conformance without the
applicable courts.

## 13. Evidence and references

Active authority order is defined in `AUTHORITY.md`. Implementation truth is
recorded separately from this target specification.

Primary architecture research and contradiction evidence:

- `RESEARCH-UNIVERSAL-CELL.md`
- `30.KNOWLEDGE/strategy/persistent-graph-attention-reconciliation-2026-07-16.md`
- `30.KNOWLEDGE/strategy/node-native-design-system-visibility-interaction-architecture-2026-07-16.md`
- `30.KNOWLEDGE/strategy/universal-visual-authority-adversarial-audit-2026-07-16.md`
- `30.KNOWLEDGE/strategy/node-language-versioned-state-security-authority-2026-07-15.md`
- `30.KNOWLEDGE/strategy/core-values-governance-authority-2026-07-16.md`

The archived contradictory specification and its hash are recorded at
`90.ARCHIVE/node-language-authority/2026-07-16/MANIFEST.md`.
