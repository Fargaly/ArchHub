# ArchHub — working memory

## SESSION-CLOSE MANDATE (founder, 2026-05-21 — non-negotiable)

After EVERY signed-off piece of work, before reporting "done":

1. **Commit** — every change committed (per the commit rules below);
   working tree clean.
2. **Document** — the AgDR (or, for a bug fix, the commit body)
   records root cause + fix + verification. `docs/ROADMAP.md` stays
   the single roadmap.
3. **Restart** — relaunch ArchHub so the running app reflects the
   committed code, and **CDP-verify the fix on the live app** — never
   report "fixed" from tests alone. The founder is a CEO, not QA.

A fix is not "done" until committed + documented + verified live.
Claiming a fix works without a live restart + CDP check is the
specific failure the founder called out 2026-05-21.

## ENGINEERING MANDATE (founder, 2026-05-15 — non-negotiable)

Every problem → dive to the ROOT. No quick patches. No stitching.

- Diagnose the actual cause, not the symptom. If a fix only addresses the
  instance in front of you, it is wrong.
- Fix the mechanism so the whole CLASS of bug cannot recur — then add a
  guard that catches it if it somehow does.
- Whack-a-mole (patching tag names, error strings, one call site) is
  failure. If you catch yourself doing it, stop and find the root.
- Verify the fix against the real running app, not just theory.
- The founder is a CEO, not a QA tester. Ship working solutions, not
  iterations that need his testing.

## ROADMAP MANDATE (founder, 2026-05-18 — non-negotiable)

ONE roadmap. `docs/ROADMAP.md` is the single source of truth for every
plan, backlog item, and milestone.

- Never create a second roadmap / plan / backlog file. New plans get
  appended into `docs/ROADMAP.md` — never spun off into their own doc.
- `docs/ROADMAP.md` is also the autonomous-loop seed: keep the section
  headers + `- [ ]` item format intact (parser: `agents/roadmap_source.py`).
- Architecture / design memos in `docs/` are reference only. Each
  carries a "design reference — not the roadmap" banner pointing back
  to `docs/ROADMAP.md`. Don't let them drift into parallel roadmaps.
- Root `ROADMAP.md` is a redirect stub — leave it pointing at
  `docs/ROADMAP.md`.

## AGDR MANDATE (founder, 2026-05-20 — non-negotiable)

Architecture-shaped work requires an **AgDR** (Agent Decision Record) in
`docs/agdr/` BEFORE any code. Adopted from apexyard's workflow-gates rule
(`github.com/me2resh/apexyard`).

- Any decision that locks an architecture, an interface, a node-kind /
  primitive, a data model, a wire / type contract, or the shape of a
  user-facing surface → write `docs/agdr/AgDR-NNNN-<slug>.md` first.
- Template: see `docs/agdr/AgDR-0001-node-system-redesign.md` —
  YAML frontmatter (id, timestamp, status, category) + Context +
  Options Considered (table) + Decision + Consequences + Artifacts.
- Surface contradictions and open forks in the AgDR — never resolve
  silently. If two existing docs disagree, the AgDR names the conflict
  and picks one, with rationale.
- Founder confirms key forks via discussion (chat / AskUserQuestion)
  before the AgDR ships executed. Status flips from `proposed` to
  `executed` only after founder sign-off.
- AgDR lives forever; supersede with another AgDR (`status:
  superseded by AgDR-NNNN`), never delete or rewrite history.
- The autonomous `/loop` "pick a slice and build" is GATED on an
  active AgDR for the slice's design class. No AgDR → no code.
- Bug fixes, tests, doc tidies, refactors that don't change
  architecture do NOT need an AgDR.

## ARCHITECTURE LOCK (founder, 2026-05-20 — non-negotiable)

Direction X is locked. See `docs/agdr/AgDR-0012-architecture-direction-x.md`.

- **Composer is the primary IDE.** Chat drives + edits + runs the graph.
  Canvas is the materialised execution + inspection surface.
- **Every wire is a Speckle `Operations.send/receive` segment.** Default
  `DiskTransport` at `.speckle/<project>/`. No server, no Docker, no
  account, fully offline. Cloud Speckle is opt-in collaboration.
- **`ai.plan` is a real canvas node** that persists each Composer turn
  as auditable + replayable artefact. Composer ≡ `ai.plan` engine; two
  surfaces.
- **ReactFlow is the canvas substrate** (committed earlier in session).

## LIBRARY-FIRST MANDATE (founder, 2026-05-20 — non-negotiable)

The library is the user's living inventory of every placeable +
composable artefact. The agent obeys these rules:

- **`library.search` is called BEFORE `library.create_node_type`.**
  Enforced via system prompt + Anthropic `strict: true` tool use.
- If a match is found (≥0.75 similarity on intent + I/O schema), USE
  the existing node. No silent duplicates.
- New nodes the agent mints MUST be MODULAR: typed inputs, typed
  outputs, `config_schema` (parameterised — no hard-coded literals in
  the body), `description`, and `examples` for future similarity
  matching. The library validator rejects non-modular specs.
- New nodes are registered to the library on creation, not on save.
  Library grows by use.

## USER-AGENCY MANDATE (founder, 2026-05-20 — non-negotiable)

- **Library is always browsable.** Cmd-K opens it. Side-panel library
  tab stays. Composer NEVER replaces these — it complements them.
- **Canvas is always directly editable.** Right-click, drag-rewire,
  inline param edits, multi-select / group / Alt-drag from slices
  B2/C — all stay.
- **Every AI write to a host is approval-gated by default.** Composer
  has three modes: **Plan** (default, gated on writes), **Auto** (auto
  reads, gated writes), **YOLO** (auto everything, opt-in, reversible).
- **Every action is reversible.** Speckle Versions are immutable
  content-addressed; undo = receive previous Version.
- **Approval surfaces are typed errors with named recoveries**, not
  freeform retry prompts.

## What ArchHub is

PyQt6 + QtWebEngine desktop AI workspace for AEC professionals. Graph-first
canvas: users wire nodes (hosts, AI conversations, filters, connector ops)
together. React/JSX UI (`app/web_ui/studio-lm.jsx`) loaded via Babel-standalone,
talks to Python via a QWebChannel bridge (`app/bridge.py`).

## Commands

- Launch: `pythonw app/main.py` (cwd = repo root)
- Tests: `python -m pytest tests/ -q --ignore=tests/test_bridge_qt.py --ignore=tests/test_ui_smoke.py`
- DevTools: relaunch with env `QTWEBENGINE_REMOTE_DEBUGGING=9223`, inspect at `http://localhost:9223/json`

## Hard-won root causes (do not regress)

- QWebChannel slots are **async** — return a Promise, never a value
  synchronously. Any JS that calls a slot must await. `index.html`
  `bridgeJson` + `studio-lm.jsx` `bridgeAsync` handle this.
- Slow work in a `@pyqtSlot` (host probes, LLM calls, COM/HTTP) **must**
  run on a background thread + emit a signal — never block the Qt main
  thread or the UI freezes ("Not Responding").
- An LLM with no real tool, asked a question needing one, **fabricates**
  a tool call. Fix = give it real tools (tools follow host reachability,
  not a settings toggle), not prompt-policing tag names.
- Connectors must report honest status (`live`/`loaded_dead`/`missing`/
  `unauthorized`) and never fabricate data when a host is offline.

## Key files

- `app/bridge.py` — QWebChannel bridge, all JS-facing slots + signals
- `app/web_ui/studio-lm.jsx` — the entire React UI (~5k lines)
- `app/connectors/base.py` — uniform connector contract (16 connectors, 116 ops)
- `app/tool_engine.py` — `ToolEngine` + `TOOLS`; the LLM's real tool surface
- `app/host_detector.py` — host reachability probes
- `app/workflows/` — graph, runner (lazy/dirty/cached cook), triggers
- `docs/ROADMAP.md` — THE roadmap: single source of truth + loop seed
- `docs/*_PLAN.md`, `docs/*_RND_*.md` — design references only (banner-marked)
