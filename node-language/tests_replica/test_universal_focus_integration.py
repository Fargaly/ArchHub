"""Courts binding the visual canvas to the persistent Focus composition."""
from __future__ import annotations

import pytest

from nodelang.cell_attention import active_focus, read_focus
from nodelang.cell_protocols import read_relation
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    build_universal_application,
    project_universal_canvas,
    restore_universal_application,
    set_universal_selection,
)
from nodelang.universal_cell import CellStore, InvalidCell


def _provider():
    provider = MemorySigningKeyProvider(
        "archhub.local.relationship-authority", b"f" * 32
    )
    provider.add_key("archhub.local.court-attestation", b"g" * 32)
    return provider


def _lens_focus_root(store, registry):
    members = read_relation(
        store.snapshot(), registry.properties_lens_root, budget=100_000
    )
    return next(
        member.participant_id for member in members
        if member.role_id == registry.roles["focus"]
    )


def test_properties_points_to_real_active_focus_not_directly_to_a_card():
    store, registry = build_universal_application(resolve_map_path())
    projection = project_universal_canvas(store, registry)
    focus_root = _lens_focus_root(store, registry)
    focus = read_focus(store.snapshot(), registry.attention_protocol, focus_root)

    assert focus_root == projection["focus"]["root"]
    assert focus_root != projection["selected"]
    assert focus.state_root == registry.attention_protocol.state("active")
    assert focus.actor_root == registry.authorization.subject_root
    assert focus.session_root == registry.authorization.session.root_id
    assert focus.scope_root == registry.canvas_root
    assert focus.primary_root == projection["selected"]
    assert projection["focus"]["reasons"] == [{
        "root": "app:focus-reason:initial-view",
        "label": "Initial application focus",
    }]
    assert projection["focus"]["consent_evidence"] == [
        registry.authorization.session.root_id
    ]


def test_selection_focus_pointer_and_history_change_in_one_store_revision():
    store, registry = build_universal_application(resolve_map_path())
    old_root = _lens_focus_root(store, registry)
    selected = tuple(registry.visible_roots[2:5])
    before = store.revision

    revision = set_universal_selection(
        store, registry, selected, focus_root=selected[-1]
    )
    assert revision == before + 1
    projection = project_universal_canvas(store, registry)
    new_root = _lens_focus_root(store, registry)
    assert new_root != old_root
    assert projection["focus"]["root"] == new_root
    assert tuple(projection["focus"]["selected"]) == selected
    assert projection["focus"]["primary"] == selected[-1]
    assert projection["focus"]["previous"] == old_root
    assert set(projection["selection"]) == set(selected)
    assert read_focus(
        store.snapshot(), registry.attention_protocol, old_root
    ).state_root == registry.attention_protocol.state("resolved")
    assert active_focus(
        store.snapshot(), registry.attention_protocol,
        session_root=registry.authorization.session.root_id,
    ).root_id == new_root


def test_invalid_selection_cannot_publish_partial_focus_or_selection_state():
    store, registry = build_universal_application(resolve_map_path())
    before = store.revision
    focus_before = _lens_focus_root(store, registry)
    with pytest.raises(InvalidCell, match="outside the active canvas"):
        set_universal_selection(
            store,
            registry,
            (registry.authorization.policy_root,),
            focus_root=registry.authorization.policy_root,
        )
    assert store.revision == before
    assert _lens_focus_root(store, registry) == focus_before


def test_visible_focus_reason_is_an_inspectable_root_not_explanatory_text_only():
    store, registry = build_universal_application(resolve_map_path())
    before = project_universal_canvas(store, registry)
    reason_root = before["focus"]["reasons"][0]["root"]
    previous_focus = before["focus"]["root"]

    set_universal_selection(store, registry, (), focus_root=reason_root)
    projection = project_universal_canvas(store, registry)
    assert projection["selected"] == reason_root
    assert projection["selected_title"] == "Initial application focus"
    assert projection["focus"]["primary"] == reason_root
    assert projection["focus"]["previous"] == previous_focus


def test_active_focus_and_properties_binding_survive_close_and_reopen(tmp_path):
    path = tmp_path / "persistent-focus.sqlite3"
    provider = _provider()
    store, registry = build_universal_application(
        resolve_map_path(), CellStore(path), key_provider=provider
    )
    selected = tuple(registry.visible_roots[5:8])
    set_universal_selection(
        store, registry, selected, focus_root=selected[-1]
    )
    expected_focus = _lens_focus_root(store, registry)
    expected_revision = store.revision
    store.close()

    reopened = CellStore(path)
    reopened, restored = restore_universal_application(
        resolve_map_path(), reopened, key_provider=provider
    )
    assert reopened.revision == expected_revision
    assert _lens_focus_root(reopened, restored) == expected_focus
    projection = project_universal_canvas(reopened, restored)
    assert projection["focus"]["root"] == expected_focus
    assert projection["focus"]["primary"] == selected[-1]
    assert set(projection["selection"]) == set(selected)
    assert active_focus(
        reopened.snapshot(), restored.attention_protocol,
        session_root=restored.authorization.session.root_id,
    ).root_id == expected_focus
