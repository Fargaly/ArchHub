---
id: AgDR-0061
title: Public WIP authority maintenance strategy
timestamp: 2026-07-23
agent: Codex
session: public-wip-authority-correction
status: executed
category: governance
projects: [archhub]
supersedes: []
superseded_by: null
---

# Public WIP Authority Maintenance Strategy

## Scope

This runbook prevents a false completion claim when public product work is only
locally clean, only partially classified, or blocked by another owner's active
worktree. It applies to `10.PRODUCT/12.PRODUCTION` when judging whether public
WIP has been coordinated against the Universal Cell authority.

This is not a workspace-wide completion certificate, not a release certificate,
and not proof that every ArchHub system is done. It is a maintenance gate for
the public product WIP boundary.

## Controlling Authority

The controlling product authority remains:

- `10.PRODUCT/13.NODE-LANGUAGE/AUTHORITY.md`
- `10.PRODUCT/13.NODE-LANGUAGE/SPEC.md`
- `00.GOVERNANCE/WORKSPACE-STANDARD.md`

`10.PRODUCT/12.PRODUCTION` may host compatibility code, projections, adapters,
evidence, and migration controls. Those files are not product authority by
classification alone.

## Completion Rule

Do not mark the goal complete unless all of these are true for the stated
scope:

1. The exact scope is named in the report: local tracked source, ignored
   generated artifacts, external owner worktrees, remote publication, or live
   runtime handoff.
2. `git status --porcelain=v1 --untracked-files=all` has been checked inside
   `10.PRODUCT/12.PRODUCTION`.
3. The WIP authority classifier has been run with external worktree coverage:
   `py -3.14 tools\authority_wip_classify.py --include-worktrees --output docs\_meta\authority_wip_classification.latest.json --enforce-no-unclassified`.
4. `docs/_meta/authority_wip_classification.latest.json` shows:
   no `unclassified_noncoordinated`, zero promotion candidates, and every
   remaining path classified with a required action.
5. `external_owner_worktree_wip` entries are reported as owner-boundary WIP,
   not absorbed, rewritten, published, or treated as clean authority.
6. Any code/doc/evidence change made during the run has a focused court and is
   committed before the report claims the local tracked source is clean.
7. If the run touches an agent/session hook adapter, launcher, installer,
   `brainwrap`, CDE scope gate, or connected-agent config, hook coverage must be
   audited for the exact affected client. Prefer
   `brain.hook_coverage_audit_cell_first` when the daemon is reachable; otherwise
   run the focused local hook-coverage courts and report the daemon boundary.
8. The public private-identifier ratchet has been run:
   `py -3.14 -m pytest tests\test_public_privacy_ratchet.py -q --timeout=90 --tb=short`.
   It is shrink-only: existing public debt may decrease, but new or widened
   private client/project references fail the court.
9. No live runtime, user-visible endpoint, Brain supervisor, Revit/Autodesk
   process, production conversion worker, or active session has been stopped,
   restarted, replaced, or handed off unless that action was explicitly in the
   scope and proved by its own court.
10. If another task owns the machine-priority slot, the generated classifier
   report carries `gate.machine_resource.active_hold=true`, and every generated
   active-work leaf carries the same `machine_resource_gate`. The public report
   must not serialize client names, drawing package identifiers, exact counts,
   or other private machine-owner details.

If any item is false, the report must say "not complete for that scope" and
name the blocker.

## Maintenance Loop

Use this loop before every public WIP completion claim, before a public push,
after any agent creates a worktree, and after a machine-priority conflict:

1. Run the local source check:
   `git status --porcelain=v1 --untracked-files=all`.
2. Run the authority classification:
   `py -3.14 tools\authority_wip_classify.py --include-worktrees --output docs\_meta\authority_wip_classification.latest.json --enforce-no-unclassified`.
   If another task owns the machine slot, mark the hold without publishing the
   private owner or scope:
   `--machine-priority-owner "<owner>" --machine-priority-status active_hold --machine-priority-scope "<bounded scope/status>"`.
   The classifier redacts those two values in T0 public evidence; exact details
   belong in private coordination records.
3. Run the focused WIP authority court:
   `py -3.14 -m pytest tests\test_authority_wip_classify.py -q --timeout=90 --tb=short`.
4. If the classifier reports `external_owner_worktree_wip`, run the exact owner
   freshness court:
   `py -3.14 -m pytest tests\test_authority_wip_classify.py::test_generated_wip_classification_matches_live_external_worktree_state -q --timeout=90 --tb=short`.
   The external owner entry is not clean authority until that court confirms
   the report's path/code/branch/HEAD signature still matches the live worktree.
   The generated active-work leaf must also carry the exact
   `external_worktrees` signature: worktree path, branch, HEAD, entry paths, and
   owner-required action. That signature must be part of the classifier digest,
   not merely printed in the report. A leaf that hides this signature is not a
   usable coordination handoff.
5. For agent/session hook work, run the exact client hook audit and focused
   courts. Minimum local courts are:
   `py -3.14 -m pytest personal-brain-mcp\tests\test_hook_coverage.py personal-brain-mcp\tests\test_installer_coverage.py tests\test_brainwrap.py -q --timeout=120 --tb=short`.
   Add client-specific courts such as
   `tests\test_antigravity_governance_hooks.py` when that client is touched.
6. Run the public private-identifier ratchet:
   `py -3.14 -m pytest tests\test_public_privacy_ratchet.py -q --timeout=90 --tb=short`.
7. Run whitespace/path sanity before commit:
   `git diff --check`.
8. Commit only the bounded correction and generated evidence.
9. Re-run the classifier after the commit so
   `docs/_meta/authority_wip_classification.latest.json` represents the final
   post-commit state.
10. If a public-site repo is involved, check it separately:
   `git status --porcelain=v1 --untracked-files=all` inside
   `10.PRODUCT/13.NODE-LANGUAGE/public_site`.

Do not replace this loop with manual scanning or conversation memory. The JSON
report is the machine-readable authority for this maintenance boundary.

## Publication Rule

Do not push or publish from a dirty branch merely because the local branch
builds. When publication is required, use one of these explicit paths:

- Create a clean publication branch from `origin/main`, cherry-pick the proven
  commits, run the required leak scans and courts, then push that branch.
- Or merge the proven branch deliberately after conflict analysis, leak scans,
  and required courts.

If `origin/main` does not contain the required files and cherry-pick fails,
that is a remote publication blocker, not a reason to claim release
completion.

## Machine Resource Rule

When another production task owns the machine-priority slot, this maintenance
loop stays light: source reads, JSON classification, focused tests, and commits
only. Do not start heavy browser, PDF, model, broad audit, preflight, or
conversion work until the slot is released. The generated classifier evidence
must carry this as `machine_resource_gate`; a clean local source report without
that gate is incomplete while the hold is active. The public gate records only
the existence of the hold and the allowed/forbidden work classes, not the
client/task identity.

After a machine-priority conflict or suspected duplicate Brain helper, run the
read-only Brain resource hygiene audit:
`py -3.14 tools\live_runtime_holders.py --audit-brain-resource-hygiene`.
The audit may identify duplicate non-listening Brain server candidates, but it
does not stop anything. A candidate may be released only after an immediate
exact PID, command-line, child-process, and listening-port recheck, and only
without touching the supervised Brain listener, live endpoints, user
applications, or the production task that owns the machine slot.

## Evidence Ledger

Every run that changes the public WIP boundary must leave:

- The refreshed `docs/_meta/authority_wip_classification.latest.json`.
- The focused court output in the final report.
- The public private-identifier ratchet output.
- Hook coverage audit output when agent/session adapters changed.
- The redacted `machine_resource_gate` when a machine-priority holder exists.
- The exact commit hash or an explicit statement that no commit was made.
- A boundary statement separating local tracked source state, external owner
  worktree state, ignored generated artifacts, remote publication state, and
  live runtime state.

This ledger is what prevents repeated heavy coordination and token burn: future
agents should start from the classifier and this runbook, not reconstruct the
same audit from scratch.
