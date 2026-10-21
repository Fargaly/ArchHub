"""Released graph contracts for generic visual relation authoring.

The interpreter in this module knows only relations, input sources, terminal
text, existing roots, constraints, and relation attachments.  Product labels
such as Parameter, Interface, BIM, Brain, or Session never enter its dispatch.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
from types import MappingProxyType
from typing import Iterable, Mapping
import uuid

from .cell_protocols import (
    CellBatch,
    compose_relation_cells,
    prepare_append_relation_members,
    read_relation,
)
from .cell_relation_contract import (
    RelationContractProtocol,
    compose_validated_relation,
    read_relation_contract,
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
    "control",
    "command",
    "operation",
    "relation-contract",
    "input",
    "source",
    "key",
    "value-kind",
    "requirement",
    "maximum-bytes",
    "participant-role",
    "fixed-value",
    "allowed-value",
    "attachment",
    "target-source",
    "target-key",
    "target-root",
    "member-role",
    "lifecycle",
    "digest",
)
STATE_NAMES = ("draft", "released")
SOURCE_NAMES = ("submitted", "context", "fixed")
VALUE_KIND_NAMES = ("text", "root")
REQUIREMENT_NAMES = ("required", "optional")


@dataclass(frozen=True, slots=True)
class RelationFormProtocol:
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
            raise InvalidCell("unknown relation-form role %r" % name) from exc


@dataclass(frozen=True, slots=True)
class RelationFormInputSpec:
    root_id: str
    key: str
    source: str
    value_kind: str
    required: bool
    maximum_bytes: int
    participant_role: str
    fixed_value_root: str | None
    allowed_value_roots: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RelationFormAttachmentSpec:
    root_id: str
    target_source: str
    target_key: str | None
    target_root: str | None
    member_role: str


@dataclass(frozen=True, slots=True)
class RelationFormBinding:
    root_id: str
    control_root: str
    command_root: str
    operation_root: str
    relation_contract_root: str
    input_specs: tuple[RelationFormInputSpec, ...]
    attachment_specs: tuple[RelationFormAttachmentSpec, ...]
    lifecycle_root: str
    lifecycle_incidence_id: str
    digest_root: str


@dataclass(frozen=True, slots=True)
class RelationFormCandidate:
    binding_root: str
    relation_root: str
    input_participants: Mapping[str, str]
    create: tuple[Cell, ...]
    replace: tuple[Cell, ...]


def _leaf(batch: CellBatch, root_id: str, atom: str | bytes) -> str:
    encoded = atom if isinstance(atom, bytes) else atom.encode("utf-8")
    batch.add(Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, encoded))
    return root_id


def bootstrap_relation_form_protocol(
    store: CellStore,
    *,
    prefix: str = "relation-form-protocol",
) -> RelationFormProtocol:
    root_id = prefix + ":root"
    snapshot = store.snapshot()
    if root_id in snapshot.cells:
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
        expected_roots = (
            *roles.values(),
            *states.values(),
            *sources.values(),
            *value_kinds.values(),
            *requirements.values(),
        )
        members = read_relation(snapshot, root_id, budget=256)
        vocabulary_role = roles["vocabulary-member"]
        if any(member.role_id != vocabulary_role for member in members):
            raise InvalidCell("relation-form protocol vocabulary drifted")
        vocabulary = {member.participant_id for member in members}
        if vocabulary - set(expected_roots):
            raise InvalidCell("relation-form protocol vocabulary drifted")
        create = tuple(
            Cell(root, NULL_CELL_ID, NULL_CELL_ID, root.rsplit(":", 1)[-1].encode("utf-8"))
            for root in expected_roots
            if root not in snapshot.cells
        )
        missing_members = tuple(
            (vocabulary_role, root) for root in expected_roots
            if root not in vocabulary
        )
        if create or missing_members:
            patch = prepare_append_relation_members(
                snapshot, root_id, missing_members, budget=256
            )
            store.commit(
                snapshot.revision,
                create=(*create, *patch.create),
                replace=patch.replace,
            )
        return open_relation_form_protocol(store.snapshot(), prefix=prefix)
    batch = CellBatch(store)
    roles = {
        name: _leaf(batch, "%s:role:%s" % (prefix, name), name)
        for name in ROLE_NAMES
    }
    states = {
        name: _leaf(batch, "%s:state:%s" % (prefix, name), name)
        for name in STATE_NAMES
    }
    sources = {
        name: _leaf(batch, "%s:source:%s" % (prefix, name), name)
        for name in SOURCE_NAMES
    }
    value_kinds = {
        name: _leaf(batch, "%s:value-kind:%s" % (prefix, name), name)
        for name in VALUE_KIND_NAMES
    }
    requirements = {
        name: _leaf(batch, "%s:requirement:%s" % (prefix, name), name)
        for name in REQUIREMENT_NAMES
    }
    batch.relation(
        (
            (roles["vocabulary-member"], member)
            for member in (
                *roles.values(),
                *states.values(),
                *sources.values(),
                *value_kinds.values(),
                *requirements.values(),
            )
        ),
        relation_id=root_id,
    )
    batch.commit()
    return RelationFormProtocol(
        root_id,
        MappingProxyType(roles),
        MappingProxyType(states),
        MappingProxyType(sources),
        MappingProxyType(value_kinds),
        MappingProxyType(requirements),
    )


def _single(members, role_id: str, label: str) -> str:
    values = tuple(
        member.participant_id for member in members if member.role_id == role_id
    )
    if len(values) != 1:
        raise InvalidCell("relation form requires exactly one %s" % label)
    return values[0]


def _optional(members, role_id: str, label: str) -> str | None:
    values = tuple(
        member.participant_id for member in members if member.role_id == role_id
    )
    if len(values) > 1:
        raise InvalidCell("relation form repeats %s" % label)
    return values[0] if values else None


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


def open_relation_form_protocol(
    snapshot: Snapshot,
    *,
    prefix: str = "relation-form-protocol",
) -> RelationFormProtocol:
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    states = {name: "%s:state:%s" % (prefix, name) for name in STATE_NAMES}
    sources = {name: "%s:source:%s" % (prefix, name) for name in SOURCE_NAMES}
    value_kinds = {
        name: "%s:value-kind:%s" % (prefix, name) for name in VALUE_KIND_NAMES
    }
    requirements = {
        name: "%s:requirement:%s" % (prefix, name)
        for name in REQUIREMENT_NAMES
    }
    root_id = prefix + ":root"
    members = read_relation(snapshot, root_id, budget=256)
    vocabulary = tuple(member.participant_id for member in members)
    expected = {
        *roles.values(), *states.values(), *sources.values(),
        *value_kinds.values(), *requirements.values(),
    }
    if (
        any(member.role_id != roles["vocabulary-member"] for member in members)
        or set(vocabulary) != expected
        or len(vocabulary) != len(expected)
    ):
        raise InvalidCell("relation-form protocol vocabulary drifted")
    for root in expected:
        expected_atom = root.rsplit(":", 1)[-1]
        if _text(snapshot, root, "relation-form vocabulary") != expected_atom:
            raise InvalidCell("relation-form vocabulary atom drifted")
    return RelationFormProtocol(
        root_id,
        MappingProxyType(roles),
        MappingProxyType(states),
        MappingProxyType(sources),
        MappingProxyType(value_kinds),
        MappingProxyType(requirements),
    )


def _read_input_spec(
    snapshot: Snapshot,
    protocol: RelationFormProtocol,
    root_id: str,
) -> RelationFormInputSpec:
    members = read_relation(snapshot, root_id, budget=128)
    allowed_roles = {
        protocol.role("key"), protocol.role("source"),
        protocol.role("value-kind"), protocol.role("requirement"),
        protocol.role("maximum-bytes"), protocol.role("participant-role"),
        protocol.role("fixed-value"), protocol.role("allowed-value"),
    }
    if any(member.role_id not in allowed_roles for member in members):
        raise InvalidCell("relation-form input contains an undeclared role")
    key_root = _single(members, protocol.role("key"), "input key")
    source_root = _single(members, protocol.role("source"), "input source")
    kind_root = _single(members, protocol.role("value-kind"), "value kind")
    requirement_root = _single(
        members, protocol.role("requirement"), "input requirement"
    )
    maximum_root = _single(
        members, protocol.role("maximum-bytes"), "maximum bytes"
    )
    participant_role = _single(
        members, protocol.role("participant-role"), "participant role"
    )
    fixed = _optional(members, protocol.role("fixed-value"), "fixed value")
    if source_root not in protocol.sources.values():
        raise InvalidCell("relation-form input source is not admitted")
    if kind_root not in protocol.value_kinds.values():
        raise InvalidCell("relation-form value kind is not admitted")
    if requirement_root not in protocol.requirements.values():
        raise InvalidCell("relation-form requirement is not admitted")
    if participant_role not in snapshot.cells:
        raise InvalidCell("relation-form participant role is missing")
    try:
        maximum = int(_text(snapshot, maximum_root, "maximum bytes"))
    except ValueError as exc:
        raise InvalidCell("relation-form maximum bytes is invalid") from exc
    if maximum < 0:
        raise InvalidCell("relation-form maximum bytes cannot be negative")
    source = _text(snapshot, source_root, "input source")
    value_kind = _text(snapshot, kind_root, "value kind")
    if (source == "fixed") != (fixed is not None):
        raise InvalidCell("fixed relation-form input has invalid value authority")
    allowed = tuple(
        member.participant_id for member in members
        if member.role_id == protocol.role("allowed-value")
    )
    if len(allowed) != len(set(allowed)):
        raise InvalidCell("relation-form input repeats an allowed value")
    if any(root not in snapshot.cells for root in allowed):
        raise InvalidCell("relation-form allowed value is missing")
    if value_kind == "text" and (fixed is not None or allowed):
        raise InvalidCell("text input cannot reference root-value constraints")
    return RelationFormInputSpec(
        root_id,
        _text(snapshot, key_root, "input key"),
        source,
        value_kind,
        requirement_root == protocol.requirements["required"],
        maximum,
        participant_role,
        fixed,
        allowed,
    )


def _read_attachment_spec(
    snapshot: Snapshot,
    protocol: RelationFormProtocol,
    root_id: str,
) -> RelationFormAttachmentSpec:
    members = read_relation(snapshot, root_id, budget=64)
    allowed_roles = {
        protocol.role("target-source"), protocol.role("target-key"),
        protocol.role("target-root"), protocol.role("member-role"),
    }
    if any(member.role_id not in allowed_roles for member in members):
        raise InvalidCell("relation-form attachment contains an undeclared role")
    source_root = _single(
        members, protocol.role("target-source"), "attachment source"
    )
    source = _text(snapshot, source_root, "attachment source")
    if source not in ("context", "fixed"):
        raise InvalidCell("attachment source must be context or fixed")
    key_root = _optional(members, protocol.role("target-key"), "target key")
    target_root = _optional(members, protocol.role("target-root"), "target root")
    member_role = _single(
        members, protocol.role("member-role"), "attachment member role"
    )
    if (source == "context") != (key_root is not None) or (
        (source == "fixed") != (target_root is not None)
    ):
        raise InvalidCell("attachment target authority is incomplete")
    if target_root is not None and target_root not in snapshot.cells:
        raise InvalidCell("fixed attachment target is missing")
    if member_role not in snapshot.cells:
        raise InvalidCell("attachment member role is missing")
    return RelationFormAttachmentSpec(
        root_id,
        source,
        _text(snapshot, key_root, "attachment target key")
        if key_root is not None else None,
        target_root,
        member_role,
    )


def _digest_fields(fields: Iterable[bytes]) -> bytes:
    digest = hashlib.sha256()
    for field in fields:
        digest.update(len(field).to_bytes(8, "big"))
        digest.update(field)
    return digest.digest()


def _binding_digest(binding: RelationFormBinding) -> bytes:
    fields = [
        binding.root_id.encode(), binding.control_root.encode(),
        binding.command_root.encode(), binding.operation_root.encode(),
        binding.relation_contract_root.encode(),
        binding.lifecycle_root.encode(),
    ]
    for spec in binding.input_specs:
        fields.extend((
            spec.root_id.encode(), spec.key.encode(), spec.source.encode(),
            spec.value_kind.encode(), b"1" if spec.required else b"0",
            str(spec.maximum_bytes).encode(), spec.participant_role.encode(),
            (spec.fixed_value_root or "").encode(),
            *(root.encode() for root in spec.allowed_value_roots),
        ))
    for spec in binding.attachment_specs:
        fields.extend((
            spec.root_id.encode(), spec.target_source.encode(),
            (spec.target_key or "").encode(), (spec.target_root or "").encode(),
            spec.member_role.encode(),
        ))
    return _digest_fields(fields)


def read_relation_form_binding(
    snapshot: Snapshot,
    protocol: RelationFormProtocol,
    binding_root: str,
    *,
    require_released: bool = True,
) -> RelationFormBinding:
    members = read_relation(snapshot, binding_root, budget=512)
    allowed_roles = {
        protocol.role("control"), protocol.role("command"),
        protocol.role("operation"),
        protocol.role("relation-contract"), protocol.role("input"),
        protocol.role("attachment"), protocol.role("lifecycle"),
        protocol.role("digest"),
    }
    if any(member.role_id not in allowed_roles for member in members):
        raise InvalidCell("relation-form binding contains an undeclared role")
    lifecycle_member = next(
        (
            member for member in members
            if member.role_id == protocol.role("lifecycle")
        ),
        None,
    )
    if lifecycle_member is None or sum(
        member.role_id == protocol.role("lifecycle") for member in members
    ) != 1:
        raise InvalidCell("relation form requires exactly one lifecycle")
    lifecycle = lifecycle_member.participant_id
    if lifecycle not in protocol.states.values():
        raise InvalidCell("relation-form lifecycle is not admitted")
    binding = RelationFormBinding(
        binding_root,
        _single(members, protocol.role("control"), "control"),
        _single(members, protocol.role("command"), "command"),
        _single(members, protocol.role("operation"), "operation"),
        _single(
            members, protocol.role("relation-contract"), "relation contract"
        ),
        tuple(
            _read_input_spec(snapshot, protocol, member.participant_id)
            for member in members if member.role_id == protocol.role("input")
        ),
        tuple(
            _read_attachment_spec(snapshot, protocol, member.participant_id)
            for member in members
            if member.role_id == protocol.role("attachment")
        ),
        lifecycle,
        lifecycle_member.incidence_id,
        _single(members, protocol.role("digest"), "digest"),
    )
    keys = tuple(spec.key for spec in binding.input_specs)
    if not keys or len(keys) != len(set(keys)):
        raise InvalidCell("relation-form input keys are empty or duplicated")
    digest_cell = _terminal(snapshot, binding.digest_root, "relation-form digest")
    if lifecycle == protocol.states["draft"]:
        if digest_cell.atom:
            raise InvalidCell("draft relation form has protected digest bytes")
        if require_released:
            raise InvalidCell("relation form is not released")
    elif not digest_cell.atom or not hmac.compare_digest(
        digest_cell.atom, _binding_digest(binding)
    ):
        raise InvalidCell("released relation form has been tampered with")
    return binding


def build_relation_form_binding(
    store: CellStore,
    protocol: RelationFormProtocol,
    *,
    binding_id: str,
    control_root: str,
    command_root: str,
    operation_root: str,
    relation_contract_root: str,
    inputs: Iterable[Mapping[str, object]],
    attachments: Iterable[Mapping[str, str]],
    released: bool = False,
) -> RelationFormBinding:
    snapshot = store.snapshot()
    if any(
        root not in snapshot.cells
        for root in (
            control_root, command_root, operation_root, relation_contract_root
        )
    ):
        raise InvalidCell("relation-form authority root is missing")
    batch = CellBatch(store)
    input_roots = []
    input_keys: set[str] = set()
    for index, raw in enumerate(inputs):
        if not isinstance(raw, Mapping):
            raise InvalidCell("relation-form input specification must be a mapping")
        root = "%s:input:%s" % (binding_id, index)
        key = raw.get("key")
        source = raw.get("source")
        value_kind = raw.get("value_kind")
        required = raw.get("required", True)
        maximum = raw.get("maximum_bytes", 0)
        participant_role = raw.get("participant_role")
        fixed = raw.get("fixed_value_root")
        raw_allowed = raw.get("allowed_value_roots", ())
        if (
            type(key) is not str
            or not key
            or key in input_keys
            or type(source) is not str
            or type(value_kind) is not str
            or type(required) is not bool
            or type(maximum) is not int
            or type(participant_role) is not str
            or (fixed is not None and type(fixed) is not str)
            or type(raw_allowed) not in (tuple, list)
            or any(type(value) is not str for value in raw_allowed)
        ):
            raise InvalidCell("relation-form input specification is invalid")
        allowed = tuple(raw_allowed)
        if source not in protocol.sources or value_kind not in protocol.value_kinds:
            raise InvalidCell("relation-form input specification is not admitted")
        if maximum < 0 or participant_role not in snapshot.cells:
            raise InvalidCell("relation-form input specification is invalid")
        if fixed is not None and fixed not in snapshot.cells:
            raise InvalidCell("relation-form fixed value is missing")
        if len(allowed) != len(set(allowed)) or any(
            value not in snapshot.cells for value in allowed
        ):
            raise InvalidCell("relation-form allowed values are invalid")
        if (source == "fixed") != (fixed is not None):
            raise InvalidCell("fixed relation-form input has invalid value authority")
        if value_kind == "text" and (fixed is not None or allowed):
            raise InvalidCell("text input cannot reference root-value constraints")
        input_keys.add(key)
        key_root = _leaf(batch, root + ":key", key)
        maximum_root = _leaf(batch, root + ":maximum-bytes", str(maximum))
        members = [
            (protocol.role("key"), key_root),
            (protocol.role("source"), protocol.sources[source]),
            (protocol.role("value-kind"), protocol.value_kinds[value_kind]),
            (
                protocol.role("requirement"),
                protocol.requirements["required" if required else "optional"],
            ),
            (protocol.role("maximum-bytes"), maximum_root),
            (protocol.role("participant-role"), participant_role),
        ]
        if fixed is not None:
            members.append((protocol.role("fixed-value"), fixed))
        members.extend(
            (protocol.role("allowed-value"), value) for value in allowed
        )
        batch.relation(members, relation_id=root)
        input_roots.append(root)
    attachment_roots = []
    for index, raw in enumerate(attachments):
        if not isinstance(raw, Mapping):
            raise InvalidCell(
                "relation-form attachment specification must be a mapping"
            )
        root = "%s:attachment:%s" % (binding_id, index)
        source = raw.get("target_source")
        member_role = raw.get("member_role")
        if type(source) is not str or type(member_role) is not str:
            raise InvalidCell("relation-form attachment specification is invalid")
        if source not in ("context", "fixed") or member_role not in snapshot.cells:
            raise InvalidCell("relation-form attachment specification is invalid")
        members = [
            (protocol.role("target-source"), protocol.sources[source]),
            (protocol.role("member-role"), member_role),
        ]
        if source == "context":
            key = raw.get("target_key")
            if type(key) is not str or not key or raw.get("target_root") is not None:
                raise InvalidCell("context attachment requires a target key")
            members.append((
                protocol.role("target-key"),
                _leaf(batch, root + ":target-key", key),
            ))
        else:
            target = raw.get("target_root")
            if (
                type(target) is not str
                or target not in snapshot.cells
                or raw.get("target_key") is not None
            ):
                raise InvalidCell("fixed attachment target is missing")
            members.append((protocol.role("target-root"), target))
        batch.relation(members, relation_id=root)
        attachment_roots.append(root)
    digest_root = _leaf(batch, binding_id + ":digest", b"")
    batch.relation((
        (protocol.role("control"), control_root),
        (protocol.role("command"), command_root),
        (protocol.role("operation"), operation_root),
        (protocol.role("relation-contract"), relation_contract_root),
        *((protocol.role("input"), root) for root in input_roots),
        *((protocol.role("attachment"), root) for root in attachment_roots),
        (protocol.role("lifecycle"), protocol.states["draft"]),
        (protocol.role("digest"), digest_root),
    ), relation_id=binding_id)
    batch.commit()
    if released:
        release_relation_form_binding(store, protocol, binding_id)
    return read_relation_form_binding(
        store.snapshot(), protocol, binding_id, require_released=released
    )


def release_relation_form_binding(
    store: CellStore,
    protocol: RelationFormProtocol,
    binding_root: str,
) -> bytes:
    snapshot = store.snapshot()
    binding = read_relation_form_binding(
        snapshot, protocol, binding_root, require_released=False
    )
    if binding.lifecycle_root != protocol.states["draft"]:
        raise InvalidCell("relation form is not a releasable draft")
    released_binding = RelationFormBinding(
        binding.root_id,
        binding.control_root,
        binding.command_root,
        binding.operation_root,
        binding.relation_contract_root,
        binding.input_specs,
        binding.attachment_specs,
        protocol.states["released"],
        binding.lifecycle_incidence_id,
        binding.digest_root,
    )
    lifecycle = snapshot.cells[binding.lifecycle_incidence_id]
    digest = snapshot.cells[binding.digest_root]
    value = _binding_digest(released_binding)
    store.commit(snapshot.revision, replace=(
        Cell(lifecycle.id, lifecycle.link0, protocol.states["released"], lifecycle.atom),
        Cell(digest.id, digest.link0, digest.link1, value),
    ))
    return value


def compose_relation_form_submission(
    snapshot: Snapshot,
    protocol: RelationFormProtocol,
    relation_protocol: RelationContractProtocol,
    binding_root: str,
    submitted: Mapping[str, str],
    context: Mapping[str, object],
    *,
    relation_id: str | None = None,
    budget: int = 10_000,
) -> RelationFormCandidate:
    binding = read_relation_form_binding(snapshot, protocol, binding_root)
    contract = read_relation_contract(
        snapshot, relation_protocol, binding.relation_contract_root,
        budget=budget,
    )
    if contract.lifecycle_root == relation_protocol.state("draft"):
        raise InvalidCell("relation form references an unreleased relation contract")
    expected_submitted = {
        spec.key for spec in binding.input_specs if spec.source == "submitted"
    }
    if set(submitted) != expected_submitted:
        raise InvalidCell("relation-form submission fields do not match authority")
    created_participants: list[Cell] = []
    participants: dict[str, str] = {}
    bindings: list[tuple[str, str]] = []
    token = uuid.uuid4().hex
    for index, spec in enumerate(binding.input_specs):
        if spec.source == "submitted":
            value = submitted[spec.key]
        elif spec.source == "context":
            try:
                value = context[spec.key]
            except KeyError as exc:
                raise InvalidCell("relation-form context input is missing") from exc
        else:
            if spec.fixed_value_root is None:
                raise InvalidCell("relation-form fixed input is incomplete")
            value = spec.fixed_value_root
        if type(value) is not str:
            raise InvalidCell("relation-form input value must be text")
        if spec.value_kind == "text":
            encoded = value.encode("utf-8")
            if spec.required and not value.strip():
                raise InvalidCell("required relation-form text is empty")
            if len(encoded) > spec.maximum_bytes:
                raise InvalidCell("relation-form text exceeds its byte limit")
            participant = "relation-form-value:%s:%s" % (token, index)
            created_participants.append(
                Cell(participant, NULL_CELL_ID, NULL_CELL_ID, encoded)
            )
        else:
            participant = value
            if participant not in snapshot.cells:
                raise InvalidCell("relation-form root input is missing")
            if spec.allowed_value_roots and participant not in spec.allowed_value_roots:
                raise InvalidCell("relation-form root input is outside its allowlist")
        participants[spec.key] = participant
        bindings.append((spec.participant_role, participant))

    staged_candidate = overlay_read_snapshot(
        snapshot, create=tuple(created_participants)
    )
    staged = Snapshot(snapshot.revision, staged_candidate.cells)
    relation = compose_validated_relation(
        staged,
        relation_protocol,
        binding.relation_contract_root,
        bindings,
        relation_id=relation_id,
        budget=budget,
    )
    create: dict[str, Cell] = {
        cell.id: cell for cell in (*created_participants, *relation.cells)
    }
    replace: dict[str, Cell] = {}
    staged_candidate = overlay_read_snapshot(
        snapshot, create=tuple(create.values())
    )
    staged = Snapshot(snapshot.revision, staged_candidate.cells)
    for attachment in binding.attachment_specs:
        if attachment.target_source == "context":
            try:
                target_value = context[attachment.target_key or ""]
            except KeyError as exc:
                raise InvalidCell("relation-form attachment context is missing") from exc
            if type(target_value) is str:
                targets = (target_value,)
            elif (
                type(target_value) is tuple
                and target_value
                and all(type(target) is str for target in target_value)
                and len(target_value) == len(set(target_value))
            ):
                targets = target_value
            else:
                raise InvalidCell(
                    "relation-form attachment context must be exact roots"
                )
        else:
            targets = (attachment.target_root or "",)
        for target in targets:
            if target not in staged.cells:
                raise InvalidCell("relation-form attachment target is missing")
            patch = prepare_append_relation_members(
                staged,
                target,
                ((attachment.member_role, relation.root_id),),
                budget=budget,
            )
            for cell in patch.create:
                if cell.id in create or cell.id in replace or cell.id in snapshot.cells:
                    raise InvalidCell("relation-form attachment identity collides")
                create[cell.id] = cell
            for cell in patch.replace:
                if cell.id in create:
                    create[cell.id] = cell
                    continue
                previous = replace.get(cell.id)
                if previous is not None and previous != cell:
                    raise InvalidCell("relation-form attachments conflict")
                replace[cell.id] = cell
            staged_candidate = overlay_read_snapshot(
                snapshot,
                create=tuple(create.values()),
                replace=tuple(replace.values()),
            )
            staged = Snapshot(snapshot.revision, staged_candidate.cells)
    return RelationFormCandidate(
        binding.root_id,
        relation.root_id,
        MappingProxyType(participants),
        tuple(create.values()),
        tuple(replace.values()),
    )


__all__ = [
    "RelationFormAttachmentSpec",
    "RelationFormBinding",
    "RelationFormCandidate",
    "RelationFormInputSpec",
    "RelationFormProtocol",
    "bootstrap_relation_form_protocol",
    "build_relation_form_binding",
    "compose_relation_form_submission",
    "open_relation_form_protocol",
    "read_relation_form_binding",
    "release_relation_form_binding",
]
