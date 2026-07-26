"""Graph authority for non-exporting device proof-key custody."""
from __future__ import annotations

import base64
import hashlib
import json
import time
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .cell_cloud_sessions import device_root_for_thumbprint
from .cell_device_keys import (
    DeviceProofKeyReference,
    PLATFORM_PROVIDER,
    SOFTWARE_PROVIDER,
)
from .cell_protocols import (
    CellBatch,
    compose_relation_cells,
    prepare_append_relation_members,
    read_relation,
)
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


ROLE_NAMES = (
    "vocabulary-member",
    "custody-member",
    "device",
    "provider",
    "algorithm",
    "public-jwk",
    "hardware-backed",
    "key-name-digest",
    "enrolled-at",
    "state",
    "revocation-reason",
)
STATE_NAMES = ("active", "revoked")


@dataclass(frozen=True, slots=True)
class DeviceCustodyProtocol:
    root_id: str
    roles: Mapping[str, str]
    states: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown device-custody role") from exc


@dataclass(frozen=True, slots=True)
class DeviceCustodyProjection:
    root_id: str
    device_root: str
    provider_root: str
    algorithm_root: str
    public_jwk_root: str
    hardware_backed_root: str
    key_name_digest_root: str
    enrolled_at_root: str
    state_root: str
    state_incidence: str
    revocation_reason_roots: tuple[str, ...]


class ActiveDeviceCustodyVerifier:
    """Resolve one active custody relation for an exact device root."""

    def __init__(self, protocol: DeviceCustodyProtocol) -> None:
        if not isinstance(protocol, DeviceCustodyProtocol):
            raise TypeError("active custody verifier requires its protocol")
        self._protocol = protocol

    def verify(
        self,
        snapshot: Snapshot,
        *,
        device_root: str,
        now: float,
    ) -> str:
        del now
        matches = []
        for custody_root in list_device_custody_roots(snapshot, self._protocol):
            custody = read_device_custody(
                snapshot, self._protocol, custody_root
            )
            if (
                custody.device_root == device_root
                and custody.state_root == self._protocol.states["active"]
            ):
                matches.append(custody_root)
        if len(matches) != 1:
            raise InvalidCell("device requires one active custody authority")
        return matches[0]


def _terminal(root_id: str, value: str) -> Cell:
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8"))


def _text(snapshot: Snapshot, root_id: str) -> str:
    try:
        return snapshot.cells[root_id].atom.decode("utf-8")
    except (KeyError, UnicodeDecodeError) as exc:
        raise InvalidCell("device-custody value is missing or invalid") from exc


def _one(members, role_root: str, label: str):
    found = [member for member in members if member.role_id == role_root]
    if len(found) != 1:
        raise InvalidCell("device custody requires exactly one %s" % label)
    return found[0]


def _jwk_document(value: Mapping[str, str]) -> str:
    if set(value) != {"crv", "kty", "x", "y"}:
        raise InvalidCell("device public JWK shape is invalid")
    if value["crv"] != "P-256" or value["kty"] != "EC":
        raise InvalidCell("device public JWK is not P-256")
    for name in ("x", "y"):
        try:
            decoded = base64.urlsafe_b64decode(value[name] + "==")
        except (ValueError, TypeError) as exc:
            raise InvalidCell("device public JWK coordinate is invalid") from exc
        if len(decoded) != 32:
            raise InvalidCell("device public JWK coordinate is invalid")
    return json.dumps(
        dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


def _jwk_thumbprint(document: str) -> str:
    return base64.urlsafe_b64encode(
        hashlib.sha256(document.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")


def bootstrap_device_custody_protocol(
    store: CellStore, *, prefix: str = "device-custody-protocol"
) -> DeviceCustodyProtocol:
    root_id = prefix + ":root"
    if root_id in store.snapshot().cells:
        return project_device_custody_protocol(store.snapshot(), prefix=prefix)
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    states = {name: "%s:state:%s" % (prefix, name) for name in STATE_NAMES}
    batch = CellBatch(store)
    for name, root in (*roles.items(), *states.items()):
        batch.add(_terminal(root, name))
    batch.relation(
        (
            (roles["vocabulary-member"], root)
            for root in (*roles.values(), *states.values())
        ),
        relation_id=root_id,
    )
    batch.commit()
    return DeviceCustodyProtocol(
        root_id, MappingProxyType(roles), MappingProxyType(states)
    )


def project_device_custody_protocol(
    snapshot: Snapshot, *, prefix: str = "device-custody-protocol"
) -> DeviceCustodyProtocol:
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    states = {name: "%s:state:%s" % (prefix, name) for name in STATE_NAMES}
    root_id = prefix + ":root"
    required = {root_id, *roles.values(), *states.values()}
    if required - set(snapshot.cells):
        raise InvalidCell("device-custody protocol is incomplete")
    members = read_relation(snapshot, root_id, budget=100_000)
    allowed = {roles["vocabulary-member"], roles["custody-member"]}
    if any(member.role_id not in allowed for member in members):
        raise InvalidCell("device-custody protocol has an undeclared member")
    vocabulary = {
        member.participant_id for member in members
        if member.role_id == roles["vocabulary-member"]
    }
    if vocabulary != {*roles.values(), *states.values()}:
        raise InvalidCell("device-custody vocabulary drifted")
    return DeviceCustodyProtocol(
        root_id, MappingProxyType(roles), MappingProxyType(states)
    )


def register_device_custody(
    store: CellStore,
    protocol: DeviceCustodyProtocol,
    reference: DeviceProofKeyReference,
    *,
    enrolled_at: float | None = None,
    allow_software: bool = False,
) -> tuple[str, int]:
    if type(reference) is not DeviceProofKeyReference:
        raise TypeError("device custody requires a proof-key reference")
    if reference.provider not in (PLATFORM_PROVIDER, SOFTWARE_PROVIDER):
        raise InvalidCell("device custody provider is not admitted")
    if reference.provider == SOFTWARE_PROVIDER and not allow_software:
        raise InvalidCell("software device custody is not admitted")
    if reference.provider == PLATFORM_PROVIDER and not reference.hardware_backed:
        raise InvalidCell("platform device custody is not hardware-backed")
    if reference.algorithm != "ES256":
        raise InvalidCell("device custody algorithm is not admitted")
    public_jwk = _jwk_document(reference.public_jwk)
    if _jwk_thumbprint(public_jwk) != reference.thumbprint:
        raise InvalidCell("device public JWK thumbprint drifted")
    snapshot = store.snapshot()
    device_root = device_root_for_thumbprint(reference.thumbprint)
    expected_device_atom = (
        "device-proof-key-thumbprint:" + reference.thumbprint
    ).encode("ascii")
    device = snapshot.cells.get(device_root)
    if (
        device is None
        or device.link0 != NULL_CELL_ID
        or device.link1 != NULL_CELL_ID
        or device.atom != expected_device_atom
    ):
        raise InvalidCell("device proof-key identity is not provisioned")
    existing = []
    for member in read_relation(snapshot, protocol.root_id, budget=100_000):
        if member.role_id != protocol.role("custody-member"):
            continue
        custody = read_device_custody(snapshot, protocol, member.participant_id)
        if custody.device_root == device_root:
            existing.append(custody.root_id)
    if existing:
        if len(existing) != 1:
            raise InvalidCell("device has multiple custody authorities")
        raise InvalidCell("device custody already exists")
    root_id = "device-custody:sha256:" + reference.thumbprint
    values = {
        "provider": reference.provider,
        "algorithm": reference.algorithm,
        "public-jwk": public_jwk,
        "hardware-backed": "true" if reference.hardware_backed else "false",
        "key-name-digest": hashlib.sha256(
            reference.key_name.encode("utf-8")
        ).hexdigest(),
        "enrolled-at": "%.6f" % (
            time.time() if enrolled_at is None else float(enrolled_at)
        ),
    }
    value_cells = {
        name: _terminal(root_id + ":" + name, value)
        for name, value in values.items()
    }
    relation = compose_relation_cells((
        (protocol.role("device"), device_root),
        (protocol.role("provider"), value_cells["provider"].id),
        (protocol.role("algorithm"), value_cells["algorithm"].id),
        (protocol.role("public-jwk"), value_cells["public-jwk"].id),
        (
            protocol.role("hardware-backed"),
            value_cells["hardware-backed"].id,
        ),
        (
            protocol.role("key-name-digest"),
            value_cells["key-name-digest"].id,
        ),
        (protocol.role("enrolled-at"), value_cells["enrolled-at"].id),
        (protocol.role("state"), protocol.states["active"]),
    ), relation_id=root_id)
    registry_patch = prepare_append_relation_members(
        snapshot,
        protocol.root_id,
        ((protocol.role("custody-member"), root_id),),
        budget=100_000,
    )
    revision = store.commit(
        snapshot.revision,
        create=(
            *value_cells.values(),
            *relation.cells,
            *registry_patch.create,
        ),
        replace=registry_patch.replace,
    )
    return root_id, revision


def read_device_custody(
    snapshot: Snapshot,
    protocol: DeviceCustodyProtocol,
    custody_root: str,
) -> DeviceCustodyProjection:
    members = read_relation(snapshot, custody_root, budget=128)
    allowed = {
        protocol.role(name) for name in ROLE_NAMES
        if name not in ("vocabulary-member", "custody-member")
    }
    if any(member.role_id not in allowed for member in members):
        raise InvalidCell("device custody contains an undeclared field")
    device = _one(members, protocol.role("device"), "device")
    provider = _one(members, protocol.role("provider"), "provider")
    algorithm = _one(members, protocol.role("algorithm"), "algorithm")
    public_jwk = _one(members, protocol.role("public-jwk"), "public-jwk")
    hardware = _one(
        members, protocol.role("hardware-backed"), "hardware-backed"
    )
    key_name = _one(
        members, protocol.role("key-name-digest"), "key-name-digest"
    )
    enrolled = _one(members, protocol.role("enrolled-at"), "enrolled-at")
    state = _one(members, protocol.role("state"), "state")
    reasons = tuple(
        member.participant_id for member in members
        if member.role_id == protocol.role("revocation-reason")
    )
    if state.participant_id not in protocol.states.values() or len(reasons) > 1:
        raise InvalidCell("device custody lifecycle drifted")
    public_document = _text(snapshot, public_jwk.participant_id)
    try:
        public_value = json.loads(public_document)
    except json.JSONDecodeError as exc:
        raise InvalidCell("device public JWK is invalid") from exc
    thumbprint = _jwk_thumbprint(_jwk_document(public_value))
    if device.participant_id != device_root_for_thumbprint(thumbprint):
        raise InvalidCell("device custody public key drifted")
    return DeviceCustodyProjection(
        custody_root,
        device.participant_id,
        provider.participant_id,
        algorithm.participant_id,
        public_jwk.participant_id,
        hardware.participant_id,
        key_name.participant_id,
        enrolled.participant_id,
        state.participant_id,
        state.incidence_id,
        reasons,
    )


def list_device_custody_roots(
    snapshot: Snapshot,
    protocol: DeviceCustodyProtocol,
) -> tuple[str, ...]:
    roots = tuple(
        member.participant_id for member in read_relation(
            snapshot, protocol.root_id, budget=100_000
        )
        if member.role_id == protocol.role("custody-member")
    )
    if len(roots) != len(set(roots)):
        raise InvalidCell("device-custody registry contains a duplicate")
    return roots


def revoke_device_custody(
    store: CellStore,
    protocol: DeviceCustodyProtocol,
    custody_root: str,
    *,
    reason: str,
) -> int:
    reason = str(reason).strip()
    if not reason or len(reason.encode("utf-8")) > 1024:
        raise ValueError("device-custody revocation reason is required")
    snapshot = store.snapshot()
    custody = read_device_custody(snapshot, protocol, custody_root)
    if custody.state_root == protocol.states["revoked"]:
        return snapshot.revision
    reason_root = custody_root + ":revocation-reason"
    reason_patch = prepare_append_relation_members(
        snapshot,
        custody_root,
        ((protocol.role("revocation-reason"), reason_root),),
        budget=128,
    )
    state_incidence = snapshot.cells[custody.state_incidence]
    return store.commit(
        snapshot.revision,
        create=(_terminal(reason_root, reason), *reason_patch.create),
        replace=(
            Cell(
                state_incidence.id,
                state_incidence.link0,
                protocol.states["revoked"],
                state_incidence.atom,
            ),
            *reason_patch.replace,
        ),
    )


__all__ = [
    "ActiveDeviceCustodyVerifier",
    "DeviceCustodyProjection",
    "DeviceCustodyProtocol",
    "bootstrap_device_custody_protocol",
    "list_device_custody_roots",
    "project_device_custody_protocol",
    "read_device_custody",
    "register_device_custody",
    "revoke_device_custody",
]
