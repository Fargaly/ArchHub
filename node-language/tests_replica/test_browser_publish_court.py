"""Real-browser publication courts over exact Shared theme revisions."""
from pathlib import Path
import shutil

import pytest

from nodelang.application_server import ApplicationServer
from nodelang.cell_attestations import CourtEvidenceDenied
from nodelang.cell_lifecycle import (
    read_lifecycle_instance,
    read_revision,
    state_heads,
)
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    assign_released_universal_theme,
    build_universal_application,
    preview_universal_theme,
    project_universal_canvas,
    promote_universal_theme_to_published,
    promote_universal_theme_to_shared,
    provision_universal_view_session,
    read_universal_theme,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell


ROOT = Path(__file__).resolve().parents[1]


def _browser_environment(monkeypatch):
    node = shutil.which("node")
    modules = ROOT / "node_modules"
    chrome = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
    if not node or not modules.joinpath("playwright", "package.json").is_file() \
            or not chrome.exists():
        pytest.skip("local real-browser court runtime is unavailable")
    monkeypatch.setenv("ARCHHUB_NODE_EXECUTABLE", node)
    monkeypatch.setenv("ARCHHUB_NODE_MODULE_PATH", str(modules))
    monkeypatch.setenv("ARCHHUB_CHROME_EXECUTABLE", str(chrome))


def _application_server(monkeypatch):
    _browser_environment(monkeypatch)
    store, registry = build_universal_application(resolve_map_path())
    server = ApplicationServer(
        universal_store=store, universal_registry=registry
    ).start()
    return store, registry, server


def test_real_browser_court_publishes_exact_shared_revision(monkeypatch):
    store, registry, server = _application_server(monkeypatch)
    try:
        source = preview_universal_theme(
            store, registry, {"accent": "#d97757"}
        )
        shared, _ = promote_universal_theme_to_shared(
            store, registry, source_revision_root=source
        )
        published, evidence = promote_universal_theme_to_published(
            store, registry, source_revision_root=shared
        )
        snapshot = store.snapshot()
        lifecycle = registry.standard_library.lifecycle_protocol
        view = registry.view_sessions[registry.authorization.subject_root]
        instance = read_lifecycle_instance(
            snapshot, registry.assembly_protocol, lifecycle, view.settings_root
        )
        assert state_heads(
            snapshot,
            lifecycle,
            instance.state_pointers[lifecycle.states["published"]],
        ) == (published,)
        revision = read_revision(snapshot, lifecycle, published)
        assert revision.predecessor_roots == (shared,)
        assert revision.evidence_roots == (evidence,)
        projection = project_universal_canvas(store, registry)
        projected = next(
            item for item in projection["configuration"]["history"]
            if item["revision"] == published
        )
        proof = projected["evidence"][0]
        assert proof["court"] == registry.theme_publish_court_root
        assert proof["result"] == "passed"
        assert len(proof["checks"]) == 10
        assert all(proof["checks"].values())
        assert projection["configuration"]["published_revision"] == published

        member = "test:identity:published-theme-member"
        store.commit(store.revision, create=(
            Cell(member, NULL_CELL_ID, NULL_CELL_ID, b"Published member"),
        ))
        provision_universal_view_session(store, registry, member)
        context = registry.authorization.broker.mint_authenticated_context(
            member,
            tenant_root=registry.authorization.tenant_root,
            assurance_root=registry.authorization.assurance_root,
            lifetime_seconds=120,
        )
        assign_released_universal_theme(store, registry, member, published)
        theme, metadata = read_universal_theme(
            store, registry, authentication_context=context
        )
        assert theme["accent"] == "#d97757"
        assert metadata["preview_revision"] == published
        assert metadata["state"] == "PUBLISHED"
        assert metadata["binding_mode"] == "direct-release"
    finally:
        server.close()


def test_browser_court_rejects_low_contrast_shared_theme(monkeypatch):
    store, registry, server = _application_server(monkeypatch)
    try:
        source = preview_universal_theme(
            store, registry, {"ink": "#111111"}
        )
        shared, _ = promote_universal_theme_to_shared(
            store, registry, source_revision_root=source
        )
        with pytest.raises(CourtEvidenceDenied, match="exact promotion"):
            promote_universal_theme_to_published(
                store, registry, source_revision_root=shared
            )
        snapshot = store.snapshot()
        lifecycle = registry.standard_library.lifecycle_protocol
        view = registry.view_sessions[registry.authorization.subject_root]
        instance = read_lifecycle_instance(
            snapshot, registry.assembly_protocol, lifecycle, view.settings_root
        )
        assert state_heads(
            snapshot,
            lifecycle,
            instance.state_pointers[lifecycle.states["published"]],
        ) == ()
    finally:
        server.close()
