"""Discover Revit sessions and use the one signed broker, without a model cache.

Use localhost: the listener's URL reservation rejects 127.0.0.1.
Each session owns its port. Capabilities and approval belong to the graph.
"""
from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from pathlib import Path
from typing import Mapping

BROKER_PORTS = range(48884, 48900)
BROKER_HOST = "localhost"
_CONNECT_TIMEOUT = 0.15
_PING_TIMEOUT = 2.0
_READ_TIMEOUT = 30.0
_REVIT_WRITE_OPS = {
    "revit.set_parameter_by_name",
    "revit.create_sheets",
    "revit.renumber_rename",
}


class RevitUnreachable(RuntimeError):
    """No Revit session answered, and that is a fact worth recording."""


# Said wherever Revit is offered on a machine that cannot connect it. The
# add-in (bridges/sources/revit_mcp*) now refuses every caller without this
# install's bridge secret (host_bridge_auth.py). Setup registers it per Revit
# year only from a release payload whose custody review is recorded
# (host_broker_installation.py); without that no registration exists here.
REVIT_ADDIN_ABSENT = (
    "Revit connects through the ArchHub Revit add-in, which is not registered "
    "for any Revit year on this machine. Setup registers it only when this "
    "build carries a reviewed add-in for that year; then restart Revit."
)


def revit_addin_years() -> list[str]:
    """Revit years whose per-user Addins folder registers the ArchHub add-in."""
    base = Path(os.environ.get("APPDATA", "")) / "Autodesk" / "Revit" / "Addins"
    years = set()
    for manifest in base.glob("*/*.addin"):
        try:
            text = manifest.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        if "RevitMCP.RevitMCPApp" in text:
            years.add(manifest.parent.name)
    return sorted(years)


def _call(port: int, route: str, body: Mapping[str, object] | None = None,
          timeout: float = _READ_TIMEOUT) -> dict:
    # The one authenticated client (host_bridge_auth.bridge_request): every
    # route but /ping is signed per request; /ping is identity only.
    from .host_bridge_auth import bridge_request
    url = "http://%s:%d%s" % (BROKER_HOST, port, route)
    status, answer = bridge_request(url, body, timeout=timeout, sign=route != "/ping")
    if status != 200:
        # A bridge refusal (401 unauthenticated, 403 browser, 503 no secret)
        # carries its reason; callers see it as a status "error".
        answer["status"] = "error"
        answer["http_status"] = status
    return answer


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
            # A title, or nothing. The whole /info dict used to stand in here
            # and carried document_path and username into every status line
            # and onto BABOOM's face (audit 2026-09-06). AutoCAD's /info names
            # its drawing document_name.
            document = (info.get("document_title") or info.get("title") or info.get("doc")
                        or info.get("document_name") or None)
        session = {
            "port": port,
            "pid": answer.get("pid"),
            "revit_version": answer.get("revit_version"),
            "service_version": answer.get("version"),
            "document": document,
        }
        # The AutoCAD broker shares this port range. It names itself on /ping
        # (service "acad-mcp") and its version on /info (acad_version); the
        # title-only document above dropped that dict, so AutoCAD read as
        # absent and was counted as Revit (founder report 2026-09-23).
        service = answer.get("service")
        if isinstance(service, str) and service:
            session["service"] = service
        if service == "acad-mcp" and info.get("status") == "ok" and info.get("acad_version"):
            session["acad_version"] = str(info["acad_version"])
        found.append(session)
    return found


def _session_for(instance: object, sessions: list[dict]) -> dict:
    """Resolve an explicit session, or the single open document.

    Naming a session that is not open is refused rather than silently
    answered by a different model: a read that quietly changes which
    building it describes is worse than a read that fails.
    """
    # The AutoCAD broker lives in the same port range and also reports a
    # document; a Revit read sent there dies in its compiler. Only a
    # session that names its Revit version is a Revit session.
    sessions = [s for s in sessions if s.get("revit_version")]
    if not sessions:
        if not revit_addin_years():
            raise RevitUnreachable(REVIT_ADDIN_ABSENT)
        raise RevitUnreachable(
            "no Revit session is listening on ports %d-%d"
            % (BROKER_PORTS.start, BROKER_PORTS.stop - 1)
        )
    wanted = str(instance or "").strip()
    if not wanted:
        opened = [session for session in sessions if session.get("document")]
        if len(opened) == 1:
            return opened[0]
        if len(opened) > 1:
            raise RevitUnreachable(
                "multiple Revit documents are open; select an explicit session port: %s"
                % ", ".join(str(session["port"]) for session in opened)
            )
        raise RevitUnreachable(
            "%d Revit session(s) are running and none has a document open"
            % len(sessions)
        )
    matches = [session for session in sessions
               if wanted in (str(session["pid"]), str(session["port"]))]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise RevitUnreachable("Revit session identity is ambiguous; select its unique port")
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
        {"id", global::RevitMCPCore.RevitIds.Of(e.Id)},
        {"name", e.Name},
        {"family", (fi!=null && fi.Symbol!=null && fi.Symbol.Family!=null)
                   ? fi.Symbol.Family.Name : ""},
        {"level", (e.LevelId!=null && global::RevitMCPCore.RevitIds.Of(e.LevelId)>0
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
        {"id", global::RevitMCPCore.RevitIds.Of(f.Id)},
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
        {"id", global::RevitMCPCore.RevitIds.Of(lv.Id)},
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
        {"id", global::RevitMCPCore.RevitIds.Of(e.Id)},
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
        {"id", global::RevitMCPCore.RevitIds.Of(id)},
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
        {"id", global::RevitMCPCore.RevitIds.Of(sh.Id)},
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
        {"id", global::RevitMCPCore.RevitIds.Of(v.Id)},
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
        {"id", global::RevitMCPCore.RevitIds.Of(e.Id)},
        {"name", e.Name},
        {"type", (w!=null && w.WallType!=null) ? w.WallType.Name : ""},
        {"length", len},
        {"level", (e.LevelId!=null && global::RevitMCPCore.RevitIds.Of(e.LevelId)>0
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
        {"id", global::RevitMCPCore.RevitIds.Of(e.Id)},
        {"name", e.Name},
        {"family", (fi!=null && fi.Symbol!=null && fi.Symbol.Family!=null)
                   ? fi.Symbol.Family.Name : ""},
        {"level", (e.LevelId!=null && global::RevitMCPCore.RevitIds.Of(e.LevelId)>0
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
        {"id", global::RevitMCPCore.RevitIds.Of(v.Id)},
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
        {"id", global::RevitMCPCore.RevitIds.Of(r.Id)},
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
    rows.Add(new Dictionary<string,object>{ {"id", global::RevitMCPCore.RevitIds.Of(g.Id)}, {"name", g.Name} });
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
        {"id", global::RevitMCPCore.RevitIds.Of(t.Id)},
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
        {"id", global::RevitMCPCore.RevitIds.Of(t.Id)},
        {"name", t.Name},
        {"linked", t.IsExternalFileReference()}
    });
}
foreach (ImportInstance i in new FilteredElementCollector(Doc).OfClass(typeof(ImportInstance))) {
    rows.Add(new Dictionary<string,object>{
        {"id", global::RevitMCPCore.RevitIds.Of(i.Id)},
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
        {"id", global::RevitMCPCore.RevitIds.Of(v.Id)},
        {"name", v.Name},
        {"view_type", v.ViewType.ToString()}
    });
}
result = rows;
""",
    'revit.list_phases': """
var rows = new List<Dictionary<string,object>>();
foreach (Phase p in Doc.Phases) {
    rows.Add(new Dictionary<string,object>{ {"id", global::RevitMCPCore.RevitIds.Of(p.Id)}, {"name", p.Name} });
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
        {"id", global::RevitMCPCore.RevitIds.Of(o.Id)},
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
        {"id", global::RevitMCPCore.RevitIds.Of(g.Id)},
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
        {"id", global::RevitMCPCore.RevitIds.Of(f.Id)},
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
        {"id", global::RevitMCPCore.RevitIds.Of(e.Id)},
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
        {"id", global::RevitMCPCore.RevitIds.Of(m.Id)},
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
var placed = new HashSet<long>();
foreach (var vp in new FilteredElementCollector(Doc).OfClass(typeof(Viewport))) {
    var v = vp as Viewport;
    if (v != null) placed.Add(global::RevitMCPCore.RevitIds.Of(v.ViewId));
}
var rows = new List<Dictionary<string,object>>();
foreach (View v in new FilteredElementCollector(Doc).OfClass(typeof(View))) {
    if (v.IsTemplate) continue;
    if (v.ViewType == ViewType.DrawingSheet) continue;
    if (v.ViewType == ViewType.ProjectBrowser) continue;
    if (v.ViewType == ViewType.SystemBrowser) continue;
    if (placed.Contains(global::RevitMCPCore.RevitIds.Of(v.Id))) continue;
    rows.Add(new Dictionary<string,object>{
        {"id", global::RevitMCPCore.RevitIds.Of(v.Id)},
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
        {"id", global::RevitMCPCore.RevitIds.Of(e.Id)},
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
        {"id", global::RevitMCPCore.RevitIds.Of(t.Id)},
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
        {"id", global::RevitMCPCore.RevitIds.Of(e.Id)},
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
        {"id", global::RevitMCPCore.RevitIds.Of(e.Id)},
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
        {"id", global::RevitMCPCore.RevitIds.Of(e.Id)},
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
            {"id", global::RevitMCPCore.RevitIds.Of(e.Id)},
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
        {"id", global::RevitMCPCore.RevitIds.Of(e.Id)},
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
        {"id", global::RevitMCPCore.RevitIds.Of(e.Id)},
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
        {"id", global::RevitMCPCore.RevitIds.Of(e.Id)},
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
        {"id", global::RevitMCPCore.RevitIds.Of(t.Id)},
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
        {"id", global::RevitMCPCore.RevitIds.Of(e.Id)},
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
            {"id", global::RevitMCPCore.RevitIds.Of(c.Id)},
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
        {"id", global::RevitMCPCore.RevitIds.Of(f.Id)},
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
    rows.Add(new Dictionary<string,object>{ {"id", global::RevitMCPCore.RevitIds.Of(e.Id)}, {"name", e.Name} });
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
        {"id", global::RevitMCPCore.RevitIds.Of(p.Id)},
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
        {"id", global::RevitMCPCore.RevitIds.Of(e.Id)},
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
        {"id", global::RevitMCPCore.RevitIds.Of(e.Id)},
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
        {"id", global::RevitMCPCore.RevitIds.Of(e.Id)},
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
            {"id", global::RevitMCPCore.RevitIds.Of(e.Id)},
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
        {"id", global::RevitMCPCore.RevitIds.Of(d.Id)},
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
    rows.Add(new Dictionary<string,object>{ {"id", global::RevitMCPCore.RevitIds.Of(v.Id)}, {"name", v.Name} });
}
result = rows;
""",
}


def _cs_string(value: object) -> str:
    return json.dumps("" if value is None else str(value))


# ---------------------------------------------------------------------------
# Geometry verbs, folded from bimwright rvt-mcp (Apache-2.0, toolset
# "geometry", src/shared/Handlers/Geometry + Workflows/ClashDetectionHandler,
# upstream 4affa2aaae3f6e7b798d1067ce7e324ad92f0f91). Copyright the bimwright
# authors; licence text in 03.TOOLS/packaging/windows/licenses/
# bimwright-rvt-mcp-Apache-2.0.txt. Modified: re-written as scripts for the
# one signed /exec broker (no second server, no named pipe), metric in and out.
#
# Each script = _GEO_PRELUDE + declarations built from checked arguments (data
# only, every value a C# literal) + a fixed body. Ids go through the one helper
# in the broker Core (RevitMCPCore.RevitIds, compiled per Revit year).
_GEO_PRELUDE = r"""
const double FT = 0.3048;
Func<ElementId,long> idv = global::RevitMCPCore.RevitIds.Of;
Func<long,ElementId> eid = global::RevitMCPCore.RevitIds.Id;
Func<XYZ,double[]> pt = gp => new double[] { Math.Round(gp.X * FT, 4), Math.Round(gp.Y * FT, 4), Math.Round(gp.Z * FT, 4) };
Func<double,double,double,XYZ> xyz = (gx, gy, gz) => new XYZ(gx / FT, gy / FT, gz / FT);
Func<string,ViewDetailLevel> detail = gs => { ViewDetailLevel gd; return Enum.TryParse(gs, true, out gd) ? gd : ViewDetailLevel.Medium; };
Func<Category,string,bool> isCategory = (gcat, gn) => gcat != null && (gcat.Name == gn || ((BuiltInCategory)idv(gcat.Id)).ToString() == gn);
List<Solid> SolidsOf(GeometryElement gge, List<Solid> gacc) {
    if (gge == null) return gacc;
    foreach (GeometryObject go in gge) {
        var gsol = go as Solid;
        if (gsol != null && gsol.Faces.Size > 0) gacc.Add(gsol);
        var ginst = go as GeometryInstance;
        if (ginst != null) SolidsOf(ginst.GetInstanceGeometry(), gacc);
    }
    return gacc;
}
Func<Element,ViewDetailLevel,List<Solid>> solids = (gel, glvl) =>
    SolidsOf(gel.get_Geometry(new Options { DetailLevel = glvl, ComputeReferences = true }), new List<Solid>());
Func<Element,View,BoundingBoxXYZ> box = (gel, gview) => gel.get_BoundingBox(gview);
var missing = new List<long>();
"""


def _ids(arguments: Mapping[str, object], *keys: str) -> list[int]:
    """Element ids from rows ({"id": n}) or plain numbers; anything else is refused."""
    found: list[int] = []
    for key in keys or ("elements", "element_ids"):
        value = arguments.get(key)
        if value in (None, ""):
            continue
        for row in value if isinstance(value, (list, tuple)) else [value]:
            raw = row.get("id") if isinstance(row, Mapping) else row
            if isinstance(raw, bool):
                raise ValueError("element id must be a number, not %r" % (raw,))
            try:
                found.append(int(str(raw).strip()))
            except (TypeError, ValueError):
                raise ValueError("element id must be a number, not %r" % (raw,)) from None
    return found


def _num(arguments: Mapping[str, object], key: str, default: float | None = None) -> float:
    value = arguments.get(key, default)
    if value in (None, ""):
        if default is None:
            raise ValueError("%s is required" % key)
        value = default
    if isinstance(value, bool):
        raise ValueError("%s must be a number" % key)
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise ValueError("%s must be a finite number" % key)
    return number


def _cs_double(value: float) -> str:
    return repr(float(value))  # finite only (_num); "1e-05" is a valid C# double literal


def _cs_strings(values: object) -> str:
    if isinstance(values, str):
        values = [part.strip() for part in values.split(",")]
    items = [_cs_string(v) for v in (values or []) if str(v).strip()]
    return "new string[] { %s }" % ", ".join(items)


def _cs_longs(values: list[int]) -> str:
    return "new long[] { %s }" % ", ".join("%dL" % v for v in values)


def _flag(arguments: Mapping[str, object], key: str, default: bool = False) -> str:
    value = arguments.get(key, default)
    if isinstance(value, str):
        value = value.strip().lower() in ("1", "true", "yes", "on")
    return "true" if bool(value) else "false"


def _choice(arguments: Mapping[str, object], key: str, allowed: tuple[str, ...]) -> str:
    value = str(arguments.get(key) or allowed[0]).strip().lower()
    if value not in allowed:
        raise ValueError("%s must be one of %s" % (key, ", ".join(allowed)))
    return _cs_string(value)


def _view_decl(arguments: Mapping[str, object], key: str = "view_id") -> str:
    ids = _ids(arguments, key)
    return "long viewId = %dL;\nView view = viewId > 0 ? Doc.GetElement(eid(viewId)) as View : null;\n" % (
        ids[0] if ids else -1)


def _geo_bounding_box(a):
    ids = _ids(a)
    if not ids:
        raise ValueError("elements are required")
    return "var ids = %s;\n%sbool withTransform = %s;\n" % (_cs_longs(ids), _view_decl(a), _flag(a, "include_transform")) + r"""
var rows = new List<Dictionary<string,object>>();
foreach (var id in ids) {
    var el = Doc.GetElement(eid(id));
    if (el == null) { missing.Add(id); continue; }
    var bb = box(el, view);
    if (bb == null) { rows.Add(new Dictionary<string,object>{ {"id", id}, {"name", el.Name}, {"bounding_box", null} }); continue; }
    var row = new Dictionary<string,object>{
        {"id", id}, {"name", el.Name},
        {"category", el.Category != null ? el.Category.Name : ""},
        {"min_m", pt(bb.Min)}, {"max_m", pt(bb.Max)},
        {"size_m", new double[] { Math.Round((bb.Max.X - bb.Min.X) * FT, 4), Math.Round((bb.Max.Y - bb.Min.Y) * FT, 4), Math.Round((bb.Max.Z - bb.Min.Z) * FT, 4) }}
    };
    if (withTransform && bb.Transform != null)
        row["transform"] = new Dictionary<string,object>{ {"origin_m", pt(bb.Transform.Origin)},
            {"basis_x", new double[] { bb.Transform.BasisX.X, bb.Transform.BasisX.Y, bb.Transform.BasisX.Z }},
            {"basis_y", new double[] { bb.Transform.BasisY.X, bb.Transform.BasisY.Y, bb.Transform.BasisY.Z }} };
    rows.Add(row);
}
result = new Dictionary<string,object>{ {"elements", rows}, {"missing", missing} };
"""


def _geo_geometry(a):
    ids = _ids(a)
    if not ids:
        raise ValueError("elements are required")
    limit = int(_num(a, "sample_limit", 20))
    if not 0 <= limit <= 500:
        raise ValueError("sample_limit must be 0-500")
    return "var ids = %s;\nvar lvl = detail(%s);\nbool samples = %s;\nint sampleLimit = %d;\n" % (
        _cs_longs(ids), _cs_string(a.get("detail_level") or "Medium"), _flag(a, "include_samples"), limit) + r"""
var rows = new List<Dictionary<string,object>>();
foreach (var id in ids) {
    var el = Doc.GetElement(eid(id));
    if (el == null) { missing.Add(id); continue; }
    var ss = solids(el, lvl);
    int faces = 0, edges = 0; double volume = 0, area = 0;
    var points = new List<double[]>();
    foreach (var s in ss) {
        faces += s.Faces.Size; edges += s.Edges.Size; volume += s.Volume;
        foreach (Face f in s.Faces) area += f.Area;
        if (samples) foreach (Edge e in s.Edges) {
            if (points.Count >= sampleLimit) break;
            points.Add(pt(e.AsCurve().GetEndPoint(0)));
        }
    }
    var row = new Dictionary<string,object>{
        {"id", id}, {"name", el.Name}, {"category", el.Category != null ? el.Category.Name : ""},
        {"solids", ss.Count}, {"faces", faces}, {"edges", edges},
        {"volume_m3", Math.Round(volume * FT * FT * FT, 6)}, {"area_m2", Math.Round(area * FT * FT, 6)}
    };
    var loc = el.Location as LocationPoint;
    if (loc != null) row["location_m"] = pt(loc.Point);
    var lc = el.Location as LocationCurve;
    if (lc != null) { row["start_m"] = pt(lc.Curve.GetEndPoint(0)); row["end_m"] = pt(lc.Curve.GetEndPoint(1)); row["length_m"] = Math.Round(lc.Curve.Length * FT, 4); }
    if (samples) row["samples_m"] = points;
    rows.Add(row);
}
result = new Dictionary<string,object>{ {"elements", rows}, {"missing", missing} };
"""


def _geo_distance(a):
    first, second = _ids(a, "element_id_1"), _ids(a, "element_id_2")
    if len(first) != 1 or len(second) != 1:
        raise ValueError("element_id_1 and element_id_2 each name one element")
    return "long idA = %dL, idB = %dL;\nstring strategy = %s;\n" % (
        first[0], second[0], _choice(a, "strategy", ("bbox", "location"))) + r"""
var ea = Doc.GetElement(eid(idA)); var eb = Doc.GetElement(eid(idB));
if (ea == null || eb == null) throw new Exception("element not found: " + (ea == null ? idA : idB));
Func<Element,XYZ> anchor = el => {
    var lp = el.Location as LocationPoint; if (lp != null) return lp.Point;
    var lc = el.Location as LocationCurve; if (lc != null) return lc.Curve.Evaluate(0.5, true);
    var b = el.get_BoundingBox(null); return b == null ? null : (b.Min + b.Max) / 2;
};
double d; string used = strategy;
var ba = ea.get_BoundingBox(null); var bbx = eb.get_BoundingBox(null);
if (strategy == "bbox" && ba != null && bbx != null) {
    double dx = Math.Max(0, Math.Max(ba.Min.X - bbx.Max.X, bbx.Min.X - ba.Max.X));
    double dy = Math.Max(0, Math.Max(ba.Min.Y - bbx.Max.Y, bbx.Min.Y - ba.Max.Y));
    double dz = Math.Max(0, Math.Max(ba.Min.Z - bbx.Max.Z, bbx.Min.Z - ba.Max.Z));
    d = Math.Sqrt(dx * dx + dy * dy + dz * dz);
} else {
    var pa = anchor(ea); var pb = anchor(eb);
    if (pa == null || pb == null) throw new Exception("an element has no location or bounding box");
    d = pa.DistanceTo(pb); used = "location";
}
result = new Dictionary<string,object>{ {"element_id_1", idA}, {"element_id_2", idB}, {"strategy", used}, {"distance_m", Math.Round(d * FT, 4)} };
"""


def _geo_clash(a):
    max_pairs, max_results = int(_num(a, "max_pairs", 1000)), int(_num(a, "max_results", 100))
    if not (1 <= max_pairs <= 100000 and 1 <= max_results <= 10000):
        raise ValueError("max_pairs 1-100000 and max_results 1-10000")
    cats_a, cats_b = _cs_strings(a.get("categories_a")), _cs_strings(a.get("categories_b"))
    if cats_a.endswith("{  }") or cats_b.endswith("{  }"):
        raise ValueError("categories_a and categories_b are required")
    return "var catsA = %s;\nvar catsB = %s;\n%sstring strategy = %s;\nint maxPairs = %d, maxResults = %d;\n" % (
        cats_a, cats_b, _view_decl(a), _choice(a, "strategy", ("bbox_then_solid", "bbox")),
        max_pairs, max_results) + r"""
Func<string[],List<Element>> pick = names => {
    var col = view != null ? new FilteredElementCollector(Doc, view.Id) : new FilteredElementCollector(Doc);
    return col.WhereElementIsNotElementType().Where(e => names.Any(n => isCategory(e.Category, n))).ToList();
};
var A = pick(catsA); var B = pick(catsB);
var clashes = new List<Dictionary<string,object>>(); int tested = 0; bool truncated = false;
foreach (var ea in A) {
    var ba = ea.get_BoundingBox(null); if (ba == null) continue;
    var filter = new BoundingBoxIntersectsFilter(new Outline(ba.Min, ba.Max));
    foreach (var eb in B) {
        if (idv(eb.Id) == idv(ea.Id)) continue;
        if (catsA.SequenceEqual(catsB) && idv(eb.Id) < idv(ea.Id)) continue;
        if (!filter.PassesFilter(eb)) continue;
        if (++tested > maxPairs) { truncated = true; break; }
        double overlap = -1;
        if (strategy == "bbox_then_solid") {
            overlap = 0;
            foreach (var sa in solids(ea, ViewDetailLevel.Medium)) foreach (var sb in solids(eb, ViewDetailLevel.Medium)) {
                try { var i = BooleanOperationsUtils.ExecuteBooleanOperation(sa, sb, BooleanOperationsType.Intersect); if (i != null) overlap += i.Volume; } catch {}
            }
            if (overlap <= 1e-9) continue;
        }
        clashes.Add(new Dictionary<string,object>{ {"element_a", idv(ea.Id)}, {"category_a", ea.Category.Name},
            {"element_b", idv(eb.Id)}, {"category_b", eb.Category.Name},
            {"overlap_m3", overlap < 0 ? (object)null : Math.Round(overlap * FT * FT * FT, 6)} });
        if (clashes.Count >= maxResults) { truncated = true; break; }
    }
    if (truncated) break;
}
result = new Dictionary<string,object>{ {"strategy", strategy}, {"pairs_tested", Math.Min(tested, maxPairs)}, {"clashes", clashes}, {"truncated", truncated} };
"""


def _geo_raycast(a):
    view_ids = _ids(a, "view3d_id")
    if len(view_ids) != 1:
        raise ValueError("view3d_id names one 3D view")
    coords = [_num(a, k) for k in ("x", "y", "z", "dir_x", "dir_y", "dir_z")]
    if not any(coords[3:]):
        raise ValueError("the direction must not be zero")
    return "long view3dId = %dL;\nvar origin = xyz(%s, %s, %s);\nvar dir = new XYZ(%s, %s, %s).Normalize();\nvar cats = %s;\ndouble maxDistance = %s;\n" % (
        view_ids[0], *(_cs_double(c) for c in coords), _cs_strings(a.get("categories")),
        _cs_double(_num(a, "max_distance", 1000.0))) + r"""
var v3 = Doc.GetElement(eid(view3dId)) as View3D;
if (v3 == null) throw new Exception("view3d_id is not a 3D view");
var ri = new ReferenceIntersector(v3) { FindReferencesInRevitLinks = false };
var hits = ri.Find(origin, dir).Where(h => h.Proximity * FT <= maxDistance).OrderBy(h => h.Proximity);
foreach (var h in hits) {
    var el = Doc.GetElement(h.GetReference().ElementId);
    if (el == null) continue;
    if (cats.Length > 0 && !cats.Any(n => isCategory(el.Category, n))) continue;
    result = new Dictionary<string,object>{ {"hit", true}, {"id", idv(el.Id)}, {"name", el.Name},
        {"category", el.Category != null ? el.Category.Name : ""}, {"distance_m", Math.Round(h.Proximity * FT, 4)},
        {"point_m", pt(h.GetReference().GlobalPoint)} };
    break;
}
if (result == null) result = new Dictionary<string,object>{ {"hit", false} };
"""


def _geo_in_volume(a):
    limit = int(_num(a, "limit", 200))
    if not 1 <= limit <= 10000:
        raise ValueError("limit must be 1-10000")
    rooms = _ids(a, "room_id")
    volume = a.get("volume") or {}
    if rooms:
        bounds = "Outline outline = null;\nlong roomId = %dL;\n" % rooms[0]
    elif isinstance(volume, Mapping) and volume.get("min") and volume.get("max"):
        lo = [float(v) for v in volume["min"]][:3]
        hi = [float(v) for v in volume["max"]][:3]
        if len(lo) != 3 or len(hi) != 3:
            raise ValueError("volume min and max are [x, y, z] in metres")
        bounds = "Outline outline = new Outline(xyz(%s, %s, %s), xyz(%s, %s, %s));\nlong roomId = -1L;\n" % tuple(
            _cs_double(v) for v in (*map(min, lo, hi), *map(max, lo, hi)))
    else:
        raise ValueError("give room_id or volume {min:[x,y,z], max:[x,y,z]} in metres")
    return bounds + "var cats = %s;\n%sstring match = %s;\nint limit = %d;\n" % (
        _cs_strings(a.get("categories")), _view_decl(a), _choice(a, "match", ("intersects", "inside")), limit) + r"""
if (outline == null) {
    var room = Doc.GetElement(eid(roomId));
    var rb = room == null ? null : room.get_BoundingBox(null);
    if (rb == null) throw new Exception("room_id has no bounding box");
    outline = new Outline(rb.Min, rb.Max);
}
ElementFilter f = match == "inside" ? (ElementFilter)new BoundingBoxIsInsideFilter(outline) : new BoundingBoxIntersectsFilter(outline);
var col = view != null ? new FilteredElementCollector(Doc, view.Id) : new FilteredElementCollector(Doc);
var rows = new List<Dictionary<string,object>>(); bool truncated = false;
foreach (var el in col.WhereElementIsNotElementType().WherePasses(f)) {
    if (el.Category == null || (cats.Length > 0 && !cats.Any(n => isCategory(el.Category, n)))) continue;
    if (rows.Count >= limit) { truncated = true; break; }
    rows.Add(new Dictionary<string,object>{ {"id", idv(el.Id)}, {"name", el.Name}, {"category", el.Category.Name} });
}
result = new Dictionary<string,object>{ {"match", match}, {"min_m", pt(outline.MinimumPoint)}, {"max_m", pt(outline.MaximumPoint)}, {"elements", rows}, {"truncated", truncated} };
"""


def _geo_measure(kind: str):
    def build(a):
        ids = _ids(a)
        if not ids:
            raise ValueError("elements are required")
        return "var ids = %s;\nvar lvl = detail(%s);\nbool wantVolume = %s;\n" % (
            _cs_longs(ids), _cs_string(a.get("detail_level") or "Medium"),
            "true" if kind == "volume" else "false") + r"""
var rows = new List<Dictionary<string,object>>(); double total = 0;
foreach (var id in ids) {
    var el = Doc.GetElement(eid(id));
    if (el == null) { missing.Add(id); continue; }
    double v = 0;
    foreach (var s in solids(el, lvl)) {
        if (wantVolume) v += s.Volume;
        else foreach (Face f in s.Faces) v += f.Area;
    }
    v = wantVolume ? v * FT * FT * FT : v * FT * FT;
    total += v;
    rows.Add(new Dictionary<string,object>{ {"id", id}, {"name", el.Name}, {wantVolume ? "volume_m3" : "area_m2", Math.Round(v, 6)} });
}
result = new Dictionary<string,object>{ {"elements", rows}, {wantVolume ? "total_volume_m3" : "total_area_m2", Math.Round(total, 6)}, {"missing", missing} };
"""
    return build


def _geo_project(a):
    ids = _ids(a, "element_id")
    if len(ids) != 1:
        raise ValueError("element_id names one element")
    face = int(_num(a, "face_index", 0))
    if face < 0:
        raise ValueError("face_index must be 0 or more")
    return "long id = %dL;\nvar p = xyz(%s, %s, %s);\nint faceIndex = %d;\nvar lvl = detail(%s);\n" % (
        ids[0], *(_cs_double(_num(a, k)) for k in ("x", "y", "z")), face,
        _cs_string(a.get("detail_level") or "Medium")) + r"""
var el = Doc.GetElement(eid(id));
if (el == null) throw new Exception("element not found: " + id);
var faces = new List<Face>();
foreach (var s in solids(el, lvl)) foreach (Face f in s.Faces) faces.Add(f);
if (faceIndex >= faces.Count) throw new Exception("face_index " + faceIndex + " is beyond the " + faces.Count + " faces");
var r = faces[faceIndex].Project(p);
result = r == null
    ? new Dictionary<string,object>{ {"projected", false}, {"face_count", faces.Count} }
    : new Dictionary<string,object>{ {"projected", true}, {"point_m", pt(r.XYZPoint)}, {"distance_m", Math.Round(r.Distance * FT, 4)},
        {"uv", new double[] { r.UVPoint.U, r.UVPoint.V }}, {"face_count", faces.Count} };
"""


def _geo_overlapping(a):
    category = str(a.get("category") or "").strip()
    if not category:
        raise ValueError("category is required")
    max_pairs, max_results = int(_num(a, "max_pairs", 1000)), int(_num(a, "max_results", 100))
    if not (1 <= max_pairs <= 100000 and 1 <= max_results <= 10000):
        raise ValueError("max_pairs 1-100000 and max_results 1-10000")
    return "string category = %s;\n%sint maxPairs = %d, maxResults = %d;\n" % (
        _cs_string(category), _view_decl(a), max_pairs, max_results) + r"""
var col = view != null ? new FilteredElementCollector(Doc, view.Id) : new FilteredElementCollector(Doc);
var els = col.WhereElementIsNotElementType().Where(e => isCategory(e.Category, category)).ToList();
var pairs = new List<Dictionary<string,object>>(); int tested = 0; bool truncated = false;
for (int i = 0; i < els.Count && !truncated; i++) {
    var bi = els[i].get_BoundingBox(null); if (bi == null) continue;
    for (int j = i + 1; j < els.Count; j++) {
        var bj = els[j].get_BoundingBox(null); if (bj == null) continue;
        if (++tested > maxPairs) { truncated = true; break; }
        double ox = Math.Min(bi.Max.X, bj.Max.X) - Math.Max(bi.Min.X, bj.Min.X);
        double oy = Math.Min(bi.Max.Y, bj.Max.Y) - Math.Max(bi.Min.Y, bj.Min.Y);
        double oz = Math.Min(bi.Max.Z, bj.Max.Z) - Math.Max(bi.Min.Z, bj.Min.Z);
        if (ox <= 0 || oy <= 0 || oz <= 0) continue;
        pairs.Add(new Dictionary<string,object>{ {"element_a", idv(els[i].Id)}, {"element_b", idv(els[j].Id)},
            {"overlap_box_m3", Math.Round(ox * oy * oz * FT * FT * FT, 6)} });
        if (pairs.Count >= maxResults) { truncated = true; break; }
    }
}
result = new Dictionary<string,object>{ {"category", category}, {"elements", els.Count}, {"pairs_tested", Math.Min(tested, maxPairs)}, {"overlaps", pairs}, {"truncated", truncated} };
"""


def _geo_centroid(a):
    ids = _ids(a)
    if not ids:
        raise ValueError("elements are required")
    return "var ids = %s;\nstring strategy = %s;\n" % (
        _cs_longs(ids), _choice(a, "strategy", ("solid_then_bbox", "bbox", "solid"))) + r"""
var rows = new List<Dictionary<string,object>>();
foreach (var id in ids) {
    var el = Doc.GetElement(eid(id));
    if (el == null) { missing.Add(id); continue; }
    XYZ c = null; string used = "";
    if (strategy != "bbox") {
        double vol = 0; XYZ sum = XYZ.Zero;
        foreach (var s in solids(el, ViewDetailLevel.Medium)) {
            if (s.Volume <= 1e-9) continue;
            sum += s.ComputeCentroid() * s.Volume; vol += s.Volume;
        }
        if (vol > 0) { c = sum / vol; used = "solid"; }
    }
    if (c == null && strategy != "solid") {
        var b = el.get_BoundingBox(null);
        if (b != null) { c = (b.Min + b.Max) / 2; used = "bbox"; }
    }
    rows.Add(new Dictionary<string,object>{ {"id", id}, {"name", el.Name}, {"strategy", used}, {"centroid_m", c == null ? null : pt(c)} });
}
result = new Dictionary<string,object>{ {"elements", rows}, {"missing", missing} };
"""


def _geo_complexity(a):
    ids = _ids(a)
    limit = int(_num(a, "limit", 200))
    if not 1 <= limit <= 10000:
        raise ValueError("limit must be 1-10000")
    cats = _cs_strings(a.get("categories"))
    if not ids and cats.endswith("{  }"):
        raise ValueError("give elements or categories")
    return "var ids = %s;\nvar cats = %s;\n%svar lvl = detail(%s);\nint limit = %d;\n" % (
        _cs_longs(ids), cats, _view_decl(a), _cs_string(a.get("detail_level") or "Medium"), limit) + r"""
IEnumerable<Element> pool;
if (ids.Length > 0) pool = ids.Select(i => Doc.GetElement(eid(i))).Where(e => e != null);
else {
    var col = view != null ? new FilteredElementCollector(Doc, view.Id) : new FilteredElementCollector(Doc);
    pool = col.WhereElementIsNotElementType().Where(e => cats.Any(n => isCategory(e.Category, n)));
}
var rows = new List<Dictionary<string,object>>(); bool truncated = false;
foreach (var el in pool) {
    if (rows.Count >= limit) { truncated = true; break; }
    int faces = 0, edges = 0, curved = 0; var ss = solids(el, lvl);
    foreach (var s in ss) {
        faces += s.Faces.Size; edges += s.Edges.Size;
        foreach (Face f in s.Faces) if (!(f is PlanarFace)) curved++;
    }
    string band = faces == 0 ? "none" : faces <= 12 ? "simple" : faces <= 200 ? "moderate" : "complex";
    rows.Add(new Dictionary<string,object>{ {"id", idv(el.Id)}, {"name", el.Name}, {"category", el.Category != null ? el.Category.Name : ""},
        {"solids", ss.Count}, {"faces", faces}, {"curved_faces", curved}, {"edges", edges}, {"complexity", band} });
}
result = new Dictionary<string,object>{ {"elements", rows.OrderByDescending(r => (int)r["faces"]).ToList()}, {"truncated", truncated} };
"""


_GEOMETRY_VERBS = {
    "revit.get_element_bounding_box": _geo_bounding_box,
    "revit.get_element_geometry": _geo_geometry,
    "revit.measure_distance_between_elements": _geo_distance,
    "revit.clash_detection": _geo_clash,
    "revit.raycast_from_point": _geo_raycast,
    "revit.find_elements_in_volume": _geo_in_volume,
    "revit.compute_element_volume": _geo_measure("volume"),
    "revit.compute_element_area": _geo_measure("area"),
    "revit.project_point_onto_face": _geo_project,
    "revit.find_overlapping_elements": _geo_overlapping,
    "revit.get_element_centroid": _geo_centroid,
    "revit.analyze_geometry_complexity": _geo_complexity,
}


def _effect_arguments(arguments: Mapping[str, object]) -> dict:
    return {
        str(key): value for key, value in arguments.items()
        if key not in ("grant", "approval", "permit", "instance", "mods_store")
    }


def _require_write_grant(op_id: str, arguments: Mapping[str, object]) -> Mapping[str, object]:
    from . import nodeslib_v2_engines as nodeslib
    grant = nodeslib._require_grant(
        arguments, operation=op_id, scope="revit.write",
        input_digest=nodeslib._digest_payload(_effect_arguments(arguments)),
    )
    from .domains.selfext import before_write_hooks
    annotations = before_write_hooks(arguments.get("mods_store"), op_id, arguments)
    if annotations:
        grant = dict(grant)
        grant["mods_before_write"] = annotations
    return grant


def _script_for(op_id: str, arguments: Mapping[str, object]) -> str | None:
    if op_id in _GEOMETRY_VERBS:
        return _GEO_PRELUDE + _GEOMETRY_VERBS[op_id](arguments)
    if op_id == "revit.elements_of_category":
        category_name = _cs_string(arguments.get("category"))
        return """
string categoryName = %s;
var rows = new List<Dictionary<string,object>>();
foreach (Category cat in Doc.Settings.Categories) {
    if (cat.Name != categoryName) continue;
    var col = new FilteredElementCollector(Doc).OfCategoryId(cat.Id).WhereElementIsNotElementType();
    foreach (var e in col) {
        rows.Add(new Dictionary<string,object>{
            {"id", global::RevitMCPCore.RevitIds.Of(e.Id)}, {"name", e.Name},
            {"category", e.Category != null ? e.Category.Name : ""}
        });
    }
}
result = rows;
""" % category_name
    if op_id == "revit.get_parameter":
        name = _cs_string(arguments.get("name") or arguments.get("parameter"))
        ids = []
        for row in arguments.get("elements") or []:
            if isinstance(row, Mapping):
                try:
                    ids.append(int(row.get("id")))
                except (TypeError, ValueError):
                    pass
        id_list = ", ".join(str(item) for item in ids)
        return """
string parameterName = %s;
var wanted = new HashSet<int>(new int[] { %s });
var rows = new List<Dictionary<string,object>>();
foreach (int id in wanted) {
    var e = Doc.GetElement(global::RevitMCPCore.RevitIds.Id(id));
    if (e == null) continue;
    var p = e.LookupParameter(parameterName);
    rows.Add(new Dictionary<string,object>{
        {"id", id}, {"name", e.Name}, {"parameter", parameterName},
        {"value", p == null ? null : (object)(p.AsValueString() ?? p.AsString())}
    });
}
result = rows;
""" % (name, id_list)
    if op_id == "revit.set_parameter_by_name":
        name = _cs_string(arguments.get("name") or arguments.get("parameter"))
        value = _cs_string(arguments.get("value"))
        ids = []
        for row in arguments.get("elements") or []:
            if isinstance(row, Mapping):
                try:
                    ids.append(int(row.get("id")))
                except (TypeError, ValueError):
                    pass
        id_list = ", ".join(str(item) for item in ids)
        return """
string parameterName = %s;
string parameterValue = %s;
var wanted = new HashSet<int>(new int[] { %s });
var rows = new List<Dictionary<string,object>>();
foreach (int id in wanted) {
    var e = Doc.GetElement(global::RevitMCPCore.RevitIds.Id(id));
    if (e == null) continue;
    var p = e.LookupParameter(parameterName);
    if (p == null || p.IsReadOnly) continue;
    bool changed = false;
    if (p.StorageType == StorageType.String) changed = p.Set(parameterValue);
    else changed = p.SetValueString(parameterValue);
    rows.Add(new Dictionary<string,object>{ {"id", id}, {"name", e.Name}, {"changed", changed} });
}
result = rows;
""" % (name, value, id_list)
    if op_id == "revit.create_sheets":
        rows = []
        for row in arguments.get("rows") or []:
            if isinstance(row, Mapping):
                rows.append((_cs_string(row.get("number")), _cs_string(row.get("name"))))
        entries = ", ".join("new string[] { %s, %s }" % item for item in rows)
        return """
var rows = new List<Dictionary<string,object>>();
foreach (var pair in new [] { %s }) {
    var sheet = ViewSheet.Create(Doc, ElementId.InvalidElementId);
    if (pair[0].Length > 0) sheet.SheetNumber = pair[0];
    if (pair[1].Length > 0) sheet.Name = pair[1];
    rows.Add(new Dictionary<string,object>{ {"id", global::RevitMCPCore.RevitIds.Of(sheet.Id)}, {"number", sheet.SheetNumber}, {"name", sheet.Name} });
}
result = rows;
""" % entries
    if op_id == "revit.renumber_rename":
        number_pattern = _cs_string(arguments.get("number_pattern") or arguments.get("number_format"))
        name_pattern = _cs_string(arguments.get("name_pattern") or arguments.get("name_format"))
        ids = []
        for row in arguments.get("elements") or []:
            if isinstance(row, Mapping):
                try:
                    ids.append(int(row.get("id")))
                except (TypeError, ValueError):
                    pass
        id_list = ", ".join(str(item) for item in ids)
        return """
string numberPattern = %s;
string namePattern = %s;
var wanted = new int[] { %s };
var rows = new List<Dictionary<string,object>>();
Func<string,int,string> applyIndexFormat = (pattern, number) => {
    if (String.IsNullOrEmpty(pattern)) return "";
    return System.Text.RegularExpressions.Regex.Replace(
        pattern,
        @"\\{index(?::([^}]+))?\\}",
        match => {
            var format = match.Groups[1].Success ? match.Groups[1].Value : "";
            if (format.Length == 0 || format == "d") return number.ToString();
            if (format.Length >= 2 && format.StartsWith("0") && format.EndsWith("d")) {
                int width;
                if (Int32.TryParse(format.Substring(1, format.Length - 2), out width))
                    return number.ToString("D" + width);
            }
            try { return String.Format("{0:" + format + "}", number); }
            catch { return number.ToString(); }
        });
};
for (int index = 0; index < wanted.Length; index++) {
    var e = Doc.GetElement(global::RevitMCPCore.RevitIds.Id(wanted[index]));
    if (e == null) continue;
    string number = applyIndexFormat(numberPattern, index + 1);
    string name = applyIndexFormat(namePattern, index + 1);
    var numberParam = e.LookupParameter("Sheet Number") ?? e.LookupParameter("Number");
    if (number.Length > 0 && numberParam != null && !numberParam.IsReadOnly) numberParam.Set(number);
    if (name.Length > 0) e.Name = name;
    rows.Add(new Dictionary<string,object>{ {"id", global::RevitMCPCore.RevitIds.Of(e.Id)}, {"number", number}, {"name", e.Name} });
}
result = rows;
""" % (number_pattern, name_pattern, id_list)
    return _READS.get(op_id)


def broker_sessions(service: str) -> list[dict]:
    """Live sessions of one broker, each by its own identity.

    Revit is only a session that names its Revit version (as _session_for
    reads it); AutoCAD only one that answers as acad-mcp. MaxMCP and anything
    else in the shared port range is neither, and is never sent their code.
    """
    if service == "revit":
        return [row for row in live_sessions()
                if row.get("revit_version") and row.get("service") in (None, "", "revit-mcp")]
    if service == "acad":
        return [row for row in live_sessions() if row.get("service") == "acad-mcp"]
    raise ValueError("unknown broker service")


def broker_call(service: str, route: str, body: Mapping[str, object] | None = None,
                *, port: int | None = None, timeout: float = _PING_TIMEOUT) -> dict:
    """One signed call to the one live Revit ("revit") or AutoCAD ("acad") broker.

    More than one live session needs ``port``; /open also accepts Home sessions.
    """
    rows = [row for row in broker_sessions(service) if port is None or row["port"] == port]
    name = "AutoCAD" if service == "acad" else "Revit"
    if not rows:
        raise RevitUnreachable("no %s session answers%s. Open %s with the ArchHub add-in loaded, then try again." % (
            name, "" if port is None else " on :%d" % port, name))
    if len(rows) > 1:
        raise RevitUnreachable("%d %s sessions answer (ports %s); name one with port" % (
            len(rows), name, ", ".join(str(row["port"]) for row in rows)))
    answer = _call(rows[0]["port"], route, body, timeout=timeout)
    return {"ok": answer.get("status") == "ok", "port": rows[0]["port"],
            "document": answer.get("title") if route == "/open" else rows[0].get("document"), **answer}


def _execute(session: Mapping[str, object], script: str, transaction: str,
             *, timeout: float | None = None) -> dict:
    """The one script transport; callers retain their admission and result contracts."""
    body = {"code": script, "transaction_name": transaction}
    if timeout is None:
        return _call(session["port"], "/exec", body)
    return _call(session["port"], "/exec", body, timeout=timeout)


_BUILD_WALLS = """
var data = %s;
var levelName = %s;
double heightMm = %s;
Level level = null;
foreach (Level lv in new FilteredElementCollector(Doc).OfClass(typeof(Level)))
    if (level == null || lv.Name == levelName) { if (lv.Name == levelName || level == null) level = lv; }
if (level == null) throw new Exception("no level in the model");
var built = new List<int>();
// The broker (RevitMCPCore.ExecAsync) runs this inside the transaction named
// by transaction_name and commits it; a second Transaction.Start here throws.
foreach (var seg in data) {
    double x1 = seg[0] / 304.8, y1 = seg[1] / 304.8;
    double x2 = seg[2] / 304.8, y2 = seg[3] / 304.8;
    if (Math.Abs(x2-x1) < 1e-6 && Math.Abs(y2-y1) < 1e-6) continue;
    var line = Line.CreateBound(new XYZ(x1, y1, 0), new XYZ(x2, y2, 0));
    var wall = Wall.Create(Doc, line, level.Id, false);
    var hp = wall.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM);
    if (hp != null) hp.Set(heightMm / 304.8);
    built.Add(global::RevitMCPCore.RevitIds.Of(wall.Id));
}
result = built;
"""


def build_walls(params: Mapping[str, object], lines: list):
    """Build one wall per wired line segment inside the live session."""
    if not lines:
        raise ValueError("no lines are wired in; nothing to build")
    sessions = [s for s in live_sessions() if s.get("revit_version")]
    wanted = str(params.get("session") or "").strip()
    if not wanted:
        listed = ", ".join(
            "%s (%s)" % (s["port"], s.get("document") or "no document")
            for s in sessions) or "none listening"
        raise ValueError(
            "set the session parameter to the Revit port to build into"
            " -- live: %s" % listed)
    session = _session_for(wanted, sessions)
    script = _BUILD_WALLS % (
        json.dumps([[float(v) for v in line[:4]] for line in lines]),
        json.dumps(str(params.get("level") or "")),
        json.dumps(float(params.get("height_mm") or 3000.0)),
    )
    answer = _execute(session, script, "ArchHub build walls")
    if answer.get("status") != "ok":
        raise ValueError("Revit refused: %s" % answer.get("error"))
    built = answer.get("result") or []
    return {"out": built}, "built %d walls on %s" % (
        len(built), session.get("document") or session["port"])




def sole_session():
    """The one live Revit session, or (None, why): two sessions means a wrong-model risk."""
    sessions = [s for s in live_sessions() if s.get("revit_version")]
    if not sessions:
        return None, "no Revit session is listening"
    if len(sessions) > 1:
        ports = ", ".join(str(s.get("port")) for s in sessions)
        return None, "%d Revit sessions are open (ports %s); close the others so the act lands in one model" % (len(sessions), ports)
    return sessions[0], ""


def authoring(script: str, transaction: str, params: Mapping[str, object], *, timeout: float = 30.0):
    """One /exec against the one live Revit session; (session, answer) or (None, why)."""
    session, why = sole_session()
    if session is None:
        return None, why
    try:
        answer = _execute(session, script, transaction, timeout=timeout)
    except Exception as failed:
        return None, "Revit did not answer: %s" % str(failed)[:160]
    if not isinstance(answer, Mapping) or answer.get("status") != "ok":
        return None, "Revit refused: %s" % (answer.get("error") if isinstance(answer, Mapping) else answer)
    return session, answer.get("result") if isinstance(answer.get("result"), Mapping) else {}


def invoke(op_id: str, arguments: Mapping[str, object]) -> dict:
    """Carry out one declared Revit operation against a live session."""
    write_grant = _require_write_grant(op_id, arguments) if op_id in _REVIT_WRITE_OPS else None
    # Arguments are checked into the script before any host is asked.
    script = _script_for(op_id, arguments)
    if script is None:
        raise RevitUnreachable(
            "this adapter does not yet carry out %s" % op_id
        )
    sessions = live_sessions()
    session = _session_for(arguments.get("instance"), sessions)
    answer = _execute(session, script, "ArchHub write" if write_grant else "ArchHub read")
    if answer.get("status") != "ok":
        raise RevitUnreachable(
            "Revit refused %s: %s" % (op_id, answer.get("error"))
        )
    result = {
        "port": session["port"],
        "pid": session["pid"],
        "revit_version": session["revit_version"],
        "document": session.get("document"),
        "result": answer.get("result"),
    }
    if write_grant:
        from . import nodeslib_v2_engines as nodeslib
        result["ok"] = True
        result["receipt"] = {
            "operation": op_id,
            "port": session["port"],
            "grant_digest": write_grant.get("digest"),
            "result_digest": nodeslib._digest_payload(answer.get("result")),
        }
        if write_grant.get("mods_before_write"):
            # Project the already-fired hook into the accepted count receipt;
            # retain its canonical scope evidence without firing it a second time.
            details = [dict(annotation) for annotation in write_grant["mods_before_write"]]
            result["receipt"]["mods_before_write_details"] = details
            result["receipt"]["mods_before_write"] = [
                {
                    "mod": annotation["mod"], "label": annotation["label"],
                    "host_count": int(bool(annotation.get("host"))),
                    "document_count": int(bool(annotation.get("document"))),
                    "element_count": annotation["elements"],
                } if annotation.get("mod") == "blast-radius" else dict(annotation)
                for annotation in details
            ]
    return result


__all__ = ["BROKER_PORTS", "REVIT_ADDIN_ABSENT", "RevitUnreachable", "broker_call", "broker_sessions", "invoke",
           "live_sessions", "revit_addin_years"]
