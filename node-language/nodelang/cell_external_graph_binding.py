"""Content-addressed relations from one Cell graph to another.

The external store remains a physical custody boundary.  This module persists
only a pseudonymous subject identity, a closed content descriptor, selected
public security metadata, and explicit relation incidence in the consumer
graph.  It never persists paths, provider resource handles, or private bytes.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import re
from types import MappingProxyType
from typing import Mapping

from .cell_cloud_routes import external_object_root, provision_external_object
from .cell_content_descriptors import (
    ContentDescriptorProtocol,
    bootstrap_content_descriptor_protocol,
    compose_content_descriptor,
    project_content_descriptor_protocol,
    verify_content_descriptor,
)
from .cell_lifecycle import graph_content_bytes
from .cell_protocols import (
    CellBatch,
    compose_relation_cells,
    prepare_append_relation_members,
    read_relation,
)
from .cell_signing_authority import (
    SigningAuthorityProtocol,
    SigningAuthorityProvider,
    read_signing_key_descriptor,
    verify_signing_key_descriptor,
)
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


MEDIA_TYPE = "application/vnd.archhub.cell-graph.signing-key-descriptor.v2"
ROLE_NAMES = (
    "vocabulary-member",
    "binding-member",
    "consumer",
    "external-subject",
    "content-descriptor",
    "remote-root-id",
    "purpose",
    "provider",
    "protection",
    "public-key-digest",
    "attestation-digest",
    "state",
    "predecessor",
    "authorization",
)
FIELD_NAMES = (
    "remote-root-id",
    "purpose",
    "provider",
    "protection",
    "public-key-digest",
    "attestation-digest",
    "state",
)
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class ExternalGraphBindingProtocol:
    root_id: str
    roles: Mapping[str, str]
    content_descriptor_protocol: ContentDescriptorProtocol

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell(
                "unknown external graph binding role %r" % name
            ) from exc


@dataclass(frozen=True, slots=True)
class ExternalGraphBindingProjection:
    root_id: str
    consumer_root: str
    external_subject_root: str
    content_descriptor_root: str
    remote_root_id: str
    purpose: str
    provider_id: str
    protection: str
    public_key_digest: str
    attestation_digest: str
    state: str
    predecessor_root: str | None
    authorization_root: str


def _terminal(root_id: str, value: str) -> Cell:
    try:
        atom = str(value).encode("ascii")
    except UnicodeEncodeError as exc:
        raise InvalidCell("external graph binding values must be ASCII") from exc
    if not atom or len(atom) > 65_536 or any(byte < 0x20 for byte in atom):
        raise InvalidCell("external graph binding value is invalid")
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, atom)


def bootstrap_external_graph_binding_protocol(
    store: CellStore, *, prefix: str = "external-graph-binding"
) -> ExternalGraphBindingProtocol:
    content_prefix = prefix + ":content-descriptor"
    content = bootstrap_content_descriptor_protocol(
        store, prefix=content_prefix
    )
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    root_id = prefix + ":root"
    batch = CellBatch(store)
    for name, role_root in roles.items():
        batch.add(_terminal(role_root, name))
    batch.relation(
        (
            (roles["vocabulary-member"], role_root)
            for role_root in roles.values()
        ),
        relation_id=root_id,
    )
    batch.commit()
    return ExternalGraphBindingProtocol(
        root_id, MappingProxyType(roles), content
    )


def project_external_graph_binding_protocol(
    snapshot: Snapshot, *, prefix: str = "external-graph-binding"
) -> ExternalGraphBindingProtocol:
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    root_id = prefix + ":root"
    required = (root_id, *roles.values())
    if any(root not in snapshot.cells for root in required):
        raise InvalidCell("external graph binding protocol is incomplete")
    members = read_relation(snapshot, root_id, budget=256)
    declared = tuple(
        member.participant_id
        for member in members
        if member.role_id == roles["vocabulary-member"]
    )
    if len(declared) != len(set(declared)) or set(declared) != set(roles.values()):
        raise InvalidCell("external graph binding vocabulary drifted")
    unknown = {
        member.role_id for member in members
        if member.role_id not in {
            roles["vocabulary-member"], roles["binding-member"]
        }
    }
    if unknown:
        raise InvalidCell("external graph binding registry has unknown roles")
    content = project_content_descriptor_protocol(
        snapshot, prefix=prefix + ":content-descriptor"
    )
    return ExternalGraphBindingProtocol(
        root_id, MappingProxyType(roles), content
    )


def _protocol(
    store: CellStore, prefix: str
) -> ExternalGraphBindingProtocol:
    if prefix + ":root" in store.snapshot().cells:
        return project_external_graph_binding_protocol(
            store.snapshot(), prefix=prefix
        )
    return bootstrap_external_graph_binding_protocol(store, prefix=prefix)


def _one(members, role_id: str, label: str) -> str:
    values = tuple(
        member.participant_id for member in members
        if member.role_id == role_id
    )
    if len(values) != 1:
        raise InvalidCell(
            "external graph binding requires exactly one %s" % label
        )
    return values[0]


def _optional(members, role_id: str, label: str) -> str | None:
    values = tuple(
        member.participant_id for member in members
        if member.role_id == role_id
    )
    if len(values) > 1:
        raise InvalidCell(
            "external graph binding repeats %s" % label
        )
    return values[0] if values else None


def read_external_graph_binding(
    snapshot: Snapshot,
    protocol: ExternalGraphBindingProtocol,
    binding_root: str,
) -> ExternalGraphBindingProjection:
    members = read_relation(snapshot, binding_root, budget=128)
    allowed = {
        protocol.role(name)
        for name in ROLE_NAMES
        if name not in ("vocabulary-member", "binding-member")
    }
    if any(member.role_id not in allowed for member in members):
        raise InvalidCell("external graph binding contains an undeclared field")
    roots = {
        name: _one(members, protocol.role(name), name)
        for name in (
            "consumer",
            "external-subject",
            "content-descriptor",
            *FIELD_NAMES,
            "authorization",
        )
    }
    predecessor = _optional(
        members, protocol.role("predecessor"), "predecessor"
    )
    values: dict[str, str] = {}
    for name in FIELD_NAMES:
        cell = snapshot.cells.get(roots[name])
        if cell is None:
            raise InvalidCell("external graph binding field is missing")
        if cell.link0 != NULL_CELL_ID or cell.link1 != NULL_CELL_ID:
            raise InvalidCell("external graph binding fields must be terminal")
        try:
            values[name] = cell.atom.decode("ascii")
        except UnicodeDecodeError as exc:
            raise InvalidCell(
                "external graph binding fields must be ASCII"
            ) from exc
        if not values[name]:
            raise InvalidCell("external graph binding fields cannot be empty")
    if not _SHA256.fullmatch(values["public-key-digest"]):
        raise InvalidCell("external graph binding public key digest is invalid")
    if (
        values["attestation-digest"] != "none"
        and not _SHA256.fullmatch(values["attestation-digest"])
    ):
        raise InvalidCell("external graph binding attestation digest is invalid")
    return ExternalGraphBindingProjection(
        binding_root,
        roots["consumer"],
        roots["external-subject"],
        roots["content-descriptor"],
        values["remote-root-id"],
        values["purpose"],
        values["provider"],
        values["protection"],
        values["public-key-digest"],
        values["attestation-digest"],
        values["state"],
        predecessor,
        roots["authorization"],
    )


def list_external_graph_bindings(
    snapshot: Snapshot, *, prefix: str = "external-graph-binding"
) -> tuple[ExternalGraphBindingProjection, ...]:
    protocol = project_external_graph_binding_protocol(
        snapshot, prefix=prefix
    )
    roots = tuple(
        member.participant_id
        for member in read_relation(snapshot, protocol.root_id, budget=100_000)
        if member.role_id == protocol.role("binding-member")
    )
    if len(roots) != len(set(roots)):
        raise InvalidCell("external graph binding registry contains duplicates")
    return tuple(
        read_external_graph_binding(snapshot, protocol, root) for root in roots
    )


def _application_membership(
    snapshot: Snapshot,
    application_root: str,
    application_member_role: str,
    binding_root: str,
) -> None:
    count = sum(
        1 for member in read_relation(
            snapshot, application_root, budget=100_000
        )
        if member.role_id == application_member_role
        and member.participant_id == binding_root
    )
    if count != 1:
        raise InvalidCell(
            "external graph binding has no unique application authority"
        )


def _expected_summary(descriptor) -> Mapping[str, str]:
    values = descriptor.values
    return MappingProxyType({
        "remote-root-id": descriptor.root_id,
        "purpose": values["purpose"],
        "provider": values["provider-id"],
        "protection": values["protection-level"],
        "public-key-digest": values["public-key-digest"],
        "attestation-digest": values["attestation-digest"],
        "state": values["state"],
    })


def verify_external_signing_authority_binding(
    application_snapshot: Snapshot,
    authority_snapshot: Snapshot,
    *,
    signing_protocol: SigningAuthorityProtocol,
    provider: SigningAuthorityProvider,
    binding_root: str,
    application_root: str,
    application_member_role: str,
    authorization_root: str,
    expected_descriptor_root: str,
    prefix: str = "external-graph-binding",
    expected_purpose: str = "universal-revision-checkpoint",
    require_signing: bool = True,
) -> ExternalGraphBindingProjection:
    protocol = project_external_graph_binding_protocol(
        application_snapshot, prefix=prefix
    )
    binding = read_external_graph_binding(
        application_snapshot, protocol, binding_root
    )
    _application_membership(
        application_snapshot,
        application_root,
        application_member_role,
        binding_root,
    )
    registered = tuple(
        member.participant_id
        for member in read_relation(
            application_snapshot, protocol.root_id, budget=100_000
        )
        if member.role_id == protocol.role("binding-member")
        and member.participant_id == binding_root
    )
    if len(registered) != 1:
        raise InvalidCell("external graph binding is not uniquely registered")
    if binding.consumer_root != application_root:
        raise InvalidCell("external graph binding consumer mismatched")
    if binding.authorization_root != authorization_root:
        raise InvalidCell("external graph binding authorization mismatched")
    if binding.remote_root_id != expected_descriptor_root:
        raise InvalidCell("external graph binding descriptor mismatched")

    descriptor = verify_signing_key_descriptor(
        authority_snapshot,
        signing_protocol,
        provider,
        expected_descriptor_root,
        require_signing=require_signing,
        require_current_authority=require_signing,
    )
    if descriptor.values["purpose"] != expected_purpose:
        raise InvalidCell("external graph binding purpose mismatched")
    external_subject = external_object_root(
        "signing-authority", descriptor.values["authority-id"]
    )
    if binding.external_subject_root != external_subject:
        raise InvalidCell("external graph binding subject mismatched")
    canonical = graph_content_bytes(
        authority_snapshot, expected_descriptor_root, budget=100_000
    )
    verify_content_descriptor(
        application_snapshot,
        protocol.content_descriptor_protocol,
        binding.content_descriptor_root,
        content=canonical,
        expected_subject_root=external_subject,
        expected_media_type=MEDIA_TYPE,
    )
    expected = _expected_summary(descriptor)
    actual = {
        "remote-root-id": binding.remote_root_id,
        "purpose": binding.purpose,
        "provider": binding.provider_id,
        "protection": binding.protection,
        "public-key-digest": binding.public_key_digest,
        "attestation-digest": binding.attestation_digest,
        "state": binding.state,
    }
    for name, value in expected.items():
        if not hmac.compare_digest(value, actual[name]):
            raise InvalidCell("external graph binding %s mismatched" % name)

    remote_predecessor = descriptor.values["predecessor-descriptor"]
    if remote_predecessor == "none":
        if binding.predecessor_root is not None:
            raise InvalidCell("external graph binding predecessor mismatched")
    else:
        if binding.predecessor_root is None:
            raise InvalidCell("external graph binding predecessor is missing")
        predecessor = read_external_graph_binding(
            application_snapshot, protocol, binding.predecessor_root
        )
        if (
            predecessor.consumer_root != binding.consumer_root
            or predecessor.external_subject_root != binding.external_subject_root
            or predecessor.remote_root_id != remote_predecessor
        ):
            raise InvalidCell("external graph binding predecessor mismatched")
        verify_signing_key_descriptor(
            authority_snapshot,
            signing_protocol,
            provider,
            remote_predecessor,
            require_signing=False,
            require_current_authority=False,
        )
        predecessor_canonical = graph_content_bytes(
            authority_snapshot, remote_predecessor, budget=100_000
        )
        verify_content_descriptor(
            application_snapshot,
            protocol.content_descriptor_protocol,
            predecessor.content_descriptor_root,
            content=predecessor_canonical,
            expected_subject_root=external_subject,
            expected_media_type=MEDIA_TYPE,
        )
    return binding


def bind_external_signing_authority(
    application_store: CellStore,
    *,
    application_root: str,
    application_member_role: str,
    authorization_root: str,
    authority_store: CellStore,
    signing_protocol: SigningAuthorityProtocol,
    provider: SigningAuthorityProvider,
    descriptor_root: str,
    prefix: str = "external-graph-binding",
    expected_purpose: str = "universal-revision-checkpoint",
) -> ExternalGraphBindingProjection:
    """Create once or verify one exact external signing-authority relation."""
    application_snapshot = application_store.snapshot()
    for root, label in (
        (application_root, "application"),
        (application_member_role, "application member role"),
        (authorization_root, "authorization"),
    ):
        if root not in application_snapshot.cells:
            raise InvalidCell("external graph binding %s is missing" % label)
    protocol = _protocol(application_store, prefix)
    authority_snapshot = authority_store.snapshot()
    descriptor = verify_signing_key_descriptor(
        authority_snapshot,
        signing_protocol,
        provider,
        descriptor_root,
        require_signing=True,
    )
    if descriptor.values["purpose"] != expected_purpose:
        raise InvalidCell("external graph binding purpose mismatched")
    external_subject = provision_external_object(
        application_store,
        namespace="signing-authority",
        external_id=descriptor.values["authority-id"],
    )
    canonical = graph_content_bytes(
        authority_snapshot, descriptor_root, budget=100_000
    )
    identity = hashlib.sha256(canonical).hexdigest()
    binding_root = "%s:binding:sha256:%s" % (prefix, identity)
    existing = {item.root_id: item for item in list_external_graph_bindings(
        application_store.snapshot(), prefix=prefix
    )}
    if binding_root in existing:
        return verify_external_signing_authority_binding(
            application_store.snapshot(),
            authority_snapshot,
            signing_protocol=signing_protocol,
            provider=provider,
            binding_root=binding_root,
            application_root=application_root,
            application_member_role=application_member_role,
            authorization_root=authorization_root,
            expected_descriptor_root=descriptor_root,
            prefix=prefix,
            expected_purpose=expected_purpose,
        )

    predecessor_remote = descriptor.values["predecessor-descriptor"]
    predecessor_root = None
    if predecessor_remote == "none":
        if existing:
            raise InvalidCell(
                "external graph binding replacement lacks predecessor continuity"
            )
    else:
        matches = tuple(
            item for item in existing.values()
            if item.remote_root_id == predecessor_remote
            and item.consumer_root == application_root
            and item.external_subject_root == external_subject
        )
        if len(matches) != 1:
            raise InvalidCell(
                "external graph binding predecessor is not uniquely trusted"
            )
        predecessor_root = matches[0].root_id

    application_snapshot = application_store.snapshot()
    content_descriptor_root = binding_root + ":content-descriptor"
    content = compose_content_descriptor(
        application_snapshot,
        protocol.content_descriptor_protocol,
        descriptor_id=content_descriptor_root,
        subject_root=external_subject,
        media_type=MEDIA_TYPE,
        content=canonical,
    )
    summary = _expected_summary(descriptor)
    scalar_cells = tuple(
        _terminal(binding_root + ":" + name, value)
        for name, value in summary.items()
    )
    members = [
        (protocol.role("consumer"), application_root),
        (protocol.role("external-subject"), external_subject),
        (protocol.role("content-descriptor"), content_descriptor_root),
        *((
            protocol.role(name), binding_root + ":" + name
        ) for name in FIELD_NAMES),
    ]
    if predecessor_root is not None:
        members.append((protocol.role("predecessor"), predecessor_root))
    members.append((protocol.role("authorization"), authorization_root))
    relation = compose_relation_cells(members, relation_id=binding_root)

    protocol_patch = prepare_append_relation_members(
        application_snapshot,
        protocol.root_id,
        ((protocol.role("binding-member"), binding_root),),
        budget=100_000,
    )
    application_members = {
        (member.role_id, member.participant_id)
        for member in read_relation(
            application_snapshot, application_root, budget=100_000
        )
    }
    required_members = tuple(
        pair for pair in (
            (application_member_role, protocol.root_id),
            (
                application_member_role,
                protocol.content_descriptor_protocol.root_id,
            ),
            (application_member_role, binding_root),
        )
        if pair not in application_members
    )
    application_patch = prepare_append_relation_members(
        application_snapshot,
        application_root,
        required_members,
        budget=100_000,
    )
    application_store.commit(
        application_snapshot.revision,
        create=(
            *scalar_cells,
            *content.cells,
            *relation.cells,
            *protocol_patch.create,
            *application_patch.create,
        ),
        replace=(*protocol_patch.replace, *application_patch.replace),
    )
    return verify_external_signing_authority_binding(
        application_store.snapshot(),
        authority_snapshot,
        signing_protocol=signing_protocol,
        provider=provider,
        binding_root=binding_root,
        application_root=application_root,
        application_member_role=application_member_role,
        authorization_root=authorization_root,
        expected_descriptor_root=descriptor_root,
        prefix=prefix,
        expected_purpose=expected_purpose,
    )


__all__ = [
    "ExternalGraphBindingProjection",
    "ExternalGraphBindingProtocol",
    "MEDIA_TYPE",
    "bind_external_signing_authority",
    "bootstrap_external_graph_binding_protocol",
    "list_external_graph_bindings",
    "project_external_graph_binding_protocol",
    "read_external_graph_binding",
    "verify_external_signing_authority_binding",
]
