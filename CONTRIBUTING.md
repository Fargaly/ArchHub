# Contributing to ArchHub

ArchHub runs a **self-driving review pipeline**. You do not have to chase
anyone for a review or a merge — the pipeline does it.

## The flow

1. **Branch.** Never commit to `main` directly — it is protected. Create a
   branch: `feat/...`, `fix/...`, `docs/...`, `chore/...`.
2. **Open a pull request** against `main`. (Use the PR template.)
3. **Automatic review.** Claude reviews every PR against the project
   mandates and posts a review. The Tests workflow runs on Windows,
   macOS, and Linux. CodeQL scans for security issues. The daily audit
   bot keeps watch on the repo as a whole.
4. **Automatic merge.** When the required checks pass, GitHub merges the
   PR by itself and deletes the branch. Nothing else is needed.
5. **If a check fails**, the PR does not merge. Fix it, push again — the
   pipeline re-runs from the top.

## Rules

- `main` is protected: a PR is required, required checks must pass, no
  force-push, no branch deletion.
- **Architecture-shaped change** (a new node kind, a data model, an
  interface, a wire/type contract, a user-facing surface) → write an
  AgDR in `docs/agdr/` first. See `CLAUDE.md` → "AGDR MANDATE".
- **One roadmap.** Plans and backlog live only in `docs/ROADMAP.md`.
- **Root-cause fixes, not patches.** See `CLAUDE.md` → "ENGINEERING
  MANDATE".
- Run the tests before pushing:
  `python -m pytest tests/ -q --ignore=tests/test_bridge_qt.py --ignore=tests/test_ui_smoke.py`
- Never commit secrets. Secret-scanning push protection blocks them.

## Who can contribute

- **Trusted contributors** are added as repo collaborators and branch
  inside the repo.
- **Everyone else**: fork the repo and open a PR from the fork — no
  write access to this repo is needed. A first-time contributor's
  workflow run needs a one-time approval before CI runs (GitHub's
  built-in guard for public repos).

Either way the rules above are identical and enforced automatically.
