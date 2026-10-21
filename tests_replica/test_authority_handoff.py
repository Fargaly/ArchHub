"""Courts for the read-only canonical authority-handoff preflight."""
from __future__ import annotations

import pytest

from nodelang.authority_handoff import (
    AuthorityHandoffEvidence,
    evaluate_universal_authority_handoff,
)


def _evidence(**overrides):
    values = {
        "graph_available": False,
        "descriptor_verified": True,
        "descriptor_active": False,
        "descriptor_owner_alive": False,
        "visible_endpoint_occupied": False,
        "active_task_count": 0,
        "active_host_count": 0,
        "activity_revision": None,
    }
    values.update(overrides)
    return AuthorityHandoffEvidence(**values)


def test_local_zero_counts_never_certify_a_clear_handoff_window():
    result = evaluate_universal_authority_handoff(_evidence())

    assert result["execution_performed"] is False
    assert result["handoff_required"] is True
    assert result["eligible_for_founder_approval"] is False
    assert result["activity"]["proven"] is False
    assert any("automatic handoff is forbidden" in item for item in result["blockers"])


def test_unproven_activity_is_labelled_as_observed_not_graph_held():
    result = evaluate_universal_authority_handoff(_evidence(
        active_task_count=2,
        active_host_count=5,
    ))

    assert "2 observed active Work item(s)" in result["blockers"]
    assert "5 observed live host session(s)" in result["blockers"]
    assert "2 active governed Work item(s)" not in result["blockers"]
    assert "5 live graph host session(s)" not in result["blockers"]


def test_revision_bound_zero_activity_can_be_presented_for_founder_approval():
    result = evaluate_universal_authority_handoff(
        _evidence(activity_revision=91)
    )

    assert result["handoff_required"] is True
    assert result["eligible_for_founder_approval"] is True
    assert result["blockers"] == []
    assert result["activity"] == {
        "revision": 91,
        "proven": True,
        "active_tasks": 0,
        "active_hosts": 0,
    }


def test_durable_revision_observation_never_certifies_graph_activity():
    result = evaluate_universal_authority_handoff(_evidence(
        durable_journal_revision=91,
    ))

    assert result["durable_journal"] == {
        "available": True,
        "revision": 91,
        "authorizes_handoff": False,
    }
    assert result["activity"]["proven"] is False
    assert result["eligible_for_founder_approval"] is False


def test_live_signed_owner_blocks_a_handoff_despite_a_clear_activity_snapshot():
    result = evaluate_universal_authority_handoff(_evidence(
        descriptor_active=True,
        descriptor_owner_alive=True,
        activity_revision=91,
    ))

    assert result["eligible_for_founder_approval"] is False
    assert result["owner"]["state"] == "active-owner-unreachable"
    assert "the signed Universal owner is still alive" in result["blockers"]


def test_unverified_descriptor_cannot_claim_an_owner_state():
    with pytest.raises(ValueError, match="unverified"):
        evaluate_universal_authority_handoff(_evidence(
            descriptor_verified=False,
            descriptor_active=False,
            descriptor_owner_alive=False,
        ))
