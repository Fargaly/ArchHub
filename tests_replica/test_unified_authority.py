from __future__ import annotations

import base64
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import inspect
import json
import uuid

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from nodelang.cell_secret_keys import MemorySigningKeyProvider
import nodelang.unified_authority as unified_authority_module
from nodelang.unified_authority import (
    AuthorizationDenied,
    BootstrapManifest,
    _append_relation_member,
    _commit_signed_change,
    _command_projection,
    _find_receipt,
    _matching_policy_proofs,
    _read_logic_proof,
    _receipt_projection,
    audit_authority_history,
    composition_root as _composition_root,
    create_relation_node,
    create_unified_authority,
    declare_definition,
    enroll_session,
    instantiate_definition,
    open_unified_authority,
    promote_definition,
    reachable_roots,
    read_definition as _read_definition,
    read_contained_scope as _read_contained_scope,
    read_instance as _read_instance,
    read_relation_node as _read_relation_node,
    relation_members,
    revoke_session,
    revise_instance,
    revise_definition,
    sign_bootstrap_manifest,
    validate_composition,
)
from nodelang.universal_cell import (
    NULL_CELL_ID,
    Cell,
    CellStore,
    InvalidCell,
    overlay_read_snapshot,
)


SECRET = b"archhub-clean-bootstrap-test-key" + b"0" * 8
CALLER_PRIVATE = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
CALLER_PUBLIC = CALLER_PRIVATE.public_key().public_bytes(
    serialization.Encoding.Raw,
    serialization.PublicFormat.Raw,
)
COMMAND_NAMESPACE = uuid.UUID("7f4d3e58-3c91-4a5c-8d4a-e84f870de5dc")
COMPOSITIONS = (
    "Brain",
    "Grand Map",
    "Workshop",
    "Governance",
    "Agent Sessions",
    "Projects",
    "Interface",
)


def _provider() -> MemorySigningKeyProvider:
    return MemorySigningKeyProvider("clean-bootstrap", SECRET)


def _authority(store: CellStore | None = None):
    target = store or CellStore()
    return create_unified_authority(
        target,
        _provider(),
        key_id="clean-bootstrap",
        application_label="ArchHub",
        principal_label="Founder",
        bootstrap_session_label="Clean rebuild session",
        bootstrap_session_public_key=CALLER_PUBLIC,
        composition_labels=COMPOSITIONS,
    )


class _Caller:
    def __init__(self, authority):
        self.actor_root = authority.manifest.principal_root
        self.session_root = authority.manifest.bootstrap_session_root
        self.public_key = CALLER_PUBLIC

    def sign(self, payload: bytes) -> bytes:
        return CALLER_PRIVATE.sign(payload)


class _KeyedCaller:
    def __init__(self, authority, session_root, private_key):
        self.actor_root = authority.manifest.principal_root
        self.session_root = session_root
        self.public_key = private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        self._private_key = private_key

    def sign(self, payload: bytes) -> bytes:
        return self._private_key.sign(payload)

    def __reduce_ex__(self, protocol):
        raise TypeError("caller capabilities cannot be serialized")


def composition_root(authority, label):
    return _composition_root(authority, label, caller=_Caller(authority))


def read_definition(authority, definition_root):
    return _read_definition(
        authority, definition_root, caller=_Caller(authority)
    )


def read_instance(authority, instance_root, *, scope_root=None):
    selected_scope = scope_root or composition_root(authority, "Projects")
    return _read_instance(
        authority,
        instance_root,
        scope_root=selected_scope,
        caller=_Caller(authority),
    )


def read_contained_scope(authority, container_root, *, scope_root, at_revision=None):
    return _read_contained_scope(
        authority,
        container_root,
        scope_root=scope_root,
        caller=_Caller(authority),
        at_revision=at_revision,
    )


def read_relation_node(authority, relation_root, *, scope_root=None):
    selected_scope = scope_root or composition_root(authority, "Projects")
    return _read_relation_node(
        authority,
        relation_root,
        scope_root=selected_scope,
        caller=_Caller(authority),
    )


class _CountingProvider(MemorySigningKeyProvider):
    def __init__(self):
        super().__init__("clean-bootstrap", SECRET)
        self.sign_count = 0

    def sign(self, key_id: str, version: int, payload: bytes) -> str:
        self.sign_count += 1
        return super().sign(key_id, version, payload)

    def verify(
        self, key_id: str, version: int, payload: bytes, signature: str
    ) -> bool:
        before = self.sign_count
        try:
            return super().verify(key_id, version, payload, signature)
        finally:
            self.sign_count = before


def _command(authority, command_id: str) -> dict[str, object]:
    return {
        "caller": _Caller(authority),
        "command_id": str(uuid.uuid5(COMMAND_NAMESPACE, command_id)),
    }


def _publish(authority, result, command_prefix: str):
    base_version = read_definition(authority, result.root_id).version
    shared = promote_definition(
        authority,
        result.root_id,
        target_lifecycle="shared",
        version=base_version + "-shared",
        evidence_roots=(result.receipt_root,),
        **_command(authority, command_prefix + "-share"),
    )
    return promote_definition(
        authority,
        result.root_id,
        target_lifecycle="published",
        version=base_version + "-published",
        evidence_roots=(shared.receipt_root,),
        **_command(authority, command_prefix + "-publish"),
    )


def _disable_policy_decision(authority):
    snapshot = authority.store.snapshot()
    decision_predicate = next(
        member.participant_id
        for member in relation_members(snapshot, authority.manifest.policy_root)
        if member.role_id == authority.role("predicate")
    )
    decision_rule = next(
        member.participant_id
        for member in relation_members(snapshot, authority.manifest.policy_root)
        if member.role_id == authority.role("rule")
        and next(
            head.participant_id
            for head in relation_members(snapshot, member.participant_id)
            if head.role_id == authority.role("head")
        )
        and next(
            predicate.participant_id
            for predicate in relation_members(
                snapshot,
                next(
                    head.participant_id
                    for head in relation_members(snapshot, member.participant_id)
                    if head.role_id == authority.role("head")
                ),
            )
            if predicate.role_id == authority.role("predicate")
        ) == decision_predicate
    )
    head_root = next(
        member.participant_id
        for member in relation_members(snapshot, decision_rule)
        if member.role_id == authority.role("head")
    )
    predicate_member = next(
        member
        for member in relation_members(snapshot, head_root)
        if member.role_id == authority.role("predicate")
    )
    incidence = snapshot.cells[predicate_member.incidence_id]
    _commit_signed_change(
        authority,
        snapshot,
        create=(),
        replace_cells=(replace(
            incidence,
            link1=authority.logic_protocol().bound_predicate,
        ),),
    )


def test_signed_bootstrap_uses_one_root_and_only_opaque_identities():
    authority = _authority()
    manifest = authority.manifest
    roots = (
        manifest.graph_id,
        manifest.application_root,
        manifest.protocol_root,
        manifest.policy_root,
        manifest.catalogue_root,
        manifest.constitution_root,
        manifest.history_root,
        manifest.principal_root,
        manifest.bootstrap_session_root,
        *(composition_root(authority, label) for label in COMPOSITIONS),
    )

    assert all(str(uuid.UUID(root)) == root for root in roots)
    assert len(set(roots)) == len(roots) - 1
    assert all(
        cell_id == "00000000-0000-0000-0000-000000000000"
        or str(uuid.UUID(cell_id)) == cell_id
        for cell_id in authority.store.snapshot().cells
    )
    assert manifest.graph_id == manifest.application_root
    assert set(roots) <= reachable_roots(
        authority.store.snapshot(), manifest.graph_id
    )
    assert BootstrapManifest.from_json(manifest.to_json()) == manifest


def test_every_bootstrap_composition_is_governed_by_a_graph_held_protocol():
    authority = _authority()
    snapshot = authority.store.snapshot()
    roots = (
        authority.manifest.graph_id,
        authority.manifest.protocol_root,
        authority.manifest.policy_root,
        authority.manifest.catalogue_root,
        authority.manifest.constitution_root,
        authority.manifest.history_root,
        authority.manifest.principal_root,
        authority.manifest.bootstrap_session_root,
        *(composition_root(authority, label) for label in COMPOSITIONS),
    )

    for root in roots:
        projection = validate_composition(authority, snapshot, root)
        assert projection.root_id == root
        assert projection.protocol_root in reachable_roots(
            snapshot, authority.manifest.protocol_root
        )


def test_current_signed_head_rejects_post_bootstrap_policy_tampering():
    authority = _authority()
    snapshot = authority.store.snapshot()
    label_value = next(
        member.participant_id
        for member in relation_members(snapshot, authority.manifest.policy_root)
        if member.role_id == authority.role("label")
    )
    payload = next(
        member.participant_id
        for member in relation_members(snapshot, label_value)
        if member.role_id == authority.role("payload")
    )
    cell = snapshot.cells[payload]
    authority.store.commit(
        snapshot.revision,
        replace=(Cell(cell.id, cell.link0, cell.link1, b'"Changed policy"'),),
    )

    with pytest.raises(InvalidCell, match="current authority head"):
        open_unified_authority(authority.store, authority.manifest, _provider())


def test_semantic_reader_rejects_a_signed_definition_with_the_wrong_protocol():
    authority = _authority()
    declared = declare_definition(
        authority,
        "Protocol court",
        {},
        version="1",
        **_command(authority, "protocol-court-declare"),
    )
    snapshot = authority.store.snapshot()
    conformance = next(
        member
        for member in relation_members(snapshot, declared.root_id)
        if member.role_id == authority.role("conforms-to")
    )
    incidence = snapshot.cells[conformance.incidence_id]
    _commit_signed_change(
        authority,
        snapshot,
        create=(),
        replace_cells=(
            Cell(
                incidence.id,
                incidence.link0,
                authority.shape("receipt"),
                incidence.atom,
            ),
        ),
    )

    with pytest.raises(
        InvalidCell,
        match="wrong structural protocol|role outside its protocol",
    ):
        read_definition(authority, declared.root_id)


def test_explicit_history_audit_verifies_every_signed_parent_head(monkeypatch):
    authority = _authority()
    declared = declare_definition(
        authority,
        "Ancestry court",
        {},
        version="1",
        **_command(authority, "ancestry-court-declare"),
    )
    revise_definition(
        authority,
        declared.root_id,
        "Ancestry court",
        {"revision": 2},
        version="2",
        **_command(authority, "ancestry-court-revise"),
    )
    parent_snapshot = authority.store.at(2)
    parent_head = next(
        member.participant_id
        for member in relation_members(
            parent_snapshot, authority.manifest.head_index_root
        )
        if member.role_id == authority.role("current-head")
    )
    signature_value = next(
        member.participant_id
        for member in relation_members(parent_snapshot, parent_head)
        if member.role_id == authority.role("signature")
    )
    signature_payload = next(
        member.participant_id
        for member in relation_members(parent_snapshot, signature_value)
        if member.role_id == authority.role("payload")
    )
    signature_cell = parent_snapshot.cells[signature_payload]
    tampered_parent = overlay_read_snapshot(
        parent_snapshot,
        replace=(
            Cell(
                signature_cell.id,
                signature_cell.link0,
                signature_cell.link1,
                json.dumps("0" * 64).encode("utf-8"),
            ),
        ),
    )
    original_at = CellStore.at

    def altered_history(store, revision):
        if store is authority.store and revision == parent_snapshot.revision:
            return tampered_parent
        return original_at(store, revision)

    monkeypatch.setattr(CellStore, "at", altered_history)

    with pytest.raises(InvalidCell, match="parent digest|signature"):
        audit_authority_history(authority)


def test_live_read_verifies_one_exact_head_without_rewalking_history(monkeypatch):
    authority = _authority()
    declared = None
    for index in range(5):
        declared = declare_definition(
            authority,
            "Bounded live verification %s" % index,
            {},
            version="1",
            **_command(authority, "bounded-live-verification-%s" % index),
        )
    assert declared is not None
    verified_revisions: list[int] = []
    original = unified_authority_module._verify_authority_head

    def counted(authority_value, snapshot, head_root):
        verified_revisions.append(snapshot.revision)
        return original(authority_value, snapshot, head_root)

    monkeypatch.setattr(
        unified_authority_module,
        "_verify_authority_head",
        counted,
    )
    read_definition(authority, declared.root_id)

    assert verified_revisions == [authority.store.revision]


def test_bootstrap_rejects_signature_or_snapshot_substitution():
    authority = _authority()
    manifest = authority.manifest

    with pytest.raises(InvalidCell, match="graph identity|signature"):
        open_unified_authority(
            authority.store,
            replace(manifest, application_root=str(uuid.uuid4())),
            _provider(),
        )
    foreign = MemorySigningKeyProvider("clean-bootstrap", b"z" * 32)
    with pytest.raises(InvalidCell, match="fingerprint"):
        open_unified_authority(authority.store, manifest, foreign)
    with pytest.raises(InvalidCell, match="snapshot digest"):
        changed = replace(manifest, accepted_snapshot_digest="f" * 64)
        open_unified_authority(
            authority.store,
            sign_bootstrap_manifest(changed, _provider()),
            _provider(),
        )


def test_definition_identity_stays_stable_while_revision_and_digest_change():
    authority = _authority()
    first = declare_definition(
        authority,
        "Project",
        {"status": "WIP", "color": "#444444"},
        version="1",
        parameters={"status": {"editor": "choice"}},
        interfaces={"project": {"direction": "both"}},
        rules={"promotion": "requires-court"},
        presentation={"shape": "compact"},
        courts={"restart": "required"},
        provenance={"source": "founder"},
        **_command(authority, "declare-project"),
    )
    before = read_definition(authority, first.root_id)

    second = revise_definition(
        authority,
        first.root_id,
        "Project",
        {"status": "WIP", "color": "#222222"},
        version="2",
        parameters={"status": {"editor": "choice"}},
        interfaces={"project": {"direction": "both"}},
        rules={"promotion": "requires-court"},
        presentation={"shape": "compact"},
        courts={"restart": "required"},
        provenance={"source": "founder"},
        **_command(authority, "revise-project-v2"),
    )
    after = read_definition(authority, first.root_id)

    assert second.root_id == first.root_id
    assert before.root_id == after.root_id
    assert before.revision_root != after.revision_root
    assert before.content_digest != after.content_digest
    assert before.content_digest not in before.root_id
    assert set(after.contracts) == {
        "defaults",
        "parameters",
        "interfaces",
        "rules",
        "presentation",
        "courts",
        "provenance",
    }


def test_definition_read_reconstructs_and_enforces_the_recorded_digest():
    authority = _authority()
    result = declare_definition(
        authority,
        "Project",
        {"status": "WIP"},
        **_command(authority, "declare-project"),
    )
    definition = read_definition(authority, result.root_id)
    snapshot = authority.store.snapshot()
    defaults_root = next(
        member.participant_id
        for member in relation_members(snapshot, definition.revision_root)
        if member.role_id == authority.role("defaults")
    )
    property_root = next(
        member.participant_id
        for member in relation_members(snapshot, defaults_root)
        if member.role_id == authority.role("property")
    )
    value_root = next(
        member.participant_id
        for member in relation_members(snapshot, property_root)
        if member.role_id == authority.role("value")
    )
    payload = snapshot.cells[value_root]
    assert payload.link0 == NULL_CELL_ID
    assert payload.link1 == NULL_CELL_ID
    authority.store.commit(
        snapshot.revision,
        replace=(Cell(payload.id, payload.link0, payload.link1, b'"PUBLISHED"'),),
    )

    with pytest.raises(InvalidCell, match="current authority head|content digest"):
        read_definition(authority, result.root_id)


def test_compound_contract_data_is_openable_graph_structure_not_json_blobs():
    authority = _authority()
    result = declare_definition(
        authority,
        "Project",
        {
            "identity": {
                "code": "BBC4",
                "tags": ["architecture", "delivery"],
            },
            "enabled": True,
        },
        parameters={
            "status": {
                "editor": "choice",
                "options": ["WIP", "Shared", "Published"],
            }
        },
        **_command(authority, "declare-openable-project"),
    )

    definition = read_definition(authority, result.root_id)
    assert definition.contracts["defaults"] == {
        "enabled": True,
        "identity": {
            "code": "BBC4",
            "tags": ["architecture", "delivery"],
        },
    }
    assert definition.contracts["parameters"] == {
        "status": {
            "editor": "choice",
            "options": ["WIP", "Shared", "Published"],
        }
    }

    snapshot = authority.store.snapshot()
    value_payloads = tuple(
        snapshot.cells[cell.link1].atom
        for cell in snapshot.cells.values()
        if cell.link0 == authority.role("payload")
    )
    for payload in value_payloads:
        decoded = json.loads(payload.decode("utf-8"))
        assert type(decoded) not in {dict, list}

    revision = read_definition(authority, result.root_id).revision_root
    defaults_root = next(
        member.participant_id
        for member in relation_members(snapshot, revision)
        if member.role_id == authority.role("defaults")
    )
    property_roots = tuple(
        member.participant_id
        for member in relation_members(snapshot, defaults_root)
        if member.role_id == authority.role("property")
    )
    top_property = next(
        root
        for root in property_roots
        if json.loads(snapshot.cells[next(
            member.participant_id
            for member in relation_members(snapshot, root)
            if member.role_id == authority.role("name")
        )].atom.decode("utf-8")) == "identity"
    )
    property_projection = validate_composition(authority, snapshot, top_property)
    assert property_projection.protocol_root == authority.shape("property")
    assert {
        member.role_id for member in property_projection.members
    } >= {
        authority.role("conforms-to"),
        authority.role("owner"),
        authority.role("name"),
        authority.role("value"),
    }
    assert not {
        authority.role("constraints"),
        authority.role("editor"),
        authority.role("authority"),
        authority.role("lifecycle"),
        authority.role("history"),
    } & {member.role_id for member in property_projection.members}
    owner = next(
        member.participant_id
        for member in property_projection.members
        if member.role_id == authority.role("owner")
    )
    assert owner == defaults_root
    name_root = next(
        member.participant_id
        for member in property_projection.members
        if member.role_id == authority.role("name")
    )
    assert snapshot.cells[name_root].link0 == NULL_CELL_ID
    assert snapshot.cells[name_root].link1 == NULL_CELL_ID
    assert snapshot.cells[name_root].atom
    nested_root = next(
        member.participant_id
        for member in property_projection.members
        if member.role_id == authority.role("value")
    )
    assert validate_composition(
        authority, snapshot, nested_root
    ).protocol_root == authority.shape("map")


def test_instances_share_exact_definition_revision_and_store_only_overrides():
    authority = _authority()
    definition = declare_definition(
        authority,
        "Project",
        {"title": "Untitled", "status": "WIP", "color": "#444444"},
        parameters={"title": {"editor": "text"}},
        **_command(authority, "declare-project"),
    )
    definition = _publish(authority, definition, "project-instance")
    result = instantiate_definition(
        authority,
        definition.root_id,
        {"title": "BBC4"},
        scope_root=composition_root(authority, "Projects"),
        **_command(authority, "create-project-bbc4"),
    )
    projection = read_instance(authority, result.root_id)
    current = read_definition(authority, definition.root_id)

    assert projection["definition"] == definition.root_id
    assert projection["definition_revision"] == current.revision_root
    assert dict(projection["values"]) == {
        "color": "#444444",
        "status": "WIP",
        "title": "BBC4",
    }
    instance_members = relation_members(authority.store.snapshot(), result.root_id)
    override_count = sum(
        member.role_id == authority.role("override") for member in instance_members
    )
    assert override_count == 1
    assert result.created_cell_count <= 64


def test_instance_cannot_override_an_undeclared_mutable_region():
    authority = _authority()
    definition = declare_definition(
        authority,
        "Project",
        {"title": "Untitled", "protected_code": "BBC4"},
        parameters={"title": {"editor": "text"}},
        **_command(authority, "declare-protected-project"),
    )
    definition = _publish(authority, definition, "protected-project")

    with pytest.raises(InvalidCell, match="undeclared mutable parameter"):
        instantiate_definition(
            authority,
            definition.root_id,
            {"protected_code": "CHANGED"},
            scope_root=composition_root(authority, "Projects"),
            **_command(authority, "override-protected-project-code"),
        )


def test_instance_override_obeys_graph_declared_type_options_and_range():
    authority = _authority()
    definition = declare_definition(
        authority,
        "Controlled parameter",
        {"status": "WIP", "priority": 1},
        parameters={
            "status": {
                "type": "text",
                "options": ["WIP", "Ready"],
                "editor": "choice",
            },
            "priority": {
                "type": "integer",
                "minimum": 1,
                "maximum": 5,
                "editor": "stepper",
            },
        },
        **_command(authority, "declare-controlled-parameter"),
    )
    definition = _publish(authority, definition, "controlled-parameter")
    scope = composition_root(authority, "Projects")
    with pytest.raises(InvalidCell, match="declared options"):
        instantiate_definition(
            authority,
            definition.root_id,
            {"status": "invented"},
            scope_root=scope,
            **_command(authority, "invalid-status-option"),
        )
    with pytest.raises(InvalidCell, match="declared maximum"):
        instantiate_definition(
            authority,
            definition.root_id,
            {"priority": 6},
            scope_root=scope,
            **_command(authority, "invalid-priority-range"),
        )
    accepted = instantiate_definition(
        authority,
        definition.root_id,
        {"status": "Ready", "priority": 5},
        scope_root=scope,
        **_command(authority, "valid-controlled-values"),
    )
    assert read_instance(authority, accepted.root_id)["values"] == {
        "priority": 5,
        "status": "Ready",
    }


def test_instance_override_obeys_graph_declared_text_length():
    authority = _authority()
    definition = declare_definition(
        authority,
        "Bounded text",
        {"body": "draft"},
        parameters={
            "body": {
                "type": "text",
                "minimum_length": 1,
                "maximum_length": 12,
                "editor": "multiline",
            },
        },
        **_command(authority, "declare-bounded-text"),
    )
    definition = _publish(authority, definition, "bounded-text")
    scope = composition_root(authority, "Projects")
    with pytest.raises(InvalidCell, match="minimum length"):
        instantiate_definition(
            authority,
            definition.root_id,
            {"body": ""},
            scope_root=scope,
            **_command(authority, "empty-bounded-text"),
        )
    with pytest.raises(InvalidCell, match="maximum length"):
        instantiate_definition(
            authority,
            definition.root_id,
            {"body": "more than twelve"},
            scope_root=scope,
            **_command(authority, "long-bounded-text"),
        )
    accepted = instantiate_definition(
        authority,
        definition.root_id,
        {"body": "hello"},
        scope_root=scope,
        **_command(authority, "valid-bounded-text"),
    )
    assert read_instance(authority, accepted.root_id)["values"]["body"] == "hello"


def test_definition_requires_evidenced_wip_shared_published_promotion():
    authority = _authority()
    with pytest.raises(InvalidCell, match="must start in WIP"):
        declare_definition(
            authority,
            "Bypassed release",
            lifecycle="published",
            **_command(authority, "declare-bypassed-release"),
        )
    draft = declare_definition(
        authority,
        "Project",
        {"title": "Untitled"},
        parameters={"title": {"editor": "text"}},
        **_command(authority, "declare-lifecycle-project"),
    )
    assert read_definition(authority, draft.root_id).lifecycle == "wip"
    with pytest.raises(InvalidCell, match="published definition"):
        instantiate_definition(
            authority,
            draft.root_id,
            {"title": "BBC4"},
            scope_root=composition_root(authority, "Projects"),
            **_command(authority, "instantiate-draft-project"),
        )
    with pytest.raises(InvalidCell, match="requires exact graph evidence"):
        promote_definition(
            authority,
            draft.root_id,
            target_lifecycle="shared",
            version="1-shared",
            evidence_roots=(),
            **_command(authority, "share-project-without-evidence"),
        )

    shared = promote_definition(
        authority,
        draft.root_id,
        target_lifecycle="shared",
        version="1-shared",
        evidence_roots=(draft.receipt_root,),
        **_command(authority, "share-lifecycle-project"),
    )
    shared_projection = read_definition(authority, draft.root_id)
    assert shared_projection.lifecycle == "shared"
    assert shared_projection.evidence_roots == (draft.receipt_root,)
    shared_again = promote_definition(
        authority,
        draft.root_id,
        target_lifecycle="shared",
        version="1-shared",
        evidence_roots=(draft.receipt_root,),
        **_command(authority, "share-lifecycle-project"),
    )
    assert shared_again.replayed is True
    assert shared_again.revision == shared.revision
    published = promote_definition(
        authority,
        draft.root_id,
        target_lifecycle="published",
        version="1-published",
        evidence_roots=(shared.receipt_root,),
        **_command(authority, "publish-lifecycle-project"),
    )
    published_projection = read_definition(authority, draft.root_id)
    assert published_projection.lifecycle == "published"
    assert published_projection.evidence_roots == (shared.receipt_root,)
    instance = instantiate_definition(
        authority,
        draft.root_id,
        {"title": "BBC4"},
        scope_root=composition_root(authority, "Projects"),
        **_command(authority, "instantiate-published-project"),
    )
    assert instance.root_id != published.root_id


def test_promotion_verifies_an_earlier_receipts_exact_signed_head():
    authority = _authority()
    draft = declare_definition(
        authority,
        "Project",
        {"title": "Untitled"},
        parameters={"title": {"editor": "text"}},
        **_command(authority, "declare-historical-evidence-project"),
    )
    declare_definition(
        authority,
        "Intervening definition",
        {},
        **_command(authority, "declare-intervening-definition"),
    )

    shared = promote_definition(
        authority,
        draft.root_id,
        target_lifecycle="shared",
        version="1-shared",
        evidence_roots=(draft.receipt_root,),
        **_command(authority, "share-with-historical-evidence"),
    )

    assert read_definition(authority, shared.root_id).lifecycle == "shared"


def test_instance_is_an_openable_composition_scope_at_every_scale():
    authority = _authority()
    domain_definition = declare_definition(
        authority,
        "Domain",
        {"title": "Untitled domain"},
        parameters={"title": {"editor": "text"}},
        **_command(authority, "declare-domain-assembly"),
    )
    domain_definition = _publish(authority, domain_definition, "domain-assembly")
    domain = instantiate_definition(
        authority,
        domain_definition.root_id,
        {"title": "Brain and Memory"},
        scope_root=composition_root(authority, "Grand Map"),
        **_command(authority, "create-brain-domain"),
    )
    requirement_definition = declare_definition(
        authority,
        "Requirement",
        {"title": "Untitled requirement"},
        parameters={"title": {"editor": "text"}},
        **_command(authority, "declare-requirement-assembly"),
    )
    requirement_definition = _publish(
        authority, requirement_definition, "requirement-assembly"
    )
    requirement = instantiate_definition(
        authority,
        requirement_definition.root_id,
        {"title": "Persistent attention"},
        scope_root=domain.root_id,
        **_command(authority, "create-persistent-attention-requirement"),
    )

    snapshot = authority.store.snapshot()
    assert any(
        member.role_id == authority.role("composition")
        and member.participant_id == requirement.root_id
        for member in relation_members(snapshot, domain.root_id)
    )
    assert requirement.root_id in reachable_roots(snapshot, domain.root_id)


def test_contained_scope_is_revision_exact_and_cannot_read_a_sibling_scope():
    authority = _authority()
    definition = declare_definition(
        authority,
        "Scope item",
        {"title": "Untitled"},
        parameters={"title": {"editor": "text"}},
        **_command(authority, "declare-contained-scope-item"),
    )
    definition = _publish(authority, definition, "contained-scope-item")
    grand_map = composition_root(authority, "Grand Map")
    projects = composition_root(authority, "Projects")
    container = instantiate_definition(
        authority,
        definition.root_id,
        {"title": "Container"},
        scope_root=grand_map,
        **_command(authority, "create-contained-scope-container"),
    )
    first = instantiate_definition(
        authority,
        definition.root_id,
        {"title": "First"},
        scope_root=container.root_id,
        **_command(authority, "create-contained-scope-first"),
    )
    sibling = instantiate_definition(
        authority,
        definition.root_id,
        {"title": "Sibling"},
        scope_root=projects,
        **_command(authority, "create-contained-scope-sibling"),
    )
    second = instantiate_definition(
        authority,
        definition.root_id,
        {"title": "Second"},
        scope_root=container.root_id,
        **_command(authority, "create-contained-scope-second"),
    )

    historical = read_contained_scope(
        authority,
        container.root_id,
        scope_root=grand_map,
        at_revision=first.revision,
    )
    current = read_contained_scope(
        authority,
        container.root_id,
        scope_root=grand_map,
    )

    assert historical.revision == first.revision
    assert first.root_id in historical.instances
    assert second.root_id not in historical.instances
    assert sibling.root_id not in historical.instances
    assert {first.root_id, second.root_id}.issubset(current.instances)
    assert sibling.root_id not in current.instances
    with pytest.raises(InvalidCell):
        read_contained_scope(
            authority,
            container.root_id,
            scope_root=projects,
        )


def test_graph_held_transition_rules_gate_one_stable_instance_identity():
    authority = _authority()
    definition = declare_definition(
        authority,
        "Governed activity",
        {"state": "draft", "title": "Untitled"},
        parameters={
            "state": {
                "type": "text",
                "options": ["draft", "assigned"],
                "editor": "choice",
            },
            "title": {"type": "text", "editor": "text"},
        },
        rules={
            "state_parameter": "state",
            "transitions": {
                "assigned": {
                    "from": ["draft"],
                    "required_connections": ["obligation", "assignee"],
                }
            },
        },
        **_command(authority, "declare-governed-activity"),
    )
    definition = _publish(authority, definition, "governed-activity")
    scope = composition_root(authority, "Projects")
    activity = instantiate_definition(
        authority,
        definition.root_id,
        {"title": "Inspect the graph"},
        scope_root=scope,
        **_command(authority, "create-governed-activity"),
    )
    revision = authority.store.revision
    count = len(authority.store.snapshot().cells)
    with pytest.raises(InvalidCell, match="missing a required connection"):
        revise_instance(
            authority,
            activity.root_id,
            {"state": "assigned"},
            scope_root=scope,
            **_command(authority, "assign-governed-activity-too-early"),
        )
    assert authority.store.revision == revision
    assert len(authority.store.snapshot().cells) == count

    create_relation_node(
        authority,
        (("source", activity.root_id), ("target", authority.manifest.policy_root)),
        scope_root=activity.root_id,
        properties={"connection": "obligation"},
        **_command(authority, "connect-governed-obligation"),
    )
    create_relation_node(
        authority,
        (("source", activity.root_id), ("target", authority.manifest.bootstrap_session_root)),
        scope_root=activity.root_id,
        properties={"connection": "assignee"},
        **_command(authority, "connect-governed-assignee"),
    )
    assigned = revise_instance(
        authority,
        activity.root_id,
        {"state": "assigned"},
        scope_root=scope,
        **_command(authority, "assign-governed-activity"),
    )
    projection = read_instance(authority, activity.root_id, scope_root=scope)
    replay = revise_instance(
        authority,
        activity.root_id,
        {"state": "assigned"},
        scope_root=scope,
        **_command(authority, "assign-governed-activity"),
    )

    assert assigned.root_id == activity.root_id
    assert projection["values"]["state"] == "assigned"
    assert replay.replayed is True
    assert replay.root_id == activity.root_id


def test_repeating_one_command_after_restart_creates_zero_cells(tmp_path):
    database = tmp_path / "archhub-clean.sqlite3"
    provider = _provider()
    store = CellStore(database)
    authority = create_unified_authority(
        store,
        provider,
        key_id="clean-bootstrap",
        application_label="ArchHub",
        principal_label="Founder",
        bootstrap_session_label="Clean rebuild session",
        bootstrap_session_public_key=CALLER_PUBLIC,
        composition_labels=COMPOSITIONS,
    )
    manifest_text = authority.manifest.to_json()
    definition = declare_definition(
        authority,
        "Project",
        {"status": "WIP"},
        parameters={"title": {"editor": "text"}},
        **_command(authority, "declare-project"),
    )
    definition = _publish(authority, definition, "project-restart")
    request = {
        "definition_root": definition.root_id,
        "overrides": {"title": "BBC4"},
        "scope_root": composition_root(authority, "Projects"),
        **_command(authority, "create-project-bbc4"),
    }
    first = instantiate_definition(authority, **request)
    revision = store.revision
    cell_count = len(store.snapshot().cells)
    store.close()

    reopened_store = CellStore(database)
    reopened = open_unified_authority(
        reopened_store,
        BootstrapManifest.from_json(manifest_text),
        provider,
    )
    second = instantiate_definition(reopened, **request)

    assert second.root_id == first.root_id
    assert second.replayed is True
    assert reopened_store.revision == revision
    assert len(reopened_store.snapshot().cells) == cell_count
    reopened_store.close()


def test_every_clean_authority_mutation_replays_without_new_semantic_cells():
    authority = _authority()
    declare_request = {
        "name": "Project",
        "defaults": {"status": "WIP"},
        "parameters": {"title": {"editor": "text"}},
        **_command(authority, "declare-idempotent-project"),
    }
    declared = declare_definition(authority, **declare_request)
    declare_revision = declared.revision
    declare_count = len(authority.store.snapshot().cells)
    declared_again = declare_definition(authority, **declare_request)
    assert declared_again.replayed is True
    assert declared_again.revision == declare_revision
    assert len(authority.store.snapshot().cells) == declare_count

    revise_request = {
        "definition_root": declared.root_id,
        "name": "Project",
        "defaults": {"status": "WIP", "title": "Untitled"},
        "parameters": {"title": {"editor": "text"}},
        "version": "2",
        **_command(authority, "revise-idempotent-project"),
    }
    revised = revise_definition(authority, **revise_request)
    revise_revision = revised.revision
    revise_count = len(authority.store.snapshot().cells)
    revised_again = revise_definition(authority, **revise_request)
    assert revised_again.replayed is True
    assert revised_again.revision == revise_revision
    assert len(authority.store.snapshot().cells) == revise_count
    revised = _publish(authority, revised, "idempotent-project")

    scope = composition_root(authority, "Projects")
    left = instantiate_definition(
        authority,
        declared.root_id,
        {"title": "Source"},
        scope_root=scope,
        **_command(authority, "instantiate-source"),
    )
    right = instantiate_definition(
        authority,
        declared.root_id,
        {"title": "Target"},
        scope_root=scope,
        **_command(authority, "instantiate-target"),
    )
    relation_request = {
        "participants": (
            ("source", left.root_id),
            ("target", right.root_id),
        ),
        "scope_root": scope,
        "properties": {"direction": "source-to-target"},
        **_command(authority, "wire-idempotent-projects"),
    }
    relation = create_relation_node(authority, **relation_request)
    relation_revision = relation.revision
    relation_count = len(authority.store.snapshot().cells)
    relation_again = create_relation_node(authority, **relation_request)
    assert relation_again.replayed is True
    assert relation_again.revision == relation_revision
    assert len(authority.store.snapshot().cells) == relation_count


def test_same_idempotency_key_cannot_change_meaning():
    authority = _authority()
    definition = declare_definition(
        authority,
        "Project",
        {"status": "WIP"},
        parameters={"title": {"editor": "text"}},
        **_command(authority, "declare-project"),
    )
    definition = _publish(authority, definition, "project-key-reuse")
    common = {
        "definition_root": definition.root_id,
        "scope_root": composition_root(authority, "Projects"),
        **_command(authority, "create-project-bbc4"),
    }
    instantiate_definition(authority, overrides={"title": "BBC4"}, **common)

    with pytest.raises(InvalidCell, match="idempotency key"):
        instantiate_definition(
            authority, overrides={"title": "Another"}, **common
        )


def test_command_uuid_is_the_direct_graph_address_for_constant_replay_lookup():
    authority = _authority()
    command_id = str(uuid.uuid5(COMMAND_NAMESPACE, "direct-command-address"))
    result = declare_definition(
        authority,
        "Direct command address",
        {},
        caller=_Caller(authority),
        command_id=command_id,
    )
    snapshot = authority.store.snapshot()
    receipt_command = next(
        member.participant_id
        for member in relation_members(snapshot, result.receipt_root)
        if member.role_id == authority.role("command")
    )

    assert receipt_command == command_id
    assert _find_receipt(
        authority,
        snapshot,
        authority.manifest.principal_root,
        authority.manifest.bootstrap_session_root,
        command_id,
    ).root_id == result.receipt_root
    lookup_source = inspect.getsource(_find_receipt)
    assert "history_root" not in lookup_source
    assert "for member in" not in lookup_source


def test_accepted_mutation_carries_the_exact_graph_logic_proof():
    authority = _authority()
    result = declare_definition(
        authority,
        "Project",
        {"status": "WIP"},
        **_command(authority, "declare-governed-project"),
    )
    snapshot = authority.store.snapshot()
    receipt_root = next(
        member.participant_id
        for member in relation_members(snapshot, authority.manifest.history_root)
        if member.role_id == authority.role("receipt")
        and next(
            participant.participant_id
            for participant in relation_members(snapshot, member.participant_id)
            if participant.role_id == authority.role("result")
        ) == result.root_id
    )
    command_root = next(
        member.participant_id
        for member in relation_members(snapshot, receipt_root)
        if member.role_id == authority.role("command")
    )
    receipt_head = next(
        member.participant_id
        for member in relation_members(snapshot, receipt_root)
        if member.role_id == authority.role("head")
    )
    current_head = next(
        member.participant_id
        for member in relation_members(
            authority.store.at(result.revision),
            authority.manifest.head_index_root,
        )
        if member.role_id == authority.role("current-head")
    )
    command = validate_composition(authority, snapshot, command_root)

    assert receipt_head == current_head
    assert "change-digest" not in authority.roles
    assert "change-count" not in authority.roles
    assert command.protocol_root == authority.shape("command")
    by_role = {member.role_id: member.participant_id for member in command.members}
    assert by_role[authority.role("actor")] == authority.manifest.principal_root
    assert by_role[authority.role("session")] == authority.manifest.bootstrap_session_root
    assert by_role[authority.role("object")] == authority.manifest.catalogue_root
    assert by_role[authority.role("scope")] == authority.manifest.catalogue_root
    proof_root = by_role[authority.role("policy")]
    assert validate_composition(
        authority, snapshot, proof_root
    ).protocol_root == authority.shape("logic-proof")
    command_projection = _command_projection(authority, snapshot, command_root)
    proof = _read_logic_proof(
        authority,
        snapshot,
        proof_root,
        expected_base_revision=command_projection.base_revision,
    )
    expected = _matching_policy_proofs(
        authority,
        authority.store.at(command_projection.base_revision),
        actor_root=authority.manifest.principal_root,
        session_root=authority.manifest.bootstrap_session_root,
        intent=command_projection.intent,
        scope_root=command_projection.scope_root,
        object_root=command_projection.object_root,
        budget=command_projection.budget,
    )
    assert expected == (proof,)
    assert proof.steps
    assert proof.top_rule_root in {step.rule_root for step in proof.steps}
    assert proof.read_roots
    assert all(
        root in authority.store.at(command_projection.base_revision).cells
        for root in proof.read_roots
    )
    assert "grant" not in authority.roles
    assert "grant" not in authority.shapes
    signature_root = by_role[authority.role("signature")]
    signature = json.loads(snapshot.cells[signature_root].atom.decode("utf-8"))
    assert isinstance(signature, str)
    assert len(base64.b64decode(signature, validate=True)) == 64


def test_public_mutation_apis_do_not_accept_raw_actor_or_session_identities():
    for mutation in (
        declare_definition,
        revise_definition,
        promote_definition,
        instantiate_definition,
        create_relation_node,
    ):
        parameters = inspect.signature(mutation).parameters
        assert "caller" in parameters
        assert "actor_root" not in parameters
        assert "session_root" not in parameters


def test_foreign_key_cannot_impersonate_founder_and_creates_zero_cells():
    authority = _authority()
    revision = authority.store.revision
    count = len(authority.store.snapshot().cells)
    foreign_private = Ed25519PrivateKey.generate()

    class ForeignCaller:
        actor_root = authority.manifest.principal_root
        session_root = authority.manifest.bootstrap_session_root
        public_key = foreign_private.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )

        @staticmethod
        def sign(payload: bytes) -> bytes:
            return foreign_private.sign(payload)

    with pytest.raises(InvalidCell, match="capability key"):
        declare_definition(
            authority,
            "Impersonated definition",
            {},
            caller=ForeignCaller(),
            command_id=str(uuid.uuid4()),
        )

    assert authority.store.revision == revision
    assert len(authority.store.snapshot().cells) == count


def test_signer_returning_after_expiry_is_rejected_before_policy_and_creates_zero_cells(
    monkeypatch,
):
    authority = _authority()
    revision = authority.store.revision
    count = len(authority.store.snapshot().cells)
    issued = datetime(2026, 8, 3, 8, 0, tzinfo=timezone.utc)
    moments = iter((issued, issued + timedelta(minutes=3)))
    monkeypatch.setattr(
        "nodelang.unified_authority._utc_now",
        lambda: next(moments),
    )

    with pytest.raises(InvalidCell, match="expired before authorization"):
        declare_definition(
            authority,
            "Expired request",
            {},
            **_command(authority, "expired-signer-court"),
        )

    assert authority.store.revision == revision
    assert len(authority.store.snapshot().cells) == count


def test_authenticated_denial_is_signed_evidence_and_replays_without_resource_cells():
    authority = _authority()
    _disable_policy_decision(authority)
    before = authority.store.snapshot()
    definitions_before = tuple(
        member.participant_id
        for member in relation_members(before, authority.manifest.catalogue_root)
        if member.role_id == authority.role("definition")
    )
    command = _command(authority, "authenticated-denial-court")

    with pytest.raises(AuthorizationDenied) as denied:
        declare_definition(authority, "Denied definition", {}, **command)

    assert denied.value.replayed is False
    assert authority.store.revision == before.revision + 1
    denied_receipt = _receipt_projection(
        authority, authority.store.snapshot(), denied.value.receipt_root
    )
    assert denied_receipt.decision == "deny"
    assert denied_receipt.policy_proof_root is None
    definitions_after = tuple(
        member.participant_id
        for member in relation_members(
            authority.store.snapshot(), authority.manifest.catalogue_root
        )
        if member.role_id == authority.role("definition")
    )
    assert definitions_after == definitions_before

    replay_revision = authority.store.revision
    with pytest.raises(AuthorizationDenied) as replayed:
        declare_definition(authority, "Denied definition", {}, **command)
    assert replayed.value.replayed is True
    assert replayed.value.receipt_root == denied.value.receipt_root
    assert authority.store.revision == replay_revision


def test_historical_receipt_recomputes_the_exact_selected_logic_proof(monkeypatch):
    authority = _authority()
    result = declare_definition(
        authority,
        "Logic proof evidence",
        {},
        **_command(authority, "historical-proof-court"),
    )
    committed = authority.store.at(result.revision)
    command_root = next(
        member.participant_id
        for member in relation_members(committed, result.receipt_root)
        if member.role_id == authority.role("command")
    )
    policy_member = next(
        member
        for member in relation_members(committed, command_root)
        if member.role_id == authority.role("policy")
    )
    incidence = committed.cells[policy_member.incidence_id]
    tampered = overlay_read_snapshot(
        committed,
        replace=(replace(incidence, link1=authority.manifest.policy_root),),
    )
    original_at = CellStore.at

    def altered_result(store, revision):
        if store is authority.store and revision == result.revision:
            return tampered
        return original_at(store, revision)

    monkeypatch.setattr(CellStore, "at", altered_result)

    with pytest.raises(InvalidCell, match="logic proof|graph policy proof"):
        _receipt_projection(authority, authority.store.snapshot(), result.receipt_root)


def test_ambiguous_graph_policy_rules_fail_closed_without_a_command_commit():
    authority = _authority()
    snapshot = authority.store.snapshot()
    decision_predicate = next(
        member.participant_id
        for member in relation_members(snapshot, authority.manifest.policy_root)
        if member.role_id == authority.role("predicate")
    )
    decision_rule = next(
        member.participant_id
        for member in relation_members(snapshot, authority.manifest.policy_root)
        if member.role_id == authority.role("rule")
        and next(
            predicate.participant_id
            for predicate in relation_members(
                snapshot,
                next(
                    head.participant_id
                    for head in relation_members(snapshot, member.participant_id)
                    if head.role_id == authority.role("head")
                ),
            )
            if predicate.role_id == authority.role("predicate")
        ) == decision_predicate
    )
    patch = _append_relation_member(
        snapshot,
        authority.manifest.policy_root,
        authority.role("rule"),
        decision_rule,
    )
    _commit_signed_change(
        authority,
        snapshot,
        create=patch.create,
        replace_cells=patch.replace,
    )
    revision = authority.store.revision
    cell_count = len(authority.store.snapshot().cells)

    with pytest.raises(InvalidCell, match="unique graph-held rules"):
        declare_definition(
            authority,
            "Ambiguous policy must not write",
            {},
            **_command(authority, "ambiguous-policy"),
        )

    assert authority.store.revision == revision
    assert len(authority.store.snapshot().cells) == cell_count


def test_replay_from_another_session_is_rejected():
    authority = _authority()
    command = _command(authority, "session-bound-replay")
    result = declare_definition(
        authority,
        "Session-bound receipt",
        {},
        **command,
    )

    with pytest.raises(InvalidCell, match="another caller"):
        _find_receipt(
            authority,
            authority.store.snapshot(),
            authority.manifest.principal_root,
            str(uuid.uuid4()),
            command["command_id"],
        )

    assert _find_receipt(
        authority,
        authority.store.snapshot(),
        authority.manifest.principal_root,
        authority.manifest.bootstrap_session_root,
        command["command_id"],
    ).root_id == result.receipt_root


def _receipt_accepted_at_payload(authority, snapshot, receipt_root):
    return next(
        member.participant_id
        for member in relation_members(snapshot, receipt_root)
        if member.role_id == authority.role("accepted-at")
    )


def test_historical_receipt_rejects_acceptance_equal_to_expiry():
    authority = _authority()
    result = declare_definition(
        authority,
        "Expiry boundary",
        {},
        **_command(authority, "expiry-boundary"),
    )
    committed = authority.store.at(result.revision)
    command_root = next(
        member.participant_id
        for member in relation_members(committed, result.receipt_root)
        if member.role_id == authority.role("command")
    )
    command = _command_projection(authority, committed, command_root)
    payload_root = _receipt_accepted_at_payload(
        authority, committed, result.receipt_root
    )
    payload = committed.cells[payload_root]
    tampered = overlay_read_snapshot(
        committed,
        replace=(replace(
            payload,
            atom=json.dumps(command.expires_at).encode("utf-8"),
        ),),
    )

    with pytest.raises(InvalidCell, match="signed command"):
        _receipt_projection(authority, tampered, result.receipt_root)


def test_historical_receipt_rejects_acceptance_before_issuance():
    authority = _authority()
    result = declare_definition(
        authority,
        "Issuance boundary",
        {},
        **_command(authority, "issuance-boundary"),
    )
    committed = authority.store.at(result.revision)
    command_root = next(
        member.participant_id
        for member in relation_members(committed, result.receipt_root)
        if member.role_id == authority.role("command")
    )
    command = _command_projection(authority, committed, command_root)
    issued = datetime.fromisoformat(command.issued_at.replace("Z", "+00:00"))
    invalid = (issued - timedelta(microseconds=1)).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")
    payload_root = _receipt_accepted_at_payload(
        authority, committed, result.receipt_root
    )
    payload = committed.cells[payload_root]
    tampered = overlay_read_snapshot(
        committed,
        replace=(replace(
            payload,
            atom=json.dumps(invalid).encode("utf-8"),
        ),),
    )

    with pytest.raises(InvalidCell, match="signed command"):
        _receipt_projection(authority, tampered, result.receipt_root)


def test_composition_root_rejects_signed_participant_with_wrong_protocol():
    authority = _authority()
    brain_root = composition_root(authority, "Brain")
    snapshot = authority.store.snapshot()
    conforms = next(
        member
        for member in relation_members(snapshot, brain_root)
        if member.role_id == authority.role("conforms-to")
    )
    incidence = snapshot.cells[conforms.incidence_id]
    _commit_signed_change(
        authority,
        snapshot,
        create=(),
        replace_cells=(replace(
            incidence,
            link1=authority.shape("definition"),
        ),),
    )

    with pytest.raises(InvalidCell, match="composition|protocol"):
        composition_root(authority, "Brain")


def test_semantic_reads_require_graph_bound_caller_and_graph_policy_proof():
    authority = _authority()
    declared = declare_definition(
        authority,
        "Protected read",
        {},
        **_command(authority, "protected-read"),
    )
    foreign_private = Ed25519PrivateKey.generate()

    class ForeignSigner:
        actor_root = authority.manifest.principal_root
        session_root = authority.manifest.bootstrap_session_root
        public_key = CALLER_PUBLIC

        @staticmethod
        def sign(payload: bytes) -> bytes:
            return foreign_private.sign(payload)

    with pytest.raises(TypeError):
        _read_definition(authority, declared.root_id)
    with pytest.raises(InvalidCell, match="signature"):
        _read_definition(
            authority,
            declared.root_id,
            caller=ForeignSigner(),
        )
    assert _read_definition(
        authority,
        declared.root_id,
        caller=_Caller(authority),
    ).root_id == declared.root_id


def test_denial_receipt_replays_after_restart_without_original_capability(tmp_path):
    database = tmp_path / "denial-replay.sqlite3"
    provider = _provider()
    store = CellStore(database)
    authority = create_unified_authority(
        store,
        provider,
        key_id="clean-bootstrap",
        application_label="ArchHub",
        principal_label="Founder",
        bootstrap_session_label="Clean rebuild session",
        bootstrap_session_public_key=CALLER_PUBLIC,
        composition_labels=COMPOSITIONS,
    )
    snapshot = store.snapshot()
    _disable_policy_decision(authority)
    command = _command(authority, "restart-denial")
    with pytest.raises(AuthorizationDenied) as denied:
        declare_definition(authority, "Denied across restart", {}, **command)
    manifest = authority.manifest.to_json()
    store.close()

    reopened_store = CellStore(database)
    reopened = open_unified_authority(
        reopened_store,
        BootstrapManifest.from_json(manifest),
        provider,
    )
    revision = reopened_store.revision
    with pytest.raises(AuthorizationDenied) as replayed:
        declare_definition(
            reopened,
            "Denied across restart",
            {},
            caller=_Caller(reopened),
            command_id=command["command_id"],
        )
    assert replayed.value.replayed is True
    assert replayed.value.receipt_root == denied.value.receipt_root
    assert reopened_store.revision == revision
    reopened_store.close()


def test_authority_key_signs_only_the_accepted_head_not_the_caller_request():
    provider = _CountingProvider()
    authority = create_unified_authority(
        CellStore(),
        provider,
        key_id="clean-bootstrap",
        application_label="ArchHub",
        principal_label="Founder",
        bootstrap_session_label="Clean rebuild session",
        bootstrap_session_public_key=CALLER_PUBLIC,
        composition_labels=COMPOSITIONS,
    )
    before = provider.sign_count
    declare_definition(
        authority,
        "Caller-signed definition",
        {},
        **_command(authority, "caller-signature-not-authority-signature"),
    )
    assert provider.sign_count == before + 1


def test_command_verifier_rejects_tampered_validity_scope_and_challenge():
    authority = _authority()
    result = declare_definition(
        authority,
        "Authenticated definition",
        {},
        **_command(authority, "authenticated-command-tamper-court"),
    )
    snapshot = authority.store.snapshot()
    receipt = next(
        member.participant_id
        for member in relation_members(snapshot, authority.manifest.history_root)
        if member.role_id == authority.role("receipt")
        and member.participant_id == result.receipt_root
    )
    command_root = next(
        member.participant_id
        for member in relation_members(snapshot, receipt)
        if member.role_id == authority.role("command")
    )

    expires_value = next(
        member.participant_id
        for member in relation_members(snapshot, command_root)
        if member.role_id == authority.role("expires-at")
    )
    expiry_cell = snapshot.cells[expires_value]
    invalid_expiry = overlay_read_snapshot(
        snapshot,
        replace=(replace(expiry_cell, atom=b'"2999-01-01T00:00:00Z"'),),
    )
    with pytest.raises(InvalidCell, match="validity window"):
        _command_projection(authority, invalid_expiry, command_root)

    scope_member = next(
        member
        for member in relation_members(snapshot, command_root)
        if member.role_id == authority.role("scope")
    )
    scope_incidence = snapshot.cells[scope_member.incidence_id]
    changed_scope = overlay_read_snapshot(
        snapshot,
        replace=(replace(
            scope_incidence,
            link1=authority.manifest.history_root,
        ),),
    )
    with pytest.raises(InvalidCell, match="caller signature"):
        _command_projection(authority, changed_scope, command_root)

    head_member = next(
        member
        for member in relation_members(snapshot, command_root)
        if member.role_id == authority.role("head")
    )
    head_incidence = snapshot.cells[head_member.incidence_id]
    changed_head = overlay_read_snapshot(
        snapshot,
        replace=(replace(
            head_incidence,
            link1=authority.manifest.history_root,
        ),),
    )
    with pytest.raises(InvalidCell, match="challenge"):
        _command_projection(authority, changed_head, command_root)


def test_raw_session_insertion_without_a_signed_head_cannot_write():
    authority = _authority()
    snapshot = authority.store.snapshot()
    foreign_session = str(uuid.uuid4())
    incidence = str(uuid.uuid4())
    authority.store.commit(snapshot.revision, create=(
        Cell(
            incidence,
            authority.role("actor"),
            authority.manifest.principal_root,
            b"",
        ),
        Cell(foreign_session, incidence, NULL_CELL_ID, b""),
    ))

    caller = _Caller(authority)
    caller.session_root = foreign_session
    with pytest.raises(InvalidCell, match="authority head"):
        declare_definition(
            authority,
            "Unauthorized definition",
            {},
            caller=caller,
            command_id=str(uuid.uuid5(COMMAND_NAMESPACE, "foreign-session-write")),
        )


def test_enrolled_session_writes_with_its_own_key_and_revocation_fails_closed():
    authority = _authority()
    founder = _Caller(authority)
    session_private = Ed25519PrivateKey.generate()
    public_key = session_private.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    sessions = composition_root(authority, "Agent Sessions")
    enrolled = enroll_session(
        authority,
        "Codex provider session",
        public_key,
        session_container_root=sessions,
        caller=founder,
        command_id=str(uuid.uuid5(COMMAND_NAMESPACE, "enroll-provider-session")),
    )
    revision = authority.store.revision
    count = len(authority.store.snapshot().cells)
    replay = enroll_session(
        authority,
        "Codex provider session",
        public_key,
        session_container_root=sessions,
        caller=founder,
        command_id=str(uuid.uuid5(COMMAND_NAMESPACE, "enroll-provider-session")),
    )
    assert replay.replayed is True
    assert replay.root_id == enrolled.root_id
    assert authority.store.revision == revision
    assert len(authority.store.snapshot().cells) == count

    provider = _KeyedCaller(authority, enrolled.root_id, session_private)
    declared = declare_definition(
        authority,
        "Provider-owned WIP assembly",
        {},
        version="1",
        caller=provider,
        command_id=str(uuid.uuid5(COMMAND_NAMESPACE, "provider-declare")),
    )
    assert declared.root_id in authority.store.snapshot().cells

    revoked = revoke_session(
        authority,
        enrolled.root_id,
        caller=founder,
        command_id=str(uuid.uuid5(COMMAND_NAMESPACE, "revoke-provider-session")),
    )
    assert revoked.root_id == enrolled.root_id
    with pytest.raises(InvalidCell, match="revoked|binding"):
        declare_definition(
            authority,
            "Revoked provider write",
            {},
            version="1",
            caller=provider,
            command_id=str(uuid.uuid5(COMMAND_NAMESPACE, "revoked-provider-declare")),
        )


def test_graph_transition_can_require_the_exact_connected_caller_session():
    authority = _authority()
    founder = _Caller(authority)
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    enrolled = enroll_session(
        authority,
        "Bound transition session",
        public_key,
        session_container_root=composition_root(authority, "Agent Sessions"),
        caller=founder,
        command_id=str(uuid.uuid5(COMMAND_NAMESPACE, "enroll-bound-transition")),
    )
    provider = _KeyedCaller(authority, enrolled.root_id, private_key)
    declared = declare_definition(
        authority,
        "Caller-bound transition",
        {"state": "draft"},
        parameters={
            "state": {
                "type": "text",
                "options": ["draft", "active"],
                "editor": "choice",
            }
        },
        rules={
            "state_parameter": "state",
            "transitions": {
                "active": {
                    "from": ["draft"],
                    "required_connections": ["owner"],
                    "caller_matches_connection": "owner",
                }
            },
        },
        caller=founder,
        command_id=str(uuid.uuid5(COMMAND_NAMESPACE, "declare-bound-transition")),
    )
    shared = promote_definition(
        authority,
        declared.root_id,
        target_lifecycle="shared",
        version="1-shared",
        evidence_roots=(declared.receipt_root,),
        caller=founder,
        command_id=str(uuid.uuid5(COMMAND_NAMESPACE, "share-bound-transition")),
    )
    promote_definition(
        authority,
        declared.root_id,
        target_lifecycle="published",
        version="1",
        evidence_roots=(shared.receipt_root,),
        caller=founder,
        command_id=str(uuid.uuid5(COMMAND_NAMESPACE, "publish-bound-transition")),
    )
    project = composition_root(authority, "Projects")
    instance = instantiate_definition(
        authority,
        declared.root_id,
        {},
        scope_root=project,
        caller=founder,
        command_id=str(uuid.uuid5(COMMAND_NAMESPACE, "instantiate-bound-transition")),
    )
    create_relation_node(
        authority,
        (("source", instance.root_id), ("target", enrolled.root_id)),
        scope_root=instance.root_id,
        properties={"connection": "owner"},
        caller=founder,
        command_id=str(uuid.uuid5(COMMAND_NAMESPACE, "connect-bound-owner")),
    )
    before = authority.store.revision
    with pytest.raises(InvalidCell, match="connected caller session"):
        revise_instance(
            authority,
            instance.root_id,
            {"state": "active"},
            scope_root=project,
            caller=founder,
            command_id=str(uuid.uuid5(COMMAND_NAMESPACE, "founder-bound-transition")),
        )
    assert authority.store.revision == before
    revised = revise_instance(
        authority,
        instance.root_id,
        {"state": "active"},
        scope_root=project,
        caller=provider,
        command_id=str(uuid.uuid5(COMMAND_NAMESPACE, "provider-bound-transition")),
    )
    assert revised.root_id == instance.root_id


def test_receipt_size_is_constant_instead_of_copying_changed_cells():
    authority = _authority()
    definition = declare_definition(
        authority,
        "Large assembly",
        {"field-%03d" % index: "default" for index in range(250)},
        parameters={
            "field-%03d" % index: {"editor": "text"}
            for index in range(250)
        },
        **_command(authority, "declare-large"),
    )
    definition = _publish(authority, definition, "large-assembly")
    small = instantiate_definition(
        authority,
        definition.root_id,
        {"field-000": "changed"},
        scope_root=composition_root(authority, "Projects"),
        **_command(authority, "instantiate-small-change"),
    )
    large = instantiate_definition(
        authority,
        definition.root_id,
        {"field-%03d" % index: "changed" for index in range(250)},
        scope_root=composition_root(authority, "Projects"),
        **_command(authority, "instantiate-large-change"),
    )

    assert large.created_cell_count > 1_000
    assert small.receipt_cell_count == large.receipt_cell_count
    assert large.receipt_cell_count < 180


def test_wire_is_an_explicit_editable_relation_node_and_survives_restart(tmp_path):
    database = tmp_path / "archhub-wire.sqlite3"
    provider = _provider()
    store = CellStore(database)
    authority = create_unified_authority(
        store,
        provider,
        key_id="clean-bootstrap",
        application_label="ArchHub",
        principal_label="Founder",
        bootstrap_session_label="Clean rebuild session",
        bootstrap_session_public_key=CALLER_PUBLIC,
        composition_labels=COMPOSITIONS,
    )
    definition = declare_definition(
        authority,
        "Project",
        {"status": "WIP"},
        parameters={"title": {"editor": "text"}},
        **_command(authority, "declare-project"),
    )
    definition = _publish(authority, definition, "wire-project")
    scope = composition_root(authority, "Projects")
    left = instantiate_definition(
        authority,
        definition.root_id,
        {"title": "Source"},
        scope_root=scope,
        **_command(authority, "create-source"),
    )
    right = instantiate_definition(
        authority,
        definition.root_id,
        {"title": "Target"},
        scope_root=scope,
        **_command(authority, "create-target"),
    )
    wire = create_relation_node(
        authority,
        (("source", left.root_id), ("target", right.root_id)),
        scope_root=scope,
        properties={
            "direction": "source-to-target",
            "policy": "explicit",
            "presentation": {"color": "#3f8f8a"},
        },
        **_command(authority, "wire-source-to-target"),
    )
    first_projection = read_relation_node(authority, wire.root_id)
    replay = create_relation_node(
        authority,
        (("source", left.root_id), ("target", right.root_id)),
        scope_root=scope,
        properties={
            "direction": "source-to-target",
            "policy": "explicit",
            "presentation": {"color": "#3f8f8a"},
        },
        **_command(authority, "wire-source-to-target"),
    )
    manifest_text = authority.manifest.to_json()
    revision = store.revision
    store.close()

    reopened_store = CellStore(database)
    reopened = open_unified_authority(
        reopened_store,
        BootstrapManifest.from_json(manifest_text),
        provider,
    )
    restored = read_relation_node(reopened, wire.root_id)

    assert replay.replayed is True
    assert replay.root_id == wire.root_id
    assert first_projection == restored
    assert restored.participants == (
        ("source", left.root_id),
        ("target", right.root_id),
    )
    assert dict(restored.properties) == {
        "direction": "source-to-target",
        "policy": "explicit",
        "presentation": {"color": "#3f8f8a"},
    }
    assert reopened_store.revision == revision
    reopened_store.close()


def test_property_predecessor_sentinel_holds_only_while_one_mint_site_exists():
    """A property naming itself means it replaced nothing.

    That reading is only sound while every property root is freshly minted,
    so no property can legitimately be its own predecessor. The sentinel is
    load-bearing and the invariant behind it is not otherwise stated: a
    second mint site, or any path that reuses a property root, turns
    "replaced nothing" into a claim that is silently false. This pins the
    invariant to the source so that change fails here instead of in a
    reader that trusts the sentinel.
    """
    import ast
    import pathlib

    source = pathlib.Path(
        unified_authority_module.__file__
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    # Reading an existing property root is normal and several readers do it.
    # What must stay unique is MINTING one: the sentinel means "this root is
    # new, so naming itself means it replaced nothing".
    minters = sorted({
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        for statement in ast.walk(node)
        if isinstance(statement, ast.Assign)
        for target in statement.targets
        if isinstance(target, ast.Name)
        and target.id.endswith("property_root")
        and isinstance(statement.value, ast.Call)
        and isinstance(statement.value.func, ast.Name)
        and statement.value.func.id == "_new_id"
    })
    assert minters == ["_build_property"], (
        "only _build_property may mint a property root. A second minter "
        "means predecessor_root == property_root stops encoding 'replaced "
        "nothing': %r" % minters
    )
    # The other half of the same invariant: a property composition assembled
    # anywhere else could carry a root that was never minted here, which
    # defeats the sentinel without adding a second minter.
    constructors = sorted({
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        for call in ast.walk(node)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "_typed_relation_cells"
        for argument in call.args
        if isinstance(argument, ast.Call)
        and isinstance(argument.func, ast.Attribute)
        and argument.func.attr == "shape"
        and argument.args
        and isinstance(argument.args[0], ast.Constant)
        and argument.args[0].value == "property"
    })
    assert constructors == ["_build_property"], (
        "only _build_property may construct a property composition: %r"
        % constructors
    )
