"""Shared Workshop mailbox over MCP; Work capabilities retain their separate authority."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import os
import builtins

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from .application_machine_transport import MachineTransportError, UniversalRuntimeClient
from .installed_workshop_coordination import InstalledWorkshopCoordinationClient
from .native_agent_hooks import user_prompt_submit_context, stop_context

class _OwnedWorkshopClient(InstalledWorkshopCoordinationClient):
    def __init__(self, owner, client):
        self._native_owner = owner
        self._native_client = client
        self._native_generation = getattr(owner, "generation", None)
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
        # Work prompt hooks retain their governed actor's inbox, independently
        # of the public shared-mailbox connector (which never enters this path).
        from .installed_workshop_coordination import InstalledWorkshopInboxReader
        if method in InstalledWorkshopInboxReader.READS and getattr(self._native_owner, "needs_inbox_recovery", lambda: False)():
            return self._native_owner.inbox_reader().call(method, parameters, **kwargs)
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

class _WorkControl:
    """Only a Work/host action needs the existing governed Work identity."""
    def __init__(self, owner=None, environment=None):
        import threading
        self.owner = owner
        self.environment = environment
        self.fixed = owner is not None or environment is not None
        self.controls = {}
        self.lock = threading.RLock()
        self.control = None
        self.supervisor = None

    def selected(self):
        # This map belongs only to governed Work authority. Mailbox tools never
        # enter it, enroll an actor, or depend on its lifecycle.
        if self.fixed:
            return self
        from mcp.server.lowlevel.server import request_ctx
        try:
            metadata = _session_metadata(request_ctx.get().meta)
        except builtins.LookupError:
            return self
        if not metadata:
            return self
        key, identity = next(iter(metadata.items()))
        runtime = "codex" if key == "threadId" else "opencode"
        with self.lock:
            if (runtime, identity) not in self.controls:
                environment = dict(os.environ)
                for name in ("CODEX_THREAD_ID", "CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID", "OPENCODE_SESSION_ID", "GEMINI_SESSION_ID"):
                    environment.pop(name, None)
                environment.update(ARCHHUB_AGENT_RUNTIME=runtime, ARCHHUB_EXTERNAL_SESSION_ID=identity)
                environment["CODEX_THREAD_ID" if runtime == "codex" else "OPENCODE_SESSION_ID"] = identity
                self.controls[(runtime, identity)] = _WorkControl(environment=environment)
            return self.controls[(runtime, identity)]

    @contextmanager
    def bound_client(self):
        selected = self.selected()
        if selected is not self:
            with selected.bound_client() as client:
                yield client
            return
        self.connect()
        with self.control.bound_client() as client:
            yield client

    def connect(self):
        from .native_agent_session import NativeAgentSession
        if self.owner is None:
            self.owner = NativeAgentSession(environment=self.environment)
        if self.control is None:
            self.control = _OwnedWorkshopClient(self.owner, self.owner.connect())
            keeper = getattr(self.owner, "start_lease_keeper", None)
            if callable(keeper):
                keeper()
            # Work enforcement retains its Stop IPC; plain mailbox calls do not
            # construct this owner, start a keeper, or start a Stop host.
            if isinstance(self.owner, NativeAgentSession):
                from .native_stop_hook import StopHostSupervisor
                self.supervisor = StopHostSupervisor(self.owner)
                self.owner._stop_supervisor = self.supervisor
                self.supervisor.start()

    def call(self, method, parameters=None, **kwargs):
        selected = self.selected()
        if selected is not self:
            return selected.call(method, parameters, **kwargs)
        with self.bound_client():
            return self.control.call(method, parameters, **kwargs)

    def close(self):
        for control in self.controls.values():
            control.close()
        if self.supervisor is not None:
            self.supervisor.close()
        if self.control is not None:
            self.owner.close()


def _caller_context(ctx):
    """Host-supplied MCP session metadata, never model-visible tool arguments."""
    return _session_metadata(ctx.request_context.meta)


def _session_metadata(meta):
    values = meta.model_dump(by_alias=True) if meta is not None else {}
    keys = [key for key in ("threadId", "ai.opencode/sessionID") if key in values]
    if len(keys) > 1:
        raise ValueError("ambiguous calling session metadata")
    if not keys:
        return {}
    key = keys[0]
    value = values[key]
    if type(value) is not str or not value or "\0" in value or len(value.encode("utf-8")) > 256:
        raise ValueError("calling session metadata is invalid")
    return {key: value}


def _mailbox_call(method, body, context):
    from .cell_secret_keys import WindowsDpapiSigningKeyProvider
    local = Path(os.environ["LOCALAPPDATA"]) / "ArchHub"
    key_path = local / "keys" / "authority-signing-v1.dpapi.json"
    if not key_path.is_file():
        raise MachineTransportError("ArchHub is not running: existing signing key unavailable")
    client = UniversalRuntimeClient(local / "active-universal-runtime.json",
        WindowsDpapiSigningKeyProvider(key_path))
    verb = "POST" if method == "send" else "GET"
    return client.request(verb, "/api/universal/agent-mail/" + method, {**body, "context": context})


def build_server(*, session=None, workshop_task=None, mailbox_call=None):
    """The shared message tools are available before any Work identity is needed."""
    server = FastMCP("archhub-agent")
    call = _mailbox_call if mailbox_call is None else mailbox_call

    @server.tool(name="send")
    def send(to: str, text: str, ctx: Context) -> dict[str, object]:
        """Post to the shared Workshop room; to='*' addresses everyone.

        Use a peer's sender_label as its readable address across connector restarts.
        The application records this connection's own name. No sender override,
        binding, enrollment or relay is accepted. All room members can read it.
        """
        return call("send", {"to": to, "text": text}, _caller_context(ctx))

    @server.tool(name="read", annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def read(ctx: Context, since: int = 0) -> dict[str, object]:
        """Read shared Workshop messages after a sequence; use next_since to continue."""
        return call("read", {"since": since}, _caller_context(ctx))

    control = _WorkControl(session)
    server.work_control = control
    if session is not None:
        # An explicit in-process Work owner is already an authorised Work
        # composition. The ordinary CLI supplies none and starts unbound.
        control.connect()
    if workshop_task is not None:
        from .native_workshop_tools import build_workshop_task_server
        task = build_workshop_task_server(control, workshop_task)
        for tool in task._tool_manager.list_tools():
            if server._tool_manager.get_tool(tool.name) is None:
                server.add_tool(tool.fn, name=tool.name, description=tool.description)
    else:
        _register_work_tools(server, control)
    from .native_workshop_tools import forbid_extra_arguments
    for tool in server._tool_manager.list_tools():
        forbid_extra_arguments(tool)
    return server


def _register_work_tools(server, control):
    attached = {}

    @server.tool(name="native.hook_stop")
    def hook_stop() -> dict[str, object]:
        """Observe the current Work gate through its existing Work authority."""
        return stop_context(control)

    @server.tool(name="native.hook_user_prompt_submit")
    def hook_user_prompt_submit() -> dict[str, object]:
        """Provide bounded Work and Workshop context for a native prompt hook.

        Read-only context delivery; does not acknowledge, approve, or execute.
        Configure this on UserPromptSubmit, after MCP connection is available.
        With a Work attached, its context is shown.
        """
        return user_prompt_submit_context(control, selected=attached['held'] if attached else None)

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
        With a Work attached (native.work_task_attach), it reads that Work.
        """
        with control.bound_client() as client:
            if attached:
                return attached['held'].assignment(client)
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
        or names the dependency that keeps it unavailable. Host execution tools
        (revit_execute_csharp, max_execute_maxscript, ...) run only while this
        session holds a claimed Work (native_host_tools).
        """
        with control.bound_client() as client:
            return client.request("GET", "/api/universal/hosts", {})

    from .native_workshop_tools import register_artifact_tools
    register_artifact_tools(server, control)
    from .native_host_tools import register_host_tools
    register_host_tools(server, control)
    # Social Works (LinkedIn, Facebook Pages, Instagram): prepare for the founder's
    # approval, then execute once. The tools take only a Work root.
    from .social_connectors import register_social_tools
    register_social_tools(server, control)

    @server.tool(name='native.work_propose')
    def work_propose(title: str, description: str, priority: int, purpose: str, inputs: dict,
                     requirements: dict, container: dict, write_grants: list[dict],
                     done_when: str | None = None, depends_on: list[str] | None = None) -> dict[str, object]:
        """Propose one governed Work to the founder. Nothing is created, granted or admitted.

        The proposal is a Workshop message from this session: the Work, its inputs,
        its requirements (artifact_reviewers must be OTHER agent sessions), its CDE
        container, and write grants [{path, scope: exact|descendants, operations}],
        one per governed root. The founder binds it, with any others he checks, in
        one action; only then does the Work exist and its grants apply.
        """
        from .work_proposals import parse, planned_payload, render
        text = render(planned_payload(title, description, priority, purpose, inputs, requirements,
                      container, write_grants, done_when=done_when, depends_on=depends_on))
        _payload, digest = parse(text)
        with control.bound_client() as client:
            if client.agent_session_root in (requirements.get('artifact_reviewers') or ()):
                raise MachineTransportError('The proposing agent cannot review its own proposed Work')
            # An ordinary Workshop note to the room, which the founder reads whole.
            sent = client.request('POST', '/api/universal/workshop', {
                'category': 'note', 'text': text, 'refs': [], 'evidence': [], 'recipients': [],
                'reply_to': None, 'idempotency_key': 'work-proposal:' + digest[:40], 'created_at': None})
        if type(sent) is not dict or type(sent.get('message_id')) is not str:
            raise MachineTransportError('The Workshop did not confirm the proposal; read it before proposing again')
        return {'message_id': sent['message_id'], 'sequence': sent.get('sequence'), 'digest': digest,
                'state': 'proposed', 'work_created': False, 'grants_admitted': False}

    @server.tool(name='native.work_plan_import')
    def work_plan_import(rows: list[dict], container: dict, write_grants: list[dict]) -> dict[str, object]:
        """Import plan JSON rows as idempotent unbound Work proposals.

        Rows are keyed by (item, task_no). Re-running the same plan posts no new
        proposals. Nothing is granted and no Work is created until the founder binds.
        """
        from .work_proposals import parse, plan_idempotency_key, plan_row_payload, render
        if type(rows) is not list or len(rows) > 500:
            raise MachineTransportError('Plan import expects a list of at most 500 rows')
        created, existing, proposals = 0, 0, []
        with control.bound_client() as client:
            for row in rows:
                payload = plan_row_payload(row, container=container, write_grants=write_grants)
                text = render(payload)
                _payload, digest = parse(text)
                sent = client.request('POST', '/api/universal/workshop', {
                    'category': 'note', 'text': text, 'refs': [], 'evidence': [], 'recipients': [],
                    'reply_to': None,
                    'idempotency_key': plan_idempotency_key(payload['inputs']['item'], payload['inputs']['task_no']),
                    'created_at': None})
                if type(sent) is not dict or type(sent.get('message_id')) is not str:
                    raise MachineTransportError('The Workshop did not confirm imported plan row')
                if type(sent.get('created')) is not bool or type(sent.get('existing')) is not bool:
                    raise MachineTransportError('The Workshop did not report imported plan idempotency')
                item = {'message_id': sent['message_id'], 'sequence': sent.get('sequence'), 'digest': digest,
                        'item': payload['inputs']['item'], 'task_no': payload['inputs']['task_no'],
                        'title': payload['title'], 'created': sent['created'], 'existing': sent['existing']}
                proposals.append(item)
                if sent['existing']:
                    existing += 1
                else:
                    created += 1
        return {'ok': True, 'created': created, 'existing': existing, 'count': len(proposals),
                'proposals': proposals, 'work_created': False, 'grants_admitted': False}

    @server.tool(name='native.work_proposals')
    def work_proposals() -> dict[str, object]:
        """Read which of this session's recent proposals the founder has bound, and to what Work."""
        from .work_proposals import KEY_PREFIX, MARKER
        with control.bound_client() as client:
            me = client.agent_session_root
            index = client.request('GET', '/api/universal/work', {'projection': 'index'})
        bound = {}
        for row in index.get('items') or ():
            key = ((row.get('interfaces') or {}).get('external-key') or {}).get('value')
            if type(key) is str and key.startswith(KEY_PREFIX):
                bound[key[len(KEY_PREFIX):]] = row.get('root')
        page = control.call('read_messages', {'limit': 50, 'before': None})
        rows = [{'message_id': entry['message_id'], 'sequence': entry['sequence'],
                 'work_root': bound.get(entry['message_id']),
                 'state': 'bound' if entry['message_id'] in bound else 'proposed'}
                for entry in page.get('entries') or ()
                if entry.get('actor') == me and str(entry.get('summary') or '').startswith(MARKER)]
        return {'agent_session': me, 'proposals': rows}

    # One Work's task surface on this same bound owner (live 717, 2026-09-30): the
    # tools a --workshop-task launch has, for one exact Work at a time, with no second
    # MCP, no re-enrollment and no raw route. The held Work keeps its uncertain
    # effects for work_reconcile, and detaches only when none is unresolved.
    attached = {}

    @server.tool(name='native.work_task_attach')
    async def work_task_attach(work_root: str, ctx: Context) -> dict[str, object]:
        """Attach one Work's task tools (claim, submit, court, reconcile) to this session.

        One exact assembly-instance root at a time; another is refused until
        native.work_task_detach. Another session's claimed Work is refused. It
        grants nothing: the application still decides every claim, submission
        and court. Nothing is enrolled or replayed.
        """
        from .native_workshop_tools import (
            build_workshop_task_server, forbid_extra_arguments, validate_selected_work,
        )
        validate_selected_work(work_root)
        if control.selected() is not control:
            raise MachineTransportError('Use a dedicated Work profile for dynamic task tools')
        if attached:
            raise MachineTransportError('Work %s is already attached; detach it first' % attached['held'].root)
        with control.bound_client() as client:
            actor = client.agent_session_root
            index = _validate_index(client.request('GET', '/api/universal/work', {'projection': 'index'}), client)
        rows = [row for row in index['items'] if row['root'] == work_root]
        if len(rows) != 1:
            raise MachineTransportError('Work %s is not a registered Work' % work_root)
        if rows[0]['claimant_session'] not in (None, actor):
            raise MachineTransportError('Work %s is claimed by another session; only its claimant '
                                        'attaches its task tools' % work_root)
        task = build_workshop_task_server(control, work_root)
        target = ctx.fastmcp
        present = {tool.name for tool in target._tool_manager.list_tools()}
        added = []
        for tool in task._tool_manager.list_tools():
            if tool.name in present:
                continue  # the general tool this server already has stays as it is
            target.add_tool(tool.fn, name=tool.name, description=tool.description,
                            annotations=tool.annotations)
            forbid_extra_arguments(target._tool_manager.get_tool(tool.name))
            added.append(tool.name)
        attached.update(held=task.selected_work, names=added, server=target)
        await ctx.session.send_tool_list_changed()
        return {'work_root': work_root, 'agent_session': actor, 'tools_added': sorted(added)}

    @server.tool(name='native.work_task_detach')
    async def work_task_detach(ctx: Context) -> dict[str, object]:
        """Detach the attached Work's task tools, only when none of its responses is unresolved.

        After an uncertain claim, submission or court, run native.work_reconcile
        first; the Work stays attached until it reconciles. Nothing is replayed.
        """
        if control.selected() is not control:
            raise MachineTransportError('Use a dedicated Work profile for dynamic task tools')
        if not attached:
            raise MachineTransportError('No Work task surface is attached')
        held = attached['held']
        with held._effect_lock:
            if held.pending is not None:
                raise MachineTransportError(
                    'The attached Work has an unresolved %s response; run native.work_reconcile '
                    'first. Nothing was detached.' % held.pending[0])
            for name in attached['names']:
                attached['server'].remove_tool(name)
            attached.clear()
        await ctx.session.send_tool_list_changed()
        return {'work_root': held.root, 'detached': True}



def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workshop-task")
    args = parser.parse_args()
    server = build_server(workshop_task=args.workshop_task)
    try:
        server.run(transport="stdio")
    finally:
        server.work_control.close()


if __name__ == "__main__":
    main()
