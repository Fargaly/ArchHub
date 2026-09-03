"""Courts for the session-owned, Cell-native relation composer."""
from __future__ import annotations

import nodelang.universal_application as universal_application_module

from nodelang.cell_protocols import prepare_append_relation_members
from nodelang.cell_relation_composer import read_relation_composer_draft
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    build_universal_application,
    instantiate_universal_relation_composer,
    project_universal_canvas,
    set_universal_selection,
    undo_universal_change,
    update_universal_relation_composer,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell


def _admit_terminal_participant(store, registry) -> str:
    participant_root = "court:relation-composer:terminal"
    store.commit(store.revision, create=(
        Cell(participant_root, NULL_CELL_ID, NULL_CELL_ID, b"Court value"),
    ))
    canvas_patch = prepare_append_relation_members(
        store.snapshot(),
        registry.canvas_root,
        ((registry.roles["member"], participant_root),),
        budget=100_000,
    )
    store.commit(
        store.revision,
        create=canvas_patch.create,
        replace=canvas_patch.replace,
    )
    view = registry.view_sessions[registry.authorization.subject_root]
    administrator = registry.authorization.subject_root
    universal_application_module._issue_resource_audience_bindings(
        store,
        registry.authorization,
        resource_roots=(participant_root,),
        lifecycle_root=(
            registry.standard_library.lifecycle_protocol.states["wip"]
        ),
        owner_root=view.subject_root,
        administrator_root=administrator,
    )
    grants = universal_application_module._issue_view_projection_grants(
        store,
        registry.authorization,
        subject_root=view.subject_root,
        visibility_root=view.visibility_root,
        target_roots=(participant_root,),
        administrator_root=administrator,
    )
    snapshot = store.snapshot()
    visibility_patch = prepare_append_relation_members(
        snapshot,
        view.visibility_root,
        ((registry.roles["visible"], participant_root),),
        budget=100_000,
    )
    session_patch = prepare_append_relation_members(
        snapshot,
        view.root_id,
        ((registry.roles["relation"], root) for root in grants),
        budget=100_000,
    )
    store.commit(
        snapshot.revision,
        create=(*visibility_patch.create, *session_patch.create),
        replace=(*visibility_patch.replace, *session_patch.replace),
    )
    return participant_root


def _complete_composer(store, registry):
    projection = project_universal_canvas(store, registry)
    definition = next(
        item for item in projection["catalog"]
        if item["name"] == "Model Descriptor"
    )
    set_universal_selection(store, registry, (), focus_root=definition["id"])
    while True:
        composer = project_universal_canvas(
            store, registry
        )["selected_definition"]["composer"]
        empty = next((
            (role, entry)
            for role in composer["roles"]
            for entry in role["entries"]
            if not entry["value"]
        ), None)
        if empty is None:
            break
        role, entry = empty
        update_universal_relation_composer(
            store,
            registry,
            definition["id"],
            "select",
            role_root=role["role"],
            entry_root=entry["id"],
            participant_root=entry["choices"][0]["id"],
        )
    update_universal_relation_composer(
        store,
        registry,
        definition["id"],
        "position",
        x=420,
        y=260,
    )
    return definition


def test_relation_draft_values_and_position_are_cells_not_browser_state():
    store, registry = build_universal_application(resolve_map_path())
    participant = _admit_terminal_participant(store, registry)
    definition = _complete_composer(store, registry)
    view = registry.view_sessions[registry.authorization.subject_root]
    draft = read_relation_composer_draft(
        store.snapshot(), registry.relation_composer_protocol, view.root_id
    )
    assert draft is not None
    assert draft.definition_root == definition["id"]
    assert (draft.x, draft.y) == (420.0, 260.0)
    assert draft.entries
    assert all(entry.participant_root is not None for entry in draft.entries)
    assert participant in {
        entry.participant_root for entry in draft.entries
    }


def test_relation_creation_uses_and_clears_graph_draft_and_undo_restores_it():
    store, registry = build_universal_application(resolve_map_path())
    _admit_terminal_participant(store, registry)
    definition = _complete_composer(store, registry)
    view = registry.view_sessions[registry.authorization.subject_root]
    before = read_relation_composer_draft(
        store.snapshot(), registry.relation_composer_protocol, view.root_id
    )
    created_root, revision = instantiate_universal_relation_composer(
        store, registry, definition["id"]
    )
    assert revision == store.revision
    assert created_root in {
        node["id"] for node in project_universal_canvas(store, registry)["nodes"]
    }
    cleared = read_relation_composer_draft(
        store.snapshot(), registry.relation_composer_protocol, view.root_id
    )
    assert cleared is not None
    assert cleared.definition_root is None
    assert cleared.entries == ()
    assert cleared.x is None and cleared.y is None

    undo_universal_change(store, registry)
    restored = read_relation_composer_draft(
        store.snapshot(), registry.relation_composer_protocol, view.root_id
    )
    assert restored == before
    assert created_root not in {
        node["id"] for node in project_universal_canvas(store, registry)["nodes"]
    }
