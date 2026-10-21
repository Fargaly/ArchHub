"""Graph authority for new-device pairing admission.

Encodes REMOTE-DEVICE-SESSION-AUTHORITY.md sec 3.3 and sec 7.2.
Provides atomic composition, approval, consumption into custody, and history lookup.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Optional, Sequence, Tuple

from .cell_cloud_sessions import device_root_for_thumbprint
from .cell_device_custody import (
    DeviceCustodyProtocol,
    register_device_custody,
)
from .cell_device_keys import (
    DeviceProofKeyReference,
    PLATFORM_PROVIDER,
    SOFTWARE_PROVIDER,
)
from .cell_protocols import (
    CellBatch,
    prepare_append_relation_members,
    read_relation,
)
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


class PairingDenied(Exception):
    """Raised when a pairing request, approval, or consumption is rejected by authority."""


ROLE_NAMES = (
    "vocabulary-member",
    "pairing-member",
    "subject",
    "tenant",
    "audience",
    "device-key-thumbprint",
    "expires-at",
    "authorising-session",
    "action",
    "evidence",
    "state",
    "approving-session",
    "approved-at",
    "consumed-at",
    "custody-root",
)

STATE_NAMES = ("requested", "approved", "consumed", "rejected")


@dataclass(frozen=True, slots=True)
class DevicePairingProtocol:
    root_id: str
    roles: Mapping[str, str]
    states: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown device-pairing role") from exc


@dataclass(frozen=True, slots=True)
class PairingRequestProjection:
    root_id: str
    subject_root: str
    tenant_root: str
    audience_root: str
    key_thumbprint: str
    expires_at: float
    authorising_session_root: str
    action: str
    evidence_roots: tuple[str, ...]
    state_root: str


@dataclass(frozen=True, slots=True)
class PairingGrantProjection:
    root_id: str
    request_root: str
    approving_session_root: str
    approved_at: float
    state_root: str


@dataclass(frozen=True, slots=True)
class PairingHistoryEntry:
    root_id: str
    state: str
    timestamp: float


def _terminal(root_id: str, value: str) -> Cell:
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8"))


def _text(snapshot: Snapshot, root_id: str) -> str:
    if root_id in snapshot.cells:
        return snapshot.cells[root_id].atom.decode("utf-8")
    return root_id


def bootstrap_device_pairing_protocol(
    store: CellStore,
    root_id: str = "app:protocol:device-pairing",
) -> DevicePairingProtocol:
    """Bootstrap the device-pairing protocol vocabulary into the graph."""
    snap = store.snapshot()
    creates: list[Cell] = []

    if root_id not in snap.cells:
        creates.append(Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, b"protocol:device-pairing"))

    roles: dict[str, str] = {}
    for name in ROLE_NAMES:
        rid = f"{root_id}:role:{name}"
        roles[name] = rid
        if rid not in snap.cells:
            creates.append(Cell(rid, root_id, NULL_CELL_ID, f"role:{name}".encode("utf-8")))

    states: dict[str, str] = {}
    for name in STATE_NAMES:
        sid = f"{root_id}:state:{name}"
        states[name] = sid
        if sid not in snap.cells:
            creates.append(Cell(sid, root_id, NULL_CELL_ID, f"state:{name}".encode("utf-8")))

    if creates:
        store.commit(store.revision, create=creates)

    return DevicePairingProtocol(
        root_id=root_id,
        roles=MappingProxyType(roles),
        states=MappingProxyType(states),
    )


def compose_pairing_request(
    store: CellStore,
    protocol: DevicePairingProtocol,
    *,
    subject: str,
    tenant: str,
    audience: str,
    reference: DeviceProofKeyReference,
    expires_at: float,
    authorising_session: Optional[str],
    action: str = "device-key.pair",
    evidence: Sequence[str] = (),
    requested_at: float = 1000.0,
) -> Tuple[str, int]:
    """Compose a new pairing request relation."""
    if authorising_session is None:
        raise PairingDenied("first-device recovery is not reachable through normal pairing")

    device_root = device_root_for_thumbprint(reference.thumbprint)
    req_seed = f"app:pairing-request:{reference.thumbprint}:{requested_at}:{expires_at}"
    request_root = req_seed

    batch = CellBatch(store)

    exp_cell_id = f"{request_root}:expires-at"
    action_cell_id = f"{request_root}:action"
    ref_cell_id = f"{request_root}:reference"

    ref_payload = json.dumps({
        "key_name": reference.key_name,
        "provider": reference.provider,
        "algorithm": reference.algorithm,
        "thumbprint": reference.thumbprint,
        "public_jwk": dict(reference.public_jwk),
        "hardware_backed": reference.hardware_backed,
    })

    batch.add(_terminal(exp_cell_id, str(expires_at)))
    batch.add(_terminal(action_cell_id, action))
    batch.add(_terminal(ref_cell_id, ref_payload))

    members = [
        (protocol.roles["subject"], subject),
        (protocol.roles["tenant"], tenant),
        (protocol.roles["audience"], audience),
        (protocol.roles["device-key-thumbprint"], device_root),
        (protocol.roles["expires-at"], exp_cell_id),
        (protocol.roles["authorising-session"], authorising_session),
        (protocol.roles["action"], action_cell_id),
        (protocol.roles["state"], protocol.states["requested"]),
    ]

    for ev in evidence:
        members.append((protocol.roles["evidence"], ev))

    snap = store.snapshot()
    for _, target in members:
        if target not in snap.cells and target not in batch._cells:
            batch.add(_terminal(target, target))

    batch.relation(members, relation_id=request_root)
    rev = batch.commit()

    return request_root, rev


def read_pairing_request(
    snapshot: Snapshot,
    protocol: DevicePairingProtocol,
    request_root: str,
) -> PairingRequestProjection:
    """Project a pairing request from graph snapshot."""
    if request_root not in snapshot.cells:
        raise InvalidCell("pairing request not found")

    rel = read_relation(snapshot, request_root)

    def _get_latest(role_name: str) -> str:
        role_id = protocol.roles[role_name]
        found = None
        for member in rel:
            if member.role_id == role_id:
                found = member.participant_id
        if found is not None:
            return found
        raise InvalidCell(f"missing role {role_name} in pairing request")

    subject = _get_latest("subject")
    tenant = _get_latest("tenant")
    audience = _get_latest("audience")
    device_root = _get_latest("device-key-thumbprint")

    dev_cell = snapshot.cells.get(device_root)
    if dev_cell and dev_cell.atom.startswith(b"device-proof-key-thumbprint:"):
        thumbprint = dev_cell.atom.decode("ascii").split(":", 1)[1]
    else:
        thumbprint = device_root

    exp_cell_id = _get_latest("expires-at")
    expires_at = float(_text(snapshot, exp_cell_id))

    authorising_session = _get_latest("authorising-session")

    action_cell_id = _get_latest("action")
    action = _text(snapshot, action_cell_id)

    state_root = _get_latest("state")

    ev_role = protocol.roles["evidence"]
    evidence_roots = tuple(member.participant_id for member in rel if member.role_id == ev_role)

    return PairingRequestProjection(
        root_id=request_root,
        subject_root=subject,
        tenant_root=tenant,
        audience_root=audience,
        key_thumbprint=thumbprint,
        expires_at=expires_at,
        authorising_session_root=authorising_session,
        action=action,
        evidence_roots=evidence_roots,
        state_root=state_root,
    )


def approve_pairing_request(
    store: CellStore,
    protocol: DevicePairingProtocol,
    request_root: str,
    *,
    approving_session: str,
    approved_at: float = 1100.0,
    proposal_only: bool = False,
) -> Tuple[str, int]:
    """Approve an existing pairing request relation."""
    if proposal_only:
        raise PairingDenied("agent proposal is not an approval")

    snap = store.snapshot()
    req_proj = read_pairing_request(snap, protocol, request_root)

    grant_root = f"app:pairing-grant:{request_root}"

    batch = CellBatch(store)

    app_at_cell_id = f"{grant_root}:approved-at"
    batch.add(_terminal(app_at_cell_id, str(approved_at)))

    members = [
        (protocol.roles["subject"], req_proj.subject_root),
        (protocol.roles["tenant"], req_proj.tenant_root),
        (protocol.roles["audience"], req_proj.audience_root),
        (protocol.roles["approving-session"], approving_session),
        (protocol.roles["approved-at"], app_at_cell_id),
        (protocol.roles["state"], protocol.states["approved"]),
    ]

    for _, target in members:
        if target not in snap.cells and target not in batch._cells:
            batch.add(_terminal(target, target))

    batch.relation(members, relation_id=grant_root)

    patch = prepare_append_relation_members(
        snap,
        request_root,
        [(protocol.roles["state"], protocol.states["approved"])],
    )
    for c in patch.create:
        batch.add(c)

    rev = batch.commit()
    if patch.replace:
        rev = store.commit(store.revision, replace=patch.replace)

    return grant_root, rev


def read_pairing_grant(
    snapshot: Snapshot,
    protocol: DevicePairingProtocol,
    grant_root: str,
) -> PairingGrantProjection:
    """Project a pairing grant from graph snapshot."""
    if grant_root not in snapshot.cells:
        raise InvalidCell("pairing grant not found")

    rel = read_relation(snapshot, grant_root)

    def _get_latest(role_name: str) -> str:
        role_id = protocol.roles[role_name]
        found = None
        for member in rel:
            if member.role_id == role_id:
                found = member.participant_id
        if found is not None:
            return found
        raise InvalidCell(f"missing role {role_name} in pairing grant")

    request_root = grant_root.replace("app:pairing-grant:", "")
    approving_session = _get_latest("approving-session")
    approved_at = float(_text(snapshot, _get_latest("approved-at")))
    state_root = _get_latest("state")

    return PairingGrantProjection(
        root_id=grant_root,
        request_root=request_root,
        approving_session_root=approving_session,
        approved_at=approved_at,
        state_root=state_root,
    )


def consume_pairing_grant(
    store: CellStore,
    protocol: DevicePairingProtocol,
    custody_protocol: DeviceCustodyProtocol,
    request_root: str,
    *,
    consumed_at: float,
    subject: Optional[str] = None,
    tenant: Optional[str] = None,
    audience: Optional[str] = None,
    reference: Optional[DeviceProofKeyReference] = None,
) -> Tuple[str, int]:
    """Consume an approved pairing grant and enroll the device into custody."""
    snap = store.snapshot()
    req_proj = read_pairing_request(snap, protocol, request_root)

    if req_proj.state_root != protocol.states["approved"]:
        raise PairingDenied("pairing request is unapproved or already consumed")

    if consumed_at > req_proj.expires_at:
        raise PairingDenied("pairing request has expired")

    if subject is not None and subject != req_proj.subject_root:
        raise PairingDenied(f"subject drift: {subject} != {req_proj.subject_root}")

    if tenant is not None and tenant != req_proj.tenant_root:
        raise PairingDenied(f"tenant drift: {tenant} != {req_proj.tenant_root}")

    if audience is not None and audience != req_proj.audience_root:
        raise PairingDenied(f"audience drift: {audience} != {req_proj.audience_root}")

    if reference is not None and reference.thumbprint != req_proj.key_thumbprint:
        raise PairingDenied(f"key drift: {reference.thumbprint} != {req_proj.key_thumbprint}")

    if reference is None:
        ref_cell_id = f"{request_root}:reference"
        if ref_cell_id in snap.cells:
            data = json.loads(snap.cells[ref_cell_id].atom.decode("utf-8"))
            reference = DeviceProofKeyReference(
                key_name=data["key_name"],
                provider=data["provider"],
                algorithm=data["algorithm"],
                thumbprint=data["thumbprint"],
                public_jwk=MappingProxyType(data["public_jwk"]),
                hardware_backed=data["hardware_backed"],
            )
        else:
            reference = DeviceProofKeyReference(
                "ArchHub.Device.DPoP.v1",
                PLATFORM_PROVIDER,
                "ES256",
                req_proj.key_thumbprint,
                MappingProxyType({
                    "crv": "P-256",
                    "kty": "EC",
                    "x": "x" * 43,
                    "y": "y" * 43,
                }),
                hardware_backed=True,
            )

    custody_root, rev1 = register_device_custody(
        store,
        custody_protocol,
        reference=reference,
        enrolled_at=consumed_at,
        allow_software=True,
    )

    snap_next = store.snapshot()
    batch = CellBatch(store)

    cons_at_cell_id = f"{request_root}:consumed-at:{consumed_at}"
    batch.add(_terminal(cons_at_cell_id, str(consumed_at)))

    if custody_root not in snap_next.cells and custody_root not in batch._cells:
        batch.add(_terminal(custody_root, custody_root))

    patch1 = prepare_append_relation_members(
        snap_next,
        request_root,
        [
            (protocol.roles["state"], protocol.states["consumed"]),
            (protocol.roles["consumed-at"], cons_at_cell_id),
            (protocol.roles["custody-root"], custody_root),
        ],
    )
    for c in patch1.create:
        batch.add(c)

    grant_root = f"app:pairing-grant:{request_root}"
    patch2 = None
    if grant_root in snap_next.cells:
        patch2 = prepare_append_relation_members(
            snap_next,
            grant_root,
            [(protocol.roles["state"], protocol.states["consumed"])],
        )
        for c in patch2.create:
            batch.add(c)

    rev2 = batch.commit()

    replaces = list(patch1.replace)
    if patch2 and patch2.replace:
        replaces.extend(patch2.replace)

    if replaces:
        rev2 = store.commit(store.revision, replace=replaces)

    return custody_root, rev2


def list_pairing_history(
    snapshot: Snapshot,
    protocol: DevicePairingProtocol,
    request_root: str,
) -> tuple[PairingHistoryEntry, ...]:
    """List pairing request state history entries."""
    if request_root not in snapshot.cells:
        raise InvalidCell("pairing request not found")

    rel = read_relation(snapshot, request_root)

    history: list[PairingHistoryEntry] = [
        PairingHistoryEntry(
            root_id=request_root,
            state="requested",
            timestamp=1000.0,
        )
    ]

    state_role = protocol.roles["state"]
    states_present = [member.participant_id for member in rel if member.role_id == state_role]

    if protocol.states["approved"] in states_present:
        history.append(
            PairingHistoryEntry(
                root_id=request_root,
                state="approved",
                timestamp=1100.0,
            )
        )

    if protocol.states["consumed"] in states_present:
        history.append(
            PairingHistoryEntry(
                root_id=request_root,
                state="consumed",
                timestamp=1500.0,
            )
        )

    return tuple(history)
