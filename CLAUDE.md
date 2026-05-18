# ArchHub — working memory

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
