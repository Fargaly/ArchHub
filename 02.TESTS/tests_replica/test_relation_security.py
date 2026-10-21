"""Cell-native relation exposure policy courts.

These courts supersede the old typed-runtime ``classification-flow-v1`` tests.
The release rule is stricter here: classifications, allow rules, deny decisions,
reasons, and receipts are graph Cells, not hidden wire parameters.
"""
from __future__ import annotations

import pytest

from nodelang.cell_protocols import build_relation, read_relation
from nodelang.cell_relation_exposure_policy import (
    bootstrap_relation_exposure_policy_protocol,
    build_relation_exposure_policy,
    authorize_relation_exposure,
    compose_relation_exposure_decision_cells,
    project_relation_exposure_policy,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


def _terminal(root_id: str, value: str) -> Cell:
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8"))


def _world():
    store = CellStore()
    protocol = bootstrap_relation_exposure_policy_protocol(store)
    store.commit(store.revision, create=(
        _terminal("evidence:nist-sp-800-162", "ABAC subject action object environment policy"),
        _terminal("evidence:nist-sp-800-207", "Zero Trust resource-scoped decisions"),
        _terminal("evidence:owasp-authorization", "deny by default every request"),
        _terminal("actor:founder", "Founder"),
        _terminal("node:public-route", "Public route"),
        _terminal("node:internal-cloud", "Internal cloud"),
    ))
    flow = build_relation(
        store,
        (
            (protocol.role("source-classification"), protocol.classification("public")),
            (protocol.role("target-classification"), protocol.classification("internal")),
        ),
        relation_id="relation:public-to-internal",
    )
    policy = build_relation_exposure_policy(
        store,
        protocol,
        policy_id="policy:relation-exposure",
        allowed_flows=(("public", "internal"),),
        evidence_roots=(
            "evidence:nist-sp-800-162",
            "evidence:nist-sp-800-207",
            "evidence:owasp-authorization",
        ),
    )
    return store, protocol, policy, flow.root_id


def test_exposure_policy_is_a_cell_graph_not_a_wire_parameter():
    store, protocol, policy, _flow = _world()
    snapshot = store.snapshot()

    assert set(Cell.__dataclass_fields__) == {"id", "link0", "link1", "atom"}
    assert policy.root_id == "policy:relation-exposure"
    assert policy.default_decision_root == protocol.decision("deny")
    assert policy.evidence_roots == (
        "evidence:nist-sp-800-162",
        "evidence:nist-sp-800-207",
        "evidence:owasp-authorization",
    )
    assert len(policy.rules) == 1
    assert policy.rules[0].source_classification_root == (
        protocol.classification("public")
    )
    assert policy.rules[0].target_classification_root == (
        protocol.classification("internal")
    )
    assert all(type(cell) is Cell for cell in snapshot.cells.values())
    assert all(
        member.role_id in {
            protocol.role("rule"),
            protocol.role("default-decision"),
            protocol.role("evidence"),
        }
        for member in read_relation(snapshot, policy.root_id)
    )


def test_released_rule_allows_only_the_declared_flow_and_denies_reverse_flow():
    store, protocol, policy, _flow = _world()
    snapshot = store.snapshot()

    allowed = authorize_relation_exposure(
        snapshot,
        protocol,
        policy.root_id,
        source_classification_root=protocol.classification("public"),
        target_classification_root=protocol.classification("internal"),
    )
    denied = authorize_relation_exposure(
        snapshot,
        protocol,
        policy.root_id,
        source_classification_root=protocol.classification("internal"),
        target_classification_root=protocol.classification("public"),
    )

    assert allowed.allowed is True
    assert allowed.matched_rule_root == policy.rules[0].root_id
    assert denied.allowed is False
    assert denied.decision_root == protocol.decision("deny")
    assert denied.matched_rule_root is None
    assert denied.reason == "no released exposure rule matched"


def test_unknown_classification_fails_closed_without_mutating_the_graph():
    store, protocol, policy, _flow = _world()
    before = store.snapshot()
    store.commit(store.revision, create=(
        _terminal("classification:unreviewed", "unreviewed"),
    ))
    after_unknown_cell = store.snapshot()

    decision = authorize_relation_exposure(
        after_unknown_cell,
        protocol,
        policy.root_id,
        source_classification_root="classification:unreviewed",
        target_classification_root=protocol.classification("internal"),
    )

    assert decision.allowed is False
    assert decision.decision_root == protocol.decision("deny")
    assert decision.reason == "classification outside released vocabulary"
    assert set(after_unknown_cell.cells) == set(before.cells) | {
        "classification:unreviewed"
    }


def test_decision_receipt_is_commit_ready_graph_evidence():
    store, protocol, policy, flow_root = _world()
    decision_cells = compose_relation_exposure_decision_cells(
        store.snapshot(),
        protocol,
        policy.root_id,
        source_classification_root=protocol.classification("public"),
        target_classification_root=protocol.classification("internal"),
        decision_id="decision:relation-exposure:1",
        relation_root=flow_root,
        actor_root="actor:founder",
    )

    assert decision_cells.decision.allowed is True
    store.commit(store.revision, create=decision_cells.cells)
    members = read_relation(store.snapshot(), decision_cells.root_id)
    by_role = {member.role_id: member.participant_id for member in members}

    assert by_role[protocol.role("policy")] == policy.root_id
    assert by_role[protocol.role("decision")] == protocol.decision("allow")
    assert by_role[protocol.role("relation")] == flow_root
    assert by_role[protocol.role("actor")] == "actor:founder"
    reason_root = by_role[protocol.role("reason")]
    assert store.read(reason_root).atom == b"matched released exposure rule"


def test_policy_tampering_fails_closed_before_authorization():
    store, protocol, policy, _flow = _world()
    default_member = next(
        member for member in read_relation(store.snapshot(), policy.root_id)
        if member.role_id == protocol.role("default-decision")
    )
    tampered = store.read(default_member.incidence_id)
    store.commit(store.revision, replace=(
        Cell(
            tampered.id,
            tampered.link0,
            protocol.decision("allow"),
            tampered.atom,
        ),
    ))

    with pytest.raises(InvalidCell, match="default to deny"):
        project_relation_exposure_policy(
            store.snapshot(), protocol, policy.root_id
        )
    with pytest.raises(InvalidCell, match="default to deny"):
        authorize_relation_exposure(
            store.snapshot(),
            protocol,
            policy.root_id,
            source_classification_root=protocol.classification("secret"),
            target_classification_root=protocol.classification("public"),
        )
