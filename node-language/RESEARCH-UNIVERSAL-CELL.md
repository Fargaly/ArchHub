# Universal Cell Architecture Room

**Status:** LIVE RESEARCH COURT
**Host:** Antigravity IDE, `00.ARCHUB` workspace
**Authority:** Founder direction + repository specifications + primary literature + executable forcing tests
**Decision rule:** A model's answer is evidence, never authority. No proposal is accepted until it survives the founder test and executable counterexamples.

**Authority relation (2026-07-16):** This file is research, rejected-proposal,
decision-history, and implementation evidence. Normative product requirements now
reside in `SPEC.md`; precedence and supersession reside in `AUTHORITY.md`. If this
transcript or one of its mutable progress statements conflicts with those files,
it is evidence of drift rather than permission to change the architecture.

## Founder Authority

The application is not a catalogue of node classes. It is built from one universal, recursively inspectable and editable cell. A value, property, parameter, function, behavior, condition, presentation, port, relation, container, session, secret policy, database, Brain, Cockpit, Grand Map, application, and website must be arrangements of the same cell anatomy.

The consequences are strict:

- No `kind = value | group | session | ui | wire | ...` class tag.
- No privileged `Group` cell required merely to contain cells.
- No nested port/property/parameter records that are not themselves cells.
- No semantic relationship that exists outside an explicit, manipulable relation-cell.
- No hidden behavior selected by a catalogue of engine operation names.
- No property, parameter, policy, presentation, or function that becomes opaque below the selected cell.
- A cell may participate in several roles at once because roles are protocols made from cells, not exclusive classes.
- Recursive interpretation stops only at an honest native boundary: identity, terminal host data, raw incidence, transaction/rewrite execution, or an external capability. It does not stop at a product concept disguised as a primitive.

## Live Participant Ledger

| Participant | Transport | Entered inference | Current contribution | Court status |
|---|---|---:|---|---|
| Founder | This task | Yes | Defined the non-negotiable universal-cell test | Authority |
| Codex | Governed task + Brain leaf `e793dfeff236bc87` | Yes | Audited the live kernel and literature; maintains this court | Active |
| Nemotron Ultra 550B | OpenRouter free route | Yes | Correctly exposed hidden classes; proposed another disguised taxonomy | Useful finding, proposal rejected |
| Claude CLI | Local CLI | No | OAuth and API-key attempts both rejected before file access | Transport failed |
| Gemini CLI | Local CLI | No | Google rejected the old client and directed migration to Antigravity | Superseded by IDE route |
| Gemini 3.5 Flash | Antigravity IDE agent panel | Yes | Exposed hidden classes; replacement still hid dispatch in string protocols | Proposal rejected |
| Nemotron Super 120B | OpenRouter free route | No | NVIDIA upstream HTTP 429 | Transport failed |
| Qwen3 Next 80B | OpenRouter free route | No | Venice upstream HTTP 429 | Transport failed |
| Llama 3.3 70B | OpenRouter free route | No | Venice upstream HTTP 429 after paced retries | Transport failed |
| Nemotron Nano 30B | OpenRouter free route | Yes | Exposed the taxonomy, then reinstated it in its proposed schema | Proposal rejected |
| Poolside Laguna M.1 | OpenRouter free route | Yes | Reduced storage to `{id,payload}`, then hid the taxonomy inside arbitrary payloads | Proposal rejected |
| Qwen3 Coder 480B | OpenRouter free route | No | Upstream HTTP 429 | Retry later |
| Hermes 3 405B | OpenRouter free route | No | Upstream HTTP 429 | Retry later |

## Discussion Transcript

### 1. Founder

> Nodes are not classifications. A node is like an object with functions, properties, and parameters, while those properties and parameters are also made from the same primitive nodes. Everything must be editable and interpretable up and down. Requiring a special Group node to put another node inside is not a universal language.

### 2. Codex: repository audit

The live kernel contradicts that authority:

```python
KINDS = {
    "value", "op", "wire", "group", "param",
    "session", "ui", "proposal", "secret_ref", "history",
}
GROUPISH = {"group", "session"}
NODE_KEYS = {"id", "kind", "title", "params", "body", "relations", "meta"}
```

`validate_node` gives those labels different legal shapes. Evaluation branches on `kind`, then on `body.floor.op`. Therefore the engine, not the graph, decides what a cell may be. One storage table does not make one universal language when the records still contain hidden classes.

The current specification also contradicts itself: its opening claims one atom and no privileged container, but later sections prescribe special kinds and typed plugs. Those later catalogues are not allowed to overrule the founder authority.

### 3. Nemotron Ultra 550B: useful diagnosis

Nemotron correctly found:

> The `kind` field is a hidden class tag. Structural validation per kind is a meta-layer.

It then proposed a replacement shaped like this:

```text
Cell {
  id,
  ports: {
    port-id: { direction, role, cell, target_port, value, policy, meta }
  },
  content: Literal | Apply | Wire | Scope | If | Ref | HostCap
}
```

### 4. Codex court decision on Nemotron proposal

**REJECTED.** It renames the problem:

- `ports` are second-class nested records instead of cells.
- `direction` and `role` are privileged semantic fields.
- seven `ContentAtom` variants replace ten old `kind` variants.
- hidden dispatch still decides what the cell means.

The useful diagnosis is retained; the proposed anatomy is not.

### 5. Transport evidence

Claude CLI named sessions were created, but Anthropic rejected both authentication paths before inference:

```text
HTTP 401: OAuth access token has been revoked.
HTTP 401: Invalid API key.
```

Gemini CLI started in read-only plan mode, but Google rejected that legacy client:

```text
IneligibleTierError: UNSUPPORTED_CLIENT
This client is no longer supported for Gemini Code Assist for individuals.
Please migrate to the Antigravity suite of products.
```

That is why this room is now hosted in Antigravity IDE and the Gemini participant is called through its native agent panel.

## Candidate Under Attack, Not Yet Accepted

The smallest honest machine currently being tested is:

```text
cell := identity + optional terminal payload
incidence := irreducible storage fact that one identity mentions another identity
meaning := cells connected through incidence, never a hardcoded class field
behavior := cells describing graph matching, rewriting, and transactions
authority := possession/reachability of explicit capability cells
evaluation := resolve protocol cells until a native terminal boundary is reached
```

This is not accepted yet. It must answer four hard attacks:

1. If incidence is also a cell, how are its endpoints stored without an infinite relation-to-relation regress?
2. How can order, direction, role, and arity emerge from cells without hiding them in field names or enums?
3. How can the graph describe and modify its own interpreter without making every edit unsafe or non-terminating?
4. What is the minimum native boundary needed for geometry, images, databases, encryption, AI sessions, UI rendering, and host effects without turning those domains into privileged kinds?

## Shared Prompt For Every Model

Read these real files before answering:

- `10.PRODUCT/13.NODE-LANGUAGE/SPEC.md`
- `10.PRODUCT/13.NODE-LANGUAGE/RESEARCH-UNIVERSAL-CELL.md`
- `10.PRODUCT/13.NODE-LANGUAGE/nodelang/core.py`
- `10.PRODUCT/13.NODE-LANGUAGE/nodelang/laws_relation.py`
- `10.PRODUCT/13.NODE-LANGUAGE/tests_replica/test_forcing_one_table.py`

Then perform an adversarial architecture review. The founder rejects every fixed semantic node taxonomy. Do not propose `Value`, `Group`, `Session`, `Wire`, `Port`, `Function`, `Secret`, `UI`, `Database`, or similar as primitive classes. Do not hide the same taxonomy in record fields, enums, content variants, operation names, or host callbacks.

Derive the minimum honest native floor and show how the same cell anatomy composes all of these:

- scalar value and structured data
- editable property and parameter
- manipulable relation with its own logic, gates, encryption, and presentation
- containment without a privileged Group class
- behavior and conditional logic
- geometry and image flow
- database/query/transaction behavior
- AI session with model, context, tools, governance, and lifecycle as editable relations
- Brain, Cockpit, Grand Map, application, and website as views/compositions of one graph

For every proposed primitive, supply a counterexample showing why it cannot itself be represented by the universal cell. Separate semantic graph state from unavoidable implementation machinery. End with a falsifiable kernel schema and forcing tests, not product prose.

## Primary Literature Being Used

- Self: prototype-based objects, slots, and methods in a live environment. Useful, but slots are not themselves fully first-class graph cells.
- COLA: bootstrapping an open object model. Useful for self-description, but its object categories must be reduced further.
- Kernel and first-class operatives: expose behavior that Lisp hides in special forms.
- 3-Lisp and reflective towers: reflection can be finite when the interpreter bottoms out at an explicit native level.
- Rewriting logic and Maude reflection: rules and modules can be represented and transformed as data.
- rho calculus: names, processes, and rewrite structure can share one reflective basis.
- miniKanren: relations need not have fixed input/output direction; search control and termination remain real concerns.
- pi-calculus: topology and communication structure can change by passing names.
- object-capability systems and Spritely: authority follows explicit connectivity and capability possession.
- RDF reification and EAV/Datomic: relations and schema can be represented as data, but their term/value categories are still not sufficient as the universal floor.
- interaction nets and port graphs: local graph rewriting is powerful, but fixed symbols, ports, or arity cannot become hidden semantic authority.
- Morphic/Self, Dynamicland Realtalk, Hazel, and Pantograph: direct manipulation, live claims, always-valid structured editing, and fluid selection are requirements for the eventual user experience.

## Acceptance Court

A candidate kernel is accepted only if executable tests prove all of the following:

- every persisted semantic entity has one physical schema;
- there is no semantic `kind`, role, direction, port, operation, container, or content enum in the kernel;
- properties, parameters, functions, policies, presentations, and relations are selectable cells with the same anatomy;
- relation-cells can be rewired, inspected, governed, encrypted, presented, versioned, and related again;
- containment, ordering, direction, arity, and typing are graph protocols, not record privileges;
- the graph can describe its interpreter while transactions preserve identity, determinism where promised, recovery, and security;
- the old application can be migrated and compared without deleting legacy authority before replacement courts pass;
- the visual editor lets a nontechnical user inspect and change the graph through direct manipulation without exposing implementation machinery by default.

## Current Round

1. Build the architecture from primary literature and executable counterexamples, not model consensus.
2. Derive a minimum physical substrate that does not smuggle semantic roles into fields, positions, enums, or host dispatch names.
3. State the unavoidable native boundary honestly.
4. Turn each claimed property into a red forcing test before changing `core.py`.
5. Only after the kernel court passes, migrate higher concepts as graph-defined protocols made from the same cell.

## Round 2: Antigravity Gemini 3.5 Flash

**Transport:** Native Antigravity IDE agent panel
**Evidence:** Visibly analyzed all five required files and returned an 18,584-character submission in the room
**Edits:** None observed
**Court status:** Diagnosis retained; proposed kernel rejected

### Gemini diagnosis

Gemini independently confirmed four live violations:

1. `kind` is a disguised class tag.
2. `body.inner` versus `body.floor` is a privileged container algebra.
3. `params` and `relations` are privileged relationship representations.
4. the floor operation dispatch makes the language closed and not self-describing.

That diagnosis agrees with the repository audit.

### Gemini proposal

Gemini proposed:

```text
Cell = <ID, Payload, Links>

ID      = globally unique string
Payload = terminal scalar, bytes, or host capability string
Links   = ordered directed list of Cell IDs
```

Its evaluator treated the first link as a behavior selector and dispatched strings such as:

```text
native:math:+
native:control:if
native:relation
native:volatile:probe
protocol:subgraph
protocol:property
protocol:ai_session
ui:layout:split
```

It claimed order comes from list position, arity from list length, direction from traversal, roles from protocol cells, and external systems from `native:*` payload strings.

### Court attack

**REJECTED.** This is a compact but still classed interpreter.

- `Payload` and ordered `Links` are two privileged semantic categories.
- list position secretly encodes endpoint role and direction; users cannot select or relate the position as a cell.
- `native:*`, `protocol:*`, and `ui:*` are semantic enums disguised as strings.
- `_evaluate` branches on `protocol:subgraph`; `_dispatch_native` branches on operation names. Hidden dispatch remains the authority.
- containment is still a special `subgraph` protocol with a privileged sink position.
- a string such as `native:host:revit_api` is forgeable and is not an object capability.
- the proposed secret cell exposes a vault URI as ordinary payload and gives no proof of non-exfiltration.
- the proposed database and geometry examples name host implementations instead of composing their semantics.
- no transaction, revision, conflict, recovery, or concurrent rewrite model is defined.
- the interpreter is described in prose but not represented or modified by the same cell anatomy.

### Executable false positive in Gemini's forcing test

Gemini's gated relation test edits `gate_state` and `v8`, then expects the wire to retain `8`. Its store only invalidates the cell edited directly:

```python
def edit_payload(self, id, payload):
    ...
    self._memo.pop(id, None)
```

The dependent `wire1` memo is never invalidated. Therefore the test passes by returning a stale cached `8`; it does not prove that the closed gate was evaluated. The same defect means reopening the gate would still return stale data. This is a decisive counterexample against the proposal's claimed live behavior.

### Round 2 decision

Gemini is a real participant and its full response remains visible in the Antigravity panel. Its critique strengthens the case against the current kernel. Its replacement does not pass the founder test and cannot become the implementation basis.

## Round 3: OpenRouter Free Fleet

### Transport ledger

| Model | Attempts | Result |
|---|---:|---|
| Nemotron Super 120B | 2 | NVIDIA upstream HTTP 429; no inference |
| Qwen3 Next 80B | 1 | Venice upstream HTTP 429; no inference |
| Llama 3.3 70B | 7 | Venice upstream HTTP 429, including six paced retries over 74 seconds; no inference |
| Nemotron Nano 30B | 2 | First response lost to Windows console encoding; second response completed, 35,685 input + 6,660 output tokens, zero cost |

Only completed inference counts as a participant. Rate-limit pages are transport evidence, not research.

### Nemotron Nano 30B diagnosis

The model correctly attacked:

- the `KINDS` table as a semantic class catalogue;
- `body.inner` versus `body.floor` as privileged containment;
- `params`, `relations`, and nested ports as second-class containers;
- `native:*`, `protocol:*`, and content variants as renamed enums.

### Nemotron Nano 30B self-contradiction

Immediately after that diagnosis, it proposed the existing kernel record as the universal anatomy:

```text
{
  id,
  kind,
  title,
  params,
  body: floor | inner,
  relations,
  meta
}
```

It then rebuilt every rejected class directly:

- parameter = `kind='param'`;
- relation = `kind='wire'`;
- containment = `kind='group'` plus `body.inner`;
- transaction = `kind='session'`;
- AI action = `kind='proposal'`;
- UI = `kind='ui'`;
- authority = `kind='secret_ref'`;
- revision = `kind='history'`.

Its claimed irreducible floor also named the old `value`, `host`, `wire`, and `secret_ref` concepts as primitives rather than deriving the storage boundary.

### Nemotron Nano 30B test failure

The proposed "no hidden kind" test explicitly imports and enforces `KINDS`. It says the evaluator must not branch on `kind`, then asserts that any value not in `KINDS` must fail validation. That test ratifies the taxonomy it claims to forbid.

Other decisive faults:

- its host-removal test does not remove the host primitive before expecting failure;
- its self-description test invents a reference to an engine function but does not represent the function semantics as cells;
- it claims every finite graph of primitives terminates, which is false in the presence of cycles, recursion, host waits, or rewrite rules;
- it claims URI prefix validation makes a capability unforgeable, but any writer can forge the string;
- it claims serial execution and cache clearing provide concurrency and transactions without defining atomic commit, isolation, conflict detection, or recovery.

**Court status: REJECTED.** The first section is useful critique. The proposed architecture and tests are the existing rejected system restated as the solution.

### Poolside Laguna M.1

**Transport:** OpenRouter free route
**Evidence:** 37,129 input + 5,399 output tokens, including 4,203 reasoning tokens, zero cost
**Court status:** Rejected

Laguna proposed the smaller physical record:

```text
cell = {id, payload}
store = {id -> cell}
```

It named identity, terminal payload, ID references, atomic store modification, and host capability invocation as the native boundary. That is closer to the actual question than the previous class catalogues.

However, it then moved the complete semantic taxonomy into arbitrary payload structures:

```text
{ref: cell_id}
{endpoints: [...], stages: [...]}
{operation: add, inputs: [...]}
[child_id1, child_id2]
```

**Court attack:**

- `payload: any` is an ungoverned second language, not a universal anatomy.
- `endpoints`, `stages`, `operation`, `inputs`, and child-list positions are privileged semantics hidden in nested host records.
- direction and order still come from list position and interpreter convention.
- "protocol cells interpret it" does not define how those protocols execute without hidden dispatch.
- host-bound functions are named as an irreducible floor but capability unforgeability and authority transfer are not defined.
- self-description, transaction isolation, conflicts, rollback, termination, and invalidation remain assertions rather than mechanisms.
- three proposed tests contain only comments or `pass`; another assertion says `kind` may exist if it is "just data," which is not executable or falsifiable.

The two-field record is not sufficient when arbitrary payload dictionaries contain the old classes. Laguna's response narrows the physical envelope but does not solve the semantic or execution floor.

## Research Foundation Matrix

This matrix separates published results from architectural inference. No cited system delivers ArchHub's full requirement. Each solves one part and exposes a boundary that our kernel must make explicit.

| Research line | What the source establishes | Where it stops short | Consequence for ArchHub | Required forcing evidence |
|---|---|---|---|---|
| [Self: The Power of Simplicity](https://dl.acm.org/doi/10.1145/38807.38828) and [Programming as an Experience](https://bibliography.selflanguage.org/_static/programming-as-experience.pdf) | A useful environment can unify state and behavior around live prototype objects, slots, delegation, and direct manipulation without classes. | Slots and slot positions remain privileged object structure; the implementation does not make every relation, slot, or interpreter decision a recursively editable peer object. | Preserve prototype-style cloning, delegation, liveness, and visible causality, but represent property membership and delegation as graph entities rather than record fields. | Clone a cell-composition, edit its protocol locally, inspect inherited and local relations, and prove no hidden class/slot table controls behavior. |
| [Kernel](https://web.cs.wpi.edu/~jshutt/kernel.html) | Special forms can be reduced: first-class operatives expose evaluation behavior, and ordinary applicatives can be built from a smaller basis. | Kernel still has a native evaluator, environments, operative/applicative distinctions, and language primitives; it is not a universal visual graph store. | Do not bake `if`, `function`, `session`, or product operations into a dispatcher. Evaluation strategy must be explicit graph state above a much smaller native rewrite boundary. | Reconstruct conditional evaluation and ordinary function application from inspectable cells; editing the evaluator graph changes behavior under a governed transaction. |
| [Reflection and Strategies in Rewriting Logic](https://maude.cs.illinois.edu/papers/abstract/tcs4009.html) | Rewriting logic can represent theories and strategies at a meta-level and execute reflective transformations in a finitely presented universal theory. | Maude's terms, equations, rules, modules, and meta-operations are still a fixed formal substrate. Reflection does not erase the host metalanguage. | The graph may describe its own rules, but the implementation must publish the exact native matcher/rewrite/transaction boundary instead of claiming infinite self-reduction. | Serialize matcher and strategy descriptions as cells; round-trip them; alter a strategy visibly; prove atomic rewrite, rollback, deterministic replay where promised, and bounded failure. |
| [Interaction Combinators](https://doi.org/10.1006/inco.1997.2643) | Distributed universal computation can arise from only three agent symbols and six local interaction rules. | The three symbols, principal ports, arities, and interaction rules are fixed meta-schema. Small is not the same as universal-cell uniformity. | Local graph rewriting is a strong execution candidate, but symbols and ports cannot become privileged semantic node classes. Rule patterns must themselves be inspectable graph state above the native matcher. | Express the combinator rules and at least one nontrivial computation as ordinary stored cells; prove the native engine dispatches only generic match/rewrite, never a symbol name. |
| [Blind graph rewriting systems](https://arxiv.org/abs/1204.3372) | A memory made from nodes with exactly two references can support computation with a processor that does not inspect stored information; the paper demonstrates embedded logical operations without built-in conditionals. | It is a four-page theoretical construction, uses physically labelled `0/1` references, and does not supply persistence, transactions, capabilities, rich terminal data, or a usable editor. | A uniform binary-reference cell is a credible physical substrate. The `0/1` positions may be machine addressing only; they cannot silently become semantic input/output, key/value, parent/child, or source/target roles. | Encode logic without dispatching on payload labels; prove semantic direction and roles are represented by editable cells; benchmark the cost of structural encodings and use explicit capability-backed blobs for large terminal data. |
| [Hierarchical port-graph rewriting](https://researchportal.lsbu.ac.uk/ws/portalfiles/portal/8078963/3678232.3678238.pdf) and [strategic port graphs](https://arxiv.org/abs/1407.7929) | Port graphs support visual, local rewriting with explicit strategies and hierarchical structures. | Node names, ports, arity, and hierarchy can remain privileged schema outside the graph. | Use the visual rewriting discipline, not its fixed port taxonomy. A visible endpoint/port must be a selectable composition of universal cells, and hierarchy must be a relation protocol. | Rewire, annotate, govern, and relate an endpoint itself; express containment without a `Group` record or parent field; preserve graph validity through edits. |
| [Reflective higher-order rho calculus correction](https://arxiv.org/abs/2209.02356) | Structured names can be derived from quoted processes, supporting mobile and reflective process structure. The 2024 journal result also documents errors in an earlier encoding claim. | Quote/drop and communication constructs remain calculus primitives, and encodability claims require proof rather than analogy. | A cell may name graph structure content-addressably, but we must not equate naming with execution or claim another calculus has been encoded without tests. | Prove alpha-equivalent graph naming, collision handling, quote/run separation, scope/authority behavior, and the exact limits of any process-calculus encoding. |
| [Relational Programming in miniKanren](https://scholarworks.iu.edu/iuswrrest/api/core/bitstreams/27f1ebb8-5114-4fa5-b598-dcfaddfd6af5/content) | Unification and constraints support relations that can run in more than one direction. | Search order, fairness, occurs checks, disequality stores, divergence, and resource use remain implementation semantics. | Wires must not be assumed to have one hardcoded input/output direction. Direction can be a protocol/query choice, but execution requires explicit strategy and budgets. | Run one relation forward, backward, and with unknowns; expose search strategy as cells; prove cancellation, bounded resource use, and useful partial results on divergence. |
| [RDF 1.2 Concepts](https://www.w3.org/TR/rdf12-concepts/) | Subject-predicate-object graphs can make statements about statements through triple terms and reifiers; reifiers can carry provenance and other facts. | RDF still privileges triple positions and term categories; triple terms are not automatically asserted, executable, transactional behaviors. | Reification validates first-class relations and provenance, but a fixed S/P/O triple is not automatically the final cell anatomy. We must distinguish semantic direction from physical incidence. | Select a relation as an entity, attach policy/history/presentation to it, relate it again, and prove assertion state is distinct from merely referring to the relation. |
| [Datomic transaction model](https://docs.datomic.com/transactions/model.html) and [transaction data](https://docs.datomic.com/transactions/transaction-data-reference.html) | A generic immutable fact relation can retain history: entity, attribute, value, transaction, and assertion/retraction; transactions are themselves entities. | Attribute position, value types, cardinality, and serialized transaction authority remain privileged database machinery. Large payloads and effects are outside the datom model. | The persistent store should be append-oriented and provenance-preserving, but `attribute` cannot be an engine enum. Schema, transaction policy, and history views must be graph-defined while commit remains an explicit native boundary. | Time-travel and replay every semantic edit; inspect the transaction as cells; reject partial writes; recover after interruption; prove type/cardinality policies are editable graph protocols. |
| [Operad of Wiring Diagrams](https://arxiv.org/abs/1305.0297) and [Decorated Cospans](https://arxiv.org/abs/1502.00872) | Networks can compose while preserving external interfaces; a composed network can itself act as one component. Decorated cospans make connections first-class mathematical morphisms. | Particular operads choose interface types, directions, generators, and composition laws outside each instance. They justify composition, not a privileged `Group` node. | The application-as-super-node requirement is mathematically coherent. Encapsulation is a view/protocol over relations, and its boundary must be openable and rewritable rather than stored as a special container class. | Collapse and expand the same subgraph without changing semantics; expose selected boundary relations as editable interface cells; compose Brain, Cockpit, map, app, and site without copying state. |
| [Hazel live typed holes](https://arxiv.org/abs/1805.00155) and [Pantograph](https://arxiv.org/abs/2411.16571) | Incomplete programs can remain meaningful and live; structured editors can preserve validity while supporting fluid selection and rearrangement. | These systems work over typed syntax trees and fixed calculi, not unrestricted self-modifying graph protocols. | The visual editor must allow incomplete wiring without freezing or silently running unsafe effects. Invalidity must become an explicit, inspectable graph state with recovery paths. | Cut, move, partially wire, and paste graph regions while the workspace remains responsive; show typed/authority holes; prevent effects until gates resolve; preserve undo and identity. |
| [Consistent Self-Adjusting Computation](https://arxiv.org/abs/1106.0478) | Memoization plus change propagation can be given a semantics with consistency and correctness relative to a pure evaluation. | Correct invalidation requires a real dependency structure; clearing only the edited cell is insufficient. Effects and distributed concurrency add further obligations. | Every derived value must have explicit dependency evidence. The current Gemini proposal's stale-cache passing test is specifically forbidden. | Edit a transitive dependency, prove every dependent is invalidated or incrementally repaired, compare the result with clean recomputation, and test cycles and effect boundaries. |
| [Robust Composition](https://www.erights.org/talks/thesis/) | Object-capability discipline ties authority to explicit possession/connectivity and addresses composition under access and concurrency concerns. | A URI, label, or secret reference string is not an unforgeable capability; host isolation and revocation still require trusted machinery. | Security must follow actual graph reachability plus unforgeable native handles. Secret values never enter ordinary payloads; policies and audit are cells, while capability minting/use is a minimal trusted boundary. | Attempt forgery, confused-deputy escalation, exfiltration, replay, delegation, revocation, and serialization; prove denied paths fail without revealing the secret. |

## Workspace Research Audit

The earlier workspace digests remain evidence, but not every architectural conclusion remains authority.

- `30.KNOWLEDGE/strategy/journalclub-research-frontiers.md` correctly identifies composition, reflection, live structured editing, and incremental computation as the research spine. Its statement that one-table storage is sufficient is now too weak: one table can still contain hidden semantic classes.
- `30.KNOWLEDGE/strategy/node-language-objectified-relations-2026-07-12.md` correctly establishes that relations need identity, lifecycle, provenance, security, and presentation. Its fixed relation/parameter/group/UI roles and privileged endpoint representation are superseded by the founder's universal-cell test.
- The `node-relation-*` and `node-runtime-*` digests from 2026-07-14 remain useful for canvas interaction, atomic edits, serialization, and performance courts. They do not decide the physical kernel anatomy.
- Existing `SPEC.md` passages that prescribe `kind`, `body.floor`, `body.inner`, typed plugs, or named floor operations are contradictory with the opening one-atom claim and are under formal revision. No implementation may cite those passages to reintroduce a catalogue.

## Honest Synthesis So Far

Published research supports the direction, but it also proves why the answer cannot be a slogan:

1. **Uniform semantics does not remove a native machine.** Every reflective system bottoms out in a host representation and transition relation. ArchHub must minimize, name, secure, and test that boundary rather than pretend it does not exist.
2. **Small taxonomies are still taxonomies.** Three combinators, triples, EAV facts, ports, slots, or `{id,payload}` records can all hide privileged positions and dispatch.
3. **First-class relations require two levels to be distinguished.** Semantic direction, roles, gates, policies, and presentation must be cells. The storage engine still needs an irreducible physical incidence/addressing mechanism; that physical direction must not be mistaken for domain direction.
4. **Execution should converge on generic graph matching plus atomic rewriting.** Named product operations belong above that floor as stored compositions. Host geometry, images, cryptography, databases, AI, files, and network access enter only through unforgeable capability handles with explicit authority and effect transactions.
5. **The visual editor is part of the language semantics.** A nontechnical user must select any semantic entity, see why it exists and what it affects, edit it safely, and observe propagation. Hidden caches, invisible wires, opaque host callbacks, or dead property forms fail the language even if the storage schema looks uniform.

This synthesis is still a candidate, not acceptance. The next artifact is a falsifiable physical schema plus red tests that try to expose disguised semantic positions, hidden dispatch, stale dependencies, authority forgery, non-atomic rewrites, and opaque containment.

## Candidate Physical Kernel V0

This is the first candidate derived from the matrix. It is deliberately smaller than the product language. It defines the machine that can host the language; it does not declare product concepts.

### One physical cell shape

```text
Cell {
    id:    CellId
    link0: CellId
    link1: CellId
    atom:  Bytes
}
```

Every cell always has the same four fields. `link0` and `link1` point to cells; the distinguished null cell represents no link. `atom` is an opaque terminal byte sequence and may be empty. The kernel does not parse `atom` as JSON, an operation name, a class, a role, a type, a port declaration, or a product command.

The four irreducible facts are:

1. `id` supplies stable addressable identity.
2. `link0` and `link1` supply a finite physical incidence basis. Their labels are machine addresses, not domain direction or endpoint roles.
3. `atom` terminates recursion for text, numbers, hashes, compact scalar encodings, and handles. Large geometry, image, model, and document payloads remain content-addressed blobs outside the graph; graph cells hold their hash, metadata protocols, authority, and transformations.
4. Versioning, write-ahead logging, indexes, locks, memory pages, and capability tables are implementation machinery around this shape, not semantic product nodes. Their observable decisions and policies are projected back into cells; their bytes and OS handles are not falsely claimed to be recursively editable semantics.

This differs from Gemini's rejected `{ID, Payload, Links}` in a decisive way: the kernel is forbidden to assign semantic meaning to link position or atom content. Gemini dispatched `native:math:+` and treated list positions as roles. V0 can only read identity/incidence, perform generic structural matching, and commit an atomic rewrite. Any meaning above that must be represented by connected cells.

### Native boundary

The native kernel may perform only these classes of action:

```text
read(cell_id, snapshot) -> Cell
match(pattern_root, target_root, snapshot, budget) -> bindings
commit(expected_snapshot, create_cells, replace_cells) -> transaction_id | conflict
invoke(capability_handle, request_root, authority_root, budget) -> result_root
```

- `read` exposes the uniform cell.
- `match` performs generic graph-structure matching. Pattern, variables, constraints, and strategy are cells rooted at `pattern_root`; the matcher may recognize only the bootstrap pattern protocol, never product labels.
- `commit` atomically creates or replaces complete cells under optimistic revision checks and appends recovery history. There is no unaudited field mutation.
- `invoke` is the only effect boundary. A capability handle is unforgeable runtime state, not a URI or string in `atom`. Requests, authority grants, results, denials, and audit evidence are graph cells.

The bootstrap pattern protocol is an unavoidable metalanguage. It must be tiny, versioned, represented in the graph for inspection, and paired with a native conformance test. Claiming that it does not exist would be dishonest.

### How familiar concepts emerge without kinds

These are protocols and lenses, not cell classes:

| Familiar concept | Graph composition |
|---|---|
| Value | A root related to terminal atom cells or to a computed result root. |
| Property / parameter | A relation composition connecting an owner, a value root, constraint roots, provenance, and presentation. The property itself has a selectable root. |
| Wire / relation | A relation root plus incidence cells linking any number of participants. Role, order, direction, gate, transform, encryption, history, and cable appearance are further cells related to that root. |
| Port | A presentation/exposure relation selecting which relation protocols are visible at a composition boundary. It is not a socket field. |
| Group | A lens over a reachability/query result with a chosen boundary. No container cell type or `children` list exists. |
| Behavior | A rule/strategy graph consumed by generic `match` and `commit`, or an explicitly authorised capability invocation. |
| Function | A behavior root plus binding/environment relations. Input/output roles are protocol cells, not ordered record slots. |
| Session | A composition root related to agent/model capability, context, tools, work, policies, lifecycle, events, and presentation. It has no special runtime class. |
| UI | A presentation protocol that maps graph queries to visual cells and interactions back to transactions. Multiple lenses may render the same roots differently. |
| Database | The versioned cell store plus query/constraint/transaction protocol graphs. No `Database` kind is required. |
| Brain / Cockpit / Grand Map / app / website | Different governed views and interaction protocols over one authoritative graph. The founder lens exposes all of them from one composition root. |

### Why the application is a super-node without a Group primitive

"Application" is a root selected by a composition protocol. The protocol defines a reachable region, its public boundary relations, the lenses available to a user, and the capabilities it may invoke. Collapsing that region presents the root as one node. Opening it changes the lens to the reachable internals. No cells move into a special container, and no second copy of state is created.

The same mechanism applies at every scale: a number's representation, a material parameter, a wall assembly, a design workflow, an AI session, Brain governance, and the entire ArchHub installation differ by connected protocols and lenses, not by physical record class.

## Candidate V0 Rejection Court

V0 is rejected immediately if any implementation does one of these:

1. Branches on an atom string such as `value`, `group`, `session`, `wire`, `if`, `math`, `ui`, `secret`, `database`, or a product/domain operation.
2. Treats `link0` as source/key/function/parent and `link1` as target/value/argument/child in semantic code. Those meanings must be graph cells.
3. Stores parameters, endpoint lists, children, styles, policies, operation arguments, or ports as nested host dictionaries/lists in `atom`.
4. Lets a relation exist only as adjacency between two roots without its own selectable identity.
5. Resolves a capability from a forgeable string, serializes the live handle, or puts protected payload bytes in ordinary atoms.
6. Mutates a cell without an atomic transaction, durable history, conflict check, dependency invalidation, and recovery evidence.
7. Uses a hidden side table for semantic roles, graph edges, groups, UI bindings, or interpreter rules.
8. Requires a user to understand the binary substrate for ordinary work. The universal floor must remain recursively inspectable, while domain lenses provide immediate, game-like interaction.

## Red Forcing Test Plan

The first implementation step is a parallel V0 kernel and red tests. The current `nodelang/core.py` remains legacy authority until migration courts pass.

1. **One shape:** every semantic record is exactly `{id, link0, link1, atom}`; no `kind`, `params`, `body`, `relations`, `meta`, nested record, or inline edge exists.
2. **No hidden dispatch:** static and dynamic instrumentation prove evaluation does not branch on atom contents or product labels.
3. **Relation recursion:** a relation has identity; its endpoint incidence, role, gate, policy, presentation, and history are cells; a second relation can target any of them.
4. **Role intersection:** the same root simultaneously participates as data, behavior, relation, parameter, presentation, and boundary without conversion or class change.
5. **Containment removal:** collapsing/opening a composition is a lens change; there is no parent, child list, group kind, or move operation.
6. **Graph-defined behavior:** boolean choice and a small arithmetic example execute from stored rewrite rules; editing a rule cell changes execution after an authorised transaction.
7. **Incremental correctness:** any transitive change yields the same result as a clean recomputation; stale memo results fail the test.
8. **Atomicity/recovery:** injected crashes at every commit stage recover to exactly the old or new snapshot, never a mixture.
9. **Capability security:** forged, copied, expired, revoked, over-broad, and confused-deputy requests fail; audit cells reveal decisions without revealing secrets.
10. **Large data:** geometry/image descriptors remain fully inspectable cells while content-addressed blobs stream without expanding every byte into visible nodes.
11. **Self-description:** the bootstrap pattern protocol and interpreter configuration are visible cells; changing governed configuration has a tested effect, while changing the native ABI requires a signed migration.
12. **Usability:** a user can select any projected entity, inspect its connected properties in the right panel, rewire it, undo it, and see propagation without seeing `link0/link1` unless explicitly descending to the floor.

## Implementation Ledger — 2026-07-15

The candidate is now executable in parallel with the legacy runtime. This is a kernel court, not a completion claim.

### Proven now

- `nodelang/universal_cell.py` persists exactly one semantic record shape: `{id, link0, link1, atom}`.
- `atom` accepts bytes only; the kernel performs no decode, JSON parse, prefix dispatch, operation lookup, or product command interpretation.
- the distinguished null cell has the same shape as every other cell;
- commits validate the complete candidate graph before publishing one new snapshot;
- stale expected revisions conflict instead of overwriting concurrent work;
- stable cell identity survives replacement and prior snapshots remain readable;
- dangling physical incidence is rejected atomically;
- a budgeted generic matcher unifies graph structure using explicit variable cells;
- the matcher recognizes a relation composition and a policy relation targeting that relation without knowing either concept;
- a pattern and replacement stored as ordinary cells execute a generic structural rewrite;
- editing the replacement cells changes the next execution;
- `nodelang/capabilities.py` mints process-local object capabilities that cannot be recreated from atom bytes, used through another broker, or pickled;
- revocation is immediate and produces bounded audit evidence without serializing the live handle.

### Executable evidence

```text
tests_replica/test_universal_cell_kernel.py       12 passed
tests_replica/test_universal_cell_capabilities.py  4 passed
combined court                                    16 passed
```

### Not proven yet

- the bootstrap matcher protocol is not yet represented and inspectable as its own governed graph;
- commits are process-atomic but not yet durable through OS/process interruption;
- capability audit events are not yet projected into ordinary cells;
- dependency discovery, incremental invalidation, cycles, and clean-recompute equivalence are not yet implemented;
- arbitrary-arity relation composition, structural protocol inheritance, lenses, and recursive right-panel inspection are not yet implemented on V0;
- legacy nodes and application state have not been migrated;
- the existing application UI is still powered by the legacy `kind/body/params/relations` runtime;
- Brain, Cockpit, Grand Map, website, AI sessions, and application are not yet one V0 graph;
- no release, cloud deployment, installer, multi-user, or visual usability court has passed on V0.

### Progress update after the initial ledger

The next courts have now executed:

- SQLite WAL durability, exact byte round-trip, two-open-store conflicts, rollback-before-commit, and complete-after-commit recovery are green;
- transitive invalidation, unrelated-edit cache reuse, cycle handling, explicit budgets, and equality with clean recomputation are green;
- arbitrary-arity relation protocol, relation-of-relation, preserved incidence identity on rewire, multi-role participation, and batch composition are green;
- Properties selection and readable scope are explicit relation cells; rewiring selection or appending a scope relation changes the projected rows without a Python-side relation list;
- boundary-aware composition prevents a domain open from recursively exploding through cross-domain dependencies;
- a rule composition contains pattern, replacement, variables, and bindings as cells; rewiring bindings changes the next execution;
- the real Grand Map imports in one revision as 38,091 uniform cells: 282 map roots, 862 current parameter properties, 309 internal relations, 153 cross-domain relations, and 15 domain compositions;
- measured import is 0.059 seconds; opening the bounded UI domain projects 2,691 cells in 0.0014 seconds;
- consolidated universal-cell court: 45 passed in 0.82 seconds;
- the legacy snapshot-writer race found by the full regression suite was fixed with unique temporary files, replace retry, cancellation by revision invalidation, and a proved writer join before final save; focused persistence court: 5 passed with no thread warning.

The current boundary remains strict: the real application canvas and right Properties panel are not yet powered by this V0 graph. Migration into that existing UI is the active court. The legacy runtime remains read-only comparison authority until equivalent behavior and visual evidence pass.

## Standard Assembly Research - 2026-07-15

The founder corrected a second false reduction after the physical-cell court.
One uniform cell is a credible storage and rewrite floor, but a product catalogue
cannot be created by drawing named cell arrangements and asserting that their
labels make them work. `List`, `Watcher`, `Logic`, `Data Store`, and `AI
Session` are user-facing assemblies. Each must have executable semantics,
explicit failure behavior, lifecycle, and evidence before it enters the
catalogue.

### Rejected implementation

The first `nodelang/cell_catalog.py` draft is rejected as architecture. It
correctly avoided adding kernel kinds, but it proved only that named manifests
contained cells and that a generic copier could clone them. That is not enough:

- the List was one head cell with no ordering, insertion, deletion, identity,
  iteration, or collaboration semantics;
- the Watcher had no commit subscription, dependency discovery, scheduling,
  replay, backpressure, cancellation, or error path;
- Logic had labelled pattern/replacement cells but no accepted evaluation
  contract;
- Data Store had no query, index, transaction, isolation, durability, or
  recovery contract;
- AI Session had no model capability, context policy, approval, cancellation,
  budget, audit, or failure contract;
- its tests proved shape and cloning, not behavior.

Nothing may import that draft into the application library. It must be replaced
in place by the generic assembly authority below, then each standard assembly
must pass its own operational court.

### Primary-system comparison

No source below is copied as ArchHub's ontology. The comparison extracts
requirements that recur across mature visual and component systems.

| Source | Proven mechanism | Limit to avoid | Requirement forced on ArchHub |
|---|---|---|---|
| [Blender node groups](https://docs.blender.org/manual/en/4.5/interface/controls/nodes/groups.html) | Reusable, nested node compositions expose explicit group input/output sockets. | A fixed socket/type system can become a second ontology. | Boundary ports are selectable cell compositions, generated from actual cross-boundary relations; recursion is rejected. |
| [Dynamo custom nodes](https://primer2.dynamobim.org/6_custom_nodes_and_packages/6-1_custom-nodes/1-introduction) | One visible node can be opened to the graph that runs it; named inputs support type hints/defaults; base definitions can update instances and publish to a library. | A closed custom-node file format or compiled component may hide execution. | Definition, instance, interface, default, documentation, library membership, and definition-update policy are graph facts; opening shows the executing cells. |
| [Node-RED subflows](https://nodered.org/docs/user-guide/editor/workspace/subflows) | Reusable subflows expose per-instance properties, status, documentation, appearance, version/module metadata, and recursion checks. | Packaged subflow modules currently hide internals and remain experimental. | Per-instance overrides, status/error outputs, docs/presentation, version/dependencies, and recursion validation are mandatory; publishing must not make internals opaque. |
| [Houdini digital assets](https://www.sidefx.com/docs/houdini/assets/edit.html), [type properties](https://www.sidefx.com/docs/houdini/ref/windows/optype.html), and [versioning](https://www.sidefx.com/docs/houdini/assets/create.html) | An asset combines an internal network, parameter interface, metadata, embedded resources, definition/instance separation, editable overrides, and upgrade/version behavior. | Locked definitions can turn the asset into an opaque binary and uncontrolled definition updates can break instances. | Draft versus released definition, linked versus local instance, explicit overrides, immutable released revision, migration graph, provenance, and compatibility court are required. |
| [LabVIEW connector panes](https://www.ni.com/docs/en-US/csh?context=lvcore_lvhowto_selecting_a_connector_pane) and [execution properties](https://www.ni.com/docs/en-US/bundle/labview-api-ref/page/dialog-boxes/execution-page-vi-properties-dialog-box.html) | A reusable subVI has an explicit connector contract and explicit choices for serial, shared-clone, or per-call state/execution. | Implicit shared state or excessive terminals makes behavior unsafe and wiring unusable. | Every executable assembly declares state ownership, concurrency/reentrancy, priority/budget, and a bounded public interface. |
| [Self-adjusting computation](https://arxiv.org/abs/1106.0478) | Correct reactive update requires recorded data/control dependencies, memoization, and change propagation consistent with clean evaluation. | A polling label or local cache clear is not a watcher. | A Watcher must record dependencies, detect committed changes, invalidate transitively, converge to clean recomputation, handle cycles, and expose scheduling/error state. |
| [WASI capabilities](https://github.com/WebAssembly/WASI/blob/main/docs/Capabilities.md) | External authority is provided through explicit imports or unforgeable runtime handles. | A string naming a secret/tool is forgeable metadata, not authority. | Effectful assemblies declare required capabilities; instances receive attenuated unforgeable handles; absence, revocation, denial, and audit are executable paths. |
| [Semantic Versioning 2.0.0](https://semver.org/) | Version meaning requires a declared public API and immutable released contents. | Incrementing a number without interface compatibility evidence says nothing. | A released assembly fingerprints its definition and interface; incompatible boundary/semantic changes require a new major definition and migration evidence. |
| [IPFS Merkle DAGs](https://docs.ipfs.tech/concepts/merkle-dag/) | Content addressing provides immutable, self-verifying graph identities and structural sharing. | Immutable content IDs alone do not provide mutable live instances or transactions. | Released definitions and large payload descriptors are content-verifiable; mutable instances keep stable identities and append transaction history. |
| [Common Expression Language](https://cel.dev/) | A deliberately bounded, non-Turing-complete expression layer can provide predictable policy evaluation. | One expression node cannot replace visible general computation or effects. | Small predicates may use a safe bounded evaluator behind an explicit capability, while general behavior remains open graph rules and all effects remain gated. |

### Accepted generic assembly contract

An assembly is not a new record, kind, container, or Python class in the
semantic store. It is an ordinary relation-root whose members are ordinary
cells playing graph-defined roles. Python dataclasses may project that graph
for tooling, but no registry dictionary, class name, or product label may be
read as authority.

A valid reusable definition must expose all of the following as cells and
relations:

1. **Definition identity and provenance.** Stable definition root, author/source,
   parent definition where applicable, and catalogue membership.
2. **Declared region.** The exact internal cell roots owned by the definition.
   Any reference leaving that region must be null, a boundary interface, or an
   explicitly declared dependency/capability. Hidden cross-boundary references
   are invalid.
3. **Public interface.** Boundary port roots, their internal targets, contracts,
   defaults, cardinality, presentation, and documentation. Direction is a
   graph role/protocol, not a physical meaning of `link0` or `link1`.
4. **State ownership.** Which cells are shared, per-instance, per-call, or
   external; initialization and reset policy; concurrency/reentrancy policy.
5. **Executable behavior.** Rule roots, dependency roots, scheduling/budget
   policy, result/status/error roots, and effect boundaries. A label is never
   behavior.
6. **Authority.** Required capability roots, attenuation/delegation policy,
   approval gate, dry-run/apply/revert behavior, and audit destinations.
7. **Lifecycle.** Draft or released state, semantic version, immutable release
   digest, dependencies, compatibility statement, migration/upgrade graph,
   deprecation state, and rollback target.
8. **Presentation and direct manipulation.** Catalogue label/icon/category and
   node-card/Properties projections are cells. Opening an instance reveals the
   same internal cells that run; editing exposed parameters rewires or edits
   those cells without a hidden duplicate settings object.
9. **Evidence.** Operational court roots, fixtures, expected outcomes,
   performance/resource budgets, security tests, and supported failure cases.
   A definition without passing evidence remains draft and cannot enter the
   standard catalogue.

### Definition and instance policy

- A **draft definition** is editable and cannot be used as a standard released
  catalogue dependency.
- Releasing computes a digest over the declared region, interface, behavior,
  capability requirements, and evidence. Released content is immutable; an
  edit creates a new definition revision.
- An **instance** is a graph relation to its definition plus graph-held
  old-root/new-root mappings. Cloning is driven only by the declared region,
  never a Python catalogue entry.
- Per-instance state is cloned. Shared dependencies and definitions remain
  referenced. Overrides are explicit relation cells and can be removed to
  return to the definition value.
- Direct or indirect definition recursion is rejected until an explicit
  resource-bounded recursive execution protocol exists.
- Linked instances may adopt a compatible release only through a migration
  transaction. Local instances keep their pinned release until explicitly
  changed.

### Admission courts

The generic mechanism is accepted only when tests prove:

1. one instantiator accepts an arbitrary definition discovered through graph
   membership without dispatching on catalogue names;
2. every cloned part and definition-to-instance mapping is present as cells;
3. undeclared cross-boundary references, missing interface targets, duplicate
   single-valued roles, recursion, and incomplete manifests are rejected;
4. per-instance state is isolated while declared shared dependencies remain
   shared;
5. editing a released definition invalidates its digest and blocks new
   instances;
6. opening an instance returns its actual declared cells, not a decorative
   reconstruction;
7. deleting a rule, capability, or interface relation removes the associated
   behavior without a fallback path;
8. every standard catalogue entry passes a behavior-specific court plus
   restart, failure, performance, security, and visual interaction evidence.

The first behavioral admissions are **List** and **Watcher** because together
they force ordered mutable structure, identity, dependency tracking,
incremental execution, state, errors, and visual editability. `Logic`, `Data
Store`, `Presentation`, and `AI Session` remain outside the standard catalogue
until equivalent courts exist.

## Boundary and Security Ratchet - 2026-07-15

The word **adapter** is not permission to hide ArchHub in opaque host code.
The original ports-and-adapters pattern separates the application inside from
technology-specific translation outside. NIST zero-trust guidance separately
requires resource-level authentication and authorization without implicit
trust, while WASI demonstrates explicit capability imports instead of ambient
authority. OWASP's secrets guidance requires fine-grained least privilege,
rotation, revocation, and auditing. These sources force the following split:

- [Cockburn, Hexagonal Architecture](https://alistair.cockburn.us/hexagonal-architecture)
- [NIST SP 800-207, Zero Trust Architecture](https://csrc.nist.gov/pubs/sp/800/207/final)
- [NIST SP 800-207A, application and service identity policy](https://csrc.nist.gov/pubs/sp/800/207/a/final)
- [WASI capability model](https://github.com/WebAssembly/WASI/blob/main/docs/Capabilities.md)
- [OWASP Secrets Management](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)

### Non-negotiable boundary

**Inside the semantic system:** application data, logic, state, UI structure,
sessions, governance, Brain, Cockpit, Grand Map, workflows, policies, and
domain behavior are openable universal-cell assemblies. They cannot be host
adapters.

**At an actual external edge only:** a narrow capability adapter may translate
one declared graph contract to an operating-system, network, database-driver,
GPU, model-provider, keyring, or physical-device API. An adapter is a leaf; it
cannot own an ArchHub parent composition, product workflow, hidden semantic
state, or fallback business logic.

Alternative providers are expected. Several adapter assemblies may implement
the same capability port and may be selected, compared, failed over, or routed
by visible graph policy. Provider replacement must not alter the universal
cell floor or the internal assembly using that port.

### External-adapter admission

An external adapter remains draft unless its graph declares and its court
proves all of the following:

1. exact external resource and protocol;
2. exact input, output, and error contract;
3. minimum request and authority scopes;
4. no ambient filesystem, network, process, environment, or secret access;
5. expiry, invocation/rate budget, timeout, cancellation, and revocation;
6. secret references only, with plaintext excluded from graph, logs, argv,
   errors, and persisted audit;
7. encryption/authentication requirements for data in transit and at rest;
8. bounded input/output size and structured parsing;
9. append-only invocation evidence containing identity, decision, timing, and
   outcome but no secret material;
10. deterministic fake provider plus denial, timeout, malformed-result,
    revocation, restart, and replacement-provider courts;
11. an anti-escape inspection proving it contains translation only and no
    product/domain workflow;
12. removal of the adapter leaves the internal graph valid but the capability
    visibly unavailable.

### Implemented security floor

`nodelang/capabilities.py` now requires every live host grant to carry a
trusted `CapabilityPolicy` with a policy identity, exact request-root set,
exact authority-root set, expiry, and invocation budget. Live handles are
process-local, unforgeable from cell bytes, non-serializable, broker-specific,
and immediately revocable. Invocation is deny-by-default with explicit denial
reasons; audit memory is bounded and never stores the live handle.

Current evidence:

```text
tests_replica/test_universal_cell_capabilities.py  6 passed
```

Not yet proven: graph-projected durable security audit, encrypted secret-vault
integration, user/service identity authentication, approval policy evaluation,
per-provider sandboxing, adapter admission tooling, and any admitted external
provider. No external adapter may be called secure or production-ready before
those courts pass.

## Closed Authoring, Adapter Consent, and Universal Lifecycle - 2026-07-15

### Why the physical cell cannot be the agent authoring API

The four-field universal cell is the execution and storage floor. It is not a
safe vocabulary for an agent composer. Giving an agent unrestricted floor
mutation would let it emit unbounded, unverified graph fragments that happen to
look like workflows. The authoring boundary is therefore a released catalogue
of higher assemblies plus a closed command grammar. This is analogous to:

- [MLIR Operation Definition Specification](https://mlir.llvm.org/docs/DefiningDialects/Operations/): a generic IR is constrained by declarative operation definitions, operands, results, traits, and verifiers from one source of truth.
- [MLIR IRDL](https://mlir.llvm.org/docs/Dialects/IRDL/): dialect definitions are themselves programs with inspectable constraints, runtime declaration, and verifier-derived valid-program generation.
- [WebAssembly Component Model](https://component-model.bytecodealliance.org/design/components.html): components compose only through declared imports and exports whose interfaces make the composition checkable.
- [CUE specification](https://cuelang.org/docs/reference/spec/): open data can be constrained and closed so undeclared fields are rejected.
- [The Update Framework](https://theupdateframework.io/papers/survivable-key-compromise-ccs2010.pdf): admitted targets are bound to version, hash, expiry, role, and delegation evidence instead of trusting an ambient package name.

ArchHub rule: normal agents may instantiate released definitions, connect
declared interfaces, configure admitted parameters, arrange the canvas, and
select graph roots. They may not create raw cells, invent commands, silently
extend the catalogue, or execute a proposed definition. Catalogue extension is
proposal-only until independent courts and founder authority release it.

Implemented evidence:

- `nodelang/cell_catalog.py`: released catalogue manifest with version and digest; membership or definition drift blocks composition.
- `nodelang/cell_composer.py`: graph-held actor, catalogue, adapter catalogue, allowed commands, closed roles, budgets, lifecycle, evidence, and digest.
- `tests_replica/test_cell_catalog.py` and `tests_replica/test_cell_composer.py`: unknown command, raw floor command, proposal execution, outside definition, quota overflow, policy drift, and catalogue drift are rejected.
- `nodelang/application_server.py`: legacy raw mutation routes are disabled by default; regression-only callers must opt in explicitly.
- `tests_replica/test_application_server_governance.py`: HTTP-level proof that raw mutation is forbidden while released-catalogue instantiation remains operational.

### Adapter admission and exact user permission

An adapter is only the final physical boundary to an OS, network, database,
GPU, device, payment rail, or host application. It cannot contain hidden
product logic. Adapters are deny-by-default and must be listed in a released,
fingerprinted adapter catalogue. An invocation is authorized only when one
exact user grant covers its adapter, action, location/resource, data class,
user, expiry, and invocation budget.

This follows [RFC 9396 Rich Authorization Requests](https://www.rfc-editor.org/rfc/rfc9396.html), which requires unknown authorization types/fields/values to be refused and supports fine-grained actions, locations, and data types; [RFC 8707 Resource Indicators](https://www.rfc-editor.org/info/rfc8707/), which binds authority to a specific resource/audience; and [OWASP Authorization guidance](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html), which requires default deny and permission validation on every request.

Implemented evidence:

- `nodelang/cell_adapters.py`: released adapter definitions/catalogue, exact permission-request nodes, process-local one-use user-consent handles, grant, revoke, drift/expiry/budget checks, and per-invocation revalidation.
- The application starts with a valid released **empty adapter catalogue**. Therefore every external effect is denied until an adapter passes admission and the user grants one exact request.
- `tests_replica/test_cell_adapters.py`: empty allowlist, over-broad scope, forged consent, handle serialization, exact action/location/datatype, budget, expiry, drift, and revocation courts.

### Immutable release descriptors separate release from live operation

A lifecycle release cannot hash every graph it can eventually resolve. Live
registries, sessions, reaction histories, and evidence ledgers legitimately
append after publication. A direct transitive reference would therefore make
ordinary operation invalidate an already-published revision.

ArchHub now uses a generic content-descriptor relation for this boundary. The
descriptor is composed only from terminal subject identity, media type,
algorithm, digest, and byte-length Cells. The frozen tenant configuration links
to catalogue and policy descriptors; use-time validation resolves the named
roots, reruns their existing release verifiers, and matches their canonical
release statements. This follows the content-addressed boundary used by OCI
descriptors, TUF targets/snapshots, and in-toto subjects without adding a
parallel authority store.

Implemented evidence:

- `nodelang/cell_content_descriptors.py`: generic closed descriptor protocol,
  stable length-framed subject statements, and fail-closed verification.
- `nodelang/cell_tenant_authority.py`: descriptor-backed tenant configurations,
  exact catalogue/policy resolution, and legacy direct-reference support only
  for append-only migration.
- `tests_replica/test_cell_content_descriptors.py`: missing, duplicate,
  non-terminal, malformed, wrong-subject, wrong-media, wrong-size, and digest
  courts.
- `tests_replica/test_cell_tenant_authority.py`: a selected release keeps the
  exact same lifecycle bytes after a Watcher is registered, while descriptor or
  catalogue drift fails closed.
- `tests_replica/test_universal_authority_migration.py`: an old selected direct
  reference is preserved, superseded by a court-published descriptor revision,
  and reopens idempotently.

### WIP, Shared, Published, and Archive are revisions, not mutable copies

[UK BIM Framework Guidance Part C](https://ukbimframework.org/wp-content/uploads/2020/09/Guidance-Part-C_Facilitating-the-common-data-environment-workflow-and-technical-solutions_Edition-1.pdf) and its [concept guidance](https://ukbimframework.org/wp-content/uploads/2019/10/Information-Management-according-to-BS-EN-ISO-19650_-Guidance-Part-1_Concepts_2ndEdition.pdf) distinguish the CDE workflow from its technical solution and require information containers to move through WIP, Shared, Published, and Archive with approval/authorization, revision/status/classification metadata, controlled access, user/date transition records, and audit history. Shared information is for coordination and is not edited in place; required changes return to WIP and are resubmitted.

Three live bidirectionally synchronized copies would violate those goals. The
accepted universal model is:

1. WIP appends immutable working revisions.
2. WIP to Shared creates an evidence-backed Shared revision referring to the exact promoted content revision.
3. Shared to Published creates an authorization-backed Published revision.
4. Later WIP never changes an existing Shared or Published revision.
5. Restore creates a new WIP revision referring to historical content; it never rewrites history.
6. Archive is the retained revision/transition history, backed by journal snapshots and verified offsite backup rather than another editable copy.

This matches [Datomic's transaction model](https://docs.datomic.com/transactions/model.html): immutable facts accrue only through complete atomic transactions, transactions are themselves reified, and every database value has a predecessor and full history.

Implemented evidence:

- `nodelang/cell_lifecycle.py`: domain-neutral state bindings, transition rules, immutable revision nodes, actors, timestamps, evidence, history, promotion, and append-only restore.
- `nodelang/cell_standard_library.py`: released `Versioned Asset` assembly in the same catalogue as Ordered List and Watcher.
- `tests_replica/test_cell_lifecycle.py`: WIP append, immutable Shared/Published promotion, continued WIP isolation, evidence/source-state rejection, and append-only restore.

The remaining product work is to make lifecycle controls visible in Properties,
wrap every user-level asset/assembly in this protocol, then specialize via
catalogue compositions for database transactions, content-addressed geometry,
monetary authorization/settlement/reconciliation, and ISO 19650 BIM workflows.

### Current integrated evidence

- Definitions, parts, interfaces, lifecycle, evidence, obligations, digests,
  catalogue membership, instances, and definition-to-instance mappings are
  graph relations; the instantiator has no catalogue-name dispatch.
- Ordered List declares its ordered-member role at its public interface and is
  edited generically while preserving incidence identity.
- Watcher declares its reaction capability and records cursor, status, error,
  and coalesced event history as cells.
- Versioned Asset declares graph-held state bindings and transitions and keeps
  WIP/Shared/Published/Archive history without domain dispatch.
- The live application shell is rendered from UI cells in the same store. The
  previous hand-written 3.6 MB/11.7 s host was replaced; measured response and
  first meaningful interaction are approximately 40-190 ms on the local court.
- The normal HTTP server disables old mutation routes, exposes the released
  composer authority, and starts with zero admitted external adapters.

Focused executable evidence at this point:

```text
catalogue + composer + adapter + lifecycle + universal application  green
HTTP raw-bypass court                                               green
browser List/Watcher drop, edit, wire, select, wheel zoom            green
browser console errors/warnings                                      0
```

## Prior-Art Correction and Frontier Boundary - 2026-07-16

The individual ideas in ArchHub are not unprecedented. The defensible frontier
claim is the governed product synthesis, and that claim remains subject to
continued prior-art search and executable comparison.

### Falsification audit correction - 2026-07-17

The earlier search was not deep enough. It missed several direct precedents,
especially HyperGraphOS and Active Graph. That omission made the frontier
statement sound broader than the evidence allowed. The entries below were
checked against current primary documentation and, for HyperGraphOS, Active
Graph, and Hydra, against shallow source checkouts rather than project taglines.

The correction does not establish that ArchHub is a copy of one existing
system. It establishes a stricter burden: ArchHub must reuse or outperform the
strongest precedent on each dimension and may claim a frontier only for the
complete conjunction that remains unproven after executable comparison.

### Closest architectural prior art found

The multi-selection Properties baseline is not invented locally. Current
[AutoCAD 2026 guidance](https://help.autodesk.com/view/ACD/2026/ENU/?guid=ACD_FOUNDATIONS_MAIN8)
shows only properties common to every selected object, displays `VARIES` for
different current values, and applies a changed common value to the selection
in one operation. Current
[Revit 2026 guidance](https://help.autodesk.com/cloudhelp/2026/ENU/Revit-GetStarted/files/GUID-A764EA7A-FE26-469B-857C-F3A70812FC34.htm)
likewise limits mixed-category selections to common instance properties. The
ArchHub requirement is stricter: the selection, common-property control,
participants, transaction, and undo evidence must remain explicit graph roots.

| System | Material overlap | Boundary that remains for ArchHub |
|---|---|---|
| [HyperGraphOS](https://github.com/HRI-EU/hypergraphos) and its [MODELSWARD paper](https://doi.org/10.5220/0013164900003896) | This is the closest visual-product precedent found. Honda Research Institute Europe built an open-source browser meta-operating system for scientific and engineering work: infinite interconnected graph workspaces, user-defined DSLs, visual models that are also data structures, data containers, documents, computation, code generation, AI/LLM and robotic workflows, palettes, ports, nested workspaces, and Git-backed revision/revert support. | Source audit at commit `e502901` found a GoJS `GraphLinksModel` with separate `nodeDataArray` and `linkDataArray`, category-dispatched DSL templates, privileged `in_`, `out_`, and `props_` arrays, 125 category strings, 48 `doCompute` dispatch names, and 25 `eval`/`new Function` sites. Links, properties, ports, behavior, application chrome, authority, and history are not recursively the same universal entity; execution and security are not a default-deny proposal/capability path. HyperGraphOS therefore strongly precedes ArchHub's visual graph OS, engineering-workspace, DSL catalogue, and AI-integration ideas, but not the one-Cell floor or the complete governance claim. Its interaction and workspace ideas must be studied for reuse instead of rebuilt from memory. |
| [Active Graph](https://github.com/yoheinakajima/activegraph) | An event-sourced graph runtime for stateful agents makes objects and typed relations durable projections of an append-only log. Relations have identities, data, and relation-level deterministic or LLM-backed behavior. It provides scoped views, bounded frames, patches, optimistic concurrency, approvals, replay, forks, structural diff, promotion, budgets, tools, and explicit failure events. This is direct precedent for relation behavior, durable agent work, proposal history, branching, and replay. | Its own documentation says control flow, behavior code, configuration, budgets, and the event log are outside the graph. Relations are binary typed edges whose behavior is selected by a Python decorator on the relation type. Direct graph mutation deliberately bypasses policy, and there is no primary direct-manipulation product UI. It is a strong candidate source for event/fork/failure courts, not the ArchHub semantic floor or complete authorization model. Source audit used release commit `148e12c` (`v1.10.0`). |
| [Hydra / LambdaGraph](https://github.com/CategoricalData/hydra) | A production-used strongly typed intermediate language makes data, schemas, and code graph terms. Its LambdaGraph model establishes an isomorphism between labeled hypergraphs and typed lambda calculus; programs are graphs and graphs are programs. The kernel can describe and regenerate itself across multiple host languages with a common test suite. This is direct precedent for a graph-native executable and self-describing language floor. | Hydra remains a typed functional language with a substantial fixed term/type system, registered host primitives, generated runtimes, coders, and build machinery. It does not supply the normal-window visual language, recursive user-controlled presentation, agent possession, CDE lifecycle, capability governance, or identity continuity across the shipped product. It should inform type/evaluation and cross-host equivalence courts rather than be misrepresented as an end-user application. |
| [WebGME](https://github.com/webgme/webgme) | A mature browser generic modeling environment lets users define DSML concepts, relationships, attributes, aspects, constraints, and visualizations in the browser. Every collaborative change becomes a broadcast micro-commit; branching gives tools consistent snapshots while users continue editing. It already combines a generic visual editor, metamodeling, collaboration, versioning, plugins, constraints, workers, and code generation. | WebGME is a metamodel-driven platform with privileged node/metatype/attribute/relationship structures and external plugins, executors, add-ons, and visualizers. The editor and execution/control planes are not the same recursively editable universal graph, and it does not provide ArchHub's proposal-only cognition, relationship-aware authorization, CDE semantics, or application-as-one-root requirement. Its collaboration, snapshot, and metamodel UX are mandatory comparison points. |
| [Jjodel](https://www.jjodel.io/) and its [research paper](https://doi.org/10.1007/s10270-025-01324-y) | A reflective, cloud-based modeling workbench focuses explicitly on reducing modeling complexity. It provides real-time collaboration, live metamodel/model/viewpoint co-evolution, visual syntax customization, modular validation and semantics, model transformations, a project megamodel, and progressive disclosure with Basic and Advanced modes. | Jjodel separates data, layout, and view sub-models and uses JSX/React and dedicated transformation/expression languages. It is not evidence that every property, relation, rule, UI control, agent, authority decision, and history fact has one universal Cell identity. It is, however, stronger current prior art for the layered-visibility and nontechnical interaction problem than the existing ArchHub prototype. |
| [Eclipse Sirius Web](https://github.com/eclipse-sirius/sirius-web) | An actively released open-source platform builds collaborative web studios for custom visual languages from reusable backend and React components. It includes diagrams and other representations, model editing, validation, and a deployable multi-user stack. | Sirius Web is a framework for model-specific studios backed by EMF/service/application subsystems, not a self-hosting universal graph computer. It remains relevant as an implementation and interaction benchmark for polished language workbenches. |
| [Structr](https://github.com/structr/structr) | A mature self-hosted low-code platform stores schemas, UI definitions, templates, scripts, workflows, files, and user data in graph technology and provides visual schema/page/flow editors, APIs, security, and AI guardrails. | Structr is direct precedent for an integrated graph-backed application platform, but its Neo4j model, Java/GraalVM runtime, DOM/page machinery, scripts, plugins, and flow nodes remain distinct implementation authorities rather than one recursively universal Cell identity. |
| [Semio](https://github.com/usalu/semio) | Direct AEC precedent combining design-information modeling, browser sketchpad, collaboration studio, CDE, assistant, graph rewriting, geometry, parametric design, and Rhino/Grasshopper integrations. | Source audit at `277881d` found explicit Kit, Design, Type, Piece, Connection, Connector, Layer, Group and related schemas plus separate SQLite, JSON Schema, GraphQL, engine, store, and UI bundles. It is a mandatory AEC product/interaction benchmark, not evidence for the one-Cell floor. |
| [ArchiCode](https://github.com/roymasad/ArchiCode) | A visual graph-first coding harness keeps architecture, plans, source evidence, tests, runs, policies, proposals, reviews, and agent work connected to a durable editable graph. | Its technical specification at `57ad7b8` separates Electron processes, React Flow nodes/edges, Zustand state, Zod schemas, JSON/JSONL stores, agent memory, policies, host code, and files. It is close precedent for graph-scoped agent possession and visual software work, but the graph is not the complete application/runtime/security substrate. |
| [ObjectStack](https://github.com/objectstack-ai/framework) and [MemberJunction](https://github.com/MemberJunction/MJ) | Metadata-driven application platforms already derive data models, APIs, forms/views, permissions, workflows, audit, and agent tools from shared definitions. | Their source authorities are large typed schema/object systems with separate kernels, databases, UI frameworks, drivers, plugins, provider abstractions, and generated artifacts. They are mandatory productivity and composer benchmarks, not recursively universal graph floors. |
| [IFC Flow](https://github.com/louistrue/ifc-flow) | A browser visual node workflow already covers IFC import, geometry, filters, transformations, properties, parameters, watches, classifications, spatial queries, analysis, live execution, editing, and export. | It uses product-specific React Flow node types and JSON/Pyodide/IfcOpenShell processing. It is the minimum visible BIM workflow comparison, not a universal language, lifecycle authority, or self-hosting application. |
| [OpenCog AtomSpace](https://wiki.opencog.org/w/AtomSpace) | One hypergraph stores knowledge and procedures; queries can be stored in the graph; some graphs are executable; the project explicitly describes all OpenCog state as living in one AtomSpace. Nodes and links are both Atoms, links can contain links, and Values flow through graph structure. | AtomSpace retains a large native Atom type hierarchy and many executable types backed by C++ classes. It is a cognitive substrate, not a visually polished AEC product with one identity across UI, BIM/CDE lifecycle, governance, evidence, authority, collaboration, and release. ArchHub must learn from its one-space discipline without reproducing a catalogue of hidden product operations. |
| [OpenCog Hyperon and MeTTa](https://hyperon.opencog.org/) and the [current implementation](https://github.com/trueagi-io/hyperon-experimental) | Programs are subgraphs of an Atomspace metagraph and compute by querying and rewriting that metagraph. The design explicitly targets runtime self-modification, distributed storage, diverse cognitive processes, and external AI integration. | The implementation describes itself as active pre-alpha. It does not provide ArchHub's normal-window visual application, AEC workflows, ISO 19650-style lifecycle, founder/user authority model, direct-manipulation design system, or release courts. It is serious language and cognitive prior art, not a drop-in product runtime. |
| [OSTIS metasystem](https://ostis-ai.github.io/ostis-metasystem/quick_start/) | OSTIS combines a universal semantic-network memory, knowledge-processing agents, and SCg graphical representation. Published descriptions state that interface objects map to semantic-network elements and that systems are built from semantically compatible components. | OSTIS uses its own SC node/connector taxonomy and knowledge-processing machine. The available UI and system focus do not establish ArchHub's one-cell physical floor, incidence-preserving visual editing, capability security, CDE lifecycle, or coherent consumer-grade AEC application. It is especially important prior art for visual semantic agents. |
| [Zerolang](https://github.com/vercel-labs/zerolang) | The current repository describes the semantic graph as the program database. Agents query and submit checked graph edits against stable IDs, types, effects, ownership, capabilities, hashes, and call edges; readable `.0` text is a projection. | This is direct prior art for graph-native programs and checked agent editing, not merely a derived-code graph. Its published product is an experimental programming language and CLI, with an explicit security warning. It does not demonstrate ArchHub's normal-window direct-manipulation graph, one root identity across the shipped UI and runtime, BIM/CDE lifecycle, multi-user visual authorization, or real-product release courts. |
| [Agint](https://arxiv.org/abs/2511.19635) and [Agint CLI](https://github.com/AgintAI/agint-cli) | A typed, effect-aware graph compiler, interpreter, runtime, and visual Flow product treats the graph as the source of truth, lets humans and agents refine it, and compiles/exports executable software. | This is direct prior art for visual graph-native software authoring and agent/human co-editing. The public CLI is a thin client for a remote beta service, and the published demo describes sandboxed software-flow generation rather than one local identity-preserving graph that is simultaneously its own product UI, authority, memory, lifecycle, multi-user data, and BIM environment. Its interaction and compiler evidence must be compared, not dismissed. |
| [Graphiti](https://github.com/getzep/graphiti), [Beads](https://github.com/gastownhall/beads), and similar agent-memory graphs | Persistent temporal knowledge and dependency graphs can improve long-running agent context and coordination. | These are memory/task layers attached to agents or source repositories. They do not make the application, UI, authority, lifecycle, effects, and agents one recursively inspectable graph. |
| [LiteGraph.js](https://github.com/jagenjo/litegraph.js) | A mature browser node engine already provides zoom, pan, multi-selection, ports, links, subgraphs, widgets, custom presentation, client/server execution, and JSON graph interchange. | Its nodes are JavaScript classes registered by type and their links are editor/runtime structures. It is valuable interaction and performance prior art, but it does not establish one universal persisted semantic record, graph-held authority, temporal provenance, CDE lifecycle, or identity continuity between product UI, governance, and execution. |
| [AGNT](https://github.com/agnt-gg/agnt) | A local-first desktop agent product combines persistent agents, memory, visual versioned workflows, checkpoints, real-time execution, multiple model providers, MCP, and user-created widgets. | It is a close product-level comparison for orchestration and ease of use. Its published architecture still presents agents, workflows, providers, memory, widgets, and plugins as subsystems; it does not demonstrate that these and the application itself are recursively editable regions of one identity-preserving universal graph with ArchHub's CDE and authorization laws. |
| [MemOS](https://github.com/MemTensor/MemOS) | An inspectable graph-shaped memory operating system supports persistent multimodal memory, editing, multiple users/agents, scheduling, and a dashboard. | It is strong reusable prior art for memory, retrieval, isolation, and agent continuity. Memory remains a service used by applications and agents rather than the same authoritative structure as the visual application, UI definitions, effects, governance, and BIM/CDE lifecycle. |
| [OpenFang](https://github.com/RightNow-AI/openfang) | A Rust agent operating system provides durable autonomous agents, scheduling, skills, tool execution, knowledge-graph work, and an operational dashboard. | It is an agent runtime, not a universal visual graph language whose application, data, policies, sessions, UI, and domain work share one recursively editable identity. Its runtime ideas should be compared for supervision and recovery, not copied as a second orchestration control plane. |
| [CoWork OS](https://github.com/CoWork-OS/CoWork-OS) | A local-first agentic desktop product combines tools, plugins, governed durable memory, temporal knowledge-graph relationships, historical queries, checkpoints, sessions, identity files, and user-facing operational surfaces. | Its published architecture still distinguishes the SQLite knowledge graph, memory/context files, task runtime, plugins, tools, and application surfaces. It is close product and interaction prior art, but does not show those subsystems or the UI itself as one recursively editable identity-preserving semantic graph. |
| [AgentOS on iii](https://github.com/iii-experimental/agentos) | An agent operating system collapses capabilities onto three protocol primitives: Worker, Function, and Trigger. It includes governance, memory, orchestration, execution, and a live function catalogue. | Its own architecture uses dozens of separate Rust workers connected through a function bus and explicitly states that there is no shared in-process state. That is a strong modular agent-runtime design, not one persistent universal graph in which product state, relations, presentation, authority, and agents retain the same root identities. |
| [AIOS](https://github.com/agiresearch/AIOS) | A researched agent operating system supplies scheduling, context, memory, storage, tool, model, SDK, Web UI, terminal, and sandboxed computer-use facilities. | It is intentionally a modular kernel plus SDK with syscall dispatch across managers. It is prior art for agent resource management and isolation, not evidence that the application and all managed resources are visually rewritable regions of one semantic floor. |
| [Microsoft Agent Governance Toolkit](https://github.com/microsoft/agent-governance-toolkit) | Deterministic middleware governs agent actions with policy, identity, sandboxing, audit, trust, MCP/A2A bridges, and broad framework adapters. | It is high-value security prior art and a candidate source of test cases. Its own documentation calls the mechanism application-level middleware and reserves containers for true isolation. It does not make the governed product, UI, policies, history, and agent body one editable graph. |
| [OpenSwarm](https://github.com/openswarm-ai/openswarm) | A local spatial canvas lets users launch and supervise multiple agent sessions, approvals, conversations, branches, and embedded views. | It is close interaction prior art for visually possessing agent sessions. Its canvas cards coordinate external agent/runtime objects; the repository does not claim that every card, permission, session, wire, application surface, and durable fact is one recursively interpretable semantic language. |
| [GraphWorld](https://openreview.net/forum?id=xUDGChZsfG) | A multi-agent graph-editing environment provides language-neutral node/edge/property mutation, compact storage, graph-aware Git diff/merge, branches, and collaborative human/agent version control. | It is direct prior art for graph collaboration, versioning, and agent editing. It is an environment for maintaining knowledge graphs, not evidence that the editing application, authorization, presentation, executable behavior, and domain product are themselves the same graph. |
| [Omnigraph](https://github.com/ModernRelay/omnigraph) | A graph-native operational and coordination layer provides multimodal data, agent branches, review/merge, time travel, blobs, server-side Cedar policy, audit, and scalable object storage. | It is strong reusable prior art for cloud graph persistence, multi-agent isolation, policy, and merge. Its cluster, schemas, stored queries, policies, server, and product clients remain declared subsystems around graphs; it does not claim the visual application and every control as recursively editable graph identity. |
| [OriginTrail DKG](https://github.com/OriginTrail/dkg) | A shared multi-agent knowledge graph provides private Working Memory, shared Working Memory, verifiable published memory, assertion lifecycle, signatures, provenance, context-graph access policies, P2P synchronization, dashboard, adapters, and MCP wiring. | It is especially close prior art for WIP-to-shared-to-published information flow, verifiable collective memory, and agent interoperability. It is still a memory/knowledge infrastructure with adapters and a dashboard, not one universal product language in which the dashboard, agents, effects, BIM objects, and governance are the same recursively editable cells. |

### Correct novelty statement

ArchHub must not claim that "everything is a node," executable graphs, visual
semantic networks, self-modifying graph programs, or graph-based agent memory
were invented here. The current research question is narrower and harder:

> Can one identity-preserving Universal Cell graph become a smooth, visually
> direct AEC product in which application, design system, BIM/CDE data,
> lifecycle, relations, rules, authority, evidence, collaboration, and agent
> cognition remain inspectable and safely rewritable at every useful scale?

No reviewed repository has yet been shown to satisfy that entire statement.
HyperGraphOS comes much closer to the visual graph-OS half than the previous
report acknowledged; Active Graph comes much closer to the durable
relation/agent-runtime half; Structr, ObjectStack, and MemberJunction come much
closer to graph/metadata-driven application production; ArchiCode comes much
closer to graph-scoped agent work; and Semio plus IFC Flow come much closer to
the visual AEC/BIM half. That is an evidence status, not a permanent uniqueness
claim. A discovered equivalent must be evaluated and reused where it is
stronger.

### Frontier test, not uniqueness theatre

The current work operates at a **systems-integration frontier**, not at a claim
that every mechanism is new. A repository falsifies or narrows that frontier
only if executable evidence shows all of these together:

1. one persisted semantic floor for data, relations, executable behavior,
   presentation, authority, history, agent sessions, and product state;
2. the shipped application is a lens over that same floor, not a handcrafted
   shell around a graph database or workflow engine;
3. users can enter compositions, inspect real interfaces/incidences, rewire,
   author parameters and presentation, and recover history visually;
4. agent cognition is replaceable and proposal-only while durable attention,
   context, identity, authority, and outcomes remain in the graph;
5. authorization, confidentiality, adapter admission, lifecycle, concurrent
   revisioning, evidence, and release courts fail closed;
6. BIM/AEC information and CDE lifecycle are ordinary compositions of the same
   language rather than a separate vertical database or plugin;
7. browser, durability, security, performance, multi-user, deployment, and
   recovery evidence runs against the real product artifact.

Hydra, OpenCog/Hyperon, OSTIS, Zerolang, and Agint are closest to items 1-2 at
the semantic-machine, language, and graph-compiler levels. HyperGraphOS is the
closest reviewed visual graph-OS and scientific/engineering workspace precedent.
Structr, ObjectStack, and MemberJunction are strongest around integrated
graph/metadata-driven application production. WebGME, Jjodel, Sirius Web,
LiteGraph, AGNT, CoWork OS, Agint Flow, ArchiCode, and OpenSwarm are strongest
around item 3 and the usable visual-workbench/product problem. Active Graph,
GraphWorld, Omnigraph, OriginTrail DKG, Graphiti, MemOS, Beads, AIOS, AgentOS,
OpenFang, and the Microsoft governance toolkit cover substantial parts of 4, 5,
and 7. Semio and IFC Flow are the closest reviewed open AEC/BIM composition and
node-workflow precedents for item 6. No reviewed source currently proves the
complete conjunction. This is not proof that no such repository exists, and it
is not a patentability or first-invention claim. It is the current falsifiable
evidence boundary. Each stronger subsystem is a reuse candidate behind an
equivalence, security, identity, and authority court.

## Agent Possession and Replaceable Cognition - 2026-07-16

An agent does not become the authority by receiving a prompt or a database
handle. The graph is the durable body; a model is one replaceable cognition
capability wired into that body.

The first conforming body requires explicit relation assemblies for:

```text
AgentIdentity(body, actor, owner, tenant, audience, provenance)
ModelBinding(body, provider, model, adapter_definition, permission, routing_policy)
AuthorityBinding(body, policy, composer_authority, delegation*, adapter_permission*)
AgentSession(body, view_session, source_snapshot, branch, model_binding,
             focus, obligation*, context_manifest, state_machine, budget, history)
ContextEntry(manifest, candidate, eligibility, attention, purpose,
             audience, sensitivity, sequence)
Assignment(obligation, body, eligibility, decision, authority, evidence, state)
Proposal(session, body, snapshot, context_manifest, target, action,
         proposed_patch, model_evidence, decision)
EffectAttempt(decision, request, authorization_evidence, permission,
              capability_policy, operational_state, outcome)
```

Possessing a relation that mentions a permission or adapter does not confer
authority. Effects require current relationship verification, authorization
against the same immutable snapshot, exact adapter permission, a
non-serializable native capability, bounded execution, and durable receipts.
Model output is proposal evidence and never receives direct Cell mutation APIs.

### Inkling admission decision

[Thinking Machines Lab Inkling](https://thinkingmachines.ai/news/introducing-inkling/)
is relevant as a possible multimodal model binding: the official release and
[model card](https://huggingface.co/thinkingmachines/Inkling) describe native
text, image, and audio input, agentic tool use, open weights, and adaptation.
It is not ArchHub's soul and is not admitted as a core dependency:

- it was released on 2026-07-15 and lacks ArchHub, BIM, IFC, geometry, CDE, and
  confidential-data courts;
- the full model is roughly one trillion parameters and normal production
  serving is datacenter-scale;
- Apache-2.0 weights are accompanied by a separate
  [Model Acceptable Use Policy](https://thinkingmachines.ai/model-acceptable-use-policy/)
  that requires a pinned legal review;
- managed providers are denied T2 and T3 data unless a later privacy and legal
  court explicitly changes that decision;
- every tool call remains an untrusted proposal behind the same allowlists,
  authorization, capability, evidence, and reconciliation gates as any model.

Inkling may enter only as an experimental provider-neutral adapter evaluated on
synthetic or T0 data. The body must remain valid when Inkling is absent, denied,
replaced, offline, or wrong.

## Executable Presentation Graph - 2026-07-16

The ten standard Properties presenters are now persisted catalogue assemblies,
not named host dispatch:

```text
field-list       focus-list       interface-list
relation-list    control-list     presentation-list
timeline         authority-list   evidence-list       cell-floor
```

Each assembly is composed from the same bounded view-template protocol. The
host interpreter recognizes only generic graph mechanics: root/item/parent
context, paths, equality and Boolean composition, ordered children, bounded
repeat/map/find/count/join, deterministic JSON, arithmetic, slicing, conditions,
attributes, and transparent fragments. Product names do not select behavior.
The legacy named dispatcher is empty, and the application fails closed if an
admitted projector is not structurally a graph template. Retired Python
projectors remain temporarily as parity oracles only; the runtime does not call
them.

Evidence from the all-presenter court:

- 112 focused language, security, presenter, and integration courts passed;
- 73 durability, application, governed-server, and interaction courts passed;
- a legacy-store copy migrated from revision 613 to 617, reopened again at 617,
  retained every presenter incidence identity, structurally recognized all ten
  projector roots, reached 110,693 Cells, and passed SQLite integrity;
- the live store migrated from revision 620 to 623, reopened again at 623,
  retained every presenter incidence identity, and passed SQLite integrity;
- warm full-canvas projection improved from about 256 ms mean to roughly
  170-185 ms after per-snapshot structural expression/template planning.

This is not the complete visual language or complete product. It proves one
important recursive property: the right Properties panel itself is now driven
by inspectable and rewritable graph assemblies. Direct visual editing of those
assemblies, richer catalogue presentation, and broader performance work remain.

## Catalogue Discovery and Placement - 2026-07-22

The catalogue interaction is grounded in established visual-programming
practice, but ArchHub cannot copy the common hidden catalogue implementation.

- The official [Dynamo Library documentation](https://primer2.dynamobim.org/3_user_interface/2-library)
  organizes reusable nodes by library/category/subcategory, exposes plain-language
  descriptions and input/output contracts, supports keyword and hierarchy search,
  and permits click or Enter placement.
- Autodesk's official [Node Autocomplete documentation](https://help.autodesk.com/cloudhelp/2025/ENU/RevitDynamo/files/RevitDynamo_Node_Autocomplete_html.html)
  narrows candidates from an exact input/output port, supports search within the
  viable subset, and can place and wire the selected result.
- Autodesk's current [Dynamo for Revit 3.6 notes](https://help.autodesk.com/cloudhelp/2026/ENU/RevitDynamo/files/RevitDynamo_Whats_New_in_Dynamo_for_Revit_html.html)
  retain port-compatible suggestions while adding keyboard cycling, search,
  documentation access, and ghosted connection previews.

The accepted ArchHub decision is narrower and stricter:

1. A catalogue entry is not a host-language object. One relation attaches the
   exact released definition to its category, searchable roots, documentation,
   icon, order, and favourite state.
2. Search is an authorised disposable lens over those graph facts. It may filter
   locally for responsiveness, but it cannot create a second source of catalogue
   meaning or let hidden definitions influence results.
3. Click, drag, and Enter placement converge on one graph-projected interaction
   lease and one governed instantiation transaction.
4. Port-compatible suggestions remain a later interaction over exact interface
   contracts. They must not be guessed from labels or implemented as a browser
   product-name switch.

This resolves catalogue discovery and placement requirements only. It does not
prove the complete editor, large-graph browser performance, visual quality, or
release readiness; those require their own revision-bound courts.

## Agent Body Security Rejection - 2026-07-16

The first Agent Body substrate correctly demonstrated durable body/session
registries, atomic context-cursor publication, context provenance, and
proposal-only intent. It is **not admitted into the application** because its
first authority boundary was inadequate:

- body policy/rule roots could be asserted without proving released authority;
- context admission accepted a caller-constructible `AuthorizationDecision`;
- proposal registration accepted arbitrary roots without authorization or a
  verified proposal protocol;
- body identity, authenticated subject, view session, and scope were not proven
  to be the same governed owner;
- model-binding replacement was unauthorised and retroactive.

The corrected boundary must evaluate exact authorization requests inside each
mutator against the captured immutable snapshot, use broker-minted
non-serializable authentication contexts, pin model bindings per session,
validate canonical session-owned registries, and expose no proposal/model
mutation API until those compositions have their own released protocols. A
green unit test over caller-fabricated decisions is not acceptable evidence.

## Agent Body Security Repair - 2026-07-16

The rejected substrate was rebuilt as an application-bound, still-unbound
Agent Body and submitted to an independent adversarial review. That review
found three P1 defects and rejected live migration: receipt terminals could be
rewritten to claim an older valid authority snapshot, restore did not prove
continued membership in Models & Agents, and authentication expiry was checked
before rather than at the Cell commit's publication boundary. It also found
that per-relation limits did not form a safe aggregate traversal budget.

The current repair passed a fresh independent adversarial audit and now:

- requires resolver revision and evaluation time to equal the authorization
  evaluation exactly;
- binds every application Agent Body receipt to the immutable Cell journal by
  proving its first-created revision and comparing the current receipt with the
  receipt at publication;
- verifies exact, signed founder tenant and principal relationship evidence at
  that historical revision;
- rejects restore unless control, body, and session each remain members of the
  Models & Agents domain exactly once;
- executes an opaque authentication-context guard inside the Cell commit after
  candidate validation and immediately before publication;
- limits a session to 128 context entries, caps body rules, receipt principals,
  resolver evidence, and relation sizes, and applies one 100,000-member work
  budget across the complete session projection;
- keeps model binding, focus, assignment, proposals, capability invocation, and
  effects unavailable. The visible body is explicitly `unbound`.

The raw substrate remains trusted in-process Floor code. Python code that can
import it can also call `CellStore` directly and is therefore outside the
untrusted browser/route threat boundary. No Agent Body mutation HTTP route is
published. This distinction must remain explicit; `__all__` is not a sandbox.

Current focused evidence is 57 passing authorization, identity, Agent Body,
durability, Cell history, reaction, visual-reachability, and performance courts,
including adversarial tests for receipt rollback, exact domain membership,
post-hoc binding injection, delayed-expiry commit, aggregate read budget, CAS
conflict, and self-observing Watcher rejection. The independent reviewer also
proved backup and historical reopen against a live nonempty WAL, denied
same-path/overwrite backup, and confirmed SQLite integrity. A backup-derived
candidate is admitted only through `CellStore.backup_to(...)`; replacing or
stopping the existing live server remains denied until candidate migration,
reopen, HTTP, visual, and interaction courts pass.

### Backup-derived candidate evidence

The live store at revision 627 and 110,801 Cells was copied through the SQLite
online-backup API into an isolated candidate. The current application restored
that candidate, installed the complete Agent Body region, and then passed these
checks:

- body and session runtime containers are `active`; model binding, focus, and
  assignment are `unbound`, and the proposal registry is empty;
- Founder Agent Control, Founder Agent Body, and Founder Agent Session are all
  visible after entering Models & Agents;
- selecting Founder Agent Body drives the normal graph-defined Properties lens
  and exposes `title` and `color`;
- SQLite `integrity_check` is `ok`;
- a clean close/reopen restored revision 646 as revision 646 with 111,838 Cells,
  proving that restore is idempotent after the deliberate scope and selection
  interaction writes;
- an isolated hidden server is listening on `127.0.0.1:8507`; the favicon route
  returns 204, a bare root request fails closed with 403 after the one-use
  desktop bootstrap is consumed, the authenticated application loaded with the
  title `ArchHub`, and the server error log is empty.

The in-app browser supplied the expected application DOM but its enterprise
network policy blocked screenshot capture from this localhost port. No alternate
browser or policy bypass was used. Therefore the candidate is running and its
graph/HTTP state is proven, but a fresh screenshot and direct pointer-interaction
court remain open. The existing `8501` server and database were not stopped,
replaced, or mutated by this candidate launch.

## Universal Cell Retention and Watcher Boundary - 2026-07-16

The original in-memory revision implementation retained one complete Cell
dictionary for every revision. A measured 110,463-Cell application with 338
revisions added about 653 MB of RSS. The floor now retains the current mapping,
one delta tuple per revision, and at most two lazily reconstructed historical
snapshots. Exact `at(revision)`, revision-chain digest, durable SQLite replay,
and immutable journal semantics remain. The same build now adds about 34 MB,
holds about 78 MB total RSS in the measured process, builds in about 2.9 seconds,
and projects the top canvas in about 81 ms.

Connecting the Agent Body also exposed a Watcher correctness defect: a raw
transitive source fingerprint could reach the Watcher's own mutable event and
state nodes, creating a self-triggering cycle. Reactions now apply a generic
observation boundary that treats their own mutable runtime roots as opaque.
Nested source changes remain observable; directly wiring a Watcher to its own
event log is rejected, disabled, and recorded as an error instead of consuming
the fixed-point budget.
