# Native owner recovery

Source implementation: explicit owner-change recovery for the general native
MCP profile and a guarded private hook composition. Installed activation remains
open. The same explicit operation also recovers a locally proven expired lease
on an unchanged owner; an unknown remote-session error alone is not expiry proof.

After an application update, a retained MCP process can still hold its previous
owner descriptor. Ordinary tools refuse this mismatch before performing effects.
Calling coordination registration or reclaiming Work does not replace that
native binding.

The general profile exposes `native.owner_status` and `native.owner_rebind`.
Inspect status first, then supply the exact old and current owner fingerprints
to rebind. The operation preserves configured runtime/external session identity,
application/database identity and the existing graph AgentSession. It enrolls
once against the verified new owner and advances the guarded delegate generation
under the existing owner lock. It neither executes nor replays the failed task.

Concurrent calls are quiesced. Rebind inside an active call is refused. Owner
selection drift, another instance, a different graph session, or lack of genuine
session continuation is refused. An uncertain enrollment is retained and cannot
be retried automatically. An existing live duplicate capability is not bypassed.

For idle expiry, status reports `lease_expired` from the retained local lease
deadline and `recovery_required`. Supply the same verified fingerprint for old
and current owner. The operation refuses a valid or unknown deadline and refuses
descriptor drift under the same runtime identity. It still requires one genuine
continuation of the same graph session. No periodic idle polling is added.

After rebind, read current Work and Workshop state before taking another action.
Changed or uncertain results require their normal reconciliation path. A status
read or successful rebind is not evidence that a task completed.

## Deployment boundaries

- An old process must load this implementation before these tools exist. Editing
  files does not inject registrations into already-running clients.
- The selected-Work profile retains its existing 18-tool inventory.
- Private hook compositions must register their retained process-custody guard
  once. Recovery checks it before and after enrollment. The write delegate
  refreshes only after the owner generation advances with the same graph session.
  A marker alone cannot enable this path.
- A command hook routed to an old Brain HTTP adapter has a separate transport
  mapping. Graph enrollment elsewhere does not prove that mapping exists.
- No application shutdown, child-process termination, configuration rewrite, or
  alternate owner is performed by these tools.

## Claude Desktop and command hooks

The workspace's private bootstrap composes the existing native MCP, write relay
and completion evaluator around one NativeAgentSession. It does not enroll a
second HTTP Brain session. The runtime selector is `claude`; accepted client
aliases normalize to it before enrollment. Raw alias enrollment is refused
(`nodelang/application_server.py:9591-9595`). That describes the private
bootstrap only. The installed hooks in `~/.claude/settings.json` still pass the
raw alias: SessionStart (line 74) runs
`../12.PRODUCTION/tools/brainwrap.py session-start --vendor claude-code`, Stop
(line 85) runs the installed copy of `native_stop_hook.py --vendor claude-code`
(byte-identical to `nodelang/native_stop_hook.py`), and the UserPromptSubmit
`brain.work_assigned_block` call (line 136) sends `"runtime": "claude-code"`.
`nodelang/native_stop_hook.py:21-27` (`canonical_runtime`) normalizes the alias
to `claude`; `brainwrap.py:439-459` (`cmd_session_start`) forwards it unchanged
(defects A and A2 below).
Historic `claude-code` graph records and receipts are retained, not merged.

Both relay peers must use the same trusted interpreter and explicit scripts,
share the retained native Claude process identity, and agree on the native
session. The private adapter admits fixed CLI/Desktop executable locations and
checks explicit session/resume identifiers or the Desktop child session export.
Ambiguous continue, identifier-free resume and fork launches remain refused.
These checks constrain cooperating local processes; they do not isolate an
adversarial user of the same Windows account.

Activation must load the new stdio implementation and route the associated hooks
to that same owner together. Leave the current profile intact until that path
is ready; setting the hook marker without the relay would block writes. Existing
running processes do not acquire new code from configuration or source edits.
No supported reload of the currently running Desktop MCP has yet been verified.

Claude's [configuration reference](https://code.claude.com/docs/en/debug-your-config)
documents that settings-file hook changes can take effect in a running session,
while MCP children need their own per-server environment. Do not switch hook
commands or markers ahead of the matching MCP process. Review both configurations
as one activation change, including effects on other running Claude sessions.
The private bootstrap, command hooks and MCP must use the same interpreter; do
not pin a particular conversation ID into shared configuration.

### Activation dependencies

Keep the existing `archhub-agent-coordination` server identity. Its native
composition uses the private `native_workshop_bootstrap.py serve` entrypoint,
which imports the installed product. The same trusted Python interpreter must
run that process and the command hooks; a venv/global interpreter split is not
an interchangeable configuration. The bootstrap supports `serve` and `stop`,
not a second SessionStart enrollment command.

Set the native-owner marker and runtime selector on both the MCP process and
the command-hook processes. MCP environment settings do not configure separate
hook children. Native session identity comes from the verified Claude process;
never put an external session ID in shared settings. Check all affected active
sessions before applying a global hook change.

| Existing behavior | Native disposition | Remaining evidence |
|---|---|---|
| SessionStart legacy enrollment | Native stdio owner connects once; no second enrollment hook | Installed process and hook must share that owner |
| Pre/Post write gate | Existing scope gate through the native relay | Actual permitted write and receipt, plus denied out-of-scope write |
| Stop completion | Native completion evaluator reads graph Work state | Installed Stop invocation; it must not manufacture acceptance |
| Prompt context | `native.hook_user_prompt_submit` supplies bounded current Work and ordinary messages | Hook configuration and delivery; not equivalent to full skill/context retrieval |
| Automatic Work assignment | Existing explicit `coordination.claim_work` claims exact Work | Prompt context does not automatically assign Work; preserve this distinction |
| Legacy observation and skill mint | No equivalent native replacement established here | Reconcile requirements before retiring; retaining a legacy authority is not migration |

Do not report this table as active hook coverage. Replacing only the MCP process
or only the hooks leaves a mixed profile. Configuration rollback must restore
the matching pair and use a supported reconnect; it cannot revert an already
running process. Preserve uncertain effects and historical session identities
without replaying actions or enrolling substitute owners.

`tests_replica/test_native_owner_rebind.py` and the existing native session/MCP
checks use signed descriptor fixtures and a recording transport. They cover
stale refusal, continuation, delegate replacement, concurrency, and uncertainty;
they do not prove installed process activation or live write-hook enrollment.

## Known governed-write enrollment defects (recorded 2026-09-16)

Source record:
`70.HANDOFFS/claude-codex-link-20260914/runtime-adapter-recovery/717-coordinator-state-20260916.txt`
(steps 1-9). Owner: transport/root. Nothing here is fixed by editing this page;
it is listed so a maintainer does not re-diagnose it. Line numbers were read
from the working tree at HEAD `b914892` (2026-09-16 20:46) and from the
installed `~/.claude/settings.json` of that day; the record's own numbers
(`universal_application.py:38496-38499`, `:38517-38534`) have drifted since.

Recovery ladder observed on one boot: ArchHub down, the gate refuses
"MachineTransportError: universal runtime pipe is unavailable"; ArchHub up and
the brain daemon down, "Brain tool request failed"; both up, "RuntimeError:
external session is not enrolled"
(`../12.PRODUCTION/personal-brain-mcp/src/personal_brain/universal_session_manager.py:451`).
Enrollment lives in the brain daemon's memory and dies with it.

- **Defect A (alias).** `~/.claude/settings.json:74` runs
  `brainwrap.py session-start --vendor claude-code`;
  `../12.PRODUCTION/tools/brainwrap.py:439-459` (`cmd_session_start`) forwards
  that vendor unchanged to `brain.hook_session_start` and prints nothing by
  design; `00.GOVERNANCE/hooks/agent_scope_gate.py:30-37` (`_RUNTIME_BY_VENDOR`)
  maps vendor `claude` to runtime `claude-code`; enrollment accepts only
  `claude` (`nodelang/application_server.py:9591-9595`: "Claude enrollment
  requires canonical runtime claude; use the existing native owner, not a
  second alias capability"). After any brain-daemon restart a Claude session
  loses governed writes and its own SessionStart hook cannot restore them: the
  configured hook exits 0, prints nothing and does not enroll. The same call
  with vendor `claude` enrolls.
- **Defect A2 (alias lock-in).** A session the hook already enrolled under
  `claude-code` cannot re-enroll as `claude`: the server answers "runtime Agent
  Session identity is already bound; renew it instead"
  (`nodelang/application_server.py:9684-9686`) and no renew tool is exposed
  (`personal-brain-mcp/src/personal_brain/server.py` registers no `renew`
  tool). Such
  sessions stay write-blocked for their whole life. Only a session whose alias
  enrollment was never made, or was wiped by a brain restart before
  re-enrolling as `claude`, can write.
- **Defect B (unwired Work).** `brain.universal_work_create` passes no
  structured references by default, so a new Work's inputs, requirements and
  `cde-container` interfaces are created unwired. `authorize_universal_cde_write`
  (`nodelang/universal_application.py:38754`; `:38772` "CDE write requires one
  claimed governed Work"; `:38791-38798` requires exactly one `cde-container`
  interface; `:38804-38808` reads its target as a value graph) then fails in
  `nodelang/cell_value_graph.py:414` with "value-graph root is not registered
  exactly once". The supported creation route can produce a Work that can
  never obtain a CDE write permit, and the refusal names the value graph
  rather than the missing interface.
- **Defect C (dead end).** While the unwired Work stays claimed, every further
  attempt refuses "Agent Session owns multiple active governed-work
  assignments" (`nodelang/universal_application.py:38732`, raised in
  `_read_universal_current_bound_work`, `:38672`). The only way out of B is to
  release that Work; nothing in the refusal says so.

Working recipe today: create the Work with `structured_references` (inputs,
requirements, and one `cde-container` shaped for
`nodelang/cell_cde_authority.py:259-300` `authorize_cde_container_write`:
`container_id` `GM.x.y`, `source_requirement`, `domain`, `suitability_status`,
`owner`, `checker`, `gate_kind`, `tier` T0-T3, `gate_spec` object,
`lifecycle_state` WIP, `revision`, `write_grants`, `allowed_paths`), then claim
exactly one Work. Governed writes were restored this way on 2026-09-16; the
source record is the proof. A fix belongs in the hooks and the enrollment
path, not in this page.
