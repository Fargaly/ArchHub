---
id: AgDR-0048
timestamp: 2026-05-25T12:30:00Z
renumbered_from: AgDR-0045 → AgDR-0046 → AgDR-0048
renumber_reason: second collision. Originally AgDR-0045 (collision with AgDR-0045-settings-brain-unified). Renumbered to 0046 in 2026-05-25 overhaul. Then 2026-05-26 founder wrote AgDR-0046-brain-settings-rebuild-workshop.md with the same 0046 id. Founder's workshop wins the 0046 slot (later timestamp + active brain rebuild thread). This file moves to 0048. Content + supersede chain unchanged.
agent: claude-code (Sonnet)
session: founder ship-everything loop · 2026-05-25
trigger: FAILURE_LOG row 7 — "AgDR-0022 + ARCHITECTURE LOCK 'ReactFlow is the canvas substrate' but ReactFlow NEVER installed"
status: executed
category: architecture
projects: [archhub]
supersedes:
  - AgDR-0012 §"ReactFlow is the canvas substrate" (committed earlier in session)
  - AgDR-0022 in full (scaffold P2.a-P2.d — never reached parity, custom canvas overtook it)
---

# Custom canvas IS the substrate — supersede the ReactFlow lock

> In the context of the founder calling out (FAILURE_LOG row 7, 2026-05-25)
> that the ARCHITECTURE LOCK declared "ReactFlow is the canvas substrate"
> but ReactFlow was never installed and `NodeCanvasRF_Stub` is a literal
> placeholder, I decided to formally supersede the lock and recognise the
> existing custom canvas (`NodeView` + `WireLayer` + `LM_GRAPH`) as the
> substrate of record, because it carries six months of shipped features
> ReactFlow has zero equivalent of (typed wires, broken-wire dialog,
> HostNodeV2 op grid, ai.plan hero render, groups + collapse, multi-select,
> bypass/freeze/pin verbs) and the migration cost (3-5 days minimum,
> regression risk across every node interaction) exceeds the value of the
> migration target (zero new user-facing capability), so that
> ROLLBACK-PROTOCOL on this FAILURE_LOG entry resolves cleanly without
> burning weeks on a parity rebuild.

## Context

AgDR-0012 (2026-05-20) ended with a single-line architecture lock: "ReactFlow is the canvas substrate." AgDR-0022 then scaffolded a feature flag (`localStorage.archhub.canvas = 'custom' | 'reactflow'`) and a stub component (`NodeCanvasRF_Stub`) that would render a "Migration ships across P2.a → P2.d" placeholder when toggled.

Reality at 2026-05-25:
- `npm install reactflow` was never run. No `package.json`, no `node_modules`, no `import { ReactFlow }` in any file.
- `NodeCanvasRF_Stub` is the only `reactflow`-labelled component. It renders a card that says "PREVIEW" and offers a "Back to custom canvas" button.
- The custom canvas (`NodeView` line 7262, `WireLayer`, `LM_GRAPH` module-global) has shipped: typed wires (AgDR-0007), groups + collapse (AgDR-0004→0006), disable verbs (AgDR-0002), add-node search (AgDR-0009), broken-wire dialog (AgDR-0041), HostNodeV2 op grid (AgDR-0024), ai.plan hero render (AgDR-0021 today), Speckle wire transport (AgDR-0012 itself, kept).
- The founder's frustration signal triggered WORKSHOP-GATE (2026-05-25) which named the contradiction as a 3-day-minimum AgDR resolution.

The contradiction is not a bug in the code — it is a bug in the AgDR. AgDR-0012 named a substrate that didn't exist yet and never came.

## Options Considered

### A — Install ReactFlow + complete the P2.a-P2.d migration
| Dimension | Assessment |
|-----------|------------|
| Cost | 3-5 days, full rewrite of NodeView + WireLayer + drag + selection + sockets + groups + verbs |
| Risk | High — every interaction regresses; every shipped AgDR-0001..0044 feature needs re-verification |
| Value | Zero new user-facing capability (custom canvas already does all of it) |
| When done | Best case: parity with where we are today, minus four days of feature work |

### B — Supersede the lock; keep custom canvas as substrate (THIS DECISION)
| Dimension | Assessment |
|-----------|------------|
| Cost | 30 minutes (this AgDR + remove `NodeCanvasRF_Stub` + drop `archhub.canvas` localStorage) |
| Risk | Negligible — code removed is dead today |
| Value | Resolves the contradiction; closes FAILURE_LOG row 7; unblocks Settings panel from hosting a stub toggle |
| When done | Immediately — same iteration |

### C — Leave the contradiction; come back to it later
| Dimension | Assessment |
|-----------|------------|
| Cost | Zero now, compounding later |
| Risk | FAILURE_LOG entry stays open; next reader thinks the lock is real and writes code against ReactFlow that won't ever run; the founder's trust erodes further |
| Value | Negative |

## Decision

**Option B.** Custom canvas is the substrate of record. Remove the ReactFlow stub. Drop the feature flag. Update the architecture banner in AgDR-0012 (via this supersede note).

## Consequences

**Becomes easier:**
- New canvas features ship against one substrate, not two
- Settings panel doesn't carry a toggle to a non-existent option
- FAILURE_LOG row 7 closes; the gap class "named tech we never installed" is documented as a thing to never repeat
- Future readers of AgDR-0012 see the supersede pointer and don't write ReactFlow-target code

**Becomes harder:**
- If we DO want a ReactFlow rewrite later (for collaboration, web preview, or a feature only ReactFlow offers), it needs a fresh AgDR with a real cost/value justification — not "the lock said so"

**To revisit:**
- If a genuine ReactFlow-only feature surfaces (live cursors, collaborative cursors via ReactFlow's collab edition, web embedding), open a new AgDR

## Artifacts

- This AgDR
- Removal of `NodeCanvasRF_Stub` component + `_readCanvasFlavor` / `_setCanvasFlavor` from `app/web_ui/studio-lm.jsx`
- Removal of the `reactflow` localStorage key reference from Settings
- `docs/FAILURE_LOG.md` row 7 marked resolved
