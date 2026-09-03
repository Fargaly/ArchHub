"""Released adapter allowlist and exact, user-consented effect grants.

Adapter descriptions and grants are ordinary universal cells.  The authority
to approve one is not data: it is a one-use process-local consent handle that
cannot be serialized or forged by writing an atom containing "approved".
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import secrets
import threading
import time
from types import MappingProxyType
from typing import Iterable, Mapping

from .cell_lifecycle import graph_content_digest
from .cell_protocols import (
    CellBatch,
    RelationMember,
    prepare_append_relation_members,
    read_relation,
)
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


ROLE_NAMES = (
    "vocabulary-member",
    "catalog-member",
    "name",
    "action",
    "location",
    "datatype",
    "adapter",
    "user",
    "lifecycle",
    "digest",
    "evidence",
    "version",
    "expires-at",
    "max-invocations",
)


@dataclass(frozen=True, slots=True)
class AdapterProtocol:
    root_id: str
    roles: Mapping[str, str]
    states: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown adapter role %r" % name) from exc


@dataclass(frozen=True, slots=True)
class AdapterDefinition:
    root_id: str
    name_root: str
    digest_root: str


@dataclass(frozen=True, slots=True)
class AdapterProjection:
    root_id: str
    name_root: str
    lifecycle_root: str
    digest_root: str
    action_roots: tuple[str, ...]
    location_roots: tuple[str, ...]
    datatype_roots: tuple[str, ...]
    evidence_roots: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AdapterCatalog:
    root_id: str
    version_root: str
    lifecycle_root: str
    digest_root: str
    adapter_roots: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PermissionProjection:
    root_id: str
    adapter_root: str
    user_root: str
    lifecycle_root: str
    digest_root: str
    action_roots: tuple[str, ...]
    location_roots: tuple[str, ...]
    datatype_roots: tuple[str, ...]
    expires_at_root: str
    max_invocations_root: str


_CONSENT_KEY = object()


class UserConsentDenied(PermissionError):
    pass


class UserConsentHandle:
    __slots__ = ("_nonce",)

    def __init__(self, key: object) -> None:
        if key is not _CONSENT_KEY:
            raise UserConsentDenied("user consent can only be minted by its broker")
        self._nonce = secrets.token_hex(16)

    def __reduce_ex__(self, protocol):
        raise TypeError("live user-consent handles cannot be serialized")


@dataclass(slots=True)
class _ConsentEntry:
    request_root: str
    user_root: str
    expires_at: float
    used: bool = False


class UserConsentBroker:
    """Trusted UI boundary for exact, short-lived, one-use user gestures."""

    def __init__(self) -> None:
        self._entries: dict[UserConsentHandle, _ConsentEntry] = {}
        self._lock = threading.RLock()

    def mint_from_user_gesture(
        self,
        request_root: str,
        user_root: str,
        *,
        lifetime_seconds: float = 120.0,
    ) -> UserConsentHandle:
        if lifetime_seconds <= 0 or lifetime_seconds > 300:
            raise ValueError("user consent lifetime must be within five minutes")
        handle = UserConsentHandle(_CONSENT_KEY)
        with self._lock:
            self._entries[handle] = _ConsentEntry(
                request_root, user_root, time.time() + lifetime_seconds
            )
        return handle

    def consume(
        self,
        handle: object,
        request_root: str,
        user_root: str,
    ) -> None:
        with self._lock:
            entry = self._entries.get(handle) if type(handle) is UserConsentHandle else None
            if entry is None:
                raise UserConsentDenied("unknown user-consent handle")
            if entry.used:
                raise UserConsentDenied("user-consent handle was already used")
            if time.time() >= entry.expires_at:
                raise UserConsentDenied("user-consent handle expired")
            if entry.request_root != request_root or entry.user_root != user_root:
                raise UserConsentDenied("user consent does not match this request")
            entry.used = True


def _new_terminal(batch: CellBatch, root_id: str, value: str) -> str:
    encoded = value.encode("utf-8")
    if not encoded:
        raise InvalidCell("adapter contract values cannot be empty")
    batch.add(Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, encoded))
    return root_id


def _for_role(members: Iterable[RelationMember], role_id: str) -> tuple[str, ...]:
    return tuple(
        member.participant_id for member in members if member.role_id == role_id
    )


def _one(members: tuple[RelationMember, ...], role_id: str, label: str) -> str:
    values = _for_role(members, role_id)
    if len(values) != 1:
        raise InvalidCell("adapter graph requires exactly one %s" % label)
    return values[0]


def _closed_roles(
    members: tuple[RelationMember, ...], allowed: set[str], label: str
) -> None:
    if any(member.role_id not in allowed for member in members):
        raise InvalidCell("%s contains an undeclared field" % label)


def bootstrap_adapter_protocol(
    store: CellStore,
    *,
    prefix: str = "adapter-protocol",
) -> AdapterProtocol:
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    states = {
        name: "%s:state:%s" % (prefix, name)
        for name in (
            "draft", "released", "requested", "granted", "denied", "revoked"
        )
    }
    batch = CellBatch(store)
    for name, root in roles.items():
        _new_terminal(batch, root, name)
    for name, root in states.items():
        _new_terminal(batch, root, name)
    root_id = prefix + ":root"
    batch.relation([
        *((roles["vocabulary-member"], root) for root in roles.values()),
        *((roles["vocabulary-member"], root) for root in states.values()),
    ], relation_id=root_id)
    batch.commit()
    return AdapterProtocol(
        root_id, MappingProxyType(roles), MappingProxyType(states)
    )


def build_adapter_definition(
    store: CellStore,
    protocol: AdapterProtocol,
    *,
    adapter_id: str,
    name: str,
    actions: Iterable[str],
    locations: Iterable[str],
    datatypes: Iterable[str],
    evidence: str,
    location_roots: Iterable[str] = (),
) -> AdapterDefinition:
    """Create a draft adapter contract; it cannot execute until released."""
    values = {
        "action": tuple(dict.fromkeys(actions)),
        "location": tuple(dict.fromkeys(locations)),
        "datatype": tuple(dict.fromkeys(datatypes)),
    }
    admitted_location_roots = tuple(dict.fromkeys(location_roots))
    if (
        not values["action"]
        or not values["datatype"]
        or (not values["location"] and not admitted_location_roots)
    ):
        raise InvalidCell("adapter requires action, location, and datatype bounds")
    snapshot = store.snapshot()
    if any(root not in snapshot.cells for root in admitted_location_roots):
        raise InvalidCell("adapter graph location capability is missing")
    batch = CellBatch(store)
    name_root = _new_terminal(batch, adapter_id + ":name", name)
    evidence_root = _new_terminal(batch, adapter_id + ":evidence", evidence)
    digest_root = adapter_id + ":digest"
    batch.add(Cell(digest_root, NULL_CELL_ID, NULL_CELL_ID, b""))
    value_roots: dict[str, tuple[str, ...]] = {}
    for role, items in values.items():
        roots = []
        for index, value in enumerate(items):
            roots.append(_new_terminal(
                batch, "%s:%s:%s" % (adapter_id, role, index), value
            ))
        value_roots[role] = tuple(roots)
    value_roots["location"] = tuple(dict.fromkeys((
        *value_roots["location"], *admitted_location_roots
    )))
    batch.relation([
        (protocol.role("name"), name_root),
        *((protocol.role("action"), root) for root in value_roots["action"]),
        *((protocol.role("location"), root) for root in value_roots["location"]),
        *((protocol.role("datatype"), root) for root in value_roots["datatype"]),
        (protocol.role("evidence"), evidence_root),
        (protocol.role("lifecycle"), protocol.states["draft"]),
        (protocol.role("digest"), digest_root),
    ], relation_id=adapter_id)
    batch.commit()
    return AdapterDefinition(adapter_id, name_root, digest_root)


def read_adapter(
    snapshot: Snapshot,
    protocol: AdapterProtocol,
    adapter_root: str,
) -> AdapterProjection:
    members = read_relation(snapshot, adapter_root, budget=10_000)
    allowed = {
        protocol.role(name) for name in (
            "name", "action", "location", "datatype", "evidence",
            "lifecycle", "digest",
        )
    }
    _closed_roles(members, allowed, "adapter definition")
    return AdapterProjection(
        adapter_root,
        _one(members, protocol.role("name"), "name"),
        _one(members, protocol.role("lifecycle"), "lifecycle"),
        _one(members, protocol.role("digest"), "digest"),
        _for_role(members, protocol.role("action")),
        _for_role(members, protocol.role("location")),
        _for_role(members, protocol.role("datatype")),
        _for_role(members, protocol.role("evidence")),
    )


def _adapter_digest(snapshot: Snapshot, adapter: AdapterProjection) -> bytes:
    digest = hashlib.blake2b(digest_size=32)
    for root in (
        adapter.root_id, adapter.name_root,
        *sorted(adapter.action_roots),
        *sorted(adapter.location_roots),
        *sorted(adapter.datatype_roots),
        *sorted(adapter.evidence_roots),
    ):
        raw = root.encode("utf-8")
        digest.update(len(raw).to_bytes(8, "big")); digest.update(raw)
        if root != adapter.root_id:
            content = graph_content_digest(snapshot, root, budget=100_000)
            digest.update(len(content).to_bytes(8, "big")); digest.update(content)
    return digest.hexdigest().encode("ascii")


def _validate_adapter(snapshot: Snapshot, adapter: AdapterProjection) -> None:
    for label, roots in (
        ("action", adapter.action_roots),
        ("location", adapter.location_roots),
        ("datatype", adapter.datatype_roots),
        ("evidence", adapter.evidence_roots),
    ):
        if not roots or len(roots) != len(set(roots)):
            raise InvalidCell("adapter %s bounds are invalid" % label)
        for root in roots:
            if root not in snapshot.cells:
                raise InvalidCell("adapter %s bound is missing" % label)
            graph_content_digest(snapshot, root, budget=100_000)


def release_adapter_definition(
    store: CellStore,
    protocol: AdapterProtocol,
    adapter_root: str,
) -> bytes:
    snapshot = store.snapshot()
    adapter = read_adapter(snapshot, protocol, adapter_root)
    _validate_adapter(snapshot, adapter)
    if adapter.lifecycle_root != protocol.states["draft"]:
        raise InvalidCell("only a draft adapter can be released")
    digest = _adapter_digest(snapshot, adapter)
    members = read_relation(snapshot, adapter_root, budget=10_000)
    lifecycle = next(
        member for member in members
        if member.role_id == protocol.role("lifecycle")
    )
    incidence = snapshot.cells[lifecycle.incidence_id]
    digest_cell = snapshot.cells[adapter.digest_root]
    store.commit(snapshot.revision, replace=(
        Cell(digest_cell.id, digest_cell.link0, digest_cell.link1, digest),
        Cell(
            incidence.id, incidence.link0,
            protocol.states["released"], incidence.atom,
        ),
    ))
    return digest


def verify_released_adapter(
    snapshot: Snapshot,
    protocol: AdapterProtocol,
    adapter_root: str,
) -> AdapterProjection:
    adapter = read_adapter(snapshot, protocol, adapter_root)
    _validate_adapter(snapshot, adapter)
    if adapter.lifecycle_root != protocol.states["released"]:
        raise InvalidCell("adapter is not released")
    expected = snapshot.cells[adapter.digest_root].atom
    actual = _adapter_digest(snapshot, adapter)
    if not expected or not hmac.compare_digest(expected, actual):
        raise InvalidCell("released adapter has drifted")
    return adapter


def _catalog_digest(
    snapshot: Snapshot,
    protocol: AdapterProtocol,
    catalog_root: str,
    adapter_roots: tuple[str, ...],
    version: bytes,
) -> bytes:
    digest = hashlib.blake2b(digest_size=32)
    for raw in (catalog_root.encode("utf-8"), version):
        digest.update(len(raw).to_bytes(8, "big")); digest.update(raw)
    for root in sorted(adapter_roots):
        adapter = verify_released_adapter(snapshot, protocol, root)
        for raw in (root.encode("utf-8"), snapshot.cells[adapter.digest_root].atom):
            digest.update(len(raw).to_bytes(8, "big")); digest.update(raw)
    return digest.hexdigest().encode("ascii")


def build_adapter_catalog(
    store: CellStore,
    protocol: AdapterProtocol,
    adapter_roots: Iterable[str] = (),
    *,
    catalog_id: str = "adapter-catalog",
    version: str = "1.0.0",
) -> str:
    roots = tuple(adapter_roots)
    if len(roots) != len(set(roots)):
        raise InvalidCell("adapter catalogue repeats an adapter")
    snapshot = store.snapshot()
    for root in roots:
        verify_released_adapter(snapshot, protocol, root)
    version_bytes = version.encode("ascii")
    if not version_bytes:
        raise InvalidCell("adapter catalogue version cannot be empty")
    version_root = catalog_id + ":version"
    digest_root = catalog_id + ":digest"
    digest = _catalog_digest(
        snapshot, protocol, catalog_id, roots, version_bytes
    )
    batch = CellBatch(store)
    batch.add(Cell(version_root, NULL_CELL_ID, NULL_CELL_ID, version_bytes))
    batch.add(Cell(digest_root, NULL_CELL_ID, NULL_CELL_ID, digest))
    batch.relation([
        *((protocol.role("catalog-member"), root) for root in roots),
        (protocol.role("version"), version_root),
        (protocol.role("lifecycle"), protocol.states["released"]),
        (protocol.role("digest"), digest_root),
    ], relation_id=catalog_id)
    batch.commit()
    return catalog_id


def verify_adapter_catalog(
    snapshot: Snapshot,
    protocol: AdapterProtocol,
    catalog_root: str,
) -> AdapterCatalog:
    members = read_relation(snapshot, catalog_root, budget=100_000)
    allowed = {
        protocol.role(name) for name in (
            "catalog-member", "version", "lifecycle", "digest"
        )
    }
    _closed_roles(members, allowed, "adapter catalogue")
    catalog = AdapterCatalog(
        catalog_root,
        _one(members, protocol.role("version"), "catalogue version"),
        _one(members, protocol.role("lifecycle"), "catalogue lifecycle"),
        _one(members, protocol.role("digest"), "catalogue digest"),
        _for_role(members, protocol.role("catalog-member")),
    )
    if catalog.lifecycle_root != protocol.states["released"]:
        raise InvalidCell("adapter catalogue is not released")
    if len(catalog.adapter_roots) != len(set(catalog.adapter_roots)):
        raise InvalidCell("adapter catalogue repeats an adapter")
    version = snapshot.cells[catalog.version_root].atom
    expected = snapshot.cells[catalog.digest_root].atom
    actual = _catalog_digest(
        snapshot, protocol, catalog_root, catalog.adapter_roots, version
    )
    if not expected or not hmac.compare_digest(expected, actual):
        raise InvalidCell("released adapter catalogue has drifted")
    return catalog


def extend_adapter_catalog(
    store: CellStore,
    protocol: AdapterProtocol,
    catalog_root: str,
    adapter_roots: Iterable[str],
) -> AdapterCatalog:
    """Append released adapters to an existing catalogue without rebuilding it."""
    target_roots = tuple(adapter_roots)
    if len(target_roots) != len(set(target_roots)):
        raise InvalidCell("adapter catalogue repeats an adapter")
    snapshot = store.snapshot()
    catalog = verify_adapter_catalog(snapshot, protocol, catalog_root)
    if catalog.adapter_roots == target_roots:
        return catalog
    if (
        len(catalog.adapter_roots) > len(target_roots)
        or target_roots[:len(catalog.adapter_roots)] != catalog.adapter_roots
    ):
        raise InvalidCell("adapter catalogue cannot be migrated as an append")
    for root in target_roots:
        verify_released_adapter(snapshot, protocol, root)
    version = snapshot.cells[catalog.version_root].atom
    digest = _catalog_digest(
        snapshot, protocol, catalog_root, target_roots, version
    )
    missing = target_roots[len(catalog.adapter_roots):]
    patch = prepare_append_relation_members(
        snapshot,
        catalog_root,
        ((protocol.role("catalog-member"), root) for root in missing),
        budget=100_000,
    )
    digest_cell = snapshot.cells[catalog.digest_root]
    store.commit(
        snapshot.revision,
        create=patch.create,
        replace=(
            *patch.replace,
            Cell(
                digest_cell.id,
                digest_cell.link0,
                digest_cell.link1,
                digest,
            ),
        ),
    )
    return verify_adapter_catalog(store.snapshot(), protocol, catalog_root)


def build_permission_request(
    store: CellStore,
    protocol: AdapterProtocol,
    catalog_root: str,
    *,
    request_id: str,
    adapter_root: str,
    user_root: str,
    action_roots: Iterable[str],
    location_roots: Iterable[str],
    datatype_roots: Iterable[str],
    expires_at: float,
    max_invocations: int,
) -> str:
    snapshot = store.snapshot()
    catalog = verify_adapter_catalog(snapshot, protocol, catalog_root)
    if adapter_root not in catalog.adapter_roots:
        raise InvalidCell("permission requests an adapter outside the allowlist")
    adapter = verify_released_adapter(snapshot, protocol, adapter_root)
    if user_root not in snapshot.cells:
        raise InvalidCell("permission user is missing")
    requested = {
        "action": tuple(dict.fromkeys(action_roots)),
        "location": tuple(dict.fromkeys(location_roots)),
        "datatype": tuple(dict.fromkeys(datatype_roots)),
    }
    available = {
        "action": set(adapter.action_roots),
        "location": set(adapter.location_roots),
        "datatype": set(adapter.datatype_roots),
    }
    for name, roots in requested.items():
        if not roots or not set(roots).issubset(available[name]):
            raise InvalidCell("permission %s exceeds adapter bounds" % name)
    if expires_at <= time.time() or max_invocations < 1:
        raise InvalidCell("permission lifetime or invocation budget is invalid")
    batch = CellBatch(store)
    expires_root = _new_terminal(
        batch, request_id + ":expires-at", repr(float(expires_at))
    )
    budget_root = _new_terminal(
        batch, request_id + ":max-invocations", str(max_invocations)
    )
    digest_root = request_id + ":digest"
    batch.add(Cell(digest_root, NULL_CELL_ID, NULL_CELL_ID, b""))
    batch.relation([
        (protocol.role("adapter"), adapter_root),
        (protocol.role("user"), user_root),
        *((protocol.role("action"), root) for root in requested["action"]),
        *((protocol.role("location"), root) for root in requested["location"]),
        *((protocol.role("datatype"), root) for root in requested["datatype"]),
        (protocol.role("expires-at"), expires_root),
        (protocol.role("max-invocations"), budget_root),
        (protocol.role("lifecycle"), protocol.states["requested"]),
        (protocol.role("digest"), digest_root),
    ], relation_id=request_id)
    batch.commit()
    return request_id


def read_permission(
    snapshot: Snapshot,
    protocol: AdapterProtocol,
    request_root: str,
) -> PermissionProjection:
    members = read_relation(snapshot, request_root, budget=10_000)
    allowed = {
        protocol.role(name) for name in (
            "adapter", "user", "action", "location", "datatype",
            "expires-at", "max-invocations", "lifecycle", "digest",
        )
    }
    _closed_roles(members, allowed, "adapter permission")
    return PermissionProjection(
        request_root,
        _one(members, protocol.role("adapter"), "permission adapter"),
        _one(members, protocol.role("user"), "permission user"),
        _one(members, protocol.role("lifecycle"), "permission lifecycle"),
        _one(members, protocol.role("digest"), "permission digest"),
        _for_role(members, protocol.role("action")),
        _for_role(members, protocol.role("location")),
        _for_role(members, protocol.role("datatype")),
        _one(members, protocol.role("expires-at"), "permission expiry"),
        _one(members, protocol.role("max-invocations"), "permission budget"),
    )


def _permission_digest(
    snapshot: Snapshot,
    catalog: AdapterCatalog,
    permission: PermissionProjection,
) -> bytes:
    digest = hashlib.blake2b(digest_size=32)
    for root in (
        permission.root_id, permission.adapter_root, permission.user_root,
        *sorted(permission.action_roots),
        *sorted(permission.location_roots),
        *sorted(permission.datatype_roots),
        permission.expires_at_root, permission.max_invocations_root,
    ):
        raw = root.encode("utf-8")
        digest.update(len(raw).to_bytes(8, "big")); digest.update(raw)
        if root != permission.root_id:
            content = graph_content_digest(snapshot, root, budget=100_000)
            digest.update(len(content).to_bytes(8, "big")); digest.update(content)
    catalog_digest = snapshot.cells[catalog.digest_root].atom
    digest.update(len(catalog_digest).to_bytes(8, "big")); digest.update(catalog_digest)
    return digest.hexdigest().encode("ascii")


def grant_permission(
    store: CellStore,
    protocol: AdapterProtocol,
    catalog_root: str,
    request_root: str,
    consent_broker: UserConsentBroker,
    consent_handle: object,
) -> bytes:
    snapshot = store.snapshot()
    catalog = verify_adapter_catalog(snapshot, protocol, catalog_root)
    permission = read_permission(snapshot, protocol, request_root)
    if permission.lifecycle_root != protocol.states["requested"]:
        raise InvalidCell("only a requested permission can be granted")
    if permission.adapter_root not in catalog.adapter_roots:
        raise InvalidCell("permission adapter is outside the allowlist")
    consent_broker.consume(
        consent_handle, request_root, permission.user_root
    )
    digest = _permission_digest(snapshot, catalog, permission)
    members = read_relation(snapshot, request_root, budget=10_000)
    lifecycle = next(
        member for member in members
        if member.role_id == protocol.role("lifecycle")
    )
    incidence = snapshot.cells[lifecycle.incidence_id]
    digest_cell = snapshot.cells[permission.digest_root]
    store.commit(snapshot.revision, replace=(
        Cell(digest_cell.id, digest_cell.link0, digest_cell.link1, digest),
        Cell(
            incidence.id, incidence.link0,
            protocol.states["granted"], incidence.atom,
        ),
    ))
    return digest


def revoke_permission(
    store: CellStore,
    protocol: AdapterProtocol,
    request_root: str,
) -> int:
    """Revocation is always safe and does not require an escalation grant."""
    snapshot = store.snapshot()
    permission = read_permission(snapshot, protocol, request_root)
    if permission.lifecycle_root not in {
        protocol.states["requested"], protocol.states["granted"]
    }:
        raise InvalidCell("permission cannot be revoked from its current state")
    member = next(
        item for item in read_relation(snapshot, request_root)
        if item.role_id == protocol.role("lifecycle")
    )
    incidence = snapshot.cells[member.incidence_id]
    return store.commit(snapshot.revision, replace=(Cell(
        incidence.id, incidence.link0, protocol.states["revoked"], incidence.atom
    ),))


def authorize_adapter_invocation(
    snapshot: Snapshot,
    protocol: AdapterProtocol,
    catalog_root: str,
    request_root: str,
    *,
    adapter_root: str,
    user_root: str,
    action_root: str,
    location_root: str,
    datatype_root: str,
    invocation_count: int,
    now: float | None = None,
) -> PermissionProjection:
    """Recheck exact adapter consent on every attempted external effect."""
    catalog = verify_adapter_catalog(snapshot, protocol, catalog_root)
    if adapter_root not in catalog.adapter_roots:
        raise InvalidCell("adapter invocation is outside the allowlist")
    adapter = verify_released_adapter(snapshot, protocol, adapter_root)
    permission = read_permission(snapshot, protocol, request_root)
    if permission.lifecycle_root != protocol.states["granted"]:
        raise InvalidCell("adapter permission is not granted")
    if permission.adapter_root != adapter_root or permission.user_root != user_root:
        raise InvalidCell("adapter permission identity does not match")
    for value, granted, admitted, label in (
        (action_root, permission.action_roots, adapter.action_roots, "action"),
        (location_root, permission.location_roots, adapter.location_roots, "location"),
        (datatype_root, permission.datatype_roots, adapter.datatype_roots, "datatype"),
    ):
        if value not in granted or value not in admitted:
            raise InvalidCell("adapter permission denies %s" % label)
    expected = snapshot.cells[permission.digest_root].atom
    actual = _permission_digest(snapshot, catalog, permission)
    if not expected or not hmac.compare_digest(expected, actual):
        raise InvalidCell("granted adapter permission has drifted")
    try:
        expires_at = float(snapshot.cells[permission.expires_at_root].atom.decode("ascii"))
        maximum = int(snapshot.cells[permission.max_invocations_root].atom.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise InvalidCell("adapter permission bounds are invalid") from exc
    if (time.time() if now is None else now) >= expires_at:
        raise InvalidCell("adapter permission expired")
    if invocation_count < 0 or invocation_count >= maximum:
        raise InvalidCell("adapter permission invocation budget is exhausted")
    return permission


def build_authorized_adapter_evidence(
    store: CellStore,
    protocol: AdapterProtocol,
    catalog_root: str,
    request_root: str,
    operational_protocol,
    *,
    adapter_root: str,
    user_root: str,
    action_root: str,
    location_root: str,
    datatype_root: str,
    invocation_count: int,
    evidence_id: str,
    evidence_type_root: str,
    payload: bytes,
) -> str:
    """Create evidence only after the exact adapter grant is rechecked."""
    authorize_adapter_invocation(
        store.snapshot(),
        protocol,
        catalog_root,
        request_root,
        adapter_root=adapter_root,
        user_root=user_root,
        action_root=action_root,
        location_root=location_root,
        datatype_root=datatype_root,
        invocation_count=invocation_count,
    )
    from .cell_state_machine import build_evidence
    return build_evidence(
        store,
        operational_protocol,
        evidence_id=evidence_id,
        evidence_type_root=evidence_type_root,
        payload=payload,
        issuer_root=adapter_root,
    )


__all__ = [
    "AdapterProtocol", "AdapterDefinition", "AdapterProjection",
    "AdapterCatalog", "PermissionProjection", "UserConsentBroker",
    "UserConsentDenied", "UserConsentHandle", "bootstrap_adapter_protocol",
    "build_adapter_definition", "release_adapter_definition",
    "verify_released_adapter", "build_adapter_catalog",
    "verify_adapter_catalog", "extend_adapter_catalog",
    "build_permission_request", "read_permission", "grant_permission",
    "revoke_permission", "authorize_adapter_invocation",
    "build_authorized_adapter_evidence",
]
