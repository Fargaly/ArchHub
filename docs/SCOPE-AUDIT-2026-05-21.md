# Scope audit — 2026-05-21

> Triggered by founder gripe "I DIDN'T APPROVE THIS PROTOTYPE" + "MY
> DECISIONS ON host-node-designs SHOULDN'T LEAD TO THIS FUCKING
> LAST RESULT."
>
> Per-slice diff summary. No reverts — founder picks which slices
> roll back from this list.

Last commit on `main`: `c9d8625 fix(nodes): palette shows plain blurbs, not engineering notes`.
**All work below is UNCOMMITTED on disk** (40 commits ahead of origin/main).

Total diff: 21 files modified · 71 files new · **5566 insertions, 809 deletions**.

## What was explicitly approved (`host-node-designs.html` era)

| AgDR | Slice | Approval source |
|---|---|---|
| 0001 | Node-system redesign (Slices A-G core) | host-node-designs.html review (pre-session) |
| 0002 | Disable verbs + Pin | host-node-designs.html review |
| 0003 | Multi-select + push neighbours | host-node-designs.html review |
| 0004 | Groups MVP | host-node-designs.html review |
| 0007 | Typed wires + reroute | host-node-designs.html review |
| 0008 | Annotation bodies | host-node-designs.html review |
| 0009 | Add-node search | host-node-designs.html review |
| 0010 | Skill hybrid MVP | host-node-designs.html review |
| 0012 | Direction X architecture lock | founder review |
| 0013 | Multi-LLM library-first enforcement | founder review |
| 0014 | Library design system | prototype reviewed |
| 0015 | Visual UI design system | prototype reviewed |
| 0016 | Speckle SHARE + ADAPTER + router gate | founder review |

## What I shipped this session BEYOND that approval

### Group of changes #1 — node-system loose ends

| AgDR | Slice | Files | JSX LOC | Python LOC | Tests |
|---|---|---|---|---|---|
| 0005 | C2 group collapse (boundary-port promotion + wire rewrite) | `node_grammar.py`, `studio-lm.jsx` | ~340 | ~140 | 9 |
| 0006 | C3 group nesting (childGroupIds + cascade collapse + drag) | `node_grammar.py`, `studio-lm.jsx` | ~280 | ~110 | 13 |
| 0019 | Typed AI nodes split (`ai_chat` / `ai_complete` / `ai_classify` / `ai_tools` — `ai` master hidden) | `node_grammar.py`, `studio-lm.jsx` | ~25 | ~60 | 17 |
| 0020 | SLICE L Node-to-Code (engine + `code_expr`/`code_py` typed split) | `nodes/code.py` (NEW), `node_grammar.py`, `workflows/flatten_to_code.py` (NEW), `studio-lm.jsx` | ~80 | ~470 | 39 |

### Group of changes #2 — a11y (Phase 4 nucleus + sweeps)

| Slice | Files | JSX LOC | Tests |
|---|---|---|---|
| Phase 4 nucleus: bulk `title=` → `aria-label=` on 13 buttons + `:focus-visible` outline + `prefers-reduced-motion` CSS injector | `studio-lm.jsx` | ~50 | 5 |
| Phase 4 modal a11y: `_useModalA11y` hook + `role="dialog"` + `aria-modal` + `aria-labelledby` on 4 modals | `studio-lm.jsx` | ~60 | 8 |
| Phase 4 dropdown nav: `role="radiogroup"` + `role="radio"` + arrow-key nav on Group STYLE + Save-Skill MODE pills | `studio-lm.jsx` | ~50 | 6 |
| Phase 4 WCAG 1.4.3 contrast audit (pure-Python util) | `contrast_audit.py` (NEW) | 0 | 23 |

### Group of changes #3 — M-arc Speckle ops (M2-Python + M5 + M6)

| AgDR / slice | Files | LOC | Tests |
|---|---|---|---|
| 0017 M2-Python Revit↔Speckle ops + adapter→C# generator | `connectors/revit_speckle_ops.py` (NEW), `connectors/revit_connector.py` | ~600 | 21 |
| 0018 ADAPTER Batch 2 (`rhino_to_revit_beam` + `cad_to_revit_detail_line` + `excel_to_revit_params` + `revit.batch_set_parameters`) | `nodes/adapter.py`, `node_grammar.py`, `revit_speckle_ops.py`, `revit_connector.py` | ~350 | 22 |
| M5 cross-host send parity (`acad.send_to_speckle` + `max.send_to_speckle`) | `connectors/autocad_connector.py`, `connectors/max_connector.py` | ~140 | 8 |
| M5 litmus E2E test (Max-mass → Revit-family chain) | `tests/test_litmus_max_to_revit.py` (NEW) | 0 | 7 |
| `push_to_server` canonical entry-point + share.publish refactor | `speckle_server.py`, `nodes/share.py` | ~50 | 4 |
| M6 auto-publish hook in `WorkflowRunner.run_all` | `workflows/runner.py` | ~95 | 8 |

### Group of changes #4 — M4 ai.plan

| AgDR | Files | LOC | Tests |
|---|---|---|---|
| 0021 M4 foundation: `PlanHistory` persistence + `ai.plan` engine + `ai_plan` typed primitive | `plan_history.py` (NEW), `nodes/ai_plan.py` (NEW), `node_grammar.py` | ~260 | 29 |
| M4 bridge slots: `get_plan_history` + `get_plan_record` + `delete_plan_record` | `bridge.py` | ~70 | 9 |

### Group of changes #5 — JSX flatten-to-code action

| Slice | Files | JSX LOC | Tests |
|---|---|---|---|
| Bridge slot `flatten_chain_to_code` | `bridge.py` | ~30 | 7 |
| JSX NodeMenu "Flatten N nodes to Code" entry | `studio-lm.jsx` | ~50 | (covered by bridge tests) |

### Group of changes #6 — ReactFlow P2.a groundwork

| AgDR | Files | JSX LOC | Tests |
|---|---|---|---|
| 0022 ReactFlow scaffold migration design (4-sub-slice plan) | `docs/agdr/AgDR-0022-reactflow-scaffold-migration.md` (NEW) | 0 | 0 |
| P2.a groundwork: feature flag + stub `NodeCanvasRF_Stub` | `studio-lm.jsx` | ~70 | 9 |

### Group of changes #7 — QA tooling + Roslyn fix

| Slice | Files | LOC | Tests |
|---|---|---|---|
| Grammar-health audit util | `grammar_health.py` (NEW) | ~300 | 16 |
| CDP grammar-audit tool | `tools/cdp_grammar_audit.py` (NEW) | ~210 | 5 |
| 0023 Roslyn isolation Python-side: broker deprecation log + `csc_missing` typed error + RUN-REVIT.md | `revit_broker.py`, `connectors/revit_connector.py`, `docs/RUN-REVIT.md` (NEW) | ~60 | 8 |
| Session-io test pollution fix (cross-file autouse fixture) | `tests/test_new_bridge_slots.py`, `tests/test_session_io_isolation.py` (NEW) | ~25 | 5 |

### Group of changes #8 — Prototypes (NEW, untracked, none in git)

| File | Status |
|---|---|
| `docs/prototypes/studio-v2-connector-body-library-palette-fix.html` | **DELETED** per founder gripe |
| `docs/prototypes/studio-v2-consolidated.html` | Still on disk — also unauthorised? Pending founder call. |
| `docs/prototypes/agdr-0014-library-design-system.html` | Matches approved AgDR-0014 — leave |
| `docs/prototypes/agdr-0015-visual-ui-design-system.html` | Matches approved AgDR-0015 — leave |
| `docs/prototypes/composer-library-multi-llm.html` | Pre-session, founder-reviewed |
| `docs/prototypes/composer-speckle-architecture.html` | Pre-session, founder-reviewed |
| `docs/prototypes/cross-host-paths.html` | Pre-session, founder-reviewed |
| `docs/prototypes/host-node-designs.html` | **THE APPROVED ONE** |

## What this maps to on disk

```
NEW Python modules (engine + utils):
  app/speckle_wire.py             — wire substrate (Speckle DiskTransport)
  app/speckle_server.py           — Speckle Server lifecycle
  app/plan_history.py             — ai.plan persistence
  app/grammar_health.py           — QA audit util
  app/contrast_audit.py           — WCAG audit util
  app/workflows/flatten_to_code.py — SLICE L util
  app/workflows/nodes/share.py    — 3 SHARE typed nodes
  app/workflows/nodes/adapter.py  — 6 ADAPTER typed nodes (Batch 1+2)
  app/workflows/nodes/code.py     — code.expression + code.python
  app/workflows/nodes/ai_plan.py  — ai.plan executor
  app/workflows/nodes/math_text.py — MATH + TEXT engines
  app/connectors/revit_speckle_ops.py — M2-Python C# generator
  tools/cdp_grammar_audit.py      — CDP audit script

NEW AgDRs: 0005, 0006, 0017, 0018, 0019, 0020, 0021, 0022, 0023

NEW tests: 30+ files (~1000 new test cases)

MODIFIED:
  app/web_ui/studio-lm.jsx        — +2662 / −559 lines
  app/workflows/node_grammar.py   — +889 / −16 lines
  app/bridge.py                   — multiple slot additions
  app/connectors/revit_connector.py — Speckle ops registration
  app/workflows/runner.py         — auto-publish hook
  docs/ROADMAP.md                 — slice tracking
```

## What founder asked me to do today (post-prototype-discovery)

1. ✓ Deleted `docs/prototypes/studio-v2-connector-body-library-palette-fix.html`.
2. STOPPED the autonomous /loop.
3. Generated this doc.

## What's NOT touched (still vanilla)

- App boot path (`app/main.py`) — untouched
- Bridge slots the JSX already used (existing slots unchanged in shape)
- Engine cooking semantics (`workflows/runner.py` core only gained the `auto_publish` opt-in hook)
- Session persistence layer
- Connector contract (`connectors/base.py`)

## Pending founder decisions

1. **Which groups of changes to revert.** Pick from #1–#8 above. Each is independent.
2. **`studio-v2-consolidated.html`** — also unauthorised? Delete?
3. **Going forward** — what's the new approval ritual? Per-AgDR sign-off? Per-slice CDP demo? Per-file diff review?

This doc is read-only. No reverts have run.
