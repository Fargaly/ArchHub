"""Append-only, graph-held compliance observations.

The protocol is domain-neutral.  A subject is evaluated against a policy and
the resulting evidence, outcome, freshness window, and predecessor are ordinary
Cell relations.  Evidence authority remains with the protocol that produced the
referenced evidence (for example a signed court attestation); this module only
binds that evidence to the exact subject and policy for later enforcement.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from types import MappingProxyType
from typing import Mapping

from .cell_protocols import (
    CellBatch,
    compose_relation_cells,
    prepare_append_relation_member,
    read_relation,
)
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


ROLE_NAMES = (
    "vocabulary-member",
    "observation-member",
    "observation-subject",
    "observation-policy",
    "observation-evidence",
    "observation-result",
    "observation-observed-at",
    "observation-expires-at",
    "observation-predecessor",
)
STATE_NAMES = ("satisfied", "unsatisfied")
_MAX_OBSERVATION_LIFETIME_SECONDS = 900.0


@dataclass(frozen=True, slots=True)
class ComplianceProtocol:
    root_id: str
    roles: Mapping[str, str]
    states: Mapping[str, str]
    registry_root: str

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown compliance role") from exc

    def state(self, name: str) -> str:
        try:
            return self.states[name]
        except KeyError as exc:
            raise InvalidCell("unknown compliance state") from exc


@dataclass(frozen=True, slots=True)
class ComplianceObservation:
    root_id: str
    subject_root: str
    policy_root: str
    evidence_root: str
    result_root: str
    observed_at: float
    expires_at: float
    predecessor_root: str | None


def _terminal(root_id: str, value: str) -> Cell:
    encoded = str(value).encode("utf-8")
    if not encoded:
        raise InvalidCell("compliance terminal cannot be empty")
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, encoded)


def _one(members, role_root: str, label: str) -> str:
    values = tuple(
        member.participant_id for member in members
        if member.role_id == role_root
    )
    if len(values) != 1:
        raise InvalidCell("compliance observation requires exactly one %s" % label)
    return values[0]


def _optional(members, role_root: str, label: str) -> str | None:
    values = tuple(
        member.participant_id for member in members
        if member.role_id == role_root
    )
    if len(values) > 1:
        raise InvalidCell("compliance observation has several %s values" % label)
    return values[0] if values else None


def _time(snapshot: Snapshot, root_id: str, label: str) -> float:
    try:
        value = float(snapshot.cells[root_id].atom.decode("ascii"))
    except (KeyError, UnicodeError, ValueError) as exc:
        raise InvalidCell("compliance %s is invalid" % label) from exc
    if not math.isfinite(value):
        raise InvalidCell("compliance %s is not finite" % label)
    return value


def _observation_root(evidence_root: str) -> str:
    return "compliance-observation:sha256:" + hashlib.sha256(
        evidence_root.encode("utf-8")
    ).hexdigest()


def bootstrap_compliance_protocol(
    store: CellStore,
    *,
    prefix: str = "compliance-protocol:v1",
) -> ComplianceProtocol:
    root_id = prefix + ":root"
    if root_id in store.snapshot().cells:
        return project_compliance_protocol(store.snapshot(), prefix=prefix)
    registry_root = prefix + ":registry"
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    states = {name: "%s:state:%s" % (prefix, name) for name in STATE_NAMES}
    batch = CellBatch(store)
    for name, root in (*roles.items(), *states.items()):
        batch.add(_terminal(root, name))
    vocabulary = (
        (roles["vocabulary-member"], root)
        for root in (*roles.values(), *states.values())
    )
    batch.relation(vocabulary, relation_id=root_id)
    batch.relation(
        (
            (roles["vocabulary-member"], root)
            for root in (*roles.values(), *states.values())
        ),
        relation_id=registry_root,
    )
    batch.commit()
    return ComplianceProtocol(
        root_id,
        MappingProxyType(roles),
        MappingProxyType(states),
        registry_root,
    )


def project_compliance_protocol(
    snapshot: Snapshot,
    *,
    prefix: str = "compliance-protocol:v1",
) -> ComplianceProtocol:
    root_id = prefix + ":root"
    registry_root = prefix + ":registry"
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    states = {name: "%s:state:%s" % (prefix, name) for name in STATE_NAMES}
    required = {root_id, registry_root, *roles.values(), *states.values()}
    if required - set(snapshot.cells):
        raise InvalidCell("compliance protocol is incomplete")
    expected_vocabulary = set((*roles.values(), *states.values()))
    for relation_root, registry in ((root_id, False), (registry_root, True)):
        members = read_relation(snapshot, relation_root, budget=100_000)
        allowed = {roles["vocabulary-member"]}
        if registry:
            allowed.add(roles["observation-member"])
        if any(member.role_id not in allowed for member in members):
            raise InvalidCell("compliance protocol has an undeclared member")
        vocabulary = {
            member.participant_id for member in members
            if member.role_id == roles["vocabulary-member"]
        }
        if vocabulary != expected_vocabulary:
            raise InvalidCell("compliance protocol vocabulary drifted")
    return ComplianceProtocol(
        root_id,
        MappingProxyType(roles),
        MappingProxyType(states),
        registry_root,
    )


def read_compliance_observation(
    snapshot: Snapshot,
    protocol: ComplianceProtocol,
    observation_root: str,
) -> ComplianceObservation:
    members = read_relation(snapshot, observation_root, budget=128)
    allowed = {
        protocol.role(name) for name in ROLE_NAMES
        if name not in {"vocabulary-member", "observation-member"}
    }
    if any(member.role_id not in allowed for member in members):
        raise InvalidCell("compliance observation contains an undeclared field")
    subject = _one(
        members, protocol.role("observation-subject"), "subject"
    )
    policy = _one(members, protocol.role("observation-policy"), "policy")
    evidence = _one(
        members, protocol.role("observation-evidence"), "evidence"
    )
    result = _one(members, protocol.role("observation-result"), "result")
    observed_root = _one(
        members, protocol.role("observation-observed-at"), "observed-at"
    )
    expires_root = _one(
        members, protocol.role("observation-expires-at"), "expires-at"
    )
    predecessor = _optional(
        members, protocol.role("observation-predecessor"), "predecessor"
    )
    if {subject, policy, evidence} - set(snapshot.cells):
        raise InvalidCell("compliance observation references a missing root")
    if result not in set(protocol.states.values()):
        raise InvalidCell("compliance result is outside the protocol")
    observed_at = _time(snapshot, observed_root, "observed-at")
    expires_at = _time(snapshot, expires_root, "expires-at")
    if (
        expires_at <= observed_at
        or expires_at - observed_at > _MAX_OBSERVATION_LIFETIME_SECONDS
    ):
        raise InvalidCell("compliance freshness window is outside policy")
    if predecessor is not None and predecessor not in snapshot.cells:
        raise InvalidCell("compliance predecessor is missing")
    return ComplianceObservation(
        observation_root,
        subject,
        policy,
        evidence,
        result,
        observed_at,
        expires_at,
        predecessor,
    )


def list_compliance_observations(
    snapshot: Snapshot,
    protocol: ComplianceProtocol,
) -> tuple[ComplianceObservation, ...]:
    roots = tuple(
        member.participant_id for member in read_relation(
            snapshot, protocol.registry_root, budget=100_000
        )
        if member.role_id == protocol.role("observation-member")
    )
    if len(roots) != len(set(roots)):
        raise InvalidCell("compliance registry contains a duplicate")
    observations = tuple(
        read_compliance_observation(snapshot, protocol, root) for root in roots
    )
    evidence_roots = tuple(item.evidence_root for item in observations)
    if len(evidence_roots) != len(set(evidence_roots)):
        raise InvalidCell("compliance evidence is bound more than once")
    return observations


def latest_compliance_observation(
    snapshot: Snapshot,
    protocol: ComplianceProtocol,
    *,
    subject_root: str,
    policy_root: str,
) -> ComplianceObservation | None:
    matches = tuple(
        item for item in list_compliance_observations(snapshot, protocol)
        if item.subject_root == subject_root and item.policy_root == policy_root
    )
    if not matches:
        return None
    latest_time = max(item.observed_at for item in matches)
    latest = tuple(item for item in matches if item.observed_at == latest_time)
    if len(latest) != 1:
        raise InvalidCell("compliance history has an ambiguous latest observation")
    return latest[0]


def record_compliance_observation(
    store: CellStore,
    protocol: ComplianceProtocol,
    *,
    subject_root: str,
    policy_root: str,
    evidence_root: str,
    satisfied: bool,
    observed_at: float,
    expires_at: float,
) -> tuple[ComplianceObservation, int]:
    if type(satisfied) is not bool:
        raise InvalidCell("compliance result must be a boolean")
    if type(observed_at) not in (int, float) or type(expires_at) not in (
        int, float
    ):
        raise InvalidCell("compliance timestamps must be numeric")
    observed_at = float(observed_at)
    expires_at = float(expires_at)
    if (
        not math.isfinite(observed_at)
        or not math.isfinite(expires_at)
        or expires_at <= observed_at
        or expires_at - observed_at > _MAX_OBSERVATION_LIFETIME_SECONDS
    ):
        raise InvalidCell("compliance freshness window is outside policy")
    snapshot = store.snapshot()
    if {subject_root, policy_root, evidence_root} - set(snapshot.cells):
        raise InvalidCell("compliance subject, policy, and evidence must exist")
    observations = list_compliance_observations(snapshot, protocol)
    if any(item.evidence_root == evidence_root for item in observations):
        raise InvalidCell("compliance evidence is already bound")
    predecessor = latest_compliance_observation(
        snapshot,
        protocol,
        subject_root=subject_root,
        policy_root=policy_root,
    )
    if predecessor is not None and observed_at <= predecessor.observed_at:
        raise InvalidCell("compliance observation time must advance")
    root_id = _observation_root(evidence_root)
    if root_id in snapshot.cells:
        raise InvalidCell("compliance observation identity already exists")
    observed_root = root_id + ":observed-at"
    expires_root = root_id + ":expires-at"
    members = [
        (protocol.role("observation-subject"), subject_root),
        (protocol.role("observation-policy"), policy_root),
        (protocol.role("observation-evidence"), evidence_root),
        (
            protocol.role("observation-result"),
            protocol.state("satisfied" if satisfied else "unsatisfied"),
        ),
        (protocol.role("observation-observed-at"), observed_root),
        (protocol.role("observation-expires-at"), expires_root),
    ]
    if predecessor is not None:
        members.append((
            protocol.role("observation-predecessor"), predecessor.root_id
        ))
    relation = compose_relation_cells(members, relation_id=root_id)
    registry_patch = prepare_append_relation_member(
        snapshot,
        protocol.registry_root,
        protocol.role("observation-member"),
        root_id,
        budget=100_000,
    )
    revision = store.commit(
        snapshot.revision,
        create=(
            _terminal(observed_root, "%.6f" % observed_at),
            _terminal(expires_root, "%.6f" % expires_at),
            *relation.cells,
            *registry_patch.create,
        ),
        replace=registry_patch.replace,
    )
    return read_compliance_observation(
        store.snapshot(), protocol, root_id
    ), revision


def require_current_compliance(
    snapshot: Snapshot,
    protocol: ComplianceProtocol,
    observation_root: str,
    *,
    expected_subject_root: str,
    expected_policy_root: str,
    now: float,
) -> ComplianceObservation:
    if type(now) not in (int, float) or not math.isfinite(float(now)):
        raise InvalidCell("compliance evaluation time is invalid")
    observation = read_compliance_observation(
        snapshot, protocol, observation_root
    )
    if observation.subject_root != expected_subject_root:
        raise PermissionError("compliance evidence belongs to another subject")
    if observation.policy_root != expected_policy_root:
        raise PermissionError("compliance evidence uses another policy")
    if observation.result_root != protocol.state("satisfied"):
        raise PermissionError("compliance policy is not satisfied")
    current = float(now)
    if current < observation.observed_at or current >= observation.expires_at:
        raise PermissionError("compliance evidence is not current")
    latest = latest_compliance_observation(
        snapshot,
        protocol,
        subject_root=expected_subject_root,
        policy_root=expected_policy_root,
    )
    if latest is None or latest.root_id != observation.root_id:
        raise PermissionError("compliance evidence is superseded")
    return observation


__all__ = [
    "ComplianceObservation",
    "ComplianceProtocol",
    "ROLE_NAMES",
    "STATE_NAMES",
    "bootstrap_compliance_protocol",
    "latest_compliance_observation",
    "list_compliance_observations",
    "project_compliance_protocol",
    "read_compliance_observation",
    "record_compliance_observation",
    "require_current_compliance",
]
