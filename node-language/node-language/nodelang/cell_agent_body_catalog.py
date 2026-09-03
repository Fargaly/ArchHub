"""Released Cell catalog for runtime-selectable Application Agent Bodies.

The catalog is deliberately separate from the Agent Body protocol. Agent Body
owns a body's identity and policy; this protocol publishes which runtime
identity and credential mode may select that already-released body.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .cell_protocols import CellBatch, compose_relation_cells, prepare_append_relation_members, read_relation
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


ROLE_NAMES = (
    "vocabulary-member",
    "entry-member",
    "body",
    "control",
    "policy",
    "runtime",
    "grand-map-node",
    "credential-mode",
    "device-custody",
    "work-event",
)
CREDENTIAL_MODES = ("machine-transport", "device-proof")


@dataclass(frozen=True, slots=True)
class AgentBodyCatalogProtocol:
    root_id: str
    roles: Mapping[str, str]
    registry_root: str

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown agent-body catalog role") from exc


@dataclass(frozen=True, slots=True)
class AgentBodyCatalogEntry:
    root_id: str
    body_root: str
    control_root: str
    policy_root: str
    runtime: str
    grand_map_node_root: str
    credential_mode: str
    device_custody_roots: tuple[str, ...]
    work_events: tuple[str, ...]


def _terminal(root_id: str, value: str) -> Cell:
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8"))


def _text(snapshot: Snapshot, root_id: str, label: str) -> str:
    try:
        return snapshot.cells[root_id].atom.decode("utf-8")
    except (KeyError, UnicodeDecodeError) as exc:
        raise InvalidCell("agent-body catalog %s is invalid" % label) from exc


def _exactly_one(members, role_id: str, label: str) -> str:
    values = tuple(member.participant_id for member in members if member.role_id == role_id)
    if len(values) != 1:
        raise InvalidCell("agent-body catalog entry requires exactly one %s" % label)
    return values[0]


def bootstrap_agent_body_catalog_protocol(
    store: CellStore,
    *,
    prefix: str = "agent-body-catalog:v1",
) -> AgentBodyCatalogProtocol:
    root_id = prefix + ":root"
    registry_root = prefix + ":registry"
    if root_id in store.snapshot().cells:
        return project_agent_body_catalog_protocol(store.snapshot(), prefix=prefix)
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    batch = CellBatch(store)
    for name, root in roles.items():
        batch.add(_terminal(root, name))
    batch.relation(
        ((roles["vocabulary-member"], root) for root in roles.values()),
        relation_id=root_id,
    )
    batch.relation(
        ((roles["vocabulary-member"], root) for root in roles.values()),
        relation_id=registry_root,
    )
    batch.commit()
    return AgentBodyCatalogProtocol(
        root_id, MappingProxyType(roles), registry_root
    )


def project_agent_body_catalog_protocol(
    snapshot: Snapshot,
    *,
    prefix: str = "agent-body-catalog:v1",
) -> AgentBodyCatalogProtocol:
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    root_id = prefix + ":root"
    registry_root = prefix + ":registry"
    if any(_root not in snapshot.cells for _root in {root_id, registry_root, *roles.values()}):
        raise InvalidCell("agent-body catalog protocol is incomplete")
    expected = tuple(roles.values())
    for relation_root, label in ((root_id, "vocabulary"), (registry_root, "registry")):
        members = read_relation(snapshot, relation_root, budget=100_000)
        if label == "vocabulary":
            actual = tuple(member.participant_id for member in members)
            if (
                actual != expected
                or any(member.role_id != roles["vocabulary-member"] for member in members)
            ):
                raise InvalidCell("agent-body catalog vocabulary drifted")
        elif any(member.role_id not in {roles["vocabulary-member"], roles["entry-member"]} for member in members):
            raise InvalidCell("agent-body catalog registry is malformed")
        elif tuple(
            member.participant_id for member in members
            if member.role_id == roles["vocabulary-member"]
        ) != expected:
            raise InvalidCell("agent-body catalog registry vocabulary drifted")
    return AgentBodyCatalogProtocol(root_id, MappingProxyType(roles), registry_root)


def compose_agent_body_catalog_entry(
    store: CellStore,
    protocol: AgentBodyCatalogProtocol,
    *,
    entry_id: str,
    body_root: str,
    control_root: str,
    policy_root: str,
    runtime: str,
    grand_map_node_root: str,
    credential_mode: str,
    device_custody_roots: tuple[str, ...] = (),
    work_events: tuple[str, ...],
) -> int:
    snapshot = store.snapshot()
    if entry_id in snapshot.cells:
        raise InvalidCell("agent-body catalog entry already exists")
    runtime = str(runtime).strip()
    credential_mode = str(credential_mode).strip()
    events = tuple(str(value).strip().casefold() for value in work_events)
    devices = tuple(str(value) for value in device_custody_roots)
    if (
        not runtime
        or len(runtime.encode("utf-8")) > 128
        or credential_mode not in CREDENTIAL_MODES
        or not events
        or any(not value or len(value.encode("utf-8")) > 64 for value in events)
        or len(events) != len(set(events))
        or len(devices) != len(set(devices))
    ):
        raise InvalidCell("agent-body catalog entry values are invalid")
    if credential_mode == "machine-transport" and devices:
        raise InvalidCell("machine-transport entries cannot bind device custody")
    required = {
        body_root, control_root, policy_root, grand_map_node_root, *devices,
    }
    if any(_root not in snapshot.cells for _root in required):
        raise InvalidCell("agent-body catalog entry references a missing root")
    value_cells = {
        "runtime": _terminal(entry_id + ":runtime", runtime),
        "credential-mode": _terminal(entry_id + ":credential-mode", credential_mode),
    }
    event_cells = tuple(
        _terminal(entry_id + ":work-event:" + value, value)
        for value in events
    )
    relation = compose_relation_cells(
        (
            (protocol.role("body"), body_root),
            (protocol.role("control"), control_root),
            (protocol.role("policy"), policy_root),
            (protocol.role("runtime"), value_cells["runtime"].id),
            (protocol.role("grand-map-node"), grand_map_node_root),
            (protocol.role("credential-mode"), value_cells["credential-mode"].id),
            *((protocol.role("device-custody"), root) for root in devices),
            *((protocol.role("work-event"), cell.id) for cell in event_cells),
        ),
        relation_id=entry_id,
    )
    registry_patch = prepare_append_relation_members(
        snapshot,
        protocol.registry_root,
        ((protocol.role("entry-member"), entry_id),),
        budget=100_000,
    )
    return store.commit(
        snapshot.revision,
        create=(*value_cells.values(), *event_cells, *relation.cells, *registry_patch.create),
        replace=registry_patch.replace,
    )


def read_agent_body_catalog_entry(
    snapshot: Snapshot,
    protocol: AgentBodyCatalogProtocol,
    entry_root: str,
) -> AgentBodyCatalogEntry:
    registered = tuple(
        member.participant_id for member in read_relation(
            snapshot, protocol.registry_root, budget=100_000
        ) if member.role_id == protocol.role("entry-member")
    )
    if registered.count(entry_root) != 1:
        raise InvalidCell("agent-body catalog entry is not registered exactly once")
    members = read_relation(snapshot, entry_root, budget=128)
    allowed = {
        protocol.role(name) for name in ROLE_NAMES
        if name not in {"vocabulary-member", "entry-member"}
    }
    if any(member.role_id not in allowed for member in members):
        raise InvalidCell("agent-body catalog entry has an undeclared field")
    body = _exactly_one(members, protocol.role("body"), "body")
    control = _exactly_one(members, protocol.role("control"), "control")
    policy = _exactly_one(members, protocol.role("policy"), "policy")
    runtime_root = _exactly_one(members, protocol.role("runtime"), "runtime")
    map_node = _exactly_one(members, protocol.role("grand-map-node"), "Grand Map node")
    mode_root = _exactly_one(members, protocol.role("credential-mode"), "credential mode")
    devices = tuple(
        member.participant_id for member in members
        if member.role_id == protocol.role("device-custody")
    )
    event_roots = tuple(
        member.participant_id for member in members
        if member.role_id == protocol.role("work-event")
    )
    runtime = _text(snapshot, runtime_root, "runtime").strip()
    mode = _text(snapshot, mode_root, "credential mode").strip()
    events = tuple(_text(snapshot, root, "work event").strip().casefold() for root in event_roots)
    if (
        not runtime
        or mode not in CREDENTIAL_MODES
        or not events
        or len(events) != len(set(events))
        or len(devices) != len(set(devices))
        or (mode == "machine-transport" and devices)
    ):
        raise InvalidCell("agent-body catalog entry values drifted")
    return AgentBodyCatalogEntry(
        entry_root, body, control, policy, runtime, map_node, mode, devices, events
    )


def list_agent_body_catalog_entries(
    snapshot: Snapshot,
    protocol: AgentBodyCatalogProtocol,
) -> tuple[AgentBodyCatalogEntry, ...]:
    members = read_relation(snapshot, protocol.registry_root, budget=100_000)
    roots = tuple(
        member.participant_id for member in members
        if member.role_id == protocol.role("entry-member")
    )
    if len(roots) != len(set(roots)):
        raise InvalidCell("agent-body catalog registry contains a duplicate")
    entries = tuple(read_agent_body_catalog_entry(snapshot, protocol, root) for root in roots)
    if len({entry.runtime for entry in entries}) != len(entries):
        raise InvalidCell("agent-body catalog runtime identity is ambiguous")
    return entries


__all__ = [
    "AgentBodyCatalogEntry",
    "AgentBodyCatalogProtocol",
    "CREDENTIAL_MODES",
    "ROLE_NAMES",
    "bootstrap_agent_body_catalog_protocol",
    "compose_agent_body_catalog_entry",
    "list_agent_body_catalog_entries",
    "project_agent_body_catalog_protocol",
    "read_agent_body_catalog_entry",
]
