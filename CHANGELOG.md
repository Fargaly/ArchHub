# Changelog

## Next build

## 20261112-1644-514b937

- Home shows your open work only: sessions that are live, waiting for you, or from today. Interrupted, archived and stale ones sit under a folded "Older" heading.
- A row's title is the work, not the agent's name. Each avatar shows clear initials with a small state dot.
- Home step cards show what each step made: tables, text and thumbnails. The step that waits for you carries Approve, Ask why and Reject.
- A session with a plan shows its planned steps on its canvas, left to right with wires. The step count is the same in the Canvas title and the Inspector.
- Opening a file never changes it.
- Known gaps: several agents cannot yet join one session; sessions are not grouped by project; Canvas step cards do not show the design's preview pictures yet.

Source: b976a451..514b9379.

## 20261112-1419-b976a45

- Canvas: one Session node with fold-out rows (Agent, You, Parameters, Tools, Context, Thread) replaces the box of pinned nodes. The toolbar has Save, Automate, Run all, undo and redo. The Inspector has This task, Properties and Automate, with the Approve card and what the task made.
- Home: the sessions list opens on a wide window and is grouped under Needs you, Working now, Today, Earlier and Older, each with a count. Archived sessions sit under Older. Each agent has its own initials and colour.
- The composer is one row on Home and Canvas.
- A Settings node on a canvas stays linked to its setting after the file is reopened.
- Project names for sessions come from your registered workspaces.
- Known gaps: step cards do not show previews of what a step made yet; sessions are not grouped by project yet.

Source: 43c6e9be..b976a451.

## 20261112-0647-43c6e9b

- Workflows are listed apart from agent sessions, with an All | Workflows | Agent sessions filter.
- The Library has one category list. Unavailable cards explain why they cannot run.
- The Canvas opening view stays put after you begin using it.

Source: 1c973f7f..43c6e9be (69bb7a8d, 971bfae1, c509d80a, 6881fc01, 43c6e9be).

## 20261112-0420-1c973f7

- The composer floats without a footer band; the status line is in the header.
- The side bar has no separate Workshop or Automate pages. The layout adapts from 900 px upward.
- Home resumes work with Approve on the step that needs it. The Canvas opens at a readable scale and preserves saved views.

Source: f6dc2d1d..1c973f7f (80eb1a5e, 8060e877, 20978e10, 6087903c, 1a81dd49, 0acdf403, de07c897).

## 20261111-1409-f6dc2d1

- Workshop project labels route to the intended sessions; delivery results distinguish returned messages from confirmed delivery.
- Ended Workshop sessions no longer become successors for active roles.
- Disposable scratch cleanup checks linked destinations; isolated tests cover protected targets and external refusals.

Source: 47fb42e5, 989e15cd, 9c3b5fbd, fd900fc9, f6dc2d1d.
