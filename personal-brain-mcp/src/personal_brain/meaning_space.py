"""MEANING_SPACE — graph-signal layer over the fragment store.

Closes BRV-08 (the dual `raw ⊕ graph` retrieval bet, acceptance #8): until
now retrieval was FTS5 candidate-gen + vector cosine + the Generative-Agents
triple-score (recency × importance × relevance) and *nothing else* — there was
no graph / geodesic / hubness signal anywhere, so the "graph-augmented recall"
half of the bet was untestable.

This module derives a real graph over fragments and exposes three classic
graph-centrality / proximity signals that a ranker can blend on top of cosine:

    * hubness   — degree centrality (how connected a node is in the
                  meaning-space; a hub fact is structurally important even when
                  its surface text barely lexically matches the query).
    * graph_rank — PageRank stationary distribution (eigenvector-flavoured
                  importance: a node pointed at by many *important* nodes ranks
                  up). Power-iteration, pure stdlib.
    * geodesic  — shortest-path proximity to a set of query "seed" nodes
                  (the strongest cosine matches). A fragment one hop from a
                  strong match is *closer in meaning-space* than an unrelated
                  fragment with the same cosine. Returned as proximity in
                  (0, 1]: 1/(1 + hops), 0.0 when unreachable.

WHERE THE EDGES COME FROM (no new table — ONE-SYSTEM / LIBRARY-FIRST):
    The fragment store already carries the graph implicitly. We materialise it
    from data that is written today, exactly like `BrainStore.doc_links`
    already mines `extra.deps` for the doc backlink graph:

      1. RDF triples — two fragments are linked when they share a `subject` or
         an `object` (a `subject`/`predicate`/`object` fact IS an edge in the
         AgDR-0042 MemoryGraph). A fragment whose `subject == other.object`
         (or vice-versa) is a directed hop along the relation.
      2. extra.deps / extra.related / extra.artifacts — explicit references by
         fragment id OR by subject/slug, the same fields `doc_links` reads.

    The result is an undirected adjacency for hubness/geodesic plus a directed
    adjacency for graph_rank (triple direction subject→object; deps source→dep).

Pure-Python, zero new deps, deterministic. O(V+E) to build, O(k·(V+E)) for the
bounded BFS, fixed-iteration power method for PageRank — cheap at brain scale
(n < ~10k fragments).
"""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Iterable, Mapping, Optional

from .models import Fragment


# ─────────────────────────── graph build ───────────────────────────────


def _norm(token: Optional[str]) -> str:
    return (token or "").strip().lower()


def _ref_tokens(frag: Fragment) -> list[str]:
    """Explicit forward references this fragment declares, normalised.

    Reads `extra.deps` / `extra.related` / `extra.references` / `extra.artifacts`
    — the same convention `BrainStore.doc_links` mines (storage.py). Each entry
    may be a fragment id, a subject string, or a doc slug; we keep all and
    resolve against both id and subject indexes when wiring edges.
    """
    out: list[str] = []
    extra = frag.extra or {}
    for key in ("deps", "related", "references", "artifacts"):
        vals = extra.get(key)
        if isinstance(vals, str):
            vals = [vals]
        if isinstance(vals, (list, tuple)):
            for v in vals:
                t = _norm(str(v))
                if t:
                    out.append(t)
    return out


class MeaningGraph:
    """An undirected + directed adjacency materialised from a fragment list.

    Construction is total: an empty / single-node / fully-disconnected fragment
    set all yield a valid (possibly edge-less) graph rather than raising. Every
    derived signal degrades to an honest neutral value (0.0 hubness, uniform
    graph_rank, 0.0 geodesic proximity) on a node with no edges — never a fake
    or a crash. That honesty is the ANTI-LIE contract for a genuinely
    unavailable signal.
    """

    def __init__(self, fragments: Iterable[Fragment]):
        self.frags: dict[str, Fragment] = {}
        # id and subject indexes for reference resolution
        self._by_subject: dict[str, set[str]] = defaultdict(set)
        self._by_object: dict[str, set[str]] = defaultdict(set)
        for f in fragments:
            if not f or not f.id:
                continue
            self.frags[f.id] = f
            s = _norm(f.subject)
            o = _norm(f.object)
            if s:
                self._by_subject[s].add(f.id)
            if o:
                self._by_object[o].add(f.id)

        self.undirected: dict[str, set[str]] = {fid: set() for fid in self.frags}
        self.out_edges: dict[str, set[str]] = {fid: set() for fid in self.frags}
        self.in_edges: dict[str, set[str]] = {fid: set() for fid in self.frags}
        self._build_edges()

    # -- edge wiring ----------------------------------------------------

    def _link(self, a: str, b: str, *, directed_a_to_b: bool) -> None:
        if a == b or a not in self.frags or b not in self.frags:
            return
        self.undirected[a].add(b)
        self.undirected[b].add(a)
        if directed_a_to_b:
            self.out_edges[a].add(b)
            self.in_edges[b].add(a)

    def _resolve(self, token: str) -> set[str]:
        """Fragment ids a reference token points to: a direct id match, or any
        fragment whose subject equals the token (a slug/subject reference)."""
        hits: set[str] = set()
        if token in self.frags:
            hits.add(token)
        hits |= self._by_subject.get(token, set())
        return hits

    def _build_edges(self) -> None:
        # (1) RDF-triple edges: subject→object direction. A fragment whose
        #     object names another fragment's subject is a directed hop
        #     (this fact's object IS that fact's topic). Symmetrised for the
        #     undirected centrality/geodesic views.
        for fid, f in self.frags.items():
            o = _norm(f.object)
            if o:
                for other in self._by_subject.get(o, set()):
                    self._link(fid, other, directed_a_to_b=True)
            # Co-subject siblings (same topic) are undirected peers — they sit
            # in the same neighbourhood of meaning-space.
            s = _norm(f.subject)
            if s:
                for sib in self._by_subject.get(s, set()):
                    self._link(fid, sib, directed_a_to_b=False)

        # (2) Explicit reference edges (extra.deps / related / references /
        #     artifacts): directed source→target.
        for fid, f in self.frags.items():
            for token in _ref_tokens(f):
                for target in self._resolve(token):
                    self._link(fid, target, directed_a_to_b=True)

    # -- size ------------------------------------------------------------

    @property
    def n(self) -> int:
        return len(self.frags)

    @property
    def edge_count(self) -> int:
        return sum(len(v) for v in self.undirected.values()) // 2

    # -- signal: hubness (degree centrality) -----------------------------

    def hubness(self) -> dict[str, float]:
        """Degree centrality in [0, 1]: deg(node) / (n - 1). A standalone node
        (or n < 2) gets 0.0 — structurally not a hub, reported honestly."""
        if self.n < 2:
            return {fid: 0.0 for fid in self.frags}
        denom = float(self.n - 1)
        return {fid: len(self.undirected[fid]) / denom for fid in self.frags}

    # -- signal: graph_rank (PageRank) -----------------------------------

    def graph_rank(self, *, damping: float = 0.85, iterations: int = 50) -> dict[str, float]:
        """PageRank over the DIRECTED graph (power iteration; dangling mass
        redistributed uniformly). Returns a probability distribution that sums
        to ~1. With no edges every node is uniform 1/n — the correct neutral.
        """
        n = self.n
        if n == 0:
            return {}
        if n == 1:
            return {next(iter(self.frags)): 1.0}

        ids = list(self.frags)
        rank = {fid: 1.0 / n for fid in ids}
        teleport = (1.0 - damping) / n
        for _ in range(max(1, iterations)):
            dangling = sum(rank[fid] for fid in ids if not self.out_edges[fid])
            new = {fid: teleport + damping * dangling / n for fid in ids}
            for fid in ids:
                outs = self.out_edges[fid]
                if not outs:
                    continue
                share = damping * rank[fid] / len(outs)
                for tgt in outs:
                    new[tgt] += share
            # normalise (guards float drift)
            total = sum(new.values()) or 1.0
            rank = {fid: v / total for fid, v in new.items()}
        return rank

    # -- signal: geodesic proximity to seeds -----------------------------

    def geodesic_proximity(self, seeds: Iterable[str]) -> dict[str, float]:
        """Multi-source BFS proximity (UNDIRECTED) to the nearest seed.

        Returns proximity = 1 / (1 + hops) in (0, 1]: a seed itself scores 1.0,
        a one-hop neighbour 0.5, two hops 0.333…; a node in a different
        component scores 0.0 (genuinely unreachable — honest, not faked).
        """
        dist: dict[str, int] = {}
        q: deque[str] = deque()
        for s in seeds:
            if s in self.frags and s not in dist:
                dist[s] = 0
                q.append(s)
        while q:
            cur = q.popleft()
            d = dist[cur]
            for nbr in self.undirected[cur]:
                if nbr not in dist:
                    dist[nbr] = d + 1
                    q.append(nbr)
        return {fid: (1.0 / (1.0 + dist[fid]) if fid in dist else 0.0)
                for fid in self.frags}


# ─────────────────────── combined signal bundle ────────────────────────


def graph_signals(
    fragments: list[Fragment],
    *,
    seeds: Optional[Iterable[str]] = None,
    damping: float = 0.85,
) -> dict[str, dict[str, float]]:
    """Compute all three signals once, keyed by fragment id.

    Returns ``{frag_id: {"hubness": h, "graph_rank": g, "geodesic": p}}``.
    `seeds` are the fragment ids the geodesic distance is measured from
    (typically the top cosine matches); when omitted, every fragment is its own
    seed (geodesic collapses to a connectivity indicator: 1.0 for all present
    nodes), so callers that only want hubness/graph_rank still get a sane map.
    """
    g = MeaningGraph(fragments)
    hub = g.hubness()
    rank = g.graph_rank(damping=damping)
    geo = g.geodesic_proximity(seeds if seeds is not None else list(g.frags))
    return {
        fid: {
            "hubness": hub.get(fid, 0.0),
            "graph_rank": rank.get(fid, 0.0),
            "geodesic": geo.get(fid, 0.0),
        }
        for fid in g.frags
    }


def blend_graph_score(
    cosine_relevance: float,
    signals: Mapping[str, float],
    *,
    w_hub: float = 0.4,
    w_rank: float = 0.6,
    w_geo: float = 0.5,
) -> float:
    """Additive graph boost on top of a raw cosine relevance.

    score = cosine + w_hub·hubness + w_rank·(n·graph_rank) + w_geo·geodesic

    `graph_rank` is multiplied by n inside the caller-facing blend so a tiny
    probability (≈1/n) becomes an O(1) signal comparable to hubness/geodesic;
    callers pass the already-scaled value via `signals['graph_rank_scaled']`
    when available, else the raw rank is used as-is. Weights are tunable; the
    defaults make the graph signal *able to outrank* a marginal cosine gap
    (which is exactly what BRV-08's acceptance test exercises) without
    swamping a strong direct lexical match.
    """
    rank_term = signals.get("graph_rank_scaled", signals.get("graph_rank", 0.0))
    return (
        max(0.0, cosine_relevance)
        + w_hub * signals.get("hubness", 0.0)
        + w_rank * rank_term
        + w_geo * signals.get("geodesic", 0.0)
    )
