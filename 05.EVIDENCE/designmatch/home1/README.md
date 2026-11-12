# Home 1 v48 branch evidence

Owner: lane/design-match. Tier: T0 synthetic product fixture. Scope: Home 1 only.

The renderer seeds 146 session files through the real task/file owners: 115 agent sessions with vendor-prefixed labels (most planless), 31 workflows, 14 live working declarations, two real waiting approvals and 58 archived tasks. Dates span today, 1-3 days, 4-7 days and over a week. It uses an isolated profile and headless Chromium; browser/server resources close in finally blocks. No live profile is read.

The pairs put the frozen v48 reference on the left and this worktree's compiled Studio on the right, at 1920x1032, 1366x768 and 1009x940. The volume court asserts exact filter counts, open list at wide sizes, distinct avatars, a meaningful planless thread, readable filters, a one-row composer, matching live/header counts and remembered collapsed sections. The full designbuild browser court also exercises actual Home approval -> completed gate -> saved-file readback.

Sources: working declarations are agentGraph.sessions (the exact header source); waiting is pending approval/task review state; age is task.updated_at; archive is the existing task archived flag, projected by listTasks(true). Collapsed sections live in homeLayout in the Settings owner. No session is deleted, moved or rewritten for grouping. New session creation passes the active workspace to the existing task owner; declarations record the registered workspace in their existing task context. Unknown old project facts remain unknown.

Privacy was committed first in 1e4a3d97: project_of reads registered workspace labels through the settings catalogue and resolves git worktrees through their common git directory. It returns no project when no registration matches. The runtime test checks arbitrary registered labels, a worktree and an unknown path, without including private names.

The supplied design_compare.js was run with --app pointing at this worktree, --group v48 and --state v48.shell,v48.home1. It stops at its obsolete New task button selector before it emits its comparison report. compare-output.log preserves that error; the frozen-reference pairs and the real-owner browser court remain available. External prior art checked: https://code.visualstudio.com/docs/agents/run/sessions/organize-sessions (workspace/timeframe grouping and archived sessions); fit follows research res-038, not a new store.

Removed: the one-option Resume switch, synthetic unreported plan cards, and the Home microphone. Commands / Sketch / Mark / Mask remain reachable through the composer scope context menu; attachment remains +. Search stays available through Ctrl K.

Remaining differences: project subgroup detail is omitted under the explicit time-box priority; state sections and archive handling are retained. Initials plus distinct identity marks are used (no vendor logo assets exist in the current avatar component). Real thread/output text replaces reference sample data and CAD thumbnails. Some spacing remains approximate. The generic comparison tool is not green. No push, install or release; installed behavior is not claimed.
