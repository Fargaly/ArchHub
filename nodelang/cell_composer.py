"""Deny-by-default authoring authority above the released assembly catalogue.

The universal cell remains the physical execution floor.  This protocol limits
ordinary authoring to a closed, released vocabulary of graph-held commands and
catalogue definitions.  It does not make a second node table or a product-kind
switch: roles, commands, limits, actor identity, evidence, lifecycle, and the
authority itself are ordinary Cells.  Python only verifies that graph contract.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
from types import MappingProxyType
from typing import Mapping

from .cell_adapters import AdapterProtocol, verify_adapter_catalog
from .cell_catalog import (
    AssemblyProtocol,
    verify_released_catalog,
    verify_released_definition,
)
from .cell_protocols import CellBatch, RelationMember, read_relation
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


ROLE_NAMES = (
    "vocabulary-member",
    "catalogue",
    "adapter-catalogue",
    "actor",
    "allowed-command",
    "limit",
    "limit-name",
    "limit-value",
    "lifecycle",
    "digest",
    "evidence",
)

COMMAND_NAMES = (
    "catalog.instantiate",
    "catalog.connect",
    "catalog.configure",
    "canvas.arrange",
    "canvas.select",
    "catalog.propose",
)

DEFAULT_AGENT_COMMANDS = (
    "catalog.instantiate",
    "catalog.connect",
    "catalog.configure",
    "canvas.arrange",
    "canvas.select",
)

DEFAULT_LIMITS = MappingProxyType({
    "max-instances": 256,
    "max-relations": 1024,
    "max-collection-items": 4096,
    "max-atom-bytes": 65_536,
    "max-commands-per-request": 32,
    "max-proposal-parts": 50_000,
})


@dataclass(frozen=True, slots=True)
class ComposerProtocol:
    root_id: str
    roles: Mapping[str, str]
    commands: Mapping[str, str]
    states: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown composer role %r" % name) from exc

    def command(self, name: str) -> str:
        try:
            return self.commands[name]
        except KeyError as exc:
            raise InvalidCell("composer command is outside the closed grammar") from exc


@dataclass(frozen=True, slots=True)
class ComposerAuthority:
    root_id: str
    actor_root: str
    digest_root: str


@dataclass(frozen=True, slots=True)
class ComposerProjection:
    root_id: str
    catalogue_root: str
    adapter_catalogue_root: str
    actor_root: str
    lifecycle_root: str
    digest_root: str
    evidence_roots: tuple[str, ...]
    allowed_command_roots: tuple[str, ...]
    limits: Mapping[str, int]


def bootstrap_composer_protocol(
    store: CellStore,
    *,
    prefix: str = "composer-protocol",
) -> ComposerProtocol:
    """Publish the closed authoring grammar as an inspectable graph."""
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    commands = {
        name: "%s:command:%s" % (prefix, name) for name in COMMAND_NAMES
    }
    states = {
        "draft": prefix + ":state:draft",
        "released": prefix + ":state:released",
        "deprecated": prefix + ":state:deprecated",
    }
    batch = CellBatch(store)
    for name, root_id in roles.items():
        batch.add(Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, name.encode("ascii")))
    for name, root_id in commands.items():
        batch.add(Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, name.encode("ascii")))
    for name, root_id in states.items():
        batch.add(Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, name.encode("ascii")))
    root_id = prefix + ":root"
    batch.relation([
        *((roles["vocabulary-member"], root) for root in roles.values()),
        *((roles["vocabulary-member"], root) for root in commands.values()),
        *((roles["vocabulary-member"], root) for root in states.values()),
    ], relation_id=root_id)
    batch.commit()
    return ComposerProtocol(
        root_id,
        MappingProxyType(roles),
        MappingProxyType(commands),
        MappingProxyType(states),
    )


def _for_role(
    members: tuple[RelationMember, ...],
    role_id: str,
) -> tuple[str, ...]:
    return tuple(
        member.participant_id for member in members if member.role_id == role_id
    )


def _one(
    members: tuple[RelationMember, ...],
    role_id: str,
    label: str,
) -> str:
    values = _for_role(members, role_id)
    if len(values) != 1:
        raise InvalidCell("composer authority requires exactly one %s" % label)
    return values[0]


def _read_limit(
    snapshot: Snapshot,
    protocol: ComposerProtocol,
    limit_root: str,
) -> tuple[str, int]:
    members = read_relation(snapshot, limit_root, budget=32)
    allowed_roles = {
        protocol.role("limit-name"), protocol.role("limit-value")
    }
    if any(member.role_id not in allowed_roles for member in members):
        raise InvalidCell("composer limit contains an undeclared field")
    name_root = _one(members, protocol.role("limit-name"), "limit name")
    value_root = _one(members, protocol.role("limit-value"), "limit value")
    try:
        name = snapshot.cells[name_root].atom.decode("ascii")
        value = int(snapshot.cells[value_root].atom.decode("ascii"))
    except (KeyError, UnicodeDecodeError, ValueError) as exc:
        raise InvalidCell("composer limit is invalid") from exc
    if not name or value < 0:
        raise InvalidCell("composer limit is invalid")
    return name, value


def _authority_digest(
    snapshot: Snapshot,
    assembly_protocol: AssemblyProtocol,
    adapter_protocol: AdapterProtocol,
    authority_root: str,
    catalogue_root: str,
    adapter_catalogue_root: str,
    actor_root: str,
    command_roots: tuple[str, ...],
    limits: Mapping[str, int],
    evidence_roots: tuple[str, ...],
) -> bytes:
    catalogue = verify_released_catalog(
        snapshot, assembly_protocol, catalogue_root
    )
    adapter_catalogue = verify_adapter_catalog(
        snapshot, adapter_protocol, adapter_catalogue_root
    )
    digest = hashlib.blake2b(digest_size=32)

    def field(value: bytes) -> None:
        digest.update(len(value).to_bytes(8, "big"))
        digest.update(value)

    field(authority_root.encode("utf-8"))
    field(catalogue_root.encode("utf-8"))
    field(snapshot.cells[catalogue.digest_root].atom)
    field(adapter_catalogue_root.encode("utf-8"))
    field(snapshot.cells[adapter_catalogue.digest_root].atom)
    field(actor_root.encode("utf-8"))
    field(snapshot.cells[actor_root].atom)
    for command_root in sorted(command_roots):
        field(command_root.encode("utf-8"))
    for name, value in sorted(limits.items()):
        field(name.encode("ascii"))
        field(str(value).encode("ascii"))
    for evidence_root in sorted(evidence_roots):
        field(evidence_root.encode("utf-8"))
        field(snapshot.cells[evidence_root].atom)
    return digest.hexdigest().encode("ascii")


def build_composer_authority(
    store: CellStore,
    protocol: ComposerProtocol,
    assembly_protocol: AssemblyProtocol,
    catalogue_root: str,
    adapter_protocol: AdapterProtocol,
    adapter_catalogue_root: str,
    *,
    authority_id: str = "agent-composer-authority",
    actor_name: str = "agent composer",
    allowed_commands: tuple[str, ...] = DEFAULT_AGENT_COMMANDS,
    limits: Mapping[str, int] = DEFAULT_LIMITS,
    evidence: str = "tests_replica/test_cell_composer.py",
) -> ComposerAuthority:
    """Release one immutable authority; unknown commands are never implied."""
    snapshot = store.snapshot()
    verify_released_catalog(snapshot, assembly_protocol, catalogue_root)
    verify_adapter_catalog(snapshot, adapter_protocol, adapter_catalogue_root)
    if not allowed_commands or len(allowed_commands) != len(set(allowed_commands)):
        raise InvalidCell("composer authority commands must be unique and non-empty")
    command_roots = tuple(protocol.command(name) for name in allowed_commands)
    normalized_limits = dict(limits)
    if not normalized_limits or any(
        not isinstance(value, int) or value < 0
        for value in normalized_limits.values()
    ):
        raise InvalidCell("composer authority limits must be non-negative integers")

    actor_root = authority_id + ":actor"
    evidence_root = authority_id + ":evidence"
    digest_root = authority_id + ":digest"
    batch = CellBatch(store)
    batch.add(Cell(
        actor_root, NULL_CELL_ID, NULL_CELL_ID, actor_name.encode("utf-8")
    ))
    batch.add(Cell(
        evidence_root, NULL_CELL_ID, NULL_CELL_ID, evidence.encode("utf-8")
    ))
    limit_roots: list[str] = []
    for index, (name, value) in enumerate(sorted(normalized_limits.items())):
        limit_root = "%s:limit:%s" % (authority_id, index)
        name_root = limit_root + ":name"
        value_root = limit_root + ":value"
        batch.add(Cell(
            name_root, NULL_CELL_ID, NULL_CELL_ID, name.encode("ascii")
        ))
        batch.add(Cell(
            value_root,
            NULL_CELL_ID,
            NULL_CELL_ID,
            str(value).encode("ascii"),
        ))
        batch.relation([
            (protocol.role("limit-name"), name_root),
            (protocol.role("limit-value"), value_root),
        ], relation_id=limit_root)
        limit_roots.append(limit_root)

    # The digest can be computed over the released catalogue and the terminals
    # already present in this uncommitted batch because those terminal values
    # are supplied directly here.
    digest = hashlib.blake2b(digest_size=32)

    def field(value: bytes) -> None:
        digest.update(len(value).to_bytes(8, "big"))
        digest.update(value)

    catalogue = verify_released_catalog(
        snapshot, assembly_protocol, catalogue_root
    )
    adapter_catalogue = verify_adapter_catalog(
        snapshot, adapter_protocol, adapter_catalogue_root
    )
    field(authority_id.encode("utf-8"))
    field(catalogue_root.encode("utf-8"))
    field(snapshot.cells[catalogue.digest_root].atom)
    field(adapter_catalogue_root.encode("utf-8"))
    field(snapshot.cells[adapter_catalogue.digest_root].atom)
    field(actor_root.encode("utf-8"))
    field(actor_name.encode("utf-8"))
    for command_root in sorted(command_roots):
        field(command_root.encode("utf-8"))
    for name, value in sorted(normalized_limits.items()):
        field(name.encode("ascii"))
        field(str(value).encode("ascii"))
    field(evidence_root.encode("utf-8"))
    field(evidence.encode("utf-8"))
    batch.add(Cell(digest_root, NULL_CELL_ID, NULL_CELL_ID, digest.hexdigest().encode("ascii")))
    batch.relation([
        (protocol.role("catalogue"), catalogue_root),
        (protocol.role("adapter-catalogue"), adapter_catalogue_root),
        (protocol.role("actor"), actor_root),
        *((protocol.role("allowed-command"), root) for root in command_roots),
        *((protocol.role("limit"), root) for root in limit_roots),
        (protocol.role("lifecycle"), protocol.states["released"]),
        (protocol.role("digest"), digest_root),
        (protocol.role("evidence"), evidence_root),
    ], relation_id=authority_id)
    batch.commit()
    return ComposerAuthority(authority_id, actor_root, digest_root)


def verify_composer_authority(
    snapshot: Snapshot,
    protocol: ComposerProtocol,
    assembly_protocol: AssemblyProtocol,
    adapter_protocol: AdapterProtocol,
    authority_root: str,
) -> ComposerProjection:
    members = read_relation(snapshot, authority_root, budget=100_000)
    allowed_roles = {
        protocol.role("catalogue"),
        protocol.role("adapter-catalogue"),
        protocol.role("actor"),
        protocol.role("allowed-command"),
        protocol.role("limit"),
        protocol.role("lifecycle"),
        protocol.role("digest"),
        protocol.role("evidence"),
    }
    if any(member.role_id not in allowed_roles for member in members):
        raise InvalidCell("composer authority contains an undeclared field")
    catalogue_root = _one(
        members, protocol.role("catalogue"), "catalogue"
    )
    adapter_catalogue_root = _one(
        members, protocol.role("adapter-catalogue"), "adapter catalogue"
    )
    actor_root = _one(members, protocol.role("actor"), "actor")
    lifecycle_root = _one(
        members, protocol.role("lifecycle"), "lifecycle"
    )
    digest_root = _one(members, protocol.role("digest"), "digest")
    command_roots = _for_role(members, protocol.role("allowed-command"))
    evidence_roots = _for_role(members, protocol.role("evidence"))
    limit_roots = _for_role(members, protocol.role("limit"))
    if lifecycle_root != protocol.states["released"]:
        raise InvalidCell("composer authority is not released")
    if not command_roots or len(command_roots) != len(set(command_roots)):
        raise InvalidCell("composer authority commands are invalid")
    vocabulary = set(protocol.commands.values())
    if any(root not in vocabulary for root in command_roots):
        raise InvalidCell("composer authority contains an unknown command")
    if not evidence_roots:
        raise InvalidCell("composer authority requires court evidence")
    limits: dict[str, int] = {}
    for limit_root in limit_roots:
        name, value = _read_limit(snapshot, protocol, limit_root)
        if name in limits:
            raise InvalidCell("composer authority repeats a limit")
        limits[name] = value
    if not limits:
        raise InvalidCell("composer authority requires resource limits")
    try:
        expected = snapshot.cells[digest_root].atom
    except KeyError as exc:
        raise InvalidCell("composer authority digest is missing") from exc
    actual = _authority_digest(
        snapshot,
        assembly_protocol,
        adapter_protocol,
        authority_root,
        catalogue_root,
        adapter_catalogue_root,
        actor_root,
        command_roots,
        limits,
        evidence_roots,
    )
    if not expected or not hmac.compare_digest(expected, actual):
        raise InvalidCell("released composer authority has drifted")
    return ComposerProjection(
        authority_root,
        catalogue_root,
        adapter_catalogue_root,
        actor_root,
        lifecycle_root,
        digest_root,
        evidence_roots,
        command_roots,
        MappingProxyType(limits),
    )


def authorize_composer_command(
    snapshot: Snapshot,
    protocol: ComposerProtocol,
    assembly_protocol: AssemblyProtocol,
    adapter_protocol: AdapterProtocol,
    authority_root: str,
    command_name: str,
    *,
    definition_root: str | None = None,
    resource_usage: Mapping[str, tuple[int, int]] | None = None,
) -> ComposerProjection:
    """Fail closed before a caller assembles a graph mutation transaction."""
    authority = verify_composer_authority(
        snapshot, protocol, assembly_protocol, adapter_protocol, authority_root
    )
    command_root = protocol.command(command_name)
    if command_root not in authority.allowed_command_roots:
        raise InvalidCell("composer authority denies command %r" % command_name)
    catalogue = verify_released_catalog(
        snapshot, assembly_protocol, authority.catalogue_root
    )
    if definition_root is not None:
        if definition_root not in catalogue.definition_roots:
            raise InvalidCell("composer definition is outside the released catalogue")
        verify_released_definition(
            snapshot, assembly_protocol, definition_root
        )
    for name, usage in (resource_usage or {}).items():
        if name not in authority.limits:
            raise InvalidCell("composer request uses an undeclared resource budget")
        try:
            current, requested = usage
        except (TypeError, ValueError) as exc:
            raise InvalidCell("composer resource usage is invalid") from exc
        if current < 0 or requested < 0:
            raise InvalidCell("composer resource usage is invalid")
        if current + requested > authority.limits[name]:
            raise InvalidCell("composer resource limit %r would be exceeded" % name)
    return authority


__all__ = [
    "ComposerProtocol",
    "ComposerAuthority",
    "ComposerProjection",
    "DEFAULT_AGENT_COMMANDS",
    "DEFAULT_LIMITS",
    "bootstrap_composer_protocol",
    "build_composer_authority",
    "verify_composer_authority",
    "authorize_composer_command",
]
