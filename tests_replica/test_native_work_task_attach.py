"""Court: one bound native owner attaches one Work's task surface at a time (2026-09-30).

Live 717: the default coordination server has no native.work_request_court. The task
tools exist only in a process launched with --workshop-task WORK_ROOT, so nine REVIEW
Works could not reach the court without a second MCP or a re-enrollment, and the Stop
hook blocked every turn. native.work_task_attach adds one Work's task tools to the
running owner through the same bound session; native.work_task_detach releases it
only while nothing it did is unresolved, so the next Work can attach.

Real application server, real native owner, real court. Only a lost court reply is
injected (after the application answered).
"""
import asyncio
import inspect

import pytest

from nodelang import native_agent_mcp as mcp
from nodelang.application_machine_transport import MachineTransportError, UniversalRuntimeClient
from nodelang.application_server import ApplicationServer
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.native_agent_session import NativeAgentSession
from tests_replica.test_universal_work_completion_court import _InProcessOwner, _green_runtime_compliance, _work

KEY = MemorySigningKeyProvider("archhub.local.universal-runtime-pipe", b"t" * 32)


class _Request:
    """The MCP request context a tool sees: the answering server and its session."""

    def __init__(self, server):
        self.fastmcp, self.session, self.changed = server, self, 0

    async def send_tool_list_changed(self):
        self.changed += 1


def _tools(server):
    return {tool.name: tool for tool in server._tool_manager.list_tools()}


def _call(server, name, request=None, **arguments):
    tool = _tools(server)[name]
    if "ctx" in inspect.signature(tool.fn).parameters:
        arguments["ctx"] = request or _Request(server)
    result = tool.fn(**arguments)
    return asyncio.run(result) if inspect.iscoroutine(result) else result


@pytest.fixture
def rig(tmp_path):
    (tmp_path / "ws").mkdir()
    app = ApplicationServer(enable_machine_transport=True, machine_descriptor_path=tmp_path / "runtime.json",
                            machine_key_provider=KEY, universal_workspace_root=tmp_path / "ws",
                            universal_state_path=tmp_path / "graph.sqlite3",
                            runtime_compliance_runner=_green_runtime_compliance).start()
    binds = []

    class Counted(UniversalRuntimeClient):
        def bind_agent_session(self, **kwargs):
            binds.append(kwargs.get("expected_agent_session"))
            return super().bind_agent_session(**kwargs)

    try:
        (tmp_path / "ws" / "a.flag").write_text("proven", encoding="utf-8")
        owner = _InProcessOwner(app)
        first = _work(owner, title="Review Work A", proof="a.flag")["created_root"]
        second = _work(owner, title="Review Work B", proof="missing.flag")["created_root"]
        native = NativeAgentSession(environment={"CLAUDE_CODE_SESSION_ID": "court-attach"},
                                    descriptor_path=tmp_path / "runtime.json", key_provider=KEY,
                                    client_factory=Counted)
        yield mcp.build_server(session=native), native, first, second, binds
    finally:
        app.close()


def test_one_bound_owner_sends_work_after_work_to_court(rig, monkeypatch):
    server, native, first, second, binds = rig
    actor = native.owner_status()["agent_session"]
    assert "native.work_request_court" not in _tools(server)

    request = _Request(server)
    attached = _call(server, "native.work_task_attach", request, work_root=first)
    assert attached["work_root"] == first and attached["agent_session"] == actor
    assert "native.work_request_court" in _tools(server) and request.changed == 1
    _call(server, "native.work_claim")
    _call(server, "native.work_submit", evidence="court-attach evidence for A")
    court = _call(server, "native.work_request_court")
    assert (court["work_root"], court["passed"], court["state"]) == (first, True, "complete")

    # One Work at a time: another root is refused while one is held.
    with pytest.raises(MachineTransportError, match="already attached"):
        _call(server, "native.work_task_attach", work_root=second)
    released = _call(server, "native.work_task_detach")
    assert released["work_root"] == first and "native.work_request_court" not in _tools(server)

    _call(server, "native.work_task_attach", work_root=second)
    _call(server, "native.work_claim")
    _call(server, "native.work_submit", evidence="court-attach evidence for B")
    original = UniversalRuntimeClient.adjudicate_work

    def lost(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise MachineTransportError("injected court reply loss after the application answered")

    monkeypatch.setattr(UniversalRuntimeClient, "adjudicate_work", lost)
    with pytest.raises(MachineTransportError, match="injected court reply loss"):
        _call(server, "native.work_request_court")
    monkeypatch.setattr(UniversalRuntimeClient, "adjudicate_work", original)
    # Uncertain: the Work stays attached, nothing is replayed.
    with pytest.raises(MachineTransportError, match="unresolved"):
        _call(server, "native.work_task_detach")
    assert "native.work_request_court" in _tools(server)
    reconciled = _call(server, "native.work_reconcile")
    assert reconciled["reconciled"] is True and reconciled["pending_operation"] is None
    assert _call(server, "native.work_task_detach")["work_root"] == second

    # The same session throughout: one enrollment, the owner's own.
    assert binds == [None] and native.owner_status()["agent_session"] == actor


def test_an_attach_names_one_exact_work(rig):
    server = rig[0]
    for root in ("", " assembly-instance:x", "assembly-instance:", "not-a-work"):
        with pytest.raises(MachineTransportError, match="one exact configured Work root"):
            _call(server, "native.work_task_attach", work_root=root)
    with pytest.raises(MachineTransportError, match="No Work task surface is attached"):
        _call(server, "native.work_task_detach")
