"""The application admits cognition as governed graph assemblies, not hidden AI."""

import pytest

from nodelang.cell_catalog import verify_released_catalog
from nodelang.cell_composer import verify_composer_authority
from nodelang.cell_protocols import read_relation
from nodelang.cell_tenant_authority import published_tenant_authority
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    _COMPOSER_AUTHORITY_V7,
    _STANDARD_CATALOG_V2,
    _STANDARD_CATALOG_V5,
    _STANDARD_CATALOG_V6,
    build_universal_application,
    project_universal_canvas,
    select_universal_root,
    set_universal_scope,
)


@pytest.fixture(scope="module")
def cognition_application():
    return build_universal_application(resolve_map_path())


def test_cognition_extends_the_immutable_catalogue_without_rewriting_v2(
    cognition_application,
):
    store, registry = cognition_application
    snapshot = store.snapshot()
    v2 = verify_released_catalog(
        snapshot, registry.assembly_protocol, _STANDARD_CATALOG_V2
    )
    v5 = verify_released_catalog(
        snapshot, registry.assembly_protocol, _STANDARD_CATALOG_V5
    )
    v6 = verify_released_catalog(
        snapshot, registry.assembly_protocol, _STANDARD_CATALOG_V6
    )
    cognition_roots = registry.agent_body.cognition_definitions.roots
    governed_work_root = (
        registry.standard_library.governed_domains
        .definitions["governed-work"].definition_root
    )

    assert registry.standard_library.catalog_root == _STANDARD_CATALOG_V6
    assert set(v5.definition_roots) == {
        *v2.definition_roots,
        *cognition_roots,
    }
    assert set(v6.definition_roots) == {
        *v5.definition_roots,
        governed_work_root,
    }
    assert set(v2.definition_roots).isdisjoint(cognition_roots)
    assert governed_work_root not in v5.definition_roots

    composer = verify_composer_authority(
        snapshot,
        registry.composer_protocol,
        registry.assembly_protocol,
        registry.adapter_protocol,
        _COMPOSER_AUTHORITY_V7,
    )
    assert composer.catalogue_root == _STANDARD_CATALOG_V6
    assert registry.composer_authority.root_id == _COMPOSER_AUTHORITY_V7

    tenant = published_tenant_authority(
        snapshot,
        registry.tenant_configuration_protocol,
        registry.assembly_protocol,
        registry.standard_library.lifecycle_protocol,
        registry.authorization.protocol,
        registry.authorization.identity_protocol,
        registry.authorization.relationship_broker,
        tenant_root=registry.authorization.tenant_root,
    )
    assert tenant.catalogue_root == _STANDARD_CATALOG_V6


def test_cognition_is_an_enterable_models_and_agents_region_not_a_side_system(
    cognition_application,
):
    store, registry = cognition_application
    snapshot = store.snapshot()
    cognition = registry.agent_body.cognition_protocol
    definitions = registry.agent_body.cognition_definitions
    expected = {
        cognition.root_id,
        definitions.status_ledger_root,
        *cognition.registries.values(),
        *definitions.roots,
    }

    model_members = {
        member.participant_id
        for member in read_relation(
            snapshot, registry.map.domains["models"], budget=100_000
        )
    }
    application_members = {
        member.participant_id
        for member in read_relation(
            snapshot, registry.application_root, budget=100_000
        )
    }
    assert expected <= model_members
    assert expected <= application_members

    for registry_root in cognition.registries.values():
        assert read_relation(snapshot, registry_root, budget=64) == ()

    assert registry.agent_body.body.model_binding_root is None
    assert registry.agent_body.session.model_binding_root is None
    assert registry.agent_body.session.proposal_roots == ()


def test_founder_can_enter_select_and_inspect_each_cognition_root(
    cognition_application,
):
    store, registry = cognition_application
    cognition = registry.agent_body.cognition_protocol
    definitions = registry.agent_body.cognition_definitions
    expected = {
        cognition.root_id,
        definitions.status_ledger_root,
        *cognition.registries.values(),
        *definitions.roots,
    }

    set_universal_scope(store, registry, registry.map.domains["models"])
    scoped = project_universal_canvas(store, registry)
    projected = {node["id"]: node for node in scoped["nodes"]}
    assert expected <= set(projected)
    assert all(projected[root]["label"] for root in expected)
    assert projected[cognition.root_id]["openable"] is True
    assert all(projected[root]["openable"] for root in definitions.roots)

    select_universal_root(store, registry, definitions.proposal_root)
    selected = project_universal_canvas(store, registry)
    assert selected["selected"] == definitions.proposal_root
    assert {row["label"] for row in selected["properties"]}.issuperset({
        "title",
        "color",
    })


def test_agent_body_and_session_expose_live_state_without_editable_copies(
    cognition_application,
):
    store, registry = cognition_application
    body = registry.agent_body.body
    session = registry.agent_body.session

    set_universal_scope(store, registry, registry.map.domains["models"])
    expected = {
        body.root_id: {
            "state": "active",
            "lifecycle": "WIP",
            "model binding": "unbound",
        },
        session.root_id: {
            "state": "active",
            "focus": "unbound",
            "assignment": "unbound",
            "model binding": "unbound",
        },
    }
    for root, values in expected.items():
        select_universal_root(store, registry, root)
        projection = project_universal_canvas(store, registry)
        properties = {
            row["label"]: row for row in projection["properties"]
        }
        for label, value in values.items():
            assert properties[label]["value"] == value
            assert properties[label]["editable"] is False


def test_status_ledger_is_a_named_selectable_graph_surface(
    cognition_application,
):
    store, registry = cognition_application
    ledger_root = registry.agent_body.cognition_definitions.status_ledger_root

    set_universal_scope(store, registry, registry.map.domains["models"])
    select_universal_root(store, registry, ledger_root)
    projection = project_universal_canvas(store, registry)

    assert projection["selected"] == ledger_root
    assert projection["selected_title"] == "Model Status Ledger"
    assert {row["label"] for row in projection["properties"]}.issuperset({
        "title",
        "color",
    })
    assert all(
        panel["id"] != registry.properties_panel_roots["floor"]
        for panel in projection["inspector"]["presentation"]["panels"]
    )
