"""Forcing courts for persistent, governed graph attention and focus."""
from __future__ import annotations

import pickle

import pytest

from nodelang.cell_attention import (
    AttentionPolicyReleaseBroker,
    FocusConsentBroker,
    accept_focus,
    active_focus,
    bootstrap_attention_protocol,
    build_attention_policy,
    open_attention_protocol,
    ordered_attentions,
    prepare_accepted_focus_transition,
    prepare_obligation,
    propose_focus,
    read_attention,
    read_decision,
    read_focus,
    read_obligation,
    read_outcome,
    read_signal,
    record_attention,
    record_decision,
    record_eligibility_decision,
    record_obligation,
    record_outcome,
    record_signal,
    release_attention_policy,
    resolve_obligation,
    verify_attention_policy,
)
from nodelang.cell_authorization import AuthorizationDecision
from nodelang.cell_protocols import read_relation, reorder_relation_members
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


BASE_ROOTS = (
    "reviewer",
    "release-evidence",
    "observer",
    "other-observer",
    "scope",
    "other-scope",
    "candidate-a",
    "candidate-b",
    "candidate-c",
    "candidate-hidden",
    "action-inspect",
    "authorization-policy",
    "authorization-rule",
    "reason-a",
    "reason-b",
    "reason-c",
    "reason-hidden",
    "source",
    "provenance",
    "trust-strong",
    "trust-weak",
    "affected",
    "sensitivity-internal",
    "audience-firm",
    "lifecycle-wip",
    "subject",
    "owner",
    "court",
    "required-evidence",
    "resolution-evidence",
    "actor",
    "other-actor",
    "session",
    "selected-a",
    "selected-b",
    "focus-authority",
    "focus-consent-a",
    "focus-consent-b",
    "decision-subject",
    "decision-action",
    "decision-authority",
    "decision-evidence",
    "provider",
    "receipt",
    "reconciliation",
    "failure-reason",
)


def _base_store(database=None):
    store = CellStore(database)
    protocol = bootstrap_attention_protocol(store)
    store.commit(
        store.revision,
        create=tuple(
            Cell(root, NULL_CELL_ID, NULL_CELL_ID, root.encode("utf-8"))
            for root in BASE_ROOTS
        ),
    )
    return store, protocol


def _released_policy(store, protocol, *, policy_id="attention-policy"):
    policy = build_attention_policy(
        store,
        protocol,
        policy_id=policy_id,
        ordered_classes=(("priority-critical", "Critical"), ("priority-normal", "Normal")),
    )
    broker = AttentionPolicyReleaseBroker()
    handle = broker.issue(
        policy_root=policy_id,
        reviewer_root="reviewer",
        evidence_root="release-evidence",
        expires_at=100.0,
        now=10.0,
    )
    release_attention_policy(
        store,
        protocol,
        broker,
        handle,
        policy_root=policy_id,
        reviewer_root="reviewer",
        evidence_root="release-evidence",
        now=11.0,
    )
    return verify_attention_policy(store.snapshot(), protocol, policy_id)


def _decision(*, candidate, allowed=True, observer="observer"):
    return AuthorizationDecision(
        allowed=allowed,
        policy_root="authorization-policy",
        subject_root=observer,
        action_root="action-inspect",
        object_root=candidate,
        determining_rule_roots=("authorization-rule",),
        reason="permit" if allowed else "default-deny",
    )


def _eligibility(store, protocol, *, root, candidate, revision, allowed=True, observer="observer", scope="scope"):
    return record_eligibility_decision(
        store,
        protocol,
        _decision(candidate=candidate, allowed=allowed, observer=observer),
        eligibility_id=root,
        scope_root=scope,
        source_snapshot_revision=revision,
        audience_root="audience-firm",
    )


def _replace_atom(store, root, atom):
    cell = store.read(root)
    store.commit(
        store.revision,
        replace=(Cell(cell.id, cell.link0, cell.link1, atom),),
    )


def test_policy_must_be_explicitly_released_and_drift_fails_closed():
    store, protocol = _base_store()
    policy = build_attention_policy(
        store,
        protocol,
        policy_id="attention-policy",
        ordered_classes=(("priority-critical", "Critical"), ("priority-normal", "Normal")),
    )
    with pytest.raises(InvalidCell, match="not released"):
        verify_attention_policy(store.snapshot(), protocol, policy.root_id)
    with pytest.raises(InvalidCell, match="not released"):
        ordered_attentions(
            store.snapshot(),
            protocol,
            observer_root="observer",
            scope_root="scope",
            policy_root=policy.root_id,
        )

    broker = AttentionPolicyReleaseBroker()
    handle = broker.issue(
        policy_root=policy.root_id,
        reviewer_root="reviewer",
        evidence_root="release-evidence",
        expires_at=100.0,
        now=10.0,
    )
    with pytest.raises(TypeError, match="not serializable"):
        pickle.dumps(handle)
    release_attention_policy(
        store,
        protocol,
        broker,
        handle,
        policy_root=policy.root_id,
        reviewer_root="reviewer",
        evidence_root="release-evidence",
        now=11.0,
    )
    with pytest.raises(InvalidCell, match="only a WIP"):
        release_attention_policy(
            store,
            protocol,
            broker,
            handle,
            policy_root=policy.root_id,
            reviewer_root="reviewer",
            evidence_root="release-evidence",
            now=12.0,
        )
    with pytest.raises(PermissionError, match="consumed"):
        broker.consume(
            handle,
            policy_root=policy.root_id,
            reviewer_root="reviewer",
            evidence_root="release-evidence",
            now=12.0,
        )
    assert verify_attention_policy(store.snapshot(), protocol, policy.root_id).class_roots == (
        "priority-critical",
        "priority-normal",
    )

    _replace_atom(store, "release-evidence", b"silently changed")
    with pytest.raises(InvalidCell, match="drifted"):
        verify_attention_policy(store.snapshot(), protocol, policy.root_id)
    assert all(type(cell) is Cell for cell in store.snapshot().cells.values())


def test_signal_idempotency_covers_the_complete_signal_not_a_subset():
    store, protocol = _base_store()
    arguments = dict(
        source_root="source",
        source_revision=7,
        observer_root="observer",
        provenance_root="provenance",
        trust_root="trust-strong",
        affected_roots=("affected",),
        observed_at="2026-07-16T12:00:00Z",
        sensitivity_root="sensitivity-internal",
        audience_root="audience-firm",
        idempotency_key="source/7/observer",
        lifecycle_root="lifecycle-wip",
    )
    assert record_signal(store, protocol, signal_id="signal-a", **arguments) == "signal-a"
    revision = store.revision
    assert record_signal(store, protocol, signal_id="signal-retry", **arguments) == "signal-a"
    assert store.revision == revision
    projection = read_signal(store.snapshot(), protocol, "signal-a")
    assert projection.trust_root == "trust-strong"
    assert projection.observed_at == "2026-07-16T12:00:00Z"

    changed = dict(arguments, trust_root="trust-weak")
    with pytest.raises(InvalidCell, match="reused for other content"):
        record_signal(store, protocol, signal_id="signal-conflict", **changed)


def test_attention_is_authorized_then_ordered_by_visible_policy_and_stable_sequence():
    store, protocol = _base_store()
    policy = _released_policy(store, protocol)
    revision = store.revision

    for suffix, candidate in (("a", "candidate-a"), ("b", "candidate-b"), ("c", "candidate-c")):
        _eligibility(
            store,
            protocol,
            root="eligibility-" + suffix,
            candidate=candidate,
            revision=revision,
        )
    record_attention(
        store,
        protocol,
        attention_id="attention-a",
        observer_root="observer",
        candidate_root="candidate-a",
        scope_root="scope",
        source_snapshot_revision=revision,
        reason_roots=("reason-a",),
        policy_root=policy.root_id,
        priority_root="priority-normal",
        eligibility_root="eligibility-a",
    )
    record_attention(
        store,
        protocol,
        attention_id="attention-b",
        observer_root="observer",
        candidate_root="candidate-b",
        scope_root="scope",
        source_snapshot_revision=revision,
        reason_roots=("reason-b",),
        policy_root=policy.root_id,
        priority_root="priority-critical",
        eligibility_root="eligibility-b",
    )
    record_attention(
        store,
        protocol,
        attention_id="attention-c",
        observer_root="observer",
        candidate_root="candidate-c",
        scope_root="scope",
        source_snapshot_revision=revision,
        reason_roots=("reason-c",),
        policy_root=policy.root_id,
        priority_root="priority-normal",
        eligibility_root="eligibility-c",
    )
    assert [item.candidate_root for item in ordered_attentions(
        store.snapshot(),
        protocol,
        observer_root="observer",
        scope_root="scope",
        policy_root=policy.root_id,
    )] == ["candidate-b", "candidate-a", "candidate-c"]

    members = read_relation(store.snapshot(), policy.class_order_root)
    assert [member.participant_id for member in members] == [
        "priority-critical",
        "priority-normal",
    ]
    reorder_relation_members(
        store,
        policy.class_order_root,
        tuple(reversed([member.incidence_id for member in members])),
    )
    with pytest.raises(InvalidCell, match="drifted"):
        ordered_attentions(
            store.snapshot(),
            protocol,
            observer_root="observer",
            scope_root="scope",
            policy_root=policy.root_id,
        )


def test_denied_or_mismatched_candidates_cannot_influence_attention():
    store, protocol = _base_store()
    policy = _released_policy(store, protocol)
    revision = store.revision
    _eligibility(
        store,
        protocol,
        root="eligibility-hidden",
        candidate="candidate-hidden",
        revision=revision,
        allowed=False,
    )
    with pytest.raises(PermissionError, match="denied candidates"):
        record_attention(
            store,
            protocol,
            attention_id="attention-hidden",
            observer_root="observer",
            candidate_root="candidate-hidden",
            scope_root="scope",
            source_snapshot_revision=revision,
            reason_roots=("reason-hidden",),
            policy_root=policy.root_id,
            priority_root="priority-critical",
            eligibility_root="eligibility-hidden",
        )

    _eligibility(
        store,
        protocol,
        root="eligibility-a",
        candidate="candidate-a",
        revision=revision,
    )
    with pytest.raises(PermissionError, match="does not match"):
        record_attention(
            store,
            protocol,
            attention_id="attention-mismatch",
            observer_root="observer",
            candidate_root="candidate-b",
            scope_root="scope",
            source_snapshot_revision=revision,
            reason_roots=("reason-b",),
            policy_root=policy.root_id,
            priority_root="priority-normal",
            eligibility_root="eligibility-a",
        )
    assert ordered_attentions(
        store.snapshot(),
        protocol,
        observer_root="observer",
        scope_root="scope",
        policy_root=policy.root_id,
    ) == ()


def test_obligation_resolution_and_focus_replacement_preserve_history():
    store, protocol = _base_store()
    policy = _released_policy(store, protocol)
    record_obligation(
        store,
        protocol,
        obligation_id="obligation-a",
        subject_root="subject",
        owner_root="owner",
        reviewer_root="reviewer",
        policy_root=policy.root_id,
        priority_root="priority-critical",
        court_roots=("court",),
        required_evidence_roots=("required-evidence",),
        created_at="2026-07-16T12:00:00Z",
    )
    before_resolution = store.snapshot()
    resolve_obligation(
        store,
        protocol,
        "obligation-a",
        evidence_root="resolution-evidence",
    )
    assert read_obligation(before_resolution, protocol, "obligation-a").state_root == protocol.state("open")
    assert read_obligation(store.snapshot(), protocol, "obligation-a").state_root == protocol.state("resolved")
    assert "resolution-evidence" in {
        member.participant_id
        for member in read_relation(store.snapshot(), "obligation-a")
    }

    propose_focus(
        store,
        protocol,
        focus_id="focus-a",
        actor_root="actor",
        session_root="session",
        scope_root="scope",
        selected_roots=("selected-a",),
        primary_root="selected-a",
        origin="model",
        reason_roots=("reason-a",),
        attention_roots=(),
        authority_root="focus-authority",
        created_at="2026-07-16T12:01:00Z",
    )
    assert active_focus(store.snapshot(), protocol, session_root="session") is None
    broker = FocusConsentBroker()
    handle = broker.issue(
        focus_root="focus-a",
        actor_root="actor",
        session_root="session",
        evidence_root="focus-consent-a",
        expires_at=100.0,
        now=10.0,
    )
    with pytest.raises(PermissionError, match="actor or session mismatch"):
        accept_focus(
            store,
            protocol,
            broker,
            handle,
            focus_root="focus-a",
            actor_root="other-actor",
            session_root="session",
            evidence_root="focus-consent-a",
            now=11.0,
        )
    accept_focus(
        store,
        protocol,
        broker,
        handle,
        focus_root="focus-a",
        actor_root="actor",
        session_root="session",
        evidence_root="focus-consent-a",
        now=11.0,
    )
    assert active_focus(store.snapshot(), protocol, session_root="session").root_id == "focus-a"

    propose_focus(
        store,
        protocol,
        focus_id="focus-b",
        actor_root="actor",
        session_root="session",
        scope_root="scope",
        selected_roots=("selected-a", "selected-b"),
        primary_root="selected-b",
        origin="user",
        reason_roots=("reason-b",),
        attention_roots=(),
        authority_root="focus-authority",
        created_at="2026-07-16T12:02:00Z",
    )
    assert read_focus(store.snapshot(), protocol, "focus-b").previous_root == "focus-a"
    before_replacement = store.snapshot()
    second_handle = broker.issue(
        focus_root="focus-b",
        actor_root="actor",
        session_root="session",
        evidence_root="focus-consent-b",
        expires_at=100.0,
        now=12.0,
    )
    accept_focus(
        store,
        protocol,
        broker,
        second_handle,
        focus_root="focus-b",
        actor_root="actor",
        session_root="session",
        evidence_root="focus-consent-b",
        now=13.0,
    )
    assert read_focus(before_replacement, protocol, "focus-a").state_root == protocol.state("active")
    assert read_focus(store.snapshot(), protocol, "focus-a").state_root == protocol.state("resolved")
    assert active_focus(store.snapshot(), protocol, session_root="session").root_id == "focus-b"


def test_prepared_obligation_joins_its_referencing_work_in_one_commit():
    store, protocol = _base_store()
    policy = _released_policy(store, protocol)
    before = store.snapshot()
    prepared = prepare_obligation(
        before,
        protocol,
        obligation_id="obligation-prepared",
        subject_root="subject",
        owner_root="owner",
        reviewer_root="reviewer",
        policy_root=policy.root_id,
        priority_root="priority-critical",
        court_roots=("court",),
        required_evidence_roots=("required-evidence",),
        created_at="2026-07-22T00:00:00Z",
    )

    assert prepared.root_id not in before.cells
    revision = store.commit(
        before.revision,
        create=(*prepared.create, Cell(
            "work:prepared-obligation", NULL_CELL_ID, NULL_CELL_ID, b""
        )),
        replace=prepared.replace,
    )

    assert revision == before.revision + 1
    assert "work:prepared-obligation" in store.snapshot().cells
    assert read_obligation(
        store.snapshot(), protocol, prepared.root_id
    ).state_root == protocol.state("open")


def test_authorised_direct_focus_is_one_atomic_graph_transition():
    store, protocol = _base_store()
    before = store.snapshot()
    first = prepare_accepted_focus_transition(
        before,
        protocol,
        focus_id="focus-direct-a",
        actor_root="actor",
        session_root="session",
        scope_root="scope",
        selected_roots=("selected-a", "selected-b"),
        primary_root="selected-b",
        origin="user",
        reason_roots=("reason-a",),
        attention_roots=(),
        authority_root="focus-authority",
        consent_evidence_root="focus-consent-a",
        created_at="2026-07-16T10:00:00Z",
    )
    assert store.revision == before.revision
    assert first.root_id not in store.snapshot().cells
    store.commit(before.revision, create=first.create, replace=first.replace)
    active = active_focus(store.snapshot(), protocol, session_root="session")
    assert active is not None
    assert active.root_id == "focus-direct-a"
    assert active.selected_roots == ("selected-a", "selected-b")
    assert active.primary_root == "selected-b"

    snapshot = store.snapshot()
    second = prepare_accepted_focus_transition(
        snapshot,
        protocol,
        focus_id="focus-direct-b",
        actor_root="actor",
        session_root="session",
        scope_root="scope",
        selected_roots=("selected-a",),
        primary_root="selected-a",
        origin="user",
        reason_roots=("reason-b",),
        attention_roots=(),
        authority_root="focus-authority",
        consent_evidence_root="focus-consent-b",
        created_at="2026-07-16T10:01:00Z",
    )
    store.commit(snapshot.revision, create=second.create, replace=second.replace)
    assert read_focus(
        store.snapshot(), protocol, "focus-direct-a"
    ).state_root == protocol.state("resolved")
    active = active_focus(store.snapshot(), protocol, session_root="session")
    assert active is not None
    assert active.root_id == "focus-direct-b"
    assert active.previous_root == "focus-direct-a"


def test_attention_focus_and_policy_survive_real_store_restart(tmp_path):
    database = tmp_path / "attention.sqlite3"
    store, protocol = _base_store(database)
    policy = _released_policy(store, protocol)
    revision = store.revision
    _eligibility(
        store,
        protocol,
        root="eligibility-a",
        candidate="candidate-a",
        revision=revision,
    )
    record_attention(
        store,
        protocol,
        attention_id="attention-a",
        observer_root="observer",
        candidate_root="candidate-a",
        scope_root="scope",
        source_snapshot_revision=revision,
        reason_roots=("reason-a",),
        policy_root=policy.root_id,
        priority_root="priority-critical",
        eligibility_root="eligibility-a",
    )
    propose_focus(
        store,
        protocol,
        focus_id="focus-a",
        actor_root="actor",
        session_root="session",
        scope_root="scope",
        selected_roots=("candidate-a",),
        primary_root="candidate-a",
        origin="user",
        reason_roots=("reason-a",),
        attention_roots=("attention-a",),
        authority_root="focus-authority",
        created_at="2026-07-16T12:00:00Z",
    )
    broker = FocusConsentBroker()
    handle = broker.issue(
        focus_root="focus-a",
        actor_root="actor",
        session_root="session",
        evidence_root="focus-consent-a",
        expires_at=100.0,
        now=10.0,
    )
    accept_focus(
        store,
        protocol,
        broker,
        handle,
        focus_root="focus-a",
        actor_root="actor",
        session_root="session",
        evidence_root="focus-consent-a",
        now=11.0,
    )
    final_revision = store.revision
    store.close()

    reopened = CellStore(database)
    reopened_protocol = open_attention_protocol(reopened.snapshot())
    assert reopened.revision == final_revision
    assert verify_attention_policy(
        reopened.snapshot(), reopened_protocol, policy.root_id
    ).class_roots == policy.class_roots
    assert read_attention(
        reopened.snapshot(), reopened_protocol, "attention-a"
    ).candidate_root == "candidate-a"
    assert active_focus(
        reopened.snapshot(), reopened_protocol, session_root="session"
    ).root_id == "focus-a"
    reopened.close()


def test_decisions_and_external_outcomes_cannot_claim_success_without_receipts():
    store, protocol = _base_store()
    record_decision(
        store,
        protocol,
        decision_id="decision-a",
        subject_root="decision-subject",
        action_root="decision-action",
        actor_root="actor",
        authority_root="decision-authority",
        evidence_roots=("decision-evidence",),
        state="accepted",
        created_at="2026-07-16T12:00:00Z",
    )
    assert read_decision(store.snapshot(), protocol, "decision-a").state_root == protocol.state("accepted")
    with pytest.raises(InvalidCell, match="receipt and reconciliation"):
        record_outcome(
            store,
            protocol,
            outcome_id="outcome-unproven",
            decision_root="decision-a",
            provider_root="provider",
            state="succeeded",
            observed_at="2026-07-16T12:01:00Z",
        )
    with pytest.raises(InvalidCell, match="requires a reason"):
        record_outcome(
            store,
            protocol,
            outcome_id="outcome-failed-without-reason",
            decision_root="decision-a",
            provider_root="provider",
            state="failed",
            observed_at="2026-07-16T12:01:00Z",
        )
    record_outcome(
        store,
        protocol,
        outcome_id="outcome-a",
        decision_root="decision-a",
        provider_root="provider",
        state="succeeded",
        observed_at="2026-07-16T12:02:00Z",
        receipt_root="receipt",
        reconciliation_root="reconciliation",
    )
    outcome = read_outcome(store.snapshot(), protocol, "outcome-a")
    assert outcome.receipt_root == "receipt"
    assert outcome.reconciliation_root == "reconciliation"
    assert all(type(cell) is Cell for cell in store.snapshot().cells.values())
