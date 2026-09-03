"""Forcing courts for the public website as a universal graph lens."""
from __future__ import annotations

import base64
import hashlib
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nodelang.application_server import ApplicationServer  # noqa: E402
from nodelang.cell_protocols import read_relation  # noqa: E402
from nodelang.cell_website import (  # noqa: E402
    PUBLIC_WEBSITE_ROUTES,
    project_universal_website_document,
    read_universal_website,
)
from nodelang.map_import import resolve_map_path  # noqa: E402
from nodelang.universal_application import build_universal_application  # noqa: E402
from nodelang.universal_cell import Cell  # noqa: E402


@pytest.fixture(scope="module")
def application():
    return build_universal_application(resolve_map_path())


def _replace_participant(store, incidence_root, participant_root):
    incidence = store.read(incidence_root)
    store.commit(store.revision, replace=(Cell(
        incidence.id, incidence.link0, participant_root, incidence.atom
    ),))


def test_website_is_the_same_application_graph_with_exact_routes(application):
    store, registry = application
    website = read_universal_website(
        store.snapshot(), registry.website.protocol, registry.website.root_id,
        application_root=registry.application_root,
        application_member_role=registry.roles["member"],
        ui_protocol=registry.ui_protocol,
        map_registry=registry.map,
        cloud_route_protocol=registry.cloud_route_protocol,
        published_lifecycle_root=(
            registry.standard_library.lifecycle_protocol.states["published"]
        ),
        read_action_root=registry.authorization.protocol.actions["read"],
    )
    application_members = read_relation(
        store.snapshot(), registry.application_root, budget=100_000
    )
    assert any(
        member.role_id == registry.roles["member"]
        and member.participant_id == website.root_id
        for member in application_members
    )
    assert set(website.route_roots) == set(PUBLIC_WEBSITE_ROUTES)
    assert set(website.page_roots) == set(PUBLIC_WEBSITE_ROUTES)
    assert set(website.cloud_route_roots) == set(PUBLIC_WEBSITE_ROUTES)
    assert all(
        website.route_roots[path]
        in {member.participant_id for member in read_relation(
            store.snapshot(), website.root_id, budget=1_000
        )}
        for path in PUBLIC_WEBSITE_ROUTES
    )


def test_every_public_domain_card_is_explicitly_bound_to_the_real_domain(application):
    store, registry = application
    website = read_universal_website(
        store.snapshot(), registry.website.protocol, registry.website.root_id,
        application_root=registry.application_root,
        application_member_role=registry.roles["member"],
        ui_protocol=registry.ui_protocol,
        map_registry=registry.map,
        cloud_route_protocol=registry.cloud_route_protocol,
        published_lifecycle_root=(
            registry.standard_library.lifecycle_protocol.states["published"]
        ),
        read_action_root=registry.authorization.protocol.actions["read"],
    )
    assert set(website.domain_binding_roots) == set(registry.map.domains)
    assert {
        key: binding.domain_root
        for key, binding in website.domain_binding_roots.items()
    } == dict(registry.map.domains)
    assert len({
        binding.card_root for binding in website.domain_binding_roots.values()
    }) == len(registry.map.domains)


def test_graph_text_edit_changes_the_public_projection(application):
    store, registry = build_universal_application(resolve_map_path())
    before = project_universal_website_document(
        store, registry.website, "/website/features",
        application_root=registry.application_root,
        application_member_role=registry.roles["member"],
        map_registry=registry.map,
        cloud_route_protocol=registry.cloud_route_protocol,
    )
    title_root = registry.website.route_title_roots["/website/features"]
    title = store.read(title_root)
    store.commit(store.revision, replace=(Cell(
        title.id, title.link0, title.link1, b"Features from the live graph"
    ),))
    after = project_universal_website_document(
        store, registry.website, "/website/features",
        application_root=registry.application_root,
        application_member_role=registry.roles["member"],
        map_registry=registry.map,
        cloud_route_protocol=registry.cloud_route_protocol,
    )
    assert before != after
    assert "Features from the live graph" in after


def test_public_projection_is_semantic_scriptless_and_private_data_free(application):
    store, registry = application
    document = project_universal_website_document(
        store, registry.website, "/website",
        application_root=registry.application_root,
        application_member_role=registry.roles["member"],
        map_registry=registry.map,
        cloud_route_protocol=registry.cloud_route_protocol,
    )
    assert document.count("<main") == 1
    assert "<nav" in document and 'aria-label="Primary"' in document
    assert '<h1' in document and "ArchHub" in document
    assert 'aria-current="page"' in document
    assert "<script" not in document
    assert ":focus-visible" in document
    for private in (
        r"C:\Users", "30.KNOWLEDGE", "20.CLIENTS", "60.PERSONAL",
        "op://", "bootstrap=", "archhub-csrf", "app:authorization",
    ):
        assert private not in document


def test_personal_theme_preview_cannot_change_public_website(application):
    store, registry = build_universal_application(resolve_map_path())
    before = project_universal_website_document(
        store, registry.website, "/website",
        application_root=registry.application_root,
        application_member_role=registry.roles["member"],
        map_registry=registry.map,
        cloud_route_protocol=registry.cloud_route_protocol,
    )
    accent_root = registry.presentation.theme_roots["accent"]
    accent = store.read(accent_root)
    store.commit(store.revision, replace=(Cell(
        accent.id, accent.link0, accent.link1, b"#00ff00"
    ),))
    after = project_universal_website_document(
        store, registry.website, "/website",
        application_root=registry.application_root,
        application_member_role=registry.roles["member"],
        map_registry=registry.map,
        cloud_route_protocol=registry.cloud_route_protocol,
    )
    assert before == after


@pytest.mark.parametrize("field", ("classification", "lifecycle-state"))
def test_public_projection_refuses_policy_tamper(field):
    store, registry = build_universal_application(resolve_map_path())
    relation = read_relation(
        store.snapshot(), registry.website.root_id, budget=1_000
    )
    role = registry.website.protocol.role(field)
    incidence = next(member.incidence_id for member in relation if member.role_id == role)
    _replace_participant(store, incidence, registry.authorization.classification_root)
    with pytest.raises(Exception):
        project_universal_website_document(
            store, registry.website, "/website",
            application_root=registry.application_root,
            application_member_role=registry.roles["member"],
            map_registry=registry.map,
            cloud_route_protocol=registry.cloud_route_protocol,
        )


def test_server_website_route_uses_no_legacy_store_or_registry(application):
    store, registry = application
    server = ApplicationServer(
        universal_store=store,
        universal_registry=registry,
    ).start()
    legacy_store, legacy_registry = server.store, server.registry

    class ForbiddenLegacy:
        def __getattribute__(self, _name):
            raise AssertionError("website touched the legacy runtime")

        def __getitem__(self, _name):
            raise AssertionError("website touched the legacy runtime")

    try:
        server.store = ForbiddenLegacy()
        server.registry = ForbiddenLegacy()
        response = urllib.request.urlopen(server.url + "/website", timeout=10)
        document = response.read().decode("utf-8")
        assert 'class="site-shell"' in document
        assert response.headers["X-ArchHub-Graph-Root"] == registry.website.root_id
        stylesheet = store.read(registry.website.stylesheet_root).atom
        digest = base64.b64encode(hashlib.sha256(stylesheet).digest()).decode("ascii")
        assert "style-src 'sha256-%s'" % digest in response.headers[
            "Content-Security-Policy"
        ]
    finally:
        server.store, server.registry = legacy_store, legacy_registry
        server.close()


def test_unknown_website_route_is_not_projected(application):
    store, registry = application
    server = ApplicationServer(
        universal_store=store,
        universal_registry=registry,
    ).start()
    try:
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(server.url + "/website/not-a-route", timeout=10)
        assert error.value.code == 404
    finally:
        server.close()
