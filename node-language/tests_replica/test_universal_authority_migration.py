import hashlib

import pytest

from nodelang.cell_adapters import (
    bootstrap_adapter_protocol,
    build_adapter_catalog,
    build_adapter_definition,
    release_adapter_definition,
)
from nodelang.cell_attestations import (
    CourtAttestationBroker,
    bootstrap_attestation_protocol,
    build_court_definition,
)
from nodelang.cell_catalog import bootstrap_assembly_protocol, project_catalog
from nodelang.cell_composer import (
    bootstrap_composer_protocol,
    build_composer_authority,
)
from nodelang.cell_domain_catalog import DOMAIN_SPECS
from nodelang.cell_lifecycle import append_wip_graph_revision
from nodelang.cell_protocols import (
    CellBatch,
    compose_relation_cells,
    read_relation,
)
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.cell_standard_library import build_standard_library_v0
from nodelang.cell_tenant_authority import (
    activate_published_tenant_roles,
    bootstrap_tenant_configuration_protocol,
    provision_tenant_identity,
    published_tenant_authority,
    select_published_tenant_revision,
    stage_tenant_authority,
)
from nodelang.universal_application import (
    _ADAPTER_CATALOG_V2,
    _ADAPTER_CATALOG_V3,
    _APPLICATION_TENANT_EXTERNAL_ID,
    _AUTHORITY_MIGRATION_V3,
    _AUTHORITY_MIGRATION_V7,
    _COMPOSER_AUTHORITY_V3,
    _COMPOSER_AUTHORITY_V7,
    _DEVICE_CUSTODY_ADAPTER_V1,
    _DEVICE_CUSTODY_ADAPTER_V2,
    _STANDARD_CATALOG_V2,
    _STANDARD_CATALOG_V5,
    _STANDARD_CATALOG_V6,
    _build_application_authorization,
    _migrate_universal_authorities_current,
    _promote_tenant_authority_revision,
    _tenant_authority_court_runner,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


def _legacy_world(*, direct_tenant_configuration: bool = False):
    store = CellStore()
    provider = MemorySigningKeyProvider(
        "archhub.local.relationship-authority", b"r" * 32
    )
    provider.add_key("archhub.local.court-attestation", b"e" * 32)
    assembly = bootstrap_assembly_protocol(
        store, prefix="app:assembly-protocol"
    )
    legacy_keys = tuple(
        spec["key"] for spec in DOMAIN_SPECS
        if spec["key"] not in {"permission-request", "governed-work"}
    )
    library = build_standard_library_v0(
        store,
        assembly,
        prefix="app:standard-library",
        catalog_id="app:standard-library:catalog",
        catalog_version="1.0.0",
        domain_keys=legacy_keys,
    )
    adapter = bootstrap_adapter_protocol(
        store, prefix="app:adapter-protocol"
    )
    composer = bootstrap_composer_protocol(
        store, prefix="app:composer-protocol"
    )
    device_adapter = build_adapter_definition(
        store,
        adapter,
        adapter_id=_DEVICE_CUSTODY_ADAPTER_V1,
        name="Windows hardware device-key custody",
        actions=("device-key.enroll",),
        locations=("windows-cng:platform-provider",),
        datatypes=("public-jwk",),
        evidence="legacy v41 adapter evidence",
    )
    release_adapter_definition(store, adapter, device_adapter.root_id)
    build_adapter_catalog(
        store,
        adapter,
        (device_adapter.root_id,),
        catalog_id=_ADAPTER_CATALOG_V2,
        version="2.0.0",
    )
    build_composer_authority(
        store,
        composer,
        assembly,
        library.catalog_root,
        adapter,
        _ADAPTER_CATALOG_V2,
        authority_id="app:agent-composer-authority:v2",
        evidence="legacy v41 composer evidence",
    )
    tenant_protocol = bootstrap_tenant_configuration_protocol(
        store, prefix="app:tenant-configuration-protocol"
    )
    tenant_root, _ = provision_tenant_identity(
        store, external_tenant_id=_APPLICATION_TENANT_EXTERNAL_ID
    )
    authorization = _build_application_authorization(
        store, tenant_root, provider
    )
    staged = stage_tenant_authority(
        store,
        tenant_protocol,
        assembly,
        library.lifecycle_protocol,
        authorization.protocol,
        external_tenant_id=_APPLICATION_TENANT_EXTERNAL_ID,
        catalogue_root=library.catalog_root,
        policy_root=authorization.policy_root,
        versioned_asset_definition_root=library.definition_roots[2],
        actor_root=authorization.subject_root,
    )
    promotion_source = staged.wip_revision_root
    published_configuration = staged.configuration_root
    if direct_tenant_configuration:
        published_configuration = (
            authorization.tenant_root + ":configuration:legacy-direct"
        )
        legacy_configuration = compose_relation_cells((
            (tenant_protocol.role("tenant"), authorization.tenant_root),
            (tenant_protocol.role("catalogue"), library.catalog_root),
            (tenant_protocol.role("policy"), authorization.policy_root),
            (tenant_protocol.role("owner-role"), staged.role_roots["owner"]),
            (
                tenant_protocol.role("administrator-role"),
                staged.role_roots["administrator"],
            ),
            (tenant_protocol.role("member-role"), staged.role_roots["member"]),
        ), relation_id=published_configuration)
        store.commit(store.revision, create=legacy_configuration.cells)
        promotion_source = append_wip_graph_revision(
            store,
            assembly,
            library.lifecycle_protocol,
            staged.lifecycle_instance_root,
            content_root=published_configuration,
            actor_root=authorization.subject_root,
            reason="legacy direct tenant configuration fixture",
        )
    attestation = bootstrap_attestation_protocol(
        store, prefix="app:attestation-protocol"
    )
    court = build_court_definition(
        store,
        attestation,
        court_id="app:court:tenant-authority",
        name="Tenant authority lifecycle court",
        builder_id="https://archhub.local/builder/tenant-authority-court",
        runner_version="1.0.0",
        policy_digest=hashlib.sha256(b"legacy tenant policy").hexdigest(),
        checks=("graph-digest", "target-state"),
    )
    broker = CourtAttestationBroker(
        key_provider=provider,
        key_id="archhub.local.court-attestation",
    )
    broker.admit_court(
        store.snapshot(),
        attestation,
        court.root_id,
        _tenant_authority_court_runner(frozenset((
            library.lifecycle_protocol.states["shared"],
            library.lifecycle_protocol.states["published"],
        ))),
    )
    shared = _promote_tenant_authority_revision(
        store,
        assembly,
        library.lifecycle_protocol,
        attestation,
        broker,
        court.root_id,
        staged.lifecycle_instance_root,
        promotion_source,
        library.lifecycle_protocol.states["shared"],
        authorization.subject_root,
    )
    published = _promote_tenant_authority_revision(
        store,
        assembly,
        library.lifecycle_protocol,
        attestation,
        broker,
        court.root_id,
        staged.lifecycle_instance_root,
        shared,
        library.lifecycle_protocol.states["published"],
        authorization.subject_root,
    )
    select_published_tenant_revision(
        store,
        tenant_protocol,
        assembly,
        library.lifecycle_protocol,
        authorization.identity_protocol,
        authorization.relationship_broker,
        tenant_root=authorization.tenant_root,
        revision_root=published,
        actor_root=authorization.subject_root,
    )
    role_relationships = activate_published_tenant_roles(
        store,
        tenant_protocol,
        assembly,
        library.lifecycle_protocol,
        authorization.protocol,
        authorization.identity_protocol,
        authorization.relationship_broker,
        tenant_root=authorization.tenant_root,
        owner_subject_root=authorization.subject_root,
        founder_administrator_root=authorization.subject_root,
    )
    roles = {
        name: "test:role:" + name
        for name in ("source", "target", "member", "why", "catalog")
    }
    batch = CellBatch(store)
    for name, root in roles.items():
        batch.add(Cell(root, NULL_CELL_ID, NULL_CELL_ID, name.encode("ascii")))
    batch.relation(
        [(roles["catalog"], library.catalog_root)],
        relation_id="test:node-library",
    )
    batch.relation(
        [
            (roles["member"], library.catalog_root),
            (roles["member"], published_configuration),
            (roles["member"], published),
            *((roles["member"], root) for root in role_relationships),
        ],
        relation_id="test:application",
    )
    batch.commit()
    return {
        "store": store,
        "provider": provider,
        "assembly": assembly,
        "library": library,
        "adapter": adapter,
        "composer": composer,
        "tenant_protocol": tenant_protocol,
        "authorization": authorization,
        "attestation": attestation,
        "broker": broker,
        "court": court.root_id,
        "roles": roles,
        "staged": staged,
        "published_configuration": published_configuration,
        "published": published,
    }


def _migrate(world):
    return _migrate_universal_authorities_current(
        world["store"],
        world["assembly"],
        world["library"],
        world["adapter"],
        world["composer"],
        world["tenant_protocol"],
        world["authorization"],
        world["attestation"],
        world["broker"],
        world["court"],
        world["roles"],
        application_root="test:application",
        library_root="test:node-library",
    )


def test_legacy_authorities_migrate_append_only_and_reopen_idempotently():
    world = _legacy_world()
    store = world["store"]
    legacy_digest_root = _DEVICE_CUSTODY_ADAPTER_V1 + ":digest"
    legacy_digest = store.read(legacy_digest_root)
    store.commit(
        store.revision,
        replace=(Cell(
            legacy_digest.id,
            legacy_digest.link0,
            legacy_digest.link1,
            b"legacy-v1-digest-boundary",
        ),),
    )
    old_cells = set(store.snapshot().cells)
    old_catalogue = world["library"].catalog_root
    old_configuration = world["staged"].configuration_root
    old_published = world["published"]
    old_composer = "app:agent-composer-authority:v2"

    migrated = _migrate_universal_authorities_current(
        store,
        world["assembly"],
        world["library"],
        world["adapter"],
        world["composer"],
        world["tenant_protocol"],
        world["authorization"],
        world["attestation"],
        world["broker"],
        world["court"],
        world["roles"],
        application_root="test:application",
        library_root="test:node-library",
    )

    snapshot = store.snapshot()
    assert migrated.migrated is True
    assert migrated.migration_root == _AUTHORITY_MIGRATION_V7
    assert old_cells <= set(snapshot.cells)
    assert old_catalogue in snapshot.cells
    assert old_configuration in snapshot.cells
    assert old_published in snapshot.cells
    assert old_composer in snapshot.cells
    assert {
        _STANDARD_CATALOG_V2,
        _STANDARD_CATALOG_V5,
        _STANDARD_CATALOG_V6,
        _DEVICE_CUSTODY_ADAPTER_V1,
        _ADAPTER_CATALOG_V2,
        _DEVICE_CUSTODY_ADAPTER_V2,
        _ADAPTER_CATALOG_V3,
        _COMPOSER_AUTHORITY_V7,
        _AUTHORITY_MIGRATION_V7,
    } <= set(snapshot.cells)
    assert snapshot.cells[legacy_digest_root].atom == b"legacy-v1-digest-boundary"
    assert migrated.device_custody_adapter_root == _DEVICE_CUSTODY_ADAPTER_V2
    assert migrated.adapter_catalog_root == _ADAPTER_CATALOG_V3
    assert {item["name"] for item in project_catalog(
        snapshot, world["assembly"], _STANDARD_CATALOG_V2
    )} >= {"Permission Request"}
    v2_definition_roots = {
        item["id"] for item in project_catalog(
            snapshot, world["assembly"], _STANDARD_CATALOG_V2
        )
    }
    v5_definition_roots = {
        item["id"] for item in project_catalog(
            snapshot, world["assembly"], _STANDARD_CATALOG_V5
        )
    }
    v6_catalog = project_catalog(
        snapshot, world["assembly"], _STANDARD_CATALOG_V6
    )
    v6_definition_roots = {item["id"] for item in v6_catalog}
    assert v5_definition_roots == {
        *v2_definition_roots,
        *migrated.cognition_definitions.roots,
    }
    assert v2_definition_roots.isdisjoint(
        migrated.cognition_definitions.roots
    )
    governed_work_roots = {
        item["id"] for item in v6_catalog
        if item["name"] == "Governed Work"
    }
    assert len(governed_work_roots) == 1
    assert governed_work_roots.isdisjoint(v5_definition_roots)
    assert v6_definition_roots == v5_definition_roots | governed_work_roots
    assert migrated.cognition_definitions.status_ledger_root in snapshot.cells
    authority = published_tenant_authority(
        snapshot,
        world["tenant_protocol"],
        world["assembly"],
        migrated.standard_library.lifecycle_protocol,
        world["authorization"].protocol,
        world["authorization"].identity_protocol,
        world["authorization"].relationship_broker,
        tenant_root=world["authorization"].tenant_root,
    )
    assert authority.catalogue_root == _STANDARD_CATALOG_V6
    library_catalogues = tuple(
        member.participant_id for member in read_relation(
            snapshot, "test:node-library"
        )
        if member.role_id == world["roles"]["catalog"]
    )
    assert library_catalogues == (_STANDARD_CATALOG_V6,)

    revision = store.revision
    reopened = _migrate_universal_authorities_current(
        store,
        world["assembly"],
        world["library"],
        world["adapter"],
        world["composer"],
        world["tenant_protocol"],
        world["authorization"],
        world["attestation"],
        world["broker"],
        world["court"],
        world["roles"],
        application_root="test:application",
        library_root="test:node-library",
    )
    assert reopened.migrated is False
    assert reopened.migration_root == _AUTHORITY_MIGRATION_V7
    assert store.revision == revision

    reason_root = _AUTHORITY_MIGRATION_V7 + ":reason"
    reason = store.read(reason_root)
    store.commit(
        store.revision,
        replace=(Cell(
            reason.id, reason.link0, reason.link1, b"tampered migration reason"
        ),),
    )
    with pytest.raises(InvalidCell, match="migration reason|migration digest"):
        _migrate_universal_authorities_current(
            store,
            world["assembly"],
            world["library"],
            world["adapter"],
            world["composer"],
            world["tenant_protocol"],
            world["authorization"],
            world["attestation"],
            world["broker"],
            world["court"],
            world["roles"],
            application_root="test:application",
            library_root="test:node-library",
        )


def test_legacy_direct_tenant_release_migrates_to_stable_descriptors():
    world = _legacy_world(direct_tenant_configuration=True)
    store = world["store"]
    legacy = published_tenant_authority(
        store.snapshot(),
        world["tenant_protocol"],
        world["assembly"],
        world["library"].lifecycle_protocol,
        world["authorization"].protocol,
        world["authorization"].identity_protocol,
        world["authorization"].relationship_broker,
        tenant_root=world["authorization"].tenant_root,
    )
    assert legacy.release_manifested is False
    old_revision = legacy.published_revision_root
    old_configuration = legacy.configuration_root
    old_cells = set(store.snapshot().cells)

    migrated = _migrate(world)
    current = published_tenant_authority(
        store.snapshot(),
        world["tenant_protocol"],
        world["assembly"],
        migrated.standard_library.lifecycle_protocol,
        world["authorization"].protocol,
        world["authorization"].identity_protocol,
        world["authorization"].relationship_broker,
        tenant_root=world["authorization"].tenant_root,
    )

    assert current.release_manifested is True
    assert current.configuration_root != old_configuration
    assert current.published_revision_root != old_revision
    assert current.catalogue_descriptor_root in store.snapshot().cells
    assert current.policy_descriptor_root in store.snapshot().cells
    assert old_cells <= set(store.snapshot().cells)
    assert old_configuration in store.snapshot().cells
    assert old_revision in store.snapshot().cells

    revision = store.revision
    reopened = _migrate(world)
    assert reopened.tenant_authority.published_revision_root == (
        current.published_revision_root
    )
    assert store.revision == revision
