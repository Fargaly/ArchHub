"""Forcing tests for the T0 website graph export boundary."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nodelang.application_server import ApplicationServer  # noqa: E402
from nodelang.cell_accounts import BETA_OFFER  # noqa: E402
from nodelang.map_import import PUBLIC_MAP_PATH  # noqa: E402
from nodelang.site_export import (  # noqa: E402
    PUBLIC_ROUTES,
    SiteExportError,
    build_site_export,
    offer_digest,
    website_offer,
    write_public_site,
)
from nodelang.universal_application import (  # noqa: E402
    build_universal_application,
)
from nodelang.universal_cell import Cell  # noqa: E402


@pytest.fixture(scope="module")
def application():
    return build_universal_application(PUBLIC_MAP_PATH)


def _replace_atom(store, root_id, value):
    cell = store.read(root_id)
    store.commit(store.revision, replace=(Cell(
        cell.id, cell.link0, cell.link1, value.encode("utf-8")
    ),))


def test_export_is_complete_deterministic_and_provenanced_by_route_cells(application):
    store, registry = application
    first = build_site_export(store, registry)
    second = build_site_export(store, registry)
    assert first == second
    assert first["format"] == "archhub-universal-cell-site-v2"
    assert first["publication_tier"] == "T0 PUBLIC"
    assert first["application_root"] == registry.application_root
    assert first["website_root"] == registry.website.root_id
    assert len(first["website_fingerprint"]) == 64
    assert tuple(first["routes"]) == PUBLIC_ROUTES
    for route, record in first["routes"].items():
        assert record["root_node"] == registry.website.page_roots[route]
        assert len(record["source_fingerprint"]) == 64
        assert record["source_roots"] == {
            "route": registry.website.route_roots[route],
            "page": registry.website.page_roots[route],
            "http_route": registry.website.cloud_route_roots[route],
            "stylesheet": registry.website.stylesheet_root,
            "title": registry.website.route_title_roots[route],
        }
        assert record["output_path"] == (
            "index.html" if route == "/website"
            else route.rsplit("/", 1)[1] + "/index.html"
        )


def test_export_is_reproducible_from_fresh_public_seed_builds():
    first_store, first_registry = build_universal_application(PUBLIC_MAP_PATH)
    second_store, second_registry = build_universal_application(PUBLIC_MAP_PATH)

    assert build_site_export(first_store, first_registry) == build_site_export(
        second_store, second_registry
    )


def test_checked_in_public_site_export_is_generated_from_current_cell_authority():
    project = Path(__file__).resolve().parents[1] / "public_site"
    checked_in = json.loads((project / "site-export.json").read_text(
        encoding="utf-8"
    ))
    offer = checked_in.get("offer")
    store, registry = build_universal_application(
        PUBLIC_MAP_PATH,
        offer=None if offer is None else website_offer(offer),
    )
    expected = build_site_export(
        store, registry,
        offer=offer,
        offer_sha256=checked_in.get("offer_sha256"),
        origin=checked_in.get("origin"),
    )

    # The checked-in export is the real record at the real origin, never a
    # self-consistent export of some other offer or a staging origin.
    assert offer == dict(BETA_OFFER)
    assert checked_in.get("offer_sha256") == offer_digest(BETA_OFFER)
    assert checked_in.get("origin") == "https://archhub.io"
    assert checked_in == expected


def test_export_changes_only_when_resolved_graph_state_changes():
    store, registry = build_universal_application(PUBLIC_MAP_PATH)
    before = build_site_export(store, registry)
    title = registry.website.route_title_roots["/website/features"]
    _replace_atom(store, title, "Graph-authored features")
    after = build_site_export(store, registry)
    assert before["export_sha256"] != after["export_sha256"]
    assert before["routes"]["/website/features"]["source_fingerprint"] != (
        after["routes"]["/website/features"]["source_fingerprint"])
    assert before["routes"]["/website/features"]["html_sha256"] != (
        after["routes"]["/website/features"]["html_sha256"])
    assert "Graph-authored features" in after["routes"]["/website/features"]["html"]
    assert before["routes"]["/website/pricing"] == after["routes"]["/website/pricing"]
    assert before["website_fingerprint"] == after["website_fingerprint"]


def test_non_public_tier_and_private_projection_values_are_refused():
    store, registry = build_universal_application(PUBLIC_MAP_PATH)
    _replace_atom(store, registry.website.classification_root, "T1 INTERNAL")
    with pytest.raises(SiteExportError, match="classified T0|publication tier"):
        build_site_export(store, registry)

    store, registry = build_universal_application(PUBLIC_MAP_PATH)
    title = registry.website.route_title_roots["/website/features"]
    _replace_atom(
        store,
        title,
        r"C:\Users\founder\00.ARCHUB\30.KNOWLEDGE\grand-map.json",
    )
    with pytest.raises(
        SiteExportError,
        match="private text|local user path|non-public workspace area",
    ):
        build_site_export(store, registry)


def test_public_payload_has_navigation_but_no_runtime_or_private_leakage(application):
    store, registry = application
    payload = build_site_export(store, registry)
    raw = json.dumps(payload, sort_keys=True)
    for forbidden in (
        r"C:\Users", "30.KNOWLEDGE", "12.PRODUCTION", "op://",
        "/api/activate", "/api/edit", "ARCHHUB_GRAND_MAP_PATH",
    ):
        assert forbidden not in raw
    for record in payload["routes"].values():
        assert 'href="/features/"' in record["html"]
        assert 'href="/pricing/"' in record["html"]
        assert 'href="/website' not in record["html"]
        assert "<script" not in record["html"]
        assert "data-action" not in record["html"]
        assert "data-edit" not in record["html"]
        assert "data-navigate" not in record["html"]


def test_legacy_registry_cannot_enter_the_publication_boundary():
    with pytest.raises(SiteExportError, match="universal application registry"):
        build_site_export(object(), {"website": {}})


def test_application_site_export_route_is_graph_declared_and_legacy_free():
    store, registry = build_universal_application(PUBLIC_MAP_PATH)
    assert "GET /api/universal/site-export" in (
        registry.application_http_route_roots
    )
    server = ApplicationServer(
        universal_store=store,
        universal_registry=registry,
    ).start()
    legacy_store, legacy_registry = server.store, server.registry

    class ForbiddenLegacy:
        def __getattribute__(self, _name):
            raise AssertionError("site export touched the legacy runtime")

        def __getitem__(self, _name):
            raise AssertionError("site export touched the legacy runtime")

    try:
        server.store = ForbiddenLegacy()
        server.registry = ForbiddenLegacy()
        request = urllib.request.Request(
            server.url + "/api/universal/site-export",
            headers={"X-ArchHub-Session": server.browser_session_token},
        )
        response = urllib.request.urlopen(request, timeout=20)
        payload = json.loads(response.read())
        assert payload["format"] == "archhub-universal-cell-site-v2"
        assert payload["website_root"] == registry.website.root_id
        assert response.headers["X-ArchHub-Classification"] == "T0 PUBLIC"
        assert response.headers["X-ArchHub-Graph-Root"] == registry.website.root_id
        assert response.headers["Content-Disposition"].endswith(
            'archhub-public-site-v2.json"'
        )
    finally:
        server.store, server.registry = legacy_store, legacy_registry
        server.close()


def test_application_site_export_route_fails_closed_after_policy_tamper():
    store, registry = build_universal_application(PUBLIC_MAP_PATH)
    server = ApplicationServer(
        universal_store=store,
        universal_registry=registry,
    ).start()
    try:
        _replace_atom(store, registry.website.classification_root, "T1 INTERNAL")
        request = urllib.request.Request(
            server.url + "/api/universal/site-export",
            headers={"X-ArchHub-Session": server.browser_session_token},
        )
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request, timeout=20)
        assert error.value.code == 503
        assert json.loads(error.value.read())["error"] == (
            "universal website export is unavailable"
        )
    finally:
        server.close()


def test_written_site_is_a_static_root_tree_with_no_scaffold_or_readme(
    application, tmp_path
):
    store, registry = application
    project = tmp_path / "public-site"
    payload = write_public_site(store, registry, project)
    written = sorted(
        path.relative_to(project).as_posix()
        for path in project.rglob("*") if path.is_file()
    )
    assert written == [
        ".gitignore", "dist/404.html", "dist/assets/site.css",
        "dist/changelog/index.html", "dist/community/index.html",
        "dist/features/index.html", "dist/index.html",
        "dist/pricing/index.html", "dist/security/index.html",
        "dist/signin/index.html", "site-export.json",
    ]
    assert (project / "dist/assets/site.css").read_text(encoding="utf-8") == (
        payload["assets"]["assets/site.css"]
    )
    for record in payload["routes"].values():
        rendered = project / "dist" / record["output_path"]
        assert rendered.read_text(encoding="utf-8") == record["html"]
    assert json.loads(
        (project / "site-export.json").read_text(encoding="utf-8")
    ) == payload
