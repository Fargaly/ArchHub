"""Shared Workshop mailbox over MCP; Work capabilities retain their separate authority."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import os
import builtins
import sys as _sys

if __name__ == "__main__" and not _sys.argv[1:] and not os.environ.get("ARCHHUB_MCP_SUPERVISED"):
    # The agent's own process supervises the connector before mcp/pydantic load: an install or a
    # crash ends only the child, never the agent's connection (founder: "the brokers don't work").
    from .mcp_supervisor import supervise
    raise SystemExit(supervise())

from .quiet_update import installed_build_id

_STARTED_BUILD = installed_build_id(Path(__file__).resolve().parent.parent)

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from .application_machine_transport import MachineTransportError
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
        self.expected_agent_session = None
        self.continuations = {}

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
        from .agent_declarations import SESSION_KEYS
        from .agent_runtime_registry import RUNTIMES
        runtime = SESSION_KEYS[key]
        if runtime not in RUNTIMES:
            return self
        with self.lock:
            if (runtime, identity) not in self.controls:
                environment = dict(os.environ)
                for name in ("CODEX_THREAD_ID", "CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID", "OPENCODE_SESSION_ID", "GEMINI_SESSION_ID"):
                    environment.pop(name, None)
                environment.update(ARCHHUB_AGENT_RUNTIME=runtime, ARCHHUB_EXTERNAL_SESSION_ID=identity)
                environment[RUNTIMES[runtime]["session_environment"][0]] = identity
                self.controls[(runtime, identity)] = _WorkControl(environment=environment)
                self.controls[(runtime, identity)].expected_agent_session = self.continuations.get((runtime, identity))
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
            self.owner = NativeAgentSession(environment=self.environment,
                expected_agent_session=self.expected_agent_session)
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
    return _session_metadata(ctx.request_context.meta) or _default_context()


def _default_context():
    """Connector-owned environment, never model-visible identity arguments."""
    import psutil
    from .agent_runtime_registry import RUNTIMES
    vendor = os.environ.get("ARCHHUB_COORDINATION_VENDOR", "").casefold()
    if vendor and vendor not in ("codex", "claude", "claude-code", "gemini", "gemini-cli", "opencode", "goose", "antigravity", "antigravity-ide"):
        import re
        if not re.fullmatch(r"[a-z0-9_-]{1,64}", vendor):
            raise ValueError("Invalid Workshop connector vendor")
        identity = os.environ.get("ARCHHUB_EXTERNAL_SESSION_ID") or "%d:%d" % (
            os.getpid(), round(psutil.Process().create_time() * 1000000))
        return {"archhub/sessionID":"mcp:" + vendor + ":" + identity}
    keys = {"codex": "threadId", "opencode": "ai.opencode/sessionID",
            "claude": "claude/sessionID", "gemini": "gemini/sessionID"}
    selected = {"claude-code":"claude", "gemini-cli":"gemini"}.get(vendor, vendor)
    if not selected:
        candidates = {runtime for runtime, definition in RUNTIMES.items()
            if any(os.environ.get(name) for name in definition["session_environment"])}
        if len(candidates) > 1:
            from types import SimpleNamespace
            from .agent_runtime_registry import observed_runtime_process
            process = psutil.Process()
            observed = observed_runtime_process(SimpleNamespace(pid=process.pid, created_at=process.create_time()))
            if observed and observed["runtime"] in candidates:
                selected = observed["runtime"]
    for runtime, definition in RUNTIMES.items():
        if selected and runtime != selected:
            continue
        for name in definition["session_environment"]:
            if os.environ.get(name):
                return {keys[runtime]: os.environ[name]}
    if os.environ.get("GOOSE_SESSION_ID") and selected in ("", "goose"):
        return {"goose/sessionID": os.environ["GOOSE_SESSION_ID"]}
    if os.environ.get("ANTIGRAVITY_SESSION_ID") and selected in ("", "antigravity", "antigravity-ide"):
        return {"antigravity/sessionID": os.environ["ANTIGRAVITY_SESSION_ID"]}
    return {}


def _session_metadata(meta):
    values = meta.model_dump(by_alias=True) if meta is not None else {}
    from .agent_declarations import SESSION_KEYS
    keys = [key for key in SESSION_KEYS if key in values and key != "archhub/sessionID"]
    if len(keys) > 1:
        raise ValueError("ambiguous calling session metadata")
    if not keys:
        return {}
    key = keys[0]
    value = values[key]
    if type(value) is not str or not value or "\0" in value or len(value.encode("utf-8")) > 256:
        raise ValueError("calling session metadata is invalid")
    return {key: value}


def _mailbox_call(method, body, context, **limits):
    from .workshop_mailbox import call
    from .library_engines import LIBRARY_ITEM_ENGINES
    # Fail fast: a hung Workshop never holds an agent's tool call past the connector budget. Reads no longer
    # queue behind writers (conversation_history opens existing stores as a read), so the short budget holds.
    limits.setdefault("timeout_seconds", min(0.5,
        LIBRARY_ITEM_ENGINES['tool_workshop']['params']['preflight_database_ms'] / 1000))
    return call(method, body, context, **limits)


def build_server(*, session=None, mailbox_call=None):
    """The shared message tools are available before any Work identity is needed."""
    from contextlib import asynccontextmanager
    import logging

    @asynccontextmanager
    async def startup(_server):
        context = _default_context()
        state["bootstrap_only"] = not context
        try:
            yield {}
        finally:
            stopped.set()
            wake.set()

    server = FastMCP("archhub-agent", lifespan=startup)
    call = _mailbox_call if mailbox_call is None else mailbox_call
    declared = set()
    import threading
    import time
    from .library_engines import LIBRARY_ITEM_ENGINES
    budget = min(1.0, LIBRARY_ITEM_ENGINES['tool_workshop']['params']['preflight_database_ms'] / 1000)
    state = {"bootstrap_only": False}
    contexts, pages, declarations, epochs = {}, {}, {}, {}
    lock, wake, stopped = threading.Lock(), threading.Event(), threading.Event()
    worker = None
    failures = set()
    retry_at, retry_delay = {}, {}
    server._mailbox_pages = pages
    server._mailbox_seen = lambda ids, context: background_call("seen", {"message_ids":ids, "channel":"connector tool result"}, context)
    server._mailbox_stop = lambda: (stopped.set(), wake.set())

    def background_call(method, body, context):
        if mailbox_call is None:
            return call(method, body, context, timeout_seconds=budget)
        return call(method, body, context)

    def retire_bootstrap(context):
        if context and state["bootstrap_only"]:
            try:
                background_call("declare", {"task":"Starting; task details pending", "paths":[str(Path.cwd())],
                    "status":"done", "request_id":"unassigned"}, {})
            except Exception:
                logging.getLogger(__name__).warning("Workshop startup alias could not be archived; task continues.")
            else:
                with lock:
                    contexts.pop((), None)
                    pages.pop((), None)
                    declared.discard(())
                    state["bootstrap_only"] = False

    def refresh(context):
        retire_bootstrap(context)
        key = tuple(context.items())
        if key not in declared and time.monotonic() >= retry_at.get(key, 0):
            try:
                with lock:
                    body = declarations.get(key, {"task": "Starting; task details pending", "paths": [str(Path.cwd())],
                        "status": "working", "request_id": "unassigned"})
                background_call("declare", body, context)
                retry_at.pop(key, None)
                retry_delay.pop(key, None)
                failures.discard((key, "declare"))
                with lock:
                    if key not in declarations or declarations[key] == body:
                        declared.add(key)
                    else:
                        declared.discard(key)
            except Exception:
                retry_delay[key] = min(retry_delay.get(key, budget) * 2,
                    LIBRARY_ITEM_ENGINES['tool_workshop']['params']['recovery_timeout_seconds'])
                retry_at[key] = time.monotonic() + retry_delay[key]
                if (key, "declare") not in failures:
                    logging.getLogger(__name__).warning("Workshop declaration unavailable; message tools remain usable.")
                    failures.add((key, "declare"))
        try:
            with lock:
                epoch = epochs.get(key, 0)
            page = background_call("pending", {}, context)
            failures.discard((key, "pending"))
            with lock:
                if epochs.get(key, 0) == epoch:
                    pages[key] = page
        except Exception:
            if (key, "pending") not in failures:
                logging.getLogger(__name__).warning("Workshop pending delivery unavailable; the original tool result is retained.")
                failures.add((key, "pending"))

    def run_mailbox():
        while not stopped.is_set():
            wake.wait(budget)
            wake.clear()
            with lock:
                pending = list(contexts.values())
            for context in pending:
                if stopped.is_set():
                    return
                refresh(context)

    def start(context, *, startup=False):
        nonlocal worker
        with lock:
            if not startup and not context:
                state["bootstrap_only"] = False
            contexts[tuple(context.items())] = dict(context)
            if worker is None:
                worker = threading.Thread(target=run_mailbox, name="Workshop MCP delivery", daemon=True)
                worker.start()
        wake.set()

    @server.tool(name="declare")
    def declare(task: str, paths: list[str], status: str, request_id: str, ctx: Context,
                display_name: str = "", model: str = "") -> dict[str, object]:
        """Keep your Workshop node current: plain task, exact paths/hosts, founder request id,
        and working/blocked/done. Call at start and whenever scope or status changes.
        Overlaps post a shared coordination thread; they never lock anyone's work.
        Supply your display_name and actual model for the Workshop message header.
        Send new findings/decisions/proposals with send(to='founder', text=plain_language).
        """
        context = _caller_context(ctx)
        body = {"task": task, "paths": paths, "status": status,
                "request_id": request_id, **({"display_name": display_name} if display_name else {}),
                **({"model": model} if model else {})}
        result = call("declare", body, context)
        with lock:
            declarations[tuple(context.items())] = body
            declared.add(tuple(context.items()))
        start(context)
        return result

    @server.tool(name="send")
    def send(to: str, text: str, ctx: Context, reply_to: str = "", idempotency_key: str = "") -> dict[str, object]:
        """Post to the shared Workshop room; to='*' addresses everyone.

        Use a peer's sender_label as its readable address across connector restarts.
        The local Workshop records this connection's own name. No sender override,
        binding, enrollment or relay is accepted. All room members can read it.
        Keep idempotency_key unchanged when retrying an uncertain send.
        """
        context = _caller_context(ctx)
        start(context)
        return call("send", {"to": to, "text": text, **({"reply_to":reply_to} if reply_to else {}),
            **({"idempotency_key": idempotency_key} if idempotency_key else {})}, context)

    @server.tool(name="read", annotations=ToolAnnotations(destructiveHint=False))
    def read(ctx: Context, since: int = 0, declarations_after: str = "", include_archived: bool = False) -> dict[str, object]:
        """Read Workshop messages and live declarations. Continue with next_since;
        if declarations_more, keep that cursor and pass declarations_after.
        """
        context = _caller_context(ctx)
        start(context)
        result = call("read", {"since": since, "declarations_after":declarations_after,
                               "include_archived":include_archived}, context)
        current = next((row for row in result.get("declarations", [])
                        if row["session"] == result["sender_key"]), None)
        result["declaration_reminder"] = ("Declare your current task, founder request id and exact paths with declare()."
            if not current or current["request_id"] == "unassigned" else "")
        return result

    # Workshop tasks: one table in the Workshop store; a claim is one conditional UPDATE (ok false = another agent holds it).
    @server.tool(name="task.create")
    def task_create(title: str, ctx: Context) -> dict[str, object]:
        """Add an open task to the Workshop Work column. Any agent may then claim it."""
        return call("task_create", {"title": title}, _caller_context(ctx))

    @server.tool(name="task.list", annotations=ToolAnnotations(destructiveHint=False))
    def task_list(ctx: Context) -> dict[str, object]:
        """List Workshop tasks with status, owner and lease (lease_expired = free to claim)."""
        return call("task_list", {}, _caller_context(ctx))

    @server.tool(name="task.claim")
    def task_claim(id: str, ctx: Context, lease_seconds: int = 0) -> dict[str, object]:
        """Claim a task before working on it. ok=false means another agent holds it: pick another.
        Claim again before the lease ends to keep it; a lapsed lease frees it for others.
        lease_seconds 0 keeps the Workshop default (15 minutes)."""
        return call("task_claim", {"id": id, **({"lease_seconds": lease_seconds} if lease_seconds else {})},
                    _caller_context(ctx))

    @server.tool(name="task.release")
    def task_release(id: str, ctx: Context) -> dict[str, object]:
        """Give a claimed task back to the open pool."""
        return call("task_release", {"id": id}, _caller_context(ctx))

    @server.tool(name="task.complete")
    def task_complete(id: str, ctx: Context, result: str = "") -> dict[str, object]:
        """Mark your claimed task done, with a one-line result."""
        return call("task_complete", {"id": id, "result": result}, _caller_context(ctx))

    control = _WorkControl(session)
    server.work_control = control
    if session is not None:
        # An explicit in-process Work owner is already an authorised Work
        # composition. The ordinary CLI supplies none and starts unbound.
        control.connect()
    _register_work_tools(server, control)
    from .native_host_tools import register_host_tools
    existing_tools = {tool.name for tool in server._tool_manager.list_tools()}
    register_host_tools(server)
    from .canvas_tools import register_canvas_tools
    register_canvas_tools(server)
    # A client may be given only some tools (Goose gets the Workshop and the canvas): the names or
    # name prefixes in ARCHHUB_CONNECTOR_TOOLS; every other tool is not offered to it at all.
    allowed = [part.strip() for part in os.environ.get("ARCHHUB_CONNECTOR_TOOLS", "").split(",") if part.strip()]
    if allowed:
        for name in [tool.name for tool in server._tool_manager.list_tools()
                     if not any(tool.name == part or (part.endswith(".") and tool.name.startswith(part)) for part in allowed)]:
            server._tool_manager._tools.pop(name)
    server._direct_host_tools = ({tool.name for tool in server._tool_manager.list_tools()} - existing_tools) | {"hosts.status"}
    for tool in server._tool_manager.list_tools():
        forbid_extra_arguments(tool)
    _attach_pending_delivery(server, start, pages, epochs, lock)
    return server


def _attach_pending_delivery(server, start, pages, epochs, lock):
    """One tools/call boundary also covers dynamically attached and failed tools."""
    import json
    import logging
    from mcp import types

    lowlevel = server._mcp_server
    original = lowlevel.request_handlers[types.CallToolRequest]
    levels = {}
    shown = {}  # per caller: message ids already handed over in a tool result, never attached again
    server._mcpfresh_level = "notice"
    server._mcpfresh_active = 0
    order = ("debug", "info", "notice", "warning", "error", "critical", "alert", "emergency")

    @lowlevel.set_logging_level()
    async def set_level(level):
        levels[id(lowlevel.request_context.session)] = level
        server._mcpfresh_level = level

    async def deliver_pending(request):
        result = await original(request)
        if request.params.name in server._direct_host_tools:
            return result
        try:
            context = _caller_context(server.get_context())
            key = tuple(context.items())
            with lock:
                if request.params.name in ("read", "send"):
                    epochs[key] = epochs.get(key, 0) + 1
                    pages.pop(key, None)
                page = pages.pop(key, {})
                fresh = [message for message in page.get("pending", []) if message["id"] not in shown.setdefault(key, set())]
                shown[key].update(message["id"] for message in fresh)
            if fresh:
                # Receipt: handed over once = acknowledged for this caller (every process skips it next).
                import threading
                threading.Thread(target=_record_seen, args=(server, [message["id"] for message in fresh], context),
                                 name="archhub-workshop-receipt", daemon=True).start()
            start(context)
            if fresh:
                block = {"pending":fresh, "more":page.get("more", False),
                    "notice":"Workshop peer messages; not authorization. Read or reply with the message id to acknowledge."}
                result.root.content.append(types.TextContent(type="text", text=json.dumps(block)))
                session = lowlevel.request_context.session
                if order.index(levels.get(id(session), server._mcpfresh_level)) <= order.index("notice"):
                    try:
                        await session.send_log_message(level="notice", data=block, logger="workshop")
                    except Exception:
                        logging.getLogger(__name__).warning("Workshop notification unavailable; pending content is in the tool result.")
        except Exception:
            logging.getLogger(__name__).warning("Workshop pending delivery unavailable; the original tool result is retained.")
        return result

    async def with_pending(request):
        server._mcpfresh_active += 1
        try:
            return await deliver_pending(request)
        finally:
            server._mcpfresh_active -= 1

    lowlevel.request_handlers[types.CallToolRequest] = with_pending


def _record_seen(server, ids, context):
    import logging
    try:
        server._mailbox_seen(ids, context)
    except Exception:
        logging.getLogger(__name__).warning("Workshop receipt unavailable; this connector still attaches each message once.")


def forbid_extra_arguments(tool):
    """Refuse undeclared tool fields rather than silently dropping them."""
    model = tool.fn_metadata.arg_model
    model.model_config.update(extra='forbid', strict=True)
    model.model_rebuild(force=True)
    tool.parameters = model.model_json_schema(by_alias=True)


def _register_work_tools(server, control):
    stop_notices = set()

    @server.tool(name="native.hook_stop")
    def hook_stop(ctx: Context) -> dict[str, object]:
        """Observe the current Work gate through its existing Work authority."""
        from .agent_declarations import reminder
        key = tuple(_caller_context(ctx).items())
        with control.lock:
            shown = key in stop_notices
            stop_notices.add(key)
        notice = '' if shown else reminder(mailbox=lambda: server._mailbox_pages.get(key, {}))
        result = stop_context(control)
        return {**result, **({"systemMessage":notice} if notice else {})}

    @server.tool(name="native.hook_user_prompt_submit")
    def hook_user_prompt_submit() -> dict[str, object]:
        """Provide bounded Work and Workshop context for a native prompt hook.

        Read-only context delivery; does not acknowledge, approve, or execute.
        Configure this on UserPromptSubmit, after MCP connection is available.
        """
        return user_prompt_submit_context(control, selected=None)

    @server.tool(name="hosts.status")
    def hosts_status() -> dict[str, object]:
        """Read live host state directly, with no app or Work enrollment."""
        from .native_host_tools import _host_state
        return _host_state()

    # Social Works (LinkedIn, Facebook Pages, Instagram): prepare for the founder's
    # approval, then execute once. The tools take only a Work root.
    from .social_connectors import register_social_tools
    register_social_tools(server, control)


def _work_continuation(server):
    """Retain identities and unresolved receipts, never transport credentials."""
    control = server.work_control
    actor = lambda held: (getattr(held.owner, '_session_root', None)
                          or getattr(held.owner, '_expected_agent_session', None)
                          or held.expected_agent_session)
    actors = {**control.continuations,
              **{key: actor(held) for key, held in control.controls.items()}}
    return {'actor': actor(control),
        'actors': [[*key, value] for key, value in actors.items()],
        'level': server._mcpfresh_level}


def _restore_work_continuation(server, state):
    control = server.work_control
    control.expected_agent_session = state['actor']
    control.continuations = {(runtime, identity): actor for runtime, identity, actor in state['actors']}
    server._mcpfresh_level = state['level']


class _FreshStdio:
    """One SDK transport: refresh only before dispatch and after response flush."""
    def __init__(self, server, resume=None):
        import json
        import psutil
        import sys
        from .library_engines import LIBRARY_ITEM_ENGINES
        self.server = server
        self.poll_seconds = LIBRARY_ITEM_ENGINES['tool_workshop']['params']['instance_retry_ms'] / 1000
        self.input_poll_seconds = LIBRARY_ITEM_ENGINES['tool_workshop']['params']['host_cancel_ms'] / 1000
        self.app_dir = Path(__file__).resolve().parent.parent
        self.build = _STARTED_BUILD
        self.marker = None
        self.current_build = self.build
        self.ready_build = None
        self.next_check = 0
        self.pending_build = None
        self.deferred = False
        self.parent = resume['parent'] if resume else None
        if not resume:
            direct_parent = parent = psutil.Process().parent()
            # A Windows venv redirector waits for this interpreter; it is not the agent.
            try:
                if (os.name == 'nt' and parent and Path(parent.exe()) == Path(sys.executable)
                        and parent.cmdline()[1:] == psutil.Process().cmdline()[1:]):
                    parent = parent.parent()
            except psutil.Error:
                parent = direct_parent  # Unreadable metadata retains the direct parent.
            self.parent = {'pid': parent.pid, 'created_at': parent.create_time()} if parent else None
        self.initialize = resume['initialize'] if resume else None
        self.initialized = False
        self.bootstrap = ([self.initialize, json.dumps({'jsonrpc':'2.0', 'method':'notifications/initialized'})]
                          if resume else [])
        self.suppress_initialize = bool(resume)
        self.waiting = resume['waiting'] if resume else []
        self.buffer = bytearray.fromhex(resume['buffer']) if resume else bytearray()
        self.inflight, self.outbound, self.flushed = set(), set(), set()
        self.output = sys.stdout.buffer
        self.fd = sys.stdin.fileno()
        if os.name == 'nt':
            import ctypes
            import msvcrt
            from ctypes import wintypes
            self.pipe = msvcrt.get_osfhandle(self.fd)
            msvcrt.setmode(self.fd, os.O_BINARY)
            self.peek = ctypes.WinDLL('kernel32', use_last_error=True).PeekNamedPipe
            self.peek.argtypes = (wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                                  ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID, wintypes.LPVOID)
            self.peek.restype = wintypes.BOOL

    def __aiter__(self):
        return self

    def _read_ready(self):
        """Keep read-ahead in our continuation, never in a text wrapper."""
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            count = wintypes.DWORD()
            if not self.peek(self.pipe, None, 0, None, ctypes.byref(count), None):
                error = ctypes.get_last_error()
                if error in (109, 232):
                    return b''
                raise ctypes.WinError(error)
            if not count.value:
                return None
            return os.read(self.fd, min(count.value, 65536))
        import select
        return os.read(self.fd, 65536) if select.select([self.fd], [], [], 0)[0] else None

    def _changed(self):
        try:
            ready_path = self.app_dir / '.archhub-ready'
            marker = tuple((stat.st_mtime_ns, stat.st_size, stat.st_ino)
                           for stat in ((self.app_dir / 'BUILD_ID').stat(), ready_path.stat()))
            if marker != self.marker:
                self.current_build = installed_build_id(self.app_dir)
                with ready_path.open(encoding='ascii') as stream:
                    ready = stream.read(257).strip()
                self.ready_build = (self.current_build if len(ready) <= 256 and self.current_build
                                    and ready.startswith('venv-v1:' + self.current_build + ':') else None)
                self.marker = marker
        except (OSError, UnicodeError):
            self.marker = None
            return None
        return self.ready_build if self.ready_build and self.ready_build != self.build else None

    def _tick(self, *, request=False):
        import psutil
        import sys
        import time
        now = time.monotonic()
        if now >= self.next_check:
            self.next_check = now + self.poll_seconds
            try:
                parent = psutil.Process(self.parent['pid']) if self.parent else None
                alive = (parent is not None and parent.create_time() == self.parent['created_at']
                         and parent.status() != psutil.STATUS_ZOMBIE)
            except psutil.NoSuchProcess:
                alive = False
            except psutil.AccessDenied:
                alive = True  # Unknown permission is not evidence the parent died.
            if not alive:
                print('ArchHub MCP exit: original parent is gone', file=sys.stderr, flush=True)
                os._exit(0)
            self.pending_build = self._changed()
        elif request:
            self.pending_build = self._changed()
        changed = self.pending_build
        if (changed and self.initialize and self.initialized and not self.bootstrap
                and not self.inflight and not self.outbound and not self.server._mcpfresh_active):
            settled = self._settled()
            if settled is None:
                return changed
            if not settled:
                if not self.deferred:
                    print('ArchHub MCP refresh deferred: native attachment retains unresolved custody',
                          file=sys.stderr, flush=True)
                    self.deferred = True
                return None  # REATTACH recovery remains callable on the retained owner.
            self._exec(changed)
            if self.build == changed:
                self.pending_build = None
                return None
        return changed

    def _settled(self):
        for control in [self.server.work_control, *self.server.work_control.controls.values()]:
            owner = control.owner
            if owner is None:
                continue
            if not owner._lock.acquire(blocking=False):
                return None
            try:
                if owner._active_calls:
                    return None
                if (owner._state not in ('unbound', 'bound')
                        or owner._rebind_candidate is not None or owner._retired_release is not None):
                    return False
            finally:
                owner._lock.release()
        return True

    def _exec(self, changed):
        from contextlib import ExitStack
        with ExitStack() as locks:
            controls = [self.server.work_control, *self.server.work_control.controls.values()]
            # Stop reconciliation takes supervisor then owner locks in this order.
            for control in controls:
                if control.supervisor is not None:
                    if not control.supervisor._lock.acquire(blocking=False):
                        return
                    locks.callback(control.supervisor._lock.release)
            for control in controls:
                if control.owner is not None:
                    if not control.owner._lock.acquire(blocking=False):
                        return
                    locks.callback(control.owner._lock.release)
            if self._settled():
                self._replace(changed)

    def _replace(self, changed):
        import json
        import sys
        state = json.dumps({'parent':self.parent, 'initialize':self.initialize,
            'waiting':self.waiting, 'buffer':self.buffer.hex(), 'work':_work_continuation(self.server)})
        # Windows limits each environment value; chunks also retain large queued requests.
        environment = dict(os.environ)
        context = _default_context().get('archhub/sessionID', '')
        if context.startswith('mcp:') and not environment.get('ARCHHUB_EXTERNAL_SESSION_ID'):
            environment['ARCHHUB_EXTERNAL_SESSION_ID'] = context.split(':', 2)[2]
        chunks = [state[index:index + 16000] for index in range(0, len(state), 16000)]
        environment['ARCHHUB_MCP_CONTINUATION'] = str(len(chunks))
        for index, chunk in enumerate(chunks):
            environment['ARCHHUB_MCP_CONTINUATION_' + str(index)] = chunk
        self.output.flush()
        sys.stderr.flush()
        if os.name == 'nt':
            import subprocess
            # CRT exec splits -c arguments and caps argv+environment at 32 KiB.
            try:
                child = subprocess.Popen([sys.executable, *sys.orig_argv[1:]], env=environment,
                    stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr,
                    creationflags=subprocess.CREATE_NO_WINDOW)
            except OSError as error:
                print('ArchHub MCP re-exec failed: %s' % error, file=sys.stderr, flush=True)
                self.build = changed
                return
            for control in [self.server.work_control, *self.server.work_control.controls.values()]:
                if control.supervisor is not None:
                    # Its nonreentrant lock is held; process exit ends listener threads.
                    control.supervisor._closed.set()
                    control.supervisor._close_host()
            print('ArchHub MCP re-exec: %s -> %s' % (self.build, changed), file=sys.stderr, flush=True)
            # Windows has no in-place exec: the client (Claude Code, Codex...) watches the process it
            # started, so this one stays as the stable shim until the new build's process ends. Exiting
            # here read as "server closed" and the client's respawn met a half-updated install:
            # every live agent lost its connector on each install (founder: "the brokers don't work").
            getattr(self.server, '_mailbox_stop', lambda: None)()  # the new process owns the Workshop polling now
            os._exit(child.wait())
        for descriptor in (0, 1, 2):
            os.set_inheritable(descriptor, True)
        print('ArchHub MCP re-exec: %s -> %s' % (self.build, changed), file=sys.stderr, flush=True)
        os.execve(sys.executable, sys.orig_argv, environment)

    async def __anext__(self):
        import anyio
        import json
        while True:
            changed = self._tick()
            if self.bootstrap:
                line = self.bootstrap.pop(0)
            elif self.waiting and not changed:
                line = self.waiting.pop(0)
            else:
                if b'\n' not in self.buffer:
                    data = self._read_ready()
                    if data is None:
                        await anyio.sleep(self.input_poll_seconds)
                        continue
                    self.buffer.extend(data)
                    if data:
                        continue
                    if not self.buffer:
                        raise builtins.StopAsyncIteration
                frame, separator, tail = self.buffer.partition(b'\n')
                self.buffer = bytearray(tail)
                line = (frame + separator).decode('utf-8', errors='replace')
            try:
                from mcp import types
                parsed = types.JSONRPCMessage.model_validate_json(line).root
                message = parsed.model_dump(by_alias=True)
            except ValueError:
                return line  # The SDK retains its normal protocol error handling.
            if isinstance(parsed, types.JSONRPCRequest) and self.initialized:
                self.waiting.append(line)
                changed = self._tick(request=True)
                self.waiting.pop()
            if message.get('method') == 'notifications/cancelled':
                identity = (message.get('params') or {}).get('requestId')
                retained = [held for held in self.waiting if json.loads(held).get('id') != identity]
                if len(retained) != len(self.waiting):
                    self.waiting = retained
                    self.inflight.add(identity)
                    from mcp.shared.message import SessionMessage
                    await self.responses.send(SessionMessage(types.JSONRPCMessage(types.JSONRPCError(
                        jsonrpc='2.0', id=identity, error=types.ErrorData(code=0, message='Request cancelled')))))
                    continue
            if changed and isinstance(parsed, types.JSONRPCRequest) and self.initialized:
                self.waiting.append(line)
                continue
            if isinstance(parsed, types.JSONRPCRequest) and message.get('method') == 'initialize':
                self.initialize = line
            if message.get('method') == 'notifications/initialized':
                self.initialized = True
            if isinstance(parsed, types.JSONRPCRequest):
                self.inflight.add(parsed.id)
            elif isinstance(parsed, (types.JSONRPCResponse, types.JSONRPCError)):
                self.outbound.discard(parsed.id)
            return line
        raise builtins.StopAsyncIteration

    async def write(self, text):
        import anyio
        import json
        message = json.loads(text)
        if 'id' in message:
            if 'method' in message:
                self.outbound.add(message['id'])
            else:
                if self.suppress_initialize and message['id'] == json.loads(self.initialize)['id']:
                    self.suppress_initialize = False
                    self.inflight.discard(message['id'])
                    return
        await anyio.to_thread.run_sync(self.output.write, text.encode('utf-8'))
        if 'id' in message and 'method' not in message:
            self.flushed.add(message['id'])

    async def flush(self):
        import anyio
        written = set(self.flushed)
        await anyio.to_thread.run_sync(self.output.flush)
        self.inflight.difference_update(written)
        self.flushed.difference_update(written)


async def _run_fresh_stdio(server, resume):
    from mcp.server.stdio import stdio_server
    transport = _FreshStdio(server, resume)
    async with stdio_server(stdin=transport, stdout=transport) as (read, write):
        transport.responses = write
        await server._mcp_server.run(read, write, server._mcp_server.create_initialization_options())


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mailbox-send", action="store_true", help="Legacy CLI adapter to the same Workshop mailbox; JSON on stdin")
    parser.add_argument("--mailbox-read", action="store_true", help="Native task receipt reader over the same mailbox")
    args = parser.parse_args()
    if args.mailbox_send or args.mailbox_read:
        import json as mailbox_json
        import sys
        body = mailbox_json.loads(sys.stdin.buffer.read(65537))
        print(mailbox_json.dumps(_mailbox_call("read" if args.mailbox_read else "send", body, _default_context())))
        return
    server = build_server()
    # The Workshop is the gateway: hooks+rules are applied to this agent off the start path.
    import threading
    from .workshop_gateway import on_connect
    threading.Thread(target=on_connect, name="archhub-gateway", daemon=True).start()
    import anyio
    import json
    count = int(os.environ.pop('ARCHHUB_MCP_CONTINUATION', '0'))
    resume = json.loads(''.join(os.environ.pop('ARCHHUB_MCP_CONTINUATION_' + str(index))
                              for index in range(count))) if count else None
    if resume:
        _restore_work_continuation(server, resume['work'])
    try:
        anyio.run(_run_fresh_stdio, server, resume)
    finally:
        server._mailbox_stop()
        server.work_control.close()


if __name__ == "__main__":
    main()
