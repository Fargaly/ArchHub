"""Image post-process runner.

Applies adjustments to the render output: brightness, contrast, color
temperature, saturation. Uses Pillow (PIL).

Session parameters consumed:
  pp_brightness    (NUMBER, -1.0 to 1.0, default 0)
  pp_contrast      (NUMBER, -1.0 to 1.0, default 0)
  pp_saturation    (NUMBER, -1.0 to 1.0, default 0)
  pp_warmth        (NUMBER, -1.0 to 1.0, default 0)  — color temperature

If none of these are in the session, returns the render path unchanged
(no-op to keep things fast).
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Optional

from session import ChainStep, Session, StepOutput

RENDERS_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ArchHub" / "renders"


def run(step: ChainStep, session: Session, router, manager,
        on_progress=None) -> StepOutput:
    """Post-process the render from the previous RENDER step."""
    def progress(msg: str) -> None:
        if on_progress: on_progress(msg)

    # Find the source image from the most recent RENDER step output in the chain
    src_path = _find_render_output(session)
    if src_path is None:
        return StepOutput(kind="text", value="No render output found to post-process.",
                          metadata={"error": "no_render"})

    # Read pp parameters
    brightness = float(session.get("pp_brightness", 0.0))
    contrast   = float(session.get("pp_contrast",   0.0))
    saturation = float(session.get("pp_saturation", 0.0))
    warmth     = float(session.get("pp_warmth",     0.0))

    # Skip if all defaults
    if brightness == 0 and contrast == 0 and saturation == 0 and warmth == 0:
        return StepOutput(kind="image", value=src_path, preview=src_path,
                          metadata={"passthrough": True})

    progress("Post-processing render…")

    try:
        from PIL import Image, ImageEnhance, ImageFilter
        img = Image.open(src_path).convert("RGB")

        # Brightness
        if brightness != 0:
            factor = 1.0 + brightness        # -1→0, 0→1, +1→2
            img = ImageEnhance.Brightness(img).enhance(max(0.0, factor))

        # Contrast
        if contrast != 0:
            factor = 1.0 + contrast
            img = ImageEnhance.Contrast(img).enhance(max(0.0, factor))

        # Saturation
        if saturation != 0:
            factor = 1.0 + saturation
            img = ImageEnhance.Color(img).enhance(max(0.0, factor))

        # Warmth (color temperature approximation)
        if warmth != 0:
            img = _apply_warmth(img, warmth)

        out_path = RENDERS_DIR / f"pp_{uuid.uuid4().hex[:8]}.png"
        img.save(str(out_path))
        progress("Post-processing complete.")
        return StepOutput(kind="image", value=str(out_path), preview=str(out_path),
                          metadata={"source": src_path})

    except ImportError:
        # Pillow not installed — return original
        return StepOutput(kind="image", value=src_path, preview=src_path,
                          metadata={"pillow_missing": True})
    except Exception as ex:
        return StepOutput(kind="text", value=f"Post-processing failed: {ex}",
                          metadata={"error": str(ex), "source": src_path})


def _apply_warmth(img, warmth: float):
    """Shift color temperature by mixing R+G-B channels."""
    from PIL import Image
    import struct

    r, g, b = img.split()

    def adjust_channel(channel, delta: int):
        lut = [max(0, min(255, i + delta)) for i in range(256)]
        return channel.point(lut)

    delta = int(warmth * 30)   # max ±30 per channel
    r = adjust_channel(r, +delta)
    g = adjust_channel(g, int(delta * 0.3))
    b = adjust_channel(b, -delta)
    return Image.merge("RGB", (r, g, b))


def _find_render_output(session: Session) -> Optional[str]:
    """Walk the chain backwards to find the most recent RENDER step with output."""
    from session import StepKind
    for step in reversed(session.chain):
        if step.kind == StepKind.RENDER and step.output is not None:
            return step.output.value
    return None
