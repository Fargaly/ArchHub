"""Revit connector — drives Autodesk Revit through the multi-session broker.

Part of the broker-backed AEC connector cluster (Revit · AutoCAD · 3ds Max).
Subclasses the uniform `Connector` contract in `connectors/base.py`.

Architecture
------------
The connector runs in ArchHub's own Python process. It does NOT talk to
Revit directly. Instead it routes every call through `revit_broker`:

    ArchHub  ──>  revit_broker.forward(session, path, ...)  ──>  RevitMCP.dll
                  (HTTP localhost:48884..48899)              (in-Revit listener)

`revit_broker.pick_session()` chooses which open Revit instance to hit —
so an architect with two Revit windows open can target one with the
optional `instance` op parameter (matched against session_id / pid /
doc-title — the broker's `prefer=` contract).

The endpoint surface — what the add-in actually exposes
-------------------------------------------------------
Inspecting `payload/sources/revit_mcp/RevitMCPApp.cs` (v0.3.0), the
RevitMCP listener exposes ONLY these routes:

    GET  /ping        → {"status":"ok","service":"revit-mcp","version":...}
    GET  /info        → active document / view / version
    POST /exec        → run a C# script, body {"code": "...",
                        "transaction_name": "..."}
    POST /screenshot  → export the active view to PNG

There is NO granular `/walls`, `/views`, `/rooms` REST endpoint. Every
granular operation in this connector is therefore implemented by POSTing
a small C# script to `/exec`. The script uses the Revit API
(`FilteredElementCollector` etc.), stashes a JSON-serialisable value in
`ctx.result`, and the add-in returns `{"status":"ok","result": <value>}`.
This is the real, documented contract — see `RevitEventHandler.cs`
`RunCSharpScript` + `SerializeResult`.

ASSUMPTION (documented per the build mandate): the `/exec` C# scripting
route is the canonical way to read model data because the shipped DLL
has no resource-style endpoints. If a future RevitMCP DLL adds e.g.
`/views`, the per-op `_RevitOp` definitions below can be repointed at a
direct path with no contract change. Until then `/exec` is correct and
code-complete.

Honesty contract
----------------
This connector NEVER fabricates Revit data. If the broker has no live
session, or the add-in errors, or the call times out, the op returns
`OpResult(ok=False, error=...)` with a clear message. This is a direct
fix for the founder's hallucination bug — a dead broker must surface an
honest error, never invented walls/doors/rooms.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from connectors.base import (
    Connector,
    ConnectorOp,
    OpResult,
    ParamSpec,
    _preview,
    register,
)

try:  # broker import is best-effort — a missing broker must not crash import
    import revit_broker
except Exception:  # pragma: no cover - broker always ships alongside
    revit_broker = None  # type: ignore


# Default transaction name for /exec calls — shows up in Revit's undo stack.
_TX_READ = "ArchHub read"
_TX_WRITE = "ArchHub action"


# ── broker plumbing ─────────────────────────────────────────────────
def _broker_offline_result(op_id: str) -> OpResult:
    """Uniform 'no live Revit' failure. Honest — never fabricated data."""
    if revit_broker is None:
        return OpResult.fail(
            "Revit broker module unavailable in this build.", op_id)
    try:
        running = revit_broker.is_any_alive()
    except Exception:
        running = False
    if running:
        # Session file(s) present but none healthy — add-in dead.
        return OpResult.fail(
            "Revit is open but the ArchHub connector isn't responding. "
            "Re-load the ArchHub connector inside Revit (or restart Revit).",
            op_id)
    return OpResult.fail(
        "Revit is not running. Open Revit and load the ArchHub connector.",
        op_id)


def _exec(op_id: str, code: str, *, instance: Optional[str] = None,
          tx_name: str = _TX_READ, timeout: float = 20.0) -> Any:
    """POST a C# script to one Revit session's /exec route and return the
    unwrapped `result` value.

    Returns either the parsed `result` payload (on success) or an
    `OpResult` (on any failure) — callers check `isinstance(x, OpResult)`.
    Never raises.
    """
    if revit_broker is None:
        return _broker_offline_result(op_id)
    try:
        session = revit_broker.pick_session(prefer=instance)
    except Exception as ex:
        return OpResult.fail(f"Revit broker error: {ex}", op_id)
    if session is None:
        return _broker_offline_result(op_id)

    body = json.dumps({"code": code, "transaction_name": tx_name}).encode("utf-8")
    try:
        resp = revit_broker.forward(
            session, "/exec", body=body, method="POST", timeout=timeout)
    except Exception as ex:
        # Broker.forward is defensive, but belt-and-braces.
        return OpResult.fail(f"Revit broker call failed: {ex}", op_id)

    if not isinstance(resp, dict):
        return OpResult.fail("Revit add-in returned a non-JSON response.", op_id)
    if resp.get("status") == "error":
        # AgDR-0023 — RevitMCP on the subprocess-csc path returns
        # `error_code: "csc_missing"` when no C# compiler is found
        # in the standard probe locations. Surface a TYPED OpResult
        # with a clear remediation pointer so the JSX UI can show
        # the Build Tools install link instead of a raw error.
        ecode = str(resp.get("error_code") or "").lower().strip()
        if ecode == "csc_missing":
            return OpResult.fail(
                "C# compiler (csc.exe) not found. Install .NET "
                "Framework 4 SDK or Visual Studio Build Tools, "
                "then restart Revit. See docs/RUN-REVIT.md.",
                op_id)
        return OpResult.fail(
            f"Revit add-in error: {resp.get('error', 'unknown error')}", op_id)
    # Success shape from RevitEventHandler.RunCSharpScript:
    #   {"status":"ok","result": <serialised ctx.result>}
    return resp.get("result")


def _session_label(instance: Optional[str] = None) -> str:
    """Short 'doc · pid' label for the chosen session, for previews."""
    if revit_broker is None:
        return ""
    try:
        s = revit_broker.pick_session(prefer=instance)
    except Exception:
        return ""
    if s is None:
        return ""
    return s.doc_title or s.session_id or f"pid {s.pid}"


def _as_list(value: Any) -> list:
    """Coerce an /exec result into list[dict]/list. Honest about shape."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        # Some scripts wrap rows under a key — unwrap the obvious ones.
        for key in ("items", "rows", "elements", "values", "data"):
            v = value.get(key)
            if isinstance(v, list):
                return v
        return [value]
    return [value]


# ── instance param (shared) ─────────────────────────────────────────
def _instance_param() -> ParamSpec:
    return ParamSpec(
        id="instance", label="Revit instance", type="text", default="",
        required=False,
        help="Target a specific open Revit window when several are open "
             "(match by document name or pid). Empty = most-recent.",
    )


# ── READ operations ─────────────────────────────────────────────────
# Each READ runs a C# script via /exec. The script collects elements with
# FilteredElementCollector and assigns a list of small dicts to ctx.result.

# C# snippet returns a List<Dictionary<string,object>> — JSON-serialises
# to list[dict]. Element name reads use the 0.3.0 Revit API.
_CS_VIEWS = """
var col = new FilteredElementCollector(Doc).OfClass(typeof(View));
var rows = new List<Dictionary<string,object>>();
foreach (View v in col) {
    if (v.IsTemplate) continue;
    rows.Add(new Dictionary<string,object>{
        {"id", v.Id.IntegerValue},
        {"name", v.Name},
        {"view_type", v.ViewType.ToString()},
        {"is_template", v.IsTemplate}
    });
}
result = rows;
"""

_CS_WALLS = """
var col = new FilteredElementCollector(Doc)
    .OfCategory(BuiltInCategory.OST_Walls).WhereElementIsNotElementType();
var rows = new List<Dictionary<string,object>>();
foreach (var e in col) {
    var w = e as Wall;
    double len = 0;
    try { var lp = e.get_Parameter(BuiltInParameter.CURVE_ELEM_LENGTH);
          if (lp != null) len = lp.AsDouble(); } catch {}
    rows.Add(new Dictionary<string,object>{
        {"id", e.Id.IntegerValue},
        {"name", e.Name},
        {"type", (w!=null && w.WallType!=null) ? w.WallType.Name : ""},
        {"length", len},
        {"level", (e.LevelId!=null && e.LevelId.IntegerValue>0
                   && Doc.GetElement(e.LevelId)!=null)
                   ? Doc.GetElement(e.LevelId).Name : ""}
    });
}
result = rows;
"""

_CS_DOORS = """
var col = new FilteredElementCollector(Doc)
    .OfCategory(BuiltInCategory.OST_Doors).WhereElementIsNotElementType();
var rows = new List<Dictionary<string,object>>();
foreach (var e in col) {
    var fi = e as FamilyInstance;
    rows.Add(new Dictionary<string,object>{
        {"id", e.Id.IntegerValue},
        {"name", e.Name},
        {"family", (fi!=null && fi.Symbol!=null && fi.Symbol.Family!=null)
                   ? fi.Symbol.Family.Name : ""},
        {"level", (e.LevelId!=null && e.LevelId.IntegerValue>0
                   && Doc.GetElement(e.LevelId)!=null)
                   ? Doc.GetElement(e.LevelId).Name : ""}
    });
}
result = rows;
"""

_CS_WINDOWS = """
var col = new FilteredElementCollector(Doc)
    .OfCategory(BuiltInCategory.OST_Windows).WhereElementIsNotElementType();
var rows = new List<Dictionary<string,object>>();
foreach (var e in col) {
    var fi = e as FamilyInstance;
    rows.Add(new Dictionary<string,object>{
        {"id", e.Id.IntegerValue},
        {"name", e.Name},
        {"family", (fi!=null && fi.Symbol!=null && fi.Symbol.Family!=null)
                   ? fi.Symbol.Family.Name : ""},
        {"level", (e.LevelId!=null && e.LevelId.IntegerValue>0
                   && Doc.GetElement(e.LevelId)!=null)
                   ? Doc.GetElement(e.LevelId).Name : ""}
    });
}
result = rows;
"""

_CS_ROOMS = """
var col = new FilteredElementCollector(Doc)
    .OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType();
var rows = new List<Dictionary<string,object>>();
foreach (var e in col) {
    double area = 0;
    try { var ap = e.get_Parameter(BuiltInParameter.ROOM_AREA);
          if (ap != null) area = ap.AsDouble(); } catch {}
    string num = "";
    try { var np = e.get_Parameter(BuiltInParameter.ROOM_NUMBER);
          if (np != null) num = np.AsString() ?? ""; } catch {}
    rows.Add(new Dictionary<string,object>{
        {"id", e.Id.IntegerValue},
        {"name", e.Name},
        {"number", num},
        {"area", area}
    });
}
result = rows;
"""

_CS_LEVELS = """
var col = new FilteredElementCollector(Doc).OfClass(typeof(Level));
var rows = new List<Dictionary<string,object>>();
foreach (Level lv in col) {
    rows.Add(new Dictionary<string,object>{
        {"id", lv.Id.IntegerValue},
        {"name", lv.Name},
        {"elevation", lv.Elevation}
    });
}
result = rows;
"""

_CS_SHEETS = """
var col = new FilteredElementCollector(Doc).OfClass(typeof(ViewSheet));
var rows = new List<Dictionary<string,object>>();
foreach (ViewSheet sh in col) {
    rows.Add(new Dictionary<string,object>{
        {"id", sh.Id.IntegerValue},
        {"number", sh.SheetNumber},
        {"name", sh.Name}
    });
}
result = rows;
"""

_CS_FAMILIES = """
var col = new FilteredElementCollector(Doc).OfClass(typeof(Family));
var rows = new List<Dictionary<string,object>>();
foreach (Family f in col) {
    rows.Add(new Dictionary<string,object>{
        {"id", f.Id.IntegerValue},
        {"name", f.Name},
        {"category", (f.FamilyCategory!=null) ? f.FamilyCategory.Name : ""}
    });
}
result = rows;
"""

_CS_SELECTION = """
var rows = new List<Dictionary<string,object>>();
foreach (var id in UIDoc.Selection.GetElementIds()) {
    var e = Doc.GetElement(id);
    if (e == null) continue;
    rows.Add(new Dictionary<string,object>{
        {"id", id.IntegerValue},
        {"name", e.Name},
        {"category", (e.Category!=null) ? e.Category.Name : ""}
    });
}
result = rows;
"""

_CS_WARNINGS = """
var rows = new List<Dictionary<string,object>>();
foreach (var w in Doc.GetWarnings()) {
    rows.Add(new Dictionary<string,object>{
        {"description", w.GetDescriptionText()},
        {"severity", w.GetSeverity().ToString()},
        {"element_count", w.GetFailingElements().Count}
    });
}
result = rows;
"""


def _read_list(op_id: str, code: str, noun: str,
               instance: Optional[str] = None) -> OpResult:
    """Run a list-producing /exec read and wrap it in an OpResult."""
    res = _exec(op_id, code, instance=instance, tx_name=_TX_READ)
    if isinstance(res, OpResult):
        return res
    rows = _as_list(res)
    label = _session_label(instance)
    preview = f"{len(rows)} {noun}{'s' if len(rows) != 1 else ''}"
    if label:
        preview += f" · {label}"
    return OpResult(ok=True, value=rows, op_id=op_id, value_preview=preview)


def _list_views(instance: str = "") -> OpResult:
    return _read_list("revit.list_views", _CS_VIEWS, "view", instance or None)


def _list_walls(instance: str = "") -> OpResult:
    return _read_list("revit.list_walls", _CS_WALLS, "wall", instance or None)


def _list_doors(instance: str = "") -> OpResult:
    return _read_list("revit.list_doors", _CS_DOORS, "door", instance or None)


def _list_windows(instance: str = "") -> OpResult:
    return _read_list(
        "revit.list_windows", _CS_WINDOWS, "window", instance or None)


def _list_rooms(instance: str = "") -> OpResult:
    return _read_list("revit.list_rooms", _CS_ROOMS, "room", instance or None)


def _list_levels(instance: str = "") -> OpResult:
    return _read_list(
        "revit.list_levels", _CS_LEVELS, "level", instance or None)


def _list_sheets(instance: str = "") -> OpResult:
    return _read_list(
        "revit.list_sheets", _CS_SHEETS, "sheet", instance or None)


def _list_families(instance: str = "") -> OpResult:
    return _read_list(
        "revit.list_families", _CS_FAMILIES, "family", instance or None)


def _get_selection(instance: str = "") -> OpResult:
    return _read_list(
        "revit.get_selection", _CS_SELECTION, "element", instance or None)


def _list_warnings(instance: str = "") -> OpResult:
    return _read_list(
        "revit.list_warnings", _CS_WARNINGS, "warning", instance or None)


# ── ACTION operations ───────────────────────────────────────────────
def _create_dimensions(instance: str = "", view_id: int = 0) -> OpResult:
    """Auto-dimension the walls in a view. DESTRUCTIVE — mutates the model.

    Best-effort: dimensions parallel walls in the target view. `view_id`
    empty = active view.
    """
    op_id = "revit.create_dimensions"
    # Build the C# inline — keep the script minimal and defensive.
    vid = int(view_id or 0)
    view_expr = (f"Doc.GetElement(new ElementId({vid})) as View"
                 if vid > 0 else "Doc.ActiveView")
    code = f"""
var view = {view_expr};
if (view == null) {{ result = new Dictionary<string,object>{{
    {{"created", 0}}, {{"error", "no target view"}} }}; }}
else {{
    int made = 0;
    var walls = new FilteredElementCollector(Doc, view.Id)
        .OfCategory(BuiltInCategory.OST_Walls)
        .WhereElementIsNotElementType().ToList();
    foreach (var e in walls) {{
        var w = e as Wall;
        if (w == null) continue;
        var lc = w.Location as LocationCurve;
        if (lc == null || !(lc.Curve is Line)) continue;
        var line = lc.Curve as Line;
        var refs = new ReferenceArray();
        try {{
            refs.Append(new Reference(w));
        }} catch {{ continue; }}
        if (refs.Size < 1) continue;
        try {{ Doc.Create.NewDimension(view, line, refs); made++; }}
        catch {{ }}
    }}
    result = new Dictionary<string,object>{{
        {{"created", made}}, {{"view", view.Name}} }};
}}
"""
    res = _exec(op_id, code, instance=instance or None, tx_name=_TX_WRITE)
    if isinstance(res, OpResult):
        return res
    data = res if isinstance(res, dict) else {"result": res}
    made = data.get("created", 0)
    return OpResult(
        ok=True, value=data, op_id=op_id,
        value_preview=f"{made} dimension{'s' if made != 1 else ''} created")


def _place_tags(instance: str = "", category: str = "Doors",
                view_id: int = 0) -> OpResult:
    """Tag every element of a category in a view. DESTRUCTIVE.

    `category` — one of Doors / Windows / Walls / Rooms. `view_id` empty
    = active view.
    """
    op_id = "revit.place_tags"
    cat_map = {
        "doors": "OST_Doors", "windows": "OST_Windows",
        "walls": "OST_Walls", "rooms": "OST_Rooms",
    }
    bic = cat_map.get(str(category or "doors").strip().lower())
    if bic is None:
        return OpResult.fail(
            f"Unknown category '{category}'. Use one of: "
            + ", ".join(sorted(cat_map)), op_id)
    vid = int(view_id or 0)
    view_expr = (f"Doc.GetElement(new ElementId({vid})) as View"
                 if vid > 0 else "Doc.ActiveView")
    code = f"""
var view = {view_expr};
if (view == null) {{ result = new Dictionary<string,object>{{
    {{"tagged", 0}}, {{"error", "no target view"}} }}; }}
else {{
    int made = 0;
    var col = new FilteredElementCollector(Doc, view.Id)
        .OfCategory(BuiltInCategory.{bic})
        .WhereElementIsNotElementType().ToList();
    foreach (var e in col) {{
        try {{
            var loc = e.Location as LocationPoint;
            XYZ pt = (loc != null) ? loc.Point : XYZ.Zero;
            IndependentTag.Create(Doc, view.Id, new Reference(e),
                false, TagMode.TM_ADDBY_CATEGORY,
                TagOrientation.Horizontal, pt);
            made++;
        }} catch {{ }}
    }}
    result = new Dictionary<string,object>{{
        {{"tagged", made}}, {{"category", "{bic}"}}, {{"view", view.Name}} }};
}}
"""
    res = _exec(op_id, code, instance=instance or None, tx_name=_TX_WRITE)
    if isinstance(res, OpResult):
        return res
    data = res if isinstance(res, dict) else {"result": res}
    made = data.get("tagged", 0)
    return OpResult(
        ok=True, value=data, op_id=op_id,
        value_preview=f"{made} tag{'s' if made != 1 else ''} placed")


def _set_parameter(instance: str = "", element_id: int = 0,
                   parameter: str = "", value: str = "") -> OpResult:
    """Set a parameter on one element by id. DESTRUCTIVE — mutates the model."""
    op_id = "revit.set_parameter"
    eid = int(element_id or 0)
    if eid <= 0:
        return OpResult.fail(
            "element_id is required (the integer Revit ElementId).", op_id)
    if not str(parameter or "").strip():
        return OpResult.fail("parameter name is required.", op_id)
    # JSON-encode the param name + value so they survive embedding safely.
    pname = json.dumps(str(parameter))
    pval = json.dumps("" if value is None else str(value))
    code = f"""
var e = Doc.GetElement(new ElementId({eid}));
if (e == null) {{ result = new Dictionary<string,object>{{
    {{"set", false}}, {{"error", "element not found"}} }}; }}
else {{
    var p = e.LookupParameter({pname});
    if (p == null) {{ result = new Dictionary<string,object>{{
        {{"set", false}}, {{"error", "parameter not found"}} }}; }}
    else if (p.IsReadOnly) {{ result = new Dictionary<string,object>{{
        {{"set", false}}, {{"error", "parameter is read-only"}} }}; }}
    else {{
        bool ok = false;
        string sval = {pval};
        try {{
            switch (p.StorageType) {{
                case StorageType.Integer:
                    ok = p.Set(int.Parse(sval)); break;
                case StorageType.Double:
                    ok = p.Set(double.Parse(sval)); break;
                case StorageType.String:
                    ok = p.Set(sval); break;
                default:
                    ok = p.Set(sval); break;
            }}
        }} catch (Exception ex) {{
            result = new Dictionary<string,object>{{
                {{"set", false}}, {{"error", ex.Message}} }};
        }}
        if (result == null) result = new Dictionary<string,object>{{
            {{"set", ok}}, {{"element", e.Name}},
            {{"parameter", {pname}}}, {{"value", sval}} }};
    }}
}}
"""
    res = _exec(op_id, code, instance=instance or None, tx_name=_TX_WRITE)
    if isinstance(res, OpResult):
        return res
    data = res if isinstance(res, dict) else {"result": res}
    if data.get("set") is False:
        return OpResult.fail(
            f"Could not set parameter: {data.get('error', 'unknown')}", op_id)
    return OpResult(
        ok=True, value=data, op_id=op_id,
        value_preview=f"set {data.get('parameter', parameter)} = "
                      f"{data.get('value', value)}")


# ── AgDR-0041 Property 1 — typed-host primitives (host swap) ────────
# The typed host nodes (workflows/nodes/host_typed.py) resolve to these
# op-ids so "Run script", "Export viewport", "Import mesh" do REAL Revit
# work — same wire, swap the host param. All three route through the
# RevitMCP broker (/exec + /screenshot) the same way every other Revit op
# does. Host offline → honest _broker_offline_result, never a fabricated
# value or an "unknown op" lie.

def _run_script(instance: str = "", code: str = "",
                params: Any = None) -> OpResult:
    """`revit.run_script` — execute a C# snippet in Revit's API context
    via the existing /exec route. Destructive escape hatch (the script
    decides whether it mutates the model). The snippet may assign a
    JSON-serialisable value to `result` to return data."""
    op_id = "revit.run_script"
    src = str(code or "").strip()
    if not src:
        return OpResult.fail("code is required", op_id)
    res = _exec(op_id, src, instance=instance or None, tx_name=_TX_WRITE,
                timeout=120.0)
    if isinstance(res, OpResult):
        return res
    return OpResult(ok=True, value=res, op_id=op_id,
                    value_preview=_preview(res))


def _export_viewport(instance: str = "", view: str = "",
                     width: int = 2048, height: int = 1536,
                     output_path: str = "") -> OpResult:
    """`revit.export_viewport` — render the active view to a PNG via the
    RevitMCP /screenshot route and return {image, depth, view, path}.

    `view` is accepted for typed-node symmetry; the shipped RevitMCP
    /screenshot exports the ACTIVE view, so when a named view is given we
    first activate it via /exec, then capture. `depth` is None on Revit
    (no depth pass in the shipped add-in) — honest, not fabricated."""
    op_id = "revit.export_viewport"
    if revit_broker is None:
        return _broker_offline_result(op_id)
    try:
        session = revit_broker.pick_session(prefer=instance or None)
    except Exception as ex:
        return OpResult.fail(f"Revit broker error: {ex}", op_id)
    if session is None:
        return _broker_offline_result(op_id)

    # Optional: switch to a named view before the capture.
    want_view = str(view or "").strip()
    if want_view:
        vname = json.dumps(want_view)
        activate = f"""
var col = new FilteredElementCollector(Doc).OfClass(typeof(View));
View target = null;
foreach (View v in col) {{
    if (!v.IsTemplate && v.Name == {vname}) {{ target = v; break; }}
}}
if (target != null) {{ UIDoc.ActiveView = target; }}
result = new Dictionary<string,object>{{
    {{"activated", target != null}}, {{"view", {vname}}} }};
"""
        act = _exec(op_id, activate, instance=instance or None,
                    tx_name=_TX_READ)
        if isinstance(act, OpResult):
            return act  # broker/add-in error — surface honestly

    out_path = str(output_path or "").strip()
    body_obj: dict[str, Any] = {"width_px": int(width or 2048)}
    if out_path:
        body_obj["output_path"] = out_path
    body = json.dumps(body_obj).encode("utf-8")
    try:
        resp = revit_broker.forward(
            session, "/screenshot", body=body, method="POST", timeout=60.0)
    except Exception as ex:
        return OpResult.fail(f"Revit screenshot call failed: {ex}", op_id)
    if not isinstance(resp, dict):
        return OpResult.fail("Revit add-in returned a non-JSON response.",
                             op_id)
    if resp.get("status") == "error":
        return OpResult.fail(
            f"Revit screenshot error: {resp.get('error', 'unknown error')}",
            op_id)
    saved = resp.get("output_path") or out_path
    vname2 = resp.get("view_name") or want_view
    value = {"image": saved, "depth": None, "view": vname2, "path": saved}
    return OpResult(ok=True, value=value, op_id=op_id,
                    value_preview=f"view '{vname2}' → {str(saved)[-40:]}")


# ── mesh import — real mesh parse → TessellatedShapeBuilder ────────
# A mesh is a {vertices, faces} pair: `vertices` is a flat list of
# [x,y,z] points, `faces` a list of vertex-index lists (each ≥3 indices,
# 0-based into `vertices`). The parsers below — OBJ, STL, PLY, glTF and
# GLB — each produce exactly this shape; `_import_mesh` embeds it into a
# C# script that rebuilds it with Revit's TessellatedShapeBuilder. This
# is the honest, no-shell path — Revit has no native importer for any of
# these mesh formats, so we parse the file in Python (full control over
# formats + errors) and hand Revit explicit geometry to build.


class MeshParseError(Exception):
    """Raised when a mesh file can't be parsed — surfaced as an honest
    OpResult.fail, never a fabricated success."""


def _parse_obj(text: str) -> tuple[list, list]:
    """Parse Wavefront OBJ → (vertices, faces).

    `vertices` = list of [x,y,z] floats (object units). `faces` = list of
    0-based index lists. Supports negative (relative) indices and the
    `v/vt/vn` face-vertex syntax (only the position index is used).
    n-gon faces are kept whole — the C# side fan-triangulates them.
    """
    vertices: list = []
    faces: list = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line[0] == "#":
            continue
        parts = line.split()
        tag = parts[0]
        if tag == "v":
            if len(parts) < 4:
                continue
            try:
                vertices.append(
                    [float(parts[1]), float(parts[2]), float(parts[3])])
            except ValueError:
                continue
        elif tag == "f":
            idx: list = []
            for tok in parts[1:]:
                # token is v, v/vt, v//vn or v/vt/vn — take the v index.
                vtok = tok.split("/")[0]
                if not vtok:
                    continue
                try:
                    vi = int(vtok)
                except ValueError:
                    continue
                # OBJ indices are 1-based; negatives are relative to the
                # current vertex count.
                if vi < 0:
                    vi = len(vertices) + vi
                else:
                    vi = vi - 1
                idx.append(vi)
            if len(idx) >= 3:
                faces.append(idx)
    if not vertices:
        raise MeshParseError("OBJ has no vertices (no `v` lines).")
    if not faces:
        raise MeshParseError("OBJ has no faces (no `f` lines).")
    # Validate indices are in range — an out-of-range face would crash
    # the C# build with an opaque IndexOutOfRange. Fail honestly here.
    nv = len(vertices)
    for f in faces:
        for vi in f:
            if vi < 0 or vi >= nv:
                raise MeshParseError(
                    f"OBJ face references vertex {vi + 1} but only {nv} "
                    "vertices exist.")
    return vertices, faces


def _parse_stl(data: bytes) -> tuple[list, list]:
    """Parse STL (binary or ASCII) → (vertices, faces).

    STL stores independent triangles with duplicated vertices; we dedup
    coincident vertices so the TessellatedShapeBuilder gets a connected
    face set (Revit needs shared vertices to form a coherent shell).
    """
    import struct

    verts: list = []
    faces: list = []
    index_of: dict = {}

    def _vid(x: float, y: float, z: float) -> int:
        # Round to 1e-6 to merge float-noise duplicates from STL.
        key = (round(x, 6), round(y, 6), round(z, 6))
        vi = index_of.get(key)
        if vi is None:
            vi = len(verts)
            index_of[key] = vi
            verts.append([x, y, z])
        return vi

    is_binary = False
    if len(data) >= 84:
        # ASCII STL starts with "solid"; but some binary files also do.
        # The reliable test: declared triangle count matches file size.
        tri_count = struct.unpack_from("<I", data, 80)[0]
        if 84 + tri_count * 50 == len(data):
            is_binary = True
    if not data.lstrip()[:5].lower().startswith(b"solid"):
        is_binary = is_binary or len(data) >= 84

    if is_binary:
        tri_count = struct.unpack_from("<I", data, 80)[0]
        off = 84
        for _ in range(tri_count):
            # 12 floats: normal(3) + v0(3) + v1(3) + v2(3); skip normal.
            vals = struct.unpack_from("<12f", data, off)
            off += 50  # 48 bytes floats + 2 byte attribute count
            a = _vid(vals[3], vals[4], vals[5])
            b = _vid(vals[6], vals[7], vals[8])
            c = _vid(vals[9], vals[10], vals[11])
            if a != b and b != c and a != c:
                faces.append([a, b, c])
    else:
        text = data.decode("utf-8", errors="replace")
        tri: list = []
        for raw in text.splitlines():
            line = raw.strip()
            if line.startswith("vertex"):
                p = line.split()
                if len(p) >= 4:
                    try:
                        tri.append((float(p[1]), float(p[2]), float(p[3])))
                    except ValueError:
                        pass
                if len(tri) == 3:
                    a = _vid(*tri[0])
                    b = _vid(*tri[1])
                    c = _vid(*tri[2])
                    if a != b and b != c and a != c:
                        faces.append([a, b, c])
                    tri = []
    if not verts:
        raise MeshParseError("STL has no vertices.")
    if not faces:
        raise MeshParseError("STL has no triangles.")
    return verts, faces


# ── PLY (Stanford polygon) — ASCII + binary_little/big_endian ──────
# Struct format chars for PLY scalar property types (both spellings).
_PLY_TYPE_FMT = {
    "char": "b", "int8": "b", "uchar": "B", "uint8": "B",
    "short": "h", "int16": "h", "ushort": "H", "uint16": "H",
    "int": "i", "int32": "i", "uint": "I", "uint32": "I",
    "float": "f", "float32": "f", "double": "d", "float64": "d",
}


def _fan_triangulate(idx: list, nv: int, what: str) -> list:
    """Fan-triangulate one polygon index list (≥3) into triangles, with
    an in-range check. Shared by every parser that yields polygons."""
    out: list = []
    for vi in idx:
        if vi < 0 or vi >= nv:
            raise MeshParseError(
                f"{what} references vertex {vi} but only {nv} exist.")
    for k in range(1, len(idx) - 1):
        a, b, c = idx[0], idx[k], idx[k + 1]
        if a != b and b != c and a != c:
            out.append([a, b, c])
    return out


def _parse_ply(data: bytes) -> tuple[list, list]:
    """Parse a Stanford PLY (ASCII or binary little/big-endian) →
    (vertices, faces).

    Reads the text header (`element vertex N`, `element face M`, each
    element's `property` lines incl. the `property list` for face index
    arrays), then the body in the declared format. x/y/z are pulled by
    property name; the face vertex-index list is fan-triangulated when a
    polygon has >3 vertices. Properties we don't use (normals, colour,
    texture coords, per-face extras) are read + skipped so the binary
    stride stays correct.
    """
    import struct

    nl = data.find(b"\n")
    if nl < 0 or not data[:nl].strip().lower().startswith(b"ply"):
        raise MeshParseError("Not a PLY file (missing 'ply' magic).")

    # Split header (ends at the line 'end_header') from the body.
    end_tok = b"end_header"
    pos = data.find(end_tok)
    if pos < 0:
        raise MeshParseError("PLY has no 'end_header'.")
    hdr_end = data.find(b"\n", pos)
    if hdr_end < 0:
        hdr_end = len(data)
    header = data[:hdr_end].decode("ascii", errors="replace")
    body = data[hdr_end + 1:]

    fmt = "ascii"
    elements: list = []   # [(name, count, [props])]; prop = dict
    cur: dict | None = None
    for raw in header.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        kw = parts[0].lower()
        if kw == "format" and len(parts) >= 2:
            fmt = parts[1].lower()
        elif kw == "element" and len(parts) >= 3:
            cur = {"name": parts[1], "count": int(parts[2]), "props": []}
            elements.append(cur)
        elif kw == "property" and cur is not None:
            if parts[1].lower() == "list":
                # property list <count_type> <index_type> <name>
                cur["props"].append({
                    "list": True, "count_type": parts[2].lower(),
                    "item_type": parts[3].lower(), "name": parts[4]})
            else:
                cur["props"].append({
                    "list": False, "type": parts[1].lower(),
                    "name": parts[2]})

    if fmt.startswith("binary_little"):
        endian = "<"
        is_ascii = False
    elif fmt.startswith("binary_big"):
        endian = ">"
        is_ascii = False
    else:
        endian = ""
        is_ascii = True

    verts: list = []
    faces: list = []

    if is_ascii:
        # Tokenise the whole body once; consume left-to-right by schema.
        toks = body.split()
        ti = 0

        def _take() -> str:
            nonlocal ti
            if ti >= len(toks):
                raise MeshParseError("PLY body ended mid-element.")
            t = toks[ti]
            ti += 1
            return t

        for el in elements:
            is_vert = el["name"].lower() == "vertex"
            is_face = el["name"].lower() == "face"
            for _ in range(el["count"]):
                xyz = {"x": 0.0, "y": 0.0, "z": 0.0}
                face_idx: list = []
                for p in el["props"]:
                    if p["list"]:
                        n = int(float(_take()))
                        items = [int(float(_take())) for _ in range(n)]
                        if is_face:
                            face_idx = items
                    else:
                        val = _take()
                        if is_vert and p["name"] in ("x", "y", "z"):
                            xyz[p["name"]] = float(val)
                if is_vert:
                    verts.append([xyz["x"], xyz["y"], xyz["z"]])
                elif is_face and len(face_idx) >= 3:
                    faces.append(face_idx)
    else:
        off = 0

        def _scalar(tp: str):
            nonlocal off
            fc = _PLY_TYPE_FMT.get(tp)
            if fc is None:
                raise MeshParseError(f"PLY: unknown property type '{tp}'.")
            sz = struct.calcsize(fc)
            val = struct.unpack_from(endian + fc, body, off)[0]
            off += sz
            return val

        for el in elements:
            is_vert = el["name"].lower() == "vertex"
            is_face = el["name"].lower() == "face"
            for _ in range(el["count"]):
                xyz = {"x": 0.0, "y": 0.0, "z": 0.0}
                face_idx = []
                for p in el["props"]:
                    if p["list"]:
                        n = int(_scalar(p["count_type"]))
                        items = [int(_scalar(p["item_type"]))
                                 for _ in range(n)]
                        if is_face:
                            face_idx = items
                    else:
                        v = _scalar(p["type"])
                        if is_vert and p["name"] in ("x", "y", "z"):
                            xyz[p["name"]] = float(v)
                if is_vert:
                    verts.append([xyz["x"], xyz["y"], xyz["z"]])
                elif is_face and len(face_idx) >= 3:
                    faces.append(face_idx)

    if not verts:
        raise MeshParseError("PLY has no vertices.")
    if not faces:
        raise MeshParseError("PLY has no faces.")
    nv = len(verts)
    tris: list = []
    for f in faces:
        tris.extend(_fan_triangulate(f, nv, "PLY face"))
    if not tris:
        raise MeshParseError("PLY faces produced no triangles.")
    return verts, tris


# ── glTF 2.0 (.gltf JSON + .glb binary container) ──────────────────
# Accessor componentType → (struct char, byte size).
_GLTF_COMP = {
    5120: ("b", 1), 5121: ("B", 1),   # BYTE / UNSIGNED_BYTE
    5122: ("h", 2), 5123: ("H", 2),   # SHORT / UNSIGNED_SHORT
    5125: ("I", 4), 5126: ("f", 4),   # UNSIGNED_INT / FLOAT
}
# Accessor type → component count.
_GLTF_NCOMP = {
    "SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4,
    "MAT2": 4, "MAT3": 9, "MAT4": 16,
}


def _gltf_resolve_buffers(gltf: dict, base_dir: str,
                          glb_bin: bytes | None) -> list:
    """Resolve every glTF buffer to raw bytes: a base64 `data:` URI, a
    sibling file referenced by a relative URI, or (buffer 0, no URI) the
    GLB binary chunk. Raises MeshParseError on anything unresolvable."""
    import base64
    import os
    import urllib.parse

    out: list = []
    for i, buf in enumerate(gltf.get("buffers", [])):
        uri = buf.get("uri")
        if uri is None:
            if glb_bin is None:
                raise MeshParseError(
                    f"glTF buffer {i} has no URI and there is no GLB "
                    "binary chunk to satisfy it.")
            out.append(glb_bin)
        elif uri.startswith("data:"):
            comma = uri.find(",")
            if comma < 0:
                raise MeshParseError(f"glTF buffer {i}: malformed data URI.")
            meta, payload = uri[:comma], uri[comma + 1:]
            if ";base64" in meta:
                out.append(base64.b64decode(payload))
            else:
                out.append(urllib.parse.unquote_to_bytes(payload))
        else:
            rel = urllib.parse.unquote(uri)
            fp = os.path.join(base_dir, rel)
            if not os.path.isfile(fp):
                raise MeshParseError(
                    f"glTF buffer {i}: sibling file not found: {rel}")
            with open(fp, "rb") as fh:
                out.append(fh.read())
    return out


def _gltf_read_accessor(gltf: dict, buffers: list, idx: int) -> list:
    """Read accessor `idx` → list of tuples (one per element). Honours the
    bufferView byteOffset/byteStride + accessor byteOffset; supports the
    interleaved (strided) layout. No sparse-accessor support (rare for
    geometry) — flagged honestly if encountered."""
    import struct

    accessors = gltf.get("accessors", [])
    if idx < 0 or idx >= len(accessors):
        raise MeshParseError(f"glTF accessor {idx} out of range.")
    acc = accessors[idx]
    if "sparse" in acc:
        raise MeshParseError(
            "glTF sparse accessors are not supported (uncommon for mesh "
            "geometry).")
    comp = acc.get("componentType")
    if comp not in _GLTF_COMP:
        raise MeshParseError(f"glTF: bad componentType {comp}.")
    fc, csize = _GLTF_COMP[comp]
    ncomp = _GLTF_NCOMP.get(acc.get("type"))
    if ncomp is None:
        raise MeshParseError(f"glTF: bad accessor type {acc.get('type')}.")
    count = int(acc.get("count", 0))
    acc_off = int(acc.get("byteOffset", 0))

    bv_idx = acc.get("bufferView")
    if bv_idx is None:
        # No bufferView → all-zero accessor (valid in spec, useless here).
        return [tuple([0] * ncomp) for _ in range(count)]
    bviews = gltf.get("bufferViews", [])
    if bv_idx < 0 or bv_idx >= len(bviews):
        raise MeshParseError(f"glTF bufferView {bv_idx} out of range.")
    bv = bviews[bv_idx]
    b_idx = bv.get("buffer", 0)
    if b_idx < 0 or b_idx >= len(buffers):
        raise MeshParseError(f"glTF buffer {b_idx} out of range.")
    raw = buffers[b_idx]
    bv_off = int(bv.get("byteOffset", 0))
    elem_size = csize * ncomp
    stride = int(bv.get("byteStride", 0)) or elem_size
    base = bv_off + acc_off

    out: list = []
    for e in range(count):
        start = base + e * stride
        vals = struct.unpack_from("<" + fc * ncomp, raw, start)
        out.append(vals)
    return out


def _mat4_mul_point(m: list, p: tuple) -> list:
    """Transform a 3-point by a column-major 4x4 glTF matrix (length 16)."""
    x, y, z = p[0], p[1], p[2]
    # glTF matrices are column-major: m[col*4 + row].
    nx = m[0] * x + m[4] * y + m[8] * z + m[12]
    ny = m[1] * x + m[5] * y + m[9] * z + m[13]
    nz = m[2] * x + m[6] * y + m[10] * z + m[14]
    nw = m[3] * x + m[7] * y + m[11] * z + m[15]
    if nw and abs(nw - 1.0) > 1e-9:
        nx, ny, nz = nx / nw, ny / nw, nz / nw
    return [nx, ny, nz]


def _trs_to_mat4(node: dict) -> list | None:
    """Build a column-major 4x4 from a node's matrix, or its
    translation/rotation/scale (TRS). Returns None for an identity node
    (no transform keys) so the caller can skip the multiply."""
    import math

    if "matrix" in node:
        m = node["matrix"]
        if len(m) == 16:
            return list(m)
    t = node.get("translation")
    r = node.get("rotation")
    s = node.get("scale")
    if not (t or r or s):
        return None
    tx, ty, tz = (t or [0.0, 0.0, 0.0])
    qx, qy, qz, qw = (r or [0.0, 0.0, 0.0, 1.0])
    sx, sy, sz = (s or [1.0, 1.0, 1.0])
    # Rotation matrix (3x3) from quaternion.
    n = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw) or 1.0
    qx, qy, qz, qw = qx / n, qy / n, qz / n, qw / n
    r00 = 1 - 2 * (qy * qy + qz * qz)
    r01 = 2 * (qx * qy - qz * qw)
    r02 = 2 * (qx * qz + qy * qw)
    r10 = 2 * (qx * qy + qz * qw)
    r11 = 1 - 2 * (qx * qx + qz * qz)
    r12 = 2 * (qy * qz - qx * qw)
    r20 = 2 * (qx * qz - qy * qw)
    r21 = 2 * (qy * qz + qx * qw)
    r22 = 1 - 2 * (qx * qx + qy * qy)
    # Column-major M = T * R * S.
    return [
        r00 * sx, r10 * sx, r20 * sx, 0.0,
        r01 * sy, r11 * sy, r21 * sy, 0.0,
        r02 * sz, r12 * sz, r22 * sz, 0.0,
        tx, ty, tz, 1.0,
    ]


def _gltf_node_world_transforms(gltf: dict) -> dict:
    """Map mesh-index → world matrix (column-major, len 16) by walking the
    node hierarchy of every scene. A mesh used by several nodes keeps the
    first node's transform (the common single-instance case). Meshes not
    referenced by any node get no entry (identity)."""
    nodes = gltf.get("nodes", [])
    out: dict = {}

    def _compose(parent: list | None, local: list | None) -> list | None:
        if parent is None:
            return local
        if local is None:
            return parent
        # parent * local, both column-major 4x4.
        res = [0.0] * 16
        for col in range(4):
            for row in range(4):
                acc = 0.0
                for k in range(4):
                    acc += parent[k * 4 + row] * local[col * 4 + k]
                res[col * 4 + row] = acc
        return res

    def _walk(ni: int, parent_m: list | None, seen: set):
        if ni < 0 or ni >= len(nodes) or ni in seen:
            return
        seen.add(ni)
        node = nodes[ni]
        world = _compose(parent_m, _trs_to_mat4(node))
        mi = node.get("mesh")
        if mi is not None and mi not in out and world is not None:
            out[mi] = world
        for child in node.get("children", []) or []:
            _walk(child, world, seen)

    scenes = gltf.get("scenes", [])
    roots: list = []
    for sc in scenes:
        roots.extend(sc.get("nodes", []) or [])
    if not roots:
        roots = list(range(len(nodes)))
    seen: set = set()
    for r in roots:
        _walk(r, None, seen)
    return out


def _parse_gltf(gltf: dict, base_dir: str,
                glb_bin: bytes | None) -> tuple[list, list]:
    """Core glTF→(vertices, faces) for both .gltf and .glb. Merges every
    primitive of every mesh into one vertex/triangle set (vertices are
    re-based per primitive so indices stay correct). Applies each mesh's
    node world transform when present. Non-triangle primitive modes are
    rejected honestly."""
    buffers = _gltf_resolve_buffers(gltf, base_dir, glb_bin)
    meshes = gltf.get("meshes", [])
    if not meshes:
        raise MeshParseError("glTF has no meshes.")
    xforms = _gltf_node_world_transforms(gltf)

    all_verts: list = []
    all_faces: list = []
    for mi, mesh in enumerate(meshes):
        world = xforms.get(mi)
        for prim in mesh.get("primitives", []):
            mode = prim.get("mode", 4)  # default TRIANGLES
            if mode != 4:
                raise MeshParseError(
                    f"glTF primitive mode {mode} unsupported — only "
                    "TRIANGLES (4). Re-export triangulated.")
            attrs = prim.get("attributes", {})
            pos_acc = attrs.get("POSITION")
            if pos_acc is None:
                raise MeshParseError("glTF primitive has no POSITION.")
            positions = _gltf_read_accessor(gltf, buffers, pos_acc)
            base = len(all_verts)
            for p in positions:
                pt = [float(p[0]), float(p[1]), float(p[2])]
                if world is not None:
                    pt = _mat4_mul_point(world, pt)
                all_verts.append(pt)
            idx_acc = prim.get("indices")
            if idx_acc is None:
                # Non-indexed: sequential triples.
                seq = list(range(len(positions)))
            else:
                seq = [int(t[0])
                       for t in _gltf_read_accessor(gltf, buffers, idx_acc)]
            for k in range(0, len(seq) - 2, 3):
                a, b, c = seq[k] + base, seq[k + 1] + base, seq[k + 2] + base
                if a != b and b != c and a != c:
                    all_faces.append([a, b, c])

    if not all_verts:
        raise MeshParseError("glTF produced no vertices.")
    if not all_faces:
        raise MeshParseError("glTF produced no triangles.")
    nv = len(all_verts)
    for f in all_faces:
        for vi in f:
            if vi < 0 or vi >= nv:
                raise MeshParseError(
                    f"glTF index {vi} out of range ({nv} vertices).")
    return all_verts, all_faces


def _parse_gltf_file(path: str) -> tuple[list, list]:
    """Read a .gltf JSON document and parse it (buffers resolved relative
    to the file's directory; embedded base64 data URIs supported)."""
    import json as _json
    import os

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        gltf = _json.load(fh)
    if not isinstance(gltf, dict):
        raise MeshParseError("glTF root is not a JSON object.")
    return _parse_gltf(gltf, os.path.dirname(os.path.abspath(path)), None)


def _parse_glb(data: bytes) -> tuple[list, list]:
    """Parse a binary glTF (.glb) container → (vertices, faces).

    Layout: 12-byte header (magic 'glTF', uint32 version, uint32 total
    length) followed by chunks, each `uint32 length · uint32 type · data`.
    Chunk type 0x4E4F534A ('JSON') carries the glTF document; 0x004E4942
    ('BIN\\0') carries the geometry buffer. We parse the JSON, then run
    the same accessor logic with the BIN chunk as buffer 0.
    """
    import json as _json
    import struct

    if len(data) < 12 or data[:4] != b"glTF":
        raise MeshParseError("Not a GLB file (missing 'glTF' magic).")
    version, total = struct.unpack_from("<II", data, 4)
    if version != 2:
        raise MeshParseError(f"GLB version {version} unsupported (need 2).")
    json_bytes: bytes | None = None
    bin_bytes: bytes | None = None
    off = 12
    end = min(total, len(data)) if total else len(data)
    while off + 8 <= end:
        clen, ctype = struct.unpack_from("<II", data, off)
        off += 8
        chunk = data[off:off + clen]
        off += clen
        if ctype == 0x4E4F534A:        # 'JSON'
            json_bytes = chunk
        elif ctype == 0x004E4942:      # 'BIN\0'
            bin_bytes = chunk
        # Unknown chunk types are skipped per spec.
    if json_bytes is None:
        raise MeshParseError("GLB has no JSON chunk.")
    gltf = _json.loads(json_bytes.decode("utf-8", errors="replace"))
    if not isinstance(gltf, dict):
        raise MeshParseError("GLB JSON chunk is not an object.")
    return _parse_gltf(gltf, "", bin_bytes)


# Every mesh format `import_mesh` can parse — used in the dispatch + in
# the honest "unsupported" error so the supported set is named in one
# place and never drifts.
_SUPPORTED_MESH_EXTS = ("obj", "stl", "ply", "gltf", "glb")


def _parse_mesh_file(path: str) -> tuple[list, list, str]:
    """Read + parse a mesh file → (vertices, faces, fmt).

    Dispatch is by extension first, then by magic bytes (so a `glTF`
    binary container or a `ply` file is still parsed even when the
    extension is wrong / missing). Supported: OBJ, STL (ascii+binary),
    PLY (ascii+binary), glTF (.gltf JSON), GLB (binary glTF).

    Raises FileNotFoundError if missing, MeshParseError on a parse
    failure, and NotImplementedError for a genuinely unsupported format
    — each surfaced as an honest OpResult.fail by the caller. NEVER
    fabricates.
    """
    import os

    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    ext = os.path.splitext(path)[1].lower().lstrip(".")

    # Text formats read as str; binary/ambiguous formats read as bytes.
    if ext == "obj":
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            verts, faces = _parse_obj(fh.read())
        return verts, faces, "obj"
    if ext == "stl":
        with open(path, "rb") as fh:
            verts, faces = _parse_stl(fh.read())
        return verts, faces, "stl"
    if ext == "ply":
        with open(path, "rb") as fh:
            verts, faces = _parse_ply(fh.read())
        return verts, faces, "ply"
    if ext == "gltf":
        return (*_parse_gltf_file(path), "gltf")
    if ext == "glb":
        with open(path, "rb") as fh:
            verts, faces = _parse_glb(fh.read())
        return verts, faces, "glb"

    # Unknown / missing extension — sniff magic bytes before giving up.
    with open(path, "rb") as fh:
        head = fh.read(64)
    if head[:4] == b"glTF":
        with open(path, "rb") as fh:
            verts, faces = _parse_glb(fh.read())
        return verts, faces, "glb"
    if head.lstrip()[:3].lower() == b"ply":
        with open(path, "rb") as fh:
            verts, faces = _parse_ply(fh.read())
        return verts, faces, "ply"
    stripped = head.lstrip().lower()
    if stripped[:5] == b"solid" or (len(head) >= 5 and b"facet" in stripped):
        with open(path, "rb") as fh:
            verts, faces = _parse_stl(fh.read())
        return verts, faces, "stl"
    # JSON object that looks like glTF (top-level "asset"/"meshes").
    if stripped[:1] == b"{" and (b"\"asset\"" in head or b"\"meshes\"" in head):
        return (*_parse_gltf_file(path), "gltf")
    raise NotImplementedError(ext or "(no extension)")


# Object-unit → Revit-internal (feet) scale. OBJ/STL are unitless; the
# overwhelmingly common authoring unit for these mesh formats in AEC is
# the metre, so we default to metres→feet. Honest + overridable: the op
# echoes the assumed unit back in the result so a caller can re-import
# with a different `unit` if the scale is wrong.
_UNIT_TO_FEET = {
    "m": 3.2808398950131235, "meter": 3.2808398950131235,
    "mm": 0.0032808398950131, "millimeter": 0.0032808398950131,
    "cm": 0.032808398950131, "centimeter": 0.032808398950131,
    "ft": 1.0, "feet": 1.0, "foot": 1.0,
    "in": 0.08333333333333333, "inch": 0.08333333333333333,
}


def _tessellate_cs(vertices: list, faces: list, scale: float,
                   ds_name: str) -> str:
    """Generate the C# that rebuilds (vertices, faces) as a real
    DirectShape via TessellatedShapeBuilder.

    The script:
      • materialises the vertex table as XYZ[] (object units → feet),
      • adds each face as a TessellatedFace (fan-triangulating n-gons),
      • Build()s a Mesh-target shape with Salvage fallback,
      • SetShape()s the resulting GeometryObjects on a fresh DirectShape,
      • returns the new element id + a verifiable face/vertex count + the
        shape's bounding box so the caller can prove the geometry is real
        and non-empty.

    A transaction is already open (RunCSharpScript wraps the script), so
    we do NOT start our own. Honest failure: if Build() yields no
    geometry, `created` is false with the builder's reason — never a
    silent empty element.
    """
    # Flatten verts to a compact C# initialiser (object units; scaled in
    # C# so the source stays small + the scale is auditable in one place).
    vert_lines = ",".join(
        f"new XYZ({v[0]!r}*S,{v[1]!r}*S,{v[2]!r}*S)" for v in vertices)
    # Faces as jagged int[][].
    face_lines = ",".join(
        "new int[]{" + ",".join(str(i) for i in f) + "}" for f in faces)
    pname = json.dumps(str(ds_name))
    return f"""
double S = {scale!r};
var V = new XYZ[]{{{vert_lines}}};
var F = new int[][]{{{face_lines}}};
DirectShape ds = DirectShape.CreateElement(
    Doc, new ElementId(BuiltInCategory.OST_GenericModel));
try {{ ds.Name = {pname}; }} catch {{ }}
var tsb = new TessellatedShapeBuilder();
tsb.OpenConnectedFaceSet(false);
int faceCount = 0;
foreach (var f in F) {{
    if (f.Length < 3) continue;
    // Fan-triangulate polygons (>3 verts) so the Mesh target accepts
    // every face; triangles pass through unchanged.
    for (int k = 1; k + 1 < f.Length; k++) {{
        var loop = new List<XYZ>{{ V[f[0]], V[f[k]], V[f[k+1]] }};
        try {{
            tsb.AddFace(new TessellatedFace(loop, ElementId.InvalidElementId));
            faceCount++;
        }} catch {{ }}
    }}
}}
tsb.CloseConnectedFaceSet();
tsb.Target = TessellatedShapeBuilderTarget.Mesh;
tsb.Fallback = TessellatedShapeBuilderFallback.Salvage;
string err = "";
bool created = false;
int geomCount = 0;
double[] bb = null;
try {{
    tsb.Build();
    var br = tsb.GetBuildResult();
    var objs = br.GetGeometricalObjects();
    geomCount = (objs != null) ? objs.Count : 0;
    if (geomCount > 0) {{
        ds.SetShape(objs);
        created = true;
        var box = ds.get_BoundingBox(null);
        if (box != null) {{
            bb = new double[]{{ box.Min.X, box.Min.Y, box.Min.Z,
                                box.Max.X, box.Max.Y, box.Max.Z }};
        }}
    }} else {{
        err = "TessellatedShapeBuilder produced no geometry "
            + "(build result empty).";
    }}
}} catch (Exception ex) {{ err = ex.GetType().Name + ": " + ex.Message; }}
result = new Dictionary<string,object>{{
    {{"created", created}},
    {{"element_id", ds.Id.IntegerValue}},
    {{"name", {pname}}},
    {{"vertex_count", V.Length}},
    {{"face_count", faceCount}},
    {{"geometry_object_count", geomCount}},
    {{"bbox", bb}},
    {{"error", err}}
}};
"""


def _import_mesh(instance: str = "", mesh: Any = None,
                 name: str = "", layer: str = "", unit: str = "m") -> OpResult:
    """`revit.import_mesh` — create a real DirectShape in the model from a
    mesh file (OBJ · STL · PLY · glTF · GLB) via Revit's
    TessellatedShapeBuilder. DESTRUCTIVE — adds an element.

    The mesh file is parsed in Python (vertices + triangle faces — Revit
    has no native importer for these formats), then rebuilt inside Revit
    as a tessellated DirectShape (BuiltInCategory OST_GenericModel) with
    REAL geometry: each face becomes a TessellatedFace, Build() yields
    the GeometryObjects, SetShape() makes it visible. The op returns the
    new element id plus a vertex/face/geometry-object count and a
    bounding box so the created geometry is verifiably non-empty.

    Honest failure modes (never a fake success):
      • file missing            → OpResult.fail
      • unsupported format      → OpResult.fail (names the supported set)
      • parse error / bad faces → OpResult.fail
      • Build() empty           → OpResult.fail with the builder's reason
    """
    op_id = "revit.import_mesh"
    # Resolve a usable path out of whatever the upstream node handed us.
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
            "import_mesh needs a mesh file path (.obj/.stl/.ply/.gltf/.glb) "
            "on the `mesh` input — got "
            f"{type(mesh).__name__} with no resolvable path.", op_id)

    # Parse the mesh file (Python-side — full control over formats +
    # errors). Honest failure for every bad-input class.
    try:
        vertices, faces, fmt = _parse_mesh_file(path)
    except FileNotFoundError:
        return OpResult.fail(f"Mesh file not found: {path}", op_id)
    except NotImplementedError as ex:
        supported = "/".join("." + e for e in _SUPPORTED_MESH_EXTS)
        return OpResult.fail(
            f"Unsupported mesh format '{ex}'. import_mesh parses "
            f"{supported} (Revit has no native importer for these — they "
            "are parsed in Python and rebuilt as a DirectShape).", op_id)
    except MeshParseError as ex:
        return OpResult.fail(f"Could not parse mesh: {ex}", op_id)
    except Exception as ex:  # pragma: no cover - defensive
        return OpResult.fail(f"Mesh read failed: {ex}", op_id)

    scale = _UNIT_TO_FEET.get(str(unit or "m").strip().lower(),
                              _UNIT_TO_FEET["m"])
    ds_name = str(name or "ArchHub Mesh")
    code = _tessellate_cs(vertices, faces, scale, ds_name)

    res = _exec(op_id, code, instance=instance or None, tx_name=_TX_WRITE,
                timeout=120.0)
    if isinstance(res, OpResult):
        return res
    data = res if isinstance(res, dict) else {"result": res}
    if not data.get("created"):
        return OpResult.fail(
            f"Could not import mesh: {data.get('error') or 'unknown'}", op_id)
    # Echo the parse stats + assumed unit so a caller can sanity-check
    # the scale (and re-import with a different `unit` if needed).
    data.setdefault("format", fmt)
    data.setdefault("unit", str(unit or "m"))
    fc = data.get("face_count", len(faces))
    vc = data.get("vertex_count", len(vertices))
    return OpResult(ok=True, value=data, op_id=op_id,
                    value_preview=f"DirectShape '{data.get('name', ds_name)}' "
                                  f"#{data.get('element_id', '?')} "
                                  f"· {vc} verts / {fc} faces")


# ── M2-Python (AgDR-0017) — Speckle ops wrappers ───────────────────
def _send_to_speckle_op(instance: str = "", value: Any = None,
                         model_name: str = "revit",
                         server_push: bool = False,
                         server_url: str = "") -> OpResult:
    """`revit.send_to_speckle` thin wrapper into
    `revit_speckle_ops.send_to_speckle`. `instance` is unused — the
    op does not touch live Revit (it ships the value through
    SpeckleWire). Kept for API symmetry with every other Revit op
    and so a downstream `revit.receive_from_speckle` lands in the
    same session selector."""
    from connectors.revit_speckle_ops import send_to_speckle
    result = send_to_speckle(
        value=value, model_name=model_name,
        server_push=bool(server_push), server_url=server_url)
    if result.get("status") == "error":
        return OpResult.fail(result.get("error", ""),
                              "revit.send_to_speckle")
    return OpResult(ok=True, value=result,
                     op_id="revit.send_to_speckle",
                     value_preview=f"{result.get('url', '')} "
                                   f"({result.get('item_count', 0)} items)")


def _receive_from_speckle_op(instance: str = "",
                              source_url: str = "") -> OpResult:
    """`revit.receive_from_speckle` thin wrapper that POSTs the
    annotation-driven create script through `/exec`."""
    if not source_url:
        return OpResult.fail("source_url is required",
                              "revit.receive_from_speckle")
    from connectors.revit_speckle_ops import receive_from_speckle
    # First-class broker-offline check — honest "Revit not running".
    if revit_broker is not None:
        try:
            running = revit_broker.is_any_alive()
        except Exception:
            running = False
        if not running:
            return _broker_offline_result("revit.receive_from_speckle")
    result = receive_from_speckle(source_url=source_url,
                                    instance=instance or None)
    if result.get("status") == "error":
        return OpResult.fail(result.get("error", ""),
                              "revit.receive_from_speckle")
    return OpResult(ok=True, value=result,
                     op_id="revit.receive_from_speckle",
                     value_preview=f"created={(result.get('result') or {}).get('created_count', 0)} "
                                   f"errors={(result.get('result') or {}).get('error_count', 0)}")


def _batch_set_parameters_op(instance: str = "",
                               source_url: str = "") -> OpResult:
    """`revit.batch_set_parameters` thin wrapper (AgDR-0018). Reads
    `{revit_element_id, revit_parameters}` items from a Speckle URL
    and pushes the parameter values onto each existing element."""
    if not source_url:
        return OpResult.fail("source_url is required",
                              "revit.batch_set_parameters")
    if revit_broker is not None:
        try:
            running = revit_broker.is_any_alive()
        except Exception:
            running = False
        if not running:
            return _broker_offline_result("revit.batch_set_parameters")
    from connectors.revit_speckle_ops import batch_set_parameters
    result = batch_set_parameters(source_url=source_url,
                                    instance=instance or None)
    if result.get("status") == "error":
        return OpResult.fail(result.get("error", ""),
                              "revit.batch_set_parameters")
    return OpResult(ok=True, value=result,
                     op_id="revit.batch_set_parameters",
                     value_preview=f"updated={(result.get('result') or {}).get('updated_count', 0)} "
                                   f"errors={(result.get('result') or {}).get('error_count', 0)}")


# ── connector ───────────────────────────────────────────────────────
class RevitConnector(Connector):
    """Autodesk Revit — drives the host through the multi-session broker."""

    host = "revit"
    display_name = "Autodesk Revit"
    mechanism = "broker"

    def probe(self) -> dict:
        """Honest broker probe — mirrors host_detector._probe_broker.

        live         — a Revit session's listener answered /ping.
        loaded_dead  — a Revit process is running but no listener answers
                       (the ArchHub connector isn't loaded / crashed).
        missing      — no Revit running at all.
        """
        if revit_broker is None:
            return {"status": "missing",
                    "note": "Revit broker module unavailable in this build.",
                    "detail": {}}
        try:
            count = revit_broker.sessions_count()
        except Exception as ex:
            return {"status": "missing",
                    "note": f"Revit broker probe failed: {ex}", "detail": {}}
        if count >= 1:
            # Confirm with a real /ping forward so we report the truth.
            try:
                session = revit_broker.pick_session()
            except Exception:
                session = None
            ping: dict = {}
            if session is not None:
                try:
                    ping = revit_broker.forward(
                        session, "/ping", method="GET", timeout=2.0)
                except Exception:
                    ping = {}
            if isinstance(ping, dict) and ping.get("status") == "error":
                # Listener present but /ping failed — treat as loaded_dead.
                return {
                    "status": "loaded_dead",
                    "note": ("Revit is open but the ArchHub connector "
                             "stopped responding — re-load it inside Revit."),
                    "detail": {"sessions": count},
                }
            doc = ""
            try:
                doc = session.doc_title if session else ""
            except Exception:
                doc = ""
            return {
                "status": "live",
                "note": (f"Revit broker live · {count} session"
                         f"{'s' if count != 1 else ''}"
                         + (f" · {doc}" if doc else "")),
                "detail": {
                    "sessions": count,
                    "version": str(ping.get("version", "")
                                    if isinstance(ping, dict) else ""),
                    "doc_title": doc,
                },
            }
        # No healthy session. Is a Revit session file present but stale?
        try:
            any_files = revit_broker.is_any_alive()
        except Exception:
            any_files = False
        if any_files:
            return {
                "status": "loaded_dead",
                "note": ("Revit is open but the ArchHub connector isn't "
                         "responding — open Revit and load the ArchHub "
                         "connector."),
                "detail": {"sessions": 0},
            }
        return {
            "status": "missing",
            "note": "Revit is not running. Open Revit and load the "
                    "ArchHub connector.",
            "detail": {"sessions": 0},
        }

    def build_ops(self) -> list:
        inst = _instance_param()

        def view_param(label: str = "View id") -> ParamSpec:
            return ParamSpec(
                id="view_id", label=label, type="number", default=0,
                help="Revit ElementId of the target view. 0 = active view.")

        return [
            # ---- READS ----
            ConnectorOp(
                op_id="revit.list_views", host="revit", kind="read",
                label="List views",
                description="Every non-template view in the model.",
                inputs=[inst], output_type="view", destructive=False,
                fn=_list_views,
            ),
            ConnectorOp(
                op_id="revit.list_walls", host="revit", kind="read",
                label="List walls",
                description="Every wall instance with type, length, level.",
                inputs=[inst], output_type="wall", destructive=False,
                fn=_list_walls,
            ),
            ConnectorOp(
                op_id="revit.list_doors", host="revit", kind="read",
                label="List doors",
                description="Every door instance with family and level.",
                inputs=[inst], output_type="door", destructive=False,
                fn=_list_doors,
            ),
            ConnectorOp(
                op_id="revit.list_windows", host="revit", kind="read",
                label="List windows",
                description="Every window instance with family and level.",
                inputs=[inst], output_type="window", destructive=False,
                fn=_list_windows,
            ),
            ConnectorOp(
                op_id="revit.list_rooms", host="revit", kind="read",
                label="List rooms",
                description="Every room with number and area.",
                inputs=[inst], output_type="room", destructive=False,
                fn=_list_rooms,
            ),
            ConnectorOp(
                op_id="revit.list_levels", host="revit", kind="read",
                label="List levels",
                description="Every level with its elevation.",
                inputs=[inst], output_type="level", destructive=False,
                fn=_list_levels,
            ),
            ConnectorOp(
                op_id="revit.list_sheets", host="revit", kind="read",
                label="List sheets",
                description="Every sheet with number and name.",
                inputs=[inst], output_type="sheet", destructive=False,
                fn=_list_sheets,
            ),
            ConnectorOp(
                op_id="revit.list_families", host="revit", kind="read",
                label="List families",
                description="Every loaded family with its category.",
                inputs=[inst], output_type="list", destructive=False,
                fn=_list_families,
            ),
            ConnectorOp(
                op_id="revit.get_selection", host="revit", kind="read",
                label="Get selection",
                description="Elements currently selected in Revit.",
                inputs=[inst], output_type="list", destructive=False,
                fn=_get_selection,
            ),
            ConnectorOp(
                op_id="revit.list_warnings", host="revit", kind="read",
                label="List warnings",
                description="Every model warning with severity.",
                inputs=[inst], output_type="list", destructive=False,
                fn=_list_warnings,
            ),
            # ---- ACTIONS ----
            ConnectorOp(
                op_id="revit.create_dimensions", host="revit", kind="action",
                label="Create dimensions",
                description="Auto-dimension straight walls in a view.",
                inputs=[inst, view_param()],
                output_type="any", destructive=True,
                fn=_create_dimensions,
            ),
            ConnectorOp(
                op_id="revit.place_tags", host="revit", kind="action",
                label="Place tags",
                description="Tag every element of a category in a view.",
                inputs=[
                    inst,
                    ParamSpec(id="category", label="Category", type="choice",
                              default="Doors",
                              options=["Doors", "Windows", "Walls", "Rooms"],
                              help="Element category to tag."),
                    view_param(),
                ],
                output_type="any", destructive=True,
                fn=_place_tags,
            ),
            ConnectorOp(
                op_id="revit.set_parameter", host="revit", kind="action",
                label="Set parameter",
                description="Set a parameter value on one element by id.",
                inputs=[
                    inst,
                    ParamSpec(id="element_id", label="Element id",
                              type="number", default=0, required=True,
                              help="Revit ElementId of the target element."),
                    ParamSpec(id="parameter", label="Parameter name",
                              type="text", default="", required=True,
                              help="Name of the parameter to set."),
                    ParamSpec(id="value", label="Value", type="text",
                              default="",
                              help="New value (parsed to the param's type)."),
                ],
                output_type="any", destructive=True,
                fn=_set_parameter,
            ),
            # ── AgDR-0041 P1 — typed-host primitives ───────────
            ConnectorOp(
                op_id="revit.run_script", host="revit", kind="action",
                label="Run script",
                description="Execute a C# snippet in Revit's API context "
                            "via /exec. Assign to `result` to return data.",
                inputs=[
                    inst,
                    ParamSpec(id="code", label="C# code", type="text",
                              default="", required=True,
                              help="C# snippet run inside a Revit "
                                   "transaction."),
                    ParamSpec(id="params", label="Params", type="any",
                              default=None,
                              help="Optional params object passed alongside "
                                   "the code."),
                ],
                output_type="any", destructive=True,
                fn=_run_script,
            ),
            ConnectorOp(
                op_id="revit.export_viewport", host="revit", kind="read",
                label="Export viewport",
                description="Render the active (or named) view to a PNG via "
                            "the RevitMCP /screenshot route.",
                inputs=[
                    inst,
                    ParamSpec(id="view", label="View name", type="text",
                              default="",
                              help="Optional view name to activate before "
                                   "capture. Empty = active view."),
                    ParamSpec(id="width", label="Width px", type="number",
                              default=2048,
                              help="Output image width in pixels."),
                    ParamSpec(id="height", label="Height px", type="number",
                              default=1536,
                              help="Output image height (best-effort)."),
                    ParamSpec(id="output_path", label="Output path",
                              type="text", default="",
                              help="Where to write the PNG. Empty = host "
                                   "default temp path."),
                ],
                output_type="any", destructive=False,
                fn=_export_viewport,
            ),
            ConnectorOp(
                op_id="revit.import_mesh", host="revit", kind="action",
                label="Import mesh",
                description="Create a real DirectShape from a mesh file "
                            "(.obj/.stl/.ply/.gltf/.glb) — parsed + rebuilt "
                            "with Revit's TessellatedShapeBuilder via /exec.",
                inputs=[
                    inst,
                    ParamSpec(id="mesh", label="Mesh", type="any",
                              default=None, required=True,
                              help="Mesh file path (.obj/.stl/.ply/.gltf/"
                                   ".glb) or an upstream geometry dict "
                                   "carrying a path/file/url."),
                    ParamSpec(id="name", label="Name", type="text",
                              default="",
                              help="Name for the created DirectShape."),
                    ParamSpec(id="layer", label="Layer", type="text",
                              default="",
                              help="Workset / sub-category hint (optional)."),
                    ParamSpec(id="unit", label="Mesh unit", type="choice",
                              default="m",
                              options=["m", "mm", "cm", "ft", "in"],
                              help="Authoring unit of the mesh file's "
                                   "coordinates (OBJ/STL/PLY are unitless; "
                                   "glTF/GLB are metres by spec). Scaled to "
                                   "Revit feet. Default metres."),
                ],
                output_type="any", destructive=True,
                fn=_import_mesh,
            ),
            # ── M2-Python (AgDR-0017) — Revit ↔ Speckle ────────
            # NB: send_to_speckle is kind="read" because it does
            # NOT mutate Revit state — it ships an upstream value
            # through SpeckleWire. The connector-op `kind`
            # describes the op's effect on the HOST. receive does
            # create native Revit elements → kind="action",
            # destructive=True.
            ConnectorOp(
                op_id="revit.send_to_speckle", host="revit",
                kind="read",
                label="Send to Speckle",
                description="Wrap upstream value + write through "
                            "SpeckleWire. Optional push to a "
                            "Speckle Server. Does not mutate Revit.",
                inputs=[
                    inst,
                    ParamSpec(id="value", label="Value", type="any",
                              default=None,
                              help="The upstream value to send. List, "
                                   "dict or scalar — shape preserved."),
                    ParamSpec(id="model_name", label="Model name",
                              type="text", default="revit",
                              help="The model name stamped on the "
                                   "Speckle commit."),
                    ParamSpec(id="server_push", label="Push to server",
                              type="boolean", default=False,
                              help="If true, also push to the configured "
                                   "Speckle Server."),
                    ParamSpec(id="server_url", label="Server URL",
                              type="text", default="",
                              help="Speckle Server URL "
                                   "(http://localhost:3000 for local)."),
                ],
                output_type="any", destructive=False,
                fn=_send_to_speckle_op,
            ),
            ConnectorOp(
                op_id="revit.receive_from_speckle", host="revit",
                kind="action",
                label="Receive from Speckle",
                description="Pull a Speckle model + create native "
                            "Revit elements per ADAPTER annotations "
                            "(Walls / DirectShapes / FamilyInstances / "
                            "Beams / DetailLines).",
                inputs=[
                    inst,
                    ParamSpec(id="source_url", label="Source URL",
                              type="text", default="",
                              required=True,
                              help="speckle://local/<hash> or a remote "
                                   "Speckle model URL."),
                ],
                output_type="any", destructive=True,
                fn=_receive_from_speckle_op,
            ),
            # ── AgDR-0018 batch-2: parameter batch update ──────
            ConnectorOp(
                op_id="revit.batch_set_parameters", host="revit",
                kind="action",
                label="Batch set parameters",
                description="For each {revit_element_id, "
                            "revit_parameters} dict pulled from a "
                            "Speckle commit, push the parameters "
                            "onto the existing element.",
                inputs=[
                    inst,
                    ParamSpec(id="source_url", label="Source URL",
                              type="text", default="",
                              required=True,
                              help="speckle://local/<hash> from "
                                   "adapter.excel_to_revit_params + "
                                   "share.publish chain."),
                ],
                output_type="any", destructive=True,
                fn=_batch_set_parameters_op,
            ),
        ]


register(RevitConnector())
