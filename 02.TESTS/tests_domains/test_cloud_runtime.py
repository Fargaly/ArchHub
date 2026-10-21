import gzip
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from nodelang import Store, relation_sources, relation_targets, validate_store
from nodelang.cloud_runtime import CloudRuntime, RUNTIME_FORMAT
from nodelang.domains.cloud import (
    build_cloud_domain,
    observe_service_health,
    set_service_authorization,
)
from nodelang.domains.community import build_community_domain
from nodelang.domains.monetization import build_monetization_domain
from nodelang.domains.users import build_users_domain


def _user():
    return {
        "id": "founder",
        "display_name": "Founder",
        "email": "founder@example.com",
        "role": "owner",
        "entitlements": ["workspace"],
        "auth": {
            "capability_ref": "op://archhub/auth/founder",
            "evidence": {
                "provider": "external-oidc",
                "method": "pkce",
                "verified": True,
                "verified_at": "2026-07-13T04:00:00Z",
                "subject_ref": "subject:founder",
            },
        },
    }


def _build(tmp_path=None):
    store = Store()
    cloud = build_cloud_domain(store)
    users = build_users_domain(store, users=[_user()])
    monetization = build_monetization_domain(store)
    community = build_community_domain(store)
    state_path = tmp_path / "cloud-runtime.json.gz" if tmp_path else None
    runtime = CloudRuntime(
        store, cloud, users=users, monetization=monetization,
        community=community, state_path=state_path,
    )
    return store, cloud, users, monetization, community, runtime


def _request(runtime, path, *, method="GET", body=None):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(runtime.url + path, data=data, method=method, headers=headers)
    try:
        with urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _history(store, operation):
    return [node for node in store.nodes.values()
            if node["kind"] == "history"
            and node["body"]["floor"]["entry"].get("op") == operation]


def _open_deployment(store, cloud):
    observe_service_health(
        store, cloud, "cloud_fly_app", "online",
        observed_at="2026-07-13T04:10:00Z", evidence="local court probe passed",
        latency_ms=8,
    )
    set_service_authorization(
        store, cloud, "cloud_fly_app", True,
        observed_at="2026-07-13T04:10:01Z", evidence="capability resolved externally",
    )
    deployment = cloud["deployments"]["cloud_deploy_pipeline"]
    fields = deployment["fields"]["fields"]
    for name, value in {
        "approved": True,
        "approved_by": "founder",
        "approved_at": "2026-07-13T04:10:02Z",
    }.items():
        store.edit(fields[name], ["body", "floor", "value"], value, actor="founder")
    assert store.pull(deployment["gate"]) == 1
    return deployment, fields


def test_runtime_routes_payloads_sources_and_gates_are_nodes_and_wires():
    store, cloud, _users, _money, _community, runtime = _build()
    try:
        routes = list(runtime._routes())
        assert len(routes) == 9
        assert {store.pull(route["params"]["runtime_route_path"])
                for route in routes} == {
            "/health", "/v1/services", "/v1/services/{service_id}",
            "/v1/graph/state", "/v1/auth/status", "/v1/quota/status",
            "/v1/billing/status", "/v1/community/status",
            "/v1/effects/dispatch",
        }
        for route in routes:
            assert store.nodes[route["params"]["runtime_payload_schema"]]["kind"] == "param"
            source_relations = []
            for relation_id in route["relations"]:
                relation = store.nodes[relation_id]
                sources = relation_sources(store.nodes, relation)
                targets = relation_targets(store.nodes, relation)
                if sources and any(item["node_id"] == route["id"] for item in targets):
                    source_relations.append(relation)
            assert len(source_relations) == 1
            assert store.pull(route["params"]["runtime_route_gate"]) is True
        for item in list(cloud["deployments"].values()) + list(cloud["syncs"].values()):
            assert store.nodes[item["effect"]]["meta"]["frozen"] is True
        assert validate_store(store) is True
    finally:
        runtime.close()


def test_real_http_reads_live_node_authorities_without_claiming_external_online():
    store, cloud, _users, money, _community, runtime = _build()
    runtime.start()
    try:
        status, health = _request(runtime, "/health")
        assert status == 200
        assert health["adapter"]["online"] is True
        assert health["external_cloud"] == "not inferred from local listener"

        status, services = _request(runtime, "/v1/services")
        assert status == 200
        assert len(services["services"]) == 13
        assert {item["status"] for item in services["services"]} == {"unknown"}
        service_id = "cloud_fly_app"
        observe_service_health(
            store, cloud, service_id, "offline",
            observed_at="2026-07-13T04:20:00Z", evidence="connection refused",
        )
        status, service = _request(runtime, "/v1/services/%s" % service_id)
        assert status == 200
        assert service["service"]["status"] == "offline"

        assert _request(runtime, "/v1/auth/status")[1]["auth"][0]["verified"] is True
        quota = _request(runtime, "/v1/quota/status")[1]["quota"]
        assert quota["plan"] == store.pull(money["subscription_params"]["plan_id"])
        assert quota["remaining:tokens"] == store.pull(money["remaining"]["tokens"])
        assert _request(runtime, "/v1/billing/status")[1]["billing"]["approval_gate"] == 0
        assert "community" in _request(runtime, "/v1/community/status")[1]
        graph = _request(runtime, "/v1/graph/state")[1]["graph"]
        assert graph["valid"] is True
        assert 0 < graph["nodes"] <= len(store.nodes)  # response exchange is appended afterward
        assert graph["kinds"]["wire"] > 0
        assert validate_store(store) is True
    finally:
        runtime.close()


def test_route_gate_edit_immediately_controls_network_behavior():
    store, _cloud, _users, _money, _community, runtime = _build()
    runtime.start()
    try:
        route = next(route for route in runtime._routes()
                     if store.pull(route["params"]["runtime_route_path"]) == "/v1/services")
        store.edit(route["params"]["runtime_route_enabled"],
                   ["body", "floor", "value"], False, actor="founder")
        status, body = _request(runtime, "/v1/services")
        assert status == 503
        assert "gate is closed" in body["error"]
        assert validate_store(store) is True
    finally:
        runtime.close()


def test_dispatch_rejects_raw_credentials_and_closed_graph_gate_without_mutation():
    store, cloud, _users, _money, _community, runtime = _build()
    effect = cloud["deployments"]["cloud_deploy_pipeline"]["effect"]
    runtime.start()
    try:
        status, body = _request(runtime, "/v1/effects/dispatch", method="POST", body={
            "target": "cloud-deployment:cloud_deploy_pipeline",
            "idempotency_key": "cloud-deploy-pipeline-v1",
            "capability_ref": "op://archhub/cloud/cloud_fly_app",
            "evidence_node": cloud["authority"],
            "actor": "founder",
            "password": "must-never-enter-the-graph",
        })
        assert status == 400
        assert "credential" in body["error"]
        assert "must-never-enter-the-graph" not in json.dumps(store.dump())
        assert store.nodes[effect]["meta"]["frozen"] is True
        assert not _history(store, "effect_apply")

        status, body = _request(runtime, "/v1/effects/dispatch", method="POST", body={
            "target": "cloud-deployment:cloud_deploy_pipeline",
            "idempotency_key": "cloud-deploy-pipeline-v1",
            "capability_ref": "op://archhub/cloud/cloud_fly_app",
            "evidence_node": cloud["authority"],
            "actor": "founder",
        })
        assert status == 403
        assert "gate is closed" in body["error"]
        assert store.nodes[effect]["meta"]["frozen"] is True
        assert not _history(store, "effect_apply")
    finally:
        runtime.close()


def test_authorized_dispatch_uses_graph_evidence_is_idempotent_and_refreezes():
    store, cloud, _users, _money, _community, runtime = _build()
    deployment, fields = _open_deployment(store, cloud)
    capability = store.pull(cloud["services"]["cloud_fly_app"]
                            ["authorization"]["capability"])
    request = {
        "target": "cloud-deployment:cloud_deploy_pipeline",
        "idempotency_key": "cloud-deploy-pipeline-v1",
        "capability_ref": capability,
        "evidence_node": fields["approved_at"],
        "actor": "founder",
    }
    runtime.start()
    try:
        status, first = _request(runtime, "/v1/effects/dispatch", method="POST", body=request)
        assert status == 200
        assert first["dispatch"]["fired"] is True
        assert first["dispatch"]["idempotent"] is False
        assert store.nodes[deployment["effect"]]["meta"]["frozen"] is True
        sink = store.nodes[first["dispatch"]["result_node"]]
        saved_plan = store.pull(sink["params"]["runtime_effect_value"])
        assert saved_plan["deployment"]["idempotency_key"] == "cloud-deploy-pipeline-v1"

        status, second = _request(runtime, "/v1/effects/dispatch", method="POST", body=request)
        assert status == 200
        assert second["dispatch"]["fired"] is False
        assert second["dispatch"]["idempotent"] is True
        assert second["dispatch"]["result_node"] == first["dispatch"]["result_node"]
        assert store.nodes[deployment["effect"]]["meta"]["frozen"] is True
        assert len(_history(store, "effect_apply")) == 2
        assert validate_store(store) is True
    finally:
        runtime.close()


def test_snapshot_persists_graph_evidence_and_reloads_without_hidden_registry(tmp_path):
    store, _cloud, _users, _money, _community, runtime = _build(tmp_path)
    runtime.start()
    state_path = runtime.state_path
    try:
        assert _request(runtime, "/v1/graph/state")[0] == 200
    finally:
        runtime.close()
    with gzip.open(state_path, "rt", encoding="utf-8") as stream:
        payload = json.load(stream)
    assert payload["format"] == RUNTIME_FORMAT
    before = len(payload["nodes"])

    loaded = CloudRuntime.load(state_path)
    loaded.start()
    try:
        status, result = _request(loaded, "/v1/graph/state")
        assert status == 200
        assert result["graph"]["valid"] is True
        assert len(loaded.store.nodes) > before
        assert any(node["title"] == "Runtime HTTP result"
                   for node in loaded.store.nodes.values())
        assert len(list(loaded._routes())) == 9
        assert validate_store(loaded.store) is True
    finally:
        loaded.close()
