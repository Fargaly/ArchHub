---
id: AgDR-0060
title: Canonical Node Language authority convergence
timestamp: 2026-07-20
agent: Codex
session: baboom-node-native-steward
status: proposed
category: architecture
projects: [archhub, baboom]
supersedes: [AgDR-0057]
superseded_by: null
---

## Context

The active authority index declares `10.PRODUCT/13.NODE-LANGUAGE/SPEC.md` as
the normative Universal Cell product target. The copied
`10.PRODUCT/12.PRODUCTION/node_runtime/` path is Git-ignored because running
processes still hold it, but it has accumulated source that differs from the
declared authority. In particular, it contains an unpromoted BABOOM context
and presentation experiment that the declared authority does not own.

AgDR-0057 said that the copied runtime would become the only forward-edit
source after its gates. That contradicts the active authority index and the
workspace contract: a live copy, legacy application surface, browser
projection, or adapter cannot define a second product truth. Treating the
copied runtime as source would make a node-native claim unverifiable.

The legacy MCP servers have the same problem. They derive tool surfaces from
local connector registries and dispatch tables. They are migration evidence,
not the semantic authority for BABOOM, models, devices, meetings, Notion, or
host actions.

## Decision

1. `10.PRODUCT/13.NODE-LANGUAGE/SPEC.md` and its declared protocols are the
   only forward-edit authority for Universal Cell semantics. This decision
   supersedes the forward-edit-source clause in AgDR-0057.
2. `12.PRODUCTION/node_runtime/` is a live compatibility copy only. It may be
   inspected, shadow-launched, and audited while a holder exists, but it MUST
   NOT receive new product semantics, be cited as a delivered feature, or be
   used to resolve a source conflict.
3. Every candidate change found only in the copied runtime is an explicit
   migration candidate. It must be reconstructed in the canonical authority,
   with red courts first, provenance to the candidate, and a decision on
   whether it preserves or removes existing protocol behavior. A bulk copy is
   forbidden.
4. BABOOM is node-native only when its persisted identity, Work, task,
   conversation, presence, device projection, approval, capability request,
   receipt, and visual state are compositions of Cells governed by released
   protocols. A process-local capability handle is permitted only at the
   physical host boundary; it is never persisted or treated as semantic
   authority.
5. An MCP transport, CLI, model provider, desktop client, meeting adapter,
   Notion adapter, or browser client may expose a projection of released graph
   capability. It must not own a static semantic tool registry, independent
   approval state, model-selection authority, task queue, or authoritative
   activity record. Legacy surfaces remain read/migration evidence until
   replaced by a graph-derived adapter that passes its courts.
6. A graph-native broker must bind each capability advertisement and invocation
   to released graph roots for the request, authority, device/session,
   data-class policy, approval, bounded grant, outcome, and revocation. The
   trusted host broker holds only the non-serializable handle and a narrow
   executor. It cannot invent a semantic action absent from those roots.
7. The runtime-drain gate must remain red while either live holders or source
   drift exists. Green requires no copied-runtime source that is missing from
   or differs from the canonical authority, plus a separately approved,
   non-interrupting live handoff.

## Consequences

- No BABOOM v2/v3/v4 context, persona, movement, cross-device, broker, or
  meeting claim may be called node-native, deployed, or complete merely
  because code exists under the ignored runtime copy or a tool directory.
- The next implementation work is a sequence of small canonical migrations:
  first the graph-defined broker lifecycle and courts, then BABOOM context and
  presence projections, then adapter-specific capabilities. Each migration
  must retain root identity and record what it replaces.
- The current running sessions remain untouched. This decision does not
  restart, kill, move, or reload a process, and does not authorize archiving
  the copied runtime.
- Old static MCP and connector registries will be treated as legacy adapters.
  They cannot be widened to simulate universality while the graph-native
  broker is absent.

## Required Courts

Before this decision can be executed:

1. A source-authority court fails when ignored copied-runtime source differs
   from the canonical Node Language authority and identifies each candidate.
2. A broker court proves deny-by-default behaviour for absent or expired
   authority, missing approval, wrong device/session, forbidden data class,
   exhausted use budget, failed handler, and revoked grant.
3. A graph conformance court proves every persisted broker lifecycle fact is
   represented by Cell compositions and that the process-local handle cannot
   be serialized, forged, or used as a hidden registry key.
4. Adapter courts prove MCP lifecycle conformance and that an adapter derives
   its visible capability surface from a released graph snapshot rather than a
   static product dispatch table.
5. A live handoff court proves that no active session is interrupted and the
   runtime-drain gate turns green only after both source drift and process
   holders are resolved.

## Founder Acceptance Required

This record is intentionally `proposed`. It changes source authority and
supersedes an executed record, so it must receive explicit founder acceptance
before status becomes `executed` or canonical product code is changed under
this decision.
