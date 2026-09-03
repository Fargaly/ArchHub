"""Remote returning-device admission over the existing Universal authority.

This module does not expose a socket and does not enroll a new device. It joins
the existing native authorization, federated identity, device custody, signed
identity relationship, and Cloud Session mechanisms against one caller-owned
``CellStore``. Short-lived OAuth values remain in the existing process-local
brokers; only their non-secret graph evidence is persisted.
"""
from __future__ import annotations

from dataclasses import dataclass
import time

import httpx

from .cell_cloud_sessions import (
    CloudSessionBroker,
    IssuedCloudSession,
    device_root_for_thumbprint,
)
from .cell_device_custody import (
    DeviceCustodyProtocol,
    list_device_custody_roots,
    read_device_custody,
)
from .cell_federated_identity import FederatedIdentityBroker
from .cell_identity import (
    IdentityProtocol,
    RelationshipAuthorityBroker,
    RelationshipAuthorityDenied,
    active_membership_roots,
    verify_authority_relationship,
)
from .cell_native_auth import (
    NativeAuthenticationProtocol,
    NativeAuthorizationBroker,
    NativeClientAdmissionVerifier,
    StartedNativeAuthorization,
    exchange_native_authorization_code,
    issue_native_cloud_session,
)
from .cell_protocols import read_relation
from .universal_cell import CellStore, InvalidCell, Snapshot


class ReturningDeviceAdmissionDenied(PermissionError):
    """The key has no one active returning-device authority."""


@dataclass(frozen=True, slots=True)
class ReturningDeviceAdmission:
    """Non-secret graph evidence read for one returning device."""

    device_root: str
    custody_root: str
    binding_root: str
    subject_root: str
    tenant_root: str
    audience_root: str
    revision: int


class ReturningDeviceAdmissionVerifier:
    """Resolve one active custody and signed subject/audience binding."""

    def __init__(
        self,
        *,
        device_custody_protocol: DeviceCustodyProtocol,
        identity_protocol: IdentityProtocol,
        relationship_broker: RelationshipAuthorityBroker,
        tenant_root: str,
        audience_root: str,
    ) -> None:
        if not isinstance(device_custody_protocol, DeviceCustodyProtocol):
            raise TypeError("returning-device verifier requires custody protocol")
        if not isinstance(identity_protocol, IdentityProtocol):
            raise TypeError("returning-device verifier requires identity protocol")
        if not isinstance(
            relationship_broker, RelationshipAuthorityBroker
        ):
            raise TypeError(
                "returning-device verifier requires relationship authority"
            )
        if not tenant_root or not audience_root:
            raise ValueError(
                "returning-device verifier requires tenant and audience"
            )
        self._device_custody_protocol = device_custody_protocol
        self._identity_protocol = identity_protocol
        self._relationship_broker = relationship_broker
        self._tenant_root = tenant_root
        self._audience_root = audience_root

    def verify(
        self,
        snapshot: Snapshot,
        *,
        proof_key_thumbprint: str,
        now: float | None = None,
    ) -> ReturningDeviceAdmission:
        current = time.time() if now is None else float(now)
        try:
            device_root = device_root_for_thumbprint(proof_key_thumbprint)
        except ValueError as exc:
            raise ReturningDeviceAdmissionDenied(
                "device has no active returning-device custody"
            ) from exc

        active_custodies = []
        for custody_root in list_device_custody_roots(
            snapshot, self._device_custody_protocol
        ):
            try:
                custody = read_device_custody(
                    snapshot,
                    self._device_custody_protocol,
                    custody_root,
                )
            except (InvalidCell, KeyError):
                continue
            if (
                custody.device_root == device_root
                and custody.state_root
                == self._device_custody_protocol.states["active"]
            ):
                active_custodies.append(custody_root)
        if len(active_custodies) != 1:
            raise ReturningDeviceAdmissionDenied(
                "device has no active returning-device custody"
            )

        bindings: list[tuple[str, str]] = []
        for member in read_relation(
            snapshot, self._identity_protocol.root_id, budget=100_000
        ):
            if (
                member.role_id
                != self._identity_protocol.roles["relationship-member"]
            ):
                continue
            try:
                relationship = verify_authority_relationship(
                    snapshot,
                    self._identity_protocol,
                    self._relationship_broker,
                    member.participant_id,
                    now=current,
                )
            except (RelationshipAuthorityDenied, InvalidCell, KeyError):
                continue
            if (
                relationship.kind_root
                == self._identity_protocol.kinds["audience-binding"]
                and relationship.source_root == device_root
                and relationship.tenant_root == self._tenant_root
                and relationship.scope_root == self._audience_root
            ):
                bindings.append(
                    (relationship.root_id, relationship.target_root)
                )
        if len(bindings) != 1:
            raise ReturningDeviceAdmissionDenied(
                "device has no unique returning-device identity binding"
            )
        binding_root, subject_root = bindings[0]
        if self._tenant_root not in active_membership_roots(
            snapshot,
            self._identity_protocol,
            self._relationship_broker,
            subject_root,
            self._tenant_root,
            now=current,
        ):
            raise ReturningDeviceAdmissionDenied(
                "returning-device tenant membership is inactive"
            )
        return ReturningDeviceAdmission(
            device_root,
            active_custodies[0],
            binding_root,
            subject_root,
            self._tenant_root,
            self._audience_root,
            snapshot.revision,
        )


class RemoteNativeCloudLoginBroker:
    """Issue one returning-device Cloud Session without a prior session."""

    def __init__(
        self,
        *,
        store: CellStore,
        protocol: NativeAuthenticationProtocol,
        registration_root: str,
        native_authorization_broker: NativeAuthorizationBroker,
        federated_identity_broker: FederatedIdentityBroker,
        cloud_session_broker: CloudSessionBroker,
        client_admission_verifier: NativeClientAdmissionVerifier,
        returning_device_verifier: ReturningDeviceAdmissionVerifier,
        allowed_action_roots: tuple[str, ...],
    ) -> None:
        if not isinstance(store, CellStore):
            raise TypeError("remote native login requires one Cell store")
        if not isinstance(protocol, NativeAuthenticationProtocol):
            raise TypeError("remote native login requires native protocol")
        if not registration_root:
            raise ValueError("remote native login registration is invalid")
        if not isinstance(
            native_authorization_broker, NativeAuthorizationBroker
        ):
            raise TypeError(
                "remote native login requires native authorization broker"
            )
        if not isinstance(federated_identity_broker, FederatedIdentityBroker):
            raise TypeError(
                "remote native login requires federated identity broker"
            )
        if not isinstance(cloud_session_broker, CloudSessionBroker):
            raise TypeError("remote native login requires Cloud Session broker")
        if not hasattr(client_admission_verifier, "verify"):
            raise TypeError(
                "remote native login requires client admission verifier"
            )
        if not isinstance(
            returning_device_verifier, ReturningDeviceAdmissionVerifier
        ):
            raise TypeError(
                "remote native login requires returning-device verifier"
            )
        if (
            not allowed_action_roots
            or any(not isinstance(root, str) or not root for root in allowed_action_roots)
        ):
            raise ValueError("remote native login requires released actions")
        self._store = store
        self._protocol = protocol
        self._registration_root = registration_root
        self._native_authorization_broker = native_authorization_broker
        self._federated_identity_broker = federated_identity_broker
        self._cloud_session_broker = cloud_session_broker
        self._client_admission_verifier = client_admission_verifier
        self._returning_device_verifier = returning_device_verifier
        self._allowed_action_roots = tuple(allowed_action_roots)

    def start(
        self,
        *,
        device_thumbprint: str,
        redirect_port: int,
        lifetime_seconds: float = 300.0,
        now: float | None = None,
    ) -> StartedNativeAuthorization:
        """Create one native transaction only for an already-trusted key."""
        self._returning_device_verifier.verify(
            self._store.snapshot(),
            proof_key_thumbprint=device_thumbprint,
            now=now,
        )
        return self._native_authorization_broker.start(
            self._store,
            self._protocol,
            self._registration_root,
            redirect_port=redirect_port,
            device_thumbprint=device_thumbprint,
            lifetime_seconds=lifetime_seconds,
            now=now,
        )

    def complete_and_issue(
        self,
        transaction_root: str,
        *,
        state: str,
        response_issuer: str,
        authorization_code: str,
        token_client: httpx.Client | None = None,
        session_lifetime_seconds: float = 900.0,
        now: float | None = None,
    ) -> IssuedCloudSession:
        """Consume one callback and return one sender-constrained session."""
        authorization = self._native_authorization_broker.complete(
            self._store,
            self._protocol,
            transaction_root,
            state=state,
            response_issuer=response_issuer,
            authorization_code=authorization_code,
            now=now,
        )
        self._returning_device_verifier.verify(
            self._store.snapshot(),
            proof_key_thumbprint=authorization.device_thumbprint,
            now=now,
        )
        assertion = exchange_native_authorization_code(
            authorization,
            client=token_client,
        )
        self._returning_device_verifier.verify(
            self._store.snapshot(),
            proof_key_thumbprint=assertion.device_thumbprint,
            now=now,
        )
        return issue_native_cloud_session(
            self._store,
            assertion,
            federated_identity_broker=self._federated_identity_broker,
            cloud_session_broker=self._cloud_session_broker,
            client_admission_verifier=self._client_admission_verifier,
            allowed_action_roots=self._allowed_action_roots,
            lifetime_seconds=session_lifetime_seconds,
            now=now,
        )


__all__ = [
    "RemoteNativeCloudLoginBroker",
    "ReturningDeviceAdmission",
    "ReturningDeviceAdmissionDenied",
    "ReturningDeviceAdmissionVerifier",
]
