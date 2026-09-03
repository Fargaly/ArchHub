# Clean coordination endpoint

The one clean-graph owner on this machine. Agents enroll and coordinate
through it. It is not the legacy machine-transport runtime and shares no
state with it.

## Address

    GET  http://127.0.0.1:8474/health
    POST http://127.0.0.1:8474/coordination

Loopback only. `Host` must be `127.0.0.1:8474` or `localhost:8474`, and
`Origin`, when sent, must be `http://127.0.0.1` or `http://localhost`.
Anything else is refused before the body is read. Request bodies are
capped at 64 KB.

## Health

    {"ok": true, "graph_id": "<uuid>", "revision": <int>}

`graph_id` is the CURRENT generation under the runtime root, and
`revision` is that graph's live revision. There is no pid file and no
status field to go stale: liveness is the OS-held owner lock on the
generation, so the service cannot advertise itself as active while dead.

## Signing

Every coordination request is signed with a DPAPI-held caller key.

    from nodelang.clean_coordination_host import CoordinationIdentity
    from nodelang.clean_coordination_mcp import LocalCoordinationClient
    from nodelang.runtime_caller_capability import WindowsDpapiCallerKeyStore

    identity = CoordinationIdentity("codex", "<thread-id>")
    keys = WindowsDpapiCallerKeyStore(WindowsDpapiCallerKeyStore.default_path())
    client = LocalCoordinationClient(identity, key_store=keys)
    client.call("register_session", {})

The sender is derived from the signed identity. It cannot be supplied as
a parameter, so one agent cannot post as another. An unsigned request is
refused with `coordination request fields are invalid`; a forged
signature with `coordination request signature is invalid`.

## Methods

    register_session     enroll this provider/thread as an agent session
    list_agents          enrolled sessions, including your own
    inbox                messages addressed to you
    send_message         direct message to one session
    followup_task        follow-up into an existing session inbox
    wait_agent           block for a peer response newer than a sequence
    mark_message_read    acknowledge one delivered message
    interrupt_agent      cooperative interrupt request
    scope_lens           projected scope for a root
    workshop_lens        Workshop projection
    revise_instance      revise one instance through the signed path

Enrollment is idempotent: repeating it returns the same session rather
than creating a second one.

## What it does not do

It issues no CDE write permit. `_METHODS` has no permit call, so file
writes gated on `brain.universal_cde_write_permit` are not served here.
That permit still routes to the legacy machine-transport runtime.
