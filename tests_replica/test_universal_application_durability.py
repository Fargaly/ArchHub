"""Restart court for the complete universal application super-node."""
import pytest
import nodelang.universal_application as universal_application_module

from nodelang.cell_authorization import AuthorizationDenied
from nodelang.cell_attention import read_focus
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.cell_cloud_routes import list_cloud_routes
from nodelang.cell_protocols import (
    compose_relation_cells,
    prepare_append_relation_members,
    read_relation,
)
from nodelang.cell_relation_composer import (
    RELATION_COMPOSER_PROTOCOL_PREFIX,
    RELATION_COMPOSER_ROLE_NAMES,
)
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    assign_released_universal_theme,
    build_universal_application,
    preview_universal_presentation_color,
    preview_universal_theme,
    promote_universal_theme_to_shared,
    project_universal_canvas,
    provision_universal_view_session,
    read_universal_theme,
    reset_universal_presentation_color,
    restore_universal_application,
    revoke_universal_authority_relationship,
    select_universal_root,
    set_universal_viewport,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore


def test_restore_evolves_legacy_relation_composer_protocol_with_registry_role(
    tmp_path,
):
    store = CellStore(tmp_path / "legacy-relation-composer.sqlite3")
    old_role_names = tuple(
        name for name in RELATION_COMPOSER_ROLE_NAMES if name not in {"x", "y"}
    )
    composer_roles = {
        name: "%s:role:%s" % (RELATION_COMPOSER_PROTOCOL_PREFIX, name)
        for name in old_role_names
    }
    composer_root = RELATION_COMPOSER_PROTOCOL_PREFIX + ":root"
    app_root = compose_relation_cells((), relation_id="app:archhub")
    old_protocol = compose_relation_cells(
        (
            (composer_roles["vocabulary-member"], role_root)
            for role_root in composer_roles.values()
        ),
        relation_id=composer_root,
    )
    store.commit(store.revision, create=(
        Cell("gm:role:member", NULL_CELL_ID, NULL_CELL_ID, b"member"),
        *(
            Cell(role_root, NULL_CELL_ID, NULL_CELL_ID, name.encode("ascii"))
            for name, role_root in composer_roles.items()
        ),
        *app_root.cells,
        *old_protocol.cells,
    ))

    protocol = (
        universal_application_module._ensure_relation_composer_protocol_graph(
            store, member_role_id="gm:role:member"
        )
    )
    snapshot = store.snapshot()
    assert protocol.root_id == composer_root
    assert all(role_root in snapshot.cells for role_root in protocol.roles.values())
    protocol_members = read_relation(snapshot, protocol.root_id, budget=64)
    assert {
        member.participant_id
        for member in protocol_members
        if member.role_id == protocol.role("vocabulary-member")
    } == set(protocol.roles.values())
    assert any(
        member.role_id == "gm:role:member"
        and member.participant_id == protocol.root_id
        for member in read_relation(snapshot, "app:archhub", budget=64)
    )
    store.close()


def test_generic_canvas_interface_reopens_as_connected_exact_history(tmp_path):
    path = tmp_path / "canvas-interface-migration.sqlite3"
    provider = MemorySigningKeyProvider(
        "archhub.local.relationship-authority", b"i" * 32
    )
    provider.add_key("archhub.local.court-attestation", b"j" * 32)
    store, registry = build_universal_application(
        resolve_map_path(), CellStore(path), key_provider=provider
    )
    wire = project_universal_canvas(store, registry)["wires"][0]
    legacy_root = universal_application_module._domain_canvas_interface_root(
        wire["source"], "source"
    )
    name_root = legacy_root + ":name"
    snapshot = store.snapshot()
    legacy = compose_relation_cells((
        (
            registry.assembly_protocol.role("interface-target"),
            wire["source"],
        ),
        (registry.assembly_protocol.role("name"), name_root),
        (
            registry.assembly_protocol.role("interface-contract"),
            registry.assembly_protocol.root_id,
        ),
        (
            registry.assembly_protocol.role("interface-presentation"),
            "app:canvas-interface:presentation:source",
        ),
    ), relation_id=legacy_root)
    registration = prepare_append_relation_members(
        snapshot,
        registry.application_root,
        ((registry.assembly_protocol.role("interface"), legacy_root),),
        budget=100_000,
    )
    store.commit(
        snapshot.revision,
        create=(
            Cell(name_root, NULL_CELL_ID, NULL_CELL_ID, b"Provides"),
            *legacy.cells,
            *registration.create,
        ),
        replace=registration.replace,
    )
    legacy_registration = next(
        member for member in read_relation(
            store.snapshot(), registry.application_root, budget=100_000
        )
        if member.participant_id == legacy_root
    )
    before_ids = frozenset(store.snapshot().cells)
    store.close()

    reopened, restored = restore_universal_application(
        resolve_map_path(), CellStore(path), key_provider=provider
    )
    snapshot = reopened.snapshot()
    assert before_ids.issubset(snapshot.cells)
    assert legacy_registration.incidence_id in snapshot.cells
    assert any(
        member.role_id == restored.roles["migration"]
        and member.participant_id
        == universal_application_module._CANVAS_INTERFACE_MIGRATION_ROOT
        for member in read_relation(
            snapshot, restored.application_root, budget=100_000
        )
    )
    projection = project_universal_canvas(reopened, restored)
    migrated_port = next(
        port for node in projection["nodes"]
        if node["id"] == wire["source"]
        for port in node["ports"]
        if port["id"] == wire["source_interface"]
    )
    exact_roots = {
        universal_application_module._relation_canvas_interface_root(
            relation_root, "source"
        )
        for relation_root in migrated_port["relation_roots"]
    }
    assert set(migrated_port["previous_roots"]) == exact_roots
    assert len(migrated_port["previous_roots"]) == len(exact_roots)
    for exact_root in exact_roots:
        exact = universal_application_module._project_canvas_interface(
            snapshot, restored.assembly_protocol, exact_root
        )
        assert exact is not None
        assert exact["previous_roots"] == [legacy_root]
    reopened.close()


def test_restore_appends_new_protected_routes_without_deleting_old_graph(
    tmp_path, monkeypatch
):
    current_specs = universal_application_module._APPLICATION_HTTP_ROUTE_SPECS
    old_specs = tuple(
        spec for spec in current_specs
        if spec[1] not in (
            "/api/universal/lifecycle-wip",
            "/api/universal/lifecycle-merge",
        )
    )
    monkeypatch.setattr(
        universal_application_module,
        "_APPLICATION_HTTP_ROUTE_SPECS",
        old_specs,
    )
    provider = MemorySigningKeyProvider(
        "archhub.local.relationship-authority", b"r" * 32
    )
    provider.add_key("archhub.local.court-attestation", b"e" * 32)
    store, registry = build_universal_application(
        resolve_map_path(),
        CellStore(tmp_path / "route-migration.sqlite3"),
        key_provider=provider,
    )
    old_roots = set(registry.application_http_route_roots.values())
    assert len(old_roots) == len(old_specs) + len(registry.website.route_roots)
    before = store.revision

    monkeypatch.setattr(
        universal_application_module,
        "_APPLICATION_HTTP_ROUTE_SPECS",
        current_specs,
    )
    store, restored = restore_universal_application(
        resolve_map_path(), store, key_provider=provider
    )
    assert store.revision > before
    assert len(restored.application_http_route_roots) == (
        len(current_specs) + len(restored.website.route_roots)
    )
    assert old_roots < set(restored.application_http_route_roots.values())
    registered = {
        route.root_id for route in list_cloud_routes(
            store.snapshot(), restored.cloud_route_protocol
        )
    }
    assert registered == set(restored.application_http_route_roots.values())
    application_members = {
        member.participant_id for member in read_relation(
            store.snapshot(), restored.application_root, budget=100_000
        )
    }
    assert registered <= application_members


def test_restore_tolerates_retired_routes_without_reactivating_them(
    tmp_path, monkeypatch
):
    current_specs = universal_application_module._APPLICATION_HTTP_ROUTE_SPECS
    retired_specs = (
        ("POST", "/api/universal/group", "edit"),
        ("POST", "/api/universal/inspector-lens", "inspect"),
        ("POST", "/api/universal/properties-panel", "inspect"),
        ("POST", "/api/universal/property-create", "edit"),
        ("POST", "/api/universal/property", "edit"),
        ("POST", "/api/universal/scope", "inspect"),
        ("POST", "/api/universal/ungroup", "edit"),
        ("POST", "/api/universal/interface-create", "edit"),
        ("POST", "/api/universal/interface-value", "edit"),
        ("POST", "/api/universal/interface", "edit"),
        ("POST", "/api/universal/cell", "edit"),
        ("POST", "/api/universal/connect", "connect"),
        ("POST", "/api/universal/disconnect", "connect"),
        ("POST", "/api/universal/rewire", "connect"),
        ("POST", "/api/universal/control", "edit"),
        ("POST", "/api/universal/undo", "edit"),
        ("POST", "/api/universal/redo", "edit"),
    )
    monkeypatch.setattr(
        universal_application_module,
        "_APPLICATION_HTTP_ROUTE_SPECS",
        (*current_specs, *retired_specs),
    )
    provider = MemorySigningKeyProvider(
        "archhub.local.relationship-authority", b"r" * 32
    )
    provider.add_key("archhub.local.court-attestation", b"e" * 32)
    store, legacy = build_universal_application(
        resolve_map_path(),
        CellStore(tmp_path / "retired-route-migration.sqlite3"),
        key_provider=provider,
    )
    retired_keys = {
        "POST /api/universal/group",
        "POST /api/universal/inspector-lens",
        "POST /api/universal/properties-panel",
        "POST /api/universal/property-create",
        "POST /api/universal/property",
        "POST /api/universal/scope",
        "POST /api/universal/ungroup",
        "POST /api/universal/interface-create",
        "POST /api/universal/interface-value",
        "POST /api/universal/interface",
        "POST /api/universal/cell",
        "POST /api/universal/connect",
        "POST /api/universal/disconnect",
        "POST /api/universal/rewire",
        "POST /api/universal/control",
        "POST /api/universal/undo",
        "POST /api/universal/redo",
    }
    assert retired_keys <= set(legacy.application_http_route_roots)

    monkeypatch.setattr(
        universal_application_module,
        "_APPLICATION_HTTP_ROUTE_SPECS",
        current_specs,
    )
    store, restored = restore_universal_application(
        resolve_map_path(), store, key_provider=provider
    )

    assert not (retired_keys & set(restored.application_http_route_roots))
    route_keys = {
        "%s %s" % (route.method, route.path_template)
        for route in list_cloud_routes(
            store.snapshot(), restored.cloud_route_protocol
        )
    }
    assert retired_keys <= route_keys


def test_restore_appends_graph_native_library_sections_to_legacy_state(
    tmp_path, monkeypatch
):
    path = tmp_path / "library-section-migration.sqlite3"
    provider = MemorySigningKeyProvider(
        "archhub.local.relationship-authority", b"l" * 32
    )
    provider.add_key("archhub.local.court-attestation", b"s" * 32)
    composer = universal_application_module._compose_node_library_sections
    monkeypatch.setattr(
        universal_application_module,
        "_compose_node_library_sections",
        lambda *_args, **_kwargs: (),
    )
    store, registry = build_universal_application(
        resolve_map_path(), CellStore(path), key_provider=provider
    )
    assert not any(
        member.role_id == registry.roles["relation"]
        for member in read_relation(
            store.snapshot(), registry.library_root, budget=32
        )
    )
    before_roots = frozenset(store.snapshot().cells)
    monkeypatch.setattr(
        universal_application_module,
        "_compose_node_library_sections",
        composer,
    )
    store, restored = restore_universal_application(
        resolve_map_path(), store, key_provider=provider
    )
    projection = project_universal_canvas(store, restored)
    assert before_roots.issubset(store.snapshot().cells)
    assert [section["label"] for section in projection["catalog_sections"]] == [
        "Core Assemblies", "Governed Data & Work", "Agents & Cognition",
    ]
    assert [
        definition
        for section in projection["catalog_sections"]
        for definition in section["definitions"]
    ] == [item["id"] for item in projection["catalog"]]


def test_full_application_registry_state_and_revocation_reopen_without_rebuild(
    tmp_path,
):
    path = tmp_path / "universal-application.sqlite3"
    provider = MemorySigningKeyProvider(
        "archhub.local.relationship-authority", b"d" * 32
    )
    provider.add_key("archhub.local.court-attestation", b"c" * 32)
    store, registry = build_universal_application(
        resolve_map_path(), CellStore(path), key_provider=provider
    )
    member_root = "test:durable:member"
    store.commit(store.revision, create=(
        Cell(member_root, NULL_CELL_ID, NULL_CELL_ID, b"Durable member"),
    ))
    view, _ = provision_universal_view_session(
        store, registry, member_root, visible_roots=registry.visible_roots[:2]
    )
    set_universal_viewport(store, registry, pan_x=91, pan_y=-44, zoom=1.25)
    theme_wip = preview_universal_theme(
        store, registry, {"accent": "#336699"}
    )
    shared_theme, _ = promote_universal_theme_to_shared(
        store, registry, source_revision_root=theme_wip
    )
    revoke_universal_authority_relationship(
        store,
        registry,
        view.principal_membership_root,
        reason="membership deliberately removed before restart",
    )
    expected_revision = store.revision
    expected_focus = registry.focus_incidence
    expected_wire_roots = registry.relation_roots
    expected_member_settings = view.settings_root
    store.close()

    reopened = CellStore(path)
    reopened, restored = restore_universal_application(
        resolve_map_path(), reopened, key_provider=provider
    )
    assert all(
        not view.root_id.endswith(":scope-trail")
        for view in restored.view_sessions.values()
    )
    assert reopened.revision == expected_revision
    assert restored.focus_incidence == expected_focus
    assert restored.relation_roots == expected_wire_roots
    assert restored.visible_roots == registry.visible_roots
    assert restored.visible_roots == (
        *restored.map.domains.values(),
        restored.core_values.root_id,
        restored.governed_work_registry_root,
    )
    assert len(restored.relation_roots) == len(expected_wire_roots)
    assert restored.view_sessions[member_root].settings_root == expected_member_settings
    assert reopened.read(restored.viewport_properties["pan_x"].value_root).atom == b"91.0"
    assert reopened.read(restored.viewport_properties["pan_y"].value_root).atom == b"-44.0"
    assert reopened.read(restored.viewport_properties["zoom"].value_root).atom == b"1.25"
    assign_released_universal_theme(
        reopened,
        restored,
        restored.authorization.subject_root,
        shared_theme,
    )
    theme, metadata = read_universal_theme(reopened, restored)
    assert theme["accent"] == "#336699"
    assert metadata["binding_mode"] == "direct-release"

    founder_projection = project_universal_canvas(reopened, restored)
    revoked = next(
        relationship
        for relationship in founder_projection["authorization"]["relationships"]
        if relationship["root"] == view.principal_membership_root
    )
    assert revoked["state"] == "revoked"
    assert revoked["verified"] is True

    member_context = restored.authorization.broker.mint_authenticated_context(
        member_root,
        tenant_root=restored.authorization.tenant_root,
        assurance_root=restored.authorization.assurance_root,
        lifetime_seconds=120,
    )
    with pytest.raises(AuthorizationDenied, match="default-deny"):
        project_universal_canvas(
            reopened, restored, authentication_context=member_context
        )
    reopened.close()


def test_personal_presentation_binding_reopens_with_identity_history_and_reset(
    tmp_path,
):
    path = tmp_path / "personal-presentation.sqlite3"
    provider = MemorySigningKeyProvider(
        "archhub.local.relationship-authority", b"p" * 32
    )
    provider.add_key("archhub.local.court-attestation", b"q" * 32)
    store, registry = build_universal_application(
        resolve_map_path(), CellStore(path), key_provider=provider
    )
    target = registry.visible_roots[0]
    select_universal_root(store, registry, target)
    revision = preview_universal_presentation_color(
        store, registry, target, "#2f80ed"
    )
    before = project_universal_canvas(store, registry)
    color = next(
        row for row in before["properties"] if row["label"] == "color"
    )
    binding_root = color["presentation_binding"]
    source_root = color["presentation_source_root"]
    expected_store_revision = store.revision
    assert color["presentation_revision"] == revision
    assert len(color["presentation_history"]) == 1
    store.close()

    reopened = CellStore(path)
    reopened, restored = restore_universal_application(
        resolve_map_path(), reopened, key_provider=provider
    )
    assert reopened.revision == expected_store_revision
    projection = project_universal_canvas(reopened, restored)
    restored_color = next(
        row for row in projection["properties"] if row["label"] == "color"
    )
    assert restored_color["value"] == "#2f80ed"
    assert restored_color["presentation_binding"] == binding_root
    assert restored_color["presentation_source_root"] == source_root
    assert restored_color["presentation_revision"] == revision
    assert len(restored_color["presentation_history"]) == 1

    reset_revision = reset_universal_presentation_color(
        reopened,
        restored,
        target,
        base_revision_root=revision,
    )
    reset = project_universal_canvas(reopened, restored)
    reset_color = next(
        row for row in reset["properties"] if row["label"] == "color"
    )
    assert reset_color["presentation_binding"] == binding_root
    assert reset_color["presentation_revision"] == reset_revision
    assert reset_color["presentation_source_mode"] == "inherited"
    assert len(reset_color["presentation_history"]) == 2
    reopened.close()


def test_restore_migrates_container_cards_out_of_every_signed_view_once(
    tmp_path,
):
    provider = MemorySigningKeyProvider(
        "archhub.local.relationship-authority", b"m" * 32
    )
    provider.add_key("archhub.local.court-attestation", b"n" * 32)
    store, registry = build_universal_application(
        resolve_map_path(),
        CellStore(tmp_path / "container-card-migration.sqlite3"),
        key_provider=provider,
    )
    roles = registry.roles
    founder = registry.view_sessions[registry.authorization.subject_root]
    first_domain = registry.visible_roots[0]

    # Recreate the obsolete durable shape: application/catalogue peer cards,
    # application selected and focused, plus signed projection grants.
    universal_application_module.rewire_incidence(
        store, founder.selection_incidences[first_domain], registry.application_root
    )
    universal_application_module.rewire_incidence(
        store, founder.focus_incidence, registry.application_root
    )
    snapshot = store.snapshot()
    patches = (
        universal_application_module.prepare_append_relation_members(
            snapshot,
            registry.canvas_root,
            (
                (roles["member"], registry.application_root),
                (roles["member"], registry.library_root),
            ),
            budget=100_000,
        ),
        universal_application_module.prepare_append_relation_members(
            snapshot,
            founder.visibility_root,
            (
                (roles["visible"], registry.application_root),
                (roles["visible"], registry.library_root),
            ),
            budget=100_000,
        ),
        universal_application_module.prepare_append_relation_members(
            snapshot,
            founder.selection_state_root,
            (
                (roles["available"], registry.library_root),
                (roles["available"], first_domain),
            ),
            budget=100_000,
        ),
    )
    store.commit(
        snapshot.revision,
        create=tuple(cell for patch in patches for cell in patch.create),
        replace=tuple(cell for patch in patches for cell in patch.replace),
    )
    grants = universal_application_module._issue_view_projection_grants(
        store,
        registry.authorization,
        subject_root=registry.authorization.subject_root,
        visibility_root=founder.visibility_root,
        target_roots=(registry.application_root, registry.library_root),
        administrator_root=registry.authorization.subject_root,
    )
    grant_snapshot = store.snapshot()
    grant_patch = universal_application_module.prepare_append_relation_members(
        grant_snapshot,
        founder.root_id,
        ((roles["relation"], root) for root in grants),
        budget=100_000,
    )
    store.commit(
        grant_snapshot.revision,
        create=grant_patch.create,
        replace=grant_patch.replace,
    )
    stale_incidences = {
        member.incidence_id
        for root in (
            registry.canvas_root,
            founder.visibility_root,
            founder.selection_state_root,
        )
        for member in read_relation(store.snapshot(), root, budget=100_000)
        if member.participant_id in registry.container_roots
    }

    store, restored = restore_universal_application(
        resolve_map_path(), store, key_provider=provider
    )
    containers = set(restored.container_roots)
    assert set(restored.visible_roots).isdisjoint(containers)
    restored_founder = restored.view_sessions[restored.authorization.subject_root]
    for root in (
        restored.canvas_root,
        restored_founder.visibility_root,
        restored_founder.selection_state_root,
    ):
        assert all(
            member.participant_id not in containers
            for member in read_relation(store.snapshot(), root, budget=100_000)
        )
    focused = next(
        member.participant_id
        for member in read_relation(
            store.snapshot(), restored_founder.properties_lens_root,
            budget=100_000,
        )
        if member.role_id == roles["focus"]
    )
    focus = read_focus(
        store.snapshot(), restored.attention_protocol, focused
    )
    assert focus.state_root == restored.attention_protocol.state("active")
    assert focus.primary_root in restored.visible_roots
    assert stale_incidences <= set(store.snapshot().cells)
    for grant_root in grants:
        relationship = universal_application_module.verify_authority_relationship(
            store.snapshot(),
            restored.authorization.identity_protocol,
            restored.authorization.relationship_broker,
            grant_root,
            require_active=False,
        )
        assert (
            relationship.state_root
            == restored.authorization.identity_protocol.states["revoked"]
        )

    migrated_revision = store.revision
    store, restored_again = restore_universal_application(
        resolve_map_path(), store, key_provider=provider
    )
    assert store.revision == migrated_revision
    assert restored_again.visible_roots == restored.visible_roots
