from __future__ import annotations

from dataclasses import replace
import pickle

import pytest

from nodelang.cell_protocols import append_relation_member, read_relation
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.cell_signing_authority import (
    LocalEd25519KmsProvider,
    ProviderSignRequest,
    ProviderSignResponse,
    SigningAuthorityDenied,
    bootstrap_signing_authority_protocol,
    build_signing_key_descriptor,
    project_signing_authority_protocol,
    read_signing_key_descriptor,
    sign_statement,
    verify_legacy_hmac_v1,
    verify_signature_envelope,
    verify_signing_key_descriptor,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


VALID_FROM = "2026-01-01T00:00:00Z"
VALID_UNTIL = "2030-01-01T00:00:00Z"


def _build(
    *, provider_id: str = "court-provider", authority_id: str = "court-authority"
):
    store = CellStore()
    protocol = bootstrap_signing_authority_protocol(
        store, prefix="court:signing"
    )
    provider = LocalEd25519KmsProvider(
        provider_id=provider_id, authority_id=authority_id
    )
    descriptor = build_signing_key_descriptor(
        store,
        protocol,
        provider,
        descriptor_id="court:key-descriptor:v1",
        resource_version=provider.current_resource,
        authority_id=authority_id,
        purpose="revision-checkpoint",
        valid_from=VALID_FROM,
        valid_until=VALID_UNTIL,
        authorization_evidence="court:authorization:1",
        release_evidence="court:release:1",
    )
    return store, protocol, provider, descriptor


def _sign(store, protocol, provider, descriptor, *, suffix: str = "1"):
    payload = ("checkpoint-payload-" + suffix).encode("ascii")
    envelope = sign_statement(
        store,
        protocol,
        provider,
        descriptor,
        envelope_id="court:envelope:" + suffix,
        statement_protocol="application/vnd.archhub.checkpoint.v2",
        context="revision-checkpoint",
        payload=payload,
        authorization_evidence="court:authorization:1",
        issued_at="2026-07-17T10:00:00Z",
        request_id="court-request-" + suffix,
    )
    return payload, envelope


def test_descriptor_and_envelope_are_strict_universal_cell_relations():
    store, protocol, provider, descriptor = _build()
    payload, envelope = _sign(store, protocol, provider, descriptor)

    projected = verify_signing_key_descriptor(
        store.snapshot(), protocol, provider, descriptor, require_signing=True
    )
    verified = verify_signature_envelope(
        store.snapshot(),
        protocol,
        provider,
        envelope,
        payload=payload,
        expected_statement_protocol="application/vnd.archhub.checkpoint.v2",
        expected_context="revision-checkpoint",
    )
    reopened = project_signing_authority_protocol(
        store.snapshot(), prefix="court:signing"
    )

    assert projected.values["resource-version"] == provider.current_resource
    assert projected.values["public-key-digest"].startswith("sha256:")
    assert verified.values["key-descriptor"] == descriptor
    assert read_relation(store.snapshot(), descriptor)
    assert read_relation(store.snapshot(), envelope)
    assert reopened.roles == protocol.roles
    assert all(isinstance(cell, Cell) for cell in store.snapshot().cells.values())


def test_payload_descriptor_and_provider_substitution_fail_closed():
    store, protocol, provider, descriptor = _build()
    payload, envelope = _sign(store, protocol, provider, descriptor)

    with pytest.raises(SigningAuthorityDenied, match="payload digest"):
        verify_signature_envelope(
            store.snapshot(), protocol, provider, envelope, payload=b"different"
        )

    foreign = LocalEd25519KmsProvider(
        provider_id="court-provider", authority_id="court-authority"
    )
    with pytest.raises(SigningAuthorityDenied, match="public-key-digest"):
        verify_signature_envelope(
            store.snapshot(), protocol, foreign, envelope, payload=payload
        )

    provider_id_root = descriptor + ":provider-id"
    original = store.read(provider_id_root)
    store.commit(
        store.revision,
        replace=(Cell(
            original.id, original.link0, original.link1, b"substituted-provider"
        ),),
    )
    with pytest.raises(InvalidCell, match="digest mismatched"):
        read_signing_key_descriptor(store.snapshot(), protocol, descriptor)


class _WrongResponseProvider:
    def __init__(self, delegate: LocalEd25519KmsProvider) -> None:
        self.delegate = delegate

    def describe(self, resource_version: str):
        return self.delegate.describe(resource_version)

    def sign(self, request: ProviderSignRequest) -> ProviderSignResponse:
        return replace(
            self.delegate.sign(request),
            resource_version=request.resource_version + "/substituted",
        )

    def verify(self, resource_version: str, payload: bytes, signature: bytes) -> bool:
        return self.delegate.verify(resource_version, payload, signature)


def test_provider_response_resource_substitution_is_rejected_before_commit():
    store, protocol, provider, descriptor = _build()
    before = store.revision

    with pytest.raises(SigningAuthorityDenied, match="response mismatched"):
        _sign(store, protocol, _WrongResponseProvider(provider), descriptor)

    assert store.revision == before
    assert "court:envelope:1" not in store.snapshot().cells


def test_rotation_preserves_old_verification_and_requires_new_descriptor():
    store, protocol, provider, old_descriptor = _build()
    old_payload, old_envelope = _sign(
        store, protocol, provider, old_descriptor, suffix="old"
    )
    new_resource = provider.rotate()

    verify_signature_envelope(
        store.snapshot(),
        protocol,
        provider,
        old_envelope,
        payload=old_payload,
    )
    with pytest.raises(SigningAuthorityDenied, match="not active"):
        _sign(store, protocol, provider, old_descriptor, suffix="denied")

    new_descriptor = build_signing_key_descriptor(
        store,
        protocol,
        provider,
        descriptor_id="court:key-descriptor:v2",
        resource_version=new_resource,
        authority_id="court-authority",
        purpose="revision-checkpoint",
        valid_from=VALID_FROM,
        valid_until=VALID_UNTIL,
        predecessor_descriptor=old_descriptor,
        authorization_evidence="court:authorization:2",
        release_evidence="court:release:2",
    )
    new_payload, new_envelope = _sign(
        store, protocol, provider, new_descriptor, suffix="new"
    )

    verify_signature_envelope(
        store.snapshot(), protocol, provider, old_envelope, payload=old_payload
    )
    verify_signature_envelope(
        store.snapshot(), protocol, provider, new_envelope, payload=new_payload
    )
    assert read_signing_key_descriptor(
        store.snapshot(), protocol, new_descriptor
    ).values["predecessor-descriptor"] == old_descriptor


def test_revocation_denies_current_use_but_retains_historical_crypto_check():
    store, protocol, provider, descriptor = _build()
    payload, envelope = _sign(store, protocol, provider, descriptor)
    provider.set_state(provider.current_resource, "revoked")

    with pytest.raises(SigningAuthorityDenied, match="not usable"):
        verify_signature_envelope(
            store.snapshot(), protocol, provider, envelope, payload=payload
        )
    verify_signature_envelope(
        store.snapshot(),
        protocol,
        provider,
        envelope,
        payload=payload,
        require_current_authority=False,
    )
    with pytest.raises(SigningAuthorityDenied):
        _sign(store, protocol, provider, descriptor, suffix="after-revocation")


def test_duplicate_unknown_and_nonterminal_fields_are_rejected():
    store, protocol, provider, descriptor = _build()
    duplicate_root = "court:duplicate-provider-id"
    store.commit(
        store.revision,
        create=(Cell(duplicate_root, NULL_CELL_ID, NULL_CELL_ID, b"court-provider"),),
    )
    append_relation_member(
        store,
        descriptor,
        protocol.role("descriptor-provider-id"),
        duplicate_root,
    )
    with pytest.raises(InvalidCell, match="exactly one provider-id"):
        read_signing_key_descriptor(store.snapshot(), protocol, descriptor)

    store, protocol, provider, descriptor = _build()
    field_root = descriptor + ":provider-id"
    field = store.read(field_root)
    store.commit(
        store.revision,
        replace=(Cell(field.id, protocol.root_id, field.link1, field.atom),),
    )
    with pytest.raises(InvalidCell, match="terminal"):
        read_signing_key_descriptor(store.snapshot(), protocol, descriptor)

    store, protocol, provider, descriptor = _build()
    unknown_root = "court:unknown-field"
    store.commit(
        store.revision,
        create=(Cell(unknown_root, NULL_CELL_ID, NULL_CELL_ID, b"unknown"),),
    )
    append_relation_member(
        store,
        descriptor,
        protocol.role("envelope-context"),
        unknown_root,
    )
    with pytest.raises(InvalidCell, match="undeclared"):
        read_signing_key_descriptor(store.snapshot(), protocol, descriptor)


def test_provider_has_no_export_surface_and_graph_contains_no_private_material():
    store, protocol, provider, descriptor = _build()
    payload, envelope = _sign(store, protocol, provider, descriptor)

    assert not hasattr(provider, "export_private_key")
    assert not hasattr(provider, "private_key")
    with pytest.raises(TypeError, match="cannot be serialized"):
        pickle.dumps(provider)
    assert all(
        b"PRIVATE KEY" not in cell.atom and b"BEGIN" not in cell.atom
        for cell in store.snapshot().cells.values()
    )
    verify_signature_envelope(
        store.snapshot(), protocol, provider, envelope, payload=payload
    )


def test_legacy_hmac_history_verifies_without_translation_or_rewrite():
    provider = MemorySigningKeyProvider("legacy-authority", b"l" * 32)
    payload = b"historical-v1-statement"
    signature = provider.sign("legacy-authority", 1, payload)

    assert verify_legacy_hmac_v1(
        provider,
        key_id="legacy-authority",
        version=1,
        payload=payload,
        signature=signature,
    )
    assert not verify_legacy_hmac_v1(
        provider,
        key_id="legacy-authority",
        version=1,
        payload=b"changed",
        signature=signature,
    )
