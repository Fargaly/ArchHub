"""Reach a running Revit, or say honestly that none is there.

This is the narrow admitted bridge for one host. It knows two things: how
to find the Revit sessions that are actually listening, and how to ask one
of them a question. It holds no catalogue -- what may be asked is declared
in the graph -- and it performs no signing, because deciding that an
effect is permitted is not the same job as carrying it out.

Every session Revit opens raises its own listener on its own port, so a
machine with four models open is four hosts, not one. Discovery is a scan
of the published range rather than a remembered port: a port remembered
from last time is a port that belongs to whatever is listening now.

The listener answers on `localhost` and refuses `127.0.0.1` outright --
its URL reservation is registered for the name, and the kernel rejects
the address before the add-in ever sees it.
"""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Mapping

BROKER_PORTS = range(48884, 48900)
BROKER_HOST = "localhost"
_CONNECT_TIMEOUT = 0.15
_PING_TIMEOUT = 2.0
_READ_TIMEOUT = 30.0


class RevitUnreachable(RuntimeError):
    """No Revit session answered, and that is a fact worth recording."""


def _call(port: int, route: str, body: Mapping[str, object] | None = None,
          timeout: float = _READ_TIMEOUT) -> dict:
    url = "http://%s:%d%s" % (BROKER_HOST, port, route)
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, method="POST" if data else "GET",
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def live_sessions() -> list[dict]:
    """Every Revit session listening right now, newest port last."""
    found: list[dict] = []
    for port in BROKER_PORTS:
        # Ask the socket before asking HTTP. A closed port answers a TCP
        # connect immediately; an HTTP request to one waits out its own
        # timeout first, and sixteen of those turned a one-second read of a
        # live model into a fifty-second one -- all of it spent on ports
        # where nothing was listening.
        probe = socket.socket()
        probe.settimeout(_CONNECT_TIMEOUT)
        try:
            listening = probe.connect_ex((BROKER_HOST, port)) == 0
        except OSError:
            listening = False
        finally:
            probe.close()
        if not listening:
            continue
        try:
            answer = _call(port, "/ping", timeout=_PING_TIMEOUT)
        except (urllib.error.URLError, OSError, ValueError, TimeoutError):
            continue
        if answer.get("status") != "ok":
            continue
        # What a session can be asked about is which document it holds, so
        # discovery reports that rather than leaving every caller to ask
        # again and choose blindly.
        try:
            info = _call(port, "/info", timeout=_PING_TIMEOUT)
        except (urllib.error.URLError, OSError, ValueError, TimeoutError):
            info = {"status": "error"}
        document = info.get("document") if info.get("status") == "ok" else None
        if document is None and info.get("status") == "ok":
            document = info.get("title") or info.get("doc") or info
        found.append({
            "port": port,
            "pid": answer.get("pid"),
            "revit_version": answer.get("revit_version"),
            "service_version": answer.get("version"),
            "document": document,
        })
    return found


def _session_for(instance: object, sessions: list[dict]) -> dict:
    """The session the caller asked for, or the most recent one.

    Naming a session that is not open is refused rather than silently
    answered by a different model: a read that quietly changes which
    building it describes is worse than a read that fails.
    """
    # The AutoCAD broker lives in the same port range and also reports a
    # document; a Revit read sent there dies in its compiler. Only a
    # session that names its Revit version is a Revit session.
    sessions = [s for s in sessions if s.get("revit_version")]
    if not sessions:
        raise RevitUnreachable(
            "no Revit session is listening on ports %d-%d"
            % (BROKER_PORTS.start, BROKER_PORTS.stop - 1)
        )
    wanted = str(instance or "").strip()
    if not wanted:
        # A session with no model open is a Revit that is running and has
        # nothing to answer about. Picking the newest one regardless meant
        # a machine with four models open could still report that there is
        # no document, so the newest session HOLDING a document wins.
        for session in reversed(sessions):
            if session.get("document"):
                return session
        raise RevitUnreachable(
            "%d Revit session(s) are running and none has a document open"
            % len(sessions)
        )
    for session in sessions:
        if wanted in (str(session["pid"]), str(session["port"])):
            return session
    raise RevitUnreachable(
        "no Revit session matches %r; open sessions are %s"
        % (wanted, ", ".join(str(s["pid"]) for s in sessions))
    )


# The C# each read runs inside Revit. The listener exposes no resource
# routes, so a read is a script that collects elements and leaves a
# JSON-serialisable value in ctx.result. Held here per declared operation
# so that what ArchHub runs inside a live model is readable, in full,
# without opening a DLL.
_READS: dict[str, str] = {
    "revit.list_doors": """
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
""",
    "revit.list_families": """
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
""",
    "revit.list_levels": """
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
""",
    "revit.list_rooms": """
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
""",
    "revit.get_selection": """
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
""",
    "revit.list_sheets": """
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
""",
    "revit.list_views": """
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
""",
    "revit.list_walls": """
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
""",
    "revit.list_warnings": """
var rows = new List<Dictionary<string,object>>();
foreach (var w in Doc.GetWarnings()) {
    rows.Add(new Dictionary<string,object>{
        {"description", w.GetDescriptionText()},
        {"severity", w.GetSeverity().ToString()},
        {"element_count", w.GetFailingElements().Count}
    });
}
result = rows;
""",
    "revit.list_windows": """
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
""",
    # Model-audit reads. Every one below was run against a live
    # workshared model before it was written down, because a read that
    # has never met a real project is a guess with a name on it.
    'revit.list_schedules': """
var rows = new List<Dictionary<string,object>>();
foreach (ViewSchedule v in new FilteredElementCollector(Doc).OfClass(typeof(ViewSchedule))) {
    if (v.IsTemplate) continue;
    rows.Add(new Dictionary<string,object>{
        {"id", v.Id.IntegerValue},
        {"name", v.Name},
        {"is_revision_schedule", v.IsTitleblockRevisionSchedule}
    });
}
result = rows;
""",
    'revit.list_revisions': """
var rows = new List<Dictionary<string,object>>();
foreach (var e in new FilteredElementCollector(Doc).OfCategory(BuiltInCategory.OST_Revisions)) {
    var r = e as Revision;
    if (r == null) continue;
    rows.Add(new Dictionary<string,object>{
        {"id", r.Id.IntegerValue},
        {"sequence", r.SequenceNumber},
        {"description", r.Description ?? ""},
        {"date", r.RevisionDate ?? ""},
        {"issued", r.Issued},
        {"issued_by", r.IssuedBy ?? ""},
        {"issued_to", r.IssuedTo ?? ""}
    });
}
result = rows;
""",
    'revit.list_grids': """
var rows = new List<Dictionary<string,object>>();
foreach (Grid g in new FilteredElementCollector(Doc).OfClass(typeof(Grid))) {
    rows.Add(new Dictionary<string,object>{ {"id", g.Id.IntegerValue}, {"name", g.Name} });
}
result = rows;
""",
    'revit.list_worksets': """
var rows = new List<Dictionary<string,object>>();
foreach (Workset w in new FilteredWorksetCollector(Doc).OfKind(WorksetKind.UserWorkset)) {
    rows.Add(new Dictionary<string,object>{
        {"id", w.Id.IntegerValue},
        {"name", w.Name},
        {"open", w.IsOpen},
        {"editable", w.IsEditable},
        {"owner", w.Owner ?? ""}
    });
}
result = rows;
""",
    'revit.list_links': """
var rows = new List<Dictionary<string,object>>();
foreach (RevitLinkType t in new FilteredElementCollector(Doc).OfClass(typeof(RevitLinkType))) {
    string status = "";
    try { status = t.GetLinkedFileStatus().ToString(); } catch {}
    rows.Add(new Dictionary<string,object>{
        {"id", t.Id.IntegerValue},
        {"name", t.Name},
        {"status", status},
        {"nested", t.IsNestedLink}
    });
}
result = rows;
""",
    'revit.list_cad_imports': """
var rows = new List<Dictionary<string,object>>();
foreach (CADLinkType t in new FilteredElementCollector(Doc).OfClass(typeof(CADLinkType))) {
    rows.Add(new Dictionary<string,object>{
        {"id", t.Id.IntegerValue},
        {"name", t.Name},
        {"linked", t.IsExternalFileReference()}
    });
}
foreach (ImportInstance i in new FilteredElementCollector(Doc).OfClass(typeof(ImportInstance))) {
    rows.Add(new Dictionary<string,object>{
        {"id", i.Id.IntegerValue},
        {"name", i.Category != null ? i.Category.Name : "(import)"},
        {"linked", i.IsLinked}
    });
}
result = rows;
""",
    'revit.list_view_templates': """
var rows = new List<Dictionary<string,object>>();
foreach (View v in new FilteredElementCollector(Doc).OfClass(typeof(View))) {
    if (!v.IsTemplate) continue;
    rows.Add(new Dictionary<string,object>{
        {"id", v.Id.IntegerValue},
        {"name", v.Name},
        {"view_type", v.ViewType.ToString()}
    });
}
result = rows;
""",
    'revit.list_phases': """
var rows = new List<Dictionary<string,object>>();
foreach (Phase p in Doc.Phases) {
    rows.Add(new Dictionary<string,object>{ {"id", p.Id.IntegerValue}, {"name", p.Name} });
}
result = rows;
""",
    'revit.list_design_options': """
var rows = new List<Dictionary<string,object>>();
foreach (DesignOption o in new FilteredElementCollector(Doc).OfClass(typeof(DesignOption))) {
    string setName = "";
    try {
        var sp = o.get_Parameter(BuiltInParameter.OPTION_SET_ID);
        if (sp != null) { var s = Doc.GetElement(sp.AsElementId()); if (s != null) setName = s.Name; }
    } catch {}
    rows.Add(new Dictionary<string,object>{
        {"id", o.Id.IntegerValue},
        {"name", o.Name},
        {"option_set", setName},
        {"primary", o.IsPrimary}
    });
}
result = rows;
""",
    'revit.list_groups': """
var rows = new List<Dictionary<string,object>>();
foreach (Group g in new FilteredElementCollector(Doc).OfClass(typeof(Group))) {
    rows.Add(new Dictionary<string,object>{
        {"id", g.Id.IntegerValue},
        {"name", g.Name},
        {"members", g.GetMemberIds().Count}
    });
}
result = rows;
""",
    'revit.list_in_place_families': """
var rows = new List<Dictionary<string,object>>();
foreach (Family f in new FilteredElementCollector(Doc).OfClass(typeof(Family))) {
    if (!f.IsInPlace) continue;
    rows.Add(new Dictionary<string,object>{
        {"id", f.Id.IntegerValue},
        {"name", f.Name},
        {"category", f.FamilyCategory != null ? f.FamilyCategory.Name : ""}
    });
}
result = rows;
""",
    'revit.list_titleblocks': """
var col = new FilteredElementCollector(Doc)
    .OfCategory(BuiltInCategory.OST_TitleBlocks).WhereElementIsElementType();
var rows = new List<Dictionary<string,object>>();
foreach (var e in col) {
    var s = e as FamilySymbol;
    rows.Add(new Dictionary<string,object>{
        {"id", e.Id.IntegerValue},
        {"name", e.Name},
        {"family", (s != null && s.Family != null) ? s.Family.Name : ""}
    });
}
result = rows;
""",
    'revit.list_materials': """
var rows = new List<Dictionary<string,object>>();
foreach (Material m in new FilteredElementCollector(Doc).OfClass(typeof(Material))) {
    rows.Add(new Dictionary<string,object>{
        {"id", m.Id.IntegerValue},
        {"name", m.Name},
        {"material_class", m.MaterialClass ?? ""}
    });
}
result = rows;
""",
    'revit.list_project_parameters': """
var rows = new List<Dictionary<string,object>>();
var it = Doc.ParameterBindings.ForwardIterator();
while (it.MoveNext()) {
    var def = it.Key as Definition;
    if (def == null) continue;
    var b = it.Current as ElementBinding;
    bool instance = (it.Current is InstanceBinding);
    int cats = 0;
    if (b != null && b.Categories != null) { foreach (Category c in b.Categories) { cats++; } }
    rows.Add(new Dictionary<string,object>{
        {"name", def.Name},
        {"binding", instance ? "instance" : "type"},
        {"categories", cats}
    });
}
result = rows;
""",
    'revit.list_views_not_on_sheet': """
var placed = new HashSet<int>();
foreach (var vp in new FilteredElementCollector(Doc).OfClass(typeof(Viewport))) {
    var v = vp as Viewport;
    if (v != null) placed.Add(v.ViewId.IntegerValue);
}
var rows = new List<Dictionary<string,object>>();
foreach (View v in new FilteredElementCollector(Doc).OfClass(typeof(View))) {
    if (v.IsTemplate) continue;
    if (v.ViewType == ViewType.DrawingSheet) continue;
    if (v.ViewType == ViewType.ProjectBrowser) continue;
    if (v.ViewType == ViewType.SystemBrowser) continue;
    if (placed.Contains(v.Id.IntegerValue)) continue;
    rows.Add(new Dictionary<string,object>{
        {"id", v.Id.IntegerValue},
        {"name", v.Name},
        {"view_type", v.ViewType.ToString()}
    });
}
result = rows;
""",
    'revit.list_rooms_unplaced': """
var col = new FilteredElementCollector(Doc)
    .OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType();
var rows = new List<Dictionary<string,object>>();
foreach (var e in col) {
    var r = e as SpatialElement;
    double area = 0;
    try { var ap = e.get_Parameter(BuiltInParameter.ROOM_AREA);
          if (ap != null) area = ap.AsDouble(); } catch {}
    bool unplaced = (r == null || r.Location == null || area <= 0);
    if (!unplaced) continue;
    string num = "";
    try { var np = e.get_Parameter(BuiltInParameter.ROOM_NUMBER);
          if (np != null) num = np.AsString() ?? ""; } catch {}
    rows.Add(new Dictionary<string,object>{
        {"id", e.Id.IntegerValue},
        {"name", e.Name},
        {"number", num},
        {"reason", (r != null && r.Location == null) ? "not placed" : "zero area"}
    });
}
result = rows;
""",
    'revit.count_by_category': """
var tally = new Dictionary<string,int>();
foreach (var e in new FilteredElementCollector(Doc).WhereElementIsNotElementType()) {
    string name = (e.Category != null) ? e.Category.Name : "(no category)";
    if (!tally.ContainsKey(name)) tally[name] = 0;
    tally[name] = tally[name] + 1;
}
var rows = new List<Dictionary<string,object>>();
foreach (var kv in tally) {
    rows.Add(new Dictionary<string,object>{ {"category", kv.Key}, {"count", kv.Value} });
}
result = rows;
""",
    'revit.list_text_notes': """
var rows = new List<Dictionary<string,object>>();
foreach (TextNote t in new FilteredElementCollector(Doc).OfClass(typeof(TextNote))) {
    string owner = "";
    try { var v = Doc.GetElement(t.OwnerViewId); if (v != null) owner = v.Name; } catch {}
    string body = t.Text ?? "";
    if (body.Length > 120) body = body.Substring(0, 120);
    rows.Add(new Dictionary<string,object>{
        {"id", t.Id.IntegerValue},
        {"view", owner},
        {"text", body.Replace((char)13, (char)32).Replace((char)10, (char)32)}
    });
}
result = rows;
""",
    'revit.list_floors': """
var col = new FilteredElementCollector(Doc)
    .OfCategory(BuiltInCategory.OST_Floors).WhereElementIsNotElementType();
var rows = new List<Dictionary<string,object>>();
foreach (var e in col) {
    double area = 0;
    try { var p = e.get_Parameter(BuiltInParameter.HOST_AREA_COMPUTED);
          if (p != null) area = p.AsDouble(); } catch {}
    rows.Add(new Dictionary<string,object>{
        {"id", e.Id.IntegerValue},
        {"type", e.Name},
        {"level", (e.LevelId != null && Doc.GetElement(e.LevelId) != null)
                  ? Doc.GetElement(e.LevelId).Name : ""},
        {"area", area}
    });
}
result = rows;
""",
    'revit.list_ceilings': """
var col = new FilteredElementCollector(Doc)
    .OfCategory(BuiltInCategory.OST_Ceilings).WhereElementIsNotElementType();
var rows = new List<Dictionary<string,object>>();
foreach (var e in col) {
    rows.Add(new Dictionary<string,object>{
        {"id", e.Id.IntegerValue},
        {"type", e.Name},
        {"level", (e.LevelId != null && Doc.GetElement(e.LevelId) != null)
                  ? Doc.GetElement(e.LevelId).Name : ""}
    });
}
result = rows;
""",
    'revit.list_roofs': """
var col = new FilteredElementCollector(Doc)
    .OfCategory(BuiltInCategory.OST_Roofs).WhereElementIsNotElementType();
var rows = new List<Dictionary<string,object>>();
foreach (var e in col) {
    rows.Add(new Dictionary<string,object>{
        {"id", e.Id.IntegerValue},
        {"type", e.Name},
        {"level", (e.LevelId != null && Doc.GetElement(e.LevelId) != null)
                  ? Doc.GetElement(e.LevelId).Name : ""}
    });
}
result = rows;
""",
    'revit.list_columns': """
var rows = new List<Dictionary<string,object>>();
foreach (var category in new[] { BuiltInCategory.OST_Columns,
                                 BuiltInCategory.OST_StructuralColumns }) {
    foreach (var e in new FilteredElementCollector(Doc)
             .OfCategory(category).WhereElementIsNotElementType()) {
        rows.Add(new Dictionary<string,object>{
            {"id", e.Id.IntegerValue},
            {"type", e.Name},
            {"category", e.Category != null ? e.Category.Name : ""},
            {"level", (e.LevelId != null && Doc.GetElement(e.LevelId) != null)
                      ? Doc.GetElement(e.LevelId).Name : ""}
        });
    }
}
result = rows;
""",
    'revit.list_stairs': """
var col = new FilteredElementCollector(Doc)
    .OfCategory(BuiltInCategory.OST_Stairs).WhereElementIsNotElementType();
var rows = new List<Dictionary<string,object>>();
foreach (var e in col) {
    rows.Add(new Dictionary<string,object>{
        {"id", e.Id.IntegerValue},
        {"type", e.Name},
        {"level", (e.LevelId != null && Doc.GetElement(e.LevelId) != null)
                  ? Doc.GetElement(e.LevelId).Name : ""}
    });
}
result = rows;
""",
    'revit.list_railings': """
var col = new FilteredElementCollector(Doc)
    .OfCategory(BuiltInCategory.OST_StairsRailing).WhereElementIsNotElementType();
var rows = new List<Dictionary<string,object>>();
foreach (var e in col) {
    rows.Add(new Dictionary<string,object>{
        {"id", e.Id.IntegerValue},
        {"type", e.Name},
        {"level", (e.LevelId != null && Doc.GetElement(e.LevelId) != null)
                  ? Doc.GetElement(e.LevelId).Name : ""}
    });
}
result = rows;
""",
    'revit.list_curtain_walls': """
var rows = new List<Dictionary<string,object>>();
foreach (var e in new FilteredElementCollector(Doc)
         .OfCategory(BuiltInCategory.OST_Walls).WhereElementIsNotElementType()) {
    var wall = e as Wall;
    if (wall == null || wall.WallType == null) continue;
    if (wall.WallType.Kind != WallKind.Curtain) continue;
    rows.Add(new Dictionary<string,object>{
        {"id", e.Id.IntegerValue},
        {"type", wall.WallType.Name},
        {"level", (e.LevelId != null && Doc.GetElement(e.LevelId) != null)
                  ? Doc.GetElement(e.LevelId).Name : ""}
    });
}
result = rows;
""",
    'revit.list_wall_types': """
var rows = new List<Dictionary<string,object>>();
foreach (WallType t in new FilteredElementCollector(Doc).OfClass(typeof(WallType))) {
    double width = 0;
    try { width = t.Width; } catch {}
    rows.Add(new Dictionary<string,object>{
        {"id", t.Id.IntegerValue},
        {"name", t.Name},
        {"kind", t.Kind.ToString()},
        {"width", width}
    });
}
result = rows;
""",
    'revit.list_areas': """
var col = new FilteredElementCollector(Doc)
    .OfCategory(BuiltInCategory.OST_Areas).WhereElementIsNotElementType();
var rows = new List<Dictionary<string,object>>();
foreach (var e in col) {
    double area = 0;
    try { var p = e.get_Parameter(BuiltInParameter.ROOM_AREA);
          if (p != null) area = p.AsDouble(); } catch {}
    string scheme = "";
    try {
        var a = e as Area;
        if (a != null && a.AreaScheme != null) scheme = a.AreaScheme.Name;
    } catch {}
    rows.Add(new Dictionary<string,object>{
        {"id", e.Id.IntegerValue},
        {"name", e.Name},
        {"scheme", scheme},
        {"area", area}
    });
}
result = rows;
""",
    'revit.list_line_styles': """
var rows = new List<Dictionary<string,object>>();
var lines = Doc.Settings.Categories.get_Item(BuiltInCategory.OST_Lines);
if (lines != null) {
    foreach (Category c in lines.SubCategories) {
        rows.Add(new Dictionary<string,object>{
            {"id", c.Id.IntegerValue},
            {"name", c.Name},
            {"line_weight", c.GetLineWeight(GraphicsStyleType.Projection) ?? 0}
        });
    }
}
result = rows;
""",
    'revit.list_sheet_revisions': """
var rows = new List<Dictionary<string,object>>();
foreach (ViewSheet s in new FilteredElementCollector(Doc).OfClass(typeof(ViewSheet))) {
    if (s.IsTemplate) continue;
    var ids = s.GetAllRevisionIds();
    var names = new List<string>();
    foreach (var id in ids) {
        var r = Doc.GetElement(id) as Revision;
        if (r != null) names.Add(r.SequenceNumber + ":" + (r.Description ?? ""));
    }
    rows.Add(new Dictionary<string,object>{
        {"sheet", s.SheetNumber},
        {"name", s.Name},
        {"revision_count", ids.Count},
        {"revisions", string.Join(" | ", names)}
    });
}
result = rows;
""",
    'revit.list_view_filters': """
var rows = new List<Dictionary<string,object>>();
foreach (ParameterFilterElement f in new FilteredElementCollector(Doc)
         .OfClass(typeof(ParameterFilterElement))) {
    int categories = 0;
    try { foreach (var c in f.GetCategories()) { categories++; } } catch {}
    rows.Add(new Dictionary<string,object>{
        {"id", f.Id.IntegerValue},
        {"name", f.Name},
        {"categories", categories}
    });
}
result = rows;
""",
    'revit.list_scope_boxes': """
var col = new FilteredElementCollector(Doc)
    .OfCategory(BuiltInCategory.OST_VolumeOfInterest).WhereElementIsNotElementType();
var rows = new List<Dictionary<string,object>>();
foreach (var e in col) {
    rows.Add(new Dictionary<string,object>{ {"id", e.Id.IntegerValue}, {"name", e.Name} });
}
result = rows;
""",
    'revit.list_reference_planes': """
var rows = new List<Dictionary<string,object>>();
foreach (ReferencePlane p in new FilteredElementCollector(Doc)
         .OfClass(typeof(ReferencePlane))) {
    string owner = "";
    try { var v = Doc.GetElement(p.OwnerViewId); if (v != null) owner = v.Name; } catch {}
    rows.Add(new Dictionary<string,object>{
        {"id", p.Id.IntegerValue},
        {"name", p.Name},
        {"view", owner}
    });
}
result = rows;
""",
    'revit.list_door_types': """
var col = new FilteredElementCollector(Doc)
    .OfCategory(BuiltInCategory.OST_Doors).WhereElementIsElementType();
var rows = new List<Dictionary<string,object>>();
foreach (var e in col) {
    var s = e as FamilySymbol;
    rows.Add(new Dictionary<string,object>{
        {"id", e.Id.IntegerValue},
        {"type", e.Name},
        {"family", (s != null && s.Family != null) ? s.Family.Name : ""}
    });
}
result = rows;
""",
    'revit.list_window_types': """
var col = new FilteredElementCollector(Doc)
    .OfCategory(BuiltInCategory.OST_Windows).WhereElementIsElementType();
var rows = new List<Dictionary<string,object>>();
foreach (var e in col) {
    var s = e as FamilySymbol;
    rows.Add(new Dictionary<string,object>{
        {"id", e.Id.IntegerValue},
        {"type", e.Name},
        {"family", (s != null && s.Family != null) ? s.Family.Name : ""}
    });
}
result = rows;
""",
    'revit.list_generic_models': """
var col = new FilteredElementCollector(Doc)
    .OfCategory(BuiltInCategory.OST_GenericModel).WhereElementIsNotElementType();
var rows = new List<Dictionary<string,object>>();
foreach (var e in col) {
    rows.Add(new Dictionary<string,object>{
        {"id", e.Id.IntegerValue},
        {"type", e.Name},
        {"level", (e.LevelId != null && Doc.GetElement(e.LevelId) != null)
                  ? Doc.GetElement(e.LevelId).Name : ""}
    });
}
result = rows;
""",
    'revit.list_furniture': """
var rows = new List<Dictionary<string,object>>();
foreach (var category in new[] { BuiltInCategory.OST_Furniture,
                                 BuiltInCategory.OST_Casework,
                                 BuiltInCategory.OST_SpecialityEquipment }) {
    foreach (var e in new FilteredElementCollector(Doc)
             .OfCategory(category).WhereElementIsNotElementType()) {
        rows.Add(new Dictionary<string,object>{
            {"id", e.Id.IntegerValue},
            {"type", e.Name},
            {"category", e.Category != null ? e.Category.Name : ""}
        });
    }
}
result = rows;
""",
    'revit.list_dimensions': """
var rows = new List<Dictionary<string,object>>();
foreach (Dimension d in new FilteredElementCollector(Doc).OfClass(typeof(Dimension))) {
    string owner = "";
    try { var v = Doc.GetElement(d.OwnerViewId); if (v != null) owner = v.Name; } catch {}
    string over = "";
    try { over = d.ValueOverride ?? ""; } catch {}
    rows.Add(new Dictionary<string,object>{
        {"id", d.Id.IntegerValue},
        {"view", owner},
        {"type", d.Name},
        {"overridden", over.Length > 0}
    });
}
result = rows;
""",
    'revit.list_legends': """
var rows = new List<Dictionary<string,object>>();
foreach (View v in new FilteredElementCollector(Doc).OfClass(typeof(View))) {
    if (v.IsTemplate) continue;
    if (v.ViewType != ViewType.Legend) continue;
    rows.Add(new Dictionary<string,object>{ {"id", v.Id.IntegerValue}, {"name", v.Name} });
}
result = rows;
""",
}

def invoke(op_id: str, arguments: Mapping[str, object]) -> dict:
    """Carry out one declared Revit operation against a live session."""
    sessions = live_sessions()
    script = _READS.get(op_id)
    if script is None:
        raise RevitUnreachable(
            "this adapter does not yet carry out %s" % op_id
        )
    session = _session_for(arguments.get("instance"), sessions)
    answer = _call(
        session["port"], "/exec",
        {"code": script, "transaction_name": "ArchHub read"},
    )
    if answer.get("status") != "ok":
        raise RevitUnreachable(
            "Revit refused %s: %s" % (op_id, answer.get("error"))
        )
    return {
        "port": session["port"],
        "pid": session["pid"],
        "revit_version": session["revit_version"],
        "result": answer.get("result"),
    }


__all__ = ["BROKER_PORTS", "RevitUnreachable", "invoke", "live_sessions"]
