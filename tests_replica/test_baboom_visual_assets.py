"""Courts for the physical BABOOM sprite-asset preflight."""
from __future__ import annotations

import struct
import zlib

import pytest

from nodelang.baboom_visual_assets import (
    BaboomVisualAssetError,
    inspect_baboom_sprite_atlas,
    inspect_baboom_sprite_atlas_v2,
)


def _png(*, width: int, height: int, rgba: bool, transparent: bool) -> bytes:
    color_type = 6 if rgba else 2
    channels = 4 if rgba else 3
    pixel = bytes((30, 50, 70, 0 if transparent else 255)) if rgba else bytes((30, 50, 70))
    payload = b"".join(
        b"\x00" + pixel * width
        for _ in range(height)
    )

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(
            ">I", zlib.crc32(kind + data) & 0xFFFFFFFF
        )

    header = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(
        b"IDAT", zlib.compress(payload)
    ) + chunk(b"IEND", b"")


def test_real_rgba_atlas_is_admitted_and_reports_stable_cells(tmp_path):
    source = tmp_path / "baboom.png"
    source.write_bytes(_png(width=256, height=192, rgba=True, transparent=True))

    atlas = inspect_baboom_sprite_atlas(source, columns=4, rows=3)

    assert atlas.path == source.resolve()
    assert (atlas.cell_width, atlas.cell_height) == (64, 64)


@pytest.mark.parametrize("rgba,transparent,error", [
    (False, False, "RGBA"),
    (True, False, "actual transparent"),
])
def test_opaque_or_simulated_transparency_is_rejected(tmp_path, rgba, transparent, error):
    source = tmp_path / "opaque.png"
    source.write_bytes(_png(width=256, height=192, rgba=rgba, transparent=transparent))

    with pytest.raises(BaboomVisualAssetError, match=error):
        inspect_baboom_sprite_atlas(source, columns=4, rows=3)


def test_atlas_grid_must_be_exact(tmp_path):
    source = tmp_path / "misaligned.png"
    source.write_bytes(_png(width=255, height=192, rgba=True, transparent=True))

    with pytest.raises(BaboomVisualAssetError, match="dimensions"):
        inspect_baboom_sprite_atlas(source, columns=4, rows=3)


def test_v2_atlas_requires_the_extended_codex_grid_and_cell_dimensions(tmp_path):
    source = tmp_path / "baboom-v2.png"
    source.write_bytes(_png(width=1536, height=2288, rgba=True, transparent=True))

    atlas = inspect_baboom_sprite_atlas_v2(source)

    assert (atlas.columns, atlas.rows) == (8, 11)
    assert (atlas.cell_width, atlas.cell_height) == (192, 208)

    wrong_cells = tmp_path / "baboom-v2-wrong-cells.png"
    wrong_cells.write_bytes(_png(width=1024, height=704, rgba=True, transparent=True))
    with pytest.raises(BaboomVisualAssetError, match="192x208"):
        inspect_baboom_sprite_atlas_v2(wrong_cells)
