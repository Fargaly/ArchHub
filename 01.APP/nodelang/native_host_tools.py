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


def _host_state() -> dict:
    from .connector_operation_evidence import host_projection
    return host_projection()


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


__all__ = ["HostToolRefused", "register_host_tools"]
