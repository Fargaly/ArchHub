"""Every host the founder works with, probed for real and driven when it answers.

One place for the brokers that are not Revit/AutoCAD (those live in
clean_revit_adapter): 3ds Max, Rhino, Blender, Excel, Word, PowerPoint,
Outlook, Notion, Dropbox. Each probe says what is true now (running,
installed, reachable, needs a key, absent) and names the wire that drives it.
Each engine returns the honest zero with a reason when the host is not there
-- never a guess, never a hidden row.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import time

# The app is windowless (pythonw): a child console would POP UP on the founder's desktop
# at every probe. Every spawn in this module carries this flag; a court asserts it.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
import urllib.error
import urllib.request
from collections.abc import Mapping
from pathlib import Path

MAX_URL = "http://127.0.0.1:48886/max-mcp"
RHINO_URL = "http://127.0.0.1:9879"
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


def _running(names: tuple[str, ...]) -> bool:
    if os.name != "nt":
        return False
    try:
        listing = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=8, stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW).stdout.casefold()
    except Exception:
        return False
    return any(name.casefold() in listing for name in names)


def _installed(paths: tuple[str, ...]) -> bool:
    return any(Path(path).exists() for path in paths)


def _com_alive(prog_id: str) -> bool:
    """True when the application is already open (never launches it)."""
    if os.name != "nt":
        return False
    try:
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
    max_up = _port_open(48886)
    rows.append({"id": "max", "name": "3ds Max", "drive": "max.exec",
                 "state": "connected" if max_up else ("running" if _running(("3dsmax.exe",)) else ("installed" if _installed((r"C:\Program Files\Autodesk\3ds Max 2026\3dsmax.exe", r"C:\Program Files\Autodesk\3ds Max 2025\3dsmax.exe")) else "absent")),
                 "detail": "MaxMCP on :48886" if max_up else "open Max with the ArchHub MaxMCP plug-in loaded (:48886)"})
    rhino_up = _port_open(9879)
    rows.append({"id": "rhino", "name": "Rhino", "drive": "rhino.exec",
                 "state": "connected" if rhino_up else ("running" if _running(("Rhino.exe",)) else ("installed" if _installed((r"C:\Program Files\Rhino 8\System\Rhino.exe", r"C:\Program Files\Rhino 7\System\Rhino.exe")) else "absent")),
                 "detail": "bridge on :9879" if rhino_up else "in Rhino: run the ArchHub bridge script (payload/rhino) to listen on :9879"})
    blender_up = _port_open(9876)
    rows.append({"id": "blender", "name": "Blender", "drive": "blender.exec",
                 "state": "connected" if blender_up else ("running" if _running(("blender.exe",)) else ("installed" if _installed((r"C:\Program Files\Blender Foundation",)) else "absent")),
                 "detail": "add-on on :9876" if blender_up else "enable the ArchHub Blender add-on (listens on :9876)"})
    for host, prog, exe, name in (("excel", "Excel.Application", "EXCEL.EXE", "Excel"), ("word", "Word.Application", "WINWORD.EXE", "Word"), ("powerpoint", "PowerPoint.Application", "POWERPNT.EXE", "PowerPoint")):
        open_now = _com_alive(prog)
        rows.append({"id": host, "name": name, "drive": "office.read",
                     "state": "connected" if open_now else ("installed" if _installed((r"C:\Program Files\Microsoft Office\root\Office16\%s" % exe,)) else "absent"),
                     "detail": "open · reads what it holds" if open_now else "installed · open a file and the reads answer"})
    outlook_open = _com_alive("Outlook.Application")
    rows.append({"id": "outlook", "name": "Outlook", "drive": "outlook.inbox",
                 "state": "connected" if outlook_open else ("installed" if _installed((r"C:\Program Files\Microsoft Office\root\Office16\OUTLOOK.EXE",)) else "absent"),
                 "detail": "open · inbox readable" if outlook_open else "installed · open Outlook and the inbox reads answer"})
    token = _notion_token()
    rows.append({"id": "notion", "name": "Notion", "drive": "notion.search",
                 "state": "connected" if token else "needs-key",
                 "detail": "integration token present" if token else "add a Notion integration token (Settings → keys → notion, or NOTION_API_KEY)"})
    dropbox = _dropbox_root()
    rows.append({"id": "dropbox", "name": "Dropbox", "drive": "dropbox.list",
                 "state": "connected" if dropbox else "absent",
                 "detail": str(dropbox) if dropbox else "no Dropbox folder in this profile"})
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


def probe_catalogue_rows() -> list[dict]:
    rows = []
    for host_id, name, processes, paths, port in _CATALOGUE:
        # A per-year row (revit-2024, autocad-2025, max-2025) is a fact about
        # what is installed; the live session rows say what is running, and a
        # process name cannot tell one year from another.
        per_year = host_id.rsplit("-", 1)[-1].isdigit()
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
    return rows


# --------------------------------------------------------------- engines --

def _honest(reason: str):
    return {"out": [], "ok": False, "reason": reason}, reason


def max_exec(params: Mapping[str, object], feeds: Mapping[str, object]):
    """MAXScript in the open 3ds Max scene through MaxMCP (:48886)."""
    code = str(params.get("code") or "")
    if not _port_open(48886):
        return _honest("3ds Max is not listening on :48886 (open Max with MaxMCP loaded)")
    if not code:
        return {"out": _http(MAX_URL + "/ping", timeout=8)}, "MaxMCP answers"
    return {"out": _http(MAX_URL + "/exec_maxscript", {"code": code})}, "ran in 3ds Max"


def rhino_exec(params: Mapping[str, object], feeds: Mapping[str, object]):
    """RhinoPython in the open Rhino model through its bridge (:9879)."""
    code = str(params.get("code") or "")
    if not _port_open(9879):
        return _honest("Rhino bridge is not listening on :9879 (run the ArchHub bridge script inside Rhino)")
    if not code:
        return {"out": {"ok": True, "bridge": RHINO_URL}}, "Rhino bridge answers"
    return {"out": _http(RHINO_URL + "/execute", {"code": code})}, "ran in Rhino"


def blender_exec(params: Mapping[str, object], feeds: Mapping[str, object]):
    """Python in the open Blender scene through the ArchHub add-on (:9876)."""
    code = str(params.get("code") or "")
    if not _port_open(9876):
        return _honest("Blender add-on is not listening on :9876 (enable the ArchHub add-on)")
    if not code:
        return {"out": _http(BLENDER_URL + "/ping", timeout=8)}, "Blender add-on answers"
    return {"out": _http(BLENDER_URL + "/execute", {"code": code})}, "ran in Blender"


def office_read(params: Mapping[str, object], feeds: Mapping[str, object]):
    """What Excel/Word/PowerPoint hold open, through the kernel office adapter."""
    from .clean_office_adapter import OfficeUnreachable, invoke
    operation = str(params.get("operation") or "excel.list_workbooks")
    arguments = {"name": params.get("name")} if params.get("name") else {}
    try:
        result = invoke(operation, arguments)
    except OfficeUnreachable as exc:
        return _honest(str(exc))
    count = result.get("count", len(result.get("rows", []) or []))
    return {"out": result}, "%s: %s" % (operation, count)


def outlook_inbox(params: Mapping[str, object], feeds: Mapping[str, object]):
    """Newest inbox items from the OPEN Outlook; never launches it."""
    count = max(1, min(int(params.get("count") or 20), 200))
    if not _com_alive("Outlook.Application"):
        return _honest("Outlook is not open")
    import win32com.client as client  # type: ignore
    app = client.GetActiveObject("Outlook.Application")
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


def _notion_title(row: Mapping[str, object]) -> str:
    for value in (row.get("properties") or {}).values():
        if isinstance(value, dict) and value.get("type") == "title":
            return "".join(t.get("plain_text", "") for t in value.get("title", []))
    return ""


def notion_search(params: Mapping[str, object], feeds: Mapping[str, object]):
    """Search the founder's Notion workspace with the integration token."""
    token = _notion_token()
    if not token:
        return _honest("no Notion token (Settings > keys > notion, or NOTION_API_KEY)")
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


ENGINES = {
    "max.exec": max_exec, "rhino.exec": rhino_exec, "blender.exec": blender_exec,
    "office.read": office_read, "outlook.inbox": outlook_inbox, "notion.search": notion_search,
    "dropbox.list": dropbox_list, "connector.rows": connector_rows,
}

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
        if _running(("Rhino.exe",)):
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
        if _running(("blender.exe",)):
            return {"ok": False, "host": host, "state": "running",
                    "error": "Blender is already open without the add-on; enable ArchHub MCP Bridge in Edit > Preferences > Add-ons (%s)" % addon.parent}
        boot = "import sys; sys.path.insert(0, %r); import archhub_mcp; archhub_mcp.register()" % str(addon.parent.parent)
        popen([exe, "--python-expr", boot], close_fds=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return {"ok": True, "host": host, "action": "launched with the ArchHub add-on (:9876)", "state": "launching"}
    if host == "max":
        return {"ok": False, "host": host, "error": "3ds Max connects through the MaxMCP plug-in on :48886, which this build does not ship"}
    return {"ok": False, "host": host, "error": "no way to open %r from ArchHub" % host}
