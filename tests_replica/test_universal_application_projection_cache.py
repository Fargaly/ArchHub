"""Performance courts for graph projections that never weaken authority."""

from collections.abc import Mapping
from time import perf_counter

import pytest

import nodelang.cell_catalog as catalog_module
import nodelang.cell_protocols as protocol_module
import nodelang.universal_application as application_module
import nodelang.application_server as server_module
from nodelang.application_server import ApplicationServer
from nodelang.cell_catalog import (
    verify_released_catalog,
    verify_released_catalog_stable,
)
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    apply_universal_canvas_gesture,
    build_universal_application,
    ensure_universal_properties_panel_interactions,
    project_universal_canvas,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, InvalidCell, Snapshot


@pytest.fixture(scope="module")
def application():
    return build_universal_application(resolve_map_path())


def test_interface_projection_runs_once_per_unique_interface_in_one_request(
    application, monkeypatch
):
    store, registry = application
    original = application_module._project_canvas_interface_uncached
    projected_roots: list[str] = []

    def counted(snapshot, protocol, interface_root):
        projected_roots.append(interface_root)
        return original(snapshot, protocol, interface_root)

    monkeypatch.setattr(
        application_module, "_project_canvas_interface_uncached", counted
    )
    project_universal_canvas(store, registry)

    assert projected_roots
    assert len(projected_roots) == len(set(projected_roots))


def test_canvas_projection_uses_one_request_local_relation_cache(
    application, monkeypatch
):
    store, registry = application
    original = application_module.read_relation
    cache_identities: set[int] = set()

    def checked(snapshot, relation_root, **kwargs):
        cache = protocol_module._RELATION_PROJECTION_CACHE.get()
        assert cache is not None
        cache_identities.add(id(cache))
        return original(snapshot, relation_root, **kwargs)

    monkeypatch.setattr(application_module, "read_relation", checked)
    project_universal_canvas(store, registry)

    assert len(cache_identities) == 1


def test_canvas_projection_stays_inside_initial_server_latency_budget(
    application,
):
    store, registry = application
    started = perf_counter()
    projection = project_universal_canvas(store, registry)
    elapsed = perf_counter() - started

    assert projection["nodes"]
    assert projection["wires"]
    assert elapsed < 2.0


def test_interaction_projection_walks_the_visible_canvas_once(monkeypatch):
    store, registry = build_universal_application(resolve_map_path())
    server = ApplicationServer(
        universal_store=store, universal_registry=registry
    )
    binding = server._resolve_browser_session(server.browser_session_token)
    expected = project_universal_canvas(
        store, registry, authentication_context=binding.context
    )
    original = server_module.project_universal_canvas
    projected_revisions: list[int] = []

    def counted(*args, **kwargs):
        projection = original(*args, **kwargs)
        projected_revisions.append(projection["revision"])
        return projection

    monkeypatch.setattr(server_module, "project_universal_canvas", counted)
    projection = server.project_interaction_canvas(binding)

    assert len(projected_revisions) == 1
    assert projected_revisions[0] < projection["revision"]
    assert projection["revision"] == store.revision
    assert projection["interaction_projection"]["revision"] == store.revision
    expected_visible = dict(expected)
    expected_visible.pop("revision")
    actual_visible = dict(projection)
    actual_visible.pop("revision")
    actual_visible.pop("interaction_projection")
    assert actual_visible == expected_visible


def test_visible_scope_cache_is_revision_exact_and_request_local(monkeypatch):
    store, registry = build_universal_application(resolve_map_path())
    view_session = registry.view_sessions[
        registry.authorization.subject_root
    ]
    # The court holds that the scope derivation runs once per request
    # scope, and its counter must sit on the derivation this path actually
    # performs. _session_canvas_roots reads the graph-held visibility
    # projection; counting _canvas_scope_for_assigned -- which only the
    # provisioning and verification paths call -- measured a function this
    # path never enters, so the count was zero however the cache behaved.
    original = application_module._visibility_scope_projection
    calls = 0

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(
        application_module, "_visibility_scope_projection", counted
    )

    @application_module.with_session_canvas_roots_scope
    def project_twice():
        snapshot = store.snapshot()
        first = application_module._session_canvas_roots(
            snapshot, registry, view_session, include_trail=True
        )
        second = application_module._session_canvas_roots(
            snapshot, registry, view_session, include_trail=True
        )
        return first, second

    first, second = project_twice()
    assert first == second
    assert calls == 1
    project_twice()
    assert calls == 2


def test_standard_catalog_projection_survives_only_unrelated_revisions(
    monkeypatch,
):
    store, registry = build_universal_application(resolve_map_path())
    original = application_module.project_catalog
    calls = 0

    def counted(snapshot, protocol, catalog_root):
        nonlocal calls
        calls += 1
        return original(snapshot, protocol, catalog_root)

    monkeypatch.setattr(application_module, "project_catalog", counted)
    verified_first = verify_released_catalog_stable(
        store,
        store.snapshot(),
        registry.assembly_protocol,
        registry.standard_library.catalog_root,
    )
    first = application_module._project_standard_catalog(
        store, store.snapshot(), registry
    )
    snapshot = store.snapshot()
    unrelated_root = "court:catalog-cache:unrelated:%s" % snapshot.revision
    store.commit(snapshot.revision, create=(Cell(
        unrelated_root, NULL_CELL_ID, NULL_CELL_ID, b"unrelated"
    ),))
    second = application_module._project_standard_catalog(
        store, store.snapshot(), registry
    )
    verified_second = verify_released_catalog_stable(
        store,
        store.snapshot(),
        registry.assembly_protocol,
        registry.standard_library.catalog_root,
    )

    assert first is second
    assert verified_first is verified_second
    assert calls == 1


def test_standard_catalog_projection_revalidates_changed_catalog_cells(
    monkeypatch,
):
    store, registry = build_universal_application(resolve_map_path())
    original = application_module.project_catalog
    calls = 0

    def counted(snapshot, protocol, catalog_root):
        nonlocal calls
        calls += 1
        return original(snapshot, protocol, catalog_root)

    monkeypatch.setattr(application_module, "project_catalog", counted)
    application_module._project_standard_catalog(
        store, store.snapshot(), registry
    )
    snapshot = store.snapshot()
    catalog = verify_released_catalog(
        snapshot,
        registry.assembly_protocol,
        registry.standard_library.catalog_root,
    )
    digest = snapshot.cells[catalog.digest_root]
    store.commit(snapshot.revision, replace=(Cell(
        digest.id, digest.link0, digest.link1, b"forged digest"
    ),))

    with pytest.raises(InvalidCell, match="catalogue has drifted"):
        application_module._project_standard_catalog(
            store, store.snapshot(), registry
        )

    assert calls == 1


def test_canvas_gesture_primes_stable_catalog_before_composer_authorization(
    application, monkeypatch
):
    store, registry = application
    project_universal_canvas(store, registry)
    original = catalog_module._catalog_digest
    digest_calls = 0

    def counted(*args, **kwargs):
        nonlocal digest_calls
        digest_calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(catalog_module, "_catalog_digest", counted)
    root = registry.map.domains["models"]
    apply_universal_canvas_gesture(
        store, registry, roots=(root,), focus_root=root
    )

    assert digest_calls == 0


def test_existing_properties_interactions_use_membership_not_store_scans(
    application, monkeypatch
):
    store, registry = application
    ensure_universal_properties_panel_interactions(
        store, registry, registry.authorization.subject_root
    )
    snapshot = store.snapshot()

    class MembershipOnlyCells(Mapping):
        def __init__(self, cells):
            self._cells = cells

        def __getitem__(self, key):
            return self._cells[key]

        def __iter__(self):
            raise AssertionError("interaction validation scanned the full store")

        def __len__(self):
            return len(self._cells)

        def __contains__(self, key):
            return key in self._cells

        def get(self, key, default=None):
            return self._cells.get(key, default)

    membership_snapshot = Snapshot(
        snapshot.revision, MembershipOnlyCells(snapshot.cells)
    )
    monkeypatch.setattr(store, "snapshot", lambda: membership_snapshot)

    ensure_universal_properties_panel_interactions(
        store, registry, registry.authorization.subject_root
    )
