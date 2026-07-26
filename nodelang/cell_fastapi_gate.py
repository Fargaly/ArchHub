"""FastAPI adapter for graph-defined cloud routes and the universal gate.

This module contains no role table and no endpoint permission catalogue.  It
projects the matched APIRoute's method/path into a registered route relation,
resolves that relation's object binding, verifies DPoP/session authority, and
submits the relation's exact fields to ``CloudRequestGate`` before invoking the
endpoint function.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import time
from typing import Any
from urllib.parse import urlsplit

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from .cell_authorization import AuthorizationDenied
from .cell_cloud_gate import CloudRequestGate
from .cell_cloud_routes import (
    CloudRouteDenied,
    CloudRouteProtocol,
    find_cloud_route,
    resolve_cloud_route,
)
from .cell_cloud_sessions import CloudSessionDenied
from .cell_dpop import DpopProofDenied
from .cell_dpop_nonce import (
    DpopNonceDenied,
    ResourceServerNonceBroker,
    extract_unverified_proof_nonce,
)
from .universal_cell import CellStore, InvalidCell


_RUNTIME_STATE_KEY = "archhub_graph_cloud_runtime_v1"
_EXPOSE_HEADERS = "DPoP-Nonce, WWW-Authenticate"
_DPOP_CHALLENGE = 'DPoP algs="ES256 PS256 EdDSA"'


@dataclass(slots=True)
class GraphCloudRuntime:
    store: CellStore
    route_protocol: CloudRouteProtocol
    gate: CloudRequestGate
    nonce_broker: ResourceServerNonceBroker
    resource_origin: str
    clock: Callable[[], float] = field(default=time.time, repr=False)

    def __post_init__(self) -> None:
        parsed = urlsplit(self.resource_origin)
        host = (parsed.hostname or "").lower()
        secure = parsed.scheme == "https"
        loopback = parsed.scheme == "http" and host in {
            "localhost", "127.0.0.1", "::1"
        }
        if (
            not (secure or loopback)
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "graph cloud resource origin must be a bare HTTPS origin"
            )
        self.resource_origin = self.resource_origin.rstrip("/")

    def target_uri(self, request: Request) -> str:
        raw_path = request.scope.get("raw_path")
        if isinstance(raw_path, bytes):
            try:
                path = raw_path.decode("ascii")
            except UnicodeDecodeError as exc:
                raise CloudRouteDenied("request path is not ASCII-encoded") from exc
        else:
            path = request.url.path
        if not path.startswith("/") or "?" in path or "#" in path:
            raise CloudRouteDenied("request target path is invalid")
        return self.resource_origin + path


def install_graph_cloud_runtime(app: Any, runtime: GraphCloudRuntime) -> None:
    """Install the only runtime capability used by governed APIRoutes."""
    setattr(app.state, _RUNTIME_STATE_KEY, runtime)


def _runtime(request: Request) -> GraphCloudRuntime:
    runtime = getattr(request.app.state, _RUNTIME_STATE_KEY, None)
    if not isinstance(runtime, GraphCloudRuntime):
        raise CloudRouteDenied("graph cloud runtime is not installed")
    return runtime


def _single_header(request: Request, name: str) -> str:
    values = request.headers.getlist(name)
    if len(values) != 1 or not values[0]:
        raise DpopProofDenied("request requires exactly one %s header" % name)
    return values[0]


def _access_token(request: Request) -> str:
    authorization = _single_header(request, "authorization")
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "dpop" or not parts[1]:
        raise DpopProofDenied("Authorization scheme must be DPoP")
    if len(parts[1]) > 512:
        raise DpopProofDenied("DPoP access token is too large")
    return parts[1]


def _response_headers(*, nonce: str | None = None) -> dict[str, str]:
    headers = {
        "WWW-Authenticate": _DPOP_CHALLENGE,
        "Cache-Control": "no-store",
        "Access-Control-Expose-Headers": _EXPOSE_HEADERS,
    }
    if nonce is not None:
        headers["DPoP-Nonce"] = nonce
        headers["WWW-Authenticate"] = (
            _DPOP_CHALLENGE
            + ', error="use_dpop_nonce"'
            + ', error_description="A fresh DPoP proof is required"'
        )
    return headers


def _authentication_challenge(
    runtime: GraphCloudRuntime,
    token: str | None,
    *,
    now: float,
) -> JSONResponse:
    nonce = None
    if token:
        try:
            nonce = runtime.nonce_broker.mint(token, now=now)
        except Exception:
            return JSONResponse(
                status_code=503,
                content={"detail": "dpop_nonce_authority_unavailable"},
                headers={"Cache-Control": "no-store"},
            )
    return JSONResponse(
        status_code=401,
        content={"detail": "dpop_authentication_required"},
        headers=_response_headers(nonce=nonce),
    )


class GraphGovernedAPIRoute(APIRoute):
    """Refuse endpoint execution until its graph route and policy authorize."""

    def get_route_handler(self) -> Callable[[Request], Any]:
        endpoint_handler = super().get_route_handler()
        path_template = self.path

        async def governed_handler(request: Request) -> Response:
            try:
                runtime = _runtime(request)
                snapshot = runtime.store.snapshot()
                route = find_cloud_route(
                    snapshot,
                    runtime.route_protocol,
                    method=request.method,
                    path_template=path_template,
                )
                resolved = resolve_cloud_route(
                    snapshot, route, path_parameters=request.path_params
                )
                target_uri = runtime.target_uri(request)
            except (CloudRouteDenied, InvalidCell, ValueError):
                return JSONResponse(
                    status_code=503,
                    content={"detail": "graph_route_unavailable"},
                    headers={"Cache-Control": "no-store"},
                )

            now = runtime.clock()
            token: str | None = None
            try:
                token = _access_token(request)
                proof_text = _single_header(request, "dpop")
                if len(proof_text) > 64 * 1024:
                    raise DpopProofDenied("DPoP proof is too large")
                proof = proof_text.encode("ascii")
                claimed_nonce = extract_unverified_proof_nonce(proof)
                nonce = runtime.nonce_broker.verify(
                    claimed_nonce, token, now=now
                )
                authorized = runtime.gate.authorize(
                    runtime.store,
                    token,
                    proof,
                    action_root=resolved.action_root,
                    object_root=resolved.object_root,
                    http_method=request.method,
                    target_uri=target_uri,
                    request_nonce=nonce,
                    resource_lineage_roots=resolved.resource_lineage_roots,
                    interface_root=resolved.interface_root,
                    purpose_root=resolved.purpose_root,
                    classification_root=resolved.classification_root,
                    audience_root=resolved.audience_root,
                    lifecycle_state_root=resolved.lifecycle_state_root,
                    operational_state_root=resolved.operational_state_root,
                    now=now,
                )
            except AuthorizationDenied:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "graph_authorization_denied"},
                    headers={"Cache-Control": "no-store"},
                )
            except (
                CloudSessionDenied,
                DpopProofDenied,
                DpopNonceDenied,
                UnicodeEncodeError,
            ):
                return _authentication_challenge(runtime, token, now=now)

            request.state.archhub_authorized_cloud_request = authorized
            request.state.archhub_route_root = resolved.route_root
            request.state.archhub_object_root = resolved.object_root
            return await endpoint_handler(request)

        return governed_handler


__all__ = [
    "GraphCloudRuntime",
    "GraphGovernedAPIRoute",
    "install_graph_cloud_runtime",
]
