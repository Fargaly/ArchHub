# Handoff — AgDR-0038: Composer Capability Nodes

- **Date:** 2026-05-22
- **From:** Revit revision-reconciliation session (founder-directed)
- **To:** ArchHub main / app-development session
- **Status:** action required — build it

## TL;DR

Build **AgDR-0038** (`docs/agdr/AgDR-0038-composer-capability-nodes.md`). It is
the mechanism that lets the **Composer create node types and wire them itself**
— as data, not hand-coded per node. Start with slice 1. Roadmap items are
seeded under M3 in `docs/ROADMAP.md`.

## Why this exists

The founder needs the Composer to mint + wire nodes without a human designing
every node type by hand (grammar `Primitive` + registry `NodeSpec` + executor +
library registration, per node). That O(n) hand-design is the bottleneck.

Prior attempts at "let the Composer create nodes" produced nothing because they
were approached as designing each node type from scratch. **They missed the
foundation that already exists:** `app/workflows/custom_nodes.py`.

`custom_nodes.py` already does declarative node specs — typed I/O, JSON,
persisted, registered to the live registry, typed ports on the canvas. It is
~60% of the answer. **Do not redesign. Extend it.** AgDR-0038 is the completion
plan.

## What exists vs what's missing

**Already built** — `custom_nodes.py` + `registry.py`: declarative specs, typed
`Port`s, `register_spec()`, the one `_build_executor()` factory, persistence,
`delete_spec()` (AgDR-0028), canvas port rendering via `node_grammar._ports_for`.

**Missing — the 4 gaps AgDR-0038 closes:**
1. No Composer tool surface — the Composer cannot reach `register_spec` / wire.
2. Executor substrate is code-or-passthrough only — no connector-op wrap, no AI.
3. No search → reuse → promote loop — LIBRARY-FIRST not enforced on minted nodes.
4. The `code` path is not sandboxed — `_build_executor` execs with full builtins.

## Build it — slices (full detail in the AgDR)

1. **Slice 1 — START HERE.** `impl` discriminator in `custom_nodes.py`
   (`python` / `connector` / `ai` / `passthrough`) + restrict the python
   sandbox + bare-`code` back-compat + grounding test. Smallest end-to-end.
2. Slice 2 — `impl.kind=connector` + `impl.kind=ai` executors.
3. Slice 3 — Composer tools in `tool_engine.py`: `node.search` / `node.create`
   / `node.place` / `graph.wire`.
4. Slice 4 — search → reuse → library auto-promotion loop.

## Process (do not skip — this is why prior work "resulted in nothing")

- AgDR-0038 is `proposed`. The founder (Fargaly) has directed it forward
  2026-05-22 — **merging the handoff PR is the sign-off.** Treat the AgDR as
  active; flip it to `executed` when slice 1 lands. The `/loop` AgDR gate is
  satisfied.
- Roadmap: the 4 slices are seeded under **M3** in `docs/ROADMAP.md` — the
  dispatcher picks them up.
- Per `CLAUDE.md` mandates: dive to the ROOT (extend `custom_nodes.py`, do not
  patch around it); tests green
  (`python -m pytest tests/ -q --ignore=tests/test_bridge_qt.py --ignore=tests/test_ui_smoke.py`);
  commit + record the AgDR; restart + CDP-verify on the live app before "done".

## Worked example — sanity-check the design

The structural revision-reconciliation workflow needed 2 bespoke nodes
(`pdf.extract_revisions`, `revit.reconcile_revision_table`). Under AgDR-0038
those are two Composer `node.create` calls carrying data specs — zero dev. The
AgDR §"Worked example" carries both. **If your slice-1 build cannot express
them as capability specs, the design is wrong — flag it, do not paper over it.**

## Reference

| File | Role |
|------|------|
| `docs/agdr/AgDR-0038-composer-capability-nodes.md` | the design |
| `app/workflows/custom_nodes.py` | the foundation to extend |
| `app/workflows/registry.py` | registry — already sufficient |
| `app/tool_engine.py` | where the Composer tools land (slice 3) |
