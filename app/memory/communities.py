"""Community detection — cluster the MemoryGraph for "god-node" surfacing.

AgDR-0042 slice 5/6 (D1·C). Surfaces clusters of densely-connected
nodes so the Library UI can group them under collapsible sections
("Your wall workflows", "Your render workflows", etc.) without
manual tagging.

Implementation choice: greedy connected-components over the subset of
edges deemed "structural" (configurable; default EXTRACTED + the
non-noisy relations). Real Louvain modularity-maximisation is
overkill at our scale (~hundreds of nodes per firm in v1) and adds a
networkx dep we don't otherwise need. The community ids returned
here are stable across re-runs given the same graph, since they're
derived from a deterministic node-id sort.

Followups (slice 5 still — but post-MVP):
  * incremental update — re-running on a delta-modified graph should
    only touch affected communities. Today we recompute from scratch.
  * "god-node" boosting — most-reused capability per community gets a
    label_boost prop the query layer respects.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Optional

from .graph import MemoryGraph, Confidence


# Relations that carry "real" structure (the kind the founder cares
# about for community sections). INFERRED `wires_with` is excluded by
# default — it's combinatorial port-shape inference, not deliberate
# composition; including it merges everything into one giant blob.
_STRUCTURAL_RELATIONS: tuple = (
    "contains",       # skill → cap (skill composition)
    "used",           # turn → cap/skill (usage history)
    "called",         # turn → tool
    "builds_on",      # decision → decision
    "supersedes",     # decision → decision
    "rationale_for",  # decision → cap/skill
)


class _UnionFind:
    """Tiny union-find with path compression + union by rank.

    Inlined rather than imported from any heavyweight dep — the algo
    is < 30 lines + the rest of the file uses it once."""

    def __init__(self):
        self.parent: dict[str, str] = {}
        self.rank: dict[str, int] = {}

    def find(self, x: str) -> str:
        if self.parent.get(x, x) == x:
            self.parent[x] = x
            self.rank.setdefault(x, 0)
            return x
        # Path compression.
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1


def detect_communities(graph: MemoryGraph,
                        *,
                        relations: Optional[Iterable[str]] = None,
                        include_inferred: bool = False,
                        ) -> dict[str, list[str]]:
    """Detect communities in `graph`. Returns {community_id: [node_ids]}.

    Args:
      graph             — open MemoryGraph.
      relations         — iterable of relation strings to treat as
                          structural edges. Default = _STRUCTURAL_RELATIONS
                          (contains, used, called, builds_on, supersedes,
                          rationale_for).
      include_inferred  — if True, INFERRED-confidence edges also fuse
                          communities. Default False (INFERRED edges
                          tend to merge unrelated clusters via
                          accidental port-shape matches).

    Community id format: `community:<smallest-node-id-in-cluster>`.
    Deterministic given the same graph state — the sort over node ids
    makes the id stable across runs.
    """
    if relations is None:
        relations = _STRUCTURAL_RELATIONS
    relation_set = set(relations)

    uf = _UnionFind()
    # Seed with every node so singletons get their own community id
    # rather than vanishing from the result.
    nodes = graph.all_nodes()
    for n in nodes:
        uf.find(n.id)

    for edge in graph.all_edges():
        if edge.relation not in relation_set:
            continue
        if (not include_inferred
                and edge.confidence == Confidence.INFERRED):
            continue
        uf.union(edge.source, edge.target)

    # Group by root. Use the smallest member id as the community id so
    # the result is stable across runs (independent of UF internal
    # parent assignment).
    groups: dict[str, list[str]] = defaultdict(list)
    for n in nodes:
        groups[uf.find(n.id)].append(n.id)

    out: dict[str, list[str]] = {}
    for _root, members in groups.items():
        members.sort()
        cid = f"community:{members[0]}"
        out[cid] = members
    return out


def annotate_communities(graph: MemoryGraph,
                          **detect_kwargs) -> int:
    """Write community membership into each node's props as
    `community_id`. Returns the number of nodes annotated.

    Idempotent — re-running with the same graph state writes the same
    ids back. Slice 5 query-time consumer (Library UI + ranker boost)
    reads from props rather than re-running detection per request.
    """
    communities = detect_communities(graph, **detect_kwargs)
    # Invert {cid: [members]} → {member: cid}
    member_to_cid: dict[str, str] = {}
    for cid, members in communities.items():
        for m in members:
            member_to_cid[m] = cid
    # Upsert via add_node (preserves all other props).
    from .graph import MemoryNode
    with graph.transaction():
        for n in graph.all_nodes():
            cid = member_to_cid.get(n.id, "")
            new_props = dict(n.props)
            new_props["community_id"] = cid
            graph.add_node(MemoryNode(
                id=n.id, kind=n.kind, label=n.label, props=new_props))
    return len(member_to_cid)


def community_stats(graph: MemoryGraph,
                     **detect_kwargs) -> list[dict]:
    """Per-community summary: id, size, dominant_kind, sample labels.

    Returned sorted by size descending so the Library UI shows the
    biggest cluster first ("Your wall workflows · 14 items" before
    "Your wan_i2v experiments · 2 items").
    """
    communities = detect_communities(graph, **detect_kwargs)
    out: list[dict] = []
    for cid, members in communities.items():
        kinds = defaultdict(int)
        labels = []
        for mid in members:
            node = graph.get_node(mid)
            if node is None:
                continue
            kinds[node.kind] += 1
            if len(labels) < 3:
                labels.append(node.label or node.id)
        dominant = max(kinds.items(), key=lambda kv: kv[1])[0] if kinds else ""
        out.append({
            "id": cid,
            "size": len(members),
            "dominant_kind": dominant,
            "sample_labels": labels,
        })
    out.sort(key=lambda c: c["size"], reverse=True)
    return out
