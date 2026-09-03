# MAKE IT REAL — execution plan (2026-05-28)

> The founder's instruction, exact: stop trimming/deleting; root-cause why each
> thing is fake; if he asked for it or it helps the project, **make it real.**
> And root-cause the PROCESS that produced shells + two brains without planning.
>
> This plan is intent-first per the MAKE-IT-REAL-NEVER-TRIM +
> ONE-SYSTEM-PLAN-BEFORE-BUILD mandates. Nothing here gets deleted. Everything
> gets BUILT REAL or, in the rare justified case, removed only with the
> four-answer reasoning shown first.
>
> Design reference — not the roadmap. See `docs/ROADMAP.md`.

---

## Process root-cause: why we got shells + two brains

The founder asked "why this result in the first place? when did I ask for 2 brains?
why aggressive working without planning?" Honest answer:

1. **Two brains** — `app/memory/graph.sqlite` (AgDR-0042, the knowledge graph) was
   built first. Later `personal-brain-mcp/brain.db` (AgDR-0044, the daemon) was
   built as a SEPARATE store instead of extending the first. No migration plan.
   `brain_unify.py` is a manual band-aid papering over the split. **The founder
   never asked for two — they came from two un-reconciled AgDRs built in a rush.**
   This is a LIBRARY-FIRST violation at the architecture level.

2. **The fakes** — the UI was scaffolded with placeholder data (fake token counts,
   fake dates, fake tables) and stub call-styles (`bridgeJson` on async slots),
   then the WIRING step was skipped and the scaffold was reported "shipped." A
   shell passed as done. Same class as "primitives shipped, runtime pending."

3. **The common mechanism** — work was declared complete at the SCAFFOLD stage,
   before the real wire reached a real backend and a real click was verified.
   Nothing in the test/CI layer caught it, because the UI is "tested" by grepping
   the source as a string — a scaffold with a fake number passes the grep.

**The fix that makes it never-happen-again (item G):** a real-test gate — every
interactive element must reach a real bridge slot (verified by a real CDP click),
and no hardcoded fake-data strings allowed in the UI. The gate fails CI on a
naked shell. That is the workflow change the founder demanded.

---

## The 8 items — intent → real deliverable → verify → prevent

### 1 · Turn the brain ON (the ambient engine)
- **Intent / who asked:** AgDR-0044 + the BRAIN-FIRST mandate + the founder's
  brain vision ("ambient memory that learns from my work"). The engine is the
  whole point of the brain.
- **Why dormant (root cause):** `build_server()` registers tools but never starts
  the background workers; `skill_mint` persists a trace but never calls
  `reflect_on_trace`; `record_outcome` (calibration) is never wired. Pieces
  built, runtime never switched on.
- **Real deliverable:** start `SyncWorker` / `PublishWorker` / `ReflexionWorker` /
  `Watchdog` in the daemon boot (guarded, env-toggle to disable). Wire
  `skill_mint → reflect_on_trace → record_outcome` so a real trace mints a real
  skill and moves the calibration α/β.
- **Verify:** boot daemon → workers tick in logs → feed a real trace → a NEW skill
  appears in `brain.db` with non-seed provenance → α/β move off 1.0/1.0.
- **Prevent:** a daemon-health assertion that the workers are alive (not just
  tools registered).

### 2 · The UI fakes → REAL (never deleted)
Each fake is a thing someone meant to build. Make it real.
- **AIBody "Reply…" box + Send** — *intent:* continue an AI node's conversation
  from the canvas. *Real:* wire Send → `send_chat_history` for that node's
  conversation; append the turn; stream the reply. *Verify:* type + send → real
  model reply appears on the node.
- **OutputBody preview/save** — *intent:* preview a node's computed output + save
  it to disk. *Real:* preview reads the node's real last output value; save →
  a real file via a bridge slot (new `save_node_output` if none exists). *Verify:*
  run a node → preview shows real value → save writes a real file.
- **ServerStrip `4.2k tok · $0.024 · :7300`** — *intent:* show real usage + cost +
  server port. *Real:* pull from `get_provider_stats` / `cloud_usage` + the real
  server port from the running app. *Verify:* numbers match actual usage; change
  after a chat.
- **Conversation `WEDNESDAY · MAY 13` divider** — *intent:* group conversations by
  date. *Real:* compute the divider from real message timestamps. *Verify:* shows
  today's real date grouping.
- **ComposeBody schedule table** — *intent:* preview a node's scheduled trigger.
  *Real:* read the actual trigger config off the node; show real rows or an empty
  state. *Verify:* matches the node's real trigger.
- **Health issue → focus node** — *intent:* click an issue, canvas pans to the bad
  node. *Real:* add the missing `lm-focus-node` listener that pans + selects.
  *Verify:* click → canvas pans to the node.
- **~10 silent menu actions (flatten / expand / group / rename / duplicate …)** —
  *root cause:* `bridgeJson` (sync) called on async Qt slots → returns a Promise →
  truthiness fails silently. *Real (mechanism fix, one root → fixes all):* switch
  to `bridgeAsync` + await. *Verify:* each action produces its real effect.
- **`LM.paper` / `LM.accent2` undefined tokens** — *intent:* real theme colors.
  *Real:* define the tokens (or map to the correct existing ones). *Verify:*
  collapsed groups + BrokenWireDialog render real colors, not `undefined`.
- **~1000 lines of orphan panels (Chats/Skills/Search)** — *intent unclear → apply
  the four-answer test BEFORE any removal.* These may be earlier surfaces the
  founder wanted (a chats list, a skills browser, a search). If beneficial →
  resurface them REAL (wire to real slots). Removal only with the four answers
  shown. **Not auto-deleted.**

### 3 · Make the missing things EXIST (real, not stubs)
- **Procore** — *intent:* AEC workflows (RFIs, submittals, change orders) — clearly
  in-scope for an AEC tool; `procore_runner.py` (543 ln, real REST) was built for
  it. *Why missing:* no `procore_connector.py`, absent from `load_all_connectors`
  → unreachable. *Real:* write the connector wrapping the runner, register it,
  honest probe. *Verify:* Procore appears in the connector list; an op runs (or
  honestly reports `unauthorized` without a token).
- **Workflow↔connector contract break** — *intent:* typed host nodes
  (`host.read_walls` / `import_mesh` / `export_viewport` / `run_script`) should do
  real host work. *Why broken:* they call op-ids no connector implements. *Real:*
  implement the missing ops on the connectors (or correct the mapping to real
  op-ids), so a typed node cooks. *Verify:* a typed host node runs end-to-end.

### 4 · Deliver REAL, verified — not primitives (the discipline, applied to all)
- Every item above ends with an **adversarial real-check**: a separate pass that
  tries to prove the deliverable is STILL a shell / placeholder / primitive. If it
  can, the item is not done. This is the structural answer to "make sure they're
  really delivered." No item is reported done without its real-check passing on
  the running app.

### 5 · Two brains → ONE (unify, per ONE-SYSTEM mandate)
- **Intent:** the founder's single brain. He never asked for two.
- **Real deliverable:** unify to one store. Decide the canonical store, migrate the
  other into it ONCE, make the daemon + the extractors read/write the same store,
  and retire `brain_unify.py` as a one-time migration (not an ongoing band-aid).
- **Verify:** one store; the in-app brain view + the daemon report the SAME counts;
  no manual sync needed; `brain_unify.py` no longer required on a fresh run.
- **Prevent:** the ONE-SYSTEM mandate (added to CLAUDE.md).

### 6 · Reconcile governance books
- **Intent:** the mandates/AgDRs are the source of truth; they drifted.
- **Real:** fix CLAUDE.md's ARCHITECTURE LOCK ReactFlow line (contradicts executed
  AgDR-0048); flip the 6 AgDRs frozen at proposed/approved despite shipping; sync
  FAILURE_LOG vs the status docs; reconcile the stale `in_progress` tasks
  (including the founder-dropped Speckle-wire item).
- **Verify:** no AgDR/mandate contradicts shipped reality; one consistent ledger.

### 7 · Real UI tests (catch fakes so the founder never points again)
- **Intent (point 7):** the founder is tired of pointing out fakes; the test layer
  must catch them.
- **Real:** (a) CDP smoke tests in CI that actually click the top surfaces and
  assert real effects; (b) a static gate that fails CI on an interactive element
  with no handler reaching a real slot, or on a hardcoded fake-data string in the
  UI. Fix the CI/local ignore-set mismatch; replace the 2 inverted dead-code-pin
  tests with real behavior tests.
- **Verify:** the gate fails on a deliberately-introduced naked shell, passes on
  the real wiring.

### 8 · Anti-delete discipline (mandate landed) — applied everywhere
- The MAKE-IT-REAL-NEVER-TRIM mandate is now in CLAUDE.md. Every item above
  obeys it: intent-first, build-real, delete only with the four-answer reasoning
  shown. Item 2's orphan panels are the live test of it — they get the four-answer
  treatment, not the trash.

---

## Execution shape

Built by orchestrated agents, each item: **analyze intent → build real →
adversarial real-check**. File ownership prevents collisions; `studio-lm.jsx`
(all UI fakes) is owned by ONE agent (sequential within the file); the brain
package items are sequenced and contention-checked against the parallel session.
Brain unify (item 5) carries its own mini-design step before code, per the
ONE-SYSTEM mandate. Nothing ships "done" without its real-check green on the
running app.
