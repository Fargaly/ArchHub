"""Embedding layer — vector similarity for skill + fact retrieval.

Slice 2 (AgDR-0044). Two implementations:

1. **Vector backend** — fastembed (bge-small-en-v1.5, 384-dim) or
   sentence-transformers (all-MiniLM-L6-v2, 384-dim) when installed.
   FAISS in-memory IndexFlatIP for cosine similarity.

2. **Lexical fallback** — TF-IDF cosine on tokenized text. Pure stdlib,
   zero deps. Used automatically when fastembed/FAISS unavailable so the
   brain still works on a fresh install before optional deps land.

Both paths satisfy the same `Embedder` Protocol so callers don't branch.

Public surface:

    from personal_brain.embeddings import get_embedder, score_against_query

    emb = get_embedder()                       # auto-detects backend
    vec = emb.encode("Tower-A wall takeoff")
    score = emb.cosine(vec_a, vec_b)
    ranked = score_against_query(query, items)
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Iterable, Optional, Protocol, runtime_checkable


# ─────────────────────── Protocol ───────────────────────────────────────


@runtime_checkable
class Embedder(Protocol):
    """Minimal contract every backend implements."""

    dim: int
    backend_name: str

    def encode(self, text: str) -> list[float]: ...
    def encode_batch(self, texts: list[str]) -> list[list[float]]: ...
    def cosine(self, a: list[float], b: list[float]) -> float: ...


# ─────────────────────── lexical fallback ──────────────────────────────


_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]+")
_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "of", "in", "on", "for", "to", "is",
    "are", "was", "were", "be", "been", "being", "i", "me", "my", "you",
    "your", "we", "our", "this", "that", "these", "those", "with", "from",
    "by", "at", "as", "but", "not", "no", "do", "does", "did", "have",
    "has", "had", "it", "its", "they", "them", "their",
})


def _tokenize(text: str) -> list[str]:
    """Lowercase tokens, drop stopwords, drop single-char tokens."""
    if not text:
        return []
    return [
        t.lower()
        for t in _TOKEN_RE.findall(text)
        if len(t) > 1 and t.lower() not in _STOPWORDS
    ]


class LexicalEmbedder:
    """TF-IDF cosine using a fixed hash-based dimensionality so different
    vocabularies still produce same-dim vectors (hashing trick — Weinberger
    et al. 2009).

    Not as good as a real model but: zero deps, deterministic, sub-ms
    encode, decent precision on technical text where vocabulary overlap is
    the main signal.
    """

    dim: int = 2048
    backend_name: str = "lexical-hash-tfidf"

    def __init__(self, dim: int = 2048):
        self.dim = dim

    def _hash(self, token: str) -> int:
        # Stable hash (don't use Python's per-process-randomized hash()).
        # FNV-1a 64-bit, then modulo dim.
        h = 0xcbf29ce484222325
        for c in token.encode("utf-8"):
            h ^= c
            h = (h * 0x100000001b3) & 0xffffffffffffffff
        return h % self.dim

    def encode(self, text: str) -> list[float]:
        tokens = _tokenize(text)
        if not tokens:
            return [0.0] * self.dim
        counts = Counter(tokens)
        # log-tf (sublinear scaling)
        v = [0.0] * self.dim
        for token, count in counts.items():
            idx = self._hash(token)
            v[idx] += 1.0 + math.log(count)
        # L2 normalize so cosine = dot product
        norm = math.sqrt(sum(x * x for x in v))
        if norm > 0:
            v = [x / norm for x in v]
        return v

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.encode(t) for t in texts]

    def cosine(self, a: list[float], b: list[float]) -> float:
        if len(a) != len(b):
            return 0.0
        return sum(x * y for x, y in zip(a, b))


# ─────────────────────── fastembed backend ─────────────────────────────


class FastEmbedEmbedder:
    """Wraps `fastembed.TextEmbedding`. ~384-dim by default. ONNX-backed,
    no GPU required, fast on CPU. Used when the optional [embed] extra is
    installed."""

    dim: int
    backend_name: str

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5"):
        try:
            from fastembed import TextEmbedding  # type: ignore
        except ImportError as ex:  # pragma: no cover
            raise RuntimeError(
                "fastembed not installed. "
                "`pip install 'personal-brain-mcp[embed]'`"
            ) from ex
        self._model = TextEmbedding(model_name=model_name)
        # Probe dim with a small encode
        probe = next(iter(self._model.embed(["x"])))
        try:
            self.dim = len(probe)
        except Exception:
            self.dim = 384
        self.backend_name = f"fastembed:{model_name}"

    def encode(self, text: str) -> list[float]:
        if not text:
            return [0.0] * self.dim
        vecs = list(self._model.embed([text]))
        return list(vecs[0])

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return [list(v) for v in self._model.embed(texts)]

    def cosine(self, a: list[float], b: list[float]) -> float:
        if len(a) != len(b):
            return 0.0
        dot = 0.0
        na = 0.0
        nb = 0.0
        for x, y in zip(a, b):
            dot += x * y
            na += x * x
            nb += y * y
        denom = math.sqrt(na) * math.sqrt(nb)
        return dot / denom if denom else 0.0


# ─────────────────────── factory ───────────────────────────────────────


_DEFAULT_EMBEDDER: Optional[Embedder] = None


def get_embedder(*, prefer: str = "auto") -> Embedder:
    """Return the cached default embedder.

    `prefer`:
      - "auto"    — fastembed if installed, else lexical
      - "fastembed" — force fastembed (raises if unavailable)
      - "lexical" — force lexical fallback (always works)
    """
    global _DEFAULT_EMBEDDER
    if _DEFAULT_EMBEDDER is not None and prefer == "auto":
        return _DEFAULT_EMBEDDER

    if prefer == "lexical":
        emb = LexicalEmbedder()
    elif prefer == "fastembed":
        emb = FastEmbedEmbedder()
    else:  # auto
        try:
            emb = FastEmbedEmbedder()
        except Exception:
            emb = LexicalEmbedder()

    if prefer == "auto":
        _DEFAULT_EMBEDDER = emb
    return emb


def reset_default_embedder() -> None:
    """Test helper — clear the cached embedder."""
    global _DEFAULT_EMBEDDER
    _DEFAULT_EMBEDDER = None


# ─────────────────────── scoring helpers ───────────────────────────────


def cosine(a: list[float], b: list[float]) -> float:
    """Generic cosine for two equal-length unit vectors. Convenience."""
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))


def score_against_query(
    query: str,
    items: Iterable[Any],
    *,
    text_attr: str = "text",
    embedder: Optional[Embedder] = None,
    descending: bool = True,
) -> list[tuple[Any, float]]:
    """Score items by cosine vs query. Returns list of (item, score) sorted.

    Item objects need a `text_attr` attribute holding the searchable string
    (or be dict-like with that key). Skills are scored against
    `description`; fragments against `text`.
    """
    emb = embedder or get_embedder()
    qvec = emb.encode(query)
    scored: list[tuple[Any, float]] = []
    for item in items:
        text = _get_text(item, text_attr)
        if not text:
            scored.append((item, 0.0))
            continue
        ivec = emb.encode(text)
        scored.append((item, emb.cosine(qvec, ivec)))
    scored.sort(key=lambda kv: kv[1], reverse=descending)
    return scored


def _get_text(item: Any, attr: str) -> str:
    if hasattr(item, attr):
        v = getattr(item, attr)
        return v if isinstance(v, str) else ""
    if isinstance(item, dict):
        return str(item.get(attr, ""))
    return ""


# ─────────────────────── Generative Agents triple score ────────────────


def triple_score(
    *,
    relevance: float,
    importance: float = 0.5,
    recency_seconds: float = 0.0,
    half_life_seconds: float = 7 * 24 * 3600.0,
    alpha: float = 1.0,
    beta: float = 0.5,
    gamma: float = 1.0,
) -> float:
    """Generative Agents (Park 2304.03442) retrieval score:
        score = α·recency + β·importance + γ·relevance

    `recency_seconds` is age (now - last_used_at, in seconds).
    `half_life_seconds` controls exponential decay (default 7 days).
    `importance` is a 0..1 LM-graded score per fragment (default 0.5).
    `relevance` is a 0..1 cosine.

    Returns a non-negative composite score. Caller picks top-K.
    """
    # Recency decay — Ebbinghaus: e^(-t/H)
    decay = math.exp(-max(recency_seconds, 0.0) / max(half_life_seconds, 1.0))
    return alpha * decay + beta * importance + gamma * max(0.0, relevance)
