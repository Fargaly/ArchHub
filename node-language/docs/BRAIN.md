# The Personal Brain

> **Reference — not the roadmap.** `docs/ROADMAP.md` is the single source of
> truth for plans and milestones. This page describes the brain as it runs
> **today** (audited 2026-06-18 against `personal-brain-mcp/`). For how the brain
> syncs to the cloud, see `docs/BACKEND_SPEC.md`.

The **personal brain** is ArchHub's memory. It is a small background program (a
"daemon") that runs on your machine, remembers what you and the AI do, and feeds
that memory back into every new session so the assistant starts already knowing
your context instead of from a blank page.

This is the core idea ArchHub is built around: **brain-first**. Every session —
and every AI agent — checks the brain before it starts work.

## What it is

- A local daemon that listens on **port 8473** (`http://127.0.0.1:8473`). Its
  health check is `http://127.0.0.1:8473/healthz`.
- It keeps a small SQLite database on your machine. That database holds three
  kinds of thing:
  - **Facts** ("fragments") — what you and the AI have learned: notes, decisions,
    references, traces of past work.
  - **Skills** — reusable procedures the AI has minted from successful work, so a
    task done once can be replayed.
  - **Wiring** — which tools, apps, and connectors (MCPs/CLIs) are available on
    each of your devices.
- It is **bound to you**. Once you sign in, the brain records its owner, so your
  memory is yours and shared firm/community memory is kept separate.
- Your memory also keeps a private copy on ArchHub Cloud
  (`https://archhub-cloud.fly.dev`), so the brain follows you across devices.

## The six workers

The brain is not just storage — it is an **engine**. When the daemon starts, it
spins up six background workers that keep your memory healthy and in sync. They
run automatically (you can turn the engine off with the `BRAIN_WORKERS=0`
environment variable, but on is the default).

| Worker | What it does |
| --- | --- |
| **Sync** | Periodically syncs firm/project/community memory between teammates (a conflict-free merge — everyone converges, nobody overwrites). |
| **Personal cloud sync** | Syncs **your** personal memory up to your private copy on ArchHub Cloud, privacy-redacted. Inert until you sign in. This is what lets your brain follow you across devices. |
| **Publish** | Publishes privacy-noised patterns to the shared federation outbox, when enabled. |
| **Reflexion** | Watches your finished work and mints reusable skills from the successful runs. |
| **Organize** | Periodically tidies memory — re-embeds new facts and re-groups them — so search and recall stay sharp as memory grows. |
| **Watchdog** | Monitors the other workers and restarts any that stop, so the engine keeps running unattended. |

## How the app shows it

You do not have to read a database to see the brain working. The desktop app
surfaces it live:

- **The brain indicator (BrainChip).** A small live readout near the model strip
  shows `brain · N skills · M facts` and the recall time of the last lookup. The
  numbers come straight from the running daemon (the bridge slot
  `get_brain_stats` in `app/bridge.py`, which reports `skills`, `facts`,
  `secret references`, and the retrieval time of the last memory hit). It updates
  on its own as the brain learns.
- **The brain view (BrainViewModal).** Clicking the indicator opens a full-screen
  view of what the brain holds — your facts, skills, and wiring — using the same
  live data path. It is the window into your memory.
- **Settings → Brain.** Shows the daemon's health, your firm identity, the team
  invite/seat controls, and tuning. If the daemon is down, this is where you see
  it and can bring it back.

When the daemon is not running yet, these surfaces show an honest "starting /
sign in to enable" state rather than a fake number.

## The brain-first operating model

Every ArchHub session — and every AI agent or collaborator working in the repo —
follows the same loop:

1. **Connect first.** Before doing any work, check the brain is up
   (`brain.health` on port 8473). If it is down, start it, do not skip it.
2. **Announce.** Tell the brain where you are (working folder, git remote, which
   tools are available) so it knows whether this is personal, project, or firm
   scope.
3. **Recall on every prompt.** Each new request pulls relevant context from the
   brain and attaches it, so the assistant answers with your history in mind.
4. **Remember as you go.** Each successful action writes back to memory, so the
   next session sees what this one did.
5. **Mint skills on close.** At the end of a session, successful work can become a
   reusable skill.

The point: memory is not a side feature. It is the moat. The brain is what makes
ArchHub get better the more you use it, and what lets it pick up where you left
off on any device.

## Privacy

- Your personal memory stays **private to you**. Firm and community memory is a
  separate, deliberately shared layer; the owner of any shared item is stamped by
  the server, so nobody can pose as someone else.
- The brain stores **references** to secrets (`op://…`), never the secret values
  themselves; the actual keys are resolved at the moment of use and never written
  into memory.
- The cloud copy of your brain is privacy-redacted before it leaves your machine,
  and it lives in your own per-account folder on the encrypted cloud disk (see
  `docs/USER_DATABASE.md`).
