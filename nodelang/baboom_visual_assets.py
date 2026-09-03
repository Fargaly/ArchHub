"""Physical BABOOM visual-asset preflight with no graph or UI authority.

The founder-supplied source PNGs often contain a *painted* checkerboard rather
than an alpha channel. Rendering those files in a transparent desktop window
creates the visible rectangular box that a companion must never show. This
module validates a candidate atlas before a future native renderer loads it; it
does not copy assets, persist metadata, or create a second visual state store.
"""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path


class BaboomVisualAssetError(ValueError):
    """A candidate visual asset is unsuitable for the native companion."""


@dataclass(frozen=True, slots=True)
class BaboomSpriteAtlas:
    """Validated, disposable facts about one alpha-capable PNG atlas."""

    path: Path
    width: int
    height: int
    columns: int
    rows: int
    cell_width: int
    cell_height: int
    # Drawn frames per row. A row is not obliged to fill the grid, and a
    # player that cycles past its art renders an empty cell. Defaulted so
    # a hand-built atlas in a court stays valid.
    frame_counts: tuple[int, ...] = ()
    # Where the staff orb sits in each drawn frame, per row: the centroid of
    # the blue-dominant pixels, measured from the art. The companion lights
    # the orb with the brain state; a light that does not follow the staff
    # would read as a bug.
    orb_points: tuple[tuple[tuple[int, int] | None, ...], ...] = ()

    def orb_point(self, row: int, frame: int) -> tuple[int, int] | None:
        """The staff orb (x, y) inside the cell for one drawn frame, or None."""
        if 0 <= row < len(self.orb_points):
            points = self.orb_points[row]
            if 0 <= frame < len(points):
                return points[frame]
        return None

    def frames_in_row(self, row: int) -> int:
        """Frames the given motion row actually carries, never fewer than one."""
        if 0 <= row < len(self.frame_counts):
            return max(1, self.frame_counts[row])
        return max(1, self.columns)


_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
CODEX_PET_V2_COLUMNS = 8
CODEX_PET_V2_ROWS = 11
CODEX_PET_V2_CELL_WIDTH = 192
CODEX_PET_V2_CELL_HEIGHT = 208


def _paeth(left: int, above: int, upper_left: int) -> int:
    estimate = left + above - upper_left
    left_distance = abs(estimate - left)
    above_distance = abs(estimate - above)
    upper_left_distance = abs(estimate - upper_left)
    if left_distance <= above_distance and left_distance <= upper_left_distance:
        return left
    if above_distance <= upper_left_distance:
        return above
    return upper_left


def _orb_points_per_row(
    image_rows: tuple[bytes, ...],
    *,
    columns: int,
    rows: int,
    cell_width: int,
    cell_height: int,
) -> tuple[tuple[tuple[int, int] | None, ...], ...]:
    """The staff orb per cell: centroid of the blue-dominant, opaque pixels."""
    out: list[tuple[tuple[int, int] | None, ...]] = []
    for row_index in range(rows):
        points: list[tuple[int, int] | None] = []
        for column_index in range(columns):
            sx = sy = n = 0
            for local_y in range(cell_height):
                scanline = image_rows[row_index * cell_height + local_y]
                base = column_index * cell_width * 4
                for local_x in range(cell_width):
                    o = base + local_x * 4
                    r, g, b, a = scanline[o], scanline[o + 1], scanline[o + 2], scanline[o + 3]
                    if a > 200 and b > 150 and b > r + 60 and g > 90:
                        sx += local_x; sy += local_y; n += 1
            points.append((round(sx / n), round(sy / n)) if n else None)
        out.append(tuple(points))
    return tuple(out)


def _drawn_frames_per_row(
    image_rows: tuple[bytes, ...],
    *,
    columns: int,
    rows: int,
    cell_width: int,
    cell_height: int,
) -> tuple[int, ...]:
    """How many frames each motion row actually carries art for.

    A sheet is a grid, but an animation is not obliged to fill its row: this
    atlas draws seven idle poses and six for most actions, leaving the last
    cells of those rows fully transparent. A player that cycles the full
    grid therefore renders nothing every few ticks, and the companion blinks
    out of existence. Counting the drawn frames here is what lets the player
    cycle only the poses that exist.

    Trailing empties are what a spritesheet leaves behind, so counting stops
    at the first blank cell rather than skipping holes -- a gap in the middle
    of a row is broken art, not a shorter animation, and is left visible.
    """
    counts: list[int] = []
    for row_index in range(rows):
        drawn = 0
        for column_index in range(columns):
            top = row_index * cell_height
            left_byte = column_index * cell_width * 4
            right_byte = left_byte + cell_width * 4
            opaque = any(
                alpha > 0
                for scanline in image_rows[top:top + cell_height]
                for alpha in scanline[left_byte + 3:right_byte:4]
            )
            if not opaque:
                break
            drawn += 1
        counts.append(drawn or 1)
    return tuple(counts)


def _unfilter_rgba_rows(payload: bytes, *, width: int, height: int) -> tuple[bytes, ...]:
    stride = width * 4
    expected_size = height * (stride + 1)
    if len(payload) != expected_size:
        raise BaboomVisualAssetError("PNG image data size is invalid")
    rows: list[bytes] = []
    offset = 0
    prior = bytes(stride)
    for _ in range(height):
        filter_kind = payload[offset]
        encoded = payload[offset + 1:offset + stride + 1]
        offset += stride + 1
        decoded = bytearray(stride)
        for index, value in enumerate(encoded):
            left = decoded[index - 4] if index >= 4 else 0
            above = prior[index]
            upper_left = prior[index - 4] if index >= 4 else 0
            if filter_kind == 0:
                decoded[index] = value
            elif filter_kind == 1:
                decoded[index] = (value + left) & 0xFF
            elif filter_kind == 2:
                decoded[index] = (value + above) & 0xFF
            elif filter_kind == 3:
                decoded[index] = (value + ((left + above) // 2)) & 0xFF
            elif filter_kind == 4:
                decoded[index] = (value + _paeth(left, above, upper_left)) & 0xFF
            else:
                raise BaboomVisualAssetError("PNG scanline filter is unsupported")
        row = bytes(decoded)
        rows.append(row)
        prior = row
    return tuple(rows)


def inspect_baboom_sprite_atlas(
    path: str | Path,
    *,
    columns: int = 4,
    rows: int = 3,
) -> BaboomSpriteAtlas:
    """Validate a non-interlaced RGBA PNG atlas with actual transparency.

    A true alpha channel alone is not enough: at least one source pixel must
    have alpha below 255. That rejects an opaque PNG that merely advertises RGBA
    and fails before a desktop renderer can show a visible rectangle.
    """
    if (
        type(columns) is not int
        or type(rows) is not int
        or columns < 1
        or rows < 1
    ):
        raise BaboomVisualAssetError("BABOOM atlas grid is invalid")
    candidate = Path(path).expanduser().resolve()
    if candidate.suffix.casefold() != ".png" or not candidate.is_file():
        raise BaboomVisualAssetError("BABOOM atlas must be an existing PNG file")
    try:
        source = candidate.read_bytes()
    except OSError as exc:
        raise BaboomVisualAssetError("BABOOM atlas cannot be read") from exc
    if not source.startswith(_PNG_SIGNATURE):
        raise BaboomVisualAssetError("BABOOM atlas is not a PNG file")
    offset = len(_PNG_SIGNATURE)
    width = height = bit_depth = color_type = interlace = None
    idat: list[bytes] = []
    while offset < len(source):
        if offset + 12 > len(source):
            raise BaboomVisualAssetError("PNG chunk framing is invalid")
        length = struct.unpack(">I", source[offset:offset + 4])[0]
        kind = source[offset + 4:offset + 8]
        data_start = offset + 8
        data_end = data_start + length
        if data_end + 4 > len(source):
            raise BaboomVisualAssetError("PNG chunk extends beyond file")
        data = source[data_start:data_end]
        offset = data_end + 4
        if kind == b"IHDR":
            if width is not None or len(data) != 13:
                raise BaboomVisualAssetError("PNG header is invalid")
            width, height, bit_depth, color_type, compression, filter_method, interlace = (
                struct.unpack(">IIBBBBB", data)
            )
            if compression != 0 or filter_method != 0:
                raise BaboomVisualAssetError("PNG encoding is unsupported")
        elif kind == b"IDAT":
            idat.append(data)
        elif kind == b"IEND":
            break
    if (
        width is None
        or height is None
        or bit_depth != 8
        or color_type != 6
        or interlace != 0
        or not idat
    ):
        raise BaboomVisualAssetError(
            "BABOOM atlas must be a non-interlaced 8-bit RGBA PNG"
        )
    if (
        width < columns * 64
        or height < rows * 64
        or width % columns
        or height % rows
    ):
        raise BaboomVisualAssetError("BABOOM atlas dimensions do not match its grid")
    try:
        decoded = zlib.decompress(b"".join(idat))
    except zlib.error as exc:
        raise BaboomVisualAssetError("PNG image data cannot be decoded") from exc
    image_rows = _unfilter_rgba_rows(decoded, width=width, height=height)
    if not any(alpha < 255 for row in image_rows for alpha in row[3::4]):
        raise BaboomVisualAssetError("BABOOM atlas has no actual transparent pixels")
    cell_width = width // columns
    cell_height = height // rows
    return BaboomSpriteAtlas(
        path=candidate,
        width=width,
        height=height,
        columns=columns,
        rows=rows,
        cell_width=cell_width,
        cell_height=cell_height,
        frame_counts=_drawn_frames_per_row(
            image_rows,
            columns=columns,
            rows=rows,
            cell_width=cell_width,
            cell_height=cell_height,
        ),
        orb_points=_orb_points_per_row(
            image_rows,
            columns=columns,
            rows=rows,
            cell_width=cell_width,
            cell_height=cell_height,
        ),
    )


def inspect_baboom_sprite_atlas_v2(path: str | Path) -> BaboomSpriteAtlas:
    """Validate the exact 8x11 Codex v2 BABOOM atlas contract.

    The generic preflight remains available for historical source inspection,
    but a native companion must not silently accept a smaller legacy grid when
    it expects the full action and look-direction set.
    """
    atlas = inspect_baboom_sprite_atlas(
        path,
        columns=CODEX_PET_V2_COLUMNS,
        rows=CODEX_PET_V2_ROWS,
    )
    if (
        atlas.cell_width != CODEX_PET_V2_CELL_WIDTH
        or atlas.cell_height != CODEX_PET_V2_CELL_HEIGHT
    ):
        raise BaboomVisualAssetError(
            "BABOOM v2 atlas cells must be 192x208 pixels"
        )
    return atlas


__all__ = [
    "BaboomSpriteAtlas", "BaboomVisualAssetError", "inspect_baboom_sprite_atlas",
    "inspect_baboom_sprite_atlas_v2",
]
