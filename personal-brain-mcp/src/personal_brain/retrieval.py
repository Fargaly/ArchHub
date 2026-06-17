"""Retrieval layer — combines FTS5 candidate generation + vector rerank +
Generative Agents triple-score (recency × importance × relevance).

Per AgDR-0044 §"Skill-mint pipeline" + 1%-frontier lane finding #6
(Schapiro replay weighting).

Slice 2 (this file) replaces the pure-FTS5 retrieval in `server.py:
make_context_payload` with a two-stage ranker:

    1. FTS5 broad candidate (k * 4 hits)
    2. Vector cosine rerank via Embedder
    3. Triple-score: α·recency + β·importance + γ·relevance
    4. Top-k final

Public surface:

    from personal_brain.retrieval import retrieve_skills, retrieve_facts

    skills = retrieve_skills(store, query, owner_user='founder', k=5)
    facts  = retrieve_facts (store, query, owner_user='founder', k=8)
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Iterable, Optional

from .embeddings import Embedder, get_embedder, triple_score
from .meaning_space import MeaningGraph, blend_graph_score
from .models import Fragment, FragmentKind, Scope, Skill
from .storage import BrainStore


# ─────────────────────── helpers ───────────────────────────────────────


def _recency_seconds(dt: Optional[datetime]) -> float:
    if dt is None:
        return 1e9  # treat unused as very old
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    return max(0.0, (now - dt).total_seconds())


def _half_life_seconds(half_life_days: float) -> float:
    return max(half_life_days, 0.5) * 24.0 * 3600.0


# ─────────────────────── skill retrieval ───────────────────────────────


def retrieve_skills(
    store: BrainStore,
    query: str,
    *,
    owner_user: str,
    scope_filter: Optional[Iterable[Scope]] = None,
    k: int = 5,
    embedder: Optional[Embedder] = None,
    alpha_recency: float = 0.5,
    beta_importance: float = 0.4,
    gamma_relevance: float = 1.0,
    expand_factor: int = 4,
) -> list[Skill]:
    """Two-stage retrieve over skills.

    Stage 1: FTS5 returns `k * expand_factor` keyword candidates.
    Stage 2: Embedder reranks via cosine on `description`.
    Stage 3: Triple-score blends recency + popularity + relevance.

    Returns top-k Skills ranked descending. Side effect: bumps
    `last_used_at` on the retrieved skills (Nader reconsolidation —
    retrieval is an implicit edit signal).
    """
    if not query.strip():
        return store.list_skills(
            scope_filter=scope_filter, owner_user=owner_user, limit=k
        )

    embedder = embedder or get_embedder()
    candidates = store.search_skills(
        query, scope_filter=scope_filter, owner_user=owner_user,
        k=max(k * expand_factor, k),
    )
    if not candidates:
        # FTS5 missed everything — fall back to full list + vector rerank
        # over a bounded slice so a vocabulary mismatch doesn't blank the
        # retrieval. Slice 6 adds an embedding index that makes this O(log n).
        candidates = store.list_skills(
            scope_filter=scope_filter, owner_user=owner_user,
            limit=max(k * expand_factor * 2, 30),
        )
    if not candidates:
        return []

    qvec = embedder.encode(query)
    scored: list[tuple[Skill, float]] = []
    for sk in candidates:
        text = sk.description + " " + " ".join(sk.triggers)
        ivec = embedder.encode(text)
        relevance = max(0.0, embedder.cosine(qvec, ivec))
        importance = _importance_from_counts(sk.success_count, sk.fail_count)
        score = triple_score(
            relevance=relevance,
            importance=importance,
            recency_seconds=_recency_seconds(sk.last_used_at),
            half_life_seconds=14 * 24 * 3600.0,  # skills decay slower than facts
            alpha=alpha_recency,
            beta=beta_importance,
            gamma=gamma_relevance,
        )
        scored.append((sk, score))

    scored.sort(key=lambda kv: kv[1], reverse=True)
    top = [s for s, _ in scored[:k]]

    for sk in top:
        # Touch the skill — its last_used_at advances. This is the
        # reconsolidation signal (lane A finding #2).
        try:
            store._conn.execute(
                "UPDATE skills SET last_used_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE id = ?",
                (sk.id,),
            )
        except Exception:
            pass

    return top


# ─────────────────────── fact retrieval ────────────────────────────────


def retrieve_facts(
    store: BrainStore,
    query: str,
    *,
    owner_user: str,
    scope_filter: Optional[Iterable[Scope]] = None,
    kinds: Optional[Iterable[FragmentKind]] = None,
    k: int = 8,
    embedder: Optional[Embedder] = None,
    alpha_recency: float = 1.0,
    beta_importance: float = 0.3,
    gamma_relevance: float = 1.0,
    expand_factor: int = 4,
) -> list[Fragment]:
    """Two-stage retrieve over fragments (facts / setups / spatial / etc.).

    Defaults to fact-like kinds (fact, setup, spatial). Set `kinds=None` to
    not filter.
    """
    if kinds is None:
        kinds = [FragmentKind.FACT, FragmentKind.SETUP, FragmentKind.SPATIAL]

    if not query.strip():
        return []

    embedder = embedder or get_embedder()
    candidates = store.search_fragments(
        query, scope_filter=scope_filter, owner_user=owner_user,
        kinds=kinds, k=max(k * expand_factor, k),
    )
    if not candidates:
        return []

    qvec = embedder.encode(query)
    scored: list[tuple[Fragment, float]] = []
    for f in candidates:
        # Combine subject + predicate + object for better text signal
        parts = [f.text]
        if f.subject:
            parts.append(f.subject)
        if f.object:
            parts.append(f.object)
        ivec = embedder.encode(" ".join(parts))
        relevance = max(0.0, embedder.cosine(qvec, ivec))
        importance = _importance_from_counts(f.success_count, f.fail_count)
        score = triple_score(
            relevance=relevance,
            importance=importance,
            recency_seconds=_recency_seconds(f.last_used_at),
            half_life_seconds=_half_life_seconds(f.half_life_days),
            alpha=alpha_recency,
            beta=beta_importance,
            gamma=gamma_relevance,
        )
        scored.append((f, score))

    scored.sort(key=lambda kv: kv[1], reverse=True)
    top = [f for f, _ in scored[:k]]
    return top


def _importance_from_counts(success: int, fail: int) -> float:
    """Wilson-style importance: high-success items rank up, but rare items
    aren't penalised. Maps to [0, 1].
    """
    total = success + fail
    if total == 0:
        return 0.3  # gentle prior for unused items
    # Smoothed success ratio
    ratio = (success + 1) / (total + 2)
    # Volume bonus (log-scaled, capped)
    import math
    volume = min(math.log(1 + total) / math.log(50), 1.0)
    return 0.5 * ratio + 0.5 * volume


# ─────────────────────── unified retrieve (mixed) ──────────────────────


def retrieve_mixed(
    store: BrainStore,
    query: str,
    *,
    owner_user: str,
    scope_filter: Optional[Iterable[Scope]] = None,
    k_skills: int = 5,
    k_facts: int = 8,
    embedder: Optional[Embedder] = None,
) -> tuple[list[Skill], list[Fragment], float]:
    """Single entry point — returns (skills, facts, elapsed_ms)."""
    t0 = time.perf_counter()
    skills = retrieve_skills(
        store, query, owner_user=owner_user, scope_filter=scope_filter,
        k=k_skills, embedder=embedder,
    )
    facts = retrieve_facts(
        store, query, owner_user=owner_user, scope_filter=scope_filter,
        k=k_facts, embedder=embedder,
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return skills, facts, elapsed_ms


# ─────────────────────── graph-augmented fact retrieval (BRV-08) ────────


def retrieve_facts_graph(
    store: BrainStore,
    query: str,
    *,
    owner_user: str,
    scope_filter: Optional[Iterable[Scope]] = None,
    kinds: Optional[Iterable[FragmentKind]] = None,
    k: int = 8,
    embedder: Optional[Embedder] = None,
    expand_factor: int = 4,
    seed_n: int = 3,
    w_hub: float = 0.4,
    w_rank: float = 0.6,
    w_geo: float = 0.5,
    return_debug: bool = False,
) -> list[Fragment] | tuple[list[Fragment], dict[str, dict[str, float]]]:
    """MEANING_SPACE recall ranker — the `raw ⊕ graph` half of the dual-retrieval
    bet (BRV-08, acceptance #8).

    This is NOT FTS-then-cosine. It is FTS candidate-gen, then a re-rank that
    BLENDS cosine relevance with three graph-centrality / proximity signals
    derived from the MemoryGraph the fragment store already carries (RDF
    subject/object triples + `extra.deps`/`related`/`references`/`artifacts`):

        final = cosine + w_hub·hubness + w_rank·(n·graph_rank) + w_geo·geodesic

    Pipeline:
      1. FTS5 broad candidates (k·expand_factor), like `retrieve_facts`.
      2. Pull the candidates' graph NEIGHBOURS from the store too, so a hub
         fact that FTS missed (vocabulary mismatch) can still surface — the
         graph signal is computed over candidates ∪ neighbours.
      3. Cosine vs query for every fragment in that set.
      4. Geodesic distance is measured from the `seed_n` strongest cosine
         matches (the query "anchors" in meaning-space).
      5. Blend → sort → top-k.

    A fragment that sits one hop from a strong match, or is a structural hub,
    can therefore outrank a fragment with a marginally higher raw cosine — which
    is exactly the behaviour the FTS-only ranker cannot produce. When the graph
    has no edges (disconnected fragments) every graph signal is its honest
    neutral and this degrades to a cosine ranking — no fabrication.

    Set `return_debug=True` to also get the per-fragment signal map (used by the
    acceptance test + any future inspector UI).
    """
    if not query.strip():
        return ([], {}) if return_debug else []
    if kinds is None:
        kinds = [FragmentKind.FACT, FragmentKind.SETUP, FragmentKind.SPATIAL]
    kinds = list(kinds)

    embedder = embedder or get_embedder()
    candidates = store.search_fragments(
        query, scope_filter=scope_filter, owner_user=owner_user,
        kinds=kinds, k=max(k * expand_factor, k),
    )
    if not candidates:
        return ([], {}) if return_debug else []

    # (2) Expand with graph neighbours pulled from the store. The neighbour
    # relation mirrors meaning_space edge wiring: fragments sharing a
    # subject/object, plus the candidates' declared extra-refs. This lets a
    # hub the FTS query missed enter the graph (and therefore the ranking).
    pool: dict[str, Fragment] = {f.id: f for f in candidates}
    _add_graph_neighbours(store, candidates, pool, scope_filter, owner_user, kinds)

    pool_list = list(pool.values())

    # (3) Cosine relevance for every fragment in the pool.
    qvec = embedder.encode(query)
    relevance: dict[str, float] = {}
    for f in pool_list:
        parts = [f.text]
        if f.subject:
            parts.append(f.subject)
        if f.object:
            parts.append(f.object)
        ivec = embedder.encode(" ".join(parts))
        relevance[f.id] = max(0.0, embedder.cosine(qvec, ivec))

    # (4) Seeds = strongest cosine matches → geodesic anchors.
    seeds = [
        fid for fid, _ in sorted(
            relevance.items(), key=lambda kv: kv[1], reverse=True
        )[:max(1, seed_n)]
    ]

    graph = MeaningGraph(pool_list)
    hub = graph.hubness()
    rank = graph.graph_rank()
    geo = graph.geodesic_proximity(seeds)
    n = max(graph.n, 1)

    # (5) Blend → sort → top-k.
    scored: list[tuple[Fragment, float]] = []
    debug: dict[str, dict[str, float]] = {}
    for f in pool_list:
        sig = {
            "hubness": hub.get(f.id, 0.0),
            "graph_rank": rank.get(f.id, 0.0),
            "graph_rank_scaled": n * rank.get(f.id, 0.0),
            "geodesic": geo.get(f.id, 0.0),
        }
        score = blend_graph_score(
            relevance.get(f.id, 0.0), sig,
            w_hub=w_hub, w_rank=w_rank, w_geo=w_geo,
        )
        scored.append((f, score))
        if return_debug:
            debug[f.id] = {
                "cosine": relevance.get(f.id, 0.0),
                "final": score,
                **sig,
            }

    scored.sort(key=lambda kv: kv[1], reverse=True)
    top = [f for f, _ in scored[:k]]
    return (top, debug) if return_debug else top


def _add_graph_neighbours(
    store: BrainStore,
    seeds: list[Fragment],
    pool: dict[str, Fragment],
    scope_filter: Optional[Iterable[Scope]],
    owner_user: str,
    kinds: list[FragmentKind],
    *,
    cap: int = 200,
) -> None:
    """Pull fragments adjacent to `seeds` in the MemoryGraph into `pool`.

    Adjacency (same definition as `meaning_space`): a fragment sharing a
    subject or object with a seed, OR named by a seed's
    `extra.deps`/`related`/`references`/`artifacts`. Bounded by `cap` so a
    pathological topic with thousands of co-subject facts can't blow the pool.
    Uses the existing FTS `search_fragments` surface to fetch by subject/object
    text — no new store method, no new table (ONE-SYSTEM).
    """
    if len(pool) >= cap:
        return
    tokens: set[str] = set()
    for f in seeds:
        for t in (f.subject, f.object):
            t = (t or "").strip()
            if t:
                tokens.add(t)
        extra = f.extra or {}
        for key in ("deps", "related", "references", "artifacts"):
            vals = extra.get(key)
            if isinstance(vals, str):
                vals = [vals]
            if isinstance(vals, (list, tuple)):
                for v in vals:
                    v = str(v).strip()
                    if v:
                        tokens.add(v)
    for tok in tokens:
        if len(pool) >= cap:
            break
        try:
            hits = store.search_fragments(
                tok, scope_filter=scope_filter, owner_user=owner_user,
                kinds=kinds, k=8,
            )
        except Exception:
            continue
        for h in hits:
            if h.id not in pool:
                pool[h.id] = h
            if len(pool) >= cap:
                break
