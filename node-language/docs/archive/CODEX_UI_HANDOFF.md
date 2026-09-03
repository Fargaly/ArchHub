# Codex UI Handoff

Date: 2026-05-13

Codex owns the Studio UI pass for now.

## Ownership Boundary

Codex is actively editing:

- `app/studio_shell.py`
- `app/main.py` startup hook for local dev-source sync
- `app/dev_source_sync.py`
- `app/release_updater.py`, `app/chat_window.py`, and `installer/setup.iss` staged-update flow
- Studio shell layout, rail, account menu, inspector, quick actions
- UI behavior that maps to the prototype in:
  `C:\Users\fargaly\Documents\Codex\2026-05-13\what-is-the-latest-most-stable\archhub-ui-prototype.html`

Claude should avoid editing those surfaces while this pass is open. Backend, cloud, connectors, agent runners, tests, quotas, and non-shell bug fixes are safe for Claude.

## Current UI Decisions

- Settings is a single workspace page in the left rail.
- The bottom user-card gear is account-only: Profile, Cloud sync, Plan and billing, Switch theme, About ArchHub.
- The right inspector must be contextual or hidden.
- No permanent LLM router billboard in the right rail.
- Home inspector shows project pulse and AEC actions.
- Chat inspector shows live parameters and session actions.
- Skills, Marketplace, Pricing, Telemetry, Settings, and Workflows hide the inspector unless a future page-specific inspector has real task value.
- Quick actions must be concrete AEC or session actions, not generic navigation.

## Reference DNA

The target product feel comes from Fargaly's preferences:

- Notion: calm, editable, organized workspace
- Claude Code: fast, keyboard-first, direct feedback
- LM Studio: transparent local/remote model control
- ComfyUI: node workflows, live parameters, rerunnable stages

## Local App Sync

The installed `%LOCALAPPDATA%\ArchHub` copy now syncs from the configured git checkout on startup through `app/dev_source_sync.py`. It copies code/docs/install assets only and preserves user data such as settings, sessions, workflows, logs, renders, and data repositories.

Current configured source checkout:

`C:\Users\fargaly\00.ARCHUB\ArchHub`

If Claude changes the repo, relaunching the installed app should pull those local changes into the installed copy before Qt imports the UI.

## Release Update Flow

Default `prompt` mode now means:

1. ArchHub checks GitHub Releases in the background.
2. If a newer installer exists, ArchHub downloads it.
3. ArchHub stages/runs the installer silently with `/ARCHHUB_STAGE=1`, `/NOCLOSEAPPLICATIONS`, and `/NORESTARTAPPLICATIONS`.
4. The in-app banner says the update is installed and asks the user to restart.
5. The Restart button only relaunches ArchHub; it does not run the installer at click time.
