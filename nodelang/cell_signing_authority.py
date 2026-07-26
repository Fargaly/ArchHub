"""Graph-held signing authority descriptors and signature envelopes.

The persisted protocol uses only universal Cells and the reusable relation
composition. Private keys remain in non-exporting host capabilities. The local
Ed25519 provider is a KMS-shaped contract implementation for courts; it is not
cloud or HSM evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import base64
import binascii
import hashlib
import hmac
import json
import re
import threading
from types import MappingProxyType
from typing import Mapping, Protocol
import uuid

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .cell_protocols import CellBatch, compose_relation_cells, read_relation
from .cell_secret_keys import SigningKeyProvider
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


DESCRIPTOR_PROTOCOL = "https://archhub.local/signing-key-descriptor/v2"
ENVELOPE_PROTOCOL = "https://archhub.local/signature-envelope/v2"
LOCAL_PROVIDER_PROTOCOL = "https://archhub.local/provider/ed25519/v1"
LEGACY_PROVIDER_PROTOCOL = "https://archhub.local/provider/hmac-sha256/v1"

DESCRIPTOR_FIELDS = (
    "descriptor-protocol",
    "authority-id",
    "purpose",
    "provider-protocol",
    "provider-id",
    "resource-version",
    "key-usage",
    "signature-algorithm",
    "payload-mode",
    "digest-algorithm",
    "signature-encoding",
    "public-key-format",
    "public-key-digest",
    "protection-level",
    "attestation-digest",
    "state",
    "valid-from",
    "valid-until",
    "predecessor-descriptor",
    "authorization-evidence",
    "release-evidence",
    "descriptor-digest",
)

ENVELOPE_FIELDS = (
    "envelope-protocol",
    "key-descriptor",
    "key-descriptor-digest",
    "statement-protocol",
    "context",
    "payload-mode",
    "digest-algorithm",
    "payload-digest",
    "signature-algorithm",
    "signature-encoding",
    "provider-resource",
    "provider-receipt-digest",
    "provider-integrity-evidence",
    "issued-at",
    "request-id",
    "authorization-evidence",
    "signature",
    "envelope-digest",
)

ROLE_NAMES = (
    "vocabulary-member",
    *("descriptor-" + name for name in DESCRIPTOR_FIELDS),
    *("envelope-" + name for name in ENVELOPE_FIELDS),
)
STATE_NAMES = ("active", "verify-only", "disabled", "revoked", "destroyed")

_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,511}\Z")


class SigningAuthorityDenied(PermissionError):
    """A signing descriptor, envelope, provider, or lifecycle gate failed."""


@dataclass(frozen=True, slots=True)
class SigningAuthorityProtocol:
    root_id: str
    roles: Mapping[str, str]
    states: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown signing authority role %r" % name) from exc


@dataclass(frozen=True, slots=True)
class ProviderKeyMetadata:
    provider_protocol: str
    provider_id: str
    resource_version: str
    key_usage: str
    signature_algorithm: str
    payload_mode: str
    digest_algorithm: str
    signature_encoding: str
    public_key_format: str
    public_key: bytes
    protection_level: str
    attestation_digest: str
    state: str

    def __post_init__(self) -> None:
        for label, value in (
            ("provider protocol", self.provider_protocol),
            ("provider id", self.provider_id),
            ("resource version", self.resource_version),
            ("key usage", self.key_usage),
            ("signature algorithm", self.signature_algorithm),
            ("payload mode", self.payload_mode),
            ("digest algorithm", self.digest_algorithm),
            ("signature encoding", self.signature_encoding),
            ("public key format", self.public_key_format),
            ("protection level", self.protection_level),
        ):
            _checked_token(value, label)
        if not self.public_key:
            raise ValueError("provider public key cannot be empty")
        if self.attestation_digest != "none" and not _SHA256.fullmatch(
            self.attestation_digest
        ):
            raise ValueError("provider attestation digest is invalid")
        if self.state not in STATE_NAMES:
            raise ValueError("provider key state is invalid")

    @property
    def public_key_digest(self) -> str:
        return "sha256:" + hashlib.sha256(self.public_key).hexdigest()


@dataclass(frozen=True, slots=True)
class ProviderSignRequest:
    request_id: str
    resource_version: str
    signature_algorithm: str
    payload_mode: str
    digest_algorithm: str
    payload: bytes


@dataclass(frozen=True, slots=True)
class ProviderSignResponse:
    request_id: str
    provider_protocol: str
    provider_id: str
    resource_version: str
    signature_algorithm: str
    signature_encoding: str
    protection_level: str
    integrity_evidence: str
    signature: bytes


class SigningAuthorityProvider(Protocol):
    """Non-exporting host capability for one allowlisted signing provider."""

    def describe(self, resource_version: str) -> ProviderKeyMetadata:
        ...

    def sign(self, request: ProviderSignRequest) -> ProviderSignResponse:
        ...

    def verify(self, resource_version: str, payload: bytes, signature: bytes) -> bool:
        ...


@dataclass(frozen=True, slots=True)
class SigningKeyDescriptorProjection:
    root_id: str
    roots: Mapping[str, str]
    values: Mapping[str, str]

    @property
    def digest(self) -> str:
        return self.values["descriptor-digest"]


@dataclass(frozen=True, slots=True)
class SignatureEnvelopeProjection:
    root_id: str
    roots: Mapping[str, str]
    values: Mapping[str, str]

    @property
    def signature(self) -> bytes:
        try:
            return base64.b64decode(self.values["signature"], validate=True)
        except (ValueError, binascii.Error) as exc:
            raise InvalidCell("signature envelope encoding is invalid") from exc


def _checked_token(value: str, label: str) -> str:
    text = str(value)
    if not _TOKEN.fullmatch(text):
        raise ValueError("%s is invalid" % label)
    return text


def _checked_ascii(value: str, label: str, *, maximum: int = 4096) -> str:
    text = str(value)
    try:
        encoded = text.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("%s must be ASCII" % label) from exc
    if not encoded or len(encoded) > maximum or any(byte < 0x20 for byte in encoded):
        raise ValueError("%s is invalid" % label)
    return text


def _checked_time(value: str, label: str, *, allow_none: bool = False) -> str:
    text = str(value)
    if allow_none and text == "none":
        return text
    if not text.endswith("Z"):
        raise ValueError("%s must be an RFC 3339 UTC timestamp" % label)
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("%s must be an RFC 3339 UTC timestamp" % label) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("%s must include UTC" % label)
    return text


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _terminal(root_id: str, value: str) -> Cell:
    try:
        atom = str(value).encode("ascii")
    except UnicodeEncodeError as exc:
        raise InvalidCell("signing authority values must be ASCII") from exc
    if not atom or len(atom) > 65_536:
        raise InvalidCell("signing authority value is empty or too large")
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, atom)


def _canonical(fields: Mapping[str, str], *, domain: str) -> bytes:
    return (
        domain.encode("ascii")
        + b"\x00"
        + json.dumps(
            dict(fields), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")
    )


def _digest(fields: Mapping[str, str], *, domain: str) -> str:
    return "sha256:" + hashlib.sha256(_canonical(fields, domain=domain)).hexdigest()


def _one(members, role_id: str, label: str) -> str:
    values = tuple(
        member.participant_id for member in members if member.role_id == role_id
    )
    if len(values) != 1:
        raise InvalidCell("signing authority requires exactly one %s" % label)
    return values[0]


def _read_fields(
    snapshot: Snapshot,
    protocol: SigningAuthorityProtocol,
    root_id: str,
    *,
    names: tuple[str, ...],
    prefix: str,
) -> tuple[Mapping[str, str], Mapping[str, str]]:
    members = read_relation(snapshot, root_id, budget=512)
    allowed = {protocol.role(prefix + name) for name in names}
    if any(member.role_id not in allowed for member in members):
        raise InvalidCell("signing authority relation contains an undeclared field")
    roots = {
        name: _one(members, protocol.role(prefix + name), name) for name in names
    }
    values: dict[str, str] = {}
    for name, field_root in roots.items():
        cell = snapshot.cells.get(field_root)
        if cell is None:
            raise InvalidCell("signing authority field is missing")
        if cell.link0 != NULL_CELL_ID or cell.link1 != NULL_CELL_ID:
            raise InvalidCell("signing authority fields must be terminal")
        try:
            values[name] = cell.atom.decode("ascii")
        except UnicodeDecodeError as exc:
            raise InvalidCell("signing authority fields must be ASCII") from exc
        if not values[name]:
            raise InvalidCell("signing authority fields cannot be empty")
    return MappingProxyType(roots), MappingProxyType(values)


def bootstrap_signing_authority_protocol(
    store: CellStore, *, prefix: str = "signing-authority-protocol"
) -> SigningAuthorityProtocol:
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    states = {name: "%s:state:%s" % (prefix, name) for name in STATE_NAMES}
    batch = CellBatch(store)
    for name, root in roles.items():
        batch.add(_terminal(root, name))
    for name, root in states.items():
        batch.add(_terminal(root, name))
    root_id = prefix + ":root"
    batch.relation(
        (
            (roles["vocabulary-member"], root)
            for root in (*roles.values(), *states.values())
        ),
        relation_id=root_id,
    )
    batch.commit()
    return SigningAuthorityProtocol(
        root_id, MappingProxyType(roles), MappingProxyType(states)
    )


def project_signing_authority_protocol(
    snapshot: Snapshot, *, prefix: str = "signing-authority-protocol"
) -> SigningAuthorityProtocol:
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    states = {name: "%s:state:%s" % (prefix, name) for name in STATE_NAMES}
    root_id = prefix + ":root"
    required = (root_id, *roles.values(), *states.values())
    if any(root not in snapshot.cells for root in required):
        raise InvalidCell("signing authority protocol is incomplete")
    members = read_relation(snapshot, root_id, budget=512)
    declared = tuple(
        member.participant_id
        for member in members
        if member.role_id == roles["vocabulary-member"]
    )
    expected = set((*roles.values(), *states.values()))
    if len(declared) != len(set(declared)) or set(declared) != expected:
        raise InvalidCell("signing authority vocabulary drifted")
    return SigningAuthorityProtocol(
        root_id, MappingProxyType(roles), MappingProxyType(states)
    )


def _descriptor_values(
    metadata: ProviderKeyMetadata,
    *,
    authority_id: str,
    purpose: str,
    valid_from: str,
    valid_until: str,
    predecessor_descriptor: str,
    authorization_evidence: str,
    release_evidence: str,
) -> dict[str, str]:
    values = {
        "descriptor-protocol": DESCRIPTOR_PROTOCOL,
        "authority-id": _checked_ascii(authority_id, "authority id", maximum=512),
        "purpose": _checked_ascii(purpose, "purpose", maximum=512),
        "provider-protocol": metadata.provider_protocol,
        "provider-id": metadata.provider_id,
        "resource-version": metadata.resource_version,
        "key-usage": metadata.key_usage,
        "signature-algorithm": metadata.signature_algorithm,
        "payload-mode": metadata.payload_mode,
        "digest-algorithm": metadata.digest_algorithm,
        "signature-encoding": metadata.signature_encoding,
        "public-key-format": metadata.public_key_format,
        "public-key-digest": metadata.public_key_digest,
        "protection-level": metadata.protection_level,
        "attestation-digest": metadata.attestation_digest,
        "state": metadata.state,
        "valid-from": _checked_time(valid_from, "valid from"),
        "valid-until": _checked_time(valid_until, "valid until", allow_none=True),
        "predecessor-descriptor": _checked_ascii(
            predecessor_descriptor, "predecessor descriptor", maximum=512
        ),
        "authorization-evidence": _checked_ascii(
            authorization_evidence, "authorization evidence", maximum=1024
        ),
        "release-evidence": _checked_ascii(
            release_evidence, "release evidence", maximum=1024
        ),
    }
    values["descriptor-digest"] = _digest(
        values, domain="ArchHub/signing-key-descriptor/v2"
    )
    return values


def build_signing_key_descriptor(
    store: CellStore,
    protocol: SigningAuthorityProtocol,
    provider: SigningAuthorityProvider,
    *,
    descriptor_id: str,
    resource_version: str,
    authority_id: str,
    purpose: str,
    valid_from: str | None = None,
    valid_until: str = "none",
    predecessor_descriptor: str = "none",
    authorization_evidence: str,
    release_evidence: str,
) -> str:
    if descriptor_id in store.snapshot().cells:
        raise InvalidCell("signing key descriptor already exists")
    metadata = provider.describe(resource_version)
    values = _descriptor_values(
        metadata,
        authority_id=authority_id,
        purpose=purpose,
        valid_from=valid_from or _now(),
        valid_until=valid_until,
        predecessor_descriptor=predecessor_descriptor,
        authorization_evidence=authorization_evidence,
        release_evidence=release_evidence,
    )
    scalar_cells = tuple(
        _terminal(descriptor_id + ":" + name, value)
        for name, value in values.items()
    )
    relation = compose_relation_cells(
        (
            (protocol.role("descriptor-" + name), descriptor_id + ":" + name)
            for name in DESCRIPTOR_FIELDS
        ),
        relation_id=descriptor_id,
    )
    store.commit(store.revision, create=(*scalar_cells, *relation.cells))
    return descriptor_id


def read_signing_key_descriptor(
    snapshot: Snapshot,
    protocol: SigningAuthorityProtocol,
    descriptor_root: str,
) -> SigningKeyDescriptorProjection:
    roots, values = _read_fields(
        snapshot,
        protocol,
        descriptor_root,
        names=DESCRIPTOR_FIELDS,
        prefix="descriptor-",
    )
    if values["descriptor-protocol"] != DESCRIPTOR_PROTOCOL:
        raise InvalidCell("signing key descriptor protocol is invalid")
    if values["state"] not in STATE_NAMES:
        raise InvalidCell("signing key descriptor state is invalid")
    for name in (
        "provider-protocol",
        "provider-id",
        "resource-version",
        "key-usage",
        "signature-algorithm",
        "payload-mode",
        "digest-algorithm",
        "signature-encoding",
        "public-key-format",
        "protection-level",
    ):
        try:
            _checked_token(values[name], name)
        except ValueError as exc:
            raise InvalidCell(str(exc)) from exc
    if not _SHA256.fullmatch(values["public-key-digest"]):
        raise InvalidCell("signing key public-key digest is invalid")
    if values["attestation-digest"] != "none" and not _SHA256.fullmatch(
        values["attestation-digest"]
    ):
        raise InvalidCell("signing key attestation digest is invalid")
    try:
        _checked_time(values["valid-from"], "valid from")
        _checked_time(values["valid-until"], "valid until", allow_none=True)
    except ValueError as exc:
        raise InvalidCell(str(exc)) from exc
    unsigned = dict(values)
    committed = unsigned.pop("descriptor-digest")
    actual = _digest(unsigned, domain="ArchHub/signing-key-descriptor/v2")
    if not hmac.compare_digest(committed, actual):
        raise InvalidCell("signing key descriptor digest mismatched")
    return SigningKeyDescriptorProjection(descriptor_root, roots, values)


def _is_current(values: Mapping[str, str], *, at: datetime | None = None) -> bool:
    instant = at or datetime.now(timezone.utc)
    starts = datetime.fromisoformat(values["valid-from"][:-1] + "+00:00")
    if instant < starts:
        return False
    if values["valid-until"] == "none":
        return True
    ends = datetime.fromisoformat(values["valid-until"][:-1] + "+00:00")
    return instant <= ends


def verify_signing_key_descriptor(
    snapshot: Snapshot,
    protocol: SigningAuthorityProtocol,
    provider: SigningAuthorityProvider,
    descriptor_root: str,
    *,
    require_signing: bool = False,
    require_current_authority: bool = True,
) -> SigningKeyDescriptorProjection:
    descriptor = read_signing_key_descriptor(snapshot, protocol, descriptor_root)
    values = descriptor.values
    metadata = provider.describe(values["resource-version"])
    expected = {
        "provider-protocol": metadata.provider_protocol,
        "provider-id": metadata.provider_id,
        "resource-version": metadata.resource_version,
        "key-usage": metadata.key_usage,
        "signature-algorithm": metadata.signature_algorithm,
        "payload-mode": metadata.payload_mode,
        "digest-algorithm": metadata.digest_algorithm,
        "signature-encoding": metadata.signature_encoding,
        "public-key-format": metadata.public_key_format,
        "public-key-digest": metadata.public_key_digest,
        "protection-level": metadata.protection_level,
        "attestation-digest": metadata.attestation_digest,
    }
    for name, expected_value in expected.items():
        if not hmac.compare_digest(values[name], expected_value):
            raise SigningAuthorityDenied("signing key %s mismatched" % name)
    if require_current_authority:
        if values["state"] not in ("active", "verify-only"):
            raise SigningAuthorityDenied("signing key descriptor is not usable")
        if metadata.state not in ("active", "verify-only"):
            raise SigningAuthorityDenied("provider key is not usable")
        if not _is_current(values):
            raise SigningAuthorityDenied("signing key descriptor is outside validity")
    if require_signing and (
        values["state"] != "active" or metadata.state != "active"
    ):
        raise SigningAuthorityDenied("signing key is not active for new signatures")
    return descriptor


def _statement_fields(
    descriptor: SigningKeyDescriptorProjection,
    *,
    statement_protocol: str,
    context: str,
    payload: bytes,
    issued_at: str,
    request_id: str,
    authorization_evidence: str,
) -> dict[str, str]:
    if not payload:
        raise SigningAuthorityDenied("signature payload cannot be empty")
    values = {
        "envelope-protocol": ENVELOPE_PROTOCOL,
        "key-descriptor": descriptor.root_id,
        "key-descriptor-digest": descriptor.digest,
        "statement-protocol": _checked_ascii(
            statement_protocol, "statement protocol", maximum=512
        ),
        "context": _checked_ascii(context, "signature context", maximum=1024),
        "payload-mode": descriptor.values["payload-mode"],
        "digest-algorithm": descriptor.values["digest-algorithm"],
        "payload-digest": "sha256:" + hashlib.sha256(payload).hexdigest(),
        "signature-algorithm": descriptor.values["signature-algorithm"],
        "signature-encoding": descriptor.values["signature-encoding"],
        "provider-resource": descriptor.values["resource-version"],
        "issued-at": _checked_time(issued_at, "issued at"),
        "request-id": _checked_token(request_id, "request id"),
        "authorization-evidence": _checked_ascii(
            authorization_evidence, "authorization evidence", maximum=1024
        ),
    }
    return values


def _signing_input(fields: Mapping[str, str], payload: bytes) -> bytes:
    framed = bytearray(_canonical(fields, domain="ArchHub/signature-envelope/v2"))
    framed.extend(len(payload).to_bytes(8, "big"))
    framed.extend(payload)
    return bytes(framed)


def _receipt_digest(response: ProviderSignResponse) -> str:
    fields = {
        "request-id": response.request_id,
        "provider-protocol": response.provider_protocol,
        "provider-id": response.provider_id,
        "resource-version": response.resource_version,
        "signature-algorithm": response.signature_algorithm,
        "signature-encoding": response.signature_encoding,
        "protection-level": response.protection_level,
        "integrity-evidence": response.integrity_evidence,
        "signature": base64.b64encode(response.signature).decode("ascii"),
    }
    return _digest(fields, domain="ArchHub/provider-sign-receipt/v2")


def sign_statement(
    store: CellStore,
    protocol: SigningAuthorityProtocol,
    provider: SigningAuthorityProvider,
    descriptor_root: str,
    *,
    envelope_id: str,
    statement_protocol: str,
    context: str,
    payload: bytes,
    authorization_evidence: str,
    issued_at: str | None = None,
    request_id: str | None = None,
) -> str:
    snapshot = store.snapshot()
    if envelope_id in snapshot.cells:
        raise InvalidCell("signature envelope already exists")
    descriptor = verify_signing_key_descriptor(
        snapshot,
        protocol,
        provider,
        descriptor_root,
        require_signing=True,
    )
    request_identity = request_id or str(uuid.uuid4())
    fields = _statement_fields(
        descriptor,
        statement_protocol=statement_protocol,
        context=context,
        payload=bytes(payload),
        issued_at=issued_at or _now(),
        request_id=request_identity,
        authorization_evidence=authorization_evidence,
    )
    response = provider.sign(ProviderSignRequest(
        request_identity,
        descriptor.values["resource-version"],
        descriptor.values["signature-algorithm"],
        descriptor.values["payload-mode"],
        descriptor.values["digest-algorithm"],
        _signing_input(fields, bytes(payload)),
    ))
    expected_response = {
        "request_id": request_identity,
        "provider_protocol": descriptor.values["provider-protocol"],
        "provider_id": descriptor.values["provider-id"],
        "resource_version": descriptor.values["resource-version"],
        "signature_algorithm": descriptor.values["signature-algorithm"],
        "signature_encoding": descriptor.values["signature-encoding"],
        "protection_level": descriptor.values["protection-level"],
    }
    for name, expected in expected_response.items():
        if not hmac.compare_digest(str(getattr(response, name)), expected):
            raise SigningAuthorityDenied("provider signing response mismatched")
    if not response.integrity_evidence or not response.signature:
        raise SigningAuthorityDenied("provider signing response is incomplete")
    fields["provider-receipt-digest"] = _receipt_digest(response)
    fields["provider-integrity-evidence"] = _checked_ascii(
        response.integrity_evidence, "provider integrity evidence", maximum=1024
    )
    fields["signature"] = base64.b64encode(response.signature).decode("ascii")
    fields["envelope-digest"] = _digest(
        fields, domain="ArchHub/signature-envelope-record/v2"
    )
    scalar_cells = tuple(
        _terminal(envelope_id + ":" + name, value) for name, value in fields.items()
    )
    relation = compose_relation_cells(
        (
            (protocol.role("envelope-" + name), envelope_id + ":" + name)
            for name in ENVELOPE_FIELDS
        ),
        relation_id=envelope_id,
    )
    store.commit(store.revision, create=(*scalar_cells, *relation.cells))
    return envelope_id


def read_signature_envelope(
    snapshot: Snapshot,
    protocol: SigningAuthorityProtocol,
    envelope_root: str,
) -> SignatureEnvelopeProjection:
    roots, values = _read_fields(
        snapshot,
        protocol,
        envelope_root,
        names=ENVELOPE_FIELDS,
        prefix="envelope-",
    )
    if values["envelope-protocol"] != ENVELOPE_PROTOCOL:
        raise InvalidCell("signature envelope protocol is invalid")
    for name in (
        "key-descriptor-digest",
        "payload-digest",
        "provider-receipt-digest",
        "envelope-digest",
    ):
        if not _SHA256.fullmatch(values[name]):
            raise InvalidCell("signature envelope %s is invalid" % name)
    if values["signature-encoding"] != "base64":
        raise InvalidCell("signature envelope encoding is unsupported")
    try:
        signature = base64.b64decode(values["signature"], validate=True)
        _checked_time(values["issued-at"], "issued at")
        _checked_token(values["request-id"], "request id")
    except (ValueError, binascii.Error) as exc:
        raise InvalidCell(str(exc)) from exc
    if not signature:
        raise InvalidCell("signature envelope signature is empty")
    unsigned = dict(values)
    committed = unsigned.pop("envelope-digest")
    actual = _digest(unsigned, domain="ArchHub/signature-envelope-record/v2")
    if not hmac.compare_digest(committed, actual):
        raise InvalidCell("signature envelope digest mismatched")
    return SignatureEnvelopeProjection(envelope_root, roots, values)


def verify_signature_envelope(
    snapshot: Snapshot,
    protocol: SigningAuthorityProtocol,
    provider: SigningAuthorityProvider,
    envelope_root: str,
    *,
    payload: bytes,
    expected_statement_protocol: str | None = None,
    expected_context: str | None = None,
    require_current_authority: bool = True,
) -> SignatureEnvelopeProjection:
    envelope = read_signature_envelope(snapshot, protocol, envelope_root)
    descriptor = verify_signing_key_descriptor(
        snapshot,
        protocol,
        provider,
        envelope.values["key-descriptor"],
        require_current_authority=require_current_authority,
    )
    if not hmac.compare_digest(
        envelope.values["key-descriptor-digest"], descriptor.digest
    ):
        raise SigningAuthorityDenied("signature descriptor digest mismatched")
    if expected_statement_protocol is not None and not hmac.compare_digest(
        envelope.values["statement-protocol"], expected_statement_protocol
    ):
        raise SigningAuthorityDenied("signature statement protocol mismatched")
    if expected_context is not None and not hmac.compare_digest(
        envelope.values["context"], expected_context
    ):
        raise SigningAuthorityDenied("signature context mismatched")
    actual_payload = "sha256:" + hashlib.sha256(bytes(payload)).hexdigest()
    if not hmac.compare_digest(envelope.values["payload-digest"], actual_payload):
        raise SigningAuthorityDenied("signature payload digest mismatched")
    compared = {
        "payload-mode": descriptor.values["payload-mode"],
        "digest-algorithm": descriptor.values["digest-algorithm"],
        "signature-algorithm": descriptor.values["signature-algorithm"],
        "signature-encoding": descriptor.values["signature-encoding"],
        "provider-resource": descriptor.values["resource-version"],
    }
    for name, expected in compared.items():
        if not hmac.compare_digest(envelope.values[name], expected):
            raise SigningAuthorityDenied("signature envelope %s mismatched" % name)
    statement_fields = {
        name: envelope.values[name]
        for name in (
            "envelope-protocol",
            "key-descriptor",
            "key-descriptor-digest",
            "statement-protocol",
            "context",
            "payload-mode",
            "digest-algorithm",
            "payload-digest",
            "signature-algorithm",
            "signature-encoding",
            "provider-resource",
            "issued-at",
            "request-id",
            "authorization-evidence",
        )
    }
    if not provider.verify(
        descriptor.values["resource-version"],
        _signing_input(statement_fields, bytes(payload)),
        envelope.signature,
    ):
        raise SigningAuthorityDenied("signature envelope signature is invalid")
    response = ProviderSignResponse(
        envelope.values["request-id"],
        descriptor.values["provider-protocol"],
        descriptor.values["provider-id"],
        descriptor.values["resource-version"],
        descriptor.values["signature-algorithm"],
        descriptor.values["signature-encoding"],
        descriptor.values["protection-level"],
        envelope.values["provider-integrity-evidence"],
        envelope.signature,
    )
    if not hmac.compare_digest(
        envelope.values["provider-receipt-digest"], _receipt_digest(response)
    ):
        raise SigningAuthorityDenied("provider receipt digest mismatched")
    return envelope


class LocalEd25519KmsProvider:
    """Non-exporting process-local provider used only for contract courts."""

    def __init__(
        self,
        *,
        provider_id: str = "archhub.local-ed25519",
        authority_id: str = "archhub-authority",
    ) -> None:
        self._provider_id = _checked_token(provider_id, "provider id")
        self._authority_id = _checked_token(authority_id, "authority id")
        self._keys: dict[str, Ed25519PrivateKey] = {}
        self._states: dict[str, str] = {}
        self._current: str | None = None
        self._lock = threading.RLock()
        self.rotate()

    def __reduce_ex__(self, protocol):
        raise TypeError("signing providers cannot be serialized")

    @property
    def current_resource(self) -> str:
        with self._lock:
            if self._current is None:
                raise SigningAuthorityDenied("provider has no active key")
            return self._current

    def rotate(self) -> str:
        with self._lock:
            if self._current is not None:
                self._states[self._current] = "verify-only"
            version = len(self._keys) + 1
            resource = "local://%s/keys/%s/versions/%d" % (
                self._provider_id,
                self._authority_id,
                version,
            )
            self._keys[resource] = Ed25519PrivateKey.generate()
            self._states[resource] = "active"
            self._current = resource
            return resource

    def set_state(self, resource_version: str, state: str) -> None:
        if state not in STATE_NAMES:
            raise ValueError("provider key state is invalid")
        with self._lock:
            if resource_version not in self._keys:
                raise SigningAuthorityDenied("unknown provider key resource")
            self._states[resource_version] = state
            if state != "active" and self._current == resource_version:
                self._current = None

    def describe(self, resource_version: str) -> ProviderKeyMetadata:
        with self._lock:
            key = self._keys.get(resource_version)
            if key is None:
                raise SigningAuthorityDenied("unknown provider key resource")
            public = key.public_key().public_bytes(
                serialization.Encoding.Raw,
                serialization.PublicFormat.Raw,
            )
            return ProviderKeyMetadata(
                LOCAL_PROVIDER_PROTOCOL,
                self._provider_id,
                resource_version,
                "sign-verify",
                "ed25519",
                "message",
                "sha256",
                "base64",
                "raw-ed25519",
                public,
                "software-process-test",
                "none",
                self._states[resource_version],
            )

    def sign(self, request: ProviderSignRequest) -> ProviderSignResponse:
        with self._lock:
            metadata = self.describe(request.resource_version)
            if metadata.state != "active":
                raise SigningAuthorityDenied("provider key is not active")
            if (
                request.signature_algorithm != metadata.signature_algorithm
                or request.payload_mode != metadata.payload_mode
                or request.digest_algorithm != metadata.digest_algorithm
                or not request.payload
            ):
                raise SigningAuthorityDenied("provider signing request mismatched")
            signature = self._keys[request.resource_version].sign(request.payload)
            integrity = "local-call-sha256:" + hashlib.sha256(
                request.request_id.encode("ascii")
                + request.resource_version.encode("ascii")
                + signature
            ).hexdigest()
            return ProviderSignResponse(
                request.request_id,
                metadata.provider_protocol,
                metadata.provider_id,
                metadata.resource_version,
                metadata.signature_algorithm,
                metadata.signature_encoding,
                metadata.protection_level,
                integrity,
                signature,
            )

    def verify(self, resource_version: str, payload: bytes, signature: bytes) -> bool:
        with self._lock:
            key = self._keys.get(resource_version)
            if key is None:
                return False
            public = key.public_key()
        try:
            public.verify(bytes(signature), bytes(payload))
        except InvalidSignature:
            return False
        return True


def verify_legacy_hmac_v1(
    provider: SigningKeyProvider,
    *,
    key_id: str,
    version: int,
    payload: bytes,
    signature: str,
) -> bool:
    """Verify historical v1 evidence without translating or rewriting it."""
    return provider.verify(key_id, version, bytes(payload), str(signature))


__all__ = [
    "DESCRIPTOR_PROTOCOL",
    "ENVELOPE_PROTOCOL",
    "LEGACY_PROVIDER_PROTOCOL",
    "LOCAL_PROVIDER_PROTOCOL",
    "LocalEd25519KmsProvider",
    "ProviderKeyMetadata",
    "ProviderSignRequest",
    "ProviderSignResponse",
    "SignatureEnvelopeProjection",
    "SigningAuthorityDenied",
    "SigningAuthorityProtocol",
    "SigningAuthorityProvider",
    "SigningKeyDescriptorProjection",
    "bootstrap_signing_authority_protocol",
    "build_signing_key_descriptor",
    "project_signing_authority_protocol",
    "read_signature_envelope",
    "read_signing_key_descriptor",
    "sign_statement",
    "verify_legacy_hmac_v1",
    "verify_signature_envelope",
    "verify_signing_key_descriptor",
]
