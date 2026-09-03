from __future__ import annotations

import ctypes
import os
import uuid

import pytest

import nodelang.windows_cng_signing_provider as cng
from nodelang.cell_revision_checkpoint import (
    RevisionCheckpointDenied,
    RevisionCheckpointGuard,
)
from nodelang.checkpoint_authority_provisioning import (
    provision_windows_revision_checkpoint_authority,
)
from nodelang.cell_signing_authority import (
    ProviderSignRequest,
    SigningAuthorityDenied,
    bootstrap_signing_authority_protocol,
    build_signing_key_descriptor,
    project_signing_authority_protocol,
    sign_statement,
    verify_signature_envelope,
)
from nodelang.universal_cell import CellStore


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows CNG court")


def _delete_court_key(provider_id: str, key_name: str) -> None:
    assert key_name.startswith("ArchHub.Court.")
    api = cng._api()
    provider_name = cng._PROVIDERS[provider_id][0]
    provider = api.open_provider(provider_name)
    key = None
    try:
        key = api.handle_type()
        status = api.library.NCryptOpenKey(
            provider,
            ctypes.byref(key),
            key_name,
            0,
            cng._NCRYPT_SILENT_FLAG,
        )
        if api.code(status) == cng._NTE_BAD_KEYSET:
            return
        api.require("open court key for cleanup", status)
        api.require(
            "delete isolated court key",
            api.library.NCryptDeleteKey(key, 0),
        )
        key = None
    finally:
        if key is not None:
            api.free(key)
        api.free(provider)


@pytest.fixture
def cng_provider_factory():
    created: list[tuple[str, str]] = []

    def factory(*, provider_id=cng.SOFTWARE_PROVIDER_ID):
        key_name = "ArchHub.Court.%s" % uuid.uuid4()
        created.append((provider_id, key_name))
        return cng.WindowsCngSigningAuthorityProvider(
            provider_id=provider_id,
            key_name=key_name,
            create=True,
        )

    yield factory
    for provider_id, key_name in reversed(created):
        _delete_court_key(provider_id, key_name)


def test_windows_cng_key_persists_reopens_and_signs(cng_provider_factory):
    provider = cng_provider_factory()
    resource = provider.current_resource
    metadata = provider.describe(resource)
    request = ProviderSignRequest(
        "court-request",
        resource,
        "ecdsa-p256-sha256-p1363",
        "message",
        "sha256",
        b"persistent authority statement",
    )
    response = provider.sign(request)

    assert metadata.provider_protocol == cng.WINDOWS_CNG_PROVIDER_PROTOCOL
    assert metadata.provider_id == cng.SOFTWARE_PROVIDER_ID
    assert metadata.protection_level == "windows-cng-software-user"
    assert metadata.public_key_format == "cng-eccpublicblob"
    assert len(metadata.public_key) == 72
    assert len(response.signature) == 64
    assert provider.verify(resource, request.payload, response.signature)
    assert not provider.verify(resource, b"changed", response.signature)
    assert not provider.verify(resource, request.payload, b"x" * 64)

    reopened = cng.WindowsCngSigningAuthorityProvider(
        provider_id=cng.SOFTWARE_PROVIDER_ID,
        key_name=provider.key_name,
        create=False,
    )
    assert reopened.current_resource == resource
    assert reopened.verify(resource, request.payload, response.signature)
    with pytest.raises(TypeError):
        reopened.__reduce_ex__(4)
    assert not hasattr(reopened, "export_private_key")
    assert not hasattr(reopened, "delete_key")


def test_windows_tpm_provider_signs_without_software_relabeling(
    cng_provider_factory,
):
    try:
        provider = cng_provider_factory(provider_id=cng.PLATFORM_PROVIDER_ID)
    except SigningAuthorityDenied as exc:
        pytest.skip("platform provider is unavailable: %s" % exc)
    metadata = provider.describe(provider.current_resource)
    request = ProviderSignRequest(
        "tpm-court-request",
        provider.current_resource,
        "ecdsa-p256-sha256-p1363",
        "message",
        "sha256",
        b"TPM authority statement",
    )
    response = provider.sign(request)

    assert metadata.provider_id == cng.PLATFORM_PROVIDER_ID
    assert metadata.protection_level == "windows-tpm-user"
    assert response.protection_level == "windows-tpm-user"
    assert provider.verify(
        provider.current_resource, request.payload, response.signature
    )


def test_windows_cng_exact_resource_rejects_other_key(cng_provider_factory):
    first = cng_provider_factory()
    second = cng_provider_factory()
    with pytest.raises(SigningAuthorityDenied, match="resource mismatched"):
        first.describe(second.current_resource)


def test_windows_cng_key_policy_denies_private_export(cng_provider_factory):
    provider = cng_provider_factory()
    api = cng._api()
    storage = api.open_provider(provider.provider_name)
    key = None
    try:
        status, key = provider._open_key(storage, provider.key_name)
        api.require("open court signing key", status)
        size = api.dword_type()
        status = api.library.NCryptExportKey(
            key,
            api.handle_type(),
            "ECCPRIVATEBLOB",
            None,
            None,
            0,
            ctypes.byref(size),
            cng._NCRYPT_SILENT_FLAG,
        )
        assert api.code(status) != 0
    finally:
        if key is not None:
            api.free(key)
        api.free(storage)


def test_windows_cng_provider_drives_graph_envelope_after_store_restart(
    tmp_path, cng_provider_factory
):
    path = tmp_path / "authority.sqlite3"
    provider = cng_provider_factory()
    store = CellStore(path)
    protocol = bootstrap_signing_authority_protocol(
        store, prefix="court:cng-signing"
    )
    descriptor = build_signing_key_descriptor(
        store,
        protocol,
        provider,
        descriptor_id="court:cng-key:v1",
        resource_version=provider.current_resource,
        authority_id="archhub-local-checkpoint",
        purpose="universal-revision-checkpoint",
        valid_from="2026-01-01T00:00:00Z",
        valid_until="2030-01-01T00:00:00Z",
        authorization_evidence="court:cng-authorization",
        release_evidence="court:cng-release",
    )
    payload = b"graph-held statement"
    envelope = sign_statement(
        store,
        protocol,
        provider,
        descriptor,
        envelope_id="court:cng-envelope",
        statement_protocol="application/vnd.archhub.cng-court.v1",
        context="cng-court",
        payload=payload,
        authorization_evidence="court:cng-authorization",
    )
    assert all(b"PRIVATE" not in cell.atom for cell in store.snapshot().cells.values())
    store.close()

    reopened_store = CellStore(path)
    reopened_protocol = project_signing_authority_protocol(
        reopened_store.snapshot(), prefix="court:cng-signing"
    )
    reopened_provider = cng.WindowsCngSigningAuthorityProvider(
        provider_id=cng.SOFTWARE_PROVIDER_ID,
        key_name=provider.key_name,
        create=False,
    )
    verified = verify_signature_envelope(
        reopened_store.snapshot(),
        reopened_protocol,
        reopened_provider,
        envelope,
        payload=payload,
        expected_statement_protocol="application/vnd.archhub.cng-court.v1",
        expected_context="cng-court",
    )
    assert verified.values["key-descriptor"] == descriptor
    reopened_store.close()


def test_windows_cng_checkpoint_authority_provisions_and_reopens(tmp_path):
    database_path = tmp_path / "application.sqlite3"
    authority_path = tmp_path / "checkpoint-authority.sqlite3"
    checkpoint_path = tmp_path / "checkpoint.json"
    key_name = "ArchHub.Court.%s" % uuid.uuid4()
    try:
        authority = provision_windows_revision_checkpoint_authority(
            database_path,
            authority_path=authority_path,
            provider_id=cng.SOFTWARE_PROVIDER_ID,
            key_name=key_name,
        )
        store = CellStore(database_path)
        guard = RevisionCheckpointGuard(
            checkpoint_path,
            database_identity=str(database_path),
            signing_authority=authority,
        )
        guard.bind(store)
        guard.require_healthy()
        guard.close()
        store.close()
        authority.store.close()

        reopened_authority = provision_windows_revision_checkpoint_authority(
            database_path,
            authority_path=authority_path,
            provider_id=cng.SOFTWARE_PROVIDER_ID,
            key_name=key_name,
        )
        reopened_store = CellStore(database_path)
        restarted = RevisionCheckpointGuard(
            checkpoint_path,
            database_identity=str(database_path),
            signing_authority=reopened_authority,
        )
        restarted.bind(reopened_store)
        restarted.require_healthy()
        restarted.close()
        reopened_store.close()
        reopened_authority.store.close()
    finally:
        _delete_court_key(cng.SOFTWARE_PROVIDER_ID, key_name)


def test_checkpoint_authority_auto_selection_is_recorded_and_stable(tmp_path):
    database_path = tmp_path / "auto-application.sqlite3"
    authority_path = tmp_path / "auto-authority.sqlite3"
    key_name = "ArchHub.Court.%s" % uuid.uuid4()
    selected = None
    try:
        authority = provision_windows_revision_checkpoint_authority(
            database_path,
            authority_path=authority_path,
            key_name=key_name,
        )
        selected = authority.provider.provider_id
        descriptor = authority.provider.describe(
            authority.provider.current_resource
        )
        assert selected in {
            cng.PLATFORM_PROVIDER_ID,
            cng.SOFTWARE_PROVIDER_ID,
        }
        assert descriptor.protection_level == (
            "windows-tpm-user"
            if selected == cng.PLATFORM_PROVIDER_ID
            else "windows-cng-software-user"
        )
        authority.store.close()

        reopened = provision_windows_revision_checkpoint_authority(
            database_path,
            authority_path=authority_path,
            key_name=key_name,
        )
        assert reopened.provider.provider_id == selected
        reopened.store.close()

        other = (
            cng.SOFTWARE_PROVIDER_ID
            if selected == cng.PLATFORM_PROVIDER_ID
            else cng.PLATFORM_PROVIDER_ID
        )
        with pytest.raises(
            RevisionCheckpointDenied, match="provider selection mismatched"
        ):
            provision_windows_revision_checkpoint_authority(
                database_path,
                authority_path=authority_path,
                provider_id=other,
                key_name=key_name,
            )
    finally:
        if selected is not None:
            _delete_court_key(selected, key_name)
