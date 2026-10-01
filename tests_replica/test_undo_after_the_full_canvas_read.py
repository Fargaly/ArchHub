"""Undo takes back a placed card after the FULL canvas read has bound it.

The installed app (a9e534e, real window, hidden desktop, 2026-10-01) still
refused Undo after placing a card. The canvas read binds several Interaction
families to every visible card, not only scope: appearance (role target),
relation-members and topology (role input), scope (control + input). The
earlier court drew scope only. This court runs every binder the server's
canvas read runs, checks the same families the real graph showed, then undoes.
"""
from __future__ import annotations

import pytest

from nodelang import universal_application as ua
from nodelang.map_import import resolve_map_path
from nodelang.universal_pipeline import create_engine_node

@pytest.fixture()
def graph():
    store, registry = ua.build_universal_application(resolve_map_path())
    try:
        yield store, registry
    finally:
        store.close()


def _on_canvas(store, registry, root):
    return any(node["id"] == root for node in ua.project_universal_canvas(store, registry)["nodes"])


def _full_read(store, registry):
    """The server's canvas read, in its order and with its exact arguments
    (application_server.py:17258-17396); any binder failure fails the court."""
    subject = next(iter(registry.view_sessions))
    ua.ensure_universal_properties_panel_interactions(store, registry, subject)
    ua.ensure_universal_relation_form_interactions(store, registry, subject)
    projection = ua.project_universal_canvas(store, registry)
    for binder in (
        ua.ensure_universal_instantiation_interactions,
        ua.ensure_universal_relation_composer_interactions,
        ua.ensure_universal_property_interactions,
        ua.ensure_universal_operational_transition_interactions,
        ua.ensure_universal_presentation_interactions,
        ua.ensure_universal_interface_value_interactions,
        ua.ensure_universal_relation_member_interactions,
        ua.ensure_universal_topology_interactions,
        ua.ensure_universal_composition_interactions,
        ua.ensure_universal_history_interactions,
        ua.ensure_universal_inspector_lens_interactions,
        ua.ensure_universal_scope_interactions,
    ):
        binder(store, registry, subject, projection)


def _families_naming(store, root):
    families = set()
    for cid, cell in store.snapshot().cells.items():
        if cid.startswith("app:interaction:") and ":incidence:" in cid and cell.link1 == root:
            families.add(cid.split(":")[2])
    return families


def test_the_full_read_binds_the_same_families_the_real_app_did(graph):
    store, registry = graph
    root = create_engine_node(store, registry, title="Read Probe", engine="lines.watch")["root"]
    _full_read(store, registry)
    snapshot = store.snapshot()
    roles = {(cid.split(":")[2], cell.link0) for cid, cell in snapshot.cells.items()
             if cid.startswith("app:interaction:") and ":incidence:" in cid and cell.link1 == root}
    target = registry.interaction_protocol.role("target")
    control = registry.interaction_protocol.role("control")
    inp = registry.interaction_protocol.role("input")
    # The families and roles the installed app's graph showed for a placed card.
    assert ("appearance", target) in roles, roles
    assert ("relation-members", inp) in roles, roles
    assert ("topology", inp) in roles, roles
    assert ("scope", control) in roles, roles


def test_one_undo_takes_back_a_card_after_the_full_canvas_read(graph):
    store, registry = graph
    root = create_engine_node(store, registry, title="Read Probe", engine="lines.watch")["root"]
    _full_read(store, registry)
    ua.undo_universal_change(store, registry)
    assert not _on_canvas(store, registry, root), "one undo takes the card back"
    ua.redo_universal_change(store, registry)
    assert _on_canvas(store, registry, root), "redo restores it"


def test_a_real_edit_still_blocks_after_the_full_read(graph):
    from nodelang.universal_cell import Cell
    store, registry = graph
    root = create_engine_node(store, registry, title="Read Probe", engine="lines.watch")["root"]
    _full_read(store, registry)
    snapshot = store.snapshot()
    store.commit(snapshot.revision, create=(Cell("court:edit:" + root[-12:], "gm:role:member", root, b""),))
    with pytest.raises(Exception, match="gained references"):
        ua.undo_universal_change(store, registry)
    assert _on_canvas(store, registry, root)
