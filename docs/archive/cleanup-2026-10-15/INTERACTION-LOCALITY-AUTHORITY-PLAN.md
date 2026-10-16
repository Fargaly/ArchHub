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

## 18. Dependency-tracked scope admission proof

The next bounded change addressed the measured composer-authority traversal in
scope admission. Scope entry previously opened a fresh request-local catalogue
verification scope and then called `authorize_composer_command`, which rebuilt
the released catalogue digest even when the Store's dependency-tracked proof
was already valid. This was redundant proof work, not an authorization rule.

The repair seeds the existing dependency-tracked released-catalogue proof at
the exact scope snapshot before `_authorize` runs. The normal composer and
application authorization decisions still execute. The stable proof's Store
listener still invalidates it when any catalogue dependency changes.

Red-to-green courts:

```text
scope proof reuse and dependency-drift denial
2 passed, 83 deselected in 23.54s
```

The first court warms the real proof, forbids a second catalogue digest walk,
and enters an openable composition. The second edits a released definition
dependency and requires scope entry to fail closed with definition drift.

Direct post-repair timing against one real built Universal Application:

| Phase | Before | After |
|---|---:|---:|
| Complete scope commit | 103.004 ms | 16.819 ms |
| Application plus composer authorization | 69.684 ms profiled | 6.183 ms |
| Composer authorization | 58.422 ms profiled | 0.162 ms |

No Cell shape, graph relation, Store, API, lifecycle, lease, authorization
decision, persistence, or cross-request projection cache changed.

This does not release the editor. Scope roots are bounded, but
`project_universal_scope_transition` still enters the shared complete canvas
interpreter. That interpreter rebuilds global invariant projection work even
though the accepted scope commit changed only the revision-bound view-session
composition. The next executable gate must forbid those unrelated global
rebuilds while proving exact canonical equality, revocation, removal, lease,
and destination-scope reconstruction. The unchanged browser budgets remain
100 ms for mutation acknowledgement and 150 ms for scope entry.

## 19. Exact scope focus without a complete Properties-lens traversal

Fresh isolated source-level instrumentation after the section 18 repair
measured one scope interaction as follows:

| Phase | Measured cost |
|---|---:|
| HTTP request and response | 283.541 ms |
| bounded canvas interpreter | 104.926 ms |
| fourteen interaction builders | 48.820 ms |
| relation projection inside the request | 70.207 ms |
| response payload | 379,014 bytes |

The relation trace recorded 5,836 reads over 983 exact revision/mapping/root
keys. The complete `app:properties-lens` relation cost 15.996 ms in one walk.
The application membership relation cost 14.325 ms across six revision-bound
walks. The latter is not in this repair: it crosses the fourteen graph-held
interaction builders and needs a separate gate.

The complete Properties-lens walk is redundant only in the minted scope path.
The scope executor has already derived the destination property roots from the
accepted canonical Cells, committed the new focus, and minted a private
materialization bound to the exact base revision, committed revision, browser
session, subject, trail, and `revision_changes`. The projector can therefore:

1. read the active focus directly through the view session's graph-held focus
   incidence and validate its role and participant;
2. use the materialized destination property roots without rereading every
   property incidence in every unrelated scope;
3. retain the complete Properties-lens traversal for exhaustive projection;
4. retain the canonical exhaustive projector as the equality comparator.

Red-to-green proof must show that the scoped projector cannot read the complete
Properties lens, still equals the canonical projection after merge, rejects a
malformed reusable projection, retains exact subject/revision/materialization
checks, and changes no Store, Cell, API, lifecycle, authorization, lease,
interaction-builder, persistence, or browser schema. No cache or second index
is introduced.

The new court first failed with HTTP 400 when the full Properties lens was
forbidden. After the bounded repair, canonical merge equality and all existing
materialization denials passed:

```text
exact scoped focus plus canonical comparator and fail-closed materialization
2 passed, 40 deselected in 27.31s
```

Fresh like-for-like instrumentation measured:

| Phase | Before | After |
|---|---:|---:|
| HTTP request and response | 283.541 ms | 228.653 ms |
| bounded canvas interpreter | 104.926 ms | 84.247 ms |
| relation projection | 70.207 ms | 45.161 ms |

The response remains 379,014 bytes and the 150 ms scope budget remains red.

## 20. Destination-bound public-interface projection

The next diagnostic profile found 394 canvas-interface projections during one
scope entry, with 368 uncached interpretations. The selected `gm:domain:ui`
destination contains 21 visible roots, 23 relations, and 259 property roots.
The application has 46 registered public interfaces, but zero of those 46 are
owned by the destination roots. Processing the complete registration is an
unrelated global traversal.

The bounded design retains application membership as authority while limiting
projection to interface identities explicitly referenced by the destination:

1. read the application relation once and retain only its interface-role
   members;
2. derive admitted interface roots from the destination relation endpoint
   incidences, the selected root, and explicit composition interface members;
3. project only the intersection of registered and admitted identities;
4. reuse the prior same-session interface-presentation options because the
   exact scope commit changed no interface vocabulary root;
5. retain exhaustive registration validation in the generic projector and the
   post-transition generic comparator.

The red court must reject any scoped call that omits the explicit admitted-root
set. Existing canonical merge equality, control coverage, subject/revision
drift, authorization, and exhaustive projection courts remain unchanged. This
adds no naming inference, persistence, cache, index, Cell field, API field, or
browser behavior.

The admitted-root court failed first with HTTP 400. After implementation, the
same canonical comparator and materialization-denial pair passed:

```text
destination-bound interfaces plus canonical comparator and fail-closed scope
2 passed, 40 deselected in 26.23s
```

Fresh measurement changed the bounded interpreter from 84.247 ms to
74.860 ms and reduced exact relation keys from 982 to 664. HTTP remained red
at 230.723 ms under the same machine load; the response stayed 379,014 bytes.

## 21. Relation-definition contract locality

The profiler records fourteen calls to
`_project_relation_definition_contract` on every scope entry. Whether a
released definition carries a relation contract is invariant across the exact
scope commit; only that contract's eligible visible-root choices change. The
same-revision previous catalogue already records which definitions have a
contract.

The bounded repair may call the canonical contract projector only for prior
catalogue entries whose `composition_contract` is a graph projection. Entries
with `None` remain `None`. The prior catalogue order and record shape are
validated before use, and the exhaustive comparator must remain equal after
the destination choices are rebuilt. No product kind, hard-coded definition,
cache, API field, or browser rule is introduced.

The bounded court first failed with HTTP 400 when all fourteen definitions
were projected. After limiting the work to the four definitions that actually
carry a relation contract, the canonical comparator and materialization
denials passed:

```text
bounded relation contracts plus canonical comparator and fail-closed scope
2 passed, 40 deselected in 25.59s
```

Fresh isolated measurement changed the bounded interpreter from 74.860 ms to
57.011 ms and relation work from 45.161 ms to 34.330 ms. The complete HTTP
request remained red at 225.211 ms and the response remained 379,014 bytes.

## 22. Released catalogue presentation reuse

Repeated unprofiled source-level measurements still reject release:

| Transition | Measurements | Response |
|---|---:|---:|
| enter `gm:domain:ui` | 202.490 / 264.197 / 252.762 ms | 379,014-379,099 bytes |
| return to `app:canvas` | 553.118 / 724.370 / 541.865 ms | 814,661 bytes |

An authorization trace disproved proof reuse as the next target. Scope entry
performs one verification at the accepted base revision and one after the
scope commit. They are different revisions and took 1.484 ms and 5.412 ms in
the measured request. They must not be merged or reused across that commit.

The next measured redundancy is the remaining four relation-definition
contract projections. Under a full request profile they consumed 94 ms,
including 71 ms in four `read_definition` calls. These definitions are part of
the released Node Library catalogue, not destination nodes, wires, controls,
properties, authorization, or active-scope state.

The existing authority already provides the required invalidation proof:

1. `verify_released_catalog_stable` verifies the current released catalogue
   and records every Cell dependency read by that proof;
2. the Store listener invalidates that proof whenever a commit touches any
   recorded dependency;
3. the previous catalogue presentation belongs to the server-held accepted
   projection that minted the exact interaction lease; it is not submitted by
   the browser;
4. the scope materialization is privately minted, bound to the same session
   and subject, requires `base + 1`, and matches the Store's exact
   `revision_changes`;
5. the scope interpreter still rebuilds destination nodes, wires, properties,
   selection, inspector state, controls, authorization, and the post-ensure
   interaction lease from canonical Cells;
6. the exhaustive projector remains the independent same-revision comparator.

The red court must forbid every call to
`_project_relation_definition_contract` on the bounded scope path. Only the
released static contract identity, role, cardinality, fixed-binding, and
constraint metadata may be reused. Every eligible choice must be rebuilt from
the destination's canonical visible Cells and labels. The court must still
prove exact canonical equality for both reused and rebuilt fields, unique and
complete controls, exact post-ensure lease revision, malformed projection
denial, subject/revision/materialization denial, and unchanged topology
removals. The exhaustive path must continue to interpret every definition
normally. No Cell, Store, schema, API, lifecycle, authorization, persistence,
cross-request projection cache, or browser handler may change.

The first attempted implementation copied complete contracts and failed the
canonical comparator because their choice lists still named the previous
scope. That implementation was rejected. The corrected repair reuses only
strictly validated static contract metadata and derives each eligible choice
from current destination Cells. The focused comparator and denial courts then
passed:

```text
static released contract plus canonical destination choices
2 passed, 40 deselected in 26.77s
```

Fresh unprofiled measurements changed domain entry from 202.490-264.197 ms to
175.273-205.446 ms. One return to the larger application scope changed from
the earlier 541.865-724.370 ms range to 454.509 ms. Both transitions remain
above their release budget, so the editor remains red.

## 23. Static design-system projection locality

The post-section-22 profile attributes 46 ms under instrumentation to opening
and validating the deterministic design-token system, including 36 ms building
its expected physical graph. Token resolution and icon projection add further
work. Scope entry cannot edit those resources: its privately minted commit is
one exact `base + 1` revision containing only the view-session scope, selection,
and focus transition. A concurrent or foreign commit invalidates the
materialization before projection.

The bounded design may reuse only the prior server-held projection's static
design-token, component, and icon data. It must:

1. strictly validate the reusable design-system projection shape;
2. rebuild personal theme revision facts and theme fields from current Cells;
3. rebuild the control-presentation and activation catalogues from current
   Cells, including current selection/scope applicability;
4. replace the reused projection's control catalogue with that rebuilt value;
5. retain exact canonical equality and the exhaustive projector as comparator;
6. reject malformed reusable design data, base/revision/subject drift, and any
   materialization not minted by the scope executor.

The red court forbids `open_archhub_design_token_system`,
`project_design_system_runtime`, and `project_icon_catalog` only on the bounded
scope path. Exhaustive projection must continue to execute all three. No
Store, Cell, schema, API, lifecycle, authorization, persistence, browser
handler, or cross-request cache changes.

The red court first returned HTTP 400. After the bounded branch reused only
strictly validated static token/component/icon data and rebuilt the current
control catalogue, the exhaustive canonical comparator and existing
materialization denials passed:

```text
static design projection plus current controls and canonical comparator
2 passed, 40 deselected in 26.13s
```

Initial end-to-end samples remained noisy and red at 192.688-213.347 ms for
domain entry and 528.796 ms for the larger application scope. Direct repeated
projector measurement is required before attributing an improvement; these
HTTP samples are not release evidence.

## 24. Explicit composition-boundary endpoint index

Repeated direct measurement of `_nested_canvas_scope` for `gm:domain:ui`
recorded a 54.890 ms median and the exact result shape 21 nodes / 23 relations /
259 properties. A diagnostic profile found 3,095 `read_relation` calls. The
scope contains 66 relation endpoints and 21 visible owners, but only 30 unique
endpoint identities. `_canvas_endpoint` repeatedly scans every owner and its
interfaces to rediscover explicit composition boundaries.

The graph already declares every boundary through an owner's `interface`
incidence and the interface's `seed` and `authority` incidences. The bounded
repair is one disposable request-local index over those exact relations:

1. read each visible owner relation once;
2. project each explicitly owned interface once through the existing generic
   interface interpreter;
3. index its graph-held seed/endpoint-incidence pairs to the owning visible
   root and projected boundary;
4. resolve each source/target endpoint through that index before falling back
   to the existing direct-interface projector;
5. reject duplicate ownership, wrong-side wiring, or malformed interfaces;
6. discard the index when `_nested_canvas_scope` returns.

The red court extends the existing locality court: no unrelated relation may
be read, no declared owner/relation may be reread, and the complete nested
scope tuple must equal the canonical pre-change result. Existing scope
canonical-comparator, topology-removal, authorization, lease, and browser
courts remain unchanged. No Cell, Store, schema, API, persistence, naming
inference, cross-request cache, or alternate graph is introduced.

The red locality court first failed when the target composition and each
endpoint owner were reread. The repair determines composition from the
already-read member relations, builds the disposable endpoint indexes once,
and passes them through `_canvas_endpoint`. Focused evidence then passed:

```text
declared-relation locality
1 passed, 41 deselected in 10.94s

locality plus canonical comparator and fail-closed scope
3 passed, 39 deselected in 36.57s
```

Repeated direct `_nested_canvas_scope` measurements changed from a 54.890 ms
median to 37.990 ms (32.944-40.621 ms), while preserving the exact 21-node,
23-relation, 259-property result. Fresh end-to-end samples were 189.601 ms for
a cold domain entry, 469.720 ms for the larger parent scope, and 161.542 ms for
domain re-entry. The direct nested-scope work improved by about 31 percent,
but the re-entry result is still above the 150 ms release budget. The next
gate must therefore measure the duplicate validation of already-existing
interaction identities before the final lease validates those same identities;
it must not weaken creation, authorization, revision, or lease checks.

## 25. Exact-snapshot interaction read scope

A warm re-entry trace measured 172.614 ms end to end. The fourteen ensure
families read 64 unique existing interactions, and the final lease read 57
unique interactions. Every lease-admitted interaction was therefore parsed
once by an ensure family and again by the lease; seven additional definitions
were correctly checked by ensure but were not visible controls in that scope.
The final lease itself took only 2.636 ms.

A second diagnostic separated the duplicated work. Ensure-time interaction
reads projected the same interaction protocol 64 times (7.840 ms) and parsed
64 interaction relations (15.177 ms). The lease projected the protocol once
(0.094 ms) and parsed its 57 admitted interactions in 2.266 ms. This rules out
removing or weakening the final lease as a useful or acceptable repair.

The bounded mechanism may reuse verified protocol and parsed interaction data
only inside one `_project_interaction_canvas` call. Every entry is keyed by the
exact immutable snapshot mapping identity, revision, protocol root, and, for
an interaction, interaction root. A cache hit must still call the generic
relation reader with the caller's budget so that a prior generous traversal
cannot bypass a later smaller budget. The context is discarded when the
request returns or raises.

The RED courts must prove:

1. repeated reads in one scope project one protocol and parse each interaction
   once while preserving the exact returned value;
2. the same revision number over a different snapshot mapping is not reused;
3. a new revision is not reused;
4. a smaller traversal budget still fails closed after a cached read;
5. calls outside the request scope do not share verified data;
6. every ensure-family semantic comparison, final action/input/subject/control
   validation, exact lease revision, canonical scope comparator, malformed
   materialization denial, and authorization behavior remain unchanged.

No Cell, Store, schema, API, lifecycle, persistence, cross-request cache,
control mapping, interaction definition, or browser handler may change.

Both new courts failed first because no interaction read scope existed. The
implemented scope retains the generic relation budget check on every cached
interaction access and keys verified values by exact snapshot mapping identity
and revision. Focused evidence passed without changing any ensure comparison
or lease rule:

```text
exact-snapshot interaction scope courts
2 passed, 16 deselected in 0.18s

complete generic interaction court
18 passed in 0.31s

canonical scope comparator, fail-closed drift, and declared locality
3 passed, 39 deselected in 37.46s
```

A post-change trace observed two required pre-commit protocol checks at
revision 837 and one shared post-commit projection check at revision 838. The
post-commit ensure and lease path therefore no longer projects the protocol 65
times. End-to-end samples remained red and load-sensitive: the best warm domain
entry was 156.301 ms, other warm samples were 206.094-207.345 ms, and a separate
instrumented entry was 179.858 ms. Parent-scope samples were 532.826-798.180 ms.
The change is accepted for authority-preserving locality, but it does not pass
the 150 ms release gate and cannot release the editor.

## 26. Rejected endpoint-classification experiment

Instrumentation initially attributed 23.592 ms to 30 failed interface
projections over large ordinary domain relations. A RED court and bounded
known-non-interface branch were implemented, and the canonical/locality courts
passed. A same-process A/B comparison against the exact prior endpoint behavior
then disproved the performance hypothesis: current median 28.651 ms versus
prior median 27.908 ms, with identical output. Profiling overhead had magnified
the failed projections; the proposed classification added no production gain.

The branch and its court were therefore removed. Interface interpretation
retains its prior universal semantics, including unregistered graph-declared
interfaces. This result rules out endpoint classification as the next latency
target and prevents an unnecessary semantic restriction from entering the
kernel.

## 27. Scope-render endpoint locality

An unprofiled caller-attributed trace of one `gm:domain:ui` scope entry found
2,810 generic relation reads taking 33.289 ms inside the accepted request. The
largest repeated traversals were 966 reads from `_canvas_endpoint` and 1,385
reads from `_relation_members_or_none`. The cause is concrete: scope discovery
already builds the graph-declared owner-interface and composition-boundary
indexes in `_nested_scope_endpoint_indexes`, but the final scoped canvas
renderer calls `_canvas_endpoint` without those indexes for every wire. Each
wire endpoint therefore rescans the visible owner relations.

The bounded repair may construct the same disposable indexes once from the
exact destination snapshot and visible roots, then pass them to every final
wire endpoint resolution. It must:

1. derive ownership and boundaries only from explicit graph incidences;
2. retain generic interface projection and malformed/duplicate-owner denial;
3. remain request-local and disappear when projection returns or raises;
4. preserve the exact canonical canvas and interaction delta;
5. retain current authorization, revision, conflict, lifecycle, lease, and
   cross-scope checks;
6. add no Cell, Store, schema, API, persistence, naming inference, cache, or
   alternate authority.

The RED court must enter a real composition scope and prove that every bounded
wire endpoint call receives the exact owner-interface and boundary indexes,
while the existing exhaustive comparator proves merged output equality. The
existing fail-closed materialization, control uniqueness, post-ensure lease,
declared-relation locality, and browser behavior courts remain unchanged.
Performance acceptance requires a same-process A/B measurement against the
exact pre-change endpoint behavior before the repair is retained.

The new court failed first with 46 unindexed final-render endpoint calls. The
bounded renderer now constructs the disposable indexes once and passes them to
both wire and selected-relation endpoint projection. Focused evidence passed:

```text
endpoint-index, canonical comparator, fail-closed drift, and locality
4 passed, 39 deselected in 52.08s
```

A 15-pair same-process A/B comparison against the exact prior scanning path
preserved identical output and changed median destination projection from
47.035 ms to 43.485 ms, a 3.549 ms / 7.5 percent improvement. Caller-attributed
relation reads fell from 2,810 to 899; the 966 `_canvas_endpoint` owner rescans
were eliminated and `_relation_members_or_none` calls fell from 1,385 to 440.
The change is accepted because the gain is independently measurable and the
court pins the graph-declared endpoint source. It does not by itself release
the still-red end-to-end 150 ms scope-entry budget.

## 28. Rejected overlay memo and exposed top-scope locality defect

Repeated real HTTP scope transitions showed the current physical overlay depth
increasing from 9 to 20. Domain entry ranged from 155.522 to 229.345 ms while
returning to the application composition ranged from 565.386 to 748.522 ms.
This justified testing the physical lookup hypothesis, but not assuming it.

The established persistent-map family is a structurally shared hash trie rather
than an unbounded linear overlay: Bagwell's *Ideal Hash Trees* describes hash
array mapped tries with bounded key lookup, while Python's current
`MappingProxyType` contract supplies a read-only view but not persistent-map
lookup guarantees. The environment contains `rpds-py` transitively, but the
product does not declare that dependency and replacing the Cell mapping with a
HAMT is a kernel migration, not a bounded editor repair.

A disposable 10,000-entry overlay memo prototype was therefore measured before
any source edit. It was not reliable: domain entry varied from 139.498 to
280.048 ms and parent entry from 454.734 to 799.989 ms as depth increased. It
also accumulated more than 111,000 cached references after five cycles. The
memo is rejected and no `CellStore` source was changed.

The follow-up parent-scope trace exposed the actual larger defect. Returning to
`app:canvas` projects only 17 nodes, 136 wires, and 5 selected properties, yet
the request performed 10,915 relation reads and spent 310.401 ms in the bounded
projector. `_property_index` swept 4,682 property relations (93.471 ms) and
`_canvas_scope_for_assigned` performed 5,361 containment reads (27.893 ms).
The top composition has no bounded authoritative property/relation scope index,
so returning to it reconstructs locality by sweeping the operating graph.

The next design gate must define that index as ordinary graph-held composition
relations, maintained atomically with topology/property changes and validated
against a full canonical reconstruction. It cannot be a Python registry, hidden
cache, copied parent projection, second store, naming convention, or route
bypass. Until that graph contract and its mutation/revocation courts exist,
parent navigation remains explicitly unreleased.

Research references:

- https://infoscience.epfl.ch/entities/publication/b892b2ce-7bf0-41d2-b68c-fb44a3c64a33
- https://docs.python.org/3.14/library/types.html#types.MappingProxyType

## 29. Hidden-descendant property exclusion

The top-scope sweep returned 4,680 property relations for 17 visible composition
roots and 136 visible relations. An exact owner check proved that only 631 of
those property relations belong to visible roots or visible relations; 4,049
belong exclusively to descendants hidden behind the composition boundary. The
631 graph-derived identities exactly equal the existing owner/property bindings,
with no missing or extra roots.

This is a correctness boundary as well as a performance defect. The active lens
must not parse hidden descendant properties merely because their ancestor is a
visible composition. The bounded repair keeps the existing canonical property
sweep but admits a property root into the resulting scope only when its explicit
graph-held owner is a visible root or visible relation. No registry lookup,
copied projection, naming inference, cache, or new graph contract is permitted.

The RED court must prove every returned property relation has exactly one owner
inside the returned visible-root/relation set and that at least one known hidden
descendant remains excluded. Existing scope comparator, authorization,
materialization, browser, and restart courts remain unchanged. After correctness
passes, direct and HTTP measurements determine whether the filter is retained as
a meaningful performance repair.

The new court failed first because hidden descendant properties were present in
the returned top scope. The bounded admission correction now retains properties
only when their explicit owner is a visible root or visible relation. Focused
authority evidence passed:

```text
hidden-property exclusion, endpoint indexes, canonical comparator,
fail-closed drift, and declared locality
5 passed, 39 deselected in 68.54s
```

Five isolated HTTP enter/return cycles preserved the exact 17-node/136-wire top
graph. Domain-entry median was 174.177 ms. Top-scope return median fell from the
prior 708.001 ms to 462.835 ms, a 245.166 ms / 34.6 percent improvement. The
change is retained because it repairs the active-lens boundary and removes a
measured cost, but both scope directions remain above the 150 ms release budget.

## 30. Top-scope endpoint locality

A post-repair phase trace measured a 391.821 ms top-scope return. Scope commit
took 93.918 ms; bounded projection took 208.801 ms; binding around the projector
added about 41.7 ms; delta construction took 0.346 ms. A direct profiler run is
diagnostic only because tracing inflated total execution, but it located the
repeated traversal: `_session_canvas_roots` spent 201 ms under instrumentation,
including 336 `_project_canvas_interface` calls. The top-scope relation sweep
calls `_canvas_endpoint` without the owner-interface and boundary indexes that
the nested-scope and final-render paths already derive from the same Cells.

The next bounded repair may construct those existing disposable indexes once
from the exact snapshot and assigned visible roots, then pass them to every
top-scope wire endpoint resolution. It must preserve generic interface
projection, malformed/duplicate-owner denial, exact visible relations,
properties, authorization, revision, conflict, lifecycle, and lease semantics.
It adds no Cell, Store, schema, API, persistence, naming inference, or
cross-request cache.

The RED court must prove every top-scope wire endpoint receives the same
request-local interface, owner, and boundary indexes. Existing hidden-property,
canonical comparator, fail-closed drift, nested locality, and final-render
endpoint courts remain unchanged. The mechanism is retained only after the
focused courts and a same-process before/after measurement preserve exact
output and show a repeatable gain.

The new court failed first because no top-scope endpoint call received the
owner or boundary indexes. The bounded repair now constructs the existing
graph-derived indexes once and passes them to every top-scope endpoint read.
Focused authority evidence passed:

```text
top and final endpoint indexes, hidden-property exclusion,
canonical comparator, fail-closed drift, and nested locality
6 passed, 39 deselected in 76.30s
```

A 15-pair same-process A/B comparison against the exact prior scanning path
preserved 136 relations and 631 properties with identical ordered output.
Median top-scope discovery changed from 65.841 ms to 49.140 ms, a 16.700 ms /
25.4 percent improvement. The repair is retained. Five end-to-end HTTP cycles
under current machine load remained variable and red: domain median 200.969 ms
and top-scope median 500.065 ms. The editor therefore remains unreleased.

## 31. Persistent physical Cell map

The remaining request profile performs tens of thousands of exact Cell identity
lookups against a linear immutable overlay chain. This is a physical storage
cost, not graph semantics. The current chain preserves snapshots cheaply but an
unchanged key can require one failed dictionary lookup per intervening revision.

The established replacement family is a persistent hash array mapped trie.
Bagwell's *Ideal Hash Trees* supplies the structural-sharing lineage; Python's
PEP 603 documents the same persistent immutable-map contract and its bounded
lookup/update characteristics. The installed `rpds-py` 0.30.0 implementation
provides `HashTrieMap`, but it is not yet declared in either product or Windows
packaging requirements and it does not promise insertion order. Physical map
iteration therefore cannot be accepted as semantic ordering.

A bounded synthetic benchmark used the same immutable `Cell` values, 20,000
base identities, sixteen 32-Cell revisions, and 120,000 unchanged-key reads.
The current overlay-chain median was 304.176 ms; `HashTrieMap` was 77.612 ms,
about 3.9 times faster. Median immutable update cost was 0.0288 ms versus
0.0424 ms. This is sufficient to create RED courts, not to claim application
performance.

The migration may replace only the physical immutable mapping under `Snapshot`.
It must preserve the four-field Cell, one Store, revision numbers, conflict and
dangling-link checks, exact changed-root sets, history/journal reconstruction,
revision-chain digests, old snapshots, candidate snapshots, mapping
immutability, and every public API. It may add no semantic index, cache, route,
schema, lifecycle, or second authority.

RED courts must prove:

1. current and historical snapshots remain immutable and prior revisions do not
   change after later commits;
2. current lookup depth is structurally bounded rather than proportional to
   revision count;
3. candidate overlays and normal commits use the same persistent mapping
   contract;
4. physical insertion order cannot alter fingerprints or revision-chain
   digests;
5. the persistent-map lookup court beats an embedded exact linear-overlay
   reference on the same process without weakening output equality;
6. runtime and Windows build requirements declare the binary dependency;
7. focused Cell, journal, restart, canonical canvas, security, and unchanged
   browser courts pass before the physical representation is accepted.

References:

- https://infoscience.epfl.ch/entities/publication/b892b2ce-7bf0-41d2-b68c-fb44a3c64a33
- https://peps.python.org/pep-0603/

The five new physical-map courts were run RED before the implementation. Four
failed: committed and candidate snapshots had no persistent backing map,
unchanged-key lookup did not beat the exact former linear-overlay reference,
and neither runtime nor Windows packaging declared the dependency. The digest
ordering court already passed and remained unchanged.

The bounded implementation replaced only `_OverlayCellMap` internals with one
`HashTrieMap`; each new immutable revision structurally shares the prior map
and keeps `_depth == 1`. `Cell`, `Snapshot`, `CellStore`, revisions, commit
validation, journal persistence, routes, and graph semantics were not changed.
`rpds-py` is now declared in runtime requirements and pinned for the Windows
bundle. The five courts then passed:

```text
tests_replica/test_universal_cell_persistent_map.py
5 passed in 0.72s
```

The same 20,000-base / sixteen-revision / 120,000-read benchmark after the
repair measured 58.255 ms for the persistent map and 295.307 ms for the exact
former overlay, a 5.07x unchanged-key lookup improvement. Existing focused
regressions are also green: 10 incremental Cell courts, 18 interaction courts,
6 history courts, 65 kernel/relation/rule/capability/durability/security courts,
16 relation-contract courts, and 8 Windows packaging courts. This proves the
physical storage contract only. The canonical application, restart, and
unchanged real-browser performance gates remain required before this migration
or the editor can be released.

A second RED court proved that `dense_read_snapshot` still copied the complete
persistent map even though the HAMT has no linear overlay to flatten. An
isolated runtime-only identity substitution preserved the exact 17-node / 136-
wire top projection while reducing domain-entry median from 139.011 to 127.260
ms and top-scope return from 842.812 to 318.916 ms. The source was then changed
so dense reads reuse the bounded immutable mapping. Sixteen persistent and
incremental courts passed, followed by 128 kernel, relation, interaction,
history, durability, shared-authority, security, and packaging courts.

Five source-backed isolated HTTP cycles then measured domain entry at 118.149
ms median and top-scope return at 317.708 ms median. All five returns preserved
17 nodes and 136 wires. The final-source complete authoring/restart court passed
in 58.83 seconds. The six unchanged canonical/fail-closed/locality courts also
passed in 159.79 seconds. The domain direction is below the 150 ms budget in
this bounded run; the parent direction and unchanged real-browser court remain
red.

## 32. Graph-held scope projection, not a copied index

The post-repair parent profile attributes 154 ms to
`_session_canvas_roots`, including 145 ms in
`_canvas_scope_for_assigned`. The application composition exposes only 17
direct roots, 136 wires, and 631 applicable properties, but the current
interpreter reads every relation and property incidence registered on the
global canvas before filtering them back to that bounded set.

Two apparent shortcuts were measured and rejected:

1. `registry.root_properties` happens to reproduce all 631 current top-scope
   properties, but it is a Python projection rebuilt at application restore.
   It is not live graph authority and cannot prove later property additions.
2. The visible domain roots currently expose zero graph interfaces carrying the
   136 top-level wire identities. Interface-derived adjacency therefore cannot
   reconstruct this scope today, and inferring it from names would violate the
   specification.

Incremental view-maintenance literature treats a materialized view as a derived
result that must be maintained from the same changes that modify its source;
the delta must cost less than full recomputation while preserving the original
query semantics. DBSP provides a formal incrementalization model for rich
queries, and graph-view maintenance applies the same rule to changing graph
patterns. ArchHub does not need a second dataflow engine for this repair. It
needs the smaller invariant already implied by the one-graph architecture: a
scope projection is an ordinary graph relation, replaced atomically in the same
Cell commit as the topology/property change that affects it.

The bounded design extends the existing per-view scope-exposure relation. One
active exposure entry for each parent scope will contain explicit graph roles
for:

- the parent scope;
- every direct visible root;
- every visible relation/wire root;
- every applicable property relation root.

The entry is not a second store or independent truth. It is a graph-held,
append-oriented materialized projection of canonical Cells. A replacement
entry and its registry-pointer change must be committed in the same revision as
wire creation/removal, property creation, placement, grouping, ungrouping, or
other membership change. Scope selection, focus, pan, and navigation do not
rewrite it. Restore/migration reconstructs it from the canonical generic
projector before the application is admitted. Runtime scope entry reads the
bounded entry; the generic full projector remains the comparator and recovery
path, not the normal navigation path.

Before implementation, RED courts must prove:

1. the initial and restored top exposure equals the generic canonical roots,
   relations, and properties at the same accepted revision;
2. wire add/remove/rewire and property add update the exposure atomically with
   no intermediate accepted revision;
3. placement, group, ungroup, undo, and redo preserve exact projection
   membership and append-only history;
4. a missing, duplicate, foreign-session, wrong-parent, or malformed exposure
   fails closed rather than falling back silently;
5. a stale exposure cannot mint an interaction lease, and recovery may rebuild
   it only from canonical Cells under the existing authority;
6. hidden descendants remain absent, while every visible control, relation,
   interface, and property required by the DOM remains present;
7. deleting the projection entry changes no underlying graph semantics, and an
   authorised reconstruction produces the same canonical view;
8. no Python registry, cross-request cache, new store, route, public schema, or
   naming inference enters the runtime path;
9. unchanged browser authoring, restart, security, and canonical comparator
   courts pass, with mutation acknowledgement at or below 100 ms and both scope
   directions at or below 150 ms.

## 33. One-request reuse of already validated relation projections

The graph-held visibility projection removed the global relation/property
sweeps and the complete authoring/restart court now passes. The current
parent-scope request still validates its bounded visibility, wire, and property
relations during the scope commit, destroys that request-local relation cache,
then walks the same immutable relation Cells again during projection. This is
duplicate physical interpretation inside one accepted transaction, not a
missing semantic index.

The bounded repair may extend the existing private
`UniversalScopeMaterialization` with exact relation projections captured from
the scope executor's existing request-local cache. Each entry must retain the
source revision, projected members, traversal budget cost, and every source
Cell whose links determined that projection. The projector may seed only its
existing request-local relation cache after proving:

1. the materialization was privately minted for the same session, subject,
   base revision, committed revision, and exact changed-root receipt;
2. every captured entry came from the exact base snapshot or its isolated
   candidate revision and belongs to the bounded visible, relation, property,
   or visibility roots;
3. every source Cell is byte-for-byte identical in the committed snapshot;
4. any source-cell, revision, session, subject, or receipt drift fails closed;
5. the seeded entries disappear when the interpreter request exits and are not
   available to a later request;
6. ordinary uncaptured relations still use canonical `read_relation`;
7. no Store, Cell, graph schema, public API, persistence, cross-request cache,
   semantic index, or alternate authority is added.

RED courts must prove exact dependency validation, disposal after the request,
all parent-scope wire/property first reads hitting the seeded cache, tampered
source denial, and unchanged canonical scope output. Only after those courts
fail for the missing mechanism may the bounded reuse be implemented. The
unchanged fail-closed, restart, authority, browser, and latency courts remain
release gates.

## 34. Carry graph-resolved endpoint interfaces through the same request

The post-reuse profile still spends about 31 ms in
`_scope_canvas_interface_roots`. The graph-held visibility validator has
already opened every indexed wire and resolved both endpoints through
`_canvas_endpoint` before the scope commit. It currently discards the exact
interface identities, and the projector walks all 136 wires again to recover
them.

The next repair may add only those already resolved interface identities to the
private `UniversalScopeMaterialization`. It must be derived from the same
accepted visibility relation, filtered to the final visible scope, and used
only when the exposure lens did not alter that baseline scope. Nested or
exposure-altered scopes retain the existing canonical discovery path. The
selected root remains added dynamically by the projector.

The RED court must reject any second call to
`_scope_canvas_interface_roots` during an eligible parent transition and then
prove exact equality with the canonical nodes, wires, selected interface, and
selected interfaces. Empty, foreign, hidden-owner, malformed, or
exposure-altered interface materialization must fall back or fail closed as
appropriate. No interface registry, new graph role, persistence, public field,
cross-request cache, naming inference, or renderer shortcut is permitted.

## 35. Batch proof for immutable relation reuse

Profiling the corrected interface-complete parent projection shows 830 captured
relation entries spending about 44 ms in per-entry source reconstruction and
snapshot comparison. The accepted Store commit already publishes the exact
changed-root receipt, while every unchanged Cell remains immutable across the
adjacent revisions. Revalidating every unchanged chain therefore repeats a
proof the Store has already supplied.

The bounded repair may seal the ordered captured batch with one deterministic
fingerprint over every source revision, relation root, projected member, step
count, and source Cell. Seeding must require that exact fingerprint and the
Store's exact changed-root receipt. If a changed root intersects any source
dependency, its current Cell must equal the captured Cell; a mismatch fails
closed. Unchanged dependencies may rely on the immutable adjacent-revision
contract. A wrong fingerprint, duplicate root, non-adjacent revision, malformed
entry, or changed dependency remains denied. The cache is still request-local
and disposable.

The RED court must reject an altered fingerprint and a changed incidence while
retaining request disposal and budget behavior. No signature authority,
process-global semantic cache, Store field, graph field, public API, or
persistence change is permitted.

## 36. Versioned graph-held visible-interface membership

The interface-complete repair exposed 46 registered ports on the 17 top-level
nodes, but finding them still scans the application composition and projects
every registered interface during each parent transition. These memberships
change only when graph topology registers an interface, so they belong beside
the existing visible-root, relation, and property memberships in the same
graph-held visibility relation.

The bounded design uses the assembly protocol's existing `interface` role; it
adds no role kind or Python registry. A graph marker records that the visibility
relation has migrated to the interface-index contract. Restore may add the
marker and exact canonical interface members once when the marker is absent.
After the marker exists, missing, extra, duplicate, foreign-owner, unregistered,
or malformed interface membership fails closed. Interface authoring appends the
new application registration and every affected visibility membership in the
same Store commit. Exposure-altered and nested scopes retain canonical bounded
discovery.

RED courts must prove exact equality with all graph-registered interfaces owned
by direct visible roots, marker presence, partial-index denial after migration,
and atomic single/batch interface authoring. Existing canonical output,
unwired-port, restart, authorization, changed-root, and request-disposal courts
remain unchanged. No second store, copied registry, naming inference,
cross-request cache, public schema, or renderer rule is permitted.

Research references:

- https://arxiv.org/abs/2203.16684
- https://arxiv.org/abs/1612.01641

## 37. Same-request reuse of the registered batch seal

The graph-held interface index is correct, but the latest phase trace keeps the
release red. Parent commit measured about 75 ms: graph visibility validation
37.7 ms, relation-batch fingerprint 18.6 ms, authorization 7.4 ms, and the
physical Store commit only 0.22 ms. Parent projection measured 96-106 ms before
HTTP and DOM work. Interface registration itself was only 2.8 ms, so removing
the graph index would neither repair the latency nor preserve the new unwired
port completeness court.

The server already opens one `relation_projection_scope` around the complete
POST. The scope executor computes a deterministic fingerprint for the exact
immutable projection tuple inside that request, but the projector calls the
same fingerprint function again before seeding the target-revision cache. This
is duplicate integrity work, not an authority requirement: the originating
tuple and its seal are both still present in the same request-local context.

The bounded repair may register `(exact tuple object, fingerprint)` only in the
existing disposable relation-projection context. Seeding may skip
recomputation only when the tuple is the same immutable object and the expected
fingerprint equals the seal registered earlier in that exact request. A later
request, reconstructed tuple, changed expected fingerprint, changed dependency,
non-adjacent revision, or changed-root mismatch retains the full deterministic
recalculation and existing denial. The registry is reset with the request
cache and is never persisted, exposed, or treated as graph authority.

The RED HTTP court rejects a second fingerprint call during the parent half of
one scope request. Existing unit and application courts continue proving wrong
fingerprint, altered source Cell, revision drift, subject drift, request
disposal, and canonical projection equality. No Cell, Store, schema, route,
public payload, lifecycle, graph role, or cross-request cache changes.

The repair is now green. Two low-level relation courts and three application
same-request/canonical/tamper courts passed. The first post-repair HTTP run kept
entry at 115.05 ms and reduced parent return from 259.66 ms to 226.19 ms median;
the parent remained above budget.

## 38. Capture only relations consumed by the parent projector

The parent materialization currently seals 830 projections: 17 visible roots,
136 wires, 631 properties, and 46 interfaces. The unchanged parent projector
reuses only wire and property relations. An alternating seven-cycle A/B run
removed the visible/interface entries from the disposable batch and preserved
exact node output in every cycle. Full and reduced projection medians were
103.37 ms and 103.56 ms respectively, while fingerprint microbenchmarks fell
from 17.83 ms to 5.91 ms.

The parent-return branch may therefore capture exactly the 136 relation roots
and 631 property roots that the projector consumes. Interface identities remain
explicit in `interface_roots`; visible roots remain explicit in
`visible_roots`; both stay validated by the graph-held visibility projection.
The nested-entry branch is unchanged because its smaller composition relations
were not part of this A/B result. The RED court now requires exact equality,
not merely a subset, between captured and consumed parent relation roots.

The exact-capture and same-request seal courts pass together. The change is
accepted for integrity and bounded work, but isolated HTTP timing remained
variable and red; no release claim follows from this micro-optimization.

## 39. Selection-scoped wire editing disclosure

The full top projection currently computes source and target rewire candidates
for all 136 binary wires. The server interaction builder and browser consumer
already admit disconnect/rewire controls only for the selected wire, so 135
wire-control payloads are unreachable in a normal turn. Profiling attributed
about 23 ms to 303 compatibility computations, before JSON transfer and client
merge cost.

Current React Flow performance guidance recommends isolating selected state
instead of repeatedly deriving it from the complete changing node/edge set:
https://reactflow.dev/learn/advanced-use/performance. The W3C disclosure
pattern likewise exposes controlled detail when its controlling element is
active: https://www.w3.org/WAI/ARIA/apg/patterns/disclosure/. These references
do not control ArchHub semantics; the specification, graph selection relation,
and existing topology interaction authority do.

The bounded repair keeps every wire and port visible. Connect candidates remain
on connectable source ports because direct manipulation can start from any such
port. Disconnect and source/target rewire controls and choices are projected
only onto the selected binary wire. Selecting a different wire changes the
graph-held focus, after which the same interpreter derives that wire's controls.
No client inference, hidden command, stale candidate list, schema addition,
graph change, or authorization bypass is introduced.

Three direct topology courts and three HTTP/canonical/reuse courts pass. A
seven-cycle isolated HTTP run then measured entry at 109.38 ms median and
parent return at 206.41 ms median, preserving 17 nodes, 136 wires, and 46
ports. The parent response is 561,653 bytes: topology patch 249,524, catalogue
164,301, interaction projection 61,262, authorization 26,657, and inspector
21,042 bytes. Parent scope remains red against the unchanged 150 ms budget.

## 40. Revision-bound reuse of an already accepted scope projection

The next trace separates the remaining parent request instead of treating its
206.41 ms total as one opaque delay. One isolated request made 1,870 relation
reads: 946 request-cache hits and 924 physical walks. Of those misses, 835 were
the canonical candidate-scope validation pass: 631 property relations, 136
wire relations, 46 interface relations, 17 visible roots, and five view-session
relations. The subsequent committed-revision projector correctly consumed its
seeded relations. A three-cycle named-boundary trace measured the projector at
74.33-84.37 ms and the complete HTTP turn at 173.20-185.54 ms under that run;
the unchanged seven-cycle acceptance median remains the controlling red result.

Re-entering a previously rendered scope is the one case where the browser
session and server already hold a complete accepted representation of that
scope. RFC 9111 describes the general safety rule for representation reuse:
the cache key must distinguish the request context, stale representations need
validation, and inappropriate reuse must be prevented. React Flow's current
performance guidance likewise recommends isolating selected state from the
complete node and edge arrays. These sources do not grant ArchHub authority;
they support the narrower implementation technique below. ArchHub's Cell
revision, subject, audience, lifecycle, scope, and interaction lease remain the
controlling proof.

The bounded mechanism may extend the existing disposable browser projection
binding so it retains one prior accepted projection per visited scope. It is a
private presentation materialization, not a Cell, Store, graph, persistence
layer, authorization result, or second source of truth. Reuse is admitted only
when all of the following are true:

1. session, subject, view, tenant, assurance, and destination scope match;
2. the server observed one uninterrupted revision lineage and every admitted
   intervening request was a scope-only transition through the existing
   `CAPABILITY_SCOPE` path;
3. the target projection was produced by the canonical interpreter and stored
   after its exact interaction lease was issued;
4. the new graph-held materialization resolves the same visible roots,
   relation roots, interface roots, and primary focus;
5. only immutable topology presentation is reused; authorization, audience,
   catalogue applicability, inspector state, controls, interactions, lease,
   revision, focus, and selection are rebuilt from current canonical Cells;
6. a graph edit, unknown revision, process restart, cache deletion, subject or
   assurance mismatch, malformed projection, topology mismatch, or changed
   primary focus discards the hint and runs the canonical path;
7. the canonical comparator remains executable and exact at the resulting
   revision; the optimisation cannot suppress a removal or mint authority.

Before implementation, RED courts must prove:

1. top -> nested -> top reuses only the exact previously accepted target-scope
   topology and still equals the generic canonical projection;
2. authorization, catalogue, inspector, controls, interaction bindings, and
   lease revision come from the new accepted revision, not the retained view;
3. foreign subject/session/view/tenant/assurance and malformed scope identity
   fail closed or fall back to canonical projection without exposing the hint;
4. any non-scope mutation or unexplained Store revision invalidates every
   retained scope projection before it can be read;
5. deleting all retained projections changes no graph semantics and the next
   transition reconstructs the complete canonical response;
6. selection/focus or topology mismatch takes the canonical path, including
   every DOM-required removal;
7. no route, public payload, Cell schema, Store field, graph role, persistence,
   lifecycle, authorization rule, or interaction contract changes;
8. the unchanged functional browser court and the <=100 ms mutation and <=150
   ms scope budgets pass without sleeps or relaxed thresholds.

Research references:

- https://www.rfc-editor.org/rfc/rfc9111.html
- https://reactflow.dev/learn/advanced-use/performance

Implementation evidence:

- The first two courts were RED because no private scope binding existed. The
  implementation now retains projections and exact root identities only under
  the existing browser-session binding. Browser session, graph view session,
  subject, tenant, assurance, target scope, and server-observed lineage are
  checked separately; confusing the two session identities was caught by the
  court and repaired without weakening either check.
- Three focused courts pass: exact top-to-nested-to-top reuse with canonical
  equality, foreign/unexplained-revision denial plus semantic disposal, and a
  parent revisit that cannot invoke the global visibility projector.
- A retained topology still re-reads the selected Properties relations from
  the current accepted snapshot. It no longer re-indexes all 631 parent
  property relations merely to redraw unchanged nodes.
- A nine-cycle isolated HTTP sample preserved 17 nodes, 136 relation-wires,
  and 46 ports. Entry measured 98.40 ms median. Parent return measured 145.09
  ms median, down from 206.41 ms before this mechanism. Individual parent
  samples ranged from 125.11 to 175.21 ms, so the unchanged 150 ms acceptance
  gate remains unreleased pending the real-browser court and tail-latency
  diagnosis. No release claim follows from the green median alone.
- Retained presentation is capped at eight scopes per browser session. Eviction
  removes the projection and its exact graph-identity tuple together and does
  not change the Cell Store revision. A focused court also proves that scope
  reuse cannot mutate the retained source projection through shared objects.
- The widened authority set passed 10 courts after the retained-scope mechanism
  was introduced. Subsequent RED-to-GREEN courts removed 63 stable node/port
  template renders and 14 stable catalogue-entry renders only when the exact
  retained target scope, selection, catalogue inputs, and library control match.
  Current authorization, catalogue contracts, inspector, controls, interaction
  bindings, lease, and revision are still rebuilt from the accepted Cells.
- The stable-descriptor and shallow immutable-copy repairs preserve canonical
  equality. The latest focused results are four scope safety courts passing and
  the stable-descriptor plus canonical comparator pair passing. The final
  widened scope-authority set also passes all 10 courts after the complete
  allocation repair.
- Three 31-cycle measurements after these repairs show that ordinary work is
  below the budget but runtime tail remains unstable. The latest sample measured
  entry at 89.48 ms median / 141.08 ms p95 and parent return at 106.84 ms median /
  151.49 ms p95 before catalogue descriptor reuse. Later samples under heavier
  client-production pressure varied between 151.49 and 170.88 ms parent p95.
  The release gate therefore remains RED.
- A collection-correlated 31-cycle trace identified the tail cause. All four
  parent requests above 150 ms coincided with two to five Python generation-1
  collections. The 26 requests with no collection had a maximum of 139.37 ms.
  Global garbage-collection disablement is rejected. Python 3.14.6 was also
  tested in an isolated non-system installation and did not remove the tail, so
  a runtime-version claim is not being used as a substitute for a product fix.

## 41. Request-local interaction allocation gate

The next diagnostic rules out a collector heuristic. `gc.get_count()` remained
at `(0, 0, 0)` immediately before parent requests that subsequently performed
between one and five generation-1 collections. It therefore provides no safe
pre-request signal. A settled-runtime sample after an explicit full collection
also remained red at 163.42 ms parent p95. Global collection disablement,
threshold tuning, collection on a timer, and version-only remediation are not
admissible repairs.

The current named-function profile shows that the retained parent projection
still performs 1,209 `read_relation` calls and verifies approximately 100 graph
interactions while issuing the new exact-revision lease. Those mechanisms are
authority, not optional work. The only admissible optimization is removal of
duplicate request-local object construction after the same immutable snapshot
and graph relation have already been verified in that request. It must not
retain an interaction across requests, revisions, subjects, sessions, or
leases, and it must not skip a budget check, protocol verification, release
check, action-input check, or any of the 14 interaction builders.

Before implementation, RED courts must prove:

1. all 14 graph interaction builders still execute and every visible control
   has exactly one graph interaction;
2. one exact request/snapshot may reuse a parsed interaction only after its
   relation budget and protocol have been verified, while a smaller budget,
   foreign Cell map, changed revision, changed protocol, or next request cannot;
3. the broker issues a new lease at the post-commit revision and performs the
   existing release/action-input/subject checks over the admitted batch;
4. no process-global GC setting, timer, persisted cache, public schema, route,
   Store, Cell, lifecycle, authorization rule, or cross-request state is added;
5. the scope result remains equal to the canonical comparator and source
   projection immutability remains green;
6. focused allocation evidence demonstrates fewer request-local parsed objects
   before the unchanged 31-cycle and real-browser budgets are rerun.

Implementation evidence:

- The new request-local court was RED because the exact protocol relation and
  interaction relation were each read twice at the same snapshot and budget.
  The existing cache now records the conservative verified budget with the
  parsed object and consults it before repeating the relation read.
- A same-or-larger budget at the exact revision and exact Cell-map identity may
  reuse the parsed object. A smaller budget still executes `read_relation` and
  retains its `MatchBudgetExceeded` behavior. A foreign Cell map, new revision,
  or next request has a different key or fresh context and cannot reuse it.
- The complete interaction-law file passes 19 courts. Four retained-scope safety
  courts and the final 10-court widened scope-authority set pass after the change.
- The unchanged 31-cycle HTTP measurement now passes the source-level p95 gate:
  entry is 89.18 ms median / 121.10 ms p95; parent return is 105.25 ms median /
  147.74 ms p95. One parent collection spike reached 162.24 ms, so the unchanged
  real-browser court remains required before editor release.
- Five source-level UI projection courts pass: dependency-tracked catalogue
  reuse, no complete-Store materialization, changed catalogue dependency denial,
  canonical authorization/catalogue delta replacement, and stable topology merge.
- The complete nine-scenario generated-runtime UI performance suite passes. A
  first grouped run had one 17.858 ms pan sample against the 16.7 ms frame gate;
  five unchanged repetitions measured 2.499-12.348 ms and the exact court then
  passed. The complete grouped suite was rerun unchanged and passed all nine
  scenarios. This resolves the synthetic-runtime gate, not the real-browser gate.

## 42. Direct-manipulation source acceptance audit

While the heavy real-browser slot remained reserved by client production, the
current generated-runtime artifact was exercised through the founder-specified
mechanics rather than a generic smoke test: directional and modifier marquee,
cursor-aware zoom and pan, graph-defined Properties tabs, parameter creation,
catalogue placement, grouping controls, relation hit targets, socket rewiring,
cardinality, and relation inspection.

The first run passed 17 scenarios and exposed one defective court assertion.
The relation-rewire scenario started with the visible source/target interfaces
`ui -> canvas`, submitted the graph-authorized source candidate at index zero,
and correctly reconciled the DOM to `brain -> canvas`. The old assertion compared
that post-transaction DOM with the pre-transaction projection and therefore
rewarded stale rendering. The probe now records the initial endpoint values;
the court separately proves the original pair, the exact requested candidate,
the changed source interface, and the unchanged target interface.

The strengthened individual court passes, and the complete focused
direct-manipulation set passes 18 scenarios. The JavaScript probe and both
real-browser verifier scripts pass syntax checks. These results prove the
generated source behavior only. Fresh Chrome evidence, screenshots, console
state, DOM timing, persistence/restart, and the unchanged 100/150 ms budgets
remain mandatory before editor release.

## 43. Visible composition interface transaction repair

The Workbench acceptance path exposed a graph-index defect after the locality
repair. A newly instantiated catalogue assembly contained all 14 graph-declared
interface Cells, but the top view's persisted visibility relation did not index
them. A later Workshop relation also registered an exact interface globally
without publishing that interface to views where its owner was already visible.
The graph data and wire endpoints were real; the view materialization was stale.

The repair keeps one Cell authority and changes no public API, schema, lifecycle,
authorization rule, or persistence system:

1. atomic top-scope instantiation now appends every interface declared on the
   new resource root to the same visibility transaction as the resource;
2. visibility admission distinguishes globally registered interfaces from
   composition-owned interfaces and verifies the latter through their explicit
   owner relation;
3. governed-work membership wires enter every eligible view relation index in
   the same commit that creates the wire;
4. Workshop-entry wires append only those newly created interfaces whose graph
   owner is already assigned to that view; and
5. legacy endpoint restore returns the exact interfaces it rewired and republishes
   only those interfaces to eligible views before strict restore verification.

The first restore rerun exposed an obsolete migration allowlist that rejected
the already-canonical interface and migration roles. The allowlist now names
those two roles explicitly. Subsequent diagnostics measured one missing governed
work relation and one missing Workshop source interface; each was repaired at
its originating transaction rather than by weakening the final verifier.

Evidence after the bounded repair:

- the strengthened Workbench court proves live interface-index completeness,
  real selectable socket endpoints, shutdown, restore, legacy endpoint upgrade,
  and wire preservation: 2 passed;
- eight unchanged visibility/scope authority courts pass, including partial
  relation/interface rejection, hidden-property denial, subject/revision drift,
  canonical scope equality, and bounded parent-scope reuse; and
- a new negative authority court proves that a structurally valid catalogue
  interface is still rejected when its owning composition is outside the visible
  graph scope; and
- all nine unchanged generated-runtime UI performance budgets pass.

This remains source and isolated-store evidence. The real-browser editor court
is still held by the explicit client-work machine-priority reservation and remains a
release requirement.

## 44. Real-browser visual acceptance strengthening

The editor court already operated the authoring mechanics, but its screenshot
files were evidence for later inspection rather than verdict inputs. That gap
would allow a functionally responsive but visibly defective editor to pass.
The unchanged application remains the subject; only the isolated browser court
and its declared check list are strengthened.

The court now also rejects:

1. overlap between the Node Library, canvas, and Properties rail;
2. visible graph sockets smaller than 24 by 24 CSS pixels;
3. clipped node titles in the accepted desktop viewport;
4. inspector tabs without one active/focusable tab, one matching panel,
   reciprocal `aria-controls` / `aria-labelledby`, or matching hidden state;
   and
5. a live marquee rectangle whose four viewport edges differ from the actual
   pointer drag rectangle by more than three CSS pixels.

The tab contract follows the W3C ARIA Authoring Practices tabs pattern:
https://www.w3.org/WAI/ARIA/apg/patterns/tabs/ . The target-size floor follows
WCAG 2.2 Success Criterion 2.5.8, and the live drag measurement follows the
current W3C Pointer Events model rather than assuming mouse-event ordering:
https://www.w3.org/TR/pointerevents/ . These standards define measurable
interaction and accessibility constraints; they do not choose ArchHub's visual
style.

Source evidence before browser execution: the JavaScript runner passes syntax
validation, the Python wrapper/tests compile, eight non-browser court checks
pass, and `git diff --check` is clean. This does not make the visual gate green.
The three new checks become evidence only when the unchanged isolated Chrome
court runs, emits its measured geometry, saves all three admitted screenshots,
and those screenshots are separately inspected for visual hierarchy and finish.
