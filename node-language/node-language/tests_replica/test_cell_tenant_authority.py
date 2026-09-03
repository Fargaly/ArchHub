from __future__ import annotations

import hashlib
from types import MappingProxyType

import pytest

from nodelang.cell_attestations import (
    CourtAttestationBroker,
    CourtInvocation,
    CourtResult,
    bootstrap_attestation_protocol,
    build_court_definition,
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
from nodelang.cell_catalog import (
    build_catalog,
    bootstrap_assembly_protocol,
    compose_catalog_instance,
    read_catalog,
)
from nodelang.cell_identity import (
    RelationshipAuthorityBroker,
    active_membership_roots,
    bootstrap_identity_protocol,
    grant_authority_relationship,
    relationship_principal_resolver,
)
from nodelang.cell_lifecycle import (
    append_wip_graph_revision,
    graph_content_bytes,
    promote_revision,
    read_revision,
)
from nodelang.cell_reactions import register_reaction_instance
from nodelang.cell_standard_library import build_standard_library_v0
from nodelang.cell_tenant_authority import (
    PublishedTenantAdmissionVerifier,
    TenantAuthorityDenied,
    activate_published_tenant_roles,
    append_tenant_authority_revision,
    bootstrap_tenant_configuration_protocol,
    provision_tenant_identity,
    published_tenant_authority,
    select_published_tenant_revision,
    stage_tenant_authority,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


EXTERNAL_TENANT_ID = "cloud-db-company-0042"


def _cell(root: str, value: str) -> Cell:
    return Cell(root, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8"))


def _world():
    store = CellStore()
    assembly = bootstrap_assembly_protocol(store, prefix="test:assembly")
    library = build_standard_library_v0(
        store, assembly, prefix="test:standard-library"
    )
    authorization = bootstrap_authorization_protocol(
        store, prefix="test:authorization"
    )
    identity = bootstrap_identity_protocol(store, prefix="test:identity")
    tenant_protocol = bootstrap_tenant_configuration_protocol(
        store, prefix="test:tenant-configuration"
    )
    roots = {
        "founder": "test:subject:founder",
        "owner": "test:subject:owner",
        "admin": "test:subject:admin",
        "member": "test:subject:member",
        "forbidden_owner": "test:subject:forbidden-owner",
        "assurance": "test:assurance:aal2",
    }
    store.commit(
        store.revision,
        create=tuple(_cell(root, name) for name, root in roots.items()),
    )
    tenant_root, role_roots = provision_tenant_identity(
        store, external_tenant_id=EXTERNAL_TENANT_ID
    )
    owner_rule = build_authorization_rule(
        store,
        authorization,
        rule_id="test:rule:tenant-owner:manage",
        effect="permit",
        principal_root=role_roots["owner"],
        object_root=tenant_root,
        action_root=authorization.actions["manage-policy"],
        tenant_root=tenant_root,
        assurance_root=roots["assurance"],
    )
    admin_member_rule = build_authorization_rule(
        store,
        authorization,
        rule_id="test:rule:tenant-admin:assign-member",
        effect="permit",
        principal_root=role_roots["administrator"],
        object_root=role_roots["member"],
        action_root=authorization.actions["manage-policy"],
        tenant_root=tenant_root,
        assurance_root=roots["assurance"],
    )
    policy = build_authorization_policy(
        store,
        authorization,
        (owner_rule, admin_member_rule),
        policy_id="test:tenant-policy",
        version="1.0.0",
    )
    release_broker = PolicyReleaseBroker()
    release_handle = release_broker.mint_from_trusted_administrator(
        policy, roots["founder"]
    )
    release_authorization_policy(
        store,
        authorization,
        policy,
        release_broker,
        release_handle,
        administrator_root=roots["founder"],
    )
    relationship_broker = RelationshipAuthorityBroker((roots["founder"],))
    staged = stage_tenant_authority(
        store,
        tenant_protocol,
        assembly,
        library.lifecycle_protocol,
        authorization,
        external_tenant_id=EXTERNAL_TENANT_ID,
        catalogue_root=library.catalog_root,
        policy_root=policy,
        versioned_asset_definition_root=library.definition_roots[2],
        actor_root=roots["founder"],
    )
    return {
        "store": store,
        "assembly": assembly,
        "library": library,
        "authorization": authorization,
        "identity": identity,
        "tenant_protocol": tenant_protocol,
        "relationship_broker": relationship_broker,
        "roots": roots,
        "tenant_root": tenant_root,
        "role_roots": role_roots,
        "policy": policy,
        "staged": staged,
    }


def _promotion_court(
    world, *, prefix: str = "test:tenant-promotion-attestation"
):
    store = world["store"]
    protocol = bootstrap_attestation_protocol(
        store, prefix=prefix
    )
    court = build_court_definition(
        store,
        protocol,
        court_id=prefix + ":court",
        name="Tenant configuration",
        builder_id="test:tenant-configuration-runner",
        runner_version="1",
        policy_digest=hashlib.sha256(b"tenant configuration policy").hexdigest(),
        checks=("graph-digest", "target-state"),
    )

    def runner(invocation: CourtInvocation) -> CourtResult:
        checks = {
            "graph-digest": hashlib.sha256(
                invocation.subject_content
            ).hexdigest() == invocation.subject_digest,
            "target-state": invocation.external_parameters.get(
                "targetState"
            ) in world["library"].lifecycle_protocol.states.values(),
        }
        return CourtResult(
            all(checks.values()),
            MappingProxyType(checks),
            MappingProxyType({"scope": "tenant configuration"}),
        )

    broker = CourtAttestationBroker()
    broker.admit_court(store.snapshot(), protocol, court.root_id, runner)
    return protocol, court.root_id, broker


def _promote(world, court, source_root: str, target_state: str) -> str:
    store = world["store"]
    lifecycle = world["library"].lifecycle_protocol
    source = read_revision(store.snapshot(), lifecycle, source_root)
    protocol, court_root, broker = court
    parameters = {
        "asset": world["staged"].lifecycle_instance_root,
        "targetState": target_state,
    }
    evidence = broker.run(
        store,
        protocol,
        court_root,
        subject_name=source_root,
        subject_content=graph_content_bytes(
            store.snapshot(), source.content_root
        ),
        external_parameters=parameters,
    )
    receipt = broker.consume(
        store.snapshot(),
        protocol,
        evidence,
        purpose="promote:%s:%s" % (
            world["staged"].lifecycle_instance_root, target_state
        ),
        expected_court_root=court_root,
        expected_subject_name=source_root,
        expected_subject_digest=store.read(source.content_digest_root).atom.decode(
            "ascii"
        ),
        expected_parameters=parameters,
    )
    return promote_revision(
        store,
        world["assembly"],
        lifecycle,
        world["staged"].lifecycle_instance_root,
        target_state_root=target_state,
        source_revision_root=source_root,
        actor_root=world["roots"]["founder"],
        evidence_roots=(evidence,),
        evidence_receipts=(receipt,),
        attestation_broker=broker,
    )


def _publish_and_activate(world):
    court = _promotion_court(world)
    lifecycle = world["library"].lifecycle_protocol
    shared = _promote(
        world,
        court,
        world["staged"].wip_revision_root,
        lifecycle.states["shared"],
    )
    published = _promote(
        world, court, shared, lifecycle.states["published"]
    )
    select_published_tenant_revision(
        world["store"],
        world["tenant_protocol"],
        world["assembly"],
        lifecycle,
        world["identity"],
        world["relationship_broker"],
        tenant_root=world["tenant_root"],
        revision_root=published,
        actor_root=world["roots"]["founder"],
    )
    relationships = activate_published_tenant_roles(
        world["store"],
        world["tenant_protocol"],
        world["assembly"],
        lifecycle,
        world["authorization"],
        world["identity"],
        world["relationship_broker"],
        tenant_root=world["tenant_root"],
        owner_subject_root=world["roots"]["owner"],
        founder_administrator_root=world["roots"]["founder"],
    )
    return published, relationships


def test_tenant_is_inert_until_court_published_then_owner_wires_activate():
    world = _world()
    verifier = PublishedTenantAdmissionVerifier(
        world["tenant_protocol"],
        world["assembly"],
        world["library"].lifecycle_protocol,
        world["authorization"],
        world["identity"],
        world["relationship_broker"],
    )
    with pytest.raises(TenantAuthorityDenied, match="Published"):
        published_tenant_authority(
            world["store"].snapshot(),
            world["tenant_protocol"],
            world["assembly"],
            world["library"].lifecycle_protocol,
            world["authorization"],
            world["identity"],
            world["relationship_broker"],
            tenant_root=world["tenant_root"],
        )
    with pytest.raises(TenantAuthorityDenied, match="Published"):
        activate_published_tenant_roles(
            world["store"],
            world["tenant_protocol"],
            world["assembly"],
            world["library"].lifecycle_protocol,
            world["authorization"],
            world["identity"],
            world["relationship_broker"],
            tenant_root=world["tenant_root"],
            owner_subject_root=world["roots"]["owner"],
            founder_administrator_root=world["roots"]["founder"],
        )
    with pytest.raises(TenantAuthorityDenied, match="Published"):
        verifier.verify(
            world["store"].snapshot(),
            tenant_root=world["tenant_root"],
            subject_root=world["roots"]["owner"],
            now=1.0,
        )

    published_revision, relationships = _publish_and_activate(world)
    published = published_tenant_authority(
        world["store"].snapshot(),
        world["tenant_protocol"],
        world["assembly"],
        world["library"].lifecycle_protocol,
        world["authorization"],
        world["identity"],
        world["relationship_broker"],
        tenant_root=world["tenant_root"],
    )
    memberships = active_membership_roots(
        world["store"].snapshot(),
        world["identity"],
        world["relationship_broker"],
        world["roots"]["owner"],
        world["tenant_root"],
    )

    assert published.published_revision_root == published_revision
    assert published.catalogue_root == world["library"].catalog_root
    assert published.policy_root == world["policy"]
    assert len(relationships) == 4
    assert world["role_roots"]["owner"] in memberships
    assert world["tenant_root"] in memberships
    atoms = b"\n".join(
        cell.atom for cell in world["store"].snapshot().cells.values()
    )
    assert EXTERNAL_TENANT_ID.encode("utf-8") not in atoms
    assert world["roots"]["founder"] not in memberships
    admission = verifier.verify(
        world["store"].snapshot(),
        tenant_root=world["tenant_root"],
        subject_root=world["roots"]["owner"],
        now=1.0,
    )
    assert admission.published_revision_root == published_revision


def test_tenant_catalogue_upgrade_appends_then_selects_a_new_release():
    world = _world()
    first_revision, _ = _publish_and_activate(world)
    first = published_tenant_authority(
        world["store"].snapshot(),
        world["tenant_protocol"],
        world["assembly"],
        world["library"].lifecycle_protocol,
        world["authorization"],
        world["identity"],
        world["relationship_broker"],
        tenant_root=world["tenant_root"],
    )
    upgraded_catalogue = build_catalog(
        world["store"],
        world["assembly"],
        world["library"].definition_roots,
        catalog_id="test:standard-library:catalog:v2",
        version="2.0.0",
    )
    configuration_root, wip_revision = append_tenant_authority_revision(
        world["store"],
        world["tenant_protocol"],
        world["assembly"],
        world["library"].lifecycle_protocol,
        world["authorization"],
        tenant_root=world["tenant_root"],
        base_configuration_root=first.configuration_root,
        catalogue_root=upgraded_catalogue,
        policy_root=first.policy_root,
        actor_root=world["roots"]["founder"],
    )

    still_selected = published_tenant_authority(
        world["store"].snapshot(),
        world["tenant_protocol"],
        world["assembly"],
        world["library"].lifecycle_protocol,
        world["authorization"],
        world["identity"],
        world["relationship_broker"],
        tenant_root=world["tenant_root"],
    )
    assert still_selected.published_revision_root == first_revision
    assert still_selected.catalogue_root == world["library"].catalog_root

    court = _promotion_court(world, prefix="test:tenant-upgrade-attestation")
    lifecycle = world["library"].lifecycle_protocol
    shared = _promote(
        world, court, wip_revision, lifecycle.states["shared"]
    )
    published = _promote(
        world, court, shared, lifecycle.states["published"]
    )
    select_published_tenant_revision(
        world["store"],
        world["tenant_protocol"],
        world["assembly"],
        lifecycle,
        world["identity"],
        world["relationship_broker"],
        tenant_root=world["tenant_root"],
        revision_root=published,
        actor_root=world["roots"]["founder"],
    )
    upgraded = published_tenant_authority(
        world["store"].snapshot(),
        world["tenant_protocol"],
        world["assembly"],
        lifecycle,
        world["authorization"],
        world["identity"],
        world["relationship_broker"],
        tenant_root=world["tenant_root"],
    )

    assert upgraded.configuration_root == configuration_root
    assert upgraded.catalogue_root == upgraded_catalogue
    assert upgraded.role_roots == first.role_roots
    assert first.configuration_root in world["store"].snapshot().cells
    assert first_revision in world["store"].snapshot().cells


def test_new_release_denies_old_role_wires_until_explicit_reactivation():
    world = _world()
    first_published, first_relationships = _publish_and_activate(world)
    verifier = PublishedTenantAdmissionVerifier(
        world["tenant_protocol"],
        world["assembly"],
        world["library"].lifecycle_protocol,
        world["authorization"],
        world["identity"],
        world["relationship_broker"],
    )
    first = verifier.verify(
        world["store"].snapshot(),
        tenant_root=world["tenant_root"],
        subject_root=world["roots"]["owner"],
        now=2.0,
    )
    assert first.published_revision_root == first_published

    next_wip = append_wip_graph_revision(
        world["store"],
        world["assembly"],
        world["library"].lifecycle_protocol,
        world["staged"].lifecycle_instance_root,
        content_root=world["staged"].configuration_root,
        actor_root=world["roots"]["founder"],
        reason="stage the next tenant release",
    )
    court = _promotion_court(
        world, prefix="test:tenant-promotion-attestation:second"
    )
    shared = _promote(
        world,
        court,
        next_wip,
        world["library"].lifecycle_protocol.states["shared"],
    )
    second_published = _promote(
        world,
        court,
        shared,
        world["library"].lifecycle_protocol.states["published"],
    )
    still_first = verifier.verify(
        world["store"].snapshot(),
        tenant_root=world["tenant_root"],
        subject_root=world["roots"]["owner"],
        now=3.0,
    )
    assert still_first.published_revision_root == first_published
    select_published_tenant_revision(
        world["store"],
        world["tenant_protocol"],
        world["assembly"],
        world["library"].lifecycle_protocol,
        world["identity"],
        world["relationship_broker"],
        tenant_root=world["tenant_root"],
        revision_root=second_published,
        actor_root=world["roots"]["founder"],
        now=3.0,
    )
    with pytest.raises(TenantAuthorityDenied, match="not activated"):
        verifier.verify(
            world["store"].snapshot(),
            tenant_root=world["tenant_root"],
            subject_root=world["roots"]["owner"],
            now=3.0,
        )

    second_relationships = activate_published_tenant_roles(
        world["store"],
        world["tenant_protocol"],
        world["assembly"],
        world["library"].lifecycle_protocol,
        world["authorization"],
        world["identity"],
        world["relationship_broker"],
        tenant_root=world["tenant_root"],
        owner_subject_root=world["roots"]["owner"],
        founder_administrator_root=world["roots"]["founder"],
        now=3.0,
    )
    second = verifier.verify(
        world["store"].snapshot(),
        tenant_root=world["tenant_root"],
        subject_root=world["roots"]["owner"],
        now=3.1,
    )
    assert second.published_revision_root == second_published
    assert set(first_relationships[:3]).isdisjoint(second_relationships[:3])


def test_owner_can_assign_admin_but_admin_policy_can_only_assign_member():
    world = _world()
    _publish_and_activate(world)
    store = world["store"]
    authorization = world["authorization"]
    identity = world["identity"]
    relationships = world["relationship_broker"]
    broker = AuthenticationBroker()
    broker.bind_graph_resolver(
        relationship_principal_resolver(identity, relationships)
    )
    owner_context = broker.mint_authenticated_context(
        world["roots"]["owner"],
        tenant_root=world["tenant_root"],
        assurance_root=world["roots"]["assurance"],
    )
    owner_request = AuthorizationRequest(
        action_root=authorization.actions["manage-policy"],
        object_root=world["tenant_root"],
        resource_lineage_roots=(
            world["roots"]["admin"], world["role_roots"]["administrator"]
        ),
    )
    reason = "owner assigned tenant administrator"
    handle = relationships.mint_from_authorized_relationship_grant(
        store.snapshot(),
        authorization,
        world["policy"],
        broker,
        owner_context,
        owner_request,
        administrator_root=world["roots"]["owner"],
        relationship_id="test:membership:admin:administrator-role",
        source_root=world["roots"]["admin"],
        target_root=world["role_roots"]["administrator"],
        kind="membership",
        tenant_root=world["tenant_root"],
        reason=reason,
    )
    grant_authority_relationship(
        store,
        identity,
        relationships,
        handle,
        relationship_id="test:membership:admin:administrator-role",
        source_root=world["roots"]["admin"],
        target_root=world["role_roots"]["administrator"],
        kind="membership",
        tenant_root=world["tenant_root"],
        administrator_root=world["roots"]["owner"],
        reason=reason,
    )

    admin_context = broker.mint_authenticated_context(
        world["roots"]["admin"],
        tenant_root=world["tenant_root"],
        assurance_root=world["roots"]["assurance"],
    )
    member_request = AuthorizationRequest(
        action_root=authorization.actions["manage-policy"],
        object_root=world["tenant_root"],
        resource_lineage_roots=(
            world["roots"]["member"], world["role_roots"]["member"]
        ),
    )
    member_reason = "administrator assigned tenant member"
    member_handle = relationships.mint_from_authorized_relationship_grant(
        store.snapshot(),
        authorization,
        world["policy"],
        broker,
        admin_context,
        member_request,
        administrator_root=world["roots"]["admin"],
        relationship_id="test:membership:member:member-role",
        source_root=world["roots"]["member"],
        target_root=world["role_roots"]["member"],
        kind="membership",
        tenant_root=world["tenant_root"],
        reason=member_reason,
    )
    grant_authority_relationship(
        store,
        identity,
        relationships,
        member_handle,
        relationship_id="test:membership:member:member-role",
        source_root=world["roots"]["member"],
        target_root=world["role_roots"]["member"],
        kind="membership",
        tenant_root=world["tenant_root"],
        administrator_root=world["roots"]["admin"],
        reason=member_reason,
    )
    forbidden_request = AuthorizationRequest(
        action_root=authorization.actions["manage-policy"],
        object_root=world["tenant_root"],
        resource_lineage_roots=(
            world["roots"]["forbidden_owner"], world["role_roots"]["owner"]
        ),
    )
    with pytest.raises(AuthorizationDenied, match="default-deny"):
        relationships.mint_from_authorized_relationship_grant(
            store.snapshot(),
            authorization,
            world["policy"],
            broker,
            admin_context,
            forbidden_request,
            administrator_root=world["roots"]["admin"],
            relationship_id="test:membership:forbidden:owner-role",
            source_root=world["roots"]["forbidden_owner"],
            target_root=world["role_roots"]["owner"],
            kind="membership",
            tenant_root=world["tenant_root"],
            reason="administrator attempted owner escalation",
        )


def test_selected_release_is_stable_when_live_watcher_registry_changes():
    world = _world()
    published_root, _ = _publish_and_activate(world)
    store = world["store"]
    lifecycle = world["library"].lifecycle_protocol
    before = read_revision(store.snapshot(), lifecycle, published_root)
    before_bytes = graph_content_bytes(
        store.snapshot(), before.content_root
    )

    composed = compose_catalog_instance(
        store.snapshot(),
        world["assembly"],
        world["library"].catalog_root,
        world["library"].definition_roots[1],
        token="tenant-release-runtime-boundary",
    )
    store.commit(store.revision, create=composed.cells)
    register_reaction_instance(
        store,
        world["assembly"],
        world["library"].reaction_protocol,
        composed.instance.root_id,
    )

    after = read_revision(store.snapshot(), lifecycle, published_root)
    after_bytes = graph_content_bytes(store.snapshot(), after.content_root)
    authority = published_tenant_authority(
        store.snapshot(),
        world["tenant_protocol"],
        world["assembly"],
        lifecycle,
        world["authorization"],
        world["identity"],
        world["relationship_broker"],
        tenant_root=world["tenant_root"],
    )

    assert before_bytes == after_bytes
    assert authority.published_revision_root == published_root
    assert authority.release_manifested is True
    assert authority.catalogue_descriptor_root is not None
    assert authority.policy_descriptor_root is not None

    reached = set()
    pending = [authority.configuration_root]
    snapshot = store.snapshot()
    while pending:
        root = pending.pop()
        if root in reached or root == NULL_CELL_ID:
            continue
        reached.add(root)
        cell = snapshot.cells[root]
        pending.extend((cell.link0, cell.link1))
    assert authority.catalogue_root not in reached
    assert authority.policy_root not in reached
    assert world["library"].reaction_protocol.registry_root not in reached


@pytest.mark.parametrize("target", ("descriptor", "catalogue"))
def test_tenant_release_manifest_tampering_fails_closed(target: str):
    world = _world()
    _publish_and_activate(world)
    store = world["store"]
    authority = published_tenant_authority(
        store.snapshot(),
        world["tenant_protocol"],
        world["assembly"],
        world["library"].lifecycle_protocol,
        world["authorization"],
        world["identity"],
        world["relationship_broker"],
        tenant_root=world["tenant_root"],
    )
    if target == "descriptor":
        root = authority.catalogue_descriptor_root + ":digest"
        replacement = b"sha256:" + b"0" * 64
    else:
        catalogue = read_catalog(
            store.snapshot(), world["assembly"], authority.catalogue_root
        )
        root = catalogue.digest_root
        replacement = b"0" * 64
    original = store.read(root)
    store.commit(
        store.revision,
        replace=(Cell(root, original.link0, original.link1, replacement),),
    )

    with pytest.raises(InvalidCell):
        published_tenant_authority(
            store.snapshot(),
            world["tenant_protocol"],
            world["assembly"],
            world["library"].lifecycle_protocol,
            world["authorization"],
            world["identity"],
            world["relationship_broker"],
            tenant_root=world["tenant_root"],
        )
