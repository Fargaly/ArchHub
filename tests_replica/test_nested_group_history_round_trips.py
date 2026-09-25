"""Acceptance court: three nested groups and their ungroups undo and redo.

Verifier finding (2026-09-25, on 9d203f5 and with crossing-wire-v2): group
inner -> middle -> outer, then ungroup outer -> middle -> inner; the first
undo landed, the SECOND was refused, "created Cell gained references after
the recorded transaction". Every undo and redo lands on the exact canvas it
returns to, reads commit nothing, and the store reopens on the last canvas.
"""
from __future__ import annotations

import json

import pytest

from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    build_universal_application,
    group_universal_selection,
    project_universal_canvas,
    redo_universal_change,
    restore_universal_application,
    set_universal_selection,
    undo_universal_change,
    ungroup_universal_composition,
)
from nodelang.universal_cell import CellStore


def _provider():
    provider = MemorySigningKeyProvider(
        "archhub.local.relationship-authority", b"w" * 32
    )
    provider.add_key("archhub.local.court-attestation", b"c" * 32)
    return provider


def _drawn(store, registry):
    revision = store.revision
    canvas = project_universal_canvas(store, registry)
    assert store.revision == revision, "a canvas read wrote the graph"
    return json.dumps(
        {"nodes": canvas["nodes"], "wires": canvas["wires"]}, sort_keys=True
    )


def test_three_nested_groups_and_ungroups_undo_and_redo_all_the_way(tmp_path):
    path = tmp_path / "nested.sqlite3"
    store, registry = build_universal_application(
        resolve_map_path(), CellStore(path), key_provider=_provider()
    )
    try:
        domains = registry.map.domains

        # Undo returns to the moment before a gesture (with the selection
        # the user had set); redo returns to the moment right after it.
        states, forward = [], []

        def group(pair, title):
            set_universal_selection(store, registry, pair, focus_root=pair[-1])
            states.append(_drawn(store, registry))
            root, _ = group_universal_selection(store, registry, title=title)
            forward.append(_drawn(store, registry))
            return root

        inner = group((domains["brain"], domains["ui"]), "Inner")
        middle = group((inner, domains["canvas"]), "Middle")
        outer = group((middle, domains["nodes"]), "Outer")
        for root in (outer, middle, inner):
            states.append(_drawn(store, registry))
            ungroup_universal_composition(store, registry, root)
            forward.append(_drawn(store, registry))
        last = forward[-1]
        for step in reversed(range(len(states))):
            undo_universal_change(store, registry)
            assert _drawn(store, registry) == states[step], ("undo", step)
        for step in range(len(states)):
            redo_universal_change(store, registry)
            assert _drawn(store, registry) == forward[step], ("redo", step)
    finally:
        store.close()
    store, registry = restore_universal_application(
        resolve_map_path(), CellStore(path), key_provider=_provider()
    )
    try:
        assert _drawn(store, registry) == last
    finally:
        store.close()


def _founder(registry):
    import nodelang.universal_application as application_module

    authority = registry.authorization
    context = application_module._active_authentication_context(authority, None)
    return authority.broker.resolve(context).subject_root


def _two_cards_grouped(store, registry):
    from nodelang.universal_application import instantiate_universal_definition

    definitions = registry.standard_library.definition_roots
    cards = tuple(
        instantiate_universal_definition(
            store, registry, definitions[0], x=400.0 + 300 * i, y=1400.0
        )[0]
        for i in range(2)
    )
    set_universal_selection(store, registry, cards, focus_root=cards[-1])
    group, _ = group_universal_selection(store, registry, title="Held")
    return group


def test_undo_refuses_a_replayed_superseded_grant_on_the_group():
    """nested-undo v2 (1): a reconciler-shaped grant dropped from the
    registry is accepted only at the generation the broker last recorded.
    Replaying generation 1 after a signed revocation (generation 2) is a
    replay: undo refuses it and writes nothing."""
    from nodelang.cell_identity import (
        grant_authority_relationship,
        read_authority_relationship,
        revoke_authority_relationship,
    )
    from nodelang.cell_protocols import (
        prepare_remove_relation_members,
        read_relation,
    )
    from nodelang.universal_cell import Conflict

    store, registry = build_universal_application(resolve_map_path())
    group = _two_cards_grouped(store, registry)
    undo_universal_change(store, registry)
    redo_universal_change(store, registry)
    authority = registry.authorization
    identity = authority.identity_protocol
    broker = authority.relationship_broker
    admin = _founder(registry)
    root = grant_authority_relationship(
        store, identity, broker, broker.mint_from_trusted_administrator(admin),
        relationship_id="test:replayed-grant:" + group,
        source_root=authority.resource_reader_principal_root,
        target_root=registry.view_sessions[admin].subject_root,
        kind="delegation",
        tenant_root=authority.tenant_root,
        scope_root=group,
        action_roots=(authority.protocol.actions["read"],),
        administrator_root=admin,
        reason="reconciler-shaped grant, generation 1",
    )
    first = store.snapshot()
    relationship = read_authority_relationship(first, identity, root)
    material = (
        relationship.state_incidence, relationship.changed_by_incidence,
        relationship.changed_at_root, relationship.generation_root,
        relationship.reason_root, relationship.digest_root,
        relationship.signature_root, relationship.key_reference_root,
        relationship.key_version_root,
    )
    revoke_authority_relationship(
        store, identity, broker, broker.mint_from_trusted_administrator(admin),
        root, administrator_root=admin, reason="generation 2 supersedes",
    )
    snapshot = store.snapshot()
    registration = next(
        member.incidence_id
        for member in read_relation(snapshot, identity.root_id, budget=100_000)
        if member.participant_id == root
    )
    drop = prepare_remove_relation_members(
        snapshot, identity.root_id, (registration,), budget=100_000
    )
    store.commit(snapshot.revision, replace=(
        *(first.cells[cell_id] for cell_id in material), *drop.replace,
    ))
    before = store.revision
    with pytest.raises(Conflict, match="gained references"):
        undo_universal_change(store, registry)
    assert store.revision == before


def test_a_forged_focus_shaped_relation_is_not_view_state():
    """nested-undo v2 (2): only a focus record the attention registry holds
    is this view's state. The same members under another root are not."""
    import nodelang.universal_application as application_module
    from nodelang.cell_protocols import compose_relation_cells, read_relation

    store, registry = build_universal_application(resolve_map_path())
    _two_cards_grouped(store, registry)
    view_session = registry.view_sessions[_founder(registry)]
    snapshot = store.snapshot()
    real = snapshot.cells[view_session.focus_incidence].link1
    members = read_relation(snapshot, real, budget=100_000)
    forged_root = "app:focus:forged" + real.rpartition(":")[2]
    forged = compose_relation_cells(
        ((member.role_id, member.participant_id) for member in members),
        relation_id=forged_root,
    )
    store.commit(store.revision, create=forged.cells)
    snapshot = store.snapshot()
    view_state = application_module._view_selection_cell(
        registry, view_session, store
    )
    assert view_state(snapshot, members[0].incidence_id)
    forged_incidence = read_relation(
        snapshot, forged_root, budget=100_000
    )[0].incidence_id
    assert not view_state(snapshot, forged_incidence)


def test_founder_undo_and_redo_never_touch_a_member_view(tmp_path):
    """nested-undo v2 (4): the founder groups, ungroups, undoes and redoes;
    the member view selection, focus, lens and visibility Cells and its
    canvas stay exactly as they were, and reading it writes nothing."""
    from nodelang.cell_protocols import read_relation
    from nodelang.universal_application import (
        instantiate_universal_definition,
        promote_universal_resource_lifecycle,
        provision_universal_view_session,
    )
    from nodelang.universal_cell import NULL_CELL_ID, Cell

    store, registry = build_universal_application(
        resolve_map_path(), CellStore(tmp_path / "member.sqlite3"),
        key_provider=_provider(),
    )
    try:
        shared, _ = instantiate_universal_definition(
            store, registry, registry.standard_library.definition_roots[2],
            x=420.0, y=640.0,
        )
        promote_universal_resource_lifecycle(store, registry, shared, "shared")
        member = "test:nested-undo:member"
        store.commit(store.revision, create=(
            Cell(member, NULL_CELL_ID, NULL_CELL_ID, b"Member"),
        ))
        provision_universal_view_session(
            store, registry, member, visible_roots=(shared,)
        )
        authority = registry.authorization
        context = authority.broker.mint_authenticated_context(
            member,
            principal_roots=(authority.member_principal_root,),
            tenant_root=authority.tenant_root,
            assurance_root=authority.assurance_root,
            lifetime_seconds=600,
        )
        view = registry.view_sessions[member]

        def member_state():
            snapshot = store.snapshot()
            ids = {view.focus_incidence}
            for relation in (
                view.selection_state_root, view.visibility_root,
                view.properties_lens_root,
            ):
                for item in read_relation(snapshot, relation, budget=100_000):
                    ids.add(item.incidence_id)
            revision = store.revision
            canvas = project_universal_canvas(
                store, registry, authentication_context=context
            )
            assert store.revision == revision, "a member read wrote the graph"
            return (
                {cell_id: snapshot.cells[cell_id] for cell_id in sorted(ids)},
                json.dumps({"nodes": canvas["nodes"], "wires": canvas["wires"]},
                           sort_keys=True),
            )

        held = member_state()
        domains = registry.map.domains
        set_universal_selection(
            store, registry, (domains["brain"], domains["ui"]),
            focus_root=domains["ui"],
        )
        inner, _ = group_universal_selection(store, registry, title="Inner")
        assert member_state() == held
        set_universal_selection(
            store, registry, (inner, domains["canvas"]),
            focus_root=domains["canvas"],
        )
        middle, _ = group_universal_selection(store, registry, title="Middle")
        assert member_state() == held
        ungroup_universal_composition(store, registry, middle)
        assert member_state() == held
        for _ in range(3):
            undo_universal_change(store, registry)
            assert member_state() == held
        for _ in range(3):
            redo_universal_change(store, registry)
            assert member_state() == held
    finally:
        store.close()
