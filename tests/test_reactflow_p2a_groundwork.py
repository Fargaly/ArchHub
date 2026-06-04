"""Canvas substrate — the CUSTOM canvas is the renderer of record (REAL tests).

REWRITTEN 2026-05-28 (MAKE-IT-REAL §7): this file used to PIN DEAD CODE via
INVERTED assertions — it asserted that the abandoned ReactFlow scaffold
(`_readCanvasFlavor`, `NodeCanvasRF_Stub`, the `archhub.canvas` localStorage
key) was ABSENT. Absence-pins give false coverage credit: they pass forever as
long as a never-installed library stays uninstalled, while telling you nothing
about whether the canvas that ACTUALLY ships still works.

Per AgDR-0048 (executed 2026-05-25) the custom canvas — `NodeCanvas` rendering
`NodeRenderer` nodes over an SVG wire layer, with pan/zoom + drag — is the
substrate of record; ReactFlow was never installed. So instead of pinning the
ghost's absence, these tests assert the REAL substrate renders nodes + wires
from `LM_GRAPH` and reacts to graph mutations. A regression that breaks the
node map, the wire layer, or the graphBump-driven recompute now FAILS here.

(The one historical-fact check that the ReactFlow scaffold stays removed is
kept, but reframed: it guards AgDR-0048's decision, not a coverage metric.)
"""
from __future__ import annotations

import re
from pathlib import Path

JSX = Path(__file__).resolve().parents[1] / "app" / "web_ui" / "studio-lm.jsx"
AGDR = Path(__file__).resolve().parents[1] / "docs" / "agdr"


def _src() -> str:
    return JSX.read_text(encoding="utf-8")


# ── 1. The custom canvas substrate component exists + is the renderer ──────

def test_nodecanvas_is_the_substrate_component():
    """`NodeCanvas` is the canvas substrate (AgDR-0048): it takes the graph
    bump counter + focus + library hooks and renders the working surface.

    LAG-ROOT FIX (2026-06-01): NodeCanvas is now `React.memo(NodeCanvasInner,…)`
    so a root re-render that doesn't change its props is skipped (it no longer
    repaints on every streamed token / unrelated root state change). The
    substrate component (which carries the params) is `NodeCanvasInner`."""
    src = _src()
    # The substrate impl carries the params — it's `NodeCanvasInner` after the
    # memo wrap (fall back to a bare `NodeCanvas =` arrow for forward-compat).
    m = re.search(r"const\s+NodeCanvas(?:Inner)?\s*=\s*\(\{([^}]*)\}\)\s*=>", src)
    assert m, "NodeCanvas substrate component must exist"
    params = m.group(1)
    # It is driven by the real canvas props.
    for prop in ("focusId", "setFocusId", "bumpGraph", "graphBump"):
        assert prop in params, f"NodeCanvas must accept `{prop}`"
    # The exported NodeCanvas must be memoized — the lag-root guard that stops
    # an unrelated root re-render from repainting the whole canvas.
    assert re.search(r"const\s+NodeCanvas\s*=\s*React\.memo\(\s*NodeCanvasInner", src), (
        "NodeCanvas must be wrapped in React.memo(NodeCanvasInner, …) so a root "
        "re-render that doesn't change its props is skipped (lag-root fix)")


def test_substrate_renders_nodes_from_LM_GRAPH():
    """The substrate composes the live graph (LM_GRAPH.nodes + user nodes) and
    maps each to a NodeRenderer — i.e. nodes actually paint, derived from real
    graph state, not a static scaffold."""
    src = _src()
    # allNodes = demo graph + user nodes, recomputed on graphBump.
    assert re.search(
        r"const\s+allNodes\s*=\s*React\.useMemo\(\s*\(\)\s*=>\s*\[\s*\.\.\.\(LM_GRAPH\.nodes",
        src,
    ), "allNodes must merge LM_GRAPH.nodes (the live graph) for rendering"
    # Each node is rendered via NodeRenderer in a map over allNodes.
    assert re.search(r"\(allNodes\s*\|\|\s*\[\]\)\.map\(\s*n\s*=>", src), (
        "the substrate must map allNodes → node elements"
    )
    assert "<NodeRenderer" in src, "nodes render through the NodeRenderer component"


def test_substrate_has_real_wire_layer():
    """Wires render in a real SVG layer with <path> elements — the custom wire
    renderer (not a ReactFlow edge)."""
    src = _src()
    assert re.search(r"<svg\b[^>]*>", src), "the substrate must have an SVG wire layer"
    # Wire paths are drawn (imperative path layer per AgDR-0047 §D6).
    assert "pathEls" in src or re.search(r"<path\b", src), (
        "the wire layer must draw <path> elements"
    )


def test_substrate_has_pan_zoom_state():
    """The custom canvas owns its pan + zoom (a ReactFlow viewport would own
    these instead) — proof the substrate is the hand-rolled one."""
    src = _src()
    assert re.search(r"const\s*\[\s*pan\s*,\s*setPan\s*\]\s*=\s*React\.useState", src)
    assert re.search(r"const\s*\[\s*zoom\s*,\s*setZoom\s*\]\s*=\s*React\.useState", src)


def test_graphbump_counter_drives_node_recompute():
    """allNodes recomputes on the `graphBump` COUNTER (not the stable bumpGraph
    callback). This is the real founder bug fix ("ping outlook did nothing"):
    new nodes appear because the memo depends on the changing counter."""
    src = _src()
    # Grab the whole allNodes useMemo statement up to its closing `)`. The body
    # is a single array-spread expression `[...(LM_GRAPH.nodes||[]), ...]`, so
    # the dep array is the LAST `[ ... ]` before the closing paren on that line.
    m = re.search(r"const\s+allNodes\s*=\s*React\.useMemo\((.+?)\)\s*;", src)
    assert m, "allNodes useMemo must exist"
    stmt = m.group(1)
    deps_m = re.search(r",\s*\[([^\]]*)\]\s*$", stmt)
    assert deps_m, f"could not find allNodes dep array in: {stmt!r}"
    deps = deps_m.group(1)
    assert "graphBump" in deps, (
        "allNodes must depend on the graphBump counter so a graph mutation "
        "re-renders the canvas (the 'ping outlook did nothing' fix)"
    )
    # The dep array must not contain the stable bumpGraph CALLBACK (depending on
    # it was the original bug — the memo never re-ran). Allow `graphBump`.
    assert not re.search(r"\bbumpGraph\b", deps), (
        "allNodes must NOT depend on the stable bumpGraph callback (that was "
        "the bug — the memo never re-ran)"
    )


# ── 2. Historical fact: the abandoned ReactFlow scaffold stays removed ─────
#      (AgDR-0048 decision guard — not a coverage metric.)

def test_reactflow_scaffold_stays_removed_per_agdr_0048():
    """AgDR-0048 superseded the 'ReactFlow is the substrate' clause; the inert
    scaffold (flavor toggle + RF stub + its localStorage key) was deleted. This
    guards that DECISION — a future agent shouldn't resurrect a parallel canvas
    engine. (Distinct from the behavior tests above, which prove the real one
    works.)"""
    src = _src()
    # The inert flavor toggle + stub are gone (deleted 2026-05-26 per Q1).
    assert "NodeCanvasRF_Stub" not in src
    assert "const _readCanvasFlavor" not in src
    assert 'data-testid="reactflow-canvas-stub"' not in src


def test_agdr_0048_supersede_doc_exists():
    """The supersede AgDR is on disk + names the renumber chain."""
    agdr = AGDR / "AgDR-0048-supersede-reactflow-lock.md"
    assert agdr.exists(), "AgDR-0048 (the supersede record) must exist"
    text = agdr.read_text(encoding="utf-8")
    assert "renumbered_from" in text
    assert "AgDR-0045" in text and "AgDR-0046" in text
