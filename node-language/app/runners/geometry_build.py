"""Geometry Build runner.

Generates Blender Python code for the current session parameters via LLM,
then executes it via the Blender HTTP addon.

Caches the generated code in StepOutput so re-render can reuse geometry
without regenerating code every time.
"""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Optional

from session import ChainStep, Session, StepOutput


GEOMETRY_SYSTEM_PROMPT = """\
You are ArchHub's Blender code generator. Generate a single, complete, runnable
Blender Python script that creates geometry matching the given parameters.

Rules:
- Always start with: import bpy
- Clear the scene first: bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete()
- Use only bpy built-ins. No external dependencies.
- Create a camera at a good default position (roughly 15m from origin, 5m high).
- Create a Sun light at 45° elevation.
- Set world background to light grey: bpy.context.scene.world.node_tree.nodes["Background"].inputs[0].default_value = (0.8, 0.8, 0.8, 1)
- At the end, set result = {"status": "ok", "objects": len(bpy.context.scene.objects)}
- Output ONLY the Python code — no markdown fences, no comments outside the code.
"""


def run(step: ChainStep, session: Session, router, manager,
        on_progress=None) -> StepOutput:
    """Generate and execute Blender geometry for the current parameters."""
    def progress(msg: str) -> None:
        if on_progress: on_progress(msg)

    # Check if Blender is reachable
    try:
        from connectors import blender_runner
        status = blender_runner.ping()
        if status is None:
            return StepOutput(
                kind="text",
                value="Blender is not running. Toggle Blender on in Connectors.",
                metadata={"error": "blender_not_reachable"}
            )
    except Exception as ex:
        return StepOutput(kind="text", value=f"Blender connection failed: {ex}",
                          metadata={"error": str(ex)})

    # Build parameter context
    params_text = _format_params(session)
    
    # Check if we already have generated code in config (re-run, same params)
    cached_code = step.config.get("blender_code")
    if cached_code and step.config.get("code_hash") == _hash_params(session):
        progress("Using cached geometry code…")
        code = cached_code
    else:
        progress("Generating Blender geometry code…")
        history = [{"role": "user", "content": f"Parameters:\n{params_text}"}]
        
        code = ""
        def on_chunk(t: str) -> None:
            nonlocal code
            code += t

        try:
            resp = router.complete(
                history,
                model="anthropic:claude-sonnet-4-6",
                on_chunk=on_chunk,
            )
            code = resp.text if resp.text else code
        except Exception as ex:
            return StepOutput(kind="text", value=f"Code generation failed: {ex}",
                              metadata={"error": str(ex)})

        code = _clean_code(code)
        # Cache in step config
        step.config["blender_code"] = code
        step.config["code_hash"] = _hash_params(session)

    progress("Executing in Blender…")
    try:
        result = blender_runner.execute(code)
    except Exception as ex:
        return StepOutput(kind="text", value=f"Blender execution failed: {ex}",
                          metadata={"error": str(ex)})

    if isinstance(result, dict) and result.get("status") == "error":
        err = result.get("error", "unknown error")
        return StepOutput(kind="text", value=f"Blender error: {err}",
                          metadata={"error": err, "code": code})

    return StepOutput(
        kind="geometry",
        value="blender://active_scene",
        metadata={"result": result, "code": code, "params": _format_params(session)}
    )


def _format_params(session: Session) -> str:
    lines = []
    for p in session.parameters.values():
        unit = f" {p.unit}" if p.unit else ""
        lines.append(f"{p.name} = {p.value}{unit}  # {p.label}")
    return "\n".join(lines) if lines else "(no parameters yet)"


def _hash_params(session: Session) -> str:
    import hashlib, json as _json
    vals = {n: p.value for n, p in session.parameters.items()}
    return hashlib.sha256(_json.dumps(vals, sort_keys=True).encode()).hexdigest()[:16]


def _clean_code(code: str) -> str:
    code = code.strip()
    code = re.sub(r"^```(?:python)?\s*", "", code, flags=re.MULTILINE)
    code = re.sub(r"```\s*$", "", code.rstrip())
    return code.strip()
