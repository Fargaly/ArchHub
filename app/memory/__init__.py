"""ArchHub memory — shared knowledge graph (AgDR-0042).

Slice 1 of v1.5 (D1·C, founder picked 2026-05-25): the core data
model + SQLite-backed store. Four extractors + query engine follow in
slices 2-3; project + decision extractors + community detection +
Speckle firm-sync in slices 4-6.

Public surface (slice 1):
    from memory import MemoryGraph, MemoryNode, MemoryEdge, Confidence
    g = MemoryGraph.open()                 # default disk path
    g.add_node(MemoryNode(id='lib:cap:revit.read_walls', kind='capability'))
    g.add_edge(MemoryEdge(source=..., target=..., relation='contains',
                          confidence=Confidence.EXTRACTED))
    g.commit()                             # persist to SQLite
    g.neighbors('lib:cap:revit.read_walls', relation='contains')

This package replaces the four separate stores (library / project /
turns / decisions) with one queryable graph. node_search keeps working
via a back-compat shim shipped in slice 3.
"""
from __future__ import annotations

from .graph import (  # noqa: F401
    MemoryGraph, MemoryNode, MemoryEdge, Confidence, default_graph_path,
)
from .query import query, neighbors_summary  # noqa: F401
from .communities import (  # noqa: F401
    detect_communities, annotate_communities, community_stats,
)

__all__ = [
    "MemoryGraph", "MemoryNode", "MemoryEdge", "Confidence",
    "default_graph_path", "query", "neighbors_summary",
    "detect_communities", "annotate_communities", "community_stats",
]
