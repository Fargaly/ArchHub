from __future__ import annotations

import base64
import json

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from nodelang.cell_authorization import AuthorizationDenied
from nodelang.cell_cloud_routes import (
    bootstrap_cloud_route_protocol,
    build_cloud_route,
    provision_external_object,
)
from nodelang.cell_dpop_nonce import ResourceServerNonceBroker
from nodelang.cell_fastapi_gate import (
    GraphCloudRuntime,
    GraphGovernedAPIRoute,
    install_graph_cloud_runtime,
)
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore


TOKEN = "test-access-token"


def _cell(root: str, value: str) -> Cell:
    return Cell(root, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8"))


def _unverified_proof(nonce: str) -> str:
    encode = lambda value: base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")
    return ".".join((
        encode(b'{"alg":"none","typ":"dpop+jwt"}'),
        encode(json.dumps({"nonce": nonce}).encode("utf-8")),
        "untrusted-signature",
    ))


class RecordingGate:
    def __init__(self, *, deny: bool = False) -> None:
        self.calls: list[dict[str, object]] = []
        self.deny = deny

    def authorize(self, store, token, proof, **fields):
        self.calls.append({
            "store": store,
            "token": token,
            "proof": proof,
            **fields,
        })
        if self.deny:
            raise AuthorizationDenied("test policy denied")
        return {"decision": "permit", "object": fields["object_root"]}


def _app(*, deny: bool = False):
    store = CellStore()
    protocol = bootstrap_cloud_route_protocol(store, prefix="test:http-routes")
    roots = {
        "action": "test:action:read",
        "interface": "test:interface:http",
        "purpose": "test:purpose:inspect",
        "audience": "test:audience:cloud-api",
        "classification": "test:classification:internal",
        "lifecycle": "test:lifecycle:production",
        "operational": "test:operational:active",
        "lineage": "test:lineage:workspace",
    }
    snapshot = store.snapshot()
    store.commit(
        snapshot.revision,
        create=tuple(_cell(root, name) for name, root in roots.items()),
    )
    object_root = provision_external_object(
        store, namespace="thing", external_id="thing-42"
    )
    build_cloud_route(
        store,
        protocol,
        route_id="test:http-route:thing",
        method="GET",
        path_template="/v1/things/{thing_id}",
        action_root=roots["action"],
        object_namespace="thing",
        object_path_parameter="thing_id",
        interface_root=roots["interface"],
        purpose_root=roots["purpose"],
        audience_root=roots["audience"],
        classification_root=roots["classification"],
        lifecycle_state_root=roots["lifecycle"],
        operational_state_root=roots["operational"],
        resource_lineage_roots=(roots["lineage"],),
    )
    gate = RecordingGate(deny=deny)
    nonce = ResourceServerNonceBroker(
        key_provider=MemorySigningKeyProvider(
            "test:http-nonce", b"http-nonce-key-material-with-more-than-32"
        ),
        key_id="test:http-nonce",
        audience="https://api.archhub.test",
        lifetime_seconds=60,
    )
    app = FastAPI()
    app.router.route_class = GraphGovernedAPIRoute
    install_graph_cloud_runtime(app, GraphCloudRuntime(
        store=store,
        route_protocol=protocol,
        gate=gate,  # type: ignore[arg-type]
        nonce_broker=nonce,
        resource_origin="https://api.archhub.test",
        clock=lambda: 1000.0,
    ))
    invoked = {"count": 0}

    @app.get("/v1/things/{thing_id}")
    def thing(thing_id: str, request: Request):
        invoked["count"] += 1
        return {
            "thing_id": thing_id,
            "route": request.state.archhub_route_root,
            "object": request.state.archhub_object_root,
            "authorization": request.state.archhub_authorized_cloud_request,
        }

    @app.get("/v1/unregistered")
    def unregistered():
        invoked["count"] += 1
        return {"unsafe": True}

    return app, gate, invoked, object_root, roots


def _challenge(client: TestClient) -> str:
    response = client.get(
        "/v1/things/thing-42",
        headers={"Authorization": "DPoP " + TOKEN},
    )
    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["dpop-nonce"]
    assert "use_dpop_nonce" in response.headers["www-authenticate"]
    return response.headers["dpop-nonce"]


def test_fastapi_route_executes_only_after_graph_route_and_gate_authorize():
    app, gate, invoked, object_root, roots = _app()
    client = TestClient(app)
    nonce = _challenge(client)
    response = client.get(
        "/v1/things/thing-42?ignored-by-dpop-htu=true",
        headers={
            "Authorization": "DPoP " + TOKEN,
            "DPoP": _unverified_proof(nonce),
            "Host": "attacker-controlled.example",
        },
    )

    assert response.status_code == 200
    assert response.json()["object"] == object_root
    assert invoked["count"] == 1
    assert len(gate.calls) == 1
    call = gate.calls[0]
    assert call["action_root"] == roots["action"]
    assert call["object_root"] == object_root
    assert call["interface_root"] == roots["interface"]
    assert call["lifecycle_state_root"] == roots["lifecycle"]
    assert call["target_uri"] == "https://api.archhub.test/v1/things/thing-42"
    assert call["token"] == TOKEN


def test_bearer_unknown_object_and_unregistered_route_never_reach_endpoint():
    app, gate, invoked, _, _ = _app()
    client = TestClient(app)
    bearer = client.get(
        "/v1/things/thing-42",
        headers={"Authorization": "Bearer " + TOKEN},
    )
    unknown = client.get(
        "/v1/things/not-provisioned",
        headers={"Authorization": "DPoP " + TOKEN},
    )
    unregistered = client.get(
        "/v1/unregistered",
        headers={"Authorization": "DPoP " + TOKEN},
    )

    assert bearer.status_code == 401
    assert unknown.status_code == 503
    assert unregistered.status_code == 503
    assert invoked["count"] == 0
    assert gate.calls == []


def test_released_graph_policy_denial_blocks_endpoint_after_valid_proof():
    app, gate, invoked, _, _ = _app(deny=True)
    client = TestClient(app)
    nonce = _challenge(client)
    response = client.get(
        "/v1/things/thing-42",
        headers={
            "Authorization": "DPoP " + TOKEN,
            "DPoP": _unverified_proof(nonce),
        },
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "graph_authorization_denied"}
    assert invoked["count"] == 0
    assert len(gate.calls) == 1
