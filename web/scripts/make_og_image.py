#!/usr/bin/env python
"""make_og_image.py - render public/og.png, the social share card.

Why this exists: the site used to hand social networks an SVG
(public/og.svg). Facebook, LinkedIn, Slack and X do not rasterise SVG for
link previews, so every share of archhub.io came out as a blank card. The
Open Graph protocol (ogp.me) expects a raster image; 1200x630 is the size
every one of those crawlers renders without cropping.

Run: python scripts/make_og_image.py
The PNG it writes is committed - the deploy build does not run Python.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WEB_ROOT = Path(__file__).resolve().parent.parent
OUT = WEB_ROOT / "public" / "og.png"

W, H = 1200, 630

# Palette mirrors the :root tokens in src/layouts/Base.astro.
BG = (14, 14, 17)
INK = (236, 232, 224)
INK_SOFT = (155, 147, 138)
INK_MUTED = (94, 87, 79)
ACCENT = (217, 119, 87)
ACCENT_HI = (232, 137, 106)
LINE = (38, 38, 46)

FONT_DIR = Path("C:/Windows/Fonts")
SERIF = FONT_DIR / "georgia.ttf"
SERIF_ITALIC = FONT_DIR / "georgiai.ttf"
SANS = FONT_DIR / "segoeui.ttf"
SANS_BOLD = FONT_DIR / "segoeuib.ttf"
MONO = FONT_DIR / "consola.ttf"


def font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    if not path.exists():
        raise SystemExit(f"font not found: {path} (run this on a machine that has it)")
    return ImageFont.truetype(str(path), size)


def main() -> int:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # Faint dot grid, the same drafting-paper texture the hero uses.
    for y in range(0, H, 22):
        for x in range(0, W, 22):
            d.point((x, y), fill=(26, 26, 32))

    # Terracotta rule along the bottom edge.
    d.rectangle([0, H - 8, W, H], fill=ACCENT)

    # Mark: the arch + oculus from the nav logo, drawn at 64px scale.
    ox, oy, s = 96, 84, 1.35
    d.arc(
        [ox, oy, ox + int(64 * s), oy + int(64 * s)],
        start=180, end=360, fill=ACCENT, width=int(6 * s),
    )
    left = ox + int(3 * s)
    right = ox + int(61 * s)
    mid = oy + int(32 * s)
    bottom = oy + int(56 * s)
    d.line([left, mid, left, bottom], fill=ACCENT, width=int(6 * s))
    d.line([right, mid, right, bottom], fill=ACCENT, width=int(6 * s))
    d.line([ox - int(4 * s), bottom + int(6 * s), ox + int(68 * s), bottom + int(6 * s)],
           fill=ACCENT, width=int(2.5 * s))

    d.text((ox + int(84 * s), oy + int(18 * s)), "ArchHub", font=font(SANS_BOLD, 46), fill=INK)

    # Headline, Instrument Serif's own fallback stack starts at Georgia.
    d.text((96, 250), "The graph-first AI workspace", font=font(SERIF, 72), fill=INK)
    line2 = font(SERIF, 72)
    d.text((96, 336), "for ", font=line2, fill=INK)
    lead = d.textlength("for ", font=line2)
    d.text((96 + lead, 336), "architects & AEC teams.",
           font=font(SERIF_ITALIC, 72), fill=ACCENT_HI)

    d.text((96, 452), "One canvas - every host you already use - local-first.",
           font=font(SANS, 30), fill=INK_SOFT)

    d.line([96, 522, W - 96, 522], fill=LINE, width=1)
    d.text((96, 542), "archhub.io", font=font(MONO, 26), fill=INK_MUTED)
    right_note = "MIT - open beta"
    f = font(MONO, 26)
    d.text((W - 96 - d.textlength(right_note, font=f), 542), right_note, font=f, fill=INK_MUTED)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, "PNG", optimize=True)
    print(f"[og] wrote {OUT} ({OUT.stat().st_size} bytes, {W}x{H})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
