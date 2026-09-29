"""The flagship seed places its cards without overlap (UI audit 2026-09-28, 09-fit-and-overlap).

Revit Sessions sat 90 units above BABOOM Status in the same column, and Sketch Lines (six rows)
ran into CAD Lines below it. The seed now places on a 320 x 260 grid. The table only decides
where a card is CREATED. A graph seeded by the old table has its OVERLAPPING seed cards
re-placed by the canvas-content migration (canvas-clean, 2026-09-28): a card that did not
overlap keeps its exact old point, a card the user pinned never moves, and after that no
re-seed moves anything (old graph + new code, not only a fresh fixture).
"""
from __future__ import annotations

import pytest

from nodelang import universal_pipeline as pipeline
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import build_universal_application, project_universal_canvas

CARD_W = 210.0  # studio.html projectStudioCanvas
GAP = 24.0


def _card_h(node) -> float:
    rows = [row for row in node.get("params", ()) if row.get("label") not in ("engine", "status")]
    return max(110.0, 60.0 + 22.0 * len(rows))


@pytest.fixture()
def graph():
    store, registry = build_universal_application(resolve_map_path())
    try:
        yield store, registry
    finally:
        store.close()


def _seeded(store, registry):
    titles = {title for title, *_ in pipeline._SEED}
    return {node["label"]: node for node in project_universal_canvas(store, registry)["nodes"]
            if node.get("label") in titles}


def test_a_fresh_seed_places_no_card_over_another(graph):
    store, registry = graph
    pipeline.seed_wall_pipeline(store, registry)
    cards = list(_seeded(store, registry).values())
    assert len(cards) == len(pipeline._SEED)
    clashes = []
    for i, a in enumerate(cards):
        for b in cards[i + 1:]:
            if (a["x"] < b["x"] + CARD_W + GAP and b["x"] < a["x"] + CARD_W + GAP and
                    a["y"] < b["y"] + _card_h(b) + GAP and b["y"] < a["y"] + _card_h(a) + GAP):
                clashes.append((a["label"], b["label"]))
    assert clashes == []


def test_the_wired_chain_reads_left_to_right_on_one_row():
    at = {title: (x, y) for title, x, y, _ in pipeline._SEED}
    chain = ["Sketch Lines", "Line Watcher", "Revit Walls"]
    assert len({at[title][1] for title in chain}) == 1
    assert [at[title][0] for title in chain] == sorted(at[title][0] for title in chain)


# The table a graph seeded before 8cc3463 carries (454e78a / dddccf6).
OLD_TABLE = {"Sketch Lines": (240.0, 200.0), "CAD Lines": (240.0, 380.0), "Line Watcher": (560.0, 290.0),
             "Revit Walls": (880.0, 290.0), "Revit Sessions": (880.0, 470.0)}


def _old_graph(store, registry, monkeypatch):
    """Seed with the OLD table and no migration: the graph as the old code left it."""
    current, settle = pipeline._SEED, pipeline.settle_canvas_content
    monkeypatch.setattr(pipeline, "_SEED", tuple((t, *OLD_TABLE[t], p) for t, _x, _y, p in current))
    monkeypatch.setattr(pipeline, "settle_canvas_content", lambda *_a, **_k: {"done": False})
    pipeline.seed_wall_pipeline(store, registry)
    monkeypatch.setattr(pipeline, "_SEED", current)
    monkeypatch.setattr(pipeline, "settle_canvas_content", settle)


def _rects(store, registry):
    """Each seeded canvas card's rectangle, measured the way the migration measures it."""
    from nodelang.canvas_placement import card_size, drawn_rows
    owned = pipeline._owner_properties(store.snapshot(), registry)
    rects = {}
    for label, node in _seeded(store, registry).items():
        rows = owned[node["id"]]
        rects[label] = (float(rows["position_x"][1]), float(rows["position_y"][1]),
                        *card_size(rows.get("engine", ("", ""))[1], drawn_rows(rows)))
    return rects


def _overlapping(rects):
    from nodelang.canvas_placement import intersects
    return {a for a in rects for b in rects if a != b and intersects(rects[a], rects[b])}


def _migrate(store, registry):
    from nodelang import commit_intent
    with commit_intent.declare(commit_intent.MIGRATION, actor=registry.application_root,
                               reason="court: migrate an old-table graph"):
        return pipeline.settle_canvas_content(store, registry, batch_size=4, pause=0)


def test_an_old_table_graph_keeps_every_point_that_did_not_overlap(graph, monkeypatch):
    store, registry = graph
    _old_graph(store, registry, monkeypatch)
    before = _rects(store, registry)
    assert {label: rect[:2] for label, rect in before.items()} == OLD_TABLE
    clashing = _overlapping(before)
    assert clashing, "the old table overlapped (Sketch Lines ran into CAD Lines)"
    _migrate(store, registry)
    after = _rects(store, registry)
    for label in set(OLD_TABLE) - clashing:
        assert after[label][:2] == OLD_TABLE[label], label
    assert after["Line Watcher"][:2] == (560.0, 290.0)
    assert {label for label in clashing if after[label][:2] != OLD_TABLE[label]}, "no overlapping card moved"
    assert _overlapping(after) == set()
    # A re-seed with the current table changes nothing.
    again = pipeline.seed_wall_pipeline(store, registry)
    assert again["counts"]["placed"] == 0
    assert _rects(store, registry) == after


def test_an_overlapping_card_the_user_pinned_is_never_moved(graph, monkeypatch):
    from nodelang.universal_application import _USER_PLACEMENT, create_universal_property
    store, registry = graph
    _old_graph(store, registry, monkeypatch)
    before = _rects(store, registry)
    assert "CAD Lines" in _overlapping(before)
    cad = _seeded(store, registry)["CAD Lines"]["id"]
    create_universal_property(store, registry, cad, "placed", _USER_PLACEMENT)
    _migrate(store, registry)
    after = _rects(store, registry)
    assert after["CAD Lines"][:2] == OLD_TABLE["CAD Lines"]
    assert _overlapping(after) == set(), "the card that was not pinned stepped off it"