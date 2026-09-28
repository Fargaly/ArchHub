"""Host tools on the shipped native MCP: one broker implementation, gated like every agent effect.

The same twenty tools the founder's development-era host server offered, served
by the installed native owner (native_agent_mcp.build_server). Nothing here
knows how to reach a host: 3ds Max, Rhino, Blender, Office, Outlook, Notion and
Dropbox go through host_brokers.ENGINES, Revit and AutoCAD through the signed
broker client in clean_revit_adapter, each broker found by its own identity.
Every bridge call is signed there (host_bridge_auth).

Gates, the ones every native tool already stands behind:

* Owner: each call is admitted inside the verified native owner (bound_client).
  A host effect then runs with the session's lock released, and the owner and
  the task's admission are verified again when it returns; if either changed
  the result is reported unconfirmed, never re-run. A changed or stale owner
  refuses before any host is reached.
* Admission and scope: a host effect (code execution, a screenshot written to
  disk) runs only while this session holds a claimed Work whose configured
  ``requirements`` name that host in ``hosts`` (for example
  ``{"hosts": ["revit", "max"]}``). The Work configuration projection carries
  exactly inputs, requirements and cde-container; requirements is the founder's
  structured object, so that is where a Work admits its hosts. The founder sets
  them as "Programs this task may use" in the Workshop (on creation and in the
  Work configuration). The host is called once; there is no retry. Reads need
  the owner, not a Work.
"""
from __future__ import annotations

from typing import Callable

from .application_machine_transport import MachineTransportError
from .host_brokers import ENGINES, EXEC_WAIT_LIMIT

INFO_WAIT = 10.0
SCREENSHOT_PATH = r"C:\temp\revit_view.png"


class HostToolRefused(MachineTransportError):
    """A host tool refused before any host was reached."""


def _engine(name: str, **params) -> dict:
    out, label = ENGINES[name](params, {})
    return {"ok": out.get("ok", True) is not False, "label": label, **out}


def _broker(service: str, route: str, body=None, port=None, wait=INFO_WAIT) -> dict:
    from . import clean_revit_adapter as brokers
    return brokers.broker_call(service, route, body, port=port, timeout=wait)


def _sessions(service: str) -> dict:
    from . import clean_revit_adapter as brokers
    rows = brokers.broker_sessions(service)
    return {"ok": bool(rows), "sessions": rows}


def _program(host: str) -> str:
    from .existing_workshop_project_revision import WORK_PROGRAMS
    return WORK_PROGRAMS[host]


def _admitted_work(client, host: str) -> str:
    """The claimed Work that admits ``host``, read under the owner, or a plain refusal."""
    projection = client.current_work_configuration()
    work = projection.get("work") if isinstance(projection, dict) else None
    if not work:
        raise HostToolRefused(
            "No task is claimed in this session yet. Claim the task in the Workshop first, then try again.")
    fields = work["configuration"].get("fields") or {}
    requirements = (fields.get("requirements") or {}).get("value")
    hosts = requirements.get("hosts") if isinstance(requirements, dict) else None
    if not isinstance(hosts, list) or host not in hosts:
        name = _program(host)
        raise HostToolRefused(
            "This task isn't allowed to use %s yet. In the Workshop, open the task's Work configuration, "
            "tick %s under Programs this task may use, and save." % (name, name))
    return work["root"]


def register_host_tools(server, control) -> None:
    """Add the host tools to a native server bound to ``control``."""

    def read(run: Callable[[], dict]) -> dict:
        with control.bound_client():
            return run()

    def effect(host: str, run: Callable[[], dict]) -> dict:
        # Admission under the owner, then the host call with the session's
        # lock released (a 240 s call must not stall its other tools), then
        # the owner and the same task's admission verified again. The host
        # is never called a second time; a failed recheck reports the result
        # as unconfirmed.
        with control.bound_client() as client:
            work = _admitted_work(client, host)
        name, reason = _program(host), None
        try:
            result = run()
        except OSError:
            # Sent, then no answer (timeout, dropped connection): the command
            # may have run. Refusals raised before the host is contacted
            # (no session, ambiguous port) are not OSError and still raise.
            result = {"ok": False}
            reason = ("%s did not answer in time. The command may have run; check %s "
                      "before anything else. Do not run it again blindly." % (name, name))
        try:
            with control.bound_client() as client:
                if _admitted_work(client, host) != work:
                    raise HostToolRefused("claimed task changed")
        except HostToolRefused:
            reason = reason or ("This task was released or its programs changed while %s was running. "
                                "The command may have run; check %s before anything else. "
                                "Do not run it again blindly." % (name, name))
        except MachineTransportError:
            reason = reason or ("ArchHub's connection to this session changed while %s was running. "
                                "The command may have run; check %s before anything else. "
                                "Do not run it again blindly." % (name, name))
        # The host's answer comes first; the gate's own verdict always wins.
        answer = {key: value for key, value in result.items()
                  if key not in ("work", "confirmed", "unconfirmed")}
        return {**answer, "work": work, "confirmed": reason is None,
                **({"unconfirmed": reason} if reason else {})}

    @server.tool(name="hosts_state")
    def hosts_state() -> dict:
        """Every host connector's live state; the same read as hosts.status."""
        with control.bound_client() as client:
            return client.request("GET", "/api/universal/hosts", {})

    @server.tool(name="revit_ping")
    def revit_ping() -> dict:
        """Live Revit sessions answering the ArchHub add-in (port, version, document)."""
        return read(lambda: _sessions("revit"))

    @server.tool(name="revit_info")
    def revit_info(port: int | None = None) -> dict:
        """Active Revit document info from the add-in."""
        return read(lambda: _broker("revit", "/info", port=port))

    @server.tool(name="revit_execute_csharp")
    def revit_execute_csharp(code: str, transaction_name: str = "ArchHub",
                             port: int | None = None) -> dict:
        """Execute C# live in Revit (globals UIApp, UIDoc, Doc; set `result`). Needs Work admitting revit."""
        return effect("revit", lambda: _broker("revit", "/exec",
                      {"code": code, "transaction_name": transaction_name}, port, EXEC_WAIT_LIMIT))

    @server.tool(name="revit_screenshot")
    def revit_screenshot(output_path: str = SCREENSHOT_PATH, width_px: int = 1920,
                         port: int | None = None) -> dict:
        """Export the active Revit view as PNG to output_path. Needs Work admitting revit."""
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
        """Execute C# live in AutoCAD (globals Doc, Db, Ed; set `result`). Needs Work admitting acad."""
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
        """Execute Python in 3ds Max via pymxs (rt; set `result`). Needs Work admitting max."""
        return effect("max", lambda: _engine("max.python", code=code, timeout_s=EXEC_WAIT_LIMIT))

    @server.tool(name="max_execute_maxscript")
    def max_execute_maxscript(script: str) -> dict:
        """Execute MAXScript in 3ds Max. Needs Work admitting max."""
        return effect("max", lambda: _engine("max.exec", code=script, timeout_s=EXEC_WAIT_LIMIT))

    @server.tool(name="blender_ping")
    def blender_ping() -> dict:
        """Is the ArchHub Blender add-on answering on :9876?"""
        return read(lambda: _engine("blender.exec", code=""))

    @server.tool(name="blender_execute_python")
    def blender_execute_python(code: str) -> dict:
        """Execute Python with bpy in the open Blender (set `result`). Needs Work admitting blender."""
        return effect("blender", lambda: _engine("blender.exec", code=code, timeout_s=EXEC_WAIT_LIMIT))

    @server.tool(name="rhino_ping")
    def rhino_ping() -> dict:
        """Is the ArchHub Rhino bridge answering on :9879?"""
        return read(lambda: _engine("rhino.exec", code=""))

    @server.tool(name="rhino_execute_python")
    def rhino_execute_python(code: str) -> dict:
        """Run RhinoPython in the open Rhino model. Needs Work admitting rhino."""
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