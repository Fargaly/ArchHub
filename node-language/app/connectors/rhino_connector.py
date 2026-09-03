"""Rhino connector — Rhino 7/8 driven through the ArchHub MCP bridge
addon, wrapped in the uniform connector contract (`connectors.base`).

Rhino integration = `archhub_mcp.py` running inside Rhino's embedded
Python, serving HTTP on 127.0.0.1:9879. `connectors.rhino_runner`
already locates Rhino, installs that addon, and speaks the HTTP
(`ping`, `info`, `execute_python`, `screenshot`). This connector adapts
those calls into the op contract; it does NOT re-do discovery or
install, and `rhino_runner`'s public surface is left intact.

Two read paths:
  * LIVE   — when the bridge answers, ops run RhinoPython snippets via
             the runner's `/execute` route (the authoritative path).
  * FILE   — `rhino.document_info` / `rhino.list_layers` accept an
             optional `file` path and, if `rhino3dm` is installed, read
             the .3dm directly without Rhino being open. Degrades
             cleanly to `OpResult.fail` if `rhino3dm` is absent.

Mechanism = "python_api": work happens inside Rhino's embedded Python
(or in `rhino3dm` for the file path).

`probe()` is honest — `live` only when the listener actually answers
`/ping`; `missing` otherwise. We never launch Rhino from `probe()`.
"""
from __future__ import annotations

import json
from typing import Any, Optional

try:  # package-relative first (app/ on sys.path)
    from connectors.base import (
        Connector, ConnectorOp, ParamSpec, OpResult, register,
    )
    from connectors import rhino_runner as _runner
except Exception:  # pragma: no cover - fallback when imported flat
    from base import (  # type: ignore
        Connector, ConnectorOp, ParamSpec, OpResult, register,
    )
    import rhino_runner as _runner  # type: ignore


_BRAND = "#801010"  # Rhino dark-red

# RhinoPython geometry-kind filter → rhinoscriptsyntax object-type bitmask.
# rs.ObjectType / rs.ObjectsByType type codes:
#   point=1, pointcloud=2, curve=4, surface=8, polysurface(brep)=16,
#   mesh=32, ...  block instances are filtered by rs.IsBlockInstance.
_GEO_KIND_MASK = {
    "points": 1,
    "curves": 4,
    "surfaces": 8,
    "breps": 16,
    "meshes": 32,
}
_GEO_KINDS = ["curves", "surfaces", "meshes", "breps", "points", "blocks"]


def _bridge_live() -> bool:
    """Cheap TCP poke at the Rhino bridge port. Never raises."""
    try:
        return bool(_runner.is_reachable(timeout=0.4))
    except Exception:
        return False


def _run_snippet(code: str, result_var: str = "result",
                 *, timeout: int = 60) -> OpResult:
    """Run a RhinoPython snippet through the runner's `/execute` route
    and unwrap its result.

    The runner returns an envelope `{status, result, ...}`. We accept
    `result` directly when present; otherwise we parse a JSON sentinel
    line out of any captured stdout so we don't depend on a specific
    addon return-shape.
    """
    sentinel = "__ARCHHUB_JSON__"
    wrapped = (
        f"{code}\n"
        "import json as _json\n"
        f"print('{sentinel}' + _json.dumps({result_var}))\n"
    )
    try:
        env = _runner.execute_python(wrapped, timeout_seconds=timeout)
    except Exception as ex:
        return OpResult.fail(f"Rhino bridge unreachable: {ex}")
    if not isinstance(env, dict):
        return OpResult.fail("Rhino bridge returned an unexpected shape")
    if env.get("status") == "error":
        return OpResult.fail(env.get("error") or "Rhino script error")
    # Preferred: structured `result` straight from the addon.
    direct = env.get("result")
    if isinstance(direct, (list, dict)):
        return OpResult(ok=True, value=direct)
    # Fallback: sentinel-tagged JSON on stdout.
    blob = ""
    for key in ("stdout", "output", "log", "raw"):
        v = env.get(key)
        if isinstance(v, str) and sentinel in v:
            blob = v
            break
    if sentinel in blob:
        line = blob.split(sentinel, 1)[1].splitlines()[0]
        try:
            return OpResult(ok=True, value=json.loads(line))
        except Exception as ex:
            return OpResult.fail(f"Could not parse Rhino result: {ex}")
    # `result` may itself be a JSON string.
    if isinstance(direct, str):
        try:
            return OpResult(ok=True, value=json.loads(direct))
        except Exception:
            return OpResult(ok=True, value=direct)
    err = env.get("error") or env.get("traceback")
    if err:
        return OpResult.fail(str(err))
    return OpResult.fail("Rhino returned no result (addon too old?)")


def _count_preview(value: Any, noun: str) -> str:
    n = len(value) if isinstance(value, (list, dict)) else 0
    return f"{n} {noun}{'s' if n != 1 else ''}"


# ── file-level read path (rhino3dm, no Rhino needed) ─────────────────

def _file_document_info(path: str) -> OpResult:
    try:
        import rhino3dm  # type: ignore
    except Exception:
        return OpResult.fail(
            "Reading a .3dm file needs rhino3dm — `pip install rhino3dm` "
            "— or open the file in Rhino so the bridge can serve it.")
    try:
        model = rhino3dm.File3dm.Read(path)
    except Exception as ex:
        return OpResult.fail(f"Could not read .3dm: {ex}")
    if model is None:
        return OpResult.fail(f"Not a readable .3dm file: {path}")
    info = {
        "file": path,
        "source": "rhino3dm",
        "object_count": len(model.Objects),
        "layer_count": len(model.Layers),
        "material_count": len(model.Materials),
    }
    try:
        info["application_name"] = model.Settings.ModelUnitSystem.name \
            if hasattr(model.Settings, "ModelUnitSystem") else ""
    except Exception:
        pass
    return OpResult(ok=True, value=info,
                    value_preview=f"{info['object_count']} objs · "
                                  f"{info['layer_count']} layers (file)")


def _file_list_layers(path: str) -> OpResult:
    try:
        import rhino3dm  # type: ignore
    except Exception:
        return OpResult.fail(
            "Reading a .3dm file needs rhino3dm — `pip install rhino3dm` "
            "— or open the file in Rhino so the bridge can serve it.")
    try:
        model = rhino3dm.File3dm.Read(path)
    except Exception as ex:
        return OpResult.fail(f"Could not read .3dm: {ex}")
    if model is None:
        return OpResult.fail(f"Not a readable .3dm file: {path}")
    rows: list[dict] = []
    for layer in model.Layers:
        col = getattr(layer, "Color", None)
        rgb = None
        if col is not None:
            try:
                rgb = [col.R, col.G, col.B]
            except Exception:
                rgb = None
        rows.append({
            "name": layer.Name,
            "full_path": getattr(layer, "FullPath", layer.Name),
            "visible": bool(getattr(layer, "Visible", True)),
            "locked": bool(getattr(layer, "Locked", False)),
            "color": rgb,
        })
    return OpResult(ok=True, value=rows,
                    value_preview=f"{len(rows)} layer"
                                  f"{'s' if len(rows) != 1 else ''} (file)")


# ── op implementations ───────────────────────────────────────────────

def _document_info(file: str = "") -> OpResult:
    """Active Rhino document info, or — if `file` is given — a file-level
    read via rhino3dm."""
    path = (file or "").strip()
    if path:
        return _file_document_info(path)
    code = (
        "import rhinoscriptsyntax as rs\n"
        "import scriptcontext as sc\n"
        "_doc = sc.doc\n"
        "result = {\n"
        "    'file': (rs.DocumentPath() or '') + (rs.DocumentName() or ''),\n"
        "    'name': rs.DocumentName() or '(unsaved)',\n"
        "    'source': 'rhino',\n"
        "    'modified': bool(rs.IsDocumentModified()),\n"
        "    'object_count': len(rs.AllObjects() or []),\n"
        "    'layer_count': len(rs.LayerNames() or []),\n"
        "    'unit_system': rs.UnitSystemName(),\n"
        "    'tolerance': rs.UnitAbsoluteTolerance(),\n"
        "}\n"
    )
    res = _run_snippet(code)
    if res.ok and isinstance(res.value, dict):
        res.value_preview = (f"{res.value.get('name', '?')} · "
                             f"{res.value.get('object_count', 0)} objs")
    return res


def _list_layers(file: str = "") -> OpResult:
    """Layers of the active Rhino document, or of a .3dm file."""
    path = (file or "").strip()
    if path:
        return _file_list_layers(path)
    code = (
        "import rhinoscriptsyntax as rs\n"
        "result = []\n"
        "for _ln in (rs.LayerNames() or []):\n"
        "    _c = rs.LayerColor(_ln)\n"
        "    result.append({\n"
        "        'name': _ln,\n"
        "        'visible': bool(rs.LayerVisible(_ln)),\n"
        "        'locked': bool(rs.LayerLocked(_ln)),\n"
        "        'color': ([int(_c.R), int(_c.G), int(_c.B)] if _c is not None else None),\n"
        "        'object_count': len(rs.ObjectsByLayer(_ln) or []),\n"
        "    })\n"
    )
    res = _run_snippet(code)
    if res.ok:
        res.value_preview = _count_preview(res.value, "layer")
    return res


def _list_objects(geo_kind: str = "curves") -> OpResult:
    """Objects of one geometry kind in the active Rhino document."""
    kind = (geo_kind or "curves").strip().lower()
    if kind not in _GEO_KINDS:
        return OpResult.fail(
            f"geo_kind must be one of {_GEO_KINDS}, got {geo_kind!r}")
    if kind == "blocks":
        code = (
            "import rhinoscriptsyntax as rs\n"
            "result = []\n"
            "for _obj in (rs.AllObjects() or []):\n"
            "    if not rs.IsBlockInstance(_obj):\n"
            "        continue\n"
            "    result.append({\n"
            "        'id': str(_obj),\n"
            "        'kind': 'block',\n"
            "        'block_name': rs.BlockInstanceName(_obj),\n"
            "        'layer': rs.ObjectLayer(_obj),\n"
            "        'name': rs.ObjectName(_obj) or '',\n"
            "    })\n"
        )
    else:
        mask = _GEO_KIND_MASK[kind]
        code = (
            "import rhinoscriptsyntax as rs\n"
            f"_ids = rs.ObjectsByType({mask}) or []\n"
            f"_kind = {kind!r}\n"
            "result = []\n"
            "for _obj in _ids:\n"
            "    _bb = rs.BoundingBox(_obj)\n"
            "    result.append({\n"
            "        'id': str(_obj),\n"
            "        'kind': _kind,\n"
            "        'layer': rs.ObjectLayer(_obj),\n"
            "        'name': rs.ObjectName(_obj) or '',\n"
            "        'has_bbox': bool(_bb),\n"
            "    })\n"
        )
    res = _run_snippet(code)
    if res.ok:
        res.value_preview = _count_preview(res.value, kind.rstrip("s"))
    return res


def _get_selection() -> OpResult:
    code = (
        "import rhinoscriptsyntax as rs\n"
        "_sel = rs.SelectedObjects() or []\n"
        "_objs = []\n"
        "for _obj in _sel:\n"
        "    _objs.append({\n"
        "        'id': str(_obj),\n"
        "        'layer': rs.ObjectLayer(_obj),\n"
        "        'type': rs.ObjectType(_obj),\n"
        "        'name': rs.ObjectName(_obj) or '',\n"
        "    })\n"
        "result = {'count': len(_objs), 'objects': _objs}\n"
    )
    res = _run_snippet(code)
    if res.ok and isinstance(res.value, dict):
        res.value_preview = f"{res.value.get('count', 0)} selected"
    return res


def _run_script(code: str = "") -> OpResult:
    """Run an arbitrary RhinoScript/Python snippet inside Rhino.
    Destructive escape hatch — passes through to the runner."""
    snippet = (code or "").strip()
    if not snippet:
        return OpResult.fail("code is required")
    try:
        env = _runner.execute_python(snippet, timeout_seconds=120)
    except Exception as ex:
        return OpResult.fail(f"Rhino bridge unreachable: {ex}")
    if not isinstance(env, dict):
        return OpResult.fail("Rhino bridge returned an unexpected shape")
    if env.get("status") == "error":
        return OpResult.fail(env.get("error") or "Rhino script error")
    out = ""
    for key in ("stdout", "output", "log"):
        v = env.get(key)
        if isinstance(v, str):
            out = v
            break
    return OpResult(ok=True, value=env,
                    value_preview=("ran · " + out.strip()[:60]) if out
                    else "script ran")


def _set_layer_visibility(layer: str = "", visible: bool = True) -> OpResult:
    name = (layer or "").strip()
    if not name:
        return OpResult.fail("layer is required")
    want = bool(visible)
    code = (
        "import rhinoscriptsyntax as rs\n"
        f"_name = {name!r}\n"
        f"_want = {want!r}\n"
        "if _name not in (rs.LayerNames() or []):\n"
        "    result = {'ok': False, 'error': 'layer not found: ' + _name}\n"
        "else:\n"
        "    rs.LayerVisible(_name, _want)\n"
        "    result = {'ok': True, 'layer': _name, 'visible': _want}\n"
    )
    res = _run_snippet(code)
    if not res.ok:
        return res
    val = res.value if isinstance(res.value, dict) else {}
    if not val.get("ok", False):
        return OpResult.fail(val.get("error", "set layer visibility failed"))
    res.value_preview = (f"{name} → "
                         f"{'visible' if want else 'hidden'}")
    return res


# ── AgDR-0041 Property 1 — typed-host primitives (host swap) ─────────
# Resolved from workflows/nodes/host_typed.py so "Export viewport" /
# "Import mesh" do REAL Rhino work — same wire, swap the host param.
# Both route through the existing rhino_runner HTTP surface; bridge
# offline → honest OpResult.fail, never a fabricated value.

def _export_viewport(view: str = "", width: int = 2048,
                     height: int = 1536, output_path: str = "") -> OpResult:
    """`rhino.export_viewport` — capture the active Rhino viewport to a
    PNG via the runner's /screenshot route. Returns {image, depth, view,
    path}. `depth` is None (no depth pass on the Rhino bridge) — honest,
    not fabricated. `view` switches the active viewport first when given."""
    op_id = "rhino.export_viewport"
    if not _bridge_live():
        return OpResult.fail(
            "Rhino bridge not reachable — open Rhino and load the ArchHub "
            "addon.", op_id)
    want_view = str(view or "").strip()
    if want_view:
        # Best-effort: switch the active viewport to the named one.
        snippet = (
            "import rhinoscriptsyntax as rs\n"
            f"_v = {want_view!r}\n"
            "try:\n"
            "    rs.CurrentView(_v)\n"
            "except Exception:\n"
            "    pass\n"
            "result = rs.CurrentView()\n"
        )
        sw = _run_snippet(snippet)
        if not sw.ok:
            return OpResult.fail(sw.error or "could not switch view", op_id)
    try:
        env = _runner.screenshot(output_path=(output_path or None),
                                 width=int(width or 2048),
                                 height=int(height or 1536))
    except Exception as ex:
        return OpResult.fail(f"Rhino screenshot failed: {ex}", op_id)
    if not isinstance(env, dict) or env.get("status") == "error":
        msg = (env or {}).get("error", "screenshot failed") \
            if isinstance(env, dict) else "screenshot failed"
        return OpResult.fail(msg, op_id)
    saved = env.get("output_path") or env.get("path") or output_path
    value = {"image": saved, "depth": None,
             "view": want_view or env.get("view", ""), "path": saved}
    return OpResult(ok=True, value=value, op_id=op_id,
                    value_preview=f"viewport → {str(saved)[-40:]}")


def _import_mesh(mesh: Any = None, name: str = "",
                 layer: str = "") -> OpResult:
    """`rhino.import_mesh` — import a .glb/.obj/.ply/.3dm mesh file into
    the active Rhino document via `rs.Command("_-Import")`. DESTRUCTIVE.
    Accepts a path string or an upstream geometry dict carrying a path."""
    op_id = "rhino.import_mesh"
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
            "import_mesh needs a mesh file path (.glb/.obj/.ply/.3dm) on "
            "the `mesh` input — got "
            f"{type(mesh).__name__} with no resolvable path.", op_id)
    if not _bridge_live():
        return OpResult.fail(
            "Rhino bridge not reachable — open Rhino and load the ArchHub "
            "addon.", op_id)
    lyr = str(layer or "").strip()
    code = (
        "import rhinoscriptsyntax as rs\n"
        "import os\n"
        f"_path = {path!r}\n"
        f"_layer = {lyr!r}\n"
        "if not os.path.exists(_path):\n"
        "    result = {'ok': False, 'error': 'mesh file not found: ' "
        "+ _path}\n"
        "else:\n"
        "    _before = set(str(o) for o in (rs.AllObjects() or []))\n"
        "    if _layer:\n"
        "        if _layer not in (rs.LayerNames() or []):\n"
        "            rs.AddLayer(_layer)\n"
        "        rs.CurrentLayer(_layer)\n"
        "    _ok = rs.Command('_-Import \"' + _path + '\" _Enter', False)\n"
        "    _after = set(str(o) for o in (rs.AllObjects() or []))\n"
        "    _new = list(_after - _before)\n"
        "    result = {'ok': bool(_ok), 'imported': len(_new),\n"
        "              'path': _path, 'layer': _layer}\n"
    )
    res = _run_snippet(code)
    if not res.ok:
        return OpResult.fail(res.error or "import failed", op_id)
    val = res.value if isinstance(res.value, dict) else {}
    if not val.get("ok", False):
        return OpResult.fail(val.get("error", "import failed"), op_id)
    res.op_id = op_id
    res.value_preview = (f"{val.get('imported', 0)} object(s) imported"
                         + (f" → {val.get('layer')}" if val.get("layer")
                            else ""))
    return res


# ── connector ────────────────────────────────────────────────────────
class RhinoConnector(Connector):
    """Rhino, driven through the ArchHub MCP bridge via `rhino_runner`."""

    host = "rhino"
    display_name = "Rhino"
    mechanism = "python_api"

    def probe(self) -> dict:
        """Honest two-state probe. `is_reachable()` is a sub-second TCP
        connect to :9879; we only call `/ping` if the port is open.
        `live` requires the listener to actually answer.
        """
        port = _runner.CONNECTOR_PORT_DEFAULT
        if not _bridge_live():
            return {
                "status": "missing",
                "note": f"Rhino bridge not reachable on :{port} — open "
                        "Rhino and load the ArchHub addon.",
                "detail": {"port": port},
            }
        # Port is open — confirm the addon actually answers /ping.
        try:
            pong = _runner.ping(timeout=3.0)
        except Exception as ex:
            return {
                "status": "missing",
                "note": f"Rhino bridge port open but ping failed: {ex}",
                "detail": {"port": port},
            }
        if isinstance(pong, dict) and pong.get("status") == "error":
            return {
                "status": "missing",
                "note": pong.get("error",
                                 f"Rhino bridge not answering on :{port}"),
                "detail": {"port": port},
            }
        note = f"Rhino bridge live on :{port}"
        detail: dict = {"port": port}
        if isinstance(pong, dict):
            detail["ping"] = pong
            ver = pong.get("version")
            if ver:
                note = f"Rhino {ver} bridge live on :{port}"
        return {"status": "live", "note": note, "detail": detail}

    def build_ops(self) -> list:
        return [
            # ── READ ────────────────────────────────────────────────
            ConnectorOp(
                op_id="rhino.document_info", host="rhino", kind="read",
                label="Document info",
                description="Active document summary — units, tolerance, "
                            "object and layer counts. Pass a .3dm path "
                            "to read a file directly (needs rhino3dm).",
                inputs=[
                    ParamSpec("file", "File (.3dm)", "file", default="",
                              help="Optional .3dm path for an offline "
                                   "file read."),
                ],
                output_type="any",
                fn=_document_info,
            ),
            ConnectorOp(
                op_id="rhino.list_layers", host="rhino", kind="read",
                label="List layers",
                description="Layers with visibility, lock state, colour "
                            "and object counts. Pass a .3dm path for an "
                            "offline file read.",
                inputs=[
                    ParamSpec("file", "File (.3dm)", "file", default="",
                              help="Optional .3dm path for an offline "
                                   "file read."),
                ],
                output_type="list",
                fn=_list_layers,
            ),
            ConnectorOp(
                op_id="rhino.list_objects", host="rhino", kind="read",
                label="List objects",
                description="Objects of one geometry kind in the active "
                            "document.",
                inputs=[
                    ParamSpec("geo_kind", "Geometry kind", "choice",
                              default="curves", options=list(_GEO_KINDS),
                              required=True,
                              help="Which geometry kind to list."),
                ],
                output_type="list",
                fn=_list_objects,
            ),
            ConnectorOp(
                op_id="rhino.get_selection", host="rhino", kind="read",
                label="Get selection",
                description="Currently selected objects in the active "
                            "document.",
                inputs=[],
                output_type="any",
                fn=_get_selection,
            ),
            # ── ACTION ──────────────────────────────────────────────
            ConnectorOp(
                op_id="rhino.run_script", host="rhino", kind="action",
                label="Run script",
                description="Execute an arbitrary RhinoScript / Python "
                            "snippet inside Rhino.",
                inputs=[
                    ParamSpec("code", "Python code", "text",
                              required=True,
                              help="RhinoPython snippet to execute."),
                ],
                output_type="any",
                destructive=True,
                fn=_run_script,
            ),
            ConnectorOp(
                op_id="rhino.set_layer_visibility", host="rhino",
                kind="action", label="Set layer visibility",
                description="Show or hide a layer in the active "
                            "document.",
                inputs=[
                    ParamSpec("layer", "Layer", "text", required=True,
                              help="Name of the layer to toggle."),
                    ParamSpec("visible", "Visible", "bool", default=True,
                              help="True = show, False = hide."),
                ],
                output_type="any",
                destructive=True,
                fn=_set_layer_visibility,
            ),
            # ── AgDR-0041 P1 — typed-host primitives ────────────────
            ConnectorOp(
                op_id="rhino.export_viewport", host="rhino", kind="read",
                label="Export viewport",
                description="Capture the active Rhino viewport to a PNG "
                            "via the bridge /screenshot route.",
                inputs=[
                    ParamSpec("view", "Viewport name", "text", default="",
                              help="Optional viewport to switch to first. "
                                   "Empty = current viewport."),
                    ParamSpec("width", "Width px", "number", default=2048,
                              help="Output image width in pixels."),
                    ParamSpec("height", "Height px", "number", default=1536,
                              help="Output image height in pixels."),
                    ParamSpec("output_path", "Output path", "text",
                              default="",
                              help="Where to write the PNG. Empty = host "
                                   "default."),
                ],
                output_type="any",
                fn=_export_viewport,
            ),
            ConnectorOp(
                op_id="rhino.import_mesh", host="rhino", kind="action",
                label="Import mesh",
                description="Import a .glb/.obj/.ply/.3dm mesh file into "
                            "the active document via _-Import.",
                inputs=[
                    ParamSpec("mesh", "Mesh", "any", required=True,
                              help="Mesh file path or an upstream geometry "
                                   "dict carrying a path/file/url."),
                    ParamSpec("name", "Name", "text", default="",
                              help="Name hint for the imported object(s)."),
                    ParamSpec("layer", "Layer", "text", default="",
                              help="Target layer (created if missing)."),
                ],
                output_type="any",
                destructive=True,
                fn=_import_mesh,
            ),
        ]


# ── self-register ────────────────────────────────────────────────────
register(RhinoConnector())
