"""Cell-native default-deny exposure policy for relation flows.

The old typed runtime had a hidden ``classification-flow-v1`` parameter on
wires.  This module rebuilds that idea as a graph protocol: classifications,
rules, decisions, evidence, and decision receipts are ordinary Cells.  The
Python functions are projections over that graph, not a new persisted record
shape.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping

from .cell_protocols import compose_relation_cells, read_relation
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


ROLE_NAMES = (
    "vocabulary-member",
    "rule",
    "policy",
    "source-classification",
    "target-classification",
    "default-decision",
    "decision",
    "reason",
    "evidence",
    "relation",
    "actor",
)
CLASSIFICATION_NAMES = ("public", "internal", "confidential", "secret")
DECISION_NAMES = ("allow", "deny")


@dataclass(frozen=True, slots=True)
class RelationExposurePolicyProtocol:
    root_id: str
    roles: Mapping[str, str]
    classifications: Mapping[str, str]
    decisions: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown exposure-policy role") from exc

    def classification(self, name: str) -> str:
        try:
            return self.classifications[name]
        except KeyError as exc:
            raise InvalidCell("unknown exposure classification") from exc

    def decision(self, name: str) -> str:
        try:
            return self.decisions[name]
        except KeyError as exc:
            raise InvalidCell("unknown exposure decision") from exc


@dataclass(frozen=True, slots=True)
class RelationExposureRuleProjection:
    root_id: str
    source_classification_root: str
    target_classification_root: str
    decision_root: str


@dataclass(frozen=True, slots=True)
class RelationExposurePolicyProjection:
    root_id: str
    default_decision_root: str
    rule_roots: tuple[str, ...]
    rules: tuple[RelationExposureRuleProjection, ...]
    evidence_roots: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RelationExposureDecision:
    allowed: bool
    policy_root: str
    source_classification_root: str
    target_classification_root: str
    decision_root: str
    matched_rule_root: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class RelationExposureDecisionCells:
    root_id: str
    decision: RelationExposureDecision
    cells: tuple[Cell, ...]


def _terminal(root_id: str, value: object) -> Cell:
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, str(value).encode("utf-8"))


def _slug(value: str) -> str:
    return "".join(
        character if character.isalnum() else "-"
        for character in value.lower()
    ).strip("-")


def _text(snapshot: Snapshot, root_id: str, label: str) -> str:
    try:
        cell = snapshot.cells[root_id]
    except KeyError as exc:
        raise InvalidCell("%s Cell is missing" % label) from exc
    if cell.link0 != NULL_CELL_ID or cell.link1 != NULL_CELL_ID:
        raise InvalidCell("%s must be a terminal Cell" % label)
    try:
        return cell.atom.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidCell("%s Cell is not UTF-8 text" % label) from exc


def _role_map(prefix: str) -> Mapping[str, str]:
    return MappingProxyType({
        name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES
    })


def _classification_map(prefix: str) -> Mapping[str, str]:
    return MappingProxyType({
        name: "%s:classification:%s" % (prefix, name)
        for name in CLASSIFICATION_NAMES
    })


def _decision_map(prefix: str) -> Mapping[str, str]:
    return MappingProxyType({
        name: "%s:decision:%s" % (prefix, name) for name in DECISION_NAMES
    })


def bootstrap_relation_exposure_policy_protocol(
    store: CellStore,
    *,
    prefix: str = "relation-exposure-policy-protocol",
) -> RelationExposurePolicyProtocol:
    root_id = prefix + ":root"
    if root_id in store.snapshot().cells:
        return project_relation_exposure_policy_protocol(
            store.snapshot(), prefix=prefix
        )
    roles = _role_map(prefix)
    classifications = _classification_map(prefix)
    decisions = _decision_map(prefix)
    vocabulary_roots = (
        *roles.values(),
        *classifications.values(),
        *decisions.values(),
    )
    terminals = [
        *(_terminal(root, name) for name, root in roles.items()),
        *(_terminal(root, name) for name, root in classifications.items()),
        *(_terminal(root, name) for name, root in decisions.items()),
    ]
    protocol = compose_relation_cells(
        ((roles["vocabulary-member"], root) for root in vocabulary_roots),
        relation_id=root_id,
    )
    store.commit(store.revision, create=(*terminals, *protocol.cells))
    return RelationExposurePolicyProtocol(
        root_id, roles, classifications, decisions
    )


def project_relation_exposure_policy_protocol(
    snapshot: Snapshot,
    *,
    prefix: str = "relation-exposure-policy-protocol",
) -> RelationExposurePolicyProtocol:
    root_id = prefix + ":root"
    roles = _role_map(prefix)
    classifications = _classification_map(prefix)
    decisions = _decision_map(prefix)
    required = {
        root_id,
        *roles.values(),
        *classifications.values(),
        *decisions.values(),
    }
    if any(_root not in snapshot.cells for _root in required):
        raise InvalidCell("relation exposure policy protocol is incomplete")
    members = read_relation(snapshot, root_id, budget=100_000)
    if any(member.role_id != roles["vocabulary-member"] for member in members):
        raise InvalidCell("relation exposure policy protocol has unknown roles")
    vocabulary = {member.participant_id for member in members}
    if vocabulary != {
        *roles.values(),
        *classifications.values(),
        *decisions.values(),
    }:
        raise InvalidCell("relation exposure policy vocabulary drifted")
    for name, root in roles.items():
        if _text(snapshot, root, "exposure-policy role") != name:
            raise InvalidCell("relation exposure policy role label drifted")
    for name, root in classifications.items():
        if _text(snapshot, root, "exposure classification") != name:
            raise InvalidCell("relation exposure classification label drifted")
    for name, root in decisions.items():
        if _text(snapshot, root, "exposure decision") != name:
            raise InvalidCell("relation exposure decision label drifted")
    return RelationExposurePolicyProtocol(
        root_id, roles, classifications, decisions
    )


def build_relation_exposure_policy(
    store: CellStore,
    protocol: RelationExposurePolicyProtocol,
    *,
    policy_id: str = "relation-exposure-policy",
    allowed_flows: Iterable[tuple[str, str]] = (),
    evidence_roots: tuple[str, ...] = (),
) -> RelationExposurePolicyProjection:
    if policy_id in store.snapshot().cells:
        return project_relation_exposure_policy(
            store.snapshot(), protocol, policy_id
        )
    snapshot = store.snapshot()
    unknown_evidence = set(evidence_roots) - set(snapshot.cells)
    if unknown_evidence:
        raise InvalidCell("exposure-policy evidence root is missing")
    unknown = {
        value
        for flow in allowed_flows
        for value in flow
        if value not in protocol.classifications
    }
    if unknown:
        raise InvalidCell(
            "unknown exposure classification in flow: %s" % sorted(unknown)
        )
    rules: list[Cell] = []
    rule_roots: list[str] = []
    seen: set[tuple[str, str]] = set()
    for source, target in allowed_flows:
        pair = (source, target)
        if pair in seen:
            raise InvalidCell("duplicate exposure-policy flow")
        seen.add(pair)
        rule_root = "%s:rule:%s-to-%s" % (
            policy_id, _slug(source), _slug(target)
        )
        rule = compose_relation_cells((
            (
                protocol.role("source-classification"),
                protocol.classification(source),
            ),
            (
                protocol.role("target-classification"),
                protocol.classification(target),
            ),
            (protocol.role("decision"), protocol.decision("allow")),
        ), relation_id=rule_root)
        rules.extend(rule.cells)
        rule_roots.append(rule_root)
    policy = compose_relation_cells((
        *((protocol.role("rule"), root) for root in rule_roots),
        (
            protocol.role("default-decision"),
            protocol.decision("deny"),
        ),
        *((protocol.role("evidence"), root) for root in evidence_roots),
    ), relation_id=policy_id)
    store.commit(store.revision, create=(*rules, *policy.cells))
    return project_relation_exposure_policy(
        store.snapshot(), protocol, policy_id
    )


def _single(
    members: Iterable[tuple[str, str]],
    role_id: str,
    label: str,
) -> str:
    values = [participant for role, participant in members if role == role_id]
    if len(values) != 1:
        raise InvalidCell("%s must appear exactly once" % label)
    return values[0]


def _project_rule(
    snapshot: Snapshot,
    protocol: RelationExposurePolicyProtocol,
    rule_root: str,
) -> RelationExposureRuleProjection:
    allowed_roles = {
        protocol.role("source-classification"),
        protocol.role("target-classification"),
        protocol.role("decision"),
    }
    members = tuple(
        (member.role_id, member.participant_id)
        for member in read_relation(snapshot, rule_root, budget=100_000)
    )
    if any(role not in allowed_roles for role, _participant in members):
        raise InvalidCell("exposure-policy rule has an unknown role")
    source = _single(
        members, protocol.role("source-classification"),
        "source classification",
    )
    target = _single(
        members, protocol.role("target-classification"),
        "target classification",
    )
    decision = _single(members, protocol.role("decision"), "rule decision")
    if source not in protocol.classifications.values():
        raise InvalidCell("rule source classification is outside protocol")
    if target not in protocol.classifications.values():
        raise InvalidCell("rule target classification is outside protocol")
    if decision not in protocol.decisions.values():
        raise InvalidCell("rule decision is outside protocol")
    return RelationExposureRuleProjection(
        rule_root, source, target, decision
    )


def project_relation_exposure_policy(
    snapshot: Snapshot,
    protocol: RelationExposurePolicyProtocol,
    policy_root: str,
) -> RelationExposurePolicyProjection:
    members = tuple(
        (member.role_id, member.participant_id)
        for member in read_relation(snapshot, policy_root, budget=100_000)
    )
    allowed_roles = {
        protocol.role("rule"),
        protocol.role("default-decision"),
        protocol.role("evidence"),
    }
    if any(role not in allowed_roles for role, _participant in members):
        raise InvalidCell("exposure policy has an unknown role")
    default_decision = _single(
        members, protocol.role("default-decision"), "default decision"
    )
    if default_decision != protocol.decision("deny"):
        raise InvalidCell("exposure policy must default to deny")
    rule_roots = tuple(
        participant
        for role, participant in members
        if role == protocol.role("rule")
    )
    rules = tuple(
        _project_rule(snapshot, protocol, root) for root in rule_roots
    )
    pairs: set[tuple[str, str]] = set()
    for rule in rules:
        pair = (
            rule.source_classification_root,
            rule.target_classification_root,
        )
        if pair in pairs:
            raise InvalidCell("exposure policy has duplicate flow rules")
        pairs.add(pair)
    evidence = tuple(
        participant
        for role, participant in members
        if role == protocol.role("evidence")
    )
    return RelationExposurePolicyProjection(
        policy_root, default_decision, rule_roots, rules, evidence
    )


def authorize_relation_exposure(
    snapshot: Snapshot,
    protocol: RelationExposurePolicyProtocol,
    policy_root: str,
    *,
    source_classification_root: str,
    target_classification_root: str,
) -> RelationExposureDecision:
    policy = project_relation_exposure_policy(snapshot, protocol, policy_root)
    if (
        source_classification_root not in protocol.classifications.values()
        or target_classification_root not in protocol.classifications.values()
    ):
        return RelationExposureDecision(
            False,
            policy_root,
            source_classification_root,
            target_classification_root,
            protocol.decision("deny"),
            None,
            "classification outside released vocabulary",
        )
    for rule in policy.rules:
        if (
            rule.source_classification_root == source_classification_root
            and rule.target_classification_root == target_classification_root
        ):
            allowed = rule.decision_root == protocol.decision("allow")
            return RelationExposureDecision(
                allowed,
                policy_root,
                source_classification_root,
                target_classification_root,
                rule.decision_root,
                rule.root_id,
                "matched released exposure rule",
            )
    return RelationExposureDecision(
        False,
        policy_root,
        source_classification_root,
        target_classification_root,
        policy.default_decision_root,
        None,
        "no released exposure rule matched",
    )


def compose_relation_exposure_decision_cells(
    snapshot: Snapshot,
    protocol: RelationExposurePolicyProtocol,
    policy_root: str,
    *,
    source_classification_root: str,
    target_classification_root: str,
    decision_id: str,
    relation_root: str | None = None,
    actor_root: str | None = None,
) -> RelationExposureDecisionCells:
    decision = authorize_relation_exposure(
        snapshot,
        protocol,
        policy_root,
        source_classification_root=source_classification_root,
        target_classification_root=target_classification_root,
    )
    reason_root = decision_id + ":reason"
    members = [
        (protocol.role("policy"), policy_root),
        (protocol.role("source-classification"), source_classification_root),
        (protocol.role("target-classification"), target_classification_root),
        (protocol.role("decision"), decision.decision_root),
        (protocol.role("reason"), reason_root),
    ]
    if relation_root is not None:
        if relation_root not in snapshot.cells:
            raise InvalidCell("relation decision target is missing")
        members.append((protocol.role("relation"), relation_root))
    if actor_root is not None:
        if actor_root not in snapshot.cells:
            raise InvalidCell("relation decision actor is missing")
        members.append((protocol.role("actor"), actor_root))
    relation = compose_relation_cells(members, relation_id=decision_id)
    return RelationExposureDecisionCells(
        decision_id,
        decision,
        (_terminal(reason_root, decision.reason), *relation.cells),
    )


__all__ = [
    "CLASSIFICATION_NAMES",
    "DECISION_NAMES",
    "ROLE_NAMES",
    "RelationExposureDecision",
    "RelationExposureDecisionCells",
    "RelationExposurePolicyProjection",
    "RelationExposurePolicyProtocol",
    "RelationExposureRuleProjection",
    "authorize_relation_exposure",
    "bootstrap_relation_exposure_policy_protocol",
    "build_relation_exposure_policy",
    "compose_relation_exposure_decision_cells",
    "project_relation_exposure_policy",
    "project_relation_exposure_policy_protocol",
]
