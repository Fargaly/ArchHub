"""Forcing tests for the T0 website graph export boundary."""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nodelang.application_server import ApplicationServer  # noqa: E402
from nodelang.map_import import PUBLIC_MAP_PATH  # noqa: E402
from nodelang.site_export import (  # noqa: E402
    PUBLIC_ROUTES,
    SiteExportError,
    build_site_export,
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
        assert record["output_path"] == route.strip("/") + "/index.html"


def test_export_is_reproducible_from_fresh_public_seed_builds():
    first_store, first_registry = build_universal_application(PUBLIC_MAP_PATH)
    second_store, second_registry = build_universal_application(PUBLIC_MAP_PATH)

    assert build_site_export(first_store, first_registry) == build_site_export(
        second_store, second_registry
    )


def test_checked_in_public_site_export_is_generated_from_current_cell_authority():
    store, registry = build_universal_application(PUBLIC_MAP_PATH)
    expected = build_site_export(store, registry)
    project = Path(__file__).resolve().parents[1] / "public_site"

    assert json.loads((project / "site-export.json").read_text(
        encoding="utf-8"
    )) == expected


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
        assert 'href="/website/features"' in record["html"]
        assert 'href="/website/pricing"' in record["html"]
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


def test_dependency_free_build_is_valid_for_sites_and_cloudflare(application, tmp_path):
    store, registry = application
    project = tmp_path / "public-site"
    payload = write_public_site(store, registry, project)
    result = subprocess.run(
        ["node", "build.mjs"], cwd=project, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (project / "dist/server/index.js").is_file()
    assert (project / "dist/.openai/hosting.json").is_file()
    assert (project / "dist/client/assets/site.css").is_file()
    assert (project / "dist/client/index.html").is_file()
    assert (project / "dist/client/404.html").is_file()
    for record in payload["routes"].values():
        rendered = project / "dist/client" / record["output_path"]
        assert rendered.read_text(encoding="utf-8") == record["html"]
    worker_check = subprocess.run(
        ["node", "--check", str(project / "dist/server/index.js")],
        capture_output=True, text=True)
    assert worker_check.returncode == 0, worker_check.stderr


def test_build_refuses_tampered_graph_export(application, tmp_path):
    store, registry = application
    project = tmp_path / "tampered-site"
    write_public_site(store, registry, project)
    source = json.loads((project / "site-export.json").read_text(encoding="utf-8"))
    source["routes"]["/website"]["html"] += "<!-- tampered -->"
    (project / "site-export.json").write_text(json.dumps(source), encoding="utf-8")
    result = subprocess.run(
        ["node", "build.mjs"], cwd=project, capture_output=True, text=True)
    assert result.returncode != 0
    assert "seal is invalid" in result.stderr


def test_regeneration_preserves_the_single_sites_identity(application, tmp_path):
    store, registry = application
    project = tmp_path / "public-site"
    write_public_site(store, registry, project)
    hosting = project / ".openai" / "hosting.json"
    hosting.write_text(json.dumps({
        "project_id": "site-authority-opaque", "d1": None, "r2": None,
    }), encoding="utf-8")
    write_public_site(store, registry, project)
    assert json.loads(hosting.read_text(encoding="utf-8")) == {
        "project_id": "site-authority-opaque", "d1": None, "r2": None,
    }
