"""HTTPS gateway for the graph-governed Universal runtime.

The local named-pipe runtime is deliberately Windows-local.  This module is a
separate, opt-in network adapter: it exposes only a bounded BABOOM/Workshop
surface and lets ``GraphGovernedAPIRoute`` resolve and authorize every path
from the persisted Cloud Route graph before forwarding it to the application
runtime.  It contains no session, device, work, or permission authority.

The factory does not bind a socket, provision TLS, issue a Cloud Session, or
enroll a device.  Deployment must provide those separately.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .application_machine_transport import (
    MachineTransportError,
    session_proof_payload,
    validate_baboom_native_frame_payload,
)
from .cell_authorization import AuthorizationDenied
from .cell_cloud_routes import CloudRouteProtocol
from .cell_dpop_nonce import ResourceServerNonceBroker
from .cell_fastapi_gate import (
    GraphCloudRuntime,
    GraphGovernedAPIRoute,
    install_graph_cloud_runtime,
)
from .cell_cloud_gate import CloudRequestGate
from .cell_cloud_sessions import CloudSessionBroker
from .universal_cell import CellStore, InvalidCell


_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_FOUNDER_DEVICE_REF = re.compile(r"^device_[0-9a-f]{24}$")
_MAX_ENVELOPE_BYTES = 1024 * 1024
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024


# This is a physical exposure ceiling, not an authority table.  A route still
# has to exist in the graph and pass CloudRequestGate before its endpoint runs.
# Keep effects narrow to BABOOM, governed Work, approvals, and recovery.
REMOTE_RUNTIME_ROUTES: tuple[tuple[str, str], ...] = (
    ("GET", "/api/universal/remote-runtime"),
    ("GET", "/api/universal/canvas"),
    ("GET", "/api/universal/work"),
    ("GET", "/api/universal/workshop"),
    ("GET", "/api/universal/devices"),
    ("GET", "/api/universal/baboom-context"),
    ("GET", "/api/universal/baboom-presence"),
    ("GET", "/api/universal/baboom-native-frame"),
    ("GET", "/api/universal/baboom-capabilities"),
    ("GET", "/api/universal/work-handoff"),
    ("GET", "/api/universal/work-claim-transfer"),
    ("POST", "/api/universal/agent-session-challenge"),
    ("POST", "/api/universal/agent-session"),
    ("POST", "/api/universal/agent-session-resume"),
    ("POST", "/api/universal/agent-session-renew"),
    ("POST", "/api/universal/baboom-command"),
    ("POST", "/api/universal/baboom-command-response"),
    ("POST", "/api/universal/baboom-command-execute"),
    ("POST", "/api/universal/runtime-presence"),
    ("POST", "/api/universal/device-custody-revoke"),
    ("POST", "/api/universal/model-delegation"),
    ("POST", "/api/universal/model-delegation-approve"),
    ("POST", "/api/universal/model-delegation-grant"),
    ("POST", "/api/universal/model-delegation-receipt"),
    ("POST", "/api/universal/model-delegation-recover"),
    ("POST", "/api/universal/model-delegation-resume"),
    ("POST", "/api/universal/model-cognition"),
    ("POST", "/api/universal/baboom-activity"),
    ("POST", "/api/universal/baboom-meeting-notes"),
    ("POST", "/api/universal/connector-delegation"),
    ("POST", "/api/universal/connector-delegation-approve"),
    ("POST", "/api/universal/connector-delegation-grant"),
    ("POST", "/api/universal/connector-delegation-receipt"),
    ("POST", "/api/universal/connector-delegation-recover"),
    ("POST", "/api/universal/connector-delegation-resume"),
    ("POST", "/api/universal/work"),
    ("POST", "/api/universal/work-handoff"),
    ("POST", "/api/universal/work-handoff-receipt"),
    ("POST", "/api/universal/work-claim-transfer"),
    ("POST", "/api/universal/work-claim-transfer-claim"),
    ("POST", "/api/universal/work-claim-transfer-cancel"),
    ("POST", "/api/universal/workshop"),
    ("POST", "/api/universal/work-next"),
    ("POST", "/api/universal/work-claim"),
    ("POST", "/api/universal/work-claim-recover"),
    ("POST", "/api/universal/work-transition"),
    ("POST", "/api/universal/work-court"),
    ("POST", "/api/universal/work-court-recover"),
    ("POST", "/api/universal/workshop-gate"),
)


class UniversalCloudGatewayError(RuntimeError):
    """The remote graph runtime did not return a valid bounded response."""


class DpopProofProvider(Protocol):
    def __call__(
        self,
        *,
        http_method: str,
        target_uri: str,
        access_token: str,
        nonce: str,
    ) -> bytes | str:
        ...


class RuntimeDeviceCredentialProvider(Protocol):
    def __call__(self, challenge: Mapping[str, object]) -> Mapping[str, object]:
        ...


class CloudDeviceBindingVerifier(Protocol):
    def __call__(
        self,
        request: dict[str, object],
        cloud_device_root: str,
    ) -> None:
        ...


@dataclass(frozen=True, slots=True)
class UniversalCloudGateway:
    """An unserved ASGI app and its current physical runtime generation."""

    app: FastAPI
    runtime_id: str
    resource_origin: str


def _canonical(value: Mapping[str, object]) -> bytes:
    return json.dumps(
        dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _valid_runtime_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", value):
        raise ValueError("cloud runtime identity is invalid")
    return value


def validate_universal_cloud_resource_origin(value: str) -> str:
    """Validate the canonical HTTPS resource origin for a cloud gateway."""
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("cloud gateway requires a bare HTTPS resource origin")
    return value.rstrip("/")


async def _read_envelope(request: Request) -> dict[str, object]:
    raw = await request.body()
    if len(raw) > _MAX_ENVELOPE_BYTES:
        raise InvalidCell("remote runtime request exceeds its size limit")
    try:
        payload = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidCell("remote runtime request is not valid JSON") from exc
    if type(payload) is not dict or set(payload) != {
        "request_id", "body", "session"
    }:
        raise InvalidCell("remote runtime request shape is invalid")
    request_id = payload["request_id"]
    if type(request_id) is not str or not _REQUEST_ID.fullmatch(request_id):
        raise InvalidCell("remote runtime request identity is invalid")
    if type(payload["body"]) is not dict or type(payload["session"]) is not dict:
        raise InvalidCell("remote runtime request values are invalid")
    return payload


def create_universal_cloud_gateway(
    *,
    store: CellStore,
    route_protocol: CloudRouteProtocol,
    gate: CloudRequestGate,
    nonce_broker: ResourceServerNonceBroker,
    resource_origin: str,
    dispatch: Callable[[dict[str, object]], Mapping[str, object]],
    verify_cloud_device: CloudDeviceBindingVerifier,
    runtime_id: str | None = None,
) -> UniversalCloudGateway:
    """Create, but do not serve, the DPoP-gated Universal runtime surface."""
    origin = validate_universal_cloud_resource_origin(resource_origin)
    generation = _valid_runtime_id(runtime_id or secrets.token_urlsafe(24))
    app = FastAPI()
    app.router.route_class = GraphGovernedAPIRoute
    install_graph_cloud_runtime(app, GraphCloudRuntime(
        store=store,
        route_protocol=route_protocol,
        gate=gate,
        nonce_broker=nonce_broker,
        resource_origin=origin,
    ))

    async def descriptor(_request: Request) -> dict[str, object]:
        return {"runtime_id": generation}

    def forward(method: str, path: str):
        async def endpoint(request: Request) -> JSONResponse:
            try:
                envelope = await _read_envelope(request)
                forwarded = {
                    "runtime_id": generation,
                    "request_id": envelope["request_id"],
                    "method": method,
                    "path": path,
                    "body": envelope["body"],
                    "session": envelope["session"],
                }
                authorized = getattr(
                    request.state, "archhub_authorized_cloud_request", None
                )
                cloud_device_root = getattr(
                    getattr(authorized, "authentication", None),
                    "device_root", None,
                )
                if not isinstance(cloud_device_root, str):
                    raise UniversalCloudGatewayError(
                        "cloud request has no verified device identity"
                    )
                verify_cloud_device(forwarded, cloud_device_root)
                result = dict(dispatch(forwarded))
                raw = _canonical(result)
                if len(raw) > _MAX_RESPONSE_BYTES:
                    raise UniversalCloudGatewayError(
                        "remote runtime response exceeds its size limit"
                    )
                return JSONResponse(content=result)
            except AuthorizationDenied:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "universal_runtime_denied"},
                    headers={"Cache-Control": "no-store"},
                )
            except (InvalidCell, ValueError, TypeError):
                return JSONResponse(
                    status_code=400,
                    content={"detail": "universal_runtime_request_invalid"},
                    headers={"Cache-Control": "no-store"},
                )
            except UniversalCloudGatewayError:
                return JSONResponse(
                    status_code=503,
                    content={"detail": "universal_runtime_unavailable"},
                    headers={"Cache-Control": "no-store"},
                )
            except Exception:
                return JSONResponse(
                    status_code=503,
                    content={"detail": "universal_runtime_unavailable"},
                    headers={"Cache-Control": "no-store"},
                )
        return endpoint

    for method, path in REMOTE_RUNTIME_ROUTES:
        if (method, path) == ("GET", "/api/universal/remote-runtime"):
            app.add_api_route(path, descriptor, methods=[method])
        else:
            app.add_api_route(path, forward(method, path), methods=[method])
    return UniversalCloudGateway(app, generation, origin)


def create_application_cloud_gateway(
    application_server: Any,
    *,
    session_broker: CloudSessionBroker,
    nonce_broker: ResourceServerNonceBroker,
    resource_origin: str,
    runtime_id: str | None = None,
) -> UniversalCloudGateway:
    """Adapt one live Universal application without adding remote authority.

    The caller must construct ``session_broker`` from a real federated identity
    flow and the application's persisted cloud-session protocol.  This helper
    deliberately accepts no token, password, or OIDC configuration; secret
    custody and issuer verification stay outside the graph adapter.
    """
    registry = getattr(application_server, "universal_registry", None)
    store = getattr(application_server, "universal_store", None)
    dispatch = getattr(application_server, "dispatch_universal_machine_route", None)
    if registry is None or not isinstance(store, CellStore) or not callable(dispatch):
        raise TypeError("application cloud gateway requires a Universal ApplicationServer")
    authorization = registry.authorization
    gate = CloudRequestGate(
        session_broker=session_broker,
        authorization_protocol=authorization.protocol,
        authentication_broker=authorization.broker,
        policy_root=authorization.policy_root,
    )
    return create_universal_cloud_gateway(
        store=store,
        route_protocol=registry.cloud_route_protocol,
        gate=gate,
        nonce_broker=nonce_broker,
        resource_origin=resource_origin,
        dispatch=dispatch,
        verify_cloud_device=(
            lambda request, cloud_device_root:
            application_server.verify_universal_cloud_request_device(
                request, cloud_device_root=cloud_device_root
            )
        ),
        runtime_id=runtime_id,
    )


class UniversalCloudRuntimeClient:
    """DPoP client for an already-issued cloud session and remote runtime."""

    def __init__(
        self,
        resource_origin: str,
        access_token: str,
        proof_provider: DpopProofProvider,
        *,
        http_client: Any | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.resource_origin = validate_universal_cloud_resource_origin(resource_origin)
        if (
            not isinstance(access_token, str)
            or not access_token.startswith("ah_dpop_")
            or len(access_token) > 512
        ):
            raise ValueError("cloud access token is invalid")
        if not callable(proof_provider):
            raise TypeError("cloud DPoP proof provider is required")
        if timeout_seconds <= 0 or timeout_seconds > 660:
            raise ValueError("cloud runtime timeout is invalid")
        self._access_token = access_token
        self._proof_provider = proof_provider
        self._http = http_client or httpx.Client(
            timeout=httpx.Timeout(timeout_seconds), follow_redirects=False
        )
        self._owns_http_client = http_client is None
        self._timeout_seconds = float(timeout_seconds)
        self._runtime_id = ""
        self.agent_session_root = ""
        self._agent_session_token = ""
        self._agent_session_expires_at = 0.0
        self._agent_session_capability_id = ""
        self._agent_session_access = "full"
        self._runtime_presence_expires_at = 0.0
        self._request_lock = threading.RLock()

    def close(self) -> None:
        if self._owns_http_client:
            self._http.close()
            self._owns_http_client = False

    def _url(self, path: str) -> str:
        if (
            not isinstance(path, str)
            or not path.startswith("/")
            or "?" in path
            or "#" in path
            or ("GET", path) not in REMOTE_RUNTIME_ROUTES
            and ("POST", path) not in REMOTE_RUNTIME_ROUTES
        ):
            raise UniversalCloudGatewayError("cloud runtime route is not admitted")
        return self.resource_origin + path

    @staticmethod
    def _response_json(response: Any) -> dict[str, object]:
        try:
            value = response.json()
        except Exception as exc:
            raise UniversalCloudGatewayError(
                "cloud runtime response is not valid JSON"
            ) from exc
        if type(value) is not dict:
            raise UniversalCloudGatewayError("cloud runtime result is invalid")
        return value

    def _http_request(
        self,
        method: str,
        path: str,
        envelope: Mapping[str, object],
    ) -> dict[str, object]:
        target_uri = self._url(path)
        response = self._http.request(
            method,
            target_uri,
            json=dict(envelope),
            headers={"Authorization": "DPoP " + self._access_token},
        )
        nonce = response.headers.get("DPoP-Nonce")
        if response.status_code == 401 and nonce:
            proof = self._proof_provider(
                http_method=method,
                target_uri=target_uri,
                access_token=self._access_token,
                nonce=nonce,
            )
            if isinstance(proof, bytes):
                proof_text = proof.decode("ascii")
            elif isinstance(proof, str):
                proof_text = proof
            else:
                raise UniversalCloudGatewayError("cloud DPoP proof is invalid")
            response = self._http.request(
                method,
                target_uri,
                json=dict(envelope),
                headers={
                    "Authorization": "DPoP " + self._access_token,
                    "DPoP": proof_text,
                },
            )
        if response.status_code != 200:
            detail = self._response_json(response).get("detail")
            raise UniversalCloudGatewayError(
                "cloud runtime request failed%s" % (
                    ": " + detail if isinstance(detail, str) else ""
                )
            )
        return self._response_json(response)

    def refresh_runtime_identity(self) -> str:
        """Read the current gateway generation before binding or recovery."""
        with self._request_lock:
            result = self._http_request(
                "GET",
                "/api/universal/remote-runtime",
                {"request_id": secrets.token_urlsafe(18), "body": {}, "session": {}},
            )
            runtime_id = result.get("runtime_id")
            self._runtime_id = _valid_runtime_id(runtime_id)
            return self._runtime_id

    def bind_agent_session(
        self,
        *,
        runtime: str,
        external_session_id: str,
        device_credential_provider: RuntimeDeviceCredentialProvider | None = None,
    ) -> dict[str, object]:
        with self._request_lock:
            if self.agent_session_root or self._agent_session_token:
                raise UniversalCloudGatewayError(
                    "cloud runtime client already has an Agent Session"
                )
            if not self._runtime_id:
                self.refresh_runtime_identity()
            body: dict[str, object] = {
                "runtime": runtime,
                "external_session_id": external_session_id,
            }
            if device_credential_provider is not None:
                challenge = self.request(
                    "POST", "/api/universal/agent-session-challenge", {"runtime": runtime}
                )
                credential = device_credential_provider(challenge)
                if type(credential) is not dict:
                    raise UniversalCloudGatewayError(
                        "cloud runtime device credential is invalid"
                    )
                body["device_credential"] = dict(credential)
            result = self.request("POST", "/api/universal/agent-session", body)
            root = result.get("agent_session")
            token = result.get("session_token")
            expires_at = result.get("expires_at")
            if (
                not isinstance(root, str)
                or not root.startswith("app:agent-session:runtime:")
                or not isinstance(token, str)
                or len(token) < 32
                or not isinstance(expires_at, (int, float))
                or float(expires_at) <= time.time()
            ):
                raise UniversalCloudGatewayError(
                    "cloud Agent Session enrollment response is invalid"
                )
            self.agent_session_root = root
            self._agent_session_token = token
            self._agent_session_expires_at = float(expires_at)
            self._agent_session_capability_id = ""
            self._agent_session_access = "full"
            return result

    @property
    def agent_session_access(self) -> str:
        """Expose the volatile recovery class without creating graph state."""
        return self._agent_session_access

    def resume_agent_session(
        self,
        *,
        runtime: str,
        external_session_id: str,
        device_credential_provider: RuntimeDeviceCredentialProvider,
    ) -> dict[str, object]:
        """Recover one existing cloud Agent Session without taking it over.

        The graph issues a separate, short-lived recovery-read capability. This
        client retains it in process memory only; it cannot renew presence or
        broaden the original BABOOM execution authority.
        """
        with self._request_lock:
            if self.agent_session_root or self._agent_session_token:
                raise UniversalCloudGatewayError(
                    "cloud runtime client already has an Agent Session"
                )
            if not self._runtime_id:
                self.refresh_runtime_identity()
            challenge = self.request(
                "POST", "/api/universal/agent-session-challenge", {"runtime": runtime}
            )
            credential = device_credential_provider(challenge)
            if type(credential) is not dict:
                raise UniversalCloudGatewayError(
                    "cloud runtime device credential is invalid"
                )
            result = self.request("POST", "/api/universal/agent-session-resume", {
                "runtime": runtime,
                "external_session_id": external_session_id,
                "device_credential": dict(credential),
            })
            root = result.get("agent_session")
            token = result.get("session_token")
            capability_id = result.get("capability")
            expires_at = result.get("expires_at")
            if (
                not isinstance(root, str)
                or not root.startswith("app:agent-session:runtime:")
                or not isinstance(token, str)
                or len(token) < 32
                or not isinstance(capability_id, str)
                or not capability_id.startswith("machine-recovery:")
                or result.get("access") != "recovery-read"
                or result.get("continued") is not True
                or not isinstance(expires_at, (int, float))
                or float(expires_at) <= time.time()
            ):
                raise UniversalCloudGatewayError(
                    "cloud Agent Session recovery response is invalid"
                )
            self.agent_session_root = root
            self._agent_session_token = token
            self._agent_session_expires_at = float(expires_at)
            self._agent_session_capability_id = capability_id
            self._agent_session_access = "recovery-read"
            return result

    def renew_agent_session(self) -> dict[str, object]:
        with self._request_lock:
            if not self.agent_session_root or not self._agent_session_token:
                raise UniversalCloudGatewayError(
                    "cloud runtime client has no Agent Session"
                )
            if self._agent_session_access != "full":
                raise UniversalCloudGatewayError(
                    "recovered cloud Agent Session is read-only and cannot renew"
                )
            result = self._request_once(
                "POST", "/api/universal/agent-session-renew", {}
            )
            token = result.get("session_token")
            expires_at = result.get("expires_at")
            if (
                result.get("agent_session") != self.agent_session_root
                or not isinstance(token, str)
                or len(token) < 32
                or not isinstance(expires_at, (int, float))
                or float(expires_at) <= time.time()
            ):
                raise UniversalCloudGatewayError(
                    "cloud Agent Session renewal response is invalid"
                )
            self._agent_session_token = token
            self._agent_session_expires_at = float(expires_at)
            return result

    def renew_runtime_presence(self) -> dict[str, object]:
        if self._agent_session_access != "full":
            raise UniversalCloudGatewayError(
                "recovered cloud Agent Session is read-only and cannot renew presence"
            )
        result = self.request("POST", "/api/universal/runtime-presence", {})
        expires_at = result.get("expires_at")
        if (
            result.get("agent_session") != self.agent_session_root
            or not isinstance(result.get("runtime"), str)
            or not isinstance(expires_at, (int, float))
            or float(expires_at) <= time.time()
            or not isinstance(result.get("revision"), int)
        ):
            raise UniversalCloudGatewayError(
                "cloud runtime presence response is invalid"
            )
        self._runtime_presence_expires_at = float(expires_at)
        return result

    def baboom_native_frame(self) -> dict[str, object]:
        """Read one revision-coherent BABOOM frame through the cloud gateway."""
        result = self.request("GET", "/api/universal/baboom-native-frame", {})
        try:
            return validate_baboom_native_frame_payload(result)
        except MachineTransportError as exc:
            raise UniversalCloudGatewayError(
                "cloud BABOOM native frame is invalid"
            ) from exc

    def resolve_baboom_command(self, *, utterance: str) -> dict[str, object]:
        """Resolve one typed BABOOM request without executing it."""
        if type(utterance) is not str or not utterance.strip() or len(utterance) > 4_000:
            raise ValueError("cloud BABOOM command utterance is invalid")
        result = self.request("POST", "/api/universal/baboom-command", {
            "utterance": utterance,
        })
        if (
            set(result) != {"catalog", "intent", "payload", "revision"}
            or result.get("catalog") != "app:baboom-command-catalog:v1"
            or type(result.get("intent")) is not str
            or type(result.get("payload")) is not str
            or type(result.get("revision")) is not int
        ):
            raise UniversalCloudGatewayError("cloud BABOOM command resolution is invalid")
        return result

    def respond_baboom_command(self, *, utterance: str) -> dict[str, object]:
        """Read one founder-safe command response through the cloud gateway."""
        if type(utterance) is not str or not utterance.strip() or len(utterance) > 4_000:
            raise ValueError("cloud BABOOM command utterance is invalid")
        result = self.request("POST", "/api/universal/baboom-command-response", {
            "utterance": utterance,
        })
        command = result.get("command")
        response = result.get("response")
        if (
            set(result) != {"command", "response"}
            or not isinstance(command, dict)
            or not isinstance(response, dict)
            or type(command.get("intent")) is not str
            or type(response.get("kind")) is not str
            or type(response.get("summary")) is not str
            or not isinstance(response.get("data"), dict)
        ):
            raise UniversalCloudGatewayError("cloud BABOOM command response is invalid")
        return result

    def execute_baboom_command(self, *, utterance: str) -> dict[str, object]:
        """Create one explicit founder-assigned Work through the cloud runtime."""
        if type(utterance) is not str or not utterance.strip() or len(utterance) > 4_000:
            raise ValueError("cloud BABOOM command utterance is invalid")
        result = self.request("POST", "/api/universal/baboom-command-execute", {
            "utterance": utterance,
        })
        if (
            set(result) != {"catalog", "intent", "work", "external_key", "created", "state", "revision"}
            or result.get("catalog") != "app:baboom-command-catalog:v1"
            or result.get("intent") != "assign-task"
            or type(result.get("work")) is not str
            or type(result.get("external_key")) is not str
            or type(result.get("created")) is not bool
            or result.get("state") != "open"
            or type(result.get("revision")) is not int
        ):
            raise UniversalCloudGatewayError("cloud BABOOM command execution is invalid")
        return result

    def create_device_handoff_work(
        self,
        *,
        title: str,
        description: str,
        priority: int,
        scope: str,
        target_device_custody: str,
        handoff_key: str,
        payload_digest: str,
        expires_at: float,
        x: float,
        y: float,
    ) -> dict[str, object]:
        """Create one custody-targeted Work through the remote graph runtime."""
        if not self.agent_session_root:
            raise UniversalCloudGatewayError(
                "device handoff requires a bound cloud Agent Session"
            )
        result = self.request("POST", "/api/universal/work-handoff", {
            "title": title,
            "description": description,
            "priority": priority,
            "scope": scope,
            "target_device_custody": target_device_custody,
            "handoff_key": handoff_key,
            "payload_digest": payload_digest,
            "expires_at": expires_at,
            "x": x,
            "y": y,
        })
        if (
            not isinstance(result.get("work_root"), str)
            or not isinstance(result.get("membership_wire"), str)
            or not isinstance(result.get("handoff_root"), str)
            or not isinstance(result.get("source_device_custody"), str)
            or type(result.get("revision")) is not int
        ):
            raise UniversalCloudGatewayError(
                "cloud device handoff creation response is invalid"
            )
        return result

    def create_device_handoff_work_for_device_ref(
        self,
        *,
        title: str,
        description: str,
        priority: int,
        scope: str,
        target_device_ref: str,
        handoff_key: str,
        payload_digest: str,
        expires_at: float,
        x: float,
        y: float,
    ) -> dict[str, object]:
        """Create a remote handoff from one opaque graph device selector."""
        if not self.agent_session_root:
            raise UniversalCloudGatewayError(
                "device handoff requires a bound cloud Agent Session"
            )
        result = self.request("POST", "/api/universal/work-handoff", {
            "title": title,
            "description": description,
            "priority": priority,
            "scope": scope,
            "target_device_ref": target_device_ref,
            "handoff_key": handoff_key,
            "payload_digest": payload_digest,
            "expires_at": expires_at,
            "x": x,
            "y": y,
        })
        if (
            not isinstance(result.get("work_root"), str)
            or not isinstance(result.get("membership_wire"), str)
            or not isinstance(result.get("handoff_root"), str)
            or not isinstance(result.get("source_device_custody"), str)
            or type(result.get("revision")) is not int
        ):
            raise UniversalCloudGatewayError(
                "selected cloud device handoff creation response is invalid"
            )
        return result

    def list_device_handoffs(self) -> dict[str, object]:
        """Read this device's custody-filtered handoffs from the remote graph."""
        if not self.agent_session_root:
            raise UniversalCloudGatewayError(
                "device handoff projection requires a bound cloud Agent Session"
            )
        result = self.request("GET", "/api/universal/work-handoff")
        expected = {
            "projection", "application", "agent_session", "device_custody",
            "revision", "items",
        }
        if (
            set(result) != expected
            or result.get("projection") != "device-handoff-v1"
            or result.get("agent_session") != self.agent_session_root
            or not isinstance(result.get("application"), str)
            or not isinstance(result.get("device_custody"), str)
            or type(result.get("revision")) is not int
            or not isinstance(result.get("items"), (list, tuple))
        ):
            raise UniversalCloudGatewayError(
                "cloud device handoff projection response is invalid"
            )
        return result

    def list_work_claim_transfers(self) -> dict[str, object]:
        """Read this device's content-free Work continuations remotely."""
        if not self.agent_session_root:
            raise UniversalCloudGatewayError(
                "work claim transfer projection requires a bound cloud Agent Session"
            )
        result = self.request("GET", "/api/universal/work-claim-transfer")
        expected = {
            "projection", "application", "agent_session", "device_custody",
            "revision", "items",
        }
        if (
            set(result) != expected
            or result.get("projection") != "work-claim-transfer-v1"
            or result.get("agent_session") != self.agent_session_root
            or not isinstance(result.get("application"), str)
            or not isinstance(result.get("device_custody"), str)
            or type(result.get("revision")) is not int
            or not isinstance(result.get("items"), (list, tuple))
        ):
            raise UniversalCloudGatewayError(
                "cloud work claim transfer projection response is invalid"
            )
        return result

    def initiate_work_claim_transfer(
        self,
        *,
        work_root: str,
        target_device_ref: str,
        transfer_key: str,
        confirmation_digest: str,
        expires_at: float,
    ) -> dict[str, object]:
        """Release one claimed Work into the same remote graph reservation."""
        if not self.agent_session_root:
            raise UniversalCloudGatewayError(
                "work claim transfer requires a bound cloud Agent Session"
            )
        result = self.request("POST", "/api/universal/work-claim-transfer", {
            "root": work_root,
            "target_device_ref": target_device_ref,
            "transfer_key": transfer_key,
            "confirmation_digest": confirmation_digest,
            "expires_at": expires_at,
        })
        expected = {
            "application", "workshop", "compliance_observation",
            "compliance_evidence", "transfer_key", "state", "expires_at",
            "target_device_ref", "policy_revision", "release_receipt_root",
            "revision", "reused",
        }
        if (
            set(result) != expected
            or result.get("state") != "released"
            or result.get("transfer_key") != transfer_key
            or result.get("target_device_ref") != target_device_ref
            or type(result.get("expires_at")) not in (int, float)
            or type(result.get("policy_revision")) is not int
            or not isinstance(result.get("release_receipt_root"), str)
            or type(result.get("revision")) is not int
            or type(result.get("reused")) is not bool
        ):
            raise UniversalCloudGatewayError(
                "cloud work claim transfer response is invalid"
            )
        return result

    def claim_work_claim_transfer(self, transfer_key: str) -> dict[str, object]:
        """Claim one incoming remote continuation by its opaque graph key."""
        if not self.agent_session_root:
            raise UniversalCloudGatewayError(
                "work claim transfer requires a bound cloud Agent Session"
            )
        result = self.request(
            "POST", "/api/universal/work-claim-transfer-claim",
            {"transfer_key": transfer_key},
        )
        expected = {
            "application", "workshop", "compliance_observation",
            "compliance_evidence", "claimed", "reused", "work",
            "history_root", "revision", "status",
        }
        if (
            set(result) != expected
            or result.get("claimed") is not True
            or result.get("reused") is not False
            or not isinstance(result.get("work"), dict)
            or type(result.get("revision")) is not int
        ):
            raise UniversalCloudGatewayError(
                "cloud work claim transfer claim response is invalid"
            )
        return result

    def cancel_work_claim_transfer(
        self, *, transfer_key: str, cancellation_digest: str,
    ) -> dict[str, object]:
        """Cancel one source-owned remote continuation without copying Work."""
        if not self.agent_session_root:
            raise UniversalCloudGatewayError(
                "work claim transfer cancellation requires a bound cloud Agent Session"
            )
        result = self.request(
            "POST", "/api/universal/work-claim-transfer-cancel",
            {
                "transfer_key": transfer_key,
                "cancellation_digest": cancellation_digest,
            },
        )
        expected = {
            "application", "workshop", "compliance_observation",
            "compliance_evidence", "transfer_key", "state",
            "cancellation_receipt_root", "revision", "reused",
        }
        if (
            set(result) != expected
            or result.get("transfer_key") != transfer_key
            or result.get("state") != "cancelled"
            or not isinstance(result.get("cancellation_receipt_root"), str)
            or type(result.get("revision")) is not int
            or type(result.get("reused")) is not bool
        ):
            raise UniversalCloudGatewayError(
                "cloud work claim transfer cancellation response is invalid"
            )
        return result

    def record_device_handoff_receipt(
        self,
        *,
        handoff_key: str,
        kind: str,
        receipt_digest: str,
    ) -> dict[str, object]:
        """Append one graph-held delivery or cancellation receipt remotely."""
        if not self.agent_session_root:
            raise UniversalCloudGatewayError(
                "device handoff receipt requires a bound cloud Agent Session"
            )
        result = self.request("POST", "/api/universal/work-handoff-receipt", {
            "handoff_key": handoff_key,
            "kind": kind,
            "receipt_digest": receipt_digest,
        })
        if (
            not isinstance(result.get("handoff_root"), str)
            or not isinstance(result.get("receipt_root"), str)
            or type(result.get("revision")) is not int
        ):
            raise UniversalCloudGatewayError(
                "cloud device handoff receipt response is invalid"
            )
        return result

    def browser_handoff(self) -> dict[str, object]:
        raise UniversalCloudGatewayError(
            "cloud device enrollment is unavailable; use the released native onboarding path"
        )

    def browser_handoff_status(self) -> dict[str, object]:
        raise UniversalCloudGatewayError(
            "cloud device enrollment is unavailable; use the released native onboarding path"
        )

    def founder_device_custody_report(self) -> dict[str, object]:
        """Read the bounded founder device posture from an active DPoP device.

        This deliberately requires an unbound client. A runtime Agent Session
        proves a specific BABOOM body, while this route is governed by the
        founder's Cloud Session and the active Device Custody matched to DPoP.
        """
        if self.agent_session_root:
            raise UniversalCloudGatewayError(
                "founder device custody requires an unbound cloud client"
            )
        result = self.request(
            "GET", "/api/universal/devices", {"projection": "founder-report"}
        )
        expected = {
            "application", "agent_session", "projection", "revision",
            "registered", "active", "revoked", "hardware_backed",
            "reported", "truncated", "devices",
        }
        counts = (
            "revision", "registered", "active", "revoked", "hardware_backed",
            "reported",
        )
        if (
            set(result) != expected
            or result.get("projection") != "founder-local-device-custody-report"
            or not isinstance(result.get("application"), str)
            or not isinstance(result.get("agent_session"), str)
            or any(type(result.get(name)) is not int or result[name] < 0 for name in counts)
            or type(result.get("truncated")) is not bool
            or not isinstance(result.get("devices"), list)
            or result["reported"] != len(result["devices"])
            or len(result["devices"]) > 12
            or result["active"] + result["revoked"] != result["registered"]
        ):
            raise UniversalCloudGatewayError(
                "cloud founder device custody response is invalid"
            )
        selectors: set[str] = set()
        for row in result["devices"]:
            if (
                type(row) is not dict
                or set(row) != {
                    "device_ref", "label", "state", "hardware_backed",
                    "baboom_bound", "runtime_present", "baboom_present",
                }
                or type(row["device_ref"]) is not str
                or not _FOUNDER_DEVICE_REF.fullmatch(row["device_ref"])
                or row["label"] != "Device " + row["device_ref"][-8:].upper()
                or row["state"] not in {"active", "revoked"}
                or any(
                    type(row[name]) is not bool
                    for name in (
                        "hardware_backed", "baboom_bound", "runtime_present",
                        "baboom_present",
                    )
                )
                or row["baboom_present"] and not row["runtime_present"]
                or row["runtime_present"] and row["state"] != "active"
                or row["device_ref"] in selectors
            ):
                raise UniversalCloudGatewayError(
                    "cloud founder device custody row is invalid"
                )
            selectors.add(row["device_ref"])
        return result

    def revoke_founder_device_custody(
        self,
        *,
        device_ref: str,
        reason_code: str,
    ) -> dict[str, object]:
        """Submit one explicit founder device-custody revocation over DPoP."""
        if self.agent_session_root:
            raise UniversalCloudGatewayError(
                "founder device custody requires an unbound cloud client"
            )
        if (
            type(device_ref) is not str
            or not _FOUNDER_DEVICE_REF.fullmatch(device_ref)
            or type(reason_code) is not str
            or reason_code not in {
                "access-removed", "compromised", "lost", "retired",
            }
        ):
            raise UniversalCloudGatewayError(
                "cloud founder device custody revocation request is invalid"
            )
        result = self.request(
            "POST",
            "/api/universal/device-custody-revoke",
            {"device_ref": device_ref, "reason_code": reason_code},
        )
        expected = {
            "application", "agent_session", "device_ref", "state",
            "reason_code", "revision",
        }
        if (
            set(result) != expected
            or not isinstance(result.get("application"), str)
            or not isinstance(result.get("agent_session"), str)
            or result.get("device_ref") != device_ref
            or result.get("state") != "revoked"
            or result.get("reason_code") != reason_code
            or type(result.get("revision")) is not int
            or result["revision"] < 0
        ):
            raise UniversalCloudGatewayError(
                "cloud founder device custody revocation response is invalid"
            )
        return result

    def claim_next_work(self) -> dict[str, object]:
        if not self.agent_session_root:
            raise UniversalCloudGatewayError(
                "next work requires a bound cloud Agent Session"
            )
        return self.request("POST", "/api/universal/work-next", {})

    def claim_work(self, work_root: str) -> dict[str, object]:
        if not self.agent_session_root:
            raise UniversalCloudGatewayError(
                "exact work claim requires a bound cloud Agent Session"
            )
        if not isinstance(work_root, str) or not work_root:
            raise UniversalCloudGatewayError("cloud work claim target is invalid")
        return self.request(
            "POST", "/api/universal/work-claim", {"root": work_root}
        )

    def recover_work_claim(
        self,
        work_root: str,
        evidence: str,
        *,
        projection: str = "status",
    ) -> dict[str, object]:
        if not self.agent_session_root:
            raise UniversalCloudGatewayError(
                "stale cloud work claim recovery requires a bound Agent Session"
            )
        if not isinstance(work_root, str) or not work_root:
            raise UniversalCloudGatewayError("cloud work claim target is invalid")
        if not isinstance(evidence, str):
            raise UniversalCloudGatewayError("cloud work claim evidence is invalid")
        if projection not in {"status", "index"}:
            raise UniversalCloudGatewayError("cloud work claim projection is invalid")
        body: dict[str, object] = {"root": work_root, "evidence": evidence}
        if projection == "index":
            body["projection"] = "index"
        return self.request("POST", "/api/universal/work-claim-recover", body)

    def bind_runtime_device_custody(
        self,
        *,
        runtime: str,
        custody_root: str,
    ) -> dict[str, object]:
        raise UniversalCloudGatewayError(
            "cloud device binding is unavailable; use the released native onboarding path"
        )

    def request(
        self,
        method: str,
        path: str,
        body: Mapping[str, object] | None = None,
        *,
        request_id: str | None = None,
    ) -> dict[str, object]:
        method = str(method).upper()
        if (method, path) not in REMOTE_RUNTIME_ROUTES:
            raise UniversalCloudGatewayError("cloud runtime route is not admitted")
        with self._request_lock:
            if path != "/api/universal/remote-runtime" and not self._runtime_id:
                self.refresh_runtime_identity()
            if (
                self.agent_session_root
                and path != "/api/universal/agent-session-renew"
                and time.time() >= self._agent_session_expires_at - 60.0
            ):
                self.renew_agent_session()
            return self._request_once(method, path, body, request_id=request_id)

    def _request_once(
        self,
        method: str,
        path: str,
        body: Mapping[str, object] | None = None,
        *,
        request_id: str | None = None,
    ) -> dict[str, object]:
        request_body = dict(body or {})
        identity = request_id or secrets.token_urlsafe(18)
        if not _REQUEST_ID.fullmatch(identity):
            raise UniversalCloudGatewayError("cloud request identity is invalid")
        session: dict[str, object] = {}
        if self.agent_session_root and self._agent_session_token:
            if not self._runtime_id:
                raise UniversalCloudGatewayError("cloud runtime identity is unavailable")
            proof = hmac.new(
                self._agent_session_token.encode("utf-8"),
                session_proof_payload(
                    runtime_id=self._runtime_id,
                    request_id=identity,
                    method=method,
                    path=path,
                    body=request_body,
                    session_root=self.agent_session_root,
                ),
                hashlib.sha256,
            ).hexdigest()
            session = {"root": self.agent_session_root, "proof": proof}
        return self._http_request(
            method,
            path,
            {"request_id": identity, "body": request_body, "session": session},
        )


__all__ = [
    "CloudDeviceBindingVerifier",
    "DpopProofProvider",
    "REMOTE_RUNTIME_ROUTES",
    "RuntimeDeviceCredentialProvider",
    "UniversalCloudGateway",
    "UniversalCloudGatewayError",
    "UniversalCloudRuntimeClient",
    "create_application_cloud_gateway",
    "create_universal_cloud_gateway",
    "validate_universal_cloud_resource_origin",
]
