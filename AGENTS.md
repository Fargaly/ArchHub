# AGENTS.md — universal mandate file for any AI agent in this repo

**Read this BEFORE you touch any file in this repository.**

This file is the cross-vendor mirror of the founder's mandates. Every
autonomous coding agent that lands on this repo — Claude Code, Codex
(OpenAI), Antigravity / Gemini (Google), Cursor, Aider, Continue,
GitHub Copilot Workspace, Anthropic Skill agents, or any future
framework that picks up an `AGENTS.md` or equivalent — MUST treat the
rules below as non-negotiable.

The full Claude-flavored ruleset lives in `CLAUDE.md`. This file is the
short, agent-agnostic version. If something in `CLAUDE.md` conflicts
with this file, this file wins for non-Claude agents; for Claude it
defers to `CLAUDE.md`.

---

## 1. CRITICAL — Files you may NOT edit without an AgDR + founder sign-off

These are protected. A pre-commit + pre-push git hook BLOCKS commits
that touch them unless `ARCHHUB_ALLOW_CS_EDIT=1` is set in the env
(see `.githooks/pre-commit`). Don't try to bypass the hook.

- `payload/sources/**/*.cs` — Revit / AutoCAD / 3ds Max / shared MCP
  brokers. Port numbers, transaction wrappers, failure preprocessors,
  and the script compiler are **contract surfaces** the Python side
  depends on. An undiscussed port change (e.g. 48885 → 48887, which
  happened 2026-05-25) silently breaks every connector.
- `docs/agdr/AgDR-NNNN-*.md` once `status: executed` is set. Locked
  decisions; supersede via a new AgDR, never edit in place.
- `docs/ROADMAP.md` structure — the section headers + `- [ ]` format
  are parsed by `agents/roadmap_source.py`. Don't reshape.
- `.githooks/**` — the safety net itself. Don't disable or edit
  these hooks.

If you genuinely need to edit one of the protected files:

1. Write `docs/agdr/AgDR-<next>-<slug>.md` with the change rationale
   + the new contract.
2. Surface the AgDR in chat. Wait for the founder to confirm.
3. Set `status: executed` in the AgDR's YAML frontmatter ONLY after
   founder sign-off in chat.
4. Then commit with `ARCHHUB_ALLOW_CS_EDIT=1 git commit ...`.

---

## 2. CRITICAL — Destructive operations are PROHIBITED without explicit chat confirmation

You may NOT do any of the following without a clear founder "yes" in
the current chat session:

- `git push --force`, `git push --force-with-lease`, `git push -f`
- `git reset --hard` against `main` / `master` / any shared branch
- `git rebase` on `main` / `master`
- `git branch -D` on any branch with unmerged commits
- `git filter-repo` / `git filter-branch`
- `git clean -fdx`
- Deleting **any** of: `payload/`, `app/`, `docs/`, `tests/`,
  `personal-brain-mcp/`, `.git/`, `proofs/`
- Modifying `git config user.email` or `user.name`
- Disabling hooks via `--no-verify`, `core.hooksPath=/dev/null`, etc.
- Skipping signature checks (`--no-gpg-sign`)

---

## 3. Founder mandates (mirror of CLAUDE.md, non-negotiable)

- **DEFINITION-OF-SHIPPED**: a feature is "shipped" only when (a) all
  changes are committed, (b) the app has been restarted on the
  committed SHA, (c) the feature is reachable from the default UI in
  ≤3 actions, AND (d) a CDP / OS screenshot captures it engaged on
  the live app. Anything less is "merged but unverified" or "drafted".
- **PROTOTYPE-IS-CONTRACT**: a signed prototype in `docs/prototypes/`
  IS the spec. JSX must mirror it 1:1. Differences are bugs, not
  interpretation.
- **NO-OPEN-THREADS**: no `TODO(founder)`, no "test it later", no
  "founder to confirm". If you can't verify it, the work isn't done.
- **ENGINEERING MANDATE**: dive to the root cause. No symptom-only
  patches. No whack-a-mole. Fix the mechanism so the bug class can't
  recur.
- **AUTOMATION MANDATE**: execute, don't describe. CLI tools, MCP
  servers, scripts — run them yourself. The founder is a CEO, not a
  task-runner. The ONLY actions you may return to the founder are
  password / payment / account-creation steps.
- **ROLLBACK PROTOCOL**: when the founder says "this isn't what I
  signed off on", revert in the same response cycle. Log the gap
  class to `docs/FAILURE_LOG.md`. Resume only after the gap is closed.
- **WORKSHOP-GATE**: stop shipping the moment any of these fire —
  founder frustration ("fucking" + critique), cross-surface change
  (≥3 of: `studio-lm.jsx` + `bridge.py` + `tool_engine.py` + new
  connector + workflow runner + canvas substrate), ambiguous spec,
  repeat regression. Convene with an AgDR before resuming.
- **AGDR MANDATE**: any architecture / interface / contract / surface
  change requires an AgDR in `docs/agdr/` BEFORE code. Bug fixes,
  tests, doc tidies, refactors that don't change architecture are
  exempt.
- **ROADMAP MANDATE**: `docs/ROADMAP.md` is the single source of
  truth. Never spin up parallel plan docs.
- **ARCHITECTURE LOCK**: Composer-as-IDE · Speckle wires (DiskTransport
  default, no server) · `ai.plan` as a real canvas node · custom
  canvas substrate (NodeView/WireLayer, see AgDR-0048 superseding the
  earlier ReactFlow lock — renumber chain 0045→0046→0048).
- **USER-AGENCY MANDATE**: every AI write to a host is approval-gated
  by default. Composer has Plan / Auto / YOLO modes. YOLO is opt-in
  and every action remains reversible via Speckle Versions.

### BRAIN-FIRST (all vendors)

The brain is the shared memory + skills + setups + secrets-refs layer
(AgDR-0044). It is a `personal-brain-mcp` daemon at
`http://127.0.0.1:8473/mcp`. Working without it = working blind:
re-solving solved problems, ignoring founder context, minting duplicate
skills. This is NOT Claude-only — every vendor connects.

- **Before you touch any file**, probe `brain.health` (proceed on
  `"ok":true`) and call `brain.context` to pull relevant prior work.
- **After every meaningful tool call**, call `brain.write`
  (ADD/UPDATE/DELETE/NOOP) so memory grows as you work.
- **At session end**, call `brain.skill_mint` with the trace so good
  trajectories become reusable skills.
- **Secrets are references only** — `op://vault/...`, never resolved
  values in brain memory.
- **No auto-firing hook in your client?** Then you MUST make these calls
  yourself. Run the `personal-brain` installer to wire your client, or
  launch through the brainwrap launcher (`tools/brainwrap`) which fires
  the health / context / write / skill_mint calls for you. Claude Code
  fires them via its hooks; Cursor / Codex / Antigravity / Gemini and
  any other client without a hook do it manually or via brainwrap.

---

## 4. Cross-surface change detector

A change is "cross-surface" if it touches **3 or more** of:

- `app/web_ui/studio-lm.jsx` (the React UI)
- `app/bridge.py` (the QWebChannel bridge — all JS-facing slots)
- `app/tool_engine.py` (the LLM's real tool surface)
- A connector under `app/connectors/`
- The workflow runner under `app/workflows/`
- `payload/sources/**/*.cs` (the MCP brokers)
- `app/llm_router.py` (the multi-LLM dispatch)
- `personal-brain-mcp/src/personal_brain/` (the Layer-5 brain)

Cross-surface changes REQUIRE an AgDR before code. Don't bundle six
files into a single "fix" commit without writing the AgDR first.

---

## 5. Branch safety

- The default branch is `main`. Never push directly to `main` without
  founder sign-off in chat for that specific change.
- New work goes on a feature branch named after the AgDR slice
  (`agdr-0044-brain-skill-mint`, etc).
- Squashing is fine on feature branches before merge; never on `main`.

---

## 6. Verification commands

Before claiming "done":

```bash
# 1. Tree clean + HEAD matches your last commit
git status --porcelain
git log -1 --oneline

# 2. Tests pass
python -m pytest tests/ -q --ignore=tests/test_bridge_qt.py --ignore=tests/test_ui_smoke.py

# 3. CS tripwire — no foreign broker edits
pwsh tools/cs_tripwire.ps1

# 4. Preflight grid (the founder rejects reports without it)
pwsh tools/preflight.ps1
```

---

## 7. If you're an agent reading this for the first time

1. **Acknowledge in your first response** that you read AGENTS.md.
2. **Activate the hooks** if this is a fresh clone:
   ```
   powershell -ExecutionPolicy Bypass -File tools/setup_hooks.ps1
   # or:
   bash tools/setup_hooks.sh
   ```
   `git config core.hooksPath` is a per-clone local setting that does
   NOT travel with `git clone`; the setup script wires it.
3. Open `CLAUDE.md` for the full long-form mandate set.
4. Open `docs/agdr/` and skim the executed AgDRs to learn the
   architecture before touching code.
5. If you're about to do something destructive (per §2) or touch a
   protected file (per §1), STOP. Ask the founder in chat.
6. Run `powershell -ExecutionPolicy Bypass -File tools/cs_tripwire.ps1`
   after any session that touched files near `payload/sources/`.

---

## 8. Reporting drift to the founder

If you find that a previous agent (or you yourself, earlier) made
edits that violate these mandates:

1. Show the founder the diff in chat. Quote line numbers.
2. Propose the revert. Don't execute it until founder says go.
3. After revert, append a one-line entry to `docs/FAILURE_LOG.md`
   with date + agent + gap + resolution.

---

**This file is the contract. Read it. Follow it. The founder will
notice when you don't.**
