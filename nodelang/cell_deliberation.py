"""Graph-native deliberation spaces assembled from universal Cells.

The protocol describes relations for a reusable deliberation space and its
append-only entries.  It contains no Workshop-specific action dispatch and no
category or phase catalogue.  Categories, phases, evidence requirements, and
authorization are graph participants supplied by each space.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Iterable, Mapping
import uuid

from .cell_authorization import (
    AuthenticationBroker,
    AuthorizationDenied,
    AuthorizationProtocol,
    AuthorizationRequest,
    require_authorization,
)
from .cell_protocols import (
    CellBatch,
    RelationMember,
    compose_relation_cells,
    prepare_append_relation_member,
    prepare_append_relation_members,
    read_relation,
    with_relation_projection_scope,
)
from .cell_value_graph import (
    ValueGraphProtocol,
    prepare_value_graph,
    read_value_graph,
)
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


ROLE_NAMES = (
    "vocabulary-member",
    "space-title",
    "space-participant",
    "space-category",
    "space-policy",
    "space-action",
    "space-scope",
    "space-interface",
    "space-purpose",
    "space-classification",
    "space-audience",
    "space-lifecycle",
    "space-operational-state",
    "space-requirement",
    "space-entry",
    "requirement-phase",
    "requirement-category",
    "requirement-minimum",
    "requirement-evidence-minimum",
    "entry-space",
    "entry-actor",
    "entry-recipient",
    "entry-category",
    "entry-content",
    "entry-reference",
    "entry-reply-to",
    "entry-evidence",
    "entry-created-at",
    "entry-sequence",
    "entry-idempotency",
    "entry-policy",
    "entry-authorization-action",
    "entry-authorization-rule",
    "entry-authorization-reason",
    "entry-lifecycle",
)

RELATION_BUDGET = 100_000
MAX_PARTICIPANTS = 1_024
MAX_CATEGORIES = 256
MAX_REQUIREMENTS = 1_024
MAX_ENTRIES = 100_000
MAX_RECIPIENTS = 1_024
MAX_REFERENCES = 4_096
MAX_EVIDENCE = 4_096
MAX_CONTENT_BYTES = 65_536
MAX_TITLE_BYTES = 512
MAX_IDEMPOTENCY_BYTES = 512


@dataclass(frozen=True, slots=True)
class DeliberationProtocol:
    root_id: str
    roles: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown deliberation role %r" % name) from exc


@dataclass(frozen=True, slots=True)
class DeliberationRequirement:
    phase_root: str
    category_root: str
    minimum_count: int = 1
    minimum_evidence_count: int = 0


@dataclass(frozen=True, slots=True)
class DeliberationSpaceBuild:
    root_id: str
    requirement_roots: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DeliberationSpaceProjection:
    root_id: str
    title: str
    participant_roots: tuple[str, ...]
    category_roots: tuple[str, ...]
    policy_root: str
    action_root: str
    scope_roots: tuple[str, ...]
    interface_root: str | None
    purpose_root: str | None
    classification_root: str | None
    audience_root: str | None
    lifecycle_root: str
    operational_state_root: str | None
    requirement_roots: tuple[str, ...]
    entry_roots: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DeliberationEntryProjection:
    root_id: str
    space_root: str
    actor_root: str
    recipient_roots: tuple[str, ...]
    category_root: str
    content: str
    reference_roots: tuple[str, ...]
    reply_to_root: str | None
    evidence_roots: tuple[str, ...]
    created_at: str
    sequence: int
    idempotency_key: str
    policy_root: str
    authorization_action_root: str
    authorization_rule_roots: tuple[str, ...]
    authorization_reason: str
    lifecycle_root: str


@dataclass(frozen=True, slots=True)
class PreparedDeliberationEntry:
    """A validated append patch, or an idempotently existing entry."""

    root_id: str
    existing_entry: DeliberationEntryProjection | None
    create: tuple[Cell, ...]
    replace: tuple[Cell, ...]


@dataclass(frozen=True, slots=True)
class DeliberationGateProjection:
    space_root: str
    phase_root: str
    reference_root: str
    allowed: bool
    required_category_roots: tuple[str, ...]
    present_category_roots: tuple[str, ...]
    missing_category_roots: tuple[str, ...]
    missing_evidence_category_roots: tuple[str, ...]
    matching_entry_roots: tuple[str, ...]
    observed_counts: Mapping[str, int]
    observed_evidence_counts: Mapping[str, int]


def _terminal(root_id: str, value: str | int) -> Cell:
    encoded = str(value).encode("utf-8")
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, encoded)


def _for_role(
    members: tuple[RelationMember, ...], role_id: str
) -> tuple[str, ...]:
    return tuple(
        member.participant_id
        for member in members
        if member.role_id == role_id
    )


def _one(
    members: tuple[RelationMember, ...], role_id: str, label: str
) -> str:
    roots = _for_role(members, role_id)
    if len(roots) != 1:
        raise InvalidCell(
            "deliberation requires exactly one %s participant" % label
        )
    return roots[0]


def _optional(
    members: tuple[RelationMember, ...], role_id: str, label: str
) -> str | None:
    roots = _for_role(members, role_id)
    if len(roots) > 1:
        raise InvalidCell(
            "deliberation permits at most one %s participant" % label
        )
    return roots[0] if roots else None


def _text(snapshot: Snapshot, root_id: str, label: str) -> str:
    try:
        cell = snapshot.cells[root_id]
    except KeyError as exc:
        raise InvalidCell("%s root is missing" % label) from exc
    if cell.link0 != NULL_CELL_ID or cell.link1 != NULL_CELL_ID:
        raise InvalidCell("%s must be a terminal Cell" % label)
    try:
        return cell.atom.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidCell("%s is not UTF-8" % label) from exc


def _closed_roles(
    members: tuple[RelationMember, ...], allowed: Iterable[str], label: str
) -> None:
    unexpected = {member.role_id for member in members} - set(allowed)
    if unexpected:
        raise InvalidCell("%s contains undeclared roles" % label)


def _bounded_unique(
    values: Iterable[str], *, label: str, maximum: int
) -> tuple[str, ...]:
    roots = tuple(values)
    if len(roots) > maximum:
        raise InvalidCell("%s exceeds its bounded size" % label)
    if len(roots) != len(set(roots)):
        raise InvalidCell("%s identities must be unique" % label)
    if any(not isinstance(root, str) or not root for root in roots):
        raise InvalidCell("%s contains an invalid identity" % label)
    return roots


def bootstrap_deliberation_protocol(
    store: CellStore, *, prefix: str = "deliberation-protocol"
) -> DeliberationProtocol:
    roles = {
        name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES
    }
    root_id = prefix + ":root"
    if root_id in store.snapshot().cells:
        return upgrade_deliberation_protocol(store, prefix=prefix)
    batch = CellBatch(store)
    for name, role_root in roles.items():
        batch.add(_terminal(role_root, name))
    batch.relation(
        (
            (roles["vocabulary-member"], role_root)
            for role_root in roles.values()
        ),
        relation_id=root_id,
    )
    batch.commit()
    return DeliberationProtocol(root_id, MappingProxyType(roles))


def upgrade_deliberation_protocol(
    store: CellStore, *, prefix: str = "deliberation-protocol"
) -> DeliberationProtocol:
    """Append newly released vocabulary only; never rebuild a live protocol."""
    roles = {
        name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES
    }
    root_id = prefix + ":root"
    snapshot = store.snapshot()
    if root_id not in snapshot.cells:
        raise InvalidCell("deliberation protocol is unavailable for upgrade")
    members = read_relation(snapshot, root_id, budget=1_024)
    vocabulary_roles = {member.role_id for member in members}
    if vocabulary_roles != {roles["vocabulary-member"]}:
        raise InvalidCell("deliberation protocol vocabulary authority drifted")
    existing: dict[str, str] = {}
    for member in members:
        name = _text(snapshot, member.participant_id, "protocol role")
        if name in existing:
            raise InvalidCell("deliberation protocol repeats a role")
        if name not in ROLE_NAMES or member.participant_id != roles[name]:
            raise InvalidCell("deliberation protocol vocabulary is incompatible")
        existing[name] = member.participant_id
    missing = tuple(name for name in ROLE_NAMES if name not in existing)
    if not missing:
        return open_deliberation_protocol(snapshot, root_id)
    if any(roles[name] in snapshot.cells for name in missing):
        raise InvalidCell("deliberation protocol has an orphan vocabulary role")
    patch = prepare_append_relation_members(
        snapshot,
        root_id,
        (
            (roles["vocabulary-member"], roles[name])
            for name in missing
        ),
        budget=1_024,
    )
    # Reuse the relation patch mechanism so an existing released protocol is
    # extended append-only rather than reconstructed.
    store.commit(
        snapshot.revision,
        create=tuple(
            _terminal(roles[name], name) for name in missing
        ) + patch.create,
        replace=patch.replace,
    )
    return open_deliberation_protocol(store.snapshot(), root_id)


def open_deliberation_protocol(
    snapshot: Snapshot, root_id: str, *, budget: int = 1_024
) -> DeliberationProtocol:
    members = read_relation(snapshot, root_id, budget=budget)
    if not members:
        raise InvalidCell("deliberation protocol vocabulary is empty")
    vocabulary_roles = {member.role_id for member in members}
    if len(vocabulary_roles) != 1:
        raise InvalidCell(
            "deliberation protocol vocabulary has inconsistent incidences"
        )
    vocabulary_role = next(iter(vocabulary_roles))
    by_name: dict[str, str] = {}
    for member in members:
        name = _text(snapshot, member.participant_id, "protocol role")
        if name in by_name:
            raise InvalidCell("deliberation protocol repeats a role")
        by_name[name] = member.participant_id
    if set(by_name) != set(ROLE_NAMES):
        raise InvalidCell(
            "deliberation protocol vocabulary is incomplete or extended"
        )
    if by_name["vocabulary-member"] != vocabulary_role:
        raise InvalidCell(
            "deliberation protocol vocabulary role does not self-identify"
        )
    return DeliberationProtocol(
        root_id,
        MappingProxyType({name: by_name[name] for name in ROLE_NAMES}),
    )


def compose_deliberation_space(
    store: CellStore,
    protocol: DeliberationProtocol,
    *,
    space_id: str,
    title: str,
    participant_roots: Iterable[str],
    category_roots: Iterable[str],
    policy_root: str,
    action_root: str,
    scope_roots: Iterable[str],
    lifecycle_root: str,
    requirements: Iterable[DeliberationRequirement] = (),
    interface_root: str | None = None,
    purpose_root: str | None = None,
    classification_root: str | None = None,
    audience_root: str | None = None,
    operational_state_root: str | None = None,
) -> DeliberationSpaceBuild:
    open_deliberation_protocol(store.snapshot(), protocol.root_id)
    if not isinstance(space_id, str) or not space_id:
        raise InvalidCell("deliberation space identity is invalid")
    if not isinstance(title, str) or not title.strip():
        raise InvalidCell("deliberation title must be non-empty")
    if len(title.encode("utf-8")) > MAX_TITLE_BYTES:
        raise InvalidCell("deliberation title exceeds its bounded size")
    participants = _bounded_unique(
        participant_roots,
        label="deliberation participants",
        maximum=MAX_PARTICIPANTS,
    )
    if not participants:
        raise InvalidCell("deliberation requires at least one participant")
    categories = _bounded_unique(
        category_roots,
        label="deliberation categories",
        maximum=MAX_CATEGORIES,
    )
    if not categories:
        raise InvalidCell("deliberation requires at least one category")
    scopes = _bounded_unique(
        scope_roots,
        label="deliberation scopes",
        maximum=64,
    )
    if not scopes:
        raise InvalidCell("deliberation requires at least one authority scope")
    requirement_specs = tuple(requirements)
    if len(requirement_specs) > MAX_REQUIREMENTS:
        raise InvalidCell("deliberation requirements exceed their bounded size")
    seen_requirements: set[tuple[str, str]] = set()
    for requirement in requirement_specs:
        if not isinstance(requirement, DeliberationRequirement):
            raise InvalidCell("deliberation requirement has an invalid shape")
        if requirement.category_root not in categories:
            raise InvalidCell("requirement category is not admitted by the space")
        key = (requirement.phase_root, requirement.category_root)
        if key in seen_requirements:
            raise InvalidCell("deliberation requirement is duplicated")
        seen_requirements.add(key)
        if type(requirement.minimum_count) is not int or not (
            1 <= requirement.minimum_count <= 1_000
        ):
            raise InvalidCell("requirement minimum is invalid")
        if type(requirement.minimum_evidence_count) is not int or not (
            0 <= requirement.minimum_evidence_count <= 1_000
        ):
            raise InvalidCell("requirement evidence minimum is invalid")

    referenced = {
        *participants,
        *categories,
        policy_root,
        action_root,
        *scopes,
        lifecycle_root,
        *(requirement.phase_root for requirement in requirement_specs),
        *(root for root in (
            interface_root,
            purpose_root,
            classification_root,
            audience_root,
            operational_state_root,
        ) if root is not None),
    }
    missing = referenced - set(store.snapshot().cells)
    if missing:
        raise InvalidCell("deliberation space references missing Cells")

    batch = CellBatch(store)
    title_root = space_id + ":title"
    batch.add(_terminal(title_root, title.strip()))
    requirement_roots: list[str] = []
    for index, requirement in enumerate(requirement_specs):
        requirement_root = "%s:requirement:%s" % (space_id, index)
        minimum_root = requirement_root + ":minimum"
        batch.add(_terminal(minimum_root, requirement.minimum_count))
        requirement_members = [
            (protocol.role("requirement-phase"), requirement.phase_root),
            (protocol.role("requirement-category"), requirement.category_root),
            (protocol.role("requirement-minimum"), minimum_root),
        ]
        if requirement.minimum_evidence_count:
            evidence_minimum_root = requirement_root + ":evidence-minimum"
            batch.add(
                _terminal(evidence_minimum_root, requirement.minimum_evidence_count)
            )
            requirement_members.append((
                protocol.role("requirement-evidence-minimum"),
                evidence_minimum_root,
            ))
        batch.relation(requirement_members, relation_id=requirement_root)
        requirement_roots.append(requirement_root)

    members = [
        (protocol.role("space-title"), title_root),
        *((protocol.role("space-participant"), root) for root in participants),
        *((protocol.role("space-category"), root) for root in categories),
        (protocol.role("space-policy"), policy_root),
        (protocol.role("space-action"), action_root),
        *((protocol.role("space-scope"), root) for root in scopes),
        (protocol.role("space-lifecycle"), lifecycle_root),
        *((protocol.role("space-requirement"), root)
          for root in requirement_roots),
    ]
    for role_name, root in (
        ("space-interface", interface_root),
        ("space-purpose", purpose_root),
        ("space-classification", classification_root),
        ("space-audience", audience_root),
        ("space-operational-state", operational_state_root),
    ):
        if root is not None:
            members.append((protocol.role(role_name), root))
    batch.relation(members, relation_id=space_id)
    batch.commit()
    return DeliberationSpaceBuild(space_id, tuple(requirement_roots))


def extend_deliberation_space(
    store: CellStore,
    protocol: DeliberationProtocol,
    *,
    space_root: str,
    participant_roots: Iterable[str] = (),
    category_roots: Iterable[str] = (),
    requirements: Iterable[DeliberationRequirement] = (),
) -> DeliberationSpaceProjection:
    """Append participants, categories, and gate requirements without rewriting a room.

    A Workshop must gain collaborators and stronger evidence obligations without
    losing its prior plans, decisions, or audit history.  This is a generic
    deliberation operation: all extensions are explicit Cells on the existing
    space relation and a repeated request is a no-op.
    """
    snapshot = store.snapshot()
    space = read_deliberation_space(snapshot, protocol, space_root)
    participants = _bounded_unique(
        participant_roots,
        label="deliberation extension participants",
        maximum=MAX_PARTICIPANTS,
    )
    categories = _bounded_unique(
        category_roots,
        label="deliberation extension categories",
        maximum=MAX_CATEGORIES,
    )
    requested_requirements = tuple(requirements)
    if len(requested_requirements) > MAX_REQUIREMENTS:
        raise InvalidCell("deliberation extension requirements exceed their bounded size")
    if set((*participants, *categories)) - set(snapshot.cells):
        raise InvalidCell("deliberation extension references missing Cells")
    new_participants = tuple(
        root for root in participants if root not in space.participant_roots
    )
    new_categories = tuple(
        root for root in categories if root not in space.category_roots
    )
    all_participants = (*space.participant_roots, *new_participants)
    all_categories = (*space.category_roots, *new_categories)
    if len(all_participants) > MAX_PARTICIPANTS:
        raise InvalidCell("deliberation participants exceed their bounded size")
    if len(all_categories) > MAX_CATEGORIES:
        raise InvalidCell("deliberation categories exceed their bounded size")

    existing_requirements = tuple(
        _read_requirement(snapshot, protocol, root, budget=RELATION_BUDGET)
        for root in space.requirement_roots
    )
    by_key = {
        (item.phase_root, item.category_root): item
        for item in existing_requirements
    }
    additions: list[DeliberationRequirement] = []
    for requirement in requested_requirements:
        if not isinstance(requirement, DeliberationRequirement):
            raise InvalidCell("deliberation extension requirement has an invalid shape")
        if requirement.category_root not in all_categories:
            raise InvalidCell("extension requirement category is not admitted")
        if type(requirement.minimum_count) is not int or not (
            1 <= requirement.minimum_count <= 1_000
        ):
            raise InvalidCell("extension requirement minimum is invalid")
        if type(requirement.minimum_evidence_count) is not int or not (
            0 <= requirement.minimum_evidence_count <= 1_000
        ):
            raise InvalidCell("extension requirement evidence minimum is invalid")
        key = (requirement.phase_root, requirement.category_root)
        previous = by_key.get(key)
        if previous is not None:
            if previous != requirement:
                raise InvalidCell("deliberation requirement cannot be rewritten")
            continue
        if key in {
            (item.phase_root, item.category_root) for item in additions
        }:
            raise InvalidCell("deliberation extension repeats a requirement")
        additions.append(requirement)

    if not new_participants and not new_categories and not additions:
        return space
    requirement_cells: list[Cell] = []
    requirement_roots: list[str] = []
    start = len(space.requirement_roots)
    for offset, requirement in enumerate(additions):
        requirement_root = "%s:requirement:%s" % (space_root, start + offset)
        if requirement_root in snapshot.cells:
            raise InvalidCell("deliberation extension requirement identity collided")
        minimum_root = requirement_root + ":minimum"
        members = [
            (protocol.role("requirement-phase"), requirement.phase_root),
            (protocol.role("requirement-category"), requirement.category_root),
            (protocol.role("requirement-minimum"), minimum_root),
        ]
        requirement_cells.append(_terminal(minimum_root, requirement.minimum_count))
        if requirement.minimum_evidence_count:
            evidence_minimum_root = requirement_root + ":evidence-minimum"
            requirement_cells.append(_terminal(
                evidence_minimum_root, requirement.minimum_evidence_count
            ))
            members.append((
                protocol.role("requirement-evidence-minimum"),
                evidence_minimum_root,
            ))
        requirement_cells.extend(
            compose_relation_cells(members, relation_id=requirement_root).cells
        )
        requirement_roots.append(requirement_root)

    patch = prepare_append_relation_members(
        snapshot,
        space_root,
        (
            *((protocol.role("space-participant"), root)
              for root in new_participants),
            *((protocol.role("space-category"), root)
              for root in new_categories),
            *((protocol.role("space-requirement"), root)
              for root in requirement_roots),
        ),
        budget=RELATION_BUDGET,
    )
    identities = tuple(cell.id for cell in (*requirement_cells, *patch.create))
    if len(identities) != len(set(identities)):
        raise InvalidCell("deliberation extension creates duplicate Cell identities")
    store.commit(
        snapshot.revision,
        create=(*requirement_cells, *patch.create),
        replace=patch.replace,
    )
    return read_deliberation_space(store.snapshot(), protocol, space_root)


def _read_requirement(
    snapshot: Snapshot,
    protocol: DeliberationProtocol,
    requirement_root: str,
    *,
    budget: int,
) -> DeliberationRequirement:
    members = read_relation(snapshot, requirement_root, budget=budget)
    allowed = (
        protocol.role("requirement-phase"),
        protocol.role("requirement-category"),
        protocol.role("requirement-minimum"),
        protocol.role("requirement-evidence-minimum"),
    )
    _closed_roles(members, allowed, "deliberation requirement")
    phase = _one(
        members, protocol.role("requirement-phase"), "requirement phase"
    )
    category = _one(
        members,
        protocol.role("requirement-category"),
        "requirement category",
    )
    minimum_root = _one(
        members,
        protocol.role("requirement-minimum"),
        "requirement minimum",
    )
    try:
        minimum = int(_text(snapshot, minimum_root, "requirement minimum"))
    except ValueError as exc:
        raise InvalidCell("requirement minimum is not an integer") from exc
    if not 1 <= minimum <= 1_000:
        raise InvalidCell("requirement minimum is outside its bounds")
    evidence_minimum_root = _optional(
        members,
        protocol.role("requirement-evidence-minimum"),
        "requirement evidence minimum",
    )
    evidence_minimum = 0
    if evidence_minimum_root is not None:
        try:
            evidence_minimum = int(_text(
                snapshot, evidence_minimum_root, "requirement evidence minimum"
            ))
        except ValueError as exc:
            raise InvalidCell(
                "requirement evidence minimum is not an integer"
            ) from exc
        if not 0 <= evidence_minimum <= 1_000:
            raise InvalidCell("requirement evidence minimum is outside its bounds")
    return DeliberationRequirement(phase, category, minimum, evidence_minimum)


def read_deliberation_space(
    snapshot: Snapshot,
    protocol: DeliberationProtocol,
    space_root: str,
    *,
    budget: int = RELATION_BUDGET,
) -> DeliberationSpaceProjection:
    members = read_relation(snapshot, space_root, budget=budget)
    allowed = tuple(
        protocol.role(name) for name in ROLE_NAMES if name.startswith("space-")
    )
    _closed_roles(members, allowed, "deliberation space")
    participants = _bounded_unique(
        _for_role(members, protocol.role("space-participant")),
        label="deliberation participants",
        maximum=MAX_PARTICIPANTS,
    )
    categories = _bounded_unique(
        _for_role(members, protocol.role("space-category")),
        label="deliberation categories",
        maximum=MAX_CATEGORIES,
    )
    requirements = _bounded_unique(
        _for_role(members, protocol.role("space-requirement")),
        label="deliberation requirements",
        maximum=MAX_REQUIREMENTS,
    )
    entries = _bounded_unique(
        _for_role(members, protocol.role("space-entry")),
        label="deliberation entries",
        maximum=MAX_ENTRIES,
    )
    if not participants or not categories:
        raise InvalidCell("deliberation space is incomplete")
    title_root = _one(members, protocol.role("space-title"), "space title")
    policy_root = _one(members, protocol.role("space-policy"), "space policy")
    action_root = _one(members, protocol.role("space-action"), "space action")
    lifecycle_root = _one(
        members, protocol.role("space-lifecycle"), "space lifecycle"
    )
    scopes = _bounded_unique(
        _for_role(members, protocol.role("space-scope")),
        label="deliberation scopes",
        maximum=64,
    )
    if not scopes:
        raise InvalidCell("deliberation space has no authority scope")
    required_roots = {
        title_root,
        policy_root,
        action_root,
        lifecycle_root,
        *participants,
        *categories,
        *requirements,
        *entries,
        *scopes,
    }
    if any(_root not in snapshot.cells for _root in required_roots):
        raise InvalidCell("deliberation space references missing Cells")
    seen: set[tuple[str, str]] = set()
    for requirement_root in requirements:
        requirement = _read_requirement(
            snapshot, protocol, requirement_root, budget=budget
        )
        if requirement.category_root not in categories:
            raise InvalidCell(
                "deliberation requirement category is no longer admitted"
            )
        key = (requirement.phase_root, requirement.category_root)
        if key in seen:
            raise InvalidCell("deliberation requirement is duplicated")
        seen.add(key)
    return DeliberationSpaceProjection(
        root_id=space_root,
        title=_text(snapshot, title_root, "space title"),
        participant_roots=participants,
        category_roots=categories,
        policy_root=policy_root,
        action_root=action_root,
        scope_roots=scopes,
        interface_root=_optional(
            members, protocol.role("space-interface"), "space interface"
        ),
        purpose_root=_optional(
            members, protocol.role("space-purpose"), "space purpose"
        ),
        classification_root=_optional(
            members,
            protocol.role("space-classification"),
            "space classification",
        ),
        audience_root=_optional(
            members, protocol.role("space-audience"), "space audience"
        ),
        lifecycle_root=lifecycle_root,
        operational_state_root=_optional(
            members,
            protocol.role("space-operational-state"),
            "space operational state",
        ),
        requirement_roots=requirements,
        entry_roots=entries,
    )


def read_deliberation_entry(
    snapshot: Snapshot,
    protocol: DeliberationProtocol,
    entry_root: str,
    *,
    budget: int = RELATION_BUDGET,
) -> DeliberationEntryProjection:
    members = read_relation(snapshot, entry_root, budget=budget)
    allowed = tuple(
        protocol.role(name) for name in ROLE_NAMES if name.startswith("entry-")
    )
    _closed_roles(members, allowed, "deliberation entry")
    content_root = _one(
        members, protocol.role("entry-content"), "entry content"
    )
    created_root = _one(
        members, protocol.role("entry-created-at"), "entry creation time"
    )
    sequence_root = _one(
        members, protocol.role("entry-sequence"), "entry sequence"
    )
    idempotency_root = _one(
        members, protocol.role("entry-idempotency"), "entry idempotency"
    )
    reason_root = _one(
        members,
        protocol.role("entry-authorization-reason"),
        "entry authorization reason",
    )
    try:
        sequence = int(_text(snapshot, sequence_root, "entry sequence"))
    except ValueError as exc:
        raise InvalidCell("entry sequence is not an integer") from exc
    if sequence < 1:
        raise InvalidCell("entry sequence is invalid")
    created_at = _text(snapshot, created_root, "entry creation time")
    _validated_timestamp(created_at)
    return DeliberationEntryProjection(
        root_id=entry_root,
        space_root=_one(
            members, protocol.role("entry-space"), "entry space"
        ),
        actor_root=_one(
            members, protocol.role("entry-actor"), "entry actor"
        ),
        recipient_roots=_bounded_unique(
            _for_role(members, protocol.role("entry-recipient")),
            label="entry recipients",
            maximum=MAX_RECIPIENTS,
        ),
        category_root=_one(
            members, protocol.role("entry-category"), "entry category"
        ),
        content=_text(snapshot, content_root, "entry content"),
        reference_roots=_bounded_unique(
            _for_role(members, protocol.role("entry-reference")),
            label="entry references",
            maximum=MAX_REFERENCES,
        ),
        reply_to_root=_optional(
            members, protocol.role("entry-reply-to"), "entry reply target"
        ),
        evidence_roots=_bounded_unique(
            _for_role(members, protocol.role("entry-evidence")),
            label="entry evidence",
            maximum=MAX_EVIDENCE,
        ),
        created_at=created_at,
        sequence=sequence,
        idempotency_key=_text(
            snapshot, idempotency_root, "entry idempotency"
        ),
        policy_root=_one(
            members, protocol.role("entry-policy"), "entry policy"
        ),
        authorization_action_root=_one(
            members,
            protocol.role("entry-authorization-action"),
            "entry authorization action",
        ),
        authorization_rule_roots=_bounded_unique(
            _for_role(members, protocol.role("entry-authorization-rule")),
            label="entry authorization rules",
            maximum=256,
        ),
        authorization_reason=_text(
            snapshot, reason_root, "entry authorization reason"
        ),
        lifecycle_root=_one(
            members, protocol.role("entry-lifecycle"), "entry lifecycle"
        ),
    )


def list_deliberation_entries(
    snapshot: Snapshot,
    protocol: DeliberationProtocol,
    space_root: str,
    *,
    budget: int = RELATION_BUDGET,
) -> tuple[DeliberationEntryProjection, ...]:
    space = read_deliberation_space(
        snapshot, protocol, space_root, budget=budget
    )
    entries = tuple(
        read_deliberation_entry(snapshot, protocol, root, budget=budget)
        for root in space.entry_roots
    )
    if any(entry.space_root != space_root for entry in entries):
        raise InvalidCell("entry belongs to a different deliberation space")
    if tuple(entry.sequence for entry in entries) != tuple(
        range(1, len(entries) + 1)
    ):
        raise InvalidCell("deliberation entry sequence is discontinuous")
    return entries


def _validated_timestamp(value: str) -> None:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 128:
        raise InvalidCell("entry timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise InvalidCell("entry timestamp is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InvalidCell("entry timestamp requires an explicit timezone")


def _same_idempotent_payload(
    entry: DeliberationEntryProjection,
    *,
    actor_root: str,
    category_root: str,
    content: str,
    recipient_roots: tuple[str, ...],
    reference_roots: tuple[str, ...],
    reply_to_root: str | None,
    evidence_roots: tuple[str, ...],
) -> bool:
    return (
        entry.actor_root == actor_root
        and entry.category_root == category_root
        and entry.content == content
        and entry.recipient_roots == recipient_roots
        and entry.reference_roots == reference_roots
        and entry.reply_to_root == reply_to_root
        and entry.evidence_roots == evidence_roots
    )


def prepare_deliberation_entry(
    snapshot: Snapshot,
    protocol: DeliberationProtocol,
    *,
    space_root: str,
    actor_root: str,
    category_root: str,
    content: str,
    idempotency_key: str,
    created_at: str,
    authorization_protocol: AuthorizationProtocol,
    authentication_broker: AuthenticationBroker,
    authentication_context: object,
    recipient_roots: Iterable[str] = (),
    reference_roots: Iterable[str] = (),
    reply_to_root: str | None = None,
    evidence_roots: Iterable[str] = (),
    pending_root_ids: Iterable[str] = (),
) -> PreparedDeliberationEntry:
    """Prepare one append-only entry without committing it.

    ``pending_root_ids`` is deliberately limited to identities that another
    generic graph composition will create in the same commit.  It lets an
    entry point at an openable value graph without creating a dangling or
    separately committed payload.
    """
    if not isinstance(content, str) or not content.strip():
        raise InvalidCell("deliberation entry content must be non-empty")
    if len(content.encode("utf-8")) > MAX_CONTENT_BYTES:
        raise InvalidCell("deliberation entry content exceeds its bounded size")
    if not isinstance(idempotency_key, str) or not idempotency_key:
        raise InvalidCell("deliberation idempotency identity is invalid")
    if len(idempotency_key.encode("utf-8")) > MAX_IDEMPOTENCY_BYTES:
        raise InvalidCell("deliberation idempotency identity is too large")
    _validated_timestamp(created_at)
    recipients = _bounded_unique(
        recipient_roots, label="entry recipients", maximum=MAX_RECIPIENTS
    )
    references = _bounded_unique(
        reference_roots, label="entry references", maximum=MAX_REFERENCES
    )
    evidence = _bounded_unique(
        evidence_roots, label="entry evidence", maximum=MAX_EVIDENCE
    )

    space = read_deliberation_space(snapshot, protocol, space_root)
    if actor_root not in space.participant_roots:
        raise AuthorizationDenied("entry actor is not a space participant")
    if category_root not in space.category_roots:
        raise InvalidCell("entry category is not admitted by the space")
    if set(recipients) - set(space.participant_roots):
        raise AuthorizationDenied("entry recipient is not a space participant")
    referenced = {actor_root, category_root, *recipients, *references, *evidence}
    if reply_to_root is not None:
        referenced.add(reply_to_root)
        if reply_to_root not in space.entry_roots:
            raise InvalidCell(
                "reply target is not an entry in the same deliberation space"
            )
    pending = _bounded_unique(
        pending_root_ids,
        label="pending entry references",
        maximum=MAX_REFERENCES + MAX_EVIDENCE,
    )
    if referenced - (set(snapshot.cells) | set(pending)):
        raise InvalidCell("deliberation entry references missing Cells")

    decision = require_authorization(
        snapshot,
        authorization_protocol,
        space.policy_root,
        authentication_broker,
        authentication_context,
        AuthorizationRequest(
            action_root=space.action_root,
            object_root=space.root_id,
            resource_lineage_roots=space.scope_roots,
            interface_root=space.interface_root,
            purpose_root=space.purpose_root,
            classification_root=space.classification_root,
            audience_root=space.audience_root,
            lifecycle_state_root=space.lifecycle_root,
            operational_state_root=space.operational_state_root,
        ),
    )
    if decision.subject_root != actor_root:
        raise AuthorizationDenied(
            "authenticated subject does not match the entry actor"
        )
    if decision.policy_root != space.policy_root:
        raise AuthorizationDenied("entry authorization policy does not match")
    if decision.action_root != space.action_root:
        raise AuthorizationDenied("entry authorization action does not match")

    existing_entries = list_deliberation_entries(
        snapshot, protocol, space_root
    )
    for existing in existing_entries:
        if existing.idempotency_key != idempotency_key:
            continue
        if _same_idempotent_payload(
            existing,
            actor_root=actor_root,
            category_root=category_root,
            content=content,
            recipient_roots=recipients,
            reference_roots=references,
            reply_to_root=reply_to_root,
            evidence_roots=evidence,
        ):
            return PreparedDeliberationEntry(
                root_id=existing.root_id,
                existing_entry=existing,
                create=(),
                replace=(),
            )
        raise InvalidCell(
            "deliberation idempotency identity was reused for another payload"
        )

    token = uuid.uuid4().hex
    entry_root = "%s:entry:%s" % (space_root, token)
    content_root = entry_root + ":content"
    created_root = entry_root + ":created-at"
    sequence_root = entry_root + ":sequence"
    idempotency_root = entry_root + ":idempotency"
    reason_root = entry_root + ":authorization-reason"
    terminals = (
        _terminal(content_root, content),
        _terminal(created_root, created_at),
        _terminal(sequence_root, len(existing_entries) + 1),
        _terminal(idempotency_root, idempotency_key),
        _terminal(reason_root, decision.reason),
    )
    members = [
        (protocol.role("entry-space"), space.root_id),
        (protocol.role("entry-actor"), actor_root),
        *((protocol.role("entry-recipient"), root) for root in recipients),
        (protocol.role("entry-category"), category_root),
        (protocol.role("entry-content"), content_root),
        *((protocol.role("entry-reference"), root) for root in references),
        *((protocol.role("entry-evidence"), root) for root in evidence),
        (protocol.role("entry-created-at"), created_root),
        (protocol.role("entry-sequence"), sequence_root),
        (protocol.role("entry-idempotency"), idempotency_root),
        (protocol.role("entry-policy"), decision.policy_root),
        (
            protocol.role("entry-authorization-action"),
            decision.action_root,
        ),
        *((protocol.role("entry-authorization-rule"), root)
          for root in decision.determining_rule_roots),
        (protocol.role("entry-authorization-reason"), reason_root),
        (protocol.role("entry-lifecycle"), space.lifecycle_root),
    ]
    if reply_to_root is not None:
        members.append((protocol.role("entry-reply-to"), reply_to_root))
    composed = compose_relation_cells(members, relation_id=entry_root)
    patch = prepare_append_relation_member(
        snapshot,
        space.root_id,
        protocol.role("space-entry"),
        entry_root,
        budget=RELATION_BUDGET,
    )
    return PreparedDeliberationEntry(
        root_id=entry_root,
        existing_entry=None,
        create=tuple((*terminals, *composed.cells, *patch.create)),
        replace=tuple(patch.replace),
    )


@with_relation_projection_scope
def append_deliberation_entry(
    store: CellStore,
    protocol: DeliberationProtocol,
    *,
    space_root: str,
    actor_root: str,
    category_root: str,
    content: str,
    idempotency_key: str,
    created_at: str,
    authorization_protocol: AuthorizationProtocol,
    authentication_broker: AuthenticationBroker,
    authentication_context: object,
    recipient_roots: Iterable[str] = (),
    reference_roots: Iterable[str] = (),
    reply_to_root: str | None = None,
    evidence_roots: Iterable[str] = (),
) -> DeliberationEntryProjection:
    """Append one text-and-reference ledger entry as its own graph revision."""
    snapshot = store.snapshot()
    prepared = prepare_deliberation_entry(
        snapshot,
        protocol,
        space_root=space_root,
        actor_root=actor_root,
        category_root=category_root,
        content=content,
        idempotency_key=idempotency_key,
        created_at=created_at,
        authorization_protocol=authorization_protocol,
        authentication_broker=authentication_broker,
        authentication_context=authentication_context,
        recipient_roots=recipient_roots,
        reference_roots=reference_roots,
        reply_to_root=reply_to_root,
        evidence_roots=evidence_roots,
    )
    if prepared.existing_entry is not None:
        return prepared.existing_entry
    store.commit(
        snapshot.revision,
        create=prepared.create,
        replace=prepared.replace,
    )
    return read_deliberation_entry(store.snapshot(), protocol, prepared.root_id)


# One ledger payload may hold this many cells. Measured on the real payloads
# (2026-09-05): a structured receipt is tens of cells; the Core Values authority
# report, validated whole from the ledger by its reader, is 688; a hook-coverage
# report slimmed to one status per client and the one touchpoint the write gate
# reads is ~1,230 (the cell encoding spends ~5 cells per scalar); the full
# per-hook dump that grew the founder's graph to 4.29 GB was ~2,180 per audit.
_DELIBERATION_PAYLOAD_CELL_LIMIT = 1_500


@with_relation_projection_scope
def append_deliberation_value_entry(
    store: CellStore,
    protocol: DeliberationProtocol,
    value_protocol: ValueGraphProtocol,
    *,
    space_root: str,
    actor_root: str,
    category_root: str,
    content: str,
    payload: object,
    payload_root: str,
    idempotency_key: str,
    created_at: str,
    authorization_protocol: AuthorizationProtocol,
    authentication_broker: AuthenticationBroker,
    authentication_context: object,
    recipient_roots: Iterable[str] = (),
    evidence_roots: Iterable[str] = (),
) -> tuple[DeliberationEntryProjection, str, int]:
    """Atomically append one ledger entry and its openable value payload."""
    snapshot = store.snapshot()
    prepared_entry = prepare_deliberation_entry(
        snapshot,
        protocol,
        space_root=space_root,
        actor_root=actor_root,
        category_root=category_root,
        content=content,
        idempotency_key=idempotency_key,
        created_at=created_at,
        authorization_protocol=authorization_protocol,
        authentication_broker=authentication_broker,
        authentication_context=authentication_context,
        recipient_roots=recipient_roots,
        reference_roots=(payload_root,),
        evidence_roots=evidence_roots,
        pending_root_ids=(payload_root,),
    )
    if prepared_entry.existing_entry is not None:
        if read_value_graph(snapshot, value_protocol, payload_root) != payload:
            raise InvalidCell(
                "deliberation idempotency identity was reused for another value"
            )
        return prepared_entry.existing_entry, payload_root, snapshot.revision

    prepared_value = prepare_value_graph(
        snapshot, value_protocol, payload, root_id=payload_root
    )
    # A ledger entry records a DECISION; its payload is the evidence for that
    # decision, not a report dump. The brain's hook-coverage audit appended its
    # whole per-client report here on every run: ~2,180 cells an audit, 1,056
    # audits, and the founder's graph went 534 MB -> 4.29 GB with boot at 694s
    # (2026-09-05). Callers write a summary and a digest; the report itself
    # lives where it is read from. The bound makes that structural.
    if len(prepared_value.create) > _DELIBERATION_PAYLOAD_CELL_LIMIT:
        raise InvalidCell(
            "deliberation payload expands to %d cells, over the %d-cell bound; "
            "record a summary and a digest instead of the whole report"
            % (len(prepared_value.create), _DELIBERATION_PAYLOAD_CELL_LIMIT)
        )
    create = (*prepared_value.create, *prepared_entry.create)
    if len({cell.id for cell in create}) != len(create):
        raise InvalidCell("atomic deliberation payload identities collide")
    revision = store.commit(
        snapshot.revision,
        create=create,
        replace=(*prepared_value.replace, *prepared_entry.replace),
    )
    committed = store.snapshot()
    entry = read_deliberation_entry(committed, protocol, prepared_entry.root_id)
    if read_value_graph(committed, value_protocol, payload_root) != payload:
        raise InvalidCell("committed deliberation payload does not round-trip")
    return entry, payload_root, revision


@with_relation_projection_scope
def read_authorized_deliberation_entries(
    snapshot: Snapshot,
    protocol: DeliberationProtocol,
    *,
    space_root: str,
    read_action_root: str,
    authorization_protocol: AuthorizationProtocol,
    authentication_broker: AuthenticationBroker,
    authentication_context: object,
) -> tuple[DeliberationEntryProjection, ...]:
    """Read a graph ledger only through its graph-held authority policy."""
    space = read_deliberation_space(snapshot, protocol, space_root)
    require_authorization(
        snapshot,
        authorization_protocol,
        space.policy_root,
        authentication_broker,
        authentication_context,
        AuthorizationRequest(
            action_root=read_action_root,
            object_root=space.root_id,
            resource_lineage_roots=space.scope_roots,
            interface_root=space.interface_root,
            purpose_root=space.purpose_root,
            classification_root=space.classification_root,
            audience_root=space.audience_root,
            lifecycle_state_root=space.lifecycle_root,
            operational_state_root=space.operational_state_root,
        ),
    )
    return list_deliberation_entries(snapshot, protocol, space_root)


def evaluate_deliberation_gate(
    snapshot: Snapshot,
    protocol: DeliberationProtocol,
    space_root: str,
    *,
    phase_root: str,
    reference_root: str,
    budget: int = RELATION_BUDGET,
) -> DeliberationGateProjection:
    if phase_root not in snapshot.cells or reference_root not in snapshot.cells:
        raise InvalidCell("deliberation gate references missing Cells")
    space = read_deliberation_space(
        snapshot, protocol, space_root, budget=budget
    )
    requirements = tuple(
        _read_requirement(snapshot, protocol, root, budget=budget)
        for root in space.requirement_roots
    )
    required = tuple(
        requirement for requirement in requirements
        if requirement.phase_root == phase_root
    )
    if not required:
        raise InvalidCell("deliberation gate phase has no graph requirement")
    matching = tuple(
        entry for entry in list_deliberation_entries(
            snapshot, protocol, space_root, budget=budget
        )
        if reference_root in entry.reference_roots
    )
    counts = {
        category: sum(
            entry.category_root == category for entry in matching
        )
        for category in dict.fromkeys(
            requirement.category_root for requirement in required
        )
    }
    evidence_counts = {
        category: len({
            evidence_root
            for entry in matching
            if entry.category_root == category
            for evidence_root in entry.evidence_roots
        })
        for category in dict.fromkeys(
            requirement.category_root for requirement in required
        )
    }
    missing = tuple(
        requirement.category_root for requirement in required
        if counts.get(requirement.category_root, 0) < requirement.minimum_count
    )
    missing_evidence = tuple(
        requirement.category_root for requirement in required
        if evidence_counts.get(requirement.category_root, 0)
        < requirement.minimum_evidence_count
    )
    present = tuple(
        category for category in counts if counts[category] > 0
    )
    return DeliberationGateProjection(
        space_root=space.root_id,
        phase_root=phase_root,
        reference_root=reference_root,
        allowed=not missing and not missing_evidence,
        required_category_roots=tuple(
            requirement.category_root for requirement in required
        ),
        present_category_roots=present,
        missing_category_roots=missing,
        missing_evidence_category_roots=missing_evidence,
        matching_entry_roots=tuple(entry.root_id for entry in matching),
        observed_counts=MappingProxyType(counts),
        observed_evidence_counts=MappingProxyType(evidence_counts),
    )


__all__ = [
    "DeliberationEntryProjection",
    "DeliberationGateProjection",
    "DeliberationProtocol",
    "DeliberationRequirement",
    "DeliberationSpaceBuild",
    "DeliberationSpaceProjection",
    "PreparedDeliberationEntry",
    "append_deliberation_entry",
    "append_deliberation_value_entry",
    "bootstrap_deliberation_protocol",
    "compose_deliberation_space",
    "extend_deliberation_space",
    "evaluate_deliberation_gate",
    "list_deliberation_entries",
    "open_deliberation_protocol",
    "prepare_deliberation_entry",
    "read_authorized_deliberation_entries",
    "read_deliberation_entry",
    "read_deliberation_space",
    "upgrade_deliberation_protocol",
]
