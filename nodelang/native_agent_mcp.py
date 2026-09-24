"""Explicit native stdio owner for Work and ordinary Workshop tools.

This entrypoint does not migrate existing clients, proxy Brain authority, wake
agents, or execute Work. One process owns one graph capability for all tools.
"""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
from mcp.server.fastmcp import Context

from .application_machine_transport import MachineTransportError
from .clean_coordination_mcp import build_server as build_coordination_server
from .installed_workshop_coordination import InstalledWorkshopCoordinationClient
from .native_agent_session import NativeAgentSession
from .native_agent_hooks import user_prompt_submit_context, stop_context


class _OwnedWorkshopClient(InstalledWorkshopCoordinationClient):
    def __init__(self, owner, client):
        self._native_owner = owner
        self._native_client = client
        self._native_generation = getattr(owner, "generation", None)
        from .native_resume_guard import NativeResumeGuard
        self.resume_guard=(NativeResumeGuard(owner) if (
            getattr(owner, '_expected_agent_session', None) or
            getattr(owner, '_environment', {}).get('SESSION_LINK_REQUIRED_CONNECTIONS')) else None)
        super().__init__(client)

    @contextmanager
    def bound_client(self):
        # Owner lock precedes client lock, matching enrollment and renewal.
        with self._native_owner.bound_client() as current:
            if current is not self._native_client:
                generation = getattr(self._native_owner, "generation", None)
                if (type(generation) is not int or type(self._native_generation) is not int
                        or generation <= self._native_generation):
                    raise MachineTransportError("native stdio client ownership changed")
                # Construct the whole guarded adapter before replacing any
                # cached delegate. The owner lock quiesces all tool calls.
                fresh = InstalledWorkshopCoordinationClient(current)
                if fresh._session != self._session:
                    raise MachineTransportError("native stdio graph session changed")
                self._client, self._descriptor_path = fresh._client, fresh._descriptor_path
                self._session, self._descriptor = fresh._session, fresh._descriptor
                self._native_client, self._native_generation = current, generation
            yield current

    def call(self, method, parameters=None, **kwargs):
        with self.bound_client():
            return super().call(method, parameters, **kwargs)


def _text(value):
    return type(value) is str and bool(value.strip()) and len(value.encode("utf-8")) <= 512


def _validate_index(result, client):
    descriptor = client._pinned_runtime_descriptor
    fields = {"application", "agent_session", "workshop", "revision",
              "brain_scope", "registry", "total", "items"}
    if (type(result) is not dict or set(result) != fields
            or result["application"] != descriptor.application_root
            or result["agent_session"] != client.agent_session_root
            or result["workshop"] != descriptor.workshop_root
            or result["registry"] != descriptor.work_registry_root
            or not _text(result["brain_scope"])
            or type(result["revision"]) is not int or result["revision"] < 0
            or type(result["total"]) is not int
            or type(result["items"]) not in (list, tuple)
            or result["total"] != len(result["items"])
            or not 0 <= result["total"] <= 4096):
        raise MachineTransportError("native Work index identity or shape is invalid")
    roots = set()
    row_fields = {"root", "membership_wire", "queue_index", "interfaces",
                  "operational", "claimant_session", "claimant_agent_body", "claim_binding"}
    for row in result["items"]:
        if (type(row) is not dict or set(row) != row_fields
                or not _text(row["root"]) or not row["root"].startswith("assembly-instance:")
                or row["root"] in roots or not _text(row["membership_wire"])
                or type(row["queue_index"]) is not int or row["queue_index"] < 0
                or type(row["interfaces"]) is not dict
                or set(row["interfaces"]) != {"external-key", "title"}
                or type(row["operational"]) is not dict
                or set(row["operational"]) != {"machine", "current_state", "current_state_label"}
                or not all(_text(value) for value in row["operational"].values())
                or any(row[key] is not None and not _text(row[key]) for key in
                       ("claimant_session", "claimant_agent_body", "claim_binding"))):
            raise MachineTransportError("native Work index row is invalid")
        roots.add(row["root"])
        for interface in row["interfaces"].values():
            if (type(interface) is not dict
                    or set(interface) != {"id", "target", "value", "editable"}
                    or not _text(interface["id"]) or not _text(interface["target"])
                    or type(interface["value"]) is not str
                    or interface["editable"] is not False):
                raise MachineTransportError("native Work index interface is invalid")
    return result


def attach_workshop_tools(owner, selected_work: str):
    """Attach task tools to an already bound native hook owner.

    Embedded clients such as OpenCode must share their hook's owner. This does
    not construct a session, enroll, claim Work, or grant a file permission.
    Retain the returned server for the owner's lifetime: its selected-Work
    adapter retains uncertain effects for work_reconcile.
    """
    from .native_workshop_tools import build_workshop_task_server, validate_selected_work
    validate_selected_work(selected_work)
    with owner.bound_client() as client:
        control = _OwnedWorkshopClient(owner, client)
        return build_workshop_task_server(control, selected_work)


def build_server(*, session=None, workshop_task: str | None = None):
    """Enroll once at explicit construction; every call rechecks that owner."""
    if workshop_task is not None:
        from .native_workshop_tools import validate_selected_work
        validate_selected_work(workshop_task)
    owner = session if session is not None else NativeAgentSession()
    client = owner.connect()
    if workshop_task is not None:
        return attach_workshop_tools(owner, workshop_task)
    control = _OwnedWorkshopClient(owner, client)
    server = build_coordination_server(client=control)

    @server.tool(name='native.hook_stop')
    def hook_stop() -> dict[str, object]:
        """Observe this retained actor's real Work gate; never enroll, submit or execute."""
        return stop_context(control)

    @server.tool(name="native.owner_status")
    def owner_status() -> dict[str, object]:
        """Inspect verified owner fingerprints while stale; no enrollment or retry."""
        return owner.owner_status()

    @server.tool(name="native.owner_rebind")
    def owner_rebind(expected_old_owner: str, expected_new_owner: str) -> dict[str, object]:
        """Recover this session after owner replacement or known lease expiry.

        Copy the two fingerprints from owner_status. Application/database and
        graph session must continue exactly. No failed tool action is replayed.
        Equal fingerprints are accepted only after the retained lease expires.
        An uncertain enrollment remains refused. Private hooks require their
        registered process custody guard; no capability or action is replayed.
        """
        return owner.rebind_owner(expected_old_owner=expected_old_owner,
                                  expected_new_owner=expected_new_owner)

    @server.tool(name="native.owner_recover")
    def owner_recover(expected_failed_owner: str, expected_current_owner: str) -> dict[str, object]:
        """Recover only the retained conditional attempt; never enroll or replay a tool."""
        return owner.recover_rebind_owner(expected_failed_owner=expected_failed_owner,
                                         expected_current_owner=expected_current_owner)

    @server.tool(name="native.owner_inspect_effects")
    def owner_inspect_effects(expected_owner: str, cursor: str | None = None) -> dict[str, object]:
        """Read this original actor's pending permit evidence; no settlement or grant."""
        return owner.inspect_enrollment(expected_owner=expected_owner, projection="effects",
                                       **({"cursor":cursor} if cursor is not None else {}))

    def host_runtime():
        # Deployment configuration, never a path supplied by a tool caller.
        node = os.environ.get("SESSION_LINK_NODE")
        if not node:
            bundled = Path(__file__).resolve().parents[1] / "runtime" / "node.exe"
            node = str(bundled) if bundled.is_file() else None
        state = os.environ.get("SESSION_LINK_STATE_DIR")
        if not node or not state:
            raise MachineTransportError("Existing Session Link host configuration is unavailable")
        return {"node_executable": node, "state_directory": state}

    @server.tool(name="native.workshop_host_attach")
    def workshop_host_attach(connection: dict, ttl_seconds: int = 300) -> dict[str, object]:
        """Attach this agent's exact existing Session Link connection to Workshop.

        Pass its non-secret connection descriptor. This does not create a
        connection, enroll another session, approve work or execute a workflow.
        Only status metadata returns; uncertain outcomes must not be retried.
        """
        return owner.attach_workshop_host(connection, ttl_seconds=ttl_seconds,
                                          **host_runtime())

    @server.tool(name="native.workshop_host_detach")
    def workshop_host_detach() -> dict[str, object]:
        """Detach this agent's Workshop channel, leaving other agents connected."""
        return owner.detach_workshop_host()

    @server.tool(name="native.hook_user_prompt_submit")
    def hook_user_prompt_submit() -> dict[str, object]:
        """Provide bounded Work and Workshop context for a native prompt hook.

        Read-only context delivery; does not acknowledge, approve, or execute.
        Configure this on UserPromptSubmit, after MCP connection is available.
        """
        return user_prompt_submit_context(control)

    @server.tool(name="native.work_current")
    def work_current() -> dict[str, object]:
        """Read this session's current claimed Work; no claim or execution."""
        with control.bound_client() as client:
            work = client.current_claimed_work()
            return {"agent_session": client.agent_session_root, "work": work}

    @server.tool(name="native.work_current_detail")
    def work_current_detail() -> dict[str, object]:
        """Read this session's claimed Work node, interfaces and claim metadata.

        Parameters are graph data, not an approved execution plan. This is a
        claimed-only view; no current claim does not prove prior Work completed.
        """
        with control.bound_client() as client:
            return client.current_claimed_work_detail()

    @server.tool(name="native.work_assignment")
    def work_assignment() -> dict[str, object]:
        """Read this session's pending Work, including blocked or awaiting review.

        Returns graph interfaces and claim metadata for one pending assignment.
        No assignment is not proof of completion. This read grants no execution
        permission and does not change state or select another agent's Work.
        """
        with control.bound_client() as client:
            return client.current_work_assignment()

    @server.tool(name="native.work_index")
    def work_index() -> dict[str, object]:
        """Read the full admitted Work registry, not an execution plan.

        The server returns the whole index; 4096 is a response validation cap,
        not a request limit or pagination. This read can be costly on large graphs.
        """
        with control.bound_client() as client:
            result = client.request("GET", "/api/universal/work", {"projection": "index"})
            return _validate_index(result, client)

    @server.tool(name="hosts.status")
    def hosts_status() -> dict[str, object]:
        """Read every host connector's live state and each operation's evidence.

        Read-only through the installed application: no host is opened and no
        operation runs. Each operation row says whether a real court proved it
        or names the dependency that keeps it unavailable. Host operations run
        only as graph nodes inside admitted Work (coordination.run_workshop_task);
        this server offers no raw host execution.
        """
        with control.bound_client() as client:
            return client.request("GET", "/api/universal/hosts", {})

    from .native_workshop_tools import register_artifact_tools
    register_artifact_tools(server, control)
    return server


def build_recovery_server(owner, *, workshop_task=None):
    """Keep recovery tools available until the same owner is ready for tools."""
    from mcp.server.fastmcp import FastMCP
    from .native_resume_guard import NativeResumeGuard
    server=FastMCP('ArchHub native recovery')
    guard=NativeResumeGuard(owner)
    activated=False

    def activate():
        nonlocal activated
        if activated:
            return {'status':'tools_available','work_admission_required':True}
        try:
            restored=guard.recover()
            if restored.get('status')!='owner_restored':
                return restored
            tools=build_server(session=owner,workshop_task=workshop_task)
            for tool in tools._tool_manager.list_tools():
                if tool.name not in {'native.owner_status','native.owner_recover','native.connection_recover','native.owner_inspect_effects'}:
                    server.add_tool(tool.fn,name=tool.name,description=tool.description,
                                    annotations=tool.annotations)
            activated=True
            return {'status':'tools_available','work_admission_required':True}
        except Exception:
            return {'status':'recovery_required','reason':'existing_owner_recovery_unconfirmed',
                    'work_admission_required':True}

    @server.tool(name='native.owner_status')
    def recovery_status():
        return {'owner':owner.owner_status(),'tools_available':activated,'work_admission_required':True}

    @server.tool(name='native.owner_inspect_effects')
    def recovery_inspect_effects(expected_owner: str, cursor: str | None = None):
        """Inspect exact original-actor evidence before activation; never enroll or replay."""
        return owner.inspect_enrollment(expected_owner=expected_owner,projection='effects',
            **({'cursor':cursor} if cursor is not None else {}))

    @server.tool(name='native.resume_recover')
    async def recovery_retry(ctx: Context):
        result=activate()
        if activated:
            await ctx.session.send_tool_list_changed()
        return result

    @server.tool(name='native.owner_recover')
    def exact_rebind_recovery(expected_failed_owner: str, expected_current_owner: str):
        return owner.recover_rebind_owner(expected_failed_owner=expected_failed_owner,
                                         expected_current_owner=expected_current_owner)

    @server.tool(name='native.connection_recover')
    def exact_connection_recovery(expected_owner: str):
        return owner.recover_connection(expected_owner=expected_owner)

    return server,activate


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workshop-task', metavar='WORK_ROOT',
        help='Restrict this MCP server to one configured Work and ordinary Workshop tools')
    parser.add_argument('--stop-hook-ipc',action='store_true',
        help='Host read-only Stop IPC inside this same native owner process')
    parser.add_argument('--expected-actor',help='Original graph actor from the admitted existing task binding')
    args = parser.parse_args()
    if args.expected_actor:
        owner=NativeAgentSession(expected_agent_session=args.expected_actor)
        server,activate=build_recovery_server(owner,workshop_task=args.workshop_task)
        activate()
    else:
        # Existing app-admitted fresh bootstrap precedes Work assignment and
        # has no original actor or Session Link binding yet.
        owner=NativeAgentSession()
        server=build_server(session=owner,workshop_task=args.workshop_task)
    hook=None
    try:
        if args.stop_hook_ipc:
            try:
                from .native_stop_hook import NativeStopHost
                hook=NativeStopHost(owner).start()
            except Exception:
                import sys
                print('Optional Native Stop observation unavailable; native MCP remains active.', file=sys.stderr)
        server.run(transport="stdio")
    finally:
        if hook is not None:
            try:
                hook.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
