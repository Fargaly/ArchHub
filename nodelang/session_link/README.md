# Session Link physical transport

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

## Installed host attachment gap

The standalone installed application cannot currently promise Codex-to-Claude
round trips. `native.mjs` needs a live Codex host context; installing the transport
does not supply one. `ask.mjs` accepts a trusted caller permission class but does
not independently attest it. A graph admission or agent-supplied name cannot
convert the default `prompting` class into `bypass`. The transport now implements
an explicit scoped delegation seam; the application's authenticated enrollment
and delivery of that capability are still integration work.

| Direction from installed app | Current condition |
| --- | --- |
| Claude request and native reply | Available native transport; prompting may be held by recipient policy. |
| Codex request and reply | Requires an admitted live Codex task context or the explicit scoped attachment below; application enrollment is not yet wired. |
| Antigravity / IDE request and reply | Available for exact discovered idle, configured sessions; internal API compatibility remains a dependency. |
| OpenCode request and reply | Managed factory exists; host entry must load installed `opencode-plugin.mjs` with the same instance state directory. |
| Arbitrary existing terminal inbound wakeup | Not implemented; shell-capable terminals can initiate requests. |

Next integration work belongs in the existing application's attachment lifecycle:
bind the native Codex task through a host-executed attachment, validate its actual
host identity and current sandbox/approval policy, and scope dispatch to the
enrolled destination. Do not persist or replay another task's environment as an
identity. `native.mjs` is the native dispatch seam; `session_link_transport.py`
owns worker construction; `desktop.py` owns instance attachment lifetime;
`installed_workshop_coordination.py` owns admission. No new permission attestation
framework is introduced: the delegated path enforces prompting. Until application
attachment is wired, Codex remains unavailable and Claude remains prompting. A native
held/uncertain request requires reconciliation, not a permission change or retry.

For OpenCode, the deployment-owned host entry imports the installed factory and
passes the admitted instance state directory. No hot replacement of an active
personal plugin is performed by transport discovery. Existing native host
permissions and model configuration remain authoritative for all providers.

### Explicit existing-connection delegation

The host attachment owner imports `delegateInstance` from `bridge.mjs`, supplies
one exact existing runtime descriptor and an already authenticated/enrolled
instance ID, and delivers the returned capability directly into application
memory. Never log, print, put on argv, or persist this capability. The function
does not scan other connections, enroll an instance, or create a daemon.
The existing owner-authenticated control channel issues a grant for its bound
Codex destination, unique connection generation, and 1–900 second lifetime
(default 300 seconds). At most eight grants exist per connection.

The application calls
`transport.attach_host(capability, instance_id=admitted_id, destination=native_id)`.
Scope checks here do not replace application enrollment. Existing `discover` and
`request` calls use this exact grant over worker stdin. Only the bound destination
is discoverable through it; no other daemon or inherited context is borrowed if
it fails. The bridge rechecks the live native destination/workspace and grant
after lookup and before dispatch. Attached calls enforce prompting.

`detach_host()` explicitly revokes through the existing connection; failed or busy
revocation remains reported as such and is not automatically retried. Application
lifecycle should cancel/join active calls, detach, then close. `close()` stops local
workers only; it does not claim a remote revocation. An unrevoked grant expires at
its fixed deadline, cannot renew itself, and is lost on bridge disconnect or
restart. Replacing a local attachment requires successful detach first.

Capabilities are local-user bearer authority, not independent proof of an agent's
identity. The existing host owner and authenticated application attachment are
the trust boundary; arbitrary graph fields cannot issue grants. Existing in-memory
bridge versions without `scopedAttachment` support remain unavailable until an
explicitly reconciled lifecycle refresh. No running connection is hot-replaced.

### Application handoff contract for the existing owner

1. The application attachment handler authenticates the native host with its
   existing machine-session/peer admission. Resolve the already enrolled native
   destination from that session's stored external fingerprint and current host
   descriptor. A title, submitted runtime ID or a graph root alone is insufficient.
2. Call the existing `ApplicationServer.prove_runtime_backend_generation()` and
   bind an opaque scope to that verified backend generation and ownership root.
   `app:archhub` by itself is not instance-unique. The application supplies this
   scope as `instance_id`; transport never derives enrollment from user input.
3. The admitted host calls `delegateInstance` on its one selected connection.
   Deliver the result through the existing authenticated attachment request or
   an in-process callback, directly into the existing transport object's
   `attach_host`. Do not route the raw capability through Workshop conversation
   content, graph atoms, diagnostic bodies, tool output or launcher arguments.
4. Recheck backend generation and enrolled destination before accepting the
   capability. The application then calls `discover`, matches the exact native
   descriptor to the enrolled fingerprint, and records only routing metadata and
   state. `attach_host` is local validation; it is not a successful native probe.
   An unavailable/expired grant must leave Codex unavailable, without fallback.
5. `NativeRecipientRelay` retains message admission and durable dispatch receipts.
   Existing bounded `request` returns recipient text and transport outcome only.
   Do not promote that reply to agent-authored Work completion or permission.
6. On detach, enrollment change or backend-generation change, stop new relay
   admission, call `cancel_pending` and require `local_call_joined`, call
   `detach_host`, and close that
   transport. Preserve an uncertain revocation outcome, including the fixed grant
   expiry; no automatic resend or renewal. The next server generation starts
   unattached. Do not copy the old capability into launcher restart parameters.

Application owners still need to implement steps 1–4 and 6 in their existing
authenticated attachment/lifecycle path. The transport does not add an HTTP
endpoint or claim this contract is already wired. Attachment changes are refused
while a worker call is active, so one call cannot change origin mid-dispatch.

### Host helper binding

`host-attachment.mjs` exports asynchronous
`attachSessionLink(connection, client, {ttlSeconds=300}={})` and
`detachSessionLink(client)`. The supplied already-bound client implements
`session_link_scope()` -> `{instance_id,destination_fingerprint}`,
`attach_session_link(capability)` -> `{attached,instance_id,expires_at}`, and
`detach_session_link()` -> its individual session outcome. Attach verifies the
SHA-256 UTF-8 Codex ID fingerprint before reusing `delegateInstance`. It passes
the grant in memory and returns allowlisted status metadata only. No retry,
enrollment, model session, or global channel shutdown is added.

`host-worker.mjs` is a private child of the Python parent holding that existing
`UniversalRuntimeClient`. Set `SESSION_LINK_PRIVATE_HOST_IPC=1` and the admitted
`SESSION_LINK_STATE_DIR`; capture stdin/stdout exclusively. It is not exposed by
`session-link.ps1` and refuses ordinary standalone invocation.

Parent sends one newline-delimited JSON frame:
`{operation:"attach",connection:<exact runtime descriptor>,ttl_seconds:300}`
or `{operation:"detach"}`. Worker emits
`{event:"client_call",id,method,args}` for only the three client methods above;
parent invokes that method on its already-bound client and returns
`{event:"client_result",id,ok:true,result}` or `{event:"client_result",id,ok:false}`.
The attach call's private `args` contains the capability: never stream or log
these frames, persist them, or put them on argv. Only the final
`{event:"result",result:<status metadata>}` may reach public CLI stdout.

Frames are bounded at 64 KiB, client calls at three, lifetime at 115 seconds.
Scope/attach/detach wait budgets are 12/40/25 seconds to accommodate the existing
client's 10/35/20 second bounds. `{operation:"cancel"}` stops local waiting only;
delivery/revocation may remain uncertain. Parent disconnect or invalid frames
end the worker without retry.

The Python binding now exists in `nodelang/session_link_host.py`:
`run_host_handoff(client, *, node_executable, state_directory, operation,
connection=None, ttl_seconds=300)`. It holds no new enrollment authority, consumes
private worker frames, calls only the expected method sequence on that existing
client and strips arbitrary output fields. `NativeAgentSession` exposes
`attach_workshop_host(connection, *, node_executable, state_directory,
ttl_seconds=300)` and `detach_workshop_host()`.
Both hold the existing `bound_client()` identity/generation guard through the
operation; detach selects that session only and calls the existing application
client directly. It starts no Node child and needs no local host configuration:
the application already owns cancellation and revocation of the attached channel.

The general `native_agent_mcp.build_server` profile now exposes
`native.workshop_host_attach(connection, ttl_seconds=300)` and
`native.workshop_host_detach()` through its existing owner. Supply a non-secret
descriptor for one already existing connection; neither tool creates a connection
or enrolls another agent. For attachment, deployment supplies `SESSION_LINK_NODE` (or the packaged
`runtime/node.exe`) and `SESSION_LINK_STATE_DIR`; tool arguments cannot select
executable/state paths. The restricted `--workshop-task` profile returns before
registering these tools and retains its restricted surface.

This is source-level tool exposure. Loading it in an existing native agent,
installed handoff and actual native round trip remain to be verified.
The Python parent uses unbuffered pipes
and owned writer threads, waits only the remaining protocol deadline for writes,
and kills/joins the child during cleanup without exposing pipe errors. Existing
authenticated client calls retain their own finite deadlines; the 115-second
protocol budget is not a claim of instantaneous cancellation of those calls or
of remote grant revocation.
