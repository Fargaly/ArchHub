# ArchHub Node Language Handbook

Status: WIP explanatory handbook; not a completion, release, or deployment claim
Authority date reviewed: 2026-07-22
Language target: ArchHub Universal Cell Specification 0.1 WIP

This handbook teaches the language defined by [SPEC.md](./SPEC.md). It does not
replace the specification, the founder's decisions, the Core Values source, or
revision-bound executable evidence. When this handbook conflicts with a higher
authority, [AUTHORITY.md](./AUTHORITY.md) decides which source controls.

Normative words in quoted or restated rules retain their specification meaning:
`MUST`, `MUST NOT`, `REQUIRED`, `SHALL`, `SHALL NOT`, `SHOULD`, `SHOULD NOT`, and
`MAY`. Text marked **Explanation**, **Example**, **Counterexample**, or **Current
implementation status** is non-normative.

**Current evidence warning:**
[`evidence/current-evidence.json`](./evidence/current-evidence.json) predates the
current 2026-07-22 source state. It was generated against earlier source
revisions and is therefore stale for the current 2026-07-22 `SPEC.md`, research,
and implementation. It cannot prove present behavior, acceptance, or release
eligibility until it is regenerated against an exact current source revision and
artifact. References to that file below identify the evidence location only.

The same seven questions are applied at every scale:

1. **WHAT** is the thing?
2. **WHY** does it exist?
3. **HOW** is it composed, interpreted, changed, and verified?
4. **WHO** may see, author, approve, execute, or operate it?
5. **WHEN** does it exist, change, react, release, or retire?
6. **WHERE** does its authority and physical effect live?
7. **PROOF** shows that the claim is true on an exact revision and artifact.

The four recurring scales are:

```text
MACRO  one governed graph computer: ArchHub and all of its regions
  |
MESO   reusable compositions: domains, assemblies, protocols, lenses, sessions
  |
MICRO  explicit meaning: relations, incidences, properties, rules, permissions
  |
FLOOR  one physical record plus a small generic execution boundary
```

No scale introduces another ontology. A macro application, a meso assembly, and
a micro property are reachable Cell compositions. Only their scope and released
protocols differ.

## 1. Reading and Using the Language

Scale: macro, meso, micro, and floor.

### WHAT

The Node Language is a persistent visual graph language in which every persisted
semantic fact is a composition of the same physical Cell record. It is also the
data model, executable rule medium, authority model, interaction language,
history model, and product structure. Familiar names such as `Watcher`, `List`,
`Session`, `Database`, `Brain`, and `Application` are reusable compositions and
lenses, not hard-coded Cell kinds.

The language has three distinct layers that must not be confused:

- **Physical floor:** `Cell(id, link0, link1, atom)` and generic native actions.
- **Graph language:** released protocols that give arrangements of Cells meaning.
- **Product vocabulary:** reviewed assemblies that people and agents can use.

### WHY

One uniform floor prevents the application from becoming a growing catalogue of
special classes, hidden dictionaries, and one-off engines. Graph-held protocols
make meaning inspectable and replaceable. Reviewed assemblies make the system
usable without forcing ordinary users to build from raw Cells.

This is the balance: universal below, constrained and teachable above.

### HOW

Read any visible thing from outside inward:

```text
visible card or cable
  -> authorised lens and presentation
  -> assembly or relation root
  -> protocol-defined roles and constraints
  -> Cells, links, and terminal atoms
```

Read any change from intent to outcome:

```text
gesture or agent proposal
  -> graph-defined interaction
  -> authorization decision
  -> expected-revision commit or capability invocation
  -> revision, receipt, reconciliation, and projected feedback
```

**Worked example:** a user drags a released `Watcher` from the catalogue. The
catalogue entry identifies an exact released definition revision. A governed
instantiation creates a WIP instance composition. The canvas shows the instance
through the Build lens. Connecting its interface creates a relation with explicit
incidences. A later source commit is observed from the durable cursor and the
Watcher's graph-held rule proposes or commits its permitted reaction.

**Failure/counterexample:** adding `kind="watcher"` to a database row and writing
`if kind == "watcher"` in Python creates a hidden product dispatch table. Drawing
a card for that row does not make it node-native.

### WHO

- Ordinary users work primarily through Use and safe Build assemblies.
- Authorised authors create and revise compositions through the closed composer.
- Stewards and the founder inspect authority, lifecycle, evidence, and impact.
- Floor maintainers inspect raw Cells and generic execution evidence.
- Agents use the same catalogue, proposal, authorization, and court paths as
  humans; they do not receive a private authoring language.

### WHEN

Use the Node Language whenever a fact must persist, be shared, affect behavior,
control visibility, authorize an action, survive restart, or be audited. Do not
materialize disposable pixels, DOM nodes, GPU buffers, process stacks, sockets,
or secret key bytes as semantic Cells.

### WHERE

Semantic authority lives in the committed Cell graph. Host code may provide the
kernel, projection, acceleration, and admitted physical capability, but it must
not own product meaning. Revision-bound implementation truth belongs in
regenerated evidence, not in this handbook. The existing
[`evidence/current-evidence.json`](./evidence/current-evidence.json) is stale for
the current 2026-07-22 sources and cannot establish present behavior.

### PROOF

- **Authority:** [SPEC.md sections 1-3](./SPEC.md) and
  [AUTHORITY.md](./AUTHORITY.md).
- **Research evidence, not authority:**
  [RESEARCH-UNIVERSAL-CELL.md](./RESEARCH-UNIVERSAL-CELL.md) records lineage,
  alternatives, and unresolved risks. It cannot change the language target.
- **Literature:** Lisp and cons-cell lineage in [A History of Lisp](https://dl.acm.org/doi/10.1145/38807.38828),
  structural reflection in [Maude rewriting logic](https://maude.cs.illinois.edu/papers/abstract/tcs4009.html),
  and graph-based abstract models in the dated
  [RDF 1.2 Concepts Candidate Recommendation](https://www.w3.org/TR/2026/CR-rdf12-concepts-20260407/).
- **Executable courts:** `tests_replica/test_universal_cell_kernel.py`,
  `tests_replica/test_cell_execution_floor_court.py`, and
  `tests_replica/test_authority_coherence.py`.
- **Status rule:** the existence of those courts is documented here. The stale
  current-evidence file cannot establish their present pass state; they must be
  rerun and recorded against the exact revision and release artifact.

## 2. Macro Scale: One Graph Computer

Scale: macro, with the same rules recursively applied inside every region.

### WHAT

ArchHub is one persistent, governed, visual graph computer. The application,
Brain, Cockpit, Grand Map, website, governance, design system, users, data,
sessions, AI work, evidence, and domains are regions and lenses of one graph.
They are not independent products connected by copied status fields.

A stable application root is the entry to the complete reachable building.
Opening a domain changes the current scope; it does not switch to another engine.

### WHY

Separate stores and dashboards create drift: one surface says a task is complete,
another says it is open, and neither can show the exact causality. One graph lets
the same requirement, actor, session, rule, evidence, and outcome retain identity
across every lawful view.

### HOW

The application root exposes authorised direct regions through explicit
relations and interfaces. Each region may itself expose nested regions. Lenses
select what the current actor may see and do without copying the roots.

**Worked example:** the founder opens the `Grand Map` region and selects one
requirement root. The Properties lens shows its lifecycle and courts. The Brain
lens shows the same root as an unresolved obligation. An authorised assignment
composition references that obligation and the assigned session. Completing
work appends evidence and changes the obligation through explicit relations; no
dashboard imports a copied percentage.

**Failure/counterexample:** a Python Brain database, a JSON Workshop document,
and an HTML Cockpit each store their own `status` for the same requirement. Even
if a synchronization job copies values among them, they are three authorities,
not one graph.

### WHO

Every actor sees an authorised projection of the same roots. The founder may
traverse broad cross-region relations. A normal user may see only project and
task regions. An agent receives a bounded focus and assignment. No actor gains
authority merely by being able to address the application root.

### WHEN

The one-graph invariant applies at creation, read, edit, reaction, collaboration,
release, deployment, backup, restore, and migration. Temporary migration bridges
may coexist only while a shrink-only retirement plan and explicit evidence show
which path is authoritative.

### WHERE

The semantic building lives under one Cell authority. Browser pages, desktop
windows, websites, model prompts, and reports are disposable projections. Remote
replicas may hold revisioned copies, but identity, ancestry, authority, conflict,
and promotion rules remain explicit graph facts.

### PROOF

- **Authority:** [SPEC.md sections 1, 6, and 12](./SPEC.md) and
  [node-native design strategy](../../30.KNOWLEDGE/strategy/node-native-design-system-visibility-interaction-architecture-2026-07-16.md).
- **Literature:** immutable graph snapshots and explicit transactions in
  [Datomic's transaction model](https://docs.datomic.com/transactions/model.html);
  a standard ontology for entities, activities, agents, and qualified provenance
  relations in the dated [W3C PROV-O Recommendation](https://www.w3.org/TR/2013/REC-prov-o-20130430/).
- **Executable Universal Cell courts:**
  `tests_replica/test_universal_grand_map_import.py` and
  `tests_replica/test_universal_application.py`.
- **Typed legacy comparison evidence only:**
  `tests_replica/test_node_native_application.py` exercises the superseded typed
  node model. It is not Universal Cell proof and cannot release this invariant.
- **WIP/proposal mechanism evidence:**
  `tests_replica/test_universal_workshop_authority.py` and
  `tests_replica/test_baboom_single_authority.py` exercise scoped mechanisms;
  they do not promote Workshop or BABOOM architecture into authority.
- **Court not yet sufficient:** no current court proves the complete shipped
  application, Brain, Cockpit, Grand Map, website, governance, cloud, and every
  domain operate as one released identity-preserving system.

## 3. Floor Scale: The One Physical Cell

Scale: floor.

### WHAT

The only persisted semantic record is:

```text
Cell {
  id: CellId
  link0: CellId
  link1: CellId
  atom: Bytes
}
```

`id` is stable identity. `link0` and `link1` are raw physical incidence without
built-in direction or ownership. `atom` is opaque terminal bytes. A distinguished
immutable null Cell terminates links. There is no persisted `kind`, `type`,
`params`, `ports`, `group`, `session`, `wire`, or product class.

### WHY

A single non-semantic shape prevents privileged product concepts from entering
the kernel. The floor stays small enough to reason about, secure, persist, replay,
and replace. Rich meaning remains possible because Cells can form arbitrary
reachable compositions.

### HOW

The kernel stores immutable snapshots and atomically commits complete next
revisions. Every non-null link resolves within the same snapshot. Protocols use
graph structure to interpret roles; the kernel does not inspect an atom and choose
product behavior.

A terminal atom may encode a released scalar representation such as UTF-8 text,
an integer, or a digest. The encoding and its role are graph-declared. `atom` is
not permission to hide an ungoverned object model in JSON.

**Worked example:** the number `900` used as a door width is stored as terminal
bytes in a value Cell. Other Cells relate that value to a property root, unit
`mm`, numeric contract, permitted range, owner, editor, lifecycle, and history.
The atom alone does not mean `door width`.

**Failure/counterexample:** one Cell atom contains a JSON object with owner,
ports, permissions, logic, UI, and status, while host code parses those fields.
The physical record may still have four fields, but the JSON has become a hidden
second semantic schema.

### WHO

Ordinary users do not create raw Cells. The trusted kernel commits them; released
protocol builders and the closed composer prepare valid compositions. Floor
maintainers may inspect raw identity and bytes under explicit authority.

### WHEN

Create or replace Cells only as part of an expected-revision atomic commit.
Preserve stable identity when the semantic root continues. Fail before publishing
if a link dangles, a budget is exceeded, or the expected revision is stale.

### WHERE

Cells live in the durable Cell store and its immutable snapshots. Caches, indexes,
rendered DOM, GPU state, and search accelerators may exist outside the graph only
as disposable revision-bound machinery whose deletion does not change meaning.

### PROOF

- **Authority:** [SPEC.md section 3](./SPEC.md) and
  [AUTHORITY.md](./AUTHORITY.md).
- **Research evidence, not authority:** the physical-floor alternatives and
  rationale in [RESEARCH-UNIVERSAL-CELL.md](./RESEARCH-UNIVERSAL-CELL.md).
- **Literature:** small universal structures are informed by Lisp cons cells,
  [Kernel's first-class operative model](https://web.cs.wpi.edu/~jshutt/kernel.html),
  and [interaction nets](https://doi.org/10.1006/inco.1997.2643). These are
  precedents, not claims that ArchHub is identical to any of them.
- **Executable courts:** `tests_replica/test_universal_cell_kernel.py` checks the
  exact shape, opaque atom, atomic commit, identity, conflicts, budgets, and
  absence of semantic side tables. `tests_replica/test_universal_cell_durability.py`
  and `tests_replica/test_store_concurrency.py` cover durability and snapshots.

## 4. Meso Scale: Roots, Compositions, and Protocols

Scale: meso, recursively reducible to micro relations and floor Cells.

### WHAT

A **root** is a stable Cell identity chosen as the entry to a reachable region. A
**composition** is the reachable arrangement interpreted through one or more
released protocols. A **protocol** is an inspectable graph definition of roles,
constraints, behavior, presentation, authority, and evidence requirements.

A composition is not a container record. A protocol is not a Python class. The
same root may satisfy several protocols at once without changing physical shape.

### WHY

Roots provide identity across time and lenses. Compositions provide scale without
new primitives. Protocols let the graph explain its own meaning while allowing
the same Cells to participate in multiple roles.

### HOW

An interpreter starts from a root, resolves the exact released protocol revision,
traverses required relations under a budget, validates role/cardinality/authority
constraints, and returns either a valid interpretation or a deterministic error.

Grouping creates a WIP composition boundary around selected roots, derives public
interfaces for crossing relations, and preserves internal identities. Ungrouping
removes only the boundary. Opening a composition changes view scope.

**Worked example:** three rule steps, two parameters, and their relations are
selected and grouped as `Facade Option Ranker`. The composition root gains an
interface for design options and one for ranked results. Opening it reveals the
same internal roots. Publishing an assembly from it is a later governed action
with version, provenance, courts, and digest.

**Failure/counterexample:** moving the selected nodes into a `Group` row, deleting
their original wires, and creating new group-specific ports destroys identity and
turns grouping into a privileged type.

### WHO

Users with Build authority may compose and open regions. Protocol authors require
stronger authority because a released protocol changes how many roots are
interpreted. Agents may propose WIP compositions through the same composer but
cannot publish protocols or broaden their own scope.

### WHEN

Resolve protocols at a named snapshot. Version protocol changes. Reject direct or
indirect recursive containment. Revalidate a composition when its protocol,
participants, authority, or referenced definition revision changes.

### WHERE

Root identity, protocol definitions, conformance relations, composition
membership, boundary interfaces, version, digest, and evidence all live in the
graph. Navigation breadcrumbs live on the view-session root, not only in browser
history.

### PROOF

- **Authority:** [SPEC.md sections 2 and 4.4](./SPEC.md).
- **Literature:** graph interpretation and vocabulary separation in
  [RDF 1.2 Concepts](https://www.w3.org/TR/2026/CR-rdf12-concepts-20260407/); reflective rules in
  [Maude](https://maude.cs.illinois.edu/papers/abstract/tcs4009.html); openable
  reusable node groups in the [Blender manual](https://docs.blender.org/manual/en/4.5/interface/controls/nodes/groups.html).
- **Executable courts:** `tests_replica/test_universal_cell_relations.py` covers
  multi-role roots and supernode reachability;
  `tests_replica/test_cell_relation_contract.py` covers structural protocol
  validation; `tests_replica/test_application_server_governance.py` includes
  group/open/ungroup routes.
- **Court not yet sufficient:** complete visual group, boundary derivation,
  recursive navigation, undo, and identity preservation still require accepted
  real-browser evidence on the current editor artifact.

## 5. Micro Scale: Relations, Incidences, Wires, and Interfaces

Scale: micro, projected visually at meso and macro scales.

### WHAT

A **relation** is a composition with its own stable root identity. It relates any
number of participants through explicit **incidence** identities. Each incidence
states the exact participant and graph-held role. An **interface** is a public
boundary composition exposing permitted contracts, roles, cardinality,
direction/polarity where declared, authority, and presentation.

A visible **wire** is a lens over a relation and its incidences. The line is not
the relation; deleting the pixels must not change meaning.

### WHY

First-class relations can carry logic, gates, transforms, encryption policy,
provenance, lifecycle, presentation, and history. Explicit incidences preserve
identity during rewiring and represent n-ary and relation-to-relation structures
without lying that everything is a binary line.

### HOW

To create a relation:

1. Select an exact released relation definition.
2. Bind each required participant role to a permitted root or interface.
3. Create a relation root and one incidence root per participant.
4. Validate role, cardinality, contract, authority, and traversal budget.
5. Commit the complete relation atomically.
6. Project sockets from real interfaces and cables from exact incidences.

Rewiring replaces the participant referenced by one incidence while preserving
the relation and incidence identities when the semantic relationship continues.
An n-ary relation uses a selectable junction presentation and one incidence leg
per endpoint.

**Worked example:** a `Room Schedule` relation connects one room set, one property
selection, one ordering rule, and one table view. The relation has four incidences.
Its visible junction exposes the four real role sockets. Selecting the wire or
junction opens the relation's own Properties, including order, gate, provenance,
and presentation.

**Failure/counterexample:** JavaScript draws one input dot and one output dot on
every card and sends `{sourceId, targetId}`. Those dots have no interface roots,
the line has no relation identity, n-ary roles disappear, and the renderer has
invented authority.

### WHO

Users and agents may connect only exposed interfaces allowed by their composer
and authorization scope. Relation-definition authors establish roles and
contracts. Security policy decides whether the actor may read, create, rewire,
detach, expose, or invoke a relation.

### WHEN

Create, rewire, reorder, or detach a relation in one atomic expected-revision
transaction. Revalidate on contract, participant, policy, definition, or authority
drift. Project wires only after exact endpoints are authorised for the current
lens.

### WHERE

Relation and incidence authority lives in Cells. Cable paths, hit targets, hover
states, and routing geometry are disposable presentation. Cross-composition
boundary sockets preserve the original relation and incidence identities.

### PROOF

- **Authority:** [SPEC.md section 4.2](./SPEC.md) and the
  [node-native interaction strategy](../../30.KNOWLEDGE/strategy/node-native-design-system-visibility-interaction-architecture-2026-07-16.md).
- **Literature:** IFC makes relationships explicit semantic objects in
  [IfcRelationship](https://standards.buildingsmart.org/IFC/RELEASE/IFC4_3/HTML/lexical/IfcRelationship.htm);
  RDF 1.2 defines graphs as sets of triples and documents reification mechanisms,
  while not supplying ArchHub graph identity or n-ary incidence semantics, in
  [RDF 1.2 Concepts](https://www.w3.org/TR/2026/CR-rdf12-concepts-20260407/); OpenUSD exposes
  editable relationship targets in the pinned
  [UsdRelationship v26.05 source](https://github.com/PixarAnimationStudios/OpenUSD/blob/v26.05/pxr/usd/usd/relationship.h).
- **Executable courts:** `tests_replica/test_universal_cell_relations.py`,
  `tests_replica/test_cell_relation_contract.py`,
  `tests_replica/test_relation_topology_editor.py`, and the real-browser entry
  point `tests_replica/test_browser_graph_editor_court.py`.
- **Court not yet sufficient:** the complete visual binary, n-ary,
  relation-to-relation, collapsed-boundary, create, select, rewire, detach, undo,
  and performance matrix is not asserted green by this handbook.

## 6. Micro Scale: Properties and Parameters

Scale: micro, edited through meso Properties lenses.

### WHAT

A property or parameter is a relation composition, not an inline field. It
relates at least:

```text
owner -> property relation -> name
                           -> value root
                           -> contract and constraints
                           -> editor and presentation
                           -> authority
                           -> lifecycle and history
```

The value root may hold text, number, a reference, structured data, geometry or
image metadata, another composition, or the root of executable graph logic.

### WHY

First-class parameters can be selected, wired, versioned, authorised, explained,
reused, and audited. Inline dictionary fields cannot participate honestly in
relations or expose their own authority and history.

### HOW

The Properties rail discovers applicable property relations by following the
current selection, lens, panel-definition, and authority relations. Each editor
is selected by a released presentation/contract relation, not a product-name
branch. Editing commits the authoritative value root.

Multi-selection exposes only common unambiguous properties. Mixed values display
`Varies`. A batch edit is one atomic, undoable transaction over the exact value
roots.

**Worked example:** selecting a wall shows `Fire rating` because the selected
wall is the owner in a property relation that is applicable in the Use lens. The
value is `60 min`, constrained by a released duration contract. Changing it to
`90 min` appends a WIP revision. Selecting the parameter root itself reveals its
constraint, provenance, access, and history.

**Failure/counterexample:** the browser receives a copied JSON wall object and
edits `wall.fireRating`. The right rail works visually, but the value has no
independent identity, relation, authority, or revision; another surface can own a
different copy.

### WHO

The property relation states who may read or edit it. Panel and editor authors
define reusable presentation. Owners do not automatically own every property
action. Agents may edit only through an admitted interaction and exact assigned
scope.

### WHEN

Create a parameter through a governed composer interaction. Edit it at an exact
revision. Revalidate constraints and authority at commit, not only when rendering
the form. Promote or merge its revision through the lifecycle protocol.

### WHERE

Property meaning, value, constraints, editor binding, authority, and history live
in the graph. The HTML input is a temporary projection. Technical identity is
available in Govern/Floor, not forced into the ordinary Use panel.

### PROOF

- **Authority:** [SPEC.md section 4.3](./SPEC.md).
- **Literature:** typed, referenced design values and cycle handling in the
  [DTCG Design Tokens Format 2025.10](https://www.designtokens.org/tr/2025.10/format/);
  provenance vocabulary in the dated
  [W3C PROV-O Recommendation](https://www.w3.org/TR/2013/REC-prov-o-20130430/).
- **Executable courts:**
  `tests_replica/test_universal_cell_relations.py::test_properties_edit_changes_the_value_cell_not_an_inline_form_field`,
  `tests_replica/test_cell_properties_view.py`,
  `tests_replica/test_universal_properties_presentation.py`, and
  `tests_replica/test_application_server_governance.py::test_http_add_parameter_creates_one_real_property_relation`.
- **Court not yet sufficient:** parameter creation, editing, multi-edit, undo,
  editor discovery, and error explanation must all pass the accepted real-browser
  editor court before visual authoring is complete.

## 7. Meso Scale: Assemblies and the Catalogue

Scale: meso, composed from micro protocols and floor Cells.

### WHAT

An **assembly** is a reusable, versioned composition definition. The **catalogue**
is the authorised graph region containing reviewed assembly definitions and their
categories, names, search terms, documentation, interfaces, provenance, versions,
digests, and courts.

The catalogue is the upper constraint layer. It gives people and agents useful
building blocks while keeping the floor universal. `Watcher`, `Ordered List`,
`Conditional`, `Versioned Asset`, `Database Transaction`, `Geometry Descriptor`,
`AI Session`, and `UI Component` are possible assemblies, not physical kinds.

### WHY

Raw universality without a catalogue would force every user or agent to invent
new graph structures, leading to incompatible workflows and unsafe composition.
A reviewed catalogue provides ease of use, predictable interfaces, proven
behavior, versioning, and bounded authoring without enlarging the kernel.

### HOW

An assembly definition exposes:

- its reachable parts and exact public interfaces;
- parameters, rules, constraints, presentation, and required capabilities;
- lifecycle, provenance, version, digest, and applicable courts;
- graph-held catalogue metadata.

Instantiation clones only declared mutable regions, preserves shared released
contract references, records the exact definition revision, and joins the
caller's WIP transaction. Search is an authorised projection over graph metadata;
the search index is disposable.

**Worked example:** the user searches `ordered list`, previews its documentation
and interfaces, and places the exact released definition. Two instances share the
released ordering contract but hold independent mutable members. Reordering one
list preserves incidence identity and does not mutate the other.

**Failure/counterexample:** a left sidebar has hard-coded React entries, and
clicking `Database` calls `createDatabaseNode()`. The catalogue is now product
dispatch in UI code, even if each output is later wrapped in Cells.

### WHO

Ordinary users instantiate released definitions. Authors may create WIP
assemblies from existing admitted assemblies. Reviewers and release authorities
promote definitions after courts. Agents use the same catalogue and may propose
novel WIP compositions, but they cannot silently mint released definitions.

### WHEN

Instantiate only from an exact released definition revision. Editing a definition
creates a new WIP revision and does not mutate existing released instances.
Deprecate and migrate definitions explicitly; do not silently redirect an old
digest to new behavior.

### WHERE

Definitions, catalogue membership, metadata, release evidence, and instance
bindings live in the graph. Browser filtering and autocomplete state may remain
local because filtering alone does not mutate authority.

### PROOF

- **Authority:** [SPEC.md section 4.5](./SPEC.md).
- **Research evidence, not authority:** catalogue alternatives and risks in
  [RESEARCH-UNIVERSAL-CELL.md](./RESEARCH-UNIVERSAL-CELL.md).
- **Literature:** discoverable node libraries in the
  [Dynamo Library](https://primer2.dynamobim.org/3_user_interface/2-library),
  and reusable composition in
  [Blender Node Groups](https://docs.blender.org/manual/en/4.5/interface/controls/nodes/groups.html).
- **Executable courts:** `tests_replica/test_cell_catalog.py`,
  `tests_replica/test_cell_standard_library.py`,
  `tests_replica/test_cell_composer.py`, and catalogue interaction cases in
  `tests_replica/test_universal_ui_interactions.py`.
- **Court not yet sufficient:** the complete user-facing catalogue, drag/keyboard
  placement, arbitrary assembly authoring, documentation access, and agent parity
  are not declared released by this handbook.

## 8. Floor to Meso: Match, Rewrite, Observe, and Invoke

Scale: floor operations interpreted through micro rules and meso assemblies.

### WHAT

The trusted native boundary is deliberately small:

```text
read(cell_id, snapshot)
match(pattern_root, target_root, snapshot, budget)
commit(expected_snapshot, creates, replacements)
rewrite(rule_root, target_root, expected_snapshot, budget)
observe(committed_revision)
invoke(capability_handle, request_root, authority_root, budget)
```

`match` finds bounded structural bindings. `rewrite` resolves a graph-held rule
and atomically applies its replacement. `observe` exposes a completed durable
commit to graph-held subscriptions and cursors. `invoke` is the only boundary to
physical side effects.

### WHY

These operations are sufficient to read, recognize, change, react, and cross into
the physical world without embedding `rank`, `watch`, `BIM`, `payment`, or other
product verbs in the kernel. Bounded generic operations are easier to audit than
an expanding native command catalogue.

### HOW

A rule composition contains pattern, replacement, variables, bindings,
constraints, authority, and budgets. Editing the rule graph changes future
behavior without changing the engine. Observation records durable cursors and
deduplication identity. Invocation requires an unforgeable host capability plus
graph-held request and authority.

**Worked example:** a Watcher observes a committed temperature value revision.
Its durable cursor proves the revision has not been processed. A graph rule
matches `temperature > limit`, rewrites an alert-state composition, and advances
the cursor atomically. If an external notification is allowed, a separate request
is authorised and passed to an admitted adapter through `invoke`; the provider
outcome returns as a receipt and is reconciled.

**Failure/counterexample:** `if node.type == "watcher": send_email(node.email)`
both hides behavior in host code and crosses an external effect boundary without
an exact capability, receipt, replay protection, or graph-visible rule.

### WHO

The kernel executes generic bounded operations. Protocol authors define rules.
Actors need mutation authority for rewrites and separate explicit authority for
effects. Adapter operators own the physical implementation and incident path.
Agents may propose rules or requests but cannot mint capability handles.

### WHEN

Match against an immutable snapshot. Commit or rewrite only with the expected
revision. Observe only completed durable commits. Invoke only after current
authorization, scope, budget, consent, and adapter identity are rechecked. Retry
effects through idempotency/reconciliation policy, never by assuming failure means
nothing happened.

### WHERE

Rules, patterns, subscriptions, cursors, requests, decisions, outcomes, and
receipts live in the graph. Matcher stacks, worker queues, process callbacks, and
live capability handles are host machinery. Secret material and capability
handles never enter ordinary atoms.

### PROOF

- **Authority:** [SPEC.md sections 3.2 and 4.1](./SPEC.md).
- **Literature:** rewriting as executable reflective structure in
  [Maude](https://maude.cs.illinois.edu/papers/abstract/tcs4009.html); incremental
  dependency ideas in the [Adapton paper](https://arxiv.org/abs/1503.07792);
  capability boundaries in the pinned
  [WASI v0.2.11 capabilities design](https://github.com/WebAssembly/WASI/blob/v0.2.11/docs/Capabilities.md).
- **Executable courts:** `tests_replica/test_universal_cell_rules.py`,
  `tests_replica/test_cell_reactions.py`,
  `tests_replica/test_cell_adapters.py`, and
  `tests_replica/test_cell_execution_floor_court.py`.
- **Court not yet sufficient:** broad equivalence proof for every optimized host
  fast path and complete packaged replay/effect recovery remain required.

## 9. Macro and Meso: Lenses and Progressive Visibility

Scale: macro audience, meso projection, micro applicability relations.

### WHAT

A **lens** is an authorised projection of the same roots for a purpose and
audience. The default progressive layers are:

| Lens | Shows by default |
|---|---|
| Use | useful objects, values, state, safe actions, visible relations |
| Build | assemblies, interfaces, relations, parameters, logic, presentation |
| Govern | authority, lifecycle, provenance, courts, attention, history, impact |
| Floor | raw Cells, links, atoms, digests, capability and kernel evidence |

Visibility is an authorization result, not CSS hiding. The Properties rail is
itself a graph-defined lens whose tabs and editors depend on selection, lens,
applicability, and authority.

### WHY

Most users should not confront hashes and raw links to change a color or inspect
a room. Experts still need a transparent path to the floor. Progressive
visibility provides simplicity without hiding authority in another system.

### HOW

The view-session root relates the actor to active scope, lens, selection, focus,
Properties tab, viewport, visibility depth, and authorized audience. Projection
resolves those relations at one snapshot. Changing a client attribute cannot
broaden what the server returns.

**Worked example:** selecting a cable in Use shows its human label and health. In
Build, the same relation root shows endpoint roles, contract, transform, and cable
presentation. Govern adds policy, lifecycle, provenance, and courts. Floor shows
the physical Cells and digests. All views address the same relation identity.

**Failure/counterexample:** the server returns raw hashes, secret references, and
policy internals to everyone, then CSS hides an `Advanced` panel. The data is
already disclosed; the lens is cosmetic and non-conforming.

### WHO

The current actor's grants determine available lenses and roots. Ordinary users
default to Use. Authors receive bounded Build scope. Stewards and the founder may
receive Govern. Floor is restricted to authorised experts. A model sees only the
same authorised projection admitted for its session.

### WHEN

Evaluate lens authority on every projection and mutation. Persist committed scope,
selection, focus, and chosen tab where continuity matters. Keep transient hover,
drag preview, and filtering local until they become committed user intent.

### WHERE

Lens definitions, panel definitions, applicability, view-session state, and
authorization live in the graph. DOM, CSS, SVG, and canvas pixels are projections.
Brain, Cockpit, and Grand Map are named lenses/regions within the application,
not independent pages with duplicate truth.

### PROOF

- **Authority:** [SPEC.md sections 6 and 7](./SPEC.md) and the
  [node-native design strategy](../../30.KNOWLEDGE/strategy/node-native-design-system-visibility-interaction-architecture-2026-07-16.md).
- **Literature:** accessibility and progressive interaction requirements in
  [WCAG 2.2 dated Recommendation](https://www.w3.org/TR/2024/REC-WCAG22-20241212/) and
  [WAI-ARIA Authoring Practices 1.2 dated Note](https://www.w3.org/TR/2021/NOTE-wai-aria-practices-1.2-20211129/); typed shared
  presentation decisions in [DTCG 2025.10](https://www.designtokens.org/tr/2025.10/format/).
- **Executable courts:** `tests_replica/test_cell_control_view.py`,
  `tests_replica/test_cell_properties_view.py`,
  `tests_replica/test_cell_evidence_floor_view.py`, and lens/Properties cases in
  `tests_replica/test_universal_ui_interactions.py`.
- **Court not yet sufficient:** a complete audience matrix proving non-disclosure,
  discoverability, and usability across all roots and packaged clients is not yet
  implemented as one release court.

## 10. Macro to Micro: Lifecycle, Revisions, Concurrency, and Effects

Scale: macro custody, meso revision sets, micro transitions and evidence.

### WHAT

ArchHub is append-oriented. A **revision** is one atomic committed graph state
with predecessor and evidence. WIP, Shared, Published, and Archived are immutable
information-state views, not mutable synchronized copies.

Independent axes remain separate:

- information state: WIP, Shared, Published, Archived;
- product source: WIP, Production;
- deployment: candidate, Deployed, retired;
- operation: pending, running, succeeded, failed, denied, reconciled;
- visibility/trust: private, team, public, classification, approval;
- external outcome: requested, accepted, settled/issued, rejected, reversed.

### WHY

One `status` field cannot tell whether information was approved, code was
released, a deployment is live, or an external transaction actually settled.
Immutable ancestry preserves history, supports restore, and prevents one user or
agent from silently overwriting another.

### HOW

Each edit names an expected base revision and appends a new head. Promotion names
an exact content revision, actor, approval, policy, and evidence. Concurrent edits
produce explicit sibling heads. Merge records every parent and an authorised
resolution. Undo and restore append compensating revisions.

External operations separate request, authorization, attempt, provider outcome,
reconciliation, and current projection. Large geometry, images, and documents may
live in admitted content-addressed storage; the graph holds digest, format,
coordinate system, metadata, lineage, access, transforms, previews, and lifecycle.

**Worked example:** two architects revise one facade from Published revision P7.
Alice produces WIP A8 and Bob produces WIP B8. Neither overwrites the other. A
reviewed merge M9 records P7, A8, and B8 ancestry, exact conflict decisions, and
evidence. Publishing M9 leaves P7 and both alternatives in history.

**Failure/counterexample:** all users write to one mutable `current_geometry` blob
and set `status="published"`. Last-write-wins discards a design, and the label
cannot prove review, external storage success, or deployment.

### WHO

Authors create WIP. Reviewers share. Designated authorities publish. Deployment
operators select released revisions for deployment. External providers report
outcomes but do not decide ArchHub lifecycle. Merge, payment, publication, and
irreversible effects require authority appropriate to their policy.

### WHEN

Append on every semantic change. Detect stale bases before commit. Reconcile
unknown external outcomes before retry. Archive by explicit policy without
erasing provenance. Backup and restore must preserve identities, ancestry,
classification, and evidence.

### WHERE

Revision ancestry, heads, transitions, approvals, receipts, conflicts, and
current projections live in the graph. Content bytes may live in an admitted
store. Provider truth remains provider evidence until reconciled; a graph label
alone cannot prove a bank, database, BIM host, or cloud operation occurred.

### PROOF

- **Authority:** [SPEC.md section 8](./SPEC.md) and
  [versioned state and security strategy](../../30.KNOWLEDGE/strategy/node-language-versioned-state-security-authority-2026-07-15.md).
- **Literature:** transaction snapshots in [Datomic](https://docs.datomic.com/transactions/model.html),
  MVCC and serialization failures in [PostgreSQL 18](https://www.postgresql.org/docs/18/mvcc-intro.html),
  provenance vocabulary in the dated [PROV-O Recommendation](https://www.w3.org/TR/2013/REC-prov-o-20130430/), and CDE states in the
  [UK BIM Framework CDE guidance](https://ukbimframework.org/wp-content/uploads/2020/09/Guidance-Part-C_Facilitating-the-common-data-environment-workflow-and-technical-solutions_Edition-1.pdf).
- **Executable courts:** `tests_replica/test_cell_lifecycle.py`,
  `tests_replica/test_cell_change_history.py`,
  `tests_replica/test_store_concurrency.py`, and
  `tests_replica/test_cell_transactions.py`.
- **Court not yet sufficient:** remote multi-user merge, disaster recovery,
  monetary settlement, database failure ambiguity, and large-geometry round trips
  still require real-provider and packaged-system courts.

## 11. Macro to Floor: Security, Authority, Capabilities, and Adapters

Scale: macro policy, meso capabilities, micro decisions, floor effect boundary.

### WHAT

Security is default-deny and relationship-aware at every scale. An authorization
decision evaluates actor, action, object, relationships, audience, scope, policy
revision, environment, time, budget, and data classification.

A **capability** is an exact, unforgeable authority to request a bounded physical
operation. An **adapter** is the narrow fingerprinted bridge that translates that
request to a host, device, API, database, file system, BIM tool, or model provider.

### WHY

Universal composition must not mean universal permission. Graph text is forgeable
data; it cannot become an OS handle, private key, or authorization merely by
claiming to be one. Narrow adapters prevent the entire application from becoming
a collection of integration-specific control planes.

### HOW

1. Authorise the candidate root before attention, projection, or ranking.
2. Resolve an exact released policy revision and relationship lineage.
3. Deny unknown subjects, actions, objects, adapters, and scopes.
4. For effects, require a current exact request and one-use or budgeted grant.
5. Invoke only an allowlisted fingerprinted adapter through an unforgeable live
   handle.
6. Store redacted decision, attempt, receipt, reconciliation, and incident facts.
7. Recheck authority at commit and effect boundaries to catch drift or revocation.

**Worked example:** an AI session proposes exporting an IFC file. The session has
read authority for the selected published model but no export capability. The
founder approves one export to a specific destination and format. An expiring
grant binds session, object revision, adapter fingerprint, action, destination,
budget, and policy. The adapter returns a digest and outcome receipt. Reuse,
destination drift, or adapter drift is denied.

**Failure/counterexample:** a Cell atom contains `{"isAdmin":true}` or an API
token. Host code trusts the text, or an agent chooses an arbitrary filesystem
path. The graph has confused a claim with authority and has leaked a secret.

### WHO

Identity providers authenticate; released graph policy authorizes; designated
approvers grant consequential operations; adapters execute only their admitted
physical scope; operators own monitoring and incident response. Agents and model
providers are untrusted proposers unless separately granted a specific action.

### WHEN

Evaluate before reads, projections, ranking, edits, releases, and effects. Recheck
at commit and invocation. Expire and revoke grants. Rotate keys according to
custody policy. Treat authorization, adapter, policy, model, and data-class drift
as fail-closed conditions.

### WHERE

Policies, public fingerprints, protected references, requests, decisions,
receipts, and redacted evidence live in the graph. Secret bytes and private keys
remain in admitted OS or cloud key custody. Live handles remain in process memory
and never enter atoms, logs, prompts, URLs, or command arguments.

### PROOF

- **Authority:** [SPEC.md section 9](./SPEC.md) and the accepted
  [versioned state and security strategy](../../30.KNOWLEDGE/strategy/node-language-versioned-state-security-authority-2026-07-15.md).
- **WIP constitutional translation, not released compliance:**
  [Core Values governance translation](../../30.KNOWLEDGE/strategy/core-values-governance-authority-2026-07-16.md).
- **Literature:** [NIST SP 800-162 ABAC](https://csrc.nist.gov/pubs/sp/800/162/upd2/final),
  [NIST SP 800-207 Zero Trust](https://csrc.nist.gov/pubs/sp/800/207/final),
  [WASI v0.2.11 Capabilities](https://github.com/WebAssembly/WASI/blob/v0.2.11/docs/Capabilities.md),
  [OAuth 2.0 Security BCP RFC 9700](https://www.rfc-editor.org/rfc/rfc9700.html),
  and [OWASP Authorization guidance](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html).
- **Executable courts:** `tests_replica/test_cell_authorization.py`,
  `tests_replica/test_cell_adapters.py`,
  `tests_replica/test_cell_secret_keys.py`,
  `tests_replica/test_cell_device_keys.py`, and
  `tests_replica/test_relation_security.py`.
- **Court not yet sufficient:** independent penetration testing, real cloud KMS,
  remote tenant isolation, incident recovery, and the full packaged threat model
  are not proven complete.

## 12. Macro and Meso: Agent Sessions, Attention, Brain, and Coordination Proposals

Scale: macro coordination, meso agent/session assemblies, micro assignments.

### WHAT

An agent body, model binding, runtime session, focus, context, assignment,
proposal, decision, outcome, and cost record are graph compositions. An external
model or CLI may temporarily **possess** an authorised agent/session composition;
it is not the composition and does not become authority.

The following definitions are normative restatements of `SPEC.md` section 5:

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
  authority, evidence, effect receipt, reconciliation, and
  reversal/compensation.

These are standard compositions, not Cell kinds. Brain is a named lawful lens and
region over the same graph for memory, attention, obligations, evidence, and
governance; it is not a second store.

**Non-normative coordination proposal:** `Workshop` and `BABOOM` are names used by
[BABOOM.md](./BABOOM.md) and WIP/research material for possible coordination and
founder-facing lenses. `SPEC.md` and `AUTHORITY.md` have not adopted that named
architecture. This handbook therefore does not require those names, surfaces, or
workflows, and their current implementations cannot become authority by existing.

### WHY

Model context is temporary and incomplete. Persisting identity, signals, focus,
obligations, decisions, outcomes, and evidence in the graph allows different
models and devices to continue coherent work without treating a prompt transcript
as truth. Explicit attention reasons also prevent a model's hidden relevance score
from becoming policy.

### HOW

An admitted session binds:

```text
agent body
  -> authenticated runtime/session
  -> model and provider descriptor revision
  -> authority and capability bounds
  -> current focus and obligations
  -> admitted context sources and budgets
  -> assignments, proposals, decisions, outcomes, receipts
```

The first attention ordering policy is the visible partial order required by
`SPEC.md`:

1. safety and data-loss risk;
2. explicit user/founder pin;
3. blocking dependency;
4. failed active court;
5. accepted due work and fairness;
6. optional model-proposed relevance.

Every ordering edge has an inspectable reason. Model output is untrusted proposal
evidence and cannot broaden scope or authority. Candidate roots are authorised
before ranking; hidden roots cannot influence visible counts, order, explanation,
embeddings, or model context.

An assignment references exact obligation, scope, actor/session, authority,
source revision, and required evidence. Every admitted reviewer receives the same
bounded, redacted coordination facts at the same graph revision. Reviews are
evidence, not commands. A later reviewer can see admitted earlier review evidence
without receiving protected roots or credentials.

**Worked example:** a visual-editor obligation is assigned to two authorised agent
sessions: one implements a bounded fix and one performs independent browser and
security review. Both reference the same obligation, scope, authority, plan, and
court roots. The reviewer records findings as evidence. Promotion remains blocked
until the exact court and approval relations are satisfied. A future coordination
lens may present this as a `Workshop`, but that label is not part of the normative
mechanism.

**Failure/counterexample:** agents coordinate in a Python dictionary chat room;
each wrapper injects a different prompt; a global JSON scope file is overwritten
by whichever agent runs last. Projecting that dictionary into Cells after the
fact does not make the room authoritative or adopt `Workshop` as architecture.

### WHO

The founder sets constitutional intent and approval thresholds. Released graph
policy determines assignment eligibility. Agent sessions propose and perform only
bounded work. Independent reviewers challenge evidence. Brain may order authorised
attention but cannot mint authority. External providers receive only admitted,
redacted context.

### WHEN

Create a session after device/runtime identity and authority are verified. Bind
context and focus at a named snapshot. Refresh or close sessions explicitly.
Signals, attention, focus, obligations, cursors, decisions, and outcomes survive
process close, session reopen, and machine-restart simulation. Revoke access when
policy, assignment, or custody changes; an open process does not prove current
authority.

### WHERE

Session semantics, assignments, signals, attention, focus, Brain obligations, and
evidence live in the graph. Model weights, provider infrastructure, process
memory, CLI transport, and MCP connections are external machinery behind admitted
boundaries. A local daemon being alive does not prove the current session is
connected or authorised. Any `Workshop` or `BABOOM` presentation remains a
non-normative projection unless adopted through the authority change protocol.

### PROOF

- **Authority:** [SPEC.md sections 5, 6, and 9](./SPEC.md) and
  [AUTHORITY.md](./AUTHORITY.md).
- **WIP/research evidence, not authority:** [BABOOM.md](./BABOOM.md) and the
  [persistent graph attention strategy](../../30.KNOWLEDGE/strategy/persistent-graph-attention-reconciliation-2026-07-16.md).
- **Literature:** the dated
  [PROV-O Recommendation](https://www.w3.org/TR/2013/REC-prov-o-20130430/) defines
  an ontology for entities, activities, agents, and qualified provenance
  relations; it does not prove truth, causality, or authorization. AI risk controls
  are addressed by the
  [NIST Generative AI Profile](https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-generative-artificial-intelligence).
- **Executable courts for adopted session/attention mechanisms:**
  `tests_replica/test_cell_agent_body.py`,
  `tests_replica/test_cell_agent_cognition.py`, and
  `tests_replica/test_cell_attention.py`.
- **WIP/proposal mechanism evidence:**
  `tests_replica/test_universal_workshop_authority.py` and
  `tests_replica/test_baboom_single_authority.py` do not adopt the proposed named
  architecture or prove it released.
- **Court not yet sufficient:** live external provider sessions, cross-device
  continuation, complete one-graph Brain replacement, and any later-adopted
  coordination surface are not claimed complete.

## 13. Meso and Micro: Visual Authoring and Presentation

Scale: meso workspace, micro direct manipulation, floor evidence on demand.

### WHAT

The visual workspace is the primary language surface. Cards present roots;
sockets present real interfaces; cables present relations/incidences; the left
catalogue presents released assemblies; the right rail presents applicable
Properties. The application itself is the top openable composition.

Visual appearance is graph state too: design tokens, component definitions,
icons, card and cable presentation, interaction policies, accessibility metadata,
and personal WIP overrides are versioned graph regions.

### WHY

Backend universality is useless to a nontechnical user if authoring requires code,
the canvas lies about topology, or controls cannot be discovered. Direct
manipulation gives the user visible causality and control while progressive
visibility prevents the floor from overwhelming ordinary work.

### HOW

Core interaction rules:

- wheel zoom is cursor-centred;
- pan, drag, wire, resize, and marquee use pointer capture;
- left-to-right marquee contains, right-to-left marquee crosses;
- Ctrl adds/toggles and Shift removes or extends according to released policy;
- gestures paint locally at animation-frame cadence and commit once at completion;
- double-click or Enter opens a composition; breadcrumbs return;
- selecting roots, sockets, relations, incidences, rules, or presentation opens
  the applicable Properties composition;
- tabs exist only when graph-defined and applicable;
- Add Parameter, Add Interface, Add Relation, Group, Ungroup, Rewire, Delete,
  Undo, and Redo are graph-defined governed interactions.

The exact `SPEC.md` release performance requirements are:

| Interaction measure | Required threshold |
|---|---|
| Pointer frame | p95 <= 16.7 ms |
| Selection feedback | same frame |
| Local mutation acknowledgement | <= 100 ms |
| Bounded scope entry | <= 150 ms |
| Steady-state long task | no task > 50 ms on the reference machine |

These are normative targets, not current results. Acceptance requires measurements
from the exact packaged artifact and declared reference machine.

**Worked example:** the user selects a room card, opens Presentation, and changes
its card color. The edit creates a personal WIP token/binding revision and updates
the preview without affecting other users. The user then drags from the room's
real `Schedule source` socket to an Ordered List's compatible interface. The
preview highlights only admitted targets; pointer release commits an explicit
relation and incidences. Undo appends a compensating revision.

**Failure/counterexample:** the UI shows generic dots, dead tabs, raw IDs, and a
static line between card centres. A color is changed in CSS, selection lives only
in JavaScript, and the page rebuilds all DOM after every pointer move. The screen
is a report about a backend, not the language.

### WHO

Ordinary users receive a clear Use experience. Authors receive Build tools allowed
by their scope. Stewards use Govern. Floor inspection is restricted. Keyboard and
pointer users must have equivalent actions. Agents use the same composer and
cannot bypass visual/graph interaction authority through a private API.

### WHEN

Project only the active bounded scope and lens. Give same-frame local feedback,
then reconcile the accepted graph revision. Personal design changes begin as WIP.
Run real-browser interaction, accessibility, performance, and security courts on
the actual artifact before release.

### WHERE

Authoritative selection, scope, committed viewport, interactions, presentation,
and design decisions live in the graph. Transient hover and gesture paint live in
the browser. HTML, CSS, SVG, and canvas are replaceable render targets, never
semantic authority.

### PROOF

- **Authority:** [SPEC.md section 7](./SPEC.md), the
  accepted [node-native design strategy](../../30.KNOWLEDGE/strategy/node-native-design-system-visibility-interaction-architecture-2026-07-16.md).
- **Adversarial evidence, not authority:** the RED
  [visual authority audit](../../30.KNOWLEDGE/strategy/universal-visual-authority-adversarial-audit-2026-07-16.md)
  records observed failures and required challenges; it does not define the
  language or prove a repair.
- **Literature:** the dated
  [Pointer Events Level 3 Candidate Recommendation Draft](https://www.w3.org/TR/2026/CRD-pointerevents3-20260522/),
  [WCAG 2.2 dated Recommendation](https://www.w3.org/TR/2024/REC-WCAG22-20241212/),
  [WAI-ARIA Authoring Practices 1.2 dated Note](https://www.w3.org/TR/2021/NOTE-wai-aria-practices-1.2-20211129/),
  [DTCG 2025.10](https://www.designtokens.org/tr/2025.10/format/), and mature
  composition interaction in [Blender Node Groups](https://docs.blender.org/manual/en/4.5/interface/controls/nodes/groups.html).
- **Executable courts:** `tests_replica/test_universal_ui_interactions.py`,
  `tests_replica/test_universal_ui_performance.py`,
  `tests_replica/test_browser_graph_editor_court.py`, and
  `tests_replica/test_browser_publish_court.py`.
- **Court not yet sufficient:** source-string, DOM-only, and backend tests cannot
  release the editor. The isolated real-browser court must pass the exact current
  artifact, including scope, selection, parameter creation, relation creation,
  Properties, group/ungroup, undo, accessibility, errors, and performance.

## 14. Macro to Floor: Conformance and Migration

Scale: all scales, capability by capability.

### WHAT

Conformance means a capability uses the one Cell floor, one root identity,
graph-held meaning, explicit causality, lawful lenses, lifecycle, security, and
applicable courts without a hidden fallback authority.

Migration consumes the legacy capability only after its graph-native replacement
passes intentionally superseding courts. Legacy code is evidence and comparison
material during migration, not automatic authority.

### WHY

A visually similar replacement can still lose identity, security, history, or
behavior. Deleting legacy work too early destroys evidence and may interrupt live
sessions. Keeping it forever creates two engines. A staged authority handoff
avoids both failures.

### HOW

For each capability:

1. Trace the founder requirement and controlling source.
2. Identify every current authority, copy, projection, and physical dependency.
3. Define the graph protocol and red courts.
4. Implement on the Universal Cell floor without product dispatch.
5. Verify security, restart, causality, usability, accessibility, and performance.
6. Switch the authoritative path through a controlled handoff.
7. Prove no fallback recreates or bypasses the old authority.
8. Archive or remove the consumed path with evidence and rollback policy.

**Worked example:** migrating a legacy Brain task table begins by mapping task
identity, scope, status, assignments, evidence, and hooks. The replacement models
  them as obligation/work/session relations. Courts prove restart, authorization,
  same-root coordination and Brain lenses, and no writes to the old table. Only
  then is the old mutator retired; a read-only migration record may remain. A
  later adopted coordination surface could be named `Workshop`, but migration
  does not assume that proposal.

**Failure/counterexample:** a new graph screen reads the old task table and wraps
each row as a temporary Cell projection. The old table still decides behavior, so
the graph is a facade. Deleting the old table at this point breaks the product.

### WHO

The founder controls product intent and acceptance. Protocol owners define the
replacement. Implementers build bounded slices. Independent reviewers challenge
security and equivalence. Operators perform controlled handoff and rollback.
No agent may declare its own implementation complete.

### WHEN

Migrate one bounded capability only after its authority is coherent and red courts
exist. Do not interrupt a live session or runtime without explicit controlled
handoff. Retire only after replacement, no-fallback, and recovery evidence pass.

### WHERE

Normative target lives in `SPEC.md`; precedence in `AUTHORITY.md`; mutable truth in
revision-bound evidence; historical sources in governed archive; implementation
and courts in the product tree. The production authority path must be explicit at
every migration revision.

### PROOF

- **Authority:** [SPEC.md sections 11-12](./SPEC.md) and
  [AUTHORITY.md change protocol](./AUTHORITY.md).
- **Literature:** provenance vocabulary in the dated
  [PROV-O Recommendation](https://www.w3.org/TR/2013/REC-prov-o-20130430/),
  transparent history concepts in pinned
  [Git revisions 2.51.0](https://git-scm.com/docs/revisions/2.51.0/),
  and supply-chain attestations in [SLSA Provenance v1.2](https://slsa.dev/spec/v1.2/provenance).
- **Executable courts:** `tests_replica/test_authority_coherence.py`,
  `tests_replica/test_universal_authority_migration.py`,
  `tests_replica/test_legacy_runtime_ratchet.py`, and
  `tests_replica/test_no_legacy_drift.py`.
- **Court not yet sufficient:** a zero-legacy, complete, packaged, cloud-deployed,
  independently reviewed ArchHub system is not proven by current scoped migration
  courts.

## 15. Recursive Worked Example: A Governed Geometry Watcher

Scale: macro, meso, micro, and floor in one example.

### WHAT

The example is a reusable `Geometry Change Watcher` that observes a model
revision, evaluates a graph-held condition, records an obligation, and optionally
requests an external BIM-host highlight. It demonstrates how one useful catalogue
item reduces all the way to the one Cell floor without becoming a native kind.

### WHY

The example combines data, geometry metadata, behavior, presentation, lifecycle,
security, external effects, agents, and visual authoring. If any part needs a
special record type or hidden product dispatch, the language has failed its own
universality claim.

### HOW

**Macro:** the Application root exposes Project, Brain, authorised work
coordination, and Models regions. One geometry revision root appears in all four
lawful lenses with the same identity. A `Workshop` label would remain a
non-normative proposal until adopted through `AUTHORITY.md`.

**Meso:** the catalogue contains an exact released `Geometry Change Watcher`
definition. Its public interfaces are `geometry revision`, `change policy`,
`obligation output`, and optional `host highlight request`. Instantiation creates
a WIP composition bound to that definition revision.

**Micro:** relation roots connect the geometry descriptor, watcher cursor, policy
rule, focus/obligation destination, presentation, and adapter request. Each
participant has an incidence identity. Properties relate the watcher to label,
enabled state, threshold, audience, and lifecycle.

**Floor:** all semantic pieces are Cells. A committed geometry descriptor change
is observed. A bounded match resolves the rule. Rewrite appends an obligation and
advances the cursor. If authorised, invoke passes an exact request through an
allowlisted BIM adapter; the receipt is reconciled into the graph.

**Worked example path:**

```text
Architect edits model in admitted BIM host
  -> adapter reports new content digest and geometry metadata
  -> graph commits GeometryRevision G18
  -> observe emits durable signal S18
  -> Watcher W3 matches released Rule R7 against G18
  -> rewrite appends Obligation O22 and advances Cursor C3
  -> Brain lens focuses O22 with explicit reason
  -> released assignment policy relates O22 to an authorised session
  -> optional host-highlight request H9 is approved and invoked
  -> adapter receipt E9 records accepted/failed/unknown outcome
  -> user sees result and can inspect every causal relation
```

**Failure/counterexample:** a file watcher notices a timestamp, calls a hard-coded
geometry function, sends a model path to an AI, and updates a dashboard badge.
There is no content revision, rule root, authorization, incidence, cursor,
receipt, replay protection, or shared identity.

### WHO

The architect controls the model and approves consequential host effects. The
Watcher reacts only within released policy. Brain orders authorised attention.
Released assignment policy assigns review. An agent may investigate the
obligation. The BIM adapter performs only the granted host action. Reviewers and
courts establish release evidence.

### WHEN

The watcher reacts only after a durable committed revision and only once per
deduplication/cursor policy. It creates WIP obligation state before any external
effect. External unknown outcomes remain unknown until reconciled. Rule, adapter,
authority, or model revision drift forces revalidation.

### WHERE

Geometry bytes may stay in admitted content-addressed storage or the BIM host.
Their semantic descriptors, digests, coordinate systems, revisions, relations,
rules, assignments, and receipts live in the graph. The host process and its API
remain outside behind the adapter boundary.

### PROOF

- **Authority:** all of [SPEC.md](./SPEC.md), especially sections 3-9.
- **Literature:** IFC relationship and coordinate concepts in
  [buildingSMART IFC 4.3](https://standards.buildingsmart.org/IFC/RELEASE/IFC4_3/HTML/),
  content descriptors in the pinned
  [OCI Image Specification v1.1.1](https://github.com/opencontainers/image-spec/blob/v1.1.1/descriptor.md),
  provenance vocabulary in the dated
  [PROV-O Recommendation](https://www.w3.org/TR/2013/REC-prov-o-20130430/), and capability security
  in [NIST SP 800-207](https://csrc.nist.gov/pubs/sp/800/207/final).
- **Executable courts:** component mechanisms have courts in
  `tests_replica/test_cell_content_descriptors.py`,
  `tests_replica/test_cell_reactions.py`,
  `tests_replica/test_cell_attention.py`,
  `tests_replica/test_cell_adapters.py`, and
  `tests_replica/test_cell_lifecycle.py`.
- **Court not yet implemented:** there is no single end-to-end real-BIM-host court
  proving this complete example, including provider ambiguity, geometry round
  trip, visual causality, restart, compensation, and packaged performance.

## 16. Normative Target Versus Current Implementation Status

Scale: macro status with evidence traceable to meso, micro, and floor courts.

### WHAT

The normative target states what ArchHub MUST become. Current implementation
status states what an exact revision and artifact actually proved. They are
different facts and must remain in different authorities.

This handbook records language semantics and evidence locations. It does not
maintain mutable pass counts or percentages.

The current `evidence/current-evidence.json` was generated at
`2026-07-21T19:08:35.441233+00:00`. Because controlling sources and implementation
changed on 2026-07-22, that file is stale for the present source state. It cannot
prove current behavior, court acceptance, completion, or release eligibility
until regenerated against the exact current revision and artifact.

### WHY

Copying status into specifications and manuals makes it stale and encourages a
focused green test to be reported as product completion. Separating target from
evidence preserves truth and lets automation regenerate status from exact runs.

### HOW

Use this evidence chain:

```text
founder decision / Core Values
  -> AUTHORITY.md precedence
  -> SPEC.md normative requirement
  -> graph obligation and applicable court
  -> exact source revision + artifact + environment
  -> executable result and retained evidence
  -> status projection with explicit open boundaries
```

The founder Core Values are constitutional input, but their software translation
remains WIP until founder-reviewed and released. Every released slice maps all ten
values to exact controls or explicit gaps; partial coverage cannot be shown as
compliant:

| Core Value | Required release mapping |
|---|---|
| Security is Sacred Trust | threat model, least privilege, secret handling, privacy, incident and recovery evidence |
| Truth Over Comfort | honest status, residual risk, and no false completion |
| You Build It, You Own It | named owner, operation, observability, maintenance, and decommission path |
| Respect Every Second | measured latency, bounded work, direct manipulation, and no needless user ceremony |
| Architect Review Mandatory | founder/architect review at the defined authority threshold |
| Solve Real Pain | traced founder/user requirement and outcome evidence |
| Simplicity Conquers Complexity | one physical model, progressive disclosure, and justified assemblies |
| Test What You Ship | courts on the real packaged artifact |
| Break It Down, Iterate Fast | bounded WIP slices without partial-green claims |
| Fix Root Causes | contradiction and recurrence analysis, not cosmetic patches |

**Worked example:** `SPEC.md` requires real interface sockets. A source test that
finds the word `socket` is not evidence. A backend court may prove incidence
identity but not usability. Release needs a real-browser court on the actual
artifact proving each visible socket maps to an authorised interface and remains
correct through select, connect, rewire, undo, scope entry, and restart where
applicable.

**Failure/counterexample:** `155 tests passed` is copied into a design document and
presented as `the application is 80% complete`. The count is stale, omits untested
boundaries, and has no defined denominator.

### WHO

Implementers produce evidence. Independent reviewers challenge it. Release
authority decides whether the applicable court set is sufficient. The founder
accepts or rejects product experience and constitutional alignment. No model,
test author, or dashboard can self-certify completion.

### WHEN

Generate evidence after source and artifact are fixed. Rerun after any relevant
change. Recheck externally variable sources at design/release review. Mark a court
red, missing, stale, or not run instead of inferring green.

### WHERE

- Target: [SPEC.md](./SPEC.md)
- Precedence: [AUTHORITY.md](./AUTHORITY.md)
- Research and rejected alternatives: [RESEARCH-UNIVERSAL-CELL.md](./RESEARCH-UNIVERSAL-CELL.md)
- Mutable evidence location:
  [`evidence/current-evidence.json`](./evidence/current-evidence.json). The present
  file is stale for the 2026-07-22 sources and cannot establish present behavior
  until regenerated against an exact current revision and artifact.
- Historical authority: governed `90.ARCHIVE` manifest named by `AUTHORITY.md`

### PROOF

- **Authority:** [AUTHORITY.md sections "Revision-bound implementation evidence"
  and "Mutable truth"](./AUTHORITY.md), plus [SPEC.md section 11](./SPEC.md).
- **Literature:** provenance vocabulary in the dated
  [PROV-O Recommendation](https://www.w3.org/TR/2013/REC-prov-o-20130430/) and
  signed statement structures in the pinned
  [in-toto Statement v1.2.0](https://github.com/in-toto/attestation/blob/v1.2.0/spec/v1/statement.md).
- **Executable mapping evidence:**
  `tests_replica/test_authority_coherence.py` addresses a bounded authority
  mapping. Its present result must be rerun because the evidence file is stale.
- **Normative rule, not a court:** the no-false-done requirement is in `SPEC.md`
  section 11.
- **Bounded revision-bound handbook court:**
  `tests_replica/test_node_language_handbook_conformance.py` binds the reviewed
  handbook, `SPEC.md`, and `AUTHORITY.md` digests; verifies the recursive teaching
  contract, adopted attention and performance restatements, source
  classification, and declared link/court paths. It does not establish semantic
  correctness or product release, and it cannot replace the real implementation,
  browser, security, usability, or artifact courts.

## 17. Sources Matrix and Maintenance

Scale: macro source governance, meso concept mapping, micro citations, floor
revision evidence.

### WHAT

This matrix separates controlling ArchHub authority from external literature.
External sources provide precedent, constraints, or comparison; they do not
override the founder or `SPEC.md`.

| Source | Role in this handbook | Limit | Verification/classification |
|---|---|---|---|
| [AUTHORITY.md](./AUTHORITY.md) | Precedence, supersession, and change protocol | Does not define a second language | Controlling local authority reviewed 2026-07-22 |
| [SPEC.md](./SPEC.md) | Normative Node Language target | Does not report mutable completion | Controlling local specification reviewed 2026-07-22 |
| [RESEARCH-UNIVERSAL-CELL.md](./RESEARCH-UNIVERSAL-CELL.md) | Research, alternatives, and contradiction record | Never authority unless formally promoted | WIP/research evidence |
| [BABOOM.md](./BABOOM.md) | Candidate assistant/coordination boundary and presentation | Named Workshop/BABOOM architecture is not adopted by `SPEC.md` or `AUTHORITY.md` | WIP proposal, never authority |
| [Design/visibility strategy](../../30.KNOWLEDGE/strategy/node-native-design-system-visibility-interaction-architecture-2026-07-16.md) | UI, lens, catalogue, and interaction detail within its accepted scope | Its open gaps remain open and it cannot claim implementation | Accepted detailed decision per `AUTHORITY.md` |
| [Versioned state/security strategy](../../30.KNOWLEDGE/strategy/node-language-versioned-state-security-authority-2026-07-15.md) | Lifecycle, security, identity, and external-effect detail within its accepted scope | Physical providers still need real courts | Accepted detailed decision per `AUTHORITY.md` |
| [Core Values governance translation](../../30.KNOWLEDGE/strategy/core-values-governance-authority-2026-07-16.md) | Candidate mapping from founder values to controls | Partial coverage cannot be called compliant | WIP until founder-reviewed and released |
| [Persistent graph attention strategy](../../30.KNOWLEDGE/strategy/persistent-graph-attention-reconciliation-2026-07-16.md) | Research supporting attention, focus, and obligation design | Cannot override the definitions and ordering in `SPEC.md` | WIP/research evidence, never authority |
| [Visual authority audit](../../30.KNOWLEDGE/strategy/universal-visual-authority-adversarial-audit-2026-07-16.md) | RED findings, rejected UI patterns, and adversarial test demands | Findings do not define architecture or prove repair | Adversarial evidence, never authority |
| [A History of Lisp](https://dl.acm.org/doi/10.1145/38807.38828) | Cons-cell and symbolic composition lineage | Historical precedent is not proof of ArchHub sufficiency | Stable DOI, primary paper |
| [Kernel first-class operative model](https://web.cs.wpi.edu/~jshutt/kernel.html) | Minimal evaluator and first-class operative precedent | Not ArchHub's Cell floor or security model | Primary author page; unverified-current and no immutable revision pin, reverify at release |
| [Interaction nets](https://doi.org/10.1006/inco.1997.2643) | Local graph interaction/rewrite precedent | Does not define ArchHub persistence, authority, or UI | Stable DOI, primary paper |
| [RDF 1.2 Concepts dated CR](https://www.w3.org/TR/2026/CR-rdf12-concepts-20260407/) | RDF graph/triple, IRI, and reification precedent | It does not by itself define graph identity, history, execution, or authorization; this is a Candidate Recommendation | Dated W3C snapshot |
| [Maude rewriting logic](https://maude.cs.illinois.edu/papers/abstract/tcs4009.html) | Reflective executable rewrite precedent | Not ArchHub's UI or security model | Primary research page; unverified-current, reverify at release |
| [Blender 4.5 Node Groups](https://docs.blender.org/manual/en/4.5/interface/controls/nodes/groups.html) | Reusable openable composition interaction | Blender's node taxonomy is not adopted | Versioned official manual |
| [IFC 4.3 documentation](https://standards.buildingsmart.org/IFC/RELEASE/IFC4_3/HTML/) and [IfcRelationship](https://standards.buildingsmart.org/IFC/RELEASE/IFC4_3/HTML/lexical/IfcRelationship.htm) | AEC relationship, geometry, and coordinate precedent | IFC entities and types are not kernel kinds | Versioned buildingSMART release |
| [OpenUSD UsdRelationship v26.05](https://github.com/PixarAnimationStudios/OpenUSD/blob/v26.05/pxr/usd/usd/relationship.h) | Editable relationship-target precedent | OpenUSD's schema and implementation are not adopted | Pinned official release tag |
| [DTCG 2025.10 Format](https://www.designtokens.org/tr/2025.10/format/) | Token interchange, aliases, groups, and cycle constraints | DTCG JSON is a projection, not Cell authority | Versioned specification |
| [Dynamo Library](https://primer2.dynamobim.org/3_user_interface/2-library) | Architect-facing catalogue discoverability | Dynamo node types are not adopted | Official living documentation; unverified-current, reverify at release |
| [Adapton paper](https://arxiv.org/abs/1503.07792) | Incremental dependency/recomputation precedent | Does not define ArchHub authority or durable effects | Versioned primary paper record |
| [WASI v0.2.11 Capabilities](https://github.com/WebAssembly/WASI/blob/v0.2.11/docs/Capabilities.md) | Capability-oriented host boundary precedent | External prior art, not ArchHub's admitted adapter policy | Pinned official release tag |
| [WCAG 2.2 dated Recommendation](https://www.w3.org/TR/2024/REC-WCAG22-20241212/) | Accessibility requirements | Passing WCAG alone does not prove usability | Dated W3C Recommendation |
| [WAI-ARIA Authoring Practices 1.2](https://www.w3.org/TR/2021/NOTE-wai-aria-practices-1.2-20211129/) | Keyboard, focus, and widget interaction patterns | Examples are not a substitute for product-specific usability courts | Dated W3C Note |
| [Datomic transactions](https://docs.datomic.com/transactions/model.html) | Immutable database values and transaction precedent | Not ArchHub's universal visual language | Official living documentation; unverified-current, reverify at release |
| [PostgreSQL 18 MVCC](https://www.postgresql.org/docs/18/mvcc-intro.html) | MVCC and serialization-failure precedent | Database concurrency does not define graph lifecycle | Versioned official manual |
| [W3C PROV-O dated Recommendation](https://www.w3.org/TR/2013/REC-prov-o-20130430/) | Ontology for entities, activities, agents, and qualified provenance relations | It does not prove truth, causality, append-only storage, or authorization | Dated W3C Recommendation |
| [UK BIM Framework CDE guidance](https://ukbimframework.org/wp-content/uploads/2020/09/Guidance-Part-C_Facilitating-the-common-data-environment-workflow-and-technical-solutions_Edition-1.pdf) | WIP/Shared/Published/Archive information workflow | Product, deployment, operation, and external-outcome axes remain separate | Dated primary industry guidance |
| [NIST SP 800-162](https://csrc.nist.gov/pubs/sp/800/162/upd2/final) | Attribute-based authorization model | Must be adapted to explicit graph relationships | Final official publication |
| [NIST SP 800-207](https://csrc.nist.gov/pubs/sp/800/207/final) | Zero-trust and least-privilege constraints | Does not define the Node Language | Final official publication |
| [RFC 9700](https://www.rfc-editor.org/rfc/rfc9700.html) | OAuth 2.0 security best-current-practice constraints | Applies only where OAuth is used | Immutable RFC |
| [OWASP Authorization Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html) | Deny-by-default and authorization review guidance | Guidance is not a formal ArchHub policy or proof | Official living document; unverified-current, reverify at release |
| [NIST Generative AI Profile](https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-generative-artificial-intelligence) | Generative-AI risk management controls | Does not define agent-session graph semantics | Final official publication page |
| [Pointer Events Level 3 dated CRD](https://www.w3.org/TR/2026/CRD-pointerevents3-20260522/) | Pointer capture and input semantics | Browser events are not graph authority; CRD is not a final Recommendation | Dated W3C snapshot |
| [Git revisions 2.51.0](https://git-scm.com/docs/revisions/2.51.0/) | Revision-selection and ancestry terminology | Git history is not ArchHub's semantic graph | Version-pinned official manual |
| [SLSA Provenance v1.2](https://slsa.dev/spec/v1.2/provenance) | Artifact provenance and supply-chain evidence | Does not replace ArchHub courts | Versioned specification |
| [OCI Image Specification v1.1.1 descriptor](https://github.com/opencontainers/image-spec/blob/v1.1.1/descriptor.md) | Content-addressed descriptor precedent | OCI descriptors do not define BIM or graph semantics | Pinned official release tag |
| [in-toto Statement v1.2.0](https://github.com/in-toto/attestation/blob/v1.2.0/spec/v1/statement.md) | Signed statement envelope precedent | Does not establish claim truth or product acceptance | Pinned official release tag |
| [RFC 9162](https://www.rfc-editor.org/rfc/rfc9162.html) | Append-only transparency-log precedent | Certificate transparency logs are not ArchHub history | Immutable RFC |

### WHY

A source matrix prevents literature from being used as decorative justification
or silently promoted into authority. It also records each precedent's limit so
similarity is not mistaken for equivalence or novelty proof.

### HOW

For every handbook change:

1. identify the controlling ArchHub source;
2. check whether the claim is normative, explanatory, or mutable status;
3. use current official or primary literature for external standards and
   time-sensitive technical claims;
4. state what the source proves and what it does not prove;
5. link an executable court or write `court not yet implemented`;
6. preserve ASCII unless a source name requires otherwise;
7. rerun the reproducible local structural, internal-link, court-path, source-
   coverage, ASCII, and word-count checks. These checks are not courts.

**Worked example:** a new `Spatial Query` assembly may cite IFC and an official
BIM tool API as literature, but its semantics must be defined by an accepted
graph protocol, its host call must use an admitted adapter, and its release needs
real geometry, authorization, restart, and visual courts.

**Failure/counterexample:** a blog says a framework is `graph-native`, so an agent
copies its class hierarchy into the kernel and calls the design researched. The
source was neither primary nor controlling, and the imported taxonomy violates
the one-Cell rule.

### WHO

Authors maintain citations and concept mappings. Reviewers verify source quality,
freshness, logic, and limits. Security and standards claims require appropriate
specialist review. The founder decides whether a proposal becomes product
authority.

### WHEN

Review the matrix whenever authority changes, an external standard is superseded,
a court is added or retired, or a release depends on an externally variable
claim. Do not rewrite historical evidence to match a later decision.

### WHERE

This handbook holds the teachable map. Controlling wording stays in its authority
source. External documents remain linked at canonical official or primary URLs.
Mutable execution results remain in revision-bound evidence.

### PROOF

- **Authority:** [AUTHORITY.md change protocol](./AUTHORITY.md).
- **Literature:** the direct sources in the matrix above.
- **Local check, not a court:** the reproducible structural check verifies every
  numbered `##` section contains `WHAT`, `WHY`, `HOW`, `WHO`, `WHEN`, `WHERE`, and
  `PROOF`, plus a worked example, failure/counterexample, authority, literature,
  and court-status marker. Separate local checks resolve internal links and court
  paths, compare cited external URLs with this matrix, enforce ASCII, and count
  words. None establishes semantic correctness or release acceptance.
- **Bounded revision-bound handbook court:**
  `tests_replica/test_node_language_handbook_conformance.py` locks an exact
  reviewed handbook, specification, and authority revision and checks recursive
  structure, adopted normative anchors, link/court resolution, source-matrix
  coverage, mutable-link policy, ASCII, and honest WIP labels. It does not
  establish semantic correctness or product release, verify external source
  truth/freshness, or make this handbook a second authority.
