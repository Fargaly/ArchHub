"""Blender connector — Blender driven through the ArchHub addon's HTTP
listener, wrapped in the uniform connector contract (`connectors.base`).

Blender integration = a Python addon loaded inside Blender that serves
HTTP on 127.0.0.1:9876. `connectors.blender_runner` already knows how to
locate Blender, install the addon, launch Blender, and speak that HTTP
(`ping`, `info`, `execute`, `render`). This connector does NOT re-do any
of that — it adapts the runner's HTTP calls into the op contract.

The READ ops (`scene_info`, `list_objects`, …) all run through the
runner's `execute()` escape hatch: a tiny `bpy` snippet that builds a
JSON-safe payload and assigns it to a conventional variable the addon
returns. No new HTTP routes are needed, and `blender_runner`'s public
API is left untouched.

Mechanism = "python_api": the work happens inside Blender's embedded
Python interpreter.

`probe()` is three-state and honest:
  * `live`        — the addon answers `/ping`
  * `loaded_dead` — Blender's process is running but nothing is on :9876
  * `missing`     — Blender is not running (or not installed)
"""
from __future__ import annotations

import json
from typing import Any, Optional

try:  # package-relative first (app/ on sys.path)
    from connectors.base import (
        Connector, ConnectorOp, ParamSpec, OpResult, register,
    )
    from connectors import blender_runner as _runner
except Exception:  # pragma: no cover - fallback when imported flat
    from base import (  # type: ignore
        Connector, ConnectorOp, ParamSpec, OpResult, register,
    )
    import blender_runner as _runner  # type: ignore


_BRAND = "#E87D0D"  # Blender orange — see HOST_NODE_UI_GRAMMAR §2.1


def _blender_process_running() -> bool:
    """True if a Blender process is alive on this machine — used to tell
    `loaded_dead` (Blender up, addon silent) from `missing` (Blender
    closed). Best-effort: psutil if present, else a tasklist/pgrep poke.
    Never raises.
    """
    try:
        import psutil  # type: ignore
        for p in psutil.process_iter(["name"]):
            name = (p.info.get("name") or "").lower()
            if "blender" in name:
                return True
        return False
    except Exception:
        pass
    # No psutil — fall back to the OS process list.
    import subprocess
    import sys as _sys
    try:
        if _sys.platform.startswith("win"):
            out = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq blender.exe", "/NH"],
                capture_output=True, text=True, timeout=5)
            return "blender.exe" in (out.stdout or "").lower()
        out = subprocess.run(["pgrep", "-i", "blender"],
                             capture_output=True, text=True, timeout=5)
        return bool((out.stdout or "").strip())
    except Exception:
        return False


def _run_snippet(code: str, result_var: str = "archhub_result",
                 *, timeout: float = 60.0) -> OpResult:
    """Execute a `bpy` snippet inside Blender via the runner's HTTP
    `/execute` route and pull a JSON payload back out of it.

    The addon's `/execute` captures stdout and returns an envelope; the
    most portable way to get structured data back is to have the snippet
    `print()` a single JSON line tagged with a sentinel, then parse it
    out of the captured stdout. This avoids depending on any specific
    addon return-shape.
    """
    sentinel = "__ARCHHUB_JSON__"
    wrapped = (
        f"{code}\n"
        "import json as _json\n"
        f"print('{sentinel}' + _json.dumps({result_var}))\n"
    )
    try:
        env = _runner.execute(wrapped, timeout=timeout)
    except Exception as ex:
        return OpResult.fail(f"Blender addon unreachable: {ex}")
    if not isinstance(env, dict):
        return OpResult.fail("Blender addon returned an unexpected shape")
    # Common error shapes from the addon / runner.
    if env.get("ok") is False or env.get("status") == "error":
        return OpResult.fail(
            env.get("error") or env.get("message")
            or "Blender script error")
    # The addon may surface stdout under several keys depending on
    # version — check them all.
    blob = ""
    for key in ("stdout", "output", "result", "raw", "log"):
        v = env.get(key)
        if isinstance(v, str) and sentinel in v:
            blob = v
            break
        if isinstance(v, dict):
            inner = v.get("stdout") or v.get("output")
            if isinstance(inner, str) and sentinel in inner:
                blob = inner
                break
    if sentinel not in blob:
        # No sentinel — the snippet may have failed before printing.
        err = env.get("error") or env.get("traceback")
        if err:
            return OpResult.fail(str(err))
        return OpResult.fail(
            "Blender did not return a result (addon too old?)")
    payload_str = blob.split(sentinel, 1)[1].splitlines()[0]
    try:
        value = json.loads(payload_str)
    except Exception as ex:
        return OpResult.fail(f"Could not parse Blender result: {ex}")
    return OpResult(ok=True, value=value)


def _count_preview(value: Any, noun: str) -> str:
    n = len(value) if isinstance(value, (list, dict)) else 0
    return f"{n} {noun}{'s' if n != 1 else ''}"


# ── op implementations ───────────────────────────────────────────────

def _scene_info() -> OpResult:
    code = (
        "import bpy\n"
        "scn = bpy.context.scene\n"
        "archhub_result = {\n"
        "    'scene': scn.name,\n"
        "    'blend_file': bpy.data.filepath or '(unsaved)',\n"
        "    'engine': scn.render.engine,\n"
        "    'frame_current': scn.frame_current,\n"
        "    'frame_start': scn.frame_start,\n"
        "    'frame_end': scn.frame_end,\n"
        "    'object_count': len(bpy.data.objects),\n"
        "    'collection_count': len(bpy.data.collections),\n"
        "    'material_count': len(bpy.data.materials),\n"
        "    'unit_system': scn.unit_settings.system,\n"
        "}\n"
    )
    res = _run_snippet(code)
    if res.ok and isinstance(res.value, dict):
        res.value_preview = (f"{res.value.get('scene', '?')} · "
                             f"{res.value.get('object_count', 0)} objs")
    return res


def _list_objects(type_filter: str = "") -> OpResult:
    tf = (type_filter or "").strip().upper()
    code = (
        "import bpy\n"
        f"_tf = {tf!r}\n"
        "archhub_result = []\n"
        "for ob in bpy.data.objects:\n"
        "    if _tf and ob.type != _tf:\n"
        "        continue\n"
        "    archhub_result.append({\n"
        "        'name': ob.name,\n"
        "        'type': ob.type,\n"
        "        'visible': bool(ob.visible_get()),\n"
        "        'location': [round(c, 4) for c in ob.location],\n"
        "        'dimensions': [round(c, 4) for c in ob.dimensions],\n"
        "        'collections': [c.name for c in ob.users_collection],\n"
        "        'parent': ob.parent.name if ob.parent else None,\n"
        "    })\n"
    )
    res = _run_snippet(code)
    if res.ok:
        res.value_preview = _count_preview(res.value, "object")
    return res


def _list_collections() -> OpResult:
    code = (
        "import bpy\n"
        "archhub_result = []\n"
        "for col in bpy.data.collections:\n"
        "    archhub_result.append({\n"
        "        'name': col.name,\n"
        "        'object_count': len(col.objects),\n"
        "        'all_object_count': len(col.all_objects),\n"
        "        'child_count': len(col.children),\n"
        "        'hide_viewport': bool(col.hide_viewport),\n"
        "        'hide_render': bool(col.hide_render),\n"
        "    })\n"
    )
    res = _run_snippet(code)
    if res.ok:
        res.value_preview = _count_preview(res.value, "collection")
    return res


def _list_materials() -> OpResult:
    code = (
        "import bpy\n"
        "archhub_result = []\n"
        "for mat in bpy.data.materials:\n"
        "    base = None\n"
        "    try:\n"
        "        if mat.use_nodes:\n"
        "            bsdf = mat.node_tree.nodes.get('Principled BSDF')\n"
        "            if bsdf is not None:\n"
        "                c = bsdf.inputs['Base Color'].default_value\n"
        "                base = [round(c[0], 3), round(c[1], 3),\n"
        "                        round(c[2], 3)]\n"
        "    except Exception:\n"
        "        base = None\n"
        "    archhub_result.append({\n"
        "        'name': mat.name,\n"
        "        'use_nodes': bool(mat.use_nodes),\n"
        "        'users': int(mat.users),\n"
        "        'base_color': base,\n"
        "    })\n"
    )
    res = _run_snippet(code)
    if res.ok:
        res.value_preview = _count_preview(res.value, "material")
    return res


def _get_selection() -> OpResult:
    code = (
        "import bpy\n"
        "sel = bpy.context.selected_objects\n"
        "active = bpy.context.view_layer.objects.active\n"
        "archhub_result = {\n"
        "    'active': active.name if active else None,\n"
        "    'count': len(sel),\n"
        "    'objects': [\n"
        "        {'name': o.name, 'type': o.type} for o in sel\n"
        "    ],\n"
        "}\n"
    )
    res = _run_snippet(code)
    if res.ok and isinstance(res.value, dict):
        res.value_preview = f"{res.value.get('count', 0)} selected"
    return res


def _run_script(code: str = "") -> OpResult:
    """Run an arbitrary `bpy` snippet inside Blender. Destructive escape
    hatch — passes straight through to the runner's `/execute`."""
    snippet = (code or "").strip()
    if not snippet:
        return OpResult.fail("code is required")
    try:
        env = _runner.execute(snippet, timeout=120.0)
    except Exception as ex:
        return OpResult.fail(f"Blender addon unreachable: {ex}")
    if not isinstance(env, dict):
        return OpResult.fail("Blender addon returned an unexpected shape")
    if env.get("ok") is False or env.get("status") == "error":
        return OpResult.fail(env.get("error")
                             or env.get("traceback")
                             or "Blender script error")
    out = ""
    for key in ("stdout", "output", "result", "log"):
        v = env.get(key)
        if isinstance(v, str):
            out = v
            break
    return OpResult(ok=True, value=env,
                    value_preview=("ran · " + out.strip()[:60]) if out
                    else "script ran")


def _set_object_visibility(object_name: str = "",
                           visible: bool = True) -> OpResult:
    name = (object_name or "").strip()
    if not name:
        return OpResult.fail("object_name is required")
    want = bool(visible)
    code = (
        "import bpy\n"
        f"_name = {name!r}\n"
        f"_want = {want!r}\n"
        "ob = bpy.data.objects.get(_name)\n"
        "if ob is None:\n"
        "    archhub_result = {'ok': False,\n"
        "                      'error': 'object not found: ' + _name}\n"
        "else:\n"
        "    ob.hide_set(not _want)\n"
        "    ob.hide_viewport = (not _want)\n"
        "    ob.hide_render = (not _want)\n"
        "    archhub_result = {'ok': True, 'name': _name,\n"
        "                      'visible': _want}\n"
    )
    res = _run_snippet(code)
    if not res.ok:
        return res
    val = res.value if isinstance(res.value, dict) else {}
    if not val.get("ok", False):
        return OpResult.fail(val.get("error", "set visibility failed"))
    res.value_preview = (f"{name} → "
                         f"{'visible' if want else 'hidden'}")
    return res


def _render(output_path: str = "", engine: str = "BLENDER_EEVEE",
            samples: Optional[int] = None) -> OpResult:
    """Render the current frame to a file via the runner's `/render`."""
    out = (output_path or "").strip()
    if not out:
        return OpResult.fail("output_path is required")
    kwargs: dict = {"engine": engine or "BLENDER_EEVEE"}
    if samples is not None:
        try:
            kwargs["samples"] = int(samples)
        except (TypeError, ValueError):
            pass
    try:
        env = _runner.render(out, **kwargs)
    except Exception as ex:
        return OpResult.fail(f"Blender render failed: {ex}")
    if not isinstance(env, dict):
        return OpResult.fail("Blender render returned an unexpected shape")
    if env.get("ok") is False or env.get("status") == "error":
        return OpResult.fail(env.get("error") or "render error")
    saved = env.get("output_path") or env.get("path") or out
    return OpResult(ok=True, value=env,
                    value_preview=f"rendered → {str(saved)[-48:]}")


# ── AgDR-0041 Property 1 — typed-host primitives (host swap) ─────────
# Resolved from workflows/nodes/host_typed.py so "Export viewport" /
# "Import mesh" do REAL Blender work — same wire, swap the host param.
# Both route through the existing blender_runner surface; addon offline
# → honest OpResult.fail, never a fabricated value.

def _export_viewport(view: str = "", width: int = 2048,
                     height: int = 1536, output_path: str = "",
                     engine: str = "BLENDER_EEVEE") -> OpResult:
    """`blender.export_viewport` — render the current scene/camera to a
    PNG via the runner's /render route. Returns {image, depth, view,
    path}. `view` is accepted for typed-node symmetry (Blender renders
    the active camera); `depth` is None (no separate depth pass here)."""
    op_id = "blender.export_viewport"
    out = (output_path or "").strip()
    if not out:
        # Default to a temp PNG so the typed node is usable with no config.
        import tempfile
        import os
        out = os.path.join(tempfile.gettempdir(), "archhub_blender_view.png")
    try:
        env = _runner.render(out, engine=engine or "BLENDER_EEVEE")
    except Exception as ex:
        return OpResult.fail(f"Blender render failed: {ex}", op_id)
    if not isinstance(env, dict):
        return OpResult.fail("Blender render returned an unexpected shape",
                             op_id)
    if env.get("ok") is False or env.get("status") == "error":
        return OpResult.fail(env.get("error") or "render error", op_id)
    saved = env.get("output_path") or env.get("path") or out
    value = {"image": saved, "depth": None, "view": str(view or ""),
             "path": saved}
    return OpResult(ok=True, value=value, op_id=op_id,
                    value_preview=f"rendered → {str(saved)[-40:]}")


def _import_mesh(mesh: Any = None, name: str = "",
                 layer: str = "") -> OpResult:
    """`blender.import_mesh` — import a .glb/.gltf/.obj/.ply/.stl/.fbx
    mesh file into the scene via the matching bpy importer. DESTRUCTIVE.
    Accepts a path string or an upstream geometry dict carrying a path."""
    op_id = "blender.import_mesh"
    path = ""
    if isinstance(mesh, str):
        path = mesh.strip()
    elif isinstance(mesh, dict):
        for k in ("path", "file", "filepath", "url", "value"):
            v = mesh.get(k)
            if isinstance(v, str) and v.strip():
                path = v.strip()
                break
    if not path:
        return OpResult.fail(
            "import_mesh needs a mesh file path (.glb/.obj/.ply/.stl/.fbx) "
            "on the `mesh` input — got "
            f"{type(mesh).__name__} with no resolvable path.", op_id)
    code = (
        "import bpy, os\n"
        f"_path = {path!r}\n"
        "_ext = os.path.splitext(_path)[1].lower()\n"
        "if not os.path.exists(_path):\n"
        "    archhub_result = {'ok': False,\n"
        "                      'error': 'mesh file not found: ' + _path}\n"
        "else:\n"
        "    _before = set(o.name for o in bpy.data.objects)\n"
        "    _ok = True; _err = ''\n"
        "    try:\n"
        "        if _ext in ('.glb', '.gltf'):\n"
        "            bpy.ops.import_scene.gltf(filepath=_path)\n"
        "        elif _ext == '.obj':\n"
        "            try: bpy.ops.wm.obj_import(filepath=_path)\n"
        "            except Exception:"
        " bpy.ops.import_scene.obj(filepath=_path)\n"
        "        elif _ext == '.ply':\n"
        "            try: bpy.ops.wm.ply_import(filepath=_path)\n"
        "            except Exception:"
        " bpy.ops.import_mesh.ply(filepath=_path)\n"
        "        elif _ext == '.stl':\n"
        "            try: bpy.ops.wm.stl_import(filepath=_path)\n"
        "            except Exception:"
        " bpy.ops.import_mesh.stl(filepath=_path)\n"
        "        elif _ext == '.fbx':\n"
        "            bpy.ops.import_scene.fbx(filepath=_path)\n"
        "        else:\n"
        "            _ok = False; _err = 'unsupported format: ' + _ext\n"
        "    except Exception as _e:\n"
        "        _ok = False; _err = str(_e)\n"
        "    _new = [o.name for o in bpy.data.objects"
        " if o.name not in _before]\n"
        "    archhub_result = {'ok': _ok, 'error': _err,\n"
        "                      'imported': len(_new), 'objects': _new,\n"
        "                      'path': _path}\n"
    )
    res = _run_snippet(code)
    if not res.ok:
        return OpResult.fail(res.error or "import failed", op_id)
    val = res.value if isinstance(res.value, dict) else {}
    if not val.get("ok", False):
        return OpResult.fail(val.get("error", "import failed"), op_id)
    res.op_id = op_id
    res.value_preview = f"{val.get('imported', 0)} object(s) imported"
    return res


# ── connector ────────────────────────────────────────────────────────
class BlenderConnector(Connector):
    """Blender, driven through the ArchHub HTTP addon via `blender_runner`."""

    host = "blender"
    display_name = "Blender"
    mechanism = "python_api"

    def probe(self) -> dict:
        """Three-state, honest. We only ping the addon (cheap, ~2 s
        timeout); we never launch Blender from here.
        """
        try:
            pong = _runner.ping(timeout=2.0)
        except Exception as ex:
            pong = None  # treat any ping fault as 'no addon'
            _ = ex
        if pong is not None:
            note = "Blender addon live on :%d" % _runner.CONNECTOR_PORT_DEFAULT
            detail: dict = {"port": _runner.CONNECTOR_PORT_DEFAULT}
            if isinstance(pong, dict):
                detail["ping"] = pong
            return {"status": "live", "note": note, "detail": detail}
        # Addon silent — is Blender even running?
        if _blender_process_running():
            return {
                "status": "loaded_dead",
                "note": "Blender is running but the ArchHub addon is not "
                        "answering on :%d — enable the addon."
                        % _runner.CONNECTOR_PORT_DEFAULT,
                "detail": {"port": _runner.CONNECTOR_PORT_DEFAULT},
            }
        return {
            "status": "missing",
            "note": "Blender is not running.",
            "detail": {},
        }

    def build_ops(self) -> list:
        return [
            # ── READ ────────────────────────────────────────────────
            ConnectorOp(
                op_id="blender.scene_info", host="blender", kind="read",
                label="Scene info",
                description="Active scene summary — engine, frame range, "
                            "counts, units.",
                inputs=[],
                output_type="any",
                fn=_scene_info,
            ),
            ConnectorOp(
                op_id="blender.list_objects", host="blender",
                kind="read", label="List objects",
                description="All scene objects with type, transform and "
                            "collection membership.",
                inputs=[
                    ParamSpec("type_filter", "Type filter", "choice",
                              default="",
                              options=["", "MESH", "CURVE", "CAMERA",
                                       "LIGHT", "EMPTY", "ARMATURE",
                                       "SURFACE", "FONT", "META"],
                              help="Restrict to one Blender object type."),
                ],
                output_type="list",
                fn=_list_objects,
            ),
            ConnectorOp(
                op_id="blender.list_collections", host="blender",
                kind="read", label="List collections",
                description="Scene collections with object and child "
                            "counts.",
                inputs=[],
                output_type="list",
                fn=_list_collections,
            ),
            ConnectorOp(
                op_id="blender.list_materials", host="blender",
                kind="read", label="List materials",
                description="All materials with node usage and base "
                            "colour.",
                inputs=[],
                output_type="list",
                fn=_list_materials,
            ),
            ConnectorOp(
                op_id="blender.get_selection", host="blender",
                kind="read", label="Get selection",
                description="Currently selected objects and the active "
                            "object.",
                inputs=[],
                output_type="any",
                fn=_get_selection,
            ),
            # ── ACTION ──────────────────────────────────────────────
            ConnectorOp(
                op_id="blender.run_script", host="blender",
                kind="action", label="Run script",
                description="Execute an arbitrary bpy Python snippet "
                            "inside Blender.",
                inputs=[
                    ParamSpec("code", "Python code", "text",
                              required=True,
                              help="bpy snippet to execute in Blender."),
                ],
                output_type="any",
                destructive=True,
                fn=_run_script,
            ),
            ConnectorOp(
                op_id="blender.set_object_visibility", host="blender",
                kind="action", label="Set object visibility",
                description="Show or hide an object in viewport and "
                            "render.",
                inputs=[
                    ParamSpec("object_name", "Object name", "text",
                              required=True,
                              help="Name of the object to toggle."),
                    ParamSpec("visible", "Visible", "bool", default=True,
                              help="True = show, False = hide."),
                ],
                output_type="any",
                destructive=True,
                fn=_set_object_visibility,
            ),
            ConnectorOp(
                op_id="blender.render", host="blender",
                kind="action", label="Render",
                description="Render the current frame to an image file.",
                inputs=[
                    ParamSpec("output_path", "Output path", "file",
                              required=True,
                              help="Where to write the rendered image."),
                    ParamSpec("engine", "Render engine", "choice",
                              default="BLENDER_EEVEE",
                              options=["BLENDER_EEVEE", "BLENDER_EEVEE_NEXT",
                                       "CYCLES", "BLENDER_WORKBENCH"],
                              help="Render engine to use."),
                    ParamSpec("samples", "Samples", "number",
                              default=None,
                              help="Sample count (optional)."),
                ],
                output_type="any",
                destructive=True,
                fn=_render,
            ),
            # ── AgDR-0041 P1 — typed-host primitives ────────────────
            ConnectorOp(
                op_id="blender.export_viewport", host="blender",
                kind="read", label="Export viewport",
                description="Render the current scene/camera to a PNG via "
                            "the addon /render route.",
                inputs=[
                    ParamSpec("view", "View", "text", default="",
                              help="Accepted for symmetry; Blender renders "
                                   "the active camera."),
                    ParamSpec("width", "Width px", "number", default=2048,
                              help="Output image width in pixels."),
                    ParamSpec("height", "Height px", "number", default=1536,
                              help="Output image height in pixels."),
                    ParamSpec("output_path", "Output path", "file",
                              default="",
                              help="Where to write the PNG. Empty = a temp "
                                   "file."),
                    ParamSpec("engine", "Render engine", "choice",
                              default="BLENDER_EEVEE",
                              options=["BLENDER_EEVEE", "BLENDER_EEVEE_NEXT",
                                       "CYCLES", "BLENDER_WORKBENCH"],
                              help="Render engine to use."),
                ],
                output_type="any",
                fn=_export_viewport,
            ),
            ConnectorOp(
                op_id="blender.import_mesh", host="blender",
                kind="action", label="Import mesh",
                description="Import a .glb/.gltf/.obj/.ply/.stl/.fbx mesh "
                            "file into the scene via the matching bpy "
                            "importer.",
                inputs=[
                    ParamSpec("mesh", "Mesh", "any", required=True,
                              help="Mesh file path or an upstream geometry "
                                   "dict carrying a path/file/url."),
                    ParamSpec("name", "Name", "text", default="",
                              help="Name hint for the imported object(s)."),
                    ParamSpec("layer", "Collection", "text", default="",
                              help="Target collection hint (optional)."),
                ],
                output_type="any",
                destructive=True,
                fn=_import_mesh,
            ),
        ]


# ── self-register ────────────────────────────────────────────────────
register(BlenderConnector())
