from __future__ import annotations

import pytest

from nodelang import KINDS, Store, relation_sources, relation_targets, validate_store
from nodelang.core import relation_stages
from nodelang.domains.cloud import (
    GRAND_MAP_CLOUD_SERVICES,
    build_cloud_domain,
    observe_service_health,
    service_status,
    set_service_authorization,
)
from nodelang.laws_effect import FrozenNode, apply_effect, dry_run


def _pairs(store: Store) -> set[tuple[str, str]]:
    pairs = set()
    for node in store.nodes.values():
        if node["kind"] != "wire":
            continue
        for source in relation_sources(store.nodes, node):
            for target in relation_targets(store.nodes, node):
                pairs.add((source["node_id"], target["node_id"]))
    return pairs


def _make_live(store: Store, domain, service_id: str) -> None:
    observe_service_health(
        store, domain, service_id, "online",
        observed_at="2026-07-13T00:00:00Z", evidence="independent health response",
    )
    set_service_authorization(
        store, domain, service_id, True,
        observed_at="2026-07-13T00:00:01Z", evidence="verified capability response",
    )


def test_cloud_is_one_open_table_and_covers_grand_map_authority():
    store = Store()
    domain = build_cloud_domain(store)

    expected = {item["id"] for item in GRAND_MAP_CLOUD_SERVICES}
    assert set(domain["services"]) == expected
    assert validate_store(store) is True
    assert set(node["kind"] for node in store.nodes.values()) <= KINDS
    assert store.nodes[domain["session"]]["kind"] == "session"
    assert store.pull(domain["authority"]) == "Grand Map / cloud"

    for service in domain["services"].values():
        assert store.nodes[service["service"]]["kind"] == "group"
        assert set(service["parts"].values()) <= set(store.open(service["service"]))
        for part_id in service["parts"].values():
            assert store.nodes[part_id]["kind"] == "group"
        for part in (service["definition"], service["endpoint"], service["health"]):
            assert all(store.nodes[param_id]["kind"] == "param" for param_id in part["fields"].values())


def test_endpoint_and_timestamped_health_propagate_into_execution_plan():
    store = Store()
    domain = build_cloud_domain(store)
    service = domain["services"]["cloud_fly_app"]

    assert service_status(store, domain, "cloud_fly_app") == "unknown"
    assert store.pull(service["ready"]) == 0
    address = service["endpoint"]["fields"]["address"]
    store.edit(address, ["body", "floor", "value"], "https://cloud.example.test", actor="user")

    with pytest.raises(ValueError, match="timestamped evidence"):
        observe_service_health(store, domain, "cloud_fly_app", "online")
    observe_service_health(
        store, domain, "cloud_fly_app", "online",
        observed_at="2026-07-13T01:00:00Z", evidence="HTTP 200 /healthz",
    )
    assert service_status(store, domain, "cloud_fly_app") == "unauthorized"
    set_service_authorization(
        store, domain, "cloud_fly_app", True,
        observed_at="2026-07-13T01:00:01Z", evidence="signed auth probe accepted",
    )

    plan = store.pull(service["plan"]["record"])
    assert plan["endpoint"]["address"] == "https://cloud.example.test"
    assert plan["health"]["evidence"] == "HTTP 200 /healthz"
    assert plan["ready"] == 1
    assert service_status(store, domain, "cloud_fly_app") == "online"
    assert validate_store(store) is True


def test_offline_and_unauthorized_are_honest_observed_states():
    store = Store()
    domain = build_cloud_domain(store)
    service_id = "cloud_auth"
    service = domain["services"][service_id]

    observe_service_health(
        store, domain, service_id, "online",
        observed_at="2026-07-13T02:00:00Z", evidence="HTTP 200",
    )
    assert service_status(store, domain, service_id) == "unauthorized"
    assert store.pull(service["ready"]) == 0

    set_service_authorization(
        store, domain, service_id, True,
        observed_at="2026-07-13T02:00:01Z", evidence="JWT verification succeeded",
    )
    assert service_status(store, domain, service_id) == "online"
    observe_service_health(
        store, domain, service_id, "offline",
        observed_at="2026-07-13T02:01:00Z", evidence="connection refused",
    )
    assert service_status(store, domain, service_id) == "offline"
    assert store.pull(service["ready"]) == 0


def test_service_deployment_sync_and_queue_relations_are_explicit_wires():
    store = Store()
    domain = build_cloud_domain(store)
    pairs = _pairs(store)

    host = domain["services"]["cloud_fly_app"]["service"]
    database = domain["services"]["cloud_persistent_db"]["service"]
    assert (host, database) in pairs

    deployment = domain["deployments"]["cloud_deploy_pipeline"]
    sync = domain["syncs"]["cloud_sync_client"]
    queue = domain["queues"]["brain-sync-queue"]
    assert (deployment["group"], host) in pairs
    assert (domain["services"]["nl_cloud_central_home"]["service"], sync["group"]) in pairs
    assert (sync["group"], domain["services"]["cloud_brain_replica"]["service"]) in pairs
    assert (queue["group"], sync["group"]) in pairs

    for item in (deployment, sync):
        stages = relation_stages(store.nodes, store.nodes[item["effect_relation"]])
        assert [(stage["mode"], stage["node_id"]) for stage in stages] == [("guard", item["gate"])]
        assert store.nodes[item["effect"]]["meta"]["frozen"] is True
    assert validate_store(store) is True


def test_raw_secrets_are_rejected_and_external_capability_refs_are_nodes():
    unsafe = dict(GRAND_MAP_CLOUD_SERVICES[0])
    unsafe["configuration"] = {"api_token": "do-not-store-this"}
    with pytest.raises(ValueError, match="secret_ref"):
        build_cloud_domain(Store(), services=[unsafe], queues=(), syncs=(), deployments=())

    bad_ref = dict(GRAND_MAP_CLOUD_SERVICES[0])
    bad_ref["auth_capability_ref"] = "plaintext-key"
    with pytest.raises(ValueError, match="op://"):
        build_cloud_domain(Store(), services=[bad_ref], queues=(), syncs=(), deployments=())

    safe = dict(GRAND_MAP_CLOUD_SERVICES[0])
    safe["auth_capability_ref"] = "op://archhub/cloud/test-capability"
    safe_store = Store()
    domain = build_cloud_domain(safe_store, services=[safe], queues=(), syncs=(), deployments=())
    capability = domain["services"]["cloud_fly_app"]["authorization"]["capability"]
    assert safe_store.nodes[capability]["kind"] == "secret_ref"
    assert safe_store.nodes[capability]["body"]["floor"]["ref"] == "op://archhub/cloud/test-capability"
    assert "value" not in safe_store.nodes[capability]["body"]["floor"]


def test_deploy_and_sync_plans_are_idempotent_gated_and_frozen():
    store = Store()
    domain = build_cloud_domain(store)
    for service_id in ("cloud_fly_app", "nl_cloud_central_home", "cloud_brain_replica"):
        _make_live(store, domain, service_id)

    deployment = domain["deployments"]["cloud_deploy_pipeline"]
    deploy_fields = deployment["fields"]["fields"]
    store.edit(deploy_fields["approved"], ["body", "floor", "value"], True, actor="founder")
    store.edit(deploy_fields["approved_by"], ["body", "floor", "value"], "founder", actor="founder")
    store.edit(deploy_fields["approved_at"], ["body", "floor", "value"], "2026-07-13T03:00:00Z", actor="founder")
    assert store.pull(deployment["gate"]) == 1

    sync = domain["syncs"]["cloud_sync_client"]
    sync_fields = sync["fields"]["fields"]
    store.edit(sync_fields["authorized"], ["body", "floor", "value"], True, actor="founder")
    store.edit(sync_fields["auth_evidence"], ["body", "floor", "value"], "scope accepted", actor="founder")
    store.edit(sync_fields["auth_observed_at"], ["body", "floor", "value"], "2026-07-13T03:00:01Z", actor="founder")
    assert store.pull(sync["gate"]) == 1

    for item, key in ((deployment, "cloud-deploy-pipeline-v1"), (sync, "cloud-sync-client-v1")):
        plan = dry_run(store, item["effect"])
        assert plan["change"]
        assert key in str(plan["change"])
        with pytest.raises(FrozenNode):
            apply_effect(store, item["effect"], {})

    store.edit(deploy_fields["idempotency_key"], ["body", "floor", "value"], "", actor="founder")
    assert store.pull(deployment["gate"]) == 0
    assert validate_store(store) is True
