"""Adversarial courts for the governed universal-Cell Agent Body substrate."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import nodelang.cell_agent_body as agent_body_module
from nodelang.cell_agent_body import (
    append_context_entry,
    begin_agent_session,
    bootstrap_agent_body_protocol,
    close_agent_session,
    compose_agent_body,
    list_agent_body_roots,
    list_agent_session_roots,
    open_agent_body_protocol,
    read_agent_body,
    read_agent_session,
    read_context_entry,
)
from nodelang.cell_authorization import (
    AuthenticationBroker,
    AuthorizationDenied,
    AuthorizationRequest,
    PolicyReleaseBroker,
    bootstrap_authorization_protocol,
    build_authorization_policy,
    build_authorization_rule,
    release_authorization_policy,
)
from nodelang.cell_protocols import (
    compose_relation_cells,
    read_relation,
    rewire_incidence,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


ROOTS = {
    "identity": b"Agent owner",
    "other-identity": b"Other identity",
    "owner-role": b"owner",
    "context": b"Authorized context",
    "other-context": b"Outside context",
    "provenance": b"Verified source",
    "trust": b"Trusted",
    "sensitivity": b"Internal",
    "audience": b"Owner only",
    "other-audience": b"Other audience",
    "lifecycle": b"WIP",
    "purpose": b"Operate ArchHub",
    "context-interface": b"Read context",
    "registry-interface": b"Edit context registry",
    "close-reason": b"Work complete",
    "model-binding": b"Unverified model",
}


def _request(
    world,
    action: str,
    object_root: str,
    *,
    lineage=(),
    interface=None,
    purpose=None,
    classification=None,
    audience="audience",
):
    return AuthorizationRequest(
        action_root=world["authorization"].actions[action],
        object_root=object_root,
        resource_lineage_roots=tuple(lineage),
        interface_root=interface,
        purpose_root=purpose,
        classification_root=classification,
        audience_root=audience,
        lifecycle_state_root="lifecycle",
        operational_state_root=world["agent"].state("active"),
    )


def _released_policy(store, authorization, rules):
    policy = build_authorization_policy(
        store,
        authorization,
        rules,
        policy_id="agent-policy",
        version="1.0.0",
    )
    releases = PolicyReleaseBroker()
    release_authorization_policy(
        store,
        authorization,
        policy,
        releases,
        releases.mint_from_trusted_administrator(policy, "identity"),
        administrator_root="identity",
    )
    return policy


def _world(database=None):
    store = CellStore(database)
    agent = bootstrap_agent_body_protocol(store, prefix="test:agent-body")
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
    store.commit(
        store.revision,
        create=(
            *compose_relation_cells(
                (("owner-role", "identity"),), relation_id="view"
            ).cells,
            *compose_relation_cells(
                (("owner-role", "identity"),), relation_id="scope"
            ).cells,
        ),
    )
    actions = authorization.actions
    rule_specs = (
        ("create", "identity", None, None, None, None),
        ("inspect", "view", None, None, None, "owner-role"),
        ("traverse", "scope", None, None, None, "owner-role"),
        (
            "read",
            "context",
            "context-interface",
            "purpose",
            "sensitivity",
            None,
        ),
        (
            "edit",
            "scope",
            "registry-interface",
            "purpose",
            "sensitivity",
            None,
        ),
        ("execute", "scope", None, None, None, "owner-role"),
    )
    rules = tuple(
        build_authorization_rule(
            store,
            authorization,
            rule_id="agent-rule:%s:%s" % (action, object_root),
            effect="permit",
            principal_root="identity",
            object_root=object_root,
            action_root=actions[action],
            interface_root=interface,
            purpose_root=purpose,
            classification_root=classification,
            audience_root="audience",
            lifecycle_state_root="lifecycle",
            operational_state_root=agent.state("active"),
            subject_relation_root=subject_relation,
        )
        for (
            action,
            object_root,
            interface,
            purpose,
            classification,
            subject_relation,
        ) in rule_specs
    )
    policy = _released_policy(store, authorization, rules)
    broker = AuthenticationBroker()
    context = broker.mint_authenticated_context(
        "identity",
        tenant_root=None,
        assurance_root="trust",
        lifetime_seconds=120,
    )
    return {
        "store": store,
        "agent": agent,
        "authorization": authorization,
        "policy": policy,
        "rules": rules,
        "broker": broker,
        "context": context,
    }


def _body(world, *, model_binding_root=None, resolver_state=None):
    return compose_agent_body(
        world["store"],
        world["agent"],
        world["authorization"],
        world["broker"],
        world["context"],
        _request(world, "create", "identity"),
        body_id="agent-body",
        identity_root="identity",
        authority_policy_root=world["policy"],
        authority_action_roots=tuple(
            world["authorization"].actions[name]
            for name in (
                "create", "inspect", "traverse", "read", "edit", "execute"
            )
        ),
        authority_rule_roots=world["rules"],
        lifecycle_root="lifecycle",
        state_root=world["agent"].state("active"),
        visibility_root="audience",
        model_binding_root=model_binding_root,
        resolver_state=resolver_state,
    )


def _session(world, *, authentication_context=None, focus_root=None):
    protocol = world["agent"]
    return begin_agent_session(
        world["store"],
        protocol,
        world["authorization"],
        world["broker"],
        world["context"] if authentication_context is None else authentication_context,
        _request(world, "inspect", "view"),
        _request(world, "traverse", "scope"),
        session_id="agent-session",
        body_root="agent-body",
        subject_root="identity",
        owner_role_root="owner-role",
        view_session_root="view",
        scope_root="scope",
        focus_root=(protocol.state("unbound") if focus_root is None else focus_root),
        assignment_root=protocol.state("unbound"),
    )


def test_agent_session_receipt_accepts_authorization_resolver_evidence_scale():
    world = _world()
    _body(world)
    resolver_roots = tuple(
        "resolver-relationship:%04d" % index for index in range(4096)
    )
    world["store"].commit(
        world["store"].revision,
        create=tuple(
            Cell(root, NULL_CELL_ID, NULL_CELL_ID, root.encode("utf-8"))
            for root in ("resolver-protocol", *resolver_roots)
        ),
    )

    class Resolver:
        def __call__(self, snapshot, identity, request, current):
            return ()

        def resolve_batch_with_state(
            self, snapshot, identity, requests, current, state
        ):
            return tuple(() for _request in requests)

    world["broker"].bind_graph_resolver(Resolver())
    snapshot = world["store"].snapshot()
    resolver_state = SimpleNamespace(
        protocol_root="resolver-protocol",
        revision=snapshot.revision,
        evaluated_at=1.0,
        active_relationships=tuple(
            SimpleNamespace(root_id=root) for root in resolver_roots
        ),
    )

    session = begin_agent_session(
        world["store"],
        world["agent"],
        world["authorization"],
        world["broker"],
        world["context"],
        _request(world, "inspect", "view"),
        _request(world, "traverse", "scope"),
        session_id="agent-session",
        body_root="agent-body",
        subject_root="identity",
        owner_role_root="owner-role",
        view_session_root="view",
        scope_root="scope",
        focus_root=world["agent"].state("unbound"),
        assignment_root=world["agent"].state("unbound"),
        resolver_state=resolver_state,
    )

    receipt = agent_body_module._read_authorization_receipt(
        world["store"].snapshot(),
        world["agent"],
        world["authorization"],
        session.view_receipt_root,
    )
    assert len(receipt.resolver_evidence_roots) == 4096
    assert receipt.resolver_evidence_roots == resolver_roots


def _append_context(
    world,
    *,
    context_request=None,
    registry_request=None,
    idempotency_key="context-selection-1",
    trust_root="trust",
):
    return append_context_entry(
        world["store"],
        world["agent"],
        world["authorization"],
        world["broker"],
        world["context"],
        context_request
        or _request(
            world,
            "read",
            "context",
            lineage=("scope",),
            interface="context-interface",
            purpose="purpose",
            classification="sensitivity",
        ),
        registry_request
        or _request(
            world,
            "edit",
            "agent-session:context-registry",
            lineage=("scope",),
            interface="registry-interface",
            purpose="purpose",
            classification="sensitivity",
        ),
        session_root="agent-session",
        context_root="context",
        provenance_root="provenance",
        trust_root=trust_root,
        sensitivity_root="sensitivity",
        audience_root="audience",
        lifecycle_root="lifecycle",
        purpose_root="purpose",
        idempotency_key=idempotency_key,
    )


def _close(world, *, authentication_context=None, request=None):
    return close_agent_session(
        world["store"],
        world["agent"],
        world["authorization"],
        world["broker"],
        world["context"] if authentication_context is None else authentication_context,
        request
        or _request(
            world,
            "execute",
            "agent-session",
            lineage=("scope",),
        ),
        "agent-session",
        reason_root="close-reason",
    )


def test_body_session_context_and_close_are_authorized_durable_relations():
    world = _world()
    body = _body(world)
    assert body.identity_root == "identity"
    assert body.model_binding_root is None
    assert body.creation_receipt_root == "agent-body:creation-receipt"
    assert list_agent_body_roots(world["store"].snapshot(), world["agent"]) == (
        "agent-body",
    )

    session = _session(world)
    assert session.subject_root == body.identity_root
    assert session.model_binding_root is None
    assert session.focus_root == world["agent"].state("unbound")
    assert session.assignment_root == world["agent"].state("unbound")
    assert session.proposal_roots == ()
    assert session.view_receipt_root == "agent-session:view-receipt"
    assert session.scope_receipt_root == "agent-session:scope-receipt"
    observed_revision = world["store"].revision

    entry_root = _append_context(world)
    entry = read_context_entry(
        world["store"].snapshot(),
        world["agent"],
        world["authorization"],
        entry_root,
    )
    assert entry.root_id.startswith("agent-context:")
    assert entry.observed_revision == observed_revision
    assert entry.context_root == "context"
    assert entry.context_authorization_reason == "explicit-permit"
    assert entry.registry_authorization_reason == "explicit-permit"
    assert entry.context_receipt_root == entry_root + ":context-receipt"
    assert entry.registry_receipt_root == entry_root + ":registry-receipt"
    session = read_agent_session(
        world["store"].snapshot(),
        world["agent"],
        world["authorization"],
        "agent-session",
    )
    assert session.context_cursor == 1
    assert session.context_entry_roots == (entry_root,)

    revision = _close(world)
    closed = read_agent_session(
        world["store"].snapshot(),
        world["agent"],
        world["authorization"],
        "agent-session",
    )
    assert closed.state_root == world["agent"].state("closed")
    assert closed.close_action_root == world["authorization"].actions["execute"]
    assert closed.close_authorization_reason == "explicit-permit"
    assert closed.close_receipt_root == "agent-session:close-receipt"
    assert closed.close_reason_root == "close-reason"
    assert _close(world) == revision
    assert world["store"].revision == revision
    assert all(type(cell) is Cell for cell in world["store"].snapshot().cells.values())


def test_restart_preserves_registry_cursor_authority_and_closed_state(tmp_path: Path):
    database = tmp_path / "agent-body.sqlite3"
    world = _world(database)
    _body(world)
    _session(world)
    entry_root = _append_context(world)
    _close(world)
    revision = world["store"].revision
    world["store"].close()

    reopened = CellStore(database)
    protocol = open_agent_body_protocol(
        reopened.snapshot(), prefix="test:agent-body"
    )
    assert reopened.revision == revision
    assert list_agent_session_roots(reopened.snapshot(), protocol) == (
        "agent-session",
    )
    session = read_agent_session(
        reopened.snapshot(), protocol, world["authorization"], "agent-session"
    )
    assert session.context_entry_roots == (entry_root,)
    assert session.context_cursor == 1
    assert session.state_root == protocol.state("closed")
    reopened.close()


def test_forged_identity_and_mismatched_requests_fail_before_mutation():
    world = _world()
    _body(world)
    other_context = world["broker"].mint_authenticated_context(
        "other-identity",
        tenant_root=None,
        assurance_root="trust",
        lifetime_seconds=120,
    )
    revision = world["store"].revision
    with pytest.raises(AuthorizationDenied):
        _session(world, authentication_context=other_context)
    assert world["store"].revision == revision

    _session(world)
    revision = world["store"].revision
    bad_context = _request(
        world,
        "read",
        "context",
        lineage=(),
        interface="context-interface",
        purpose="purpose",
        classification="sensitivity",
    )
    with pytest.raises(InvalidCell, match="lineage"):
        _append_context(world, context_request=bad_context)
    bad_registry = _request(
        world,
        "edit",
        "agent-session:context-registry",
        lineage=("scope",),
        interface="registry-interface",
        purpose="purpose",
        classification="sensitivity",
        audience="other-audience",
    )
    with pytest.raises(InvalidCell, match="audience"):
        _append_context(world, registry_request=bad_registry)
    with pytest.raises(AuthorizationDenied):
        _close(world, authentication_context=object())
    assert world["store"].revision == revision
    assert read_agent_session(
        world["store"].snapshot(),
        world["agent"],
        world["authorization"],
        "agent-session",
    ).context_entry_roots == ()


def test_unreleased_cognition_focus_assignment_and_proposals_are_unavailable():
    world = _world()
    with pytest.raises(InvalidCell, match="model binding requires"):
        _body(world, model_binding_root="model-binding")
    assert list_agent_body_roots(world["store"].snapshot(), world["agent"]) == ()
    _body(world)
    revision = world["store"].revision
    with pytest.raises(InvalidCell, match="focus and assignment"):
        _session(world, focus_root="context")
    assert world["store"].revision == revision
    body_members = read_relation(
        world["store"].snapshot(), "agent-body", budget=100_000
    )
    model_incidence = next(
        member.incidence_id
        for member in body_members
        if member.role_id == world["agent"].role("body-model-binding")
    )
    rewire_incidence(world["store"], model_incidence, "model-binding")
    with pytest.raises(InvalidCell, match="model binding requires"):
        read_agent_body(
            world["store"].snapshot(),
            world["agent"],
            world["authorization"],
            "agent-body",
        )
    assert not hasattr(agent_body_module, "append_proposal_root")
    assert not hasattr(agent_body_module, "replace_agent_body_model_binding")


@pytest.mark.parametrize("role_name", ("session-focus", "session-assignment"))
def test_post_hoc_focus_or_assignment_rewire_fails_closed(role_name):
    world = _world()
    _body(world)
    _session(world)
    members = read_relation(
        world["store"].snapshot(), "agent-session", budget=100_000
    )
    incidence = next(
        member.incidence_id for member in members
        if member.role_id == world["agent"].role(role_name)
    )
    rewire_incidence(world["store"], incidence, "context")
    with pytest.raises(InvalidCell, match="focus and assignment"):
        read_agent_session(
            world["store"].snapshot(),
            world["agent"],
            world["authorization"],
            "agent-session",
        )


def test_policy_rule_and_incidence_drift_fail_closed():
    world = _world()
    _body(world)
    _session(world)
    _append_context(world)
    snapshot = world["store"].snapshot()
    body_members = read_relation(snapshot, "agent-body", budget=100_000)
    identity_incidence = next(
        member.incidence_id
        for member in body_members
        if member.role_id == world["agent"].role("body-identity")
    )
    rewire_incidence(world["store"], identity_incidence, "other-identity")
    with pytest.raises((InvalidCell, AuthorizationDenied)):
        read_agent_body(
            world["store"].snapshot(),
            world["agent"],
            world["authorization"],
            "agent-body",
        )

    world = _world()
    _body(world)
    receipt_members = read_relation(
        world["store"].snapshot(),
        "agent-body:creation-receipt",
        budget=256,
    )
    evaluated_root = next(
        member.participant_id
        for member in receipt_members
        if member.role_id == world["agent"].role("receipt-evaluated-at")
    )
    evaluated = world["store"].read(evaluated_root)
    world["store"].commit(
        world["store"].revision,
        replace=(Cell(
            evaluated.id,
            evaluated.link0,
            evaluated.link1,
            b"invalid-time",
        ),),
    )
    with pytest.raises(InvalidCell, match="time"):
        read_agent_body(
            world["store"].snapshot(),
            world["agent"],
            world["authorization"],
            "agent-body",
        )

    world = _world()
    _body(world)
    body_members = read_relation(
        world["store"].snapshot(), "agent-body", budget=100_000
    )
    visibility_incidence = next(
        member.incidence_id
        for member in body_members
        if member.role_id == world["agent"].role("body-visibility")
    )
    rewire_incidence(world["store"], visibility_incidence, "other-audience")
    with pytest.raises(AuthorizationDenied, match="audience"):
        read_agent_body(
            world["store"].snapshot(),
            world["agent"],
            world["authorization"],
            "agent-body",
        )


def test_context_registry_and_cursor_publish_in_one_commit():
    world = _world()
    _body(world)
    session = _session(world)
    before_revision = world["store"].revision
    before_snapshot = world["store"].snapshot()
    entry_root = _append_context(world)
    assert world["store"].revision == before_revision + 1
    assert before_snapshot.cells[session.context_cursor_root].atom == b"0"
    after = read_agent_session(
        world["store"].snapshot(),
        world["agent"],
        world["authorization"],
        "agent-session",
    )
    assert after.context_cursor == 1
    assert after.context_entry_roots == (entry_root,)

    revision = world["store"].revision
    assert _append_context(world) == entry_root
    assert world["store"].revision == revision
    with pytest.raises(InvalidCell, match="reused for other content"):
        _append_context(
            world,
            idempotency_key="context-selection-1",
            trust_root="other-audience",
        )


def test_agent_body_module_has_no_execution_or_effect_path():
    source = Path(agent_body_module.__file__).read_text(encoding="utf-8").lower()
    for forbidden in (
        "openai",
        "anthropic",
        "invoke(",
        "append_proposal_root",
        "replace_agent_body_model_binding",
        "from .core",
        "nodelang.core",
        "core.store",
    ):
        assert forbidden not in source


def test_commit_rechecks_live_authentication_context(monkeypatch):
    world = _world()
    revision = world["store"].revision
    evaluate = agent_body_module.evaluate_node_requests

    def revoke_after_evaluation(*args, **kwargs):
        result = evaluate(*args, **kwargs)
        world["broker"].revoke(world["context"])
        return result

    monkeypatch.setattr(
        agent_body_module,
        "evaluate_node_requests",
        revoke_after_evaluation,
    )
    with pytest.raises(AuthorizationDenied, match="unknown authenticated context"):
        _body(world)
    assert world["store"].revision == revision
    assert "agent-body" not in world["store"].snapshot().cells


def test_receipt_persists_sealed_resolver_evidence():
    world = _world()
    world["store"].commit(
        world["store"].revision,
        create=(
            Cell("resolver-protocol", NULL_CELL_ID, NULL_CELL_ID, b"resolver"),
            Cell("signed-relationship", NULL_CELL_ID, NULL_CELL_ID, b"signed"),
        ),
    )

    class Resolver:
        def __call__(self, snapshot, identity, request, current):
            return ()

        def resolve_batch_with_state(
            self, snapshot, identity, requests, current, state
        ):
            return tuple(() for _request in requests)

    world["broker"].bind_graph_resolver(Resolver())
    resolver_state = SimpleNamespace(
        protocol_root="resolver-protocol",
        revision=world["store"].revision,
        evaluated_at=0.0,
        active_relationships=(SimpleNamespace(root_id="signed-relationship"),),
    )
    body = _body(world, resolver_state=resolver_state)
    receipt = agent_body_module._read_authorization_receipt(
        world["store"].snapshot(),
        world["agent"],
        world["authorization"],
        body.creation_receipt_root,
    )
    assert receipt.resolver_protocol_root == "resolver-protocol"
    assert receipt.resolver_revision == resolver_state.revision
    assert receipt.resolver_evaluated_at == 0.0
    assert receipt.resolver_evidence_roots == ("signed-relationship",)


def test_context_limit_fails_before_mutation(monkeypatch):
    world = _world()
    _body(world)
    _session(world)
    revision = world["store"].revision
    monkeypatch.setattr(agent_body_module, "MAX_CONTEXT_ENTRIES", 0)
    with pytest.raises(InvalidCell, match="context entry limit"):
        _append_context(world)
    assert world["store"].revision == revision


def test_session_projection_has_one_aggregate_read_budget(monkeypatch):
    world = _world()
    _body(world)
    _session(world)
    _append_context(world)
    monkeypatch.setattr(agent_body_module, "MAX_SESSION_READ_WORK", 1)
    with pytest.raises(InvalidCell, match="aggregate read budget"):
        read_agent_session(
            world["store"].snapshot(),
            world["agent"],
            world["authorization"],
            "agent-session",
        )
