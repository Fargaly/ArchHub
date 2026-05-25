---
id: AgDR-0043
timestamp: 2026-05-25
status: proposed
founder-signoff: pending — review `docs/prototypes/signed/workshop-2026-05-25.html` and pick SHIP / REVISE / HOLD
category: process+ui
supersedes: none
builds-on: [AgDR-0012, AgDR-0014, AgDR-0015, AgDR-0021, AgDR-0022, AgDR-0024, AgDR-0041, AgDR-0042]
---

# AgDR-0043 — Workshop · Deliver the surface · 7-hat council

## Context

Founder, 2026-05-25 (verbatim):

> "I need A workshop... spawn a council of agents... 7 hats strategy... do a fucking proper R&D... device a plan... show me a prototype... and this fucking prototype should be the actual fucking thing that I get... and I want to see results.... what does it mean that something is shipped if you promise something and deliver a totaly diffrent shit?? where are the nodes...where are every fucking thing I kept deciding in your fucking previous prototypes?... Give me What You promised... No Cutting corners... Not halfassing work... Not telling me something is done when it's not... when I tell you to loop I mean you go on and on untill you finalize every fucking thing... don't keep open threads... nothing for testing later.... you do every fucking thing needs to be done. WTF is that? Honesty is a Fucking mandate"

Trigger: the gap between "shipped per commit log + tests" and "founder opens app and feels different." 14 commits across the last loop landed backend (memory graph, validators, bridge slots) but UI surface is unchanged from his daily experience. Pattern over multiple sessions, not one.

A 7-hat council (per De Bono's six + R&D) ran in parallel. Findings synthesised in `docs/prototypes/signed/workshop-2026-05-25.html`.

## Hat synthesis (1 line each)

| Hat | Headline |
|-----|----------|
| ① White · facts | Backend 100% · UI surface ~10%. ai.plan has 0 JSX references. Memory graph has 0 UI consumers. ReactFlow architecturally locked but never installed. |
| ② Red · emotion | Trust debt > tech debt. He is 1-2 invisible-ship cycles from quitting Claude on this project. |
| ③ Black · risk | 10,335-line JSX monolith · `graphBump` god-counter re-renders everything · 63 unbatched `saveCurrentGraph()` calls · zero panel resize/theme/keybind. |
| ④ Yellow · works | Substrate is the asset — 16 connectors / 116 ops / 79 grammar primitives / 6-provider router / 2473 tests. Don't rebuild — **surface** it. |
| ⑤ Green · creative | 60-second perception flip is achievable: 4 use case tiles on home + Composer chat as centerpiece + status bar + Cmd+K + memory-aware Library. |
| ⑥ Blue · process | 7 new mandates needed (Definition of Shipped · Prototype-Is-Contract · No Open Threads · Pre-flight · Post-loop Audit · Rollback · Workshop Gate). |
| ⑦ R&D · scan | Match Linear's feel in 4 weeks. Steal: Qt-ADS docking (VS Code/OBS) · @-mention chips (Cursor) · Cmd+K w/ recency (Linear) · Ctrl+B bypass (ComfyUI) · cursor-centered zoom (Figma). Wedge: chat-driven graph mutation with visible diffs. |

Full hat outputs preserved in commit body of this AgDR.

## Decision

**Adopt the workshop output verbatim** subject to founder picking SHIP / REVISE / HOLD on `docs/prototypes/signed/workshop-2026-05-25.html`. The prototype IS the contract per new Prototype-Is-Contract mandate (item §6.2 below).

Three sprints execute sequentially:

### Sprint 0 (today · 4 hours)
Process · the rails before the trains.
- 7 new mandates land in `CLAUDE.md`
- `tools/preflight.ps1` script (7-question gate)
- `tools/loop_audit.ps1` script (post-loop audit)
- `docs/FAILURE_LOG.md` created
- `prototypes/signed/` directory established (this AgDR + workshop HTML inside)

### Sprint 1 (Day 1-2 · the 60-second perception flip)
1. **4 use case tiles on Home** — Revit→render, photo→mass, drone→walls, text→plan. Click → live canvas pre-wired.
2. **Composer chat as 56px centerpiece** — floating bar canvas-bottom-center, ⌘K focus, ghost-node preview as you type.
3. **Resizable left/right panels + saved layout** — 2 drag handles + CSS vars + localStorage.
4. **Status bar at canvas bottom** — broker / hosts / cost / memory count, all live.
5. **Debounce `saveCurrentGraph()` 250ms** — single scheduler converges all 63 call sites.

### Sprint 2 (Day 3-7 · make memory + composer visible)
6. **⌘K command palette** — fuzzy + recency, indexes nodes / skills / commands / sessions.
7. **Memory-aware Library** — collapsible community sections from `memory.communities`, similarity-ranked.
8. **ai.plan as hero node** — 2.5× size, mini sub-canvas of steps, cost chip, step indicator.
9. **Wire animation during cook** — SVG/CSS conic-gradient · phase color.
10. **Theme system · DARK / BLUEPRINT / VELLUM** — CSS vars · ⌘⇧T · persist.
11. **@-mention chips in Composer** — contenteditable + cmdk picker + chip pills.

### Sprint 3 (Week 2-3 · the structural ones)
12. **Split `studio-lm.jsx` into 8-10 files via `window.ArchHubUI`** — devtools nav, per-file Babel cache, lazy-load modals.
13. **Kill `graphBump` god-counter** — `useReducer` + selectors. Streaming chat no longer re-renders canvas; drag 60fps.
14. **Imperative drag** — `useRef` Map + DOM transform during drag, React state on drag-end only.
15. **Keyboard shortcuts JSON config + rebind UI** — `SHORTCUTS` map + `useShortcut(name)` hook.
16. **Perform Mode · ⌘⇧P** — hides chrome for client demos.

## Consequences

- **Trust restoration** — founder opens app post-Sprint 1 and the 4 tiles + composer + status bar make the change visible in seconds.
- **Prototype-is-contract** — the workshop HTML becomes the JSX spec. Visual drift > a few px requires a new AgDR.
- **Process mandates enforce** — no more "shipped per tests" without "shipped per CDP-verified click-path."
- **Substrate preserved** — Hat 4 explicitly bans rebuild of the 2473-test backend; this is a surfacing exercise.
- **Calendar honest** — 3-4 weeks for full plan. Sprint 0+1 lands in 2 days.

## Open forks (per AGDR mandate — never resolve silently)

| Fork | Default if no answer | Founder picks |
|------|----------------------|---------------|
| Move 6 (⌘K palette) recency formula | VS Code's `score × log10(useCount+1)×0.3 × recencyDecay` | accept default OR revise |
| Move 7 (memory-aware Library) — show all categories or top-3 recent? | top-3 recent + collapsible rest | revise |
| Move 12 (split JSX) — Path A `window.ArchHubUI` namespace OR Path B real ES modules via `<script type="module">` | Path A (no build step change) | Path B if founder wants build-step refactor |
| Sprint 3 timing — pause shipping during structural week 2-3 OR overlap with Sprint 2 polish | overlap (smaller atomic commits) | pause |

## Artifacts

- This AgDR.
- `docs/prototypes/signed/workshop-2026-05-25.html` — the contract prototype (interactive, themed, 3 themes, ⌘K, tile click).
- `CLAUDE.md` — 7 new mandates appended (Sprint 0).
- `tools/preflight.ps1` — 7-question pre-flight gate.
- `tools/loop_audit.ps1` — post-loop audit.
- `docs/FAILURE_LOG.md` — running record of "shipped-but-invisible" failures + resolutions.
- Per-move commits will reference this AgDR in their body.
