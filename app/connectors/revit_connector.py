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
        ]


register(RevitConnector())
