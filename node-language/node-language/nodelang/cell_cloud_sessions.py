"""Device-bound cloud sessions assembled from universal Cells and relations.

The access token and client private key never enter the graph. A visible
session manifest carries only non-secret references and digests. Its authority
is an ordinary signed delegation relationship whose evidence includes the
content-addressed manifest digest, identity verification, and device binding.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import math
import secrets
import time
from types import MappingProxyType
from typing import Iterable, Mapping, Protocol

from .cell_authorization import AuthenticationBroker, AuthenticationContext
from .cell_federated_identity import FederatedAuthentication
from .cell_identity import (
    IdentityProtocol,
    RelationshipAuthorityBroker,
    RelationshipAuthorityDenied,
    active_membership_roots,
    grant_authority_relationship,
    revoke_authority_relationship,
    verify_authority_relationship,
)
from .cell_protocols import (
    CellBatch,
    RelationMember,
    compose_relation_cells,
    prepare_append_relation_member,
    prepare_append_relation_members,
    read_relation,
)
from .universal_cell import (
    NULL_CELL_ID,
    Cell,
    CellStore,
    Conflict,
    InvalidCell,
    Snapshot,
)


PROOF_REPLAY_ROLE_NAMES = (
    "proof-replay-policy",
    "proof-replay-policy-lifecycle",
    "proof-replay-policy-release",
    "proof-replay-window",
    "proof-replay-capacity",
    "proof-replay-retention-seconds",
    "proof-replay-slot-member",
)
LEGACY_PROOF_USE_ROLE_NAME = "proof-use-member"

ROLE_NAMES = (
    "vocabulary-member",
    "session-member",
    *PROOF_REPLAY_ROLE_NAMES,
    "subject",
    "tenant",
    "device",
    "audience",
    "assurance",
    "authentication-method",
    "issued-at",
    "auth-time",
    "expires-at",
    "token-digest",
    "proof-key-thumbprint",
    "evidence",
    "manifest-digest",
    "session",
    "proof-id-digest",
    "http-method",
    "target-uri-digest",
    "observed-at",
)

MAX_TOKEN_LENGTH = 512
MAX_PROOF_BYTES = 64 * 1024
DEFAULT_PROOF_REPLAY_CAPACITY = 1024
MAX_PROOF_REPLAY_CAPACITY = 1024
DEFAULT_PROOF_REPLAY_RETENTION_SECONDS = 15.0
MAX_PROOF_REPLAY_RETENTION_SECONDS = 3600.0
MAX_PROOF_REPLAY_COMMIT_ATTEMPTS = 32
_HTTP_METHOD_CHARS = frozenset(
    "!#$%&'*+-.^_`|~0123456789"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
)


class CloudSessionDenied(PermissionError):
    pass


class RequestProofVerifier(Protocol):
    """Trusted RFC 9449 verifier boundary; implementations use JOSE code."""

    def verify(
        self,
        proof: bytes,
        *,
        access_token: str,
        expected_thumbprint: str,
        http_method: str,
        target_uri: str,
        expected_nonce: str,
        now: float,
    ) -> str:
        """Return the verified proof `jti`, or raise on any failed check."""


@dataclass(frozen=True, slots=True)
class TenantAdmissionEvidence:
    """The exact released tenant authority admitted for a cloud request."""

    tenant_root: str
    published_revision_root: str
    catalogue_root: str
    policy_root: str


class TenantAdmissionVerifier(Protocol):
    """Trusted graph verifier for one tenant's currently released authority."""

    def verify(
        self,
        snapshot: Snapshot,
        *,
        tenant_root: str,
        subject_root: str,
        now: float,
    ) -> TenantAdmissionEvidence:
        """Return current release evidence, or deny the subject and tenant."""


class DeviceCustodyVerifier(Protocol):
    """Trusted graph verifier for one device's active key custody."""

    def verify(
        self,
        snapshot: Snapshot,
        *,
        device_root: str,
        now: float,
    ) -> str:
        """Return one active custody root, or deny the device."""


@dataclass(frozen=True, slots=True)
class ProofReplayPolicyReleaseEvidence:
    """One exact Published replay-policy revision admitted for use."""

    policy_root: str
    lifecycle_instance_root: str
    wip_revision_root: str
    shared_revision_root: str
    published_revision_root: str
    capacity: int
    retention_seconds: float


class ProofReplayPolicyAuthorityVerifier(Protocol):
    """Verify the current graph-released replay policy from one snapshot."""

    def verify(
        self,
        snapshot: Snapshot,
        protocol: "CloudSessionProtocol",
    ) -> ProofReplayPolicyReleaseEvidence:
        """Return exact Published evidence or deny an ungoverned policy."""


@dataclass(frozen=True, slots=True)
class CloudSessionProtocol:
    root_id: str
    roles: Mapping[str, str]
    proof_replay_policy_root: str
    proof_replay_policy_lifecycle_root: str | None = None

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown cloud-session role %r" % name) from exc


@dataclass(frozen=True, slots=True)
class CloudSessionProjection:
    root_id: str
    subject_root: str
    tenant_root: str
    device_root: str
    audience_root: str
    assurance_root: str
    authentication_method_root: str
    issued_at_root: str
    auth_time_root: str
    expires_at_root: str
    token_digest_root: str
    proof_key_thumbprint_root: str
    evidence_roots: tuple[str, ...]
    manifest_digest_root: str
    proof_replay_window_root: str
    proof_replay_policy_release_root: str


@dataclass(frozen=True, slots=True)
class ProofReplayWindowProjection:
    root_id: str
    capacity_root: str
    retention_seconds_root: str
    slot_roots: tuple[str, ...]
    capacity: int
    retention_seconds: float


@dataclass(frozen=True, slots=True)
class ProofReplayPolicyProjection:
    root_id: str
    capacity_root: str
    retention_seconds_root: str
    capacity: int
    retention_seconds: float


@dataclass(frozen=True, slots=True)
class ProofReplaySlotProjection:
    root_id: str
    proof_id_digest_root: str
    http_method_root: str
    target_uri_digest_root: str
    observed_at_root: str
    proof_id_digest: str
    http_method: str
    target_uri_digest: str
    observed_at: float


@dataclass(frozen=True, slots=True)
class IssuedCloudSession:
    session_root: str
    authority_relationship_root: str
    access_token: str
    expires_at: float


@dataclass(frozen=True, slots=True)
class CloudRequestAuthentication:
    context: AuthenticationContext
    session_root: str
    proof_use_root: str
    proof_use_revision: int
    device_root: str
    subject_root: str
    tenant_root: str
    audience_root: str
    assurance_root: str

    @property
    def proof_use_evidence(self) -> tuple[str, int]:
        """Return immutable proof evidence identity as root plus revision."""
        return self.proof_use_root, self.proof_use_revision


def _terminal_cell(root_id: str, value: str) -> Cell:
    encoded = str(value).encode("utf-8")
    if not encoded:
        raise InvalidCell("cloud-session values cannot be empty")
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, encoded)


def _atom(snapshot: Snapshot, root_id: str) -> str:
    try:
        return snapshot.cells[root_id].atom.decode("utf-8")
    except (KeyError, UnicodeDecodeError) as exc:
        raise CloudSessionDenied(
            "cloud-session graph value is missing or invalid"
        ) from exc


def _for_role(
    members: Iterable[RelationMember], role_id: str
) -> tuple[str, ...]:
    return tuple(
        member.participant_id for member in members
        if member.role_id == role_id
    )


def _one(members: tuple[RelationMember, ...], role_id: str, label: str) -> str:
    values = _for_role(members, role_id)
    if len(values) != 1:
        raise InvalidCell("cloud session requires exactly one %s" % label)
    return values[0]


def _validated_replay_policy(
    capacity: int, retention_seconds: float
) -> tuple[int, float]:
    if (
        isinstance(capacity, bool)
        or not isinstance(capacity, int)
        or not 1 <= capacity <= MAX_PROOF_REPLAY_CAPACITY
    ):
        raise ValueError(
            "proof replay capacity must be an integer from 1 to %s"
            % MAX_PROOF_REPLAY_CAPACITY
        )
    if (
        isinstance(retention_seconds, bool)
        or not isinstance(retention_seconds, (int, float))
        or not math.isfinite(float(retention_seconds))
        or float(retention_seconds) <= 0
        or float(retention_seconds) > MAX_PROOF_REPLAY_RETENTION_SECONDS
    ):
        raise ValueError(
            "proof replay retention must be a finite positive duration"
        )
    return capacity, float(retention_seconds)


def _proof_replay_policy_cells(
    protocol: CloudSessionProtocol,
    *,
    capacity: int,
    retention_seconds: float,
) -> tuple[Cell, ...]:
    root = protocol.proof_replay_policy_root
    capacity_cell = _terminal_cell(root + ":capacity", str(capacity))
    retention_cell = _terminal_cell(
        root + ":retention-seconds", str(retention_seconds)
    )
    relation = compose_relation_cells((
        (protocol.role("proof-replay-capacity"), capacity_cell.id),
        (
            protocol.role("proof-replay-retention-seconds"),
            retention_cell.id,
        ),
    ), relation_id=root)
    return (capacity_cell, retention_cell, *relation.cells)


def bootstrap_cloud_session_protocol(
    store: CellStore,
    *,
    prefix: str = "cloud-session-protocol",
    proof_replay_capacity: int = DEFAULT_PROOF_REPLAY_CAPACITY,
    proof_replay_retention_seconds: float = (
        DEFAULT_PROOF_REPLAY_RETENTION_SECONDS
    ),
) -> CloudSessionProtocol:
    capacity, retention_seconds = _validated_replay_policy(
        proof_replay_capacity, proof_replay_retention_seconds
    )
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    protocol = CloudSessionProtocol(
        prefix + ":root",
        MappingProxyType(roles),
        prefix + ":proof-replay-policy",
    )
    batch = CellBatch(store)
    for name, root in roles.items():
        batch.add(_terminal_cell(root, name))
    for cell in _proof_replay_policy_cells(
        protocol,
        capacity=capacity,
        retention_seconds=retention_seconds,
    ):
        batch.add(cell)
    batch.relation(
        (
            *((roles["vocabulary-member"], root) for root in roles.values()),
            (
                roles["proof-replay-policy"],
                protocol.proof_replay_policy_root,
            ),
        ),
        relation_id=protocol.root_id,
    )
    batch.commit()
    return protocol


def project_cloud_session_protocol(
    snapshot: Snapshot, *, prefix: str = "cloud-session-protocol"
) -> CloudSessionProtocol:
    """Recover the deterministic protocol vocabulary without writing Cells."""
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    policy_root = prefix + ":proof-replay-policy"
    protocol = CloudSessionProtocol(
        prefix + ":root", MappingProxyType(roles), policy_root
    )
    legacy_proof_use_role = (
        "%s:role:%s" % (prefix, LEGACY_PROOF_USE_ROLE_NAME)
    )
    root_id = prefix + ":root"
    if any(
        root not in snapshot.cells
        for root in (root_id, policy_root, *roles.values())
    ):
        raise InvalidCell("cloud-session protocol is incomplete")
    for name, root in roles.items():
        if _atom(snapshot, root) != name:
            raise InvalidCell("cloud-session protocol vocabulary drifted")
    members = read_relation(snapshot, root_id, budget=100_000)
    vocabulary = tuple(
        member.participant_id
        for member in members
        if member.role_id == roles["vocabulary-member"]
    )
    vocabulary_set = set(vocabulary)
    expected_vocabulary = set(roles.values())
    permitted_vocabulary = expected_vocabulary | {legacy_proof_use_role}
    if legacy_proof_use_role in vocabulary_set:
        legacy_cell = snapshot.cells.get(legacy_proof_use_role)
        if legacy_cell != _terminal_cell(
            legacy_proof_use_role, LEGACY_PROOF_USE_ROLE_NAME
        ):
            raise InvalidCell(
                "cloud-session legacy proof-use vocabulary drifted"
            )
    if (
        len(vocabulary) != len(set(vocabulary))
        or expected_vocabulary - vocabulary_set
        or vocabulary_set - permitted_vocabulary
        or any(
            member.role_id not in (
                roles["vocabulary-member"],
                roles["session-member"],
                roles["proof-replay-policy"],
                roles["proof-replay-policy-lifecycle"],
                *(
                    (legacy_proof_use_role,)
                    if legacy_proof_use_role in vocabulary_set else ()
                ),
            )
            for member in members
        )
    ):
        raise InvalidCell("cloud-session protocol relation drifted")
    policy_members = _for_role(
        members, roles["proof-replay-policy"]
    )
    if policy_members != (policy_root,):
        raise InvalidCell("cloud-session replay policy wiring drifted")
    lifecycle_members = _for_role(
        members, roles["proof-replay-policy-lifecycle"]
    )
    if len(lifecycle_members) > 1:
        raise InvalidCell(
            "cloud-session replay policy lifecycle wiring drifted"
        )
    if lifecycle_members and lifecycle_members[0] not in snapshot.cells:
        raise InvalidCell(
            "cloud-session replay policy lifecycle is missing"
        )
    read_proof_replay_policy(snapshot, protocol)
    return CloudSessionProtocol(
        protocol.root_id,
        protocol.roles,
        protocol.proof_replay_policy_root,
        lifecycle_members[0] if lifecycle_members else None,
    )


def bind_proof_replay_policy_lifecycle(
    store: CellStore,
    protocol: CloudSessionProtocol,
    lifecycle_instance_root: str,
) -> CloudSessionProtocol:
    """Wire one lifecycle instance to replay policy authority exactly once."""
    snapshot = store.snapshot()
    if lifecycle_instance_root not in snapshot.cells:
        raise InvalidCell(
            "cloud-session replay policy lifecycle is missing"
        )
    current = project_cloud_session_protocol(
        snapshot,
        prefix=protocol.root_id.removesuffix(":root"),
    )
    if current.proof_replay_policy_lifecycle_root is not None:
        if (
            current.proof_replay_policy_lifecycle_root
            != lifecycle_instance_root
        ):
            raise InvalidCell(
                "cloud-session replay policy lifecycle is already bound"
            )
        return current
    patch = prepare_append_relation_member(
        snapshot,
        current.root_id,
        current.role("proof-replay-policy-lifecycle"),
        lifecycle_instance_root,
        budget=100_000,
    )
    store.commit(
        snapshot.revision,
        create=patch.create,
        replace=patch.replace,
    )
    return project_cloud_session_protocol(
        store.snapshot(),
        prefix=protocol.root_id.removesuffix(":root"),
    )


def ensure_cloud_session_protocol(
    store: CellStore,
    *,
    prefix: str = "cloud-session-protocol",
    proof_replay_capacity: int = DEFAULT_PROOF_REPLAY_CAPACITY,
    proof_replay_retention_seconds: float = (
        DEFAULT_PROOF_REPLAY_RETENTION_SECONDS
    ),
) -> CloudSessionProtocol:
    """Migrate only missing deterministic vocabulary Cells, then verify."""
    capacity, retention_seconds = _validated_replay_policy(
        proof_replay_capacity, proof_replay_retention_seconds
    )
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    protocol = CloudSessionProtocol(
        prefix + ":root",
        MappingProxyType(roles),
        prefix + ":proof-replay-policy",
    )
    legacy_proof_use_role = (
        "%s:role:%s" % (prefix, LEGACY_PROOF_USE_ROLE_NAME)
    )
    root_id = prefix + ":root"
    if root_id not in store.snapshot().cells:
        return bootstrap_cloud_session_protocol(
            store,
            prefix=prefix,
            proof_replay_capacity=capacity,
            proof_replay_retention_seconds=retention_seconds,
        )
    for _ in range(4):
        snapshot = store.snapshot()
        members = read_relation(snapshot, root_id, budget=100_000)
        vocabulary = tuple(
            member.participant_id
            for member in members
            if member.role_id == roles["vocabulary-member"]
        )
        if len(vocabulary) != len(set(vocabulary)):
            raise InvalidCell(
                "cloud-session protocol vocabulary is duplicated"
            )
        if any(
            root not in (*roles.values(), legacy_proof_use_role)
            for root in vocabulary
        ):
            raise InvalidCell(
                "cloud-session protocol vocabulary is extended"
            )
        if legacy_proof_use_role in vocabulary:
            legacy_cell = snapshot.cells.get(legacy_proof_use_role)
            if legacy_cell != _terminal_cell(
                legacy_proof_use_role, LEGACY_PROOF_USE_ROLE_NAME
            ):
                raise InvalidCell(
                    "cloud-session legacy proof-use vocabulary drifted"
                )
        for name, root in roles.items():
            existing = snapshot.cells.get(root)
            if existing is not None and (
                existing.link0 != NULL_CELL_ID
                or existing.link1 != NULL_CELL_ID
                or existing.atom != name.encode("utf-8")
            ):
                raise InvalidCell(
                    "cloud-session protocol vocabulary drifted"
                )
        missing = tuple(
            (name, root)
            for name, root in roles.items()
            if root not in vocabulary
        )
        if any(
            name not in PROOF_REPLAY_ROLE_NAMES for name, _root in missing
        ):
            raise InvalidCell(
                "cloud-session legacy protocol vocabulary is incomplete"
            )
        role_cells = tuple(
            _terminal_cell(root, name)
            for name, root in missing
            if root not in snapshot.cells
        )
        policy_members = _for_role(
            members, roles["proof-replay-policy"]
        )
        if len(policy_members) > 1 or (
            policy_members
            and policy_members != (protocol.proof_replay_policy_root,)
        ):
            raise InvalidCell(
                "cloud-session replay policy wiring drifted"
            )
        create_policy = not policy_members
        if create_policy:
            if protocol.proof_replay_policy_root in snapshot.cells:
                read_proof_replay_policy(snapshot, protocol)
                policy_cells: tuple[Cell, ...] = ()
            else:
                policy_cells = _proof_replay_policy_cells(
                    protocol,
                    capacity=capacity,
                    retention_seconds=retention_seconds,
                )
        else:
            read_proof_replay_policy(snapshot, protocol)
            policy_cells = ()
        if not missing and not create_policy:
            return project_cloud_session_protocol(snapshot, prefix=prefix)
        append_members = (
            *(
                (roles["vocabulary-member"], root)
                for _name, root in missing
            ),
            *(
                ((
                    roles["proof-replay-policy"],
                    protocol.proof_replay_policy_root,
                ),)
                if create_policy else ()
            ),
        )
        patch = prepare_append_relation_members(
            snapshot,
            root_id,
            append_members,
            budget=100_000,
        )
        try:
            store.commit(
                snapshot.revision,
                create=(*role_cells, *policy_cells, *patch.create),
                replace=patch.replace,
            )
        except Conflict:
            continue
    raise InvalidCell("cloud-session protocol migration was contended")


def device_root_for_thumbprint(thumbprint: str) -> str:
    if (
        len(thumbprint) != 43
        or any(
            char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
            for char in thumbprint
        )
    ):
        raise ValueError(
            "device proof-key thumbprint must be RFC 7638 SHA-256 base64url"
        )
    return "device-proof-key:sha256:" + thumbprint


def provision_device_binding(
    store: CellStore,
    protocol: IdentityProtocol,
    relationship_broker: RelationshipAuthorityBroker,
    administration_handle: object,
    *,
    relationship_id: str,
    proof_key_thumbprint: str,
    subject_root: str,
    tenant_root: str,
    audience_root: str,
    administrator_root: str,
    reason: str,
    evidence_roots: tuple[str, ...] = (),
    now: float | None = None,
) -> str:
    """Provision one device public-key identity for a subject and audience."""
    device_root = device_root_for_thumbprint(proof_key_thumbprint)
    expected_atom = (
        "device-proof-key-thumbprint:" + proof_key_thumbprint
    ).encode("ascii")
    snapshot = store.snapshot()
    existing = snapshot.cells.get(device_root)
    if existing is None:
        store.commit(snapshot.revision, create=(Cell(
            device_root, NULL_CELL_ID, NULL_CELL_ID, expected_atom
        ),))
    elif (
        existing.link0 != NULL_CELL_ID
        or existing.link1 != NULL_CELL_ID
        or existing.atom != expected_atom
    ):
        raise InvalidCell("device proof-key identity drifted")
    return grant_authority_relationship(
        store,
        protocol,
        relationship_broker,
        administration_handle,
        relationship_id=relationship_id,
        source_root=device_root,
        target_root=subject_root,
        kind="audience-binding",
        tenant_root=tenant_root,
        scope_root=audience_root,
        administrator_root=administrator_root,
        reason=reason,
        evidence_roots=evidence_roots,
        now=now,
    )


def _sha256_hex(value: str) -> bool:
    return (
        len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def read_proof_replay_slot(
    snapshot: Snapshot,
    protocol: CloudSessionProtocol,
    slot_root: str,
) -> ProofReplaySlotProjection:
    members = read_relation(snapshot, slot_root, budget=8)
    allowed = {
        protocol.role("proof-id-digest"),
        protocol.role("http-method"),
        protocol.role("target-uri-digest"),
        protocol.role("observed-at"),
    }
    if len(members) != 4 or any(
        member.role_id not in allowed for member in members
    ):
        raise InvalidCell("proof replay slot shape drifted")
    proof_root = _one(
        members, protocol.role("proof-id-digest"), "proof digest"
    )
    method_root = _one(
        members, protocol.role("http-method"), "HTTP method"
    )
    target_root = _one(
        members, protocol.role("target-uri-digest"), "target URI digest"
    )
    observed_root = _one(
        members, protocol.role("observed-at"), "observation time"
    )
    expected_roots = {
        "proof-id-digest": slot_root + ":proof-id-digest",
        "http-method": slot_root + ":http-method",
        "target-uri-digest": slot_root + ":target-uri-digest",
        "observed-at": slot_root + ":observed-at",
    }
    if (
        proof_root != expected_roots["proof-id-digest"]
        or method_root != expected_roots["http-method"]
        or target_root != expected_roots["target-uri-digest"]
        or observed_root != expected_roots["observed-at"]
    ):
        raise InvalidCell("proof replay slot evidence is not slot-owned")
    proof_digest = _atom(snapshot, proof_root)
    method = _atom(snapshot, method_root)
    target_digest = _atom(snapshot, target_root)
    try:
        observed_at = float(_atom(snapshot, observed_root))
    except ValueError as exc:
        raise InvalidCell("proof replay slot time is invalid") from exc
    if not math.isfinite(observed_at) or observed_at < 0:
        raise InvalidCell("proof replay slot time is invalid")
    if (
        not _sha256_hex(proof_digest)
        or not method
        or len(method) > 32
        or any(char not in _HTTP_METHOD_CHARS for char in method)
        or not _sha256_hex(target_digest)
        or observed_at <= 0
    ):
        raise InvalidCell("proof replay slot evidence is invalid")
    return ProofReplaySlotProjection(
        slot_root,
        proof_root,
        method_root,
        target_root,
        observed_root,
        proof_digest,
        method,
        target_digest,
        observed_at,
    )


def read_proof_replay_policy(
    snapshot: Snapshot,
    protocol: CloudSessionProtocol,
) -> ProofReplayPolicyProjection:
    root = protocol.proof_replay_policy_root
    members = read_relation(snapshot, root, budget=4)
    allowed = {
        protocol.role("proof-replay-capacity"),
        protocol.role("proof-replay-retention-seconds"),
    }
    if len(members) != 2 or any(
        member.role_id not in allowed for member in members
    ):
        raise InvalidCell("proof replay policy shape drifted")
    capacity_root = _one(
        members, protocol.role("proof-replay-capacity"), "replay capacity"
    )
    retention_root = _one(
        members,
        protocol.role("proof-replay-retention-seconds"),
        "replay retention",
    )
    if (
        capacity_root != root + ":capacity"
        or retention_root != root + ":retention-seconds"
    ):
        raise InvalidCell("proof replay policy values are not policy-owned")
    try:
        capacity_text = _atom(snapshot, capacity_root)
        capacity = int(capacity_text)
        retention_seconds = float(_atom(snapshot, retention_root))
    except ValueError as exc:
        raise InvalidCell("proof replay policy value is invalid") from exc
    try:
        _validated_replay_policy(capacity, retention_seconds)
    except ValueError as exc:
        raise InvalidCell("proof replay policy value is invalid") from exc
    if str(capacity) != capacity_text:
        raise InvalidCell("proof replay policy capacity is not canonical")
    return ProofReplayPolicyProjection(
        root,
        capacity_root,
        retention_root,
        capacity,
        retention_seconds,
    )


def read_proof_replay_window(
    snapshot: Snapshot,
    protocol: CloudSessionProtocol,
    window_root: str,
) -> ProofReplayWindowProjection:
    members = read_relation(
        snapshot, window_root, budget=MAX_PROOF_REPLAY_CAPACITY + 4
    )
    allowed = {
        protocol.role("proof-replay-capacity"),
        protocol.role("proof-replay-retention-seconds"),
        protocol.role("proof-replay-slot-member"),
    }
    if any(member.role_id not in allowed for member in members):
        raise InvalidCell("proof replay window contains an undeclared field")
    capacity_root = _one(
        members, protocol.role("proof-replay-capacity"), "replay capacity"
    )
    retention_root = _one(
        members,
        protocol.role("proof-replay-retention-seconds"),
        "replay retention",
    )
    slot_roots = _for_role(
        members, protocol.role("proof-replay-slot-member")
    )
    try:
        capacity_text = _atom(snapshot, capacity_root)
        capacity = int(capacity_text)
    except ValueError as exc:
        raise InvalidCell("proof replay capacity is invalid") from exc
    if (
        isinstance(capacity, bool)
        or str(capacity) != capacity_text
        or not 1 <= capacity <= MAX_PROOF_REPLAY_CAPACITY
        or capacity_root != window_root + ":capacity"
        or retention_root != window_root + ":retention-seconds"
        or len(slot_roots) > capacity
        or len(set(slot_roots)) != len(slot_roots)
        or slot_roots != tuple(
            "%s:slot:%04d" % (window_root, index)
            for index in range(len(slot_roots))
        )
        or any(root not in snapshot.cells for root in slot_roots)
    ):
        raise InvalidCell("proof replay capacity is invalid")
    try:
        retention_seconds = float(_atom(snapshot, retention_root))
    except ValueError as exc:
        raise InvalidCell("proof replay retention is invalid") from exc
    if (
        not math.isfinite(retention_seconds)
        or retention_seconds <= 0
        or retention_seconds > MAX_PROOF_REPLAY_RETENTION_SECONDS
    ):
        raise InvalidCell("proof replay retention is invalid")
    return ProofReplayWindowProjection(
        window_root,
        capacity_root,
        retention_root,
        slot_roots,
        capacity,
        retention_seconds,
    )


def _proof_replay_window_cells(
    protocol: CloudSessionProtocol,
    session_root: str,
    *,
    capacity: int,
    retention_seconds: float,
) -> tuple[str, tuple[Cell, ...]]:
    window_root = session_root + ":proof-replay-window"
    capacity_cell = _terminal_cell(
        window_root + ":capacity", str(capacity)
    )
    retention_cell = _terminal_cell(
        window_root + ":retention-seconds", str(retention_seconds)
    )
    window_relation = compose_relation_cells((
        (protocol.role("proof-replay-capacity"), capacity_cell.id),
        (
            protocol.role("proof-replay-retention-seconds"),
            retention_cell.id,
        ),
    ), relation_id=window_root)
    return window_root, (
        capacity_cell,
        retention_cell,
        *window_relation.cells,
    )


def _proof_replay_slot_cells(
    protocol: CloudSessionProtocol,
    slot_root: str,
    *,
    proof_digest: str,
    http_method: str,
    target_digest: str,
    observed_at: float,
) -> tuple[Cell, ...]:
    values = {
        "proof-id-digest": proof_digest,
        "http-method": http_method,
        "target-uri-digest": target_digest,
        "observed-at": repr(float(observed_at)),
    }
    value_cells = {
        name: _terminal_cell("%s:%s" % (slot_root, name), value)
        for name, value in values.items()
    }
    relation = compose_relation_cells((
        (
            protocol.role("proof-id-digest"),
            value_cells["proof-id-digest"].id,
        ),
        (
            protocol.role("http-method"),
            value_cells["http-method"].id,
        ),
        (
            protocol.role("target-uri-digest"),
            value_cells["target-uri-digest"].id,
        ),
        (
            protocol.role("observed-at"),
            value_cells["observed-at"].id,
        ),
    ), relation_id=slot_root)
    return (*value_cells.values(), *relation.cells)


def read_cloud_session(
    snapshot: Snapshot,
    protocol: CloudSessionProtocol,
    session_root: str,
) -> CloudSessionProjection:
    members = read_relation(snapshot, session_root, budget=256)
    allowed = {
        protocol.role(name) for name in (
            "subject",
            "tenant",
            "device",
            "audience",
            "assurance",
            "authentication-method",
            "issued-at",
            "auth-time",
            "expires-at",
            "token-digest",
            "proof-key-thumbprint",
            "evidence",
            "manifest-digest",
            "proof-replay-window",
            "proof-replay-policy-release",
        )
    }
    if any(member.role_id not in allowed for member in members):
        raise InvalidCell("cloud session contains an undeclared field")
    return CloudSessionProjection(
        session_root,
        _one(members, protocol.role("subject"), "subject"),
        _one(members, protocol.role("tenant"), "tenant"),
        _one(members, protocol.role("device"), "device"),
        _one(members, protocol.role("audience"), "audience"),
        _one(members, protocol.role("assurance"), "assurance"),
        _one(
            members,
            protocol.role("authentication-method"),
            "authentication method",
        ),
        _one(members, protocol.role("issued-at"), "issued-at"),
        _one(members, protocol.role("auth-time"), "auth-time"),
        _one(members, protocol.role("expires-at"), "expires-at"),
        _one(members, protocol.role("token-digest"), "token digest"),
        _one(
            members,
            protocol.role("proof-key-thumbprint"),
            "proof-key thumbprint",
        ),
        _for_role(members, protocol.role("evidence")),
        _one(members, protocol.role("manifest-digest"), "manifest digest"),
        _one(
            members,
            protocol.role("proof-replay-window"),
            "proof replay window",
        ),
        _one(
            members,
            protocol.role("proof-replay-policy-release"),
            "proof replay policy release",
        ),
    )


def _manifest_payload(
    snapshot: Snapshot,
    protocol: CloudSessionProtocol,
    session: CloudSessionProjection,
) -> bytes:
    replay_window = read_proof_replay_window(
        snapshot, protocol, session.proof_replay_window_root
    )
    document = {
        "root": session.root_id,
        "subject": session.subject_root,
        "tenant": session.tenant_root,
        "device": session.device_root,
        "audience": session.audience_root,
        "assurance": session.assurance_root,
        "authentication_method": _atom(
            snapshot, session.authentication_method_root
        ),
        "issued_at": _atom(snapshot, session.issued_at_root),
        "auth_time": _atom(snapshot, session.auth_time_root),
        "expires_at": _atom(snapshot, session.expires_at_root),
        "token_digest": _atom(snapshot, session.token_digest_root),
        "proof_key_thumbprint": _atom(
            snapshot, session.proof_key_thumbprint_root
        ),
        "evidence": sorted(session.evidence_roots),
        "proof_replay_window": {
            "root": replay_window.root_id,
            "capacity": replay_window.capacity,
            "retention_seconds": _atom(
                snapshot, replay_window.retention_seconds_root
            ),
        },
        "proof_replay_policy_release": (
            session.proof_replay_policy_release_root
        ),
    }
    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def verify_cloud_session_manifest(
    snapshot: Snapshot,
    protocol: CloudSessionProtocol,
    session_root: str,
) -> CloudSessionProjection:
    registered = {
        member.participant_id for member in read_relation(
            snapshot, protocol.root_id, budget=100_000
        )
        if member.role_id == protocol.role("session-member")
    }
    if session_root not in registered:
        raise CloudSessionDenied("cloud session is not protocol-registered")
    session = read_cloud_session(snapshot, protocol, session_root)
    digest = hashlib.sha256(
        _manifest_payload(snapshot, protocol, session)
    ).hexdigest()
    expected_root = "cloud-session-manifest:sha256:" + digest
    if session.manifest_digest_root != expected_root:
        raise CloudSessionDenied("cloud session manifest digest drifted")
    if _atom(snapshot, expected_root) != digest:
        raise CloudSessionDenied("cloud session manifest evidence drifted")
    if session.device_root != device_root_for_thumbprint(
        _atom(snapshot, session.proof_key_thumbprint_root)
    ):
        raise CloudSessionDenied("cloud session device binding drifted")
    return session


class CloudSessionBroker:
    """Issue and authenticate short-lived, proof-of-possession sessions."""

    def __init__(
        self,
        *,
        session_protocol: CloudSessionProtocol,
        identity_protocol: IdentityProtocol,
        relationship_broker: RelationshipAuthorityBroker,
        authentication_broker: AuthenticationBroker,
        request_proof_verifier: RequestProofVerifier,
        replay_policy_authority_verifier: (
            ProofReplayPolicyAuthorityVerifier
        ),
        tenant_admission_verifier: TenantAdmissionVerifier,
        device_custody_verifier: DeviceCustodyVerifier,
        session_issuer_root: str,
        proof_replay_retention_seconds: float | None = None,
    ) -> None:
        declared_retention = getattr(
            request_proof_verifier, "replay_retention_seconds", None
        )
        if (
            declared_retention is not None
            and proof_replay_retention_seconds is not None
            and float(declared_retention)
            != float(proof_replay_retention_seconds)
        ):
            raise ValueError(
                "proof replay retention declarations disagree"
            )
        retention = (
            declared_retention
            if declared_retention is not None
            else proof_replay_retention_seconds
        )
        if (
            isinstance(retention, bool)
            or not isinstance(retention, (int, float))
            or not math.isfinite(float(retention))
            or float(retention) <= 0
            or float(retention) > MAX_PROOF_REPLAY_RETENTION_SECONDS
        ):
            raise ValueError(
                "proof replay retention must be a finite positive duration"
            )
        self._session_protocol = session_protocol
        self._identity_protocol = identity_protocol
        self._relationship_broker = relationship_broker
        self._authentication_broker = authentication_broker
        self._request_proof_verifier = request_proof_verifier
        if not hasattr(replay_policy_authority_verifier, "verify"):
            raise TypeError(
                "cloud session requires replay policy release verification"
            )
        self._replay_policy_authority_verifier = (
            replay_policy_authority_verifier
        )
        self._tenant_admission_verifier = tenant_admission_verifier
        if not hasattr(device_custody_verifier, "verify"):
            raise TypeError("cloud session requires device custody verification")
        self._device_custody_verifier = device_custody_verifier
        self._session_issuer_root = session_issuer_root
        self._proof_replay_retention_seconds = float(retention)

    def _released_replay_policy(
        self,
        snapshot: Snapshot,
    ) -> ProofReplayPolicyReleaseEvidence:
        try:
            evidence = self._replay_policy_authority_verifier.verify(
                snapshot, self._session_protocol
            )
            policy = read_proof_replay_policy(
                snapshot, self._session_protocol
            )
        except Exception as exc:
            raise CloudSessionDenied(
                "proof replay policy has no active Published release"
            ) from exc
        if (
            type(evidence) is not ProofReplayPolicyReleaseEvidence
            or evidence.policy_root
            != self._session_protocol.proof_replay_policy_root
            or evidence.lifecycle_instance_root
            != self._session_protocol.proof_replay_policy_lifecycle_root
            or evidence.capacity != policy.capacity
            or evidence.retention_seconds != policy.retention_seconds
            or any(
                root not in snapshot.cells
                for root in (
                    evidence.wip_revision_root,
                    evidence.shared_revision_root,
                    evidence.published_revision_root,
                )
            )
        ):
            raise CloudSessionDenied(
                "proof replay policy release evidence drifted"
            )
        return evidence

    def _tenant_admission(
        self,
        snapshot: Snapshot,
        *,
        tenant_root: str,
        subject_root: str,
        now: float,
    ) -> TenantAdmissionEvidence:
        try:
            evidence = self._tenant_admission_verifier.verify(
                snapshot,
                tenant_root=tenant_root,
                subject_root=subject_root,
                now=now,
            )
        except Exception as exc:
            raise CloudSessionDenied(
                "cloud session tenant release is inactive"
            ) from exc
        if (
            type(evidence) is not TenantAdmissionEvidence
            or evidence.tenant_root != tenant_root
            or any(
                root not in snapshot.cells
                for root in (
                    evidence.published_revision_root,
                    evidence.catalogue_root,
                    evidence.policy_root,
                )
            )
        ):
            raise CloudSessionDenied(
                "cloud session tenant release evidence drifted"
            )
        return evidence

    def _verified_device_binding(
        self,
        snapshot: Snapshot,
        *,
        device_root: str,
        subject_root: str,
        tenant_root: str,
        audience_root: str,
        now: float,
    ) -> str:
        matches = []
        for member in read_relation(
            snapshot, self._identity_protocol.root_id, budget=100_000
        ):
            if member.role_id != self._identity_protocol.roles[
                "relationship-member"
            ]:
                continue
            try:
                relationship = verify_authority_relationship(
                    snapshot,
                    self._identity_protocol,
                    self._relationship_broker,
                    member.participant_id,
                    now=now,
                )
            except (RelationshipAuthorityDenied, InvalidCell, KeyError):
                continue
            if (
                relationship.kind_root
                == self._identity_protocol.kinds["audience-binding"]
                and relationship.source_root == device_root
                and relationship.target_root == subject_root
                and relationship.tenant_root == tenant_root
                and relationship.scope_root == audience_root
            ):
                matches.append(relationship.root_id)
        if len(matches) != 1:
            raise CloudSessionDenied(
                "device requires one active subject/audience binding"
            )
        return matches[0]

    def _verified_device_custody(
        self,
        snapshot: Snapshot,
        *,
        device_root: str,
        now: float,
    ) -> str:
        try:
            custody_root = self._device_custody_verifier.verify(
                snapshot,
                device_root=device_root,
                now=now,
            )
        except Exception as exc:
            raise CloudSessionDenied(
                "cloud session device custody is inactive"
            ) from exc
        if (
            not isinstance(custody_root, str)
            or not custody_root
            or custody_root not in snapshot.cells
        ):
            raise CloudSessionDenied(
                "cloud session device custody evidence drifted"
            )
        return custody_root

    def issue(
        self,
        store: CellStore,
        authentication: FederatedAuthentication,
        *,
        proof_key_thumbprint: str,
        allowed_action_roots: Iterable[str],
        lifetime_seconds: float = 900.0,
        now: float | None = None,
    ) -> IssuedCloudSession:
        if type(authentication) is not FederatedAuthentication:
            raise CloudSessionDenied(
                "session issuance requires broker-verified identity"
            )
        current = time.time() if now is None else now
        if lifetime_seconds <= 0 or lifetime_seconds > 3600:
            raise ValueError("cloud session lifetime must be within one hour")
        identity = self._authentication_broker.resolve(
            authentication.context, now=current
        )
        if (
            identity.subject_root != authentication.subject_root
            or identity.tenant_root != authentication.tenant_root
            or identity.assurance_root != authentication.assurance_root
        ):
            raise CloudSessionDenied("federated identity context drifted")
        actions = tuple(dict.fromkeys(allowed_action_roots))
        snapshot = store.snapshot()
        replay_policy_release = self._released_replay_policy(snapshot)
        replay_policy = read_proof_replay_policy(
            snapshot, self._session_protocol
        )
        if (
            replay_policy.retention_seconds
            < self._proof_replay_retention_seconds
        ):
            raise CloudSessionDenied(
                "proof replay policy is shorter than verification"
            )
        required = {
            authentication.subject_root,
            authentication.tenant_root,
            authentication.audience_root,
            authentication.assurance_root,
            authentication.evidence_root,
            *actions,
        }
        if not actions or any(root not in snapshot.cells for root in required):
            raise CloudSessionDenied(
                "session scope references missing or empty graph authority"
            )
        tenant_admission = self._tenant_admission(
            snapshot,
            tenant_root=authentication.tenant_root,
            subject_root=authentication.subject_root,
            now=current,
        )
        device_root = device_root_for_thumbprint(proof_key_thumbprint)
        device_custody_root = self._verified_device_custody(
            snapshot,
            device_root=device_root,
            now=current,
        )
        device_binding_root = self._verified_device_binding(
            snapshot,
            device_root=device_root,
            subject_root=authentication.subject_root,
            tenant_root=authentication.tenant_root,
            audience_root=authentication.audience_root,
            now=current,
        )
        external_expiry = float(authentication.claims["expires_at"])
        expires_at = min(current + lifetime_seconds, external_expiry)
        if expires_at <= current:
            raise CloudSessionDenied("federated identity expired before issuance")
        token = "ah_dpop_" + secrets.token_urlsafe(32)
        token_digest = hashlib.sha256(token.encode("ascii")).hexdigest()
        session_root = "cloud-session:" + secrets.token_hex(16)
        values = {
            "authentication-method": authentication.claims[
                "authentication_method"
            ],
            "issued-at": "%.6f" % current,
            "auth-time": authentication.claims["auth_time"],
            "expires-at": "%.6f" % expires_at,
            "token-digest": token_digest,
            "proof-key-thumbprint": proof_key_thumbprint,
        }
        value_cells = {
            name: _terminal_cell("%s:%s" % (session_root, name), value)
            for name, value in values.items()
        }
        replay_window_root, replay_window_cells = (
            _proof_replay_window_cells(
                self._session_protocol,
                session_root,
                capacity=replay_policy.capacity,
                retention_seconds=replay_policy.retention_seconds,
            )
        )
        provisional = CloudSessionProjection(
            session_root,
            authentication.subject_root,
            authentication.tenant_root,
            device_root,
            authentication.audience_root,
            authentication.assurance_root,
            value_cells["authentication-method"].id,
            value_cells["issued-at"].id,
            value_cells["auth-time"].id,
            value_cells["expires-at"].id,
            value_cells["token-digest"].id,
            value_cells["proof-key-thumbprint"].id,
            (
                authentication.evidence_root,
                device_custody_root,
                device_binding_root,
                tenant_admission.published_revision_root,
                replay_policy_release.published_revision_root,
            ),
            "",
            replay_window_root,
            replay_policy_release.published_revision_root,
        )
        temp_cells = dict(snapshot.cells)
        temp_cells.update({cell.id: cell for cell in value_cells.values()})
        temp_cells.update({cell.id: cell for cell in replay_window_cells})
        temp_snapshot = Snapshot(snapshot.revision, MappingProxyType(temp_cells))
        manifest_digest = hashlib.sha256(
            _manifest_payload(
                temp_snapshot, self._session_protocol, provisional
            )
        ).hexdigest()
        manifest_root = "cloud-session-manifest:sha256:" + manifest_digest
        manifest_cell = _terminal_cell(manifest_root, manifest_digest)
        relation = compose_relation_cells((
            (self._session_protocol.role("subject"), authentication.subject_root),
            (self._session_protocol.role("tenant"), authentication.tenant_root),
            (self._session_protocol.role("device"), device_root),
            (self._session_protocol.role("audience"), authentication.audience_root),
            (self._session_protocol.role("assurance"), authentication.assurance_root),
            (self._session_protocol.role("authentication-method"), value_cells["authentication-method"].id),
            (self._session_protocol.role("issued-at"), value_cells["issued-at"].id),
            (self._session_protocol.role("auth-time"), value_cells["auth-time"].id),
            (self._session_protocol.role("expires-at"), value_cells["expires-at"].id),
            (self._session_protocol.role("token-digest"), value_cells["token-digest"].id),
            (self._session_protocol.role("proof-key-thumbprint"), value_cells["proof-key-thumbprint"].id),
            (self._session_protocol.role("evidence"), authentication.evidence_root),
            (self._session_protocol.role("evidence"), device_custody_root),
            (self._session_protocol.role("evidence"), device_binding_root),
            (self._session_protocol.role("evidence"), tenant_admission.published_revision_root),
            (
                self._session_protocol.role("evidence"),
                replay_policy_release.published_revision_root,
            ),
            (self._session_protocol.role("manifest-digest"), manifest_root),
            (
                self._session_protocol.role("proof-replay-window"),
                replay_window_root,
            ),
            (
                self._session_protocol.role("proof-replay-policy-release"),
                replay_policy_release.published_revision_root,
            ),
        ), relation_id=session_root)
        patch = prepare_append_relation_member(
            snapshot,
            self._session_protocol.root_id,
            self._session_protocol.role("session-member"),
            session_root,
            budget=100_000,
        )
        store.commit(
            snapshot.revision,
            create=(
                *value_cells.values(),
                *replay_window_cells,
                manifest_cell,
                *relation.cells,
                *patch.create,
            ),
            replace=patch.replace,
        )
        authority_root = session_root + ":authority"
        handle = self._relationship_broker.mint_from_trusted_administrator(
            self._session_issuer_root
        )
        grant_authority_relationship(
            store,
            self._identity_protocol,
            self._relationship_broker,
            handle,
            relationship_id=authority_root,
            source_root=session_root,
            target_root=authentication.subject_root,
            kind="delegation",
            tenant_root=authentication.tenant_root,
            scope_root=authentication.audience_root,
            action_roots=actions,
            administrator_root=self._session_issuer_root,
            expires_at=expires_at,
            reason="device-bound federated cloud session",
            evidence_roots=(
                manifest_root,
                authentication.evidence_root,
                device_custody_root,
                device_binding_root,
                tenant_admission.published_revision_root,
                replay_policy_release.published_revision_root,
            ),
            now=current,
        )
        return IssuedCloudSession(
            session_root, authority_root, token, expires_at
        )

    def _session_for_token(
        self, snapshot: Snapshot, token_digest: str
    ) -> CloudSessionProjection:
        matches = []
        for member in read_relation(
            snapshot, self._session_protocol.root_id, budget=100_000
        ):
            if member.role_id != self._session_protocol.role("session-member"):
                continue
            try:
                session = verify_cloud_session_manifest(
                    snapshot, self._session_protocol, member.participant_id
                )
            except (CloudSessionDenied, InvalidCell, KeyError):
                continue
            if _atom(snapshot, session.token_digest_root) == token_digest:
                matches.append(session)
        if len(matches) != 1:
            raise CloudSessionDenied("access token has no unique active session")
        return matches[0]

    def _authority(
        self,
        snapshot: Snapshot,
        session: CloudSessionProjection,
        *,
        requested_action_root: str,
        now: float,
    ):
        root = session.root_id + ":authority"
        try:
            relationship = verify_authority_relationship(
                snapshot,
                self._identity_protocol,
                self._relationship_broker,
                root,
                now=now,
            )
        except (RelationshipAuthorityDenied, InvalidCell, KeyError) as exc:
            raise CloudSessionDenied("cloud session authority is inactive") from exc
        if (
            relationship.kind_root
            != self._identity_protocol.kinds["delegation"]
            or relationship.source_root != session.root_id
            or relationship.target_root != session.subject_root
            or relationship.tenant_root != session.tenant_root
            or relationship.scope_root != session.audience_root
            or requested_action_root not in relationship.action_roots
            or session.manifest_digest_root not in relationship.evidence_roots
        ):
            raise CloudSessionDenied("cloud session authority scope drifted")
        device_custody_root = self._verified_device_custody(
            snapshot,
            device_root=session.device_root,
            now=now,
        )
        if (
            device_custody_root not in session.evidence_roots
            or device_custody_root not in relationship.evidence_roots
        ):
            raise CloudSessionDenied(
                "cloud session device custody evidence changed"
            )
        self._verified_device_binding(
            snapshot,
            device_root=session.device_root,
            subject_root=session.subject_root,
            tenant_root=session.tenant_root,
            audience_root=session.audience_root,
            now=now,
        )
        tenant_admission = self._tenant_admission(
            snapshot,
            tenant_root=session.tenant_root,
            subject_root=session.subject_root,
            now=now,
        )
        if (
            tenant_admission.published_revision_root
            not in session.evidence_roots
            or tenant_admission.published_revision_root
            not in relationship.evidence_roots
        ):
            raise CloudSessionDenied(
                "cloud session tenant release revision changed"
            )
        replay_policy_release = self._released_replay_policy(snapshot)
        if (
            replay_policy_release.published_revision_root
            != session.proof_replay_policy_release_root
            or replay_policy_release.published_revision_root
            not in session.evidence_roots
            or replay_policy_release.published_revision_root
            not in relationship.evidence_roots
        ):
            raise CloudSessionDenied(
                "cloud session replay policy release revision changed"
            )
        if session.tenant_root not in active_membership_roots(
            snapshot,
            self._identity_protocol,
            self._relationship_broker,
            session.subject_root,
            session.tenant_root,
            now=now,
        ):
            raise CloudSessionDenied("cloud session tenant membership is inactive")
        return relationship

    def _record_proof_use(
        self,
        store: CellStore,
        *,
        session: CloudSessionProjection,
        token_digest: str,
        requested_action_root: str,
        proof_id: str,
        http_method: str,
        target_uri: str,
        observed_at: float,
    ) -> tuple[str, int]:
        proof_digest = hashlib.sha256(proof_id.encode("utf-8")).hexdigest()
        target_digest = hashlib.sha256(
            target_uri.encode("utf-8")
        ).hexdigest()
        for _ in range(MAX_PROOF_REPLAY_COMMIT_ATTEMPTS):
            snapshot = store.snapshot()
            current_session = verify_cloud_session_manifest(
                snapshot,
                self._session_protocol,
                session.root_id,
            )
            if (
                current_session != session
                or _atom(snapshot, current_session.token_digest_root)
                != token_digest
            ):
                raise CloudSessionDenied(
                    "cloud session changed during request admission"
                )
            self._authority(
                snapshot,
                current_session,
                requested_action_root=requested_action_root,
                now=observed_at,
            )
            try:
                window = read_proof_replay_window(
                    snapshot,
                    self._session_protocol,
                    current_session.proof_replay_window_root,
                )
                slots = tuple(
                    read_proof_replay_slot(
                        snapshot, self._session_protocol, slot_root
                    )
                    for slot_root in window.slot_roots
                )
            except InvalidCell as exc:
                raise CloudSessionDenied(
                    "proof replay window drifted"
                ) from exc
            if (
                window.retention_seconds
                < self._proof_replay_retention_seconds
            ):
                raise CloudSessionDenied(
                    "proof replay retention is shorter than verification"
                )
            active = tuple(
                slot for slot in slots
                if slot.observed_at + window.retention_seconds >= observed_at
            )
            if any(
                hmac.compare_digest(slot.proof_id_digest, proof_digest)
                for slot in active
            ):
                raise CloudSessionDenied("request proof was replayed")
            available = tuple(
                slot for slot in slots
                if slot.observed_at + window.retention_seconds < observed_at
            )
            if available:
                selected = min(
                    available,
                    key=lambda slot: (slot.observed_at, slot.root_id),
                )
                replacement = (
                    _terminal_cell(
                        selected.proof_id_digest_root, proof_digest
                    ),
                    _terminal_cell(selected.http_method_root, http_method),
                    _terminal_cell(
                        selected.target_uri_digest_root, target_digest
                    ),
                    _terminal_cell(
                        selected.observed_at_root, repr(float(observed_at))
                    ),
                )
                try:
                    revision = store.commit(
                        snapshot.revision,
                        replace=replacement,
                    )
                    return selected.root_id, revision
                except Conflict:
                    continue
            if len(slots) >= window.capacity:
                raise CloudSessionDenied("request proof replay window is full")
            slot_root = "%s:slot:%04d" % (
                window.root_id,
                len(slots),
            )
            slot_cells = _proof_replay_slot_cells(
                self._session_protocol,
                slot_root,
                proof_digest=proof_digest,
                http_method=http_method,
                target_digest=target_digest,
                observed_at=observed_at,
            )
            patch = prepare_append_relation_member(
                snapshot,
                window.root_id,
                self._session_protocol.role("proof-replay-slot-member"),
                slot_root,
                budget=MAX_PROOF_REPLAY_CAPACITY + 4,
            )
            try:
                revision = store.commit(
                    snapshot.revision,
                    create=(*slot_cells, *patch.create),
                    replace=patch.replace,
                )
                return slot_root, revision
            except Conflict:
                continue
        raise CloudSessionDenied("request proof recording was contended")

    def authenticate_request(
        self,
        store: CellStore,
        access_token: str,
        proof: bytes,
        *,
        requested_action_root: str,
        http_method: str,
        target_uri: str,
        expected_nonce: str,
        now: float | None = None,
    ) -> CloudRequestAuthentication:
        if (
            not access_token.startswith("ah_dpop_")
            or len(access_token) > MAX_TOKEN_LENGTH
        ):
            raise CloudSessionDenied("access token shape is invalid")
        proof_bytes = bytes(proof)
        if not proof_bytes or len(proof_bytes) > MAX_PROOF_BYTES:
            raise CloudSessionDenied("request proof size is invalid")
        if (
            not http_method
            or len(http_method) > 32
            or any(char not in _HTTP_METHOD_CHARS for char in http_method)
            or not target_uri
            or not expected_nonce
        ):
            raise CloudSessionDenied("request binding fields are required")
        current = time.time() if now is None else now
        token_digest = hashlib.sha256(access_token.encode("ascii")).hexdigest()
        snapshot = store.snapshot()
        session = self._session_for_token(snapshot, token_digest)
        relationship = self._authority(
            snapshot,
            session,
            requested_action_root=requested_action_root,
            now=current,
        )
        try:
            expires_at = float(_atom(snapshot, session.expires_at_root))
        except ValueError as exc:
            raise CloudSessionDenied("cloud session expiry is invalid") from exc
        if expires_at <= current:
            raise CloudSessionDenied("cloud session expired")
        expected_thumbprint = _atom(
            snapshot, session.proof_key_thumbprint_root
        )
        try:
            proof_id = self._request_proof_verifier.verify(
                proof_bytes,
                access_token=access_token,
                expected_thumbprint=expected_thumbprint,
                http_method=http_method,
                target_uri=target_uri,
                expected_nonce=expected_nonce,
                now=current,
            )
        except Exception as exc:
            raise CloudSessionDenied("request proof verification failed") from exc
        if not isinstance(proof_id, str) or not proof_id:
            raise CloudSessionDenied("request proof verifier returned no identity")
        proof_use_root, proof_use_revision = self._record_proof_use(
            store,
            session=session,
            token_digest=token_digest,
            requested_action_root=requested_action_root,
            proof_id=proof_id,
            http_method=http_method,
            target_uri=target_uri,
            observed_at=current,
        )
        # This context is per-request. Every subsequent HTTP request must
        # present and record a fresh proof, so revocation is checked again.
        context = self._authentication_broker.mint_authenticated_context(
            session.subject_root,
            tenant_root=session.tenant_root,
            assurance_root=session.assurance_root,
            lifetime_seconds=min(5.0, max(0.001, expires_at - current)),
        )
        return CloudRequestAuthentication(
            context=context,
            session_root=session.root_id,
            proof_use_root=proof_use_root,
            device_root=session.device_root,
            subject_root=session.subject_root,
            tenant_root=session.tenant_root,
            audience_root=session.audience_root,
            assurance_root=session.assurance_root,
            proof_use_revision=proof_use_revision,
        )

    def revoke(
        self,
        store: CellStore,
        session_root: str,
        *,
        administrator_root: str,
        reason: str,
        now: float | None = None,
    ) -> int:
        handle = self._relationship_broker.mint_from_trusted_administrator(
            administrator_root
        )
        return revoke_authority_relationship(
            store,
            self._identity_protocol,
            self._relationship_broker,
            handle,
            session_root + ":authority",
            administrator_root=administrator_root,
            reason=reason,
            now=now,
        )


__all__ = [
    "PROOF_REPLAY_ROLE_NAMES",
    "LEGACY_PROOF_USE_ROLE_NAME",
    "DEFAULT_PROOF_REPLAY_CAPACITY",
    "MAX_PROOF_REPLAY_CAPACITY",
    "DEFAULT_PROOF_REPLAY_RETENTION_SECONDS",
    "CloudSessionDenied",
    "RequestProofVerifier",
    "TenantAdmissionEvidence",
    "TenantAdmissionVerifier",
    "CloudSessionProtocol",
    "DeviceCustodyVerifier",
    "CloudSessionProjection",
    "ProofReplayPolicyProjection",
    "ProofReplayWindowProjection",
    "ProofReplaySlotProjection",
    "IssuedCloudSession",
    "CloudRequestAuthentication",
    "CloudSessionBroker",
    "bootstrap_cloud_session_protocol",
    "project_cloud_session_protocol",
    "ensure_cloud_session_protocol",
    "device_root_for_thumbprint",
    "provision_device_binding",
    "read_cloud_session",
    "read_proof_replay_policy",
    "read_proof_replay_window",
    "read_proof_replay_slot",
    "verify_cloud_session_manifest",
]
