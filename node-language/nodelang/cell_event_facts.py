"""Released graph contracts for bounded observations from a device adapter.

An event fact is data, never authority.  The browser may measure a value named
by a released fact specification; the Interaction graph still decides whether
that value is admitted and what capability can consume it.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import math
from types import MappingProxyType
from typing import Iterable, Mapping

from .cell_protocols import (
    CellBatch,
    prepare_append_relation_members,
    read_relation,
)
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


ROLE_NAMES = (
    "vocabulary-member",
    "key",
    "source",
    "value-kind",
    "requirement",
    "minimum",
    "maximum",
    "maximum-bytes",
    "lifecycle",
    "digest",
)
STATE_NAMES = ("draft", "released")
SOURCE_NAMES = (
    "canvas-point-x",
    "canvas-point-y",
    "canvas-viewport-pan-x",
    "canvas-viewport-pan-y",
    "canvas-viewport-zoom",
    "relation-participant-index",
    "topology-candidate-index",
    "submitted",
)
VALUE_KIND_NAMES = ("number", "text")
REQUIREMENT_NAMES = ("required", "optional")


@dataclass(frozen=True, slots=True)
class EventFactProtocol:
    root_id: str
    roles: Mapping[str, str]
    states: Mapping[str, str]
    sources: Mapping[str, str]
    value_kinds: Mapping[str, str]
    requirements: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown event-fact role %r" % name) from exc


@dataclass(frozen=True, slots=True)
class EventFactSpec:
    root_id: str
    key: str
    source: str
    value_kind: str
    required: bool
    minimum: float | None
    maximum: float | None
    maximum_bytes: int | None
    lifecycle_root: str
    lifecycle_incidence_id: str
    digest_root: str


def _leaf(batch: CellBatch, root_id: str, atom: str | bytes) -> str:
    encoded = atom if isinstance(atom, bytes) else atom.encode("utf-8")
    batch.add(Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, encoded))
    return root_id


def _terminal(snapshot: Snapshot, root_id: str, label: str) -> Cell:
    try:
        cell = snapshot.cells[root_id]
    except KeyError as exc:
        raise InvalidCell("%s is missing" % label) from exc
    if cell.link0 != NULL_CELL_ID or cell.link1 != NULL_CELL_ID:
        raise InvalidCell("%s is not terminal" % label)
    return cell


def _text(snapshot: Snapshot, root_id: str, label: str) -> str:
    try:
        return _terminal(snapshot, root_id, label).atom.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidCell("%s is not UTF-8" % label) from exc


def _single(members, role_id: str, label: str) -> tuple[str, str]:
    matches = tuple(member for member in members if member.role_id == role_id)
    if len(matches) != 1:
        raise InvalidCell("event fact requires exactly one %s" % label)
    return matches[0].participant_id, matches[0].incidence_id


def _optional(members, role_id: str, label: str) -> tuple[str, str] | None:
    matches = tuple(member for member in members if member.role_id == role_id)
    if len(matches) > 1:
        raise InvalidCell("event fact repeats %s" % label)
    if not matches:
        return None
    return matches[0].participant_id, matches[0].incidence_id


def bootstrap_event_fact_protocol(
    store: CellStore,
    *,
    prefix: str = "event-fact-protocol",
) -> EventFactProtocol:
    root_id = prefix + ":root"
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    states = {name: "%s:state:%s" % (prefix, name) for name in STATE_NAMES}
    sources = {name: "%s:source:%s" % (prefix, name) for name in SOURCE_NAMES}
    value_kinds = {
        name: "%s:value-kind:%s" % (prefix, name)
        for name in VALUE_KIND_NAMES
    }
    requirements = {
        name: "%s:requirement:%s" % (prefix, name)
        for name in REQUIREMENT_NAMES
    }
    vocabulary = (
        *roles.values(), *states.values(), *sources.values(),
        *value_kinds.values(), *requirements.values(),
    )
    snapshot = store.snapshot()
    if root_id not in snapshot.cells:
        batch = CellBatch(store)
        for root in vocabulary:
            _leaf(batch, root, root.rsplit(":", 1)[-1])
        batch.relation(
            ((roles["vocabulary-member"], root) for root in vocabulary),
            relation_id=root_id,
        )
        batch.commit()
    else:
        members = read_relation(snapshot, root_id, budget=256)
        existing = {member.participant_id for member in members}
        missing = tuple(root for root in vocabulary if root not in existing)
        if missing:
            if any(
                member.role_id != roles["vocabulary-member"]
                for member in members
            ):
                raise InvalidCell("event-fact protocol vocabulary drifted")
            leaves = tuple(
                Cell(
                    root,
                    NULL_CELL_ID,
                    NULL_CELL_ID,
                    root.rsplit(":", 1)[-1].encode("utf-8"),
                )
                for root in missing
                if root not in snapshot.cells
            )
            patch = prepare_append_relation_members(
                snapshot,
                root_id,
                tuple((roles["vocabulary-member"], root) for root in missing),
                budget=256,
            )
            store.commit(
                snapshot.revision,
                create=(*leaves, *patch.create),
                replace=patch.replace,
            )
    protocol = EventFactProtocol(
        root_id,
        MappingProxyType(roles),
        MappingProxyType(states),
        MappingProxyType(sources),
        MappingProxyType(value_kinds),
        MappingProxyType(requirements),
    )
    project_event_fact_protocol(store.snapshot(), protocol)
    return protocol


def project_event_fact_protocol(
    snapshot: Snapshot,
    protocol: EventFactProtocol,
) -> EventFactProtocol:
    expected = {
        *protocol.roles.values(), *protocol.states.values(),
        *protocol.sources.values(), *protocol.value_kinds.values(),
        *protocol.requirements.values(),
    }
    members = read_relation(snapshot, protocol.root_id, budget=256)
    if (
        len(members) != len(expected)
        or {member.participant_id for member in members} != expected
        or any(
            member.role_id != protocol.roles["vocabulary-member"]
            for member in members
        )
    ):
        raise InvalidCell("event-fact protocol vocabulary drifted")
    for root in expected:
        if _text(snapshot, root, "event-fact vocabulary") != root.rsplit(":", 1)[-1]:
            raise InvalidCell("event-fact protocol vocabulary atom drifted")
    return protocol


def _digest_fields(fields: Iterable[bytes]) -> bytes:
    digest = hashlib.sha256()
    for field in fields:
        digest.update(len(field).to_bytes(8, "big"))
        digest.update(field)
    return digest.digest()


def _spec_digest(spec: EventFactSpec) -> bytes:
    fields = [
        spec.root_id.encode(),
        spec.key.encode(),
        spec.source.encode(),
        spec.value_kind.encode(),
        b"1" if spec.required else b"0",
    ]
    if spec.minimum is not None:
        fields.extend((
            format(spec.minimum, ".17g").encode(),
            format(spec.maximum, ".17g").encode(),
        ))
    if spec.maximum_bytes is not None:
        fields.append(str(spec.maximum_bytes).encode())
    fields.append(
        spec.lifecycle_root.encode(),
    )
    return _digest_fields(fields)


def read_event_fact_spec(
    snapshot: Snapshot,
    protocol: EventFactProtocol,
    spec_root: str,
    *,
    require_released: bool = True,
) -> EventFactSpec:
    project_event_fact_protocol(snapshot, protocol)
    members = read_relation(snapshot, spec_root, budget=128)
    allowed = {
        protocol.role("key"), protocol.role("source"),
        protocol.role("value-kind"), protocol.role("requirement"),
        protocol.role("minimum"), protocol.role("maximum"),
        protocol.role("maximum-bytes"),
        protocol.role("lifecycle"), protocol.role("digest"),
    }
    if any(member.role_id not in allowed for member in members):
        raise InvalidCell("event fact contains an undeclared role")
    key_root, _ = _single(members, protocol.role("key"), "key")
    source_root, _ = _single(members, protocol.role("source"), "source")
    kind_root, _ = _single(members, protocol.role("value-kind"), "value kind")
    requirement_root, _ = _single(
        members, protocol.role("requirement"), "requirement"
    )
    minimum_member = _optional(
        members, protocol.role("minimum"), "minimum"
    )
    maximum_member = _optional(
        members, protocol.role("maximum"), "maximum"
    )
    maximum_bytes_member = _optional(
        members, protocol.role("maximum-bytes"), "maximum bytes"
    )
    lifecycle_root, lifecycle_incidence = _single(
        members, protocol.role("lifecycle"), "lifecycle"
    )
    digest_root, _ = _single(members, protocol.role("digest"), "digest")
    if source_root not in protocol.sources.values():
        raise InvalidCell("event-fact source is not admitted")
    if kind_root not in protocol.value_kinds.values():
        raise InvalidCell("event-fact value kind is not admitted")
    if requirement_root not in protocol.requirements.values():
        raise InvalidCell("event-fact requirement is not admitted")
    if lifecycle_root not in protocol.states.values():
        raise InvalidCell("event-fact lifecycle is not admitted")
    value_kind = _text(snapshot, kind_root, "event-fact value kind")
    minimum = maximum = None
    maximum_bytes = None
    if value_kind == "number":
        if minimum_member is None or maximum_member is None:
            raise InvalidCell("numeric event fact requires finite bounds")
        if maximum_bytes_member is not None:
            raise InvalidCell("numeric event fact cannot have a byte bound")
        try:
            minimum = float(_text(
                snapshot, minimum_member[0], "event-fact minimum"
            ))
            maximum = float(_text(
                snapshot, maximum_member[0], "event-fact maximum"
            ))
        except ValueError as exc:
            raise InvalidCell("event-fact numeric boundary is invalid") from exc
        if (
            not math.isfinite(minimum)
            or not math.isfinite(maximum)
            or minimum > maximum
        ):
            raise InvalidCell("event-fact numeric boundaries are invalid")
    elif value_kind == "text":
        if minimum_member is not None or maximum_member is not None:
            raise InvalidCell("text event fact cannot have numeric bounds")
        if maximum_bytes_member is None:
            raise InvalidCell("text event fact requires a byte bound")
        try:
            maximum_bytes = int(_text(
                snapshot,
                maximum_bytes_member[0],
                "event-fact maximum bytes",
            ))
        except ValueError as exc:
            raise InvalidCell("event-fact byte bound is invalid") from exc
        if maximum_bytes < 0:
            raise InvalidCell("event-fact byte bound cannot be negative")
    else:
        raise InvalidCell("event-fact value kind is not admitted")
    spec = EventFactSpec(
        spec_root,
        _text(snapshot, key_root, "event-fact key"),
        _text(snapshot, source_root, "event-fact source"),
        value_kind,
        requirement_root == protocol.requirements["required"],
        minimum,
        maximum,
        maximum_bytes,
        lifecycle_root,
        lifecycle_incidence,
        digest_root,
    )
    if require_released:
        if spec.lifecycle_root != protocol.states["released"]:
            raise InvalidCell("event-fact specification is not released")
        if not hmac.compare_digest(
            _terminal(snapshot, spec.digest_root, "event-fact digest").atom,
            _spec_digest(spec),
        ):
            raise InvalidCell("event-fact specification digest drifted")
    return spec


def build_event_fact_spec(
    store: CellStore,
    protocol: EventFactProtocol,
    *,
    spec_id: str,
    key: str,
    source: str,
    value_kind: str = "number",
    minimum: float | None = None,
    maximum: float | None = None,
    maximum_bytes: int | None = None,
    required: bool = True,
    released: bool = True,
) -> EventFactSpec:
    if (
        source not in protocol.sources
        or value_kind not in protocol.value_kinds
        or not key
    ):
        raise InvalidCell("event-fact specification identity is invalid")
    if value_kind == "number":
        if (
            minimum is None
            or maximum is None
            or maximum_bytes is not None
            or not math.isfinite(minimum)
            or not math.isfinite(maximum)
            or minimum > maximum
        ):
            raise InvalidCell("event-fact specification boundaries are invalid")
    elif value_kind == "text":
        if (
            minimum is not None
            or maximum is not None
            or type(maximum_bytes) is not int
            or maximum_bytes < 0
        ):
            raise InvalidCell("event-fact specification byte bound is invalid")
    else:
        raise InvalidCell("event-fact specification value kind is invalid")
    batch = CellBatch(store)
    key_root = _leaf(batch, spec_id + ":key", key)
    digest_root = _leaf(batch, spec_id + ":digest", b"")
    bounds = []
    if value_kind == "number":
        minimum_root = _leaf(
            batch, spec_id + ":minimum", format(minimum, ".17g")
        )
        maximum_root = _leaf(
            batch, spec_id + ":maximum", format(maximum, ".17g")
        )
        bounds.extend((
            (protocol.role("minimum"), minimum_root),
            (protocol.role("maximum"), maximum_root),
        ))
    else:
        maximum_bytes_root = _leaf(
            batch, spec_id + ":maximum-bytes", str(maximum_bytes)
        )
        bounds.append((
            protocol.role("maximum-bytes"), maximum_bytes_root
        ))
    batch.relation((
        (protocol.role("key"), key_root),
        (protocol.role("source"), protocol.sources[source]),
        (protocol.role("value-kind"), protocol.value_kinds[value_kind]),
        (
            protocol.role("requirement"),
            protocol.requirements["required" if required else "optional"],
        ),
        *bounds,
        (protocol.role("lifecycle"), protocol.states["draft"]),
        (protocol.role("digest"), digest_root),
    ), relation_id=spec_id)
    batch.commit()
    if released:
        release_event_fact_spec(store, protocol, spec_id)
    return read_event_fact_spec(
        store.snapshot(), protocol, spec_id, require_released=released
    )


def release_event_fact_spec(
    store: CellStore,
    protocol: EventFactProtocol,
    spec_root: str,
) -> bytes:
    snapshot = store.snapshot()
    spec = read_event_fact_spec(
        snapshot, protocol, spec_root, require_released=False
    )
    if spec.lifecycle_root != protocol.states["draft"]:
        raise InvalidCell("event-fact specification is not a releasable draft")
    released = EventFactSpec(
        spec.root_id,
        spec.key,
        spec.source,
        spec.value_kind,
        spec.required,
        spec.minimum,
        spec.maximum,
        spec.maximum_bytes,
        protocol.states["released"],
        spec.lifecycle_incidence_id,
        spec.digest_root,
    )
    lifecycle = snapshot.cells[spec.lifecycle_incidence_id]
    digest = snapshot.cells[spec.digest_root]
    value = _spec_digest(released)
    store.commit(snapshot.revision, replace=(
        Cell(
            lifecycle.id,
            lifecycle.link0,
            protocol.states["released"],
            lifecycle.atom,
        ),
        Cell(digest.id, digest.link0, digest.link1, value),
    ))
    return value


def validate_event_fact_values(
    snapshot: Snapshot,
    protocol: EventFactProtocol,
    spec_roots: Iterable[str],
    supplied: object,
) -> Mapping[str, object]:
    specs = tuple(
        read_event_fact_spec(snapshot, protocol, root) for root in spec_roots
    )
    if len(specs) != len({spec.root_id for spec in specs}):
        raise InvalidCell("event-fact contract repeats a specification")
    if type(supplied) is not list or any(
        not isinstance(item, Mapping)
        or set(item) != {"input", "value"}
        or type(item.get("input")) is not str
        for item in supplied
    ):
        raise InvalidCell("interaction event facts have an invalid shape")
    pairs = tuple((item["input"], item["value"]) for item in supplied)
    if len(pairs) != len({root for root, _value in pairs}):
        raise InvalidCell("interaction event facts repeat an input identity")
    by_root = dict(pairs)
    allowed = {spec.root_id for spec in specs}
    required = {spec.root_id for spec in specs if spec.required}
    if not required.issubset(by_root) or not set(by_root).issubset(allowed):
        raise InvalidCell("interaction event facts do not match the released contract")
    result: dict[str, object] = {}
    for spec in specs:
        if spec.root_id not in by_root:
            continue
        value = by_root[spec.root_id]
        if spec.value_kind == "number":
            if type(value) not in (int, float):
                raise InvalidCell(
                    "interaction numeric event fact has an invalid value"
                )
            numeric = float(value)
            if (
                not math.isfinite(numeric)
                or spec.minimum is None
                or spec.maximum is None
                or numeric < spec.minimum
                or numeric > spec.maximum
            ):
                raise InvalidCell(
                    "interaction event fact is outside its released bounds"
                )
            admitted: object = numeric
        elif spec.value_kind == "text":
            if type(value) is not str:
                raise InvalidCell(
                    "interaction text event fact has an invalid value"
                )
            try:
                encoded = value.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise InvalidCell(
                    "interaction text event fact is not valid UTF-8"
                ) from exc
            if (
                spec.maximum_bytes is None
                or len(encoded) > spec.maximum_bytes
            ):
                raise InvalidCell(
                    "interaction text event fact exceeds its released bound"
                )
            if spec.required and not value:
                raise InvalidCell(
                    "interaction text event fact is required"
                )
            admitted = value
        else:
            raise InvalidCell("interaction event fact kind is not admitted")
        if spec.key in result:
            raise InvalidCell("event-fact contract repeats a key")
        result[spec.key] = admitted
    return MappingProxyType(result)


__all__ = [
    "EventFactProtocol",
    "EventFactSpec",
    "bootstrap_event_fact_protocol",
    "build_event_fact_spec",
    "project_event_fact_protocol",
    "read_event_fact_spec",
    "release_event_fact_spec",
    "validate_event_fact_values",
]
