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
