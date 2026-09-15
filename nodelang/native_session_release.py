"""Ephemeral capability retirement, never graph identity or Work retirement."""
import hashlib
import hmac
import math
import re
import time

from .application_machine_transport import MachinePipePeer, session_proof_payload
from .cell_authorization import AuthorizationDenied
from .cell_protocols import read_relation
from .universal_cell import NULL_CELL_ID

RELEASE = "/api/universal/agent-session-release"
STATUS = "/api/universal/agent-session-release-status"
RECEIPT_SECONDS = 600
RECEIPT_LIMIT = 128


def _authenticated(owner, request, peer):
    """Caller holds the session lock; returns exact live or retired custody."""
    body, session = request.get("body"), request.get("session")
    if (request.get("method") != "POST" or request.get("path") not in {RELEASE, STATUS}
            or type(body) is not dict or set(body) != {"release_id"}
            or type(body["release_id"]) is not str
            or not re.fullmatch(r"[0-9a-f]{32}", body["release_id"])
            or type(session) is not dict or set(session) != {"root", "proof"}
            or type(session["root"]) is not str or type(session["proof"]) is not str
            or type(peer) is not MachinePipePeer):
        raise AuthorizationDenied("native release requires its exact bound request and OS peer")
    actor, release_id = session["root"], body["release_id"]
    now = time.time()
    receipts = owner._machine_agent_release_receipts
    for key in tuple(receipts):
        if receipts[key]["until"] <= now:
            del receipts[key]
    held = receipts.get((actor, release_id))
    binding = held["binding"] if held else owner._machine_agent_sessions.get(actor)
    if binding is None or (not held and binding["expires_at"] <= now and request["path"] != STATUS):
        raise AuthorizationDenied("native release outcome unknown or capability expired")
    if binding.get("enrollment_peer") != {"pid": peer.pid, "created_at": peer.created_at}:
        raise AuthorizationDenied("native release OS owner changed")
    proof = hmac.new(binding["token"].encode("utf-8"), session_proof_payload(
        runtime_id=request["runtime_id"], request_id=request["request_id"],
        method=request["method"], path=request["path"], body=body,
        session_root=actor, capability_id=None), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(session["proof"], proof):
        raise AuthorizationDenied("native release proof is invalid")
    return actor, release_id, dict(binding), held


def _registry_entries(snapshot, protocol, start=None, remaining=None):
    """Stream the existing relation, constant auxiliary memory, no cutoff.

    At most the snapshot's physical cell count may be visited. That detects
    cycles without a growing seen set; it is not a lifetime permit limit.
    No second graph index or persisted permit state is introduced.
    """
    cursor = start or protocol.root_id
    remaining = len(snapshot.cells) if remaining is None else remaining
    while cursor != NULL_CELL_ID:
        if remaining <= 0:
            raise AuthorizationDenied("native release permit registry contains a cycle")
        remaining -= 1
        chain = snapshot.cells.get(cursor)
        if chain is None:
            raise AuthorizationDenied("native release permit registry has a dangling chain")
        if chain.link0 == NULL_CELL_ID:
            if chain.link1 != NULL_CELL_ID:
                raise AuthorizationDenied("native release empty registry has a tail")
            return
        incidence = snapshot.cells.get(chain.link0)
        if incidence is None or incidence.link0 not in snapshot.cells or incidence.link1 not in snapshot.cells:
            raise AuthorizationDenied("native release permit registry has a dangling incidence")
        yield incidence, cursor, chain.link1
        cursor = chain.link1


def _registered_permits(snapshot, protocol):
    for incidence, _cursor, _next in _registry_entries(snapshot, protocol):
        if incidence.link0 == protocol.role("permit-member"):
            yield incidence.link1


def read_pending_effects(snapshot, protocol, actor, *, start=None, remaining=None):
    """Bounded persisted evidence for one actor; never settle or infer an effect."""
    from .cell_cde_authority import read_cde_write_permit

    selected, receipts = [], []
    next_chain = NULL_CELL_ID
    remaining = len(snapshot.cells) if remaining is None else remaining
    next_remaining = 0
    deadline = time.monotonic() + 0.1
    for index, (entry, cursor, following) in enumerate(_registry_entries(snapshot, protocol, start, remaining)):
        if index >= 256 or len(selected) + len(receipts) >= 16 or time.monotonic() >= deadline:
            next_chain = cursor
            next_remaining = remaining - index
            break
        if entry.link0 == protocol.role("receipt-member"):
            fields = read_relation(snapshot, entry.link1, budget=32)
            roots = [field.participant_id for field in fields if field.role_id == protocol.role("receipt-permit")]
            if len(roots) != 1:
                raise AuthorizationDenied("Native effects receipt reference is ambiguous")
            permit = read_cde_write_permit(snapshot, protocol, roots[0])
            if permit.agent_session_root == actor:
                # Registry references are evidence pointers, not validated
                # settlement receipts. Avoid the receipt reader's global rescan.
                receipts.append({"root":entry.link1, "permit":permit.root_id, "verified":False})
            continue
        if entry.link0 != protocol.role("permit-member"):
            continue
        permit = read_cde_write_permit(snapshot, protocol, entry.link1)
        if permit.agent_session_root != actor:
            continue
        if permit.state_root in {protocol.states["consumed"],protocol.states["revoked"]}:
            continue
        if permit.state_root != protocol.states["active"]:
            raise AuthorizationDenied("native release permit state is unknown")
        selected.append({"permit": permit.root_id, "agent_session": actor,
            "work_root": permit.work_root, "container_root": permit.container_root,
            "container_id": permit.container_id, "operation": permit.operation,
            "path": permit.path, "content_digest": permit.content_digest,
            "request_id": permit.request_id, "state": "active",
            "issued_at": permit.issued_at, "expires_at": permit.expires_at,
            "receipts": []})
    return {"projection": "effects", "agent_session": actor, "revision": snapshot.revision,
        "pending_permits": selected, "receipt_references":receipts,
        "truncated": next_chain != NULL_CELL_ID, "_next_chain":next_chain,
        "_next_remaining":next_remaining,
        "settlement_performed": False}


def _has_pending_permit(snapshot, protocol, actor):
    for permit_root in _registered_permits(snapshot, protocol):
        fields = read_relation(snapshot, permit_root, budget=128, retain_projection=False)
        actors = [row.participant_id for row in fields if row.role_id == protocol.role("agent-session")]
        if len(actors) != 1:
            raise AuthorizationDenied("native release permit owner projection is ambiguous")
        actor_cell = snapshot.cells.get(actors[0])
        if actor_cell is None or actor_cell.link0 != NULL_CELL_ID or actor_cell.link1 != NULL_CELL_ID:
            raise AuthorizationDenied("native release permit owner projection is invalid")
        if actor_cell.atom != actor.encode("utf-8"):
            continue
        states = [row.participant_id for row in fields if row.role_id == protocol.role("state")]
        if len(states) != 1:
            raise AuthorizationDenied("native release permit state projection is ambiguous")
        if states[0] in {protocol.states["consumed"], protocol.states["revoked"]}:
            continue
        if states[0] != protocol.states["active"]:
            raise AuthorizationDenied("native release permit state is unknown")
        expiries = [row.participant_id for row in fields if row.role_id == protocol.role("expires-at")]
        if len(expiries) != 1:
            raise AuthorizationDenied("native release permit expiry is ambiguous")
        expiry_cell = snapshot.cells.get(expiries[0])
        if expiry_cell is None or expiry_cell.link0 != NULL_CELL_ID or expiry_cell.link1 != NULL_CELL_ID:
            raise AuthorizationDenied("native release permit expiry is invalid")
        try:
            expiry = float(expiry_cell.atom.decode("utf-8"))
        except (ValueError, UnicodeError):
            raise AuthorizationDenied("native release permit expiry is invalid") from None
        if not math.isfinite(expiry) or expiry <= 0:
            raise AuthorizationDenied("native release permit expiry is invalid")
        # Expiry ends permission to start a write, not uncertainty about whether
        # an admitted write happened. Keep custody until an actual receipt or
        # explicit reconciliation settles it; never infer no-write from time.
        return True
    return False


def release_session(owner, request, peer):
    """Authenticate, project outside global locks, then recheck exact revision."""
    with owner.mutation_lock, owner._machine_agent_session_lock:
        actor, release_id, binding, held = _authenticated(owner, request, peer)
        if held:
            return dict(held["result"])
        if request["path"] == STATUS:
            # Exact token/peer still exists. An expired retained token proves
            # non-release but grants no new lease; ordinary routes still refuse
            # it. Existing explicit known-expiry rebind remains necessary.
            return {"released":False, "retained":True, "agent_session":actor, "release_id":release_id,
                    "lease_expired":binding["expires_at"] <= time.time()}
        now = time.time()
        issued = int(release_id[:8], 16)
        if not now - 60 <= issued <= now + 5:
            raise AuthorizationDenied("native release request is stale or future dated")
        # Recheck graph/custody while the exact token cannot rotate.
        resolved, current = owner._machine_agent_binding_for_request(request)
        if resolved != actor or current["token"] != binding["token"]:
            raise AuthorizationDenied("native release capability changed")
        snapshot = owner.universal_store.snapshot()
        protocol = owner.universal_registry.cde_write_authority_protocol
    pending = _has_pending_permit(snapshot, protocol, actor)
    with owner.mutation_lock, owner._machine_agent_session_lock:
        _, _, checked, held = _authenticated(owner, request, peer)
        if held:
            return dict(held["result"])
        if checked != binding:
            raise AuthorizationDenied("native release actor activity or owner changed; capability retained")
        if pending:
            raise AuthorizationDenied("native release has an unreceipted CDE permit")
        if owner._machine_agent_active_requests.get(actor, 0) > 1:
            raise AuthorizationDenied("native release has an active operation")
        # Verified requests retain their actor until the entire dispatch ends,
        # including model/provider calls outside mutation_lock. Another actor's
        # work is not a reason to poison this owner's clean close.
        relay = owner.native_recipient_relay
        if relay is not None:
            with relay._channel_lock:
                if actor in relay._channels or actor in relay._attaching:
                    raise AuthorizationDenied("native release requires explicit Session Link detach")
                if any(actor in peers for peers in relay._pending_jobs.values()):
                    raise AuthorizationDenied("native release waits for Session Link delivery settlement")
        # Never evict a still-valid recovery receipt to make room for a release.
        receipts = owner._machine_agent_release_receipts
        if len(receipts) >= RECEIPT_LIMIT:
            raise AuthorizationDenied("native release receipt capacity reached")
        until = time.time() + RECEIPT_SECONDS
        result = {"released": True, "agent_session": actor, "release_id": release_id,
                  "recovery_until": until,
                  "revision": owner.universal_store.revision}
        receipts[(actor, release_id)] = {"binding": dict(binding),
            "result": result, "until": until}
        del owner._machine_agent_sessions[actor]
        return dict(result)
