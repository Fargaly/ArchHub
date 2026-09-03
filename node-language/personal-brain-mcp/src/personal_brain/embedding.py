"""Brain #31 multimodal · CLIP-style vision embedding helper.

Per founder ask 2026-05-26: "this brain should have a way to understand
geometry & pictures."

Day-4 deliverable: a 512-dim CLIP embedding for IMAGE fragments + the
matching cosine helper. Brain #31 day-5 (similarity query) uses the
embedding as the relevance signal AFTER the day-3 perceptual-hash
hamming-distance pre-filter narrows the candidate set.

Why CLIP
--------
CLIP (Contrastive Language-Image Pretraining) maps images AND text into
the same vector space. That gives us two queries for free:

  - **image → image**: "find renders that look like this reference"
  - **text → image**: "find renders matching the prompt 'south facade
    with brick cladding'" — the brain returns image fragments without
    them ever having been described in text

The cross-modal query is the bigger unlock: AEC users have visual
references (mood boards, precedent photos) but search by typing.

Dependencies
------------
sentence-transformers + torch are heavy (~500MB on disk + ~2GB RAM
when loaded). They're lazy-imported the first time `embed_image` or
`embed_text` is called. When missing, the functions return None and
the caller falls back to phash-only similarity (lossy but better
than nothing).

Model
-----
Default: `sentence-transformers/clip-ViT-B-32`. ~150MB download,
512-dim output, runs CPU-only ~200ms per image on a modern laptop.
Override via env var `ARCHHUB_BRAIN_CLIP_MODEL` to use a beefier model.

Caching
-------
Sentence-Transformers caches the downloaded weights under
`~/.cache/huggingface/`. First call blocks on download (~1 min on
fast connection); subsequent calls instant.
"""
from __future__ import annotations

import io
import math
import os
from typing import Optional


# Module-level cache of the loaded model so subsequent embeds reuse it.
_MODEL = None
_MODEL_NAME = os.environ.get(
    "ARCHHUB_BRAIN_CLIP_MODEL",
    "sentence-transformers/clip-ViT-B-32",
)


def _load_model():
    """Lazy-load the CLIP model. Returns None when deps absent."""
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
    except Exception:
        return None
    try:
        _MODEL = SentenceTransformer(_MODEL_NAME)
    except Exception:
        _MODEL = None
    return _MODEL


# ── Image / text embedding ────────────────────────────────────────


def embed_image(payload: bytes) -> Optional[list[float]]:
    """Return a 512-dim float vector for an image, or None if CLIP
    isn't installed / image can't be decoded.

    Caller should handle the absence gracefully — the day-5 similarity
    query falls back to perceptual-hash-only ranking when embedding is
    None.
    """
    model = _load_model()
    if model is None:
        return None
    try:
        from PIL import Image  # type: ignore
    except Exception:
        return None
    try:
        with Image.open(io.BytesIO(payload)) as im:
            im = im.convert("RGB")
            vec = model.encode([im])
    except Exception:
        return None
    if vec is None or len(vec) == 0:
        return None
    return [float(x) for x in vec[0]]


def embed_text(text: str) -> Optional[list[float]]:
    """Return a 512-dim float vector for free-form text. Lives in the
    same CLIP space as `embed_image` so cross-modal queries (text →
    image / image → text) work via cosine on the two vectors."""
    if not text:
        return None
    model = _load_model()
    if model is None:
        return None
    try:
        vec = model.encode([text])
    except Exception:
        return None
    if vec is None or len(vec) == 0:
        return None
    return [float(x) for x in vec[0]]


# ── Vector math (pure-stdlib · always available) ──────────────────


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity in [-1, 1] · 1 = identical direction, 0 =
    orthogonal, -1 = opposite. Returns 0 for zero-length / mismatched
    vectors."""
    if not a or not b:
        return 0.0
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def is_clip_available() -> bool:
    """Cheap probe — caller can short-circuit a search to phash-only
    when CLIP isn't installed without paying the model-load cost."""
    try:
        import sentence_transformers  # noqa: F401  # type: ignore
        import PIL  # noqa: F401  # type: ignore
    except Exception:
        return False
    return True
