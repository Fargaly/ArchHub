---
id: AgDR-0041
timestamp: 2026-05-24
status: executed
founder-signoff: 2026-05-24 — picks recorded on docs/prototypes/graph-robustness-2026-05-24.html (r1–r6 all YES, r2 right-click variant)
category: architecture
supersedes: none
builds-on: [AgDR-0001, AgDR-0040]
---

# AgDR-0041 — Graph robustness: swap, freeze, delete, validate, bypass

> **Executed 2026-05-24.** All 6 properties shipped in one /loop
> session. Founder reviewed
> `docs/prototypes/graph-robustness-2026-05-24.html` and signed off
> r1–r6 (r2 right-click variant). Substrate landed before Tier 0
> ComfyUI + DashScope connectors as planned — the 4 use cases
> (Revit→render, photo→mass, drone→walls, text→plan) run on top.
>
> Shipping commits (all 2026-05-24):
> - P3 + P6 tools + UI badges      · `8fda8b2`
> - P6 runner bypass                · `10b0f76`
> - P1 typed host nodes             · `2406c4a`
> - P5 structured validator         · `c348ffe`
> - P2 swap suggestions             · `c99f918`
> - P4 delete decision matrix       · `9c6e870`
>
> Backend complete. UI surfaces (GraphHealthPanel · BrokenWireDialog ·
> swap-with menu) are next-session work.

## Context

Founder, 2026-05-24: *"this allows the user to swap nodes and things
should still work fine. user can swap rhino with 3ds max, or revit or
blender. maybe a user freezes or deletes the upscale node. do you
get me?"* — and later *"allow for ignoring the node entirely dropping
it from the workflow if possible like stopping it like freezing but
without even taking the cached values."*

Translation: the graph must survive structural edits without breaking
the user's flow. Today AgDR-0001 gives us typed Ports and AgDR-0040
gives us `impl.kind=graph` recursion. We have the substrate. We do
NOT have the operations that let users morph a graph mid-flight —
swap providers, freeze expensive nodes, bypass on demand, delete
intermediates without dead wires, see type mismatches before cook.

Adding these operations is **assimilation, not redesign** (per the
2026-05-24 mandate): each property maps onto an existing module
with a small extension.

## Options considered

| # | Option | Verdict |
|---|--------|---------|
| 1 | Ship use cases first, robustness later | ✗ users hit dead-ends on day 1; rework cost dominates |
| 2 | Per-property AgDRs (six separate) | ✗ all six share the same edit-time data flow; six AgDRs fragment the design |
| 3 | One AgDR covering all six properties, ships before use cases | ✓ **chosen** — coherent design, lands as substrate |

## Decision

Six robustness properties ship together, all assimilated into existing
files (zero new top-level architecture):

### Property 1 — Host swap (typed variants)
`host.import_mesh`, `host.read_walls`, `host.export_viewport` etc. each
carry a `host` selector param (`revit | rhino | 3dsmax | blender`).
Same wire, change one dropdown → different desktop app. Already
supported by AgDR-0001's connector primitive selector pattern; we
add the typed variants in `app/workflows/nodes/host/*.py`.

### Property 2 — Type-compatible swap (right-click "swap with…")
Per founder pick `r2 = YES — but only on right-click "swap with…"`,
not surfaced in Inspector permanently. New tool
`library.suggest_swaps(node_id) → [{type, score, port_match}]` wraps
existing `node_search` with port-type filter. UI: right-click context
menu lists alternatives ranked by I/O compatibility. Click to swap
in place; runner re-cooks downstream.

### Property 3 — Freeze ❄ (per-node)
Per founder pick `r3 = YES — freeze ships per-node`. New `node.frozen`
bool. Runner: if `frozen`, skip dirty-check + return cached output.
Upstream changes ignored until unfrozen. UI: ❄ badge top-right of node,
Inspector toggle + "Force re-cook" button. Hash mismatch warning when
upstream changes vs cached input hash.

### Property 4 — Delete with auto-bridge
On `graph.on_node_delete(id)`:
1. Inspect upstream src port type vs downstream dst port type.
2. If exact match OR src is sub-type of dst → silent auto-rewire.
3. If mismatch → broken-wire state + Inspector recovery dialog offering:
   (a) insert adapter (`node_search(in_type=src, out_type=dst)`),
   (b) restore deleted, (c) swap downstream node.

### Property 5 — Live validator
Validator runs on every graph edit (debounced 200ms). Wires + nodes
light up **green** (valid) / **yellow** (partial — optional input
unset) / **red** (type mismatch, blocked). New `graph.validate()` tool
returns issue list; new `GraphHealthPanel` React component shows
totals + click-to-focus issues. Cook button gains "Cook valid + partial,
skip broken" affordance.

### Property 6 — Bypass ○ (per founder addition 2026-05-24)
`node.bypassed` bool. Runner skips `execute()` entirely. Upstream
input port → downstream output port via greedy (name, type) match;
ambiguous mappings trigger Inspector pair-prompt. **No cache held**,
re-cooks on each upstream change. UI: dashed border + ○ badge.
Node state cycle: `Active ⇄ Frozen ❄ ⇄ Bypassed ○ ⇄ Deleted ⨯`.

## Consequences

- **User confidence** — every structural edit has a predictable
  outcome. No "I deleted a node and the whole graph is dead."
- **Provider portability** — swap Anthropic↔Qwen↔OpenAI without
  rewiring; swap Revit↔Rhino without lifting a finger.
- **Cost control** — freeze + bypass let users avoid burning paid
  API calls during iteration.
- **Composer affordance** — when Composer mints a graph, it can
  emit nodes with `bypassed=true` for "optional polish" stages,
  letting users opt in.
- **Test surface grows** — +18 new tests (3 per property) join the
  existing 186 cloud_backend + 2172 app tests.

## Build slices

1. **Slice 1** — typed host variants (P1) + runner `frozen` / `bypassed`
   bool support (P3, P6).
2. **Slice 2** — `graph.on_node_delete` decision matrix (P4) + adapter
   search.
3. **Slice 3** — live validator (P5) + `GraphHealthPanel` UI.
4. **Slice 4** — Inspector right-click swap menu (P2) + state-cycle UI
   polish (❄ / ○ badges, dashed border, state cycle indicator).

## Artifacts

- This AgDR.
- `docs/prototypes/graph-robustness-2026-05-24.html` — 6-property visual
  mock + Inspector mocks + decision tables (founder reviewed).
- `app/workflows/runner.py` — `frozen` / `bypassed` checks in `_pull`.
- `app/workflows/graph.py` — `on_node_delete` decision matrix.
- `app/workflows/nodes/host/*.py` — typed host variants.
- `app/library.py` — `suggest_swaps()` + `find_adapter()`.
- `app/tool_engine.py` — `node_freeze` / `node_bypass` / `library_suggest_swaps`
  / `graph_validate` tools.
- `app/web_ui/studio-lm.jsx` — Inspector swap menu, ❄/○ badges,
  `GraphHealthPanel`, `BrokenWireDialog`.
- `tests/test_graph_robustness.py` — 18 new tests.
