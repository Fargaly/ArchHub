from __future__ import annotations

import time

import pytest

from nodelang.cell_compliance import (
    bootstrap_compliance_protocol,
    latest_compliance_observation,
    project_compliance_protocol,
    read_compliance_observation,
    record_compliance_observation,
    require_current_compliance,
)
from nodelang.cell_protocols import CellBatch
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


def _fixture():
    store = CellStore()
    batch = CellBatch(store)
    for root, value in (
        ("subject:agent-session", "session"),
        ("policy:runtime-write", "policy"),
        ("evidence:green", "green-evidence"),
        ("evidence:red", "red-evidence"),
        ("subject:other-session", "other-session"),
    ):
        batch.add(Cell(root, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8")))
    batch.commit()
    protocol = bootstrap_compliance_protocol(
        store, prefix="court:compliance-protocol"
    )
    return store, protocol


def test_compliance_observation_is_relation_cells_not_an_opaque_document():
    store, protocol = _fixture()
    observation, revision = record_compliance_observation(
        store,
        protocol,
        subject_root="subject:agent-session",
        policy_root="policy:runtime-write",
        evidence_root="evidence:green",
        satisfied=True,
        observed_at=100.0,
        expires_at=160.0,
    )

    assert revision == store.revision
    projected = read_compliance_observation(
        store.snapshot(), protocol, observation.root_id
    )
    assert projected.subject_root == "subject:agent-session"
    assert projected.policy_root == "policy:runtime-write"
    assert projected.evidence_root == "evidence:green"
    assert projected.result_root == protocol.state("satisfied")
    assert projected.predecessor_root is None

    cells = [
        cell for cell in store.snapshot().cells.values()
        if cell.id.startswith(observation.root_id)
    ]
    assert cells
    assert all(b"{" not in cell.atom and b"[" not in cell.atom for cell in cells)
    assert project_compliance_protocol(
        store.snapshot(), prefix="court:compliance-protocol"
    ) == protocol


def test_latest_observation_is_exactly_scoped_and_forms_an_append_only_chain():
    store, protocol = _fixture()
    first, _ = record_compliance_observation(
        store,
        protocol,
        subject_root="subject:agent-session",
        policy_root="policy:runtime-write",
        evidence_root="evidence:red",
        satisfied=False,
        observed_at=100.0,
        expires_at=140.0,
    )
    second, _ = record_compliance_observation(
        store,
        protocol,
        subject_root="subject:agent-session",
        policy_root="policy:runtime-write",
        evidence_root="evidence:green",
        satisfied=True,
        observed_at=110.0,
        expires_at=170.0,
    )

    assert second.predecessor_root == first.root_id
    assert latest_compliance_observation(
        store.snapshot(),
        protocol,
        subject_root="subject:agent-session",
        policy_root="policy:runtime-write",
    ) == second
    assert latest_compliance_observation(
        store.snapshot(),
        protocol,
        subject_root="subject:other-session",
        policy_root="policy:runtime-write",
    ) is None


@pytest.mark.parametrize("now", [99.0, 160.0, 180.0])
def test_current_compliance_fails_closed_for_future_or_expired_evidence(now):
    store, protocol = _fixture()
    observation, _ = record_compliance_observation(
        store,
        protocol,
        subject_root="subject:agent-session",
        policy_root="policy:runtime-write",
        evidence_root="evidence:green",
        satisfied=True,
        observed_at=100.0,
        expires_at=160.0,
    )

    with pytest.raises(PermissionError):
        require_current_compliance(
            store.snapshot(),
            protocol,
            observation.root_id,
            expected_subject_root="subject:agent-session",
            expected_policy_root="policy:runtime-write",
            now=now,
        )


def test_current_compliance_rejects_red_and_other_session_without_mutation():
    store, protocol = _fixture()
    red, _ = record_compliance_observation(
        store,
        protocol,
        subject_root="subject:agent-session",
        policy_root="policy:runtime-write",
        evidence_root="evidence:red",
        satisfied=False,
        observed_at=100.0,
        expires_at=160.0,
    )
    before = store.revision

    with pytest.raises(PermissionError, match="not satisfied"):
        require_current_compliance(
            store.snapshot(),
            protocol,
            red.root_id,
            expected_subject_root="subject:agent-session",
            expected_policy_root="policy:runtime-write",
            now=120.0,
        )
    with pytest.raises(PermissionError, match="subject"):
        require_current_compliance(
            store.snapshot(),
            protocol,
            red.root_id,
            expected_subject_root="subject:other-session",
            expected_policy_root="policy:runtime-write",
            now=120.0,
        )
    assert store.revision == before


def test_duplicate_evidence_cannot_be_rebound_or_recorded_twice():
    store, protocol = _fixture()
    record_compliance_observation(
        store,
        protocol,
        subject_root="subject:agent-session",
        policy_root="policy:runtime-write",
        evidence_root="evidence:green",
        satisfied=True,
        observed_at=time.time(),
        expires_at=time.time() + 60.0,
    )

    with pytest.raises(InvalidCell, match="evidence"):
        record_compliance_observation(
            store,
            protocol,
            subject_root="subject:other-session",
            policy_root="policy:runtime-write",
            evidence_root="evidence:green",
            satisfied=True,
            observed_at=time.time(),
            expires_at=time.time() + 60.0,
        )
