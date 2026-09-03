"""One cloud request gate: proof-of-possession authentication then policy."""
from __future__ import annotations

from dataclasses import dataclass

from .cell_authorization import (
    AuthenticationBroker,
    AuthorizationDecision,
    AuthorizationProtocol,
    AuthorizationRequest,
    require_authorization,
)
from .cell_cloud_sessions import (
    CloudRequestAuthentication,
    CloudSessionBroker,
)
from .universal_cell import CellStore


@dataclass(frozen=True, slots=True)
class AuthorizedCloudRequest:
    authentication: CloudRequestAuthentication
    decision: AuthorizationDecision


class CloudRequestGate:
    """Fail-closed entrypoint shared by HTTP, WebSocket, and job adapters."""

    def __init__(
        self,
        *,
        session_broker: CloudSessionBroker,
        authorization_protocol: AuthorizationProtocol,
        authentication_broker: AuthenticationBroker,
        policy_root: str,
    ) -> None:
        self._session_broker = session_broker
        self._authorization_protocol = authorization_protocol
        self._authentication_broker = authentication_broker
        self._policy_root = policy_root

    def authorize(
        self,
        store: CellStore,
        access_token: str,
        request_proof: bytes,
        *,
        action_root: str,
        object_root: str,
        http_method: str,
        target_uri: str,
        request_nonce: str,
        resource_lineage_roots: tuple[str, ...] = (),
        interface_root: str | None = None,
        purpose_root: str | None = None,
        classification_root: str | None = None,
        audience_root: str | None = None,
        lifecycle_state_root: str | None = None,
        operational_state_root: str | None = None,
        invocation_count: int = 0,
        now: float | None = None,
    ) -> AuthorizedCloudRequest:
        authentication = self._session_broker.authenticate_request(
            store,
            access_token,
            request_proof,
            requested_action_root=action_root,
            http_method=http_method,
            target_uri=target_uri,
            expected_nonce=request_nonce,
            now=now,
        )
        request = AuthorizationRequest(
            action_root=action_root,
            object_root=object_root,
            resource_lineage_roots=resource_lineage_roots,
            interface_root=interface_root,
            purpose_root=purpose_root,
            classification_root=classification_root,
            audience_root=audience_root,
            lifecycle_state_root=lifecycle_state_root,
            operational_state_root=operational_state_root,
            invocation_count=invocation_count,
            now=now,
        )
        decision = require_authorization(
            store.snapshot(),
            self._authorization_protocol,
            self._policy_root,
            self._authentication_broker,
            authentication.context,
            request,
        )
        return AuthorizedCloudRequest(authentication, decision)


__all__ = ["AuthorizedCloudRequest", "CloudRequestGate"]
