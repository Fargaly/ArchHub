# Canvas v48 branch evidence

Owner: lane/design-match. Tier: T0 synthetic product fixture. Scope: Canvas only.

The pair PNGs place the frozen v48 reference on the left and this worktree's compiled Studio on the right, at 1864x949, 1366x768 and 1009x940. render.py owns a disposable server/profile; render.cjs owns a headless browser; both close their resources. compose.py creates and checks the pairs.

The exact requested pytest command is in release-command.txt; its single run ended `9 failed, 759 passed, 1 skipped, 1 warning in 764.49s`. release-output.log preserves the errors. Eight startup failures were stale compiled bytes during source edits. Final recompilation and the full designbuild file rerun ended `1 failed, 13 passed, 1 warning in 131.35s`; focused-output.log preserves the remaining failure: test_designbuild_board[resume] times out waiting for approval.gate status Done after approving from Home. The extra native Session card was fixed in the shared folding predicate; the rendered-agent rerun passed for both Codex and Claude, including held-write approval.

The expanded Canvas court passed: Session panels, Save/skill menu, Automate/trigger ownership, Inspector tabs, Ask why/Reject, undo/redo, arrange, More, Library dock, composer recipient/Send transport, Run all dispatch/error handling, more-steps panning and saved list/file edits. The renderer's Run all fixture reports `Unknown socket on Make native Revit details`; this proves dispatch and visible failure, not successful execution of that synthetic pipeline. Actual held writes and approval execution passed in the rendered-agent court.

Controls removed for lack of time: none.

Remaining design differences: real text/table output previews replace the reference's CAD thumbnails; type-derived icons and live account/agent/status values differ; approval actions are consolidated in This task; task preview-tab and composer recipient styling differ; some spacing remains approximate. No Home 1, Library or Home 2 redesign was started. No push, install or release; installed behavior is not claimed.
