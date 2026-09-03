"""Hybrid recall — BM25 lexical lane beside the dense (cosine) lane, with a
per-query blend weight alpha (Tier-1 research: Query-Adaptive Hybrid Search).

Why this exists
---------------
The dense lane (``embeddings.Embedder`` cosine inside ``retrieval.retrieve_facts``)
is strong on paraphrase ("wall quantity" ~ "takeoff schedule") but weak on
EXACT-CODE queries: identifiers like ``AP_CORNICE``, ``CW22``, node ids, sheet
numbers. Those tokens carry all the signal, and an embedding — especially the
hash-TF-IDF lexical fallback — can dilute them across a long memory text. BM25
(Okapi) is the classic exact-term ranker: rare terms get a large idf, so the one
memory that actually contains ``AP_CORNICE`` wins the lexical lane outright.

Design (all stdlib, deterministic, pure — memo-safe, no I/O, no LLM):

* ``tokenize``            — whitespace/punct split that PRESERVES exact code
                            tokens (``[A-Z0-9_]+`` with at least one letter)
                            verbatim and lowercases everything else.
* ``BM25``                — Okapi BM25 over a fixed corpus, k1=1.5, b=0.75,
                            idf = ln(1 + (N - df + 0.5)/(df + 0.5))  (the
                            non-negative "+1" variant used by Lucene).
* ``blend``               — alpha·minmax(dense) + (1-alpha)·minmax(bm25).
* ``predict_alpha``       — per-query alpha heuristic (see its docstring).
* ``hybrid_scores``       — convenience: query + texts + dense scores → blended
                            scores. GUARANTEE: alpha == 1.0 returns the dense
                            scores list unchanged (bit-identical current
                            behavior — no normalization, no BM25 pass).

ZERO-RISK CONTRACT: nothing in the existing retrieval path changes unless a
caller passes an alpha < 1.0. ``retrieval.retrieve_facts`` guards on
``hybrid_alpha == 1.0`` and runs the untouched original loop in that case.
"""
from __future__ import annotations

import math
import re
from typing import Optional, Sequence

# ─────────────────────── tokenizer ─────────────────────────────────────

# Candidate tokens: runs of word characters (underscore kept INSIDE a token so
# AP_CORNICE survives as one unit; every other punctuation char splits).
_WORD_RE = re.compile(r"[A-Za-z0-9_]+")

# An exact-code token: only uppercase letters / digits / underscores, with at
# least one letter (pure numbers pass through lowercase() unchanged anyway).
_CODE_TOKEN_RE = re.compile(r"(?=[A-Z0-9_]*[A-Z])[A-Z0-9_]+\Z")

# predict_alpha trigger — the query contains something code-shaped:
#   [A-Z]{2,}[0-9_]  →  CW22, AA3D, JPD17 (caps run followed by digit/underscore)
#   [A-Z_]{4,}       →  AP_CORNICE, NETLOAD (long all-caps / underscored code)
#   \d{2,}           →  9820, 48885 (multi-digit ids / sheet numbers)
_CODE_QUERY_RE = re.compile(r"[A-Z]{2,}[0-9_]|[A-Z_]{4,}|\d{2,}")


def tokenize(text: str) -> list[str]:
    """Split on whitespace/punctuation, keep exact-code tokens whole.

    ``'AP_CORNICE ring profile, CW22.'`` → ``['AP_CORNICE', 'ring', 'profile',
    'CW22']``. Codes (all-caps [A-Z0-9_]+ with a letter) are preserved verbatim
    so they match memory texts exactly; everything else is lowercased so prose
    matches case-insensitively.
    """
    if not text:
        return []
    out: list[str] = []
    for tok in _WORD_RE.findall(text):
        if _CODE_TOKEN_RE.match(tok):
            out.append(tok)
        else:
            out.append(tok.lower())
    return out


# ─────────────────────── BM25 (Okapi) ──────────────────────────────────


class BM25:
    """Okapi BM25 over a fixed list of texts. k1=1.5, b=0.75 (task spec).

    idf(t)      = ln(1 + (N - df + 0.5) / (df + 0.5))          [non-negative]
    score(q, d) = Σ_t∈q  idf(t) · tf·(k1+1) / (tf + k1·(1 - b + b·|d|/avgdl))

    Deterministic and pure: the corpus is tokenized once in __init__ and
    scoring reads only that snapshot.
    """

    def __init__(self, texts: Sequence[str], *, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.docs: list[list[str]] = [tokenize(t) for t in texts]
        self.n = len(self.docs)
        self.doc_lens = [len(d) for d in self.docs]
        self.avgdl = (sum(self.doc_lens) / self.n) if self.n else 0.0
        # document frequency per term
        self.df: dict[str, int] = {}
        for doc in self.docs:
            for term in set(doc):
                self.df[term] = self.df.get(term, 0) + 1

    def idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        return math.log(1.0 + (self.n - df + 0.5) / (df + 0.5))

    def score(self, query: str, index: int) -> float:
        """BM25 score of doc `index` for `query`."""
        doc = self.docs[index]
        if not doc:
            return 0.0
        dl = self.doc_lens[index]
        s = 0.0
        for term in tokenize(query):
            tf = doc.count(term)
            if tf == 0:
                continue
            denom = tf + self.k1 * (1.0 - self.b + self.b * dl / self.avgdl)
            s += self.idf(term) * tf * (self.k1 + 1.0) / denom
        return s

    def scores(self, query: str) -> list[float]:
        return [self.score(query, i) for i in range(self.n)]


# ─────────────────────── blend ─────────────────────────────────────────


def _min_max(scores: Sequence[float]) -> list[float]:
    """Min-max normalize to [0, 1]. A constant list (max == min) normalizes to
    all-zeros — the lane carries no ranking information, so it contributes
    nothing to the blend (honest neutral, no fabricated preference)."""
    if not scores:
        return []
    lo = min(scores)
    hi = max(scores)
    span = hi - lo
    if span <= 0.0:
        return [0.0] * len(scores)
    return [(s - lo) / span for s in scores]


def blend(
    dense_scores: Sequence[float],
    bm25_scores: Sequence[float],
    alpha: float,
) -> list[float]:
    """Combine the two lanes: alpha·minmax(dense) + (1-alpha)·minmax(bm25).

    alpha=1.0 → pure dense ORDER (values are min-max normalized, so use
    ``hybrid_scores`` when you need the raw dense values back verbatim).
    alpha=0.0 → pure BM25 order. Lists must be same length (one score per
    candidate, same candidate order in both lanes).
    """
    if len(dense_scores) != len(bm25_scores):
        raise ValueError(
            f"lane length mismatch: dense={len(dense_scores)} "
            f"bm25={len(bm25_scores)}"
        )
    nd = _min_max(dense_scores)
    nb = _min_max(bm25_scores)
    return [alpha * d + (1.0 - alpha) * b for d, b in zip(nd, nb)]


# ─────────────────────── per-query alpha ───────────────────────────────


def predict_alpha(query: str) -> float:
    """Query-adaptive blend weight (documented heuristic).

    Returns 1.0 — pure dense, EXACTLY the current behavior — unless the query
    contains an exact-code token, detected by the regex
    ``[A-Z]{2,}[0-9_]|[A-Z_]{4,}|\\d{2,}``:

      * ``[A-Z]{2,}[0-9_]`` — a caps run followed by a digit or underscore
        (``CW22``, ``AA3D``, ``JPD17``),
      * ``[A-Z_]{4,}``      — a long all-caps/underscore code (``AP_CORNICE``,
        ``NETLOAD``),
      * ``\\d{2,}``          — a multi-digit id (``9820``, port ``48885``).

    Rationale: such tokens are near-unique identifiers; embedding lanes dilute
    them while BM25's idf spikes on them. 0.5 gives both lanes equal say — the
    dense lane still breaks ties among docs sharing the code, but a doc that
    actually CONTAINS the code cannot be buried by fuzzy semantic neighbours.
    """
    if _CODE_QUERY_RE.search(query or ""):
        return 0.5
    return 1.0


# ─────────────────────── convenience: one-call hybrid ──────────────────


def hybrid_scores(
    query: str,
    texts: Sequence[str],
    dense_scores: Sequence[float],
    alpha: Optional[float] = None,
) -> list[float]:
    """Blend dense scores with a BM25 lane over `texts` for `query`.

    ``alpha=None`` → ``predict_alpha(query)``. ``alpha == 1.0`` returns
    ``list(dense_scores)`` UNCHANGED (no normalization, no BM25 pass) — this is
    the zero-risk guard: the pure-dense path is bit-identical to passing dense
    scores straight through.
    """
    if len(texts) != len(dense_scores):
        raise ValueError(
            f"texts/dense length mismatch: {len(texts)} vs {len(dense_scores)}"
        )
    if alpha is None:
        alpha = predict_alpha(query)
    if alpha == 1.0:
        return list(dense_scores)
    return blend(dense_scores, BM25(texts).scores(query), alpha)
