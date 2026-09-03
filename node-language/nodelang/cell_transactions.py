"""Graph-held atomic transaction sets over generic structural rewrite rules.

A transaction is an ordinary relation whose step participants are ordinary
relations. Each step identifies one graph-held rule and one continuing target
root. Every rule is matched and materialized against the same immutable Store
revision; one Store commit publishes the complete candidate set or nothing.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from types import MappingProxyType
from typing import Callable, Iterable, Mapping

from .cell_lifecycle import graph_content_digest
from .cell_protocols import CellBatch, RelationMember, read_relation
from .cell_rules import RuleProtocol, read_rule, rule_content_digest
from .universal_cell import (
    NULL_CELL_ID,
    Cell,
    CellStore,
    Conflict,
    InvalidCell,
    PreparedRewrite,
    Snapshot,
)


ROLE_NAMES = (
    "vocabulary-member",
    "step",
    "rule",
    "target",
    "evidence",
    "outcome",
)


@dataclass(frozen=True, slots=True)
class TransactionProtocol:
    root_id: str
    roles: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown transaction role %r" % name) from exc


@dataclass(frozen=True, slots=True)
class TransactionStep:
    root_id: str
    rule_root: str
    target_root: str


@dataclass(frozen=True, slots=True)
class GraphTransaction:
    root_id: str
    steps: tuple[TransactionStep, ...]
    evidence_roots: tuple[str, ...]
    outcome_roots: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TransactionBuild:
    root_id: str
    step_roots: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TransactionExecution:
    root_id: str
    revision: int
    rewrites: tuple[PreparedRewrite, ...]
    touched_roots: tuple[str, ...]
    evidence_roots: tuple[str, ...]
    outcome_roots: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PreparedTransaction:
    root_id: str
    revision: int
    rewrites: tuple[PreparedRewrite, ...]
    create: tuple[Cell, ...]
    replace: tuple[Cell, ...]
    touched_roots: tuple[str, ...]
    evidence_roots: tuple[str, ...]
    outcome_roots: tuple[str, ...]


def bootstrap_transaction_protocol(
    store: CellStore,
    *,
    prefix: str = "transaction-protocol",
) -> TransactionProtocol:
    roles = {
        name: "%s:role:%s" % (prefix, name)
        for name in ROLE_NAMES
    }
    protocol = TransactionProtocol(
        "%s:root" % prefix,
        MappingProxyType(roles),
    )
    batch = CellBatch(store)
    for name, root_id in roles.items():
        batch.add(Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, name.encode()))
    batch.relation(
        (
            (roles["vocabulary-member"], roles[name])
            for name in ROLE_NAMES
        ),
        relation_id=protocol.root_id,
    )
    batch.commit()
    return protocol


def _single(members: tuple[RelationMember, ...], role_id: str) -> str:
    values = tuple(
        member.participant_id for member in members if member.role_id == role_id
    )
    if len(values) != 1:
        raise InvalidCell(
            "transaction protocol requires exactly one %r participant" % role_id
        )
    return values[0]


def _many(members: tuple[RelationMember, ...], role_id: str) -> tuple[str, ...]:
    return tuple(
        member.participant_id for member in members if member.role_id == role_id
    )


def project_transaction_protocol(
    snapshot: Snapshot,
    root_id: str,
    *,
    budget: int = 128,
) -> TransactionProtocol:
    members = read_relation(snapshot, root_id, budget=budget)
    if not members:
        raise InvalidCell("transaction protocol vocabulary is empty")
    vocabulary_roles = {member.role_id for member in members}
    if len(vocabulary_roles) != 1:
        raise InvalidCell(
            "transaction protocol vocabulary has inconsistent incidences"
        )
    vocabulary_role = next(iter(vocabulary_roles))
    by_label: dict[str, str] = {}
    for member in members:
        cell = snapshot.cells[member.participant_id]
        if cell.link0 != NULL_CELL_ID or cell.link1 != NULL_CELL_ID:
            raise InvalidCell("transaction protocol role is not terminal")
        try:
            label = cell.atom.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise InvalidCell("transaction protocol role is not UTF-8") from exc
        if label in by_label:
            raise InvalidCell("transaction protocol repeats a role label")
        by_label[label] = member.participant_id
    if set(by_label) != set(ROLE_NAMES):
        raise InvalidCell("transaction protocol vocabulary is incomplete or extended")
    if by_label["vocabulary-member"] != vocabulary_role:
        raise InvalidCell("transaction vocabulary role does not self-identify")
    return TransactionProtocol(root_id, MappingProxyType(by_label))


def build_transaction(
    store: CellStore,
    protocol: TransactionProtocol,
    *,
    transaction_id: str,
    steps: Iterable[tuple[str, str]],
    evidence_roots: Iterable[str] = (),
    outcome_roots: Iterable[str] = (),
) -> TransactionBuild:
    declared_steps = tuple(steps)
    evidence = tuple(evidence_roots)
    outcomes = tuple(outcome_roots)
    if not declared_steps:
        raise InvalidCell("transaction requires at least one rule step")
    if len(declared_steps) > 4_096:
        raise InvalidCell("transaction has too many rule steps")
    targets = tuple(target for _rule, target in declared_steps)
    if len(targets) != len(set(targets)):
        raise InvalidCell("transaction repeats a continuing target root")
    if len(evidence) != len(set(evidence)):
        raise InvalidCell("transaction repeats an evidence root")
    if len(outcomes) != len(set(outcomes)):
        raise InvalidCell("transaction repeats an outcome root")

    snapshot = store.snapshot()
    participants = {
        root
        for rule_root, target_root in declared_steps
        for root in (rule_root, target_root)
    } | set(evidence) | set(outcomes)
    if any(_root not in snapshot.cells for _root in participants):
        raise InvalidCell("transaction references a missing graph root")
    if project_transaction_protocol(snapshot, protocol.root_id) != protocol:
        raise InvalidCell("transaction protocol authority drifted")

    batch = CellBatch(store)
    step_roots: list[str] = []
    for index, (rule_root, target_root) in enumerate(declared_steps):
        step_root = "%s:step:%s" % (transaction_id, index)
        batch.relation((
            (protocol.role("rule"), rule_root),
            (protocol.role("target"), target_root),
        ), relation_id=step_root)
        step_roots.append(step_root)
    members = [
        (protocol.role("step"), step_root) for step_root in step_roots
    ]
    members.extend((protocol.role("evidence"), root) for root in evidence)
    members.extend((protocol.role("outcome"), root) for root in outcomes)
    batch.relation(members, relation_id=transaction_id)
    batch.commit()
    return TransactionBuild(transaction_id, tuple(step_roots))


def read_transaction(
    snapshot: Snapshot,
    protocol: TransactionProtocol,
    transaction_root: str,
    *,
    budget: int = 10_000,
) -> GraphTransaction:
    if project_transaction_protocol(
        snapshot, protocol.root_id, budget=budget
    ) != protocol:
        raise InvalidCell("transaction protocol authority drifted")
    members = read_relation(snapshot, transaction_root, budget=budget)
    admitted = {
        protocol.role("step"),
        protocol.role("evidence"),
        protocol.role("outcome"),
    }
    if any(member.role_id not in admitted for member in members):
        raise InvalidCell("transaction contains an undeclared participant role")
    step_roots = _many(members, protocol.role("step"))
    evidence = _many(members, protocol.role("evidence"))
    outcomes = _many(members, protocol.role("outcome"))
    if not step_roots or len(step_roots) > 4_096:
        raise InvalidCell("transaction has an invalid rule-step count")
    if len(step_roots) != len(set(step_roots)):
        raise InvalidCell("transaction repeats a rule-step root")
    if len(evidence) != len(set(evidence)):
        raise InvalidCell("transaction repeats an evidence root")
    if len(outcomes) != len(set(outcomes)):
        raise InvalidCell("transaction repeats an outcome root")

    steps: list[TransactionStep] = []
    for step_root in step_roots:
        step_members = read_relation(snapshot, step_root, budget=budget)
        if any(
            member.role_id not in {
                protocol.role("rule"), protocol.role("target")
            }
            for member in step_members
        ):
            raise InvalidCell("transaction step contains an undeclared role")
        steps.append(TransactionStep(
            step_root,
            _single(step_members, protocol.role("rule")),
            _single(step_members, protocol.role("target")),
        ))
    targets = tuple(step.target_root for step in steps)
    if len(targets) != len(set(targets)):
        raise InvalidCell("transaction repeats a continuing target root")
    return GraphTransaction(
        transaction_root,
        tuple(steps),
        evidence,
        outcomes,
    )


def transaction_content_digest(
    snapshot: Snapshot,
    protocol: TransactionProtocol,
    rule_protocol: RuleProtocol,
    transaction_root: str,
    *,
    budget: int = 10_000,
) -> bytes:
    transaction = read_transaction(
        snapshot, protocol, transaction_root, budget=budget
    )
    canonical = bytearray(b"ArchHub/universal-cell-transaction/v1\x00")

    def field(value: bytes) -> None:
        canonical.extend(len(value).to_bytes(8, "big"))
        canonical.extend(value)

    field(protocol.root_id.encode())
    for name in ROLE_NAMES:
        field(name.encode())
        field(protocol.role(name).encode())
    field(transaction.root_id.encode())
    for step in transaction.steps:
        field(step.root_id.encode())
        field(step.target_root.encode())
        field(rule_content_digest(
            snapshot, rule_protocol, step.rule_root, budget=budget
        ))
    for label, roots in (
        (b"evidence", transaction.evidence_roots),
        (b"outcome", transaction.outcome_roots),
    ):
        for root in sorted(roots):
            field(label)
            field(root.encode())
            field(graph_content_digest(snapshot, root, budget=budget))
    return hashlib.sha256(canonical).hexdigest().encode("ascii")


def prepare_transaction(
    store: CellStore,
    protocol: TransactionProtocol,
    rule_protocol: RuleProtocol,
    transaction_root: str,
    *,
    expected_revision: int | None = None,
    budget: int = 10_000,
) -> PreparedTransaction:
    """Materialize every declared rule against one revision without committing."""
    snapshot = store.snapshot()
    revision = snapshot.revision if expected_revision is None else expected_revision
    if snapshot.revision != revision:
        raise Conflict(
            "expected revision %s, current revision is %s"
            % (revision, snapshot.revision)
        )
    transaction = read_transaction(
        snapshot, protocol, transaction_root, budget=budget
    )
    if len(transaction.steps) > budget:
        raise InvalidCell("transaction rule-step count exceeds its budget")

    prepared: list[PreparedRewrite] = []
    created: dict[str, Cell] = {}
    replaced: dict[str, Cell] = {}
    for step in transaction.steps:
        rule = read_rule(snapshot, rule_protocol, step.rule_root, budget=budget)
        rewrite = store.prepare_rewrite(
            expected_revision=revision,
            pattern_root=rule.pattern_root,
            target_root=step.target_root,
            pattern_variables=rule.pattern_variables,
            replacement_root=rule.replacement_root,
            replacement_variables=rule.replacement_bindings,
            replacement_constants=rule.replacement_constants,
            budget=budget,
        )
        prepared.append(rewrite)
        for cell in rewrite.create:
            if cell.id in created or cell.id in replaced:
                raise InvalidCell("transaction materialized one identity twice")
            created[cell.id] = cell
        for cell in rewrite.replace:
            if cell.id in created or cell.id in replaced:
                raise InvalidCell("transaction changes one continuing root twice")
            replaced[cell.id] = cell

    return PreparedTransaction(
        transaction.root_id,
        revision,
        tuple(prepared),
        tuple(created.values()),
        tuple(replaced.values()),
        tuple(sorted((*created, *replaced))),
        transaction.evidence_roots,
        transaction.outcome_roots,
    )


def execute_transaction(
    store: CellStore,
    protocol: TransactionProtocol,
    rule_protocol: RuleProtocol,
    transaction_root: str,
    *,
    expected_revision: int | None = None,
    precommit_guard: Callable[[], None] | None = None,
    budget: int = 10_000,
) -> TransactionExecution:
    """Materialize every declared rule against one revision and commit once."""
    prepared = prepare_transaction(
        store,
        protocol,
        rule_protocol,
        transaction_root,
        expected_revision=expected_revision,
        budget=budget,
    )
    committed = store.commit(
        prepared.revision,
        create=prepared.create,
        replace=prepared.replace,
        precommit_guard=precommit_guard,
    )
    return TransactionExecution(
        prepared.root_id,
        committed,
        prepared.rewrites,
        prepared.touched_roots,
        prepared.evidence_roots,
        prepared.outcome_roots,
    )


__all__ = [
    "TransactionProtocol",
    "TransactionStep",
    "GraphTransaction",
    "TransactionBuild",
    "PreparedTransaction",
    "TransactionExecution",
    "bootstrap_transaction_protocol",
    "project_transaction_protocol",
    "build_transaction",
    "prepare_transaction",
    "read_transaction",
    "transaction_content_digest",
    "execute_transaction",
]
