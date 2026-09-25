"""Acceptance court: no gesture bricks the next boot.

Verifier finding (canvas2 r4 probe6, 2026-09-25, present on main 6e167b6):
after a member view was provisioned (a Shared instance), selecting two map
domains and grouping them failed with "Conflict: expected revision 942,
current revision is 943", and the next ``restore_universal_application``
raised "RelationshipAuthorityDenied: authority relationship generation
history is discontinuous". Without the member view the same sequence
reopened.

Two causes, one court each below:
  * provisioning indexed fewer interfaces than the canvas reader derives, so
    the first read COMMITTED the rest, inside the group, after its snapshot;
  * reopening re-verified every historical generation of a relationship
    against its CURRENT evidence, so a Shared promotion (an evidence
    revision) made generation 1 read as drifted: the history "discontinuous".

Law bound here:
  * a gesture either commits whole or writes nothing;
  * whatever a gesture did, the store reopens and draws the same canvas.
"""
from __future__ import annotations

import json

from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    build_universal_application,
    group_universal_selection,
    instantiate_universal_definition,
    project_universal_canvas,
    promote_universal_resource_lifecycle,
    provision_universal_view_session,
    redo_universal_change,
    restore_universal_application,
    set_universal_selection,
    undo_universal_change,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


def _provider():
    provider = MemorySigningKeyProvider(
        "archhub.local.relationship-authority", b"w" * 32
    )
    provider.add_key("archhub.local.court-attestation", b"c" * 32)
    return provider


def _drawn(store, registry):
    canvas = project_universal_canvas(store, registry)
    return json.dumps(
        {"nodes": canvas["nodes"], "wires": canvas["wires"]}, sort_keys=True
    )


def _member_view(store, registry):
    shared, _ = instantiate_universal_definition(
        store, registry, registry.standard_library.definition_roots[2],
        x=420.0, y=640.0,
    )
    promote_universal_resource_lifecycle(store, registry, shared, "shared")
    member = "test:group-after-member-view:member"
    store.commit(store.revision, create=(
        Cell(member, NULL_CELL_ID, NULL_CELL_ID, b"Member"),
    ))
    provision_universal_view_session(
        store, registry, member, visible_roots=(shared,)
    )
    return shared


def test_grouping_domains_after_a_member_view_commits_and_reopens(tmp_path):
    path = tmp_path / "member-group.sqlite3"
    store, registry = build_universal_application(
        resolve_map_path(), CellStore(path), key_provider=_provider()
    )
    try:
        _member_view(store, registry)
        # A read writes nothing: the member's index already holds what the
        # reader derives, so no heal lands inside the next gesture.
        revision = store.revision
        project_universal_canvas(store, registry)
        assert store.revision == revision, "a canvas read wrote the graph"
        domains = registry.map.domains
        selected = (domains["brain"], domains["ui"])
        set_universal_selection(store, registry, selected, focus_root=selected[-1])
        before = store.revision
        try:
            group, _ = group_universal_selection(store, registry, title="Domains")
        except InvalidCell as refusal:
            # A refused gesture writes nothing.
            assert store.revision == before, (
                "a refused group wrote the graph: %s" % refusal
            )
            raise AssertionError("grouping two domains was refused: %s" % refusal)
        grouped = _drawn(store, registry)
        undo_universal_change(store, registry)
        redo_universal_change(store, registry)
        assert _drawn(store, registry) == grouped
    finally:
        store.close()
    store, registry = restore_universal_application(
        resolve_map_path(), CellStore(path), key_provider=_provider()
    )
    try:
        assert _drawn(store, registry) == grouped
        assert group in {node["id"] for node in
                         project_universal_canvas(store, registry)["nodes"]}
    finally:
        store.close()


def test_a_shared_promotion_reopens(tmp_path):
    """No member view, no group: promotion alone bricked the next boot."""
    path = tmp_path / "shared.sqlite3"
    store, registry = build_universal_application(
        resolve_map_path(), CellStore(path), key_provider=_provider()
    )
    try:
        shared, _ = instantiate_universal_definition(
            store, registry, registry.standard_library.definition_roots[2],
            x=420.0, y=640.0,
        )
        promote_universal_resource_lifecycle(store, registry, shared, "shared")
        drawn = _drawn(store, registry)
    finally:
        store.close()
    store, registry = restore_universal_application(
        resolve_map_path(), CellStore(path), key_provider=_provider()
    )
    try:
        assert _drawn(store, registry) == drawn
    finally:
        store.close()


def _founder(registry):
    import nodelang.universal_application as application_module

    authority = registry.authorization
    context = application_module._active_authentication_context(authority, None)
    return authority.broker.resolve(context).subject_root


def _append_signed_evidence(store, registry, relationship_root, extra_root):
    """A later signed generation whose evidence has one MORE member."""
    import hashlib
    import time

    import nodelang.cell_identity as identity_module
    from nodelang.cell_protocols import prepare_append_relation_members

    authority = registry.authorization
    identity = authority.identity_protocol
    broker = authority.relationship_broker
    admin = _founder(registry)
    snapshot = store.snapshot()
    relationship = identity_module.verify_authority_relationship(
        snapshot, identity, broker, relationship_root
    )
    evidence = (*relationship.evidence_roots, extra_root)
    generation = int(snapshot.cells[relationship.generation_root].atom) + 1
    changed = "%.6f" % time.time()
    reason = "court: evidence membership grows"

    def atom(root):
        return snapshot.cells[root].atom.decode("utf-8")

    key_reference, key_version = broker.current_key_reference()
    signed = identity_module._payload(
        root_id=relationship.root_id,
        source_root=relationship.source_root,
        target_root=relationship.target_root,
        kind_root=relationship.kind_root,
        tenant_root=relationship.tenant_root,
        scope_root=relationship.scope_root,
        action_roots=relationship.action_roots,
        state_root=relationship.state_root,
        issuer_root=relationship.issuer_root,
        changed_by_root=admin,
        issued_at=atom(relationship.issued_at_root),
        changed_at=changed,
        expires_at=(atom(relationship.expires_at_root)
                    if relationship.expires_at_root else None),
        generation=generation,
        reason=reason,
        evidence_roots=evidence,
        key_reference=key_reference,
        key_version=key_version,
    )
    signature = broker.authorize_signature(
        broker.mint_from_trusted_administrator(admin), admin, signed,
        key_reference, key_version, administration_scope=b"court",
    )
    digest = hashlib.sha256(signed).hexdigest()
    by = snapshot.cells[relationship.changed_by_incidence]
    replace = [Cell(by.id, by.link0, admin, by.atom)] + [
        Cell(root, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8"))
        for root, value in (
            (relationship.changed_at_root, changed),
            (relationship.generation_root, str(generation)),
            (relationship.reason_root, reason),
            (relationship.digest_root, digest),
            (relationship.signature_root, signature),
            (relationship.key_reference_root, key_reference),
            (relationship.key_version_root, str(key_version)),
        )
    ]
    grow = prepare_append_relation_members(
        snapshot, relationship_root,
        ((identity.roles["evidence"], extra_root),), budget=100_000,
    )
    store.commit(
        snapshot.revision, create=grow.create,
        replace=(*replace, *grow.replace),
    )
    broker.record_generation(relationship_root, generation)
    return generation


def test_evidence_membership_that_changes_after_promotion_reopens(tmp_path):
    """Coordinator gap (B): each generation is verified against the evidence
    membership ITS revision held, not today's. After a Shared promotion, a
    signed relationship whose later generation has one MORE evidence member
    must not make its earlier generation read as drifted."""
    from nodelang.cell_identity import grant_authority_relationship

    path = tmp_path / "evidence-grows.sqlite3"
    store, registry = build_universal_application(
        resolve_map_path(), CellStore(path), key_provider=_provider()
    )
    try:
        shared, _ = instantiate_universal_definition(
            store, registry, registry.standard_library.definition_roots[2],
            x=420.0, y=640.0,
        )
        promote_universal_resource_lifecycle(store, registry, shared, "shared")
        subject = "test:evidence-grows:subject"
        store.commit(store.revision, create=(
            Cell(subject, NULL_CELL_ID, NULL_CELL_ID, b"Court subject"),
        ))
        authority = registry.authorization
        admin = _founder(registry)
        binding = grant_authority_relationship(
            store,
            authority.identity_protocol,
            authority.relationship_broker,
            authority.relationship_broker.mint_from_trusted_administrator(admin),
            relationship_id="test:evidence-grows:membership",
            source_root=subject,
            target_root=authority.tenant_root,
            kind="membership",
            tenant_root=authority.tenant_root,
            administrator_root=admin,
            reason="court relationship with one evidence member",
            evidence_roots=(shared,),
        )
        generation = _append_signed_evidence(
            store, registry, binding, registry.application_root
        )
        assert generation == 2
        drawn = _drawn(store, registry)
    finally:
        store.close()
    store, registry = restore_universal_application(
        resolve_map_path(), CellStore(path), key_provider=_provider()
    )
    try:
        assert registry.authorization.relationship_broker.verify_generation(
            binding, generation
        )
        assert _drawn(store, registry) == drawn
    finally:
        store.close()
