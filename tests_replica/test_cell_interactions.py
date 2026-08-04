"""Courts for one graph-held interaction path with no product dispatch."""
from __future__ import annotations

import inspect
import pickle

import pytest

from nodelang import cell_interactions as interaction_runtime
from nodelang.cell_authorization import (
    AuthenticationBroker,
    PolicyReleaseBroker,
    bootstrap_authorization_protocol,
    build_authorization_policy,
    build_authorization_rule,
    release_authorization_policy,
)
from nodelang.cell_interactions import (
    InteractionProjectionBroker,
    InteractionProjectionDenied,
    InteractionProjectionExpired,
    InteractionReleaseBroker,
    bootstrap_interaction_protocol,
    build_interaction,
    execute_interaction,
    project_interaction_protocol,
    project_control_interactions,
    release_interaction,
    verify_released_interaction,
)
from nodelang.cell_protocols import read_relation, rewire_incidence
from nodelang.cell_rules import bootstrap_rule_protocol, build_rule
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.cell_transactions import (
    bootstrap_transaction_protocol,
    build_transaction,
)
from nodelang.universal_cell import (
    NULL_CELL_ID,
    Cell,
    CellStore,
    Conflict,
    InvalidCell,
    MatchBudgetExceeded,
    NoMatch,
    Snapshot,
    _OverlayCellMap,
)


def _terminal(root_id: str, value: str) -> Cell:
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8"))


def _build_authority(store: CellStore):
    protocol = bootstrap_authorization_protocol(
        store, prefix="interaction-test:authorization"
    )
    roots = {
        "subject": "interaction-test:subject",
        "principal": "interaction-test:principal",
        "object": "interaction-test:view",
        "release_object": "interaction-test:interaction-definitions",
        "assurance": "interaction-test:assurance",
    }
    store.commit(store.revision, create=tuple(
        _terminal(root_id, name) for name, root_id in roots.items()
    ))
    rule_root = build_authorization_rule(
        store,
        protocol,
        rule_id="interaction-test:authorization:permit",
        effect="permit",
        principal_root=roots["principal"],
        object_root=roots["object"],
        action_root=protocol.actions["edit"],
        assurance_root=roots["assurance"],
    )
    release_rule_root = build_authorization_rule(
        store,
        protocol,
        rule_id="interaction-test:authorization:release",
        effect="permit",
        principal_root=roots["principal"],
        object_root=roots["release_object"],
        action_root=protocol.actions["publish"],
        assurance_root=roots["assurance"],
    )
    policy_root = build_authorization_policy(
        store,
        protocol,
        (rule_root, release_rule_root),
        policy_id="interaction-test:authorization:policy",
        version="1",
    )
    release_broker = PolicyReleaseBroker()
    release_authorization_policy(
        store,
        protocol,
        policy_root,
        release_broker,
        release_broker.mint_from_trusted_administrator(
            policy_root, roots["subject"]
        ),
        administrator_root=roots["subject"],
    )
    broker = AuthenticationBroker()
    context = broker.mint_authenticated_context(
        roots["subject"],
        principal_roots=(roots["principal"],),
        tenant_root=None,
        assurance_root=roots["assurance"],
    )
    return protocol, policy_root, broker, context, roots


def _build_rules(store: CellStore):
    cells = (
        Cell("p:current", NULL_CELL_ID, NULL_CELL_ID, b""),
        Cell("p:desired", NULL_CELL_ID, NULL_CELL_ID, b""),
        Cell("p:state", "p:current", "p:desired", b"state"),
        Cell("r:activate:left", NULL_CELL_ID, NULL_CELL_ID, b""),
        Cell("r:activate:right", NULL_CELL_ID, NULL_CELL_ID, b""),
        Cell(
            "r:activate",
            "r:activate:left",
            "r:activate:right",
            b"state",
        ),
        Cell("r:retain:left", NULL_CELL_ID, NULL_CELL_ID, b""),
        Cell("r:retain:right", NULL_CELL_ID, NULL_CELL_ID, b""),
        Cell("r:retain", "r:retain:left", "r:retain:right", b"state"),
    )
    store.commit(store.revision, create=cells)
    protocol = bootstrap_rule_protocol(store)
    activate = build_rule(
        store,
        protocol,
        rule_id="rule:activate",
        pattern_root="p:state",
        replacement_root="r:activate",
        pattern_variables=("p:current", "p:desired"),
        replacement_bindings={
            "r:activate:left": "p:desired",
            "r:activate:right": "p:desired",
        },
    ).root_id
    retain = build_rule(
        store,
        protocol,
        rule_id="rule:retain",
        pattern_root="p:state",
        replacement_root="r:retain",
        pattern_variables=("p:current", "p:desired"),
        replacement_bindings={
            "r:retain:left": "p:current",
            "r:retain:right": "p:desired",
        },
    ).root_id
    return protocol, activate, retain


def _build_fixture():
    store = CellStore()
    rule_protocol, activate, retain = _build_rules(store)
    auth = _build_authority(store)
    authorization_protocol, policy_root, broker, context, roots = auth
    interaction_protocol = bootstrap_interaction_protocol(store)
    lifecycle_root = "interaction-test:released"
    event_root = "interaction-test:event:activate"
    session_root = "interaction-test:browser-session"
    created = [
        _terminal(lifecycle_root, "released"),
        _terminal(event_root, "activate"),
        _terminal(session_root, "browser session"),
    ]
    interactions = []
    controls = []
    targets = []
    for index in range(3):
        control = f"control:{index}"
        current = f"state:{index}:current"
        desired = f"state:{index}:desired"
        target = f"state:{index}"
        created.extend((
            _terminal(control, f"control {index}"),
            _terminal(current, f"current {index}"),
            _terminal(desired, f"desired {index}"),
            Cell(target, current, desired, b"state"),
        ))
        controls.append(control)
        targets.append(target)
    store.commit(store.revision, create=tuple(created))
    transaction_protocol = bootstrap_transaction_protocol(
        store, prefix="interaction-test:transaction-protocol"
    )
    activate_actions = []
    retain_actions = []
    for index, target in enumerate(targets):
        activate_actions.append(build_transaction(
            store,
            transaction_protocol,
            transaction_id=f"interaction-test:transaction:activate:{index}",
            steps=((activate, target),),
        ).root_id)
        retain_actions.append(build_transaction(
            store,
            transaction_protocol,
            transaction_id=f"interaction-test:transaction:retain:{index}",
            steps=((retain, target),),
        ).root_id)
    for index, (control, target) in enumerate(zip(controls, targets)):
        interactions.append(build_interaction(
            store,
            interaction_protocol,
            interaction_id=f"interaction:{index}",
            control_root=control,
            event_root=event_root,
            target_root=target,
            action_root=activate_actions[index],
            subject_root=roots["subject"],
            policy_root=policy_root,
            authorization_action_root=authorization_protocol.actions["edit"],
            authorization_object_root=roots["object"],
            lifecycle_root=lifecycle_root,
        ).root_id)
    release_key_id = "interaction-test-release"
    release_key_provider = MemorySigningKeyProvider(
        release_key_id, b"interaction-test-release-key-32-bytes"
    )
    release_broker = InteractionReleaseBroker(
        release_key_provider, key_id=release_key_id
    )
    projection_broker = InteractionProjectionBroker(release_broker)
    projection_handle = projection_broker.mint(
        store.snapshot(),
        session_root=session_root,
        subject_root=roots["subject"],
        view_root=roots["object"],
    )
    projection_broker.issue(
        projection_handle,
        store.snapshot(),
        interaction_protocol,
        controls,
        interactions,
        rule_protocol=rule_protocol,
        transaction_protocol=transaction_protocol,
    )
    return {
        "store": store,
        "rule_protocol": rule_protocol,
        "transaction_protocol": transaction_protocol,
        "activate": activate,
        "retain": retain,
        "activate_actions": tuple(activate_actions),
        "retain_actions": tuple(retain_actions),
        "authorization_protocol": authorization_protocol,
        "policy_root": policy_root,
        "broker": broker,
        "context": context,
        "roots": roots,
        "interaction_protocol": interaction_protocol,
        "event": event_root,
        "controls": tuple(controls),
        "targets": tuple(targets),
        "interactions": tuple(interactions),
        "projection_broker": projection_broker,
        "release_broker": release_broker,
        "projection_handle": projection_handle,
        "session_root": session_root,
    }


def test_interaction_read_scope_reuses_only_one_exact_snapshot(monkeypatch):
    fixture = _build_fixture()
    store = fixture["store"]
    protocol = fixture["interaction_protocol"]
    interaction_root = fixture["interactions"][0]
    snapshot = store.snapshot()
    original_project = interaction_runtime.project_interaction_protocol
    protocol_projections = []

    def record_protocol_projection(current_snapshot, root_id, **kwargs):
        protocol_projections.append((current_snapshot.revision, id(current_snapshot.cells)))
        return original_project(current_snapshot, root_id, **kwargs)

    monkeypatch.setattr(
        interaction_runtime,
        "project_interaction_protocol",
        record_protocol_projection,
    )
    with interaction_runtime.interaction_projection_scope():
        first = interaction_runtime.read_interaction(
            snapshot, protocol, interaction_root, budget=512
        )
        second = interaction_runtime.read_interaction(
            snapshot, protocol, interaction_root, budget=512
        )
        assert second is first
    assert protocol_projections == [(snapshot.revision, id(snapshot.cells))]

    outside = interaction_runtime.read_interaction(
        snapshot, protocol, interaction_root, budget=512
    )
    assert outside == first
    assert outside is not first
    assert protocol_projections == [
        (snapshot.revision, id(snapshot.cells)),
        (snapshot.revision, id(snapshot.cells)),
    ]


def test_interaction_read_scope_does_not_repeat_same_budget_relation_reads(
    monkeypatch,
):
    fixture = _build_fixture()
    store = fixture["store"]
    protocol = fixture["interaction_protocol"]
    interaction_root = fixture["interactions"][0]
    snapshot = store.snapshot()
    original_read_relation = interaction_runtime.read_relation
    relation_reads = []

    def record_relation_read(current_snapshot, root_id, **kwargs):
        relation_reads.append((
            current_snapshot.revision,
            id(current_snapshot.cells),
            root_id,
            kwargs.get("budget"),
        ))
        return original_read_relation(current_snapshot, root_id, **kwargs)

    monkeypatch.setattr(
        interaction_runtime, "read_relation", record_relation_read
    )
    with interaction_runtime.interaction_projection_scope():
        first = interaction_runtime.read_interaction(
            snapshot, protocol, interaction_root, budget=512
        )
        second = interaction_runtime.read_interaction(
            snapshot, protocol, interaction_root, budget=512
        )
        assert second is first

    assert [root for _revision, _cells, root, _budget in relation_reads].count(
        protocol.root_id
    ) == 1
    assert [root for _revision, _cells, root, _budget in relation_reads].count(
        interaction_root
    ) == 1


def test_interaction_read_scope_rejects_budget_and_snapshot_aliasing(monkeypatch):
    fixture = _build_fixture()
    store = fixture["store"]
    protocol = fixture["interaction_protocol"]
    interaction_root = fixture["interactions"][0]
    snapshot = store.snapshot()
    foreign_cells = dict(snapshot.cells)
    foreign_cells.pop(interaction_root)
    foreign_snapshot = Snapshot(snapshot.revision, foreign_cells)
    original_project = interaction_runtime.project_interaction_protocol
    protocol_projections = []

    def record_protocol_projection(current_snapshot, root_id, **kwargs):
        protocol_projections.append((current_snapshot.revision, id(current_snapshot.cells)))
        return original_project(current_snapshot, root_id, **kwargs)

    monkeypatch.setattr(
        interaction_runtime,
        "project_interaction_protocol",
        record_protocol_projection,
    )
    with interaction_runtime.interaction_projection_scope():
        accepted = interaction_runtime.read_interaction(
            snapshot, protocol, interaction_root, budget=512
        )
        with pytest.raises(MatchBudgetExceeded):
            interaction_runtime.read_interaction(
                snapshot, protocol, interaction_root, budget=1
            )
        with pytest.raises(InvalidCell):
            interaction_runtime.read_interaction(
                foreign_snapshot, protocol, interaction_root, budget=512
            )
        store.commit(
            store.revision,
            create=(_terminal("interaction-test:new-revision", "new revision"),),
        )
        next_snapshot = store.snapshot()
        next_read = interaction_runtime.read_interaction(
            next_snapshot, protocol, interaction_root, budget=512
        )
        assert next_read == accepted
        assert next_read is not accepted

    assert protocol_projections == [
        (snapshot.revision, id(snapshot.cells)),
        (foreign_snapshot.revision, id(foreign_snapshot.cells)),
        (next_snapshot.revision, id(next_snapshot.cells)),
    ]


def _execute(fixture, index: int):
    store = fixture["store"]
    fixture["projection_broker"].issue(
        fixture["projection_handle"],
        store.snapshot(),
        fixture["interaction_protocol"],
        fixture["controls"],
        fixture["interactions"],
        rule_protocol=fixture["rule_protocol"],
        transaction_protocol=fixture["transaction_protocol"],
    )
    return execute_interaction(
        store,
        fixture["interaction_protocol"],
        fixture["transaction_protocol"],
        fixture["rule_protocol"],
        fixture["authorization_protocol"],
        fixture["broker"],
        fixture["context"],
        fixture["projection_broker"],
        fixture["projection_handle"],
        interaction_root=fixture["interactions"][index],
        control_root=fixture["controls"][index],
        event_root=fixture["event"],
        expected_revision=store.revision,
    )


def test_interaction_protocol_reconstructs_from_persisted_graph_root(tmp_path):
    path = tmp_path / "interaction-protocol.sqlite3"
    store = CellStore(path)
    protocol = bootstrap_interaction_protocol(store)
    root_id = protocol.root_id
    store.close()

    reopened = CellStore(path)
    restored = project_interaction_protocol(reopened.snapshot(), root_id)
    assert restored == protocol
    reopened.close()


def test_three_unrelated_controls_execute_through_one_graph_path():
    fixture = _build_fixture()
    execute_code = execute_interaction.__code__.co_code
    for index, target in enumerate(fixture["targets"]):
        assert execute_interaction.__code__.co_code == execute_code
        before = fixture["store"].read(target)
        assert before.link0 != before.link1
        result = _execute(fixture, index)
        after = fixture["store"].read(target)
        assert after.link0 == before.link1
        assert result.rewrite.root_id == fixture["activate_actions"][index]
        assert target in result.rewrite.touched_roots
        assert result.authorization.allowed is True


def test_interaction_inputs_require_named_transaction_bindings():
    # Named per-input binding is not implemented yet; this court is intentionally
    # red until the interaction contract carries names and explicit binding
    # relations.
    fixture = _build_fixture()
    store = fixture["store"]

    assert "input_bindings" in inspect.signature(build_interaction).parameters

    control_root = "control:input-binding-red"
    store.commit(
        store.revision,
        create=(_terminal(control_root, "input binding red"),),
    )

    input_rule_root = build_rule(
        store,
        fixture["rule_protocol"],
        rule_id="rule:input-binding-red",
        pattern_root="p:state",
        replacement_root="r:activate",
        pattern_variables=("p:current", "p:desired"),
        replacement_bindings={"r:activate:left": "p:desired"},
        replacement_constants={
            "r:activate:right": fixture["targets"][1],
            "r:activate:missing": fixture["targets"][0],
        },
    ).root_id
    transaction_root = build_transaction(
        store,
        fixture["transaction_protocol"],
        transaction_id="interaction-test:transaction:input-binding-red",
        steps=((input_rule_root, fixture["targets"][0]),),
    ).root_id
    interaction_root = build_interaction(
        store,
        fixture["interaction_protocol"],
        interaction_id="interaction:input-binding-red",
        control_root=control_root,
        event_root=fixture["event"],
        target_root=fixture["targets"][0],
        # This interaction intentionally provides only one input root while the
        # action rule declares two distinct input contracts.
        input_roots=(fixture["targets"][1],),
        action_root=transaction_root,
        subject_root=fixture["roots"]["subject"],
        policy_root=fixture["policy_root"],
        authorization_action_root=(
            fixture["authorization_protocol"].actions["edit"]
        ),
        authorization_object_root=fixture["roots"]["object"],
        lifecycle_root="interaction-test:released",
    ).root_id

    handle = fixture["projection_broker"].mint(
        store.snapshot(),
        session_root=fixture["session_root"],
        subject_root=fixture["roots"]["subject"],
        view_root=fixture["roots"]["object"],
    )
    fixture["projection_broker"].issue(
        handle,
        store.snapshot(),
        fixture["interaction_protocol"],
        (control_root,),
        (interaction_root,),
        rule_protocol=fixture["rule_protocol"],
        transaction_protocol=fixture["transaction_protocol"],
    )
    with pytest.raises(InvalidCell, match="explicitly bound"):
        execute_interaction(
            store,
            fixture["interaction_protocol"],
            fixture["transaction_protocol"],
            fixture["rule_protocol"],
            fixture["authorization_protocol"],
            fixture["broker"],
            fixture["context"],
            fixture["projection_broker"],
            handle,
            interaction_root=interaction_root,
            control_root=control_root,
            event_root=fixture["event"],
            expected_revision=store.revision,
        )


def test_nontransaction_admission_does_not_iterate_the_complete_snapshot(
    monkeypatch,
):
    fixture = _build_fixture()
    capability_root = "interaction-test:capability:scope"
    fixture["store"].commit(
        fixture["store"].revision,
        create=(_terminal(capability_root, "scope"),),
    )
    interaction_root = build_interaction(
        fixture["store"],
        fixture["interaction_protocol"],
        interaction_id="interaction:bounded-input-membership",
        control_root=fixture["controls"][0],
        event_root=fixture["event"],
        target_root=fixture["targets"][0],
        input_roots=(fixture["targets"][1],),
        action_root=capability_root,
        subject_root=fixture["roots"]["subject"],
        policy_root=fixture["policy_root"],
        authorization_action_root=(
            fixture["authorization_protocol"].actions["edit"]
        ),
        authorization_object_root=fixture["roots"]["object"],
        lifecycle_root="interaction-test:released",
    ).root_id
    projection = InteractionProjectionBroker()
    handle = projection.mint(
        fixture["store"].snapshot(),
        session_root=fixture["session_root"],
        subject_root=fixture["roots"]["subject"],
        view_root=fixture["roots"]["object"],
    )
    projection.issue(
        handle,
        fixture["store"].snapshot(),
        fixture["interaction_protocol"],
        (fixture["controls"][0],),
        (interaction_root,),
        rule_protocol=fixture["rule_protocol"],
        transaction_protocol=fixture["transaction_protocol"],
        admitted_nontransaction_action_roots=(capability_root,),
    )
    source_snapshot = fixture["store"].snapshot()
    snapshot = Snapshot(
        source_snapshot.revision,
        _OverlayCellMap(source_snapshot.cells, {}),
    )
    monkeypatch.setattr(fixture["store"], "snapshot", lambda: snapshot)
    cell_map_type = type(snapshot.cells)

    def reject_complete_snapshot_iteration(_cells):
        raise AssertionError(
            "bounded interaction admission iterated the complete Cell graph"
        )

    monkeypatch.setattr(
        cell_map_type, "__iter__", reject_complete_snapshot_iteration
    )
    admitted = interaction_runtime.admit_interaction(
        fixture["store"],
        fixture["interaction_protocol"],
        fixture["transaction_protocol"],
        fixture["rule_protocol"],
        fixture["authorization_protocol"],
        fixture["broker"],
        fixture["context"],
        projection,
        handle,
        interaction_root=interaction_root,
        control_root=fixture["controls"][0],
        event_root=fixture["event"],
        expected_revision=snapshot.revision,
        admitted_nontransaction_action_roots=(capability_root,),
    )
    assert admitted.interaction.root_id == interaction_root
    assert admitted.interaction.input_roots == (fixture["targets"][1],)


def test_projection_issue_returns_the_exact_in_call_verified_interactions():
    fixture = _build_fixture()
    issued = fixture["projection_broker"].issue_with_interactions(
        fixture["projection_handle"],
        fixture["store"].snapshot(),
        fixture["interaction_protocol"],
        fixture["controls"],
        fixture["interactions"],
        rule_protocol=fixture["rule_protocol"],
        transaction_protocol=fixture["transaction_protocol"],
    )
    assert issued.lease.revision == fixture["store"].revision
    assert tuple(
        interaction.root_id for interaction in issued.interactions
    ) == fixture["interactions"]
    assert tuple(
        issued.lease.bindings[control] for control in fixture["controls"]
    ) == fixture["interactions"]
    with pytest.raises(TypeError, match="issues cannot be serialized"):
        pickle.dumps(issued)


def test_rewiring_action_incidence_changes_behavior_without_engine_edit():
    fixture = _build_fixture()
    members = read_relation(
        fixture["store"].snapshot(), fixture["interactions"][0], budget=64
    )
    action_member = next(
        member for member in members
        if member.role_id == fixture["interaction_protocol"].role("action")
    )
    rewire_incidence(
        fixture["store"],
        action_member.incidence_id,
        fixture["retain_actions"][0],
    )
    before = fixture["store"].read(fixture["targets"][0])
    _execute(fixture, 0)
    after = fixture["store"].read(fixture["targets"][0])
    assert after.link0 == before.link0
    assert after.link1 == before.link1


def test_graph_held_precondition_blocks_before_action_mutation():
    fixture = _build_fixture()
    fixture["store"].commit(fixture["store"].revision, create=(
        Cell("blocked:left", NULL_CELL_ID, NULL_CELL_ID, b""),
        Cell("blocked:right", NULL_CELL_ID, NULL_CELL_ID, b""),
        Cell("blocked:pattern", "blocked:left", "blocked:right", b"blocked"),
        Cell("blocked:replacement:left", NULL_CELL_ID, NULL_CELL_ID, b""),
        Cell("blocked:replacement:right", NULL_CELL_ID, NULL_CELL_ID, b""),
        Cell(
            "blocked:replacement",
            "blocked:replacement:left",
            "blocked:replacement:right",
            b"blocked",
        ),
    ))
    blocked = build_rule(
        fixture["store"],
        fixture["rule_protocol"],
        rule_id="rule:blocked-precondition",
        pattern_root="blocked:pattern",
        replacement_root="blocked:replacement",
        pattern_variables=("blocked:left", "blocked:right"),
        replacement_bindings={
            "blocked:replacement:left": "blocked:left",
            "blocked:replacement:right": "blocked:right",
        },
    ).root_id
    guarded = build_interaction(
        fixture["store"],
        fixture["interaction_protocol"],
        interaction_id="interaction:guarded",
        control_root=fixture["controls"][0],
        event_root=fixture["event"],
        target_root=fixture["targets"][0],
        precondition_roots=(blocked,),
        action_root=fixture["activate_actions"][0],
        subject_root=fixture["roots"]["subject"],
        policy_root=fixture["policy_root"],
        authorization_action_root=fixture["authorization_protocol"].actions["edit"],
        authorization_object_root=fixture["roots"]["object"],
        lifecycle_root="interaction-test:released",
    ).root_id
    admitted = build_interaction(
        fixture["store"],
        fixture["interaction_protocol"],
        interaction_id="interaction:admitted-precondition",
        control_root=fixture["controls"][1],
        event_root=fixture["event"],
        target_root=fixture["targets"][1],
        precondition_roots=(fixture["activate"],),
        action_root=fixture["activate_actions"][1],
        subject_root=fixture["roots"]["subject"],
        policy_root=fixture["policy_root"],
        authorization_action_root=fixture["authorization_protocol"].actions["edit"],
        authorization_object_root=fixture["roots"]["object"],
        lifecycle_root="interaction-test:released",
    ).root_id
    broker = InteractionProjectionBroker()
    handle = broker.mint(
        fixture["store"].snapshot(),
        session_root=fixture["session_root"],
        subject_root=fixture["roots"]["subject"],
        view_root=fixture["roots"]["object"],
    )
    broker.issue(
        handle,
        fixture["store"].snapshot(),
        fixture["interaction_protocol"],
        (fixture["controls"][0],),
        (guarded,),
        rule_protocol=fixture["rule_protocol"],
        transaction_protocol=fixture["transaction_protocol"],
    )
    before = fixture["store"].read(fixture["targets"][0])
    with pytest.raises(NoMatch):
        execute_interaction(
            fixture["store"],
            fixture["interaction_protocol"],
            fixture["transaction_protocol"],
            fixture["rule_protocol"],
            fixture["authorization_protocol"],
            fixture["broker"],
            fixture["context"],
            broker,
            handle,
            interaction_root=guarded,
            control_root=fixture["controls"][0],
            event_root=fixture["event"],
            expected_revision=fixture["store"].revision,
        )
    assert fixture["store"].read(fixture["targets"][0]) == before

    broker.issue(
        handle,
        fixture["store"].snapshot(),
        fixture["interaction_protocol"],
        (fixture["controls"][1],),
        (admitted,),
        rule_protocol=fixture["rule_protocol"],
        transaction_protocol=fixture["transaction_protocol"],
    )
    admitted_before = fixture["store"].read(fixture["targets"][1])
    execute_interaction(
        fixture["store"],
        fixture["interaction_protocol"],
        fixture["transaction_protocol"],
        fixture["rule_protocol"],
        fixture["authorization_protocol"],
        fixture["broker"],
        fixture["context"],
        broker,
        handle,
        interaction_root=admitted,
        control_root=fixture["controls"][1],
        event_root=fixture["event"],
        expected_revision=fixture["store"].revision,
    )
    assert fixture["store"].read(fixture["targets"][1]).link0 == (
        admitted_before.link1
    )


def test_declared_input_cannot_be_ignored_by_action_rule():
    fixture = _build_fixture()
    interaction = build_interaction(
        fixture["store"],
        fixture["interaction_protocol"],
        interaction_id="interaction:unbound-input",
        control_root=fixture["controls"][2],
        event_root=fixture["event"],
        target_root=fixture["targets"][2],
        input_roots=(fixture["targets"][0],),
        action_root=fixture["activate_actions"][2],
        subject_root=fixture["roots"]["subject"],
        policy_root=fixture["policy_root"],
        authorization_action_root=fixture["authorization_protocol"].actions["edit"],
        authorization_object_root=fixture["roots"]["object"],
        lifecycle_root="interaction-test:released",
    ).root_id
    projection = InteractionProjectionBroker()
    handle = projection.mint(
        fixture["store"].snapshot(),
        session_root=fixture["session_root"],
        subject_root=fixture["roots"]["subject"],
        view_root=fixture["roots"]["object"],
    )
    before = fixture["store"].read(fixture["targets"][2])
    with pytest.raises(InvalidCell, match="input"):
        projection.issue(
            handle,
            fixture["store"].snapshot(),
            fixture["interaction_protocol"],
            (fixture["controls"][2],),
            (interaction,),
            rule_protocol=fixture["rule_protocol"],
            transaction_protocol=fixture["transaction_protocol"],
        )
    assert fixture["store"].read(fixture["targets"][2]) == before


def test_dead_duplicate_and_unprojected_controls_fail_closed():
    fixture = _build_fixture()
    snapshot = fixture["store"].snapshot()
    projected = project_control_interactions(
        snapshot,
        fixture["interaction_protocol"],
        fixture["controls"],
        fixture["interactions"],
    )
    assert dict(projected) == dict(zip(
        fixture["controls"], fixture["interactions"]
    ))

    with pytest.raises(InvalidCell, match="exactly one"):
        project_control_interactions(
            snapshot,
            fixture["interaction_protocol"],
            (*fixture["controls"], "dead-control"),
            fixture["interactions"],
        )

    duplicate = build_interaction(
        fixture["store"],
        fixture["interaction_protocol"],
        interaction_id="interaction:duplicate",
        control_root=fixture["controls"][0],
        event_root=fixture["event"],
        target_root=fixture["targets"][0],
        action_root=fixture["activate_actions"][0],
        subject_root=fixture["roots"]["subject"],
        policy_root=fixture["policy_root"],
        authorization_action_root=fixture["authorization_protocol"].actions["edit"],
        authorization_object_root=fixture["roots"]["object"],
        lifecycle_root="interaction-test:released",
    ).root_id
    with pytest.raises(InvalidCell, match="exactly one"):
        project_control_interactions(
            fixture["store"].snapshot(),
            fixture["interaction_protocol"],
            fixture["controls"],
            (*fixture["interactions"], duplicate),
        )

    with pytest.raises(PermissionError, match="not admitted"):
        restricted_broker = InteractionProjectionBroker()
        restricted_handle = restricted_broker.mint(
            fixture["store"].snapshot(),
            session_root=fixture["session_root"],
            subject_root=fixture["roots"]["subject"],
            view_root=fixture["roots"]["object"],
        )
        restricted_broker.issue(
            restricted_handle,
            fixture["store"].snapshot(),
            fixture["interaction_protocol"],
            fixture["controls"][1:],
            fixture["interactions"][1:],
            rule_protocol=fixture["rule_protocol"],
            transaction_protocol=fixture["transaction_protocol"],
        )
        execute_interaction(
            fixture["store"],
            fixture["interaction_protocol"],
            fixture["transaction_protocol"],
            fixture["rule_protocol"],
            fixture["authorization_protocol"],
            fixture["broker"],
            fixture["context"],
            restricted_broker,
            restricted_handle,
            interaction_root=fixture["interactions"][0],
            control_root=fixture["controls"][0],
            event_root=fixture["event"],
            expected_revision=fixture["store"].revision,
        )


def test_stale_wrong_control_event_and_subject_do_not_mutate():
    fixture = _build_fixture()
    target = fixture["targets"][0]
    before = fixture["store"].read(target)
    stale = fixture["store"].revision
    fixture["store"].commit(
        stale, create=(_terminal("concurrent", "commit"),)
    )
    with pytest.raises(Conflict):
        execute_interaction(
            fixture["store"],
            fixture["interaction_protocol"],
            fixture["transaction_protocol"],
            fixture["rule_protocol"],
            fixture["authorization_protocol"],
            fixture["broker"],
            fixture["context"],
            fixture["projection_broker"],
            fixture["projection_handle"],
            interaction_root=fixture["interactions"][0],
            control_root=fixture["controls"][0],
            event_root=fixture["event"],
            expected_revision=stale,
        )
    assert fixture["store"].read(target) == before

    fixture["projection_broker"].issue(
        fixture["projection_handle"],
        fixture["store"].snapshot(),
        fixture["interaction_protocol"],
        fixture["controls"],
        fixture["interactions"],
        rule_protocol=fixture["rule_protocol"],
        transaction_protocol=fixture["transaction_protocol"],
    )
    for field, wrong in (("control_root", fixture["controls"][1]),
                         ("event_root", "interaction-test:released")):
        arguments = {
            "interaction_root": fixture["interactions"][0],
            "control_root": fixture["controls"][0],
            "event_root": fixture["event"],
            "expected_revision": fixture["store"].revision,
        }
        arguments[field] = wrong
        with pytest.raises(PermissionError):
            execute_interaction(
                fixture["store"],
                fixture["interaction_protocol"],
                fixture["transaction_protocol"],
                fixture["rule_protocol"],
                fixture["authorization_protocol"],
                fixture["broker"],
                fixture["context"],
                fixture["projection_broker"],
                fixture["projection_handle"],
                **arguments,
            )
        assert fixture["store"].read(target) == before

    forged_subject = "interaction-test:forged-subject"
    fixture["store"].commit(
        fixture["store"].revision,
        create=(_terminal(forged_subject, "forged"),),
    )
    forged = build_interaction(
        fixture["store"],
        fixture["interaction_protocol"],
        interaction_id="interaction:forged",
        control_root=fixture["controls"][0],
        event_root=fixture["event"],
        target_root=target,
        action_root=fixture["activate_actions"][0],
        subject_root=forged_subject,
        policy_root=fixture["policy_root"],
        authorization_action_root=fixture["authorization_protocol"].actions["edit"],
        authorization_object_root=fixture["roots"]["object"],
        lifecycle_root="interaction-test:released",
    ).root_id
    with pytest.raises(PermissionError, match="subject"):
        fixture["projection_broker"].issue(
            fixture["projection_handle"],
            fixture["store"].snapshot(),
            fixture["interaction_protocol"],
            (fixture["controls"][0],),
            (forged,),
            rule_protocol=fixture["rule_protocol"],
            transaction_protocol=fixture["transaction_protocol"],
        )
    assert fixture["store"].read(target) == before


def test_projection_lease_is_unforgeable_revision_scoped_and_revocable():
    fixture = _build_fixture()
    handle = fixture["projection_handle"]
    with pytest.raises(TypeError):
        pickle.dumps(handle)

    with pytest.raises(InteractionProjectionDenied, match="unknown"):
        fixture["projection_broker"].resolve(
            object(),
            fixture["store"].snapshot(),
            expected_revision=fixture["store"].revision,
            control_root=fixture["controls"][0],
            interaction_root=fixture["interactions"][0],
        )

    fixture["projection_broker"].revoke(handle)
    with pytest.raises(InteractionProjectionDenied, match="revoked"):
        fixture["projection_broker"].resolve(
            handle,
            fixture["store"].snapshot(),
            expected_revision=fixture["store"].revision,
            control_root=fixture["controls"][0],
            interaction_root=fixture["interactions"][0],
        )


def test_projection_lease_reports_expiry_before_execution():
    fixture = _build_fixture()
    lease = fixture["projection_broker"].issue(
        fixture["projection_handle"],
        fixture["store"].snapshot(),
        fixture["interaction_protocol"],
        fixture["controls"],
        fixture["interactions"],
        rule_protocol=fixture["rule_protocol"],
        transaction_protocol=fixture["transaction_protocol"],
        lifetime_seconds=60.0,
        now=100.0,
    )
    target = fixture["targets"][0]
    before = fixture["store"].read(target)
    with pytest.raises(InteractionProjectionExpired, match="expired"):
        fixture["projection_broker"].resolve(
            fixture["projection_handle"],
            fixture["store"].snapshot(),
            expected_revision=lease.revision,
            control_root=fixture["controls"][0],
            interaction_root=fixture["interactions"][0],
            now=lease.expires_at,
        )
    assert fixture["store"].read(target) == before


def test_projection_issue_verifies_protocol_once_for_the_exact_snapshot(
    monkeypatch,
):
    fixture = _build_fixture()
    calls = 0
    original = interaction_runtime.project_interaction_protocol

    def counted(snapshot, root_id, *, budget=256):
        nonlocal calls
        calls += 1
        return original(snapshot, root_id, budget=budget)

    monkeypatch.setattr(
        interaction_runtime,
        "project_interaction_protocol",
        counted,
    )
    fixture["projection_broker"].issue(
        fixture["projection_handle"],
        fixture["store"].snapshot(),
        fixture["interaction_protocol"],
        fixture["controls"],
        fixture["interactions"],
        rule_protocol=fixture["rule_protocol"],
        transaction_protocol=fixture["transaction_protocol"],
    )
    assert calls == 1


def test_projection_issue_fails_closed_when_protocol_authority_drifted():
    fixture = _build_fixture()
    store = fixture["store"]
    control_role = fixture["interaction_protocol"].role("control")
    original = store.read(control_role)
    store.commit(
        store.revision,
        replace=(
            Cell(
                original.id,
                original.link0,
                original.link1,
                b"forged-control",
            ),
        ),
    )
    with pytest.raises(
        InvalidCell,
        match="vocabulary is incomplete or extended",
    ):
        fixture["projection_broker"].issue(
            fixture["projection_handle"],
            store.snapshot(),
            fixture["interaction_protocol"],
            fixture["controls"],
            fixture["interactions"],
            rule_protocol=fixture["rule_protocol"],
            transaction_protocol=fixture["transaction_protocol"],
        )


def test_released_interaction_digest_rejects_behavior_drift(monkeypatch):
    fixture = _build_fixture()
    evidence_root = "interaction-test:release-evidence"
    fixture["store"].commit(
        fixture["store"].revision,
        create=(_terminal(evidence_root, "independent interaction court"),),
    )
    released = build_interaction(
        fixture["store"],
        fixture["interaction_protocol"],
        interaction_id="interaction:released",
        control_root=fixture["controls"][0],
        event_root=fixture["event"],
        target_root=fixture["targets"][0],
        action_root=fixture["activate_actions"][0],
        subject_root=fixture["roots"]["subject"],
        policy_root=fixture["policy_root"],
        authorization_action_root=fixture["authorization_protocol"].actions["edit"],
        authorization_object_root=fixture["roots"]["object"],
        release_policy_root=fixture["policy_root"],
        release_authorization_action_root=(
            fixture["authorization_protocol"].actions["publish"]
        ),
        release_authorization_object_root=fixture["roots"]["release_object"],
        version="1.0.0",
        evidence_roots=(evidence_root,),
    ).root_id
    release_broker = fixture["release_broker"]
    handle = release_broker.mint_from_review(
        released,
        fixture["roots"]["subject"],
        (evidence_root,),
    )
    with pytest.raises(TypeError):
        pickle.dumps(handle)
    with pytest.raises(PermissionError, match="authenticated identity"):
        release_interaction(
            fixture["store"],
            fixture["interaction_protocol"],
            fixture["transaction_protocol"],
            fixture["rule_protocol"],
            release_broker,
            handle,
            released,
            reviewer_root=fixture["roots"]["principal"],
            authorization_protocol=fixture["authorization_protocol"],
            authentication_broker=fixture["broker"],
            authentication_context=fixture["context"],
        )
    original_commit = CellStore.commit
    conflict_injected = False

    def conflict_once(self, expected_revision, **kwargs):
        nonlocal conflict_injected
        if self is fixture["store"] and not conflict_injected:
            conflict_injected = True
            raise Conflict("synthetic release conflict")
        return original_commit(self, expected_revision, **kwargs)

    monkeypatch.setattr(CellStore, "commit", conflict_once)
    with pytest.raises(Conflict, match="synthetic release conflict"):
        release_interaction(
            fixture["store"],
            fixture["interaction_protocol"],
            fixture["transaction_protocol"],
            fixture["rule_protocol"],
            release_broker,
            handle,
            released,
            reviewer_root=fixture["roots"]["subject"],
            authorization_protocol=fixture["authorization_protocol"],
            authentication_broker=fixture["broker"],
            authentication_context=fixture["context"],
        )
    monkeypatch.setattr(CellStore, "commit", original_commit)

    before_release = fixture["store"].revision
    released_revision = release_interaction(
        fixture["store"],
        fixture["interaction_protocol"],
        fixture["transaction_protocol"],
        fixture["rule_protocol"],
        release_broker,
        handle,
        released,
        reviewer_root=fixture["roots"]["subject"],
        authorization_protocol=fixture["authorization_protocol"],
        authentication_broker=fixture["broker"],
        authentication_context=fixture["context"],
    )
    assert released_revision == before_release + 1
    prior = fixture["store"].at(before_release)
    prior_projection = next(
        member for member in read_relation(prior, released, budget=64)
        if member.role_id == fixture["interaction_protocol"].role("lifecycle")
    )
    assert prior_projection.participant_id == (
        fixture["interaction_protocol"].state("draft")
    )
    released_projection = verify_released_interaction(
        fixture["store"].snapshot(),
        fixture["interaction_protocol"],
        fixture["transaction_protocol"],
        fixture["rule_protocol"],
        released,
        release_broker=release_broker,
    )
    assert released_projection.reviewer_root == fixture["roots"]["subject"]
    assert fixture["store"].read(released_projection.digest_root).atom
    with pytest.raises(PermissionError, match="already used"):
        release_broker.consume(
            handle,
            released,
            fixture["roots"]["subject"],
            (evidence_root,),
        )
    fixture["projection_broker"].issue(
        fixture["projection_handle"],
        fixture["store"].snapshot(),
        fixture["interaction_protocol"],
        (fixture["controls"][0],),
        (released,),
        rule_protocol=fixture["rule_protocol"],
        transaction_protocol=fixture["transaction_protocol"],
        require_released=True,
    )

    action_member = next(
        member for member in read_relation(
            fixture["store"].snapshot(), released, budget=64
        )
        if member.role_id == fixture["interaction_protocol"].role("action")
    )
    rewire_incidence(
        fixture["store"], action_member.incidence_id, fixture["retain_actions"][0]
    )
    with pytest.raises(InvalidCell, match="digest"):
        fixture["projection_broker"].issue(
            fixture["projection_handle"],
            fixture["store"].snapshot(),
            fixture["interaction_protocol"],
            (fixture["controls"][0],),
            (released,),
            rule_protocol=fixture["rule_protocol"],
            transaction_protocol=fixture["transaction_protocol"],
            require_released=True,
        )

    tampered = interaction_runtime.read_interaction(
        fixture["store"].snapshot(),
        fixture["interaction_protocol"],
        released,
    )
    forged_digest = interaction_runtime._interaction_content_digest(
        fixture["store"].snapshot(),
        fixture["interaction_protocol"],
        fixture["transaction_protocol"],
        fixture["rule_protocol"],
        tampered,
    )
    digest_cell = fixture["store"].read(tampered.digest_root)
    fixture["store"].commit(
        fixture["store"].revision,
        replace=(Cell(
            digest_cell.id,
            digest_cell.link0,
            digest_cell.link1,
            forged_digest,
        ),),
    )
    with pytest.raises(InvalidCell, match="signature"):
        fixture["projection_broker"].issue(
            fixture["projection_handle"],
            fixture["store"].snapshot(),
            fixture["interaction_protocol"],
            (fixture["controls"][0],),
            (released,),
            rule_protocol=fixture["rule_protocol"],
            transaction_protocol=fixture["transaction_protocol"],
            require_released=True,
        )


def test_release_digest_tracks_definition_not_mutable_target_data():
    fixture = _build_fixture()
    evidence_root = "interaction-test:boundary-evidence"
    fixture["store"].commit(
        fixture["store"].revision,
        create=(_terminal(evidence_root, "review evidence"),),
    )
    released = build_interaction(
        fixture["store"],
        fixture["interaction_protocol"],
        interaction_id="interaction:boundary",
        control_root=fixture["controls"][0],
        event_root=fixture["event"],
        target_root=fixture["targets"][0],
        action_root=fixture["activate_actions"][0],
        subject_root=fixture["roots"]["subject"],
        policy_root=fixture["policy_root"],
        authorization_action_root=fixture["authorization_protocol"].actions["edit"],
        authorization_object_root=fixture["roots"]["object"],
        release_policy_root=fixture["policy_root"],
        release_authorization_action_root=(
            fixture["authorization_protocol"].actions["publish"]
        ),
        release_authorization_object_root=fixture["roots"]["release_object"],
        version="1.0.0",
        evidence_roots=(evidence_root,),
    ).root_id
    release_broker = fixture["release_broker"]
    release_interaction(
        fixture["store"],
        fixture["interaction_protocol"],
        fixture["transaction_protocol"],
        fixture["rule_protocol"],
        release_broker,
        release_broker.mint_from_review(
            released, fixture["roots"]["subject"], (evidence_root,)
        ),
        released,
        reviewer_root=fixture["roots"]["subject"],
        authorization_protocol=fixture["authorization_protocol"],
        authentication_broker=fixture["broker"],
        authentication_context=fixture["context"],
    )

    target = fixture["store"].read(fixture["targets"][0])
    mutable_value = fixture["store"].read(target.link1)
    fixture["store"].commit(
        fixture["store"].revision,
        replace=(Cell(
            mutable_value.id,
            mutable_value.link0,
            mutable_value.link1,
            b"user-edited runtime data",
        ),),
    )
    verify_released_interaction(
        fixture["store"].snapshot(),
        fixture["interaction_protocol"],
        fixture["transaction_protocol"],
        fixture["rule_protocol"],
        released,
        release_broker=release_broker,
    )

    evidence = fixture["store"].read(evidence_root)
    fixture["store"].commit(
        fixture["store"].revision,
        replace=(Cell(
            evidence.id,
            evidence.link0,
            evidence.link1,
            b"altered evidence",
        ),),
    )
    with pytest.raises(InvalidCell, match="digest"):
        verify_released_interaction(
            fixture["store"].snapshot(),
            fixture["interaction_protocol"],
            fixture["transaction_protocol"],
            fixture["rule_protocol"],
            released,
            release_broker=release_broker,
        )


def test_release_required_projection_handle_cannot_be_downgraded():
    fixture = _build_fixture()
    strict_broker = InteractionProjectionBroker(fixture["release_broker"])
    strict_handle = strict_broker.mint(
        fixture["store"].snapshot(),
        session_root=fixture["session_root"],
        subject_root=fixture["roots"]["subject"],
        view_root=fixture["roots"]["object"],
        require_released=True,
    )
    with pytest.raises(InvalidCell, match="not released"):
        strict_broker.issue(
            strict_handle,
            fixture["store"].snapshot(),
            fixture["interaction_protocol"],
            fixture["controls"],
            fixture["interactions"],
            rule_protocol=fixture["rule_protocol"],
            transaction_protocol=fixture["transaction_protocol"],
            require_released=False,
        )
