# ArchHub — working memory

## DEFINITION-OF-SHIPPED MANDATE (founder, 2026-05-25 — non-negotiable)

"Shipped" has ONE meaning: the founder can launch ArchHub, click around
for 60 seconds without instructions, and SEE the thing working.
Anything less is "written," not shipped.

- **User-visible path.** Every shipped feature has a continuous code
  path from a visible UI affordance (button, panel, command, hotkey)
  through `bridge.py` to the backend and back. Code that exists only
  in a module nothing reaches is a draft, not a ship.
- **60-second discoverability.** A user who has never seen the feature
  finds it within 60 seconds of opening the app, with no founder
  coaching. If discovery needs a paragraph of instructions, the
  feature isn't shipped — the entry point is missing.
- **Visual proof, not test logs.** Reporting "shipped" REQUIRES a CDP
  screenshot of the live ArchHub window showing the feature engaged
  (clicked, opened, executed), captured AFTER restart on the
  committed HEAD. Unit tests passing ≠ shipped. Server-side logs ≠
  shipped.
- **Real interaction.** Claude clicks the affordance via CDP
  `Runtime.evaluate` or computer-use, observes the resulting DOM /
  network / state change, and includes the before/after evidence in
  the report.
- **Honesty floor.** If any of the above is missing, the word "shipped"
  is BANNED from the report. Use "wired but not exposed," "merged but
  unverified," or "drafted" — never "shipped."

## PROTOTYPE-IS-CONTRACT MANDATE (founder, 2026-05-25 — non-negotiable)

When the founder signs off on a prototype (HTML mock, Figma, sketch,
`docs/prototypes/*`), that artifact IS the spec. The shipped JSX
mirrors it 1:1 — layout, copy, spacing, colors, icons, motion. No
"interpretation."

- **Pixel-anchored.** The shipped surface and the signed prototype
  open side-by-side and look the same. Material differences are bugs,
  not stylistic choices.
- **Prototype lives in repo.** Signed prototypes move to
  `docs/prototypes/signed/<slug>/` with a frozen timestamp + AgDR
  reference. They are read-only after sign-off — modifications
  require a new AgDR.
- **Diff before claiming parity.** Before reporting any
  prototype-derived feature shipped, run a visual diff: CDP screenshot
  of the running JSX vs. the prototype render, side-by-side in the
  report. Drifts > a few px or any copy change require either fixing
  the JSX or a written deviation note in the AgDR — never silent
  drift.
- **Founder's eye is the test.** If the founder opens the app and says
  "this is not what I signed off on," the prototype wins. Roll forward
  to parity, not backward to argument.

## NO-OPEN-THREADS MANDATE (founder, 2026-05-25 — non-negotiable)

A loop iteration ends with ZERO open threads. "I'll test it later,"
"we can wire that up next," "leaving a TODO for the founder" are the
failure modes the founder banned 2026-05-25.

- **Closed thread definition.** Every change in the iteration is: (a)
  committed, (b) live-verified on the running app, (c) documented in
  AgDR or commit body, (d) free of `TODO(founder)`, `XXX`,
  `FIXME(later)`, and "for testing" stubs in code touched this
  iteration.
- **No deferred work to the founder.** Tasks tagged "founder to test,"
  "founder to confirm visually," "founder to click through" are
  forbidden in commit messages and reports. Either Claude verifies it
  via CDP, or the work is not done.
- **Per-iteration grep gate.** Before declaring loop iteration
  complete, run `grep -nE "TODO\(founder\)|FOUNDER:|to be tested|verify in app$"
  -- <files-touched-this-iteration>`. Any hit blocks the "done"
  report until resolved.
- **Roadmap reconciliation.** Any item moved from `- [ ]` to `- [x]`
  in `docs/ROADMAP.md` has a verified-live receipt (screenshot +
  commit SHA) linked in the iteration summary. Unchecked items don't
  disappear — they're either kept open or explicitly cancelled with
  reason.

## PRE-FLIGHT-CHECK MANDATE (founder, 2026-05-25 — non-negotiable)

Before the word "shipped," "done," "delivered," or "complete" appears
in a report, Claude runs this 7-question check internally. Each answer
comes from a tool call, not memory. ANY "No" → not shipped.

1. **Built?** Does `git status` show a clean tree AND `git log -1`
   show the change committed?
2. **Restarted?** Has ArchHub been killed and relaunched on the
   committed SHA in this iteration (process PID newer than the commit
   timestamp)?
3. **Reachable?** Does CDP `http://localhost:9223/json` return the
   expected page with the new bundle hash loaded?
4. **Visible?** Does a CDP `document.querySelector` for the new
   affordance (data-testid, aria-label, or unique text) return a node
   with `offsetParent !== null`?
5. **Clickable?** Does dispatching a click via CDP produce the
   observable state change (DOM mutation, network call, log line,
   panel open)?
6. **Persistent?** After the interaction, does relaunching the app
   preserve the resulting state (if state-bearing)?
7. **Discoverable?** Is the entry point reachable from the default
   open view in ≤ 3 user actions without console / DevTools?

The check runs as `tools/preflight.ps1` — its output is pasted
verbatim into the report. Reports without the preflight block are
rejected by the founder by default.

## POST-LOOP-AUDIT MANDATE (founder, 2026-05-25 — non-negotiable)

After every `/loop` iteration, before reporting "done," Claude runs
the audit below via `tools/loop_audit.ps1`. The audit output IS the
iteration summary plus a 2-line founder-facing recap.

The audit performs, in order:
1. `git log --oneline <iteration-start-sha>..HEAD` — every commit in
   the iteration listed.
2. `git diff --stat <iteration-start-sha>..HEAD` — every file touched.
3. For each file touched: `grep -nE
   "TODO\(founder\)|FOUNDER:|FIXME\(later\)|verify in app$|for testing"`
   — must be empty.
4. Process check: ArchHub PID + start time, confirming
   restart-after-commit.
5. CDP probe: bundle hash on `http://localhost:9223/json` matches the
   JSX file hash on disk.
6. For every roadmap item flipped to `- [x]` this iteration: a CDP
   screenshot named `proof_<roadmap-id>_<commit-sha>.png` under
   `proofs/<date>/`.
7. AgDR check: every architecture-shaped commit links to an `executed`
   AgDR.

The audit BLOCKS the "done" report when any step fails.

## ROLLBACK-PROTOCOL MANDATE (founder, 2026-05-25 — non-negotiable)

When the founder opens the app and the thing Claude called "shipped"
is missing, broken, or different from the prototype, the response is
NOT a TODO and NOT an apology — it's an immediate rollback-or-finish.

- **Acknowledge in one line.** "The N preflight checks I claimed
  passed did not actually pass — re-running now." No paragraphs, no
  excuses.
- **Re-run preflight live, paste result.** The founder sees the actual
  Y/N grid that should have been run the first time.
- **Decision: finish or revert.** Within the SAME response cycle,
  either (a) close the gap and re-verify end-to-end with CDP proof,
  or (b) revert the misleading commit with `git revert <sha>` and
  re-open the roadmap item. No third option ("I'll fix it next
  iteration") is permitted.
- **Update the failure log.** Append a one-line entry to
  `docs/FAILURE_LOG.md`: date, claim, gap found, resolution. The log
  is read at the start of every loop iteration so the same gap class
  doesn't recur.
- **No new feature work** until the gap is closed. Loop pauses;
  founder doesn't have to ask.

## WORKSHOP-GATE MANDATE (founder, 2026-05-25 — non-negotiable)

Claude STOPS shipping and convenes a workshop (multi-hat,
AgDR-anchored) when ANY of the trigger conditions below fire.
Shipping over a fired trigger is itself a process violation.

Trigger conditions:
- **Ambiguity hit.** A spec / prototype has two plausible readings
  and resolving silently would risk the prototype-is-contract
  mandate.
- **Cross-surface change.** A change touches ≥ 3 of:
  `studio-lm.jsx`, `bridge.py`, `tool_engine.py`, a new connector,
  the workflow runner, or the canvas substrate.
- **Founder frustration signal.** The founder uses any of: "fed up,"
  "different shit," "open threads," "not what I signed off,"
  "fucking" + critique. STOP, convene, do not patch.
- **Repeat regression.** A bug whose class has been "fixed" before
  reappears. Engineering mandate says fix the mechanism — that
  requires design, not another patch.
- **Preflight fails twice in a row** on the same feature.
- **Loop iteration produced zero verified ships.** The loop is
  spinning without landing. Stop, audit, design.

Workshop output is an AgDR (per existing AGDR mandate) + a closed
thread of next actions. Only after the AgDR ships `executed` and the
founder confirms does shipping resume.

## AUTOMATION MANDATE (founder, 2026-05-22 — non-negotiable)

Never hand the founder a checklist of manual steps. The founder is a
CEO, not a task-runner. "You do X, then Y" is a failure.

- Anything doable from the machine — DO IT. Install + run the CLI
  (`fly`, `gh`, `stripe`, `npm`, `dotnet`, …) via Bash/PowerShell;
  drive apps via computer-use; script it. Execute, don't describe.
- Anything that needs a repeatable external interaction — build an MCP
  server for it and use it. Automate, don't delegate.
- Before claiming something needs the founder, CHECK the machine: is
  the CLI installed, is it already authenticated, is the key already
  in `.env` / secrets? Assume nothing — verify.
- The ONLY actions that may return to the founder are the hard safety
  limits: creating an account, a purchase / entering card details,
  typing a password. Even then — do everything up to that one step,
  then name that single action. Never a list.

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
