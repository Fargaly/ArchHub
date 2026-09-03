"""Forcing court for universal graph-held authorization."""
import inspect
import pickle
import time

import pytest

from nodelang.cell_authorization import (
    AuthenticationBroker,
    AuthorizationDenied,
    AuthorizationRequest,
    PolicyReleaseBroker,
    authorize_node_request,
    authorize_node_requests,
    bootstrap_authorization_protocol,
    build_authorization_policy,
    build_authorization_rule,
    release_authorization_policy,
    require_authorization,
)
from nodelang.cell_protocols import compose_relation_cells, read_relation
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


@pytest.fixture()
def authority():
    store = CellStore()
    protocol = bootstrap_authorization_protocol(store)
    roots = {
        "founder": b"Founder",
        "member": b"Member",
        "architect-role": b"Architect role",
        "workspace": b"Workspace",
        "node-a": b"Node A",
        "node-b": b"Node B",
        "port-properties": b"Properties port",
        "purpose-design": b"Design",
        "class-internal": b"Internal",
        "audience-firm": b"Firm",
        "state-wip": b"WIP",
        "state-pending": b"Pending",
        "assurance-strong": b"Strong authentication",
        "assurance-weak": b"Weak authentication",
    }
    store.commit(store.revision, create=tuple(
        Cell(root, NULL_CELL_ID, NULL_CELL_ID, atom)
        for root, atom in roots.items()
    ))
    return store, protocol


def _context(store, broker, *, subject="member", principals=()):
    return broker.mint_authenticated_context(
        subject, principal_roots=principals,
        tenant_root="workspace", assurance_root="assurance-strong",
        lifetime_seconds=120,
    )


def _request(protocol, **changes):
    values = dict(
        action_root=protocol.actions["edit"],
        object_root="node-a",
        resource_lineage_roots=("workspace",),
        interface_root="port-properties",
        purpose_root="purpose-design",
        classification_root="class-internal",
        audience_root="audience-firm",
        lifecycle_state_root="state-wip",
        operational_state_root="state-pending",
        invocation_count=0,
    )
    values.update(changes)
    return AuthorizationRequest(**values)


def _released_policy(store, protocol, rule_roots, *, policy_id="policy:test"):
    policy = build_authorization_policy(
        store, protocol, rule_roots,
        policy_id=policy_id, version="1.0.0",
    )
    broker = PolicyReleaseBroker()
    handle = broker.mint_from_trusted_administrator(
        policy, "founder", lifetime_seconds=60
    )
    release_authorization_policy(
        store, protocol, policy, broker, handle, administrator_root="founder"
    )
    return policy


def test_empty_released_policy_is_default_deny(authority):
    store, protocol = authority
    policy = _released_policy(store, protocol, ())
    identities = AuthenticationBroker()
    context = _context(store, identities)
    decision = authorize_node_request(
        store.snapshot(), protocol, policy, identities, context,
        _request(protocol),
    )
    assert decision.allowed is False
    assert decision.reason == "default-deny"
    with pytest.raises(AuthorizationDenied):
        require_authorization(
            store.snapshot(), protocol, policy, identities, context,
            _request(protocol),
        )


def test_batch_authorization_resolves_one_graph_revision_once(authority):
    store, protocol = authority
    rules = tuple(
        build_authorization_rule(
            store,
            protocol,
            rule_id="rule:batch:%s" % object_root,
            effect="permit",
            principal_root="architect-role",
            object_root=object_root,
            action_root=protocol.actions["read"],
        )
        for object_root in ("node-a", "node-b")
    )
    policy = _released_policy(store, protocol, rules)

    class BatchResolver:
        def __init__(self):
            self.batch_calls = 0
            self.single_calls = 0

        def __call__(self, snapshot, identity, request, now):
            self.single_calls += 1
            return ("architect-role",)

        def resolve_batch(self, snapshot, identity, requests, now):
            self.batch_calls += 1
            return tuple(("architect-role",) for _request in requests)

    resolver = BatchResolver()
    identities = AuthenticationBroker()
    identities.bind_graph_resolver(resolver)
    context = _context(store, identities)
    requests = tuple(
        _request(
            protocol,
            action_root=protocol.actions["read"],
            object_root=object_root,
            interface_root=None,
            purpose_root=None,
            classification_root=None,
            audience_root=None,
            lifecycle_state_root=None,
            operational_state_root=None,
        )
        for object_root in ("node-a", "node-b")
    )
    decisions = authorize_node_requests(
        store.snapshot(), protocol, policy, identities, context, requests
    )
    assert [decision.object_root for decision in decisions] == ["node-a", "node-b"]
    assert all(decision.allowed for decision in decisions)
    assert resolver.batch_calls == 1
    assert resolver.single_calls == 0


def test_exact_subject_action_object_interface_and_attributes_are_required(authority):
    store, protocol = authority
    rule = build_authorization_rule(
        store, protocol, rule_id="rule:exact", effect="permit",
        principal_root="member", object_root="node-a",
        action_root=protocol.actions["edit"],
        interface_root="port-properties", purpose_root="purpose-design",
        tenant_root="workspace", assurance_root="assurance-strong",
        classification_root="class-internal",
        audience_root="audience-firm", lifecycle_state_root="state-wip",
        operational_state_root="state-pending",
    )
    policy = _released_policy(store, protocol, (rule,))
    identities = AuthenticationBroker()
    context = _context(store, identities)
    assert require_authorization(
        store.snapshot(), protocol, policy, identities, context,
        _request(protocol),
    ).allowed
    weak_context = identities.mint_authenticated_context(
        "member", tenant_root="workspace",
        assurance_root="assurance-weak", lifetime_seconds=120,
    )
    assert not authorize_node_request(
        store.snapshot(), protocol, policy, identities, weak_context,
        _request(protocol),
    ).allowed
    for changed in (
        {"object_root": "node-b", "resource_lineage_roots": ()},
        {"action_root": protocol.actions["execute"]},
        {"interface_root": None},
        {"audience_root": None},
        {"lifecycle_state_root": None},
    ):
        assert not authorize_node_request(
            store.snapshot(), protocol, policy, identities, context,
            _request(protocol, **changed),
        ).allowed


def test_relationship_principal_and_resource_lineage_are_authoritative(authority):
    store, protocol = authority
    rule = build_authorization_rule(
        store, protocol, rule_id="rule:role", effect="permit",
        principal_root="architect-role", object_root="workspace",
        action_root=protocol.actions["inspect"], tenant_root="workspace",
    )
    policy = _released_policy(store, protocol, (rule,))
    identities = AuthenticationBroker()
    member = _context(
        store, identities, principals=("architect-role",)
    )
    request = _request(
        protocol, action_root=protocol.actions["inspect"],
        object_root="node-b", resource_lineage_roots=("workspace",),
        interface_root=None, purpose_root=None, classification_root=None,
        audience_root=None, lifecycle_state_root=None,
        operational_state_root=None,
    )
    assert require_authorization(
        store.snapshot(), protocol, policy, identities, member, request
    ).allowed
    outsider = _context(store, identities)
    assert not authorize_node_request(
        store.snapshot(), protocol, policy, identities, outsider, request
    ).allowed


def test_subject_relation_condition_allows_only_the_owned_node(authority):
    store, protocol = authority
    owner_role = "role:owner"
    session_a = "session:a"
    session_b = "session:b"
    store.commit(store.revision, create=(
        Cell(owner_role, NULL_CELL_ID, NULL_CELL_ID, b"owner"),
        Cell("member-b", NULL_CELL_ID, NULL_CELL_ID, b"Member B"),
        *compose_relation_cells(
            ((owner_role, "member"),), relation_id=session_a
        ).cells,
        *compose_relation_cells(
            ((owner_role, "member-b"),), relation_id=session_b
        ).cells,
    ))
    rule = build_authorization_rule(
        store, protocol, rule_id="rule:owned-session", effect="permit",
        principal_root="architect-role", object_root="workspace",
        action_root=protocol.actions["inspect"], tenant_root="workspace",
        subject_relation_root=owner_role,
    )
    policy = _released_policy(store, protocol, (rule,))
    identities = AuthenticationBroker()
    member = _context(store, identities, principals=("architect-role",))

    def request(root):
        return _request(
            protocol, action_root=protocol.actions["inspect"],
            object_root=root, resource_lineage_roots=("workspace",),
            interface_root=None, purpose_root=None, classification_root=None,
            audience_root=None, lifecycle_state_root=None,
            operational_state_root=None,
        )

    assert require_authorization(
        store.snapshot(), protocol, policy, identities, member,
        request(session_a),
    ).allowed
    assert not authorize_node_request(
        store.snapshot(), protocol, policy, identities, member,
        request(session_b),
    ).allowed


def test_explicit_forbid_overrides_matching_permit(authority):
    store, protocol = authority
    permit = build_authorization_rule(
        store, protocol, rule_id="rule:permit", effect="permit",
        principal_root="member", object_root="workspace",
        action_root=protocol.actions["export"], tenant_root="workspace",
    )
    forbid = build_authorization_rule(
        store, protocol, rule_id="rule:forbid", effect="forbid",
        principal_root="member", object_root="node-a",
        action_root=protocol.actions["export"], tenant_root="workspace",
        classification_root="class-internal",
    )
    policy = _released_policy(store, protocol, (permit, forbid))
    identities = AuthenticationBroker()
    context = _context(store, identities)
    decision = authorize_node_request(
        store.snapshot(), protocol, policy, identities, context,
        _request(protocol, action_root=protocol.actions["export"]),
    )
    assert not decision.allowed
    assert decision.reason == "explicit-forbid"
    assert decision.determining_rule_roots == (forbid,)


def test_rule_expiry_and_invocation_budget_fail_closed(authority):
    store, protocol = authority
    rule = build_authorization_rule(
        store, protocol, rule_id="rule:bounded", effect="permit",
        principal_root="member", object_root="node-a",
        action_root=protocol.actions["edit"],
        expires_at=time.time() + 60, max_invocations=1,
    )
    policy = _released_policy(store, protocol, (rule,))
    identities = AuthenticationBroker()
    context = _context(store, identities)
    assert authorize_node_request(
        store.snapshot(), protocol, policy, identities, context,
        _request(
            protocol, interface_root=None, purpose_root=None,
            classification_root=None, audience_root=None,
            lifecycle_state_root=None, operational_state_root=None,
        ),
    ).allowed
    assert not authorize_node_request(
        store.snapshot(), protocol, policy, identities, context,
        _request(
            protocol, interface_root=None, purpose_root=None,
            classification_root=None, audience_root=None,
            lifecycle_state_root=None, operational_state_root=None,
            invocation_count=1,
        ),
    ).allowed


def test_policy_drift_and_forged_or_serialized_identity_are_rejected(authority):
    store, protocol = authority
    rule = build_authorization_rule(
        store, protocol, rule_id="rule:drift", effect="permit",
        principal_root="member", object_root="node-a",
        action_root=protocol.actions["read"],
    )
    policy = _released_policy(store, protocol, (rule,))
    identities = AuthenticationBroker()
    context = _context(store, identities)
    with pytest.raises(TypeError):
        pickle.dumps(context)
    with pytest.raises(TypeError):
        type(context)(object())

    rule_members = read_relation(store.snapshot(), rule)
    object_member = next(
        member for member in rule_members
        if member.role_id == protocol.roles["object"]
    )
    incidence = store.read(object_member.incidence_id)
    store.commit(store.revision, replace=(Cell(
        incidence.id, incidence.link0, "node-b", incidence.atom,
    ),))
    with pytest.raises(InvalidCell, match="drifted"):
        authorize_node_request(
            store.snapshot(), protocol, policy, identities, context,
            _request(
                protocol, action_root=protocol.actions["read"],
                interface_root=None, purpose_root=None,
                classification_root=None, audience_root=None,
                lifecycle_state_root=None, operational_state_root=None,
            ),
        )


def test_authorization_floor_contains_no_product_domain_dispatch():
    source = inspect.getsource(authorize_node_request).lower()
    for forbidden in (
        '"composer"', '"payment"', '"database"', '"geometry"',
        '"bim"', '"cockpit"',
    ):
        assert forbidden not in source
