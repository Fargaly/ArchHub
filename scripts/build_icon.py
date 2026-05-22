"""Generate the ArchHub .ico + .icns from the brand v0.1 ArchMark.

Renders ArchMark via Qt's QPainter using the same path geometry as
`studio_shell.ArchMark`, then packs three release-ready assets:
  - `app/assets/archhub.ico`  — Windows, 7 sizes (16..256) via Pillow
  - `app/assets/archhub.icns` — macOS, PNG-payload blocks (32..1024)
  - `app/assets/archhub.png`  — 256-px fallback (Linux AppImage icon)
Run once whenever the brand mark changes.
"""
from __future__ import annotations

import os
import struct
import sys
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, Qt
from PyQt6.QtGui import (
    QBrush, QColor, QPainter, QPainterPath, QPen, QPixmap,
)
from PyQt6.QtWidgets import QApplication


def render_archmark(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    terra = QColor("#c96442")
    terra_deep = QColor("#8a3a25")
    paper = QColor("#f7f4ee")

    # Drawing geometry comes from brand.jsx::ArchMark / studio_shell.ArchMark.
    p.scale(size / 64.0, size / 64.0)

    path = QPainterPath()
    path.moveTo(10, 56)
    path.lineTo(10, 32)
    path.arcTo(10, 10, 44, 44, 180, -180)
    path.lineTo(54, 56)
    pen = QPen(terra)
    pen.setWidthF(4.5)
    pen.setCapStyle(Qt.PenCapStyle.SquareCap)
    p.setPen(pen)
    p.drawPath(path)

    inner = QPainterPath()
    inner.moveTo(18, 56)
    inner.lineTo(18, 34)
    inner.arcTo(18, 20, 28, 28, 180, -180)
    inner.lineTo(46, 56)
    c_inner = QColor(terra)
    c_inner.setAlphaF(0.45)
    pen2 = QPen(c_inner)
    pen2.setWidthF(1.3)
    p.setPen(pen2)
    p.drawPath(inner)

    p.setPen(QPen(terra_deep, 2.4))
    p.setBrush(QBrush(paper))
    p.drawEllipse(QPointF(32, 22), 5.2, 5.2)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(terra_deep))
    p.drawEllipse(QPointF(32, 22), 1.8, 1.8)

    pen3 = QPen(terra)
    pen3.setWidthF(1.5)
    pen3.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen3)
    p.drawLine(6, 58, 58, 58)
    p.end()
    return pm


# .icns OSType -> pixel size. PNG-payload types only (macOS 10.7+);
# the legacy raw-RGB/mask types are deliberately omitted — every macOS
# that can run a PyQt6 build reads the PNG form. ic13/ic14 are the @2x
# retina variants and reuse the same PNG bytes as ic08/ic09.
_ICNS_TYPES = [
    (b"ic11", 32),     # 16x16@2x
    (b"ic12", 64),     # 32x32@2x
    (b"ic07", 128),    # 128x128
    (b"ic08", 256),    # 256x256
    (b"ic13", 256),    # 128x128@2x
    (b"ic09", 512),    # 512x512
    (b"ic14", 512),    # 256x256@2x
    (b"ic10", 1024),   # 512x512@2x
]


def _png_bytes(size: int) -> bytes:
    """Render ArchMark at `size` and return PNG-encoded bytes (no disk)."""
    pm = render_archmark(size)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    pm.save(buf, "PNG")
    buf.close()
    return bytes(ba)


def build_icns(out_dir: Path) -> Path:
    """Pack an Apple .icns from the ArchMark geometry.

    .icns layout: the 'icns' magic + a uint32 big-endian total file
    length, then a flat list of icon blocks. Each block is a 4-byte
    OSType, a uint32 big-endian length (counting its own 8-byte
    header), then the payload — here always a PNG. No table of
    contents: macOS walks the blocks linearly."""
    cache: dict[int, bytes] = {}
    blocks = bytearray()
    for ostype, size in _ICNS_TYPES:
        if size not in cache:
            cache[size] = _png_bytes(size)
        data = cache[size]
        blocks += ostype
        blocks += struct.pack(">I", 8 + len(data))
        blocks += data
    icns = b"icns" + struct.pack(">I", 8 + len(blocks)) + bytes(blocks)
    icns_path = out_dir / "archhub.icns"
    icns_path.write_bytes(icns)
    print(f"rendered .icns -> {icns_path.name} "
          f"({len(_ICNS_TYPES)} entries, {len(cache)} unique sizes)")
    return icns_path


def verify_icns(icns_path: Path) -> bool:
    """Parse the .icns back and decode every block — prove it's valid."""
    raw = icns_path.read_bytes()
    if raw[:4] != b"icns":
        print(f"ERROR: bad magic {raw[:4]!r}", file=sys.stderr)
        return False
    declared = struct.unpack(">I", raw[4:8])[0]
    if declared != len(raw):
        print(f"ERROR: length header {declared} != file size {len(raw)}",
              file=sys.stderr)
        return False
    try:
        from PIL import Image
    except Exception:
        print("WARN: Pillow absent — skipped per-block PNG decode.")
        return True
    want = dict(_ICNS_TYPES)
    off, seen = 8, 0
    while off < len(raw):
        ostype = raw[off:off + 4]
        blen = struct.unpack(">I", raw[off + 4:off + 8])[0]
        if blen < 8 or off + blen > len(raw):
            print(f"ERROR: {ostype!r} block length {blen} out of bounds",
                  file=sys.stderr)
            return False
        img = Image.open(BytesIO(raw[off + 8:off + blen]))
        exp = want.get(ostype)
        if exp is not None and img.size != (exp, exp):
            print(f"ERROR: {ostype!r} is {img.size}, expected "
                  f"{exp}x{exp}", file=sys.stderr)
            return False
        seen += 1
        off += blen
    if seen != len(_ICNS_TYPES):
        print(f"ERROR: parsed {seen} blocks, expected {len(_ICNS_TYPES)}",
              file=sys.stderr)
        return False
    print(f"verified .icns: {seen}/{len(_ICNS_TYPES)} blocks decode clean")
    return True


def main() -> int:
    app = QApplication(sys.argv)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    out_dir = Path(__file__).resolve().parent.parent / "app" / "assets"
    out_dir.mkdir(parents=True, exist_ok=True)
    png_paths: list[Path] = []
    for s in sizes:
        pm = render_archmark(s)
        png_path = out_dir / f"archmark_{s}.png"
        pm.save(str(png_path), "PNG")
        png_paths.append(png_path)
        print(f"rendered {s}x{s} -> {png_path.name}")

    # Build multi-size .ico via Pillow.
    try:
        from PIL import Image
    except Exception:
        print("ERROR: Pillow required (`pip install Pillow`).", file=sys.stderr)
        return 1
    # Pillow ICO save uses `sizes` to downscale from the SOURCE image,
    # and `append_images` to embed additional sizes at their native
    # resolution. Use the largest (256) as source so 16/24/32/48/64/128
    # come from append_images at their pre-rendered crisp sizes.
    imgs = [Image.open(str(p)) for p in png_paths]
    biggest = imgs[-1]
    others = imgs[:-1]
    ico_path = out_dir / "archhub.ico"
    biggest.save(
        str(ico_path),
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=others,
    )
    # Also overwrite the 256-px PNG as the fallback.
    pm256 = render_archmark(256)
    pm256.save(str(out_dir / "archhub.png"), "PNG")
    # Clean up intermediate per-size PNGs.
    for p in png_paths:
        try:
            p.unlink(missing_ok=True)
        except Exception:
            pass
    size_kb = ico_path.stat().st_size / 1024
    print(f".ico written: {ico_path}  ({size_kb:.1f} KB, {len(sizes)} sizes)")

    # macOS .icns — packed straight from the same ArchMark geometry.
    icns_path = build_icns(out_dir)
    if not verify_icns(icns_path):
        print("ERROR: .icns failed verification.", file=sys.stderr)
        return 1
    icns_kb = icns_path.stat().st_size / 1024
    print(f".icns written: {icns_path}  ({icns_kb:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
