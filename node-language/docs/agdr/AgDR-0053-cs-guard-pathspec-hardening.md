---
id: AgDR-0053
title: cs-guard pathspec hardening — make the broker .cs guard match direct children of payload/sources/, not just subdirectories
timestamp: 2026-06-02
agent: claude-code (Opus 4.8)
session: governance-cs-guard-pathspec-hardening
status: executed
category: governance
projects: [archhub]
supersedes: null
superseded_by: null
founder-signoff: GRANTED 2026-06-02 — founder explicitly directed this guard-hardening fix in chat (AGENTS.md §1 protected-file flow). This record documents the fix; it STRENGTHENS the existing guard and does not change any broker contract.
executed: "Executed 2026-06-02 — founder authorized the .githooks hardening in chat; pathspec swapped at all 3 guard sites to ':(glob)payload/sources/**/*.cs'."
predecessor_verified: "AgDR-0050 (no-brain-on-commit floor) executed 2026-06-01 — its brain-commit-gate block in pre-commit/pre-push is left untouched by this change; both hooks remain sh -n + bash -n clean after the edit."
---

> **STATUS: Executed 2026-06-02.** Founder-authorized guard-hardening of the
> protected `.githooks` (AGENTS.md §1 — the founder explicitly directed this fix
> in chat). The broker `.cs` guard's pathspec was changed at **all 3 sites**
> (one in `.githooks/pre-commit`, two in `.githooks/pre-push`) from
> `'payload/sources/**/*.cs'` to `':(glob)payload/sources/**/*.cs'`. Nothing else
> in either hook was touched — the `ARCHHUB_ALLOW_CS_EDIT=1` short-circuit, the
> AgDR-0050 brain-commit-gate block, the exit codes, the branch-deletion /
> new-branch-range logic, and the human-facing heredoc messages are all
> unchanged.

## Context

The broker `.cs` guard (AGENTS.md §1; pre-commit + pre-push hooks born after the
2026-05-25 Antigravity incident that silently changed broker ports 48885→48887
and bypassed transaction wrappers) is the source-controlled safety net that
blocks any agent from committing or pushing edits to the Revit / AutoCAD / 3ds
Max / shared MCP broker sources under `payload/sources/` without an AgDR +
founder sign-off (`ARCHHUB_ALLOW_CS_EDIT=1`).

All 3 guard invocations used the pathspec `'payload/sources/**/*.cs'`:

- `.githooks/pre-commit` — the `STAGED_CS` index-vs-HEAD diff:
  ```
  STAGED_CS=$(git diff --cached --name-only --diff-filter=ACMR \
              -- 'payload/sources/**/*.cs' 2>/dev/null || true)
  ```
- `.githooks/pre-push` — the **new-branch** range (`git log` over the last 50):
  ```
  cs_changes=$(git log --name-only --pretty=format: -50 "$range" -- \
               'payload/sources/**/*.cs' 2>/dev/null | sort -u | grep -v '^$' || true)
  ```
- `.githooks/pre-push` — the **normal** range (`remote_sha..local_sha`):
  ```
  cs_changes=$(git log --name-only --pretty=format: "$remote_sha..$local_sha" -- \
               'payload/sources/**/*.cs' 2>/dev/null | sort -u | grep -v '^$' || true)
  ```

**The fnmatch direct-child miss.** Git's pathspec matching (without the
`:(glob)` magic) uses `fnmatch` **without** the `FNM_PATHNAME` flag, so a `*`
freely crosses `/`. Counter-intuitively, the failure is not that `*` is too
greedy — it is that the literal substring `/**/` in a non-glob pathspec requires
**at least one** path segment between `sources/` and the filename. Under
git 2.54.0.windows.1 (the repo's git), `'payload/sources/**/*.cs'` therefore
matches a `.cs` in a **subdirectory** (`payload/sources/shared/ScriptCompiler.cs`)
but **MISSES a `.cs` placed DIRECTLY** in `payload/sources/` (e.g.
`payload/sources/Foo.cs`). Today every real broker source lives in a subdir
(`acad_mcp/`, `revit_mcp/`, `revit_mcp_core/`, `shared/`), so the gap is latent —
but a future broker `.cs` added directly under `payload/sources/` would bypass
the guard **silently**, with no error and no block.

**FakeBroker.cs verified bypass.** Reproduced in a throwaway repo on the repo's
own git (2.54.0.windows.1):

- A commit touching **only** `payload/sources/Foo.cs` (a direct child) yields
  `(empty)` from `git log --name-only --pretty=format: <range> -- 'payload/sources/**/*.cs'`
  — i.e. the pre-push guard sees nothing and the push is **allowed**. Same miss
  for `git diff --cached -- 'payload/sources/**/*.cs'` at commit time.
- The same commit under `':(glob)payload/sources/**/*.cs'` returns
  `payload/sources/Foo.cs` — the guard **catches** it.
- Subdirectory files (`payload/sources/shared/ScriptCompiler.cs`) are matched by
  **both** the old and new pathspec, so existing coverage is fully preserved.

## Options Considered

| Option | Pathspec | Direct child caught? | Subdir caught? | Notes |
|--------|----------|----------------------|----------------|-------|
| A — status quo | `'payload/sources/**/*.cs'` | **NO** (silent bypass) | yes | the bug |
| B — two pathspecs | `'payload/sources/*.cs' 'payload/sources/**/*.cs'` | yes | yes | works, but the bare `*` relies on the no-FNM_PATHNAME slash-crossing quirk; two tokens to keep in sync across 3 sites |
| C — `:(glob)` magic (CHOSEN) | `':(glob)payload/sources/**/*.cs'` | yes | yes | single token; `:(glob)` makes `**` mean "zero or more path segments" explicitly + depth-independent; no reliance on fnmatch slash quirk |

Both B and C **tested clean** for the direct-child and subdir cases across
`git diff --cached` (pre-commit) and `git log` (pre-push, both ranges).

## Decision

**Option C** — apply `':(glob)payload/sources/**/*.cs'` identically at all 3
guard sites.

Rationale: it is a single pathspec token (no two-token pair to drift across the
3 sites), and the `:(glob)` magic gives `**` explicit, depth-independent
"match any number of directories including zero" semantics rather than leaning on
git's accidental no-`FNM_PATHNAME` behavior of a bare `*`. The `:(glob)` prefix
contains `(` / `)` which the shell would otherwise interpret, so the pathspec is
kept inside the **single quotes** that already wrapped it — shell passes the
literal `:(glob)payload/sources/**/*.cs` straight to git, which parses the magic.

Changed (all 3, identically):

- `.githooks/pre-commit` `STAGED_CS` → `-- ':(glob)payload/sources/**/*.cs'`
- `.githooks/pre-push` new-branch range → `':(glob)payload/sources/**/*.cs'`
- `.githooks/pre-push` normal range → `':(glob)payload/sources/**/*.cs'`

**Explicitly NOT changed:** the `ARCHHUB_ALLOW_CS_EDIT=1` short-circuit (both
hooks), the AgDR-0050 brain-commit-gate block (both hooks), every `exit 0` /
`exit 1`, the branch-deletion (`local_sha == 40 zeros`) skip, the new-branch vs
normal range branching, and the human-facing heredoc / comment text (which still
reads the friendly `payload/sources/**/*.cs` glob — it is display copy, not a
load-bearing pathspec).

## Incident-safety note

This change **STRENGTHENS the broker guard only.** It is a pure widening of what
the existing guard already catches — a direct-child `.cs` that previously slipped
through is now blocked, exactly like a subdir `.cs` always has been.

- **No broker contract change.** No port number, no protocol, no transaction
  wrapper, no failure-preprocessor, no `payload/sources/**/*.cs` source file is
  touched by this AgDR. The guard is the only thing modified.
- **No port / transaction change.** Nothing in this edit alters the Revit /
  AutoCAD / 3ds Max broker ports or the script-compiler contract the Python side
  depends on. This is the meta-layer (the hook), not the broker.
- **Fail-safe direction.** The change makes the guard *more* likely to block, not
  less. The worst-case regression of a too-broad pathspec is a false-positive
  block (recoverable via the documented `ARCHHUB_ALLOW_CS_EDIT=1` opt-in), never
  a silent foreign edit slipping through.
- **No behavior change for existing files.** Every `.cs` currently under
  `payload/sources/**` is in a subdirectory and was already matched; it stays
  matched. Non-`.cs` files remain ignored by the guard.

## Verification

- `sh -n .githooks/pre-commit` and `sh -n .githooks/pre-push` → clean.
  `bash -n` on both → clean.
- Throwaway-repo functional test of the **edited** pre-commit, installed as a
  real `.git/hooks/pre-commit`:
  1. stage direct-child `payload/sources/Foo.cs` → **BLOCKED** (rc=1), banner
     lists `payload/sources/Foo.cs`. *(This is the case that previously bypassed.)*
  2. same file with `ARCHHUB_ALLOW_CS_EDIT=1` → **ALLOWED** (rc=0); short-circuit intact.
  3. stage subdir `payload/sources/shared/ScriptCompiler.cs` → **BLOCKED** (rc=1); prior coverage preserved.
  4. stage a non-broker file only → **ALLOWED** (rc=0); brain-commit-gate fail-open message fired, guard correctly ignores non-`.cs`.
- Throwaway-repo `git log` test of the pre-push ranges: a direct-child-only commit
  returns `(empty)` under the old pathspec (bypass confirmed) and the filename
  under `':(glob)…'` (caught).
- `git diff` of the working tree shows exactly **3 changed lines** — one per guard
  site — and no other hunks.

## Consequences

- A future broker `.cs` added directly at `payload/sources/<File>.cs` is now
  caught by both the commit-time and push-time guards. The latent silent-bypass
  class is closed.
- The hooks stay POSIX-`sh` clean (they run under whatever git invokes; tested
  under both `sh` and `bash`).
- The friendly heredoc/comment copy intentionally still shows the readable
  `payload/sources/**/*.cs` glob for humans; the load-bearing pathspecs use the
  `:(glob)` form.

## Rollback

Single-token revert at each of the 3 sites — change
`':(glob)payload/sources/**/*.cs'` back to `'payload/sources/**/*.cs'` in
`.githooks/pre-commit` (the `STAGED_CS` line) and the two `cs_changes` lines in
`.githooks/pre-push`. No other file, contract, or state is affected, so a plain
`git revert` of the hook commit (or a 3-line manual edit) fully restores prior
behavior. Because the change is additive-coverage only, rollback simply
re-opens the direct-child gap; it cannot corrupt history, ports, or transactions.

## Artifacts

- `.githooks/pre-commit` — `STAGED_CS` pathspec → `':(glob)payload/sources/**/*.cs'`
- `.githooks/pre-push` — both `cs_changes` pathspecs (new-branch range + normal range) → `':(glob)payload/sources/**/*.cs'`
- `docs/agdr/AgDR-0053-cs-guard-pathspec-hardening.md` — this record
