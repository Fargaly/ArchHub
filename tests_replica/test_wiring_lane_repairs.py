"""Engine cards wire, show every parameter, seed once, and read the graph's pick.

Audit 2026-09-24 at 72bcaae, each finding pinned by one court here:

- An engine card's out/in sockets carried the read-only role, and the canvas
  projected an input socket as never connectable, so Studio could not finish
  a wire between two engine cards.
- Studio's parameter panel received only the first four rows, so Revit
  Walls' ``session`` row never reached it.
- The flagship seed matched its marker only on the level on screen, so a seed
  run inside another scope placed a second set of twelve cards.
- Sketch Lines declared no ``max_gap`` row, though its engine reads one.
- Think and Vision cards read ARCHHUB_AGENT_MODEL only, never the composer
  pick the graph holds.
- The Parameter engine read ``value`` while its card declares ``default``.
"""
from __future__ import annotations

import pytest

from nodelang import universal_application as app
from nodelang.map_import import resolve_map_path
from nodelang.stem_graph_evaluation import StemNode, evaluate_stem_graph
from nodelang.universal_application import (
    build_universal_application,
    connect_universal_roots,
    project_universal_canvas,
    set_universal_scope,
)
from nodelang.universal_pipeline import (
    _SEED_MARKER,
    _canvas_roots,
    _owner_properties,
    create_engine_node,
    run_universal_pipeline,
    seed_wall_pipeline,
)


@pytest.fixture()
def graph():
    store, registry = build_universal_application(resolve_map_path())
    try:
        yield store, registry
    finally:
        store.close()


def _node(projection, root):
    return next(node for node in projection["nodes"] if node["id"] == root)


def test_a_new_engine_out_wires_to_another_engine_in(graph):
    store, registry = graph
    first = create_engine_node(store, registry, title="Watch A", engine="lines.watch")["root"]
    second = create_engine_node(store, registry, title="Watch B", engine="lines.watch", x=560.0)["root"]
    projection = project_universal_canvas(store, registry)
    out = next(port for port in _node(projection, first)["ports"]
               if port["id"] == "app:pipeline-interface:%s:source" % first.rsplit(":", 1)[-1])
    socket = next(port for port in _node(projection, second)["ports"]
                  if port["id"] == "app:pipeline-interface:%s:target" % second.rsplit(":", 1)[-1])
    assert out["connectable"] is True and out["read_only"] is False
    assert socket["connectable"] is True and socket["read_only"] is False
    wire_root, _revision = connect_universal_roots(
        store, registry, first, second,
        source_interface=out["id"], target_interface=socket["id"],
    )
    wires = project_universal_canvas(store, registry)["wires"]
    assert any(
        wire["id"] == wire_root and wire["source"] == first and wire["target"] == second
        for wire in wires
    )


def test_every_parameter_row_reaches_the_parameter_payload(graph):
    store, registry = graph
    seed_wall_pipeline(store, registry)
    projection = project_universal_canvas(store, registry)
    walls = next(node for node in projection["nodes"] if node["label"] == "Revit Walls")
    labels = [row["label"] for row in walls["params"]]
    assert len(labels) > 4
    assert "session" in labels


def test_seeding_in_two_scopes_leaves_one_set(graph):
    store, registry = graph
    first = seed_wall_pipeline(store, registry)
    set_universal_scope(store, registry, registry.map.domains["models"])
    second = seed_wall_pipeline(store, registry)
    snapshot = store.snapshot()
    owned = _owner_properties(snapshot, registry)
    members = set(_canvas_roots(snapshot, registry)[0])
    markers = [
        rows[_SEED_MARKER][1].strip()
        for root, rows in owned.items()
        if root in members and _SEED_MARKER in rows and rows[_SEED_MARKER][1].strip()
    ]
    assert first["counts"]["placed"] == 12
    assert second["counts"]["placed"] == 0
    assert len(markers) == len(set(markers)) == 12


def test_sketch_lines_seeds_its_max_gap(graph):
    store, registry = graph
    seed_wall_pipeline(store, registry)
    projection = project_universal_canvas(store, registry)
    sketch = next(node for node in projection["nodes"] if node["label"] == "Sketch Lines")
    rows = _owner_properties(store.snapshot(), registry)[sketch["id"]]
    assert rows["max_gap"][1] == "8"


def test_a_blank_model_card_runs_on_the_graph_pick_and_refuses_without_one(graph, monkeypatch):
    store, registry = graph
    monkeypatch.delenv("ARCHHUB_AGENT_MODEL", raising=False)
    root = create_engine_node(store, registry, title="Think", engine="library.think")["root"]
    from nodelang.agent_composer import NO_MODEL_CHOSEN
    from nodelang.library_engines import think
    refused = run_universal_pipeline(
        store, registry, effect_engines={"library.think": think}, only_roots=[root])
    assert (refused["display"].get(root) or refused["pending"].get(root)) == NO_MODEL_CHOSEN

    app.set_universal_composer_model(store, registry, "openrouter/vendor/model-a")
    seen = {}

    def fake_think(params, feeds):
        seen.update(params)
        return {"out": "ok"}, "answered"

    run_universal_pipeline(
        store, registry, effect_engines={"library.think": fake_think}, only_roots=[root])
    assert seen["model"] == "openrouter/vendor/model-a"
    # The pick fills the run only; the card's own row stays what he left.
    assert _owner_properties(store.snapshot(), registry)[root]["model"][1] == ""


def test_parameter_engine_reads_its_declared_default():
    node = StemNode("n:param", "input.parameter", {"name": "width", "default": "240"})
    evaluation = evaluate_stem_graph([node], [], None)
    assert evaluation.display["n:param"] == "240"
    bound = StemNode("n:bound", "input.parameter", {"value": "5", "default": "240"})
    assert evaluate_stem_graph([bound], [], None).display["n:bound"] == "5"


def _age_socket(store, registry, root):
    """Put one socket back in the shape an older build placed it."""
    from nodelang.universal_application import prepare_append_relation_members
    snapshot = store.snapshot()
    read_only = registry.roles["read-only"]
    patch = prepare_append_relation_members(
        snapshot, root, ((read_only, read_only),), budget=64)
    store.commit(snapshot.revision, create=patch.create, replace=patch.replace)


def test_old_read_only_engine_sockets_are_released_once(graph):
    from nodelang import commit_intent
    from nodelang.universal_pipeline import release_pipeline_socket_read_only
    store, registry = graph
    first = create_engine_node(store, registry, title="Old A", engine="lines.watch")["root"]
    second = create_engine_node(store, registry, title="Old B", engine="lines.watch", x=560.0)["root"]
    sockets = [
        "app:pipeline-interface:%s:%s" % (root.rsplit(":", 1)[-1], side)
        for root in (first, second) for side in ("source", "target")
    ]
    for socket in sockets:
        _age_socket(store, registry, socket)
    old = project_universal_canvas(store, registry)
    assert not any(
        port["connectable"] for root in (first, second)
        for port in _node(old, root)["ports"] if port["id"] in sockets
    )
    with commit_intent.declare(commit_intent.MIGRATION, actor="court", reason="old sockets"):
        assert release_pipeline_socket_read_only(store, registry) == 4
    migrated = store.revision
    with commit_intent.declare(commit_intent.MIGRATION, actor="court", reason="second boot"):
        assert release_pipeline_socket_read_only(store, registry) == 0
    assert store.revision == migrated
    wire_root, _revision = connect_universal_roots(
        store, registry, first, second,
        source_interface=sockets[0], target_interface=sockets[3],
    )
    assert any(wire["id"] == wire_root for wire in project_universal_canvas(store, registry)["wires"])
