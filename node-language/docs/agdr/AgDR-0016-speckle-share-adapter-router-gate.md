---
id: AgDR-0016
timestamp: 2026-05-21T00:00:00Z
agent: claude-code (Sonnet)
session: m1-shipping · founder /loop till finalize
trigger: founder decisions 2026-05-21 on DiskTransport vs ServerTransport + SHARE nodes + ADAPTER nodes + 6-op Speckle host master drop
status: executed
founder-signoff: 2026-05-25 — bulk-flip per D4·A pick on docs/prototypes/four-decisions-2026-05-25.html (shipped weeks ago, status drift)
category: architecture
projects: [archhub]
supersedes:
  - AgDR-0012 §"Wire substrate — Speckle" lines 218-233 — refines the
    transport defaulting + opt-in mechanism + adds SHARE node trigger.
  - AgDR-0012 §"What ships" line on Speckle host master — drops the
    6-op REST host connector entirely (covered by wire layer + 3
    SHARE nodes + adapter category).
---

# Speckle: DiskTransport default · Server opt-in via SHARE nodes · ADAPTER category for cross-host native mapping · Router gate wired

> In the context of founder review 2026-05-21 ("we host our own
> Speckle server and use it for data connections" + "the server can be
> a localhost also and allows for remote connection if needed" + "go
> with disk transport... create nodes that when the user use them
> inside their workflow it opens a local host server so the
> worksharing is optional"), I decided to **lock DiskTransport as the
> default wire substrate** with **Speckle Server as opt-in lazy-started
> via 3 typed SHARE nodes** (`share.server` / `share.publish` /
> `share.subscribe`), **drop the 6-op Speckle host master** (covered
> by the wire + SHARE nodes), and **add an ADAPTER category for
> cross-host native-type mapping** (founder's "Max mass → Revit family
> with parameters" example). Also: **wire the LIBRARY-FIRST gate**
> (AgDR-0013 Layer 3) into `llm_router._complete_once` so the
> enforcement built earlier this session actually runs. Accepting:
> server-pushing requires Docker installed (graceful "docker not
> installed" prompt when absent); a localhost Speckle Server costs ~30-90s
> cold-start on first SHARE.server fire; adapter coverage starts with
> 3 nodes (cad→wall, max→family, generic→directshape) and grows per
> demand.

## Context

AgDR-0012 §"Wire substrate — Speckle" locked:
- "Default transport: `DiskTransport` at `.speckle/<project>/` (project-
  local, copy/paste-portable, scoped). `SQLiteTransport` per-user
  fallback."
- "Memory transport for ephemeral in-session wires."
- "ServerTransport opt-in for collaboration / cloud sync. Cloud
  Speckle (`app.speckle.systems`) or self-hosted."

Founder review surfaced three refinements + corrections:

1. **Do we need a Speckle HOST connector if the wire layer is Speckle?**
   Original AgDR-0012 §"What ships" listed Speckle as a host master
   with `speckle.send_to_stream` / `speckle.receive_from_stream` /
   `speckle.list_streams` / `speckle.list_branches` /
   `speckle.list_commits` / `speckle.create_stream` — six REST ops.
   **Founder: redundant if Speckle is the wire.** The wire layer
   already does send/receive; explicit "send to Speckle" is noise.

2. **Server vs disk vs both?**
   Founder confirmed: localhost Speckle Server can also accept remote
   connections (bind 0.0.0.0 + port-forward / Tailscale / etc.). Same
   instance = both modes by network config. So one URL handles
   solo-local + team-LAN + remote-cloud.
   **Decision (mine, founder-confirmed): DiskTransport stays the
   default substrate (zero-infra, 1ms reads, offline-safe).
   ServerTransport opt-in by user wiring a SHARE node.**

3. **Wires must map data as per native categories.**
   Founder's litmus: 3ds Max mass → Revit Family with parameters.
   AgDR-0012 §"What collapses" mentioned `geometry.cad_to_revit`
   adapter op but never built. Founder demand: **typed adapter nodes
   per source/target pair**, configurable target category +
   parameters + family bindings. Receive-side host connector reads
   annotations + creates native.

## Options Considered

### Fork 1 — Server transport default vs opt-in

| Option | Picked | Why |
|---|---|---|
| **Server-first** — every wire goes through localhost Speckle Server by default | no | Solo user must deploy Docker stack day one · per-wire 30-200ms latency vs 1ms disk · offline = broken · cache-miss cliff on docker restart |
| **Disk-first, server opt-in** — DiskTransport default, ServerTransport activated by placing a SHARE node | **YES** | Zero-infra solo experience · fast cooks · offline works · server arrives when team needs it · URL is config (localhost · LAN · cloud · self-host all same code path) |
| Hybrid auto-detect (server if reachable, fall back to disk) | no | Two modes with implicit behaviour switch = surprising · users can't reason about latency |

**Pick: Disk-first.** Implemented in `app/speckle_wire.py` (M1.a).

### Fork 2 — 6-op Speckle host master

| Option | Picked | Why |
|---|---|---|
| Keep `speckle.send_to_stream` + 5 sibling REST ops as one of the 16 host masters | no | Redundant — every wire IS Speckle send/receive already · explicit "send to Speckle" becomes noise · pollutes palette |
| **Drop the host master · 3 typed SHARE nodes cover all explicit interaction** (`share.server` · `share.publish` · `share.subscribe`) | **YES** | Wire layer = implicit transport · SHARE nodes = explicit collaboration · clear UX layering |
| Keep but rename to "Speckle Remote" with reduced op surface | no | Half-measure · still leaks Speckle implementation into the palette |

**Pick: Drop.** Connector module stays in `app/connectors/speckle_connector.py` for back-compat with saved graphs that reference it; not added to the per-host master list.

### Fork 3 — Cross-host native mapping mechanism

| Option | Picked | Why |
|---|---|---|
| Generic `glue.script` Python adapter per pair | no (last resort) | Too low-level · user types Python for every mapping |
| Speckle's built-in receive-side conversion (DirectShape fallback when no specific mapping) | partial | Works but lossy — flat geometry, no parameters · founder explicitly wants native FamilyInstance with parameters |
| **Typed ADAPTER nodes per source/target pair** annotating the Base with `revit_*` metadata; receive-side reads annotations to drive native creation | **YES** | Typed wire-in by user · AI Composer can search/place via `library.search` · Speckle Revit connector reads annotations + creates native · DirectShape stays as the generic fallback adapter |

**Pick: Typed adapter nodes.** First three shipped:
- `adapter.cad_to_revit_wall` — Polyline → Wall (level / wall_type / height / top_offset / structural)
- `adapter.to_revit_directshape` — Generic fallback under any built-in category
- `adapter.max_to_revit_family` — Mass → FamilyInstance (target_category / family_name / family_template / parameter map)

Future adapters (next 6-8 weeks): `adapter.rhino_to_revit_beam`, `adapter.rhino_to_revit_directshape`, `adapter.cad_to_revit_detail_line`, `adapter.excel_to_revit_params`.

### Fork 4 — Router LIBRARY-FIRST gate placement

| Option | Picked | Why |
|---|---|---|
| Insert at provider client (Anthropic / OpenAI / etc.) per-client | no | Logic duplicated × 8 providers · drift risk |
| **Insert at `llm_router._complete_once` between tool-call extraction and `ToolEngine.invoke`** | **YES** | Single insertion point · model-agnostic · all providers covered · graceful degrade if gate module missing |
| Insert at `ToolEngine.invoke` itself | no | Same as router but couples gate to tool engine (gate is a router concern; tool engine should stay free of LIBRARY-FIRST domain logic) |

**Pick: Router-level insertion.** Implemented `llm_router.py:1257-1280` (state construction) + `:1387-1424` (gate check + denial path).

## Decision

### Wire substrate (refines AgDR-0012 §"Wire substrate — Speckle")

```
DEFAULT: DiskTransport (SQLiteTransport at <project>/Objects.db)
  • Local-only · always available · offline-safe
  • Per-project isolation via use_default_cache=False
  • Foundation: `app/speckle_wire.py.SpeckleWire`

OPT-IN: ServerTransport (lazy-started via SHARE nodes)
  • User places `share.server` to ensure localhost server up
  • User places `share.publish` to push a wire's value
  • User places `share.subscribe` to pull from a URL (local OR remote)
  • Server URL is config (localhost · LAN · self-host · cloud — all
    identical code path)
```

### Server lifecycle

```
Docker required.
Compose template bundled at `docker-resources/speckle-compose.yml`
(postgres + redis + minio + speckle-server).
First-run: docker compose -f <user-dir>/docker-compose.yml up -d.
Health poll /api/health until 200 OK (up to 90s cold-start).
Subsequent runs: silent fast-path (already-up check ~50ms).
Errors typed: docker_missing · compose_failed · compose_timeout ·
              server_unhealthy.
```

### SHARE category (3 typed grammar primitives)

```
share.server     no inputs                    → server_url · status
share.publish    value: Base                  → model_url · status
share.subscribe  source_url: string           → value · status
```

Wiring example (founder's flow):
```
[some upstream node]
    ↓ value
[share.server]                         ← lazy-starts Docker stack
    ↓ server_url
[share.publish] (config: model_name="myProject")
                                        ← input value comes from upstream
    ↓ model_url
[text/output]                          ← capture URL for sharing
```

### ADAPTER category (3 initial typed nodes)

```
adapter.cad_to_revit_wall      Polyline → Wall (level/type/height/top-offset/structural)
adapter.to_revit_directshape   Any Base → DirectShape (built-in category)
adapter.max_to_revit_family    Mass → FamilyInstance (category/family/template/params)
```

Mechanism: each adapter ENRICHES the Base with `revit_*` annotations
(`revit_target_category`, `revit_family_name`, `revit_parameters`, etc.).
Receive-side Speckle Revit connector reads annotations + creates native.

### Router gate wiring

Insertion at `llm_router.py:1257-1280` (state) + `:1387-1424` (check):

```python
# Before every ToolEngine.invoke for library_* tools:
if _lib_gate is not None and _lib_gate.is_library_tool(inv.tool_name):
    decision = _lib_gate.check(inv.tool_name, inv.arguments, _lib_turn_state)
    if not decision.allow:
        inv.result = {
            "status": "error",
            "error": decision.reason,
            "retry_hint": decision.retry_hint,
            "code": "library_first_blocked",
        }
        continue  # skip ToolEngine.invoke
# else fall through to ToolEngine.invoke normally
```

Graceful degrade: if `library_gate` module import fails, `_lib_gate=None`
and all calls fall through to ToolEngine.invoke (no enforcement, but
chat turn still works). Honest fallback beats blocking the user.

## Consequences

### What ships (this session — already done)

- `app/speckle_wire.py` (M1.a) — SpeckleWire substrate, 25 tests
- `app/speckle_server.py` (M1.5) — lifecycle, 15 tests
- `app/workflows/nodes/share.py` — 3 SHARE engines + grammar primitives, 21 tests
- `app/workflows/nodes/adapter.py` — 3 ADAPTER engines + grammar primitives, 18 tests
- `app/llm_router.py` LIBRARY-FIRST gate insertion + 7 tests
- specklepy 3.2.6 added as dep
- Grammar primitive count: 67 → 73 (3 SHARE + 3 ADAPTER added)
- `docs/ROADMAP.md` updated with shipped slices

### What collapses

- 6-op Speckle host master removed from the per-host master roster.
  Connector module `app/connectors/speckle_connector.py` stays for
  back-compat; not added to palette in M2+.
- `geometry.cad_to_revit` adapter op (AgDR-0012 §"What collapses"
  placeholder) replaced by `adapter.cad_to_revit_wall` (now real).

### What's reinforced

- DiskTransport-first matches the AEC-desktop-tool category (Houdini,
  Grasshopper, Dynamo all stay local) — not the SaaS-graph category
  (n8n cloud).
- Server opt-in keeps zero-infra solo onboarding intact.
- LIBRARY-FIRST gate is enforced at runtime, not just documented.
- Adapter category is the typed grammar primitive answering the
  "cross-host native mapping" question — extensible per source/target pair.

### Tests

| Module | Tests | What it proves |
|---|---|---|
| `test_speckle_wire.py` | 25 | Round-trip · hash determinism · project isolation · foreign Base passthrough |
| `test_speckle_server.py` | 15 | Lifecycle API · error paths · idempotency · Docker mocking |
| `test_share_nodes.py` | 21 | 3 SHARE executors · fast-path / start / error · server-push fallback |
| `test_adapter_nodes.py` | 18 | Annotation correctness · list-input handling · defaults · category |
| `test_router_library_gate.py` | 7 | Gate behavior · router import · source-shape guard |
| **Total this AgDR** | **86** | |

Suite: 1664/1664 green · zero regression.

### Risks

- Docker requirement on the SHARE.server path. Mitigation: typed
  `docker_missing` error + clear prompt + DiskTransport path still
  works without Docker.
- specklepy version drift (3.2.6 today; Speckle bumps frequently).
  Mitigation: pin in requirements; cover with smoke tests; the
  JSON-wrap coerce is version-agnostic.
- Server-push from `share.publish` needs auth tokens for non-local
  servers. M1.5 attempts anonymously + falls back gracefully (server
  push failure does NOT block local DiskTransport write — that's the
  primary path).
- Adapter coverage gap: only 3 pairs today. Mitigation: pattern
  matches; new adapters follow the same template; AI Composer can
  surface "no adapter exists yet for this pair" + fall back to
  `adapter.to_revit_directshape`.

## Implementation order (carried over to ROADMAP)

1. ✓ M1.a · Speckle wire (done this session)
2. ✓ M1.5 · SHARE nodes + server lifecycle (done this session)
3. ✓ Adapter category + 3 first nodes (done this session)
4. ✓ Router gate wired (done this session)
5. ☐ M2 · Bundle Speckle Revit connector (or IPC) + wire adapter annotations to native creation
6. ☐ M1.a · ReactFlow scaffold (parallel)
7. ☐ M3 · Composer panel
8. ☐ M4 · `ai.plan` as canvas node
9. ☐ M5 · End-to-end litmus (Max mass → Revit family · CAD wall → Revit wall)
10. ☐ M6 · Per-graph `auto_publish` setting + Speckle Automate webhooks

## Open forks for founder

1. **Flip AgDR-0013 / 0014 / 0015 to `executed`** (or instruct revert).
   Code rests on them as `proposed`. This AgDR-0016 also lands as
   `proposed` pending your sign-off.
2. **Speckle Server auth model for `share.publish`.** Currently
   attempts anonymous push + falls back gracefully on auth failure.
   Want to add an API-token-via-secrets-store path now, or wait for
   M6 collaboration polish?
3. **Adapter coverage priority.** Next 3 adapters to ship:
   `adapter.rhino_to_revit_beam`, `adapter.cad_to_revit_detail_line`,
   `adapter.excel_to_revit_params` — confirm or reorder?

## Artifacts

- This AgDR.
- Shipped code: `app/speckle_wire.py`, `app/speckle_server.py`,
  `app/workflows/nodes/share.py`, `app/workflows/nodes/adapter.py`,
  `app/llm_router.py` (gate insertion).
- Bundled: `docker-resources/speckle-compose.yml` (compose template).
- ROADMAP entry for M1.a / M1.5 / ADAPTER / router-gate-wired.
