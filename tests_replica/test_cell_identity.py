"""Forcing court for signed, live relationship authority."""
import time

import pytest

import nodelang.cell_identity as cell_identity_module
from nodelang.cell_authorization import (
    AuthenticationBroker,
    AuthorizationDenied,
    AuthorizationRequest,
    PolicyReleaseBroker,
    bootstrap_authorization_protocol,
    build_authorization_policy,
    build_authorization_rule,
    release_authorization_policy,
    require_authorization,
)
from nodelang.cell_identity import (
    RelationshipAuthorityBroker,
    RelationshipAuthorityDenied,
    active_membership_roots,
    bootstrap_identity_protocol,
    grant_authority_relationship,
    prepare_authority_relationship_grant,
    prepare_authority_relationship_revocation,
    read_authority_relationship,
    record_authority_relationship_revocation,
    relationship_principal_resolver,
    restore_relationship_authority_history,
    revise_authority_relationship_evidence,
    revoke_authority_relationship,
    verify_authority_relationship,
    verify_relationship_authority_snapshot,
)
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.cell_protocols import read_relation
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


@pytest.fixture()
def graph_authority():
    store = CellStore()
    authorization = bootstrap_authorization_protocol(
        store, prefix="test:authorization"
    )
    identity = bootstrap_identity_protocol(store, prefix="test:identity")
    roots = {
        "admin": b"Administrator",
        "alice": b"Alice",
        "bob": b"Bob",
        "tenant-a": b"Tenant A",
        "tenant-b": b"Tenant B",
        "architects": b"Architects",
        "reviewers": b"Reviewers",
        "delegated-editor": b"Delegated editor authority",
        "document-a": b"Document A",
        "document-b": b"Document B",
        "assurance": b"Strong authentication",
        "evidence-a": b"Evidence A",
        "evidence-b": b"Evidence B",
    }
    store.commit(store.revision, create=tuple(
        Cell(root, NULL_CELL_ID, NULL_CELL_ID, atom)
        for root, atom in roots.items()
    ))
    relationship_broker = RelationshipAuthorityBroker(("admin",))
    return store, authorization, identity, relationship_broker


def _grant(
    store, protocol, broker, relationship_id, source, target, *,
    kind="membership", tenant="tenant-a", scope=None, actions=(),
    expires_at=None, now=None, evidence_roots=(),
):
    handle = broker.mint_from_trusted_administrator("admin")
    return grant_authority_relationship(
        store,
        protocol,
        broker,
        handle,
        relationship_id=relationship_id,
        source_root=source,
        target_root=target,
        kind=kind,
        tenant_root=tenant,
        administrator_root="admin",
        scope_root=scope,
        action_roots=actions,
        expires_at=expires_at,
        evidence_roots=evidence_roots,
        now=now,
    )


def _release_policy(store, protocol, rules):
    policy = build_authorization_policy(
        store,
        protocol,
        rules,
        policy_id="test:policy",
        version="1.0.0",
    )
    release_broker = PolicyReleaseBroker()
    handle = release_broker.mint_from_trusted_administrator(policy, "admin")
    release_authorization_policy(
        store,
        protocol,
        policy,
        release_broker,
        handle,
        administrator_root="admin",
    )
    return policy


def _context(broker, subject="alice", tenant="tenant-a"):
    return broker.mint_authenticated_context(
        subject,
        tenant_root=tenant,
        assurance_root="assurance",
        lifetime_seconds=120,
    )


def _request(protocol, action, resource, *, lineage=(), now=None):
    return AuthorizationRequest(
        action_root=protocol.actions[action],
        object_root=resource,
        resource_lineage_roots=tuple(dict.fromkeys((resource, *lineage))),
        now=now,
    )


def test_membership_is_one_signed_relation_shape_and_resolves_transitively(
    graph_authority,
):
    store, _, identity, broker = graph_authority
    tenant_membership = _grant(
        store, identity, broker, "membership:alice:tenant", "alice", "tenant-a"
    )
    group_membership = _grant(
        store, identity, broker, "membership:alice:architects", "alice", "architects"
    )
    nested_membership = _grant(
        store, identity, broker, "membership:architects:reviewers",
        "architects", "reviewers",
    )

    assert active_membership_roots(
        store.snapshot(), identity, broker, "alice", "tenant-a"
    ) == ("architects", "reviewers", "tenant-a")
    for relationship_root in (
        tenant_membership, group_membership, nested_membership
    ):
        relationship = verify_authority_relationship(
            store.snapshot(), identity, broker, relationship_root
        )
        assert relationship.kind_root == identity.kinds["membership"]
        assert relationship.state_root == identity.states["active"]


def test_signed_relationship_can_be_prepared_for_one_caller_owned_commit(
    graph_authority,
):
    store, _, identity, broker = graph_authority
    snapshot = store.snapshot()
    pending = Cell("pending:document", NULL_CELL_ID, NULL_CELL_ID, b"pending")
    prepared = prepare_authority_relationship_grant(
        snapshot,
        identity,
        broker,
        broker.mint_from_trusted_administrator("admin"),
        relationship_id="audience:pending-document",
        source_root=pending.id,
        target_root="reviewers",
        kind="audience-binding",
        tenant_root="tenant-a",
        administrator_root="admin",
        evidence_roots=(pending.id,),
        pending_roots=(pending.id,),
    )
    assert store.snapshot() == snapshot
    from nodelang.cell_protocols import prepare_append_relation_member
    patch = prepare_append_relation_member(
        snapshot,
        identity.root_id,
        identity.role("relationship-member"),
        prepared.root_id,
        budget=100_000,
    )
    store.commit(
        snapshot.revision,
        create=(pending, *prepared.cells, *patch.create),
        replace=patch.replace,
    )
    broker.record_generation(prepared.root_id, prepared.generation)
    assert verify_authority_relationship(
        store.snapshot(), identity, broker, prepared.root_id
    ).source_root == pending.id


def test_group_membership_drives_authorization_and_revocation_is_immediate(
    graph_authority,
):
    store, authorization, identity, relationship_broker = graph_authority
    _grant(
        store, identity, relationship_broker,
        "membership:alice:tenant", "alice", "tenant-a",
    )
    group_membership = _grant(
        store, identity, relationship_broker,
        "membership:alice:architects", "alice", "architects",
    )
    rule = build_authorization_rule(
        store,
        authorization,
        rule_id="rule:architects:read",
        effect="permit",
        principal_root="architects",
        object_root="document-a",
        action_root=authorization.actions["read"],
        tenant_root="tenant-a",
        assurance_root="assurance",
    )
    policy = _release_policy(store, authorization, (rule,))
    authentication = AuthenticationBroker()
    authentication.bind_graph_resolver(
        relationship_principal_resolver(identity, relationship_broker)
    )
    context = _context(authentication)

    assert require_authorization(
        store.snapshot(), authorization, policy, authentication, context,
        _request(authorization, "read", "document-a"),
    ).allowed

    handle = relationship_broker.mint_from_trusted_administrator("admin")
    revoke_authority_relationship(
        store,
        identity,
        relationship_broker,
        handle,
        group_membership,
        administrator_root="admin",
        reason="project access removed",
    )
    with pytest.raises(AuthorizationDenied, match="default-deny"):
        require_authorization(
            store.snapshot(), authorization, policy, authentication, context,
            _request(authorization, "read", "document-a"),
		)


def test_prepared_revocation_mutates_only_inside_its_exact_atomic_commit(
    graph_authority,
):
    store, _authorization, identity, relationship_broker = graph_authority
    relationship = _grant(
        store,
        identity,
        relationship_broker,
        "membership:alice:architects",
        "alice",
        "architects",
    )
    before = store.revision
    patch = prepare_authority_relationship_revocation(
        store.snapshot(),
        identity,
        relationship_broker,
        relationship_broker.mint_from_trusted_administrator("admin"),
        relationship,
        administrator_root="admin",
        reason="project access removed",
    )
    assert store.revision == before
    assert verify_authority_relationship(
        store.snapshot(), identity, relationship_broker, relationship
    ).state_root == identity.states["active"]

    revision = store.commit(
        patch.expected_revision,
        create=patch.create,
        replace=patch.replace,
    )
    with pytest.raises(RelationshipAuthorityDenied, match="generation"):
        verify_authority_relationship(
            store.snapshot(), identity, relationship_broker, relationship
        )
    record_authority_relationship_revocation(
        relationship_broker, patch, revision
    )
    with pytest.raises(RelationshipAuthorityDenied, match="revoked"):
        verify_authority_relationship(
            store.snapshot(), identity, relationship_broker, relationship
        )
    with pytest.raises(RelationshipAuthorityDenied, match="revision"):
        record_authority_relationship_revocation(
            relationship_broker, patch, revision + 1
        )


def test_verified_authority_snapshot_is_revision_bound_and_revocation_wins(
    graph_authority,
):
    store, authorization, identity, relationship_broker = graph_authority
    _grant(
        store, identity, relationship_broker,
        "membership:alice:tenant", "alice", "tenant-a",
    )
    group_membership = _grant(
        store, identity, relationship_broker,
        "membership:alice:architects", "alice", "architects",
    )
    rule = build_authorization_rule(
        store,
        authorization,
        rule_id="rule:architects:snapshot-read",
        effect="permit",
        principal_root="architects",
        object_root="document-a",
        action_root=authorization.actions["read"],
        tenant_root="tenant-a",
        assurance_root="assurance",
    )
    policy = _release_policy(store, authorization, (rule,))
    authentication = AuthenticationBroker()
    authentication.bind_graph_resolver(
        relationship_principal_resolver(identity, relationship_broker)
    )
    context = _context(authentication)
    evaluated_at = time.time()
    before = store.snapshot()
    verified = verify_relationship_authority_snapshot(
        before,
        identity,
        relationship_broker,
        now=evaluated_at,
    )
    request = _request(
        authorization, "read", "document-a", now=evaluated_at
    )

    assert require_authorization(
        before,
        authorization,
        policy,
        authentication,
        context,
        request,
        resolver_state=verified,
    ).allowed

    handle = relationship_broker.mint_from_trusted_administrator("admin")
    revoke_authority_relationship(
        store,
        identity,
        relationship_broker,
        handle,
        group_membership,
        administrator_root="admin",
        reason="snapshot court revocation",
        now=evaluated_at,
    )
    after = store.snapshot()
    with pytest.raises(RelationshipAuthorityDenied, match="revision is stale"):
        require_authorization(
            after,
            authorization,
            policy,
            authentication,
            context,
            request,
            resolver_state=verified,
        )
    after_verified = verify_relationship_authority_snapshot(
        after,
        identity,
        relationship_broker,
        now=evaluated_at,
    )
    with pytest.raises(AuthorizationDenied, match="default-deny"):
        require_authorization(
            after,
            authorization,
            policy,
            authentication,
            context,
            request,
            resolver_state=after_verified,
        )


def test_authority_snapshot_reads_the_protocol_registry_once(
    graph_authority,
    monkeypatch,
):
    store, _, identity, broker = graph_authority
    for index in range(3):
        _grant(
            store,
            identity,
            broker,
            f"membership:alice:group:{index}",
            "alice",
            "architects",
        )

    protocol_reads = 0
    original_read_relation = cell_identity_module.read_relation

    def counted_read_relation(snapshot, relation_id, *, budget):
        nonlocal protocol_reads
        if relation_id == identity.root_id:
            protocol_reads += 1
        return original_read_relation(snapshot, relation_id, budget=budget)

    monkeypatch.setattr(
        cell_identity_module,
        "read_relation",
        counted_read_relation,
    )

    verified = verify_relationship_authority_snapshot(
        store.snapshot(),
        identity,
        broker,
    )

    assert len(verified.relationships) == 3
    assert protocol_reads == 1


def test_direct_relationship_verification_rejects_signed_unregistered_material(
    graph_authority,
):
    store, _, identity, broker = graph_authority
    snapshot = store.snapshot()
    prepared = prepare_authority_relationship_grant(
        snapshot,
        identity,
        broker,
        broker.mint_from_trusted_administrator("admin"),
        relationship_id="membership:unregistered",
        source_root="alice",
        target_root="architects",
        kind="membership",
        tenant_root="tenant-a",
        administrator_root="admin",
    )
    store.commit(snapshot.revision, create=prepared.cells)
    broker.record_generation(prepared.root_id, prepared.generation)

    with pytest.raises(InvalidCell, match="not protocol-registered"):
        verify_authority_relationship(
            store.snapshot(),
            identity,
            broker,
            prepared.root_id,
        )


def test_relationship_evidence_revision_is_signed_monotonic_and_history_safe(
    graph_authority,
):
    store, _, identity, broker = graph_authority
    relationship_root = _grant(
        store,
        identity,
        broker,
        "membership:alice:tenant:evidence",
        "alice",
        "tenant-a",
        evidence_roots=("evidence-a",),
    )
    before = store.snapshot()
    handle = broker.mint_from_trusted_administrator("admin")
    revise_authority_relationship_evidence(
        store,
        identity,
        broker,
        handle,
        relationship_root,
        administrator_root="admin",
        evidence_roots=("evidence-b",),
        reason="court evidence superseded",
    )

    revised = verify_authority_relationship(
        store.snapshot(), identity, broker, relationship_root
    )
    assert revised.evidence_roots == ("evidence-b",)
    assert store.read(revised.generation_root).atom == b"2"
    with pytest.raises(RelationshipAuthorityDenied, match="stale or unknown"):
        verify_authority_relationship(
            before, identity, broker, relationship_root
        )

    with pytest.raises(InvalidCell, match="preserve evidence cardinality"):
        revise_authority_relationship_evidence(
            store,
            identity,
            broker,
            broker.mint_from_trusted_administrator("admin"),
            relationship_root,
            administrator_root="admin",
            evidence_roots=("evidence-a", "evidence-b"),
            reason="invalid cardinality",
        )

    revoke_authority_relationship(
        store,
        identity,
        broker,
        broker.mint_from_trusted_administrator("admin"),
        relationship_root,
        administrator_root="admin",
        reason="court revoke after evidence revision",
    )
    assert store.read(revised.generation_root).atom == b"3"
    with pytest.raises(RelationshipAuthorityDenied, match="revoked"):
        verify_authority_relationship(
            store.snapshot(), identity, broker, relationship_root
        )

def test_tenant_membership_is_required_on_every_request_and_is_cross_tenant_safe(
    graph_authority,
):
    store, authorization, identity, relationship_broker = graph_authority
    membership = _grant(
        store, identity, relationship_broker,
        "membership:alice:tenant", "alice", "tenant-a",
    )
    rule = build_authorization_rule(
        store,
        authorization,
        rule_id="rule:alice:read",
        effect="permit",
        principal_root="alice",
        object_root="document-a",
        action_root=authorization.actions["read"],
        tenant_root="tenant-a",
        assurance_root="assurance",
    )
    policy = _release_policy(store, authorization, (rule,))
    authentication = AuthenticationBroker()
    authentication.bind_graph_resolver(
        relationship_principal_resolver(identity, relationship_broker)
    )
    context = _context(authentication)
    cross_tenant = _context(authentication, tenant="tenant-b")

    assert require_authorization(
        store.snapshot(), authorization, policy, authentication, context,
        _request(authorization, "read", "document-a"),
    ).allowed
    with pytest.raises(AuthorizationDenied, match="tenant membership"):
        require_authorization(
            store.snapshot(), authorization, policy, authentication,
            cross_tenant, _request(authorization, "read", "document-a"),
        )

    handle = relationship_broker.mint_from_trusted_administrator("admin")
    revoke_authority_relationship(
        store,
        identity,
        relationship_broker,
        handle,
        membership,
        administrator_root="admin",
        reason="user disabled",
    )
    with pytest.raises(AuthorizationDenied, match="tenant membership"):
        require_authorization(
            store.snapshot(), authorization, policy, authentication, context,
            _request(authorization, "read", "document-a"),
        )


def test_delegation_is_exact_scope_action_tenant_expiry_and_revocable(
    graph_authority,
):
    store, authorization, identity, relationship_broker = graph_authority
    _grant(
        store, identity, relationship_broker,
        "membership:alice:tenant", "alice", "tenant-a",
    )
    delegation = _grant(
        store,
        identity,
        relationship_broker,
        "delegation:editor:alice:document-a",
        "delegated-editor",
        "alice",
        kind="delegation",
        scope="document-a",
        actions=(authorization.actions["edit"],),
        expires_at=time.time() + 60,
    )
    rule = build_authorization_rule(
        store,
        authorization,
        rule_id="rule:delegated-editor:edit",
        effect="permit",
        principal_root="delegated-editor",
        object_root="document-a",
        action_root=authorization.actions["edit"],
        tenant_root="tenant-a",
        assurance_root="assurance",
    )
    policy = _release_policy(store, authorization, (rule,))
    authentication = AuthenticationBroker()
    authentication.bind_graph_resolver(
        relationship_principal_resolver(identity, relationship_broker)
    )
    context = _context(authentication)

    assert require_authorization(
        store.snapshot(), authorization, policy, authentication, context,
        _request(authorization, "edit", "document-a"),
    ).allowed
    for request in (
        _request(authorization, "read", "document-a"),
        _request(authorization, "edit", "document-b"),
    ):
        with pytest.raises(AuthorizationDenied):
            require_authorization(
                store.snapshot(), authorization, policy, authentication,
                context, request,
            )

    handle = relationship_broker.mint_from_trusted_administrator("admin")
    revoke_authority_relationship(
        store,
        identity,
        relationship_broker,
        handle,
        delegation,
        administrator_root="admin",
        reason="delegated task completed",
    )
    with pytest.raises(AuthorizationDenied):
        require_authorization(
            store.snapshot(), authorization, policy, authentication, context,
            _request(authorization, "edit", "document-a"),
        )


def test_graph_text_cannot_forge_or_replay_relationship_authority(
    graph_authority,
):
    store, _, identity, broker = graph_authority
    relationship_root = _grant(
        store, identity, broker,
        "membership:alice:architects", "alice", "architects",
    )
    active_snapshot = store.snapshot()
    active = read_authority_relationship(
        active_snapshot, identity, relationship_root
    )
    handle = broker.mint_from_trusted_administrator("admin")
    revoke_authority_relationship(
        store,
        identity,
        broker,
        handle,
        relationship_root,
        administrator_root="admin",
        reason="removed",
    )

    replay_ids = (
        active.state_incidence,
        active.changed_by_incidence,
        active.changed_at_root,
        active.generation_root,
        active.reason_root,
        active.digest_root,
        active.signature_root,
    )
    snapshot = store.snapshot()
    store.commit(
        snapshot.revision,
        replace=tuple(active_snapshot.cells[root] for root in replay_ids),
    )
    with pytest.raises(RelationshipAuthorityDenied, match="generation"):
        verify_authority_relationship(
            store.snapshot(), identity, broker, relationship_root
        )


def test_rewiring_a_signed_membership_invalidates_its_authority(
    graph_authority,
):
    store, _, identity, broker = graph_authority
    relationship_root = _grant(
        store, identity, broker,
        "membership:alice:architects", "alice", "architects",
    )
    snapshot = store.snapshot()
    target = next(
        member for member in read_relation(snapshot, relationship_root)
        if member.role_id == identity.roles["target"]
    )
    incidence = snapshot.cells[target.incidence_id]
    store.commit(snapshot.revision, replace=(Cell(
        incidence.id, incidence.link0, "reviewers", incidence.atom
    ),))
    with pytest.raises(RelationshipAuthorityDenied, match="digest"):
        verify_authority_relationship(
            store.snapshot(), identity, broker, relationship_root
        )


def test_tenant_admin_can_sign_only_the_exact_policy_authorized_relationship(
    graph_authority,
):
    store, authorization, identity, relationship_broker = graph_authority
    _grant(
        store,
        identity,
        relationship_broker,
        "membership:alice:tenant",
        "alice",
        "tenant-a",
    )
    rule = build_authorization_rule(
        store,
        authorization,
        rule_id="rule:alice:manage-tenant-a",
        effect="permit",
        principal_root="alice",
        object_root="tenant-a",
        action_root=authorization.actions["manage-policy"],
        tenant_root="tenant-a",
        assurance_root="assurance",
    )
    policy = _release_policy(store, authorization, (rule,))
    authentication = AuthenticationBroker()
    authentication.bind_graph_resolver(
        relationship_principal_resolver(identity, relationship_broker)
    )
    context = _context(authentication)
    with pytest.raises(RelationshipAuthorityDenied, match="exact"):
        relationship_broker.mint_from_authorized_relationship_grant(
            store.snapshot(),
            authorization,
            policy,
            authentication,
            context,
            _request(authorization, "manage-policy", "tenant-a"),
            administrator_root="alice",
            relationship_id="membership:bob:tenant-a",
            source_root="bob",
            target_root="tenant-a",
            kind="membership",
            tenant_root="tenant-a",
            reason="under-scoped request",
        )
    request = _request(
        authorization, "manage-policy", "tenant-a", lineage=("bob",)
    )
    reason = "tenant administrator admitted Bob"
    handle = relationship_broker.mint_from_authorized_relationship_grant(
        store.snapshot(),
        authorization,
        policy,
        authentication,
        context,
        request,
        administrator_root="alice",
        relationship_id="membership:bob:tenant-a",
        source_root="bob",
        target_root="tenant-a",
        kind="membership",
        tenant_root="tenant-a",
        reason=reason,
    )
    with pytest.raises(RelationshipAuthorityDenied, match="another mutation"):
        grant_authority_relationship(
            store,
            identity,
            relationship_broker,
            handle,
            relationship_id="membership:bob:tenant-a",
            source_root="bob",
            target_root="tenant-b",
            kind="membership",
            tenant_root="tenant-b",
            administrator_root="alice",
            reason=reason,
        )
    relationship = grant_authority_relationship(
        store,
        identity,
        relationship_broker,
        handle,
        relationship_id="membership:bob:tenant-a",
        source_root="bob",
        target_root="tenant-a",
        kind="membership",
        tenant_root="tenant-a",
        administrator_root="alice",
        reason=reason,
    )
    projection = verify_authority_relationship(
        store.snapshot(), identity, relationship_broker, relationship
    )
    assert projection.changed_by_root == "alice"
    assert projection.tenant_root == "tenant-a"
    with pytest.raises(RelationshipAuthorityDenied, match="already used"):
        grant_authority_relationship(
            store,
            identity,
            relationship_broker,
            handle,
            relationship_id="membership:bob:architects",
            source_root="bob",
            target_root="architects",
            kind="membership",
            tenant_root="tenant-a",
            administrator_root="alice",
            reason=reason,
        )
    revoke_reason = "tenant administrator removed Bob"
    revoke_request = _request(
        authorization,
        "manage-policy",
        "tenant-a",
        lineage=("bob", relationship),
    )
    revoke_handle = (
        relationship_broker.mint_from_authorized_relationship_revoke(
            store.snapshot(),
            identity,
            authorization,
            policy,
            authentication,
            context,
            revoke_request,
            administrator_root="alice",
            relationship_root=relationship,
            reason=revoke_reason,
        )
    )
    with pytest.raises(RelationshipAuthorityDenied, match="another mutation"):
        revoke_authority_relationship(
            store,
            identity,
            relationship_broker,
            revoke_handle,
            relationship,
            administrator_root="alice",
            reason="different reason",
        )
    revoke_authority_relationship(
        store,
        identity,
        relationship_broker,
        revoke_handle,
        relationship,
        administrator_root="alice",
        reason=revoke_reason,
    )
    with pytest.raises(RelationshipAuthorityDenied, match="revoked"):
        verify_authority_relationship(
            store.snapshot(), identity, relationship_broker, relationship
        )


def test_default_deny_cannot_mint_tenant_relationship_signing_authority(
    graph_authority,
):
    store, authorization, identity, relationship_broker = graph_authority
    _grant(
        store,
        identity,
        relationship_broker,
        "membership:alice:tenant",
        "alice",
        "tenant-a",
    )
    unrelated = build_authorization_rule(
        store,
        authorization,
        rule_id="rule:alice:read-document",
        effect="permit",
        principal_root="alice",
        object_root="document-a",
        action_root=authorization.actions["read"],
        tenant_root="tenant-a",
        assurance_root="assurance",
    )
    policy = _release_policy(store, authorization, (unrelated,))
    authentication = AuthenticationBroker()
    authentication.bind_graph_resolver(
        relationship_principal_resolver(identity, relationship_broker)
    )
    with pytest.raises(AuthorizationDenied, match="default-deny"):
        relationship_broker.mint_from_authorized_relationship_grant(
            store.snapshot(),
            authorization,
            policy,
            authentication,
            _context(authentication),
            _request(authorization, "manage-policy", "tenant-a"),
            administrator_root="alice",
            relationship_id="membership:bob:tenant-a",
            source_root="bob",
            target_root="tenant-a",
            kind="membership",
            tenant_root="tenant-a",
            reason="unauthorized grant",
        )


def _durable_identity_store(path, provider):
    store = CellStore(path)
    identity = bootstrap_identity_protocol(store, prefix="durable:identity")
    store.commit(store.revision, create=tuple(
        Cell(root, NULL_CELL_ID, NULL_CELL_ID, atom)
        for root, atom in {
            "admin": b"Administrator",
            "alice": b"Alice",
            "tenant-a": b"Tenant A",
            "architects": b"Architects",
        }.items()
    ))
    broker = RelationshipAuthorityBroker(
        ("admin",), key_provider=provider, key_id="durable-authority"
    )
    return store, identity, broker


def test_signed_revocation_and_key_rotation_survive_store_restart(tmp_path):
    path = tmp_path / "authority.sqlite3"
    provider = MemorySigningKeyProvider("durable-authority", b"1" * 32)
    store, identity, broker = _durable_identity_store(path, provider)
    relationship_root = _grant(
        store, identity, broker,
        "membership:alice:architects", "alice", "architects",
    )
    provider.rotate("durable-authority", b"2" * 32)
    handle = broker.mint_from_trusted_administrator("admin")
    revoke_authority_relationship(
        store,
        identity,
        broker,
        handle,
        relationship_root,
        administrator_root="admin",
        reason="access removed",
    )
    assert store.revisions() == tuple(range(store.revision + 1))
    store.close()

    reopened = CellStore(path)
    restarted_broker = RelationshipAuthorityBroker(
        ("admin",), key_provider=provider, key_id="durable-authority"
    )
    restored = restore_relationship_authority_history(
        reopened, identity, restarted_broker
    )
    assert restored[relationship_root] == 2
    relationship = verify_authority_relationship(
        reopened.snapshot(),
        identity,
        restarted_broker,
        relationship_root,
        require_active=False,
    )
    assert relationship.state_root == identity.states["revoked"]
    assert reopened.read(relationship.key_version_root).atom == b"2"
    with pytest.raises(RelationshipAuthorityDenied, match="revoked"):
        verify_authority_relationship(
            reopened.snapshot(), identity, restarted_broker, relationship_root
        )
    reopened.close()


def test_restart_history_rejects_replayed_active_generation(tmp_path):
    path = tmp_path / "replay.sqlite3"
    provider = MemorySigningKeyProvider("durable-authority", b"r" * 32)
    store, identity, broker = _durable_identity_store(path, provider)
    relationship_root = _grant(
        store, identity, broker,
        "membership:alice:architects", "alice", "architects",
    )
    active_snapshot = store.snapshot()
    active = read_authority_relationship(active_snapshot, identity, relationship_root)
    handle = broker.mint_from_trusted_administrator("admin")
    revoke_authority_relationship(
        store,
        identity,
        broker,
        handle,
        relationship_root,
        administrator_root="admin",
        reason="access removed",
    )
    replay_ids = (
        active.state_incidence,
        active.changed_by_incidence,
        active.changed_at_root,
        active.generation_root,
        active.reason_root,
        active.digest_root,
        active.signature_root,
        active.key_reference_root,
        active.key_version_root,
    )
    snapshot = store.snapshot()
    store.commit(
        snapshot.revision,
        replace=tuple(active_snapshot.cells[root] for root in replay_ids),
    )
    store.close()

    reopened = CellStore(path)
    restarted_broker = RelationshipAuthorityBroker(
        ("admin",), key_provider=provider, key_id="durable-authority"
    )
    restored = restore_relationship_authority_history(
        reopened, identity, restarted_broker
    )
    assert restored[relationship_root] == 2
    with pytest.raises(RelationshipAuthorityDenied, match="generation"):
        verify_authority_relationship(
            reopened.snapshot(), identity, restarted_broker, relationship_root
        )
    reopened.close()


def test_restart_history_does_not_rebuild_unrelated_revisions(
    tmp_path, monkeypatch
):
    path = tmp_path / "bounded-history.sqlite3"
    provider = MemorySigningKeyProvider("durable-authority", b"h" * 32)
    store, identity, broker = _durable_identity_store(path, provider)
    relationship_root = _grant(
        store, identity, broker,
        "membership:alice:architects", "alice", "architects",
    )
    authority_revision = store.revision
    for index in range(200):
        store.commit(store.revision, create=(Cell(
            "unrelated:ui:%03d" % index,
            NULL_CELL_ID,
            NULL_CELL_ID,
            b"presentation-only",
        ),))
    store.close()

    reopened = CellStore(path)
    original_at = reopened.at
    reconstructed = []

    def counted_at(revision):
        reconstructed.append(revision)
        return original_at(revision)

    monkeypatch.setattr(reopened, "at", counted_at)
    restarted_broker = RelationshipAuthorityBroker(
        ("admin",), key_provider=provider, key_id="durable-authority"
    )
    restored = restore_relationship_authority_history(
        reopened, identity, restarted_broker
    )

    assert restored[relationship_root] == 1
    assert len(reconstructed) <= 5
    assert all(revision <= authority_revision for revision in reconstructed)
    reopened.close()


def test_restart_with_wrong_key_cannot_admit_relationship_authority(tmp_path):
    path = tmp_path / "wrong-key.sqlite3"
    provider = MemorySigningKeyProvider("durable-authority", b"a" * 32)
    store, identity, broker = _durable_identity_store(path, provider)
    _grant(
        store, identity, broker,
        "membership:alice:architects", "alice", "architects",
    )
    store.close()

    reopened = CellStore(path)
    wrong_provider = MemorySigningKeyProvider("durable-authority", b"z" * 32)
    wrong_broker = RelationshipAuthorityBroker(
        ("admin",), key_provider=wrong_provider, key_id="durable-authority"
    )
    with pytest.raises(RelationshipAuthorityDenied, match="no trusted signature"):
        restore_relationship_authority_history(reopened, identity, wrong_broker)
    reopened.close()


def test_signing_secret_is_never_written_to_cell_database(tmp_path):
    path = tmp_path / "no-secret.sqlite3"
    secret = b"ARCHHUB-RAW-SIGNING-KEY-NEVER-IN-CELLS"
    provider = MemorySigningKeyProvider("durable-authority", secret)
    store, identity, broker = _durable_identity_store(path, provider)
    _grant(
        store, identity, broker,
        "membership:alice:architects", "alice", "architects",
    )
    store.close()
    assert secret not in path.read_bytes()
