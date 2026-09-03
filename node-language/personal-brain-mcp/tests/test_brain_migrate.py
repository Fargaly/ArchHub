"""Tests for tools/brain_migrate — the ONE-TIME graph.sqlite → brain.db
migration that replaces the ongoing brain_unify band-aid.

Pins the ONE-SYSTEM-PLAN-BEFORE-BUILD contract (founder, 2026-05-28):
  1. a first run folds every graph node into the canonical brain.db AND
     writes the `migrated_from_graph` marker;
  2. a SECOND run is a marker-gated NO-OP (ran=False) — a fresh machine
     never needs the band-aid twice;
  3. `force=True` re-runs but stays idempotent (no duplicate fragments —
     the underlying unify() content-prechecks);
  4. when graph.sqlite is ABSENT, brain.db is already the sole store and the
     migration no-ops cleanly (the desired single-store end-state);
  5. `migrate()` reuses the proven `brain_unify.unify()` mapping so the
     graph nodes become `graph:<id>` fragments in brain.db.

Hermetic: real on-disk temp paths (the marker + idempotency need a durable
brain.db round-trip), never the user's live stores.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_TOOLS = _REPO / "tools"
_APP = _REPO / "app"
for _p in (_TOOLS, _APP):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from memory.graph import MemoryGraph, MemoryEdge, MemoryNode  # noqa: E402
from personal_brain.storage import BrainStore  # noqa: E402

import brain_migrate  # noqa: E402


# ── fixtures ─────────────────────────────────────────────────────────


def _seed_graph(path: Path) -> int:
    """Write a tiny 3-node / 1-edge graph at `path`. Returns node count."""
    g = MemoryGraph.open(path)
    try:
        g.add_node(MemoryNode(id="cap:revit.read_walls", kind="capability",
                              label="Read walls", props={"host": "revit"}))
        g.add_node(MemoryNode(id="dec:speckle-wires", kind="decision",
                              label="Speckle wires", props={"agdr": "0012"}))
        g.add_node(MemoryNode(id="skill:revfix", kind="skill",
                              label="revfix flow"))
        g.add_edge(MemoryEdge(source="cap:revit.read_walls",
                              target="dec:speckle-wires", relation="informs"))
        return g.count_nodes()
    finally:
        g.close()


@pytest.fixture
def paths(tmp_path: Path):
    graph_path = tmp_path / "graph.sqlite"
    brain_path = tmp_path / "brain.db"
    n = _seed_graph(graph_path)
    return graph_path, brain_path, n


# ── tests ────────────────────────────────────────────────────────────


def test_first_run_migrates_and_writes_marker(paths):
    graph_path, brain_path, n = paths
    res = brain_migrate.migrate(graph_path=graph_path, brain_path=brain_path)

    assert res["ran"] is True
    assert res["graph_nodes"] == n == 3
    assert res["imported"] == 3      # 3 fresh fragments
    assert res["skipped"] == 0
    # canonical store now holds the graph nodes as graph:<id> fragments
    store = BrainStore.open(brain_path)
    try:
        assert store.count_fragments() == 3
        assert store.get_fragment("graph:cap:revit.read_walls") is not None
        # marker stamped so a fresh run knows it is done
        marker = store.get_meta(brain_migrate._MARKER_KEY)
        assert marker is not None and "graph_nodes" in marker
    finally:
        store.close()


def test_second_run_is_marker_gated_noop(paths):
    graph_path, brain_path, _ = paths
    first = brain_migrate.migrate(graph_path=graph_path, brain_path=brain_path)
    assert first["ran"] is True

    second = brain_migrate.migrate(graph_path=graph_path, brain_path=brain_path)
    assert second["ran"] is False
    assert second["noop_reason"] == "already migrated (marker present)"
    # no second copy — the band-aid is not needed twice
    assert second["fragments_after"] == 3


def test_force_reruns_but_stays_idempotent(paths):
    graph_path, brain_path, _ = paths
    brain_migrate.migrate(graph_path=graph_path, brain_path=brain_path)

    forced = brain_migrate.migrate(
        graph_path=graph_path, brain_path=brain_path, force=True,
    )
    assert forced["ran"] is True
    # forced re-run updates content but NEVER duplicates rows
    assert forced["fragments_before"] == forced["fragments_after"] == 3
    assert forced["imported"] == 3 and forced["skipped"] == 0 \
        or forced["skipped"] == 3   # content-precheck may skip unchanged


def test_absent_graph_is_clean_noop(tmp_path: Path):
    # The desired single-store end-state: no staging graph at all.
    brain_path = tmp_path / "brain.db"
    BrainStore.open(brain_path).close()  # materialise an empty canonical store
    res = brain_migrate.migrate(
        graph_path=tmp_path / "does-not-exist.sqlite",
        brain_path=brain_path,
    )
    assert res["ran"] is False
    assert "already sole store" in res["noop_reason"]
    assert res["fragments_after"] == 0
