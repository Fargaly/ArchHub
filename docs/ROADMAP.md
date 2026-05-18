# ArchHub Roadmap — single source of truth

> **This is the one roadmap — and per founder mandate (2026-05-18) it
> stays the only one.** Every plan, backlog item and milestone lives
> here; no parallel roadmap or plan file may be created. It is also the
> machine-readable seed for the autonomous loop
> (`agents/roadmap_source.py`). Each `- [ ]` line is an OPEN backlog
> item the dispatcher picks up; `- [x]` is shipped.
> Tag priority `#P0` / `#P1` / `#P2`. Department hint in parentheses
> routes the item — `eng`, `qa`, `docs`, `ops`, `rnd`.
>
> When an item ships, MOVE it to "Done — last 7 days"; the loop records
> its hash in `agents/state/completed_roadmap_ids.txt` on the next tick.
>
> Consolidated 2026-05-18 from 6 scattered docs. The product-version
> history (the old root `ROADMAP.md`) is folded into "Shipped" below.
> The four design/architecture memos are NOT roadmaps — they are listed
> under "Design references" and kept for rationale only.

## Shipped — milestone arc

| Milestone | What |
|---|---|
| v0.25–v0.27 | Connector self-heal · Outlook COM · Studio 3-pane shell · brand v0.1 · Revit multi-session broker |
| v0.28–v0.33 | Add-Host wizard · workflow node canvas · marketplace · ⌘K palette · parameters sidebar |
| v0.34.x | Voice · telemetry KPIs · reasoning surfacing · multi-host polish (15 point releases) |
| graph-first pivot | WorkspaceShell replaces the page-based shell; Session = Graph; canvas is the primary surface (`studio-lm.jsx`) |
| connectors | 16 host/office/broker connectors on a uniform base contract |
| cloud backend | companies / multi-seat · admin dashboard · welcome email · per-company quota · invite email-match |
| release artifacts | Windows installer · macOS `.icns` + `.dmg` · Linux AppImage |
| repo hygiene | domain canonicalized to archhub.io · roadmap docs consolidated · 1323 tests green |

Per-version detail: `CHANGELOG.md` and git history.

## NEXT 7 DAYS

- [ ] #P0 Push the repo to GitHub — CI (AppImage / macOS / test / CodeQL / Dependabot) is unverified and inert until the default branch is pushed (ops)
- [ ] #P0 Graph-first canvas "Run" is broken for the curated node library — the 80 `LM_LIBRARY` node types (`LM_NODE_TEMPLATES`, `studio-lm.jsx:1846`) carry NO engine `type` field; `bridge.run_workflow`/`run_node` pass the raw canvas graph to `WorkflowRunner`, which dispatches on `node.type` → empty → `registry` miss → `"no executor for ''"` (`runner.py:475`). A user can drag, wire and Run any curated library node and it errors. (Connector-op nodes carry `op_id`, custom nodes carry `custom_type`, conversation chat uses a separate path — those 3 DO work; the 80-node curated palette does not.) Root fix — bind the canvas library to the engine registry: either generate `LM_LIBRARY` from the node registry, or map every `LM_NODE_TEMPLATES` id → engine `type`. Verify a library-node graph cooks end-to-end. Same drift class as the connector/tool_engine parallel registries (eng)
- [ ] #P1 archhub.io go-live — DNS records, Fly deploy, Resend domain verification, `PUBLIC_URL` secret (ops)
- [x] #P1 `tool_policies` override store audited (2026-05-18) — root fix: `tests/conftest.py` now isolates `secrets_store` suite-wide (autouse fixture), so no test can pollute the real settings store ever; verified 1156 tests pass. The existing all-"allow" overrides were NOT test-created (no test bulk-sets "allow"; `test_ai_behaviour` was already isolated) — they are founder/app Settings state. Resetting them is the founder's call (Settings → AI Behaviour → Reset) (qa)
- [x] #P2 SessionCard host pills + last-message preview — `get_sessions` now emits `host` / `last` / `node_count` / `messages` via `session_io.list_sessions_rich`; the JSX card already had the render slots; shipped 2026-05-18 (eng)
- [ ] #P2 Home filter chip `scheduled` is dead — no session-schedule model exists; remove the chip. (The `workflows` chip now works — `get_sessions` emits `node_count`.) (eng)

## NEXT 30 DAYS

- [ ] #P2 `/dashboard` authed-roster test — current tests only assert the page renders, not the authenticated company/team render (qa)
- [ ] #P2 First-run profile capture — zero automated coverage on the `get_profile` / `save_profile` bridge slots + `FirstRunProfile` (qa)
- [ ] #P1 Cloud Pro / Studio paid tiers — auth + Stripe phase per `docs/CLOUD_REVIVAL_PLAN.md` (eng)
- [ ] #P2 Deploy the 3ds Max host add-in — `payload/max/` does not exist; the connector is code-complete but `probe()` honestly reports `missing` until the add-in ships. Build + deploy from `payload/sources/max_mcp/` (ops)
- [ ] #P2 Outlook connector op gap — it ships 8 named ops, but `ai_behaviour.py` + `outlook_runner` were built for ~15 (`set_categories`, `set_categories_by_filter`, `auto_categorize_by_*`, `search_threads`, `list_folders`, `move_to_folder`, `flag_for_followup`, ...). The `execute_python` escape hatch was wired 2026-05-18; wire the named category/folder ops too (eng)
- [ ] #P2 Connector escape-hatch parity — surface ops the runners already support but the connectors don't expose: `revit.execute_csharp` + `revit.screenshot`, `autocad.execute_csharp`, `max.execute_python`, `rhino.screenshot`, `{illustrator,indesign,photoshop}.execute_jsx`. Template: `outlook.execute_python` (commit ae79db5) (eng)
- [ ] #P2 Tool-registry unification — `tool_engine.TOOLS` (hand list) and `connectors.base` ops are two parallel registries, both emitted to the LLM; 6 hosts get duplicate tools. Audit 2026-05-18 confirmed the surface is functionally honest (no dead routes) but drifted. After escape-hatch parity migrates the unique `TOOLS` ops to connector ops: delete the ~42 stale `TOOLS` host entries, recouple `llm_router._filter_tools_by_relevance`, drop the legacy `HOSTS`/`_http` stack, then add a tool-surface drift guard (eng)
- [ ] #P2 `acad` vs `autocad` host-name mismatch — the AutoCAD connector's `host` and the `tool_engine`/`ai_behaviour` family name disagree. Pick one, repo-wide (eng)
- [ ] #P2 Flaky test `test_host_executor_returns_typed_envelope` — asserts Revit version `"2025"` but the host-node executor returns the machine-detected version (`"2020"` on this box). Pre-existing, environment-dependent. Fix: don't hardcode a machine-dependent version, or make the executor echo the requested config (qa)

## LATER

- [ ] #P2 Civil 3D connector — blocked on Autodesk licence funding; design memo `docs/CIVIL_3D_ROADMAP.md` (rnd)
- [ ] #P2 SOC 2 Type I audit — triggered by first enterprise prospect with budget (ops)
- [ ] #P2 Canvas v2 power-user features — multi-select align, copy/paste subgraph, mini-map; spec `docs/CANVAS_PLAN.md` §7 (eng)
- [ ] #P2 Connector depth pass — bring all 18 host families to genuine parity; spec `docs/CONNECTOR_MASTER_PLAN_2026-05-15.md` (eng)

## Done — last 7 days

<!-- autopopulated by agents/roadmap_dispatcher.py — do not edit by hand -->

## Design references

Not roadmaps — architecture / decision memos, kept for rationale. Anything
actionable from these is tracked as a backlog item in the sections above.

- `docs/CANVAS_PLAN.md` — visual-canvas architecture (NodeGraphQt history + current JSX)
- `docs/CONNECTOR_MASTER_PLAN_2026-05-15.md` — 18-host connector build spec
- `docs/CLOUD_REVIVAL_PLAN.md` — cloud architecture decision (Cloudflare / Neon proposal)
- `docs/CIVIL_3D_ROADMAP.md` — Civil 3D connector design memo (deferred feature)
