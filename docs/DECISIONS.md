# Decision log

Every architecture-class change (store, runtime, launcher, dependency, gate, top-level package, file over 3,000 lines) adds one entry here in the same commit. `.githooks/pre-commit` → `tools/pipeline/decision_check.py` refuses the commit otherwise.

Entry format:

```
## D-<nnn> <title> (<date>, <agent>)
Request: F<n>
Prior art: <product> -> <mechanism>; <product> -> <mechanism>
Replaces: <what is replaced and deleted in this patch> | nothing exists
```

Open RED decisions (taken before this gate; to reverse or fix): see `70.HANDOFFS/archhub-integrated-repair-20260909/01.WIP/ARCH-DECISIONS-AUDIT-2026-10-17.md`.

## D-001 Restore the product pre-commit gate and refuse unrecorded decisions (2026-10-17, Claude c91e research)
Request: F76
Prior art: ArchUnit -> architecture rules fail the build; MADR/Nygard ADR -> one record per decision
Replaces: the .githooks/pre-commit deleted in 458fb512 (2026-07-27); this interim check is replaced by compiler E0600 (ACOMPILER3R) and then deleted

## D-002 BABOOM presence defaults to the tray; no new store (2026-10-18, Claude 717)
Request: F31
Prior art: Windows notification area -> status as a tray badge and tooltip, details on click; Discord/Slack tray presence -> background agents live in the tray, never float over other apps
Replaces: the always-on-top BABOOM companion window and its floating "Reconnecting to ArchHub…" panel and "Open ArchHub" button (removed in this patch). The "new store" flagged by decision_check is a test fixture opening a scratch SQLite file inside tests_replica/test_presence1_acceptance.py; no product store is added.

## D-003 AGENTLINK2 - one Workshop mailbox (2026-10-18, Codex)
Request: F37
Founder verbatim: "Every agent talks through one shared message store with two tools; the machinery it replaces is deleted in the same patch."
Founder verbatim: "ONE store (the existing Workshop messages table) plus MCP `send(to, text)` / `read(since)` on the existing agent MCP server, for every agent. No owner binding, no recovery mode, no relay."
Prior art: mcp_agent_mail -> mailbox plus send/read shape supplied in the founder brief (checked licence has OpenAI/Anthropic rider; no code adopted or analysed); Claude Code agent teams -> named peers sharing tasks and messages (official docs, clean-room behavior); OpenDesign (Apache-2.0) -> declarative runtime definitions and one registry, no native-owner state machine.
Replaces: native_mcp_launcher.py, deferred_codex_binding.py, native_resume_guard.py, recovery-only MCP server and coordination owner/rebind/attachment tools, the six bound cloud chat APIs, the unused clean browser participant path, and the obsolete bound generic writer/ack/list/register/lens adapter branches. No owner API remains on shared messaging. Caller-map evidence identifies separate Work/file/host/cloud dependencies retained under their existing authority.
Budget: exchange <2 s for two started independent agent client processes, each with its own MCP connector, measured separately from installed acceptance; zero idle graph growth; bounded incremental public read, 100 rows/240000 bytes. Installed acceptance remains 717's post-landing court.
Told: 2026-10-17 user-facing plan stated shared Workshop send/read, same-patch deletion, no binding or new UI.
Identity: server observes authenticated local named-pipe PID and creation time. Codex threadId and OpenCode ai.opencode/sessionID are read only from host MCP request metadata, then namespaced under the OS-observed connector identity. The existing author field records a registry-based generated project/session label with that unforgeable key. Readable labels survive connector restarts; absent host session metadata, project labels can be ambiguous. No per-session owner map or registration exists. Model-visible tools cannot set sender or context; the local CLI host owns its MCP metadata. Caller-provided sender fields are refused. The verified dispatch, checkpoint and existing Workshop route/scope guards apply; an OS peer may send 30 accepted notes per rolling minute regardless of host session metadata. No graph enrollment, Work grants, founder-private reads or tool effect replay.

Primary metadata contracts checked 2026-10-17: https://github.com/openai/codex/blob/main/codex-rs/app-server/src/request_processors/mcp_processor.rs (host overwrites threadId); https://dev.opencode.ai/v2/docs/mcp-servers/ (ai.opencode/sessionID). These are protocol correlation fields, never a sender tool argument.

Retained callers: NativeWorkDelivery contact effects serve workshop_workflow native execution and independent review, plus workshop_session_start native CLI start. NativeAgentSession/file permit release/recovery serve governed Work/file/host authority only. Signed clean host serves Workspace Settings and host/Work effects; remote OAuth work.claim remains independently authorized. Session Link physical transport remains only for Work contact effects, cloud native-session discovery/interruption and Goose ACP owned-process cleanup. The development-only NodeServer moves into its sole real caller tools/serve_grandmap.py; its behavior tests remain.
Private integration: the obsolete archhub_message branch in 00.GOVERNANCE/hooks/opencode_native_gate.py and the stale messaging allow/deny names in hooks/native_workshop_launch.py are replaced by the pinned two-file companion, kept outside the public product patch.717 must land that companion with the product; adjacent archhub_work and private reviewed-candidate readiness checks are preserved. Installed acceptance remains717.
