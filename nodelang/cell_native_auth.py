"""Native OpenID Connect authorization as universal-cell relations.

The graph holds released public client configuration, one bounded transaction,
and one immutable completion relation.  Browser/session secrets stay in the
trusted process: raw state, nonce, PKCE verifier, authorization code, and token
responses are never persisted as Cell atoms.

The flow follows RFC 8252, RFC 7636, RFC 9207, and RFC 9700: external browser,
exact IPv4 loopback redirect, PKCE S256, exact response issuer, bounded
transaction lifetime, and one-use callback state.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import hmac
import json
import secrets
import threading
import time
from types import MappingProxyType
from typing import Mapping, Protocol
from urllib.parse import urlencode, urlsplit

import httpx

from .cell_cloud_sessions import (
    CloudSessionBroker,
    IssuedCloudSession,
    device_root_for_thumbprint,
)
from .cell_federated_identity import FederatedIdentityBroker
from .cell_identity import (
    IdentityProtocol,
    RelationshipAuthorityBroker,
    RelationshipAuthorityDenied,
    grant_authority_relationship,
    verify_authority_relationship,
)
from .cell_oidc_discovery import VerifiedOidcDiscovery
from .cell_protocols import (
    RelationMember,
    compose_relation_cells,
    prepare_append_relation_member,
    read_relation,
)
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


MAX_TOKEN_RESPONSE_BYTES = 1024 * 1024
MAX_ID_TOKEN_BYTES = 256 * 1024

ROLE_NAMES = (
    "vocabulary-member",
    "client-member",
    "transaction-member",
    "completion-member",
    "issuer",
    "client-id",
    "authorization-endpoint",
    "token-endpoint",
    "redirect-host",
    "redirect-path",
    "scope",
    "metadata-expires-at",
    "client",
    "client-authority",
    "redirect-uri",
    "state-digest",
    "nonce-digest",
    "pkce-challenge",
    "pkce-method",
    "device",
    "created-at",
    "expires-at",
    "transaction",
    "authorization-code-digest",
    "response-issuer",
    "completed-at",
    "manifest-digest",
)


class NativeAuthenticationDenied(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class NativeAuthenticationProtocol:
    root_id: str
    roles: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell(
                "unknown native-authentication role %r" % name
            ) from exc


@dataclass(frozen=True, slots=True)
class NativeClientRegistration:
    root_id: str
    issuer_root: str
    client_id_root: str
    authorization_endpoint_root: str
    token_endpoint_root: str
    redirect_host_root: str
    redirect_path_root: str
    scope_roots: tuple[str, ...]
    metadata_expires_at_root: str
    manifest_digest_root: str


@dataclass(frozen=True, slots=True)
class NativeAuthorizationTransaction:
    root_id: str
    client_root: str
    client_authority_root: str
    redirect_uri_root: str
    state_digest_root: str
    nonce_digest_root: str
    pkce_challenge_root: str
    pkce_method_root: str
    device_root: str
    created_at_root: str
    expires_at_root: str
    manifest_digest_root: str


@dataclass(frozen=True, slots=True)
class NativeAuthorizationCompletion:
    root_id: str
    transaction_root: str
    authorization_code_digest_root: str
    response_issuer_root: str
    completed_at_root: str
    manifest_digest_root: str


@dataclass(frozen=True, slots=True)
class StartedNativeAuthorization:
    transaction_root: str
    authorization_url: str
    expires_at: float


@dataclass(frozen=True, slots=True)
class NativeClientAdmissionEvidence:
    relationship_root: str
    tenant_root: str
    audience_root: str


class NativeClientAdmissionVerifier(Protocol):
    def verify(
        self,
        snapshot: Snapshot,
        *,
        registration_root: str,
        now: float,
    ) -> NativeClientAdmissionEvidence:
        ...


_AUTHORIZATION_CODE_KEY = object()
_IDENTITY_ASSERTION_KEY = object()


class NativeAuthorizationCode:
    """One-use process capability containing callback and PKCE secrets."""

    __slots__ = (
        "transaction_root",
        "completion_root",
        "registration_root",
        "issuer",
        "client_id",
        "token_endpoint",
        "redirect_uri",
        "authorization_code",
        "code_verifier",
        "nonce",
        "device_thumbprint",
        "tenant_root",
        "audience_root",
        "client_authority_root",
        "_used",
        "_lock",
    )

    def __init__(
        self,
        key: object,
        *,
        transaction_root: str,
        completion_root: str,
        registration_root: str,
        issuer: str,
        client_id: str,
        token_endpoint: str,
        redirect_uri: str,
        authorization_code: str,
        code_verifier: str,
        nonce: str,
        device_thumbprint: str,
        tenant_root: str,
        audience_root: str,
        client_authority_root: str,
    ) -> None:
        if key is not _AUTHORIZATION_CODE_KEY:
            raise TypeError("authorization code capability is broker authority")
        self.transaction_root = transaction_root
        self.completion_root = completion_root
        self.registration_root = registration_root
        self.issuer = issuer
        self.client_id = client_id
        self.token_endpoint = token_endpoint
        self.redirect_uri = redirect_uri
        self.authorization_code = authorization_code
        self.code_verifier = code_verifier
        self.nonce = nonce
        self.device_thumbprint = device_thumbprint
        self.tenant_root = tenant_root
        self.audience_root = audience_root
        self.client_authority_root = client_authority_root
        self._used = False
        self._lock = threading.RLock()

    def consume(self) -> None:
        with self._lock:
            if self._used:
                raise NativeAuthenticationDenied(
                    "authorization code capability was already consumed"
                )
            self._used = True

    def __reduce_ex__(self, protocol):
        raise TypeError("authorization code capability cannot be serialized")


class NativeIdentityAssertion:
    """Broker-only transient ID token ready for the federated court."""

    __slots__ = (
        "transaction_root",
        "completion_root",
        "registration_root",
        "id_token",
        "expected_issuer",
        "expected_audience",
        "expected_nonce",
        "device_thumbprint",
        "tenant_root",
        "audience_root",
        "client_authority_root",
        "_used",
        "_lock",
    )

    def __init__(
        self,
        key: object,
        *,
        transaction_root: str,
        completion_root: str,
        registration_root: str,
        id_token: bytes,
        expected_issuer: str,
        expected_audience: str,
        expected_nonce: str,
        device_thumbprint: str,
        tenant_root: str,
        audience_root: str,
        client_authority_root: str,
    ) -> None:
        if key is not _IDENTITY_ASSERTION_KEY:
            raise TypeError("native identity assertion is broker authority")
        self.transaction_root = transaction_root
        self.completion_root = completion_root
        self.registration_root = registration_root
        self.id_token = id_token
        self.expected_issuer = expected_issuer
        self.expected_audience = expected_audience
        self.expected_nonce = expected_nonce
        self.device_thumbprint = device_thumbprint
        self.tenant_root = tenant_root
        self.audience_root = audience_root
        self.client_authority_root = client_authority_root
        self._used = False
        self._lock = threading.RLock()

    def consume(self) -> None:
        with self._lock:
            if self._used:
                raise NativeAuthenticationDenied(
                    "native identity assertion was already consumed"
                )
            self._used = True

    def __reduce_ex__(self, protocol):
        raise TypeError("native identity assertion cannot be serialized")


@dataclass(slots=True)
class _PendingAuthorization:
    transaction_root: str
    registration_root: str
    state: str
    nonce: str
    code_verifier: str
    redirect_uri: str
    device_thumbprint: str
    tenant_root: str
    audience_root: str
    client_authority_root: str
    expires_at: float
    used: bool = False
    completing: bool = False


def _terminal(root_id: str, value: str) -> Cell:
    encoded = value.encode("utf-8")
    if not encoded:
        raise InvalidCell("native-authentication scalar cannot be empty")
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, encoded)


def _atom(snapshot: Snapshot, root_id: str, label: str) -> str:
    try:
        cell = snapshot.cells[root_id]
        if cell.link0 != NULL_CELL_ID or cell.link1 != NULL_CELL_ID:
            raise NativeAuthenticationDenied("%s is not scalar" % label)
        return cell.atom.decode("utf-8")
    except (KeyError, UnicodeDecodeError) as exc:
        raise NativeAuthenticationDenied(
            "%s is missing or invalid" % label
        ) from exc


def _for_role(
    members: tuple[RelationMember, ...], role_id: str
) -> tuple[str, ...]:
    return tuple(
        member.participant_id for member in members
        if member.role_id == role_id
    )


def _one(
    members: tuple[RelationMember, ...], role_id: str, label: str
) -> str:
    values = _for_role(members, role_id)
    if len(values) != 1:
        raise NativeAuthenticationDenied(
            "native authentication requires exactly one %s" % label
        )
    return values[0]


def _digest(document: Mapping[str, object]) -> str:
    payload = json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _base64url_sha256(value: str) -> str:
    return base64.urlsafe_b64encode(
        hashlib.sha256(value.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")


def _registered(
    snapshot: Snapshot,
    protocol: NativeAuthenticationProtocol,
    role_name: str,
) -> tuple[str, ...]:
    return _for_role(
        read_relation(snapshot, protocol.root_id, budget=100_000),
        protocol.role(role_name),
    )


def bootstrap_native_authentication_protocol(
    store: CellStore,
    *,
    prefix: str = "native-authentication-protocol",
) -> NativeAuthenticationProtocol:
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    root_id = prefix + ":root"
    scalars = tuple(_terminal(root, name) for name, root in roles.items())
    relation = compose_relation_cells(
        ((roles["vocabulary-member"], root) for root in roles.values()),
        relation_id=root_id,
    )
    store.commit(store.revision, create=(*scalars, *relation.cells))
    return NativeAuthenticationProtocol(root_id, MappingProxyType(roles))


def project_native_authentication_protocol(
    snapshot: Snapshot,
    *,
    prefix: str = "native-authentication-protocol",
) -> NativeAuthenticationProtocol:
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    root_id = prefix + ":root"
    if any(root not in snapshot.cells for root in (root_id, *roles.values())):
        raise InvalidCell("native-authentication protocol is incomplete")
    return NativeAuthenticationProtocol(root_id, MappingProxyType(roles))


def _validate_redirect_path(path: str) -> str:
    value = str(path)
    if (
        not value.startswith("/")
        or value.startswith("//")
        or "?" in value
        or "#" in value
        or "\\" in value
        or len(value) > 512
        or not value.isascii()
    ):
        raise ValueError("native redirect path is invalid")
    return value


def _validate_public_client_id(client_id: str) -> str:
    value = str(client_id)
    if (
        not value
        or len(value) > 512
        or any(ord(character) < 0x21 or ord(character) > 0x7E for character in value)
    ):
        raise ValueError("native public client ID is invalid")
    return value


def _validate_scopes(scopes: tuple[str, ...]) -> tuple[str, ...]:
    values = tuple(dict.fromkeys(str(value) for value in scopes))
    if "openid" not in values or not values:
        raise ValueError("native OIDC scopes must include openid")
    if any(
        not value
        or len(value) > 128
        or any(
            ord(character) not in range(0x21, 0x7F)
            or character in {'"', "\\"}
            for character in value
        )
        for value in values
    ):
        raise ValueError("native OIDC scope is invalid")
    return values


def build_native_client_registration(
    store: CellStore,
    protocol: NativeAuthenticationProtocol,
    discovery_authority: VerifiedOidcDiscovery,
    *,
    registration_id: str,
    client_id: str,
    scopes: tuple[str, ...] = ("openid",),
    redirect_host: str = "127.0.0.1",
    redirect_path: str = "/oauth/callback",
    now: float | None = None,
) -> str:
    """Release one public native client only from verified discovery output."""
    if type(discovery_authority) is not VerifiedOidcDiscovery:
        raise NativeAuthenticationDenied(
            "native client registration requires verified discovery authority"
        )
    discovery = discovery_authority.snapshot
    current = time.time() if now is None else now
    client_id = _validate_public_client_id(client_id)
    scopes = _validate_scopes(scopes)
    redirect_path = _validate_redirect_path(redirect_path)
    if redirect_host != "127.0.0.1":
        raise ValueError("native redirect host must be the IPv4 loopback literal")
    if (
        discovery.authorization_endpoint is None
        or discovery.token_endpoint is None
        or "code" not in discovery.response_types
        or "S256" not in discovery.code_challenge_methods
        or not discovery.authorization_response_issuer_supported
    ):
        raise NativeAuthenticationDenied(
            "OIDC discovery is not ready for a protected native code flow"
        )
    if current >= discovery.metadata_expires_at:
        raise NativeAuthenticationDenied("OIDC discovery metadata expired")
    document = {
        "issuer": discovery.issuer,
        "client_id": client_id,
        "authorization_endpoint": discovery.authorization_endpoint,
        "token_endpoint": discovery.token_endpoint,
        "redirect_host": redirect_host,
        "redirect_path": redirect_path,
        "scopes": list(scopes),
        "metadata_expires_at": "%.6f" % discovery.metadata_expires_at,
    }
    digest = _digest(document)
    fields: list[tuple[str, str]] = [
        ("issuer", discovery.issuer),
        ("client-id", client_id),
        ("authorization-endpoint", discovery.authorization_endpoint),
        ("token-endpoint", discovery.token_endpoint),
        ("redirect-host", redirect_host),
        ("redirect-path", redirect_path),
        ("metadata-expires-at", document["metadata_expires_at"]),
        ("manifest-digest", digest),
    ]
    fields.extend(("scope-%s" % index, value) for index, value in enumerate(scopes))
    scalar_roots = {
        name: "%s:field:%s" % (registration_id, name) for name, _ in fields
    }
    members = [
        (protocol.role("issuer"), scalar_roots["issuer"]),
        (protocol.role("client-id"), scalar_roots["client-id"]),
        (
            protocol.role("authorization-endpoint"),
            scalar_roots["authorization-endpoint"],
        ),
        (protocol.role("token-endpoint"), scalar_roots["token-endpoint"]),
        (protocol.role("redirect-host"), scalar_roots["redirect-host"]),
        (protocol.role("redirect-path"), scalar_roots["redirect-path"]),
        *(
            (protocol.role("scope"), scalar_roots["scope-%s" % index])
            for index in range(len(scopes))
        ),
        (
            protocol.role("metadata-expires-at"),
            scalar_roots["metadata-expires-at"],
        ),
        (protocol.role("manifest-digest"), scalar_roots["manifest-digest"]),
    ]
    snapshot = store.snapshot()
    relation = compose_relation_cells(members, relation_id=registration_id)
    patch = prepare_append_relation_member(
        snapshot,
        protocol.root_id,
        protocol.role("client-member"),
        registration_id,
        budget=100_000,
    )
    store.commit(
        snapshot.revision,
        create=(
            *(_terminal(scalar_roots[name], value) for name, value in fields),
            *relation.cells,
            *patch.create,
        ),
        replace=patch.replace,
    )
    read_native_client_registration(store.snapshot(), protocol, registration_id)
    return registration_id


def read_native_client_registration(
    snapshot: Snapshot,
    protocol: NativeAuthenticationProtocol,
    registration_root: str,
) -> NativeClientRegistration:
    if registration_root not in _registered(snapshot, protocol, "client-member"):
        raise NativeAuthenticationDenied("native client is not registered")
    members = read_relation(snapshot, registration_root, budget=256)
    allowed = {
        protocol.role(name) for name in (
            "issuer", "client-id", "authorization-endpoint", "token-endpoint",
            "redirect-host", "redirect-path", "scope", "metadata-expires-at",
            "manifest-digest",
        )
    }
    if any(member.role_id not in allowed for member in members):
        raise NativeAuthenticationDenied("native client contains undeclared fields")
    registration = NativeClientRegistration(
        registration_root,
        _one(members, protocol.role("issuer"), "issuer"),
        _one(members, protocol.role("client-id"), "client ID"),
        _one(
            members,
            protocol.role("authorization-endpoint"),
            "authorization endpoint",
        ),
        _one(members, protocol.role("token-endpoint"), "token endpoint"),
        _one(members, protocol.role("redirect-host"), "redirect host"),
        _one(members, protocol.role("redirect-path"), "redirect path"),
        _for_role(members, protocol.role("scope")),
        _one(
            members,
            protocol.role("metadata-expires-at"),
            "metadata expiry",
        ),
        _one(members, protocol.role("manifest-digest"), "manifest digest"),
    )
    document = {
        "issuer": _atom(snapshot, registration.issuer_root, "issuer"),
        "client_id": _atom(snapshot, registration.client_id_root, "client ID"),
        "authorization_endpoint": _atom(
            snapshot,
            registration.authorization_endpoint_root,
            "authorization endpoint",
        ),
        "token_endpoint": _atom(
            snapshot, registration.token_endpoint_root, "token endpoint"
        ),
        "redirect_host": _atom(
            snapshot, registration.redirect_host_root, "redirect host"
        ),
        "redirect_path": _atom(
            snapshot, registration.redirect_path_root, "redirect path"
        ),
        "scopes": [
            _atom(snapshot, root, "scope") for root in registration.scope_roots
        ],
        "metadata_expires_at": _atom(
            snapshot,
            registration.metadata_expires_at_root,
            "metadata expiry",
        ),
    }
    expected = _digest(document)
    if not hmac.compare_digest(
        expected,
        _atom(snapshot, registration.manifest_digest_root, "manifest digest"),
    ):
        raise NativeAuthenticationDenied("native client manifest drifted")
    return registration


def activate_native_client_registration(
    store: CellStore,
    native_protocol: NativeAuthenticationProtocol,
    identity_protocol: IdentityProtocol,
    relationship_broker: RelationshipAuthorityBroker,
    administration_handle: object,
    *,
    registration_root: str,
    relationship_id: str,
    tenant_root: str,
    audience_root: str,
    administrator_root: str,
    reason: str,
    evidence_roots: tuple[str, ...] = (),
    now: float | None = None,
) -> str:
    """Sign the explicit tenant/audience wire that activates one client."""
    registration = read_native_client_registration(
        store.snapshot(), native_protocol, registration_root
    )
    evidence = tuple(dict.fromkeys((
        registration.manifest_digest_root,
        *evidence_roots,
    )))
    return grant_authority_relationship(
        store,
        identity_protocol,
        relationship_broker,
        administration_handle,
        relationship_id=relationship_id,
        source_root=registration_root,
        target_root=tenant_root,
        kind="audience-binding",
        tenant_root=tenant_root,
        scope_root=audience_root,
        administrator_root=administrator_root,
        reason=reason,
        evidence_roots=evidence,
        now=now,
    )


class SignedNativeClientAdmissionVerifier:
    """Require one active signed client-to-tenant/audience activation wire."""

    def __init__(
        self,
        *,
        native_protocol: NativeAuthenticationProtocol,
        identity_protocol: IdentityProtocol,
        relationship_broker: RelationshipAuthorityBroker,
        tenant_root: str,
        audience_root: str,
    ) -> None:
        self._native_protocol = native_protocol
        self._identity_protocol = identity_protocol
        self._relationship_broker = relationship_broker
        self._tenant_root = tenant_root
        self._audience_root = audience_root

    def verify(
        self,
        snapshot: Snapshot,
        *,
        registration_root: str,
        now: float,
    ) -> NativeClientAdmissionEvidence:
        registration = read_native_client_registration(
            snapshot, self._native_protocol, registration_root
        )
        matches = []
        for member in read_relation(
            snapshot, self._identity_protocol.root_id, budget=100_000
        ):
            if member.role_id != self._identity_protocol.roles[
                "relationship-member"
            ]:
                continue
            try:
                relationship = verify_authority_relationship(
                    snapshot,
                    self._identity_protocol,
                    self._relationship_broker,
                    member.participant_id,
                    now=now,
                )
            except (RelationshipAuthorityDenied, InvalidCell, KeyError):
                continue
            if (
                relationship.kind_root
                == self._identity_protocol.kinds["audience-binding"]
                and relationship.source_root == registration_root
                and relationship.target_root == self._tenant_root
                and relationship.tenant_root == self._tenant_root
                and relationship.scope_root == self._audience_root
                and registration.manifest_digest_root
                in relationship.evidence_roots
            ):
                matches.append(relationship.root_id)
        if len(matches) != 1:
            raise NativeAuthenticationDenied(
                "native client requires one active signed tenant activation"
            )
        return NativeClientAdmissionEvidence(
            matches[0], self._tenant_root, self._audience_root
        )


def read_native_authorization_transaction(
    snapshot: Snapshot,
    protocol: NativeAuthenticationProtocol,
    transaction_root: str,
) -> NativeAuthorizationTransaction:
    if transaction_root not in _registered(
        snapshot, protocol, "transaction-member"
    ):
        raise NativeAuthenticationDenied(
            "native authorization transaction is not registered"
        )
    members = read_relation(snapshot, transaction_root, budget=256)
    allowed = {
        protocol.role(name) for name in (
            "client", "client-authority", "redirect-uri", "state-digest", "nonce-digest",
            "pkce-challenge", "pkce-method", "device", "created-at",
            "expires-at", "manifest-digest",
        )
    }
    if any(member.role_id not in allowed for member in members):
        raise NativeAuthenticationDenied(
            "native authorization transaction contains undeclared fields"
        )
    transaction = NativeAuthorizationTransaction(
        transaction_root,
        _one(members, protocol.role("client"), "client"),
        _one(
            members,
            protocol.role("client-authority"),
            "client authority",
        ),
        _one(members, protocol.role("redirect-uri"), "redirect URI"),
        _one(members, protocol.role("state-digest"), "state digest"),
        _one(members, protocol.role("nonce-digest"), "nonce digest"),
        _one(members, protocol.role("pkce-challenge"), "PKCE challenge"),
        _one(members, protocol.role("pkce-method"), "PKCE method"),
        _one(members, protocol.role("device"), "device"),
        _one(members, protocol.role("created-at"), "created-at"),
        _one(members, protocol.role("expires-at"), "expires-at"),
        _one(members, protocol.role("manifest-digest"), "manifest digest"),
    )
    document = {
        "client": transaction.client_root,
        "client_authority": transaction.client_authority_root,
        "redirect_uri": _atom(
            snapshot, transaction.redirect_uri_root, "redirect URI"
        ),
        "state_digest": _atom(
            snapshot, transaction.state_digest_root, "state digest"
        ),
        "nonce_digest": _atom(
            snapshot, transaction.nonce_digest_root, "nonce digest"
        ),
        "pkce_challenge": _atom(
            snapshot, transaction.pkce_challenge_root, "PKCE challenge"
        ),
        "pkce_method": _atom(
            snapshot, transaction.pkce_method_root, "PKCE method"
        ),
        "device": transaction.device_root,
        "created_at": _atom(snapshot, transaction.created_at_root, "created-at"),
        "expires_at": _atom(snapshot, transaction.expires_at_root, "expires-at"),
    }
    if (
        transaction.client_root not in snapshot.cells
        or transaction.client_authority_root not in snapshot.cells
    ):
        raise NativeAuthenticationDenied(
            "native transaction client authority is missing"
        )
    expected = _digest(document)
    if not hmac.compare_digest(
        expected,
        _atom(snapshot, transaction.manifest_digest_root, "manifest digest"),
    ):
        raise NativeAuthenticationDenied(
            "native authorization transaction manifest drifted"
        )
    if _atom(snapshot, transaction.pkce_method_root, "PKCE method") != "S256":
        raise NativeAuthenticationDenied("native transaction PKCE method drifted")
    return transaction


def read_native_authorization_completion(
    snapshot: Snapshot,
    protocol: NativeAuthenticationProtocol,
    completion_root: str,
) -> NativeAuthorizationCompletion:
    if completion_root not in _registered(snapshot, protocol, "completion-member"):
        raise NativeAuthenticationDenied(
            "native authorization completion is not registered"
        )
    members = read_relation(snapshot, completion_root, budget=128)
    allowed = {
        protocol.role(name) for name in (
            "transaction", "authorization-code-digest", "response-issuer",
            "completed-at", "manifest-digest",
        )
    }
    if any(member.role_id not in allowed for member in members):
        raise NativeAuthenticationDenied(
            "native authorization completion contains undeclared fields"
        )
    completion = NativeAuthorizationCompletion(
        completion_root,
        _one(members, protocol.role("transaction"), "transaction"),
        _one(
            members,
            protocol.role("authorization-code-digest"),
            "authorization-code digest",
        ),
        _one(members, protocol.role("response-issuer"), "response issuer"),
        _one(members, protocol.role("completed-at"), "completed-at"),
        _one(members, protocol.role("manifest-digest"), "manifest digest"),
    )
    document = {
        "transaction": completion.transaction_root,
        "authorization_code_digest": _atom(
            snapshot,
            completion.authorization_code_digest_root,
            "authorization-code digest",
        ),
        "response_issuer": _atom(
            snapshot, completion.response_issuer_root, "response issuer"
        ),
        "completed_at": _atom(
            snapshot, completion.completed_at_root, "completed-at"
        ),
    }
    expected = _digest(document)
    if not hmac.compare_digest(
        expected,
        _atom(snapshot, completion.manifest_digest_root, "manifest digest"),
    ):
        raise NativeAuthenticationDenied(
            "native authorization completion manifest drifted"
        )
    return completion


def native_authorization_status(
    snapshot: Snapshot,
    protocol: NativeAuthenticationProtocol,
    transaction_root: str,
    *,
    now: float | None = None,
) -> str:
    transaction = read_native_authorization_transaction(
        snapshot, protocol, transaction_root
    )
    completions = tuple(
        root for root in _registered(snapshot, protocol, "completion-member")
        if read_native_authorization_completion(
            snapshot, protocol, root
        ).transaction_root == transaction_root
    )
    if len(completions) > 1:
        raise NativeAuthenticationDenied(
            "native authorization transaction has multiple completions"
        )
    if completions:
        return "completed"
    current = time.time() if now is None else now
    try:
        expires_at = float(
            _atom(snapshot, transaction.expires_at_root, "expires-at")
        )
    except ValueError as exc:
        raise NativeAuthenticationDenied(
            "native authorization expiry is invalid"
        ) from exc
    return "expired" if current >= expires_at else "pending"


class NativeAuthorizationBroker:
    """Own transaction secrets while graph relations own public authority."""

    def __init__(
        self, client_admission_verifier: NativeClientAdmissionVerifier
    ) -> None:
        if not hasattr(client_admission_verifier, "verify"):
            raise TypeError("native client admission verifier is required")
        self._client_admission_verifier = client_admission_verifier
        self._pending: dict[str, _PendingAuthorization] = {}
        self._lock = threading.RLock()

    def start(
        self,
        store: CellStore,
        protocol: NativeAuthenticationProtocol,
        registration_root: str,
        *,
        redirect_port: int,
        device_thumbprint: str,
        lifetime_seconds: float = 300.0,
        now: float | None = None,
    ) -> StartedNativeAuthorization:
        current = time.time() if now is None else now
        if not isinstance(redirect_port, int) or not (1024 <= redirect_port <= 65535):
            raise ValueError("native callback port must be a bound unprivileged port")
        if lifetime_seconds <= 0 or lifetime_seconds > 600:
            raise ValueError("native authorization lifetime must be within ten minutes")
        device_root = device_root_for_thumbprint(device_thumbprint)
        snapshot = store.snapshot()
        if device_root not in snapshot.cells:
            raise NativeAuthenticationDenied(
                "native authorization device is not provisioned"
            )
        registration = read_native_client_registration(
            snapshot, protocol, registration_root
        )
        try:
            admission = self._client_admission_verifier.verify(
                snapshot,
                registration_root=registration_root,
                now=current,
            )
        except Exception as exc:
            raise NativeAuthenticationDenied(
                "native client tenant activation is unavailable"
            ) from exc
        if (
            type(admission) is not NativeClientAdmissionEvidence
            or admission.relationship_root not in snapshot.cells
            or admission.tenant_root not in snapshot.cells
            or admission.audience_root not in snapshot.cells
        ):
            raise NativeAuthenticationDenied(
                "native client tenant activation evidence drifted"
            )
        try:
            metadata_expires = float(_atom(
                snapshot,
                registration.metadata_expires_at_root,
                "metadata expiry",
            ))
        except ValueError as exc:
            raise NativeAuthenticationDenied(
                "native client metadata expiry is invalid"
            ) from exc
        if current >= metadata_expires:
            raise NativeAuthenticationDenied(
                "native client discovery authority expired"
            )
        redirect_uri = "http://127.0.0.1:%s%s" % (
            redirect_port,
            _atom(snapshot, registration.redirect_path_root, "redirect path"),
        )
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(64)
        if not (43 <= len(code_verifier) <= 128):
            raise RuntimeError("generated PKCE verifier has invalid length")
        challenge = _base64url_sha256(code_verifier)
        transaction_root = "native-authorization:" + secrets.token_hex(16)
        expires_at = current + lifetime_seconds
        document = {
            "client": registration_root,
            "client_authority": admission.relationship_root,
            "redirect_uri": redirect_uri,
            "state_digest": _sha256(state),
            "nonce_digest": _sha256(nonce),
            "pkce_challenge": challenge,
            "pkce_method": "S256",
            "device": device_root,
            "created_at": "%.6f" % current,
            "expires_at": "%.6f" % expires_at,
        }
        document["manifest_digest"] = _digest(document)
        fields = tuple((name, str(value)) for name, value in document.items())
        scalar_roots = {
            name: "%s:field:%s" % (transaction_root, name)
            for name, _ in fields
        }
        members = (
            (protocol.role("client"), registration_root),
            (
                protocol.role("client-authority"),
                admission.relationship_root,
            ),
            (protocol.role("redirect-uri"), scalar_roots["redirect_uri"]),
            (protocol.role("state-digest"), scalar_roots["state_digest"]),
            (protocol.role("nonce-digest"), scalar_roots["nonce_digest"]),
            (protocol.role("pkce-challenge"), scalar_roots["pkce_challenge"]),
            (protocol.role("pkce-method"), scalar_roots["pkce_method"]),
            (protocol.role("device"), device_root),
            (protocol.role("created-at"), scalar_roots["created_at"]),
            (protocol.role("expires-at"), scalar_roots["expires_at"]),
            (
                protocol.role("manifest-digest"),
                scalar_roots["manifest_digest"],
            ),
        )
        relation = compose_relation_cells(members, relation_id=transaction_root)
        patch = prepare_append_relation_member(
            snapshot,
            protocol.root_id,
            protocol.role("transaction-member"),
            transaction_root,
            budget=100_000,
        )
        with self._lock:
            if transaction_root in self._pending:
                raise RuntimeError("native authorization identity collision")
            self._pending[transaction_root] = _PendingAuthorization(
                transaction_root,
                registration_root,
                state,
                nonce,
                code_verifier,
                redirect_uri,
                device_thumbprint,
                admission.tenant_root,
                admission.audience_root,
                admission.relationship_root,
                expires_at,
            )
        try:
            store.commit(
                snapshot.revision,
                create=(
                    *(
                        _terminal(scalar_roots[name], value)
                        for name, value in fields
                    ),
                    *relation.cells,
                    *patch.create,
                ),
                replace=patch.replace,
            )
        except Exception:
            with self._lock:
                self._pending.pop(transaction_root, None)
            raise
        authorization_endpoint = _atom(
            snapshot,
            registration.authorization_endpoint_root,
            "authorization endpoint",
        )
        query = {
            "response_type": "code",
            "client_id": _atom(
                snapshot, registration.client_id_root, "client ID"
            ),
            "redirect_uri": redirect_uri,
            "scope": " ".join(
                _atom(snapshot, root, "scope")
                for root in registration.scope_roots
            ),
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        separator = "&" if urlsplit(authorization_endpoint).query else "?"
        return StartedNativeAuthorization(
            transaction_root,
            authorization_endpoint + separator + urlencode(query),
            expires_at,
        )

    def complete(
        self,
        store: CellStore,
        protocol: NativeAuthenticationProtocol,
        transaction_root: str,
        *,
        state: str,
        response_issuer: str,
        authorization_code: str,
        now: float | None = None,
    ) -> NativeAuthorizationCode:
        current = time.time() if now is None else now
        if (
            not isinstance(authorization_code, str)
            or not (1 <= len(authorization_code) <= 4096)
            or any(ord(character) < 0x20 for character in authorization_code)
        ):
            raise NativeAuthenticationDenied("authorization code is invalid")
        with self._lock:
            pending = self._pending.get(transaction_root)
            if pending is None or pending.used or pending.completing:
                raise NativeAuthenticationDenied(
                    "native authorization transaction has no live secret custody"
                )
            if current >= pending.expires_at:
                pending.used = True
                self._pending.pop(transaction_root, None)
                raise NativeAuthenticationDenied(
                    "native authorization transaction expired"
                )
            if not isinstance(state, str) or not hmac.compare_digest(
                state, pending.state
            ):
                raise NativeAuthenticationDenied(
                    "native authorization state mismatched"
                )
            snapshot = store.snapshot()
            transaction = read_native_authorization_transaction(
                snapshot, protocol, transaction_root
            )
            try:
                admission = self._client_admission_verifier.verify(
                    snapshot,
                    registration_root=transaction.client_root,
                    now=current,
                )
            except Exception as exc:
                raise NativeAuthenticationDenied(
                    "native client tenant activation was revoked"
                ) from exc
            if (
                type(admission) is not NativeClientAdmissionEvidence
                or admission.relationship_root
                != transaction.client_authority_root
                or admission.relationship_root != pending.client_authority_root
                or admission.tenant_root != pending.tenant_root
                or admission.audience_root != pending.audience_root
            ):
                raise NativeAuthenticationDenied(
                    "native client tenant activation changed"
                )
            if native_authorization_status(
                snapshot, protocol, transaction_root, now=current
            ) != "pending":
                raise NativeAuthenticationDenied(
                    "native authorization transaction is not pending"
                )
            registration = read_native_client_registration(
                snapshot, protocol, transaction.client_root
            )
            issuer = _atom(snapshot, registration.issuer_root, "issuer")
            if not isinstance(response_issuer, str) or not hmac.compare_digest(
                response_issuer, issuer
            ):
                raise NativeAuthenticationDenied(
                    "native authorization response issuer mismatched"
                )
            if not hmac.compare_digest(
                _sha256(state),
                _atom(snapshot, transaction.state_digest_root, "state digest"),
            ):
                raise NativeAuthenticationDenied(
                    "native authorization state evidence drifted"
                )
            pending.completing = True

        try:
            completion_root = (
                "native-authorization-completion:" + secrets.token_hex(16)
            )
            document = {
                "transaction": transaction_root,
                "authorization_code_digest": _sha256(authorization_code),
                "response_issuer": response_issuer,
                "completed_at": "%.6f" % current,
            }
            document["manifest_digest"] = _digest(document)
            fields = tuple(
                (name, str(value)) for name, value in document.items()
            )
            scalar_roots = {
                name: "%s:field:%s" % (completion_root, name)
                for name, _ in fields
            }
            relation = compose_relation_cells((
                (protocol.role("transaction"), transaction_root),
                (
                    protocol.role("authorization-code-digest"),
                    scalar_roots["authorization_code_digest"],
                ),
                (
                    protocol.role("response-issuer"),
                    scalar_roots["response_issuer"],
                ),
                (protocol.role("completed-at"), scalar_roots["completed_at"]),
                (
                    protocol.role("manifest-digest"),
                    scalar_roots["manifest_digest"],
                ),
            ), relation_id=completion_root)
            patch = prepare_append_relation_member(
                snapshot,
                protocol.root_id,
                protocol.role("completion-member"),
                completion_root,
                budget=100_000,
            )
            store.commit(
                snapshot.revision,
                create=(
                    *(
                        _terminal(scalar_roots[name], value)
                        for name, value in fields
                    ),
                    *relation.cells,
                    *patch.create,
                ),
                replace=patch.replace,
            )
        except Exception:
            with self._lock:
                if self._pending.get(transaction_root) is pending:
                    pending.completing = False
            raise
        with self._lock:
            if self._pending.get(transaction_root) is not pending:
                raise RuntimeError(
                    "native authorization secret custody changed during commit"
                )
            pending.used = True
            pending.completing = False
            self._pending.pop(transaction_root, None)
        read_native_authorization_completion(
            store.snapshot(), protocol, completion_root
        )
        return NativeAuthorizationCode(
            _AUTHORIZATION_CODE_KEY,
            transaction_root=transaction_root,
            completion_root=completion_root,
            registration_root=pending.registration_root,
            issuer=issuer,
            client_id=_atom(snapshot, registration.client_id_root, "client ID"),
            token_endpoint=_atom(
                snapshot, registration.token_endpoint_root, "token endpoint"
            ),
            redirect_uri=pending.redirect_uri,
            authorization_code=authorization_code,
            code_verifier=pending.code_verifier,
            nonce=pending.nonce,
            device_thumbprint=pending.device_thumbprint,
            tenant_root=pending.tenant_root,
            audience_root=pending.audience_root,
            client_authority_root=pending.client_authority_root,
        )


def exchange_native_authorization_code(
    authorization: NativeAuthorizationCode,
    *,
    client: httpx.Client | None = None,
) -> NativeIdentityAssertion:
    """Exchange one callback code without retaining provider token secrets."""
    if type(authorization) is not NativeAuthorizationCode:
        raise NativeAuthenticationDenied(
            "token exchange requires a native authorization capability"
        )
    authorization.consume()
    owned = client is None
    transport = client or httpx.Client(
        timeout=httpx.Timeout(10.0, connect=5.0),
        follow_redirects=False,
    )
    try:
        response = transport.post(
            authorization.token_endpoint,
            data={
                "grant_type": "authorization_code",
                "code": authorization.authorization_code,
                "redirect_uri": authorization.redirect_uri,
                "client_id": authorization.client_id,
                "code_verifier": authorization.code_verifier,
            },
            headers={
                "Accept": "application/json",
                "Cache-Control": "no-store",
            },
            follow_redirects=False,
        )
        if response.status_code != 200:
            raise NativeAuthenticationDenied(
                "native token endpoint did not return 200"
            )
        content_type = response.headers.get("content-type", "").split(
            ";", 1
        )[0].strip().lower()
        if content_type != "application/json":
            raise NativeAuthenticationDenied(
                "native token response content type is invalid"
            )
        content = response.content
        if len(content) > MAX_TOKEN_RESPONSE_BYTES:
            raise NativeAuthenticationDenied(
                "native token response is too large"
            )
        try:
            payload = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise NativeAuthenticationDenied(
                "native token response JSON is invalid"
            ) from exc
        if not isinstance(payload, dict):
            raise NativeAuthenticationDenied(
                "native token response must be an object"
            )
        id_token = payload.get("id_token")
        if (
            not isinstance(id_token, str)
            or not (1 <= len(id_token.encode("ascii", "ignore")) <= MAX_ID_TOKEN_BYTES)
            or not id_token.isascii()
        ):
            raise NativeAuthenticationDenied(
                "native token response has no valid ID token"
            )
        return NativeIdentityAssertion(
            _IDENTITY_ASSERTION_KEY,
            transaction_root=authorization.transaction_root,
            completion_root=authorization.completion_root,
            registration_root=authorization.registration_root,
            id_token=id_token.encode("ascii"),
            expected_issuer=authorization.issuer,
            expected_audience=authorization.client_id,
            expected_nonce=authorization.nonce,
            device_thumbprint=authorization.device_thumbprint,
            tenant_root=authorization.tenant_root,
            audience_root=authorization.audience_root,
            client_authority_root=authorization.client_authority_root,
        )
    except httpx.HTTPError as exc:
        raise NativeAuthenticationDenied(
            "native token endpoint transport failed"
        ) from exc
    finally:
        if owned:
            transport.close()


def issue_native_cloud_session(
    store: CellStore,
    assertion: NativeIdentityAssertion,
    *,
    federated_identity_broker: FederatedIdentityBroker,
    cloud_session_broker: CloudSessionBroker,
    client_admission_verifier: NativeClientAdmissionVerifier,
    allowed_action_roots: tuple[str, ...],
    lifetime_seconds: float = 900.0,
    now: float | None = None,
) -> IssuedCloudSession:
    """Consume native identity evidence into one device-bound cloud session."""
    if type(assertion) is not NativeIdentityAssertion:
        raise NativeAuthenticationDenied(
            "cloud issuance requires a native identity assertion capability"
        )
    assertion.consume()
    current = time.time() if now is None else now
    try:
        admission = client_admission_verifier.verify(
            store.snapshot(),
            registration_root=assertion.registration_root,
            now=current,
        )
    except Exception as exc:
        raise NativeAuthenticationDenied(
            "native client tenant activation was revoked before session issuance"
        ) from exc
    if (
        type(admission) is not NativeClientAdmissionEvidence
        or admission.relationship_root != assertion.client_authority_root
        or admission.tenant_root != assertion.tenant_root
        or admission.audience_root != assertion.audience_root
    ):
        raise NativeAuthenticationDenied(
            "native client tenant activation changed before session issuance"
        )
    authentication = federated_identity_broker.authenticate(
        store,
        assertion.id_token,
        expected_issuer=assertion.expected_issuer,
        expected_audience=assertion.expected_audience,
        expected_nonce=assertion.expected_nonce,
        tenant_root=admission.tenant_root,
        audience_root=admission.audience_root,
        now=now,
    )
    return cloud_session_broker.issue(
        store,
        authentication,
        proof_key_thumbprint=assertion.device_thumbprint,
        allowed_action_roots=allowed_action_roots,
        lifetime_seconds=lifetime_seconds,
        now=now,
    )


__all__ = [
    "MAX_ID_TOKEN_BYTES",
    "MAX_TOKEN_RESPONSE_BYTES",
    "NativeAuthenticationDenied",
    "NativeAuthenticationProtocol",
    "NativeAuthorizationBroker",
    "NativeAuthorizationCode",
    "NativeAuthorizationCompletion",
    "NativeAuthorizationTransaction",
    "NativeClientAdmissionEvidence",
    "NativeClientAdmissionVerifier",
    "NativeClientRegistration",
    "NativeIdentityAssertion",
    "SignedNativeClientAdmissionVerifier",
    "StartedNativeAuthorization",
    "activate_native_client_registration",
    "bootstrap_native_authentication_protocol",
    "build_native_client_registration",
    "exchange_native_authorization_code",
    "issue_native_cloud_session",
    "native_authorization_status",
    "project_native_authentication_protocol",
    "read_native_authorization_completion",
    "read_native_authorization_transaction",
    "read_native_client_registration",
]
