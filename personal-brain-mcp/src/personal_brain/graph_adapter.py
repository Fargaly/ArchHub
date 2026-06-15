"""MemoryGraphStore — the app knowledge-graph surface over the ONE brain.db.

ONE-SYSTEM-PLAN-BEFORE-BUILD mandate (founder, 2026-05-28). This module is the
real resolution of the two-store debt that storage.py's header used to defer
("does NOT yet import ArchHub's app.memory.graph.MemoryGraph"). Until now
ArchHub ran TWO disjoint stores:

  (a) app/memory/graph.py  MemoryGraph → graph.sqlite   (the AgDR-0042
      knowledge graph the extractors write: capability / decision / skill /
      turn nodes + typed edges), and
  (b) personal-brain-mcp  BrainStore  → brain.db        (the daemon's
      fragment + skill store the MCP serves on :8473).

They were reconciled only by the manual band-aid tools/brain_unify.py, which
had to be RE-RUN forever to copy (a)→(b). That is exactly the "two systems
doing one job is a planning bug" smell.

This adapter UNIFIES them to one store WITHOUT minting a third: it presents the
*exact* MemoryGraph read/write API, but every node/edge is persisted as a
Fragment row in the SAME brain.db the daemon already serves, using the
canonical ``graph:<node.id>`` id + kind mapping brain_unify.unify()
established. So a node written through this surface is the SAME row a
``BrainStore.get_fragment("graph:<id>")`` reads, and a fact written as a
Fragment via the brain is visible here as a graph node. ONE graph, two
interchangeable surfaces, no sync, no schema migration.

Drop-in compatibility: ``MemoryGraphStore`` exposes ``add_node``, ``add_edge``,
``add_nodes``, ``add_edges``, ``get_node``, ``all_nodes``, ``all_edges``,
``neighbors``, ``count_nodes``, ``count_edges``, ``remove_node``,
``remove_edge``, ``transaction``, ``to_dict``, ``close`` — the surface
``app/memory/graph.py`` callers (extractors, query, sync, bridge) use. It
returns the same ``MemoryNode`` / ``MemoryEdge`` dataclasses the app defines,
so callers can't tell they're talking to brain.db.

The app's ``MemoryGraph.open(brain_store=...)`` routes here; absent a brain
store it keeps its standalone graph.sqlite behaviour (this package must still
import + run with no ArchHub app on the path — it ships standalone too).
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterable, Iterator, Optional

from .models import Scope, Visibility
from .storage import BrainStore


# ── MemoryNode / MemoryEdge shapes ───────────────────────────────────────
#
# The app defines these as frozen dataclasses in app/memory/graph.py. This
# package ships standalone (no guarantee ArchHub/app is importable), so we
# resolve the REAL classes when the app IS on the path and otherwise fall
# back to local structurally-identical stand-ins. Either way the public
# objects this adapter returns quack exactly like MemoryNode / MemoryEdge
# (``.id/.kind/.label/.props`` and ``.source/.target/.relation/.confidence/
# .props``), so a caller that has the real classes gets real instances and a
# standalone caller gets compatible ones.


def _resolve_app_graph_types():
    try:  # pragma: no cover - depends on app being importable
        from memory.graph import (  # type: ignore
            MemoryNode as _Node,
            MemoryEdge as _Edge,
            Confidence as _Conf,
        )
        return _Node, _Edge, _Conf
    except Exception:
        return None, None, None


_AppNode, _AppEdge, _AppConfidence = _resolve_app_graph_types()


if _AppNode is not None:
    MemoryNode = _AppNode  # type: ignore
    MemoryEdge = _AppEdge  # type: ignore
    Confidence = _AppConfidence  # type: ignore
else:  # standalone fallback — structurally identical to app/memory/graph.py.
    from dataclasses import dataclass, field
    from enum import Enum

    class Confidence(str, Enum):  # type: ignore[no-redef]
        EXTRACTED = "EXTRACTED"
        INFERRED = "INFERRED"

    @dataclass(frozen=True)
    class MemoryNode:  # type: ignore[no-redef]
        id: str
        kind: str
        label: str = ""
        props: dict = field(default_factory=dict)

        def to_dict(self) -> dict:
            return {
                "id": self.id, "kind": self.kind,
                "label": self.label or self.id, "props": dict(self.props),
            }

    @dataclass(frozen=True)
    class MemoryEdge:  # type: ignore[no-redef]
        source: str
        target: str
        relation: str
        confidence: "Confidence" = Confidence.EXTRACTED
        props: dict = field(default_factory=dict)

        def to_dict(self) -> dict:
            return {
                "source": self.source, "target": self.target,
                "relation": self.relation,
                "confidence": self.confidence.value,
                "props": dict(self.props),
            }


def _coerce_confidence(raw: Any) -> "Confidence":
    """Coerce a raw confidence value (str / enum) to the resolved Confidence
    enum, defaulting to EXTRACTED on anything unrecognised."""
    if isinstance(raw, Confidence):
        return raw
    try:
        return Confidence(str(raw))
    except Exception:
        return Confidence.EXTRACTED


# ── MemoryGraphStore ─────────────────────────────────────────────────────


class MemoryGraphStore:
    """A ``MemoryGraph``-compatible view backed entirely by one ``BrainStore``
    (brain.db). Construct directly from a store, or via ``open(...)`` to build
    the store for you.

    Every method mirrors ``app/memory/graph.py``'s ``MemoryGraph`` so this is a
    drop-in. Writes go through ``BrainStore``'s graph-node / graph-edge
    primitives, which persist Fragments using the canonical ``graph:`` id
    convention — meaning reads/writes here and on the brain hit the SAME rows.
    """

    def __init__(
        self,
        store: BrainStore,
        *,
        owner_user: str = "founder",
        scope: Scope = Scope.PROJECT,
        visibility: Visibility = Visibility.PRIVATE,
        contributing_agent: str = "memory_graph",
        own_store: bool = False,
    ):
        self._store = store
        self._owner_user = owner_user
        self._scope = scope
        self._visibility = visibility
        self._agent = contributing_agent
        # When True, close() also closes the underlying store (we opened it).
        self._own_store = own_store

    # ── factory ──

    @classmethod
    def open(
        cls,
        path: "Optional[str]" = None,
        *,
        owner_user: str = "founder",
        scope: Scope = Scope.PROJECT,
    ) -> "MemoryGraphStore":
        """Open a unified graph backed by a brain.db at ``path`` (default =
        the brain's OS-appropriate location; ``:memory:`` for tests)."""
        store = BrainStore.open(path)
        return cls(store, owner_user=owner_user, scope=scope, own_store=True)

    @property
    def store(self) -> BrainStore:
        """The underlying brain store (the ONE backing store)."""
        return self._store

    def close(self) -> None:
        if self._own_store:
            self._store.close()

    # ── write API (mirrors MemoryGraph) ──

    def add_node(self, node: "MemoryNode") -> None:
        """Upsert a node by id — persisted as a Fragment in brain.db."""
        self._store.write_graph_node(
            node,
            owner_user=self._owner_user,
            scope=self._scope,
            visibility=self._visibility,
            contributing_agent=self._agent,
        )

    def add_edge(self, edge: "MemoryEdge") -> None:
        """Upsert an edge by (source, target, relation). Both endpoints must
        already exist — raises ValueError otherwise, exactly like
        MemoryGraph.add_edge (keeps the unified graph consistent so a BFS
        terminates cleanly)."""
        if not self._node_exists(edge.source):
            raise ValueError(
                f"add_edge: source node {edge.source!r} not in graph")
        if not self._node_exists(edge.target):
            raise ValueError(
                f"add_edge: target node {edge.target!r} not in graph")
        self._store.write_graph_edge(
            edge.source, edge.target, edge.relation,
            confidence=_coerce_confidence(edge.confidence).value,
            props=dict(edge.props or {}),
            owner_user=self._owner_user,
            scope=self._scope,
            contributing_agent=self._agent,
        )
        # Refresh the incident-edge sidecars on both endpoint node fragments
        # so extra["graph_edges"] stays in sync (legacy-reader parity).
        self._refresh_node_sidecar(edge.source)
        if edge.target != edge.source:
            self._refresh_node_sidecar(edge.target)

    def add_nodes(self, nodes: "Iterable[MemoryNode]") -> int:
        n = 0
        for node in nodes:
            self.add_node(node)
            n += 1
        return n

    def add_edges(self, edges: "Iterable[MemoryEdge]") -> int:
        n = 0
        for edge in edges:
            if not self._node_exists(edge.source):
                raise ValueError(
                    f"add_edges: source {edge.source!r} missing "
                    f"(processed {n} edges)")
            if not self._node_exists(edge.target):
                raise ValueError(
                    f"add_edges: target {edge.target!r} missing "
                    f"(processed {n} edges)")
            self.add_edge(edge)
            n += 1
        return n

    def remove_node(self, node_id: str) -> bool:
        return self._store.remove_graph_node(node_id)

    def remove_edge(self, source: str, target: str, relation: str) -> bool:
        removed = self._store.remove_graph_edge(source, target, relation)
        if removed:
            self._refresh_node_sidecar(source)
            if target != source:
                self._refresh_node_sidecar(target)
        return removed

    # ── read API (mirrors MemoryGraph) ──

    def get_node(self, node_id: str) -> "Optional[MemoryNode]":
        d = self._store.get_graph_node(node_id)
        return self._dict_to_node(d) if d is not None else None

    def all_nodes(self, kind: "Optional[str]" = None) -> "list[MemoryNode]":
        return [self._dict_to_node(d) for d in self._store.all_graph_nodes(kind=kind)]

    def all_edges(self, relation: "Optional[str]" = None) -> "list[MemoryEdge]":
        return [self._dict_to_edge(d) for d in self._store.all_graph_edges(relation=relation)]

    def neighbors(
        self, node_id: str, *, direction: str = "out",
        relation: "Optional[str]" = None,
    ) -> "list[MemoryEdge]":
        return [
            self._dict_to_edge(d)
            for d in self._store.graph_edges_incident(
                node_id, direction=direction, relation=relation
            )
        ]

    def count_nodes(self, kind: "Optional[str]" = None) -> int:
        return self._store.count_graph_nodes(kind=kind)

    def count_edges(self, relation: "Optional[str]" = None) -> int:
        return self._store.count_graph_edges(relation=relation)

    # ── batch transactions ──

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Group writes. BrainStore auto-commits per write (autocommit conn),
        so this is a structural no-op kept for MemoryGraph API parity — code
        that wraps extractor batches in ``with g.transaction():`` keeps
        working unchanged."""
        yield

    # ── serialisation (graphify-compatible) ──

    def to_dict(self) -> dict:
        return {
            "nodes": [n.to_dict() for n in self.all_nodes()],
            "edges": [e.to_dict() for e in self.all_edges()],
        }

    # ── internal ──

    def _node_exists(self, node_id: str) -> bool:
        return self._store.get_graph_node(node_id) is not None

    def _refresh_node_sidecar(self, node_id: str) -> None:
        """Re-read the node + re-write it so its extra['graph_edges'] picks up
        the latest incident edges (write_graph_node recomputes the sidecar)."""
        d = self._store.get_graph_node(node_id)
        if d is None:
            return
        self._store.write_graph_node(
            self._dict_to_node(d),
            owner_user=self._owner_user,
            scope=self._scope,
            visibility=self._visibility,
            contributing_agent=self._agent,
        )

    @staticmethod
    def _dict_to_node(d: dict) -> "MemoryNode":
        return MemoryNode(
            id=d["id"], kind=d.get("kind", ""),
            label=d.get("label", "") or "",
            props=dict(d.get("props") or {}),
        )

    @staticmethod
    def _dict_to_edge(d: dict) -> "MemoryEdge":
        return MemoryEdge(
            source=d["source"], target=d["target"],
            relation=d["relation"],
            confidence=_coerce_confidence(d.get("confidence", "EXTRACTED")),
            props=dict(d.get("props") or {}),
        )


__all__ = ["MemoryGraphStore", "MemoryNode", "MemoryEdge", "Confidence"]
