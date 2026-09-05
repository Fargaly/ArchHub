"""Every card the seed declares must reach the canvas carrying an engine.

Three losses stood behind this court, all of them silent:

The seed adopted a node by its human-readable TITLE. The grand map
publishes a domain titled "Connectors"; the seed adopted that domain,
wrote no engine row onto it, and skipped its own twelfth card. Twelve
were declared and eleven ran, and nothing anywhere said so.

The engine one card names lived only inside the HTTP handler, so the
launcher's boot run could not find it and that card read "engine
baboom.presence is pending" until the founder clicked Run.

The flagship chain shipped with empty inputs, so all four of its nodes
pended at every boot and the founder's first open showed nothing working.

So: the declared engines must be ones the LAUNCHER's engine set holds
(both sets computed here, never restated), re-seeding an existing graph
must adopt and complete rather than skip, the seed must report its
counts, and the samples the chain reads must be there to read.
"""
from __future__ import annotations

import os

import pytest

from nodelang.map_import import resolve_map_path
from nodelang.pipeline_engines import PIPELINE_ENGINES
from nodelang.universal_application import (
    build_universal_application,
    project_universal_canvas,
)
from nodelang.universal_pipeline import (
    _SEED,
    _SEED_MARKER,
    _graph_engines,
    _owner_properties,
    create_engine_node,
    seed_wall_pipeline,
)


def launcher_engines(store, registry) -> set[str]:
    """What the launcher's run can actually reach.

    launch_archhub_test.py hands run_universal_pipeline PIPELINE_ENGINES,
    and the run merges its own graph engines in. Both sides are computed
    here: a court that restated the list would pass while the launcher
    stayed blind to a card.
    """
    return set(PIPELINE_ENGINES) | set(_graph_engines(store, registry))


@pytest.fixture(scope="module")
def graph():
    """One fresh universal application, built once for this file."""
    store, registry = build_universal_application(resolve_map_path())
    try:
        yield store, registry
    finally:
        store.close()


@pytest.fixture(scope="module")
def historical(graph):
    """A graph in the shape the pre-fix seed left behind.

    Cards placed by title, with no marker row and with the flagship
    chain's inputs blank, and no "Connectors" card at all, because the
    grand-map domain of that title had already swallowed it.
    """
    store, registry = graph
    before = {}
    for title, x, y, properties in _SEED:
        engine = properties["engine"]
        if engine not in PIPELINE_ENGINES or title == "Connector Status":
            # The two BABOOM cards named engines the library never held,
            # and the connector card is the one that was lost: none of the
            # three can be part of the graph this fixture reproduces.
            continue
        blanked = {
            label: ("" if label.endswith("_path") else value)
            for label, value in properties.items()
            if label not in (_SEED_MARKER, "engine")
        }
        answer = create_engine_node(
            store, registry, title=title, engine=engine, x=x, y=y,
            properties=blanked,
        )
        before[title] = answer["root"]
    return before


@pytest.fixture(scope="module")
def seeded(graph, historical):
    store, registry = graph
    return seed_wall_pipeline(store, registry)


def test_every_seeded_card_names_an_engine_the_launcher_knows(graph):
    store, registry = graph
    known = launcher_engines(store, registry)
    declared = {
        str(properties["engine"]) for _title, _x, _y, properties in _SEED
    }
    assert declared, "the seed declares no cards at all"
    assert declared <= known, (
        "seeded engines the launcher cannot run: %s"
        % sorted(declared - known)
    )


def test_the_boot_run_can_answer_baboom_presence(graph):
    store, registry = graph
    # It used to exist only inside the HTTP handler, so the launcher's own
    # run left the card pending until someone clicked Run.
    engines = _graph_engines(store, registry)
    assert "baboom.presence" in engines
    outputs, shown = engines["baboom.presence"]({}, {})
    assert "runtime session" in shown
    assert "active_runtime_sessions" in outputs["out"]


def test_reseeding_adopts_the_existing_cards_and_completes_them(
    graph, historical, seeded
):
    store, registry = graph
    assert seeded["skipped"] == [], seeded["skipped"]
    adopted = set(seeded["adopted"])
    assert adopted == set(historical), (
        "a card already on the canvas was not adopted: %s"
        % sorted(set(historical) - adopted)
    )
    for title, root in historical.items():
        assert seeded["placed"][title] == root, (
            "%s was placed a second time instead of adopted" % title
        )
    # Adoption without completion is the original defect: the rows the
    # adopted card was missing must have been written onto it.
    assert seeded["counts"]["completed"] > 0
    owned = _owner_properties(store.snapshot(), registry)
    for title, _x, _y, properties in _SEED:
        root = seeded["placed"][title]
        rows = owned.get(root) or {}
        for label, value in properties.items():
            assert label in rows, "%s lost its %s row" % (title, label)
            if str(value).strip():
                assert rows[label][1].strip(), (
                    "%s.%s stayed blank" % (title, label)
                )
        assert rows["engine"][1] == properties["engine"]
        assert rows[_SEED_MARKER][1] == properties[_SEED_MARKER]


def test_a_stranger_of_the_same_title_is_never_adopted(graph, seeded):
    store, registry = graph
    projection = project_universal_canvas(store, registry)
    owned = _owner_properties(store.snapshot(), registry)
    seeded_roots = set(seeded["placed"].values())
    strangers = [
        str(node["id"]) for node in projection.get("nodes", ())
        if str(node["id"]) not in seeded_roots
        and (owned.get(str(node["id"])) or {}).get(_SEED_MARKER)
    ]
    assert strangers == [], strangers
    # The grand map's own "Connectors" domain is the stranger that took the
    # twelfth card: it must still be a domain, with no engine on it.
    for node in projection.get("nodes", ()):
        if str(node.get("label")) != "Connectors":
            continue
        assert "engine" not in (owned.get(str(node["id"])) or {})
    stamped = [
        marker for marker in (
            (owned.get(str(node["id"])) or {}).get(_SEED_MARKER, ("", ""))[1]
            for node in projection.get("nodes", ())
        ) if marker
    ]
    assert len(stamped) == len(set(stamped)) == len(_SEED), (
        "the canvas carries %d marked cards for %d declared"
        % (len(stamped), len(_SEED))
    )


def test_the_seed_reports_what_it_placed_adopted_and_skipped(seeded):
    counts = seeded["counts"]
    assert set(counts) == {
        "declared", "placed", "adopted", "completed", "skipped",
    }
    assert counts["declared"] == len(_SEED)
    assert (
        counts["placed"] + counts["adopted"] + counts["skipped"]
        == counts["declared"]
    ), counts
    assert len(seeded["placed"]) == counts["declared"]


def test_the_chain_reads_a_sample_that_is_actually_there():
    named = {
        (title, label): str(value)
        for title, _x, _y, properties in _SEED
        for label, value in properties.items()
        if label.endswith("_path")
    }
    assert named, "the chain declares no input file at all"
    for (title, label), path in named.items():
        assert path.strip(), "%s.%s ships blank" % (title, label)
        assert os.path.isfile(path), "%s.%s: no file at %s" % (
            title, label, path
        )
        with open(path, "rb") as handle:
            assert handle.read(1), path


def test_the_flagship_chain_answers_from_the_shipped_sample():
    pytest.importorskip("cv2")
    from nodelang.pipeline_engines import sketch_lines, watch_lines

    parameters = {
        label: str(value)
        for title, _x, _y, properties in _SEED
        for label, value in properties.items()
        if title == "Sketch Lines"
    }
    produced, shown = sketch_lines(parameters, {})
    assert produced["out"], shown
    _passed, watched = watch_lines({}, {"in": produced["out"]})
    assert watched.startswith("%d lines" % len(produced["out"]))
