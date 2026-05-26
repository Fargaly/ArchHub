"""Brain #31 multimodal · perceptual-hash helpers.

Per founder ask 2026-05-26: "this brain should have a way to understand
geometry & pictures."

Day-3 deliverable: derive a 64-bit perceptual hash from image bytes OR
geometry summary so Fragment.perceptual_hash gets populated. The hash
lets the future similarity-query slice do a cheap Hamming-distance
pre-filter before running the more expensive CLIP-style embedding match.

Algorithms
----------
**phash_image(bytes)** — classic DCT-style perceptual hash:
  1. Decode → grayscale (PIL if available; bail to None if not).
  2. Resize to 32×32 then down-sample to 8×8 (DCT preserves low freq).
  3. Compute mean.
  4. Each cell → 1 if ≥ mean else 0 → 64 bits → 16-char hex.

**phash_geometry(volume, aabb, vertex_count, face_count)** — pure stdlib:
  serialise the 6 scalars into a canonical string, sha256, take the
  first 16 hex chars (64 bits). Similar geometries (same volume + bbox
  + counts) → same hash. NOT the same as classic phash for images —
  it's a content-identity hash that lets us spot near-duplicates by
  size rather than visual similarity (which BRep / mesh inherently
  lacks).

**hamming_hex(a, b)** — bit-distance between two 16-char hex hashes.
  Used by the future similarity query.

PIL dependency
--------------
phash_image lazy-imports `PIL.Image`. When Pillow isn't installed it
returns None — caller is responsible for handling the absence (e.g.
skip phash + rely on CLIP embedding alone).
"""
from __future__ import annotations

import hashlib
import io
from typing import Optional, Tuple


# ── Image perceptual hash ─────────────────────────────────────────


def phash_image(payload: bytes) -> Optional[str]:
    """64-bit perceptual hash of an image as 16-char hex.

    Returns None when Pillow isn't installed OR when payload can't be
    decoded as an image (callers tolerate the absence; CLIP embedding
    is the fallback similarity signal in the day-5 query).
    """
    try:
        from PIL import Image  # type: ignore
    except Exception:
        return None
    try:
        with Image.open(io.BytesIO(payload)) as im:
            # Convert to grayscale (one channel for the comparison)
            im = im.convert("L")
            # Resize to 32×32 then downsample to 8×8 — classic pHash
            # shape. LANCZOS for the first pass preserves edges; the
            # second downsample is a plain average.
            im = im.resize((32, 32), Image.LANCZOS)
            im = im.resize((8, 8), Image.BOX)
            pixels = list(im.getdata())
    except Exception:
        return None

    if len(pixels) != 64:
        return None
    avg = sum(pixels) / 64
    bits = 0
    for i, p in enumerate(pixels):
        if p >= avg:
            bits |= (1 << (63 - i))
    # Pad to exactly 16 hex chars.
    return f"{bits:016x}"


# ── Geometry derived hash ─────────────────────────────────────────


def phash_geometry(
    *,
    volume: float = 0.0,
    aabb: Tuple[float, float, float] = (0.0, 0.0, 0.0),
    vertex_count: int = 0,
    face_count: int = 0,
    rounding: int = 3,
) -> str:
    """Content-identity hash for geometry — 64-bit hex.

    Bounds are rounded to `rounding` decimals so floating-point noise
    doesn't perturb the hash for "the same wall produced twice." Two
    geometries with identical (volume, aabb, vertex_count, face_count)
    after rounding collide — feature, not bug: it's how we detect
    near-duplicates cheaply before the expensive shape-match.
    """
    canonical = (
        f"v={round(float(volume), rounding)}|"
        f"aabb={round(float(aabb[0]), rounding)},"
        f"{round(float(aabb[1]), rounding)},"
        f"{round(float(aabb[2]), rounding)}|"
        f"vc={int(vertex_count)}|"
        f"fc={int(face_count)}"
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return digest[:16]


# ── Hamming distance ──────────────────────────────────────────────


def hamming_hex(a: str, b: str) -> int:
    """Bit-distance between two equal-length hex strings.

    Returns the count of differing bits. For two 16-char hex hashes
    (= 64 bits) the result is in [0, 64].

    Raises ValueError when lengths differ.
    """
    if len(a) != len(b):
        raise ValueError(
            f"hamming_hex: length mismatch ({len(a)} vs {len(b)})"
        )
    try:
        ai = int(a, 16)
        bi = int(b, 16)
    except ValueError as ex:
        raise ValueError(f"invalid hex: {ex}") from ex
    return bin(ai ^ bi).count("1")
