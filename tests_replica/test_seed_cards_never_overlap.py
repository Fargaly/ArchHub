"""The flagship seed places its cards without overlap (UI audit 2026-09-28, 09-fit-and-overlap).

Revit Sessions sat 90 units above BABOOM Status in the same column, and Sketch Lines (six rows)
ran into CAD Lines below it. The seed now places on a 320 x 260 grid. The table only decides
where a card is CREATED: a graph seeded by the old table keeps every card where it is when the
new code re-seeds it (old graph + new code, not only a fresh fixture).
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


def test_a_graph_seeded_by_the_old_table_is_never_moved(graph, monkeypatch):
    store, registry = graph
    old = (("Sketch Lines", 240.0, 200.0), ("CAD Lines", 240.0, 380.0), ("Line Watcher", 560.0, 290.0),
           ("Revit Walls", 880.0, 290.0), ("Revit Sessions", 880.0, 470.0), ("Brain Recall", 240.0, 560.0),
           ("Brain Facts", 560.0, 560.0), ("BABOOM Status", 880.0, 560.0), ("BABOOM Presence", 1200.0, 560.0),
           ("Skills Library", 240.0, 740.0), ("Thinking Chain", 560.0, 740.0), ("Connector Status", 880.0, 740.0))
    points = {title: (x, y) for title, x, y in old}
    current = pipeline._SEED
    monkeypatch.setattr(pipeline, "_SEED", tuple((t, *points[t], p) for t, _x, _y, p in current))
    pipeline.seed_wall_pipeline(store, registry)
    before = {label: (node["x"], node["y"]) for label, node in _seeded(store, registry).items()}
    assert before == points, "the fixture is the old graph"
    monkeypatch.setattr(pipeline, "_SEED", current)
    again = pipeline.seed_wall_pipeline(store, registry)
    assert again["counts"]["placed"] == 0
    after = {label: (node["x"], node["y"]) for label, node in _seeded(store, registry).items()}
    assert after == before
