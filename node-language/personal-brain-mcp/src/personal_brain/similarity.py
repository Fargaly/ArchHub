"""Brain #31 multimodal · day-5 similarity search.

Per founder ask 2026-05-26: "this brain should have a way to understand
geometry & pictures."

Day-5 deliverable: `find_similar` — given an image/text/geometry query,
rank stored multimodal fragments by similarity.

Algorithm
---------
1. **Candidate set**: list_fragments filtered to kinds=[IMAGE, GEOMETRY]
   + caller's scope_filter + owner_user. Limit to N (default 500) to
   bound the cosine pass.
2. **Perceptual-hash pre-filter** (when query_phash provided): rank
   candidates by ascending hamming distance, keep top max_phash
   (default 50). Cheap, no model load.
3. **Embedding cosine refine** (when query_embedding provided AND
   candidates have embeddings): score each survivor by cosine
   similarity, sort descending. Returns up to `k` results.
4. **Fallback**: when neither phash nor embedding works (e.g. CLIP
   missing + query has no phash), return phash-only ranked results.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from .embedding import cosine
from .models import Fragment, FragmentKind, Scope
from .phash import hamming_hex


@dataclass
class SimilarHit:
    """One result from find_similar — fragment + per-signal score."""
    fragment: Fragment
    phash_distance: Optional[int] = None        # 0=identical · 64=opposite
    embedding_cosine: Optional[float] = None    # -1..1 · None if no embedding
    rank_score: float = 0.0                     # combined rank (higher better)


def find_similar(
    store,
    *,
    query_phash: Optional[str] = None,
    query_embedding: Optional[list[float]] = None,
    kinds: Optional[Iterable[FragmentKind]] = None,
    scope_filter: Optional[Iterable[Scope]] = None,
    owner_user: Optional[str] = None,
    k: int = 5,
    max_candidates: int = 500,
    max_phash: int = 50,
) -> list[SimilarHit]:
    """Rank multimodal fragments by similarity to the query.

    At least one of `query_phash` / `query_embedding` must be provided.
    Returns up to `k` SimilarHit ranked best-first.
    """
    if not query_phash and not query_embedding:
        return []

    # Candidate set — default to IMAGE + GEOMETRY when caller doesn't
    # narrow it themselves.
    if kinds is None:
        kinds = [FragmentKind.IMAGE, FragmentKind.GEOMETRY]
    candidates = store.list_fragments(
        scope_filter=scope_filter,
        kinds=kinds,
        owner_user=owner_user,
        limit=max_candidates,
    )

    hits: list[SimilarHit] = []
    for frag in candidates:
        hit = SimilarHit(fragment=frag)
        # phash pre-filter score
        if query_phash and frag.perceptual_hash:
            try:
                hit.phash_distance = hamming_hex(
                    query_phash, frag.perceptual_hash,
                )
            except ValueError:
                # Length mismatch — incompatible hash formats. Skip
                # phash signal but keep the candidate alive for the
                # embedding pass.
                hit.phash_distance = None
        hits.append(hit)

    # Apply phash filter: keep top max_phash by ascending distance.
    if query_phash:
        scored = [h for h in hits if h.phash_distance is not None]
        unscored = [h for h in hits if h.phash_distance is None]
        scored.sort(key=lambda h: h.phash_distance)
        hits = scored[:max_phash] + unscored

    # Embedding refine.
    if query_embedding:
        for h in hits:
            if h.fragment.embedding:
                h.embedding_cosine = cosine(query_embedding, h.fragment.embedding)

    # Combined ranking score: prefer embedding cosine when present
    # (range 0..1 after rescaling from -1..1); fall back to inverted
    # phash distance (1.0 = identical · 0 = 64 bits apart).
    for h in hits:
        if h.embedding_cosine is not None:
            # Rescale -1..1 → 0..1
            h.rank_score = (h.embedding_cosine + 1.0) / 2.0
        elif h.phash_distance is not None:
            h.rank_score = 1.0 - (h.phash_distance / 64.0)
        else:
            h.rank_score = 0.0

    hits.sort(key=lambda h: h.rank_score, reverse=True)
    return hits[:k]
