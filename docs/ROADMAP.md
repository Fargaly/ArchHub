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
- [ ] #P0 Graph-first canvas "Run" is broken for the curated node library — the 80 `LM_LIBRARY` node types (`LM_NODE_TEMPLATES`, `studio-lm.jsx:1846`) carry NO engine `type` field; `bridge.run_workflow`/`run_node` pass the raw canvas graph to `WorkflowRunner`, which dispatches on `node.type` → empty → `registry` miss → `"no executor for ''"` (`runner.py:475`). A user can drag, wire and Run any curated library node and it errors. (Connector-op nodes carry `op_id`, custom nodes carry `custom_type`, conversation chat uses a separate path — those 3 DO work; the 80-node curated palette does not.) Investigation 2026-05-18 found it is deeper than a missing field: of the 80 `LM_LIBRARY` nodes only ~30 have a real engine executor (7 `host.*`, `control.if/merge/foreach`, `conversation.chat`, `llm.classify`, connector-op-backed reads). The other ~50 — most `filter`/`transform`/`compose`/`annotate` nodes, the 11 non-engine host nodes (word/excel/teams/notion/…), `logic` switch/loop/split/delay/throttle, several `ai` nodes — have NO engine executor at all. `LM_LIBRARY` is an aspirational catalogue (`docs/NODE_LIBRARY_v2.md`) the engine never caught up to. Fix is multi-slice: (1) binding adapter; (2) wire the ~30 nodes that have executors + verify graphs cook; (3) the ~50-node executor gap — build the missing executors (default — make it work) or trim the library. Same parallel-registry drift class as connectors/tool_engine.
  - SLICE-1 SPEC (verified 2026-05-18): the binding is a multi-field ADAPTER, not a `type` stamp. Canvas nodes carry `cat` + `id` + `params` (a list of `{k,v,type}`); `runner.py` dispatches on `node.type` and reads `node.config` (a dict) — it reads neither `cat` nor `params` (verified `runner.py:380,425,481`). Engine types confirmed: `host.{family}`, `conversation.chat`, `control.if/merge/foreach`, `llm.complete/complete_with_tools/classify`, `aec.*`, `io/output.parameter`, `data.constant`, `subgraph.*`. Slice 1 = a canvas-node→engine-node normaliser (in `addNodeFromLibrary` or bridge-side) that stamps `type` from a verified `id`→`type` map AND folds `params`→`config`; then a runner test proving a `control.if` / `conversation.chat` graph cooks end-to-end. Half-implementing (type only, no config) makes nodes "run" with empty config — looks fixed, isn't — so it ships as one correct adapter, not a partial stamp (eng)
- [ ] #P0 Bridge slots block the Qt main thread — boot-hang, observed LIVE 2026-05-18: a clean relaunch hung on the boot splash ~8 min (backend self-test finished in seconds per `boot.log`; UI never rendered; `pythonw` idle at 7s CPU = blocked, not spinning). A 2nd relaunch of identical code booted fine → non-deterministic. Cause: sync work on the Qt main thread — `get_models` (Ollama + LM Studio HTTP), `probe_connector` (COM/HTTP probe), and the startup slot prefetches in `index.html`; when a host is slow/unresponsive the main thread blocks and the QtWebEngine UI never completes its bridge handshake. Boot hangs forever on some fraction of launches → P0 (was #P1). Fix: every slow `@pyqtSlot` (probes, LLM, COM/HTTP) + every startup prefetch runs on a worker thread + signal, mirroring `run_connector_op` — never block the Qt main thread (CLAUDE.md rule) (eng)
- [ ] #P0 NODE-SYSTEM REDESIGN — node grammar + UI/UX (founder mandate 2026-05-18). The current ~80-node library is decorative and mostly non-functional; redesign around a SMALL set of primitive/master nodes with ComfyUI / n8n / Grasshopper / Dynamo-grade UX. Founder intent (a guideline, NOT a literal spec — research + design, apply judgment): nodes simple, modular, composable from each other with logic. Primitive families — INPUTS (multiple nodes, optimum input control); OUTPUTS (multiple nodes, optimum output control); WATCHERS & TRIGGERS (view / list / model / image / …); CONNECTORS (ONE master node per host — every tool + data call exposed as right-panel parameters, no scattered per-op host nodes); AI (ONE master node — every AI action as a parameter). From these primitives, generate other nodes. Save-as-Skill → the skill is itself a usable node (recursive). The selected node's parameters render in the right-side panel. Folds in the canvas-Run #P0 above — build executors for the NEW small node set, not the old 80. Design: `docs/NODE_GRAMMAR.md` (written 2026-05-18 — the principle, the ~12-primitive grammar, skill-as-node, 10 build slices). Loop until grammar + UI/UX shipped and working — zero decorative nodes. (eng)
  - SLICE 1: one node model — canvas nodes carry the registry `type` (not `cat`); one port-type vocabulary (engine `PortType`); `params`≡engine `config`; `run_workflow` cooks a real graph end-to-end. Subsumes the canvas-Run #P0 above. (eng)
  - SLICE 2: `connector` master node — collapse the 18 host nodes + 118 one-per-op nodes into ONE node per host; `op` param; the op's `ConnectorOp.inputs` render as right-panel params. (eng)
  - SLICE 3: `ai` master node — one node, `action` param (chat/complete/classify/extract/vision/embed/tools); action's params in the right panel. (eng)
  - SLICES 4-10: input/constant/output primitives · logic (if/merge/foreach/switch) · watch+trigger nodes+executors · filter+transform executors · skill-as-node (subgraph reference semantics) · UI/UX pass (typed sockets, add-node search, run feedback) · delete old `LM_LIBRARY`/`NODE_LIBRARY_v2.md`. Full detail in the memo. (eng)
- [ ] #P1 archhub.io go-live — DNS records, Fly deploy, Resend domain verification, `PUBLIC_URL` secret (ops)
- [x] #P1 `tool_policies` override store audited (2026-05-18) — root fix: `tests/conftest.py` now isolates `secrets_store` suite-wide (autouse fixture), so no test can pollute the real settings store ever; verified 1156 tests pass. The existing all-"allow" overrides were NOT test-created (no test bulk-sets "allow"; `test_ai_behaviour` was already isolated) — they are founder/app Settings state. Resetting them is the founder's call (Settings → AI Behaviour → Reset) (qa)
- [x] #P2 SessionCard host pills + last-message preview — `get_sessions` now emits `host` / `last` / `node_count` / `messages` via `session_io.list_sessions_rich`; the JSX card already had the render slots; shipped 2026-05-18 (eng)
- [x] #P0 Firm-tier quota revenue bug (2026-05-18) — a company on the Firm plan was capped at the 2000 `companies.msg_limit` column DEFAULT instead of its 1,000,000 quota (`config.PLAN_QUOTAS["firm"]`) — 99.8% of paid quota silently withheld. Root: `db.create_company` never seeded `msg_limit`, and `db.update_company` (the billing webhook's only company call) updated `plan` without re-deriving `msg_limit`. Audit found the class is wider — `billing.py` routed only `checkout.session.completed` to companies; `customer.subscription.updated` (Studio→Firm upgrade) and `.deleted` (cancellation) were user-only, so an upgrade/cancel never reached the company row. Root fix: the plan→msg_limit invariant now lives in `db.create_company` + `db.update_company` (a plan change re-derives `msg_limit` + resets `msg_used` — impossible to set a plan and leave a stale quota); `billing.py` gained company branches for subscription updated/deleted via `_company_from_subscription`; dead `update_company_quota` (aspirational, never wired) deleted. +8 tests; 180 cloud tests green (eng)
- [x] #P1 Skills panel "empty & not working" (2026-05-18) — the founder saw the Skills list show ~19 skills that did nothing on click. Root: a three-way store drift — `get_saved_skills` listed `skills.library` (engine-format Workflow store), `load_skill` globbed the source-tree `app/skills/`, and storage/export/import used `%LOCALAPPDATA%/ArchHub/skills/`. The panel listed skills the loader could never find → every click 404'd. The earlier `load_skill` slot (c93966a) was a patch — it un-deadened the button but read the wrong store. Root fix: `get_saved_skills` + `load_skill` now share one resolver (`bridge._scan_canvas_skills` — canvas-format: `%LOCALAPPDATA%/ArchHub/skills/` user store + `app/skills/` shipped seeds); `save_as_skill` writes the user store not the source tree; JSX `LM_SAVED_SKILLS` fallback is `[]` not 6 hardcoded demo skills. Guard test pins list⊆loadable. 54 bridge tests green (eng)
- [ ] #P2 Home filter chip `scheduled` is dead — no session-schedule model exists; remove the chip. (The `workflows` chip now works — `get_sessions` emits `node_count`.) (eng)

## NEXT 30 DAYS

- [ ] #P2 `/dashboard` authed-roster test — current tests only assert the page renders, not the authenticated company/team render (qa)
- [ ] #P2 First-run profile capture — zero automated coverage on the `get_profile` / `save_profile` bridge slots + `FirstRunProfile` (qa)
- [ ] #P1 Cloud Pro / Studio paid tiers — auth + Stripe phase per `docs/CLOUD_REVIVAL_PLAN.md` (eng)
- [ ] #P1 Session tokens are immortal — `db.issue_token` stores only `token`/`user_id`/`created_at` (no expiry) and `db.user_for_token` does ZERO expiry check, yet `auth.py` advertises a 90-day `expires_at` to the client. The advertised expiry is theater — a leaked `ah_live_…` token grants permanent access. Fix: store an expiry on the `tokens` row + enforce it in `user_for_token` (mirror the `codes`-table check at `db.py:586`). Security (eng)
- [ ] #P2 Company seat-limit ignores outstanding invites — `companies.py invite_member` (line 219) comments "count existing members + outstanding invites" but only counts members (`db.count_company_members`). A company over-invites past `seat_limit`: 3 members + N pending invites all pass the check, then all accept. Count members + un-accepted invites (eng)
- [ ] #P2 `proxy.chat_completions` has no success-path test — only the two 402 quota-exhausted cases are covered (`cloud_backend/tests/test_company_quota.py`). The happy path (in-quota request → model route → 200 + usage increment) has zero coverage; the core revenue path is untested (qa)
- [ ] #P2 Polar billing is company-blind — `polar.py` only ever calls `db.update_user_plan`; no webhook path (`subscription.created/updated/canceled`) routes to a company, and `create_checkout_url` hardcodes `archhub_kind:"user"`. A company on `BILLING_PROVIDER=polar` cannot get a paid plan at all. Stripe is the active provider so this is a gap not a regression; build company checkout + company webhook routing (mirror `billing._company_from_subscription`) before Polar goes live (eng)
- [ ] #P2 Surface engine-format library skills in the canvas Skills panel — the `skills.library` Workflow store (seed skills from `production_seeds.py`/`seeds.py`, and the chat skill-matcher's source) is engine-shaped (`type`/`config`/`inputs`); the canvas panel only renders canvas-format skills (`cat`/`x`/`y`/`ins`/`params`). Surfacing the library seeds in the panel needs an engine→canvas node converter — the inverse of the #P0 canvas-Run binding adapter; build alongside #P0 slice-1 (eng)
- [ ] #P2 Delete dead `SkillsPanel` + `SearchPanel` JSX components — `studio-lm.jsx:2686`/`:2761` define both but nothing renders them (`panel` state is `'nodes'`-only since the chats/skills/search panels were removed — `studio-lm.jsx:602`). ~140 lines of decorative dead code; the live Skills surface is the node-library `★ SKILLS` section (eng)
- [ ] #P2 Deploy the 3ds Max host add-in — `payload/max/` does not exist; the connector is code-complete but `probe()` honestly reports `missing` until the add-in ships. Build + deploy from `payload/sources/max_mcp/` (ops)
- [ ] #P2 Outlook connector op gap — it ships 8 named ops, but `ai_behaviour.py` + `outlook_runner` were built for ~15 (`set_categories`, `set_categories_by_filter`, `auto_categorize_by_*`, `search_threads`, `list_folders`, `move_to_folder`, `flag_for_followup`, ...). The `execute_python` escape hatch was wired 2026-05-18; wire the named category/folder ops too (eng)
- [ ] #P2 Connector escape-hatch parity — surface ops the runners already support but the connectors don't expose: `revit.execute_csharp` + `revit.screenshot`, `autocad.execute_csharp`, `max.execute_python`, `rhino.screenshot`, `{illustrator,indesign,photoshop}.execute_jsx`. Template: `outlook.execute_python` (commit ae79db5) (eng)
- [ ] #P2 Tool-registry unification — `tool_engine.TOOLS` (hand list) and `connectors.base` ops are two parallel registries, both emitted to the LLM; 6 hosts get duplicate tools. Audit 2026-05-18 confirmed the surface is functionally honest (no dead routes) but drifted. After escape-hatch parity migrates the unique `TOOLS` ops to connector ops: delete the ~42 stale `TOOLS` host entries, recouple `llm_router._filter_tools_by_relevance`, drop the legacy `HOSTS`/`_http` stack, then add a tool-surface drift guard (eng)
- [ ] #P2 Bridge dead-slot cleanup — ~21 `@pyqtSlot`s have no JSX caller (memory mutations, trigger arm/disarm, node-MCP dispatch, settings housekeeping: `set_theme`/`export_all`/`set_host_active`/`wire_transform`/...), and `index.html` prefetches 4 slots into window vars `studio-lm.jsx` never reads. For each: wire the intended UI action, or delete the slot (eng)
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
- `docs/NODE_GRAMMAR.md` — node-system redesign: the node grammar, ~12 primitives, skill-as-node, build slices (supersedes `NODE_LIBRARY_v2.md`)
- `docs/CONNECTOR_MASTER_PLAN_2026-05-15.md` — 18-host connector build spec
- `docs/CLOUD_REVIVAL_PLAN.md` — cloud architecture decision (Cloudflare / Neon proposal)
- `docs/CIVIL_3D_ROADMAP.md` — Civil 3D connector design memo (deferred feature)
