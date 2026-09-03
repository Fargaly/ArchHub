"""Render runner.

Calls the Blender addon's /render endpoint. Saves the output image to a
temp file under %LOCALAPPDATA%/ArchHub/renders/.

The render step reads render-related parameters from the session:
  sun_elevation   (ANGLE, default 45°)
  camera_height   (LENGTH, default 5m)
  render_samples  (INTEGER, default 64)
  render_engine   (ENUM, default "BLENDER_EEVEE")
  render_width    (INTEGER, default 1280)
  render_height   (INTEGER, default 720)
"""
from __future__ import annotations

import os
import time
import uuid
from pathlib import Path
from typing import Optional

from session import ChainStep, Session, StepOutput

RENDERS_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ArchHub" / "renders"
RENDERS_DIR.mkdir(parents=True, exist_ok=True)


def run(step: ChainStep, session: Session, router, manager,
        on_progress=None) -> StepOutput:
    """Render the current Blender scene and return the image path."""
    def progress(msg: str) -> None:
        if on_progress: on_progress(msg)

    try:
        from connectors import blender_runner
        status = blender_runner.ping()
        if status is None:
            return StepOutput(kind="text",
                              value="Blender is not running.",
                              metadata={"error": "blender_not_reachable"})
    except Exception as ex:
        return StepOutput(kind="text", value=f"Blender connection failed: {ex}")

    # Read render parameters from session (with sensible defaults)
    engine   = session.get("render_engine",  "BLENDER_EEVEE")
    samples  = int(session.get("render_samples", 64))
    width    = int(session.get("render_width",  1280))
    height   = int(session.get("render_height",  720))
    sun_elev = float(session.get("sun_elevation", 45.0))
    cam_h    = float(session.get("camera_height",  5.0))

    # Apply camera + lighting via execute before rendering
    setup_code = _build_setup_code(sun_elev, cam_h)
    try:
        from connectors import blender_runner as br
        br.execute(setup_code, timeout=30)
    except Exception:
        pass   # non-fatal — use whatever Blender has

    output_path = RENDERS_DIR / f"render_{uuid.uuid4().hex[:8]}.png"
    progress(f"Rendering ({engine}, {samples} samples)…")

    try:
        from connectors import blender_runner as br
        result = br.render(
            output_path,
            engine=engine,
            samples=samples,
            resolution=(width, height),
            timeout=600,
        )
    except Exception as ex:
        return StepOutput(kind="text", value=f"Render failed: {ex}",
                          metadata={"error": str(ex)})

    if isinstance(result, dict) and result.get("status") == "error":
        err = result.get("error", "unknown")
        return StepOutput(kind="text", value=f"Render error: {err}",
                          metadata={"error": err})

    # Blender may save to <path>.png or just <path>
    actual = output_path if output_path.exists() else Path(str(output_path) + ".png")
    if not actual.exists():
        # Some versions strip the extension — search
        matches = list(RENDERS_DIR.glob(f"render_{output_path.stem[-8:]}*"))
        actual = matches[0] if matches else output_path

    progress("Render complete.")
    return StepOutput(
        kind="image",
        value=str(actual),
        preview=str(actual),
        metadata={"engine": engine, "samples": samples,
                  "width": width, "height": height,
                  "result": result}
    )


def _build_setup_code(sun_elevation: float, camera_height: float) -> str:
    """Return Blender Python to set sun elevation + camera height."""
    import math
    sun_rad = math.radians(sun_elevation)
    # Rotate camera to camera_height above origin
    return f"""
import bpy, math

# Set sun elevation
for obj in bpy.data.objects:
    if obj.type == 'LIGHT' and obj.data.type == 'SUN':
        obj.rotation_euler = (math.radians(90 - {sun_elevation}), 0, math.radians(45))

# Set camera height
for obj in bpy.data.objects:
    if obj.type == 'CAMERA':
        obj.location.z = {camera_height}
        # Point camera at origin
        import mathutils
        direction = mathutils.Vector((0, 0, 0)) - obj.location
        rot = direction.to_track_quat('-Z', 'Y')
        obj.rotation_euler = rot.to_euler()

result = {{"ok": True}}
"""
