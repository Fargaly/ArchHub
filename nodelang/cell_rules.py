"""Editable graph protocol for generic universal-cell rewrite rules."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from types import MappingProxyType
from typing import Mapping

from .cell_protocols import CellBatch, RelationMember, read_relation
from .universal_cell import (
    NULL_CELL_ID,
    Cell,
    CellStore,
    Conflict,
    InvalidCell,
    RewriteResult,
    Snapshot,
)


@dataclass(frozen=True, slots=True)
class RuleProtocol:
    root_id: str
    vocabulary_member_role: str
    pattern_role: str
    replacement_role: str
    pattern_variable_role: str
    replacement_variable_role: str
    constant_role: str
    binding_role: str


@dataclass(frozen=True, slots=True)
class RuleBuild:
    root_id: str
    binding_roots: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RuleProjection:
    root_id: str
    pattern_root: str
    replacement_root: str
    pattern_variables: tuple[str, ...]
    replacement_bindings: Mapping[str, str]
    replacement_constants: Mapping[str, str]
    binding_roots: tuple[str, ...]


_ROLE_FIELDS = (
    ("vocabulary member", "vocabulary_member_role"),
    ("pattern", "pattern_role"),
    ("replacement", "replacement_role"),
    ("pattern variable", "pattern_variable_role"),
    ("replacement variable", "replacement_variable_role"),
    ("constant", "constant_role"),
    ("binding", "binding_role"),
)


def bootstrap_rule_protocol(
    store: CellStore,
    *,
    prefix: str = "rule-protocol",
) -> RuleProtocol:
    role_roots = {
        field: "%s:role:%s" % (prefix, label.replace(" ", "-"))
        for label, field in _ROLE_FIELDS
    }
    protocol = RuleProtocol(
        root_id="%s:root" % prefix,
        **role_roots,
    )
    batch = CellBatch(store)
    for label, field in _ROLE_FIELDS:
        role_id = getattr(protocol, field)
        batch.add(Cell(role_id, NULL_CELL_ID, NULL_CELL_ID, label.encode("utf-8")))
    batch.relation(
        (
            (protocol.vocabulary_member_role, getattr(protocol, field))
            for _label, field in _ROLE_FIELDS
        ),
        relation_id=protocol.root_id,
    )
    batch.commit()
    return protocol


def project_rule_protocol(
    snapshot: Snapshot,
    root_id: str,
    *,
    budget: int = 128,
) -> RuleProtocol:
    """Reconstruct the rule vocabulary from its graph-held root."""
    members = read_relation(snapshot, root_id, budget=budget)
    if not members:
        raise InvalidCell("rule protocol vocabulary is empty")
    vocabulary_roles = {member.role_id for member in members}
    if len(vocabulary_roles) != 1:
        raise InvalidCell("rule protocol vocabulary has inconsistent incidences")
    vocabulary_role = next(iter(vocabulary_roles))
    by_label: dict[str, str] = {}
    for member in members:
        cell = snapshot.cells[member.participant_id]
        if cell.link0 != NULL_CELL_ID or cell.link1 != NULL_CELL_ID:
            raise InvalidCell("rule protocol role is not terminal")
        try:
            label = cell.atom.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise InvalidCell("rule protocol role label is not UTF-8") from exc
        if label in by_label:
            raise InvalidCell("rule protocol repeats a role label")
        by_label[label] = member.participant_id
    expected = {label for label, _field in _ROLE_FIELDS}
    if set(by_label) != expected:
        raise InvalidCell("rule protocol vocabulary is incomplete or extended")
    if by_label["vocabulary member"] != vocabulary_role:
        raise InvalidCell("rule protocol vocabulary role does not self-identify")
    return RuleProtocol(
        root_id=root_id,
        **{
            field: by_label[label]
            for label, field in _ROLE_FIELDS
        },
    )


def build_rule(
    store: CellStore,
    protocol: RuleProtocol,
    *,
    rule_id: str,
    pattern_root: str,
    replacement_root: str,
    pattern_variables: tuple[str, ...],
    replacement_bindings: Mapping[str, str],
    replacement_constants: Mapping[str, str] | None = None,
) -> RuleBuild:
    declared = frozenset(pattern_variables)
    constants = dict(replacement_constants or {})
    if not set(replacement_bindings.values()).issubset(declared):
        raise InvalidCell("replacement binding references an undeclared variable")
    if set(replacement_bindings).intersection(constants):
        raise InvalidCell("replacement placeholder has conflicting bindings")
    batch = CellBatch(store)
    binding_roots: list[str] = []
    specifications = [
        (replacement_variable, protocol.pattern_variable_role, pattern_variable)
        for replacement_variable, pattern_variable
        in sorted(replacement_bindings.items())
    ] + [
        (replacement_variable, protocol.constant_role, constant_root)
        for replacement_variable, constant_root in sorted(constants.items())
    ]
    for index, (replacement_variable, binding_role, binding_root_id) in enumerate(
        specifications
    ):
        binding_root = "%s:binding:%s" % (rule_id, index)
        batch.relation([
            (protocol.replacement_variable_role, replacement_variable),
            (binding_role, binding_root_id),
        ], relation_id=binding_root)
        binding_roots.append(binding_root)
    members = [
        (protocol.pattern_role, pattern_root),
        (protocol.replacement_role, replacement_root),
    ]
    members.extend(
        (protocol.pattern_variable_role, variable)
        for variable in pattern_variables
    )
    members.extend(
        (protocol.binding_role, binding_root)
        for binding_root in binding_roots
    )
    batch.relation(members, relation_id=rule_id)
    batch.commit()
    return RuleBuild(rule_id, tuple(binding_roots))


def _members_for_role(
    members: tuple[RelationMember, ...],
    role_id: str,
) -> tuple[str, ...]:
    return tuple(
        member.participant_id for member in members if member.role_id == role_id
    )


def _single(members: tuple[RelationMember, ...], role_id: str) -> str:
    values = _members_for_role(members, role_id)
    if len(values) != 1:
        raise InvalidCell("rule protocol requires exactly one %r participant" % role_id)
    return values[0]


def read_rule(
    snapshot: Snapshot,
    protocol: RuleProtocol,
    rule_root: str,
    *,
    budget: int = 10_000,
) -> RuleProjection:
    if project_rule_protocol(snapshot, protocol.root_id, budget=budget) != protocol:
        raise InvalidCell("rule protocol authority drifted")
    members = read_relation(snapshot, rule_root, budget=budget)
    admitted_rule_roles = {
        protocol.pattern_role,
        protocol.replacement_role,
        protocol.pattern_variable_role,
        protocol.binding_role,
    }
    if any(member.role_id not in admitted_rule_roles for member in members):
        raise InvalidCell("rule contains an undeclared participant role")
    pattern_root = _single(members, protocol.pattern_role)
    replacement_root = _single(members, protocol.replacement_role)
    pattern_variables = _members_for_role(
        members, protocol.pattern_variable_role
    )
    if len(pattern_variables) != len(set(pattern_variables)):
        raise InvalidCell("rule repeats a pattern variable")
    binding_roots = _members_for_role(members, protocol.binding_role)
    if len(binding_roots) != len(set(binding_roots)):
        raise InvalidCell("rule repeats a binding root")
    replacement_bindings: dict[str, str] = {}
    replacement_constants: dict[str, str] = {}
    for binding_root in binding_roots:
        binding = read_relation(snapshot, binding_root, budget=budget)
        admitted_binding_roles = {
            protocol.replacement_variable_role,
            protocol.pattern_variable_role,
            protocol.constant_role,
        }
        if any(
            member.role_id not in admitted_binding_roles for member in binding
        ):
            raise InvalidCell("rule binding contains an undeclared role")
        replacement_variable = _single(
            binding, protocol.replacement_variable_role
        )
        pattern_variables_for_binding = _members_for_role(
            binding, protocol.pattern_variable_role
        )
        constants_for_binding = _members_for_role(
            binding, protocol.constant_role
        )
        if (
            len(pattern_variables_for_binding) + len(constants_for_binding)
            != 1
        ):
            raise InvalidCell(
                "rule binding requires exactly one variable or constant"
            )
        if (
            replacement_variable in replacement_bindings
            or replacement_variable in replacement_constants
        ):
            raise InvalidCell("replacement variable is bound more than once")
        if pattern_variables_for_binding:
            pattern_variable = pattern_variables_for_binding[0]
            if pattern_variable not in pattern_variables:
                raise InvalidCell(
                    "rule binding references an undeclared pattern variable"
                )
            replacement_bindings[replacement_variable] = pattern_variable
        else:
            replacement_constants[replacement_variable] = constants_for_binding[0]
    return RuleProjection(
        rule_root,
        pattern_root,
        replacement_root,
        pattern_variables,
        MappingProxyType(replacement_bindings),
        MappingProxyType(replacement_constants),
        binding_roots,
    )


def rule_content_digest(
    snapshot: Snapshot,
    protocol: RuleProtocol,
    rule_root: str,
    *,
    budget: int = 10_000,
) -> bytes:
    """Fingerprint rule meaning while treating bound graph roots as identities."""
    rule = read_rule(snapshot, protocol, rule_root, budget=budget)
    canonical = bytearray(b"ArchHub/universal-cell-rule/v1\x00")

    def field(value: bytes) -> None:
        canonical.extend(len(value).to_bytes(8, "big"))
        canonical.extend(value)

    for value in (
        protocol.root_id,
        protocol.vocabulary_member_role,
        protocol.pattern_role,
        protocol.replacement_role,
        protocol.pattern_variable_role,
        protocol.replacement_variable_role,
        protocol.constant_role,
        protocol.binding_role,
        rule.root_id,
        rule.pattern_root,
        rule.replacement_root,
    ):
        field(value.encode("utf-8"))
    for variable in sorted(rule.pattern_variables):
        field(b"pattern-variable")
        field(variable.encode("utf-8"))
    for replacement, pattern in sorted(rule.replacement_bindings.items()):
        field(b"variable-binding")
        field(replacement.encode("utf-8"))
        field(pattern.encode("utf-8"))
    for replacement, constant in sorted(rule.replacement_constants.items()):
        field(b"constant-binding")
        field(replacement.encode("utf-8"))
        field(constant.encode("utf-8"))

    def graph(label: bytes, root_id: str, boundaries: frozenset[str]) -> None:
        pending = [root_id]
        reached: dict[str, Cell] = {}
        steps = 0
        while pending:
            steps += 1
            if steps > budget:
                raise InvalidCell("rule digest traversal exceeded its budget")
            cell_id = pending.pop()
            if cell_id == NULL_CELL_ID or cell_id in boundaries or cell_id in reached:
                continue
            try:
                cell = snapshot.cells[cell_id]
            except KeyError as exc:
                raise InvalidCell("rule graph contains a dangling cell") from exc
            reached[cell_id] = cell
            pending.extend((cell.link0, cell.link1))
        field(label)
        for cell_id in sorted(reached):
            cell = reached[cell_id]
            field(cell.id.encode("utf-8"))
            field(cell.link0.encode("utf-8"))
            field(cell.link1.encode("utf-8"))
            field(cell.atom)

    graph(b"pattern", rule.pattern_root, frozenset(rule.pattern_variables))
    graph(
        b"replacement",
        rule.replacement_root,
        frozenset((
            *rule.replacement_bindings,
            *rule.replacement_constants,
        )),
    )
    return hashlib.sha256(canonical).hexdigest().encode("ascii")


def execute_rule(
    store: CellStore,
    protocol: RuleProtocol,
    rule_root: str,
    target_root: str,
    *,
    expected_revision: int | None = None,
    budget: int = 10_000,
) -> RewriteResult:
    """Resolve all rewrite arguments from the selected rule composition."""
    snapshot = store.snapshot()
    revision = snapshot.revision if expected_revision is None else expected_revision
    if snapshot.revision != revision:
        raise Conflict(
            "expected revision %s, current revision is %s"
            % (revision, snapshot.revision)
        )
    rule = read_rule(snapshot, protocol, rule_root, budget=budget)
    return store.rewrite(
        expected_revision=revision,
        pattern_root=rule.pattern_root,
        target_root=target_root,
        pattern_variables=rule.pattern_variables,
        replacement_root=rule.replacement_root,
        replacement_variables=rule.replacement_bindings,
        replacement_constants=rule.replacement_constants,
        budget=budget,
    )


def match_rule(
    store: CellStore,
    protocol: RuleProtocol,
    rule_root: str,
    target_root: str,
    *,
    expected_revision: int | None = None,
    budget: int = 10_000,
) -> Mapping[str, str]:
    """Match one graph-held rule without materializing its replacement."""
    snapshot = store.snapshot()
    revision = snapshot.revision if expected_revision is None else expected_revision
    if snapshot.revision != revision:
        raise Conflict(
            "expected revision %s, current revision is %s"
            % (revision, snapshot.revision)
        )
    rule = read_rule(snapshot, protocol, rule_root, budget=budget)
    return MappingProxyType(store.match(
        snapshot.cells,
        pattern_root=rule.pattern_root,
        target_root=target_root,
        variables=rule.pattern_variables,
        budget=budget,
        revision=revision,
    ))


__all__ = [
    "RuleProtocol",
    "RuleBuild",
    "RuleProjection",
    "bootstrap_rule_protocol",
    "project_rule_protocol",
    "build_rule",
    "read_rule",
    "rule_content_digest",
    "match_rule",
    "execute_rule",
]
