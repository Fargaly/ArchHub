"""Graph-held cardinality and participant constraints for Cell relations.

The persisted authority in this module is composed only from ordinary Cells.
Python objects are immutable projections of a selected protocol, contract, or
validation result.  Target roles are discovered from the selected contract;
the validator contains no role catalogue or role-specific dispatch.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import hmac
from types import MappingProxyType
from typing import Iterable, Mapping
import uuid

from .cell_protocols import CellBatch, RelationMember, compose_relation_cells
from .universal_cell import (
    NULL_CELL_ID,
    Cell,
    CellStore,
    InvalidCell,
    MatchBudgetExceeded,
    Snapshot,
    _OverlayCellMap,
)


_PROTOCOL_ROLE_NAMES = (
    "vocabulary-member",
    "lifecycle",
    "digest",
    "constraint",
    "constrained-role",
    "minimum",
    "maximum",
    "fixed-participant",
    "terminal-atom-maximum",
    "participant-existence",
    "definition-digest",
)
_PROTOCOL_STATE_NAMES = ("draft", "released", "definition-bound")
_PROTOCOL_VALUE_NAMES = ("participant-required", "participant-optional")


@dataclass(frozen=True, slots=True)
class RelationContractProtocol:
    """Read projection of one graph-held relation-contract vocabulary."""

    root_id: str
    roles: Mapping[str, str]
    states: Mapping[str, str]
    values: Mapping[str, str]
    digest_root: str

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown relation-contract protocol role %r" % name) from exc

    def state(self, name: str) -> str:
        try:
            return self.states[name]
        except KeyError as exc:
            raise InvalidCell("unknown relation-contract protocol state %r" % name) from exc

    def value(self, name: str) -> str:
        try:
            return self.values[name]
        except KeyError as exc:
            raise InvalidCell("unknown relation-contract protocol value %r" % name) from exc


@dataclass(frozen=True, slots=True)
class RoleConstraintBuild:
    root_id: str
    minimum_root: str
    maximum_root: str
    terminal_atom_maximum_root: str | None


@dataclass(frozen=True, slots=True)
class RelationContractBuild:
    root_id: str
    digest_root: str
    constraint_roots: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RoleConstraintProjection:
    root_id: str
    participant_role: str
    minimum: int
    maximum: int
    minimum_root: str
    maximum_root: str
    fixed_participant_root: str | None
    terminal_atom_maximum: int | None
    terminal_atom_maximum_root: str | None
    require_participant_exists: bool
    existence_root: str


@dataclass(frozen=True, slots=True)
class RelationContractProjection:
    root_id: str
    lifecycle_root: str
    lifecycle_incidence_id: str
    digest_root: str
    constraint_roots: tuple[str, ...]
    constraints: tuple[RoleConstraintProjection, ...]
    definition_digest_root: str | None


@dataclass(frozen=True, slots=True)
class RelationValidation:
    relation_root: str
    contract_root: str
    member_count: int
    role_counts: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class RelationContractAuthority:
    """The one unambiguous released contract capability selected by a definition."""

    protocol: RelationContractProtocol
    contract: RelationContractProjection


@dataclass(frozen=True, slots=True)
class RelationCandidate:
    """A contract-valid relation region that has not been committed."""

    root_id: str
    cells: tuple[Cell, ...]
    validation: RelationValidation


class _Budget:
    def __init__(self, limit: int) -> None:
        if type(limit) is not int or limit < 1:
            raise MatchBudgetExceeded(
                "relation-contract traversal budget must be a positive integer"
            )
        self.limit = limit
        self.used = 0

    def spend(self) -> None:
        self.used += 1
        if self.used > self.limit:
            raise MatchBudgetExceeded(
                "relation-contract traversal exceeded %s cells" % self.limit
            )


class _Reader:
    def __init__(self, snapshot: Snapshot, budget: _Budget) -> None:
        self.snapshot = snapshot
        self.budget = budget

    def cell(self, cell_id: str, label: str) -> Cell:
        self.budget.spend()
        cell = self.snapshot.cells.get(cell_id)
        if cell is None:
            raise InvalidCell("%s is missing" % label)
        return cell

    def relation(self, relation_root: str, label: str) -> tuple[RelationMember, ...]:
        members: list[RelationMember] = []
        seen_chain: set[str] = set()
        seen_incidence: set[str] = set()
        cursor = relation_root
        while cursor != NULL_CELL_ID:
            if cursor in seen_chain:
                raise InvalidCell("%s chain contains a cycle" % label)
            seen_chain.add(cursor)
            chain = self.cell(cursor, "%s chain cell" % label)
            if chain.atom:
                raise InvalidCell("%s chain contains unexpected atom bytes" % label)
            if chain.link0 == NULL_CELL_ID:
                if cursor != relation_root or chain.link1 != NULL_CELL_ID:
                    raise InvalidCell("%s chain contains an empty member" % label)
                break
            incidence = self.cell(chain.link0, "%s incidence" % label)
            if incidence.id in seen_incidence:
                raise InvalidCell("%s repeats an incidence identity" % label)
            seen_incidence.add(incidence.id)
            if incidence.atom:
                raise InvalidCell("%s incidence contains unexpected atom bytes" % label)
            if incidence.link0 not in self.snapshot.cells:
                raise InvalidCell("%s role is missing" % label)
            if incidence.link1 not in self.snapshot.cells:
                raise InvalidCell("%s participant is missing" % label)
            members.append(RelationMember(
                incidence.id,
                incidence.link0,
                incidence.link1,
            ))
            cursor = chain.link1
        return tuple(members)


def _new_id(prefix: str) -> str:
    return "%s:%s" % (prefix, uuid.uuid4().hex)


def _terminal(reader: _Reader, root_id: str, label: str) -> Cell:
    cell = reader.cell(root_id, label)
    if cell.link0 != NULL_CELL_ID or cell.link1 != NULL_CELL_ID:
        raise InvalidCell("%s must be a terminal Cell" % label)
    return cell


def _hash_fields(fields: Iterable[bytes]) -> bytes:
    digest = hashlib.blake2b(digest_size=32)
    for field in fields:
        digest.update(len(field).to_bytes(8, "big"))
        digest.update(field)
    return digest.hexdigest().encode("ascii")


def _protocol_content_digest(
    reader: _Reader,
    protocol: RelationContractProtocol,
) -> bytes:
    fields: list[bytes] = [
        protocol.root_id.encode("utf-8"),
        protocol.digest_root.encode("utf-8"),
    ]
    for category, names, roots in (
        (b"role", _PROTOCOL_ROLE_NAMES, protocol.roles),
        (b"state", _PROTOCOL_STATE_NAMES, protocol.states),
        (b"value", _PROTOCOL_VALUE_NAMES, protocol.values),
    ):
        for name in names:
            root_id = roots[name]
            cell = _terminal(reader, root_id, "protocol vocabulary Cell")
            fields.extend((
                category,
                name.encode("ascii"),
                root_id.encode("utf-8"),
                cell.atom,
            ))
    fields.append(protocol.state("released").encode("utf-8"))
    return _hash_fields(fields)


def _single_root_for_atom(
    roots_by_atom: Mapping[bytes, set[str]],
    atom: bytes,
) -> str:
    roots = roots_by_atom.get(atom, set())
    if len(roots) != 1:
        raise InvalidCell(
            "relation-contract protocol vocabulary is incomplete or duplicated"
        )
    return next(iter(roots))


def _open_protocol(
    reader: _Reader,
    protocol_root: str,
) -> RelationContractProtocol:
    members = reader.relation(protocol_root, "relation-contract protocol")
    roots_by_atom: dict[bytes, set[str]] = {}
    for participant_id in {member.participant_id for member in members}:
        participant = _terminal(
            reader, participant_id, "relation-contract protocol participant"
        )
        roots_by_atom.setdefault(participant.atom, set()).add(participant.id)

    roles = {
        name: _single_root_for_atom(roots_by_atom, name.encode("ascii"))
        for name in _PROTOCOL_ROLE_NAMES
    }
    states = {
        name: _single_root_for_atom(roots_by_atom, name.encode("ascii"))
        for name in _PROTOCOL_STATE_NAMES
    }
    values = {
        name: _single_root_for_atom(roots_by_atom, name.encode("ascii"))
        for name in _PROTOCOL_VALUE_NAMES
    }
    vocabulary_roots = (*roles.values(), *states.values(), *values.values())
    digest_participants = tuple(
        member.participant_id
        for member in members
        if member.role_id == roles["digest"]
    )
    if len(digest_participants) != 1:
        raise InvalidCell("relation-contract protocol digest relation is invalid")
    digest_root = digest_participants[0]
    expected_pairs = Counter([
        *((roles["vocabulary-member"], root) for root in vocabulary_roots),
        (roles["lifecycle"], states["released"]),
        (roles["digest"], digest_root),
    ])
    actual_pairs = Counter(
        (member.role_id, member.participant_id) for member in members
    )
    if actual_pairs != expected_pairs:
        raise InvalidCell("relation-contract protocol relation has been tampered with")

    protocol = RelationContractProtocol(
        root_id=protocol_root,
        roles=MappingProxyType(roles),
        states=MappingProxyType(states),
        values=MappingProxyType(values),
        digest_root=digest_root,
    )
    digest_cell = _terminal(reader, digest_root, "relation-contract protocol digest")
    actual_digest = _protocol_content_digest(reader, protocol)
    if not digest_cell.atom or not hmac.compare_digest(digest_cell.atom, actual_digest):
        raise InvalidCell("relation-contract protocol has been tampered with")
    return protocol


def _verified_protocol(
    reader: _Reader,
    selected: RelationContractProtocol,
) -> RelationContractProtocol:
    opened = _open_protocol(reader, selected.root_id)
    if (
        dict(opened.roles) != dict(selected.roles)
        or dict(opened.states) != dict(selected.states)
        or dict(opened.values) != dict(selected.values)
        or opened.digest_root != selected.digest_root
    ):
        raise InvalidCell(
            "selected relation-contract protocol projection does not match the graph"
        )
    return opened


def bootstrap_relation_contract_protocol(
    store: CellStore,
    *,
    prefix: str = "relation-contract-protocol",
) -> RelationContractProtocol:
    """Create and protect one relation-contract vocabulary in one commit."""
    if not isinstance(prefix, str) or not prefix:
        raise InvalidCell("relation-contract protocol prefix must be non-empty")
    roles = {name: "%s:role:%s" % (prefix, name) for name in _PROTOCOL_ROLE_NAMES}
    states = {
        name: "%s:state:%s" % (prefix, name) for name in _PROTOCOL_STATE_NAMES
    }
    values = {
        name: "%s:value:%s" % (prefix, name) for name in _PROTOCOL_VALUE_NAMES
    }
    digest_root = "%s:digest" % prefix
    root_id = "%s:root" % prefix
    terminals = tuple(
        Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, name.encode("ascii"))
        for name, root_id in (
            *roles.items(),
            *states.items(),
            *values.items(),
        )
    ) + (Cell(digest_root, NULL_CELL_ID, NULL_CELL_ID, b""),)
    relation = compose_relation_cells([
        *((roles["vocabulary-member"], root) for root in roles.values()),
        *((roles["vocabulary-member"], root) for root in states.values()),
        *((roles["vocabulary-member"], root) for root in values.values()),
        (roles["lifecycle"], states["released"]),
        (roles["digest"], digest_root),
    ], relation_id=root_id)
    snapshot = store.snapshot()
    candidate_cells = _OverlayCellMap(
        snapshot.cells,
        {cell.id: cell for cell in (*terminals, *relation.cells)},
    )
    protocol = RelationContractProtocol(
        root_id=root_id,
        roles=MappingProxyType(roles),
        states=MappingProxyType(states),
        values=MappingProxyType(values),
        digest_root=digest_root,
    )
    candidate = Snapshot(snapshot.revision + 1, candidate_cells)
    digest = _protocol_content_digest(_Reader(candidate, _Budget(10_000)), protocol)
    created = tuple(
        Cell(cell.id, cell.link0, cell.link1, digest)
        if cell.id == digest_root
        else cell
        for cell in (*terminals, *relation.cells)
    )
    store.commit(snapshot.revision, create=created)
    return protocol


def open_relation_contract_protocol(
    snapshot: Snapshot,
    protocol_root: str,
    *,
    budget: int,
) -> RelationContractProtocol:
    """Open and verify a graph-held relation-contract vocabulary."""
    return _open_protocol(_Reader(snapshot, _Budget(budget)), protocol_root)


def _one_member(
    members: tuple[RelationMember, ...],
    role_id: str,
    label: str,
) -> RelationMember:
    matches = tuple(member for member in members if member.role_id == role_id)
    if len(matches) != 1:
        raise InvalidCell("%s requires exactly one participant" % label)
    return matches[0]


def _optional_member(
    members: tuple[RelationMember, ...],
    role_id: str,
    label: str,
) -> RelationMember | None:
    matches = tuple(member for member in members if member.role_id == role_id)
    if len(matches) > 1:
        raise InvalidCell("%s cannot be repeated" % label)
    return matches[0] if matches else None


def _nonnegative_integer(reader: _Reader, root_id: str, label: str) -> int:
    cell = _terminal(reader, root_id, label)
    try:
        text = cell.atom.decode("ascii")
        value = int(text)
    except (UnicodeDecodeError, ValueError) as exc:
        raise InvalidCell("%s is not a non-negative integer" % label) from exc
    if value < 0 or text != str(value):
        raise InvalidCell("%s is not a non-negative integer" % label)
    return value


def _read_constraint(
    reader: _Reader,
    protocol: RelationContractProtocol,
    constraint_root: str,
) -> RoleConstraintProjection:
    members = reader.relation(constraint_root, "role constraint")
    allowed = {
        protocol.role("constrained-role"),
        protocol.role("minimum"),
        protocol.role("maximum"),
        protocol.role("fixed-participant"),
        protocol.role("terminal-atom-maximum"),
        protocol.role("participant-existence"),
    }
    if any(member.role_id not in allowed for member in members):
        raise InvalidCell("role constraint contains an unknown field")
    constrained = _one_member(
        members, protocol.role("constrained-role"), "constrained role"
    )
    minimum_member = _one_member(
        members, protocol.role("minimum"), "constraint minimum"
    )
    maximum_member = _one_member(
        members, protocol.role("maximum"), "constraint maximum"
    )
    existence_member = _one_member(
        members,
        protocol.role("participant-existence"),
        "participant existence constraint",
    )
    fixed_member = _optional_member(
        members, protocol.role("fixed-participant"), "fixed participant constraint"
    )
    atom_member = _optional_member(
        members,
        protocol.role("terminal-atom-maximum"),
        "terminal atom maximum constraint",
    )
    if constrained.participant_id == NULL_CELL_ID:
        raise InvalidCell("constrained role cannot be the null Cell")
    reader.cell(constrained.participant_id, "constrained role")
    minimum = _nonnegative_integer(
        reader, minimum_member.participant_id, "constraint minimum"
    )
    maximum = _nonnegative_integer(
        reader, maximum_member.participant_id, "constraint maximum"
    )
    if minimum > maximum:
        raise InvalidCell("constraint minimum exceeds its maximum")
    if fixed_member is not None and fixed_member.participant_id == NULL_CELL_ID:
        raise InvalidCell("fixed participant cannot be the null Cell")
    atom_maximum = None
    atom_maximum_root = None
    if atom_member is not None:
        atom_maximum_root = atom_member.participant_id
        atom_maximum = _nonnegative_integer(
            reader, atom_maximum_root, "terminal atom maximum"
        )
    if existence_member.participant_id == protocol.value("participant-required"):
        require_exists = True
    elif existence_member.participant_id == protocol.value("participant-optional"):
        require_exists = False
    else:
        raise InvalidCell("participant existence constraint has an unknown value")
    return RoleConstraintProjection(
        root_id=constraint_root,
        participant_role=constrained.participant_id,
        minimum=minimum,
        maximum=maximum,
        minimum_root=minimum_member.participant_id,
        maximum_root=maximum_member.participant_id,
        fixed_participant_root=(
            fixed_member.participant_id if fixed_member is not None else None
        ),
        terminal_atom_maximum=atom_maximum,
        terminal_atom_maximum_root=atom_maximum_root,
        require_participant_exists=require_exists,
        existence_root=existence_member.participant_id,
    )


def build_role_constraint(
    store: CellStore,
    protocol: RelationContractProtocol,
    *,
    constraint_id: str,
    participant_role: str,
    minimum: int,
    maximum: int,
    fixed_participant_root: str | None = None,
    terminal_atom_maximum: int | None = None,
    require_participant_exists: bool = True,
    budget: int,
) -> RoleConstraintBuild:
    """Build one allowed target-role constraint as an ordinary relation."""
    snapshot = store.snapshot()
    selected = _verified_protocol(_Reader(snapshot, _Budget(budget)), protocol)
    if type(minimum) is not int or minimum < 0:
        raise InvalidCell("constraint minimum must be a non-negative integer")
    if type(maximum) is not int or maximum < minimum:
        raise InvalidCell("constraint maximum must be an integer at least minimum")
    if type(require_participant_exists) is not bool:
        raise InvalidCell("participant existence requirement must be boolean")
    if participant_role == NULL_CELL_ID or participant_role not in snapshot.cells:
        raise InvalidCell("constrained role is missing")
    if fixed_participant_root is not None and (
        fixed_participant_root == NULL_CELL_ID
        or fixed_participant_root not in snapshot.cells
    ):
        raise InvalidCell("fixed participant is missing")
    if terminal_atom_maximum is not None and (
        type(terminal_atom_maximum) is not int or terminal_atom_maximum < 0
    ):
        raise InvalidCell("terminal atom maximum must be a non-negative integer")

    token = uuid.uuid4().hex
    minimum_root = "%s:minimum:%s" % (constraint_id, token)
    maximum_root = "%s:maximum:%s" % (constraint_id, token)
    atom_maximum_root = (
        "%s:terminal-atom-maximum:%s" % (constraint_id, token)
        if terminal_atom_maximum is not None
        else None
    )
    batch = CellBatch(store)
    batch.add(Cell(
        minimum_root, NULL_CELL_ID, NULL_CELL_ID, str(minimum).encode("ascii")
    ))
    batch.add(Cell(
        maximum_root, NULL_CELL_ID, NULL_CELL_ID, str(maximum).encode("ascii")
    ))
    if atom_maximum_root is not None:
        batch.add(Cell(
            atom_maximum_root,
            NULL_CELL_ID,
            NULL_CELL_ID,
            str(terminal_atom_maximum).encode("ascii"),
        ))
    members = [
        (selected.role("constrained-role"), participant_role),
        (selected.role("minimum"), minimum_root),
        (selected.role("maximum"), maximum_root),
        (
            selected.role("participant-existence"),
            selected.value(
                "participant-required"
                if require_participant_exists
                else "participant-optional"
            ),
        ),
    ]
    if fixed_participant_root is not None:
        members.append((selected.role("fixed-participant"), fixed_participant_root))
    if atom_maximum_root is not None:
        members.append((
            selected.role("terminal-atom-maximum"), atom_maximum_root
        ))
    batch.relation(members, relation_id=constraint_id)
    batch.commit()
    return RoleConstraintBuild(
        constraint_id, minimum_root, maximum_root, atom_maximum_root
    )


def _contract_content_digest(
    reader: _Reader,
    protocol: RelationContractProtocol,
    contract: RelationContractProjection,
) -> bytes:
    protocol_digest = _terminal(
        reader, protocol.digest_root, "relation-contract protocol digest"
    )
    fields: list[bytes] = [
        protocol.root_id.encode("utf-8"),
        protocol_digest.atom,
        contract.root_id.encode("utf-8"),
        contract.lifecycle_root.encode("utf-8"),
        contract.digest_root.encode("utf-8"),
    ]
    for constraint in sorted(
        contract.constraints, key=lambda item: (item.participant_role, item.root_id)
    ):
        fields.extend((
            constraint.root_id.encode("utf-8"),
            constraint.participant_role.encode("utf-8"),
            constraint.minimum_root.encode("utf-8"),
            _terminal(reader, constraint.minimum_root, "constraint minimum").atom,
            constraint.maximum_root.encode("utf-8"),
            _terminal(reader, constraint.maximum_root, "constraint maximum").atom,
            (constraint.fixed_participant_root or "").encode("utf-8"),
            constraint.existence_root.encode("utf-8"),
        ))
        if constraint.terminal_atom_maximum_root is not None:
            fields.extend((
                constraint.terminal_atom_maximum_root.encode("utf-8"),
                _terminal(
                    reader,
                    constraint.terminal_atom_maximum_root,
                    "terminal atom maximum",
                ).atom,
            ))
        else:
            fields.extend((b"", b""))
    if contract.definition_digest_root is not None:
        definition_digest = _terminal(
            reader, contract.definition_digest_root, "definition digest"
        )
        fields.extend((
            contract.definition_digest_root.encode("utf-8"),
            definition_digest.atom,
        ))
    else:
        fields.extend((b"", b""))
    return _hash_fields(fields)


def _read_contract(
    reader: _Reader,
    protocol: RelationContractProtocol,
    contract_root: str,
    *,
    verify_digest: bool,
) -> RelationContractProjection:
    members = reader.relation(contract_root, "relation contract")
    allowed = {
        protocol.role("lifecycle"),
        protocol.role("digest"),
        protocol.role("constraint"),
        protocol.role("definition-digest"),
    }
    if any(member.role_id not in allowed for member in members):
        raise InvalidCell("relation contract contains an unknown field")
    lifecycle = _one_member(
        members, protocol.role("lifecycle"), "relation contract lifecycle"
    )
    digest = _one_member(
        members, protocol.role("digest"), "relation contract digest"
    )
    definition_digest = _optional_member(
        members,
        protocol.role("definition-digest"),
        "relation contract definition digest",
    )
    constraint_roots = tuple(
        member.participant_id
        for member in members
        if member.role_id == protocol.role("constraint")
    )
    if len(constraint_roots) != len(set(constraint_roots)):
        raise InvalidCell("relation contract contains duplicate constraints")
    constraints = tuple(
        _read_constraint(reader, protocol, root_id) for root_id in constraint_roots
    )
    constrained_roles = tuple(item.participant_role for item in constraints)
    if len(constrained_roles) != len(set(constrained_roles)):
        raise InvalidCell("relation contract contains duplicate role constraints")
    digest_cell = _terminal(reader, digest.participant_id, "relation contract digest")
    definition_digest_root = (
        definition_digest.participant_id if definition_digest is not None else None
    )
    if definition_digest_root is not None:
        definition_cell = _terminal(
            reader, definition_digest_root, "definition digest"
        )
        if not definition_cell.atom:
            raise InvalidCell("definition digest cannot be empty")
    projection = RelationContractProjection(
        root_id=contract_root,
        lifecycle_root=lifecycle.participant_id,
        lifecycle_incidence_id=lifecycle.incidence_id,
        digest_root=digest.participant_id,
        constraint_roots=constraint_roots,
        constraints=constraints,
        definition_digest_root=definition_digest_root,
    )
    draft = protocol.state("draft")
    released = protocol.state("released")
    definition_bound = protocol.state("definition-bound")
    if projection.lifecycle_root == draft:
        if definition_digest_root is not None or digest_cell.atom:
            raise InvalidCell("draft relation contract has protected-state bytes")
    elif projection.lifecycle_root == released:
        if definition_digest_root is not None:
            raise InvalidCell("released relation contract has an invalid binding")
    elif projection.lifecycle_root == definition_bound:
        if definition_digest_root is None:
            raise InvalidCell("definition-bound relation contract has no digest binding")
    else:
        raise InvalidCell("relation contract has an unknown lifecycle state")
    if verify_digest and projection.lifecycle_root != draft:
        actual = _contract_content_digest(reader, protocol, projection)
        if not digest_cell.atom or not hmac.compare_digest(digest_cell.atom, actual):
            raise InvalidCell("relation contract has been tampered with")
    return projection


def _candidate_snapshot(
    snapshot: Snapshot,
    *,
    create: Iterable[Cell] = (),
    replace: Iterable[Cell] = (),
) -> Snapshot:
    cells: dict[str, Cell] = {}
    for cell in create:
        cells[cell.id] = cell
    for cell in replace:
        cells[cell.id] = cell
    return Snapshot(
        snapshot.revision + 1,
        _OverlayCellMap(snapshot.cells, cells),
    )


def build_relation_contract(
    store: CellStore,
    protocol: RelationContractProtocol,
    *,
    contract_id: str,
    constraint_roots: Iterable[str],
    released: bool = False,
    definition_digest_root: str | None = None,
    budget: int,
) -> RelationContractBuild:
    """Build a draft, released, or definition-digest-bound contract relation."""
    if type(released) is not bool:
        raise InvalidCell("released flag must be boolean")
    if released and definition_digest_root is not None:
        raise InvalidCell("choose released or definition-digest-bound authority")
    snapshot = store.snapshot()
    tracker = _Budget(budget)
    selected = _verified_protocol(_Reader(snapshot, tracker), protocol)
    roots = tuple(constraint_roots)
    if len(roots) != len(set(roots)):
        raise InvalidCell("relation contract contains duplicate constraints")
    constraints = tuple(
        _read_constraint(_Reader(snapshot, tracker), selected, root_id)
        for root_id in roots
    )
    role_ids = tuple(item.participant_role for item in constraints)
    if len(role_ids) != len(set(role_ids)):
        raise InvalidCell("relation contract contains duplicate role constraints")
    if definition_digest_root is not None:
        definition_digest = _terminal(
            _Reader(snapshot, tracker), definition_digest_root, "definition digest"
        )
        if not definition_digest.atom:
            raise InvalidCell("definition digest cannot be empty")
        lifecycle_root = selected.state("definition-bound")
    elif released:
        lifecycle_root = selected.state("released")
    else:
        lifecycle_root = selected.state("draft")

    digest_root = _new_id("%s:digest" % contract_id)
    members = [
        (selected.role("lifecycle"), lifecycle_root),
        (selected.role("digest"), digest_root),
        *((selected.role("constraint"), root_id) for root_id in roots),
    ]
    if definition_digest_root is not None:
        members.append((selected.role("definition-digest"), definition_digest_root))
    relation = compose_relation_cells(members, relation_id=contract_id)
    created = (Cell(digest_root, NULL_CELL_ID, NULL_CELL_ID, b""), *relation.cells)
    if lifecycle_root != selected.state("draft"):
        candidate = _candidate_snapshot(snapshot, create=created)
        candidate_reader = _Reader(candidate, tracker)
        projection = _read_contract(
            candidate_reader, selected, contract_id, verify_digest=False
        )
        digest_value = _contract_content_digest(
            candidate_reader, selected, projection
        )
        created = tuple(
            Cell(cell.id, cell.link0, cell.link1, digest_value)
            if cell.id == digest_root
            else cell
            for cell in created
        )
    store.commit(snapshot.revision, create=created)
    return RelationContractBuild(contract_id, digest_root, roots)


def read_relation_contract(
    snapshot: Snapshot,
    protocol: RelationContractProtocol,
    contract_root: str,
    *,
    budget: int,
) -> RelationContractProjection:
    """Open one contract and verify any protected lifecycle state."""
    tracker = _Budget(budget)
    selected = _verified_protocol(_Reader(snapshot, tracker), protocol)
    return _read_contract(
        _Reader(snapshot, tracker), selected, contract_root, verify_digest=True
    )


def resolve_relation_contract_authority(
    snapshot: Snapshot,
    *,
    capability_roots: Iterable[str],
    rule_roots: Iterable[str],
    budget: int,
) -> RelationContractAuthority:
    """Resolve exactly one released graph-held relation contract without labels."""
    protocols: list[RelationContractProtocol] = []
    for capability_root in tuple(capability_roots):
        try:
            protocols.append(open_relation_contract_protocol(
                snapshot, capability_root, budget=budget
            ))
        except InvalidCell:
            continue
    if len(protocols) != 1:
        raise InvalidCell(
            "definition requires exactly one relation-contract capability"
        )
    protocol = protocols[0]
    contracts: list[RelationContractProjection] = []
    for rule_root in tuple(rule_roots):
        try:
            contract = read_relation_contract(
                snapshot, protocol, rule_root, budget=budget
            )
        except InvalidCell:
            continue
        if contract.lifecycle_root == protocol.state("draft"):
            continue
        contracts.append(contract)
    if len(contracts) != 1:
        raise InvalidCell(
            "definition requires exactly one released relation contract"
        )
    return RelationContractAuthority(protocol, contracts[0])


def compose_validated_relation(
    snapshot: Snapshot,
    protocol: RelationContractProtocol,
    contract_root: str,
    bindings: Iterable[tuple[str, str]],
    *,
    relation_id: str | None = None,
    budget: int,
    allow_draft: bool = False,
) -> RelationCandidate:
    """Compose and validate one relation candidate without mutating the store."""
    pairs = tuple(bindings)
    if len(pairs) > budget:
        raise MatchBudgetExceeded(
            "relation candidate exceeds the explicit allocation budget"
        )
    root_id = relation_id or _new_id("relation-candidate")
    if root_id in snapshot.cells:
        raise InvalidCell("relation candidate identity already exists")
    relation = compose_relation_cells(pairs, relation_id=root_id)
    candidate_ids = tuple(cell.id for cell in relation.cells)
    if len(candidate_ids) != len(set(candidate_ids)):
        raise InvalidCell("relation candidate repeats a Cell identity")
    if any(cell_id in snapshot.cells for cell_id in candidate_ids):
        raise InvalidCell("relation candidate collides with existing Cells")
    candidate_snapshot = _candidate_snapshot(snapshot, create=relation.cells)
    validation = validate_relation(
        candidate_snapshot,
        protocol,
        contract_root,
        root_id,
        budget=budget,
        allow_draft=allow_draft,
    )
    return RelationCandidate(root_id, relation.cells, validation)


def release_relation_contract(
    store: CellStore,
    protocol: RelationContractProtocol,
    contract_root: str,
    *,
    budget: int,
) -> bytes:
    """Atomically protect one valid draft contract with its content digest."""
    snapshot = store.snapshot()
    tracker = _Budget(budget)
    selected = _verified_protocol(_Reader(snapshot, tracker), protocol)
    contract = _read_contract(
        _Reader(snapshot, tracker), selected, contract_root, verify_digest=True
    )
    if contract.lifecycle_root != selected.state("draft"):
        raise InvalidCell("only a draft relation contract can be released")
    lifecycle_incidence = snapshot.cells[contract.lifecycle_incidence_id]
    digest_cell = snapshot.cells[contract.digest_root]
    lifecycle_replacement = Cell(
        lifecycle_incidence.id,
        lifecycle_incidence.link0,
        selected.state("released"),
        lifecycle_incidence.atom,
    )
    blank_digest = Cell(
        digest_cell.id, digest_cell.link0, digest_cell.link1, b""
    )
    candidate = _candidate_snapshot(
        snapshot, replace=(lifecycle_replacement, blank_digest)
    )
    candidate_reader = _Reader(candidate, tracker)
    released_contract = _read_contract(
        candidate_reader, selected, contract_root, verify_digest=False
    )
    digest_value = _contract_content_digest(
        candidate_reader, selected, released_contract
    )
    store.commit(snapshot.revision, replace=(
        lifecycle_replacement,
        Cell(digest_cell.id, digest_cell.link0, digest_cell.link1, digest_value),
    ))
    return digest_value


def validate_relation(
    snapshot: Snapshot,
    protocol: RelationContractProtocol,
    contract_root: str,
    relation_root: str,
    *,
    budget: int,
    allow_draft: bool = False,
) -> RelationValidation:
    """Validate a target relation only from the selected graph-held authority."""
    if type(allow_draft) is not bool:
        raise InvalidCell("allow_draft must be boolean")
    tracker = _Budget(budget)
    selected = _verified_protocol(_Reader(snapshot, tracker), protocol)
    contract = _read_contract(
        _Reader(snapshot, tracker), selected, contract_root, verify_digest=True
    )
    if contract.lifecycle_root == selected.state("draft") and not allow_draft:
        raise InvalidCell("draft relation contract is not authoritative")
    constraints = {item.participant_role: item for item in contract.constraints}
    members = _Reader(snapshot, tracker).relation(relation_root, "target relation")
    counts = {role_id: 0 for role_id in constraints}
    for member in members:
        constraint = constraints.get(member.role_id)
        if constraint is None:
            raise InvalidCell("target relation contains an unknown participant role")
        participant_id = member.participant_id
        if constraint.require_participant_exists and (
            participant_id == NULL_CELL_ID or participant_id not in snapshot.cells
        ):
            raise InvalidCell("target relation has a missing required participant")
        if (
            constraint.fixed_participant_root is not None
            and participant_id != constraint.fixed_participant_root
        ):
            raise InvalidCell("target relation has the wrong fixed participant root")
        if constraint.terminal_atom_maximum is not None:
            participant = _terminal(
                _Reader(snapshot, tracker),
                participant_id,
                "target relation terminal participant",
            )
            if len(participant.atom) > constraint.terminal_atom_maximum:
                raise InvalidCell("target relation terminal atom is oversized")
        counts[member.role_id] += 1
    for role_id, constraint in constraints.items():
        count = counts[role_id]
        if count < constraint.minimum:
            raise InvalidCell(
                "target relation role %r is below minimum cardinality" % role_id
            )
        if count > constraint.maximum:
            raise InvalidCell(
                "target relation role %r exceeds maximum cardinality" % role_id
            )
    return RelationValidation(
        relation_root=relation_root,
        contract_root=contract_root,
        member_count=len(members),
        role_counts=MappingProxyType(counts),
    )


validate_relation_against_contract = validate_relation
