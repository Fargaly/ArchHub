# OpenCode native governance activation

Status: source candidate, synthetic checks only. Not active in OpenCode.

The public `nodelang/session_link/opencode-governance.mjs` plugin uses Node
child_process, never Bun.spawn. A trusted private loader supplies an absolute
Python command and one private native-gate composition script. Public product
modules do not import workspace governance or legacy source trees.

For each actual `tool.execute.before` sessionID, one direct child retains a
NativeAgentSession. OpenCode has its own exact native body/catalog entry;
its identity cannot be substituted with another runtime. The child observes
its installed OpenCode.exe parent, creation time and native session export,
and reads the exact session through that parent's authenticated loopback API
before enrollment. This proves local host/session custody, not isolation from
a malicious same-user process or proof that arbitrary plugin code is trusted.

The private composition injects NativeWriteTransport into the existing
placement/permit/receipt gate. Pre/post share the native sessionID and callID,
normalized original arguments, workspace and retained owner. Successful
pre-admission alone is never a completed write. Missing/failed post receipts
retain the pending entry and block continuation. No idle hook clears it.
Supplemental legacy Brain observation is not called: graph permits/receipts
remain the authority. Migration of general observation/learning is separate.

Supported tool mappings: read/glob/grep/list, Write from native write, Edit
from native edit, and Bash from native bash/powershell. Patch, custom tools
and tools with unknown argument shapes are refused until their governance path
is admitted. Node compatibility does not authorize arbitrary shell mutations.

Shell admission lives in the shared gate (`pretooluse_validate.shell_admission`).
It has no parser of its own: it tokenises with the gate's `_split_shell` and
first applies the gate's command rules (worktree, clone, copy, kill, launch,
secrets, BelowNormal, private areas), each refusing with its own quoted rule.
Only then do rules SHELL-0..6 narrow it to the OpenCode allowlist: read-only git
(status, log, diff, show; archive/--output only into the admitted lane),
`cmd /c start "" /belownormal /wait /b` python -m pytest or node --test with
every path inside one 70.HANDOFFS/<lane>/work/<export> and each test path an
existing directory or a .py (pytest) / .js .mjs .cjs (node, at least one path)
source, never a glob, mkdir/rmdir of the
test lock, and mkdir/rmdir/Set-Content only inside the session's admitted lane
folder (`laneFolders` in the trusted loader), never OpenCode configuration
(~/.config/opencode, .opencode, opencode.json[c]) or a `.git` folder by any path,
junction, redirect or Windows spelling (trailing dots/spaces); no path names a
`:stream`, and Node configuration (package.json, tsconfig.json, node_modules
JSON) is never written. Shell
writes create plain data files only (.txt .json .md .log .out .csv .patch .diff,
git archives); anything a test run could execute or import (.py, conftest,
.mjs/.js, .ps1/.cmd/.bat/.sh, pytest.ini) goes through the governed file-write
tool. Every shell write target also
passes the placement validator. Refusals quote the rule. Shell carries no graph
permit or receipt; the allowlist is its admission.

A native Edit refused as `[write_target_unresolved] write session identity is
unresolved` came from the retired singular loader, which sent no OpenCode
callID, so the broker had no tool_use_id. This plugin sends sessionID and
callID as session_id and tool_use_id; gate refusals now name their rule.

Limits: four live owners, 128 retained session identities, 64 queued native
requests per session, one MiB request/reply, 64 KiB child diagnostics, and a
30-second caller wait. Read hooks retain separate call records; native RPCs
serialize, but one read's after hook need not precede another read's before
hook. Writes require no other pending tool. Unknown outcomes block continuation.

After ten idle minutes, one hour total, explicit disposal, or before the exact
lease deadline minus60seconds, the private worker requests release only with
no pending tools. It renews while tools remain active. Known expiry or installed
owner change uses the existing same-instance rebind with both observed owner
fingerprints only without pending calls or release ambiguity.
The server refuses this actor's active operations, all unreceipted active permits
(including expired ones), attached Session Link channels or pending deliveries.
Expiry never proves that a write did not happen. Late settlement of an expired
unreceipted permit remains an open reconciliation gap; custody is retained.
Consumed/revoked permits retain their original evidence.
Graph session identity, Work claims and history remain.
Reopening requires a confirmed release handshake plus clean child exit and must
return the same graph identity with continued=true. An unexplained exit
quarantines that session, but observed child exit frees the live slot for other
sessions. The next call reconciles instead of waiting for a restart: a release
ack from the exact actor lifts it; otherwise one read-only probe
(`opencode_native_gate.py --reconcile`, the existing agent-session-reconcile
route with the effects projection) lifts it only when the owner holds no
binding (released) or an expired one (owner gone) with zero unreceipted
permits and no active operation. Anything else stays refused, reuses its
verdict for 15 seconds, and names the coordinator command
`opencode_native_gate.py --reconcile-status <session> <actor>`. Reopening
still pins the recorded actor; no probe enrolls. Plugin records left uncertain
settle on the same verdict only for read, write and edit, whose effects the
permit/receipt ledger accounts. Uncertain shell calls and Work executions carry
no permit, so they stay retained and refused. A sealed last-request watermark plus clean exit can prove a racing
request was not evaluated. That call returns non-delivery, never automatic replay.

The private worker reads its inherited pipe on the main thread, with a bounded
byte buffer and deadline-aware readiness checks. No buffered stdin daemon remains
at interpreter shutdown. Its one-hour retirement preference never cuts off
pending calls. EOF or unavailable lease with pending effects emits an unresolved
result and exits unsuccessfully; it cannot recreate a closed postreceipt channel.
Graph permits and plugin pending records remain for explicit reconciliation.

Local before-hook refusals proven to occur before an input write remove only
that call's preparing record. Transport uncertainty and after-hook failures
retain their records. A prior request failure does not imply that a later queued
request was delivered. No refused call is automatically replayed.

A lost release response permits only an explicit status read with the same
old capability, release ID and OS process custody. Up to 128 receipts retain
the old HMAC verifier in runtime memory for 600 seconds; no live receipt is
evicted to make space. IDs contain creation seconds and random bytes, and new
release attempts older than 60 seconds refuse. Thus an expired old request
cannot retire a rotated capability. Missing/rotated recovery proof remains
unknown. An exact retained token/OS-peer status can prove non-release and restore
the client for explicit detach or settlement. An expired retained token grants
no lease: existing known-expiry rebind is required. No tokens enter files/replies.

Permit checks stream the graph registry outside mutation/session locks, with
constant auxiliary memory and no lifetime count cutoff. Only this actor's
permit fields determine release. The sole production issue/consume routes
advance an in-memory activity fence before their graph transaction. Rechecking
that binding prevents this actor's concurrent permit race without rejecting
unrelated revisions. This fence is not a permit ledger or write authority.

## Coupled activation and recovery

1. Root independently reviews native custody, exact catalog migration, private
   gate injection, pre/post pairing, and the installed package inclusion.
2. Install the reviewed product candidate and verify the exact OpenCode body
   and catalog entry in the same application instance. Never use wildcard body
   fallback as proof of native admission. Install the release/status routes,
   native client and worker together with the exact catalog migration.
3. Verify the actual OpenCode plugin version supplies sessionID/callID and
   after-tool args. Verify Edit newline prediction against a real reversible
   fixture before admitting writes; synthetic mapping is not byte proof.
4. Replace the legacy loader only as one reviewed profile: public installed
   governance module, private composition, installed interpreter, and existing
   public Session Link plugin. Preserve the old loader as exact rollback
   evidence outside the active plugin directories. Never load both profiles.
5. OpenCode documentation guarantees startup discovery, not safe hot reload.
   Do not change live files or restart for this candidate. If supported reconnect
   cannot reload the existing session safely, root must request that specific
   reconnect after the complete profile is ready. Do not create another chat.
6. Prove one actual native prewrite permit, file outcome and postwrite receipt
   using the same session/call and graph actor; then prove a refused write.
   Tool access remains unverified until these installed checks pass.
7. On refusal/uncertainty retain exact IDs and pending records. Roll back the
   complete profile only after settling or explicitly recording in-flight
   work. File rollback does not change already loaded plugin processes.

The separate Claude MCP/command-hook profile must also activate together.
A legacy Claude hook reporting runtime Agent Session unknown cannot be repaired
by hot-loading a new hook ahead of its native MCP owner. Do not replay that
write, erase its pending evidence, or reuse another session's capability.

Sources: [OpenCode plugin hooks](https://opencode.ai/docs/plugins/),
[OpenCode plugin API](https://github.com/anomalyco/opencode/blob/dev/packages/plugin/src/index.ts).
