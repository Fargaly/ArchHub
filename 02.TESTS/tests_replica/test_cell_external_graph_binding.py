from __future__ import annotations

import pytest

from nodelang.cell_external_graph_binding import (
    bind_external_signing_authority,
    list_external_graph_bindings,
    verify_external_signing_authority_binding,
)
from nodelang.cell_protocols import compose_relation_cells, read_relation
from nodelang.cell_signing_authority import (
    LocalEd25519KmsProvider,
    bootstrap_signing_authority_protocol,
    build_signing_key_descriptor,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


def _terminal(root: str, value: str) -> Cell:
    return Cell(root, NULL_CELL_ID, NULL_CELL_ID, value.encode("ascii"))


def _application() -> tuple[CellStore, str, str, str]:
    store = CellStore()
    application_root = "court:application"
    member_role = "court:role:member"
    authorization_root = "court:authorization"
    store.commit(
        store.revision,
        create=(
            _terminal(member_role, "member"),
            _terminal(authorization_root, "founder authority"),
        ),
    )
    application = compose_relation_cells((), relation_id=application_root)
    store.commit(store.revision, create=application.cells)
    return store, application_root, member_role, authorization_root


def _authority(
    *,
    provider: LocalEd25519KmsProvider | None = None,
    descriptor_root: str = "court:authority:descriptor:v1",
    predecessor: str = "none",
):
    store = CellStore()
    protocol = bootstrap_signing_authority_protocol(
        store, prefix="court:authority:protocol"
    )
    provider = provider or LocalEd25519KmsProvider(
        provider_id="court-kms", authority_id="court-key"
    )
    store.commit(
        store.revision,
        create=(
            _terminal("court:authority:authorization", "authorized"),
            _terminal("court:authority:release", "released"),
        ),
    )
    descriptor = build_signing_key_descriptor(
        store,
        protocol,
        provider,
        descriptor_id=descriptor_root,
        resource_version=provider.current_resource,
        authority_id="court:external-authority",
        purpose="universal-revision-checkpoint",
        valid_from="2026-01-01T00:00:00Z",
        valid_until="2030-01-01T00:00:00Z",
        predecessor_descriptor=predecessor,
        authorization_evidence="court:authority:authorization",
        release_evidence="court:authority:release",
    )
    return store, protocol, provider, descriptor


def _bound():
    application = _application()
    authority = _authority()
    app_store, app_root, member_role, authorization_root = application
    authority_store, protocol, provider, descriptor = authority
    binding = bind_external_signing_authority(
        app_store,
        application_root=app_root,
        application_member_role=member_role,
        authorization_root=authorization_root,
        authority_store=authority_store,
        signing_protocol=protocol,
        provider=provider,
        descriptor_root=descriptor,
        prefix="court:external-binding",
    )
    return application, authority, binding


def test_external_authority_is_an_explicit_content_addressed_application_relation():
    application, authority, binding = _bound()
    app_store, app_root, member_role, authorization_root = application
    authority_store, protocol, provider, descriptor = authority

    verified = verify_external_signing_authority_binding(
        app_store.snapshot(),
        authority_store.snapshot(),
        signing_protocol=protocol,
        provider=provider,
        binding_root=binding.root_id,
        application_root=app_root,
        application_member_role=member_role,
        authorization_root=authorization_root,
        expected_descriptor_root=descriptor,
        prefix="court:external-binding",
    )

    app_members = read_relation(app_store.snapshot(), app_root, budget=10_000)
    assert binding.root_id in {
        member.participant_id
        for member in app_members
        if member.role_id == member_role
    }
    assert verified.remote_root_id == descriptor
    assert verified.purpose == "universal-revision-checkpoint"
    assert verified.provider_id == "court-kms"
    assert verified.public_key_digest.startswith("sha256:")
    assert verified.content_descriptor_root in app_store.snapshot().cells
    assert len(list_external_graph_bindings(
        app_store.snapshot(), prefix="court:external-binding"
    )) == 1


def test_external_binding_does_not_copy_provider_resource_or_remote_evidence():
    application, authority, binding = _bound()
    app_store, _app_root, _member_role, _authorization_root = application
    _authority_store, _protocol, provider, _descriptor = authority
    atoms = tuple(cell.atom for cell in app_store.snapshot().cells.values())

    assert provider.current_resource.encode("ascii") not in atoms
    assert b"court:authority:authorization" not in atoms
    assert b"court:authority:release" not in atoms
    assert binding.external_subject_root.startswith("external-object:sha256:")


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("remote-root-id", b"court:authority:descriptor:other"),
        ("purpose", b"other-purpose"),
        ("provider", b"other-provider"),
        ("protection", b"other-protection"),
        ("public-key-digest", b"sha256:" + b"0" * 64),
        ("attestation-digest", b"sha256:" + b"1" * 64),
        ("state", b"revoked"),
    ),
)
def test_external_binding_summary_tampering_fails_closed(field, replacement):
    application, authority, binding = _bound()
    app_store, app_root, member_role, authorization_root = application
    authority_store, protocol, provider, descriptor = authority
    root = binding.root_id + ":" + field
    original = app_store.read(root)
    app_store.commit(
        app_store.revision,
        replace=(Cell(root, original.link0, original.link1, replacement),),
    )

    with pytest.raises(InvalidCell):
        verify_external_signing_authority_binding(
            app_store.snapshot(),
            authority_store.snapshot(),
            signing_protocol=protocol,
            provider=provider,
            binding_root=binding.root_id,
            application_root=app_root,
            application_member_role=member_role,
            authorization_root=authorization_root,
            expected_descriptor_root=descriptor,
            prefix="court:external-binding",
        )


def test_content_descriptor_tamper_and_valid_descriptor_substitution_fail_closed():
    application, authority, binding = _bound()
    app_store, app_root, member_role, authorization_root = application
    authority_store, protocol, provider, descriptor = authority
    digest_root = binding.content_descriptor_root + ":digest"
    original = app_store.read(digest_root)
    app_store.commit(
        app_store.revision,
        replace=(Cell(
            digest_root,
            original.link0,
            original.link1,
            b"sha256:" + b"0" * 64,
        ),),
    )
    with pytest.raises(InvalidCell, match="digest"):
        verify_external_signing_authority_binding(
            app_store.snapshot(), authority_store.snapshot(),
            signing_protocol=protocol, provider=provider,
            binding_root=binding.root_id, application_root=app_root,
            application_member_role=member_role,
            authorization_root=authorization_root,
            expected_descriptor_root=descriptor,
            prefix="court:external-binding",
        )

    other_store, other_protocol, other_provider, other_descriptor = _authority(
        descriptor_root="court:authority:descriptor:valid-other"
    )
    with pytest.raises(InvalidCell, match="descriptor"):
        verify_external_signing_authority_binding(
            app_store.snapshot(), other_store.snapshot(),
            signing_protocol=other_protocol, provider=other_provider,
            binding_root=binding.root_id, application_root=app_root,
            application_member_role=member_role,
            authorization_root=authorization_root,
            expected_descriptor_root=other_descriptor,
            prefix="court:external-binding",
        )


def test_binding_removed_from_application_authority_fails_closed():
    application, authority, binding = _bound()
    app_store, app_root, member_role, authorization_root = application
    authority_store, protocol, provider, descriptor = authority
    members = read_relation(app_store.snapshot(), app_root, budget=10_000)
    binding_member = next(
        member for member in members
        if member.role_id == member_role
        and member.participant_id == binding.root_id
    )
    incidence = app_store.read(binding_member.incidence_id)
    app_store.commit(
        app_store.revision,
        replace=(Cell(
            incidence.id,
            incidence.link0,
            app_root,
            incidence.atom,
        ),),
    )
    with pytest.raises(InvalidCell, match="application"):
        verify_external_signing_authority_binding(
            app_store.snapshot(), authority_store.snapshot(),
            signing_protocol=protocol, provider=provider,
            binding_root=binding.root_id, application_root=app_root,
            application_member_role=member_role,
            authorization_root=authorization_root,
            expected_descriptor_root=descriptor,
            prefix="court:external-binding",
        )


def test_rotation_creates_successor_binding_and_preserves_predecessor():
    application, authority, first = _bound()
    app_store, app_root, member_role, authorization_root = application
    authority_store, protocol, provider, first_descriptor = authority
    provider.rotate()
    second_descriptor = build_signing_key_descriptor(
        authority_store,
        protocol,
        provider,
        descriptor_id="court:authority:descriptor:v2",
        resource_version=provider.current_resource,
        authority_id="court:external-authority",
        purpose="universal-revision-checkpoint",
        valid_from="2026-01-02T00:00:00Z",
        valid_until="2030-01-01T00:00:00Z",
        predecessor_descriptor=first_descriptor,
        authorization_evidence="court:authority:authorization",
        release_evidence="court:authority:release",
    )
    second = bind_external_signing_authority(
        app_store,
        application_root=app_root,
        application_member_role=member_role,
        authorization_root=authorization_root,
        authority_store=authority_store,
        signing_protocol=protocol,
        provider=provider,
        descriptor_root=second_descriptor,
        prefix="court:external-binding",
    )

    assert second.root_id != first.root_id
    assert second.predecessor_root == first.root_id
    assert first.root_id in app_store.snapshot().cells
    assert tuple(
        item.root_id for item in list_external_graph_bindings(
            app_store.snapshot(), prefix="court:external-binding"
        )
    ) == (first.root_id, second.root_id)


def test_rotation_without_matching_predecessor_is_rejected():
    application = _application()
    authority_store, protocol, provider, first_descriptor = _authority()
    provider.rotate()
    second_descriptor = build_signing_key_descriptor(
        authority_store,
        protocol,
        provider,
        descriptor_id="court:authority:descriptor:v2",
        resource_version=provider.current_resource,
        authority_id="court:external-authority",
        purpose="universal-revision-checkpoint",
        valid_from="2026-01-02T00:00:00Z",
        valid_until="2030-01-01T00:00:00Z",
        predecessor_descriptor=first_descriptor,
        authorization_evidence="court:authority:authorization",
        release_evidence="court:authority:release",
    )
    app_store, app_root, member_role, authorization_root = application

    with pytest.raises(InvalidCell, match="predecessor"):
        bind_external_signing_authority(
            app_store,
            application_root=app_root,
            application_member_role=member_role,
            authorization_root=authorization_root,
            authority_store=authority_store,
            signing_protocol=protocol,
            provider=provider,
            descriptor_root=second_descriptor,
            prefix="court:external-binding",
        )
