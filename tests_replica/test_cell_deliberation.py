"""Forcing courts for a Cell-native deliberation/workshop authority."""
from __future__ import annotations

import pytest

from nodelang.cell_authorization import (
    AuthenticationBroker,
    AuthorizationDenied,
    PolicyReleaseBroker,
    bootstrap_authorization_protocol,
    build_authorization_policy,
    build_authorization_rule,
    release_authorization_policy,
)
from nodelang.cell_deliberation import (
    DeliberationRequirement,
    append_deliberation_entry,
    append_deliberation_value_entry,
    bootstrap_deliberation_protocol,
    compose_deliberation_space,
    evaluate_deliberation_gate,
    extend_deliberation_space,
    list_deliberation_entries,
    open_deliberation_protocol,
    read_deliberation_entry,
    read_deliberation_space,
)
from nodelang.cell_protocols import compose_relation_cells
from nodelang.cell_value_graph import (
    bootstrap_value_graph_protocol,
    read_value_graph,
)
from nodelang.cell_protocols import read_relation, rewire_incidence
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


ROOTS = {
    "founder": b"Founder",
    "outsider": b"Outsider",
    "workspace": b"ArchHub workspace",
    "assurance-strong": b"Strong authentication",
    "lifecycle-wip": b"WIP",
    "category-note": b"note",
    "category-plan": b"plan",
    "category-test": b"test",
    "category-doc": b"doc",
    "category-court": b"court",
    "phase-claim": b"claim",
    "phase-done": b"done",
    "leaf-a": b"work leaf A",
    "evidence-a": b"court evidence A",
}


def _system(database_path=None):
    store = CellStore(database_path)
    deliberation = bootstrap_deliberation_protocol(
        store, prefix="test:deliberation"
    )
    authorization = bootstrap_authorization_protocol(
        store, prefix="test:authorization"
    )
    store.commit(
        store.revision,
        create=tuple(
            Cell(root, NULL_CELL_ID, NULL_CELL_ID, atom)
            for root, atom in ROOTS.items()
        ),
    )
    rule = build_authorization_rule(
        store,
        authorization,
        rule_id="test:rule:founder-create",
        effect="permit",
        principal_root="founder",
        object_root="workspace",
        action_root=authorization.actions["create"],
    )
    policy = build_authorization_policy(
        store,
        authorization,
        (rule,),
        policy_id="test:policy:workshop",
        version="1.0.0",
    )
    releases = PolicyReleaseBroker()
    handle = releases.mint_from_trusted_administrator(policy, "founder")
    release_authorization_policy(
        store,
        authorization,
        policy,
        releases,
        handle,
        administrator_root="founder",
    )
    space = compose_deliberation_space(
        store,
        deliberation,
        space_id="test:workshop",
        title="ArchHub Workshop",
        participant_roots=("founder",),
        category_roots=(
            "category-note",
            "category-plan",
            "category-test",
            "category-doc",
            "category-court",
        ),
        policy_root=policy,
        action_root=authorization.actions["create"],
        scope_roots=("workspace",),
        lifecycle_root="lifecycle-wip",
        requirements=(
            DeliberationRequirement("phase-claim", "category-plan"),
            DeliberationRequirement("phase-done", "category-test"),
            DeliberationRequirement("phase-done", "category-doc"),
            DeliberationRequirement("phase-done", "category-court"),
        ),
    )
    identities = AuthenticationBroker()
    context = identities.mint_authenticated_context(
        "founder",
        principal_roots=("founder",),
        tenant_root="workspace",
        assurance_root="assurance-strong",
        lifetime_seconds=120,
    )
    return store, deliberation, authorization, identities, context, space


def _append(store, deliberation, authorization, identities, context, **changes):
    values = dict(
        space_root="test:workshop",
        actor_root="founder",
        category_root="category-plan",
        content="Inspect the Cell authority before changing it.",
        reference_roots=("leaf-a",),
        recipient_roots=(),
        evidence_roots=(),
        reply_to_root=None,
        idempotency_key="plan:leaf-a:v1",
        created_at="2026-07-17T12:00:00+00:00",
        authorization_protocol=authorization,
        authentication_broker=identities,
        authentication_context=context,
    )
    values.update(changes)
    return append_deliberation_entry(store, deliberation, **values)


def test_space_and_entries_are_relations_not_a_json_room_blob():
    store, protocol, authorization, identities, context, _space = _system()
    entry = _append(
        store, protocol, authorization, identities, context,
        recipient_roots=("founder",), evidence_roots=("evidence-a",),
    )
    snapshot = store.snapshot()
    assert snapshot.cells["test:workshop"].atom == b""
    assert snapshot.cells[entry.root_id].atom == b""
    projected = read_deliberation_entry(snapshot, protocol, entry.root_id)
    assert projected.actor_root == "founder"
    assert projected.category_root == "category-plan"
    assert projected.content == "Inspect the Cell authority before changing it."
    assert projected.reference_roots == ("leaf-a",)
    assert projected.recipient_roots == ("founder",)
    assert projected.evidence_roots == ("evidence-a",)
    assert projected.policy_root == "test:policy:workshop"
    assert projected.authorization_rule_roots == (
        "test:rule:founder-create",
    )
    assert read_deliberation_space(
        snapshot, protocol, "test:workshop"
    ).entry_roots == (entry.root_id,)


def test_value_payload_and_ledger_entry_are_one_atomic_graph_revision():
    store, protocol, authorization, identities, context, _space = _system()
    values = bootstrap_value_graph_protocol(store, prefix="test:values")
    before = store.revision
    payload = {
        "owner": "founder",
        "gate": "release",
        "evidence": ["court:one", "court:two"],
    }
    entry, payload_root, revision = append_deliberation_value_entry(
        store,
        protocol,
        values,
        space_root="test:workshop",
        actor_root="founder",
        category_root="category-test",
        content="Release court completed.",
        payload=payload,
        payload_root="test:payload:release-court-1",
        idempotency_key="release-court-1",
        created_at="2026-07-21T12:00:00+00:00",
        authorization_protocol=authorization,
        authentication_broker=identities,
        authentication_context=context,
    )
    assert revision == before + 1 == store.revision
    assert entry.reference_roots == (payload_root,)
    assert read_value_graph(store.snapshot(), values, payload_root) == payload
    assert len(list_deliberation_entries(
        store.snapshot(), protocol, "test:workshop"
    )) == 1

    repeated, repeated_root, repeated_revision = append_deliberation_value_entry(
        store,
        protocol,
        values,
        space_root="test:workshop",
        actor_root="founder",
        category_root="category-test",
        content="Release court completed.",
        payload=payload,
        payload_root=payload_root,
        idempotency_key="release-court-1",
        created_at="2026-07-21T12:00:00+00:00",
        authorization_protocol=authorization,
        authentication_broker=identities,
        authentication_context=context,
    )
    assert repeated.root_id == entry.root_id
    assert repeated_root == payload_root
    assert repeated_revision == revision == store.revision

    with pytest.raises(InvalidCell, match="another value"):
        append_deliberation_value_entry(
            store,
            protocol,
            values,
            space_root="test:workshop",
            actor_root="founder",
            category_root="category-test",
            content="Release court completed.",
            payload={"owner": "different"},
            payload_root=payload_root,
            idempotency_key="release-court-1",
            created_at="2026-07-21T12:00:00+00:00",
            authorization_protocol=authorization,
            authentication_broker=identities,
            authentication_context=context,
        )


def test_gate_requirements_are_graph_policy_and_rewiring_changes_behavior():
    store, protocol, authorization, identities, context, space = _system()
    _append(store, protocol, authorization, identities, context)
    claim = evaluate_deliberation_gate(
        store.snapshot(), protocol, "test:workshop",
        phase_root="phase-claim", reference_root="leaf-a",
    )
    done = evaluate_deliberation_gate(
        store.snapshot(), protocol, "test:workshop",
        phase_root="phase-done", reference_root="leaf-a",
    )
    assert claim.allowed is True
    assert done.allowed is False
    assert done.missing_category_roots == (
        "category-test", "category-doc", "category-court"
    )

    requirement = space.requirement_roots[0]
    members = read_relation(store.snapshot(), requirement)
    category_incidence = next(
        item.incidence_id for item in members
        if item.role_id == protocol.role("requirement-category")
    )
    rewire_incidence(store, category_incidence, "category-court")
    rewired = evaluate_deliberation_gate(
        store.snapshot(), protocol, "test:workshop",
        phase_root="phase-claim", reference_root="leaf-a",
    )
    assert rewired.allowed is False
    assert rewired.missing_category_roots == ("category-court",)


def test_space_extension_adds_collaborators_and_evidence_gates_without_history_loss():
    store, protocol, authorization, identities, context, _space = _system()
    store.commit(store.revision, create=(
        Cell("agent-a", NULL_CELL_ID, NULL_CELL_ID, b"Agent A"),
        Cell("category-research", NULL_CELL_ID, NULL_CELL_ID, b"research"),
    ))
    before = store.revision
    extended = extend_deliberation_space(
        store,
        protocol,
        space_root="test:workshop",
        participant_roots=("agent-a",),
        category_roots=("category-research",),
        requirements=(DeliberationRequirement(
            "phase-claim", "category-research", 1, 1
        ),),
    )
    assert store.revision == before + 1
    assert extended.participant_roots == ("founder", "agent-a")
    assert extended.category_roots[-1] == "category-research"
    assert len(extended.requirement_roots) == 5

    _append(store, protocol, authorization, identities, context)
    missing = evaluate_deliberation_gate(
        store.snapshot(), protocol, "test:workshop",
        phase_root="phase-claim", reference_root="leaf-a",
    )
    assert missing.allowed is False
    assert missing.missing_category_roots == ("category-research",)
    assert missing.missing_evidence_category_roots == ("category-research",)

    _append(
        store, protocol, authorization, identities, context,
        category_root="category-research",
        content="Research record without a source.",
        idempotency_key="research:leaf-a:empty",
        created_at="2026-07-17T12:01:00+00:00",
    )
    missing_evidence = evaluate_deliberation_gate(
        store.snapshot(), protocol, "test:workshop",
        phase_root="phase-claim", reference_root="leaf-a",
    )
    assert missing_evidence.missing_category_roots == ()
    assert missing_evidence.missing_evidence_category_roots == (
        "category-research",
    )

    _append(
        store, protocol, authorization, identities, context,
        category_root="category-research",
        content="Research record with admitted evidence.",
        evidence_roots=("evidence-a",),
        idempotency_key="research:leaf-a:evidence",
        created_at="2026-07-17T12:02:00+00:00",
    )
    admitted = evaluate_deliberation_gate(
        store.snapshot(), protocol, "test:workshop",
        phase_root="phase-claim", reference_root="leaf-a",
    )
    assert admitted.allowed is True
    assert admitted.observed_evidence_counts["category-research"] == 1

    revision = store.revision
    repeated = extend_deliberation_space(
        store,
        protocol,
        space_root="test:workshop",
        participant_roots=("agent-a",),
        category_roots=("category-research",),
        requirements=(DeliberationRequirement(
            "phase-claim", "category-research", 1, 1
        ),),
    )
    assert repeated == read_deliberation_space(
        store.snapshot(), protocol, "test:workshop"
    )
    assert store.revision == revision


def test_protocol_vocabulary_upgrade_is_append_only_and_keeps_existing_rooms_readable():
    from nodelang.cell_deliberation import ROLE_NAMES, upgrade_deliberation_protocol

    store = CellStore()
    prefix = "test:legacy-deliberation"
    missing_name = "requirement-evidence-minimum"
    legacy_names = tuple(name for name in ROLE_NAMES if name != missing_name)
    roles = {name: "%s:role:%s" % (prefix, name) for name in legacy_names}
    relation = compose_relation_cells(
        ((roles["vocabulary-member"], root) for root in roles.values()),
        relation_id=prefix + ":root",
    )
    store.commit(store.revision, create=(
        *(Cell(root, NULL_CELL_ID, NULL_CELL_ID, name.encode("ascii"))
          for name, root in roles.items()),
        *relation.cells,
    ))
    before_cells = set(store.snapshot().cells)
    upgraded = upgrade_deliberation_protocol(store, prefix=prefix)
    assert upgraded.role(missing_name) in store.snapshot().cells
    assert before_cells.issubset(store.snapshot().cells)
    assert open_deliberation_protocol(
        store.snapshot(), prefix + ":root"
    ) == upgraded


def test_append_is_authorized_participant_bound_and_idempotent():
    store, protocol, authorization, identities, context, _space = _system()
    first = _append(store, protocol, authorization, identities, context)
    revision = store.revision
    repeated = _append(store, protocol, authorization, identities, context)
    assert repeated.root_id == first.root_id
    assert store.revision == revision
    assert len(list_deliberation_entries(
        store.snapshot(), protocol, "test:workshop"
    )) == 1
    with pytest.raises(InvalidCell, match="idempotency"):
        _append(
            store, protocol, authorization, identities, context,
            content="Different content under the same request identity.",
        )

    outsider_context = identities.mint_authenticated_context(
        "outsider",
        principal_roots=("outsider",),
        tenant_root="workspace",
        assurance_root="assurance-strong",
        lifetime_seconds=120,
    )
    with pytest.raises(AuthorizationDenied):
        _append(
            store, protocol, authorization, identities, outsider_context,
            actor_root="outsider", idempotency_key="outsider:attempt",
        )


def test_append_uses_request_local_relation_projection_scope(monkeypatch):
    import nodelang.cell_deliberation as deliberation_module
    from nodelang.cell_protocols import _RELATION_PROJECTION_CACHE

    store, protocol, authorization, identities, context, _space = _system()
    original = deliberation_module.require_authorization
    cache_seen = []

    def recording_require_authorization(*args, **kwargs):
        cache_seen.append(_RELATION_PROJECTION_CACHE.get() is not None)
        return original(*args, **kwargs)

    monkeypatch.setattr(
        deliberation_module,
        "require_authorization",
        recording_require_authorization,
    )

    _append(store, protocol, authorization, identities, context)

    assert cache_seen == [True]


def test_reply_must_target_an_entry_in_the_same_space():
    store, protocol, authorization, identities, context, _space = _system()
    first = _append(store, protocol, authorization, identities, context)
    second = _append(
        store, protocol, authorization, identities, context,
        category_root="category-note",
        content="Reviewed.",
        reply_to_root=first.root_id,
        idempotency_key="reply:leaf-a:v1",
        created_at="2026-07-17T12:01:00+00:00",
    )
    assert read_deliberation_entry(
        store.snapshot(), protocol, second.root_id
    ).reply_to_root == first.root_id
    with pytest.raises(InvalidCell, match="same deliberation space"):
        _append(
            store, protocol, authorization, identities, context,
            reply_to_root="leaf-a", idempotency_key="bad-reply",
        )


def test_cell_deliberation_survives_process_restart(tmp_path):
    path = tmp_path / "deliberation.sqlite3"
    store, protocol, authorization, identities, context, _space = _system(path)
    entry = _append(store, protocol, authorization, identities, context)
    store.close()

    reopened = CellStore(path)
    restored_protocol = open_deliberation_protocol(
        reopened.snapshot(), "test:deliberation:root"
    )
    entries = list_deliberation_entries(
        reopened.snapshot(), restored_protocol, "test:workshop"
    )
    assert tuple(item.root_id for item in entries) == (entry.root_id,)
    assert evaluate_deliberation_gate(
        reopened.snapshot(), restored_protocol, "test:workshop",
        phase_root="phase-claim", reference_root="leaf-a",
    ).allowed
    reopened.close()
