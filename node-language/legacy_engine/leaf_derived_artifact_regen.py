"""LEAF — SPEC.md §5 made COURT-ENFORCEABLE: the graph is the single source of
truth; a derived artifact (cache / index / host shim) is allowed ONLY if it is a
DETERMINISTIC function of the graph and DELETE-AND-REGENERATE yields it
BIT-IDENTICAL, holding ZERO node-able logic. Anything that diverges from what the
graph regenerates is a FORBIDDEN second source -> banned / reverted.

This leaf USES the REAL engine (`node_lang.Graph`, kind `ui_render`) — it does
NOT add to it. The `ui_render` node already COMPUTES the toolbar HTML from the
`accent` node + the `ui_element` nodes. That computed HTML is the *only* logic;
the cache file is pure downstream bytes.

  1. BUILD a small graph whose `ui_render` node computes the toolbar HTML from
     element/accent nodes.
  2. WRITE that computed output to a DERIVED file (a cache), recording its sha256.
  3. ALLOWED   — delete the cache, REGENERATE it from the graph, assert the bytes
                 are BIT-IDENTICAL (same sha256)  -> ALLOWED_REGEN_IDENTICAL.
  4. FORBIDDEN — hand-edit the cache to diverge from the graph output, run
                 court_artifact_ok(graph, render_node, path) :=
                   (regenerate_from_graph(graph, render_node) == file_bytes);
                 assert it returns FALSE (divergence = forbidden 2nd source)
                 -> FORBIDDEN_SECOND_SOURCE_DETECTED.
  5. The GRAPH ITSELF never changed in either case — the artifact is downstream,
     disposable. Asserted by snapshotting `g.to_session()` before/after.

The check is a deterministic function of the graph + the file on disk — that IS
the court rule: a derived artifact must prove delete-and-regenerate-identical, or
it is a forbidden second source.

Run:
  cd <NODE_LANGUAGE_ROOT>
  PYTHONIOENCODING=utf-8 python leaf_derived_artifact_regen.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from . import node_lang  # the REAL engine — class Graph, kind "ui_render" computes the HTML

CACHE = HERE / "_derived_toolbar.cache.html"   # the DERIVED artifact (disposable)
RENDER_NODE = "toolbar"                          # the ui_render node id


def build_graph() -> node_lang.Graph:
    """A small graph whose `ui_render` node COMPUTES the toolbar HTML from an
    accent (colour) node + element nodes. The graph is the single source."""
    g = node_lang.Graph()
    g.add("accent", "accent", params={"color": "#d97757"})        # app colour, as a node
    g.add("e_save", "ui_element", params={"type": "button", "label": "Save"})
    g.add("e_sync", "ui_element", params={"type": "button", "label": "Sync"})
    g.add("e_revert", "ui_element", params={"type": "button", "label": "Revert"})
    g.add(RENDER_NODE, "ui_render", params={
        "accent": "accent",
        "elements": ["e_save", "e_sync", "e_revert"],
    })
    return g


def regenerate_from_graph(g: node_lang.Graph, render_node: str) -> bytes:
    """The artifact's ONLY producer: the graph computes it. Deterministic — the
    bytes are a pure function of the graph's current state. UTF-8, no extras."""
    return g.eval(render_node).encode("utf-8")


def write_cache(g: node_lang.Graph, render_node: str, path: Path) -> str:
    """Write the graph-computed artifact to the derived file; return its sha256."""
    data = regenerate_from_graph(g, render_node)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def court_artifact_ok(g: node_lang.Graph, render_node: str, path: Path) -> bool:
    """THE §5 COURT RULE. A derived artifact is ALLOWED iff what the graph
    regenerates is BIT-IDENTICAL to the file on disk. Diverge -> FALSE
    (forbidden second source). Pure: (regen_from_graph == file_bytes)."""
    if not path.exists():
        return False
    return regenerate_from_graph(g, render_node) == path.read_bytes()


def snapshot(g: node_lang.Graph) -> str:
    """A stable fingerprint of the graph itself (NOT the artifact), to prove the
    graph never changed while the downstream artifact was deleted / hand-edited."""
    return hashlib.sha256(
        json.dumps(g.to_session(), sort_keys=True).encode("utf-8")
    ).hexdigest()


def main() -> int:
    g = build_graph()
    graph_before = snapshot(g)

    # 2) WRITE the computed output to the DERIVED file, record sha256.
    sha_written = write_cache(g, RENDER_NODE, CACHE)
    print(f"BUILT       graph source -> ui_render({RENDER_NODE!r}) computed "
          f"{CACHE.stat().st_size} bytes, sha256={sha_written[:16]}…")

    # 3) ALLOWED case: DELETE the cache, REGENERATE from the graph, assert
    #    BIT-IDENTICAL (same sha256).
    CACHE.unlink()
    assert not CACHE.exists(), "cache must actually be gone before regenerate"
    sha_regen = write_cache(g, RENDER_NODE, CACHE)
    assert sha_regen == sha_written, (
        "REGENERATE must be bit-identical", sha_written, sha_regen)
    assert court_artifact_ok(g, RENDER_NODE, CACHE), "court must PASS the regen"
    print(f"ALLOWED_REGEN_IDENTICAL  delete+regenerate -> same sha256="
          f"{sha_regen[:16]}…  (deterministic function of the graph; court PASS)")

    # 4) FORBIDDEN case: HAND-EDIT the cache so it diverges from the graph output;
    #    the court check must return FALSE (divergence = forbidden 2nd source).
    tampered = CACHE.read_bytes().replace(b"Save", b"Deploy-To-Prod")  # a second source
    assert tampered != CACHE.read_bytes(), "tamper must actually change the bytes"
    CACHE.write_bytes(tampered)
    ok = court_artifact_ok(g, RENDER_NODE, CACHE)
    assert ok is False, ("FORBIDDEN: hand-edited cache must be REFUTED", ok)
    print("FORBIDDEN_SECOND_SOURCE_DETECTED  hand-edited cache diverges from "
          "graph regen -> court_artifact_ok=False  (banned/revert)")

    # The cache is disposable: regenerate from the graph reverts the tamper.
    write_cache(g, RENDER_NODE, CACHE)
    assert court_artifact_ok(g, RENDER_NODE, CACHE), "regenerate must heal the tamper"

    # 5) THE GRAPH ITSELF never changed in either case — artifact is downstream.
    graph_after = snapshot(g)
    assert graph_after == graph_before, (
        "graph must be UNCHANGED by cache delete/tamper", graph_before, graph_after)
    print(f"GRAPH_UNCHANGED  source fingerprint identical before/after "
          f"({graph_before[:16]}…)  -> the artifact is downstream, disposable")

    # cleanup the disposable artifact
    CACHE.unlink(missing_ok=True)

    print("LEAF_OK  §5 enforced: deterministic regen ALLOWED bit-identical; "
          "divergent hand-edit FORBIDDEN (second source detected); graph "
          "is the single source of truth, never mutated by the cache.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
