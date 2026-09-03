"""Content-addressed subject descriptors composed from universal Cells.

Descriptors are closed relations whose fields are terminal values. They name a
subject without linking transitively into its mutable graph. Callers resolve
the subject identity and supply the canonical bytes that the descriptor pins.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import re
from types import MappingProxyType
from typing import Mapping

from .cell_protocols import CellBatch, compose_relation_cells, read_relation
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


ROLE_NAMES = (
    "vocabulary-member",
    "subject-id",
    "media-type",
    "digest-algorithm",
    "digest",
    "size",
)
SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class ContentDescriptorProtocol:
    root_id: str
    roles: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown content descriptor role %r" % name) from exc


@dataclass(frozen=True, slots=True)
class ContentDescriptorBuild:
    root_id: str
    cells: tuple[Cell, ...]


@dataclass(frozen=True, slots=True)
class ContentDescriptorProjection:
    root_id: str
    subject_root: str
    media_type: str
    digest_algorithm: str
    digest: str
    size: int


def _terminal(root_id: str, value: str) -> Cell:
    try:
        atom = value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise InvalidCell("content descriptor values must be ASCII") from exc
    if not atom:
        raise InvalidCell("content descriptor values cannot be empty")
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, atom)


def bootstrap_content_descriptor_protocol(
    store: CellStore, *, prefix: str = "content-descriptor-protocol"
) -> ContentDescriptorProtocol:
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    root_id = prefix + ":root"
    batch = CellBatch(store)
    for name, role_root in roles.items():
        batch.add(_terminal(role_root, name))
    batch.relation(
        ((roles["vocabulary-member"], root) for root in roles.values()),
        relation_id=root_id,
    )
    batch.commit()
    return ContentDescriptorProtocol(root_id, MappingProxyType(roles))


def project_content_descriptor_protocol(
    snapshot: Snapshot, *, prefix: str = "content-descriptor-protocol"
) -> ContentDescriptorProtocol:
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    root_id = prefix + ":root"
    if any(root not in snapshot.cells for root in (root_id, *roles.values())):
        raise InvalidCell("content descriptor protocol is incomplete")
    members = read_relation(snapshot, root_id, budget=128)
    declared = tuple(
        member.participant_id for member in members
        if member.role_id == roles["vocabulary-member"]
    )
    if len(declared) != len(set(declared)) or set(declared) != set(roles.values()):
        raise InvalidCell("content descriptor vocabulary drifted")
    return ContentDescriptorProtocol(root_id, MappingProxyType(roles))


def content_identity_bytes(*fields: bytes | str) -> bytes:
    """Return a stable length-framed identity statement for a released subject."""
    result = bytearray(b"ArchHub/content-identity/v1\x00")
    for field in fields:
        raw = field.encode("utf-8") if isinstance(field, str) else bytes(field)
        result.extend(len(raw).to_bytes(8, "big"))
        result.extend(raw)
    return bytes(result)


def compose_content_descriptor(
    snapshot: Snapshot,
    protocol: ContentDescriptorProtocol,
    *,
    descriptor_id: str,
    subject_root: str,
    media_type: str,
    content: bytes,
) -> ContentDescriptorBuild:
    """Compose, but do not commit, one closed content descriptor relation."""
    if descriptor_id in snapshot.cells:
        raise InvalidCell("content descriptor root already exists")
    if subject_root not in snapshot.cells:
        raise InvalidCell("content descriptor subject is missing")
    if not content:
        raise InvalidCell("content descriptor canonical subject cannot be empty")
    try:
        subject_root.encode("ascii")
        media_type.encode("ascii")
    except UnicodeEncodeError as exc:
        raise InvalidCell("content descriptor identity must be ASCII") from exc
    digest = "sha256:" + hashlib.sha256(content).hexdigest()
    scalar_values = {
        "subject-id": subject_root,
        "media-type": media_type,
        "digest-algorithm": "sha256",
        "digest": digest,
        "size": str(len(content)),
    }
    scalar_cells = tuple(
        _terminal(descriptor_id + ":" + name, value)
        for name, value in scalar_values.items()
    )
    scalar_roots = {
        name: descriptor_id + ":" + name for name in scalar_values
    }
    relation = compose_relation_cells(
        (
            (protocol.role(name), scalar_roots[name])
            for name in scalar_values
        ),
        relation_id=descriptor_id,
    )
    return ContentDescriptorBuild(
        descriptor_id, (*scalar_cells, *relation.cells)
    )


def build_content_descriptor(
    store: CellStore,
    protocol: ContentDescriptorProtocol,
    *,
    descriptor_id: str,
    subject_root: str,
    media_type: str,
    content: bytes,
) -> str:
    built = compose_content_descriptor(
        store.snapshot(),
        protocol,
        descriptor_id=descriptor_id,
        subject_root=subject_root,
        media_type=media_type,
        content=content,
    )
    store.commit(store.revision, create=built.cells)
    return built.root_id


def _one(members, role_id: str, label: str) -> str:
    roots = tuple(
        member.participant_id for member in members
        if member.role_id == role_id
    )
    if len(roots) != 1:
        raise InvalidCell("content descriptor requires exactly one %s" % label)
    return roots[0]


def read_content_descriptor(
    snapshot: Snapshot,
    protocol: ContentDescriptorProtocol,
    descriptor_root: str,
) -> ContentDescriptorProjection:
    members = read_relation(snapshot, descriptor_root, budget=64)
    field_names = ROLE_NAMES[1:]
    allowed = {protocol.role(name) for name in field_names}
    if any(member.role_id not in allowed for member in members):
        raise InvalidCell("content descriptor contains an undeclared field")
    roots = {
        name: _one(members, protocol.role(name), name)
        for name in field_names
    }
    values: dict[str, str] = {}
    for name, root in roots.items():
        try:
            cell = snapshot.cells[root]
        except KeyError as exc:
            raise InvalidCell("content descriptor field is missing") from exc
        if cell.link0 != NULL_CELL_ID or cell.link1 != NULL_CELL_ID:
            raise InvalidCell("content descriptor fields must be terminal")
        try:
            values[name] = cell.atom.decode("ascii")
        except UnicodeDecodeError as exc:
            raise InvalidCell("content descriptor fields must be ASCII") from exc
        if not values[name]:
            raise InvalidCell("content descriptor fields cannot be empty")
    if values["digest-algorithm"] != "sha256":
        raise InvalidCell("content descriptor digest algorithm is unsupported")
    if not SHA256_PATTERN.fullmatch(values["digest"]):
        raise InvalidCell("content descriptor digest is invalid")
    try:
        size = int(values["size"])
    except ValueError as exc:
        raise InvalidCell("content descriptor size is invalid") from exc
    if size < 1:
        raise InvalidCell("content descriptor size is invalid")
    return ContentDescriptorProjection(
        descriptor_root,
        values["subject-id"],
        values["media-type"],
        values["digest-algorithm"],
        values["digest"],
        size,
    )


def verify_content_descriptor(
    snapshot: Snapshot,
    protocol: ContentDescriptorProtocol,
    descriptor_root: str,
    *,
    content: bytes,
    expected_subject_root: str | None = None,
    expected_media_type: str | None = None,
) -> ContentDescriptorProjection:
    descriptor = read_content_descriptor(snapshot, protocol, descriptor_root)
    if descriptor.subject_root not in snapshot.cells:
        raise InvalidCell("content descriptor subject is missing")
    if (
        expected_subject_root is not None
        and descriptor.subject_root != expected_subject_root
    ):
        raise InvalidCell("content descriptor subject mismatched")
    if expected_media_type is not None and descriptor.media_type != expected_media_type:
        raise InvalidCell("content descriptor media type mismatched")
    if len(content) != descriptor.size:
        raise InvalidCell("content descriptor size mismatched")
    actual = "sha256:" + hashlib.sha256(content).hexdigest()
    if not hmac.compare_digest(descriptor.digest, actual):
        raise InvalidCell("content descriptor digest mismatched")
    return descriptor


__all__ = [
    "ContentDescriptorBuild",
    "ContentDescriptorProjection",
    "ContentDescriptorProtocol",
    "bootstrap_content_descriptor_protocol",
    "build_content_descriptor",
    "compose_content_descriptor",
    "content_identity_bytes",
    "project_content_descriptor_protocol",
    "read_content_descriptor",
    "verify_content_descriptor",
]
