---
id: AgDR-0050
title: no-brain-on-commit floor — codify "no brain.write = extra scrutiny" as a cross-vendor commit gate
timestamp: 2026-06-01
agent: claude-code (Opus 4.8)
session: governance-no-brain-on-commit-floor
status: executed
category: governance
projects: [archhub, personal-brain-mcp]
supersedes: null
superseded_by: null
founder-signoff: GRANTED 2026-06-01 — founder said "wire it" in chat, authorizing the .githooks wiring step (see "Wiring requires founder sign-off" below)
executed: "Executed 2026-06-01 — founder said 'wire it' in chat; wired into .githooks/pre-commit + pre-push in WARN mode."
predecessor_verified: "AgDR-0044 (personal-brain-mcp) executed + daemon live this session — brain.health returned ok:true (skills:63, facts:410, engine.all_alive:true) at 2026-06-01"
---

> **STATUS: Executed 2026-06-01.** This record proposed a governance floor and
> shipped a ready, tested check-script (`tools/brain_commit_gate.py`). The
> founder said **"wire it"** in chat on 2026-06-01, granting the sign-off the
> "Wiring requires founder sign-off" section below demands. The gate is now
> wired into `.githooks/pre-commit` **and** `.githooks/pre-push` as an
> additive, second check that runs **after** the existing `payload/sources/**/*.cs`
> guard (which is unchanged). It runs in **WARN mode by default**
> (`ARCHHUB_BRAIN_COMMIT_GATE` unset/`warn` → exit 0, never blocks); `=block`
> is the opt-in. The hook invocation is itself fail-open: a missing python, an
> absent gate file, or any invocation error still allows the commit/push.
>
> _Original proposed-state note (kept for history): "This record proposes a
> governance floor and ships a ready, tested check-script. It does NOT wire
> anything into `.githooks/**`. The hook edit is a separate step that requires
> founder sign-off in chat."_

## Context

The unification is nearly complete: **every vendor now connects to the brain
via hooks.** Claude Code fires `brain.health` / `brain.context` / `brain.write`
/ `brain.skill_mint` through its native `~/.claude/settings.json` hooks
(AgDR-0044 slice 3); Cursor / Codex / Antigravity / Gemini and any hookless CLI
get the same lifecycle through `tools/brainwrap` (AGENTS.md §3 BRAIN-FIRST). So
*per-client* the brain is wired.

But those hooks are **per-client and advisory**. They live in each vendor's own
config, they fire inside that vendor's runtime, and a contributor (or a future
agent, or a misconfigured client) can simply not have them — or disable them —
and still push code. The hooks make the brain easy to use; they do not make it
*enforced across vendors*.

The **only cross-vendor enforcement point that already exists** is the git
hook layer (`.githooks/pre-commit`, `.githooks/pre-push`). It runs regardless of
which editor or agent produced the commit, on every contributor's clone, at
commit/push time. Today it guards exactly one thing: foreign edits to
`payload/sources/**/*.cs` (the broker contract surfaces) — see AGENTS.md §1.

Meanwhile CLAUDE.md (BRAIN-FIRST mandate) and AGENTS.md §3 already state the
policy this AgDR codifies, in prose:

> *"PRs from contributors whose work shows no brain interaction (zero
> `brain.write` ops in trace, no `<brain_context>` injection) are reviewed
> with extra scrutiny — they're working without the shared memory + may be
> reinventing prior work."* — CLAUDE.md, BRAIN-FIRST

That sentence is a **human-review** rule with no mechanism. Nothing checks it;
it depends on a reviewer remembering to look. This AgDR turns that prose into a
**gate**: a commit that touches the live product surface (`app/**` or
`payload/**`) is checked, at commit time, for evidence that the brain was
actually engaged this session. It is the "no-brain-on-commit floor" — the last
unification piece, placing the enforcement at the one layer that already spans
every vendor.

### Why a gate, and why now

- **The hooks are the carrot; this is the (soft) stick.** BRAIN-FIRST is
  non-negotiable in prose but unenforced in code. A floor at the git layer is
  the natural home because it is the *only* place all vendors converge.
- **It fits an existing pattern.** `.githooks/pre-commit` already inspects the
  staged set and decides warn/block on an env flag. This gate is a sibling
  check with the same shape (inspect `git diff --cached`, decide, respect an
  env override) — not a new mechanism (ONE-SYSTEM-PLAN-BEFORE-BUILD).
- **It is honest about its limits** (see "Detection limitation" below). A git
  hook has no session transcript and cannot prove a `brain.write` happened
  *for this commit*. The gate is a best-effort recency + provenance check, and
  it **warns by default** — it never silently blocks honest work.

## Detection limitation (stated up front — this is best-effort)

A git hook runs as a short-lived subprocess. It has **no access to the agent's
session transcript**, no list of the tool calls the agent made, and no
guaranteed link between "this commit" and "a brain.write that happened in the
session that produced it." There is therefore **no way to *prove*** that a
`brain.write` occurred *for this specific commit*. Any claim otherwise would be
the ANTI-LIE failure mode.

What the gate *can* do is a **best-effort recency + provenance check** against
the live brain daemon: ask the brain whether there is a recent fragment whose
provenance is plausibly tied to *this repo / cwd* within the last N minutes. The
daemon's `brain.browse` surface exposes, per fragment: a `last_used` date, a
`why` ("used recently" / "learned recently" when ≤7d), the fragment `text` /
`headline` / `details`, and a `timeline` bucketed by date. Provenance
(`accessed_resources`, the touched file paths) is what ties a fragment to a
repo. The gate matches on: a fragment dated **today** whose text / headline /
details / accessed-resources reference this repo path, the repo basename, or one
of the staged file paths.

This is a **heuristic, not a proof.** It can yield false-positives (an unrelated
fragment mentioning "ArchHub" today) and false-negatives (a real brain.write the
daemon hasn't surfaced in browse yet, or whose text doesn't name a path). That
imprecision is exactly why the gate **warns by default and only blocks behind an
explicit env opt-in** — never the reverse.

## Options considered

### Option A — Detection mechanism: how does the gate know the brain was engaged?

| # | Mechanism | Pros | Cons | Verdict |
|---|-----------|------|------|---------|
| **A1** | **Query the live daemon (`brain.browse`) for a recent fragment with provenance tied to this repo/cwd within N minutes** | Uses the brain that BRAIN-FIRST already requires to be running; no new artifact; reuses the exact stdlib SSE/JSON-RPC transport `brainwrap.py` uses; fails-open cleanly when the daemon is down (fresh clone, CI) | Date-granularity recency in `browse`; heuristic text/path match; can false-positive/negative | **Primary (chosen)** |
| A2 | Check a **session marker file** the brain hooks drop (e.g. `~/.archhub/brain/last_write_<repohash>.json` with a timestamp) | Minute-granularity; cheap to read; works offline | Requires the brain hooks to *write* the marker — a NEW contract the hooks don't have today; a fresh/foreign client without the hook never drops it → marker-absent is indistinguishable from brain-down; adds a file to maintain | **Secondary (documented, not built)** — adopt later if A1's date-granularity proves too coarse, by having the PostToolUse→brain.write hook also stamp the marker |
| A3 | Parse the agent's transcript for `brain.write` calls | Direct evidence of the call | The hook has NO transcript access (see limitation); different per vendor; impossible to do portably at commit time | ✗ rejected — not available to a git hook |
| A4 | Trust the per-client hooks; add nothing at the git layer | Zero new code | Leaves the cross-vendor gap open — the entire point of this floor | ✗ rejected — defeats the purpose |

**Chosen: A1**, with **A2 documented as the upgrade path.** A1 needs no new
contract and reuses the running daemon. If the founder later wants
minute-precision and offline operation, the brain's existing
`PostToolUse→brain.write` hook gains a one-line marker stamp (A2) and the gate
reads the marker first, falling back to A1 — additive, no redesign.

### Option B — Enforcement strength: warn or block?

| # | Strength | Pros | Cons | Verdict |
|---|----------|------|------|---------|
| **B1** | **Warn-only by default; block only when `ARCHHUB_BRAIN_COMMIT_GATE=block`** | Never blocks honest work on a heuristic; mirrors the existing `.cs` hook's env-gated strictness (`ARCHHUB_ALLOW_CS_EDIT`); a team that wants hard enforcement opts in; respects the detection limitation | A warning can be ignored | **Chosen** |
| B2 | Block by default; bypass with an env flag | Strong enforcement | Blocking on a *heuristic* punishes false-negatives (real work, daemon slow to surface it) and bricks fresh clones / CI; inverts the safe default | ✗ rejected — a best-effort signal must not hard-block by default |
| B3 | Block, no override | Maximal | Violates AUTOMATION/AGENTS safety + would brick CI and fresh clones; no escape hatch | ✗ rejected |

**Chosen: B1.** The gate's exit contract: **exit 0 = ok-or-warn (default)**;
**exit 1 = block, ONLY when `ARCHHUB_BRAIN_COMMIT_GATE=block`** AND the brain was
reachable AND no qualifying recent fragment was found. If the brain is
**unreachable**, the gate **fails OPEN** (prints a notice, exit 0) in every mode
— a fresh clone with no daemon, or CI, must never be blocked by this floor.

### Option C — Trigger scope: which commits get checked?

| # | Scope | Verdict |
|---|-------|---------|
| **C1** | **Touches `app/**` or `payload/**`** (the live product surface — UI/bridge/engine/connectors and the broker payload) | **Chosen** — these are the surfaces where "working without shared memory = reinventing prior work" actually bites. Mirrors the cross-surface spirit of AGENTS.md §4. |
| C2 | Every commit (docs, tests, tooling too) | ✗ rejected — a docs typo or a test tweak does not need brain provenance; over-broad triggers train people to ignore the warning |
| C3 | Only `app/**` | ✗ rejected — `payload/**` carries the broker sources + packaged product; brain context matters there too |

## Decision

1. **Ship `tools/brain_commit_gate.py`** — a standalone, pure-stdlib, tested
   check-script. Given the staged file list (`git diff --cached --name-only`,
   which the script computes itself or accepts via `--staged-file`/stdin for
   testability), it:
   - **Decides if the commit touches the product surface** — any staged path
     under `app/` or `payload/`. If not → prints `skip`, exit 0 (nothing to
     check).
   - **If it does**, queries the brain daemon (`http://127.0.0.1:8473/mcp`,
     overridable via `BRAIN_DAEMON_URL`) **best-effort** for a recent
     `brain.write` fragment whose provenance is tied to this repo/cwd within the
     last **N minutes** (default 120, overridable via
     `ARCHHUB_BRAIN_COMMIT_GATE_WINDOW_MIN`). Detection = a fragment dated today
     (or `why` ∈ {used recently, learned recently}) whose text / headline /
     details / accessed-resources reference the repo path, repo basename, or a
     staged path.
   - **Prints a clear verdict** to stderr (found / not-found / brain-down /
     skip), naming exactly what it checked and why.
   - **Exit contract:** `0` = ok-or-warn (the default for *every* outcome
     except a confirmed block); `1` = block **only** when
     `ARCHHUB_BRAIN_COMMIT_GATE=block` AND brain reachable AND no qualifying
     fragment found.
2. **Fail-open is absolute.** Brain unreachable, daemon error, timeout, malformed
   response, gate's own bug → print a notice, exit 0, in all modes. A fresh
   clone (no daemon, no brain history) is never blocked. This mirrors the
   fail-open discipline already proven in `tools/brainwrap.py` and
   `tools/anti_laziness_gate.py`.
3. **Default is warn.** `ARCHHUB_BRAIN_COMMIT_GATE` unset or `warn` → the gate
   prints a recommendation and exits 0 even when no fragment is found. Only the
   explicit `block` value can produce exit 1.
4. **Reuse, do not reinvent, the transport.** The script copies the *pattern* of
   `brainwrap.call_tool` (urllib + the MCP `tools/call` envelope + SSE `data:`
   parsing) so it stays pure-stdlib and dependency-free, and degrades the same
   way. (It does not import brainwrap to avoid coupling a git-hook-time tool to
   the larger launcher; the transport is ~25 lines.)
5. **WIRING IS OUT OF SCOPE.** This AgDR does **not** touch `.githooks/**`. The
   proposed (future, founder-approved) wiring would append a call to
   `.githooks/pre-commit` (and/or `pre-push`) of the form
   `python tools/brain_commit_gate.py || exit $?` — but only after the founder
   signs off, and only as a *separate* commit made with
   `ARCHHUB_ALLOW_CS_EDIT=1` per the existing `.cs` hook's own rule. See the
   explicit clause below.

### Exit-code contract (the gate logic, precisely)

```
staged = git diff --cached --name-only
touches_surface = any(p starts with "app/" or "payload/" for p in staged)

if not touches_surface:
    print "skip — no app/ or payload/ paths staged"
    exit 0

brain = query brain.browse(query = repo-name + staged-paths)   # best-effort
if brain is unreachable / errored / timed out:
    print "brain unreachable — FAIL-OPEN (not blocking)"
    exit 0                                  # fresh clone / CI safe

found = any fragment dated today (or why∈{used,learned recently})
        whose text/headline/details/accessed_resources references
        this repo path | repo basename | a staged path
        AND within the last N minutes (best-effort, date-granular)

if found:
    print "ok — recent brain interaction tied to this repo found"
    exit 0

# not found, brain WAS reachable:
mode = env ARCHHUB_BRAIN_COMMIT_GATE  (default "warn")
if mode == "block":
    print "BLOCKED — no recent brain.write tied to this repo. Connect to the brain (BRAIN-FIRST) and retry, or set ARCHHUB_BRAIN_COMMIT_GATE=warn."
    exit 1
else:
    print "WARNING — no recent brain.write tied to this repo (BRAIN-FIRST). Proceeding (warn mode)."
    exit 0
```

## Consequences

### What becomes easier / better
- The BRAIN-FIRST prose ("no brain.write = extra scrutiny") gains a **mechanism**
  at the one layer every vendor shares. A commit to the product surface from a
  client that never touched the brain now surfaces a visible warning at commit
  time — the reviewer no longer has to remember to check.
- **Cross-vendor, by construction.** Because it lives (when wired) in the git
  hook, it fires for Claude Code, Cursor, Codex, Antigravity, Gemini, a bare
  shell — identically. No per-client config to drift.
- **Opt-in hard enforcement** for teams/CI that want it (`=block`), without
  punishing the default solo flow.

### Costs / what changes
- One new file: `tools/brain_commit_gate.py` (+ its test). No existing file
  changes in this AgDR. No `.githooks` change in this AgDR.
- When *later* wired (separate approved step): `.githooks/pre-commit` gains a few
  lines; commit time gains one fast, fail-open daemon probe (sub-second; skipped
  entirely for commits that don't touch `app/`/`payload/`).

### Honest limitations (carried forward)
- Date-granularity recency + heuristic text/path match (Option A1) → false
  positives/negatives possible. This is **why the default is warn.** The A2
  marker-file upgrade path is documented if precision is later needed.
- A determined contributor can ignore a warning or set `=warn`. The floor raises
  the cost of working blind; it does not make it impossible. That is the correct
  ceiling for a best-effort signal — hard, unbypassable blocking belongs only on
  *provable* contract violations (like the `.cs` broker guard), not on a
  heuristic.

## Rollback

- **Before wiring (current state):** nothing to roll back — the gate is an inert
  standalone file. Delete `tools/brain_commit_gate.py` (+ test) and the repo is
  unchanged. No commit path is affected.
- **After wiring (future):** revert the single `.githooks/pre-commit` commit
  (made with `ARCHHUB_ALLOW_CS_EDIT=1`), or set
  `ARCHHUB_BRAIN_COMMIT_GATE=warn` (or unset it) to neuter blocking instantly
  without a code change. Because the gate fails-open and warns by default, even a
  buggy wiring cannot block honest commits in the default configuration.
- **Emergency:** the standard `git commit --no-verify` bypass (AGENTS.md
  acknowledges it for a broken hook) still works — but per AGENTS.md §2 that is
  only for a genuinely broken hook, not routine bypass.

## WIRING — FOUNDER SIGN-OFF GRANTED, NOW EXECUTED

**This AgDR proposed the gate. As of 2026-06-01 it is WIRED.**

- `.githooks/**` is protected (AGENTS.md §1; the `.githooks/pre-commit` header
  itself states broker/hook edits require an AgDR + founder sign-off).
- The wiring — appending the `brain_commit_gate.py` call into
  `.githooks/pre-commit` **and** `.githooks/pre-push` — was the **separate,
  approved step**, now done:
  1. ✅ Founder reviewed this AgDR and said **"wire it"** in chat (2026-06-01).
  2. ✅ This AgDR's `status` flipped `proposed → executed` (recording the
     sign-off; see `executed:` frontmatter + the STATUS banner).
  3. ✅ The `.githooks/pre-commit` + `.githooks/pre-push` edits are to be
     committed with `ARCHHUB_ALLOW_CS_EDIT=1 git commit ...` per the existing
     hook's rule (the brain-gate addition is additive and does not touch the
     `.cs` guard, but the hooks live under `.githooks/` so the founder's
     opt-in env is used for the commit).
- The brain gate was added **after** the existing `.cs` guard in each hook,
  warns by default, and the hook invocation is fail-open (missing python /
  absent gate / any error → commit proceeds). The `.cs` guard is unchanged and
  still hard-blocks staged `payload/sources/**/*.cs` without
  `ARCHHUB_ALLOW_CS_EDIT=1`.

## Cross-mandate check (CONSOLIDATE-WITH-ALL-MANDATES)

- **AGDR**: governance/contract-shaped → an AgDR is the correct artifact; written
  before any wiring. ✓
- **AGENTS §1 / `.githooks` protection**: respected — zero `.githooks` edits;
  wiring explicitly deferred to a signed step. ✓
- **ONE-SYSTEM-PLAN-BEFORE-BUILD**: the gate is a *sibling* of the existing
  `.cs` hook check (same inspect-staged / env-gated shape), not a parallel
  system; transport pattern reused from `brainwrap.py`. ✓
- **ANTI-LIE**: the detection limitation is stated plainly; the gate is called a
  best-effort heuristic, never "proof"; it warns rather than over-claims. ✓
- **AUTOMATION**: the gate runs itself (computes the staged list, probes the
  daemon) — no manual checklist handed to the founder. ✓
- **BRAIN-FIRST**: this *operationalises* BRAIN-FIRST; verified the daemon live
  this session before writing. ✓
- **NO-OPEN-THREADS**: the script is delivered tested + run; the only open item
  is the founder's wiring decision, which is a genuine true-boundary (a
  protected-file change needing sign-off), not deferred work. ✓
- **DEFINITION-OF-SHIPPED**: this is a governance doc + a CLI tool, not a
  user-visible app feature — so "shipped" is not claimed for a UI surface; the
  tool is "built + tested + run," and wiring is gated. ✓

## Artifacts

- This AgDR (`docs/agdr/AgDR-0050-no-brain-on-commit-floor.md`) — **status:
  executed** (founder "wire it", 2026-06-01).
- `tools/brain_commit_gate.py` — the standalone, fail-open, tested gate script
  (delivered with this AgDR).
- `tests/test_brain_commit_gate.py` — 20 tests, all passing; covers:
  touches-app→checks, no-app→skip, daemon-down→fail-open/exit0, block-mode
  behaviour, found→exit0.
- **WIRED (2026-06-01):** `.githooks/pre-commit` and `.githooks/pre-push` each
  gained an additive brain-gate invocation AFTER the existing `.cs` guard,
  WARN by default, fail-open around the invocation. The `payload/sources/**/*.cs`
  guard in both hooks is unchanged.
- Codifies: CLAUDE.md BRAIN-FIRST "extra scrutiny" clause + AGENTS.md §3.
- Builds on: AgDR-0044 (personal-brain-mcp), AGENTS.md §1 (`.cs` hook pattern).
