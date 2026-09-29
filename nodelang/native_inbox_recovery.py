"""Same-actor read-only inbox access and evidence-based stale permit settlement.

After an owner replacement a native actor may be unable to restore its full
capability: conditional enrollment stays refused while one of its CDE permits
has no receipt. That refusal is correct for writes. It must not also cut the
actor off from reading the deliberation spaces it is authorized for, so the
same verified actor of the same instance may hold a separate read-only
capability. It sees exactly what its full session saw: public messages and
messages it wrote or received, in spaces where it is a participant.

A stale permit is reconciled only by its owning actor (or the in-process
instance owner) against the current file state the application observes
itself. File state is not execution history, so reconciliation never claims
the write happened or did not; it records what is there now, states its limits
and refuses any replay of that change. Age is a precondition, never evidence.
Each settlement is one bounded operational record (SPEC 3.3), not a graph
revision.
"""
import hashlib
import math
from pathlib import Path
import re
import secrets
import time
import uuid

from .application_machine_transport import MachinePipePeer
from .cell_authorization import AuthorizationDenied

NATIVE_RUNTIMES = frozenset({"codex", "claude", "gemini", "opencode"})
IDENTITY_FIELDS = frozenset({"runtime", "external_session_id", "expected_agent_session"})
SETTLE_FIELDS = IDENTITY_FIELDS | {"permit", "settlement"}
OWNER_SETTLE_FIELDS = frozenset({"expected_agent_session", "permit", "settlement"})
OUTCOMES = frozenset({"reconciled"})
INBOX_READS = frozenset({
    ("GET", "/api/universal/deliberation"),
    ("GET", "/api/universal/workshop"),
})
INBOX_READ_SECONDS = 900.0
INBOX_READ_LIMIT = 64
TARGET_READ_LIMIT = 64 * 1024 * 1024


def is_native_identity_body(body):
    return type(body) is dict and set(body) == IDENTITY_FIELDS


def is_native_settlement_body(body, *, direct):
    return type(body) is dict and set(body) == (OWNER_SETTLE_FIELDS if direct else SETTLE_FIELDS)


def native_inbox_read_admitted(request):
    """The read-only capability reads messages; it never sends or writes."""
    key = (str(request.get("method") or "").upper(), str(request.get("path") or ""))
    return key in INBOX_READS and (key[1] != "/api/universal/workshop" or not request.get("body"))


def refuse_legacy_space_for_recovery(owner, request):
    """Older graph-ledger spaces have no per-actor filter: never read them read-only.

    Their entries are returned whole (every recipient) under the application
    context, so a recovered reader is refused rather than confined by a wrapper.
    The decision comes from the binding revalidated under the route lock, so a
    capability retired after admission (or any unknown one) is denied, never
    passed. Internal calls and the founder desktop carry no machine session.
    """
    if request is None:
        return
    if type(request) is not dict:
        raise AuthorizationDenied("older conversation read requires an authenticated request")
    if set(request) == {"method", "path", "body"} or request.get("session") == {}:
        return
    with owner.mutation_lock:
        _root, binding = owner._machine_agent_binding_for_request(request)
    if binding.get("scope") == "native-inbox":
        raise AuthorizationDenied(
            "This older conversation cannot be read while the agent reconnects to the app")


def _verified_actor(owner, request, peer, body):
    """Same checks as effect inspection: signed local peer, exact original actor."""
    from .native_enrollment_reconciliation import PATH, reconcile_enrollment
    if type(peer) is not MachinePipePeer:
        raise AuthorizationDenied("native recovery requires an authenticated local peer")
    identity = {key: body[key] for key in IDENTITY_FIELDS}
    return reconcile_enrollment(owner, {**request, "path": PATH, "body": identity}, peer)


def open_inbox_read(owner, request, peer):
    """Issue one short read-only capability for the verified original actor."""
    from .application_server import _agent_body_catalog_entry_for_runtime
    from .native_session_release import _has_pending_permit
    body = request.get("body")
    if not is_native_identity_body(body) or body["runtime"] not in NATIVE_RUNTIMES:
        raise AuthorizationDenied("native inbox recovery requires the exact original identity")
    with owner.mutation_lock, owner._machine_agent_session_lock:
        identity = _verified_actor(owner, request, peer, body)
        actor = identity["agent_session"]
        entry = _agent_body_catalog_entry_for_runtime(
            owner.universal_store.snapshot(), owner.universal_registry, body["runtime"])
        capabilities = owner._machine_agent_recovery_capabilities
        now = time.time()
        for key in tuple(capabilities):
            held = capabilities[key]
            if held["expires_at"] <= now or (held.get("scope") == "native-inbox"
                                             and held["session_root"] == actor):
                # One read capability per actor; a new request retires the old one.
                capabilities.pop(key)
        if sum(1 for held in capabilities.values() if held.get("scope") == "native-inbox") >= INBOX_READ_LIMIT:
            raise AuthorizationDenied("native inbox recovery capacity is occupied")
        capability = "machine-recovery:%s" % uuid.uuid4().hex
        token = secrets.token_urlsafe(48)
        expires_at = now + min(float(owner.machine_session_lifetime_seconds), INBOX_READ_SECONDS)
        capabilities[capability] = {
            "session_root": actor, "token": token, "runtime": body["runtime"],
            "catalog_entry": entry.root_id, "device_custody": None,
            "external_session_fingerprint": hashlib.sha256(
                body["external_session_id"].encode("utf-8")).hexdigest(),
            "access": "recovery-read", "scope": "native-inbox",
            "enrollment_peer": {"pid": peer.pid, "created_at": peer.created_at},
            "issued_at": now, "expires_at": expires_at,
        }
        writes_blocked = bool(identity["active_operations"]) or _has_pending_permit(
            owner.universal_store.snapshot(),
            owner.universal_registry.cde_write_authority_protocol, actor)
        return {"agent_session": actor, "session_token": token, "capability": capability,
                "runtime": body["runtime"], "access": "recovery-read", "scope": "native-inbox",
                "continued": True, "issued_at": now, "expires_at": expires_at,
                "writes_blocked": writes_blocked, "revision": owner.universal_store.revision}


def _permit_for(owner, permit_root):
    from .cell_cde_authority import read_cde_write_permit
    from .native_session_release import _registered_permits
    protocol = owner.universal_registry.cde_write_authority_protocol
    snapshot = owner.universal_store.snapshot()
    if type(permit_root) is not str or not 0 < len(permit_root.encode("utf-8")) <= 512:
        raise AuthorizationDenied("stale permit identity is invalid")
    storage = protocol.operational_storage
    if storage is None or storage.get_permit(permit_root) is None:
        if permit_root not in set(_registered_permits(snapshot, protocol)):
            raise AuthorizationDenied("stale permit is unknown to this application")
    return read_cde_write_permit(snapshot, protocol, permit_root)


EVIDENCE_LIMITS = (
    "Current file state only. It does not show whether this permit wrote: a copy "
    "or restore can keep an old modification time, and the same content may have "
    "been there before. The change is not repeated automatically.")


def _identity(status):
    return (status.st_ino, status.st_dev, status.st_size, status.st_mtime_ns)


def observe_target(workspace_root, permit):
    """Current state of one permitted target; never a claim about who wrote it."""
    root = Path(workspace_root).resolve()
    target = (root / permit.path).resolve()
    if target == root or root not in target.parents:
        raise AuthorizationDenied("stale permit target is outside this workspace")
    if not target.exists():
        if target.exists() or target.is_symlink():
            raise AuthorizationDenied("the file changed while it was being checked; try again")
        return {"observed_state": "absent", "observed_digest": None, "observed_mtime_ns": None}
    if not target.is_file():
        raise AuthorizationDenied("the permitted target is not a file; it stays unresolved")
    before = target.stat()
    if before.st_size > TARGET_READ_LIMIT:
        raise AuthorizationDenied("the permitted file is too large to check; it stays unresolved")
    data = target.read_bytes()
    after = target.stat()
    if _identity(before) != _identity(after) or len(data) != after.st_size:
        raise AuthorizationDenied("the file changed while it was being checked; try again")
    digest = hashlib.sha256(data).hexdigest()
    if digest == permit.content_digest:
        state = "holds-permitted-content"
    elif b"\r\n" in data and hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest() == permit.content_digest:
        state = "holds-permitted-content-crlf"
    else:
        state = "differs-from-permitted-content"
    return {"observed_state": state, "observed_digest": digest, "observed_mtime_ns": after.st_mtime_ns}


def settle_stale_permit(owner, *, actor, permit_root, settlement, settled_by, now=None):
    """Reconcile one expired, unreceipted permit of actor against current state.

    File observations establish current state, not execution history, so the
    result is never "applied" or "not applied". It records what is there now,
    states its limits, and closes the permit: the same change is never replayed.
    """
    from .cell_cde_authority import ensure_store_cde_storage
    if settlement not in OUTCOMES or settled_by not in {"actor", "instance-owner"}:
        raise AuthorizationDenied("stale permit settlement request is invalid")
    if type(actor) is not str or not re.fullmatch(r"app:agent-session:runtime:[a-f0-9]{32}", actor):
        raise AuthorizationDenied("stale permit settlement actor is invalid")
    with owner.mutation_lock, owner._machine_agent_session_lock:
        permit = _permit_for(owner, permit_root)
        if permit.agent_session_root != actor:
            raise AuthorizationDenied("stale permit belongs to another agent")
        protocol = owner.universal_registry.cde_write_authority_protocol
        storage = protocol.operational_storage or ensure_store_cde_storage(owner.universal_store)
        held = storage.get_settlement(permit.root_id)
        if held is not None:
            return {**held, "already_settled": True, "replayed": False}
        if permit.state_root != protocol.states["active"]:
            raise AuthorizationDenied("permit already has a receipt; nothing to settle")
        now = time.time() if now is None else float(now)
        if not math.isfinite(now) or now < permit.expires_at:
            raise AuthorizationDenied("permit is still inside its write window; settle after it expires")
        if owner._machine_agent_active_requests.get(actor, 0):
            raise AuthorizationDenied("agent has a request in flight; settle when it is idle")
        workspace = getattr(owner, "universal_workspace_root", None)
        if workspace is None:
            raise AuthorizationDenied("workspace evidence is unavailable")
        observed = observe_target(workspace, permit)
        stored = storage.record_settlement({
            "permit_root": permit.root_id, "agent_session_root": actor,
            "outcome": "reconciled-no-replay", "execution_history": "unknown",
            "evidence_limits": EVIDENCE_LIMITS, **observed,
            "path": permit.path, "content_digest": permit.content_digest,
            "work_root": permit.work_root, "request_id": permit.request_id,
            "permit_issued_at": permit.issued_at, "permit_expires_at": permit.expires_at,
            "settled_by": settled_by, "settled_at": now,
            "graph_revision": owner.universal_store.revision,
        })
        return {**stored, "already_settled": False, "replayed": False}


def refuse_reconciled_replay(owner, actor, work_root, request_id):
    """Refuse only a retry of the SAME reconciled operation (its Work and request).

    A fresh, separately admitted operation has its own request identity and is
    allowed even when it writes the same content: equal content is not replay.
    """
    storage = getattr(owner.universal_registry.cde_write_authority_protocol, "operational_storage", None)
    if storage is not None and storage.reconciled_operation(actor, work_root, request_id) is not None:
        raise AuthorizationDenied(
            "This exact write was reconciled after an uncertain outcome and is not "
            "retried automatically. Start a new write request to make the change again.")


def settle_from_request(owner, request, peer, *, direct):
    """Actor settles its own permit; the in-process instance owner may settle any."""
    body = request.get("body")
    if not is_native_settlement_body(body, direct=direct):
        raise AuthorizationDenied("stale permit settlement requires its exact request")
    if direct:
        return settle_stale_permit(owner, actor=body["expected_agent_session"],
            permit_root=body["permit"], settlement=body["settlement"], settled_by="instance-owner")
    if body["runtime"] not in NATIVE_RUNTIMES:
        raise AuthorizationDenied("stale permit settlement requires a native actor")
    with owner.mutation_lock, owner._machine_agent_session_lock:
        identity = _verified_actor(owner, request, peer, body)
        return settle_stale_permit(owner, actor=identity["agent_session"],
            permit_root=body["permit"], settlement=body["settlement"], settled_by="actor")


__all__ = ["native_inbox_read_admitted", "open_inbox_read", "observe_target",
           "refuse_legacy_space_for_recovery", "refuse_reconciled_replay",
           "settle_stale_permit", "settle_from_request"]
