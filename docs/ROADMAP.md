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
- [ ] #P1 archhub.io go-live — DNS records, Fly deploy, Resend domain verification, `PUBLIC_URL` secret (ops)
- [x] #P2 SessionCard host pills + last-message preview — `get_sessions` now emits `host` / `last` / `node_count` / `messages` via `session_io.list_sessions_rich`; the JSX card already had the render slots; shipped 2026-05-18 (eng)
- [ ] #P2 Home filter chip `scheduled` is dead — no session-schedule model exists; remove the chip. (The `workflows` chip now works — `get_sessions` emits `node_count`.) (eng)

## NEXT 30 DAYS

- [ ] #P2 `/dashboard` authed-roster test — current tests only assert the page renders, not the authenticated company/team render (qa)
- [ ] #P2 First-run profile capture — zero automated coverage on the `get_profile` / `save_profile` bridge slots + `FirstRunProfile` (qa)
- [ ] #P1 Cloud Pro / Studio paid tiers — auth + Stripe phase per `docs/CLOUD_REVIVAL_PLAN.md` (eng)
- [ ] #P2 Deploy the 3ds Max host add-in — `payload/max/` does not exist; the connector is code-complete but `probe()` honestly reports `missing` until the add-in ships. Build + deploy from `payload/sources/max_mcp/` (ops)

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
