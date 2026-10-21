# Session Link physical transport

Ordinary MCP `send`, `read`, and `declare` now use the selected profile's public
Workshop conversation table through `workshop_mailbox.py`. They do not resolve
the GUI runtime pointer, start Qt, open the graph, or acquire a signing key.
The application uses the same implementation and rows. Declarations are typed
SQLite rows rather than graph cells. The profile must already contain its
conversation binding; missing profiles never create a replacement database.
Private conversations and private reply references remain outside this API.
Work and host actions retain their existing authority boundary.

The existing Session Link implementation is reused here. `../session_link_transport.py`
owns one bounded Node worker per call, with no new service, room, model session or
message database. The application owns graph admission, enrolled identities,
request idempotency, durable attempted/outcome records and Work settlement.

`SessionLinkTransport(node_executable, state_dir, env=None)` exposes:

- `discover(timeout_seconds=20)` → `{status, recipients, providers, ...}`.
- `request(recipient, text, timeout_seconds=180, cancel_event=None,
  permission_mode="prompting")` → `{status, request_id, recipient?, reply?, reason?, ...}`.
- `close()` signals owned active waits to stop and prevents new calls.
- `create_channel()` returns a fresh unattached transport with the same runtime
  and instance state, cleared Codex caller context and no worker process.
- `cancel_pending(timeout_seconds=8)` signals and joins the active local call
  without closing the channel. Check `local_call_joined`; `uncertain` means the
  bounded join did not finish. It never claims external cancellation/revocation.

Recipient must be an exact descriptor from discovery; the worker compares its
app, native ID, process/port/socket, workspace and provider runtime again before
dispatch. Duplicate native IDs across IDE windows use `selector=ID@PID`. These
facts establish routing only; they cannot enroll an agent or grant graph authority.

States: `not_sent` is a pre-dispatch refusal; `replied` includes native reply data;
`uncertain` requires external reconciliation before retry; `cancelled_wait` stops
local waiting and never claims recipient cancellation. Even `replied` leaves
`work_authority=false` and `execution_verified=false`. Caller admission and durable
attempt records must precede the effect. There is no automatic retry.

Worker input/output is bounded. Windows workers run in an owned kill-on-close job,
so terminating a wait cleans up its helper descendants, not the existing native
host apps. V8 heap is bounded at 96 MiB; one worker may run per transport object.
Application scheduling must bound the number of transport instances (the current
attachment integration admits at most eight per-session channels, one dispatcher).
The base transport serves non-Codex recipients; each Codex recipient needs its
own exact attached channel. Discovery
uses targeted native APIs and registry metadata, not full transcript replay.

Frozen layout: `runtime/node.exe`, its matching license, and all assets in this
directory. Source execution requires an explicit admitted Node executable.
No PATH or handoff-directory runtime fallback is used. `state_dir` must be outside
the entire source/frozen root and contains disposable connection routing and locks
only. Claude-native ephemeral peer credentials stay in its native registry; they
are never vendored or logged. `vendor/PROVENANCE.md` records MIT dependency origin.

`opencode-plugin.mjs` is the managed host plugin factory. A deployment-owned host
entry supplies `createSessionLinkPlugin({stateDirectory})` using the same admitted
application state directory; it must reference installed assets, not a development
checkout. Changing host attachment is an explicit lifecycle operation. Existing
personal provider plugins/daemons remain running until their normal reconciled
migration; application discovery must report them unavailable when unattached.

Compatibility `ask.mjs`, `bridge.mjs`, and `session-link.ps1` preserve the personal
CLI. The product callable uses `worker.mjs`; it never starts persistent bridge
daemons. Legacy personal entry points forward to this canonical implementation.

Limits: Windows native integrations are verified on the development host, not on
a clean installed machine. Codex needs an admitted native app context; absence is
not permission to borrow an identity. Antigravity uses an internal API and reuses
the exact native model/permission configuration. Native busy sessions are refused.
The caller must prevent synchronous requests to its own waiting session.

## Explicit free OpenCode model selection (source; activation required)

The compatibility CLI can request one approved free OpenRouter model for one
prompt in an existing OpenCode session:

```powershell
& $sessionLink ask --app opencode --session $existingSessionId --file $messageFile --provider openrouter --model 'qwen/qwen3.8-27b:free'
& $sessionLink send $existingConnectionId --file $messageFile --provider openrouter --model 'nex-agi/nex-n2.5-pro:free'
```

Use the installed `session-link.ps1` path, an exact discovered session or saved
connection ID, and a UTF-8 message file. Both provider and model are required for
selection. Omitting both retains the original SDK prompt behavior. No global or
session configuration is written; native last-used-model behavior is not controlled
by this adapter. This option is not yet exposed by the product Python worker API.

The approved IDs are declared in `opencode-model.mjs`. Immediately before prompting,
the plugin reads the public OpenRouter catalogue with an eight-second timeout and
an eight-MiB response cap. It requires tool support and zero prices for every
reported pricing field, including prompt/completion. Missing, null, malformed,
negative or nonzero prices refuse the request. There is no paid fallback.

The [official OpenCode SDK](https://opencode.ai/docs/sdk/) documents
`session.prompt` with `body.model: {providerID, modelID}`. No output-token option
is added. Give free workers sufficient task context and output room; resource
limits and one-local-job scheduling still apply.

An explicit request checks the running plugin's capability before sending. Old
bridges reject `send-model`; old plugins reject `capabilities`. Never retry a
timed-out or uncertain request automatically. A locally queued message or an
`onDispatch` callback establishes at most a plugin RPC attempt, not that a native
prompt ran: catalogue validation may still refuse inside the plugin.

The receipt contains requested and actual provider/model for **every assistant
message in the exact completed turn**. Missing or mismatched identity yields
`model_selection_failed`, not proof the requested model ran. `ask` prints the
receipt and exits nonzero on mismatch; the persistent bridge forwards the status
and receipt visibly to the bound Codex task and records them in its delivery log.

Packaging already includes this entire asset directory (`ArchHub.spec`). Activation
also requires a deployment-owned OpenCode entry importing the installed plugin
factory. An existing inline personal plugin does not acquire these changes from
a package update. The [plugin documentation](https://opencode.ai/docs/plugins/)
loads local plugins at startup. The current plugin retains its server in a process
global singleton and exposes no hot-reload/teardown operation; a supported in-process
upgrade has not been established. Coordinate a normal OpenCode process restart
only after its work and uncertain requests are reconciled, retain the same native
session, then resume the exact saved binding and verify one new reply/receipt.
Do not kill the process or restart other apps to activate this feature.

## Retained transport boundaries

The public mailbox uses the selected profile's existing conversation tables even
when the Qt window is closed; a missing profile is never replaced. MCP session
metadata supplies a stable display address across connector restarts, not Work
or host authority. Raw pipe clients use their observed process identity. Supply
the same `idempotency_key` to MCP `send` when retrying an uncertain message;
reuse with different content is refused. Native task completion still requires
the independently observed target process generation. Declaration liveness
follows the originating native agent parent, not unrelated desktop ancestors.

Agent coordination uses the existing Workshop messages table through MCP `send(to, text)` and `read(since)` (`nodelang/native_agent_mcp.py`). It has no native-owner attachment, recovery-only server, enrollment, Session Link host channel or Workshop relay.

Session Link files still used by separate capabilities remain here: `session_link_transport.py` supplies the cloud relay and the existing Work/session discovery and execution paths; `_OwnedProcessJob` contains Goose ACP child-process lifetime. `session_link_config.py` and the governance hooks still install and enforce governed file/Work permissions. These are not the agent mailbox. Historical delivery readers continue to render previously stored receipts without replaying them.

## Agent communication cutover (AGENTDECLARE)

Public ask/send/reply/answer chat entrypoints now post to Workshop through the existing MCP sink. serve/connect/reconnect no longer start a peer-chat pipe. Use MCP declare/read/send for all agent communication; reply_to keeps coordination in one thread. The earlier personal-chat examples above are historical and are not the post-cutover interface. Application-owned native task execution uses a mailbox task pointer, then reads its authenticated completion from that same mailbox. No separate request/reply files or completion pipe are created by ask.mjs.
