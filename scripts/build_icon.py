"""Generate the ArchHub .ico from the brand v0.1 ArchMark drawing.

Renders ArchMark at 7 sizes (16/24/32/48/64/128/256) via Qt's QPainter
using the same path geometry as `studio_shell.ArchMark`, then packs
into a multi-size .ico via Pillow. Output overwrites
`app/assets/archhub.ico`. Run once whenever the brand mark changes.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPointF, Qt
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
