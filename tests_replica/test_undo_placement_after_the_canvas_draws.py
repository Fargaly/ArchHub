"""Undo takes back a placed card after the canvas has drawn it.

On 2026-10-01 the installed app (build aa41122, real window on an isolated
desktop) placed a library card, then refused Undo with 400 "created Cell
gained references after the recorded transaction". Drawing the canvas binds
one scope Interaction to every visible card; that record names the new card
(role control/input) and the undo guard read it as a later edit. The earlier
courts never drew the canvas between placement and undo.
"""
from __future__ import annotations

import pytest

from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    build_universal_application,
    ensure_universal_scope_interactions,
    project_universal_canvas,
    redo_universal_change,
    undo_universal_change,
)
from nodelang.universal_pipeline import create_engine_node


@pytest.fixture()
def graph():
    store, registry = build_universal_application(resolve_map_path())
    try:
        yield store, registry
    finally:
        store.close()


def _on_canvas(store, registry, root):
    return any(node["id"] == root for node in project_universal_canvas(store, registry)["nodes"])


def _draw(store, registry):
    """What the canvas read does: project, then bind the visible controls."""
    subject = next(iter(registry.view_sessions))
    ensure_universal_scope_interactions(store, registry, subject, project_universal_canvas(store, registry))


def _references_to(store, root):
    snapshot = store.snapshot()
    return [cid for cid, cell in snapshot.cells.items() if root in (cell.link0, cell.link1)]


def test_the_canvas_draw_binds_an_interaction_to_the_placed_card(graph):
    store, registry = graph
    root = create_engine_node(store, registry, title="Drawn Probe", engine="lines.watch")["root"]
    before = set(_references_to(store, root))
    _draw(store, registry)
    added = set(_references_to(store, root)) - before
    assert any(cid.startswith("app:interaction:") for cid in added), (
        "the draw must reproduce the real app's write: an Interaction naming the card", added)


def test_one_undo_takes_back_a_card_the_canvas_has_drawn(graph):
    store, registry = graph
    root = create_engine_node(store, registry, title="Drawn Probe", engine="lines.watch")["root"]
    _draw(store, registry)
    undo_universal_change(store, registry)
    assert not _on_canvas(store, registry, root), "one undo takes the drawn card back"
    redo_universal_change(store, registry)
    assert _on_canvas(store, registry, root), "redo puts the same card back"


def test_a_real_edit_on_the_placed_card_still_blocks_its_undo(graph):
    """The tolerance is for Interaction bindings only; an edit still pins the card."""
    from nodelang.universal_cell import Cell
    store, registry = graph
    root = create_engine_node(store, registry, title="Drawn Probe", engine="lines.watch")["root"]
    _draw(store, registry)
    snapshot = store.snapshot()
    store.commit(snapshot.revision, create=(Cell("court:edit:" + root[-12:], "gm:role:member", root, b""),))
    with pytest.raises(Exception, match="gained references"):
        undo_universal_change(store, registry)
    assert _on_canvas(store, registry, root)


def test_a_lookalike_interaction_incidence_still_blocks_undo(graph):
    """Only a verified Interaction this view bound is tolerated; a Cell that
    merely reads like one (no record, no registration) stays a dependency."""
    from nodelang.universal_cell import Cell
    store, registry = graph
    root = create_engine_node(store, registry, title="Drawn Probe", engine="lines.watch")["root"]
    _draw(store, registry)
    snapshot = store.snapshot()
    drawn = next(cell for cid, cell in snapshot.cells.items()
                 if cid.startswith("app:interaction:") and ":incidence:" in cid and cell.link1 == root)
    store.commit(snapshot.revision, create=(Cell("app:interaction:forged:incidence:0", drawn.link0, root, b""),))
    with pytest.raises(Exception, match="gained references"):
        undo_universal_change(store, registry)
    assert _on_canvas(store, registry, root)


def test_a_registered_evidence_member_naming_the_card_still_blocks_undo(graph):
    """A valid, registered incidence of the drawn Interaction in any role other
    than its control/input binding of this card is a later dependency."""
    from nodelang.cell_protocols import prepare_append_relation_members
    from nodelang.universal_cell import Cell
    store, registry = graph
    root = create_engine_node(store, registry, title="Drawn Probe", engine="lines.watch")["root"]
    _draw(store, registry)
    snapshot = store.snapshot()
    record = next(cid.rpartition(":incidence:")[0] for cid, cell in snapshot.cells.items()
                  if cid.startswith("app:interaction:") and ":incidence:" in cid and cell.link1 == root)
    patch = prepare_append_relation_members(
        snapshot, record, ((registry.interaction_protocol.role("evidence"), root),))
    old, new = patch.incidence_ids[0], record + ":incidence:999"
    rename = lambda c: Cell(new if c.id == old else c.id, new if c.link0 == old else c.link0,
                            new if c.link1 == old else c.link1, c.atom)
    store.commit(snapshot.revision, create=tuple(map(rename, patch.create)),
                 replace=tuple(map(rename, patch.replace)))
    with pytest.raises(Exception, match="gained references"):
        undo_universal_change(store, registry)
    assert _on_canvas(store, registry, root)
