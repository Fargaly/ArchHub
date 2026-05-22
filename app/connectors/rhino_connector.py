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
        "    'file': rs.DocumentPath() + (rs.DocumentName() or ''),\n"
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
        "        'color': [_c[0], _c[1], _c[2]] if _c else None,\n"
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
        ]


# ── self-register ────────────────────────────────────────────────────
register(RhinoConnector())
