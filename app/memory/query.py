"""memory.query — BFS search over the MemoryGraph.

AgDR-0042 slice 3/6 (D1·C). Replaces node_search Jaccard with a
graph-aware ranker: seed by token overlap on labels + props, BFS to
gather neighbours, score by combined token overlap + neighbour weight
+ edge confidence + recency.

Public:

    from memory import MemoryGraph
    from memory.query import query

    g = MemoryGraph.open()
    hits = query(g, "revit wall takeoff", limit=5)
    # → [{id, kind, label, score, why}]

`why` carries a 1-line provenance string the UI / LLM can show:
"matched 'revit' on label; used in 3 prior turns; contained by skill
foo".

Cheap by default — pure SQL + Python; no embeddings, no LLM. Slice 5
(Louvain communities) layers in cluster-aware ranking on top.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Iterable, Optional

from .graph import MemoryGraph, MemoryNode, MemoryEdge, Confidence


# ── tokenisation ─────────────────────────────────────────────────────


# Split on anything non-alphanumeric. Lowercase. Drop short tokens that
# would inflate noise scores (a / an / to / on / …). The same surface
# used for both the question + each node's token bag, so the same
# normalisation falls out either side of the comparison.
_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+")
_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "for", "to", "of", "in",
    "on", "at", "is", "are", "be", "was", "were", "with", "by", "from",
    "as", "that", "this", "it", "its", "i", "me", "my", "we", "us",
    "you", "your", "do", "does", "did", "have", "has", "had", "will",
    "would", "should", "could", "can", "find", "show", "get", "make",
    "give",
}


def _tokens(text: str) -> set[str]:
    if not text:
        return set()
    return {
        w.lower() for w in _TOKEN_RE.findall(text)
        if len(w) > 1 and w.lower() not in _STOPWORDS
    }


def _node_tokens(node: MemoryNode) -> set[str]:
    """Token bag for a node — label + key props (type / category /
    side_effects / name). Skip blob props (in_types lists) so a search
    for 'string' doesn't match every node with a string port."""
    parts = [node.id, node.kind, node.label]
    for k in ("type", "category", "side_effects", "name", "prompt"):
        v = node.props.get(k)
        if isinstance(v, str):
            parts.append(v)
    return _tokens(" ".join(p for p in parts if p))


# ── scoring ──────────────────────────────────────────────────────────


# Tunables. Conservative defaults — over-tuning here is premature
# until slice 5 community detection lands.
_W_TOKEN_OVERLAP = 10.0   # per shared token
_W_USED_EDGE     = 3.0    # per incoming `used` edge from a turn
_W_CONTAINS_EDGE = 2.0    # per incoming `contains` edge from a skill
_W_RECENCY_TURN  = 1.0    # bonus for being touched by a recent turn
_BFS_MAX_DEPTH   = 2      # neighbour depth from each seed


def _confidence_weight(c: Confidence) -> float:
    """INFERRED edges count for less than EXTRACTED — the query layer
    is the chokepoint where this matters."""
    return 1.0 if c == Confidence.EXTRACTED else 0.4


# ── main entry ───────────────────────────────────────────────────────


def query(graph: MemoryGraph,
           question: str,
           *,
           limit: int = 10,
           kinds: Optional[Iterable[str]] = None,
           min_score: float = 0.0,
           ) -> list[dict]:
    """Rank nodes by relevance to `question`.

    Args:
      graph     — open MemoryGraph.
      question  — free-text user question. Tokenised + matched against
                  each node's label + key props.
      limit     — max results to return. Default 10.
      kinds     — optional filter (only return results of these kinds).
                  E.g. ('skill',) for Skill-only matches; ('capability',
                  'skill') for either.
      min_score — drop results below this score. Default 0 (keep all
                  that matched at least one token).

    Returns: list of {id, kind, label, score, why} sorted by score
    descending. Empty list when nothing matched. `why` is a short
    provenance string suitable for the LLM tool result or UI.
    """
    q_tokens = _tokens(question)
    if not q_tokens:
        return []

    kind_filter = set(kinds) if kinds else None

    # 1. Seed pass — every node that shares ≥1 token with the question
    # becomes a seed with a base score proportional to overlap.
    seeds: dict[str, float] = {}
    why: dict[str, list[str]] = defaultdict(list)
    for node in graph.all_nodes():
        overlap = q_tokens & _node_tokens(node)
        if not overlap:
            continue
        score = _W_TOKEN_OVERLAP * len(overlap)
        seeds[node.id] = score
        # Token-overlap is the strongest signal — surface it in `why`.
        why[node.id].append(
            f"matched {sorted(overlap)[:3]} on label/props")

    # 2. BFS — for each seed, walk outgoing + incoming edges up to
    # _BFS_MAX_DEPTH and accumulate weighted scores onto reached nodes.
    # Confidence + relation type determine the per-hop weight.
    frontier: dict[str, float] = dict(seeds)
    for _depth in range(_BFS_MAX_DEPTH):
        next_frontier: dict[str, float] = defaultdict(float)
        for node_id, base_score in frontier.items():
            for edge in graph.neighbors(node_id, direction="both"):
                other = edge.target if edge.source == node_id else edge.source
                conf_w = _confidence_weight(edge.confidence)
                # Edge-relation specific bonuses on the OTHER node.
                if edge.relation == "used":
                    bonus = _W_USED_EDGE * conf_w
                    if node_id in seeds:  # only emit `why` on first hop
                        why[other].append("used by a recent turn")
                elif edge.relation == "contains":
                    bonus = _W_CONTAINS_EDGE * conf_w
                    if edge.target == other and node_id in seeds:
                        why[other].append(f"contained by skill matching '{node_id[len('lib:skill:'):]}'")
                elif edge.relation == "called":
                    bonus = _W_USED_EDGE * conf_w
                else:
                    bonus = 1.0 * conf_w
                # Decay each hop so distant nodes don't outscore direct
                # matches. Linear decay is enough at depth 2.
                next_frontier[other] += bonus * (0.5 ** (_depth + 1))
        # Merge the next frontier into the seed scores.
        for node_id, add in next_frontier.items():
            seeds[node_id] = seeds.get(node_id, 0.0) + add
        frontier = dict(next_frontier)

    # 3. Filter + rank.
    results: list[dict] = []
    for node_id, score in seeds.items():
        if score < min_score:
            continue
        node = graph.get_node(node_id)
        if node is None:
            continue
        if kind_filter and node.kind not in kind_filter:
            continue
        results.append({
            "id": node_id,
            "kind": node.kind,
            "label": node.label or node_id,
            "score": round(score, 3),
            "why": "; ".join(why.get(node_id) or ["bfs-reachable"]),
        })
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:limit]


def neighbors_summary(graph: MemoryGraph, node_id: str) -> dict:
    """Companion helper — for an LLM that picked a result, return its
    in/out neighbours grouped by relation. Lets the LLM ask "tell me
    more about lib:skill:foo" without a follow-up tool call to query."""
    node = graph.get_node(node_id)
    if node is None:
        return {"status": "error", "error": f"unknown node {node_id!r}"}
    out_groups: dict[str, list[str]] = defaultdict(list)
    in_groups: dict[str, list[str]] = defaultdict(list)
    for edge in graph.neighbors(node_id, direction="out"):
        out_groups[edge.relation].append(edge.target)
    for edge in graph.neighbors(node_id, direction="in"):
        in_groups[edge.relation].append(edge.source)
    return {
        "status": "ok",
        "node": node.to_dict(),
        "out": {k: v for k, v in out_groups.items()},
        "in":  {k: v for k, v in in_groups.items()},
    }
