"""Tenant copies composed from existing catalogue, lifecycle, policy, and wires.

This is a higher-level graph assembly, not a kernel node kind.  A tenant has a
pseudonymous stable identity, per-tenant role nodes, a versioned configuration
relation, and signed membership relationships.  Role authority is activated
only after the configuration reaches a court-backed Published revision.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
from types import MappingProxyType
from typing import Mapping
import time
import uuid

from .cell_authorization import AuthorizationProtocol, verify_authorization_policy
from .cell_catalog import (
    AssemblyProtocol,
    instantiate_catalog_definition,
    verify_released_catalog,
)
from .cell_content_descriptors import (
    ContentDescriptorProtocol,
    bootstrap_content_descriptor_protocol,
    compose_content_descriptor,
    content_identity_bytes,
    project_content_descriptor_protocol,
    read_content_descriptor,
    verify_content_descriptor,
)
from .cell_cloud_sessions import TenantAdmissionEvidence
from .cell_cloud_routes import external_object_root, provision_external_object
from .cell_identity import (
    IdentityProtocol,
    RelationshipAuthorityBroker,
    RelationshipAuthorityDenied,
    active_membership_roots,
    grant_authority_relationship,
    revoke_authority_relationship,
    verify_authority_relationship,
)
from .cell_lifecycle import (
    LifecycleProtocol,
    append_wip_graph_revision,
    read_lifecycle_instance,
    read_revision,
    state_heads,
)
from .cell_protocols import (
    CellBatch,
    RelationMember,
    compose_relation_cells,
    prepare_append_relation_member,
    read_relation,
)
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


ROLE_NAMES = (
    "vocabulary-member",
    "binding-member",
    "selection-member",
    "tenant",
    "lifecycle-instance",
    "catalogue",
    "policy",
    "owner-role",
    "administrator-role",
    "member-role",
    "binding-digest",
    "selected-revision",
    "selection-actor",
    "selection-time",
    "selection-predecessor",
    "selection-digest",
)
TENANT_ROLE_NAMES = ("owner", "administrator", "member")
CATALOGUE_RELEASE_MEDIA_TYPE = "application/vnd.archhub.catalogue-release.v1"
POLICY_RELEASE_MEDIA_TYPE = "application/vnd.archhub.policy-release.v1"


class TenantAuthorityDenied(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class TenantConfigurationProtocol:
    root_id: str
    roles: Mapping[str, str]
    descriptor_protocol: ContentDescriptorProtocol

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown tenant configuration role %r" % name) from exc


@dataclass(frozen=True, slots=True)
class TenantConfigurationProjection:
    root_id: str
    tenant_root: str
    catalogue_root: str
    policy_root: str
    role_roots: Mapping[str, str]
    catalogue_descriptor_root: str | None
    policy_descriptor_root: str | None

    @property
    def release_manifested(self) -> bool:
        return (
            self.catalogue_descriptor_root is not None
            and self.policy_descriptor_root is not None
        )


@dataclass(frozen=True, slots=True)
class TenantBindingProjection:
    root_id: str
    tenant_root: str
    lifecycle_instance_root: str
    digest: str


@dataclass(frozen=True, slots=True)
class StagedTenantAuthority:
    tenant_root: str
    role_roots: Mapping[str, str]
    configuration_root: str
    lifecycle_instance_root: str
    binding_root: str
    wip_revision_root: str


@dataclass(frozen=True, slots=True)
class PublishedTenantAuthority:
    tenant_root: str
    role_roots: Mapping[str, str]
    configuration_root: str
    lifecycle_instance_root: str
    published_revision_root: str
    catalogue_root: str
    policy_root: str
    catalogue_descriptor_root: str | None
    policy_descriptor_root: str | None

    @property
    def release_manifested(self) -> bool:
        return (
            self.catalogue_descriptor_root is not None
            and self.policy_descriptor_root is not None
        )


@dataclass(frozen=True, slots=True)
class TenantReleaseSelection:
    root_id: str
    tenant_root: str
    lifecycle_instance_root: str
    selected_revision_root: str
    actor_root: str
    selected_at: float
    predecessor_root: str | None
    digest: str


class PublishedTenantAdmissionVerifier:
    """Admit only subjects wired to one currently Published tenant graph."""

    def __init__(
        self,
        tenant_protocol: TenantConfigurationProtocol,
        assembly_protocol: AssemblyProtocol,
        lifecycle_protocol: LifecycleProtocol,
        authorization_protocol: AuthorizationProtocol,
        identity_protocol: IdentityProtocol,
        relationship_broker: RelationshipAuthorityBroker,
    ) -> None:
        self._tenant_protocol = tenant_protocol
        self._assembly_protocol = assembly_protocol
        self._lifecycle_protocol = lifecycle_protocol
        self._authorization_protocol = authorization_protocol
        self._identity_protocol = identity_protocol
        self._relationship_broker = relationship_broker

    def verify(
        self,
        snapshot: Snapshot,
        *,
        tenant_root: str,
        subject_root: str,
        now: float,
    ) -> TenantAdmissionEvidence:
        published = published_tenant_authority(
            snapshot,
            self._tenant_protocol,
            self._assembly_protocol,
            self._lifecycle_protocol,
            self._authorization_protocol,
            self._identity_protocol,
            self._relationship_broker,
            tenant_root=tenant_root,
            now=now,
        )
        reachable = set(active_membership_roots(
            snapshot,
            self._identity_protocol,
            self._relationship_broker,
            subject_root,
            tenant_root,
            now=now,
        ))
        active_roles = set(published.role_roots.values()).intersection(reachable)
        if tenant_root not in reachable or not active_roles:
            raise TenantAuthorityDenied(
                "subject has no active role in the Published tenant"
            )

        activated_roles = set()
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
                relationship.source_root in active_roles
                and relationship.target_root == tenant_root
                and relationship.tenant_root == tenant_root
                and relationship.kind_root
                == self._identity_protocol.kinds["membership"]
                and published.published_revision_root
                in relationship.evidence_roots
            ):
                activated_roles.add(relationship.source_root)
        if not activated_roles:
            raise TenantAuthorityDenied(
                "subject role is not activated by the current Published tenant"
            )
        return TenantAdmissionEvidence(
            tenant_root,
            published.published_revision_root,
            published.catalogue_root,
            published.policy_root,
        )


def _terminal(root_id: str, value: str) -> Cell:
    atom = value.encode("utf-8")
    if not atom:
        raise InvalidCell("tenant authority scalar cannot be empty")
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, atom)


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
        raise TenantAuthorityDenied("tenant graph requires exactly one %s" % label)
    return values[0]


def bootstrap_tenant_configuration_protocol(
    store: CellStore, *, prefix: str = "tenant-configuration-protocol"
) -> TenantConfigurationProtocol:
    descriptors = bootstrap_content_descriptor_protocol(
        store, prefix=prefix + ":release-descriptor"
    )
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    root_id = prefix + ":root"
    batch = CellBatch(store)
    for name, root in roles.items():
        batch.add(_terminal(root, name))
    batch.relation(
        (
            *((roles["vocabulary-member"], root) for root in roles.values()),
            (roles["vocabulary-member"], descriptors.root_id),
        ),
        relation_id=root_id,
    )
    batch.commit()
    return TenantConfigurationProtocol(
        root_id, MappingProxyType(roles), descriptors
    )


def ensure_tenant_release_descriptor_protocol(
    store: CellStore, *, prefix: str = "tenant-configuration-protocol"
) -> None:
    """Append the generic release-descriptor vocabulary to a legacy protocol."""
    descriptor_prefix = prefix + ":release-descriptor"
    descriptor_root = descriptor_prefix + ":root"
    snapshot = store.snapshot()
    if descriptor_root not in snapshot.cells:
        bootstrap_content_descriptor_protocol(store, prefix=descriptor_prefix)
        snapshot = store.snapshot()
    else:
        project_content_descriptor_protocol(snapshot, prefix=descriptor_prefix)
    tenant_root = prefix + ":root"
    vocabulary_role = prefix + ":role:vocabulary-member"
    if tenant_root not in snapshot.cells or vocabulary_role not in snapshot.cells:
        raise InvalidCell("tenant configuration protocol is incomplete")
    members = read_relation(snapshot, tenant_root, budget=256)
    matches = tuple(
        member for member in members
        if member.role_id == vocabulary_role
        and member.participant_id == descriptor_root
    )
    if len(matches) > 1:
        raise InvalidCell("tenant release descriptor vocabulary is duplicated")
    if not matches:
        patch = prepare_append_relation_member(
            snapshot,
            tenant_root,
            vocabulary_role,
            descriptor_root,
            budget=256,
        )
        store.commit(
            snapshot.revision, create=patch.create, replace=patch.replace
        )


def project_tenant_configuration_protocol(
    snapshot: Snapshot, *, prefix: str = "tenant-configuration-protocol"
) -> TenantConfigurationProtocol:
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    root_id = prefix + ":root"
    if any(root not in snapshot.cells for root in (root_id, *roles.values())):
        raise InvalidCell("tenant configuration protocol is incomplete")
    descriptors = project_content_descriptor_protocol(
        snapshot, prefix=prefix + ":release-descriptor"
    )
    members = read_relation(snapshot, root_id, budget=256)
    descriptor_members = tuple(
        member for member in members
        if member.role_id == roles["vocabulary-member"]
        and member.participant_id == descriptors.root_id
    )
    if len(descriptor_members) != 1:
        raise InvalidCell("tenant release descriptor vocabulary is not exact")
    return TenantConfigurationProtocol(
        root_id, MappingProxyType(roles), descriptors
    )


def tenant_role_roots(external_tenant_id: str) -> Mapping[str, str]:
    tenant_root = external_object_root("tenant", external_tenant_id)
    return MappingProxyType({
        name: "%s:role:%s" % (tenant_root, name)
        for name in TENANT_ROLE_NAMES
    })


def provision_tenant_identity(
    store: CellStore, *, external_tenant_id: str
) -> tuple[str, Mapping[str, str]]:
    """Create pseudonymous tenant and per-tenant role identities only."""
    tenant_root = provision_external_object(
        store, namespace="tenant", external_id=external_tenant_id
    )
    roles = tenant_role_roots(external_tenant_id)
    snapshot = store.snapshot()
    create = []
    for name, root in roles.items():
        expected = _terminal(root, name)
        existing = snapshot.cells.get(root)
        if existing is None:
            create.append(expected)
        elif existing != expected:
            raise InvalidCell("tenant role identity drifted")
    if create:
        store.commit(snapshot.revision, create=create)
    return tenant_root, roles


def _read_configuration(
    snapshot: Snapshot,
    protocol: TenantConfigurationProtocol,
    configuration_root: str,
) -> TenantConfigurationProjection:
    members = read_relation(snapshot, configuration_root, budget=128)
    allowed = {
        protocol.role(name) for name in (
            "tenant", "catalogue", "policy", "owner-role",
            "administrator-role", "member-role",
        )
    }
    if any(member.role_id not in allowed for member in members):
        raise TenantAuthorityDenied(
            "tenant configuration contains an undeclared field"
        )
    catalogue_field = _one(
        members, protocol.role("catalogue"), "catalogue"
    )
    policy_field = _one(members, protocol.role("policy"), "policy")

    def resolve_descriptor(
        field_root: str, expected_media_type: str, label: str
    ) -> tuple[str, str | None]:
        field_members = read_relation(snapshot, field_root, budget=100_000)
        descriptor_roles = {
            protocol.descriptor_protocol.role(name)
            for name in (
                "subject-id", "media-type", "digest-algorithm", "digest", "size"
            )
        }
        uses_descriptor_vocabulary = any(
            member.role_id in descriptor_roles for member in field_members
        )
        expected_prefix = configuration_root + ":descriptor:"
        if not uses_descriptor_vocabulary:
            if field_root.startswith(expected_prefix):
                raise TenantAuthorityDenied(
                    "tenant %s descriptor is incomplete" % label
                )
            return field_root, None
        try:
            descriptor = read_content_descriptor(
                snapshot, protocol.descriptor_protocol, field_root
            )
        except InvalidCell as exc:
            raise TenantAuthorityDenied(
                "tenant %s descriptor is invalid" % label
            ) from exc
        if descriptor.media_type != expected_media_type:
            raise TenantAuthorityDenied(
                "tenant %s descriptor media type drifted" % label
            )
        return descriptor.subject_root, descriptor.root_id

    catalogue_root, catalogue_descriptor = resolve_descriptor(
        catalogue_field, CATALOGUE_RELEASE_MEDIA_TYPE, "catalogue"
    )
    policy_root, policy_descriptor = resolve_descriptor(
        policy_field, POLICY_RELEASE_MEDIA_TYPE, "policy"
    )
    return TenantConfigurationProjection(
        configuration_root,
        _one(members, protocol.role("tenant"), "tenant"),
        catalogue_root,
        policy_root,
        MappingProxyType({
            "owner": _one(members, protocol.role("owner-role"), "owner role"),
            "administrator": _one(
                members,
                protocol.role("administrator-role"),
                "administrator role",
            ),
            "member": _one(members, protocol.role("member-role"), "member role"),
        }),
        catalogue_descriptor,
        policy_descriptor,
    )


def _catalogue_release_content(
    snapshot: Snapshot,
    assembly_protocol: AssemblyProtocol,
    catalogue_root: str,
) -> bytes:
    catalogue = verify_released_catalog(
        snapshot, assembly_protocol, catalogue_root
    )
    return content_identity_bytes(
        CATALOGUE_RELEASE_MEDIA_TYPE,
        catalogue.root_id,
        snapshot.cells[catalogue.version_root].atom,
        snapshot.cells[catalogue.digest_root].atom,
    )


def _policy_release_content(
    snapshot: Snapshot,
    authorization_protocol: AuthorizationProtocol,
    policy_root: str,
) -> bytes:
    policy = verify_authorization_policy(
        snapshot, authorization_protocol, policy_root
    )
    return content_identity_bytes(
        POLICY_RELEASE_MEDIA_TYPE,
        policy.root_id,
        snapshot.cells[policy.version_root].atom,
        snapshot.cells[policy.digest_root].atom,
    )


def _verify_configuration_release_descriptors(
    snapshot: Snapshot,
    tenant_protocol: TenantConfigurationProtocol,
    assembly_protocol: AssemblyProtocol,
    authorization_protocol: AuthorizationProtocol,
    configuration: TenantConfigurationProjection,
) -> None:
    catalogue_content = _catalogue_release_content(
        snapshot, assembly_protocol, configuration.catalogue_root
    )
    policy_content = _policy_release_content(
        snapshot, authorization_protocol, configuration.policy_root
    )
    if configuration.catalogue_descriptor_root is not None:
        verify_content_descriptor(
            snapshot,
            tenant_protocol.descriptor_protocol,
            configuration.catalogue_descriptor_root,
            content=catalogue_content,
            expected_subject_root=configuration.catalogue_root,
            expected_media_type=CATALOGUE_RELEASE_MEDIA_TYPE,
        )
    if configuration.policy_descriptor_root is not None:
        verify_content_descriptor(
            snapshot,
            tenant_protocol.descriptor_protocol,
            configuration.policy_descriptor_root,
            content=policy_content,
            expected_subject_root=configuration.policy_root,
            expected_media_type=POLICY_RELEASE_MEDIA_TYPE,
        )
    if (
        configuration.catalogue_descriptor_root is None
    ) != (configuration.policy_descriptor_root is None):
        raise TenantAuthorityDenied(
            "tenant release manifest is only partially described"
        )


def read_tenant_configuration(
    snapshot: Snapshot,
    protocol: TenantConfigurationProtocol,
    configuration_root: str,
) -> TenantConfigurationProjection:
    """Project one closed tenant configuration relation."""
    return _read_configuration(snapshot, protocol, configuration_root)


def _binding_digest(tenant_root: str, lifecycle_instance_root: str) -> str:
    payload = "\x00".join((
        "ArchHub/tenant-lifecycle-binding/v1",
        tenant_root,
        lifecycle_instance_root,
    )).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def read_tenant_binding(
    snapshot: Snapshot,
    protocol: TenantConfigurationProtocol,
    binding_root: str,
) -> TenantBindingProjection:
    registered = _for_role(
        read_relation(snapshot, protocol.root_id, budget=100_000),
        protocol.role("binding-member"),
    )
    if binding_root not in registered:
        raise TenantAuthorityDenied("tenant binding is not protocol-registered")
    members = read_relation(snapshot, binding_root, budget=64)
    allowed = {protocol.role(name) for name in (
        "tenant", "lifecycle-instance", "binding-digest"
    )}
    if any(member.role_id not in allowed for member in members):
        raise TenantAuthorityDenied("tenant binding contains an undeclared field")
    tenant_root = _one(members, protocol.role("tenant"), "tenant")
    instance_root = _one(
        members, protocol.role("lifecycle-instance"), "lifecycle instance"
    )
    digest_root = _one(
        members, protocol.role("binding-digest"), "binding digest"
    )
    try:
        digest = snapshot.cells[digest_root].atom.decode("ascii")
    except (KeyError, UnicodeDecodeError) as exc:
        raise TenantAuthorityDenied("tenant binding digest is invalid") from exc
    if not hmac.compare_digest(digest, _binding_digest(tenant_root, instance_root)):
        raise TenantAuthorityDenied("tenant binding digest mismatched")
    return TenantBindingProjection(
        binding_root, tenant_root, instance_root, digest
    )


def _binding_for_tenant(
    snapshot: Snapshot,
    protocol: TenantConfigurationProtocol,
    tenant_root: str,
) -> TenantBindingProjection:
    bindings = []
    for root in _for_role(
        read_relation(snapshot, protocol.root_id, budget=100_000),
        protocol.role("binding-member"),
    ):
        try:
            binding = read_tenant_binding(snapshot, protocol, root)
        except (TenantAuthorityDenied, InvalidCell, KeyError):
            continue
        if binding.tenant_root == tenant_root:
            bindings.append(binding)
    if len(bindings) != 1:
        raise TenantAuthorityDenied(
            "tenant has no unique valid lifecycle binding"
        )
    return bindings[0]


def _selection_digest(
    tenant_root: str,
    lifecycle_instance_root: str,
    selected_revision_root: str,
    actor_root: str,
    selected_at: str,
    predecessor_root: str | None,
) -> str:
    payload = "\x00".join((
        "ArchHub/tenant-release-selection/v1",
        tenant_root,
        lifecycle_instance_root,
        selected_revision_root,
        actor_root,
        selected_at,
        predecessor_root or "",
    )).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def read_tenant_release_selection(
    snapshot: Snapshot,
    tenant_protocol: TenantConfigurationProtocol,
    identity_protocol: IdentityProtocol,
    relationship_broker: RelationshipAuthorityBroker,
    selection_root: str,
    *,
    now: float | None = None,
) -> TenantReleaseSelection:
    registered = _for_role(
        read_relation(snapshot, tenant_protocol.root_id, budget=100_000),
        tenant_protocol.role("selection-member"),
    )
    if selection_root not in registered:
        raise TenantAuthorityDenied("tenant release selection is not registered")
    members = read_relation(snapshot, selection_root, budget=64)
    allowed = {tenant_protocol.role(name) for name in (
        "tenant", "lifecycle-instance", "selected-revision",
        "selection-actor", "selection-time", "selection-predecessor",
        "selection-digest",
    )}
    if any(member.role_id not in allowed for member in members):
        raise TenantAuthorityDenied(
            "tenant release selection contains an undeclared field"
        )
    tenant_root = _one(members, tenant_protocol.role("tenant"), "tenant")
    instance_root = _one(
        members,
        tenant_protocol.role("lifecycle-instance"),
        "lifecycle instance",
    )
    revision_root = _one(
        members,
        tenant_protocol.role("selected-revision"),
        "selected revision",
    )
    actor_root = _one(
        members, tenant_protocol.role("selection-actor"), "selection actor"
    )
    selected_at_root = _one(
        members, tenant_protocol.role("selection-time"), "selection time"
    )
    digest_root = _one(
        members, tenant_protocol.role("selection-digest"), "selection digest"
    )
    predecessors = _for_role(
        members, tenant_protocol.role("selection-predecessor")
    )
    if len(predecessors) > 1:
        raise TenantAuthorityDenied(
            "tenant release selection has multiple predecessors"
        )
    predecessor = predecessors[0] if predecessors else None
    try:
        selected_at_text = snapshot.cells[selected_at_root].atom.decode("ascii")
        selected_at = float(selected_at_text)
        digest = snapshot.cells[digest_root].atom.decode("ascii")
    except (KeyError, UnicodeDecodeError, ValueError) as exc:
        raise TenantAuthorityDenied(
            "tenant release selection values are invalid"
        ) from exc
    expected = _selection_digest(
        tenant_root,
        instance_root,
        revision_root,
        actor_root,
        selected_at_text,
        predecessor,
    )
    if not hmac.compare_digest(digest, expected):
        raise TenantAuthorityDenied("tenant release selection digest drifted")
    try:
        authority = verify_authority_relationship(
            snapshot,
            identity_protocol,
            relationship_broker,
            selection_root + ":authority",
            now=now,
        )
    except (RelationshipAuthorityDenied, InvalidCell, KeyError) as exc:
        raise TenantAuthorityDenied(
            "tenant release selection authority is invalid"
        ) from exc
    if (
        authority.kind_root != identity_protocol.kinds["delegation"]
        or authority.source_root != selection_root
        or authority.target_root != tenant_root
        or authority.tenant_root != tenant_root
        or authority.scope_root != revision_root
        or authority.issuer_root != actor_root
        or authority.changed_by_root != actor_root
        or revision_root not in authority.evidence_roots
    ):
        raise TenantAuthorityDenied(
            "tenant release selection authority drifted"
        )
    return TenantReleaseSelection(
        selection_root,
        tenant_root,
        instance_root,
        revision_root,
        actor_root,
        selected_at,
        predecessor,
        digest,
    )


def _current_tenant_release_selection(
    snapshot: Snapshot,
    tenant_protocol: TenantConfigurationProtocol,
    identity_protocol: IdentityProtocol,
    relationship_broker: RelationshipAuthorityBroker,
    tenant_root: str,
    *,
    now: float | None = None,
) -> TenantReleaseSelection:
    selections = []
    for root in _for_role(
        read_relation(snapshot, tenant_protocol.root_id, budget=100_000),
        tenant_protocol.role("selection-member"),
    ):
        try:
            selection = read_tenant_release_selection(
                snapshot,
                tenant_protocol,
                identity_protocol,
                relationship_broker,
                root,
                now=now,
            )
        except (TenantAuthorityDenied, InvalidCell, KeyError):
            continue
        if selection.tenant_root == tenant_root:
            selections.append(selection)
    if not selections:
        raise TenantAuthorityDenied(
            "tenant has no explicitly selected Published release"
        )
    current = selections[-1]
    if len(selections) > 1 and current.predecessor_root != selections[-2].root_id:
        raise TenantAuthorityDenied(
            "tenant release selection history is discontinuous"
        )
    return current


def current_tenant_release_selection(
    snapshot: Snapshot,
    tenant_protocol: TenantConfigurationProtocol,
    identity_protocol: IdentityProtocol,
    relationship_broker: RelationshipAuthorityBroker,
    tenant_root: str,
    *,
    now: float | None = None,
) -> TenantReleaseSelection:
    """Return the latest valid signed selection in one continuous history."""
    return _current_tenant_release_selection(
        snapshot,
        tenant_protocol,
        identity_protocol,
        relationship_broker,
        tenant_root,
        now=now,
    )


def select_published_tenant_revision(
    store: CellStore,
    tenant_protocol: TenantConfigurationProtocol,
    assembly_protocol: AssemblyProtocol,
    lifecycle_protocol: LifecycleProtocol,
    identity_protocol: IdentityProtocol,
    relationship_broker: RelationshipAuthorityBroker,
    *,
    tenant_root: str,
    revision_root: str,
    actor_root: str,
    now: float | None = None,
) -> str:
    """Sign one explicit release event; publication alone never broadcasts."""
    snapshot = store.snapshot()
    binding = _binding_for_tenant(snapshot, tenant_protocol, tenant_root)
    instance = read_lifecycle_instance(
        snapshot,
        assembly_protocol,
        lifecycle_protocol,
        binding.lifecycle_instance_root,
    )
    published_heads = state_heads(
        snapshot,
        lifecycle_protocol,
        instance.state_pointers[lifecycle_protocol.states["published"]],
    )
    if revision_root not in published_heads:
        raise TenantAuthorityDenied(
            "only a Published tenant revision can be selected"
        )
    revision = read_revision(snapshot, lifecycle_protocol, revision_root)
    configuration = _read_configuration(
        snapshot, tenant_protocol, revision.content_root
    )
    if configuration.tenant_root != tenant_root:
        raise TenantAuthorityDenied("selected revision belongs to another tenant")
    try:
        predecessor = _current_tenant_release_selection(
            snapshot,
            tenant_protocol,
            identity_protocol,
            relationship_broker,
            tenant_root,
            now=now,
        ).root_id
    except TenantAuthorityDenied as exc:
        if "no explicitly selected" not in str(exc):
            raise
        predecessor = None
    selected_at_text = "%.6f" % (time.time() if now is None else now)
    selection_root = "%s:release-selection:%s" % (
        tenant_root, uuid.uuid4().hex
    )
    selected_at_root = selection_root + ":selected-at"
    digest_root = selection_root + ":digest"
    digest = _selection_digest(
        tenant_root,
        binding.lifecycle_instance_root,
        revision_root,
        actor_root,
        selected_at_text,
        predecessor,
    )
    pairs = [
        (tenant_protocol.role("tenant"), tenant_root),
        (
            tenant_protocol.role("lifecycle-instance"),
            binding.lifecycle_instance_root,
        ),
        (tenant_protocol.role("selected-revision"), revision_root),
        (tenant_protocol.role("selection-actor"), actor_root),
        (tenant_protocol.role("selection-time"), selected_at_root),
        (tenant_protocol.role("selection-digest"), digest_root),
    ]
    if predecessor is not None:
        pairs.append((
            tenant_protocol.role("selection-predecessor"), predecessor
        ))
    relation = compose_relation_cells(pairs, relation_id=selection_root)
    patch = prepare_append_relation_member(
        snapshot,
        tenant_protocol.root_id,
        tenant_protocol.role("selection-member"),
        selection_root,
        budget=100_000,
    )
    store.commit(
        snapshot.revision,
        create=(
            _terminal(selected_at_root, selected_at_text),
            _terminal(digest_root, digest),
            *relation.cells,
            *patch.create,
        ),
        replace=patch.replace,
    )
    handle = relationship_broker.mint_from_trusted_administrator(actor_root)
    grant_authority_relationship(
        store,
        identity_protocol,
        relationship_broker,
        handle,
        relationship_id=selection_root + ":authority",
        source_root=selection_root,
        target_root=tenant_root,
        kind="delegation",
        tenant_root=tenant_root,
        scope_root=revision_root,
        administrator_root=actor_root,
        reason="select Published tenant release",
        evidence_roots=(revision_root,),
        now=now,
    )
    read_tenant_release_selection(
        store.snapshot(),
        tenant_protocol,
        identity_protocol,
        relationship_broker,
        selection_root,
        now=now,
    )
    return selection_root


def stage_tenant_authority(
    store: CellStore,
    tenant_protocol: TenantConfigurationProtocol,
    assembly_protocol: AssemblyProtocol,
    lifecycle_protocol: LifecycleProtocol,
    authorization_protocol: AuthorizationProtocol,
    *,
    external_tenant_id: str,
    catalogue_root: str,
    policy_root: str,
    versioned_asset_definition_root: str,
    actor_root: str,
) -> StagedTenantAuthority:
    """Create an inert WIP tenant configuration; no user membership yet."""
    snapshot = store.snapshot()
    verify_released_catalog(snapshot, assembly_protocol, catalogue_root)
    verify_authorization_policy(snapshot, authorization_protocol, policy_root)
    if actor_root not in snapshot.cells:
        raise InvalidCell("tenant provisioning actor is missing")
    tenant_root = external_object_root("tenant", external_tenant_id)
    if any(
        binding.tenant_root == tenant_root
        for binding in (
            read_tenant_binding(snapshot, tenant_protocol, root)
            for root in _for_role(
                read_relation(snapshot, tenant_protocol.root_id, budget=100_000),
                tenant_protocol.role("binding-member"),
            )
        )
    ):
        raise InvalidCell("tenant authority is already staged")
    _, provisioned_roles = provision_tenant_identity(
        store, external_tenant_id=external_tenant_id
    )
    role_roots = dict(provisioned_roles)
    configuration_root = "%s:configuration:%s" % (
        tenant_root, uuid.uuid4().hex
    )
    snapshot = store.snapshot()
    catalogue_descriptor = compose_content_descriptor(
        snapshot,
        tenant_protocol.descriptor_protocol,
        descriptor_id=configuration_root + ":descriptor:catalogue",
        subject_root=catalogue_root,
        media_type=CATALOGUE_RELEASE_MEDIA_TYPE,
        content=_catalogue_release_content(
            snapshot, assembly_protocol, catalogue_root
        ),
    )
    policy_descriptor = compose_content_descriptor(
        snapshot,
        tenant_protocol.descriptor_protocol,
        descriptor_id=configuration_root + ":descriptor:policy",
        subject_root=policy_root,
        media_type=POLICY_RELEASE_MEDIA_TYPE,
        content=_policy_release_content(
            snapshot, authorization_protocol, policy_root
        ),
    )
    configuration = compose_relation_cells((
        (tenant_protocol.role("tenant"), tenant_root),
        (tenant_protocol.role("catalogue"), catalogue_descriptor.root_id),
        (tenant_protocol.role("policy"), policy_descriptor.root_id),
        (tenant_protocol.role("owner-role"), role_roots["owner"]),
        (
            tenant_protocol.role("administrator-role"),
            role_roots["administrator"],
        ),
        (tenant_protocol.role("member-role"), role_roots["member"]),
    ), relation_id=configuration_root)
    store.commit(
        store.revision,
        create=(
            *catalogue_descriptor.cells,
            *policy_descriptor.cells,
            *configuration.cells,
        ),
    )
    staged_configuration = _read_configuration(
        store.snapshot(), tenant_protocol, configuration_root
    )
    _verify_configuration_release_descriptors(
        store.snapshot(),
        tenant_protocol,
        assembly_protocol,
        authorization_protocol,
        staged_configuration,
    )

    instance = instantiate_catalog_definition(
        store,
        assembly_protocol,
        catalogue_root,
        versioned_asset_definition_root,
    )
    read_lifecycle_instance(
        store.snapshot(), assembly_protocol, lifecycle_protocol, instance.root_id
    )
    wip_revision = append_wip_graph_revision(
        store,
        assembly_protocol,
        lifecycle_protocol,
        instance.root_id,
        content_root=configuration_root,
        actor_root=actor_root,
        reason="stage tenant authority configuration",
    )

    binding_root = tenant_root + ":lifecycle-binding"
    digest = _binding_digest(tenant_root, instance.root_id)
    digest_root = binding_root + ":digest"
    snapshot = store.snapshot()
    binding = compose_relation_cells((
        (tenant_protocol.role("tenant"), tenant_root),
        (tenant_protocol.role("lifecycle-instance"), instance.root_id),
        (tenant_protocol.role("binding-digest"), digest_root),
    ), relation_id=binding_root)
    patch = prepare_append_relation_member(
        snapshot,
        tenant_protocol.root_id,
        tenant_protocol.role("binding-member"),
        binding_root,
        budget=100_000,
    )
    store.commit(
        snapshot.revision,
        create=(
            _terminal(digest_root, digest),
            *binding.cells,
            *patch.create,
        ),
        replace=patch.replace,
    )
    read_tenant_binding(store.snapshot(), tenant_protocol, binding_root)
    return StagedTenantAuthority(
        tenant_root,
        MappingProxyType(role_roots),
        configuration_root,
        instance.root_id,
        binding_root,
        wip_revision,
    )


def append_tenant_authority_revision(
    store: CellStore,
    tenant_protocol: TenantConfigurationProtocol,
    assembly_protocol: AssemblyProtocol,
    lifecycle_protocol: LifecycleProtocol,
    authorization_protocol: AuthorizationProtocol,
    *,
    tenant_root: str,
    base_configuration_root: str,
    catalogue_root: str,
    policy_root: str,
    actor_root: str,
    reason: str = "revise tenant authority configuration",
) -> tuple[str, str]:
    """Append an inert WIP configuration without rewriting tenant history."""
    snapshot = store.snapshot()
    verify_released_catalog(snapshot, assembly_protocol, catalogue_root)
    verify_authorization_policy(snapshot, authorization_protocol, policy_root)
    if actor_root not in snapshot.cells:
        raise InvalidCell("tenant configuration actor is missing")
    binding = _binding_for_tenant(snapshot, tenant_protocol, tenant_root)
    base = _read_configuration(
        snapshot, tenant_protocol, base_configuration_root
    )
    if base.tenant_root != tenant_root:
        raise TenantAuthorityDenied(
            "tenant configuration base belongs to another tenant"
        )
    configuration_root = "%s:configuration:%s" % (
        tenant_root, uuid.uuid4().hex
    )
    catalogue_descriptor = compose_content_descriptor(
        snapshot,
        tenant_protocol.descriptor_protocol,
        descriptor_id=configuration_root + ":descriptor:catalogue",
        subject_root=catalogue_root,
        media_type=CATALOGUE_RELEASE_MEDIA_TYPE,
        content=_catalogue_release_content(
            snapshot, assembly_protocol, catalogue_root
        ),
    )
    policy_descriptor = compose_content_descriptor(
        snapshot,
        tenant_protocol.descriptor_protocol,
        descriptor_id=configuration_root + ":descriptor:policy",
        subject_root=policy_root,
        media_type=POLICY_RELEASE_MEDIA_TYPE,
        content=_policy_release_content(
            snapshot, authorization_protocol, policy_root
        ),
    )
    configuration = compose_relation_cells((
        (tenant_protocol.role("tenant"), tenant_root),
        (tenant_protocol.role("catalogue"), catalogue_descriptor.root_id),
        (tenant_protocol.role("policy"), policy_descriptor.root_id),
        (tenant_protocol.role("owner-role"), base.role_roots["owner"]),
        (
            tenant_protocol.role("administrator-role"),
            base.role_roots["administrator"],
        ),
        (tenant_protocol.role("member-role"), base.role_roots["member"]),
    ), relation_id=configuration_root)
    store.commit(
        snapshot.revision,
        create=(
            *catalogue_descriptor.cells,
            *policy_descriptor.cells,
            *configuration.cells,
        ),
    )
    revised_configuration = _read_configuration(
        store.snapshot(), tenant_protocol, configuration_root
    )
    _verify_configuration_release_descriptors(
        store.snapshot(),
        tenant_protocol,
        assembly_protocol,
        authorization_protocol,
        revised_configuration,
    )
    revision_root = append_wip_graph_revision(
        store,
        assembly_protocol,
        lifecycle_protocol,
        binding.lifecycle_instance_root,
        content_root=configuration_root,
        actor_root=actor_root,
        reason=reason,
    )
    return configuration_root, revision_root


def published_tenant_authority(
    snapshot: Snapshot,
    tenant_protocol: TenantConfigurationProtocol,
    assembly_protocol: AssemblyProtocol,
    lifecycle_protocol: LifecycleProtocol,
    authorization_protocol: AuthorizationProtocol,
    identity_protocol: IdentityProtocol,
    relationship_broker: RelationshipAuthorityBroker,
    *,
    tenant_root: str,
    now: float | None = None,
) -> PublishedTenantAuthority:
    binding = _binding_for_tenant(snapshot, tenant_protocol, tenant_root)
    instance = read_lifecycle_instance(
        snapshot,
        assembly_protocol,
        lifecycle_protocol,
        binding.lifecycle_instance_root,
    )
    heads = state_heads(
        snapshot,
        lifecycle_protocol,
        instance.state_pointers[lifecycle_protocol.states["published"]],
    )
    selection = _current_tenant_release_selection(
        snapshot,
        tenant_protocol,
        identity_protocol,
        relationship_broker,
        tenant_root,
        now=now,
    )
    if (
        selection.lifecycle_instance_root != binding.lifecycle_instance_root
        or selection.selected_revision_root not in heads
    ):
        raise TenantAuthorityDenied(
            "tenant selected release is not an active Published revision"
        )
    revision = read_revision(
        snapshot, lifecycle_protocol, selection.selected_revision_root
    )
    configuration = _read_configuration(
        snapshot, tenant_protocol, revision.content_root
    )
    if configuration.tenant_root != tenant_root:
        raise TenantAuthorityDenied("published tenant configuration identity drifted")
    _verify_configuration_release_descriptors(
        snapshot,
        tenant_protocol,
        assembly_protocol,
        authorization_protocol,
        configuration,
    )
    return PublishedTenantAuthority(
        tenant_root,
        configuration.role_roots,
        configuration.root_id,
        binding.lifecycle_instance_root,
        revision.root_id,
        configuration.catalogue_root,
        configuration.policy_root,
        configuration.catalogue_descriptor_root,
        configuration.policy_descriptor_root,
    )


def activate_published_tenant_roles(
    store: CellStore,
    tenant_protocol: TenantConfigurationProtocol,
    assembly_protocol: AssemblyProtocol,
    lifecycle_protocol: LifecycleProtocol,
    authorization_protocol: AuthorizationProtocol,
    identity_protocol: IdentityProtocol,
    relationship_broker: RelationshipAuthorityBroker,
    *,
    tenant_root: str,
    owner_subject_root: str,
    founder_administrator_root: str,
    now: float | None = None,
) -> tuple[str, ...]:
    """Activate role wires only for one court-published tenant configuration."""
    published = published_tenant_authority(
        store.snapshot(),
        tenant_protocol,
        assembly_protocol,
        lifecycle_protocol,
        authorization_protocol,
        identity_protocol,
        relationship_broker,
        tenant_root=tenant_root,
        now=now,
    )
    snapshot = store.snapshot()
    if any(root not in snapshot.cells for root in (
        owner_subject_root, founder_administrator_root
    )):
        raise InvalidCell("tenant owner or founder authority is missing")
    role_roots = set(published.role_roots.values())
    stale_role_relationships = []
    for member in read_relation(
        snapshot, identity_protocol.root_id, budget=100_000
    ):
        if member.role_id != identity_protocol.roles["relationship-member"]:
            continue
        try:
            relationship = verify_authority_relationship(
                snapshot,
                identity_protocol,
                relationship_broker,
                member.participant_id,
                now=now,
            )
        except (RelationshipAuthorityDenied, InvalidCell, KeyError):
            continue
        if (
            relationship.kind_root == identity_protocol.kinds["membership"]
            and relationship.source_root in role_roots
            and relationship.target_root == tenant_root
            and relationship.tenant_root == tenant_root
            and published.published_revision_root
            not in relationship.evidence_roots
        ):
            stale_role_relationships.append(relationship.root_id)
    for relationship_root in stale_role_relationships:
        handle = relationship_broker.mint_from_trusted_administrator(
            founder_administrator_root
        )
        revoke_authority_relationship(
            store,
            identity_protocol,
            relationship_broker,
            handle,
            relationship_root,
            administrator_root=founder_administrator_root,
            reason="superseded by Published tenant configuration",
            now=now,
        )

    release_tag = hashlib.sha256(
        published.published_revision_root.encode("utf-8")
    ).hexdigest()[:20]
    specifications = [
        (
            "%s:membership:role:%s:release:%s" % (
                tenant_root, name, release_tag
            ),
            role_root,
            tenant_root,
            "activate tenant %s role" % name,
            True,
        )
        for name, role_root in published.role_roots.items()
    ]
    specifications.append((
        "%s:membership:owner:%s" % (tenant_root, owner_subject_root),
        owner_subject_root,
        published.role_roots["owner"],
        "assign initial tenant owner",
        False,
    ))
    roots = []
    for (
        relationship_id, source_root, target_root, reason, release_bound
    ) in specifications:
        if relationship_id in store.snapshot().cells:
            relationship = verify_authority_relationship(
                store.snapshot(),
                identity_protocol,
                relationship_broker,
                relationship_id,
                now=now,
            )
            if (
                relationship.source_root != source_root
                or relationship.target_root != target_root
                or relationship.tenant_root != tenant_root
                or relationship.kind_root
                != identity_protocol.kinds["membership"]
                or (
                    release_bound
                    and published.published_revision_root
                    not in relationship.evidence_roots
                )
            ):
                raise TenantAuthorityDenied(
                    "existing tenant role relationship has drifted"
                )
            roots.append(relationship_id)
            continue
        handle = relationship_broker.mint_from_trusted_administrator(
            founder_administrator_root
        )
        roots.append(grant_authority_relationship(
            store,
            identity_protocol,
            relationship_broker,
            handle,
            relationship_id=relationship_id,
            source_root=source_root,
            target_root=target_root,
            kind="membership",
            tenant_root=tenant_root,
            administrator_root=founder_administrator_root,
            reason=reason,
            evidence_roots=(published.published_revision_root,),
            now=now,
        ))
    return tuple(roots)


__all__ = [
    "PublishedTenantAuthority",
    "PublishedTenantAdmissionVerifier",
    "StagedTenantAuthority",
    "TenantAuthorityDenied",
    "TenantBindingProjection",
    "TenantConfigurationProjection",
    "TenantConfigurationProtocol",
    "TenantReleaseSelection",
    "activate_published_tenant_roles",
    "bootstrap_tenant_configuration_protocol",
    "current_tenant_release_selection",
    "ensure_tenant_release_descriptor_protocol",
    "project_tenant_configuration_protocol",
    "provision_tenant_identity",
    "published_tenant_authority",
    "append_tenant_authority_revision",
    "read_tenant_configuration",
    "read_tenant_binding",
    "read_tenant_release_selection",
    "select_published_tenant_revision",
    "stage_tenant_authority",
    "tenant_role_roots",
]
