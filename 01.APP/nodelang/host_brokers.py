"""Every host the founder works with, probed for real and driven when it answers.

One place for the brokers that are not Revit/AutoCAD (those live in
clean_revit_adapter): 3ds Max, Rhino, Blender, Excel, Word, PowerPoint,
Outlook, Notion, Dropbox. Each probe says what is true now (running,
installed, reachable, needs a key, absent) and names the wire that drives it.
Each engine returns the honest zero with a reason when the host is not there
-- never a guess, never a hidden row.
"""
from __future__ import annotations

import ctypes
import json
import ntpath
import os
import socket
import subprocess
import threading
import time

import urllib.error
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from functools import partial
from datetime import datetime, timezone

# MaxMCP (bridges/sources/max_mcp/max_mcp_startup.py) binds the first free
# port from 48886 to 48899 -- the range the AutoCAD and Revit brokers share --
# and answers /max-mcp/ping with service "max-mcp". A port is not an identity:
# 48886 was hard-coded here and is where AutoCAD's broker listens, so MAXScript
# went to AutoCAD (founder report 2026-09-23). Max is only a listener that
# answers as MaxMCP.
MAX_PORTS = range(48886, 48900)
MAX_ROUTE = "/max-mcp"
MAX_SERVICE = "max-mcp"
# The installer carries the MaxMCP startup script (bridges/max), which refuses
# every unsigned caller (host_bridge_auth.py). Setup places it in each installed
# 3ds Max version's startup folder only when the build carries its custody
# review (colleague_setup.register_max_startup); until then none is placed.
MAX_PLUGIN_ABSENT = (
    "3ds Max connects through the ArchHub MaxMCP startup script (it answers as "
    "max-mcp on 48886-48899), which is not in any 3ds Max startup folder on this "
    "machine. Setup places it only when this build carries its reviewed script; "
    "then restart 3ds Max."
)
RHINO_URL = "http://127.0.0.1:9879"
# Broker discovery node: its typed parameters.
BROKER_NODE = {'id': 'host.brokers', 'params': {'info_timeout_seconds': 0.4}}


def broker_sessions(service: str, *, include_document=True) -> list[dict]:
    """Discover session files, then verify each live broker's identity."""
    from .clean_revit_adapter import _call, _CONNECT_TIMEOUT, _PING_TIMEOUT
    if service not in ("revit", "acad"):
        raise ValueError("unknown broker service")
    family = "autocad" if service == "acad" else "revit"
    directory = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ArchHub" / "sessions"
    found = {}
    try:
        processes = _windows_process_table() if os.name == "nt" else None
    except ProcessEnumerationUnavailable:
        processes = None
    # Newest session files first; skip anything whose PID is not a live host.
    paths = sorted(directory.glob(family + "-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in paths[:24]:
        try:
            row = json.loads(path.read_text(encoding="utf-8-sig"))
            port, pid = row["port"], row["pid"]
            if (row.get("family") != family or type(port) is not int or
                    not 1 <= port <= 65535 or type(pid) is not int or pid <= 0):
                continue
            expected = "acad.exe" if service == "acad" else "revit.exe"
            if processes is not None and processes.get(pid, {}).get("name") != expected:
                continue
            # Stale session files must not spend their HTTP timeout budget.
            if not _port_open(port, timeout=_CONNECT_TIMEOUT):
                continue
            ping = _call(port, "/ping", timeout=_PING_TIMEOUT)
            if ping.get("status") != "ok" or ping.get("pid") != pid:
                continue
            identity = ping.get("service")
            if (service == "acad" and identity != "acad-mcp" or
                    service == "revit" and (not ping.get("revit_version") or
                    identity not in (None, "", "revit-mcp"))):
                continue
            info = {}
            if include_document:
                import urllib.error
                try:
                    # Cap hard: live add-in /info can hang; fixtures answer immediately.
                    info = _call(port, "/info", timeout=BROKER_NODE["params"]["info_timeout_seconds"])
                except (urllib.error.URLError, OSError, ValueError, TimeoutError):
                    info = {}
            document = (info.get("document") or info.get("document_title") or info.get("title") or
                        info.get("doc") or info.get("document_name") or
                        row.get("document") or row.get("document_title") or row.get("title") or "")
            found[port] = {"port": port, "pid": pid, "service": identity,
                "revit_version": ping.get("revit_version"),
                "acad_version": info.get("acad_version") or ping.get("acad_version"),
                "service_version": ping.get("version"), "document": document}
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return [found[port] for port in sorted(found)]


def broker_call(service: str, route: str, body=None, *, port=None, timeout=10.0) -> dict:
    """One signed call; ambiguity and stale identities refuse before dispatch."""
    import urllib.error
    from .clean_revit_adapter import _call, _PING_TIMEOUT, RevitUnreachable
    rows = [row for row in broker_sessions(service, include_document=False) if port is None or row["port"] == port]
    name = "AutoCAD" if service == "acad" else "Revit"
    if not rows:
        raise RevitUnreachable("no %s session answers; open it with the ArchHub add-in loaded" % name)
    if len(rows) != 1:
        raise RevitUnreachable("%d %s sessions answer; name one with port" % (len(rows), name))
    row = rows[0]
    # /info on the live add-in can hang; never burn the founder <2s budget on it.
    if route == "/info":
        wait = min(float(timeout), float(_PING_TIMEOUT), 1.5)
        try:
            answer = _call(row["port"], route, body, timeout=wait)
        except (urllib.error.URLError, OSError, ValueError, TimeoutError):
            answer = {"status": "ok", "service": row.get("service"), "pid": row.get("pid"),
                      "port": row["port"], "revit_version": row.get("revit_version"),
                      "acad_version": row.get("acad_version"), "version": row.get("service_version"),
                      "document": row.get("document") or "", "info_source": "ping-discovery"}
        if answer.get("status") != "ok":
            answer = {"status": "ok", "service": row.get("service"), "pid": row.get("pid"),
                      "port": row["port"], "revit_version": row.get("revit_version"),
                      "acad_version": row.get("acad_version"), "version": row.get("service_version"),
                      "document": row.get("document") or "", "info_source": "ping-discovery",
                      "broker_status": answer.get("status"), "http_status": answer.get("http_status")}
        return {"ok": True, "port": row["port"],
                "document": (answer.get("document") or answer.get("document_title") or answer.get("title") or
                             answer.get("document_name") or row.get("document") or ""), **answer}
    answer = _call(row["port"], route, body, timeout=timeout)
    return {"ok": answer.get("status") == "ok", "port": row["port"],
            "document": (answer.get("document") or answer.get("document_title") or answer.get("title") or
                         answer.get("document_name") or row.get("document")), **answer}


def _watcher_script(host, request):
    """Typed offset/read operations; all supplied text becomes a quoted C# literal."""
    source = request.get("source", {})
    element = source.get("element", {})
    write = request["action"] == "write"
    element_id = json.dumps(element.get("id") or request.get("element") or "")
    document = json.dumps(source.get("document") or request.get("document") or "")
    revision = json.dumps(element.get("revision", ""))
    view = json.dumps(source.get("view") or request.get("view") or "")
    offset = json.dumps(request.get("offsetMm", 0.0), allow_nan=False)
    header = "// WATCHER_REQUEST " + json.dumps(request, allow_nan=False) + "\n"
    if host == "Revit":
        return header + """
string wanted = %s, document = %s, viewName = %s;
string docId = Doc.ProjectInformation.UniqueId + "|" + Doc.PathName + "|" + Doc.Title;
if (document != "" && docId != document) throw new Exception("Source document changed");
var views = new Autodesk.Revit.DB.FilteredElementCollector(Doc).OfClass(typeof(Autodesk.Revit.DB.View))
    .Cast<Autodesk.Revit.DB.View>().Where(v => !v.IsTemplate && v.ViewType == Autodesk.Revit.DB.ViewType.FloorPlan)
    .GroupBy(v => v.Name).Where(g => g.Count() == 1).Select(g => g.First()).ToList();
if (viewName == "") viewName = Doc.ActiveView.Name;
var selectedView = views.SingleOrDefault(v => v.Name == viewName);
if (selectedView == null) throw new Exception("Choose an available floor plan view");
var ids = UIDoc.Selection.GetElementIds();
var wall = (wanted != "" ? Doc.GetElement(wanted) : ids.Count == 1 ? Doc.GetElement(ids.First()) : null) as Autodesk.Revit.DB.Wall;
if (wall != null && !new Autodesk.Revit.DB.FilteredElementCollector(Doc, selectedView.Id).ToElementIds().Contains(wall.Id))
    throw new Exception("Selected element is outside this view");
if (%s) {
    if (wall == null || wall.VersionGuid.ToString() != %s) throw new Exception("Source revision changed");
    Autodesk.Revit.DB.ElementTransformUtils.MoveElement(Doc, wall.Id, new Autodesk.Revit.DB.XYZ(0, %s / 304.8, 0));
}
object element = null;
if (wall != null) {
    var location = wall.Location as Autodesk.Revit.DB.LocationCurve;
    if (location == null || !(location.Curve is Autodesk.Revit.DB.Line)) throw new Exception("Choose a straight wall");
    var a = location.Curve.GetEndPoint(0); var b = location.Curve.GetEndPoint(1);
    element = new Dictionary<string, object> {
        {"id",wall.UniqueId}, {"label",wall.Name}, {"revision",wall.VersionGuid.ToString()},
        {"start",new double[]{a.X*304.8/15.0,a.Y*304.8/15.0}},
        {"end",new double[]{b.X*304.8/15.0,b.Y*304.8/15.0}},
        {"lengthMm",location.Curve.Length*304.8}, {"thicknessMm",wall.Width*304.8}
    };
}
result = new Dictionary<string, object> {{"document",docId},
    {"view",viewName},{"views",views.Select(v=>v.Name).ToArray()},{"element",element}};
""" % (element_id, document, view, "true" if write else "false", revision, offset)
    return header + """
var Db = Doc.Database; var Ed = Doc.Editor;
string wanted = %s, document = %s, viewName = %s;
string docId = Db.FingerprintGuid.ToString() + "|" + Doc.Name;
if (document != "" && docId != document) throw new Exception("Source document changed");
var tr = Db.TransactionManager.TopTransaction;
var layouts = (Autodesk.AutoCAD.DatabaseServices.DBDictionary)tr.GetObject(Db.LayoutDictionaryId, Autodesk.AutoCAD.DatabaseServices.OpenMode.ForRead);
var views = new List<string>();
foreach (Autodesk.AutoCAD.DatabaseServices.DBDictionaryEntry item in layouts) views.Add(item.Key);
if (viewName == "") viewName = Autodesk.AutoCAD.DatabaseServices.LayoutManager.Current.CurrentLayout;
if (!views.Contains(viewName)) throw new Exception("Source view changed");
Autodesk.AutoCAD.DatabaseServices.ObjectId id = Autodesk.AutoCAD.DatabaseServices.ObjectId.Null;
if (wanted != "") id = Db.GetObjectId(false, new Autodesk.AutoCAD.DatabaseServices.Handle(Convert.ToInt64(wanted,16)),0);
else {
    var selection = Ed.SelectImplied();
    if (selection.Status == Autodesk.AutoCAD.EditorInput.PromptStatus.OK && selection.Value.Count == 1)
        id = selection.Value.GetObjectIds()[0];
}
var line = id.IsNull ? null : tr.GetObject(id,Autodesk.AutoCAD.DatabaseServices.OpenMode.ForRead) as Autodesk.AutoCAD.DatabaseServices.Line;
if (line != null) {
    var block = (Autodesk.AutoCAD.DatabaseServices.BlockTableRecord)tr.GetObject(line.OwnerId,Autodesk.AutoCAD.DatabaseServices.OpenMode.ForRead);
    if (!block.IsLayout || ((Autodesk.AutoCAD.DatabaseServices.Layout)tr.GetObject(block.LayoutId,Autodesk.AutoCAD.DatabaseServices.OpenMode.ForRead)).LayoutName != viewName)
        throw new Exception("Selected element is outside this view");
}
Func<Autodesk.AutoCAD.DatabaseServices.Line,string> version = l => string.Join("|",
    new double[]{l.StartPoint.X,l.StartPoint.Y,l.StartPoint.Z,l.EndPoint.X,l.EndPoint.Y,l.EndPoint.Z,l.Thickness}
        .Select(v => v.ToString("R",System.Globalization.CultureInfo.InvariantCulture)));
// Geometry units must be explicit; guessing INSUNITS would corrupt the edit distance.
if (Db.Insunits != Autodesk.AutoCAD.DatabaseServices.UnitsValue.Millimeters) throw new Exception("AutoCAD Watcher requires drawing units in millimetres");
if (%s) {
    if (line == null || version(line) != %s) throw new Exception("Source revision changed");
    line.UpgradeOpen();
    line.TransformBy(Autodesk.AutoCAD.Geometry.Matrix3d.Displacement(new Autodesk.AutoCAD.Geometry.Vector3d(0,%s,0)));
}
object element = null;
if (line != null) element = new Dictionary<string,object> {
    {"id",line.Handle.ToString()}, {"label","Line " + line.Handle.ToString()}, {"revision",version(line)},
    {"start",new double[]{line.StartPoint.X/15.0,line.StartPoint.Y/15.0}},
    {"end",new double[]{line.EndPoint.X/15.0,line.EndPoint.Y/15.0}},
    {"lengthMm",line.Length}, {"thicknessMm",line.Thickness}
};
result = new Dictionary<string,object> {{"document",docId},
    {"view",viewName},{"views",views.ToArray()},{"element",element}};
""" % (element_id, document, view, "true" if write else "false", revision, offset)


def _watcher_call(host, request, *, instance=None, timeout_seconds: float = 30.0):
    from .clean_revit_adapter import broker_call, broker_sessions
    from .universal_cell import InvalidCell
    if host not in {"Revit", "AutoCAD"}:
        raise InvalidCell("Watcher supports Revit walls and AutoCAD lines")
    service = "revit" if host == "Revit" else "acad"
    rows = [row for row in broker_sessions(service) if instance is None or row["port"] == instance]
    if len(rows) != 1:
        raise InvalidCell("Choose exactly one available source host session")
    body = {"code":_watcher_script(host, request), "transaction_name":"ArchHub Watcher " + request["action"]}
    if host == "Revit" and request["action"] == "read":
        body["transaction"] = False   # a read opens no transaction in the model: nothing can be written or undone
    answer = broker_call(service, "/exec", body, port=rows[0]["port"], timeout=timeout_seconds)
    if answer.get("status") != "ok" or type(answer.get("result")) is not dict:
        raise InvalidCell("Watcher source refused: " + str(answer.get("error") or "No geometry readback"))
    return {**answer["result"], "host":host, "instance":rows[0]["port"]}


def watcher_read(host, *, instance=None, view=None, document=None, element=None):
    return _watcher_call(host, {"action":"read", "view":view, "document":document,
        "element":element}, instance=instance)


def watcher_write(payload):
    source = payload["source"]
    return _watcher_call(source["host"], {"action":"write", **payload}, instance=source["instance"])


def _max_plugin_installed() -> bool:
    """True when a 3ds Max startup folder of this user loads MaxMCP."""
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "Autodesk" / "3dsMax"
    return any(base.glob("*/ENU/scripts/startup/max_mcp_startup.py"))
BLENDER_URL = "http://127.0.0.1:9876"
NOTION_URL = "https://api.notion.com/v1"


def _port_open(port: int, timeout: float = 0.15) -> bool:
    probe = socket.socket()
    probe.settimeout(timeout)
    try:
        return probe.connect_ex(("127.0.0.1", port)) == 0
    finally:
        probe.close()


def _http(url: str, body: Mapping[str, object] | None = None, headers: Mapping[str, str] | None = None, timeout: float = 20.0):
    data = json.dumps(dict(body)).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET")
    request.add_header("Accept", "application/json")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        text = response.read().decode("utf-8", "replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


class BridgeRefused(RuntimeError):
    """A host bridge answered and refused this caller; its reason is the message."""


def _bridge_call(url: str, body: Mapping[str, object] | None = None, timeout: float = 20.0):
    """One signed call to a local host bridge through the one authenticated client.

    The bridges refuse every route but /ping without a fresh signature
    (host_bridge_auth.py); a refusal comes back as BridgeRefused with the
    bridge's own reason.
    """
    from .host_bridge_auth import bridge_request
    status, answer = bridge_request(url, body, timeout=timeout)
    if status != 200:
        raise BridgeRefused("the bridge refused the call (HTTP %d): %s"
                            % (status, answer.get("error") or "no reason given"))
    return answer


# The development host server waited 240 s for a host's answer. A graph node
# keeps the 20 s default; an explicit caller may ask for more, never past this.
EXEC_WAIT_LIMIT = 240.0


def _exec_wait(params: Mapping[str, object]) -> float:
    try:
        asked = float(params.get("timeout_s") or 20.0)
    except (TypeError, ValueError):
        asked = 20.0
    return max(1.0, min(asked, EXEC_WAIT_LIMIT))


def _max_endpoint(timeout: float = 1.5) -> str | None:
    """The base URL of the MaxMCP that answers with its own identity, or None."""
    for port in MAX_PORTS:
        if not _port_open(port):
            continue
        base = "http://127.0.0.1:%d%s" % (port, MAX_ROUTE)
        try:
            answer = _http(base + "/ping", timeout=timeout)
        except Exception:
            continue
        if isinstance(answer, Mapping) and answer.get("service") == MAX_SERVICE:
            return base
    return None


class ProcessEnumerationUnavailable(RuntimeError):
    """A complete host-presence observation could not be obtained."""


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_uint32), ("cntUsage", ctypes.c_uint32),
        ("th32ProcessID", ctypes.c_uint32), ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", ctypes.c_uint32), ("cntThreads", ctypes.c_uint32),
        ("th32ParentProcessID", ctypes.c_uint32), ("pcPriClassBase", ctypes.c_int32),
        ("dwFlags", ctypes.c_uint32), ("szExeFile", ctypes.c_wchar * 260),
    ]


def _process_snapshot_api():
    kernel = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = (ctypes.c_uint32, ctypes.c_uint32)
    kernel.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    for name in ("Process32FirstW", "Process32NextW"):
        function = getattr(kernel, name)
        function.argtypes = (ctypes.c_void_p, ctypes.POINTER(_PROCESSENTRY32W))
        function.restype = ctypes.c_int
    kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel.CloseHandle.restype = ctypes.c_int
    return kernel


def _windows_process_table() -> dict[int, dict]:
    """Fresh, bounded presence hints; never process identity or authority."""
    try:
        kernel = _process_snapshot_api()
        handle = kernel.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    except (OSError, AttributeError) as error:
        raise ProcessEnumerationUnavailable("Windows process observation is unavailable") from error
    if handle in (None, 0, ctypes.c_void_p(-1).value):
        raise ProcessEnumerationUnavailable("Windows process snapshot could not be opened")
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        processes = {}
        available = kernel.Process32FirstW(handle, ctypes.byref(entry))
        if not available:
            if ctypes.get_last_error() == 18:  # ERROR_NO_MORE_FILES
                return {}
            raise ProcessEnumerationUnavailable("Windows process snapshot could not be read")
        for index in range(8192):
            name = ntpath.basename(entry.szExeFile).casefold()
            if not name:
                raise ProcessEnumerationUnavailable("Windows process snapshot contains an invalid name")
            processes[entry.th32ProcessID] = {'name':name, 'ppid':entry.th32ParentProcessID}
            if index == 8191:
                # Do not read an extra entry merely to distinguish the cap
                # from a complete enumeration. Exhaustion remains unknown.
                raise ProcessEnumerationUnavailable("Windows process snapshot exceeds its entry budget")
            if not kernel.Process32NextW(handle, ctypes.byref(entry)):
                if ctypes.get_last_error() == 18:
                    return processes
                raise ProcessEnumerationUnavailable("Windows process snapshot ended incompletely")
        raise ProcessEnumerationUnavailable("Windows process snapshot exceeds its entry budget")
    except OSError as error:
        raise ProcessEnumerationUnavailable("Windows process observation failed") from error
    finally:
        if not kernel.CloseHandle(handle):
            raise ProcessEnumerationUnavailable("Windows process snapshot could not be closed")


def _windows_process_names() -> frozenset[str]:
    return frozenset(row['name'] for row in _windows_process_table().values())


def _running(names: tuple[str, ...]) -> bool:
    if os.name != "nt":
        return False
    observed = _windows_process_names()
    return any(ntpath.basename(name).casefold() in observed for name in names)


def _installed(paths: tuple[str, ...]) -> bool:
    return any(Path(path).exists() for path in paths)


# COM proxies belong to their creating apartment. Only an explicit open_host
# retains this handle; passive discovery must never CoCreate an application.
_outlook_session = threading.local()


def _outlook_application():
    """Reuse an explicitly opened Outlook on this thread, or attach via ROT."""
    app = getattr(_outlook_session, "application", None)
    if app is not None:
        try:
            app.Version  # Reject disconnected proxies after Outlook closes.
            return app
        except Exception:
            _outlook_session.application = None
    import pythoncom  # type: ignore
    import win32com.client as client  # type: ignore
    pythoncom.CoInitialize()
    return client.GetActiveObject("Outlook.Application")


def _com_alive(prog_id: str) -> bool:
    """True when the application is already open (never launches it)."""
    if os.name != "nt":
        return False
    try:
        if prog_id == "Outlook.Application":
            _outlook_application()
            return True
        import pythoncom  # type: ignore
        import win32com.client as client  # type: ignore
        pythoncom.CoInitialize()
        client.GetActiveObject(prog_id)
        return True
    except Exception:
        return False


def _notion_token() -> str:
    token = os.environ.get("NOTION_API_KEY", "").strip()
    if token:
        return token
    try:
        from app import secrets_store  # noqa: PLC0415
        return (secrets_store.load_api_key("notion") or "").strip()
    except Exception:
        return ""


def _dropbox_root() -> Path | None:
    for candidate in (Path.home() / "Dropbox", Path(os.environ.get("USERPROFILE", "")) / "Dropbox"):
        if candidate.is_dir():
            return candidate
    return None


# ---------------------------------------------------------------- probes --

def probe_host_rows() -> list[dict]:
    """Rows for every non-Revit/AutoCAD host, each with its real state now."""
    rows: list[dict] = []
    max_url = _max_endpoint()
    max_up = max_url is not None
    max_state = "connected" if max_up else ("running" if _running(("3dsmax.exe",)) else ("installed" if _installed((r"C:\Program Files\Autodesk\3ds Max 2026\3dsmax.exe", r"C:\Program Files\Autodesk\3ds Max 2025\3dsmax.exe")) else "absent"))
    max_plugin = max_up or _max_plugin_installed()
    rows.append({"id": "max", "name": "3ds Max", "drive": "max.exec",
                 "state": max_state if max_plugin or max_state == "absent" else "unavailable",
                 "detail": ("MaxMCP on :%s" % max_url.split(":")[2].split("/")[0]) if max_up
                 else "open Max with the ArchHub MaxMCP plug-in loaded (it answers as max-mcp on 48886-48899)"
                 if max_plugin else MAX_PLUGIN_ABSENT})
    rhino_up = _port_open(9879)
    rows.append({"id": "rhino", "name": "Rhino", "drive": "rhino.exec",
                 "state": "connected" if rhino_up else ("running" if _running(("Rhino.exe",)) else ("installed" if _installed((r"C:\Program Files\Rhino 8\System\Rhino.exe", r"C:\Program Files\Rhino 7\System\Rhino.exe")) else "absent")),
                 "detail": "bridge on :9879" if rhino_up else "say \"open Rhino\" in ArchHub to start Rhino with its bridge (listens on :9879)"})
    blender_up = _port_open(9876)
    rows.append({"id": "blender", "name": "Blender", "drive": "blender.exec",
                 "state": "connected" if blender_up else ("running" if _running(("blender.exe",)) else ("installed" if _installed((r"C:\Program Files\Blender Foundation",)) else "absent")),
                 "detail": "add-on on :9876" if blender_up else "say \"open Blender\" in ArchHub to start Blender with its add-on (listens on :9876)"})
    for host, prog, exe, name in (("excel", "Excel.Application", "EXCEL.EXE", "Excel"), ("word", "Word.Application", "WINWORD.EXE", "Word"), ("powerpoint", "PowerPoint.Application", "POWERPNT.EXE", "PowerPoint")):
        open_now = _com_alive(prog)
        rows.append({"id": host, "name": name, "drive": "office.read",
                     "state": "connected" if open_now else ("installed" if _installed((r"C:\Program Files\Microsoft Office\root\Office16\%s" % exe,)) else "absent"),
                     "detail": "open · reads what it holds" if open_now else "installed · open a file and the reads answer"})
    outlook_open = _com_alive("Outlook.Application")
    rows.append({"id": "outlook", "name": "Outlook", "drive": "outlook.inbox",
                 "state": "connected" if outlook_open else ("installed" if _installed((r"C:\Program Files\Microsoft Office\root\Office16\OUTLOOK.EXE",)) else "absent"),
                 "detail": "open · inbox readable" if outlook_open else "installed · open Outlook and the inbox reads answer"})
    from .outlook_graph import invoke as graph_invoke
    graph_prerequisites = graph_invoke("prerequisites", {})
    graph_ready = (graph_prerequisites.get("ok") is True
                   and graph_prerequisites.get("state") == "prerequisites-ready")
    rows.append({"id": "outlook-new", "name": "Outlook (New / Microsoft Graph)",
                 "drive": "outlook.graph.inbox",
                 "state": "prerequisites-ready" if graph_ready else graph_prerequisites.get("state", "unavailable"),
                 "detail": ("PowerShell and Microsoft Graph SDK prerequisites are available; authentication has not been checked"
                            if graph_ready else graph_prerequisites.get("reason", "Microsoft Graph prerequisite check is unavailable"))})
    rows.append({"id": "outlook-imap", "name": "Company mail (Yahoo / Turbify IMAP)",
                 "drive": "outlook.imap.inbox", "state": "needs-sign-in",
                 "detail": "direct read-only mailbox access; connect with company email and an app password; status verifies the exact account"})
    token = _notion_token()
    signed_in = _notion_signed_in()
    rows.append({"id": "notion", "name": "Notion", "drive": "notion.search",
                 "state": "connected" if token or signed_in else "needs-sign-in",
                 "detail": ("integration token present" if token else "signed in to Notion" if signed_in
                            else "connect Notion: one sign-in in the browser, no token to copy (notion.connect)")})
    dropbox = _dropbox_root()
    rows.append({"id": "dropbox", "name": "Dropbox", "drive": "dropbox.list",
                 "state": "connected" if dropbox else "absent",
                 "detail": "Dropbox folder present" if dropbox else "no Dropbox folder in this profile"})
    return rows


# The rest of the catalogue the old app carried (host_detector + HOST_CATALOG):
# programs the founder works with that have a probe today and a wire when one
# lands. Installed/running is a fact; "no wire yet" is said, not hidden.
_CATALOGUE = (
    # id, name, process names, install paths, port (0 = none)
    ("revit-2024", "Revit 2024", ("Revit.exe",), (r"C:\Program Files\Autodesk\Revit 2024\Revit.exe",), 0),
    ("revit-2023", "Revit 2023", ("Revit.exe",), (r"C:\Program Files\Autodesk\Revit 2023\Revit.exe",), 0),
    ("revit-2022", "Revit 2022", ("Revit.exe",), (r"C:\Program Files\Autodesk\Revit 2022\Revit.exe",), 0),
    ("autocad-2025", "AutoCAD 2025", ("acad.exe",), (r"C:\Program Files\Autodesk\AutoCAD 2025\acad.exe",), 0),
    ("autocad-2024", "AutoCAD 2024", ("acad.exe",), (r"C:\Program Files\Autodesk\AutoCAD 2024\acad.exe",), 0),
    ("max-2025", "3ds Max 2025", ("3dsmax.exe",), (r"C:\Program Files\Autodesk\3ds Max 2025\3dsmax.exe",), 0),
    ("photoshop", "Photoshop", ("Photoshop.exe",), (r"C:\Program Files\Adobe",), 0),
    ("illustrator", "Illustrator", ("Illustrator.exe",), (r"C:\Program Files\Adobe",), 0),
    ("indesign", "InDesign", ("InDesign.exe",), (r"C:\Program Files\Adobe",), 0),
    ("teams", "Teams", ("ms-teams.exe", "Teams.exe"), (), 0),
    ("lmstudio", "LM Studio", ("LM Studio.exe",), (), 1234),
    ("antigravity", "Antigravity", ("Antigravity.exe",), (), 0),
    ("procore", "Procore", (), (), 0),
)

_CONNECTORS_NOT_BUILT = (
    ("civil3d", "Civil 3D"),
    ("navisworks", "Navisworks"),
    ("sketchup", "SketchUp"),
    ("archicad", "Archicad"),
    ("ifc", "IFC"),
    ("bluebeam", "Bluebeam"),
    ("enscape", "Enscape"),
    ("powerbi", "Power BI"),
    ("sharepoint", "SharePoint"),
    ("slack", "Slack"),
    ("airtable", "Airtable"),
)


def revit_years() -> list[str]:
    from .clean_revit_adapter import revit_addin_years
    return revit_addin_years()


def _revit_absent() -> str:
    from .clean_revit_adapter import REVIT_ADDIN_ABSENT
    return REVIT_ADDIN_ABSENT


def probe_catalogue_rows() -> list[dict]:
    rows = []
    for host_id, name, processes, paths, port in _CATALOGUE:
        # A per-year row (revit-2024, autocad-2025, max-2025) is a fact about
        # what is installed; the live session rows say what is running, and a
        # process name cannot tell one year from another.
        per_year = host_id.rsplit("-", 1)[-1].isdigit()
        if (host_id.startswith("revit-") and paths and _installed(paths)
                and host_id.split("-", 1)[1] not in revit_years()):
            rows.append({"id": host_id, "name": name, "drive": "",
                         "state": "unavailable", "detail": _revit_absent()})
            continue
        if port and _port_open(port):
            state, detail = "connected", "answering on :%d" % port
        elif processes and not per_year and _running(processes):
            state, detail = "running", "open - no wire in this build yet"
        elif paths and _installed(paths):
            state, detail = "installed", "installed - no wire in this build yet"
        elif host_id == "procore":
            state, detail = "needs-key", "add a Procore token to connect"
        else:
            state, detail = "absent", "not found on this machine"
        rows.append({"id": host_id, "name": name, "drive": "", "state": state, "detail": detail})
    for host_id, name in _CONNECTORS_NOT_BUILT:
        rows.append({"id": host_id, "name": name, "drive": "", "state": "off",
                     "detail": "no connector yet", "connector_built": False})
    return rows


# --------------------------------------------------------------- engines --

def _honest(reason: str):
    return {"out": [], "ok": False, "reason": reason}, reason


def max_exec(params: Mapping[str, object], feeds: Mapping[str, object]):
    """MAXScript in the open 3ds Max scene through MaxMCP, found by its identity."""
    code = str(params.get("code") or "")
    base = _max_endpoint()
    if base is None:
        return _honest("no MaxMCP answers as max-mcp on 48886-48899 (open Max with MaxMCP loaded)")
    if not code:
        return {"out": _http(base + "/ping", timeout=8)}, "MaxMCP answers"
    # MaxMCP reads the MAXScript from "script" (max_mcp_startup.py _run_kind).
    try:
        return {"out": _bridge_call(base + "/exec_maxscript", {"script": code}, timeout=_exec_wait(params))}, "ran in 3ds Max"
    except BridgeRefused as refused:
        return _honest("3ds Max: %s" % refused)


def max_info(params: Mapping[str, object], feeds: Mapping[str, object]):
    """Scene info from the open 3ds Max through MaxMCP."""
    base = _max_endpoint()
    if base is None:
        return _honest("no MaxMCP answers as max-mcp on 48886-48899 (open Max with MaxMCP loaded)")
    try:
        return {"out": _bridge_call(base + "/info")}, "3ds Max scene"
    except BridgeRefused as refused:
        return _honest("3ds Max: %s" % refused)


def max_python(params: Mapping[str, object], feeds: Mapping[str, object]):
    """Python (pymxs, rt) in the open 3ds Max scene through MaxMCP /exec."""
    code = str(params.get("code") or "")
    base = _max_endpoint()
    if base is None:
        return _honest("no MaxMCP answers as max-mcp on 48886-48899 (open Max with MaxMCP loaded)")
    if not code:
        return _honest("no Python code to run in 3ds Max")
    try:
        return {"out": _bridge_call(base + "/exec", {"code": code}, timeout=_exec_wait(params))}, "ran in 3ds Max"
    except BridgeRefused as refused:
        return _honest("3ds Max: %s" % refused)


def rhino_exec(params: Mapping[str, object], feeds: Mapping[str, object]):
    """RhinoPython in the open Rhino model through its bridge (:9879)."""
    code = str(params.get("code") or "")
    if not _port_open(9879):
        return _honest("Rhino bridge is not listening on :9879 (run the ArchHub bridge script inside Rhino)")
    if not code:
        return {"out": {"ok": True, "bridge": RHINO_URL}}, "Rhino bridge answers"
    try:
        return {"out": _bridge_call(RHINO_URL + "/execute", {"code": code}, timeout=_exec_wait(params))}, "ran in Rhino"
    except BridgeRefused as refused:
        return _honest("Rhino: %s" % refused)


def blender_exec(params: Mapping[str, object], feeds: Mapping[str, object]):
    """Python in the open Blender scene through the ArchHub add-on (:9876)."""
    code = str(params.get("code") or "")
    if not _port_open(9876):
        return _honest("Blender add-on is not listening on :9876 (enable the ArchHub add-on)")
    if not code:
        return {"out": _http(BLENDER_URL + "/ping", timeout=8)}, "Blender add-on answers"
    try:
        return {"out": _bridge_call(BLENDER_URL + "/execute", {"code": code}, timeout=_exec_wait(params))}, "ran in Blender"
    except BridgeRefused as refused:
        return _honest("Blender: %s" % refused)


def office_read(params: Mapping[str, object], feeds: Mapping[str, object]):
    """What Excel/Word/PowerPoint hold open, through the kernel office adapter."""
    from .clean_office_adapter import OfficeUnreachable, invoke
    operation = str(params.get("operation") or "excel.list_workbooks")
    arguments = {"name": params.get("name")} if params.get("name") else {}
    if operation == "excel.read_range":
        arguments = {"file": params.get("file"), "sheet": params.get("sheet"), "range": params.get("range")}
    try:
        result = invoke(operation, arguments)
    except OfficeUnreachable as exc:
        return _honest(str(exc))
    count = result.get("count", len(result.get("rows", []) or []))
    return {"out": result}, "%s: %s" % (operation, count)


def excel_write_range(params: Mapping[str, object], feeds: Mapping[str, object]):
    """Write rows to a local xlsx/csv path through the governed file writer."""
    from .nodeslib_v2_engines import write_table_file
    held = feeds.get("rows") if isinstance(feeds, Mapping) else None
    if held is None and isinstance(feeds, Mapping):
        held = feeds.get("in")
    return write_table_file(params, {"rows": held})


def outlook_inbox(params: Mapping[str, object], feeds: Mapping[str, object]):
    """Newest inbox items from the OPEN Outlook; never launches it."""
    transport = str(params.get("transport") or "classic").casefold()
    if transport == "graph":
        from .outlook_graph import inbox
        return inbox(params, feeds)
    if transport == "imap":
        from .outlook_imap import inbox
        return inbox(params, feeds)
    if transport != "classic":
        return _honest("Unsupported Outlook transport; select classic, graph or imap")
    count = max(1, min(int(params.get("count") or 20), 200))
    if not _com_alive("Outlook.Application"):
        return _honest("Outlook is not open")
    app = _outlook_application()
    items = app.GetNamespace("MAPI").GetDefaultFolder(6).Items
    items.Sort("[ReceivedTime]", True)
    rows = []
    for index in range(1, count + 1):
        try:
            item = items.Item(index)
        except Exception:
            break
        rows.append({"subject": str(getattr(item, "Subject", "")), "sender": str(getattr(item, "SenderName", "")),
                     "received": str(getattr(item, "ReceivedTime", "")), "unread": bool(getattr(item, "UnRead", False))})
    return {"out": rows}, "%d inbox item(s)" % len(rows)


def outlook_correspondence(operation, params, feeds):
    """Bounded reads through the SAME running-Outlook attachment owner."""
    from .clean_office_adapter import coordination_arguments
    from .library_engines import _OUTLOOK, draft_email
    args = coordination_arguments(operation, params, feeds)
    if operation in ('outlook.reply_draft', 'outlook.forward_draft'):
        reference = 'reply_to' if operation == 'outlook.reply_draft' else 'forward_of'
        args[reference] = args[reference] or args['message_id']
        if not args[reference]:
            raise ValueError('set message_id for the draft')
        return draft_email(args, feeds)
    app = _OUTLOOK[0]()
    if app is None:
        return _honest('Outlook is not open')
    namespace = app.GetNamespace('MAPI')
    conversation = str(args.get('conversation_id') or '')
    if operation == 'outlook.read_thread' and not conversation:
        if not args['message_id']:
            raise ValueError('set conversation_id or message_id')
        original = (namespace.GetItemFromID(args['message_id'], args['store_id']) if args['store_id']
                    else namespace.GetItemFromID(args['message_id']))
        conversation = str(original.ConversationID)
    limit, scan_limit = int(args['limit']), int(args['scan_limit'])
    if not 1 <= limit <= 1000 or not 1 <= scan_limit <= 10000:
        raise ValueError('Outlook limit/scan_limit out of range')
    since = datetime.fromisoformat(str(args['since']).replace('Z', '+00:00')) if args.get('since') else None
    if since and since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    rows, scanned, seen = [], 0, set()
    for folder_id in args['folders']:
        default = {'inbox': 6, 'sent': 5, 'drafts': 16}.get(str(folder_id).casefold())
        if default is not None:
            folder = (namespace.GetStoreFromID(args['store_id']).GetDefaultFolder(default)
                      if args['store_id'] else namespace.GetDefaultFolder(default))
        else:
            folder = (namespace.GetFolderFromID(str(folder_id), args['store_id']) if args['store_id']
                      else namespace.GetFolderFromID(str(folder_id)))
        items = folder.Items
        items.Sort('[ReceivedTime]', True)
        for index in range(1, int(items.Count) + 1):
            if scanned >= scan_limit or len(rows) >= limit:
                break
            scanned += 1
            item = items.Item(index)
            if int(getattr(item, 'Class', 43)) != 43:
                continue
            identity = (str(item.Parent.StoreID), str(item.EntryID))
            if identity in seen:
                continue
            seen.add(identity)
            if conversation and str(item.ConversationID) != conversation:
                continue
            received = str(item.ReceivedTime)
            if since:
                observed = datetime.fromisoformat(received.replace('Z', '+00:00'))
                if observed.tzinfo is None:
                    observed = observed.replace(tzinfo=since.tzinfo)
                if observed < since:
                    continue
            row = {'id': str(item.EntryID), 'store_id': identity[0], 'folder_id': str(folder.EntryID),
                   'conversation_id': str(item.ConversationID), 'subject': str(item.Subject),
                   'sender': str(item.SenderName), 'sender_address': str(item.SenderEmailAddress),
                   'to': str(item.To), 'cc': str(item.CC), 'received': received, 'unread': bool(item.UnRead)}
            if args['include_body']:
                row['body'], row['html_body'] = str(item.Body), str(item.HTMLBody)
            keywords = args.get('keywords') or []
            haystack = ' '.join(str(row.get(k, '')) for k in ('subject', 'sender', 'sender_address', 'body')).casefold()
            if keywords and not all(str(word).casefold() in haystack for word in keywords):
                continue
            if args['include_attachments']:
                row['attachments'] = [{'name': str(item.Attachments.Item(i).FileName),
                                       'bytes': int(item.Attachments.Item(i).Size)}
                                      for i in range(1, int(item.Attachments.Count) + 1)]
            rows.append(row)
    return {'out': rows, 'scanned': scanned, 'truncated': scanned >= scan_limit or len(rows) >= limit}, '%d correspondence item(s)' % len(rows)


def office_coordination(operation, params, feeds, *, owner_admitted=False):
    from .clean_office_adapter import coordination_arguments, invoke
    args = coordination_arguments(operation, params, feeds)
    result = invoke(operation, args, owner_admitted=owner_admitted)
    return result, operation


def coordination_engine_table(gate):
    """Attach existing actions through the application's per-call owner gate."""
    from .clean_office_adapter import COORDINATION_NODES
    from .library_engines import draft_email
    engines = {}
    for name in COORDINATION_NODES:
        if name.startswith(('excel.', 'pdf.')):
            effect = partial(office_coordination, name, owner_admitted=True)
        elif name == 'library.draft_email':
            effect = draft_email
        else:
            effect = partial(outlook_correspondence, name)
        engines[name] = gate(name, effect)
    return engines


def _notion_title(row: Mapping[str, object]) -> str:
    for value in (row.get("properties") or {}).values():
        if isinstance(value, dict) and value.get("type") == "title":
            return "".join(t.get("plain_text", "") for t in value.get("title", []))
    return ""


def _notion_signed_in() -> bool:
    from . import notion_mcp  # noqa: PLC0415
    return notion_mcp.connected()


def notion_connect(params: Mapping[str, object], feeds: Mapping[str, object]):
    """Connect Notion with Notion's own sign-in: the browser asks once, nothing is copied."""
    from . import notion_mcp  # noqa: PLC0415
    try:
        answer = notion_mcp.connect()
    except (OSError, ValueError, urllib.error.URLError) as exc:
        return _honest("Notion sign-in could not start: %s" % exc)
    if not answer.get("ok"):
        return _honest(str(answer.get("error") or "Notion sign-in did not complete"))
    return {"out": [{"connected": True}]}, "Notion is connected"


def notion_search(params: Mapping[str, object], feeds: Mapping[str, object]):
    """Search the founder's Notion workspace: an integration token if one is set, else the Notion sign-in."""
    token = _notion_token()
    if not token:
        from . import notion_mcp  # noqa: PLC0415
        if not notion_mcp.connected():
            return _honest("Notion is not connected yet: run notion.connect once (the browser asks to Allow)")
        try:
            rows = notion_mcp.search(str(params.get("query") or ""))
        except notion_mcp.NotionNotConnected as exc:
            return _honest(str(exc))
        except notion_mcp.NotionToolError as exc:
            return _honest("Notion refused the search: %s" % exc)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            return _honest("Notion could not be reached: %s" % exc)
        return {"out": rows}, "%d Notion result(s)" % len(rows)
    try:
        data = _http(NOTION_URL + "/search", {"query": str(params.get("query") or ""), "page_size": 20},
                     {"Authorization": "Bearer " + token, "Notion-Version": "2022-06-28"})
    except urllib.error.HTTPError as exc:
        return _honest("Notion answered HTTP %s" % exc.code)
    rows = [{"id": r.get("id"), "object": r.get("object"), "url": r.get("url"), "title": _notion_title(r)} for r in data.get("results", [])]
    return {"out": rows}, "%d Notion result(s)" % len(rows)


def dropbox_list(params: Mapping[str, object], feeds: Mapping[str, object]):
    """Files under the Dropbox folder of this profile."""
    root = _dropbox_root()
    if root is None:
        return _honest("no Dropbox folder in this profile")
    target = (root / str(params.get("path") or "")).resolve()
    if root not in target.parents and target != root:
        return _honest("path escapes the Dropbox folder")
    if not target.is_dir():
        return _honest("no such folder: %s" % target)
    rows = [{"name": p.name, "dir": p.is_dir(), "bytes": (p.stat().st_size if p.is_file() else 0)} for p in sorted(target.iterdir())[:500]]
    return {"out": rows}, "%d entr(ies) in %s" % (len(rows), target)


def connector_rows(params: Mapping[str, object], feeds: Mapping[str, object]):
    rows = probe_host_rows() + probe_catalogue_rows()
    return {"out": rows}, "%d host(s)" % len(rows)


from .outlook_graph import inbox as _graph_inbox, status as _graph_status, categories as _graph_categories, categorize as _graph_categorize
from .outlook_imap import inbox as _imap_inbox, status as _imap_status, message as _imap_message


ENGINES = {
    "max.exec": max_exec, "max.info": max_info, "max.python": max_python, "rhino.exec": rhino_exec, "blender.exec": blender_exec,
    "office.read": office_read, "excel.write_range": excel_write_range, "outlook.inbox": outlook_inbox, "notion.search": notion_search,
    "notion.connect": notion_connect,
    "dropbox.list": dropbox_list, "connector.rows": connector_rows,
    "outlook.graph.inbox": _graph_inbox, "outlook.graph.status": _graph_status,
    "outlook.graph.categories": _graph_categories, "outlook.graph.categorize": _graph_categorize,
    "outlook.imap.inbox": _imap_inbox, "outlook.imap.status": _imap_status,
    "outlook.imap.message": _imap_message,
}
for _coordination_engine in ('outlook.search', 'outlook.read_thread', 'outlook.reply_draft', 'outlook.forward_draft'):
    ENGINES[_coordination_engine] = partial(outlook_correspondence, _coordination_engine)
for _coordination_engine in ('excel.read_table', 'excel.build_workbook', 'excel.write_cells',
                             'excel.share_workbook', 'excel.open', 'pdf.extract_text', 'pdf.snip'):
    ENGINES[_coordination_engine] = partial(office_coordination, _coordination_engine)

__all__ = ["ENGINES", "probe_host_rows", "probe_catalogue_rows"]


# ---------------------------------------------------------------- open --

_OFFICE_PROGIDS = {
    "excel": "Excel.Application", "word": "Word.Application",
    "powerpoint": "PowerPoint.Application", "outlook": "Outlook.Application",
}
# What keeps an automation-started Office instance alive after the reference
# drops, and registered in the running-object table so the probe and the
# reads can find it. Measured on the founder's machine: EXCEL.EXE launched as a
# process never registered (Excel registers only after it loses focus); a
# Dispatch made Visible with UserControl and one workbook registered in 1 s,
# was seen from a separate process, and survived release.
_OFFICE_KEEPALIVE = {
    "excel": ("Workbooks", "UserControl"), "word": ("Documents", None),
    "powerpoint": ("Presentations", None), "outlook": (None, None),
}
_RHINO_EXES = (r"C:\Program Files\Rhino 8\System\Rhino.exe", r"C:\Program Files\Rhino 7\System\Rhino.exe")
_BLENDER_ROOT = Path(r"C:\Program Files\Blender Foundation")


def _bridges_dir() -> Path:
    """The bridge scripts the installer ships beside the app (bridges/<host>)."""
    return Path(__file__).resolve().parent.parent / "bridges"


def _blender_exe() -> str | None:
    if not _BLENDER_ROOT.is_dir():
        return None
    found = sorted(_BLENDER_ROOT.glob("Blender */blender.exe"))
    return str(found[-1]) if found else None


def open_host(host: str, *, popen=None, com_alive=None, dispatch=None, wait_s: float = 8.0) -> dict:
    """Bring one INSTALLED host to CONNECTED, the way the founder would by hand.

    Office: open it through COM, visible and kept alive, and wait for it to
    register (the reads answer once it is open). Rhino:
    launch it running the shipped ArchHub bridge script, which binds :9879.
    Blender: launch it with the shipped add-on registered, which binds :9876.
    3ds Max needs the MaxMCP plug-in, which this build does not ship -- said
    plainly. Nothing here pretends: the state reported is the next probe's.
    """
    host = str(host or "").strip().casefold()
    if host == "outlook-imap":
        from .outlook_imap import open_sign_in
        return {"host": host, **open_sign_in()}
    if host == "outlook-new":
        from .outlook_graph import invoke
        return {"host": host, **invoke("connect", {})}
    popen = popen or subprocess.Popen
    com_alive = com_alive or _com_alive
    if host in _OFFICE_PROGIDS:
        progid = _OFFICE_PROGIDS[host]
        if com_alive(progid):
            return {"ok": True, "host": host, "action": "already open", "state": "connected"}
        try:
            if dispatch is None:
                import pythoncom  # type: ignore
                import win32com.client as client  # type: ignore
                pythoncom.CoInitialize()
                dispatch = client.Dispatch
            app = dispatch(progid)
            collection, keep = _OFFICE_KEEPALIVE[host]
            if host == "outlook":
                app.Session.GetDefaultFolder(6).Display()  # the inbox window keeps Outlook running
                _outlook_session.application = app
            else:
                app.Visible = True
                if keep:
                    setattr(app, keep, True)
                docs = getattr(app, collection)
                if docs.Count == 0:
                    docs.Add()
            del app
        except Exception as exc:
            return {"ok": False, "host": host, "error": "%s: %s" % (type(exc).__name__, exc)}
        if host == "outlook" and com_alive(progid):
            return {"ok": True, "host": host, "action": "opened, session retained on this thread", "state": "connected"}
        deadline = time.monotonic() + float(wait_s)
        while time.monotonic() < deadline:
            if com_alive(progid):
                return {"ok": True, "host": host, "action": "opened, visible, kept alive", "state": "connected"}
            time.sleep(0.5)
        return {"ok": True, "host": host, "action": "opened, visible, kept alive", "state": "launching"}
    if host == "rhino":
        exe = next((p for p in _RHINO_EXES if Path(p).exists()), None)
        script = _bridges_dir() / "rhino" / "archhub_mcp.py"
        if exe is None:
            return {"ok": False, "host": host, "error": "Rhino is not installed"}
        if not script.is_file():
            return {"ok": False, "host": host, "error": "the Rhino bridge script did not ship (%s)" % script}
        try:
            running = _running(("Rhino.exe",))
        except ProcessEnumerationUnavailable:
            return {"ok": False, "host": host,
                    "error": "Rhino process status is unavailable; no application was launched"}
        if running:
            return {"ok": False, "host": host, "state": "running",
                    "error": 'Rhino is already open without the bridge; in Rhino run: _-RunPythonScript "%s"' % script}
        popen([exe, "/nosplash", '/runscript=_-RunPythonScript "%s"' % script], close_fds=True,
              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return {"ok": True, "host": host, "action": "launched with the ArchHub bridge (:9879)", "state": "launching"}
    if host == "blender":
        exe = _blender_exe()
        addon = _bridges_dir() / "blender" / "archhub_mcp" / "__init__.py"
        if exe is None:
            return {"ok": False, "host": host, "error": "Blender is not installed"}
        if not addon.is_file():
            return {"ok": False, "host": host, "error": "the Blender add-on did not ship (%s)" % addon}
        try:
            running = _running(("blender.exe",))
        except ProcessEnumerationUnavailable:
            return {"ok": False, "host": host,
                    "error": "Blender process status is unavailable; no application was launched"}
        if running:
            return {"ok": False, "host": host, "state": "running",
                    "error": "Blender is already open without the add-on; enable ArchHub MCP Bridge in Edit > Preferences > Add-ons (%s)" % addon.parent}
        boot = "import sys; sys.path.insert(0, %r); import archhub_mcp; archhub_mcp.register()" % str(addon.parent.parent)
        popen([exe, "--python-expr", boot], close_fds=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return {"ok": True, "host": host, "action": "launched with the ArchHub add-on (:9876)", "state": "launching"}
    if host == "max":
        return {"ok": False, "host": host, "error": MAX_PLUGIN_ABSENT}
    return {"ok": False, "host": host, "error": "no way to open %r from ArchHub" % host}
