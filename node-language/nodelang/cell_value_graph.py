"""Universal structured values as openable Cell relations, never JSON atoms."""
from __future__ import annotations

from dataclasses import dataclass
import math
from types import MappingProxyType
from typing import Mapping
from urllib.parse import quote

from .cell_protocols import (
    compose_relation_cells,
    prepare_append_relation_member,
    prepare_append_relation_members,
    read_relation,
)
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


ROLE_NAMES = (
    "value-member", "variant", "content", "entry-member", "key", "value",
    "index",
)
VARIANT_NAMES = ("null", "boolean", "integer", "number", "text", "bytes", "object", "array")
MAX_DEPTH = 64
MAX_VALUE_NODES = 10_000
MAX_SCALAR_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class ValueGraphProtocol:
    root_id: str
    roles: Mapping[str, str]
    variants: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown value-graph role %r" % name) from exc

    def variant(self, name: str) -> str:
        try:
            return self.variants[name]
        except KeyError as exc:
            raise InvalidCell("unknown value-graph variant %r" % name) from exc


@dataclass(frozen=True, slots=True)
class PreparedValueGraph:
    """One validated value graph, ready to join an enclosing atomic commit."""

    root_id: str
    create: tuple[Cell, ...]
    replace: tuple[Cell, ...]


def _terminal(root_id: str, value: str | bytes) -> Cell:
    atom = value if type(value) is bytes else value.encode("utf-8")
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, atom)


def bootstrap_value_graph_protocol(
    store: CellStore, *, prefix: str = "value-graph-protocol"
) -> ValueGraphProtocol:
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    variants = {
        name: "%s:variant:%s" % (prefix, name) for name in VARIANT_NAMES
    }
    root_id = prefix + ":root"
    relation = compose_relation_cells(
        tuple((roles["variant"], root) for root in variants.values()),
        relation_id=root_id,
    )
    store.commit(
        store.revision,
        create=(
            *(_terminal(root, name) for name, root in roles.items()),
            *(_terminal(root, name) for name, root in variants.items()),
            *relation.cells,
        ),
    )
    return ValueGraphProtocol(
        root_id, MappingProxyType(roles), MappingProxyType(variants)
    )


def project_value_graph_protocol(
    snapshot: Snapshot, *, prefix: str = "value-graph-protocol"
) -> ValueGraphProtocol:
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    variants = {
        name: "%s:variant:%s" % (prefix, name) for name in VARIANT_NAMES
    }
    root_id = prefix + ":root"
    required = (root_id, *roles.values(), *variants.values())
    if any(root not in snapshot.cells for root in required):
        raise InvalidCell("value-graph protocol is incomplete")
    members = read_relation(snapshot, root_id, budget=100_000)
    declared_variants = tuple(
        (member.role_id, member.participant_id) for member in members
        if member.role_id == roles["variant"]
    )
    if (
        sorted(declared_variants) != sorted(
            (roles["variant"], root) for root in variants.values()
        )
        or any(
            member.role_id not in {roles["variant"], roles["value-member"]}
            for member in members
        )
    ):
        raise InvalidCell("value-graph protocol vocabulary drifted")
    return ValueGraphProtocol(
        root_id, MappingProxyType(roles), MappingProxyType(variants)
    )


def _part(value: object) -> str:
    return quote(str(value), safe="")


def _scalar_variant(value: object) -> tuple[str, bytes]:
    if value is None:
        return "null", b""
    if type(value) is bool:
        return "boolean", b"true" if value else b"false"
    if type(value) is int:
        return "integer", str(value).encode("ascii")
    if type(value) is float:
        if not math.isfinite(value):
            raise InvalidCell("value-graph numbers must be finite")
        return "number", repr(value).encode("ascii")
    if type(value) is str:
        return "text", value.encode("utf-8")
    if type(value) is bytes:
        return "bytes", value
    raise InvalidCell("value-graph scalar type is not admitted")


class _Builder:
    def __init__(self, protocol: ValueGraphProtocol) -> None:
        self.protocol = protocol
        self.cells: dict[str, Cell] = {}
        self.value_roots: list[str] = []

    def add(self, cell: Cell) -> None:
        previous = self.cells.get(cell.id)
        if previous is not None and previous != cell:
            raise InvalidCell("value-graph identity collision")
        self.cells[cell.id] = cell
        if len(self.cells) > MAX_VALUE_NODES:
            raise InvalidCell("value-graph exceeds its node budget")

    def relation(self, root_id: str, members) -> None:
        relation = compose_relation_cells(tuple(members), relation_id=root_id)
        for cell in relation.cells:
            self.add(cell)

    def build(self, root_id: str, value: object, depth: int = 0) -> None:
        if depth > MAX_DEPTH:
            raise InvalidCell("value-graph exceeds its depth budget")
        if type(value) is dict:
            if any(type(key) is not str for key in value):
                raise InvalidCell("value-graph object keys must be text")
            entries = []
            for index, key in enumerate(sorted(value)):
                entry_root = "%s:entry:%s" % (root_id, _part(key))
                key_root = entry_root + ":key"
                value_root = entry_root + ":value"
                index_root = entry_root + ":index"
                self.build(key_root, key, depth + 1)
                self.build(value_root, value[key], depth + 1)
                self.build(index_root, index, depth + 1)
                self.relation(entry_root, (
                    (self.protocol.role("key"), key_root),
                    (self.protocol.role("value"), value_root),
                    (self.protocol.role("index"), index_root),
                ))
                entries.append((self.protocol.role("entry-member"), entry_root))
            self.relation(root_id, (
                (self.protocol.role("variant"), self.protocol.variant("object")),
                *entries,
            ))
        elif type(value) in (list, tuple):
            entries = []
            for index, item in enumerate(value):
                entry_root = "%s:entry:%s" % (root_id, index)
                index_root = entry_root + ":index"
                value_root = entry_root + ":value"
                self.build(index_root, index, depth + 1)
                self.build(value_root, item, depth + 1)
                self.relation(entry_root, (
                    (self.protocol.role("index"), index_root),
                    (self.protocol.role("value"), value_root),
                ))
                entries.append((self.protocol.role("entry-member"), entry_root))
            self.relation(root_id, (
                (self.protocol.role("variant"), self.protocol.variant("array")),
                *entries,
            ))
        else:
            variant, atom = _scalar_variant(value)
            if len(atom) > MAX_SCALAR_BYTES:
                raise InvalidCell(
                    "value-graph scalar exceeds its inline byte budget; use a blob reference"
                )
            content_root = root_id + ":content"
            self.add(_terminal(content_root, atom))
            self.relation(root_id, (
                (self.protocol.role("variant"), self.protocol.variant(variant)),
                (self.protocol.role("content"), content_root),
            ))
        self.value_roots.append(root_id)


def build_value_graph(
    store: CellStore,
    protocol: ValueGraphProtocol,
    value: object,
    *,
    root_id: str,
) -> tuple[str, int]:
    """Commit one deterministic structured value and register its root."""
    snapshot = store.snapshot()
    prepared = prepare_value_graph(snapshot, protocol, value, root_id=root_id)
    revision = store.commit(
        snapshot.revision,
        create=prepared.create,
        replace=prepared.replace,
    )
    read_value_graph(store.snapshot(), protocol, root_id)
    return root_id, revision


def prepare_value_graph(
    snapshot: Snapshot,
    protocol: ValueGraphProtocol,
    value: object,
    *,
    root_id: str,
) -> PreparedValueGraph:
    """Prepare a deterministic value graph without making it authoritative yet.

    The caller can combine this patch with another graph composition in one
    ``CellStore.commit``.  This prevents a ledger reference from ever pointing
    at a payload that was committed separately or not committed at all.
    """
    if type(root_id) is not str or not root_id:
        raise InvalidCell("value-graph root identity is invalid")
    if root_id in snapshot.cells:
        raise InvalidCell("value-graph root already exists")
    builder = _Builder(protocol)
    builder.build(root_id, value)
    if set(builder.cells) & set(snapshot.cells):
        raise InvalidCell("value-graph would overwrite an existing Cell")
    patch = prepare_append_relation_member(
        snapshot,
        protocol.root_id,
        protocol.role("value-member"),
        root_id,
        budget=100_000,
    )
    return PreparedValueGraph(
        root_id=root_id,
        create=tuple((*builder.cells.values(), *patch.create)),
        replace=tuple(patch.replace),
    )


def build_value_graphs(
    store: CellStore,
    protocol: ValueGraphProtocol,
    values_by_root: Mapping[str, object],
) -> tuple[tuple[str, ...], int]:
    """Commit deterministic structured values and register all roots together."""
    if not values_by_root:
        raise InvalidCell("value-graph batch requires at least one root")
    roots = tuple(values_by_root)
    if any(type(root_id) is not str or not root_id for root_id in roots):
        raise InvalidCell("value-graph root identity is invalid")
    if len(roots) != len(set(roots)):
        raise InvalidCell("value-graph batch contains duplicate roots")
    snapshot = store.snapshot()
    if any(root_id in snapshot.cells for root_id in roots):
        raise InvalidCell("value-graph root already exists")
    builder = _Builder(protocol)
    for root_id in roots:
        builder.build(root_id, values_by_root[root_id])
    if set(builder.cells) & set(snapshot.cells):
        raise InvalidCell("value-graph would overwrite an existing Cell")
    patch = prepare_append_relation_members(
        snapshot,
        protocol.root_id,
        (
            (protocol.role("value-member"), root_id)
            for root_id in roots
        ),
        budget=100_000,
    )
    revision = store.commit(
        snapshot.revision,
        create=(*builder.cells.values(), *patch.create),
        replace=patch.replace,
    )
    committed = store.snapshot()
    for root_id in roots:
        read_value_graph(committed, protocol, root_id)
    return roots, revision


def _one(members, role_id: str, label: str) -> str:
    roots = tuple(
        member.participant_id for member in members if member.role_id == role_id
    )
    if len(roots) != 1:
        raise InvalidCell("value-graph requires one %s" % label)
    return roots[0]


def read_value_graph(
    snapshot: Snapshot,
    protocol: ValueGraphProtocol,
    root_id: str,
    *,
    max_depth: int = MAX_DEPTH,
) -> object:
    """Validate and project one registered value graph."""
    registered = tuple(
        member.participant_id
        for member in read_relation(snapshot, protocol.root_id, budget=100_000)
        if member.role_id == protocol.role("value-member")
    )
    if registered.count(root_id) != 1:
        raise InvalidCell("value-graph root is not registered exactly once")
    seen: set[str] = set()

    def read(root: str, depth: int) -> object:
        if depth > max_depth:
            raise InvalidCell("value-graph exceeds its read depth budget")
        if root in seen:
            raise InvalidCell("value-graph contains a cycle")
        seen.add(root)
        if len(seen) > MAX_VALUE_NODES:
            raise InvalidCell("value-graph exceeds its read node budget")
        members = read_relation(snapshot, root, budget=MAX_VALUE_NODES)
        variant_root = _one(members, protocol.role("variant"), "variant")
        variants = {
            value: name for name, value in protocol.variants.items()
        }
        try:
            variant = variants[variant_root]
        except KeyError as exc:
            raise InvalidCell("value-graph variant is outside the protocol") from exc
        allowed = {protocol.role("variant")}
        if variant in {"object", "array"}:
            allowed.add(protocol.role("entry-member"))
        else:
            allowed.add(protocol.role("content"))
        if any(member.role_id not in allowed for member in members):
            raise InvalidCell("value-graph node contains an undeclared role")
        if variant in {"object", "array"}:
            entries = tuple(
                member.participant_id for member in members
                if member.role_id == protocol.role("entry-member")
            )
            projected = []
            for entry_root in entries:
                entry = read_relation(snapshot, entry_root, budget=64)
                entry_allowed = {
                    protocol.role("key"), protocol.role("value"),
                    protocol.role("index"),
                }
                if any(member.role_id not in entry_allowed for member in entry):
                    raise InvalidCell("value-graph entry contains an undeclared role")
                index_root = _one(entry, protocol.role("index"), "entry index")
                index = read(index_root, depth + 1)
                if type(index) is not int:
                    raise InvalidCell("value-graph entry index is not an integer")
                value_root = _one(entry, protocol.role("value"), "entry value")
                if variant == "object":
                    key_root = _one(entry, protocol.role("key"), "entry key")
                    key = read(key_root, depth + 1)
                    if type(key) is not str:
                        raise InvalidCell("value-graph entry key is not text")
                else:
                    if any(
                        member.role_id == protocol.role("key") for member in entry
                    ):
                        raise InvalidCell("value-graph array entry has a key")
                    key = None
                projected.append((index, key, read(value_root, depth + 1)))
            projected.sort(key=lambda item: item[0])
            if [item[0] for item in projected] != list(range(len(projected))):
                raise InvalidCell("value-graph entry indexes are not contiguous")
            if variant == "array":
                return [item[2] for item in projected]
            result = {}
            for _index, key, value in projected:
                if key in result:
                    raise InvalidCell("value-graph object key is duplicated")
                result[key] = value
            return result
        content_root = _one(members, protocol.role("content"), "content")
        try:
            content = snapshot.cells[content_root]
        except KeyError as exc:
            raise InvalidCell("value-graph content is missing") from exc
        if content.link0 != NULL_CELL_ID or content.link1 != NULL_CELL_ID:
            raise InvalidCell("value-graph scalar content is not terminal")
        atom = content.atom
        try:
            if variant == "null":
                if atom:
                    raise InvalidCell("value-graph null content is not empty")
                return None
            if variant == "boolean":
                if atom not in (b"true", b"false"):
                    raise InvalidCell("value-graph boolean content is invalid")
                return atom == b"true"
            if variant == "integer":
                return int(atom.decode("ascii"))
            if variant == "number":
                value = float(atom.decode("ascii"))
                if not math.isfinite(value):
                    raise InvalidCell("value-graph number is not finite")
                return value
            if variant == "text":
                return atom.decode("utf-8")
            if variant == "bytes":
                return bytes(atom)
        except (UnicodeError, ValueError) as exc:
            raise InvalidCell("value-graph scalar content is invalid") from exc
        raise InvalidCell("value-graph scalar variant is invalid")

    return read(root_id, 0)


__all__ = [
    "MAX_DEPTH", "MAX_SCALAR_BYTES", "MAX_VALUE_NODES", "ROLE_NAMES",
    "VARIANT_NAMES", "PreparedValueGraph", "ValueGraphProtocol",
    "bootstrap_value_graph_protocol",
    "build_value_graph", "build_value_graphs", "project_value_graph_protocol",
    "prepare_value_graph", "read_value_graph",
]
