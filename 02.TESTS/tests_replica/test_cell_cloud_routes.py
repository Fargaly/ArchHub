from __future__ import annotations

import pytest

from nodelang.cell_cloud_routes import (
    CloudRouteDenied,
    bootstrap_cloud_route_protocol,
    build_cloud_route,
    external_object_root,
    find_cloud_route,
    list_cloud_routes,
    provision_external_object,
    read_cloud_route,
    resolve_cloud_route,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


def _cell(root: str, value: str) -> Cell:
    return Cell(root, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8"))


def _world():
    store = CellStore()
    protocol = bootstrap_cloud_route_protocol(store, prefix="test:routes")
    roots = {
        "action_read": "test:action:read",
        "action_edit": "test:action:edit",
        "object_settings": "test:object:settings",
        "interface_http": "test:interface:http",
        "purpose_operate": "test:purpose:operate",
        "audience_api": "test:audience:api",
        "classification_internal": "test:classification:internal",
        "lifecycle_production": "test:lifecycle:production",
        "state_active": "test:state:active",
        "lineage_product": "test:lineage:product",
    }
    snapshot = store.snapshot()
    store.commit(
        snapshot.revision,
        create=tuple(_cell(root, name) for name, root in roots.items()),
    )
    return store, protocol, roots


def test_static_route_is_one_inspectable_relation_and_resolves_exactly():
    store, protocol, roots = _world()
    route_root = build_cloud_route(
        store,
        protocol,
        route_id="test:route:settings:read",
        method="GET",
        path_template="/v1/settings",
        action_root=roots["action_read"],
        object_root=roots["object_settings"],
        interface_root=roots["interface_http"],
        purpose_root=roots["purpose_operate"],
        audience_root=roots["audience_api"],
        classification_root=roots["classification_internal"],
        lifecycle_state_root=roots["lifecycle_production"],
        operational_state_root=roots["state_active"],
        resource_lineage_roots=(roots["lineage_product"],),
    )
    route = find_cloud_route(
        store.snapshot(), protocol, method="get", path_template="/v1/settings"
    )
    resolved = resolve_cloud_route(store.snapshot(), route)

    assert route.root_id == route_root
    assert route.action_root == roots["action_read"]
    assert resolved.object_root == roots["object_settings"]
    assert resolved.interface_root == roots["interface_http"]
    assert resolved.lifecycle_state_root == roots["lifecycle_production"]
    assert resolved.resource_lineage_roots == (roots["lineage_product"],)
    assert len(route.digest) == 64


def test_dynamic_route_binds_path_input_to_preprovisioned_graph_identity():
    store, protocol, roots = _world()
    external_id = "company-db-id-97"
    object_root = provision_external_object(
        store, namespace="tenant", external_id=external_id
    )
    build_cloud_route(
        store,
        protocol,
        route_id="test:route:tenant:edit",
        method="PATCH",
        path_template="/v1/companies/{company_id}",
        action_root=roots["action_edit"],
        object_namespace="tenant",
        object_path_parameter="company_id",
        interface_root=roots["interface_http"],
        audience_root=roots["audience_api"],
    )
    route = find_cloud_route(
        store.snapshot(),
        protocol,
        method="PATCH",
        path_template="/v1/companies/{company_id}",
    )
    resolved = resolve_cloud_route(
        store.snapshot(), route, path_parameters={"company_id": external_id}
    )

    assert resolved.object_root == object_root
    atoms = b"\n".join(
        cell.atom for cell in store.snapshot().cells.values()
    )
    assert external_id.encode("utf-8") not in atoms
    assert external_object_root("tenant", external_id) in store.snapshot().cells


def test_dynamic_route_rejects_missing_or_unprovisioned_object():
    store, protocol, roots = _world()
    build_cloud_route(
        store,
        protocol,
        route_id="test:route:tenant:read",
        method="GET",
        path_template="/v1/companies/{company_id}",
        action_root=roots["action_read"],
        object_namespace="tenant",
        object_path_parameter="company_id",
    )
    route = list_cloud_routes(store.snapshot(), protocol)[0]
    with pytest.raises(CloudRouteDenied, match="absent"):
        resolve_cloud_route(store.snapshot(), route, path_parameters={})
    with pytest.raises(CloudRouteDenied, match="not graph-provisioned"):
        resolve_cloud_route(
            store.snapshot(), route, path_parameters={"company_id": "unknown"}
        )


def test_unknown_duplicate_and_ambiguous_routes_fail_closed():
    store, protocol, roots = _world()
    with pytest.raises(CloudRouteDenied, match="no unique"):
        find_cloud_route(
            store.snapshot(), protocol, method="GET", path_template="/v1/missing"
        )
    with pytest.raises(ValueError, match="either one static"):
        build_cloud_route(
            store,
            protocol,
            route_id="test:route:ambiguous",
            method="GET",
            path_template="/v1/ambiguous/{id}",
            action_root=roots["action_read"],
            object_root=roots["object_settings"],
            object_namespace="thing",
            object_path_parameter="id",
        )
    build_cloud_route(
        store,
        protocol,
        route_id="test:route:one",
        method="GET",
        path_template="/v1/one",
        action_root=roots["action_read"],
        object_root=roots["object_settings"],
    )
    with pytest.raises(InvalidCell, match="already registered"):
        build_cloud_route(
            store,
            protocol,
            route_id="test:route:duplicate",
            method="GET",
            path_template="/v1/one",
            action_root=roots["action_read"],
            object_root=roots["object_settings"],
        )
    store.commit(
        store.revision,
        create=(_cell("test:forged-route", "looks like a route"),),
    )
    with pytest.raises(CloudRouteDenied, match="not protocol-registered"):
        read_cloud_route(store.snapshot(), protocol, "test:forged-route")


def test_route_relation_tampering_is_detected_by_semantic_digest():
    store, protocol, roots = _world()
    route_root = build_cloud_route(
        store,
        protocol,
        route_id="test:route:tamper",
        method="GET",
        path_template="/v1/tamper",
        action_root=roots["action_read"],
        object_root=roots["object_settings"],
    )
    route = read_cloud_route(store.snapshot(), protocol, route_root)
    digest_root = route_root + ":field:route-digest"
    digest_cell = store.read(digest_root)
    store.commit(
        store.revision,
        replace=(Cell(
            digest_cell.id,
            digest_cell.link0,
            digest_cell.link1,
            b"0" * 64,
        ),),
    )
    with pytest.raises(CloudRouteDenied, match="digest mismatch"):
        read_cloud_route(store.snapshot(), protocol, route_root)


def test_index_reuses_verified_routes_and_invalidates_changes(tmp_path, monkeypatch):
    from nodelang import cell_cloud_routes as routes
    from nodelang.cell_protocols import remove_relation_member

    store = CellStore(tmp_path / 'routes.sqlite3')
    protocol = bootstrap_cloud_route_protocol(store)
    store.commit(store.revision, create=(_cell('action', 'read'), _cell('object', 'scope')))
    def add(name):
        return build_cloud_route(store, protocol, route_id=name, method='GET',
                                 path_template='/' + name, action_root='action', object_root='object')
    add('one')
    lookup = lambda name, snapshot=None: find_cloud_route(snapshot or store.snapshot(), protocol,
        method='GET', path_template='/' + name, store=store)
    from nodelang.cell_protocols import relation_projection_scope
    with relation_projection_scope(max_retained_bytes=1024 * 1024, max_entries=1):
        assert lookup('one').root_id == 'one'
    old = store.snapshot()
    with monkeypatch.context() as patch:
        patch.setattr(routes, '_read_registered_cloud_route', lambda *_a, **_k: pytest.fail('registry reprojected'))
        store.commit(store.revision, create=(_cell('unrelated', 'session'),))
        assert lookup('one').root_id == 'one'
    add('two')
    assert lookup('two').root_id == 'two'
    with pytest.raises(CloudRouteDenied, match='no unique'):
        lookup('two', old)
    from nodelang.cell_protocols import read_relation
    member = next(m for m in read_relation(store.snapshot(), protocol.root_id) if m.participant_id == 'two')
    remove_relation_member(store, protocol.root_id, member.incidence_id)
    with pytest.raises(CloudRouteDenied, match='no unique'):
        lookup('two')
    digest = store.read('one:field:route-digest')
    store.commit(store.revision, replace=(Cell(digest.id, digest.link0, digest.link1, b'0' * 64),))
    with pytest.raises(CloudRouteDenied, match='digest mismatch'):
        lookup('one')
    store.close()


def test_route_index_never_holds_cache_lock_while_waiting_for_store(monkeypatch):
    import threading
    from nodelang import cell_cloud_routes as routes
    store, protocol, roots = _world()
    build_cloud_route(store, protocol, route_id='lock-route', method='GET', path_template='/lock',
                     action_root=roots['action_read'], object_root=roots['object_settings'])
    attempted = threading.Event()
    original = store.snapshot
    def snapshot():
        attempted.set()
        return original()
    monkeypatch.setattr(store, 'snapshot', snapshot)
    errors = []
    # Pin the input before the worker waits for the store lock.
    pinned = original()
    def lookup_pinned():
        try:
            find_cloud_route(pinned, protocol, method='GET', path_template='/lock', store=store)
        except Exception as exc:
            errors.append(exc)
    thread = threading.Thread(target=lookup_pinned, daemon=True)
    try:
        with store.stable_snapshot():
            thread.start()
            assert attempted.wait(5)
            acquired = routes._ROUTE_INDEX_LOCK.acquire(timeout=1)
            assert acquired, 'route cache lock was held while waiting for the store'
            if acquired:
                routes._ROUTE_INDEX_LOCK.release()
        thread.join(5)
        assert not thread.is_alive()
        assert not errors
    finally:
        store.close()


def test_cached_lookup_refuses_a_forged_duplicate_pair():
    from types import MappingProxyType
    from nodelang.cell_cloud_routes import prepare_cloud_route
    from nodelang.cell_protocols import compose_relation_cells, prepare_append_relation_member
    from nodelang.universal_cell import Snapshot
    store, protocol, roots = _world()
    build_cloud_route(store, protocol, route_id='one', method='GET', path_template='/duplicate',
                     action_root=roots['action_read'], object_root=roots['object_settings'])
    assert find_cloud_route(store.snapshot(), protocol, method='GET',
                            path_template='/duplicate', store=store).root_id == 'one'
    empty = compose_relation_cells((), relation_id=protocol.root_id)
    blank = Snapshot(0, MappingProxyType({cell.id: cell for cell in empty.cells}))
    forged = prepare_cloud_route(blank, protocol, route_id='forged', method='GET',
        path_template='/duplicate', action_root=roots['action_read'], object_root=roots['object_settings'])
    patch = prepare_append_relation_member(store.snapshot(), protocol.root_id,
                                           protocol.role('route-member'), 'forged')
    store.commit(store.revision, create=(*forged, *patch.create), replace=patch.replace)
    with pytest.raises(CloudRouteDenied, match='no unique'):
        find_cloud_route(store.snapshot(), protocol, method='GET', path_template='/duplicate', store=store)
