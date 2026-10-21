from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from nodelang.application_machine_transport import session_proof_payload
from nodelang.cell_authorization import AuthorizationDenied
from nodelang.cell_cloud_routes import (
    bootstrap_cloud_route_protocol,
    build_cloud_route,
)
from nodelang.cell_dpop_nonce import ResourceServerNonceBroker
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore
from nodelang.universal_cloud_gateway import (
    REMOTE_RUNTIME_ROUTES,
    UniversalCloudGatewayError,
    UniversalCloudRuntimeClient,
    create_universal_cloud_gateway,
)
from nodelang.universal_cloud_listener import (
    UniversalCloudTlsListener,
    create_universal_cloud_tls_server,
)


TOKEN = "ah_dpop_test-access-token"
ORIGIN = "https://gateway.archhub.test"
RUNTIME_ID = "gateway-runtime-generation-0001"


def test_cloud_gateway_exposes_connector_lifecycle_only_as_declared_routes():
    expected = {
        ("POST", "/api/universal/connector-delegation"),
        ("POST", "/api/universal/connector-delegation-approve"),
        ("POST", "/api/universal/connector-delegation-grant"),
        ("POST", "/api/universal/connector-delegation-receipt"),
        ("POST", "/api/universal/connector-delegation-recover"),
        ("POST", "/api/universal/connector-delegation-resume"),
        ("POST", "/api/universal/baboom-activity"),
        ("POST", "/api/universal/baboom-meeting-notes"),
    }
    assert expected.issubset(set(REMOTE_RUNTIME_ROUTES))
    assert {
        ("GET", "/api/universal/devices"),
        ("GET", "/api/universal/baboom-presence"),
        ("GET", "/api/universal/baboom-native-frame"),
        ("GET", "/api/universal/baboom-capabilities"),
        ("GET", "/api/universal/work-handoff"),
        ("GET", "/api/universal/work-claim-transfer"),
        ("POST", "/api/universal/work-handoff"),
        ("POST", "/api/universal/work-handoff-receipt"),
        ("POST", "/api/universal/work-claim-transfer"),
        ("POST", "/api/universal/work-claim-transfer-claim"),
        ("POST", "/api/universal/work-claim-transfer-cancel"),
        ("POST", "/api/universal/agent-session-resume"),
        ("POST", "/api/universal/device-custody-revoke"),
    }.issubset(set(REMOTE_RUNTIME_ROUTES))


def _cell(root: str, value: str) -> Cell:
    return Cell(root, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8"))


def _proof(nonce: str) -> str:
    encode = lambda value: base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")
    return ".".join((
        encode(b'{"alg":"none","typ":"dpop+jwt"}'),
        encode(json.dumps({"nonce": nonce}).encode("utf-8")),
        "untrusted-signature",
    ))


class RecordingGate:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def authorize(self, store, token, proof, **fields):
        self.calls.append({"token": token, "proof": proof, **fields})
        return SimpleNamespace(
            authentication=SimpleNamespace(
                device_root="device-proof-key:sha256:" + "A" * 43
            )
        )


def _gateway():
    store = CellStore()
    routes = bootstrap_cloud_route_protocol(store, prefix="court:cloud-route")
    roots = {
        "read": "court:action:read",
        "inspect": "court:action:inspect",
        "create": "court:action:create",
        "edit": "court:action:edit",
        "execute": "court:action:execute",
        "manage-policy": "court:action:manage-policy",
        "scope": "court:remote-runtime:scope",
        "interface": "court:interface:remote-runtime",
        "purpose": "court:purpose:operate",
        "audience": "court:audience:founder",
        "classification": "court:classification:internal",
        "published": "court:lifecycle:published",
    }
    snapshot = store.snapshot()
    store.commit(
        snapshot.revision,
        create=tuple(_cell(root, name) for name, root in roots.items()),
    )
    for method, path, action in (
        ("GET", "/api/universal/remote-runtime", "read"),
        ("POST", "/api/universal/agent-session", "create"),
        ("POST", "/api/universal/agent-session-resume", "execute"),
        ("POST", "/api/universal/agent-session-challenge", "inspect"),
        ("POST", "/api/universal/baboom-command", "read"),
        ("POST", "/api/universal/baboom-command-response", "read"),
        ("POST", "/api/universal/baboom-command-execute", "create"),
        ("POST", "/api/universal/work-next", "execute"),
        ("GET", "/api/universal/baboom-context", "read"),
        ("GET", "/api/universal/baboom-presence", "read"),
        ("GET", "/api/universal/baboom-native-frame", "read"),
        ("GET", "/api/universal/baboom-capabilities", "read"),
        ("GET", "/api/universal/work-handoff", "read"),
        ("GET", "/api/universal/work-claim-transfer", "read"),
        ("GET", "/api/universal/devices", "read"),
        ("POST", "/api/universal/device-custody-revoke", "manage-policy"),
        ("POST", "/api/universal/work-claim-transfer", "edit"),
        ("POST", "/api/universal/work-claim-transfer-claim", "execute"),
        ("POST", "/api/universal/work-claim-transfer-cancel", "edit"),
    ):
        build_cloud_route(
            store,
            routes,
            route_id="court:route:%s:%s" % (
                method.lower(), path.rsplit("/", 1)[-1],
            ),
            method=method,
            path_template=path,
            action_root=roots[action],
            object_root=roots["scope"],
            interface_root=roots["interface"],
            purpose_root=roots["purpose"],
            audience_root=roots["audience"],
            classification_root=roots["classification"],
            lifecycle_state_root=roots["published"],
            resource_lineage_roots=(roots["scope"],),
        )
    gate = RecordingGate()
    nonce = ResourceServerNonceBroker(
        key_provider=MemorySigningKeyProvider(
            "court:cloud-nonce", b"n" * 32
        ),
        key_id="court:cloud-nonce",
        audience=ORIGIN,
        lifetime_seconds=60,
    )
    calls: list[dict[str, object]] = []
    issued_at = time.time()

    def dispatch(request: dict[str, object]):
        calls.append(request)
        assert request["runtime_id"] == RUNTIME_ID
        path = request["path"]
        if path == "/api/universal/agent-session":
            body = request["body"]
            if isinstance(body, dict) and str(body.get("runtime", "")).startswith("baboom"):
                assert body.get("device_credential") == {
                    "challenge_id": "court-device-challenge",
                    "custody_root": "device-custody:sha256:court-cloud",
                    "signature": "court-signature",
                }
            return {
                "agent_session": "app:agent-session:runtime:court-cloud",
                "session_token": "s" * 48,
                "expires_at": issued_at + 900.0,
            }
        if path == "/api/universal/agent-session-resume":
            assert request["session"] == {}
            assert request["body"] == {
                "runtime": "baboom-execution",
                "external_session_id": "court-cloud-recovery",
                "device_credential": {
                    "challenge_id": "court-device-challenge",
                    "custody_root": "device-custody:sha256:court-cloud",
                    "signature": "court-signature",
                },
            }
            return {
                "agent_session": "app:agent-session:runtime:court-cloud",
                "session_token": "r" * 48,
                "capability": "machine-recovery:court-cloud",
                "access": "recovery-read",
                "continued": True,
                "expires_at": issued_at + 120.0,
            }
        if path == "/api/universal/agent-session-challenge":
            return {
                "challenge_id": "court-device-challenge",
                "nonce": "court-device-nonce",
                "runtime": str(request["body"].get("runtime", "")),
                "runtime_id": RUNTIME_ID,
                "catalog_entry": "app:agent-body-catalog-entry:baboom",
                "expires_at": issued_at + 90.0,
            }
        if path == "/api/universal/baboom-context":
            session = request["session"]
            assert isinstance(session, dict)
            expected = hmac.new(
                ("s" * 48).encode("utf-8"),
                session_proof_payload(
                    runtime_id=RUNTIME_ID,
                    request_id=str(request["request_id"]),
                    method="GET",
                    path="/api/universal/baboom-context",
                    body={},
                    session_root="app:agent-session:runtime:court-cloud",
                ),
                hashlib.sha256,
            ).hexdigest()
            if session != {
                "root": "app:agent-session:runtime:court-cloud",
                "proof": expected,
            }:
                raise AuthorizationDenied("runtime Agent Session proof is invalid")
            return {"revision": 24, "available": True}
        if path == "/api/universal/baboom-presence":
            assert request["body"] == {}
            assert isinstance(request["session"], dict)
            return {
                "projection": "app:baboom-companion-directive:v1",
                "revision": 24,
                "fingerprint": "baboom-directive:sha256:" + "d" * 64,
                "persona_form": "focus",
                "motion": "idle",
                "message": "No governed Work needs attention.",
                "context": "ArchHub | Live activity",
                "compact_message": "",
                "ttl_seconds": 12.0,
                "action": "",
                "action_label": "",
            }
        if path == "/api/universal/baboom-native-frame":
            assert request["body"] == {}
            assert isinstance(request["session"], dict)
            frame_issued_at = time.time()
            return {
                "projection": "app:baboom-native-frame:v2",
                "revision": 24,
                "issued_at": frame_issued_at,
                "expires_at": frame_issued_at + 12.0,
                "context": {"revision": 24},
                "directive": {
                    "revision": 24,
                    "ttl_seconds": 12.0,
                    "action": "",
                },
                "report": None,
            }
        if path == "/api/universal/baboom-command":
            assert request["body"] == {"utterance": "Assign task: inspect Work"}
            assert isinstance(request["session"], dict)
            return {
                "catalog": "app:baboom-command-catalog:v1",
                "intent": "assign-task",
                "payload": "inspect Work",
                "revision": 24,
            }
        if path == "/api/universal/baboom-command-response":
            assert request["body"] == {"utterance": "Workshop report"}
            assert isinstance(request["session"], dict)
            return {
                "command": {
                    "catalog": "app:baboom-command-catalog:v1",
                    "intent": "workshop-report",
                    "payload": "Workshop report",
                    "revision": 24,
                },
                "response": {
                    "kind": "workshop-report",
                    "summary": "Latest bounded founder-local Workshop entries.",
                    "data": {"revision": 24, "entries": []},
                },
            }
        if path == "/api/universal/baboom-command-execute":
            assert request["body"] == {"utterance": "Assign task: inspect Work"}
            assert isinstance(request["session"], dict)
            return {
                "catalog": "app:baboom-command-catalog:v1",
                "intent": "assign-task",
                "work": "assembly-instance:governed-work:court-cloud-task",
                "external_key": "baboom-founder-task:v1:" + "c" * 64,
                "created": True,
                "state": "open",
                "revision": 25,
            }
        if path == "/api/universal/baboom-capabilities":
            assert request["body"] == {}
            assert isinstance(request["session"], dict)
            return {
                "projection": "founder-local-baboom-capability-report",
                "revision": 24,
                "models": [],
                "connectors": [],
                "routes": ["GET /api/universal/baboom-capabilities"],
            }
        if path == "/api/universal/work-handoff":
            assert request["body"] == {}
            assert isinstance(request["session"], dict)
            return {
                "projection": "device-handoff-v1",
                "application": "app:archhub",
                "agent_session": "app:agent-session:runtime:court-cloud",
                "device_custody": "device-custody:sha256:" + "A" * 43,
                "revision": 24,
                "items": [],
            }
        if path == "/api/universal/work-claim-transfer":
            if request["method"] == "GET":
                assert request["body"] == {}
                assert isinstance(request["session"], dict)
                return {
                    "projection": "work-claim-transfer-v1",
                    "application": "app:archhub",
                    "agent_session": "app:agent-session:runtime:court-cloud",
                    "device_custody": "device-custody:sha256:" + "A" * 43,
                    "revision": 27,
                    "items": [{
                        "transfer_key": "a" * 64,
                        "direction": "outgoing",
                        "issued_at": 1.0,
                        "expires_at": 2.0,
                        "state": "released",
                        "claimable": False,
                    }],
                }
            assert request["body"] == {
                "root": "assembly-instance:governed-work:court-cloud",
                "target_device_ref": "device_0123456789abcdef01234567",
                "transfer_key": "a" * 64,
                "confirmation_digest": "b" * 64,
                "expires_at": 600.0,
            }
            return {
                "application": "app:archhub",
                "workshop": "app:workshop",
                "compliance_observation": "app:compliance:observation",
                "compliance_evidence": "app:compliance:evidence",
                "transfer_key": "a" * 64,
                "state": "released",
                "expires_at": 600.0,
                "target_device_ref": "device_0123456789abcdef01234567",
                "policy_revision": 27,
                "release_receipt_root": "work-claim-transfer:receipt:release",
                "revision": 28,
                "reused": False,
            }
        if path == "/api/universal/work-claim-transfer-claim":
            assert request["body"] == {"transfer_key": "a" * 64}
            return {
                "application": "app:archhub",
                "workshop": "app:workshop",
                "compliance_observation": "app:compliance:observation",
                "compliance_evidence": "app:compliance:evidence",
                "claimed": True,
                "reused": False,
                "work": {"root": "assembly-instance:governed-work:court-cloud"},
                "history_root": "app:work-history:claim",
                "revision": 29,
                "status": {"state": "claimed"},
            }
        if path == "/api/universal/work-claim-transfer-cancel":
            assert request["body"] == {
                "transfer_key": "a" * 64,
                "cancellation_digest": "c" * 64,
            }
            return {
                "application": "app:archhub",
                "workshop": "app:workshop",
                "compliance_observation": "app:compliance:observation",
                "compliance_evidence": "app:compliance:evidence",
                "transfer_key": "a" * 64,
                "state": "cancelled",
                "cancellation_receipt_root": "work-claim-transfer:receipt:cancellation",
                "revision": 30,
                "reused": False,
            }
        if path == "/api/universal/work-next":
            return {"claimed": False, "work": None}
        if path == "/api/universal/devices":
            assert request["body"] == {"projection": "founder-report"}
            assert request["session"] == {}
            return {
                "application": "app:archhub",
                "agent_session": "app:agent-session:founder",
                "projection": "founder-local-device-custody-report",
                "revision": 25,
                "registered": 1,
                "active": 1,
                "revoked": 0,
                "hardware_backed": 1,
                "reported": 1,
                "truncated": False,
                "devices": [{
                    "device_ref": "device_0123456789abcdef01234567",
                    "label": "Device 01234567",
                    "state": "active",
                    "hardware_backed": True,
                    "baboom_bound": False,
                    "runtime_present": False,
                    "baboom_present": False,
                }],
            }
        if path == "/api/universal/device-custody-revoke":
            assert request["body"] == {
                "device_ref": "device_0123456789abcdef01234567",
                "reason_code": "retired",
            }
            assert request["session"] == {}
            return {
                "application": "app:archhub",
                "agent_session": "app:agent-session:founder",
                "device_ref": "device_0123456789abcdef01234567",
                "state": "revoked",
                "reason_code": "retired",
                "revision": 26,
            }
        raise AssertionError("unexpected gateway path %s" % path)

    def verify_cloud_device(request: dict[str, object], cloud_device_root: str):
        assert cloud_device_root == "device-proof-key:sha256:" + "A" * 43
        assert request["runtime_id"] == RUNTIME_ID

    gateway = create_universal_cloud_gateway(
        store=store,
        route_protocol=routes,
        gate=gate,  # type: ignore[arg-type]
        nonce_broker=nonce,
        resource_origin=ORIGIN,
        runtime_id=RUNTIME_ID,
        dispatch=dispatch,
        verify_cloud_device=verify_cloud_device,
    )
    return gateway, gate, calls, roots


def test_cloud_gateway_requires_graph_route_then_preserves_agent_binding():
    gateway, gate, calls, roots = _gateway()
    http = TestClient(gateway.app)
    client = UniversalCloudRuntimeClient(
        ORIGIN, TOKEN, lambda **fields: _proof(fields["nonce"]), http_client=http
    )
    try:
        enrolled = client.bind_agent_session(
            runtime="codex", external_session_id="court-cloud-client"
        )
        result = client.request("GET", "/api/universal/baboom-context")
        frame = client.baboom_native_frame()
        command = client.resolve_baboom_command(
            utterance="Assign task: inspect Work"
        )
        response = client.respond_baboom_command(utterance="Workshop report")
        execution = client.execute_baboom_command(
            utterance="Assign task: inspect Work"
        )
        capabilities = client.request(
            "GET", "/api/universal/baboom-capabilities"
        )
        handoffs = client.list_device_handoffs()
        no_work = client.claim_next_work()
    finally:
        client.close()

    assert enrolled["agent_session"] == "app:agent-session:runtime:court-cloud"
    assert result == {"revision": 24, "available": True}
    assert frame["projection"] == "app:baboom-native-frame:v2"
    assert frame["report"] is None
    assert command["intent"] == "assign-task"
    assert response["response"]["kind"] == "workshop-report"
    assert execution["intent"] == "assign-task"
    assert execution["created"] is True
    assert capabilities["projection"] == "founder-local-baboom-capability-report"
    assert handoffs["projection"] == "device-handoff-v1"
    assert no_work == {"claimed": False, "work": None}
    assert [call["path"] for call in calls] == [
        "/api/universal/agent-session",
        "/api/universal/baboom-context",
        "/api/universal/baboom-native-frame",
        "/api/universal/baboom-command",
        "/api/universal/baboom-command-response",
        "/api/universal/baboom-command-execute",
        "/api/universal/baboom-capabilities",
        "/api/universal/work-handoff",
        "/api/universal/work-next",
    ]
    assert len(gate.calls) == 10
    assert gate.calls[0]["action_root"] == roots["read"]
    assert gate.calls[1]["action_root"] == roots["create"]
    assert gate.calls[2]["action_root"] == roots["read"]
    assert gate.calls[2]["target_uri"] == (
        ORIGIN + "/api/universal/baboom-context"
    )
    assert gate.calls[3]["action_root"] == roots["read"]
    assert gate.calls[3]["target_uri"] == (
        ORIGIN + "/api/universal/baboom-native-frame"
    )
    assert gate.calls[4]["action_root"] == roots["read"]
    assert gate.calls[4]["target_uri"] == (
        ORIGIN + "/api/universal/baboom-command"
    )
    assert gate.calls[5]["action_root"] == roots["read"]
    assert gate.calls[5]["target_uri"] == (
        ORIGIN + "/api/universal/baboom-command-response"
    )
    assert gate.calls[6]["action_root"] == roots["create"]
    assert gate.calls[6]["target_uri"] == (
        ORIGIN + "/api/universal/baboom-command-execute"
    )
    assert gate.calls[7]["action_root"] == roots["read"]
    assert gate.calls[7]["target_uri"] == (
        ORIGIN + "/api/universal/baboom-capabilities"
    )
    assert gate.calls[8]["action_root"] == roots["read"]
    assert gate.calls[8]["target_uri"] == (
        ORIGIN + "/api/universal/work-handoff"
    )
    assert gate.calls[9]["action_root"] == roots["execute"]


def test_cloud_gateway_rejects_malformed_envelopes_without_dispatch():
    gateway, _gate, calls, _roots = _gateway()
    http = TestClient(gateway.app)
    probe = http.get(
        "/api/universal/baboom-context",
        headers={"Authorization": "DPoP " + TOKEN},
    )
    assert probe.status_code == 401
    response = http.request(
        "GET",
        "/api/universal/baboom-context",
        json={},
        headers={
            "Authorization": "DPoP " + TOKEN,
            "DPoP": _proof(probe.headers["DPoP-Nonce"]),
        },
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "universal_runtime_request_invalid"}
    assert calls == []


def test_cloud_client_forwards_graph_work_continuations_without_a_remote_queue():
    gateway, gate, calls, roots = _gateway()
    client = UniversalCloudRuntimeClient(
        ORIGIN, TOKEN, lambda **fields: _proof(fields["nonce"]),
        http_client=TestClient(gateway.app),
    )
    try:
        client.bind_agent_session(
            runtime="baboom-execution",
            external_session_id="court-cloud-continuation",
            device_credential_provider=lambda challenge: {
                "challenge_id": challenge["challenge_id"],
                "custody_root": "device-custody:sha256:court-cloud",
                "signature": "court-signature",
            },
        )
        transfers = client.list_work_claim_transfers()
        released = client.initiate_work_claim_transfer(
            work_root="assembly-instance:governed-work:court-cloud",
            target_device_ref="device_0123456789abcdef01234567",
            transfer_key="a" * 64,
            confirmation_digest="b" * 64,
            expires_at=600.0,
        )
        claimed = client.claim_work_claim_transfer("a" * 64)
        cancelled = client.cancel_work_claim_transfer(
            transfer_key="a" * 64,
            cancellation_digest="c" * 64,
        )
    finally:
        client.close()

    assert transfers["projection"] == "work-claim-transfer-v1"
    assert set(transfers["items"][0]) == {
        "transfer_key", "direction", "issued_at", "expires_at", "state", "claimable",
    }
    assert released["state"] == "released"
    assert claimed["claimed"] is True
    assert cancelled["state"] == "cancelled"
    continuation_calls = [
        call for call in calls if "work-claim-transfer" in str(call["path"])
    ]
    assert [call["path"] for call in continuation_calls] == [
        "/api/universal/work-claim-transfer",
        "/api/universal/work-claim-transfer",
        "/api/universal/work-claim-transfer-claim",
        "/api/universal/work-claim-transfer-cancel",
    ]
    assert all("title" not in call["body"] for call in continuation_calls)
    assert all("description" not in call["body"] for call in continuation_calls)
    assert [entry["action_root"] for entry in gate.calls[-4:]] == [
        roots["read"], roots["edit"], roots["execute"], roots["edit"],
    ]


def test_cloud_client_provisions_no_device_key_but_forwards_its_challenge_proof():
    gateway, gate, calls, roots = _gateway()
    client = UniversalCloudRuntimeClient(
        ORIGIN, TOKEN, lambda **fields: _proof(fields["nonce"]),
        http_client=TestClient(gateway.app),
    )

    result = client.bind_agent_session(
        runtime="baboom",
        external_session_id="court-cloud-baboom",
        device_credential_provider=lambda challenge: {
            "challenge_id": challenge["challenge_id"],
            "custody_root": "device-custody:sha256:court-cloud",
            "signature": "court-signature",
        },
    )

    assert result["agent_session"] == "app:agent-session:runtime:court-cloud"
    assert [call["path"] for call in calls] == [
        "/api/universal/agent-session-challenge",
        "/api/universal/agent-session",
    ]
    assert gate.calls[0]["action_root"] == roots["read"]
    assert gate.calls[1]["action_root"] == roots["inspect"]
    assert gate.calls[2]["action_root"] == roots["create"]


def test_cloud_client_recovers_a_read_only_baboom_session_without_takeover():
    gateway, gate, calls, roots = _gateway()
    client = UniversalCloudRuntimeClient(
        ORIGIN, TOKEN, lambda **fields: _proof(fields["nonce"]),
        http_client=TestClient(gateway.app),
    )
    try:
        recovered = client.resume_agent_session(
            runtime="baboom-execution",
            external_session_id="court-cloud-recovery",
            device_credential_provider=lambda challenge: {
                "challenge_id": challenge["challenge_id"],
                "custody_root": "device-custody:sha256:court-cloud",
                "signature": "court-signature",
            },
        )
        with pytest.raises(UniversalCloudGatewayError, match="read-only and cannot renew"):
            client.renew_agent_session()
        with pytest.raises(UniversalCloudGatewayError, match="read-only and cannot renew presence"):
            client.renew_runtime_presence()
    finally:
        client.close()

    assert recovered["access"] == "recovery-read"
    assert client.agent_session_access == "recovery-read"
    assert [call["path"] for call in calls] == [
        "/api/universal/agent-session-challenge",
        "/api/universal/agent-session-resume",
    ]
    assert gate.calls[-2]["action_root"] == roots["inspect"]
    assert gate.calls[-1]["action_root"] == roots["execute"]


def test_cloud_founder_device_custody_uses_an_unbound_dpop_client():
    gateway, gate, calls, roots = _gateway()
    client = UniversalCloudRuntimeClient(
        ORIGIN, TOKEN, lambda **fields: _proof(fields["nonce"]),
        http_client=TestClient(gateway.app),
    )

    report = client.founder_device_custody_report()
    revoked = client.revoke_founder_device_custody(
        device_ref="device_0123456789abcdef01234567",
        reason_code="retired",
    )

    assert report["devices"][0]["state"] == "active"
    assert revoked["state"] == "revoked"
    assert [call["path"] for call in calls] == [
        "/api/universal/devices",
        "/api/universal/device-custody-revoke",
    ]
    assert gate.calls[-2]["action_root"] == roots["read"]
    assert gate.calls[-1]["action_root"] == roots["manage-policy"]
    client.agent_session_root = "app:agent-session:runtime:court-cloud"
    with pytest.raises(UniversalCloudGatewayError, match="unbound cloud client"):
        client.founder_device_custody_report()


def test_cloud_runtime_client_never_admits_an_unlisted_route():
    gateway, _gate, _calls, _roots = _gateway()
    client = UniversalCloudRuntimeClient(
        ORIGIN, TOKEN, lambda **fields: _proof(fields["nonce"]),
        http_client=TestClient(gateway.app),
    )

    with pytest.raises(UniversalCloudGatewayError, match="not admitted"):
        client.request("POST", "/api/universal/cell", {})
    with pytest.raises(UniversalCloudGatewayError, match="native onboarding"):
        client.browser_handoff_status()
    with pytest.raises(UniversalCloudGatewayError, match="native onboarding"):
        client.bind_runtime_device_custody(
            runtime="baboom",
            custody_root="device-custody:sha256:court-cloud",
        )


def test_cloud_client_reads_the_graph_owned_companion_directive():
    gateway, _gate, _calls, _roots = _gateway()
    client = UniversalCloudRuntimeClient(
        ORIGIN,
        TOKEN,
        lambda **fields: _proof(fields["nonce"]),
        http_client=TestClient(gateway.app),
    )

    directive = client.request("GET", "/api/universal/baboom-presence")

    assert directive["projection"] == "app:baboom-companion-directive:v1"
    assert directive["motion"] == "idle"
    assert directive["action"] == ""
    assert directive["message"] == "No governed Work needs attention."


def test_cloud_tls_listener_is_explicit_direct_tls_and_never_starts_on_build(tmp_path):
    gateway, _gate, _calls, _roots = _gateway()
    certificate = tmp_path / "certificate.pem"
    private_key = tmp_path / "private-key.pem"
    certificate.write_text("test certificate", encoding="ascii")
    private_key.write_text("test key", encoding="ascii")

    server = create_universal_cloud_tls_server(
        gateway,
        UniversalCloudTlsListener(
            host="127.0.0.1",
            port=9443,
            certificate_file=certificate,
            private_key_file=private_key,
        ),
    )

    assert server.started is False
    assert server.config.ssl_certfile == str(certificate.resolve())
    assert server.config.ssl_keyfile == str(private_key.resolve())
    assert server.config.reload is False
    assert server.config.workers == 1
    assert server.config.access_log is False
    assert server.config.proxy_headers is False
    assert server.config.forwarded_allow_ips == ""

    with pytest.raises(ValueError, match="regular file"):
        create_universal_cloud_tls_server(
            gateway,
            UniversalCloudTlsListener(
                host="127.0.0.1",
                port=9443,
                certificate_file=tmp_path / "missing.pem",
                private_key_file=private_key,
            ),
        )
