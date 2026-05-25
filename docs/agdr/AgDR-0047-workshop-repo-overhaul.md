---
id: AgDR-0047
timestamp: 2026-05-25T18:30:00Z
agent: claude-code (Sonnet)
session: founder workshop · "revise the entire repo bit by bit · docs · logs · architecture · clean the shit · make sure it's working · without fucking things up"
trigger: founder workshop request 2026-05-25 — "whatever you did isn't appearing in application · find a way to make it work faster · revise the entire repo bit by bit · documentation, logs, architecture, clean the shit"
status: proposed
founder-signoff: pending — review forks F1-F5 below before slice work begins
category: workshop
projects: [archhub, personal-brain-mcp]
supersedes: []
extends:
  - AgDR-0026 (cold-start lag — perf slices land on top)
  - AgDR-0043 (workshop · deliver the surface — earlier workshop, this one continues)
  - AgDR-0044 (personal-brain-mcp — verifies brain wiring is honest)
  - AgDR-0045 (settings + brain unified)
  - AgDR-0046 (custom canvas substrate — ReactFlow lock superseded)
---

# Workshop — Repo overhaul · docs · logs · architecture · clean · perf

> In the context of the founder asking 2026-05-25 to "revise the entire
> repo bit by bit · documentation · logs · architecture · clean the
> shit · make sure it's working without fucking things up", with the
> WORKSHOP-GATE mandate firing on "fucking + critique" frustration and
> the BRAIN-FIRST mandate now in force, I am writing this AgDR as the
> workshop output. It consolidates four parallel scout audits (docs ·
> logs · architecture · perf) into one ranked plan, locks the slice
> ordering with risk grades + verification gates, and surfaces five
> founder-signoff forks (F1-F5) before any slice ships. The goal is a
> clean repo that the founder can navigate without tripping on stale
> AgDRs, ghost build artifacts, dead code, or unmeasured lag.

## Context

Four scouts ran in parallel against HEAD `d7c1d33`. Findings consolidated below.
Brain is reachable (`http://127.0.0.1:8473/mcp` returns `ok:true`, 0 skills,
0 facts). ArchHub renders fully — verified via OS screenshot. The recent
ship-everything loop landed 18 commits with no test regressions (2489/2489
passing), but it also exposed latent debt across all four scout dimensions.

## Findings (consolidated)

### A. Docs (scout #1 — 16 AgDR drifts, 4 orphan HTMLs, 19 orphan PNGs)

A1. **AgDR-0045 id collision.** Two files claimed `id: AgDR-0045`. The later one (`supersede-reactflow-lock.md`) has been **renumbered to AgDR-0046** in the same commit that ships this workshop, with `renumbered_from: AgDR-0045` recorded in its frontmatter. All references in CLAUDE.md / AGENTS.md / FAILURE_LOG.md / studio-lm.jsx already updated.

A2. **AgDR-0012 still claimed ReactFlow.** Status flipped to `partially_superseded` with a DOC BANNER pointing at AgDR-0046 + a `superseded_sections` list. Now honest.

A3. **AgDR status drift.** 13 AgDRs (0024-0036 inclusive) carry `status: approved` instead of `executed` or `superseded`. Single reconciliation pass needed.

A4. **Orphan prototypes.** `docs/prototypes/archhub-redesign-2026-05-24.html`, `assimilation-deepdive-2026-05-24.html`, `comfyui-alibaba-assimilation-2026-05-24.html`, `host-node-direction-a-comfyui-hybrid.html` — referenced nowhere. Action: archive to `docs/prototypes/_reverted/` (composer-redesign one is from a reverted commit) and `docs/prototypes/_iterations/` (the assimilation series).

A5. **Orphan PNGs.** 19 dev-iteration screenshots in `docs/prototypes/`. Action: move to `docs/prototypes/_screenshots/`.

A6. **Plan-doc drift.** `docs/CIVIL_3D_ROADMAP.md`, `docs/CONNECTOR_MASTER_PLAN_2026-05-15.md`, `docs/CLOUD_REVIVAL_PLAN.md` need the "design reference — not the roadmap" banner per CLAUDE.md ROADMAP MANDATE.

A7. **ROADMAP.md self-drift.** "38 AgDRs" claim (real count 47 after this commit). "0005, 0006 still proposed" wrong (both executed). Action: regenerate the ledger paragraph from the directory.

A8. **Root-level .md sprawl.** 16 root .md files. Strong consolidation candidate: merge `CONVENTIONS.md` stub into `CONTRIBUTING.md`; consider folding `DEVELOPMENT_LOG.md` history into `CHANGELOG.md` then archiving.

A9. **FAILURE_LOG.md format.** Wide table rows. Action: add a `status` column (open/closed); reformat to block-per-entry if width remains painful.

### B. Logs (scout #2 — central config missing, boot.log at repo root)

B1. **`boot.log` writes to repo root** (RED). `app/main.py:217` opens `APP_ROOT.parent / "boot.log"`. Should be `%LOCALAPPDATA%/ArchHub/logs/boot.log`. Fix the path; also update `agents/status_report.py:57`, `scripts/reality_smoke.py:572`, `agents/post_report_to_github.py:83` which read the old path.

B2. **No central logging config** (RED). Three independent loggers (`main.py` raw `open`, `llm_router.py` inline `_trace`, `revit_broker.py` unattached logger). Action: add `app/logging_config.py` with one `RotatingFileHandler` rooted at `%LOCALAPPDATA%/ArchHub/logs/`, called once from `main.py`. Migrate the 3 sites.

B3. **Layer 5 brain is reachable but empty** (YELLOW, expected). 4 pre_prompt events injecting 0 skills + 0 facts. Brain needs first-turn seeding — leave for normal use.

B4. **Iter12 streaming runaway (historical)** (YELLOW). 2026-05-12 Gemini called outlook_set_categories repeatedly to iter12 in `llm_trace.log`. Add iter-count guard rail (cap at iter10 abort) in `llm_router.py` near `_max_iterations`.

B5. **Missing proof PNGs** (YELLOW). Commit `11de2d3` has a `proof_canvas_decluttered_11de2d3.png` on disk that's not committed. AgDR-0044 / AgDR-0046 / USER-AGENCY ships have no proof. Backfill or accept the gap explicitly in FAILURE_LOG.

B6. **WER reports clean last 7d** (GREEN). No fresh crashes.

### C. Architecture (scout #3 — collisions, dead code, orphan slots)

C1. **AgDR-0045 id collision** — resolved per A1 in this commit.

C2. **AgDR-0012 ReactFlow claim** — resolved per A2.

C3. **Dead JSX**: `NodeCanvasRF_Stub` (jsx:~7555) + `_readCanvasFlavor` / `_setCanvasFlavor` + `window.__archhubCanvasFlavor` / `window.__archhubSetCanvasFlavor` exports (jsx:~7503-7520). Per AgDR-0046 §Artifacts the removal was promised. Hold until F4 decision below — kept today only so `test_reactflow_p2a_groundwork.py` doesn't break.

C4. **Dead JSX**: `bumpGraphSync` (jsx:1098) — zero callers. `bumpGraphRaf` alias (jsx:1100) — pure cosmetic. `_LM_GRAPH_DEMO_DEAD` (jsx:825) — 100-line demo dict, zero refs.

C5. **Orphan Python**: `app/workflows_panel.py` — explicit "TODO(shadow-audit): this module is currently orphan." Delete after F4.

C6. **Orphan Python**: `ChatWindow._open_connectors` (chat_window.py:2782, "orphan since v1.3.2") + `_open_reality_check` (chat_window.py:3145, "orphan since v1.3.1"). Delete after F4.

C7. **Bridge slot ↔ JSX consumer mismatch**:
- JSX calls 2 undefined slots: `bridgeCall('cook_session', ...)` (jsx:2051), `bridgeCall('open_file', ...)` (jsx:11338). Silent no-ops. Action: define slots OR remove callers.
- 49 bridge slots have zero JSX callers (primitives shipped, UI absent). The DEFINITION-OF-SHIPPED + ANTI-LIE mandate is violated for each. Fork F2 picks the resolution.

C8. **PortType vs speckle_type drift.** AgDR-0012 §232-233 deprecates PortType; 33 source files still use it, 4 use speckle_type. Migration was never executed. Fork F3.

C9. **LM_GRAPH god-mutable** (jsx:809). 58 mutation sites across 12700 lines. Each site mutates in-place then calls `bumpGraph()` by convention; any forgotten call = stale UI; any mid-mutation crash = corrupt state. Proper fix = `useReducer({nodes, wires, groups})`. Multi-day refactor.

C10. **Settings TODO drift.** `settings_page.py:151` "TODO(shadow-audit): SettingsDialog ALREADY contains its own AI Behaviour section… user sees both surfaces stacked." Active UI dup bug.

C11. **main.py:511** "TODO(shadow-audit): Settings → Appearance HUD overlay + hotkey rebind shown to every user but only honoured when StudioShell construction fails." Disconnected toggle.

### D. Perf (scout #4 — 10 next sources, ranked)

D1. **#1 (idle, L risk)**: `RailMiniMap` 500ms `setInterval(onBump, 500)` forces global re-render every half-second idle. 1-line fix (drop interval; rely on `lm-graph-bump`).

D2. **#2 (drag/idle, L risk)**: `NodeCanvas` state-stash effect (jsx:5098-5108) has NO dep array — runs after EVERY render including 60Hz drag. Calls `getBoundingClientRect()` (forced layout) + allocates new state object → triggers `RailMiniMap` re-render every frame. 1-line fix (add deps `[pan, zoom, positions, allNodes]`).

D3. **#3 (streaming, L-M risk)**: streaming chunk handler does TWO O(N) scans per chunk to find the streaming AI node + message. ~30-80 chunks/s × O(N×msgs) = hundreds of property reads per chunk. Fix: cache `streamingConvNode` + `streamingMsgIx` in a ref on first chunk; clear on `onDone`.

D4. **#4 (drag/render, L risk)**: `Workspace.allNodes` non-memoized spread (jsx:4576). Mirror the NodeCanvas memo pattern + wrap `NodeRail` / `ConversationRail` in `React.memo`.

D5. **#5 (drag, M risk)**: Inline SVG `M…C…` path strings rebuilt per wire per frame (jsx:6009-6058). 50 wires × 60fps = ~6000 string allocs/sec. Memoize per-wire `{d, color, strokeW}` keyed by endpoints + status.

D6. **#6 (drag, H risk — biggest single win)**: full React state cycle per drag pixel. `setPositions` clones N-entry dict + Alt-overlap O(N²) check + downstream useMemo cascades. Architecture shift: imperative `node.style.transform = translate(x,y)` during drag, commit React state on mouseup. Wires for the dragged node re-pathed by direct `d` attr update.

D7. **#7 (drag, L risk)**: `nodeById` useMemo creates N node clones on every drag pixel (jsx:5753-5755) — depends on `positions` which is fresh ref every drag frame → memo busts.

D8. **#8 (streaming, L risk)**: `HealthStripItem` `bridgeAsync('graph_validate', JSON.stringify(LM_GRAPH))` runs even when graph hash unchanged. Hash + skip when stable.

D9. **#9 (idle, L risk)**: `BrainChip` 4s poll + `MemoryStripItem` 30s poll + `PerfHud` 1s tick — all run regardless of visibility. Switch to event-driven OR gate on `document.visibilityState`.

D10. **#10 (drag/render, L risk)**: 5 `getBoundingClientRect` reads outside refs force layout flushes on each call. Cache in ref refreshed only on resize.

## Founder forks (signoff required before slice work begins)

**F1 — Slice ordering: ship perf first or docs first?**
- F1.A: PERF FIRST — D1/D2/D4/D7 (low-risk wins) before any docs/logs cleanup. Founder feels the app responsive within the same iteration. Docs cleanup comes after.
- F1.B: DOCS FIRST — A1-A9 + B1/B2 clean up the cruft so future slices land on a navigable repo. Perf comes second.
- F1.C **(recommended)**: INTERLEAVE — ship the 4 lowest-risk perf fixes first (1 commit), then the A/B housekeeping (2-3 commits), then the harder perf work (D5, D6).

**F2 — 49 orphan bridge slots (no JSX caller):**
- F2.A: DELETE the unused slots from `bridge.py`. Dead code, clean removal.
- F2.B: KEEP slots, ADD their UI consumers (Memory mgmt UI, Trigger panel, Provider page, Storage stats panel, etc). Multi-week scope.
- F2.C **(recommended)**: KEEP slots with a single-line `# JSX consumer pending — AgDR-NNNN` comment per slot, plus a `bridge_slot_health` test that fails CI when an orphan slot has no inline reference to a planned AgDR. Document the gap; don't lie about it.

**F3 — PortType → speckle_type migration:**
- F3.A: EXECUTE the migration per AgDR-0012 — touch 33 files. High risk; needs its own AgDR slice.
- F3.B: SUPERSEDE the AgDR-0012 §232-233 lines via a new AgDR ("PortType stays — speckle_type is for wire transport only"). Honest.
- F3.C **(recommended)**: B for now (AgDR-0048 — formally retract the migration). Revisit when wire transport gets attention.

**F4 — Dead code removal aggression:**
- F4.A: AGGRESSIVE — delete `workflows_panel.py`, `ChatWindow._open_connectors`, `_open_reality_check`, `NodeCanvasRF_Stub`, `_readCanvasFlavor` / `_setCanvasFlavor`, `bumpGraphSync`, `bumpGraphRaf`, `_LM_GRAPH_DEMO_DEAD`. Also update `tests/test_reactflow_p2a_groundwork.py` to assert the stub is GONE (inverted test).
- F4.B: CONSERVATIVE — leave everything; flag with `@deprecated` comments + a docs/agdr/AgDR for tracking.
- F4.C **(recommended)**: A — be aggressive. The audit identified them as truly dead; the tests anchor goes with the supersede.

**F5 — Imperative drag (D6) ordering:**
- F5.A: SHIP NOW alongside other perf slices. High risk; biggest gain.
- F5.B: DEFER — it's a multi-day refactor and the other perf wins may make it unnecessary.
- F5.C **(recommended)**: B — defer to its own AgDR (AgDR-0049). Measure after shipping D1/D2/D4/D7/D8/D9 (the low-risk batch) whether D6 is still needed. If founder still feels lag, escalate.

## Decision

Pending founder signoff on F1-F5 above. Default picks (recommended set):
- F1.C (interleave)
- F2.C (keep slots + tests)
- F3.C (formally retract migration)
- F4.A (aggressive dead-code delete)
- F5.C (defer D6)

## Consequences (after default picks)

**Becomes easier:**
- Repo is honest about its own state (no stale AgDR claims, no dead-code that pretends to ship)
- Future agents land on a clean substrate; AGENTS.md + .githooks already block the next intrusion
- Perf gains measurable per slice via PerfHud (FPS / save_calls)
- FAILURE_LOG has explicit closed-row receipts

**Becomes harder:**
- D6 stays open as a known performance ceiling. Acknowledged.
- 49 bridge slots get an `# AgDR-NNNN pending` annotation each; the visible deferral is honest but big.

**Cancels nothing.** This AgDR adds work; doesn't retract any prior shipped surface.

## Artifacts (this commit + the slice commits to follow)

- This AgDR
- AgDR-0046 renumbered + frontmatter records `renumbered_from: AgDR-0045`
- AgDR-0012 status flipped to `partially_superseded` + DOC BANNER
- AGENTS.md / CLAUDE.md / FAILURE_LOG.md / studio-lm.jsx updated for the AgDR-0045 → AgDR-0046 rename
- Slice commits to follow per the slice plan below

## Slice plan (post-signoff)

| # | Slice | Risk | Files | Tests | Verification |
|---|---|---|---|---|---|
| S1 | Perf low-risk batch (D1, D2, D4, D7) | L | studio-lm.jsx | full suite | PerfHud delta on streaming + drag |
| S2 | Boot.log relocation + central logging config (B1, B2) | L | main.py, llm_router.py, revit_broker.py, agents/status_report.py, scripts/reality_smoke.py, agents/post_report_to_github.py + new app/logging_config.py | full suite | restart + grep new log path |
| S3 | AgDR status reconciliation (A3) | L | docs/agdr/*.md (13 files) | none | AgDR ledger regenerated |
| S4 | Prototype + PNG archive (A4, A5) | L | docs/prototypes/* | none | mv operations only |
| S5 | Plan-doc banners (A6) + ROADMAP regen (A7) | L | docs/CIVIL_3D_ROADMAP.md, docs/CONNECTOR_MASTER_PLAN_2026-05-15.md, docs/CLOUD_REVIVAL_PLAN.md, docs/ROADMAP.md | none | grep banner present |
| S6 | Dead-code aggressive delete (C3-C6, F4.A) | M | studio-lm.jsx, chat_window.py, workflows_panel.py (delete) + test inversion | full suite | tree clean of dead syms |
| S7 | Streaming hot-path perf (D3) | L-M | studio-lm.jsx | full suite | PerfHud per-chunk |
| S8 | Idle pollers gated on visibility (D9) | L | studio-lm.jsx | full suite | observe idle CPU |
| S9 | bridge_slot_health test + slot annotation (F2.C) | L | bridge.py + new tests/test_bridge_slot_health.py | full suite | new test passes |
| S10 | Cleanup commit · CHANGELOG · proofs backfill | L | CHANGELOG.md + proofs/2026-05-25/ | none | preflight grid |
| S11 | Post-overhaul preflight + founder review | L | (verification only) | preflight + loop_audit + cs_tripwire | founder signoff |

Wire transport / PortType (F3) and imperative drag (F5) become AgDR-0048 / AgDR-0049 respectively, NOT this slice plan.

## References

- AgDR-0043 (prior workshop — surface delivery)
- AgDR-0044 (personal-brain-mcp)
- AgDR-0045 (settings + brain unified)
- AgDR-0046 (custom canvas substrate)
- CLAUDE.md mandates: DEFINITION-OF-SHIPPED, NO-OPEN-THREADS, PRE-FLIGHT-CHECK, POST-LOOP-AUDIT, ROLLBACK-PROTOCOL, WORKSHOP-GATE, AUTOMATION, AGDR, ROADMAP, BRAIN-FIRST
- AGENTS.md (cross-vendor mandate file)
