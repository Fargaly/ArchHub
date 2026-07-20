---
id: AgDR-0056
title: Capability-specific cloud readiness contract for the node-native resource graph
timestamp: 2026-07-13
agent: Codex
session: node-native-unification
status: executed
category: cloud
projects: [archhub]
supersedes: null
superseded_by: null
---

## Context

`GET /healthz` proves only that the FastAPI process can answer. It cannot prove
that SQLite is queryable, the persistent volume is mounted, billing products
are configured, transactional email is configured, or the public website is
reachable. Treating that single response as evidence for all external resource
nodes would create false-green governance.

The founder has directed that databases, storage, billing, email, website,
governance, Brain, and application runtime be consumed into one node-native
system through explicit ports, wires, policies, and evidence.

## Decision

Add `GET /readyz`, a read-only capability report. The endpoint returns one
independent record per capability:

- `database`: opens the configured SQLite database and executes `SELECT 1`.
- `persistent_storage`: verifies the configured data directory exists and is
  the parent authority for the database and replica root. It does not write a
  test file.
- `billing`: reports provider and whether the required product identifiers are
  configured. It never calls checkout or creates a payment object.
- `email`: reports whether production delivery is configured. It never sends.
- `website_publication`: reports the canonical configured public origin only;
  external HTTP reachability remains the resource graph's live probe.

The route always returns HTTP 200 when a report can be constructed. Overall
readiness and every capability's `ok` value are explicit fields; consumers must
not infer readiness from the HTTP status alone.

## Security And Data Rules

- No secret values, tokens, user rows, counts, file listings, or private
  absolute paths are returned.
- Database evidence is a bounded `SELECT 1`, never a schema or data export.
- Storage evidence performs no mutation.
- Errors are reduced to stable non-sensitive reason codes.
- The endpoint is evidence only. All external writes remain authenticated,
  founder/policy-gated, frozen, and audited by their existing routes and the
  node-native effect layer.

## Consequences

- Resource adapters can bind each capability to its own evidence node.
- A healthy process with a broken database or missing provider remains visibly
  partial/red.
- SQLite remains the current payload host; the graph owns its identity,
  policy, ports, lineage, and control. A later Postgres lift keeps this
  readiness schema stable.
