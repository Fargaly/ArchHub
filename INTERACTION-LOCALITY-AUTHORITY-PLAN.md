# Interaction Locality Authority Plan

Status: WIP pre-implementation evidence

Date: 2026-07-23

Scope: Universal graph editor only

Release effect: none. This document does not release a mechanism.

## 1. Macro: what, why, how, who, when, where

### What

ArchHub has one canonical Universal Cell graph. The browser does not own a
second graph. It receives an authorised, revision-bound lens over the current
session scope.

Browser interactions belong to one of three execution classes:

1. Local presentation: ephemeral visual feedback that changes no semantic Cell.
2. Scope-local graph mutation: a committed change to the current view session,
   focus, viewport, or scope trail.
3. Shared or cross-scope authority mutation: a semantic change that can affect
   another scope, actor, released resource, relation, lifecycle, or physical
   effect.

### Why

The current browser path treats local pointer activity as if every action
requires a fresh projection of the operating graph. The result is not merely
slow code. It contradicts the product model:

- `SPEC.md` section 4.4 says opening a composition changes scope and does not
  create a second graph.
- `SPEC.md` section 4.5 says filtering is local projection state and must not
  mutate the graph.
- `SPEC.md` section 7 requires same-frame selection feedback and graph-held
  view-session selection after commit.
- `SPEC.md` section 11 requires local acknowledgement at or below 100 ms and
  bounded scope entry at or below 150 ms.

### How

Keep one `CellStore`. Keep every semantic state change as a Cell revision.
Operate local presentation directly in the browser. Validate scope-local
commits against the exact accepted session-scope projection and revision.
Return a bounded delta for that same scope. Fall back to the exhaustive graph
path only when revision, scope, authority, or cross-scope conditions require
it.

### Who

- Browser adapter: same-frame presentation, pointer correlation, and rendering
  of an admitted revision-bound delta.
- Application server: session binding, revision check, interaction lease,
  authorisation, bounded projection, and fail-closed fallback.
- Universal Cell graph: sole semantic authority for focus, selection, viewport,
  scope trail, content, relations, lifecycle, rules, and evidence.
- Courts: release authority for functional, security, revision, and latency
  claims.

### When

Local presentation happens immediately. Scope-local state is committed when a
gesture becomes semantically complete and differs from the accepted state.
Shared mutation occurs only after its existing graph-issued interaction,
authorisation, revision, integrity, and conflict checks pass.

### Where

- Browser pipeline: `nodelang/ui_runtime.py`
- HTTP and session projection boundary: `nodelang/application_server.py`
- Cell-native projection and mutation: `nodelang/universal_application.py`
- Physical authority: `nodelang/universal_cell.py`
- Real-browser evidence:
  `nodelang/browser_scope_locality_court.cjs`

## 2. Meso: complete browser interaction classification

The classification is about effect and authority, not about visible control
names. A familiar feature name does not create a new primitive.

| Interaction family | Immediate phase | Committed phase | Class | Required boundary |
|---|---|---|---|---|
| Hover, cursor, socket highlight, wire candidate highlight | DOM/CSS only | None | Local presentation | No request |
| Catalogue keyword/category filter | Local authorised list only | None | Local presentation | No graph mutation and no second catalogue |
| Click selection feedback | DOM selection immediately | Focus/selection only if changed | Scope-local graph mutation | Exact session, scope, revision |
| Ctrl/Shift selection and marquee feedback | DOM selection immediately | Focus/selection only if changed | Scope-local graph mutation | Exact visible roots and revision |
| Relation/interface/focus selection | DOM focus immediately | View-session focus only if changed | Scope-local graph mutation | Exact projected identity |
| Wheel zoom and space pan | DOM transform per frame | View-session viewport after debounce and only if changed | Scope-local graph mutation | Exact session and revision |
| Enter/back/breadcrumb for an already-authorised composition | DOM pending state only | Scope trail/focus change | Scope-local graph mutation | Exact projected control, reachable composition, revision |
| Properties tab or inspector lens | DOM pending state only | View-session lens state | Scope-local graph mutation | Exact graph-issued control and revision |
| Node drag | DOM transform per frame | Position value roots | Shared semantic mutation | WIP ownership, scope, authorisation, conflict |
| Label/value/property edit | Local editor state | Participating value roots | Shared semantic mutation | WIP/lifecycle/authority and atomic history |
| Add property or interface | Local form state | New relation composition | Shared semantic mutation | Released form, owner, contract, lifecycle, authority |
| Group/ungroup | Local pending state | Composition boundary and interfaces | Shared semantic mutation | Identity/connectivity preservation and authority |
| Catalogue placement | Local preview | Exact definition instance | Shared semantic mutation | Released definition revision and WIP scope |
| Connect/rewire/disconnect | Local cable preview | Relation/incidence roots | Shared or cross-scope mutation | Interface contract, duplicate, scope, authority, integrity |
| Undo/redo | Local pending state | Compensation/history graph | Shared semantic mutation | Exact history head and conflict checks |
| Lifecycle share/publish/archive | Local pending state | Lifecycle and immutable revision views | Cross-scope authority mutation | Approval, policy, evidence, no silent broadcast |
| Theme share/publish | Local personal preview | Audience/lifecycle selection | Cross-scope authority mutation | Personal WIP first, explicit audience approval |
| Adapter/effect execution | Local pending state | Proposal, grant, receipt, reconciliation | Physical shared effect | Allowlist, permission, expiry, effect receipt |
| Governance/authority issue or revoke | Local pending state | Authority relationship graph | Cross-scope authority mutation | Founder/admin authority, evidence, audit |

### Classification consequences

Local presentation cannot:

- write a Cell;
- enqueue a governed mutation;
- request `/api/universal/canvas`;
- broaden visibility;
- become authority for a later request.

Scope-local graph mutation can:

- commit view-session Cells;
- use the exact accepted session-scope projection as bounded evidence;
- return an existing revision-bound interaction or topology delta.

It cannot:

- create a second session store;
- treat a browser object as semantic truth;
- admit a root absent from the exact projection;
- bypass revision, session, scope, or authorisation checks.

Shared and cross-scope mutation retains the exhaustive checks required by the
affected relation, resource, lifecycle, audience, and authority. A local fast
path is not a general bypass.

## 3. Micro: measured current scope-entry pipeline

### Test artifact

Command:

```text
py -3.14 -m pytest tests_replica\test_browser_scope_locality_court.py -q -s --timeout=180
```

Environment:

- isolated loopback `ApplicationServer`;
- headless installed Chrome;
- real rendered ArchHub artifact;
- no live process, browser, or founder session attached;
- source revision: current WIP worktree on 2026-07-23.

### Result

The functional scope change passed. Four locality checks failed.

| Evidence | Measured result |
|---|---:|
| End-to-end double-click to visible new scope | 1019.8 ms |
| Governed pointerup gesture POSTs before scope POST | 2 |
| No-op gesture commits | 2 |
| Full `GET /api/universal/canvas` requests | 3 |
| Total tracked requests | 6 |
| DOM reconciliation batches | 5 |
| DOM mutation records | 719 |

Exact request order:

1. `POST /api/universal/gesture`, receipt revision 822 -> 822, 92.6 ms.
2. `GET /api/universal/canvas`, 186.9 ms.
3. `POST /api/universal/gesture`, receipt revision 822 -> 822, 47.3 ms.
4. `GET /api/universal/canvas`, 140.9 ms.
5. `POST /api/universal/interaction` for `gm:domain:ui`,
   receipt revision 822 -> 823, 133.7 ms.
6. `GET /api/universal/canvas`, 365.3 ms.

The two pointerup writes are proven no-ops because each committed revision
equals its submitted projection revision. They still force two complete canvas
requests before the scope interaction can reconcile.

DOM mutation batches contain 18, 18, 1, 1, and 681 records. The final 681-record
batch is the scope replacement. The earlier batches are selection/reconciliation
activity produced before the authorised scope is visible.

### Causal trace in current source

1. Universal canvas `pointerdown` starts a `drag` gesture and applies local
   selection in `ui_runtime.py`.
2. Every unmoved card `pointerup` calls `commit(...)`.
3. `commit` calls `universalMutation('/api/universal/gesture', ...)`.
4. `universalMutation` serialises through `mutationTail`.
5. Receipt mode waits for the POST receipt and then synchronously requests
   `/api/universal/canvas`.
6. Only after that full projection is accepted does the queue release the next
   pointerup mutation.
7. `dblclick` calls `navigateScope`, but its interaction waits behind both
   pointerup operations.
8. Scope receipt mode performs a third full canvas request.
9. The browser reconciles the replacement DOM and finally exposes the new
   scope.

This is a measured queue design failure. It is not a network availability
problem and not a reason to weaken security.

## 4. Standards and literature

### Pointer and double-click ordering

W3C Pointer Events states that compatibility mouse events may be delayed or
grouped after pointerup, while their relative order remains consistent. Click
remains required. Therefore the implementation must not assume a fixed
pointerup/click/dblclick timing across devices:

https://www.w3.org/TR/pointerevents/#compatibility-mapping-with-mouse-events

W3C UI Events Algorithms sends click after mouseup and dblclick after the click
that completes a double click. The court must prove the actual ArchHub sequence,
not infer it from one browser:

https://www.w3.org/TR/uievents/event-algo.html

### Revision and concurrency

RFC 9110 `If-Match` defines the relevant rule: a state-changing request must not
be applied when the selected representation no longer matches. ArchHub uses an
exact graph revision and interaction lease rather than an HTTP entity tag, but
the lost-update principle is the same:

https://www.rfc-editor.org/rfc/rfc9110.html#name-if-match

Kung and Robinson's optimistic concurrency control separates read, validation,
and write phases. A local projection is useful only if validation proves it is
still the accepted revision before commit:

https://www.cs.cmu.edu/~15712/papers/kung81.pdf

### Incremental projection

Gupta, Mumick, and Subrahmanian show that a derived view can be maintained from
changes rather than recomputed from all base data. ArchHub's stricter rule is
that the view is disposable and revision-bound; deleting it cannot change graph
meaning:

https://doi.org/10.1145/170036.170066

This supports a bounded delta. It does not justify a second semantic store.

## 5. Smallest authority-preserving design

### Existing authority retained

- One `CellStore`.
- One application root.
- Existing browser session binding.
- Existing interaction projection broker and one-use lease.
- Existing revision and conflict checks.
- Existing authorisation and integrity courts.
- Existing `interaction-delta-v1` and `topology-delta-v1` response contracts.
- Existing generic exhaustive graph projection as fail-closed recovery.

### Disposable session-scope projection

The server may retain only the already existing browser projection for:

- one browser session root;
- one accepted Store revision;
- one active scope root;
- roots, interfaces, relations, controls, and view state visible in that scope.

It is an accelerator, not authority. It is derived from canonical Cells and
discarded on revision or session mismatch. No persistence, side database,
shadow graph, semantic cache, or alternate control plane is allowed.

### Local presentation

Hover, filtering, pointer preview, and same-frame selection feedback remain in
the browser and make no request.

An unmoved pointerup on a card must not submit a mutation when the projected
selection/focus already equals the requested result.

Single-click persistence and double-click scope entry must be coordinated by
the graph-projected interaction policy, not a hidden timing literal. The
browser may hold an ephemeral pending click, but it has no authority and is
discarded on scope change, revision change, pointer cancellation, or a second
activation.

### Scope-local commit

For selection, viewport, lens, and scope trail:

1. Resolve the exact browser session and accepted projection.
2. Require the submitted revision and interaction lease to equal the Store
   revision and cached projection revision.
3. Require all referenced roots and controls to exist in that exact scope
   projection.
4. Apply only the bounded view-session Cell replacements.
5. Commit one atomic Store revision if and only if semantic values changed.
6. Produce an existing revision-bound delta for the affected session scope.
7. Reconcile only changed DOM identities.

### Invalidation and conflict

Discard the disposable projection when:

- Store revision differs;
- browser session or subject differs;
- active scope root differs;
- interaction lease is absent, expired, consumed, or belongs to another
  projection;
- projected identity is missing or duplicated;
- authorisation or audience changes;
- a shared change invalidates a visible interface, relation, or control.

On invalidation:

- do not apply the local request;
- return the existing stale/expired projection failure;
- obtain one authoritative bounded projection if possible;
- use the exhaustive graph projection only when bounded reconciliation cannot
  prove completeness;
- never silently merge a stale local action.

### Cross-scope fallback

Node movement, content edits, grouping, instantiation, relations, lifecycle,
authority, and effects keep their existing semantic checks. A cross-scope
relation or shared resource must inspect every affected scope/audience required
by its protocol. The local projection may avoid re-reading facts it already
proves, but it cannot replace a required cross-scope authorisation or integrity
check.

## 6. Security review before implementation

| Threat | Required control |
|---|---|
| Stale projection modifies newer graph | Exact Store/projection/lease revision equality; fail closed |
| Browser forges a visible root | Root and control must be present in the server-held exact projection |
| Projection from another session is replayed | Bind projection and lease to browser session root and subject |
| Local scope broadens visibility | Scope destination must be a projected, authorised composition control |
| No-op request consumes queue or lease | Compare requested semantic state before mutation; no request for browser-proven no-op, server no-op remains idempotent |
| Remote commit arrives during local action | Revision validation rejects; bounded reconciliation or exhaustive recovery |
| Delta omits a required removal | Delta includes ordered identity sets/removals, or recovery is mandatory |
| Accelerator becomes hidden authority | Disposable only; deletion and generic-path equivalence courts |
| Cross-scope write uses local shortcut | Classification and route courts require full relation/lifecycle/authority checks |
| Timing code hides policy | Use graph-projected interaction policy; no untracked literal |
| Pointer event ordering differs by device | Court actual pointer/click/dblclick sequences; do not assume compatibility-event timing |

## 7. Red-to-green court plan

These are release blockers, not optional unit tests.

### Real-browser locality

Existing red court:

`tests_replica/test_browser_scope_locality_court.py`

It must prove:

- local scope entry makes zero full `/api/universal/canvas` requests;
- no no-op pointerup mutation is submitted;
- no pointerup mutation blocks the scope interaction;
- the scope response carries the exact committed revision and authorised scope;
- scope entry remains functional.

The unchanged editor court must also pass:

`tests_replica/test_browser_graph_editor_court.py`

Required budgets:

- mutation acknowledgement at or below 100 ms;
- scope entry at or below 150 ms;
- all existing functional checks green.

### Focused authority and conflict courts

Before release, add:

1. Exact leased selection accepts only roots in the current scope projection.
2. Exact leased selection performs no `_session_canvas_roots` host scan.
3. Exact leased no-op selection creates no revision.
4. Scope delta refuses a stale Store revision.
5. Scope delta refuses a projection from another session or subject.
6. Scope delta refuses a target absent from the leased projection.
7. A remote/new revision forces bounded reconciliation or exhaustive recovery.
8. Cross-scope topology retains authorisation, duplicate, contract, and
   integrity checks.
9. Deleting all disposable projections changes no semantic result.
10. Catalogue filtering triggers no request and changes no Cell revision.

### Performance and regression

Run:

- focused session/scope/gesture courts;
- topology and relation security courts;
- `tests_replica/test_universal_ui_performance.py`;
- unchanged real-browser graph editor court;
- locality court;
- existing authority and Universal Cell kernel courts.

No threshold will be weakened to obtain green.

## 8. Pre-implementation court baseline

Measured on 2026-07-23 against the current WIP source. No mechanism change was
made while establishing this baseline.

| Requirement | Executable court | Current result |
|---|---|---|
| 1. Selection admits only current-scope roots | `test_scope_interaction_refuses_a_target_absent_from_the_leased_scope` | GREEN |
| 2. Exact selection performs no host scan | `test_exact_leased_selection_does_not_rescan_the_current_canvas` | RED: current gesture path calls `_session_canvas_roots` |
| 3. Exact no-op selection creates no revision | `test_exact_leased_noop_selection_creates_no_revision` | GREEN |
| 4. Stale Store revision is refused | `test_scope_interaction_refuses_a_stale_store_revision_without_mutation` | GREEN |
| 5. Projection is bound to exact browser subject | `test_cached_projection_is_bound_to_the_exact_browser_subject` | RED: cache key checks session root and revision but not subject |
| 6. Absent leased target is refused | `test_scope_interaction_refuses_a_target_absent_from_the_leased_scope` | GREEN |
| 7. New revision cannot replay stale UI state | `test_projection_reconciliation_cannot_replay_a_stale_property_change` plus stale Store court | GREEN |
| 8. Cross-scope topology retains security | duplicate, contract, composition-boundary, signed-scope, and live-revocation courts listed below | GREEN |
| 9. Disposable projection deletion changes no semantics | `test_discarding_disposable_projection_changes_no_graph_semantics` | GREEN |
| 10. Catalogue filtering makes no request | `test_node_library_search_filters_graph_metadata_and_places_by_keyboard` | GREEN |

The separate bounded-response contract is also RED:

`test_scope_interaction_delta_does_not_call_the_full_canvas_projector`

The current scope interaction commits correctly, then calls
`project_interaction_canvas`, which rebuilds the complete visible projection.

Exact commands and evidence:

```text
py -3.14 -m pytest tests_replica/test_application_server_governance.py -q
  --timeout=180 -k "scope_interaction_refuses_a_stale or
  scope_interaction_refuses_a_target or exact_leased_noop or
  discarding_disposable_projection"
4 passed, 33 deselected in 36.21s

py -3.14 -m pytest tests_replica/test_universal_ui_interactions.py -q
  --timeout=180 -k "projection_reconciliation_cannot_replay_a_stale_property_change
  or node_library_search_filters_graph_metadata_and_places_by_keyboard"
2 passed, 75 deselected in 15.37s

py -3.14 -m pytest tests_replica/test_universal_application.py
  tests_replica/test_application_server_governance.py -q --timeout=180
  -k "drawn_domain_wire_preserves_both_selected_interfaces or
  visual_interface_authoring_rejects_partial_and_mismatched_graphs or
  group_and_ungroup_are_lossless_personal_wip_compositions or
  member_scope_inherits_the_signed_assignment_without_broadening_it or
  running_http_session_is_denied_immediately_by_graph_revocation"
5 passed, 116 deselected in 59.33s
```

The three red focused courts are not release failures discovered after a
repair. They are the pre-change executable contract for the one bounded
locality repair.

## 9. Implementation sequence

1. Keep this plan and the red locality evidence under review.
2. Add focused red authority/conflict courts.
3. Implement one bounded change: exact leased scope-local mutation plus scoped
   delta, without changing Cell shape, persisted schema, lifecycle, or public
   route.
4. Measure the same request/DOM trace.
5. Rerun focused security/function courts.
6. Rerun the unchanged real-browser editor court.
7. Release the editor boundary only if every required court and budget is green.

## 10. Explicit non-goals

This repair will not:

- create a second graph or session database;
- persist a projection;
- bypass graph interaction leases;
- weaken cross-scope authorisation;
- change the Universal Cell shape;
- introduce a product-specific kernel operation;
- attach to or restart a live founder session;
- release BABOOM desktop acceptance before editor release.

## 11. Second pre-change gate: remaining scope-entry latency

The first locality repair removed the duplicate pointer mutation, the full
`/api/universal/canvas` request, and the stale queue handoff. It did not meet
the release latency. The editor therefore remains RED.

### Unchanged real-browser result

The unchanged editor court completed in 18.19 seconds. Every functional check
passed. The only failures were the existing latency contracts:

| Measurement | Current | Required |
|---|---:|---:|
| Scope response | 384.6 ms | at or below 150 ms |
| Scope rendered | 406.6 ms | at or below 150 ms |
| Worst mutation acknowledgement | 379.9 ms | at or below 100 ms |

Other mutations ranged from 18 ms to 187.8 ms. No failed response, console
error, page error, or functional editor regression was observed.

### Measured phase attribution

One isolated scope POST against the current revision measured 313.041 ms from
the local HTTP client:

| Phase | Measured |
|---|---:|
| Interaction admission | 37.623 ms |
| Scope commit | 91.405 ms |
| New-scope projection and binding | 161.583 ms |
| Delta construction | 0.142 ms |
| Integrity check | 0.010 ms |
| JSON serialization and send | 0.934 ms |
| Remaining handler and loopback overhead | about 22 ms |

The real browser added about 67 ms before response acknowledgement and about
22-27 ms for DOM reconciliation in representative runs.

The returned topology delta is 150,326 bytes. Its largest fields are:

| Field | Bytes |
|---|---:|
| `topology_patch` | 45,126 |
| `interaction_projection` | 41,905 |
| `inspector` | 26,047 |
| `properties` | 10,640 |
| `control_state` | 8,377 |
| `obligations` | 6,387 |
| `configuration_state` | 5,344 |

### Confirmed causes

1. `_nested_canvas_scope` reads the destination relation, then scans 622
   global relation candidates for the 21-node UI scope. The destination
   already carries 291 explicit scoped relation/property incidences. All 23
   resulting UI wires are in that explicit set. The one additional property
   is already in `registry.root_properties`.
2. The same path then scans the global canvas property relation list after
   consulting the owner-indexed `root_properties`. For all 15 imported domain
   scopes, every returned wire is explicitly scoped. All additional returned
   items are owner properties, not undisclosed wires.
3. Scope admission authorizes the exact leased interaction. Scope commit then
   performs application/composer authorization and verifies the same released
   catalogue twice inside one request. This is real duplicate proof work; it
   must not be removed unless exact equivalence and revocation courts pass.
4. Materialized new-scope projection still indexes 4,805 Properties-lens
   relations even though the active UI scope has 259 property relations. One
   measured `_property_index` call consumed 26.596 ms; the other four calls
   together consumed less than 0.04 ms.
5. Projection also recomputes registered interfaces, view templates, catalogue
   metadata, design tokens, authorization labels, toolbar state, and
   configuration that the scope-only commit cannot semantically change.
6. The server returns unchanged global state in every topology delta. The
   browser currently requires those copies even though it already holds the
   exact base projection.

### Hypotheses still under test

1. Explicit scope incidences plus owner-indexed properties can replace the
   global relation/property scans for an authorised scope transition.
2. A scope-transition projection can recompute only the new scope, selection,
   inspector, Properties content, interfaces, topology, and interaction
   bindings while retaining exact unchanged fields from the accepted base
   projection.
3. The application/composer authorization work can be shared within one
   request only through existing revision-exact proof scopes; no authorization
   decision may be skipped or reused after a relevant Cell changes.
4. Omitting unchanged fields from the scope delta will reduce transport and
   merge work without changing the reconstructed projection.

### Smallest authority-preserving design

Introduce one disposable scope-transition materialization in the existing
interaction request. It is not persisted and is not a second graph.

1. Input authority is the exact leased browser projection, session, subject,
   accepted Store revision, and graph interaction.
2. The scope mutation remains one canonical `CellStore.commit`.
3. The materialization records the exact new revision, scope trail, visible
   roots, scoped relations, owner properties, and touched view-session Cell
   identities.
4. The server recomputes all scope-local graph fields and interaction bindings
   from the new canonical revision.
5. A field from the accepted base projection may be retained only when its
   declared dependencies are disjoint from the scope commit and the relevant
   authority proof remains valid at the new revision.
6. The server-held result is a complete disposable projection at the new
   revision; the browser receives only the changed topology/state fields.
7. Any revision, session, subject, scope, dependency, authorization, audience,
   lifecycle, or interaction-binding mismatch discards the materialization and
   falls back to the existing exhaustive projection or fails closed.

This design does not change the Cell shape, Store, persisted schema, public
route, lifecycle, interaction lease, or graph semantics.

### Red courts required before the second mechanism

1. A scope transition must not invoke `project_universal_canvas` after the
   canonical scope commit.
2. Scope derivation must not read a registered relation that is outside the
   destination's explicit scope incidences and owner-property set.
3. The bounded result, merged with its exact base projection, must equal the
   exhaustive canonical projection for every openable domain.
4. Every retained invariant field must equal the canonical generic projection
   at the same accepted revision.
5. Destination-scope controls, relations, interfaces, and properties must be
   rebuilt from canonical Cells, not copied from the previous scope.
6. Added, removed, or rewired relations and properties must invalidate the
   bounded path and preserve the exhaustive result.
7. Foreign-subject, foreign-session, stale-revision, expired-lease, and revoked
   authority cases must fail closed.
8. Cross-scope relation and shared-resource mutations must retain the existing
   authorization, contract, duplicate, lifecycle, and integrity checks.
9. Deleting every disposable projection must leave graph semantics unchanged.
10. The topology delta must carry every node and wire removal required to make
    the browser DOM equal the canonical new scope.
11. The unchanged locality and editor browser courts must pass at their original
   100 ms mutation and 150 ms scope-entry budgets.

Only one bounded mechanism will be implemented after these contracts are
executable. No threshold will be changed and no broad cache will be added.

### Second red baseline

The first two executable locality/equivalence contracts are RED before the
second mechanism:

```text
py -3.14 -m pytest tests_replica/test_application_server_governance.py -q
  --timeout=180 -k "scope_transition_does_not_use_the_generic_projector_and_matches_it
  or nested_scope_reads_only_declared_relations_and_owner_properties"
2 failed, 37 deselected in 15.38s
```

- The scope POST returns 400 when the generic `project_universal_canvas`
  projector is forbidden, proving that the current materialized path still
  depends on the generic projector.
- UI scope derivation reads `gm:wire:canvas:0`, an unrelated registered
  relation outside the UI destination's explicit scope and owner-property set.

The canonical-equivalence, invariant-field, rebuilt-local-field, and complete
DOM-removal assertions are part of the same first court and will execute only
after the bounded path stops invoking the generic projector. Existing stale,
foreign-subject, no-op, disposal, cross-scope, contract, and revocation courts
remain the fail-closed baseline and are not weakened.

## 12. First measured change under the second gate

The first bounded change after the second pre-change gate removes repeated
interaction-protocol reconstruction inside one exact accepted snapshot.

- The interaction protocol is still reconstructed from canonical Cells and
  compared with the supplied protocol before any interaction is admitted.
- The broker then reads the bounded interaction roots against that verified
  protocol. The server uses the same private bounded-reader shape when it
  constructs presentation bindings.
- The public HTTP contract, Cell shape, Store, interaction lease fields,
  lifecycle, authorization, integrity, and persistence are unchanged.
- No projection, protocol, or interaction fact is persisted or reused across
  revisions.

New focused courts:

```text
py -3.14 -m pytest tests_replica/test_cell_interactions.py -q
14 passed in 0.19s
```

This includes:

- exactly one protocol verification for a bounded broker issue at one exact
  snapshot;
- fail-closed rejection when a protocol vocabulary Cell is changed.

A temporary grouping regression was traced before accepting performance
evidence. The server import for the existing public `read_interaction` helper
had been removed while adding the private batch reader, but the scope execution
path still used it. Scope POST therefore returned HTTP 400 with
`name 'read_interaction' is not defined`; grouping waited for a DOM state that
could not occur. Restoring that import repaired the defect without changing
graph behavior.

Focused semantic evidence after repair:

```text
test_browser_routes_group_open_and_ungroup_the_live_governed_canvas
1 passed

focused stale/absent/no-op/disposal/scope-relation courts
5 passed

focused cross-scope/interface/grouping/revocation/subject courts
6 passed

unchanged browser scope-locality court
1 passed in 9.54s
```

The unchanged real-browser editor court again passes every functional check.
It remains RED only on the unchanged latency budgets:

| Measurement | Before this change | After this change | Required |
|---|---:|---:|---:|
| Scope response | 384.6 ms | 310.4 ms | at or below 150 ms |
| Scope rendered | 406.6 ms | 329.5 ms | at or below 150 ms |
| Worst mutation acknowledgement | 379.9 ms | 305.6 ms | at or below 100 ms |

The change removed about 74 ms from scope response and about 77 ms from rendered
scope entry in these unchanged browser runs. It did not satisfy the release
contract.

The canonical bounded-transition court remains RED because the scope route
still invokes the generic `project_universal_canvas` projector after commit.
The explicit destination-scope relation court is GREEN. No second mechanism is
accepted until the remaining cost is measured again and the canonical
equivalence court can execute without weakening its generic-projector ban.

## 13. Pre-change gate for the bounded scope-transition projector

This is the required measurement and proof boundary before replacing the
generic projector call in the scope-transition route. No mechanism change was
made while collecting it.

### Fresh all-functional browser baseline

The unchanged real-browser editor court completed in 18.20 seconds. Grouping,
ungrouping, scope entry, library placement, parameter editing, inspector lenses,
interface creation, wire creation, and topology reconciliation all passed.
There were no failed HTTP responses. Only the original latency gates failed:

| Measurement | Current | Required |
|---|---:|---:|
| Scope response | 310.4 ms | at or below 150 ms |
| Scope rendered | 329.5 ms | at or below 150 ms |
| Worst mutation acknowledgement | 305.6 ms | at or below 100 ms |

The unchanged browser locality court is GREEN: one pass in 9.54 seconds.

### Fresh phase and payload attribution

An isolated scope POST at the current WIP revision measured:

| Phase | Wall time |
|---|---:|
| Canonical scope commit | 71.054 ms |
| Complete projection plus interaction binding | 103.912 ms |
| Topology delta | 0.130 ms |
| Local HTTP total | 191.871 ms |
| Response payload | 150,375 bytes |

The profile was repeated with deterministic instrumentation. Profiling overhead
increased wall time, so the figures below identify causal work rather than
release latency:

- scope commit: 157.332 ms profiled;
- projection and binding: 259.547 ms profiled;
- generic `project_universal_canvas`: 141 ms cumulative;
- relation reads: 101 ms cumulative across 3,577 calls;
- bounded interaction reads: 44 ms cumulative for 190 reads;
- graph view templates: 23 ms cumulative for 47 renders;
- interface projections: 25 ms cumulative for 364 projections;
- dense snapshot compaction: 18 ms;
- broker issue: 22 ms;
- event-fact authority: 24 ms;
- scope commit admission: 79 ms profiled;
- scope commit application/composer authorization: 48 ms profiled;
- destination scope derivation: 10 ms profiled.

The generic call occurs before the fourteen existing
`ensure_universal_*_interactions` families. A correct bounded projector must
therefore provide a complete canonical scope projection to those unchanged
builders. It cannot optimize only the outgoing delta, omit interaction
authority, or issue a lease before the ensured interaction Cells are committed.

### Bounded implementation scope

The mechanism is one private scope-transition projector inside the existing
Universal Application interpreter:

1. Keep `project_universal_canvas` as the exhaustive generic projector and
   canonical comparator.
2. Add a private/public-module-internal
   `project_universal_scope_transition` entry that does not call the generic
   projector.
3. Both entries may share one internal interpreter, but scope mode must require:
   the exact server-held previous projection, browser session, subject, view,
   expected base revision, accepted new revision, and
   `UniversalScopeMaterialization`.
4. Scope mode recomputes destination nodes, wires, properties, interfaces,
   selection, focus, inspector, controls, authorization labels, descriptors,
   and signatures from canonical Cells at the new revision.
5. It may retain a base field only if its declared dependencies are disjoint
   from the scope commit and the retained value equals the exhaustive projector
   at the same new revision.
6. The existing fourteen interaction builders remain unchanged and consume the
   complete bounded projection. Existing control uniqueness, visible-control
   coverage, event-fact authority, broker issue, exact post-ensure revision,
   lease, authorization, integrity, and cross-scope checks remain unchanged.
7. The server returns the existing topology-delta contract. No external field,
   route, schema, storage, lifecycle, or Cell changes.
8. Any subject, session, view, base revision, accepted revision, lease,
   authorization, scope, root, relation, interface, or removal mismatch fails
   closed. The generic projector is an offline/test comparator, not a runtime
   dependency or fallback for the accepted local scope path.

### Red-to-green proof plan

The existing red comparator court remains the primary mechanism gate:

`test_scope_transition_does_not_use_the_generic_projector_and_matches_it`

It must run with the application-server generic projector patched to reject and
then prove:

1. every retained invariant field equals an exhaustive generic projection at
   the same accepted revision;
2. destination controls, relations, interfaces, properties, nodes, and wires
   are rebuilt from canonical Cells;
3. subject, browser session, view, base revision, accepted revision, and lease
   mismatch fail closed;
4. cross-scope authorization, revocation, relation contracts, duplicates,
   lifecycle, and integrity behavior are unchanged;
5. deleting disposable projection material changes no graph semantics;
6. the response carries every DOM-required node and wire removal;
7. no enabled visible control is missing a graph interaction;
8. controls remain unique;
9. the interaction lease binds the exact post-ensure committed revision;
10. merging the topology delta into the exact previous projection equals the
    exhaustive canonical projection.

Focused source scope:

- `nodelang/universal_application.py`: interpreter entry and exact bounded
  validation only;
- `nodelang/application_server.py`: select the bounded entry for an accepted
  scope materialization and pass the already verified previous projection;
- `tests_replica/test_application_server_governance.py`: comparator,
  fail-closed, control, lease-revision, and removal courts;
- this plan: measurements and evidence.

No UI runtime, browser handler, public route, external schema, Cell shape,
storage, persistence, lifecycle, authorization policy, public runtime, or live
desktop process is in scope.

## 14. Bounded projector result and third diagnostic gate

The bounded scope-transition mechanism from section 13 is now implemented and
independently verified. This section records its exact result and the remaining
latency before any third mechanism is selected.

### Correctness evidence

The runtime scope path no longer calls the generic full-canvas projector. The
generic projector remains an offline comparator. The bounded result supplies
the existing interaction builders, retains their graph-published controls, and
issues the interaction lease at the exact post-ensure revision.

Local focused evidence:

```text
test_cell_interactions.py
14 passed in 0.19s

bounded projector, fail-closed, visible-control and declared-scope courts
4 passed, 37 deselected in 31.75s

browser delta consumer and topology courts
3 passed, 75 deselected in 12.44s

stale/absent/no-op/disposal/local-relation courts
5 passed, 36 deselected in 41.55s

cross-scope/interface/group/revocation/subject courts
6 passed, 119 deselected in 58.92s

real-browser locality court
1 passed in 10.75s
```

Independent read-only rerun:

```text
bounded application-server authority courts
4 passed, 37 deselected in 32.19s

browser authorization/catalog merge and topology courts
2 passed, 76 deselected in 12.52s
```

The unchanged real-browser editor court remains functionally green and
performance red. Its current isolated run had no failed HTTP responses or
console/page errors:

| Measurement | Current | Required |
|---|---:|---:|
| Scope response | 419.5 ms | at or below 150 ms |
| Scope rendered | 440.3 ms | at or below 150 ms |
| Worst mutation acknowledgement | 415.3 ms | at or below 100 ms |

The editor boundary is therefore not released.

### Stable-boundary phase measurement

The diagnostic rig used only three named runtime boundaries already exercised
by the green courts:

- `submit_universal_scope_interaction`;
- `ApplicationServer._project_interaction_canvas`;
- `_topology_canvas_delta`.

One isolated HTTP 200 scope transition measured:

| Phase | Wall time |
|---|---:|
| Scope commit | 103.004 ms |
| Bounded projection plus interaction binding | 123.391 ms |
| Topology delta construction | 0.132 ms |
| Local HTTP total | 269.987 ms |

The figures vary between cold and warm runs, so they are causal attribution,
not a replacement for the unchanged browser release court. A separate warmer
sample measured 66.984 ms for the scope commit, 60.568 ms for the bounded
projector entry, 0.137 ms for the delta, and 191.656 ms for local HTTP.

Two failed diagnostic markers did not change product source or court evidence:

1. a read-only `rg` query returned the normal no-match exit code 1, which a
   parallel orchestration wrapper treated as failure;
2. an attempted marker targeted `ApplicationServer._universal_integrity`, but
   that callable belongs to the generated HTTP handler. Python raised
   `AttributeError` before the POST.

Both isolated servers were closed. The corrected measurement above used no
unverified target.

### Released proof attribution

The current request performs one substantive released-catalogue proof for the
composer at the base revision:

| Proof operation | Revision | Calls and measured cost |
|---|---:|---:|
| Composer catalogue proof | 822 | 12.365 ms, then 0.001 ms in the same request |
| Adapter catalogue proof | 822 | 0.059 ms |
| Composer authority including digest | 822 | 12.519 ms |
| Stable catalogue proof after scope commit | 823 | 0.010 ms and 0.007 ms |
| Adapter catalogue proof after commit | 823 | 0.050 ms |

The second composer catalogue call is already reused by the existing
request-local catalogue proof. The post-commit stable proof is also already
effectively free because the scope commit did not touch any catalogue
dependency. Suppressing either check cannot account for the remaining latency.

The request-local catalogue key currently contains:

- the exact snapshot revision;
- the exact snapshot Cell-map identity;
- the assembly-protocol root;
- the catalogue root.

The proof reads and validates the released lifecycle Cell, catalogue digest,
definition membership, definition digests, interfaces, obligations, and
dependency relations from that exact snapshot. Subject and audience are not
part of this content-release proof. They are evaluated separately by
`require_authorization`, which receives the exact snapshot, resolved subject
and tenant, action, object, purpose, classification, audience, policy, and
revision-bound relationship-authority snapshot. No final authorization
decision is reused by the catalogue cache.

Any future combined request proof must include the exact snapshot identity and
revision plus subject, tenant/principals, action, object, audience, purpose,
classification, lifecycle, protocol roots, expiry, and every graph dependency.
No such combined proof exists or is proposed as accepted work here.

### Canonical response payload

The topology response is 379,117 compact JSON bytes:

| Delta field | Bytes | Share |
|---|---:|---:|
| `catalog` | 202,057 | 53.3% |
| `topology_patch` | 45,126 | 11.9% |
| `interaction_projection` | 41,905 | 11.1% |
| `authorization` | 26,657 | 7.0% |
| `inspector` | 26,047 | 6.9% |
| `properties` | 10,640 | 2.8% |
| `control_state` | 8,377 | 2.2% |
| `obligations` | 6,387 | 1.7% |
| `configuration_state` | 5,344 | 1.4% |

The catalogue has fourteen entries. Only four entries differ between the base
and destination scope, and each differs only in `composition_contract`:

| Definition | New entry bytes |
|---|---:|
| Model Descriptor | 35,260 |
| Cognition Request | 27,636 |
| Proposal | 26,901 |
| Model Binding | 25,480 |

Those four complete entries account for 115,277 bytes. In authorization, only
`assigned_canvas_roots` changes.

This does not authorize sending partial catalogue or authorization facts.
Current canonical merge courts require the complete fields because earlier
omission made the browser projection differ from the canonical projection.

### Browser merge and DOM attribution

The current real-browser scope run received the HTTP response at 419.5 ms and
observed the destination scope in the DOM at 440.3 ms. Therefore response-body
completion, JSON decoding, canonical merge, and DOM reconciliation together
take at most 20.8 ms in that run. There is not yet a trusted in-page marker that
separates those four subphases, so this plan does not invent a finer result.

The existing rendered-DOM stress probe remains green:

| Existing 250-node / 500-wire probe | Current |
|---|---:|
| Property reconciliation | 46.300 ms |
| Topology append and reconciliation | 85.955 ms |

The browser is not free, but the scope release failure is currently dominated
by server mutation/projection work before the response, not the observed
post-response scope reconciliation window.

### Third pre-change proof plan

No third optimization mechanism is approved by this diagnostic. Before changing
proof reuse or response fields, executable red courts must prove:

1. a request proof is bound to the exact snapshot identity and revision,
   subject, tenant/principals, action, object, audience, purpose,
   classification, lifecycle, protocol roots, expiry, and dependency set;
2. changing or revoking any bound Cell invalidates the proof and fails closed;
3. request-local reuse cannot cross a request, subject, session, revision,
   audience, lifecycle, or protocol boundary;
4. a reconstructed catalogue and authorization projection equals the generic
   canonical projection at the accepted revision;
5. destination controls, composition choices, relation choices, and assigned
   roots are neither stale nor omitted;
6. browser merge plus DOM state equals the canonical destination projection,
   including removals and revocation;
7. the public route, JSON schema, CellStore, graph schema, lifecycle, leases,
   persistence, and authorization behavior remain unchanged;
8. the unchanged functional browser court and original 100 ms / 150 ms budgets
   pass.

No cross-request cache, field suppression, alternate session store, hidden
authority, broad projection cache, threshold change, or transport/schema change
is permitted by this gate.

## 15. Pre-change gate for bounded admission and binding traversals

Section 14 rules out released-proof caching, response-field reduction, and
browser reconciliation as the next target. This gate is limited to the current
103.004 ms scope-commit and 123.391 ms projection/binding branches. It does not
change the commit, any interaction builder, the lease revision, or the
canonical comparator.

### Internal timing tree

The following cProfile figures include profiling overhead and have overlapping
cumulative children. They identify causal work; the unprofiled stable-boundary
measurements in section 14 remain the release baseline.

Scope commit:

| Internal operation | Profiled cumulative |
|---|---:|
| `admit_interaction` | 90.747 ms |
| `_authorize` | 69.684 ms |
| composer authority verification | 58.422 ms |
| all `read_relation` calls | 33.129 ms |
| two authorization evaluations | 20.449 ms |
| `dense_snapshot` | 17.900 ms |
| `_set_universal_scope_execution` | 11.384 ms |
| `_nested_canvas_scope` | 5.543 ms |

Projection and binding:

| Internal operation | Profiled cumulative |
|---|---:|
| bounded canvas interpreter | 132.570 ms |
| all `read_relation` calls | 95.454 ms |
| 39 bounded interaction-read batches | 42.514 ms |
| canvas-interface projection | 22.310 ms |
| interaction broker issue | 21.422 ms |
| seven event-fact authority ensures | 19.707 ms |
| `dense_snapshot` | 16.505 ms |
| property interaction ensure | 16.234 ms |
| instantiation interaction ensure | 13.055 ms |
| presentation interaction ensure | 10.242 ms |
| scope interaction ensure | 10.182 ms |
| relation-composer interaction ensure | 6.197 ms |

All fourteen `ensure_universal_*_interactions` families remain required. Their
graph Cells and exact post-ensure lease are not bypassed.

### Exact redundant traversal in admission

The non-transaction admission path currently checks a bounded tuple of input
roots with:

```python
set(interaction.input_roots) - set(snapshot.cells)
```

The second set materializes every Cell identity in the accepted snapshot. On
the current 159,668-Cell graph, seven direct measurements were:

```text
full snapshot iteration:
27.513, 27.118, 32.311, 37.241, 26.768, 27.823, 30.442 ms
median: 27.823 ms

bounded Mapping membership for the two roots:
0.102, 0.064, 0.083, 0.088, 0.025, 0.027, 0.087 ms
median: 0.083 ms
```

Both operations answer the same question. Exact `Mapping.__contains__` checks
preserve missing-root denial without traversing unrelated Cells.

### Exact redundant traversal after the fourteen builders

After all interaction builders commit, `InteractionProjectionBroker.issue`
reads and validates the complete interaction batch. The server then reads the
same batch again solely to construct the outgoing binding descriptors.

One exact scope projection recorded:

| Reader | Revision | Interaction roots | Roots digest | Time |
|---|---:|---:|---|---:|
| broker issue | 829 | 57 | `718fba5878b4c0c4558e79e640704c06b1f8e603b83557f03278b57ae0577864` | 7.356 ms |
| server binding | 829 | 57 | `718fba5878b4c0c4558e79e640704c06b1f8e603b83557f03278b57ae0577864` | 1.989 ms |

The broker traversal is authoritative and remains. The second traversal may be
removed only by explicitly returning the already-verified immutable
interaction tuple from the broker call stack. It may not be stored, cached,
reconstructed from HTTP data, or reused across a request or revision.

### Red courts before runtime changes

1. A non-transaction admission with bounded input roots must not iterate the
   complete snapshot mapping. Exact membership remains required, and a missing
   input root still fails closed.
2. The broker must be able to return the exact interaction objects it verified
   while issuing the lease, in the requested root order and at the lease
   revision.
3. The server must build outgoing binding descriptors from that returned tuple
   without a second canonical interaction read.
4. Every one of the fourteen existing interaction-builder families must still
   execute through its current function and publish any required Cells.
5. Control uniqueness, visible-control coverage, event-fact authority,
   admitted non-transaction actions, interaction subject, action inputs, and
   release requirements remain unchanged.
6. The lease revision must equal the exact post-ensure Store revision.
7. The bounded projection merged into its base must still equal the exhaustive
   canonical comparator, including authorization, catalogue, topology,
   inspector, properties, controls, and removals.
8. Stale revision, foreign subject/session, expired lease, revoked authority,
   missing input, duplicate control, and cross-scope denials remain green.
9. The unchanged browser functional and 100 ms / 150 ms performance courts
   remain the release authority.

### Bounded implementation scope

Only these runtime regions are eligible after the courts are red:

- `cell_interactions.py`: bounded input membership and an explicit
  issue-result that carries the already-verified in-call interaction tuple;
- `application_server.py`: consume that tuple for binding descriptors;
- focused interaction/application-server courts;
- this evidence plan.

`universal_application.py`, all fourteen interaction builders, the Cell shape,
Store, graph schema, persistence, public HTTP route and JSON schema,
authorization, lifecycle, interaction lease fields, generic comparator, UI
runtime, live process, and desktop surface are out of scope.

## 16. Bounded admission and binding repair

The section 15 courts were made red before runtime changes.

| Court | Exact red result |
|---|---|
| bounded non-transaction input admission | `cell_interactions.py:1695` iterated the complete overlay through `set(snapshot.cells)` |
| broker in-call interaction handoff | `InteractionProjectionBroker` had no `issue_with_interactions` operation |
| server duplicate-read denial | scope interaction returned HTTP 400 when the second server-side interaction batch read was forbidden |

The first admission-court run exposed a court-only fixture mismatch: the small
fixture used a copied `mappingproxy`, while the operating graph uses an overlay
mapping. The court was corrected to supply an overlay-backed snapshot and then
failed at the measured production line. No runtime source was changed to make
that fixture red.

### Implemented mechanism

1. Non-transaction admission now checks each declared input root through exact
   mapping membership. It no longer constructs a set of all Cell identities.
2. Broker issue can return one immutable, request-local
   `InteractionProjectionIssue` containing the lease and the exact interaction
   tuple verified during that issue call.
3. The existing `issue` interface remains compatible and returns the same
   lease by delegating to the bounded operation.
4. The application server consumes the returned tuple when building binding
   descriptors. It does not reread the same interaction roots.
5. The tuple is not persisted, cached, serialized, or reusable across a
   request. The ephemeral issue object rejects serialization mechanically, and
   its court proves that denial. The broker still verifies every interaction
   and issues the lease at the exact post-builder Store revision.

No Universal Cell shape, Store, graph schema, protocol, authorization,
lifecycle, public route, JSON response field, interaction builder, generic
comparator, UI runtime, or live process changed.

### Red-to-green evidence

```text
bounded admission plus broker issue courts
2 passed in 0.15s

duplicate server read plus all fourteen builder counters
1 passed in 9.14s

complete interaction-kernel court
16 passed in 0.22s

bounded projector, comparator, fail-closed, relation-scope, and duplicate-read
5 passed, 37 deselected in 43.24s

scope-locality real-browser court
1 passed in 11.11s
```

The widened JavaScript run initially found one stale court fixture:
`rapid_queued_gestures` clicked openable composition cards and waited for two
gesture writes. The current interaction policy deliberately defers and
coalesces openable-card click persistence so a double-click scope action is not
blocked by pointer-up writes. The same queue court against three non-openable
nodes produced two requests at consecutive revisions, zero stale requests, the
correct final selection, and no errors. The court fixture was narrowed to those
non-openable nodes; production UI code was unchanged.

```text
queue revision, authorization/catalog merge, and stable topology consumer
3 passed, 75 deselected in 12.68s
```

### Release state

The bounded mechanism is green through its focused and widened correctness
courts. The editor is not released. The unchanged heavy real-browser editor
court must still prove all functional checks plus the original 100 ms mutation
and 150 ms scope-entry budgets. That run is temporarily held for an explicit
external machine-priority production window; thresholds and acceptance
requirements are unchanged.

## 17. User-control acceptance closure while browser execution is held

The isolated browser court was audited against the founder's explicit editor
requirements while an external production task owned the machine-priority
slot.
Three capabilities already existed through graph-authored controls but were not
part of the release browser evidence:

1. personal recolouring of the selected node through the Presentation panel;
2. keyboard Undo and Redo through the graph-held change history;
3. local Node Library search followed by governed assembly placement.

The Presentation, history, and Node Library work changed no application
mechanism; they extended acceptance over existing graph-authored behavior. The
modifier-click audit did expose one runtime defect: pointer-up deferred every
unmoved openable-card click, including Shift/Ctrl selection, as if it might
become a double-click scope action. `ui_runtime.py` now records whether the
pointer-down included a selection modifier and bypasses that deferral only for
the modifier case. Unmodified openable clicks retain the existing double-click
scope boundary. No public route, Cell schema, lifecycle, authorization,
projection mode, alternate authority, live runtime, or process changed.

The existing court now requires:

- `presentation-color-updates-node`: open the graph-authored Presentation
  panel, submit the leased colour interaction, observe the same colour on the
  selected canvas card and swatch, and observe `PERSONAL-WIP` provenance;
- `keyboard-undo-redo`: undo an accepted title edit to its exact original value
  with `Ctrl+Z`, then redo it to the accepted edited value with `Ctrl+Y`;
- `library-search-is-local-and-usable`: filter to the Watcher assembly with no
  gesture or interaction request, activate that exact visible result with
  `ArrowDown`, and place it with `Enter` through its governed interaction;
- modifier click and marquee selection: Shift removes and Ctrl adds, while
  unmodified openable-card clicks retain the double-click scope boundary.

An independent read-only review found five proof defects in the first browser
court extension. The court now:

- correlates the initial and modifier-selection clicks plus every marquee
  exchange to the exact requested root list, accepted base revision, and a
  strictly newer committed revision;
- fails release on any failed governed response instead of accepting a later
  unrelated response;
- proves left-to-right partial intersection rejects a card while right-to-left
  crossing accepts it;
- proves Shift/Ctrl marquee operations preserve the other selected card;
- presses `ArrowDown` and `Enter` in the Node Library and verifies the exact
  returned `created_root` was absent before placement and is the only new
  Watcher card afterward;
- admits screenshot output only to a dedicated child of the operating-system
  temporary directory and rejects workspace destinations.

Focused mechanism evidence:

```text
presentation colour lease
1 passed, 78 deselected in 8.75s

Cell-native history keyboard controls
1 passed, 78 deselected in 12.40s

Node Library local search and keyboard placement
1 passed, 78 deselected in 10.39s

modifier click and marquee selection
2 passed, 77 deselected in 13.13s

screenshot custody boundary
1 passed, 1 deselected in 0.60s

browser court check-set parity
27 Python checks == 27 JavaScript checks
```

These focused results prove the mechanisms and the release-court contract, not
the browser release. The isolated real-browser run, screenshots, console/page
error check, direct-manipulation budgets, and visual inspection remain pending
until the external production task explicitly releases the machine slot.

When that slot is released, the court will write three isolated acceptance
screenshots to an explicitly supplied, court-admitted child of the
operating-system temporary directory: the initial graph, the active
Presentation edit, and the final authored graph. Those images must be inspected
in addition to the executable checks; a green DOM court alone does not
establish visual quality.

### Visual acceptance checklist

The 1600 x 960 desktop screenshots remain red unless all applicable checks are
visible:

Initial graph:

- the Node Library is visibly a searchable authoring catalogue, not an index;
- cards, ports, labels, and wires have a readable hierarchy without overlap or
  clipped text;
- wire endpoints make the actual source/target relation legible;
- selection feedback is attached to the selected object;
- the right-side Properties lens is immediately associated with the selected
  node;
- the default Use/Build view does not expose raw hashes or floor identities.

Presentation edit:

- Presentation is a working tab in the same Properties lens, not a separate
  modal or technical page;
- the selected card and the colour control show the same new colour;
- provenance is understandable without requiring the founder to read a raw
  Cell identity;
- panel content is neither clipped nor dominated by terminal-like metadata.

Final authored graph:

- newly placed nodes, parameters, interfaces, and wires are visible in the
  current scope;
- grouping, scope navigation, canvas controls, and relation handles remain
  discoverable;
- the graph remains readable after the full authoring sequence;
- there is no blank surface, displaced selection rectangle, incoherent
  overlap, console error, or stale status message.

Any failed visual item keeps the editor unreleased even if every machine check
returns true.
