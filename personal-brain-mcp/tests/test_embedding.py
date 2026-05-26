"""Brain #31 day-4 · CLIP embedding helper tests.

CLIP / sentence-transformers / torch are HEAVY (~500MB download · ~2GB
RAM when loaded). Tests that exercise the embedding path are gated on
their availability via skipif. The cosine helper is pure stdlib and is
tested always.

Pins:
- cosine returns expected values for identity / orthogonal / opposite
- cosine returns 0 for empty + mismatched-length vectors
- is_clip_available reports the truth without raising
- embed_image / embed_text gracefully return None when CLIP missing
- embed_text round-trips a 512-dim vector when CLIP available
"""
from __future__ import annotations

import io
import math

import pytest

from personal_brain.embedding import (
    cosine,
    embed_image,
    embed_text,
    is_clip_available,
)


CLIP_OK = is_clip_available()


# ── cosine (always available) ─────────────────────────────────────


def test_cosine_identical_is_one():
    a = [1.0, 2.0, 3.0]
    assert math.isclose(cosine(a, a), 1.0, abs_tol=1e-9)


def test_cosine_orthogonal_is_zero():
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert math.isclose(cosine(a, b), 0.0, abs_tol=1e-9)


def test_cosine_opposite_is_minus_one():
    a = [1.0, 0.0]
    b = [-1.0, 0.0]
    assert math.isclose(cosine(a, b), -1.0, abs_tol=1e-9)


def test_cosine_empty_returns_zero():
    assert cosine([], [1.0]) == 0.0
    assert cosine([1.0], []) == 0.0
    assert cosine([], []) == 0.0


def test_cosine_length_mismatch_returns_zero():
    assert cosine([1.0, 2.0], [1.0]) == 0.0


def test_cosine_zero_vector_returns_zero():
    """All-zero vector has no direction — cosine is undefined,
    function returns 0 not NaN."""
    assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_cosine_scale_invariant():
    """cos(a, 2a) == 1 — only direction matters, not magnitude."""
    a = [1.0, 2.0, 3.0]
    b = [2.0, 4.0, 6.0]
    assert math.isclose(cosine(a, b), 1.0, abs_tol=1e-9)


# ── is_clip_available ──────────────────────────────────────────────


def test_is_clip_available_returns_bool():
    assert isinstance(is_clip_available(), bool)


# ── embed_image / embed_text — graceful absence ───────────────────


def test_embed_text_empty_returns_none():
    assert embed_text("") is None
    assert embed_text(None) is None


@pytest.mark.skipif(CLIP_OK, reason="CLIP installed — tested in next block")
def test_embed_image_returns_none_when_clip_missing():
    assert embed_image(b"any") is None


@pytest.mark.skipif(CLIP_OK, reason="CLIP installed — tested in next block")
def test_embed_text_returns_none_when_clip_missing():
    assert embed_text("hello") is None


# ── embed paths — only when CLIP available ────────────────────────


@pytest.mark.skipif(not CLIP_OK, reason="CLIP not installed")
def test_embed_text_returns_512_dim_vector():
    vec = embed_text("south facade with brick cladding")
    assert vec is not None
    assert len(vec) == 512
    assert all(isinstance(x, float) for x in vec)


@pytest.mark.skipif(not CLIP_OK, reason="CLIP not installed")
def test_embed_image_returns_512_dim_vector():
    from PIL import Image  # type: ignore
    img = Image.new("RGB", (64, 64), (128, 64, 32))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    vec = embed_image(buf.getvalue())
    assert vec is not None
    assert len(vec) == 512


@pytest.mark.skipif(not CLIP_OK, reason="CLIP not installed")
def test_embed_image_returns_none_for_garbage():
    """Non-image bytes can't decode → returns None, doesn't raise."""
    assert embed_image(b"not an image") is None


@pytest.mark.skipif(not CLIP_OK, reason="CLIP not installed")
def test_cross_modal_text_to_image_cosine_higher_for_match():
    """The whole point of CLIP: a text description should be CLOSER
    in cosine space to a matching image than to a mismatched one.
    Uses synthetic colour blocks since we don't have real renders
    in the test fixtures — the test asserts directional consistency,
    not absolute thresholds."""
    from PIL import Image  # type: ignore
    red = Image.new("RGB", (64, 64), (220, 30, 30))
    blue = Image.new("RGB", (64, 64), (30, 30, 220))
    bufs = []
    for img in (red, blue):
        b = io.BytesIO()
        img.save(b, format="PNG")
        bufs.append(b.getvalue())
    v_red = embed_image(bufs[0])
    v_blue = embed_image(bufs[1])
    v_query = embed_text("a deep red square")
    assert v_red is not None
    assert v_blue is not None
    assert v_query is not None
    # The query phrase should cosine-match red > blue.
    sim_red = cosine(v_query, v_red)
    sim_blue = cosine(v_query, v_blue)
    assert sim_red > sim_blue, (
        f"text→image should prefer red ({sim_red:.3f}) over blue ({sim_blue:.3f})"
    )
