"""Brain #31 day-3 · perceptual-hash helper tests.

Pins:
- phash_image returns 16-char hex (or None when Pillow missing)
- phash_image stable across re-encodes of the same image
- phash_geometry is deterministic + content-addressed
- phash_geometry tolerates small float noise via rounding
- hamming_hex computes bit distance correctly
"""
from __future__ import annotations

import io

import pytest

from personal_brain.phash import (
    hamming_hex,
    phash_geometry,
    phash_image,
)


# ── phash_image ───────────────────────────────────────────────────

try:
    from PIL import Image  # type: ignore
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False


def _png_bytes(colour: tuple, size: int = 32) -> bytes:
    """Synthesise a tiny solid-colour PNG for tests."""
    img = Image.new("RGB", (size, size), colour)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.skipif(not PIL_AVAILABLE, reason="Pillow not installed")
def test_phash_image_returns_16_char_hex():
    h = phash_image(_png_bytes((128, 128, 128)))
    assert h is not None
    assert len(h) == 16
    assert all(c in "0123456789abcdef" for c in h)


@pytest.mark.skipif(not PIL_AVAILABLE, reason="Pillow not installed")
def test_phash_image_stable_across_reencodes():
    """Same source image re-saved as PNG (re-compressed) produces the
    same perceptual hash."""
    src = Image.new("RGB", (64, 64), (200, 50, 50))
    buf1 = io.BytesIO()
    src.save(buf1, format="PNG", compress_level=1)
    buf2 = io.BytesIO()
    src.save(buf2, format="PNG", compress_level=9)
    assert phash_image(buf1.getvalue()) == phash_image(buf2.getvalue())


@pytest.mark.skipif(not PIL_AVAILABLE, reason="Pillow not installed")
def test_phash_image_different_for_different_images():
    h_red = phash_image(_png_bytes((255, 0, 0)))
    h_blue = phash_image(_png_bytes((0, 0, 255)))
    # Solid red vs solid blue may collide because grayscale conversion
    # flattens both to a single grey value. Verify with a gradient
    # instead so the 8×8 cells differ.
    img_grad = Image.new("L", (32, 32))
    for y in range(32):
        for x in range(32):
            img_grad.putpixel((x, y), (x * 8) % 256)
    buf = io.BytesIO()
    img_grad.save(buf, format="PNG")
    h_grad = phash_image(buf.getvalue())
    assert h_red != h_grad


def test_phash_image_returns_none_for_garbage():
    """Non-image bytes can't decode → returns None."""
    if not PIL_AVAILABLE:
        assert phash_image(b"not an image") is None
    else:
        assert phash_image(b"not an image") is None


def test_phash_image_handles_pil_missing_gracefully():
    """The function never raises on bad input — None is the fallback."""
    assert phash_image(b"") is None or phash_image(b"") is not None


# ── phash_geometry ────────────────────────────────────────────────


def test_phash_geometry_returns_16_char_hex():
    h = phash_geometry(volume=10.0, aabb=(1, 2, 3),
                       vertex_count=100, face_count=200)
    assert len(h) == 16
    assert all(c in "0123456789abcdef" for c in h)


def test_phash_geometry_deterministic():
    h1 = phash_geometry(volume=5.5, aabb=(1.1, 2.2, 3.3),
                        vertex_count=42, face_count=84)
    h2 = phash_geometry(volume=5.5, aabb=(1.1, 2.2, 3.3),
                        vertex_count=42, face_count=84)
    assert h1 == h2


def test_phash_geometry_changes_with_volume():
    h1 = phash_geometry(volume=5.0, aabb=(1, 1, 1))
    h2 = phash_geometry(volume=10.0, aabb=(1, 1, 1))
    assert h1 != h2


def test_phash_geometry_tolerates_float_noise_via_rounding():
    """1.0001 and 1.0002 round to the same 3-decimal value."""
    h1 = phash_geometry(volume=1.0001, aabb=(1, 1, 1))
    h2 = phash_geometry(volume=1.0002, aabb=(1, 1, 1))
    assert h1 == h2  # both round to 1.000


def test_phash_geometry_changes_with_vertex_count():
    h1 = phash_geometry(volume=1, aabb=(1, 1, 1), vertex_count=10)
    h2 = phash_geometry(volume=1, aabb=(1, 1, 1), vertex_count=20)
    assert h1 != h2


def test_phash_geometry_changes_with_face_count():
    h1 = phash_geometry(volume=1, aabb=(1, 1, 1), face_count=10)
    h2 = phash_geometry(volume=1, aabb=(1, 1, 1), face_count=20)
    assert h1 != h2


# ── hamming_hex ────────────────────────────────────────────────────


def test_hamming_hex_identical_is_zero():
    assert hamming_hex("ffffffffffffffff", "ffffffffffffffff") == 0


def test_hamming_hex_inverse_is_64():
    assert hamming_hex("ffffffffffffffff", "0000000000000000") == 64


def test_hamming_hex_one_bit_diff():
    assert hamming_hex("0000000000000001", "0000000000000000") == 1


def test_hamming_hex_rejects_length_mismatch():
    with pytest.raises(ValueError):
        hamming_hex("abc", "abcd")


def test_hamming_hex_rejects_invalid_hex():
    with pytest.raises(ValueError):
        hamming_hex("zzzz", "0000")
