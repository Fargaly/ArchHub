"""Universal-Cell transparency log and RFC 9162 consistency primitives.

The Merkle construction follows RFC 9162 section 2.1 exactly. Persisted logs,
leaves, proofs, and checkpoints are ordinary relation compositions. Independent
witness services are added above this log boundary; a local log alone is not a
distributed rollback witness.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import base64
import binascii
import hashlib
import hmac
import json
from types import MappingProxyType
from typing import Iterable, Mapping
import uuid

from .cell_protocols import (
    CellBatch,
    append_relation_member,
    compose_relation_cells,
    prepare_append_relation_member,
    read_relation,
)
from .cell_signing_authority import (
    SigningAuthorityProtocol,
    SigningAuthorityProvider,
    sign_statement,
    verify_signing_key_descriptor,
    verify_signature_envelope,
)
from .universal_cell import (
    NULL_CELL_ID,
    Cell,
    CellStore,
    Conflict,
    InvalidCell,
    Snapshot,
)


LOG_PROTOCOL = "https://archhub.local/transparency-log/v1"
LEAF_PROTOCOL = "https://archhub.local/transparency-leaf/v1"
PROOF_PROTOCOL = "https://archhub.local/merkle-consistency-proof/rfc9162/v1"
CHECKPOINT_PROTOCOL = "https://archhub.local/transparency-checkpoint/v1"
CHECKPOINT_STATEMENT_PROTOCOL = (
    "application/vnd.archhub.transparency-checkpoint.v1"
)
CHECKPOINT_CONTEXT = "transparency-checkpoint"
CHECKPOINT_SIGNING_PURPOSE = "transparency-checkpoint"
WITNESS_POLICY_PROTOCOL = "https://archhub.local/witness-policy/v1"
WITNESS_ADMISSION_PROTOCOL = "https://archhub.local/witness-admission/v1"
WITNESS_STATE_LOG_PROTOCOL = "https://archhub.local/witness-state-log/v1"
WITNESS_STATE_PROTOCOL = "https://archhub.local/witness-state/v1"
WITNESS_RECEIPT_PROTOCOL = "https://archhub.local/witness-receipt/v1"
WITNESS_STATEMENT_PROTOCOL = "application/vnd.archhub.witness-receipt.v1"
WITNESS_CONTEXT = "transparency-witness"
WITNESS_SIGNING_PURPOSE = "transparency-witness"

LOG_FIELDS = ("protocol", "origin", "leaf", "checkpoint")
LEAF_FIELDS = ("protocol", "index", "content", "content-digest")
PROOF_FIELDS = (
    "protocol",
    "origin",
    "old-size",
    "new-size",
    "old-root",
    "new-root",
    "path",
    "proof-digest",
)
CHECKPOINT_FIELDS = (
    "protocol",
    "origin",
    "tree-size",
    "root-hash",
    "previous-size",
    "previous-root-hash",
    "latest-leaf",
    "latest-leaf-digest",
    "issued-at",
    "policy-root",
    "policy-digest",
    "proof-root",
    "proof-digest",
    "log-envelope-root",
    "checkpoint-digest",
)
WITNESS_POLICY_FIELDS = (
    "protocol",
    "origin",
    "threshold",
    "max-staleness-seconds",
    "witness",
    "policy-digest",
)
WITNESS_ADMISSION_FIELDS = (
    "protocol",
    "witness-id",
    "descriptor-root",
    "descriptor-digest",
    "state",
)
WITNESS_STATE_LOG_FIELDS = ("protocol", "witness-id", "state")
WITNESS_STATE_FIELDS = (
    "protocol",
    "witness-id",
    "origin",
    "tree-size",
    "root-hash",
    "checkpoint-digest",
    "previous-state",
    "receipt-root",
    "issued-at",
    "state-digest",
)
WITNESS_RECEIPT_FIELDS = (
    "protocol",
    "witness-id",
    "descriptor-root",
    "descriptor-digest",
    "checkpoint-root",
    "checkpoint-digest",
    "policy-root",
    "policy-digest",
    "proof-root",
    "proof-digest",
    "origin",
    "tree-size",
    "root-hash",
    "issued-at",
    "envelope-root",
    "receipt-digest",
)
ROLE_NAMES = (
    "vocabulary-member",
    *("log-" + name for name in LOG_FIELDS),
    *("leaf-" + name for name in LEAF_FIELDS),
    *("proof-" + name for name in PROOF_FIELDS),
    *("checkpoint-" + name for name in CHECKPOINT_FIELDS),
    *("witness-policy-" + name for name in WITNESS_POLICY_FIELDS),
    *("witness-admission-" + name for name in WITNESS_ADMISSION_FIELDS),
    *("witness-state-log-" + name for name in WITNESS_STATE_LOG_FIELDS),
    *("witness-state-" + name for name in WITNESS_STATE_FIELDS),
    *("witness-receipt-" + name for name in WITNESS_RECEIPT_FIELDS),
)

_SHA256 = "sha256:"
_EMPTY_ROOT = hashlib.sha256(b"").digest()


class TransparencyDenied(PermissionError):
    """A transparency graph, proof, checkpoint, or signing gate failed."""


@dataclass(frozen=True, slots=True)
class TransparencyProtocol:
    root_id: str
    roles: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown transparency role %r" % name) from exc


@dataclass(frozen=True, slots=True)
class MerkleHead:
    size: int
    root: bytes

    def __post_init__(self) -> None:
        if self.size < 0 or len(self.root) != 32:
            raise ValueError("Merkle head is invalid")

    @property
    def root_text(self) -> str:
        return _SHA256 + self.root.hex()


@dataclass(frozen=True, slots=True)
class TransparencyLogProjection:
    root_id: str
    origin: str
    leaf_roots: tuple[str, ...]
    checkpoint_roots: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TransparencyLeafProjection:
    root_id: str
    index: int
    content: bytes
    content_digest: str


@dataclass(frozen=True, slots=True)
class ConsistencyProofProjection:
    root_id: str
    origin: str
    old_size: int
    new_size: int
    old_root: bytes
    new_root: bytes
    path: tuple[bytes, ...]
    digest: str


@dataclass(frozen=True, slots=True)
class TransparencyCheckpointProjection:
    root_id: str
    origin: str
    tree_size: int
    root_hash: bytes
    previous_size: int
    previous_root_hash: bytes
    latest_leaf_root: str
    latest_leaf_digest: str
    issued_at: str
    policy_root: str
    policy_digest: str
    proof_root: str
    proof_digest: str
    envelope_root: str
    digest: str


@dataclass(frozen=True, slots=True)
class WitnessAdmission:
    witness_id: str
    descriptor_root: str
    descriptor_digest: str
    state: str = "active"


@dataclass(frozen=True, slots=True)
class WitnessPolicyProjection:
    root_id: str
    origin: str
    threshold: int
    max_staleness_seconds: int
    admissions: Mapping[str, WitnessAdmission]
    digest: str


@dataclass(frozen=True, slots=True)
class WitnessStateProjection:
    root_id: str
    witness_id: str
    origin: str
    tree_size: int
    root_hash: bytes
    checkpoint_digest: str
    previous_state_root: str
    receipt_root: str
    issued_at: str
    digest: str


@dataclass(frozen=True, slots=True)
class WitnessReceiptProjection:
    root_id: str
    witness_id: str
    descriptor_root: str
    descriptor_digest: str
    checkpoint_root: str
    checkpoint_digest: str
    policy_root: str
    policy_digest: str
    proof_root: str
    proof_digest: str
    origin: str
    tree_size: int
    root_hash: bytes
    issued_at: str
    envelope_root: str
    digest: str


@dataclass(frozen=True, slots=True)
class WitnessReceiptEvidence:
    store: CellStore
    transparency_protocol: TransparencyProtocol
    signing_protocol: SigningAuthorityProtocol
    provider: SigningAuthorityProvider
    descriptor_root: str
    state_log_root: str
    receipt_root: str


def _hash_leaf(content: bytes) -> bytes:
    return hashlib.sha256(b"\x00" + bytes(content)).digest()


def _hash_node(left: bytes, right: bytes) -> bytes:
    if len(left) != 32 or len(right) != 32:
        raise ValueError("Merkle node hashes must be 32 bytes")
    return hashlib.sha256(b"\x01" + left + right).digest()


def _split(size: int) -> int:
    if size <= 1:
        raise ValueError("Merkle split requires more than one leaf")
    return 1 << ((size - 1).bit_length() - 1)


def merkle_tree_hash(entries: Iterable[bytes]) -> bytes:
    """Return RFC 9162 MTH for an ordered sequence of raw leaf entries."""
    values = tuple(bytes(entry) for entry in entries)

    def subtree(start: int, end: int) -> bytes:
        size = end - start
        if size == 0:
            return _EMPTY_ROOT
        if size == 1:
            return _hash_leaf(values[start])
        split = _split(size)
        return _hash_node(
            subtree(start, start + split),
            subtree(start + split, end),
        )

    return subtree(0, len(values))


def merkle_head(entries: Iterable[bytes]) -> MerkleHead:
    values = tuple(bytes(entry) for entry in entries)
    return MerkleHead(len(values), merkle_tree_hash(values))


def inclusion_proof(entries: Iterable[bytes], leaf_index: int) -> tuple[bytes, ...]:
    values = tuple(bytes(entry) for entry in entries)
    if leaf_index < 0 or leaf_index >= len(values):
        raise ValueError("Merkle inclusion index is out of range")

    def path(index: int, start: int, end: int) -> tuple[bytes, ...]:
        size = end - start
        if size == 1:
            return ()
        split = _split(size)
        if index < split:
            return path(index, start, start + split) + (
                merkle_tree_hash(values[start + split:end]),
            )
        return path(index - split, start + split, end) + (
            merkle_tree_hash(values[start:start + split]),
        )

    return path(leaf_index, 0, len(values))


def verify_inclusion_proof(
    leaf_hash: bytes,
    leaf_index: int,
    tree_size: int,
    root_hash: bytes,
    path: Iterable[bytes],
) -> bool:
    """Verify RFC 9162 section 2.1.3.2 without accepting extra nodes."""
    if (
        len(leaf_hash) != 32
        or len(root_hash) != 32
        or leaf_index < 0
        or tree_size < 1
        or leaf_index >= tree_size
    ):
        return False
    fn = leaf_index
    sn = tree_size - 1
    result = bytes(leaf_hash)
    for raw in path:
        node = bytes(raw)
        if len(node) != 32 or sn == 0:
            return False
        if fn & 1 or fn == sn:
            result = _hash_node(node, result)
            if not fn & 1:
                while not fn & 1 and fn != 0:
                    fn >>= 1
                    sn >>= 1
        else:
            result = _hash_node(result, node)
        fn >>= 1
        sn >>= 1
    return sn == 0 and hmac.compare_digest(result, root_hash)


def consistency_proof(
    entries: Iterable[bytes], old_size: int
) -> tuple[bytes, ...]:
    """Generate the unique minimal RFC 9162 section 2.1.4.1 proof."""
    values = tuple(bytes(entry) for entry in entries)
    new_size = len(values)
    if old_size < 0 or old_size > new_size:
        raise ValueError("Merkle consistency sizes are invalid")
    if old_size in (0, new_size):
        return ()

    def subproof(
        old: int, start: int, end: int, complete: bool
    ) -> tuple[bytes, ...]:
        size = end - start
        if old == size:
            return () if complete else (merkle_tree_hash(values[start:end]),)
        split = _split(size)
        if old <= split:
            return subproof(old, start, start + split, complete) + (
                merkle_tree_hash(values[start + split:end]),
            )
        return subproof(old - split, start + split, end, False) + (
            merkle_tree_hash(values[start:start + split]),
        )

    return subproof(old_size, 0, new_size, True)


def verify_consistency_proof(
    old_size: int,
    new_size: int,
    old_root: bytes,
    new_root: bytes,
    path: Iterable[bytes],
) -> bool:
    """Verify RFC 9162 section 2.1.4.2 with strict size handling."""
    nodes = tuple(bytes(node) for node in path)
    if (
        old_size < 0
        or new_size < 0
        or old_size > new_size
        or len(old_root) != 32
        or len(new_root) != 32
        or any(len(node) != 32 for node in nodes)
    ):
        return False
    if old_size == 0:
        return (
            not nodes
            and hmac.compare_digest(old_root, _EMPTY_ROOT)
            and (new_size > 0 or hmac.compare_digest(new_root, _EMPTY_ROOT))
        )
    if old_size == new_size:
        return not nodes and hmac.compare_digest(old_root, new_root)
    if not nodes:
        return False
    proof = nodes
    if old_size & (old_size - 1) == 0:
        proof = (bytes(old_root),) + proof
    fn = old_size - 1
    sn = new_size - 1
    while fn & 1:
        fn >>= 1
        sn >>= 1
    first_root = proof[0]
    second_root = proof[0]
    for node in proof[1:]:
        if sn == 0:
            return False
        if fn & 1 or fn == sn:
            first_root = _hash_node(node, first_root)
            second_root = _hash_node(node, second_root)
            if not fn & 1:
                while True:
                    fn >>= 1
                    sn >>= 1
                    if fn & 1 or fn == 0:
                        break
        else:
            second_root = _hash_node(second_root, node)
        fn >>= 1
        sn >>= 1
    return (
        sn == 0
        and hmac.compare_digest(first_root, old_root)
        and hmac.compare_digest(second_root, new_root)
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _terminal(root_id: str, value: str) -> Cell:
    try:
        atom = str(value).encode("ascii")
    except UnicodeEncodeError as exc:
        raise InvalidCell("transparency values must be ASCII") from exc
    if not atom or len(atom) > 1_500_000:
        raise InvalidCell("transparency value is empty or too large")
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, atom)


def _canonical(fields: Mapping[str, str], *, domain: str) -> bytes:
    return (
        domain.encode("ascii")
        + b"\x00"
        + json.dumps(
            dict(fields), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")
    )


def _digest(fields: Mapping[str, str], *, domain: str) -> str:
    return _SHA256 + hashlib.sha256(_canonical(fields, domain=domain)).hexdigest()


def _root_text(value: bytes) -> str:
    if len(value) != 32:
        raise ValueError("Merkle root must be 32 bytes")
    return _SHA256 + value.hex()


def _root_bytes(value: str, label: str) -> bytes:
    if not value.startswith(_SHA256) or len(value) != 71:
        raise InvalidCell("%s is invalid" % label)
    try:
        raw = bytes.fromhex(value[len(_SHA256):])
    except ValueError as exc:
        raise InvalidCell("%s is invalid" % label) from exc
    if len(raw) != 32:
        raise InvalidCell("%s is invalid" % label)
    return raw


def _one(members, role_id: str, label: str) -> str:
    roots = tuple(
        member.participant_id for member in members if member.role_id == role_id
    )
    if len(roots) != 1:
        raise InvalidCell("transparency relation requires exactly one %s" % label)
    return roots[0]


def _values(
    snapshot: Snapshot,
    protocol: TransparencyProtocol,
    root_id: str,
    *,
    fields: tuple[str, ...],
    prefix: str,
    repeated: frozenset[str] = frozenset(),
) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
    members = read_relation(snapshot, root_id, budget=4096)
    allowed = {protocol.role(prefix + field) for field in fields}
    if any(member.role_id not in allowed for member in members):
        raise InvalidCell("transparency relation contains an undeclared field")
    roots: dict[str, tuple[str, ...]] = {}
    values: dict[str, tuple[str, ...]] = {}
    for field in fields:
        role = protocol.role(prefix + field)
        selected = tuple(
            member.participant_id for member in members if member.role_id == role
        )
        if field in repeated:
            roots[field] = selected
            values[field] = selected
            continue
        if len(selected) != 1:
            raise InvalidCell(
                "transparency relation requires exactly one %s" % field
            )
        cell = snapshot.cells.get(selected[0])
        if cell is None:
            raise InvalidCell("transparency field is missing")
        if cell.link0 != NULL_CELL_ID or cell.link1 != NULL_CELL_ID:
            raise InvalidCell("transparency scalar fields must be terminal")
        try:
            text = cell.atom.decode("ascii")
        except UnicodeDecodeError as exc:
            raise InvalidCell("transparency scalar fields must be ASCII") from exc
        if not text:
            raise InvalidCell("transparency scalar fields cannot be empty")
        roots[field] = selected
        values[field] = (text,)
    return roots, values


def bootstrap_transparency_protocol(
    store: CellStore, *, prefix: str = "transparency-protocol"
) -> TransparencyProtocol:
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    batch = CellBatch(store)
    for name, root in roles.items():
        batch.add(_terminal(root, name))
    root_id = prefix + ":root"
    batch.relation(
        ((roles["vocabulary-member"], root) for root in roles.values()),
        relation_id=root_id,
    )
    batch.commit()
    return TransparencyProtocol(root_id, MappingProxyType(roles))


def project_transparency_protocol(
    snapshot: Snapshot, *, prefix: str = "transparency-protocol"
) -> TransparencyProtocol:
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    root_id = prefix + ":root"
    if any(root not in snapshot.cells for root in (root_id, *roles.values())):
        raise InvalidCell("transparency protocol is incomplete")
    members = read_relation(snapshot, root_id, budget=512)
    declared = tuple(
        member.participant_id
        for member in members
        if member.role_id == roles["vocabulary-member"]
    )
    if len(declared) != len(set(declared)) or set(declared) != set(roles.values()):
        raise InvalidCell("transparency protocol vocabulary drifted")
    return TransparencyProtocol(root_id, MappingProxyType(roles))


def build_transparency_log(
    store: CellStore,
    protocol: TransparencyProtocol,
    *,
    log_id: str,
    origin: str,
) -> str:
    if log_id in store.snapshot().cells:
        raise InvalidCell("transparency log already exists")
    origin_root = log_id + ":origin"
    protocol_root = log_id + ":protocol"
    relation = compose_relation_cells(
        (
            (protocol.role("log-protocol"), protocol_root),
            (protocol.role("log-origin"), origin_root),
        ),
        relation_id=log_id,
    )
    store.commit(
        store.revision,
        create=(
            _terminal(protocol_root, LOG_PROTOCOL),
            _terminal(origin_root, origin),
            *relation.cells,
        ),
    )
    return log_id


def read_transparency_log(
    snapshot: Snapshot,
    protocol: TransparencyProtocol,
    log_root: str,
) -> TransparencyLogProjection:
    _, values = _values(
        snapshot,
        protocol,
        log_root,
        fields=LOG_FIELDS,
        prefix="log-",
        repeated=frozenset(("leaf", "checkpoint")),
    )
    if values["protocol"][0] != LOG_PROTOCOL:
        raise InvalidCell("transparency log protocol is invalid")
    leaves = values["leaf"]
    checkpoints = values["checkpoint"]
    if len(leaves) != len(set(leaves)) or len(checkpoints) != len(set(checkpoints)):
        raise InvalidCell("transparency log contains duplicate members")
    return TransparencyLogProjection(
        log_root, values["origin"][0], leaves, checkpoints
    )


def append_transparency_leaf(
    store: CellStore,
    protocol: TransparencyProtocol,
    log_root: str,
    content: bytes,
    *,
    leaf_id: str | None = None,
) -> str:
    payload = bytes(content)
    if not payload or len(payload) > 1_000_000:
        raise TransparencyDenied("transparency leaf is empty or too large")
    log = read_transparency_log(store.snapshot(), protocol, log_root)
    root = leaf_id or "%s:leaf:%d:%s" % (
        log_root, len(log.leaf_roots), uuid.uuid4()
    )
    encoded = base64.b64encode(payload).decode("ascii")
    fields = {
        "protocol": LEAF_PROTOCOL,
        "index": str(len(log.leaf_roots)),
        "content": encoded,
        "content-digest": _SHA256 + hashlib.sha256(payload).hexdigest(),
    }
    scalars = tuple(
        _terminal(root + ":" + name, value) for name, value in fields.items()
    )
    relation = compose_relation_cells(
        (
            (protocol.role("leaf-" + name), root + ":" + name)
            for name in LEAF_FIELDS
        ),
        relation_id=root,
    )
    store.commit(store.revision, create=(*scalars, *relation.cells))
    append_relation_member(store, log_root, protocol.role("log-leaf"), root)
    return root


def read_transparency_leaf(
    snapshot: Snapshot,
    protocol: TransparencyProtocol,
    leaf_root: str,
) -> TransparencyLeafProjection:
    _, values = _values(
        snapshot,
        protocol,
        leaf_root,
        fields=LEAF_FIELDS,
        prefix="leaf-",
    )
    if values["protocol"][0] != LEAF_PROTOCOL:
        raise InvalidCell("transparency leaf protocol is invalid")
    try:
        index = int(values["index"][0])
        content = base64.b64decode(values["content"][0], validate=True)
    except (ValueError, binascii.Error) as exc:
        raise InvalidCell("transparency leaf encoding is invalid") from exc
    digest = values["content-digest"][0]
    actual = _SHA256 + hashlib.sha256(content).hexdigest()
    if index < 0 or not content or not hmac.compare_digest(digest, actual):
        raise InvalidCell("transparency leaf is invalid")
    return TransparencyLeafProjection(leaf_root, index, content, digest)


def read_log_leaves(
    snapshot: Snapshot,
    protocol: TransparencyProtocol,
    log_root: str,
) -> tuple[TransparencyLeafProjection, ...]:
    log = read_transparency_log(snapshot, protocol, log_root)
    leaves = tuple(
        read_transparency_leaf(snapshot, protocol, root) for root in log.leaf_roots
    )
    if tuple(leaf.index for leaf in leaves) != tuple(range(len(leaves))):
        raise InvalidCell("transparency leaf indexes are not contiguous")
    return leaves


def _build_consistency_proof(
    store: CellStore,
    protocol: TransparencyProtocol,
    *,
    proof_id: str,
    origin: str,
    old_head: MerkleHead,
    new_head: MerkleHead,
    path: tuple[bytes, ...],
) -> str:
    semantic = {
        "protocol": PROOF_PROTOCOL,
        "origin": origin,
        "old-size": str(old_head.size),
        "new-size": str(new_head.size),
        "old-root": old_head.root_text,
        "new-root": new_head.root_text,
    }
    path_values = tuple(base64.b64encode(node).decode("ascii") for node in path)
    digest_fields = {**semantic, "path": json.dumps(path_values)}
    proof_digest = _digest(
        digest_fields, domain="ArchHub/merkle-consistency-proof/rfc9162/v1"
    )
    scalar_values = {**semantic, "proof-digest": proof_digest}
    scalar_cells = tuple(
        _terminal(proof_id + ":" + name, value)
        for name, value in scalar_values.items()
    )
    path_cells = tuple(
        _terminal("%s:path:%d" % (proof_id, index), value)
        for index, value in enumerate(path_values)
    )
    relation = compose_relation_cells(
        (
            *((protocol.role("proof-" + name), proof_id + ":" + name)
              for name in semantic),
            *((protocol.role("proof-path"), "%s:path:%d" % (proof_id, index))
              for index in range(len(path_values))),
            (protocol.role("proof-proof-digest"), proof_id + ":proof-digest"),
        ),
        relation_id=proof_id,
    )
    store.commit(
        store.revision, create=(*scalar_cells, *path_cells, *relation.cells)
    )
    return proof_id


def read_consistency_proof(
    snapshot: Snapshot,
    protocol: TransparencyProtocol,
    proof_root: str,
) -> ConsistencyProofProjection:
    _, values = _values(
        snapshot,
        protocol,
        proof_root,
        fields=PROOF_FIELDS,
        prefix="proof-",
        repeated=frozenset(("path",)),
    )
    if values["protocol"][0] != PROOF_PROTOCOL:
        raise InvalidCell("consistency proof protocol is invalid")
    path_values: list[bytes] = []
    path_text: list[str] = []
    for root in values["path"]:
        cell = snapshot.cells.get(root)
        if cell is None or cell.link0 != NULL_CELL_ID or cell.link1 != NULL_CELL_ID:
            raise InvalidCell("consistency proof path must be terminal")
        try:
            text = cell.atom.decode("ascii")
            raw = base64.b64decode(text, validate=True)
        except (UnicodeDecodeError, ValueError, binascii.Error) as exc:
            raise InvalidCell("consistency proof path is invalid") from exc
        if len(raw) != 32:
            raise InvalidCell("consistency proof path hash is invalid")
        path_text.append(text)
        path_values.append(raw)
    try:
        old_size = int(values["old-size"][0])
        new_size = int(values["new-size"][0])
    except ValueError as exc:
        raise InvalidCell("consistency proof sizes are invalid") from exc
    old_root = _root_bytes(values["old-root"][0], "old Merkle root")
    new_root = _root_bytes(values["new-root"][0], "new Merkle root")
    digest_fields = {
        "protocol": values["protocol"][0],
        "origin": values["origin"][0],
        "old-size": values["old-size"][0],
        "new-size": values["new-size"][0],
        "old-root": values["old-root"][0],
        "new-root": values["new-root"][0],
        "path": json.dumps(tuple(path_text)),
    }
    actual = _digest(
        digest_fields, domain="ArchHub/merkle-consistency-proof/rfc9162/v1"
    )
    committed = values["proof-digest"][0]
    if not hmac.compare_digest(committed, actual):
        raise InvalidCell("consistency proof digest mismatched")
    if not verify_consistency_proof(
        old_size, new_size, old_root, new_root, path_values
    ):
        raise InvalidCell("Merkle consistency proof is invalid")
    return ConsistencyProofProjection(
        proof_root,
        values["origin"][0],
        old_size,
        new_size,
        old_root,
        new_root,
        tuple(path_values),
        committed,
    )


def _checkpoint_semantic(
    *,
    origin: str,
    new_head: MerkleHead,
    old_head: MerkleHead,
    latest_leaf: TransparencyLeafProjection,
    issued_at: str,
    policy_root: str,
    policy_digest: str,
    proof_root: str,
    proof_digest: str,
) -> dict[str, str]:
    return {
        "protocol": CHECKPOINT_PROTOCOL,
        "origin": origin,
        "tree-size": str(new_head.size),
        "root-hash": new_head.root_text,
        "previous-size": str(old_head.size),
        "previous-root-hash": old_head.root_text,
        "latest-leaf": latest_leaf.root_id,
        "latest-leaf-digest": latest_leaf.content_digest,
        "issued-at": issued_at,
        "policy-root": policy_root,
        "policy-digest": policy_digest,
        "proof-root": proof_root,
        "proof-digest": proof_digest,
    }


def issue_transparency_checkpoint(
    store: CellStore,
    protocol: TransparencyProtocol,
    signing_protocol: SigningAuthorityProtocol,
    signing_provider: SigningAuthorityProvider,
    signing_descriptor_root: str,
    log_root: str,
    *,
    policy_root: str,
    policy_digest: str,
    authorization_evidence: str,
    checkpoint_id: str | None = None,
    issued_at: str | None = None,
) -> str:
    snapshot = store.snapshot()
    descriptor = verify_signing_key_descriptor(
        snapshot,
        signing_protocol,
        signing_provider,
        signing_descriptor_root,
        require_signing=True,
    )
    if descriptor.values["purpose"] != CHECKPOINT_SIGNING_PURPOSE:
        raise TransparencyDenied("transparency log signing purpose mismatched")
    log = read_transparency_log(snapshot, protocol, log_root)
    leaves = read_log_leaves(snapshot, protocol, log_root)
    if not leaves:
        raise TransparencyDenied("cannot checkpoint an empty transparency log")
    entries = tuple(leaf.content for leaf in leaves)
    new_head = merkle_head(entries)
    if log.checkpoint_roots:
        previous = verify_transparency_checkpoint(
            snapshot,
            protocol,
            signing_protocol,
            signing_provider,
            signing_descriptor_root,
            log_root,
            log.checkpoint_roots[-1],
            expected_policy_root=policy_root,
            expected_policy_digest=policy_digest,
        )
        old_head = MerkleHead(previous.tree_size, previous.root_hash)
    else:
        old_head = MerkleHead(0, _EMPTY_ROOT)
    if new_head.size <= old_head.size:
        raise TransparencyDenied("transparency checkpoint requires a new leaf")
    path = consistency_proof(entries, old_head.size)
    root = checkpoint_id or "%s:checkpoint:%d:%s" % (
        log_root, new_head.size, uuid.uuid4()
    )
    proof_root = root + ":consistency-proof"
    _build_consistency_proof(
        store,
        protocol,
        proof_id=proof_root,
        origin=log.origin,
        old_head=old_head,
        new_head=new_head,
        path=path,
    )
    proof = read_consistency_proof(store.snapshot(), protocol, proof_root)
    timestamp = issued_at or _now()
    semantic = _checkpoint_semantic(
        origin=log.origin,
        new_head=new_head,
        old_head=old_head,
        latest_leaf=leaves[-1],
        issued_at=timestamp,
        policy_root=policy_root,
        policy_digest=policy_digest,
        proof_root=proof_root,
        proof_digest=proof.digest,
    )
    checkpoint_digest = _digest(
        semantic, domain="ArchHub/transparency-checkpoint/v1"
    )
    signed = {**semantic, "checkpoint-digest": checkpoint_digest}
    envelope_root = root + ":log-signature"
    sign_statement(
        store,
        signing_protocol,
        signing_provider,
        signing_descriptor_root,
        envelope_id=envelope_root,
        statement_protocol=CHECKPOINT_STATEMENT_PROTOCOL,
        context=CHECKPOINT_CONTEXT,
        payload=_canonical(signed, domain="ArchHub/transparency-checkpoint/v1"),
        authorization_evidence=authorization_evidence,
        issued_at=timestamp,
    )
    all_fields = {
        **semantic,
        "log-envelope-root": envelope_root,
        "checkpoint-digest": checkpoint_digest,
    }
    scalars = tuple(
        _terminal(root + ":" + name, value) for name, value in all_fields.items()
    )
    relation = compose_relation_cells(
        (
            (protocol.role("checkpoint-" + name), root + ":" + name)
            for name in CHECKPOINT_FIELDS
        ),
        relation_id=root,
    )
    store.commit(store.revision, create=(*scalars, *relation.cells))
    verify_transparency_checkpoint(
        store.snapshot(),
        protocol,
        signing_protocol,
        signing_provider,
        signing_descriptor_root,
        log_root,
        root,
        expected_policy_root=policy_root,
        expected_policy_digest=policy_digest,
    )
    append_relation_member(
        store, log_root, protocol.role("log-checkpoint"), root
    )
    return root


def read_transparency_checkpoint(
    snapshot: Snapshot,
    protocol: TransparencyProtocol,
    checkpoint_root: str,
) -> TransparencyCheckpointProjection:
    _, values = _values(
        snapshot,
        protocol,
        checkpoint_root,
        fields=CHECKPOINT_FIELDS,
        prefix="checkpoint-",
    )
    scalar = {name: values[name][0] for name in CHECKPOINT_FIELDS}
    if scalar["protocol"] != CHECKPOINT_PROTOCOL:
        raise InvalidCell("transparency checkpoint protocol is invalid")
    try:
        tree_size = int(scalar["tree-size"])
        previous_size = int(scalar["previous-size"])
        if not scalar["issued-at"].endswith("Z"):
            raise ValueError("timestamp is not UTC")
        datetime.fromisoformat(scalar["issued-at"][:-1] + "+00:00")
    except ValueError as exc:
        raise InvalidCell("transparency checkpoint values are invalid") from exc
    root_hash = _root_bytes(scalar["root-hash"], "checkpoint root")
    previous_root = _root_bytes(
        scalar["previous-root-hash"], "checkpoint previous root"
    )
    semantic = {
        name: scalar[name]
        for name in CHECKPOINT_FIELDS
        if name not in ("log-envelope-root", "checkpoint-digest")
    }
    actual = _digest(semantic, domain="ArchHub/transparency-checkpoint/v1")
    if not hmac.compare_digest(scalar["checkpoint-digest"], actual):
        raise InvalidCell("transparency checkpoint digest mismatched")
    return TransparencyCheckpointProjection(
        checkpoint_root,
        scalar["origin"],
        tree_size,
        root_hash,
        previous_size,
        previous_root,
        scalar["latest-leaf"],
        scalar["latest-leaf-digest"],
        scalar["issued-at"],
        scalar["policy-root"],
        scalar["policy-digest"],
        scalar["proof-root"],
        scalar["proof-digest"],
        scalar["log-envelope-root"],
        scalar["checkpoint-digest"],
    )


def verify_transparency_checkpoint(
    snapshot: Snapshot,
    protocol: TransparencyProtocol,
    signing_protocol: SigningAuthorityProtocol,
    signing_provider: SigningAuthorityProvider,
    signing_descriptor_root: str,
    log_root: str,
    checkpoint_root: str,
    *,
    expected_policy_root: str,
    expected_policy_digest: str,
) -> TransparencyCheckpointProjection:
    log = read_transparency_log(snapshot, protocol, log_root)
    checkpoint = read_transparency_checkpoint(
        snapshot, protocol, checkpoint_root
    )
    if checkpoint.origin != log.origin:
        raise TransparencyDenied("transparency checkpoint origin mismatched")
    if (
        checkpoint.policy_root != expected_policy_root
        or not hmac.compare_digest(
            checkpoint.policy_digest, expected_policy_digest
        )
    ):
        raise TransparencyDenied("transparency checkpoint policy mismatched")
    leaves = read_log_leaves(snapshot, protocol, log_root)
    if checkpoint.tree_size < 1 or checkpoint.tree_size > len(leaves):
        raise TransparencyDenied("transparency checkpoint size is invalid")
    selected = leaves[:checkpoint.tree_size]
    head = merkle_head(leaf.content for leaf in selected)
    if not hmac.compare_digest(head.root, checkpoint.root_hash):
        raise TransparencyDenied("transparency checkpoint root mismatched")
    latest = selected[-1]
    if (
        latest.root_id != checkpoint.latest_leaf_root
        or not hmac.compare_digest(
            latest.content_digest, checkpoint.latest_leaf_digest
        )
    ):
        raise TransparencyDenied("transparency checkpoint latest leaf mismatched")
    proof = read_consistency_proof(snapshot, protocol, checkpoint.proof_root)
    if (
        proof.origin != checkpoint.origin
        or proof.old_size != checkpoint.previous_size
        or proof.new_size != checkpoint.tree_size
        or not hmac.compare_digest(proof.old_root, checkpoint.previous_root_hash)
        or not hmac.compare_digest(proof.new_root, checkpoint.root_hash)
        or not hmac.compare_digest(proof.digest, checkpoint.proof_digest)
    ):
        raise TransparencyDenied("transparency checkpoint proof mismatched")
    semantic = _checkpoint_semantic(
        origin=checkpoint.origin,
        new_head=MerkleHead(checkpoint.tree_size, checkpoint.root_hash),
        old_head=MerkleHead(
            checkpoint.previous_size, checkpoint.previous_root_hash
        ),
        latest_leaf=latest,
        issued_at=checkpoint.issued_at,
        policy_root=checkpoint.policy_root,
        policy_digest=checkpoint.policy_digest,
        proof_root=checkpoint.proof_root,
        proof_digest=checkpoint.proof_digest,
    )
    signed = {**semantic, "checkpoint-digest": checkpoint.digest}
    descriptor = verify_signing_key_descriptor(
        snapshot,
        signing_protocol,
        signing_provider,
        signing_descriptor_root,
    )
    if descriptor.values["purpose"] != CHECKPOINT_SIGNING_PURPOSE:
        raise TransparencyDenied("transparency log signing purpose mismatched")
    envelope = verify_signature_envelope(
        snapshot,
        signing_protocol,
        signing_provider,
        checkpoint.envelope_root,
        payload=_canonical(signed, domain="ArchHub/transparency-checkpoint/v1"),
        expected_statement_protocol=CHECKPOINT_STATEMENT_PROTOCOL,
        expected_context=CHECKPOINT_CONTEXT,
    )
    if envelope.values["key-descriptor"] != signing_descriptor_root:
        raise TransparencyDenied("transparency log signing descriptor mismatched")
    if checkpoint.previous_size == 0:
        if checkpoint.previous_root_hash != _EMPTY_ROOT:
            raise TransparencyDenied("initial checkpoint root is invalid")
    else:
        previous = tuple(
            read_transparency_checkpoint(snapshot, protocol, root)
            for root in log.checkpoint_roots
            if root != checkpoint_root
        )
        matches = tuple(
            candidate for candidate in previous
            if candidate.tree_size == checkpoint.previous_size
            and hmac.compare_digest(
                candidate.root_hash, checkpoint.previous_root_hash
            )
        )
        if len(matches) != 1:
            raise TransparencyDenied(
                "transparency checkpoint predecessor is missing or ambiguous"
            )
    return checkpoint


def _admission_semantic(admission: WitnessAdmission) -> dict[str, str]:
    if admission.state not in ("active", "disabled", "revoked"):
        raise InvalidCell("witness admission state is invalid")
    if not admission.witness_id or not admission.descriptor_root:
        raise InvalidCell("witness admission identity is invalid")
    _root_bytes(admission.descriptor_digest, "witness descriptor digest")
    return {
        "protocol": WITNESS_ADMISSION_PROTOCOL,
        "witness-id": admission.witness_id,
        "descriptor-root": admission.descriptor_root,
        "descriptor-digest": admission.descriptor_digest,
        "state": admission.state,
    }


def build_witness_policy(
    store: CellStore,
    protocol: TransparencyProtocol,
    *,
    policy_id: str,
    origin: str,
    threshold: int,
    admissions: Iterable[WitnessAdmission],
    max_staleness_seconds: int = 0,
) -> str:
    admitted = tuple(sorted(admissions, key=lambda item: item.witness_id))
    if not admitted or len({item.witness_id for item in admitted}) != len(admitted):
        raise InvalidCell("witness policy identities must be unique")
    active_count = sum(item.state == "active" for item in admitted)
    if threshold < 1 or threshold > active_count:
        raise InvalidCell("witness policy threshold is invalid")
    if max_staleness_seconds < 0:
        raise InvalidCell("witness policy staleness is invalid")
    if policy_id in store.snapshot().cells:
        raise InvalidCell("witness policy already exists")
    admission_values = tuple(_admission_semantic(item) for item in admitted)
    admission_roots = tuple(
        "%s:witness:%d" % (policy_id, index)
        for index in range(len(admitted))
    )
    created: list[Cell] = []
    for root, values in zip(admission_roots, admission_values):
        created.extend(
            _terminal(root + ":" + name, value)
            for name, value in values.items()
        )
        relation = compose_relation_cells(
            (
                (
                    protocol.role("witness-admission-" + name),
                    root + ":" + name,
                )
                for name in WITNESS_ADMISSION_FIELDS
            ),
            relation_id=root,
        )
        created.extend(relation.cells)
    semantic = {
        "protocol": WITNESS_POLICY_PROTOCOL,
        "origin": origin,
        "threshold": str(threshold),
        "max-staleness-seconds": str(max_staleness_seconds),
        "witnesses": json.dumps(admission_values, sort_keys=True, separators=(",", ":")),
    }
    policy_digest = _digest(semantic, domain="ArchHub/witness-policy/v1")
    scalar = {
        "protocol": WITNESS_POLICY_PROTOCOL,
        "origin": origin,
        "threshold": str(threshold),
        "max-staleness-seconds": str(max_staleness_seconds),
        "policy-digest": policy_digest,
    }
    created.extend(
        _terminal(policy_id + ":" + name, value)
        for name, value in scalar.items()
    )
    relation = compose_relation_cells(
        (
            (protocol.role("witness-policy-protocol"), policy_id + ":protocol"),
            (protocol.role("witness-policy-origin"), policy_id + ":origin"),
            (protocol.role("witness-policy-threshold"), policy_id + ":threshold"),
            (
                protocol.role("witness-policy-max-staleness-seconds"),
                policy_id + ":max-staleness-seconds",
            ),
            *((protocol.role("witness-policy-witness"), root)
              for root in admission_roots),
            (
                protocol.role("witness-policy-policy-digest"),
                policy_id + ":policy-digest",
            ),
        ),
        relation_id=policy_id,
    )
    created.extend(relation.cells)
    store.commit(store.revision, create=tuple(created))
    return policy_id


def _read_witness_admission(
    snapshot: Snapshot,
    protocol: TransparencyProtocol,
    admission_root: str,
) -> WitnessAdmission:
    _, values = _values(
        snapshot,
        protocol,
        admission_root,
        fields=WITNESS_ADMISSION_FIELDS,
        prefix="witness-admission-",
    )
    scalar = {name: values[name][0] for name in WITNESS_ADMISSION_FIELDS}
    if scalar["protocol"] != WITNESS_ADMISSION_PROTOCOL:
        raise InvalidCell("witness admission protocol is invalid")
    return WitnessAdmission(
        scalar["witness-id"],
        scalar["descriptor-root"],
        scalar["descriptor-digest"],
        scalar["state"],
    )


def read_witness_policy(
    snapshot: Snapshot,
    protocol: TransparencyProtocol,
    policy_root: str,
) -> WitnessPolicyProjection:
    _, values = _values(
        snapshot,
        protocol,
        policy_root,
        fields=WITNESS_POLICY_FIELDS,
        prefix="witness-policy-",
        repeated=frozenset(("witness",)),
    )
    if values["protocol"][0] != WITNESS_POLICY_PROTOCOL:
        raise InvalidCell("witness policy protocol is invalid")
    admissions = tuple(
        _read_witness_admission(snapshot, protocol, root)
        for root in values["witness"]
    )
    if not admissions or len({item.witness_id for item in admissions}) != len(admissions):
        raise InvalidCell("witness policy identities are missing or duplicated")
    try:
        threshold = int(values["threshold"][0])
        max_staleness = int(values["max-staleness-seconds"][0])
    except ValueError as exc:
        raise InvalidCell("witness policy numeric values are invalid") from exc
    active_count = sum(item.state == "active" for item in admissions)
    if threshold < 1 or threshold > active_count or max_staleness < 0:
        raise InvalidCell("witness policy values are invalid")
    semantic = {
        "protocol": values["protocol"][0],
        "origin": values["origin"][0],
        "threshold": values["threshold"][0],
        "max-staleness-seconds": values["max-staleness-seconds"][0],
        "witnesses": json.dumps(
            tuple(_admission_semantic(item) for item in admissions),
            sort_keys=True,
            separators=(",", ":"),
        ),
    }
    actual = _digest(semantic, domain="ArchHub/witness-policy/v1")
    committed = values["policy-digest"][0]
    if not hmac.compare_digest(committed, actual):
        raise InvalidCell("witness policy digest mismatched")
    return WitnessPolicyProjection(
        policy_root,
        values["origin"][0],
        threshold,
        max_staleness,
        MappingProxyType({item.witness_id: item for item in admissions}),
        committed,
    )


def build_log_consistency_proof(
    store: CellStore,
    protocol: TransparencyProtocol,
    log_root: str,
    *,
    old_size: int,
    new_size: int,
    proof_id: str | None = None,
) -> str:
    leaves = read_log_leaves(store.snapshot(), protocol, log_root)
    if old_size < 0 or old_size > new_size or new_size > len(leaves):
        raise TransparencyDenied("requested consistency proof sizes are invalid")
    log = read_transparency_log(store.snapshot(), protocol, log_root)
    entries = tuple(leaf.content for leaf in leaves[:new_size])
    old_head = MerkleHead(old_size, merkle_tree_hash(entries[:old_size]))
    new_head = MerkleHead(new_size, merkle_tree_hash(entries))
    root = proof_id or "%s:witness-proof:%d:%d:%s" % (
        log_root, old_size, new_size, uuid.uuid4()
    )
    return _build_consistency_proof(
        store,
        protocol,
        proof_id=root,
        origin=log.origin,
        old_head=old_head,
        new_head=new_head,
        path=consistency_proof(entries, old_size),
    )


def build_witness_state_log(
    store: CellStore,
    protocol: TransparencyProtocol,
    *,
    state_log_id: str,
    witness_id: str,
) -> str:
    if state_log_id in store.snapshot().cells:
        raise InvalidCell("witness state log already exists")
    scalar = {
        "protocol": WITNESS_STATE_LOG_PROTOCOL,
        "witness-id": witness_id,
    }
    cells = tuple(
        _terminal(state_log_id + ":" + name, value)
        for name, value in scalar.items()
    )
    relation = compose_relation_cells(
        (
            (
                protocol.role("witness-state-log-protocol"),
                state_log_id + ":protocol",
            ),
            (
                protocol.role("witness-state-log-witness-id"),
                state_log_id + ":witness-id",
            ),
        ),
        relation_id=state_log_id,
    )
    store.commit(store.revision, create=(*cells, *relation.cells))
    return state_log_id


def _read_witness_state_log(
    snapshot: Snapshot,
    protocol: TransparencyProtocol,
    state_log_root: str,
) -> tuple[str, tuple[str, ...]]:
    _, values = _values(
        snapshot,
        protocol,
        state_log_root,
        fields=WITNESS_STATE_LOG_FIELDS,
        prefix="witness-state-log-",
        repeated=frozenset(("state",)),
    )
    if values["protocol"][0] != WITNESS_STATE_LOG_PROTOCOL:
        raise InvalidCell("witness state log protocol is invalid")
    states = values["state"]
    if len(states) != len(set(states)):
        raise InvalidCell("witness state log contains duplicate states")
    return values["witness-id"][0], states


def read_witness_state(
    snapshot: Snapshot,
    protocol: TransparencyProtocol,
    state_root: str,
) -> WitnessStateProjection:
    _, values = _values(
        snapshot,
        protocol,
        state_root,
        fields=WITNESS_STATE_FIELDS,
        prefix="witness-state-",
    )
    scalar = {name: values[name][0] for name in WITNESS_STATE_FIELDS}
    if scalar["protocol"] != WITNESS_STATE_PROTOCOL:
        raise InvalidCell("witness state protocol is invalid")
    try:
        tree_size = int(scalar["tree-size"])
        if not scalar["issued-at"].endswith("Z"):
            raise ValueError("timestamp is not UTC")
        datetime.fromisoformat(scalar["issued-at"][:-1] + "+00:00")
    except ValueError as exc:
        raise InvalidCell("witness state values are invalid") from exc
    root_hash = _root_bytes(scalar["root-hash"], "witness state root")
    semantic = {
        name: scalar[name] for name in WITNESS_STATE_FIELDS
        if name != "state-digest"
    }
    actual = _digest(semantic, domain="ArchHub/witness-state/v1")
    if tree_size < 1 or not hmac.compare_digest(scalar["state-digest"], actual):
        raise InvalidCell("witness state digest mismatched")
    return WitnessStateProjection(
        state_root,
        scalar["witness-id"],
        scalar["origin"],
        tree_size,
        root_hash,
        scalar["checkpoint-digest"],
        scalar["previous-state"],
        scalar["receipt-root"],
        scalar["issued-at"],
        scalar["state-digest"],
    )


def latest_witness_state(
    snapshot: Snapshot,
    protocol: TransparencyProtocol,
    state_log_root: str,
) -> WitnessStateProjection | None:
    witness_id, roots = _read_witness_state_log(
        snapshot, protocol, state_log_root
    )
    states = tuple(read_witness_state(snapshot, protocol, root) for root in roots)
    for index, state in enumerate(states):
        if state.witness_id != witness_id:
            raise InvalidCell("witness state identity mismatched")
        expected_previous = "none" if index == 0 else states[index - 1].root_id
        if state.previous_state_root != expected_previous:
            raise InvalidCell("witness state chain is invalid")
        if index and state.tree_size <= states[index - 1].tree_size:
            raise InvalidCell("witness state size is not monotonic")
    return states[-1] if states else None


def _witness_states(
    snapshot: Snapshot,
    protocol: TransparencyProtocol,
    state_log_root: str,
) -> tuple[str, tuple[WitnessStateProjection, ...]]:
    witness_id, roots = _read_witness_state_log(
        snapshot, protocol, state_log_root
    )
    states = tuple(read_witness_state(snapshot, protocol, root) for root in roots)
    latest_witness_state(snapshot, protocol, state_log_root)
    return witness_id, states


def _receipt_semantic(
    *,
    witness_id: str,
    descriptor_root: str,
    descriptor_digest: str,
    checkpoint: TransparencyCheckpointProjection,
    policy: WitnessPolicyProjection,
    proof: ConsistencyProofProjection,
    issued_at: str,
) -> dict[str, str]:
    return {
        "protocol": WITNESS_RECEIPT_PROTOCOL,
        "witness-id": witness_id,
        "descriptor-root": descriptor_root,
        "descriptor-digest": descriptor_digest,
        "checkpoint-root": checkpoint.root_id,
        "checkpoint-digest": checkpoint.digest,
        "policy-root": policy.root_id,
        "policy-digest": policy.digest,
        "proof-root": proof.root_id,
        "proof-digest": proof.digest,
        "origin": checkpoint.origin,
        "tree-size": str(checkpoint.tree_size),
        "root-hash": _root_text(checkpoint.root_hash),
        "issued-at": issued_at,
    }


def _state_matches_checkpoint(
    state: WitnessStateProjection | None,
    checkpoint: TransparencyCheckpointProjection,
) -> bool:
    return bool(
        state is not None
        and state.origin == checkpoint.origin
        and state.tree_size == checkpoint.tree_size
        and hmac.compare_digest(state.root_hash, checkpoint.root_hash)
        and hmac.compare_digest(
            state.checkpoint_digest, checkpoint.digest
        )
    )


def read_witness_receipt(
    snapshot: Snapshot,
    protocol: TransparencyProtocol,
    receipt_root: str,
) -> WitnessReceiptProjection:
    _, values = _values(
        snapshot,
        protocol,
        receipt_root,
        fields=WITNESS_RECEIPT_FIELDS,
        prefix="witness-receipt-",
    )
    scalar = {name: values[name][0] for name in WITNESS_RECEIPT_FIELDS}
    if scalar["protocol"] != WITNESS_RECEIPT_PROTOCOL:
        raise InvalidCell("witness receipt protocol is invalid")
    try:
        tree_size = int(scalar["tree-size"])
        if not scalar["issued-at"].endswith("Z"):
            raise ValueError("timestamp is not UTC")
        datetime.fromisoformat(scalar["issued-at"][:-1] + "+00:00")
    except ValueError as exc:
        raise InvalidCell("witness receipt values are invalid") from exc
    root_hash = _root_bytes(scalar["root-hash"], "witness receipt root")
    semantic = {
        name: scalar[name] for name in WITNESS_RECEIPT_FIELDS
        if name not in ("envelope-root", "receipt-digest")
    }
    actual = _digest(semantic, domain="ArchHub/witness-receipt/v1")
    if tree_size < 1 or not hmac.compare_digest(scalar["receipt-digest"], actual):
        raise InvalidCell("witness receipt digest mismatched")
    return WitnessReceiptProjection(
        receipt_root,
        scalar["witness-id"],
        scalar["descriptor-root"],
        scalar["descriptor-digest"],
        scalar["checkpoint-root"],
        scalar["checkpoint-digest"],
        scalar["policy-root"],
        scalar["policy-digest"],
        scalar["proof-root"],
        scalar["proof-digest"],
        scalar["origin"],
        tree_size,
        root_hash,
        scalar["issued-at"],
        scalar["envelope-root"],
        scalar["receipt-digest"],
    )


class GraphWitnessService:
    """One monotonic witness backed by its own universal-Cell store."""

    def __init__(
        self,
        *,
        store: CellStore,
        transparency_protocol: TransparencyProtocol,
        signing_protocol: SigningAuthorityProtocol,
        provider: SigningAuthorityProvider,
        descriptor_root: str,
        state_log_root: str,
        witness_id: str,
    ) -> None:
        self.store = store
        self.transparency_protocol = transparency_protocol
        self.signing_protocol = signing_protocol
        self.provider = provider
        self.descriptor_root = descriptor_root
        self.state_log_root = state_log_root
        self.witness_id = witness_id
        stored_id, _ = _read_witness_state_log(
            store.snapshot(), transparency_protocol, state_log_root
        )
        if stored_id != witness_id:
            raise InvalidCell("witness service identity mismatched")

    def __reduce_ex__(self, protocol):
        raise TypeError("witness services cannot be serialized")

    def cosign(
        self,
        *,
        log_snapshot: Snapshot,
        log_protocol: TransparencyProtocol,
        log_signing_protocol: SigningAuthorityProtocol,
        log_provider: SigningAuthorityProvider,
        log_descriptor_root: str,
        log_root: str,
        checkpoint_root: str,
        policy_root: str,
        proof_root: str,
        receipt_id: str | None = None,
        issued_at: str | None = None,
    ) -> str:
        policy = read_witness_policy(log_snapshot, log_protocol, policy_root)
        checkpoint = verify_transparency_checkpoint(
            log_snapshot,
            log_protocol,
            log_signing_protocol,
            log_provider,
            log_descriptor_root,
            log_root,
            checkpoint_root,
            expected_policy_root=policy.root_id,
            expected_policy_digest=policy.digest,
        )
        if policy.origin != checkpoint.origin:
            raise TransparencyDenied("witness policy origin mismatched")
        admission = policy.admissions.get(self.witness_id)
        if admission is None or admission.state != "active":
            raise TransparencyDenied("witness is not actively admitted")
        descriptor = verify_signing_key_descriptor(
            self.store.snapshot(),
            self.signing_protocol,
            self.provider,
            self.descriptor_root,
            require_signing=True,
        )
        if (
            descriptor.values["purpose"] != WITNESS_SIGNING_PURPOSE
            or
            admission.descriptor_root != self.descriptor_root
            or not hmac.compare_digest(admission.descriptor_digest, descriptor.digest)
        ):
            raise TransparencyDenied("witness signing descriptor mismatched")
        proof = read_consistency_proof(log_snapshot, log_protocol, proof_root)
        if (
            proof.origin != checkpoint.origin
            or proof.new_size != checkpoint.tree_size
            or not hmac.compare_digest(proof.new_root, checkpoint.root_hash)
        ):
            raise TransparencyDenied("witness consistency proof target mismatched")
        current = latest_witness_state(
            self.store.snapshot(), self.transparency_protocol, self.state_log_root
        )
        old_size = 0 if current is None else current.tree_size
        old_root = _EMPTY_ROOT if current is None else current.root_hash
        if checkpoint.tree_size < old_size:
            raise TransparencyDenied("witness checkpoint would roll history back")
        if checkpoint.tree_size == old_size:
            if not hmac.compare_digest(checkpoint.root_hash, old_root):
                raise TransparencyDenied("witness observed a same-size split root")
            if current is None or checkpoint.digest != current.checkpoint_digest:
                raise TransparencyDenied("witness observed a conflicting checkpoint")
            return current.receipt_root
        if (
            proof.old_size != old_size
            or not hmac.compare_digest(proof.old_root, old_root)
        ):
            raise TransparencyDenied("witness proof does not start at retained state")
        if not verify_consistency_proof(
            old_size,
            checkpoint.tree_size,
            old_root,
            checkpoint.root_hash,
            proof.path,
        ):
            raise TransparencyDenied("witness consistency proof is invalid")
        timestamp = issued_at or _now()
        if policy.max_staleness_seconds:
            checkpoint_time = datetime.fromisoformat(
                checkpoint.issued_at[:-1] + "+00:00"
            )
            now = datetime.fromisoformat(timestamp[:-1] + "+00:00")
            age = (now - checkpoint_time).total_seconds()
            if age < 0 or age > policy.max_staleness_seconds:
                raise TransparencyDenied("witness checkpoint is stale")
        root = receipt_id or "%s:receipt:%d:%s" % (
            self.state_log_root, checkpoint.tree_size, uuid.uuid4()
        )
        semantic = _receipt_semantic(
            witness_id=self.witness_id,
            descriptor_root=self.descriptor_root,
            descriptor_digest=descriptor.digest,
            checkpoint=checkpoint,
            policy=policy,
            proof=proof,
            issued_at=timestamp,
        )
        receipt_digest = _digest(semantic, domain="ArchHub/witness-receipt/v1")
        signed = {**semantic, "receipt-digest": receipt_digest}
        envelope_root = root + ":signature"
        try:
            sign_statement(
                self.store,
                self.signing_protocol,
                self.provider,
                self.descriptor_root,
                envelope_id=envelope_root,
                statement_protocol=WITNESS_STATEMENT_PROTOCOL,
                context=WITNESS_CONTEXT,
                payload=_canonical(signed, domain="ArchHub/witness-receipt/v1"),
                authorization_evidence="witness-policy:" + policy.digest,
                issued_at=timestamp,
            )
        except Conflict as exc:
            advanced = latest_witness_state(
                self.store.snapshot(),
                self.transparency_protocol,
                self.state_log_root,
            )
            if _state_matches_checkpoint(advanced, checkpoint):
                return advanced.receipt_root
            raise TransparencyDenied(
                "witness state changed concurrently"
            ) from exc
        receipt_fields = {
            **semantic,
            "envelope-root": envelope_root,
            "receipt-digest": receipt_digest,
        }
        receipt_cells = tuple(
            _terminal(root + ":" + name, value)
            for name, value in receipt_fields.items()
        )
        receipt_relation = compose_relation_cells(
            (
                (
                    self.transparency_protocol.role("witness-receipt-" + name),
                    root + ":" + name,
                )
                for name in WITNESS_RECEIPT_FIELDS
            ),
            relation_id=root,
        )
        snapshot = self.store.snapshot()
        persisted_current = latest_witness_state(
            snapshot, self.transparency_protocol, self.state_log_root
        )
        observed_root = "none" if current is None else current.root_id
        persisted_root = (
            "none" if persisted_current is None else persisted_current.root_id
        )
        if persisted_root != observed_root:
            if _state_matches_checkpoint(persisted_current, checkpoint):
                return persisted_current.receipt_root
            raise TransparencyDenied("witness state changed concurrently")

        state_root = root + ":state"
        state_semantic = {
            "protocol": WITNESS_STATE_PROTOCOL,
            "witness-id": self.witness_id,
            "origin": checkpoint.origin,
            "tree-size": str(checkpoint.tree_size),
            "root-hash": _root_text(checkpoint.root_hash),
            "checkpoint-digest": checkpoint.digest,
            "previous-state": persisted_root,
            "receipt-root": root,
            "issued-at": timestamp,
        }
        state_fields = {
            **state_semantic,
            "state-digest": _digest(
                state_semantic, domain="ArchHub/witness-state/v1"
            ),
        }
        state_cells = tuple(
            _terminal(state_root + ":" + name, value)
            for name, value in state_fields.items()
        )
        state_relation = compose_relation_cells(
            (
                (
                    self.transparency_protocol.role("witness-state-" + name),
                    state_root + ":" + name,
                )
                for name in WITNESS_STATE_FIELDS
            ),
            relation_id=state_root,
        )
        patch = prepare_append_relation_member(
            snapshot,
            self.state_log_root,
            self.transparency_protocol.role("witness-state-log-state"),
            state_root,
        )
        try:
            self.store.commit(
                snapshot.revision,
                create=(
                    *receipt_cells,
                    *receipt_relation.cells,
                    *state_cells,
                    *state_relation.cells,
                    *patch.create,
                ),
                replace=patch.replace,
            )
        except Conflict as exc:
            advanced = latest_witness_state(
                self.store.snapshot(),
                self.transparency_protocol,
                self.state_log_root,
            )
            if _state_matches_checkpoint(advanced, checkpoint):
                return advanced.receipt_root
            raise TransparencyDenied(
                "witness state changed concurrently"
            ) from exc
        persisted = latest_witness_state(
            self.store.snapshot(), self.transparency_protocol, self.state_log_root
        )
        if persisted is None or persisted.receipt_root != root:
            raise TransparencyDenied("witness state was not persisted")
        return root


def verify_witness_receipt(
    *,
    log_snapshot: Snapshot,
    log_protocol: TransparencyProtocol,
    checkpoint: TransparencyCheckpointProjection,
    policy: WitnessPolicyProjection,
    evidence: WitnessReceiptEvidence,
    accepted_at: datetime | None = None,
) -> WitnessReceiptProjection:
    receipt = read_witness_receipt(
        evidence.store.snapshot(),
        evidence.transparency_protocol,
        evidence.receipt_root,
    )
    admission = policy.admissions.get(receipt.witness_id)
    if admission is None or admission.state != "active":
        raise TransparencyDenied("receipt witness is not actively admitted")
    descriptor = verify_signing_key_descriptor(
        evidence.store.snapshot(),
        evidence.signing_protocol,
        evidence.provider,
        evidence.descriptor_root,
    )
    if (
        descriptor.values["purpose"] != WITNESS_SIGNING_PURPOSE
        or
        evidence.descriptor_root != admission.descriptor_root
        or receipt.descriptor_root != admission.descriptor_root
        or not hmac.compare_digest(descriptor.digest, admission.descriptor_digest)
        or not hmac.compare_digest(receipt.descriptor_digest, admission.descriptor_digest)
    ):
        raise TransparencyDenied("receipt witness descriptor mismatched")
    proof = read_consistency_proof(
        log_snapshot, log_protocol, receipt.proof_root
    )
    expected = (
        receipt.checkpoint_root == checkpoint.root_id
        and hmac.compare_digest(receipt.checkpoint_digest, checkpoint.digest)
        and receipt.policy_root == policy.root_id
        and hmac.compare_digest(receipt.policy_digest, policy.digest)
        and hmac.compare_digest(receipt.proof_digest, proof.digest)
        and receipt.origin == checkpoint.origin == policy.origin
        and receipt.tree_size == checkpoint.tree_size == proof.new_size
        and hmac.compare_digest(receipt.root_hash, checkpoint.root_hash)
        and hmac.compare_digest(proof.new_root, checkpoint.root_hash)
    )
    if not expected:
        raise TransparencyDenied("witness receipt subject mismatched")
    semantic = _receipt_semantic(
        witness_id=receipt.witness_id,
        descriptor_root=receipt.descriptor_root,
        descriptor_digest=receipt.descriptor_digest,
        checkpoint=checkpoint,
        policy=policy,
        proof=proof,
        issued_at=receipt.issued_at,
    )
    signed = {**semantic, "receipt-digest": receipt.digest}
    envelope = verify_signature_envelope(
        evidence.store.snapshot(),
        evidence.signing_protocol,
        evidence.provider,
        receipt.envelope_root,
        payload=_canonical(signed, domain="ArchHub/witness-receipt/v1"),
        expected_statement_protocol=WITNESS_STATEMENT_PROTOCOL,
        expected_context=WITNESS_CONTEXT,
    )
    if envelope.values["key-descriptor"] != evidence.descriptor_root:
        raise TransparencyDenied("witness envelope descriptor mismatched")
    state_witness_id, states = _witness_states(
        evidence.store.snapshot(),
        evidence.transparency_protocol,
        evidence.state_log_root,
    )
    if state_witness_id != receipt.witness_id:
        raise TransparencyDenied("witness state log identity mismatched")
    matching_states = tuple(
        state for state in states
        if state.receipt_root == receipt.root_id
    )
    if len(matching_states) != 1:
        raise TransparencyDenied("witness receipt has no unique persisted state")
    state = matching_states[0]
    if (
        state.witness_id != receipt.witness_id
        or state.origin != receipt.origin
        or state.tree_size != receipt.tree_size
        or not hmac.compare_digest(state.root_hash, receipt.root_hash)
        or not hmac.compare_digest(state.checkpoint_digest, receipt.checkpoint_digest)
    ):
        raise TransparencyDenied("witness persisted state mismatched")
    if policy.max_staleness_seconds:
        accepted = accepted_at or datetime.now(timezone.utc)
        receipt_time = datetime.fromisoformat(receipt.issued_at[:-1] + "+00:00")
        age = (accepted - receipt_time).total_seconds()
        if age < 0 or age > policy.max_staleness_seconds:
            raise TransparencyDenied("witness receipt is stale")
    return receipt


def verify_witness_quorum(
    *,
    log_snapshot: Snapshot,
    log_protocol: TransparencyProtocol,
    log_signing_protocol: SigningAuthorityProtocol,
    log_provider: SigningAuthorityProvider,
    log_descriptor_root: str,
    log_root: str,
    checkpoint_root: str,
    policy_root: str,
    evidence: Iterable[WitnessReceiptEvidence],
    accepted_at: datetime | None = None,
) -> tuple[WitnessReceiptProjection, ...]:
    policy = read_witness_policy(log_snapshot, log_protocol, policy_root)
    checkpoint = verify_transparency_checkpoint(
        log_snapshot,
        log_protocol,
        log_signing_protocol,
        log_provider,
        log_descriptor_root,
        log_root,
        checkpoint_root,
        expected_policy_root=policy.root_id,
        expected_policy_digest=policy.digest,
    )
    receipts: list[WitnessReceiptProjection] = []
    seen: set[str] = set()
    for item in evidence:
        receipt = verify_witness_receipt(
            log_snapshot=log_snapshot,
            log_protocol=log_protocol,
            checkpoint=checkpoint,
            policy=policy,
            evidence=item,
            accepted_at=accepted_at,
        )
        if receipt.witness_id in seen:
            raise TransparencyDenied("witness quorum contains a duplicate witness")
        seen.add(receipt.witness_id)
        receipts.append(receipt)
    if len(receipts) < policy.threshold:
        raise TransparencyDenied("witness quorum threshold is not satisfied")
    return tuple(receipts)


__all__ = [
    "CHECKPOINT_CONTEXT",
    "CHECKPOINT_PROTOCOL",
    "CHECKPOINT_SIGNING_PURPOSE",
    "CHECKPOINT_STATEMENT_PROTOCOL",
    "ConsistencyProofProjection",
    "LEAF_PROTOCOL",
    "LOG_PROTOCOL",
    "MerkleHead",
    "PROOF_PROTOCOL",
    "TransparencyCheckpointProjection",
    "TransparencyDenied",
    "TransparencyLeafProjection",
    "TransparencyLogProjection",
    "TransparencyProtocol",
    "GraphWitnessService",
    "WITNESS_ADMISSION_PROTOCOL",
    "WITNESS_CONTEXT",
    "WITNESS_POLICY_PROTOCOL",
    "WITNESS_RECEIPT_PROTOCOL",
    "WITNESS_SIGNING_PURPOSE",
    "WITNESS_STATE_LOG_PROTOCOL",
    "WITNESS_STATE_PROTOCOL",
    "WITNESS_STATEMENT_PROTOCOL",
    "WitnessAdmission",
    "WitnessPolicyProjection",
    "WitnessReceiptEvidence",
    "WitnessReceiptProjection",
    "WitnessStateProjection",
    "append_transparency_leaf",
    "bootstrap_transparency_protocol",
    "build_transparency_log",
    "build_log_consistency_proof",
    "build_witness_policy",
    "build_witness_state_log",
    "consistency_proof",
    "inclusion_proof",
    "issue_transparency_checkpoint",
    "merkle_head",
    "merkle_tree_hash",
    "project_transparency_protocol",
    "read_consistency_proof",
    "read_log_leaves",
    "read_transparency_checkpoint",
    "read_transparency_leaf",
    "read_transparency_log",
    "read_witness_policy",
    "read_witness_receipt",
    "read_witness_state",
    "latest_witness_state",
    "verify_consistency_proof",
    "verify_inclusion_proof",
    "verify_transparency_checkpoint",
    "verify_witness_quorum",
    "verify_witness_receipt",
]
