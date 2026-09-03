"""Universal WIP/Shared/Published/Archive revision and promotion protocol.

The protocol is domain-neutral.  BIM information containers, geometry blobs,
database records, monetary intents, Brain records, and releases can all use the
same graph-held state bindings and transition rules.  Published history is
never edited; restore appends a new WIP revision.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from types import MappingProxyType
from typing import Iterable, Mapping
import uuid

from .cell_catalog import (
    AssemblyInstanceCells,
    AssemblyProtocol,
    build_definition,
    build_interface,
    build_role_obligation,
    read_definition,
    release_definition,
)
from .cell_attestations import CourtAttestationBroker
from .cell_protocols import (
    CellBatch,
    RelationMember,
    compose_relation_cells,
    prepare_append_relation_members,
    read_relation,
)
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


ROLE_NAMES = (
    "vocabulary-member",
    "manifest-member",
    "state-binding",
    "transition",
    "state",
    "pointer",
    "revision",
    "content",
    "content-digest",
    "predecessor",
    "branch",
    "from-state",
    "to-state",
    "required-evidence",
    "actor",
    "timestamp",
    "evidence",
    "reason",
    "history",
)


@dataclass(frozen=True, slots=True)
class LifecycleProtocol:
    root_id: str
    roles: Mapping[str, str]
    states: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown lifecycle role %r" % name) from exc


@dataclass(frozen=True, slots=True)
class LifecycleDefinition:
    definition_root: str
    manifest_root: str
    part_roots: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LifecycleInstance:
    instance_root: str
    manifest_root: str
    history_root: str
    content_interface_root: str
    state_pointers: Mapping[str, str]
    state_bindings: Mapping[str, str]
    transition_roots: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RevisionProjection:
    root_id: str
    content_root: str
    content_digest_root: str
    state_root: str
    predecessor_roots: tuple[str, ...]
    branch_root: str
    actor_root: str | None
    timestamp_root: str | None
    evidence_roots: tuple[str, ...]
    reason_root: str | None

    @property
    def predecessor_root(self) -> str | None:
        """Compatibility lens for ordinary one-parent revisions."""
        return self.predecessor_roots[0] if len(self.predecessor_roots) == 1 else None


_LIFECYCLE_REVISION_PATCH_KEY = object()


@dataclass(frozen=True, slots=True)
class LifecycleRevisionPatch:
    """Sealed lifecycle append prepared against one immutable snapshot."""

    _key: object
    expected_revision: int
    revision_root: str
    create: tuple[Cell, ...]
    replace: tuple[Cell, ...]

    def __post_init__(self) -> None:
        if self._key is not _LIFECYCLE_REVISION_PATCH_KEY:
            raise TypeError(
                "lifecycle revision patches can only be prepared by protocol"
            )


def bootstrap_lifecycle_protocol(
    store: CellStore,
    *,
    prefix: str = "lifecycle-protocol",
) -> LifecycleProtocol:
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    states = {
        "wip": prefix + ":state:wip",
        "shared": prefix + ":state:shared",
        "published": prefix + ":state:published",
        "archived": prefix + ":state:archived",
    }
    batch = CellBatch(store)
    for name, root in roles.items():
        batch.add(Cell(root, NULL_CELL_ID, NULL_CELL_ID, name.encode("ascii")))
    for name, root in states.items():
        batch.add(Cell(root, NULL_CELL_ID, NULL_CELL_ID, name.upper().encode("ascii")))
    root_id = prefix + ":root"
    batch.relation([
        *((roles["vocabulary-member"], root) for root in roles.values()),
        *((roles["vocabulary-member"], root) for root in states.values()),
    ], relation_id=root_id)
    batch.commit()
    return LifecycleProtocol(
        root_id, MappingProxyType(roles), MappingProxyType(states)
    )


def _relation_into(
    batch: CellBatch,
    members: Iterable[tuple[str, str]],
    root_id: str,
) -> tuple[str, ...]:
    built = compose_relation_cells(members, relation_id=root_id)
    for cell in built.cells:
        batch.add(cell)
    return tuple(cell.id for cell in built.cells)


def build_versioned_asset_definition(
    store: CellStore,
    assembly: AssemblyProtocol,
    lifecycle: LifecycleProtocol,
    *,
    prefix: str = "versioned-asset",
    name: str = "Versioned Asset",
    version: str = "2.0.0",
    contract: str = (
        "immutable multi-head revision DAG; evidence-gated promotion; "
        "append-only restore"
    ),
    documentation: str = (
        "Versioned Asset: branches and WIP, Shared, Published, Archive heads "
        "are governed revisions"
    ),
    presentation: str = "standard-library/versioned-asset",
    operational_evidence: str = "tests_replica/test_cell_lifecycle.py",
    extra_part_roots: Iterable[str] = (),
    extra_interface_roots: Iterable[str] = (),
    extra_state_roots: Iterable[str] = (),
    extra_rule_roots: Iterable[str] = (),
    extra_capability_roots: Iterable[str] = (),
    extra_status_roots: Iterable[str] = (),
    extra_error_roots: Iterable[str] = (),
    extra_evidence_roots: Iterable[str] = (),
    extra_obligation_roots: Iterable[str] = (),
    extra_shared_roots: Iterable[str] = (),
) -> LifecycleDefinition:
    """Release a reusable assembly whose behavior is declared by graph rules."""
    initial_content = prefix + ":initial-content"
    initial_digest = prefix + ":initial-content-digest"
    initial_branch = prefix + ":branch:main"
    initial_actor = prefix + ":actor:system"
    initial_revision = prefix + ":initial-revision"
    history_root = prefix + ":history"
    status_root = prefix + ":status"
    error_root = prefix + ":error"
    interface_name = prefix + ":interface-name"
    contract_root = prefix + ":contract"
    presentation_root = prefix + ":presentation"
    documentation_root = prefix + ":documentation"
    evidence_root = prefix + ":court-evidence"
    batch = CellBatch(store)
    for root, atom in (
        (initial_content, b""),
        (initial_digest, hashlib.sha256(b"").hexdigest().encode("ascii")),
        (initial_branch, b"main"),
        (initial_actor, b"system"),
        (status_root, b"WIP"),
        (error_root, b""),
        (interface_name, b"content"),
        (
            contract_root,
            contract.encode("utf-8"),
        ),
        (presentation_root, presentation.encode("utf-8")),
        (
            documentation_root,
            documentation.encode("utf-8"),
        ),
        (
            evidence_root,
            operational_evidence.encode("utf-8"),
        ),
    ):
        batch.add(Cell(root, NULL_CELL_ID, NULL_CELL_ID, atom))

    parts: list[str] = [
        initial_content, initial_digest, initial_branch, initial_actor,
        status_root, error_root, interface_name, contract_root,
        presentation_root, documentation_root,
    ]
    parts.extend(_relation_into(batch, [
        (lifecycle.role("content"), initial_content),
        (lifecycle.role("content-digest"), initial_digest),
        (lifecycle.role("state"), lifecycle.states["wip"]),
        (lifecycle.role("branch"), initial_branch),
        (lifecycle.role("actor"), initial_actor),
    ], initial_revision))

    state_pointers: dict[str, str] = {}
    binding_roots: list[str] = []
    for state_name, state_root in lifecycle.states.items():
        pointer_root = "%s:pointer:%s" % (prefix, state_name)
        pointer_members = (
            [(lifecycle.role("revision"), initial_revision)]
            if state_name == "wip" else []
        )
        parts.extend(_relation_into(batch, pointer_members, pointer_root))
        binding_root = "%s:state-binding:%s" % (prefix, state_name)
        parts.extend(_relation_into(batch, [
            (lifecycle.role("state"), state_root),
            (lifecycle.role("pointer"), pointer_root),
        ], binding_root))
        state_pointers[state_root] = pointer_root
        binding_roots.append(binding_root)

    transition_roots: list[str] = []
    for transition_name, source, target in (
        ("share", lifecycle.states["wip"], lifecycle.states["shared"]),
        ("publish", lifecycle.states["shared"], lifecycle.states["published"]),
        ("archive", lifecycle.states["published"], lifecycle.states["archived"]),
    ):
        transition_root = "%s:transition:%s" % (prefix, transition_name)
        parts.extend(_relation_into(batch, [
            (lifecycle.role("from-state"), source),
            (lifecycle.role("to-state"), target),
            (lifecycle.role("required-evidence"), lifecycle.role("evidence")),
        ], transition_root))
        transition_roots.append(transition_root)

    parts.extend(_relation_into(batch, [
        (lifecycle.role("revision"), initial_revision),
    ], history_root))
    manifest_root = prefix + ":manifest"
    parts.extend(_relation_into(batch, [
        *((lifecycle.role("state-binding"), root) for root in binding_roots),
        *((lifecycle.role("transition"), root) for root in transition_roots),
        (lifecycle.role("history"), history_root),
    ], manifest_root))
    batch.commit()

    interface = build_interface(
        store,
        assembly,
        interface_id=prefix + ":interface:content",
        target_root=initial_content,
        name_root=interface_name,
        contract_root=contract_root,
        presentation_root=presentation_root,
        documentation_root=documentation_root,
    )
    parts.extend(interface.part_roots)
    manifest_snapshot = store.snapshot()
    manifest_patch = prepare_append_relation_members(
        manifest_snapshot,
        manifest_root,
        ((lifecycle.role("content"), interface.root_id),),
        budget=100_000,
    )
    store.commit(
        manifest_snapshot.revision,
        create=manifest_patch.create,
        replace=manifest_patch.replace,
    )
    parts.extend(cell.id for cell in manifest_patch.create)
    obligations = tuple(
        build_role_obligation(
            store,
            assembly,
            obligation_id=prefix + ":obligation:" + role,
            required_role=assembly.role(role),
        ).root_id
        for role in ("state", "rule", "status", "error")
    )
    parts.extend(extra_part_roots)
    definition = build_definition(
        store,
        assembly,
        definition_id=prefix + ":definition",
        name=name,
        version=version,
        part_roots=tuple(dict.fromkeys(parts)),
        interface_roots=(interface.root_id, *extra_interface_roots),
        state_roots=(
            initial_content, initial_digest, initial_branch, initial_actor,
            initial_revision, history_root,
            *state_pointers.values(), status_root, error_root,
            *extra_state_roots,
        ),
        rule_roots=(manifest_root, *transition_roots, *extra_rule_roots),
        capability_roots=(lifecycle.root_id, *extra_capability_roots),
        status_roots=(status_root, *extra_status_roots),
        error_roots=(error_root, *extra_error_roots),
        evidence_roots=(evidence_root, *extra_evidence_roots),
        obligation_roots=(*obligations, *extra_obligation_roots),
        shared_roots=(
            *lifecycle.roles.values(),
            *lifecycle.states.values(),
            lifecycle.root_id,
            *extra_shared_roots,
        ),
    )
    release_definition(store, assembly, definition.root_id)
    return LifecycleDefinition(
        definition.root_id, manifest_root, tuple(parts)
    )


def _for_role(members: Iterable[RelationMember], role: str) -> tuple[str, ...]:
    return tuple(member.participant_id for member in members if member.role_id == role)


def _one(members: tuple[RelationMember, ...], role: str, label: str) -> str:
    values = _for_role(members, role)
    if len(values) != 1:
        raise InvalidCell("lifecycle graph requires exactly one %s" % label)
    return values[0]


def read_lifecycle_instance(
    snapshot: Snapshot,
    assembly: AssemblyProtocol,
    lifecycle: LifecycleProtocol,
    instance_root: str,
) -> LifecycleInstance:
    instance_members = read_relation(snapshot, instance_root, budget=100_000)
    if lifecycle.root_id not in _for_role(
        instance_members, assembly.role("capability")
    ):
        raise InvalidCell("assembly instance has no lifecycle capability")
    manifests = []
    for rule_root in _for_role(instance_members, assembly.role("rule")):
        members = read_relation(snapshot, rule_root, budget=100_000)
        if _for_role(members, lifecycle.role("history")):
            manifests.append((rule_root, members))
    if len(manifests) != 1:
        raise InvalidCell("lifecycle instance requires one manifest")
    manifest_root, manifest_members = manifests[0]
    history_root = _one(
        manifest_members, lifecycle.role("history"), "history"
    )
    state_pointers: dict[str, str] = {}
    state_bindings: dict[str, str] = {}
    for binding_root in _for_role(
        manifest_members, lifecycle.role("state-binding")
    ):
        binding = read_relation(snapshot, binding_root, budget=32)
        state_root = _one(binding, lifecycle.role("state"), "binding state")
        pointer_root = _one(binding, lifecycle.role("pointer"), "state pointer")
        if state_root in state_pointers:
            raise InvalidCell("lifecycle repeats a state binding")
        state_pointers[state_root] = pointer_root
        state_bindings[state_root] = binding_root
    if set(state_pointers) != set(lifecycle.states.values()):
        raise InvalidCell("lifecycle state bindings are incomplete")
    content_interfaces = _for_role(
        manifest_members, lifecycle.role("content")
    )
    if not content_interfaces:
        revision_roots = _for_role(
            read_relation(snapshot, history_root, budget=100_000),
            lifecycle.role("revision"),
        )
        content_roots = {
            _one(
                read_relation(snapshot, revision_root, budget=100_000),
                lifecycle.role("content"),
                "revision content",
            )
            for revision_root in revision_roots
        }
        content_interfaces = tuple(
            interface_root
            for interface_root in _for_role(
                instance_members, assembly.role("interface")
            )
            if _one(
                read_relation(snapshot, interface_root, budget=100_000),
                assembly.role("interface-target"),
                "interface target",
            ) in content_roots
        )
    if len(content_interfaces) != 1:
        raise InvalidCell("lifecycle instance requires one content interface")
    return LifecycleInstance(
        instance_root,
        manifest_root,
        history_root,
        content_interfaces[0],
        MappingProxyType(state_pointers),
        MappingProxyType(state_bindings),
        _for_role(manifest_members, lifecycle.role("transition")),
    )


def graph_content_bytes(
    snapshot: Snapshot,
    content_root: str,
    *,
    budget: int = 100_000,
) -> bytes:
    """Canonical court input for scalar content or a reachable Cell assembly.

    Terminal values remain their original atom bytes.  For a wired root, every
    reachable identity, link, and atom is length-framed in stable identity
    order. This exact byte string can be inspected by a court and then hashed.
    """
    if budget < 1:
        raise InvalidCell("graph content digest budget must be positive")
    try:
        root = snapshot.cells[content_root]
    except KeyError as exc:
        raise InvalidCell("lifecycle content root is missing") from exc
    if root.link0 == NULL_CELL_ID and root.link1 == NULL_CELL_ID:
        return root.atom

    reached: dict[str, Cell] = {}
    pending = [content_root]
    while pending:
        root_id = pending.pop()
        if root_id in reached:
            continue
        if len(reached) >= budget:
            raise InvalidCell("graph content digest exceeded its cell budget")
        try:
            cell = snapshot.cells[root_id]
        except KeyError as exc:
            raise InvalidCell("graph content contains a dangling link") from exc
        reached[root_id] = cell
        if cell.link0 != NULL_CELL_ID:
            pending.append(cell.link0)
        if cell.link1 != NULL_CELL_ID:
            pending.append(cell.link1)

    canonical = bytearray(b"ArchHub/universal-cell-graph-content/v1\x00")

    def field(value: bytes) -> None:
        canonical.extend(len(value).to_bytes(8, "big"))
        canonical.extend(value)

    field(content_root.encode("utf-8"))
    for cell_id in sorted(reached):
        cell = reached[cell_id]
        field(cell.id.encode("utf-8"))
        field(cell.link0.encode("utf-8"))
        field(cell.link1.encode("utf-8"))
        field(cell.atom)
        if len(canonical) > 64 * 1024 * 1024:
            raise InvalidCell("graph content canonical form exceeds 64 MiB")
    return bytes(canonical)


def graph_content_digest(
    snapshot: Snapshot,
    content_root: str,
    *,
    budget: int = 100_000,
) -> bytes:
    """SHA-256 fingerprint of the exact bytes a lifecycle court inspects."""
    return hashlib.sha256(graph_content_bytes(
        snapshot, content_root, budget=budget
    )).hexdigest().encode("ascii")


def read_revision(
    snapshot: Snapshot,
    lifecycle: LifecycleProtocol,
    revision_root: str,
) -> RevisionProjection:
    members = read_relation(snapshot, revision_root, budget=1024)
    def optional(role: str, label: str) -> str | None:
        values = _for_role(members, lifecycle.role(role))
        if len(values) > 1:
            raise InvalidCell("revision repeats %s" % label)
        return values[0] if values else None
    content_root = _one(
        members, lifecycle.role("content"), "revision content"
    )
    digest_root = _one(
        members,
        lifecycle.role("content-digest"),
        "revision content digest",
    )
    expected_digest = graph_content_digest(snapshot, content_root)
    if snapshot.cells[digest_root].atom != expected_digest:
        raise InvalidCell("revision content digest does not match content")
    return RevisionProjection(
        revision_root,
        content_root,
        digest_root,
        _one(members, lifecycle.role("state"), "revision state"),
        _for_role(members, lifecycle.role("predecessor")),
        _one(members, lifecycle.role("branch"), "revision branch"),
        optional("actor", "actor"),
        optional("timestamp", "timestamp"),
        _for_role(members, lifecycle.role("evidence")),
        optional("reason", "reason"),
    )


def seed_composed_lifecycle_content(
    snapshot: Snapshot,
    assembly: AssemblyProtocol,
    lifecycle: LifecycleProtocol,
    composed: AssemblyInstanceCells,
    content: bytes,
    *,
    actor_root: str | None = None,
) -> AssemblyInstanceCells:
    """Seed a newly composed lifecycle instance without a second commit.

    ``actor_root`` makes first-user-action instances retain the real author
    instead of inheriting the catalogue definition's system actor.
    """
    if actor_root is not None and actor_root not in snapshot.cells:
        raise InvalidCell("initial lifecycle actor is missing")
    definition = read_definition(
        snapshot, assembly, composed.instance.definition_root
    )
    manifests = []
    for definition_root in definition.rule_roots:
        members = read_relation(snapshot, definition_root, budget=100_000)
        histories = _for_role(members, lifecycle.role("history"))
        if histories:
            manifests.append(histories)
    if len(manifests) != 1 or len(manifests[0]) != 1:
        raise InvalidCell(
            "composed lifecycle definition requires one manifest history"
        )
    history_members = read_relation(
        snapshot, manifests[0][0], budget=100_000
    )
    revision_roots = _for_role(
        history_members, lifecycle.role("revision")
    )
    candidates = [
        read_revision(snapshot, lifecycle, root) for root in revision_roots
    ]
    candidates = [
        revision for revision in candidates
        if revision.state_root == lifecycle.states["wip"]
        and not revision.predecessor_roots
    ]
    if len(candidates) != 1:
        raise InvalidCell(
            "composed lifecycle definition requires one initial WIP revision"
        )
    initial = candidates[0]
    try:
        content_root = composed.instance.cell_map[initial.content_root]
        digest_root = composed.instance.cell_map[initial.content_digest_root]
    except KeyError as exc:
        raise InvalidCell(
            "initial lifecycle content is outside the cloned region"
        ) from exc
    payload = bytes(content)
    atom_replacements = {
        content_root: payload,
        digest_root: hashlib.sha256(payload).hexdigest().encode("ascii"),
    }
    participant_replacements: dict[str, str] = {}
    if actor_root is not None:
        initial_members = read_relation(
            snapshot, initial.root_id, budget=1024
        )
        actor_members = tuple(
            member for member in initial_members
            if member.role_id == lifecycle.role("actor")
        )
        if len(actor_members) != 1:
            raise InvalidCell(
                "initial lifecycle revision has no unique actor"
            )
        try:
            actor_incidence = composed.instance.cell_map[
                actor_members[0].incidence_id
            ]
        except KeyError as exc:
            raise InvalidCell(
                "initial lifecycle actor is outside the cloned region"
            ) from exc
        participant_replacements[actor_incidence] = actor_root
    found = set()
    actor_found = set()
    cells = []
    for cell in composed.cells:
        atom = atom_replacements.get(cell.id)
        participant = participant_replacements.get(cell.id)
        if atom is None and participant is None:
            cells.append(cell)
            continue
        if atom is not None:
            found.add(cell.id)
        if participant is not None:
            actor_found.add(cell.id)
        cells.append(Cell(
            cell.id,
            cell.link0,
            participant if participant is not None else cell.link1,
            atom if atom is not None else cell.atom,
        ))
    if found != set(atom_replacements):
        raise InvalidCell("composed lifecycle content cells are missing")
    if actor_found != set(participant_replacements):
        raise InvalidCell("composed lifecycle actor incidence is missing")
    return AssemblyInstanceCells(composed.instance, tuple(cells))


def state_heads(
    snapshot: Snapshot,
    lifecycle: LifecycleProtocol,
    pointer_root: str,
) -> tuple[str, ...]:
    """Read the immutable set of revision heads for one lifecycle state."""
    members = read_relation(snapshot, pointer_root, budget=100_000)
    revisions = _for_role(members, lifecycle.role("revision"))
    if len(revisions) != len(set(revisions)):
        raise InvalidCell("lifecycle state head set repeats a revision")
    return revisions


def lifecycle_history(
    snapshot: Snapshot,
    lifecycle: LifecycleProtocol,
    instance: LifecycleInstance,
) -> tuple[str, ...]:
    return _for_role(
        read_relation(snapshot, instance.history_root, budget=100_000),
        lifecycle.role("revision"),
    )


def _new_revision_cells(
    lifecycle: LifecycleProtocol,
    *,
    content_root: str,
    content_digest_root: str,
    state_root: str,
    predecessor_roots: tuple[str, ...],
    branch_root: str,
    actor_root: str,
    evidence_roots: tuple[str, ...],
    reason: str | None,
) -> tuple[str, tuple[Cell, ...]]:
    token = uuid.uuid4().hex
    revision_root = "lifecycle:revision:" + token
    timestamp_root = "lifecycle:timestamp:" + token
    cells = [Cell(
        timestamp_root,
        NULL_CELL_ID,
        NULL_CELL_ID,
        datetime.now(timezone.utc).isoformat().encode("ascii"),
    )]
    reason_root = None
    if reason is not None:
        reason_root = "lifecycle:reason:" + token
        cells.append(Cell(
            reason_root, NULL_CELL_ID, NULL_CELL_ID, reason.encode("utf-8")
        ))
    members = [
        (lifecycle.role("content"), content_root),
        (lifecycle.role("content-digest"), content_digest_root),
        (lifecycle.role("state"), state_root),
        (lifecycle.role("branch"), branch_root),
        (lifecycle.role("actor"), actor_root),
        (lifecycle.role("timestamp"), timestamp_root),
        *((lifecycle.role("predecessor"), root) for root in predecessor_roots),
        *((lifecycle.role("evidence"), root) for root in evidence_roots),
    ]
    if reason_root is not None:
        members.append((lifecycle.role("reason"), reason_root))
    relation = compose_relation_cells(members, relation_id=revision_root)
    cells.extend(relation.cells)
    return revision_root, tuple(cells)


def _prepare_revision_append(
    snapshot: Snapshot,
    assembly: AssemblyProtocol,
    lifecycle: LifecycleProtocol,
    instance: LifecycleInstance,
    *,
    state_root: str,
    next_head_roots: tuple[str, ...],
    revision_root: str,
    revision_cells: tuple[Cell, ...],
    active_content_root: str | None = None,
) -> LifecycleRevisionPatch:
    if revision_root not in next_head_roots:
        raise InvalidCell("new lifecycle revision must become a state head")
    if len(next_head_roots) != len(set(next_head_roots)):
        raise InvalidCell("lifecycle next head set repeats a revision")
    pointer = compose_relation_cells(
        (
            (lifecycle.role("revision"), head_root)
            for head_root in next_head_roots
        ),
        relation_id="lifecycle:pointer:" + uuid.uuid4().hex,
    )
    history_patch = prepare_append_relation_members(
        snapshot,
        instance.history_root,
        ((lifecycle.role("revision"), revision_root),),
        budget=100_000,
    )
    instance_patch = prepare_append_relation_members(
        snapshot,
        instance.instance_root,
        (
            (assembly.role("part"), cell.id)
            for cell in (*revision_cells, *pointer.cells)
        ),
        budget=100_000,
    )
    binding_root = instance.state_bindings[state_root]
    binding_members = read_relation(snapshot, binding_root, budget=32)
    pointer_members = tuple(
        member for member in binding_members
        if member.role_id == lifecycle.role("pointer")
    )
    if len(pointer_members) != 1:
        raise InvalidCell("lifecycle state binding has no unique pointer")
    pointer_incidence = snapshot.cells[pointer_members[0].incidence_id]
    replacements = {
        cell.id: cell for cell in (
            *history_patch.replace, *instance_patch.replace,
            Cell(
                pointer_incidence.id,
                pointer_incidence.link0,
                pointer.build.root_id,
                pointer_incidence.atom,
            ),
        )
    }
    if active_content_root is not None:
        interface_members = read_relation(
            snapshot, instance.content_interface_root, budget=100_000
        )
        target_members = tuple(
            member for member in interface_members
            if member.role_id == assembly.role("interface-target")
        )
        if len(target_members) != 1:
            raise InvalidCell("lifecycle content interface has no unique target")
        target_incidence = snapshot.cells[target_members[0].incidence_id]
        replacements[target_incidence.id] = Cell(
            target_incidence.id,
            target_incidence.link0,
            active_content_root,
            target_incidence.atom,
        )
    return LifecycleRevisionPatch(
        _LIFECYCLE_REVISION_PATCH_KEY,
        snapshot.revision,
        revision_root,
        (
            *revision_cells,
            *pointer.cells,
            *history_patch.create,
            *instance_patch.create,
        ),
        tuple(replacements.values()),
    )


def _append_revision(
    store: CellStore,
    snapshot: Snapshot,
    assembly: AssemblyProtocol,
    lifecycle: LifecycleProtocol,
    instance: LifecycleInstance,
    *,
    state_root: str,
    next_head_roots: tuple[str, ...],
    revision_root: str,
    revision_cells: tuple[Cell, ...],
    active_content_root: str | None = None,
) -> int:
    patch = _prepare_revision_append(
        snapshot,
        assembly,
        lifecycle,
        instance,
        state_root=state_root,
        next_head_roots=next_head_roots,
        revision_root=revision_root,
        revision_cells=revision_cells,
        active_content_root=active_content_root,
    )
    return store.commit(
        patch.expected_revision,
        create=patch.create,
        replace=patch.replace,
    )


def append_wip_revision(
    store: CellStore,
    assembly: AssemblyProtocol,
    lifecycle: LifecycleProtocol,
    instance_root: str,
    *,
    content: bytes,
    actor_root: str,
    base_revision_root: str | None = None,
    branch_root: str | None = None,
    reason: str = "edit",
) -> str:
    snapshot = store.snapshot()
    if actor_root not in snapshot.cells:
        raise InvalidCell("lifecycle actor is missing")
    instance = read_lifecycle_instance(
        snapshot, assembly, lifecycle, instance_root
    )
    wip_state = lifecycle.states["wip"]
    predecessor, current_heads = _resolve_base_revision(
        snapshot,
        lifecycle,
        instance,
        state_root=wip_state,
        base_revision_root=base_revision_root,
    )
    branch = _resolve_branch_root(
        snapshot, lifecycle, predecessor, branch_root
    )
    content_root, digest_root, content_cells = _content_cells(content)
    revision_root, revision_cells = _new_revision_cells(
        lifecycle,
        content_root=content_root,
        content_digest_root=digest_root,
        state_root=wip_state,
        predecessor_roots=(predecessor,) if predecessor else (),
        branch_root=branch,
        actor_root=actor_root,
        evidence_roots=(),
        reason=reason,
    )
    next_heads = tuple(
        head for head in current_heads if head != predecessor
    ) + (revision_root,)
    _append_revision(
        store, snapshot, assembly, lifecycle, instance,
        state_root=wip_state,
        next_head_roots=next_heads,
        revision_root=revision_root,
        revision_cells=(*content_cells, *revision_cells),
        active_content_root=content_root,
    )
    return revision_root


def append_wip_graph_revision(
    store: CellStore,
    assembly: AssemblyProtocol,
    lifecycle: LifecycleProtocol,
    instance_root: str,
    *,
    content_root: str,
    actor_root: str,
    base_revision_root: str | None = None,
    branch_root: str | None = None,
    reason: str = "edit graph assembly",
    digest_budget: int = 100_000,
) -> str:
    """Append WIP whose content is an existing wired Cell assembly."""
    snapshot = store.snapshot()
    if actor_root not in snapshot.cells:
        raise InvalidCell("lifecycle actor is missing")
    digest_value = graph_content_digest(
        snapshot, content_root, budget=digest_budget
    )
    instance = read_lifecycle_instance(
        snapshot, assembly, lifecycle, instance_root
    )
    wip_state = lifecycle.states["wip"]
    predecessor, current_heads = _resolve_base_revision(
        snapshot,
        lifecycle,
        instance,
        state_root=wip_state,
        base_revision_root=base_revision_root,
    )
    branch = _resolve_branch_root(
        snapshot, lifecycle, predecessor, branch_root
    )
    digest_root = "lifecycle:content-digest:" + uuid.uuid4().hex
    revision_root, revision_cells = _new_revision_cells(
        lifecycle,
        content_root=content_root,
        content_digest_root=digest_root,
        state_root=wip_state,
        predecessor_roots=(predecessor,) if predecessor else (),
        branch_root=branch,
        actor_root=actor_root,
        evidence_roots=(),
        reason=reason,
    )
    next_heads = tuple(
        head for head in current_heads if head != predecessor
    ) + (revision_root,)
    _append_revision(
        store,
        snapshot,
        assembly,
        lifecycle,
        instance,
        state_root=wip_state,
        next_head_roots=next_heads,
        revision_root=revision_root,
        revision_cells=(
            Cell(
                digest_root,
                NULL_CELL_ID,
                NULL_CELL_ID,
                digest_value,
            ),
            *revision_cells,
        ),
        active_content_root=content_root,
    )
    return revision_root


def _content_cells(content: bytes) -> tuple[str, str, tuple[Cell, ...]]:
    token = uuid.uuid4().hex
    content_root = "lifecycle:content:" + token
    digest_root = "lifecycle:content-digest:" + token
    payload = bytes(content)
    return content_root, digest_root, (
        Cell(content_root, NULL_CELL_ID, NULL_CELL_ID, payload),
        Cell(
            digest_root,
            NULL_CELL_ID,
            NULL_CELL_ID,
            hashlib.sha256(payload).hexdigest().encode("ascii"),
        ),
    )


def _resolve_base_revision(
    snapshot: Snapshot,
    lifecycle: LifecycleProtocol,
    instance: LifecycleInstance,
    *,
    state_root: str,
    base_revision_root: str | None,
) -> tuple[str | None, tuple[str, ...]]:
    heads = state_heads(
        snapshot, lifecycle, instance.state_pointers[state_root]
    )
    base = base_revision_root
    if base is None:
        if len(heads) > 1:
            raise InvalidCell(
                "lifecycle state has multiple heads; select an explicit base"
            )
        base = heads[0] if heads else None
    if base is None:
        return None, heads
    if base not in lifecycle_history(snapshot, lifecycle, instance):
        raise InvalidCell("lifecycle base revision is outside history")
    if read_revision(snapshot, lifecycle, base).state_root != state_root:
        raise InvalidCell("lifecycle base revision belongs to another state")
    return base, heads


def _resolve_branch_root(
    snapshot: Snapshot,
    lifecycle: LifecycleProtocol,
    predecessor_root: str | None,
    requested_branch_root: str | None,
) -> str:
    if requested_branch_root is not None:
        if requested_branch_root not in snapshot.cells:
            raise InvalidCell("lifecycle branch is missing")
        return requested_branch_root
    if predecessor_root is None:
        raise InvalidCell("a root lifecycle revision requires a branch")
    return read_revision(
        snapshot, lifecycle, predecessor_root
    ).branch_root


def merge_wip_revisions(
    store: CellStore,
    assembly: AssemblyProtocol,
    lifecycle: LifecycleProtocol,
    instance_root: str,
    *,
    parent_revision_roots: Iterable[str],
    content: bytes,
    actor_root: str,
    evidence_roots: Iterable[str],
    evidence_receipts: Iterable[object],
    attestation_broker: CourtAttestationBroker,
    branch_root: str | None = None,
) -> str:
    """Resolve selected WIP heads into one explicit multi-parent revision."""
    snapshot = store.snapshot()
    parents = tuple(dict.fromkeys(parent_revision_roots))
    evidence = tuple(dict.fromkeys(evidence_roots))
    receipts = tuple(evidence_receipts)
    if len(parents) < 2:
        raise InvalidCell("a lifecycle merge requires at least two parents")
    if len(parents) > 256:
        raise InvalidCell("a lifecycle merge exceeds the parent budget")
    if actor_root not in snapshot.cells or any(
        root not in snapshot.cells for root in evidence
    ):
        raise InvalidCell("merge actor or evidence is missing")
    if not evidence or len(receipts) != len(evidence):
        raise InvalidCell(
            "a lifecycle merge requires one consumed court receipt per evidence"
        )
    instance = read_lifecycle_instance(
        snapshot, assembly, lifecycle, instance_root
    )
    wip_state = lifecycle.states["wip"]
    current_heads = state_heads(
        snapshot, lifecycle, instance.state_pointers[wip_state]
    )
    if any(parent not in current_heads for parent in parents):
        raise InvalidCell("a lifecycle merge parent is not a current WIP head")
    payload = bytes(content)
    parents_digest = hashlib.sha256(
        "\0".join(parents).encode("utf-8")
    ).hexdigest()
    content_digest = hashlib.sha256(payload).hexdigest()
    parameters = {
        "asset": instance_root,
        "targetState": wip_state,
        "parentsDigest": parents_digest,
    }
    purpose = "merge:%s:%s" % (instance_root, parents_digest)
    for evidence_root, receipt in zip(evidence, receipts):
        attestation_broker.authorize_consumed_evidence(
            receipt,
            evidence_root=evidence_root,
            purpose=purpose,
            expected_subject_name=instance_root,
            expected_subject_digest=content_digest,
            expected_parameters=parameters,
        )
    branch = _resolve_branch_root(
        snapshot, lifecycle, parents[0], branch_root
    )
    content_root, digest_root, content_cells = _content_cells(payload)
    revision_root, revision_cells = _new_revision_cells(
        lifecycle,
        content_root=content_root,
        content_digest_root=digest_root,
        state_root=wip_state,
        predecessor_roots=parents,
        branch_root=branch,
        actor_root=actor_root,
        evidence_roots=evidence,
        reason="merge",
    )
    next_heads = tuple(
        head for head in current_heads if head not in parents
    ) + (revision_root,)
    _append_revision(
        store, snapshot, assembly, lifecycle, instance,
        state_root=wip_state,
        next_head_roots=next_heads,
        revision_root=revision_root,
        revision_cells=(*content_cells, *revision_cells),
        active_content_root=content_root,
    )
    return revision_root


def prepare_promotion_revision(
    snapshot: Snapshot,
    assembly: AssemblyProtocol,
    lifecycle: LifecycleProtocol,
    instance_root: str,
    *,
    target_state_root: str,
    source_revision_root: str | None = None,
    actor_root: str,
    evidence_roots: Iterable[str],
    evidence_receipts: Iterable[object],
    attestation_broker: CourtAttestationBroker,
) -> LifecycleRevisionPatch:
    """Prepare one court-authorized promotion for an atomic wider commit."""
    evidence = tuple(dict.fromkeys(evidence_roots))
    receipts = tuple(evidence_receipts)
    if actor_root not in snapshot.cells or any(root not in snapshot.cells for root in evidence):
        raise InvalidCell("promotion actor or evidence is missing")
    if not evidence or len(receipts) != len(evidence):
        raise InvalidCell(
            "promotion requires one consumed court receipt per evidence root"
        )
    instance = read_lifecycle_instance(
        snapshot, assembly, lifecycle, instance_root
    )
    matching = []
    for transition_root in instance.transition_roots:
        transition = read_relation(snapshot, transition_root, budget=16)
        to_state = _one(
            transition, lifecycle.role("to-state"), "transition target"
        )
        if to_state == target_state_root:
            matching.append(transition)
    if len(matching) != 1:
        raise InvalidCell("target state has no unique admitted transition")
    transition = matching[0]
    source_state = _one(
        transition, lifecycle.role("from-state"), "transition source"
    )
    if _for_role(transition, lifecycle.role("required-evidence")) and not evidence:
        raise InvalidCell("lifecycle transition requires evidence")
    source_heads = state_heads(
        snapshot, lifecycle, instance.state_pointers[source_state]
    )
    if not source_heads:
        raise InvalidCell("lifecycle source state has no revision")
    if source_revision_root is None:
        if len(source_heads) > 1:
            raise InvalidCell(
                "lifecycle source state has multiple heads; select one"
            )
        source_revision_root = source_heads[0]
    elif source_revision_root not in source_heads:
        raise InvalidCell("promotion source is not a current state head")
    source_revision = read_revision(snapshot, lifecycle, source_revision_root)
    target_heads = state_heads(
        snapshot, lifecycle, instance.state_pointers[target_state_root]
    )
    if any(
        source_revision_root in read_revision(
            snapshot, lifecycle, target_root
        ).predecessor_roots
        for target_root in target_heads
    ):
        raise InvalidCell("lifecycle source revision was already promoted")
    try:
        source_digest = snapshot.cells[
            source_revision.content_digest_root
        ].atom.decode("ascii")
    except (KeyError, UnicodeDecodeError) as exc:
        raise InvalidCell("lifecycle source digest is invalid") from exc
    parameters = {
        "asset": instance_root,
        "targetState": target_state_root,
    }
    purpose = "promote:%s:%s" % (instance_root, target_state_root)
    for evidence_root, receipt in zip(evidence, receipts):
        attestation_broker.authorize_consumed_evidence(
            receipt,
            evidence_root=evidence_root,
            purpose=purpose,
            expected_subject_name=source_revision_root,
            expected_subject_digest=source_digest,
            expected_parameters=parameters,
        )
    revision_root, revision_cells = _new_revision_cells(
        lifecycle,
        content_root=source_revision.content_root,
        content_digest_root=source_revision.content_digest_root,
        state_root=target_state_root,
        predecessor_roots=(source_revision_root,),
        branch_root=source_revision.branch_root,
        actor_root=actor_root,
        evidence_roots=evidence,
        reason="promotion",
    )
    return _prepare_revision_append(
        snapshot, assembly, lifecycle, instance,
        state_root=target_state_root,
        next_head_roots=(*target_heads, revision_root),
        revision_root=revision_root,
        revision_cells=revision_cells,
    )


def promote_revision(
    store: CellStore,
    assembly: AssemblyProtocol,
    lifecycle: LifecycleProtocol,
    instance_root: str,
    *,
    target_state_root: str,
    source_revision_root: str | None = None,
    actor_root: str,
    evidence_roots: Iterable[str],
    evidence_receipts: Iterable[object],
    attestation_broker: CourtAttestationBroker,
) -> str:
    patch = prepare_promotion_revision(
        store.snapshot(),
        assembly,
        lifecycle,
        instance_root,
        target_state_root=target_state_root,
        source_revision_root=source_revision_root,
        actor_root=actor_root,
        evidence_roots=evidence_roots,
        evidence_receipts=evidence_receipts,
        attestation_broker=attestation_broker,
    )
    store.commit(
        patch.expected_revision,
        create=patch.create,
        replace=patch.replace,
    )
    return patch.revision_root


def restore_revision_as_wip(
    store: CellStore,
    assembly: AssemblyProtocol,
    lifecycle: LifecycleProtocol,
    instance_root: str,
    historical_revision_root: str,
    *,
    actor_root: str,
    base_revision_root: str | None = None,
    branch_root: str | None = None,
) -> str:
    snapshot = store.snapshot()
    if actor_root not in snapshot.cells:
        raise InvalidCell("lifecycle actor is missing")
    instance = read_lifecycle_instance(
        snapshot, assembly, lifecycle, instance_root
    )
    if historical_revision_root not in lifecycle_history(
        snapshot, lifecycle, instance
    ):
        raise InvalidCell("restore target is outside lifecycle history")
    historical = read_revision(
        snapshot, lifecycle, historical_revision_root
    )
    wip_state = lifecycle.states["wip"]
    predecessor, current_heads = _resolve_base_revision(
        snapshot,
        lifecycle,
        instance,
        state_root=wip_state,
        base_revision_root=base_revision_root,
    )
    branch = _resolve_branch_root(
        snapshot, lifecycle, predecessor, branch_root
    )
    parents = tuple(dict.fromkeys(
        root for root in (predecessor, historical_revision_root) if root
    ))
    revision_root, revision_cells = _new_revision_cells(
        lifecycle,
        content_root=historical.content_root,
        content_digest_root=historical.content_digest_root,
        state_root=wip_state,
        predecessor_roots=parents,
        branch_root=branch,
        actor_root=actor_root,
        evidence_roots=(),
        reason="restore:" + historical_revision_root,
    )
    _append_revision(
        store, snapshot, assembly, lifecycle, instance,
        state_root=wip_state,
        next_head_roots=tuple(
            head for head in current_heads if head != predecessor
        ) + (revision_root,),
        revision_root=revision_root,
        revision_cells=revision_cells,
        active_content_root=historical.content_root,
    )
    return revision_root


__all__ = [
    "LifecycleProtocol", "LifecycleDefinition", "LifecycleInstance",
    "RevisionProjection", "LifecycleRevisionPatch",
    "bootstrap_lifecycle_protocol",
    "build_versioned_asset_definition", "read_lifecycle_instance",
    "read_revision", "seed_composed_lifecycle_content", "state_heads",
    "lifecycle_history",
    "append_wip_revision", "append_wip_graph_revision",
    "graph_content_bytes", "graph_content_digest", "merge_wip_revisions",
    "prepare_promotion_revision", "promote_revision",
    "restore_revision_as_wip",
]
