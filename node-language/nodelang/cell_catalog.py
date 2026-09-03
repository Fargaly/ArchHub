"""Graph-authoritative reusable assemblies above the universal-cell floor.

This module deliberately contains no Watcher, List, Logic, Session, or product
dispatch. Definitions, catalogue membership, interfaces, state ownership,
rules, capabilities, failures, evidence, versions, and instance mappings are
ordinary universal-cell relations. Python objects below are read projections;
the persisted graph is the authority.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
import hashlib
import hmac
import threading
from types import MappingProxyType
from typing import Iterable, Mapping
import uuid
from weakref import WeakKeyDictionary, ref

from .cell_protocols import (
    CellBatch,
    RelationMember,
    compose_relation_cells,
    read_relation,
)
from .cell_relation_contract import (
    RelationCandidate,
    resolve_relation_contract_authority,
    validate_relation,
)
from .universal_cell import (
    NULL_CELL_ID,
    Cell,
    CellStore,
    InvalidCell,
    Snapshot,
    overlay_read_snapshot,
)


ROLE_NAMES = (
    "vocabulary-member",
    "catalog-member",
    "part",
    "interface",
    "interface-target",
    "interface-member-role",
    "interface-contract",
    "interface-default",
    "interface-presentation",
    "interface-documentation",
    "state",
    "rule",
    "capability",
    "status",
    "error",
    "evidence",
    "obligation",
    "required-role",
    "minimum",
    "shared",
    "definition-dependency",
    "name",
    "version",
    "lifecycle",
    "digest",
    "provenance",
    "mapping",
    "definition-side",
    "instance-side",
)


@dataclass(frozen=True, slots=True)
class AssemblyProtocol:
    """Bootstrap identities for one graph-held assembly vocabulary."""

    root_id: str
    roles: Mapping[str, str]
    states: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown assembly role %r" % name) from exc


@dataclass(frozen=True, slots=True)
class InterfaceBuild:
    root_id: str
    part_roots: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ObligationBuild:
    root_id: str
    minimum_root: str


@dataclass(frozen=True, slots=True)
class DefinitionBuild:
    root_id: str
    name_root: str
    version_root: str
    digest_root: str


@dataclass(frozen=True, slots=True)
class DefinitionProjection:
    root_id: str
    name_root: str
    version_root: str
    lifecycle_root: str
    digest_root: str
    part_roots: tuple[str, ...]
    interface_roots: tuple[str, ...]
    state_roots: tuple[str, ...]
    rule_roots: tuple[str, ...]
    capability_roots: tuple[str, ...]
    status_roots: tuple[str, ...]
    error_roots: tuple[str, ...]
    evidence_roots: tuple[str, ...]
    obligation_roots: tuple[str, ...]
    shared_roots: tuple[str, ...]
    dependency_roots: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CatalogProjection:
    root_id: str
    version_root: str
    lifecycle_root: str
    digest_root: str
    definition_roots: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AssemblyInstance:
    root_id: str
    definition_root: str
    cell_map: Mapping[str, str]


_CATALOG_VERIFICATION_CACHE: ContextVar[
    dict[tuple[str, int, int, str, str], object] | None
] = ContextVar("catalog_verification_cache", default=None)
_STABLE_CATALOG_VERIFICATION_CACHE: WeakKeyDictionary[
    CellStore,
    tuple[tuple[str, str], CatalogProjection, frozenset[str]],
] = WeakKeyDictionary()
_STABLE_CATALOG_VERIFICATION_LISTENERS: WeakKeyDictionary[
    CellStore, object
] = WeakKeyDictionary()
_STABLE_CATALOG_VERIFICATION_CACHE_LOCK = threading.RLock()


@contextmanager
def catalog_verification_scope():
    """Reuse released-assembly proofs only inside one interpreter request."""
    existing = _CATALOG_VERIFICATION_CACHE.get()
    if existing is not None:
        yield
        return
    token = _CATALOG_VERIFICATION_CACHE.set({})
    try:
        yield
    finally:
        _CATALOG_VERIFICATION_CACHE.reset(token)


def with_catalog_verification_scope(function):
    """Run an interpreter entrypoint with request-local release proofs."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        with catalog_verification_scope():
            return function(*args, **kwargs)
    return wrapped


@dataclass(frozen=True, slots=True)
class AssemblyInstanceCells:
    instance: AssemblyInstance
    cells: tuple[Cell, ...]


def _new_id(prefix: str) -> str:
    return "%s:%s" % (prefix, uuid.uuid4().hex)


def bootstrap_assembly_protocol(
    store: CellStore,
    *,
    prefix: str = "assembly-protocol",
) -> AssemblyProtocol:
    """Create the protocol itself as ordinary cells in one revision."""
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    states = {
        "draft": "%s:state:draft" % prefix,
        "released": "%s:state:released" % prefix,
        "deprecated": "%s:state:deprecated" % prefix,
    }
    batch = CellBatch(store)
    for name, root_id in roles.items():
        batch.add(Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, name.encode("ascii")))
    for name, root_id in states.items():
        batch.add(Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, name.encode("ascii")))
    root_id = "%s:root" % prefix
    batch.relation(
        [
            *((roles["vocabulary-member"], root) for root in roles.values()),
            *((roles["vocabulary-member"], root) for root in states.values()),
        ],
        relation_id=root_id,
    )
    batch.commit()
    return AssemblyProtocol(
        root_id=root_id,
        roles=MappingProxyType(roles),
        states=MappingProxyType(states),
    )


def build_interface(
    store: CellStore,
    protocol: AssemblyProtocol,
    *,
    interface_id: str,
    target_root: str,
    name_root: str | None = None,
    member_role_root: str | None = None,
    contract_root: str | None = None,
    default_root: str | None = None,
    presentation_root: str | None = None,
    documentation_root: str | None = None,
) -> InterfaceBuild:
    """Build one public boundary as an open relation of ordinary cells."""
    members = [(protocol.role("interface-target"), target_root)]
    for role_name, participant in (
        ("name", name_root),
        ("interface-member-role", member_role_root),
        ("interface-contract", contract_root),
        ("interface-default", default_root),
        ("interface-presentation", presentation_root),
        ("interface-documentation", documentation_root),
    ):
        if participant is not None:
            members.append((protocol.role(role_name), participant))
    batch = CellBatch(store)
    built = batch.relation(members, relation_id=interface_id)
    batch.commit()
    return InterfaceBuild(
        interface_id,
        tuple(dict.fromkeys((*built.chain_ids, *built.incidence_ids))),
    )


def build_role_obligation(
    store: CellStore,
    protocol: AssemblyProtocol,
    *,
    obligation_id: str,
    required_role: str,
    minimum: int = 1,
) -> ObligationBuild:
    """Express one release requirement as graph data, not a Python profile."""
    if minimum < 0:
        raise InvalidCell("assembly obligation minimum cannot be negative")
    minimum_root = obligation_id + ":minimum"
    batch = CellBatch(store)
    batch.add(Cell(
        minimum_root,
        NULL_CELL_ID,
        NULL_CELL_ID,
        str(minimum).encode("ascii"),
    ))
    batch.relation([
        (protocol.role("required-role"), required_role),
        (protocol.role("minimum"), minimum_root),
    ], relation_id=obligation_id)
    batch.commit()
    return ObligationBuild(obligation_id, minimum_root)


def build_definition(
    store: CellStore,
    protocol: AssemblyProtocol,
    *,
    definition_id: str,
    name: str,
    version: str,
    part_roots: Iterable[str],
    interface_roots: Iterable[str],
    state_roots: Iterable[str] = (),
    rule_roots: Iterable[str] = (),
    capability_roots: Iterable[str] = (),
    status_roots: Iterable[str] = (),
    error_roots: Iterable[str] = (),
    evidence_roots: Iterable[str] = (),
    obligation_roots: Iterable[str] = (),
    shared_roots: Iterable[str] = (),
    dependency_roots: Iterable[str] = (),
) -> DefinitionBuild:
    """Create an editable draft definition; release is a separate court."""
    token = uuid.uuid4().hex
    name_root = "%s:metadata:%s:name" % (definition_id, token)
    version_root = "%s:metadata:%s:version" % (definition_id, token)
    digest_root = "%s:metadata:%s:digest" % (definition_id, token)
    shared = tuple(dict.fromkeys(
        (
            protocol.root_id,
            *protocol.roles.values(),
            *protocol.states.values(),
            *shared_roots,
        )
    ))
    batch = CellBatch(store)
    batch.add(Cell(name_root, NULL_CELL_ID, NULL_CELL_ID, name.encode("utf-8")))
    batch.add(Cell(
        version_root, NULL_CELL_ID, NULL_CELL_ID, version.encode("ascii")
    ))
    batch.add(Cell(digest_root, NULL_CELL_ID, NULL_CELL_ID, b""))
    members = [
        (protocol.role("name"), name_root),
        (protocol.role("version"), version_root),
        (protocol.role("lifecycle"), protocol.states["draft"]),
        (protocol.role("digest"), digest_root),
    ]
    for role_name, roots in (
        ("part", part_roots),
        ("interface", interface_roots),
        ("state", state_roots),
        ("rule", rule_roots),
        ("capability", capability_roots),
        ("status", status_roots),
        ("error", error_roots),
        ("evidence", evidence_roots),
        ("obligation", obligation_roots),
        ("shared", shared),
        ("definition-dependency", dependency_roots),
    ):
        members.extend((protocol.role(role_name), root) for root in roots)
    batch.relation(members, relation_id=definition_id)
    batch.commit()
    return DefinitionBuild(definition_id, name_root, version_root, digest_root)


def _for_role(
    members: Iterable[RelationMember],
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
        raise InvalidCell("assembly definition requires exactly one %s" % label)
    return values[0]


def read_definition(
    snapshot: Snapshot,
    protocol: AssemblyProtocol,
    definition_root: str,
    *,
    budget: int = 100_000,
) -> DefinitionProjection:
    members = read_relation(snapshot, definition_root, budget=budget)
    return DefinitionProjection(
        root_id=definition_root,
        name_root=_one(members, protocol.role("name"), "name"),
        version_root=_one(members, protocol.role("version"), "version"),
        lifecycle_root=_one(members, protocol.role("lifecycle"), "lifecycle"),
        digest_root=_one(members, protocol.role("digest"), "digest"),
        part_roots=_for_role(members, protocol.role("part")),
        interface_roots=_for_role(members, protocol.role("interface")),
        state_roots=_for_role(members, protocol.role("state")),
        rule_roots=_for_role(members, protocol.role("rule")),
        capability_roots=_for_role(members, protocol.role("capability")),
        status_roots=_for_role(members, protocol.role("status")),
        error_roots=_for_role(members, protocol.role("error")),
        evidence_roots=_for_role(members, protocol.role("evidence")),
        obligation_roots=_for_role(members, protocol.role("obligation")),
        shared_roots=_for_role(members, protocol.role("shared")),
        dependency_roots=_for_role(
            members, protocol.role("definition-dependency")
        ),
    )


def _definition_digest(
    snapshot: Snapshot,
    protocol: AssemblyProtocol,
    definition: DefinitionProjection,
) -> bytes:
    digest = hashlib.blake2b(digest_size=32)

    def field(value: bytes) -> None:
        digest.update(len(value).to_bytes(8, "big"))
        digest.update(value)

    members = read_relation(snapshot, definition.root_id, budget=100_000)
    excluded = {protocol.role("digest"), protocol.role("lifecycle")}
    logical_members = sorted(
        (member.role_id, member.participant_id)
        for member in members
        if member.role_id not in excluded
    )
    for role_id, participant_id in logical_members:
        field(role_id.encode("utf-8"))
        field(participant_id.encode("utf-8"))

    content_roots = set(definition.part_roots)
    content_roots.update((
        definition.name_root,
        definition.version_root,
        *definition.evidence_roots,
        *definition.obligation_roots,
    ))
    pending = list(definition.obligation_roots)
    while pending:
        root_id = pending.pop()
        if root_id in content_roots or root_id == NULL_CELL_ID:
            continue
        cell = snapshot.cells[root_id]
        content_roots.add(root_id)
        pending.extend((cell.link0, cell.link1))
    for root_id in sorted(content_roots):
        cell = snapshot.cells[root_id]
        field(cell.id.encode("utf-8"))
        field(cell.link0.encode("utf-8"))
        field(cell.link1.encode("utf-8"))
        field(cell.atom)
    return digest.hexdigest().encode("ascii")


def _assert_unique(values: tuple[str, ...], label: str) -> None:
    if len(values) != len(set(values)):
        raise InvalidCell("assembly definition repeats a %s root" % label)


def _assert_no_recursion(
    snapshot: Snapshot,
    protocol: AssemblyProtocol,
    definition_root: str,
) -> None:
    active: set[str] = set()
    complete: set[str] = set()

    def visit(root_id: str) -> None:
        if root_id in active:
            raise InvalidCell("recursive assembly definitions are not admitted")
        if root_id in complete:
            return
        active.add(root_id)
        definition = read_definition(snapshot, protocol, root_id)
        for dependency in definition.dependency_roots:
            visit(dependency)
        active.remove(root_id)
        complete.add(root_id)

    visit(definition_root)


def validate_definition(
    snapshot: Snapshot,
    protocol: AssemblyProtocol,
    definition_root: str,
    *,
    require_release_evidence: bool = False,
) -> DefinitionProjection:
    """Validate one definition without interpreting a catalogue name."""
    definition = read_definition(snapshot, protocol, definition_root)
    for label, values in (
        ("part", definition.part_roots),
        ("interface", definition.interface_roots),
        ("state", definition.state_roots),
        ("rule", definition.rule_roots),
        ("capability", definition.capability_roots),
        ("status", definition.status_roots),
        ("error", definition.error_roots),
        ("evidence", definition.evidence_roots),
        ("obligation", definition.obligation_roots),
        ("shared", definition.shared_roots),
        ("dependency", definition.dependency_roots),
    ):
        _assert_unique(values, label)

    if not definition.part_roots:
        raise InvalidCell("assembly definition has no declared region")
    if not definition.interface_roots:
        raise InvalidCell("assembly definition has no public interface")
    if require_release_evidence:
        if not definition.evidence_roots:
            raise InvalidCell("released assembly requires operational evidence")

    required_roots = {
        definition.name_root,
        definition.version_root,
        definition.lifecycle_root,
        definition.digest_root,
        *definition.part_roots,
        *definition.capability_roots,
        *definition.evidence_roots,
        *definition.obligation_roots,
        *definition.shared_roots,
        *definition.dependency_roots,
    }
    if any(root_id not in snapshot.cells for root_id in required_roots):
        raise InvalidCell("assembly definition references missing cells")

    parts = set(definition.part_roots)
    for label, roots in (
        ("interface", definition.interface_roots),
        ("state", definition.state_roots),
        ("status", definition.status_roots),
        ("error", definition.error_roots),
    ):
        if not set(roots).issubset(parts):
            raise InvalidCell("assembly %s roots must belong to its region" % label)
    if not set(definition.rule_roots).issubset(
        parts | set(definition.shared_roots)
    ):
        raise InvalidCell(
            "assembly rule roots must belong to its region or shared authority"
        )

    allowed_external = {
        NULL_CELL_ID,
        definition.name_root,
        definition.version_root,
        definition.lifecycle_root,
        definition.digest_root,
        *definition.capability_roots,
        *definition.evidence_roots,
        *definition.obligation_roots,
        *definition.shared_roots,
        *definition.dependency_roots,
    }
    for part_id in definition.part_roots:
        part = snapshot.cells[part_id]
        for linked in (part.link0, part.link1):
            if linked not in parts and linked not in allowed_external:
                raise InvalidCell(
                    "assembly region contains an undeclared boundary reference"
                )

    for interface_root in definition.interface_roots:
        interface = read_relation(snapshot, interface_root, budget=100_000)
        target = _one(
            interface,
            protocol.role("interface-target"),
            "interface target",
        )
        if target not in parts:
            raise InvalidCell("assembly interface targets outside its region")

    definition_members = read_relation(
        snapshot, definition_root, budget=100_000
    )
    for obligation_root in definition.obligation_roots:
        obligation = read_relation(snapshot, obligation_root, budget=100_000)
        required_role = _one(
            obligation,
            protocol.role("required-role"),
            "obligation required role",
        )
        minimum_root = _one(
            obligation,
            protocol.role("minimum"),
            "obligation minimum",
        )
        try:
            minimum = int(snapshot.cells[minimum_root].atom.decode("ascii"))
        except (KeyError, UnicodeDecodeError, ValueError) as exc:
            raise InvalidCell("assembly obligation minimum is invalid") from exc
        if minimum < 0:
            raise InvalidCell("assembly obligation minimum is invalid")
        actual = sum(
            member.role_id == required_role for member in definition_members
        )
        if actual < minimum:
            label = snapshot.cells[required_role].atom.decode(
                "utf-8", errors="replace"
            )
            raise InvalidCell(
                "assembly obligation requires %s %s participant(s)"
                % (minimum, label)
            )

    _assert_no_recursion(snapshot, protocol, definition_root)
    return definition


def release_definition(
    store: CellStore,
    protocol: AssemblyProtocol,
    definition_root: str,
) -> bytes:
    """Validate and atomically publish an immutable, fingerprinted release."""
    snapshot = store.snapshot()
    definition = validate_definition(
        snapshot,
        protocol,
        definition_root,
        require_release_evidence=True,
    )
    if definition.lifecycle_root != protocol.states["draft"]:
        raise InvalidCell("only a draft assembly can be released")
    release_digest = _definition_digest(snapshot, protocol, definition)
    members = read_relation(snapshot, definition_root, budget=100_000)
    lifecycle_members = tuple(
        member for member in members
        if member.role_id == protocol.role("lifecycle")
    )
    lifecycle = lifecycle_members[0]
    digest_cell = snapshot.cells[definition.digest_root]
    incidence = snapshot.cells[lifecycle.incidence_id]
    store.commit(
        snapshot.revision,
        replace=(
            Cell(
                digest_cell.id,
                digest_cell.link0,
                digest_cell.link1,
                release_digest,
            ),
            Cell(
                incidence.id,
                incidence.link0,
                protocol.states["released"],
                incidence.atom,
            ),
        ),
    )
    return release_digest


def verify_released_definition(
    snapshot: Snapshot,
    protocol: AssemblyProtocol,
    definition_root: str,
) -> DefinitionProjection:
    cache = _CATALOG_VERIFICATION_CACHE.get()
    cache_key = (
        "definition",
        snapshot.revision,
        id(snapshot.cells),
        protocol.root_id,
        definition_root,
    )
    if cache is not None and cache_key in cache:
        cached = cache[cache_key]
        if type(cached) is not DefinitionProjection:
            raise InvalidCell("definition verification cache is invalid")
        return cached
    definition = validate_definition(
        snapshot,
        protocol,
        definition_root,
        require_release_evidence=True,
    )
    if definition.lifecycle_root != protocol.states["released"]:
        raise InvalidCell("assembly definition is not released")
    expected = snapshot.cells[definition.digest_root].atom
    actual = _definition_digest(snapshot, protocol, definition)
    if not expected or not hmac.compare_digest(expected, actual):
        raise InvalidCell("released assembly definition has drifted")
    if cache is not None:
        cache[cache_key] = definition
    return definition


def build_catalog(
    store: CellStore,
    protocol: AssemblyProtocol,
    definition_roots: Iterable[str],
    *,
    catalog_id: str = "assembly-catalog",
    version: str = "1.0.0",
) -> str:
    """Publish a released, fingerprinted catalogue of admitted definitions."""
    roots = tuple(definition_roots)
    if not roots:
        raise InvalidCell("released catalogue requires at least one definition")
    if len(roots) != len(set(roots)):
        raise InvalidCell("released catalogue repeats a definition")
    snapshot = store.snapshot()
    for root_id in roots:
        verify_released_definition(snapshot, protocol, root_id)
    try:
        version_bytes = version.encode("ascii")
    except UnicodeEncodeError as exc:
        raise InvalidCell("catalogue version must be ASCII") from exc
    if not version_bytes:
        raise InvalidCell("catalogue version cannot be empty")
    version_root = catalog_id + ":metadata:version"
    digest_root = catalog_id + ":metadata:digest"
    digest = _catalog_digest(
        snapshot,
        protocol,
        catalog_id,
        roots,
        version_bytes,
    )
    batch = CellBatch(store)
    batch.add(Cell(
        version_root, NULL_CELL_ID, NULL_CELL_ID, version_bytes
    ))
    batch.add(Cell(
        digest_root, NULL_CELL_ID, NULL_CELL_ID, digest
    ))
    batch.relation(
        [
            *((protocol.role("catalog-member"), root_id) for root_id in roots),
            (protocol.role("version"), version_root),
            (protocol.role("lifecycle"), protocol.states["released"]),
            (protocol.role("digest"), digest_root),
        ],
        relation_id=catalog_id,
    )
    batch.commit()
    return catalog_id


def _catalog_digest(
    snapshot: Snapshot,
    protocol: AssemblyProtocol,
    catalog_root: str,
    definition_roots: tuple[str, ...],
    version: bytes,
) -> bytes:
    digest = hashlib.blake2b(digest_size=32)

    def field(value: bytes) -> None:
        digest.update(len(value).to_bytes(8, "big"))
        digest.update(value)

    field(catalog_root.encode("utf-8"))
    field(version)
    for definition_root in sorted(definition_roots):
        definition = verify_released_definition(
            snapshot, protocol, definition_root
        )
        field(definition_root.encode("utf-8"))
        field(snapshot.cells[definition.digest_root].atom)
    return digest.hexdigest().encode("ascii")


def read_catalog(
    snapshot: Snapshot,
    protocol: AssemblyProtocol,
    catalog_root: str,
) -> CatalogProjection:
    members = read_relation(snapshot, catalog_root, budget=100_000)
    return CatalogProjection(
        root_id=catalog_root,
        version_root=_one(
            members, protocol.role("version"), "catalogue version"
        ),
        lifecycle_root=_one(
            members, protocol.role("lifecycle"), "catalogue lifecycle"
        ),
        digest_root=_one(
            members, protocol.role("digest"), "catalogue digest"
        ),
        definition_roots=_for_role(
            members, protocol.role("catalog-member")
        ),
    )


def verify_released_catalog(
    snapshot: Snapshot,
    protocol: AssemblyProtocol,
    catalog_root: str,
) -> CatalogProjection:
    """Reject catalogue membership or definition drift before composition."""
    cache = _CATALOG_VERIFICATION_CACHE.get()
    cache_key = (
        "catalog",
        snapshot.revision,
        id(snapshot.cells),
        protocol.root_id,
        catalog_root,
    )
    if cache is not None and cache_key in cache:
        cached = cache[cache_key]
        if type(cached) is not CatalogProjection:
            raise InvalidCell("catalogue verification cache is invalid")
        return cached
    catalog = read_catalog(snapshot, protocol, catalog_root)
    if catalog.lifecycle_root != protocol.states["released"]:
        raise InvalidCell("assembly catalogue is not released")
    if not catalog.definition_roots:
        raise InvalidCell("released catalogue contains no definitions")
    if len(catalog.definition_roots) != len(set(catalog.definition_roots)):
        raise InvalidCell("released catalogue repeats a definition")
    try:
        version = snapshot.cells[catalog.version_root].atom
        expected = snapshot.cells[catalog.digest_root].atom
    except KeyError as exc:
        raise InvalidCell("assembly catalogue metadata is missing") from exc
    if not version or not expected:
        raise InvalidCell("assembly catalogue metadata is empty")
    actual = _catalog_digest(
        snapshot,
        protocol,
        catalog.root_id,
        catalog.definition_roots,
        version,
    )
    if not hmac.compare_digest(expected, actual):
        raise InvalidCell("released assembly catalogue has drifted")
    if cache is not None:
        cache[cache_key] = catalog
    return catalog


def _relation_dependency_roots(
    snapshot: Snapshot,
    relation_root: str,
    *,
    budget: int = 100_000,
) -> set[str]:
    """Return only the physical Cells that encode one relation chain."""
    dependencies: set[str] = set()
    cursor = relation_root
    steps = 0
    while cursor != NULL_CELL_ID:
        steps += 1
        if steps > budget:
            raise InvalidCell("catalogue dependency relation exceeds its budget")
        if cursor in dependencies:
            raise InvalidCell("catalogue dependency relation contains a cycle")
        chain = snapshot.cells.get(cursor)
        if chain is None:
            raise InvalidCell("catalogue dependency relation is dangling")
        dependencies.add(cursor)
        if chain.link0 == NULL_CELL_ID:
            if chain.link1 != NULL_CELL_ID:
                raise InvalidCell("catalogue dependency relation has an invalid tail")
            break
        if chain.link0 not in snapshot.cells:
            raise InvalidCell("catalogue dependency incidence is missing")
        dependencies.add(chain.link0)
        cursor = chain.link1
    return dependencies


def _catalog_verification_dependencies(
    snapshot: Snapshot,
    protocol: AssemblyProtocol,
    catalog: CatalogProjection,
) -> frozenset[str]:
    """Collect the exact Cells read by catalogue release verification."""
    dependencies = _relation_dependency_roots(snapshot, catalog.root_id)
    dependencies.update((
        catalog.version_root,
        catalog.lifecycle_root,
        catalog.digest_root,
    ))
    pending = list(catalog.definition_roots)
    visited: set[str] = set()
    while pending:
        definition_root = pending.pop()
        if definition_root in visited:
            continue
        visited.add(definition_root)
        definition = read_definition(snapshot, protocol, definition_root)
        dependencies.update(
            _relation_dependency_roots(snapshot, definition_root)
        )
        dependencies.update((
            definition.name_root,
            definition.version_root,
            definition.lifecycle_root,
            definition.digest_root,
            *definition.part_roots,
            *definition.evidence_roots,
            *definition.obligation_roots,
        ))
        for interface_root in definition.interface_roots:
            dependencies.update(
                _relation_dependency_roots(snapshot, interface_root)
            )
        for obligation_root in definition.obligation_roots:
            dependencies.update(
                _relation_dependency_roots(snapshot, obligation_root)
            )
            obligation = read_relation(snapshot, obligation_root, budget=100_000)
            dependencies.update(
                member.participant_id for member in obligation
                if member.role_id in (
                    protocol.role("required-role"),
                    protocol.role("minimum"),
                )
            )
        pending.extend(definition.dependency_roots)
    return frozenset(dependencies)


def _ensure_stable_catalog_listener(store: CellStore) -> None:
    with _STABLE_CATALOG_VERIFICATION_CACHE_LOCK:
        if store in _STABLE_CATALOG_VERIFICATION_LISTENERS:
            return
        store_reference = ref(store)

        def invalidate(event) -> None:
            current_store = store_reference()
            if current_store is None:
                return
            with _STABLE_CATALOG_VERIFICATION_CACHE_LOCK:
                cached = _STABLE_CATALOG_VERIFICATION_CACHE.get(current_store)
                if cached is not None and not event.touched.isdisjoint(cached[2]):
                    _STABLE_CATALOG_VERIFICATION_CACHE.pop(current_store, None)

        store.subscribe(invalidate)
        _STABLE_CATALOG_VERIFICATION_LISTENERS[store] = invalidate


def verify_released_catalog_stable(
    store: CellStore,
    snapshot: Snapshot,
    protocol: AssemblyProtocol,
    catalog_root: str,
) -> CatalogProjection:
    """Reuse a release proof until a Cell read by that proof is committed."""
    if snapshot.revision != store.revision:
        return verify_released_catalog(snapshot, protocol, catalog_root)
    stable_key = (protocol.root_id, catalog_root)
    with _STABLE_CATALOG_VERIFICATION_CACHE_LOCK:
        cached = _STABLE_CATALOG_VERIFICATION_CACHE.get(store)
        if cached is not None and cached[0] == stable_key:
            catalog = cached[1]
        else:
            catalog = None
    if catalog is None:
        catalog = verify_released_catalog(snapshot, protocol, catalog_root)
        dependencies = _catalog_verification_dependencies(
            snapshot, protocol, catalog
        )
        _ensure_stable_catalog_listener(store)
        with _STABLE_CATALOG_VERIFICATION_CACHE_LOCK:
            _STABLE_CATALOG_VERIFICATION_CACHE[store] = (
                stable_key, catalog, dependencies
            )
        if snapshot.revision != store.revision:
            with _STABLE_CATALOG_VERIFICATION_CACHE_LOCK:
                current = _STABLE_CATALOG_VERIFICATION_CACHE.get(store)
                if current is not None and current[1] is catalog:
                    _STABLE_CATALOG_VERIFICATION_CACHE.pop(store, None)

    request_cache = _CATALOG_VERIFICATION_CACHE.get()
    if request_cache is not None:
        request_cache[(
            "catalog",
            snapshot.revision,
            id(snapshot.cells),
            protocol.root_id,
            catalog_root,
        )] = catalog
    return catalog


def _catalog_roots(
    snapshot: Snapshot,
    protocol: AssemblyProtocol,
    catalog_root: str,
) -> tuple[str, ...]:
    return verify_released_catalog(
        snapshot, protocol, catalog_root
    ).definition_roots


def project_catalog(
    snapshot: Snapshot,
    protocol: AssemblyProtocol,
    catalog_root: str,
) -> tuple[dict[str, object], ...]:
    result: list[dict[str, object]] = []
    catalog = verify_released_catalog(snapshot, protocol, catalog_root)
    for definition_root in catalog.definition_roots:
        definition = verify_released_definition(
            snapshot, protocol, definition_root
        )
        result.append({
            "id": definition.root_id,
            "name": snapshot.cells[definition.name_root].atom.decode("utf-8"),
            "version": snapshot.cells[definition.version_root].atom.decode("ascii"),
            "interfaces": len(definition.interface_roots),
            "parts": len(definition.part_roots),
        })
    return tuple(result)


def instantiate_catalog_definition(
    store: CellStore,
    protocol: AssemblyProtocol,
    catalog_root: str,
    definition_root: str,
) -> AssemblyInstance:
    """Clone any admitted definition using only graph-declared membership."""
    snapshot = store.snapshot()
    composed = compose_catalog_instance(
        snapshot, protocol, catalog_root, definition_root
    )
    store.commit(snapshot.revision, create=composed.cells)
    return composed.instance


def compose_relation_backed_catalog_instance(
    snapshot: Snapshot,
    protocol: AssemblyProtocol,
    catalog_root: str,
    definition_root: str,
    candidate: RelationCandidate,
    *,
    token: str | None = None,
    budget: int = 100_000,
) -> AssemblyInstanceCells:
    """Wrap one contract-valid relation as a WIP catalogue instance candidate."""
    catalog = verify_released_catalog(snapshot, protocol, catalog_root)
    if definition_root not in catalog.definition_roots:
        raise InvalidCell("definition is outside the active catalogue")
    definition = verify_released_definition(snapshot, protocol, definition_root)
    authority = resolve_relation_contract_authority(
        snapshot,
        capability_roots=definition.capability_roots,
        rule_roots=definition.rule_roots,
        budget=budget,
    )
    if (
        candidate.validation.relation_root != candidate.root_id
        or candidate.validation.contract_root != authority.contract.root_id
    ):
        raise InvalidCell("relation candidate does not match definition authority")
    candidate_ids = tuple(cell.id for cell in candidate.cells)
    if (
        not candidate_ids
        or candidate.root_id not in candidate_ids
        or len(candidate_ids) != len(set(candidate_ids))
        or any(cell_id in snapshot.cells for cell_id in candidate_ids)
    ):
        raise InvalidCell("relation candidate has an invalid isolated region")
    candidate_snapshot = overlay_read_snapshot(
        snapshot, create=candidate.cells
    )
    validate_relation(
        candidate_snapshot,
        authority.protocol,
        authority.contract.root_id,
        candidate.root_id,
        budget=budget,
    )

    token = token or uuid.uuid4().hex
    mapping_root = "assembly-instance:%s:mapping:relation" % token
    mapping = compose_relation_cells((
        (protocol.role("definition-side"), authority.contract.root_id),
        (protocol.role("instance-side"), candidate.root_id),
    ), relation_id=mapping_root)
    interface_cells: list[Cell] = []
    interface_roots: list[str] = []
    for index, constraint in enumerate(authority.contract.constraints):
        interface_root = "assembly-instance:%s:interface:%s" % (
            token, index
        )
        interface = compose_relation_cells((
            (protocol.role("interface-target"), candidate.root_id),
            (protocol.role("name"), constraint.participant_role),
            (
                protocol.role("interface-member-role"),
                constraint.participant_role,
            ),
            (
                protocol.role("interface-contract"),
                authority.contract.root_id,
            ),
            (
                protocol.role("interface-documentation"),
                constraint.root_id,
            ),
        ), relation_id=interface_root)
        interface_roots.append(interface_root)
        interface_cells.extend(interface.cells)
    instance_root = "assembly-instance:%s" % token
    instance_cells = compose_relation_cells((
        (protocol.role("provenance"), definition_root),
        (protocol.role("version"), definition.version_root),
        (protocol.role("part"), candidate.root_id),
        *((protocol.role("interface"), root) for root in interface_roots),
        (protocol.role("rule"), authority.contract.root_id),
        (protocol.role("capability"), authority.protocol.root_id),
        (protocol.role("mapping"), mapping_root),
    ), relation_id=instance_root)
    created = (
        *candidate.cells,
        *mapping.cells,
        *interface_cells,
        *instance_cells.cells,
    )
    created_ids = tuple(cell.id for cell in created)
    if (
        len(created_ids) != len(set(created_ids))
        or set(created_ids).intersection(snapshot.cells)
    ):
        raise InvalidCell("relation-backed instance identity collides")
    return AssemblyInstanceCells(
        AssemblyInstance(
            root_id=instance_root,
            definition_root=definition_root,
            cell_map=MappingProxyType({}),
        ),
        tuple(created),
    )


def compose_catalog_instance(
    snapshot: Snapshot,
    protocol: AssemblyProtocol,
    catalog_root: str,
    definition_root: str,
    *,
    token: str | None = None,
) -> AssemblyInstanceCells:
    """Compose an admitted instance for a larger caller-owned transaction."""
    catalog = verify_released_catalog(snapshot, protocol, catalog_root)
    if definition_root not in catalog.definition_roots:
        raise InvalidCell("definition is outside the active catalogue")
    definition = verify_released_definition(
        snapshot, protocol, definition_root
    )
    token = token or uuid.uuid4().hex
    translated = {
        old_id: "assembly-instance:%s:part:%s" % (token, index)
        for index, old_id in enumerate(definition.part_roots)
    }
    cells: list[Cell] = []
    for old_id in definition.part_roots:
        old = snapshot.cells[old_id]
        cells.append(Cell(
            translated[old_id],
            translated.get(old.link0, old.link0),
            translated.get(old.link1, old.link1),
            old.atom,
        ))

    mapping_roots: list[str] = []
    for index, old_id in enumerate(definition.part_roots):
        mapping_root = "assembly-instance:%s:mapping:%s" % (token, index)
        mapping = compose_relation_cells([
            (protocol.role("definition-side"), old_id),
            (protocol.role("instance-side"), translated[old_id]),
        ], relation_id=mapping_root)
        cells.extend(mapping.cells)
        mapping_roots.append(mapping_root)

    instance_root = "assembly-instance:%s" % token
    members: list[tuple[str, str]] = [
        (protocol.role("provenance"), definition_root),
        (protocol.role("version"), definition.version_root),
        *((protocol.role("part"), translated[root])
          for root in definition.part_roots),
        *((protocol.role("interface"), translated[root])
          for root in definition.interface_roots),
        *((protocol.role("state"), translated[root])
          for root in definition.state_roots),
        *((protocol.role("rule"), translated.get(root, root))
          for root in definition.rule_roots),
        *((protocol.role("status"), translated[root])
          for root in definition.status_roots),
        *((protocol.role("error"), translated[root])
          for root in definition.error_roots),
        *((protocol.role("capability"), root)
          for root in definition.capability_roots),
        *((protocol.role("mapping"), root) for root in mapping_roots),
    ]
    instance_cells = compose_relation_cells(members, relation_id=instance_root)
    cells.extend(instance_cells.cells)
    return AssemblyInstanceCells(
        AssemblyInstance(
            root_id=instance_root,
            definition_root=definition_root,
            cell_map=MappingProxyType(translated),
        ),
        tuple(cells),
    )


def open_instance(
    snapshot: Snapshot,
    protocol: AssemblyProtocol,
    instance_root: str,
) -> frozenset[str]:
    """Return the actual cloned region and mappings behind a visible node."""
    members = read_relation(snapshot, instance_root, budget=100_000)
    opened = set(_for_role(members, protocol.role("part")))
    for mapping_root in _for_role(members, protocol.role("mapping")):
        opened.add(mapping_root)
        mapping = read_relation(snapshot, mapping_root, budget=100_000)
        opened.update(member.incidence_id for member in mapping)
        opened.update(member.participant_id for member in mapping)
    return frozenset(opened)


__all__ = [
    "AssemblyProtocol",
    "InterfaceBuild",
    "ObligationBuild",
    "DefinitionBuild",
    "DefinitionProjection",
    "CatalogProjection",
    "AssemblyInstance",
    "AssemblyInstanceCells",
    "bootstrap_assembly_protocol",
    "build_interface",
    "build_role_obligation",
    "build_definition",
    "read_definition",
    "validate_definition",
    "release_definition",
    "verify_released_definition",
    "build_catalog",
    "read_catalog",
    "verify_released_catalog",
    "catalog_verification_scope",
    "with_catalog_verification_scope",
    "project_catalog",
    "compose_relation_backed_catalog_instance",
    "compose_catalog_instance",
    "instantiate_catalog_definition",
    "open_instance",
]
