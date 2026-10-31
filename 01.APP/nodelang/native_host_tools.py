"""Native host tools call existing signed brokers directly, without app enrollment.

Reads need no Work. Effects require settings.json host_effects[host] == true,
checked before and after one dispatch; uncertain calls are never replayed.
"""
from __future__ import annotations

from typing import Callable

from .host_brokers import ENGINES, EXEC_WAIT_LIMIT

# Reads must answer inside the founder <2s budget; never sit on a hung signed /info.
INFO_WAIT = 1.5
SCREENSHOT_PATH = r"C:\temp\revit_view.png"


class HostToolRefused(RuntimeError):
    """A host tool refused before any host was reached."""


def _engine(engine: str, **params) -> dict:
    out, label = ENGINES[engine](params, {})
    return {"ok": out.get("ok", True) is not False, "label": label, **out}


def _broker(service: str, route: str, body=None, port=None, wait=INFO_WAIT) -> dict:
    from . import host_brokers as brokers
    return brokers.broker_call(service, route, body, port=port, timeout=wait)


def _sessions(service: str) -> dict:
    from . import host_brokers as brokers
    rows = brokers.broker_sessions(service, include_document=False)
    return {"ok": bool(rows), "sessions": rows}


def _allow_effect(host: str) -> None:
    import json
    import os
    from pathlib import Path
    path = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ArchHub" / "settings.json"
    try:
        settings = json.loads(path.read_text(encoding="utf-8-sig"))
        permissions = settings.get("host_effects", {})
        allowed = isinstance(permissions, dict) and permissions.get(host) is True
    except (OSError, ValueError, AttributeError):
        allowed = False
    if not allowed:
        raise HostToolRefused("Local host effect permission is disabled for %s (settings.json: host_effects)." % host)


_HOST_STATE = {"value": None, "at": 0.0, "running": None}
# Host probing node: a probe walks every host port and can take seconds; a tool never waits for it.
HOST_STATE_NODE = {"id": "hosts.state", "params": {"fresh_seconds": 10.0, "first_wait_seconds": 0.5}}


def _host_state() -> dict:
    """The newest host probe; a stale one refreshes beside the caller (nothing waits on a slow host)."""
    import threading
    import time
    from .connector_operation_evidence import host_projection
    params = HOST_STATE_NODE["params"]
    if time.monotonic() - _HOST_STATE["at"] >= params["fresh_seconds"] and _HOST_STATE["running"] is None:
        def refresh():
            try:
                _HOST_STATE.update(value=host_projection(), at=time.monotonic())
            finally:
                _HOST_STATE["running"] = None
        _HOST_STATE["running"] = threading.Thread(target=refresh, name="archhub-host-probe", daemon=True)
        _HOST_STATE["running"].start()
    running = _HOST_STATE["running"]
    if _HOST_STATE["value"] is None and running is not None:
        running.join(params["first_wait_seconds"])
    if _HOST_STATE["value"] is None:
        return {"ok": True, "connectors": [], "operations": [], "probing": True,
                "detail": "Hosts are being probed; ask again in a few seconds."}
    return _HOST_STATE["value"]


def register_host_tools(server, control=None, *, read_only=False) -> None:
    """Keep the existing MCP tools independent of Work and graph ownership."""
    def read(run: Callable[[], dict]) -> dict:
        return run()

    def effect(host: str, run: Callable[[], dict]) -> dict:
        _allow_effect(host)
        reason = None
        try:
            result = run()
        except OSError:
            result = {"ok": False}
            reason = "%s did not answer. The command may have run; check the host. Do not run it again blindly." % host
        try:
            _allow_effect(host)
        except HostToolRefused:
            reason = reason or "Local permission changed. The command may have run; check the host. Do not run it again blindly."
        answer = {key: value for key, value in result.items()
                  if key not in ("work", "confirmed", "unconfirmed")}
        return {**answer, "confirmed": reason is None,
                **({"unconfirmed": reason} if reason else {})}

    @server.tool(name="hosts_state")
    def hosts_state() -> dict:
        """Every host connector's live state; the same read as hosts.status."""
        return _host_state()

    if read_only:
        return

    @server.tool(name="revit_ping")
    def revit_ping() -> dict:
        """Live Revit sessions answering the ArchHub add-in (port, version, document)."""
        return read(lambda: _sessions("revit"))

    @server.tool(name="revit_info")
    def revit_info(port: int | None = None) -> dict:
        """Active Revit document info from the add-in."""
        return read(lambda: _broker("revit", "/info", port=port))

    @server.tool(name="revit_open_document")
    def revit_open_document(path: str, activate: bool = True, view: str | None = None,
                            port: int | None = None) -> dict:
        """Open and activate a model (UNC supported), optionally a named view. Works at Home; no model write."""
        return effect("revit", lambda: _broker("revit", "/open", {"path": path, "activate": activate, "view": view},
                                    port, EXEC_WAIT_LIMIT))

    @server.tool(name="revit_execute_csharp")
    def revit_execute_csharp(code: str, transaction_name: str = "ArchHub",
                             port: int | None = None, transaction: bool = True) -> dict:
        """C# with UIApp/UIDoc/Doc and result. Doc is null at Home; transaction:false for app calls. Needs local host effect permission."""
        return effect("revit", lambda: _broker("revit", "/exec",
                      {"code": code, "transaction_name": transaction_name,
                       **({"transaction": False} if not transaction else {})}, port, EXEC_WAIT_LIMIT))

    @server.tool(name="revit_screenshot")
    def revit_screenshot(output_path: str = SCREENSHOT_PATH, width_px: int = 1920,
                         port: int | None = None) -> dict:
        """Export the active Revit view as PNG to output_path. Needs local revit effect permission."""
        return effect("revit", lambda: _broker("revit", "/screenshot",
                      {"output_path": output_path, "width_px": width_px}, port, EXEC_WAIT_LIMIT))

    @server.tool(name="acad_ping")
    def acad_ping() -> dict:
        """Live AutoCAD sessions answering the ArchHub broker."""
        return read(lambda: _sessions("acad"))

    @server.tool(name="acad_info")
    def acad_info(port: int | None = None) -> dict:
        """Active AutoCAD document info."""
        return read(lambda: _broker("acad", "/info", port=port))

    @server.tool(name="acad_execute_csharp")
    def acad_execute_csharp(code: str, transaction_name: str = "ArchHub",
                            port: int | None = None) -> dict:
        """Execute C# live in AutoCAD (globals Doc, Db, Ed; set `result`). Needs local acad effect permission."""
        return effect("acad", lambda: _broker("acad", "/exec",
                      {"code": code, "transaction_name": transaction_name}, port, EXEC_WAIT_LIMIT))

    @server.tool(name="max_ping")
    def max_ping() -> dict:
        """Is a MaxMCP answering as max-mcp on 48886-48899?"""
        return read(lambda: _engine("max.exec", code=""))

    @server.tool(name="max_info")
    def max_info() -> dict:
        """3ds Max scene info."""
        return read(lambda: _engine("max.info"))

    @server.tool(name="max_execute_python")
    def max_execute_python(code: str) -> dict:
        """Execute Python in 3ds Max via pymxs (rt; set `result`). Needs local max effect permission."""
        return effect("max", lambda: _engine("max.python", code=code, timeout_s=EXEC_WAIT_LIMIT))

    @server.tool(name="max_execute_maxscript")
    def max_execute_maxscript(script: str) -> dict:
        """Execute MAXScript in 3ds Max. Needs local max effect permission."""
        return effect("max", lambda: _engine("max.exec", code=script, timeout_s=EXEC_WAIT_LIMIT))

    @server.tool(name="blender_ping")
    def blender_ping() -> dict:
        """Is the ArchHub Blender add-on answering on :9876?"""
        return read(lambda: _engine("blender.exec", code=""))

    @server.tool(name="blender_execute_python")
    def blender_execute_python(code: str) -> dict:
        """Execute Python with bpy in the open Blender (set `result`). Needs local blender effect permission."""
        return effect("blender", lambda: _engine("blender.exec", code=code, timeout_s=EXEC_WAIT_LIMIT))

    @server.tool(name="rhino_ping")
    def rhino_ping() -> dict:
        """Is the ArchHub Rhino bridge answering on :9879?"""
        return read(lambda: _engine("rhino.exec", code=""))

    @server.tool(name="rhino_execute_python")
    def rhino_execute_python(code: str) -> dict:
        """Run RhinoPython in the open Rhino model. Needs local rhino effect permission."""
        return effect("rhino", lambda: _engine("rhino.exec", code=code, timeout_s=EXEC_WAIT_LIMIT))

    @server.tool(name="office_read")
    def office_read(operation: str, name: str = "") -> dict:
        """Read what Excel/Word/PowerPoint hold open (excel.list_workbooks, word.list_documents, ...)."""
        return read(lambda: _engine("office.read", operation=operation, name=name))

    @server.tool(name="outlook_inbox")
    def outlook_inbox(count: int = 20) -> dict:
        """Newest inbox items from the open Outlook; never launches it."""
        return read(lambda: _engine("outlook.inbox", count=count))

    @server.tool(name="notion_search")
    def notion_search(query: str = "") -> dict:
        """Search the Notion workspace (needs the integration token)."""
        return read(lambda: _engine("notion.search", query=query))

    @server.tool(name="dropbox_list")
    def dropbox_list(path: str = "") -> dict:
        """Files under the Dropbox folder of this profile."""
        return read(lambda: _engine("dropbox.list", path=path))


def _revit_info(params, feeds=None):
    return {"out": _broker("revit", "/info", port=params.get("port"))}, "revit info"


def _revit_open_document(params, feeds=None):
    _allow_effect("revit")
    body = {"path": params.get("path") or "", "activate": bool(params.get("activate", True)),
            "view": params.get("view") or None}
    return {"out": _broker("revit", "/open", body, params.get("port"), EXEC_WAIT_LIMIT)}, "revit open"


def _revit_execute_csharp(params, feeds=None):
    _allow_effect("revit")
    body = {"code": params.get("code") or "", "transaction_name": params.get("transaction_name") or "ArchHub"}
    if params.get("transaction") is False:
        body["transaction"] = False
    return {"out": _broker("revit", "/exec", body, params.get("port"), EXEC_WAIT_LIMIT)}, "revit exec"


def _revit_screenshot(params, feeds=None):
    _allow_effect("revit")
    body = {"output_path": params.get("output_path") or SCREENSHOT_PATH, "width_px": params.get("width_px")}
    return {"out": _broker("revit", "/screenshot", body, params.get("port"), EXEC_WAIT_LIMIT)}, "revit screenshot"


def _acad_info(params, feeds=None):
    return {"out": _broker("acad", "/info", port=params.get("port"))}, "acad info"


def _acad_execute_csharp(params, feeds=None):
    _allow_effect("acad")
    body = {"code": params.get("code") or "", "transaction_name": params.get("transaction_name") or "ArchHub"}
    return {"out": _broker("acad", "/exec", body, params.get("port"), EXEC_WAIT_LIMIT)}, "acad exec"


def _sessions_engine(service):
    def engine(params, feeds=None):
        return {"out": _sessions(service)}, service + " sessions"
    return engine


def _hosts_state_engine(params, feeds=None):
    held = HOST_STATE_NODE["params"]
    for key in ("fresh_seconds", "first_wait_seconds"):
        if params.get(key) not in (None, ""):
            held[key] = float(params[key])
    return {"out": _host_state()}, "hosts"


TOOL_ENGINES = {
    "hosts.state": _hosts_state_engine,
    "revit.info": _revit_info,
    "revit.open_document": _revit_open_document,
    "revit.execute_csharp": _revit_execute_csharp,
    "revit.screenshot": _revit_screenshot,
    "acad.ping": _sessions_engine("acad"),
    "acad.info": _acad_info,
    "acad.execute_csharp": _acad_execute_csharp,
}

# One registry: the Library node for each tool register_host_tools already exposes.
HOST_TOOLS = (
    {"id": "hosts_state", "title": "Hosts", "engine": "hosts.state", "sub": "Every host connector's live state",
     "params": dict(HOST_STATE_NODE["params"]),
     "types": {}},
    {"id": "revit_ping", "title": "Revit ping", "engine": "revit.sessions", "sub": "Live Revit sessions",
     "params": {}, "types": {}},
    {"id": "revit_info", "title": "Revit info", "engine": "revit.info", "sub": "Active Revit document",
     "params": {"port": None}, "types": {"port": "integer"}},
    {"id": "revit_open_document", "title": "Open Revit document", "engine": "revit.open_document",
     "sub": "Open a model in Revit",
     "params": {"path": "", "activate": True, "view": "", "port": None},
     "types": {"path": "text", "activate": "bool", "view": "text", "port": "integer"}},
    {"id": "revit_execute_csharp", "title": "Revit C#", "engine": "revit.execute_csharp",
     "sub": "Run C# in the open Revit",
     "params": {"code": "", "transaction_name": "ArchHub", "port": None, "transaction": True},
     "types": {"code": "text", "transaction_name": "text", "port": "integer", "transaction": "bool"}},
    {"id": "revit_screenshot", "title": "Revit screenshot", "engine": "revit.screenshot",
     "sub": "Export the active view as PNG",
     "params": {"output_path": SCREENSHOT_PATH, "width_px": 1920, "port": None},
     "types": {"output_path": "text", "width_px": "integer", "port": "integer"}},
    {"id": "acad_ping", "title": "AutoCAD ping", "engine": "acad.ping", "sub": "Live AutoCAD sessions",
     "params": {}, "types": {}},
    {"id": "acad_info", "title": "AutoCAD info", "engine": "acad.info", "sub": "Active AutoCAD document",
     "params": {"port": None}, "types": {"port": "integer"}},
    {"id": "acad_execute_csharp", "title": "AutoCAD C#", "engine": "acad.execute_csharp",
     "sub": "Run C# in the open AutoCAD",
     "params": {"code": "", "transaction_name": "ArchHub", "port": None},
     "types": {"code": "text", "transaction_name": "text", "port": "integer"}},
    {"id": "max_ping", "title": "3ds Max ping", "engine": "max.exec", "sub": "Is 3ds Max answering",
     "params": {"code": ""}, "types": {"code": "text"}},
    {"id": "max_info", "title": "3ds Max info", "engine": "max.info", "sub": "3ds Max scene info",
     "params": {}, "types": {}},
    {"id": "max_execute_python", "title": "3ds Max Python", "engine": "max.python", "sub": "Run Python in 3ds Max",
     "params": {"code": ""}, "types": {"code": "text"}},
    {"id": "max_execute_maxscript", "title": "3ds Max MAXScript", "engine": "max.exec", "sub": "Run MAXScript in 3ds Max",
     "params": {"code": ""}, "types": {"code": "text"}},
    {"id": "blender_ping", "title": "Blender ping", "engine": "blender.exec", "sub": "Is Blender answering",
     "params": {"code": ""}, "types": {"code": "text"}},
    {"id": "blender_execute_python", "title": "Blender Python", "engine": "blender.exec", "sub": "Run Python in Blender",
     "params": {"code": ""}, "types": {"code": "text"}},
    {"id": "rhino_ping", "title": "Rhino ping", "engine": "rhino.exec", "sub": "Is Rhino answering",
     "params": {"code": ""}, "types": {"code": "text"}},
    {"id": "rhino_execute_python", "title": "Rhino Python", "engine": "rhino.exec", "sub": "Run Python in Rhino",
     "params": {"code": ""}, "types": {"code": "text"}},
    {"id": "office_read", "title": "Office read", "engine": "office.read", "sub": "Read open Excel, Word or PowerPoint",
     "params": {"operation": "", "name": ""}, "types": {"operation": "text", "name": "text"}},
    {"id": "outlook_inbox", "title": "Outlook inbox", "engine": "outlook.inbox", "sub": "Newest inbox items",
     "params": {"count": 20}, "types": {"count": "integer"}},
    {"id": "notion_search", "title": "Notion search", "engine": "notion.search", "sub": "Search the Notion workspace",
     "params": {"query": ""}, "types": {"query": "text"}},
    {"id": "dropbox_list", "title": "Dropbox list", "engine": "dropbox.list", "sub": "Files in Dropbox",
     "params": {"path": ""}, "types": {"path": "text"}},
)


__all__ = ["HostToolRefused", "HOST_TOOLS", "TOOL_ENGINES", "register_host_tools"]
