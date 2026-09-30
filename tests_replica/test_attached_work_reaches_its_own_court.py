"""Court: an attached Work reaches its own court, whatever else the session has pending (live 717, 2026-09-30).

The Stop gate names each submitted Work and says: attach it, run
native.work_request_court. 717 did, for one of its nine submitted Works, and the
application refused: "Agent Session owns multiple active governed-work
assignments". The attached Work's tools resolved "the current assignment" for the
whole session, so any session holding two or more pending Works could never
reach any court. The founder's desktop session holds four.

Now the attached Work's tools read that exact Work's claim. The single-claim rule
stays where it belongs, on claiming new Work, and another session's Work cannot
be attached at all.

Real application server, real native owners, real court; nothing is faked.
"""
import pytest

from nodelang import native_agent_mcp as mcp
from nodelang.application_machine_transport import MachineTransportError
from nodelang.application_server import ApplicationServer
from nodelang.native_agent_session import NativeAgentSession
from tests_replica.test_native_work_task_attach import KEY, _call
from tests_replica.test_universal_work_completion_court import _InProcessOwner, _green_runtime_compliance, _work


def _native(tmp_path, name):
    """A running native owner: building its MCP server binds its session."""
    native = NativeAgentSession(environment={"CLAUDE_CODE_SESSION_ID": name},
                                descriptor_path=tmp_path / "runtime.json", key_provider=KEY)
    return native, mcp.build_server(session=native)


@pytest.fixture
def app(tmp_path):
    (tmp_path / "ws").mkdir()
    (tmp_path / "ws" / "a.flag").write_text("proven", encoding="utf-8")
    server = ApplicationServer(enable_machine_transport=True, machine_descriptor_path=tmp_path / "runtime.json",
                               machine_key_provider=KEY, universal_workspace_root=tmp_path / "ws",
                               universal_state_path=tmp_path / "graph.sqlite3",
                               runtime_compliance_runner=_green_runtime_compliance).start()
    try:
        yield server, _InProcessOwner(server)
    finally:
        server.close()


def _works(owner, *proofs):
    return [_work(owner, title="Attached court " + proof, proof=proof)["created_root"] for proof in proofs]


def _state(owner, root):
    items = owner.request("GET", "/api/universal/work", {"projection": "index"})["items"]
    row = next(item for item in items if item["root"] == root)
    return row["operational"]["current_state_label"].casefold(), row["claimant_session"]


def _claim(native, root, *, submit=False):
    with native.bound_client() as client:
        assert client.claim_work(root)["claimed"] is True
        if submit:
            client.request("POST", "/api/universal/work-transition",
                           {"root": root, "event": "submit", "evidence": "evidence for " + root})


def test_a_session_with_several_pending_works_reaches_each_attached_court(app, tmp_path):
    _server, owner = app
    passing, failing, held = _works(owner, "a.flag", "missing.flag", "a.flag")
    native, server = _native(tmp_path, "attached-court")
    actor = native.owner_status()["agent_session"]
    _claim(native, passing, submit=True)
    _claim(native, failing, submit=True)
    _claim(native, held)                          # two submitted Works and one claimed

    _call(server, "native.work_task_attach", work_root=passing)
    assert _call(server, "native.work_assignment")["work"]["root"] == passing
    court = _call(server, "native.work_request_court")
    assert (court["work_root"], court["passed"], court["state"]) == (passing, True, "complete")
    assert _state(owner, failing) == ("review", actor)     # the court ran for the attached Work only
    assert _state(owner, held) == ("claimed", actor)
    _call(server, "native.work_task_detach")

    _call(server, "native.work_task_attach", work_root=failing)
    court = _call(server, "native.work_request_court")
    assert (court["work_root"], court["passed"], court["state"]) == (failing, False, "claimed")
    assert _state(owner, held) == ("claimed", actor)


def test_another_sessions_work_cannot_be_attached(app, tmp_path):
    _server, owner = app
    theirs, = _works(owner, "a.flag")
    other, _other_server = _native(tmp_path, "attached-court-other")
    _claim(other, theirs, submit=True)
    _me, server = _native(tmp_path, "attached-court-me")
    with pytest.raises(MachineTransportError, match="claimed by another session"):
        _call(server, "native.work_task_attach", work_root=theirs)
    with pytest.raises(MachineTransportError, match="not a registered Work"):
        _call(server, "native.work_task_attach", work_root="assembly-instance:not-registered")
    assert "native.work_request_court" not in {tool.name for tool in server._tool_manager.list_tools()}
    assert _state(owner, theirs)[0] == "review"


def test_claiming_new_work_still_needs_the_single_claim(app, tmp_path):
    _server, owner = app
    submitted, held, new = _works(owner, "a.flag", "a.flag", "a.flag")
    native, server = _native(tmp_path, "attached-court-claim")
    _claim(native, submitted, submit=True)
    _claim(native, held)
    _call(server, "native.work_task_attach", work_root=new)
    assert _call(server, "native.work_assignment")["work"] is None     # not this session's claim yet
    with pytest.raises(MachineTransportError, match="already holds claimed Work %s" % held):
        _call(server, "native.work_claim")
    assert _state(owner, new) == ("open", None)
