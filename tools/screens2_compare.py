"""Reproducible plate comparisons; data differences are intentionally not masked."""
from pathlib import Path
import hashlib
import json

import numpy as np
from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
PLATES = {
    "home": "082-2026-10-13_5.6b_home2",
    "canvas": "061-2026-10-13_5.1_canvas_session",
    "system": "065-2026-10-13_5.4_settings_system_graph",
}


def block_ssim(a, b):
    """Mean luminance SSIM over 8x8 windows, standard C1/C2 at L=255."""
    a = np.asarray(a.convert("L"), dtype=float)
    b = np.asarray(b.convert("L"), dtype=float)
    h, w = a.shape
    a = a[:h//8*8, :w//8*8].reshape(h//8, 8, w//8, 8).transpose(0, 2, 1, 3)
    b = b[:h//8*8, :w//8*8].reshape(h//8, 8, w//8, 8).transpose(0, 2, 1, 3)
    ma, mb = a.mean((2, 3)), b.mean((2, 3))
    va, vb = a.var((2, 3)), b.var((2, 3))
    cov = ((a-ma[..., None, None])*(b-mb[..., None, None])).mean((2, 3))
    return float((((2*ma*mb+6.5025)*(2*cov+58.5225))/((ma*ma+mb*mb+6.5025)*(va+vb+58.5225))).mean())


rows = []
for screen, suffix in PLATES.items():
    plate = ROOT / "inputs" / f"ARCHHUB-CLD-DES-DSYS-{suffix}.png"
    rendered = ROOT / "evidence" / f"SCREENS2-{screen}.png"
    a, b = Image.open(plate).convert("RGB"), Image.open(rendered).convert("RGB")
    assert a.size == b.size, (screen, a.size, b.size)
    delta = ImageChops.difference(a, b)
    data = np.asarray(delta, dtype=float)
    row = {"screen": screen, "plate": str(plate.relative_to(ROOT)), "render": str(rendered.relative_to(ROOT)),
           "size": a.size, "ssim_8x8": block_ssim(a, b), "mean_absolute_rgb_error": float(data.mean()),
           "changed_pixels_gt_16": int((data.max(2)>16).sum()),
           "render_sha256": hashlib.sha256(rendered.read_bytes()).hexdigest()}
    rows.append(row)
    side = Image.new("RGB", (a.width*2, a.height+28), "#15151a")
    side.paste(a, (0, 28)); side.paste(b, (a.width, 28))
    draw = ImageDraw.Draw(side)
    draw.text((12, 6), "SUPPLIED PLATE", fill="white")
    draw.text((a.width+12, 6), "PRODUCTION COMPONENTS / STORE FIXTURE", fill="white")
    side.save(ROOT / "evidence" / f"SCREENS2-{screen}-side-by-side.png")
    delta.save(ROOT / "evidence" / f"SCREENS2-{screen}-diff.png")
    print(f"{screen}: SSIM={row['ssim_8x8']:.6f}; mean RGB error={row['mean_absolute_rgb_error']:.6f}; changed pixels >16={row['changed_pixels_gt_16']}")
(ROOT / "evidence" / "SCREENS2-perceptual-diff.json").write_text(json.dumps({"method": "unmasked RGB MAE and mean 8x8 luminance SSIM, L=255, K1=.01, K2=.03", "comparisons": rows}, indent=2)+"\n", encoding="utf-8")
