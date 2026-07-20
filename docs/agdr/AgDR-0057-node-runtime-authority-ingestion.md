---
id: AgDR-0057
title: Ingest the universal node runtime into the tracked product authority
timestamp: 2026-07-13
agent: Codex
session: node-native-unification
status: executed
category: architecture
projects: [archhub]
supersedes: null
superseded_by: null
---

## Context

The live schema-32 node-native application, its universal one-table kernel,
tests, and Windows packaging source currently live in
`10.PRODUCT/13.NODE-LANGUAGE`. That directory is outside every Git repository.
Meanwhile the public ArchHub authority is the tracked repository at
`10.PRODUCT/12.PRODUCTION`, whose own node-grammar documentation names the
external kernel as the engine of record.

That is not a shippable authority arrangement. A live and packaged engine that
is not versioned with the product cannot be reviewed, reproduced, protected by
CI, or coordinated with the existing application, Brain, Cloud, website, and
installer as one product.

## Decision

Create `node_runtime/` inside the tracked public repository and ingest only the
current runtime authority:

- `nodelang/` universal kernel, laws, domains, application, website, and hosts;
- `tests_replica/` and `tests_domains/` forcing courts;
- `packaging/windows/` reproducible desktop bundle and installer source;
- `public_site/` node-native website export source;
- `SPEC.md` as the runtime contract.

Prototype scripts, generated ledgers, caches, rendered HTML, and old parallel
engines are not promoted into the authority subtree.

`node_runtime/` becomes the only forward-edit source after these gates pass:

1. source files are byte-identical to the schema-32 source being promoted;
2. the full application, persistence, desktop, kernel, and packaging courts run
   from `12.PRODUCTION/node_runtime`;
3. the normal live endpoint is launched from the tracked subtree and preserves
   the same persistent graph through the versioned migration path;
4. a package built from the tracked subtree contains the matching schema;
5. no T1/T2/T3 data or machine-bound path enters the public subtree.

The external `13.NODE-LANGUAGE` directory remains untouched as rollback
evidence during the transition. It is not edited after parity is established
and is not deleted until the tracked runtime, remaining domain integrations,
and release courts prove that no required authority still depends on it.

## Consequences

- The node-native application becomes part of the actual product history and
  CI boundary instead of an adjacent prototype.
- Existing dirty work in `12.PRODUCTION` is not overwritten; ingestion uses a
  new subtree and works with the current branch.
- The legacy application remains available only while its unconsumed domains
  and connectors are migrated behind explicit node ports and relations.
- Temporary duplication exists only for rollback during the authority move;
  forward work must occur in `node_runtime/` after the gates pass.

## Execution evidence

Completed on 2026-07-13:

- 99 selected authority files were ingested into `node_runtime/` with no cache,
  binary, build-output, or large-file leakage into the public tree.
- The live application is launched from
  `12.PRODUCTION/node_runtime/run_application_server.py` and serves schema
  `2026.07.13.33` at `http://127.0.0.1:8482/` with a valid graph.
- The application registry passes the exact `Cloud HTTP Runtime` session-node
  identifier into the Cloud adapter. A restart diff proved one unchanged Cloud
  session and only five new append-only `op:set` history nodes for listener
  state; no runtime structure was duplicated.
- The tracked authority court passed 125 tests in 445.35 seconds across the
  application, persistence, desktop runtime, packaging, engine, and all domain
  suites.
- The `.32 -> .33` migration preserves founder-visible state, replaces the
  retired CDE scope, and appends a `schema_archive` history node containing the
  old snapshot SHA-256 and node/history counts. The byte-identical rollback
  remains available and its hash matches the archive node.
- The private CDE overlay and Brain active-work ledger now contain 282 Grand
  Map leaves with 1,075 route/gate references to
  `10.PRODUCT/12.PRODUCTION/node_runtime`; no retired or missing path remains.
- The tracked Windows build passed its source-portability gate and produced
  `ArchHub-Setup-0.1.0-x64.exe` with embedded schema `2026.07.13.33`, size
  141,377,502 bytes, and SHA-256
  `918df8c2f630be2150f011f5a89ac94b8076ea38f5dc40d9c064822ddfc30e2b`.

This decision records successful source-authority ingestion only. The installer
is still unsigned, rendered founder acceptance is still pending, and external
production adapters, remaining Grand Map leaves, security/recovery/multi-user
courts, signing, deployment, and final release criteria remain open work.

## 2026-07-20 Source Re-admission

The current Universal runtime source set was re-admitted into `node_runtime/`:
334 source artifacts across the runtime, replica/domain courts, packaging, and
public site matched the external rollback tree byte-for-byte after admission.
Eleven tracked-runtime-only courts and `run_application_server.py` were
preserved. BABOOM's desktop, relay, device-custody, and encrypted-brief client
imports now resolve only from `node_runtime/`; 89 companion authority, relay,
motion, presence, and UI courts passed against that source.

This is source parity, not a live rollover. The existing external runtime owner
was not stopped, restarted, or replaced. A controlled handoff plus runtime,
rendered desktop, and device verification remains required before the tracked
runtime can be described as the live owner.

## 2026-07-20 BABOOM Boundary Hardening

BABOOM source now accepts no local semantic mirror: legacy Brain Work and
Workshop reads, the department YAML queue, Steward JSON projection, event
journal, direct voice-model request, and persisted model-result artifact have
been removed from the active paths. Voice questions create exact Universal Work
before a model delegation is prepared; the one-use approval and receipt remain
graph-held. `176` BABOOM courts passed, including static authority-boundary
coverage. This is still source evidence only. The live graph owner and BABOOM
companion were not restarted because a host session remains active and the
runtime is unhealthy.

The source companion now exposes `BABOOM.cmd rollout-evidence`, a read-only
gate that reports the session, Brain, graph-lens, and Device Custody conditions
needed before founder approval. The gate exits non-zero when any condition is
unmet and performs no lifecycle action.

The source runtime also exposes the founder-only
`GET /api/universal/baboom-capabilities` Cell lens. It projects only released
BABOOM model adapters, connector adapters, and governed routes from one graph
revision. BABOOM no longer imports the legacy workflow/tool/connector registry
or reports its counts as capability authority; the retired department-cycle
provider is absent from the released BABOOM connector mapping. The graph-released
model `location` and connector `operation`, rather than a provider-name catalog,
select the bounded local host adapter; unknown bindings fail closed.

The execution machine contract now accepts the released `provider_root` Cell
identity for Cognition, model delegation, and connector delegation. The
Universal runtime verifies membership by reading the model or connector protocol
registry relation; `UniversalApplicationRegistry` no longer retains a
provider-name-to-root map. Label-only requests are denied before delegation.

## 2026-07-20 Active BABOOM Surface Purity

The active BABOOM desktop sensor, headless Steward, and rule engine no longer
read the device-local Codex activity/session journal. The rule engine also no
longer turns local Brain, repository, foreground, idle, or supervisor readings
into an active message. Its proactive Work, Workshop, Attention, capability,
runtime-presence, device, and foreground-activity reports derive from the
bounded, same-revision Universal graph briefing. A compact UI arrow
may expose only the matching graph suggestion; its Work claim still requires
the existing founder confirmation and bound Agent Session.

The local session reader remains only in the read-only rollout safety preflight
that protects an active physical host from restart or rollover. It is not a
BABOOM semantic authority and cannot create a report, suggestion, Work, claim,
or effect. Focused UI, Steward, rule, and authority-boundary courts passed;
the running desktop and graph owner were not reloaded.

The runtime-visible graph lens remains `app:baboom-context:v1`; the current
runtime constant and replica courts still assert that value. Runtime presence
is projected from graph-held presence leases plus the local runtime's bounded
current-device proof. Foreground-app observations are admitted only as
content-free cognition capsules; no served BABOOM context histogram is
versioned in this repo yet. A v2/v3 context-lens promotion remains open until
the route, graph projection, and courts change together. The running desktop
and runtime were not reloaded.
