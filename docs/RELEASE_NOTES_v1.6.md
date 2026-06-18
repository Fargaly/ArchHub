# ArchHub v1.6.0 — release notes

> Reference — not the roadmap; see [docs/ROADMAP.md](ROADMAP.md).

This release makes the parts of ArchHub that were already working *visible*, and
consolidates the latest design into the running app.

## What you will see

- **Your account, always in view.** A chip in the top bar shows that you are
  signed in, your plan, and how many messages you have left — sourced from the
  live cloud account, not a placeholder.
- **The brain shows its real size on open.** The brain chip now reads its live
  count (skills + facts) the moment the app starts, instead of saying "idle"
  until your first chat.
- **The router stops being a black box.** Under each answer you see which model
  replied, and a live note when it switches provider (for example, one provider
  is out of credit so it falls back to another).
- **Update from inside the app.** When a new signed release is available you get
  an "update available" banner; one click installs it and relaunches — no manual
  download.
- **Sessions sync to the cloud.** A "Sync sessions" control on the home screen
  pushes and pulls your node-graph sessions so they follow you across machines.
- **A Team screen.** Create a firm, invite teammates by email, and assign roles
  (owner, admin, member) with seats — backed by the live permissions model.
- **A Self-Heal Inspector.** A live timeline of the recoveries ArchHub performs
  on its own — host reconnects, connector re-loads, graph repairs — with an
  honest empty state when nothing has needed healing.

## Design

- The design tokens are now a single source of truth (`tokens.jsx` /
  `window.AH`): terracotta accent, the Architects Daughter wordmark, a 12-step
  type scale, a canvas tracing grid, and a consistent wire vocabulary.

## Under the hood

- Never-blank GPU path with software-render self-heal; viewport-culled canvas
  for a fast graph at scale.
- Reference documentation for the cloud backend, user database, permissions, and
  the brain (see `docs/BACKEND_SPEC.md`, `docs/USER_DATABASE.md`,
  `docs/PERMISSIONS.md`, `docs/CLOUD_API.md`, `docs/BRAIN.md`).
- Line-ending policy pinned for the JSX bundle so the build hash is stable across
  Windows and CI.
