"""W6: a graph opens on the newer code and adopts the website as a revision.

SPEC 4.5 holds an instance to the contract it was published with until an
explicit adoption. A graph published before the docs pages holds the seven
core routes. The code that now declares twelve opens that graph, adopts the
newer revision through the website revision path, records what it adopted,
and leaves the seven published pages exactly the Cells that published them:
they stay readable as the earlier revision. A website changed by hand is not
a published revision. It is refused for that edit, and the clean graph beside
it still opens, so the refusal is never a refusal of the revision itself.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nodelang.cell_website as cell_website  # noqa: E402
from nodelang.cell_secret_keys import MemorySigningKeyProvider  # noqa: E402
from nodelang.cell_website import (  # noqa: E402
    CORE_WEBSITE_ROUTES,
    PUBLIC_WEBSITE_ROUTES,
    project_universal_website_document,
)
from nodelang.map_import import PUBLIC_MAP_PATH  # noqa: E402
from nodelang.universal_application import (  # noqa: E402
    build_universal_application,
    restore_universal_application,
)
from nodelang.universal_cell import Cell, CellStore, InvalidCell  # noqa: E402


def website_definition_revisions(snapshot):
    """The recorded revisions; a build without the revision path records none."""
    reader = getattr(cell_website, "website_definition_revisions", None)
    return () if reader is None else reader(snapshot)


def _provider():
    provider = MemorySigningKeyProvider(
        "archhub.local.relationship-authority", b"w" * 32
    )
    provider.add_key("archhub.local.court-attestation", b"6" * 32)
    return provider


def _published_before_the_docs_pages(provider):
    """One application graph exactly as the earlier definition published it."""
    with pytest.MonkeyPatch.context() as scoped:
        scoped.setattr(cell_website, "_docs_pages", lambda: {})
        store, registry = build_universal_application(
            PUBLIC_MAP_PATH, CellStore(), key_provider=provider,
        )
    assert set(registry.website.route_roots) == set(CORE_WEBSITE_ROUTES)
    return store, registry


def test_an_earlier_revision_opens_adopts_and_keeps_the_pages_it_published():
    provider = _provider()
    store, registry = _published_before_the_docs_pages(provider)
    published = {
        path: store.read(root)
        for path, root in registry.website.page_roots.items()
    }

    store, restored = restore_universal_application(
        PUBLIC_MAP_PATH, store, key_provider=provider,
    )

    assert set(restored.website.route_roots) == set(PUBLIC_WEBSITE_ROUTES)
    # The pages the earlier revision published are the same Cells, untouched.
    for path, cell in published.items():
        assert restored.website.page_roots[path] == cell.id
        assert store.read(cell.id) == cell
    records = website_definition_revisions(store.snapshot())
    assert len(records) == 2, records
    assert records[0].startswith("website definition revision 1")
    assert "routes: %s" % ",".join(CORE_WEBSITE_ROUTES) in records[0]
    assert records[1].startswith("website definition revision 2")
    assert "previous: app:website:definition:revision:1" in records[1]
    adopted = tuple(
        path for path in PUBLIC_WEBSITE_ROUTES
        if path not in CORE_WEBSITE_ROUTES
    )
    assert "adopted: %s" % ",".join(adopted) in records[1]

    home = project_universal_website_document(
        store, restored.website, "/website",
        application_root=restored.application_root,
        application_member_role=restored.roles["member"],
        map_registry=restored.map,
        cloud_route_protocol=restored.cloud_route_protocol,
    )
    assert "site-footer" in home
    for path in adopted:
        page = project_universal_website_document(
            store, restored.website, path,
            application_root=restored.application_root,
            application_member_role=restored.roles["member"],
            map_registry=restored.map,
            cloud_route_protocol=restored.cloud_route_protocol,
        )
        assert "site-doc-body" in page


def test_a_second_boot_adopts_nothing_a_second_time():
    provider = _provider()
    store, registry = _published_before_the_docs_pages(provider)
    store, restored = restore_universal_application(
        PUBLIC_MAP_PATH, store, key_provider=provider,
    )
    records = website_definition_revisions(store.snapshot())
    revision = store.revision
    again = cell_website.ensure_universal_website(
        store,
        application_root=restored.application_root,
        application_member_role=restored.roles["member"],
        ui_protocol=restored.ui_protocol,
        cloud_route_protocol=restored.cloud_route_protocol,
        map_registry=restored.map,
        published_lifecycle_root=restored.website.lifecycle_root,
        read_action_root=restored.website.read_action_root,
        adopt=True,
    )
    assert store.revision == revision
    assert set(again.route_roots) == set(PUBLIC_WEBSITE_ROUTES)
    assert website_definition_revisions(store.snapshot()) == records


def test_a_hand_edited_website_is_refused_while_the_clean_graph_opens():
    provider = _provider()
    edited, registry = _published_before_the_docs_pages(provider)
    path_root = "app:website:path:%s" % cell_website._part("/website/features")
    cell = edited.read(path_root)
    edited.commit(edited.revision, replace=(Cell(
        cell.id, cell.link0, cell.link1, b"/website/labs",
    ),))
    with pytest.raises(InvalidCell) as refused:
        restore_universal_application(
            PUBLIC_MAP_PATH, edited, key_provider=provider,
        )
    # Refused for the edit, and nothing was adopted over it.
    assert "public website route graph drifted" not in str(refused.value)
    assert website_definition_revisions(edited.snapshot()) == ()

    clean, _ = _published_before_the_docs_pages(provider)
    clean, restored = restore_universal_application(
        PUBLIC_MAP_PATH, clean, key_provider=provider,
    )
    assert set(restored.website.route_roots) == set(PUBLIC_WEBSITE_ROUTES)