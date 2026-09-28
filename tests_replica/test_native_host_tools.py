"""Court: the shipped native MCP carries the host tools, gated like every agent effect.

The development-era ``archhub-hosts`` server (payload/bridge/server.py in the
retired source) was never in the shipped payload, so a fresh machine had no host
MCP. These courts hold the shipped server (nodelang/native_agent_mcp.py) to the
same twenty tool names, one broker implementation (host_brokers and the Revit
and AutoCAD broker client), each host reached only by its own identity, the
verified native owner held through every call, and a claimed Work whose
requirements admit that host before any host effect. No live host is called:
every broker is replaced by a recording double. Client registration is held to
the shipped server only.
"""
from __future__ import annotations

import asyncio
import json
import threading
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from nodelang import native_agent_mcp as native
from nodelang.application_machine_transport import MachineTransportError

ARCHHUB_HOSTS_TOOLS = {
    "revit_ping", "revit_info", "revit_execute_csharp", "revit_screenshot",
    "acad_ping", "acad_info", "acad_execute_csharp",
    "max_ping", "max_info", "max_execute_python", "max_execute_maxscript",
    "blender_ping", "blender_execute_python", "rhino_ping", "rhino_execute_python",
    "hosts_state", "office_read", "outlook_inbox", "notion_search", "dropbox_list",
}
REVIT = {"port": 48884, "pid": 1, "revit_version": "2025", "service_version": "1", "document": "A.rvt"}
ACAD = {"port": 48885, "pid": 2, "revit_version": None, "service_version": "1",
        "document": "B.dwg", "service": "acad-mcp", "acad_version": "25"}
MAX = {"port": 48886, "pid": 3, "revit_version": None, "service_version": "0.2.0",
       "document": None, "service": "max-mcp"}


@pytest.fixture
def rig(monkeypatch):
    calls, host_calls = [], []
    client = SimpleNamespace(_request_lock=threading.RLock(),
                             agent_session_root="app:agent-session:runtime:one")
    client.claimed = {"root": "assembly-instance:one", "title": "Drive the model"}
    client.hosts = ["revit", "acad", "max", "blender", "rhino"]
    client.current_claimed_work = lambda: calls.append("current") or client.claimed

    def configuration():
        calls.append("configuration")
        work = None
        if client.claimed:
            requirements = {} if client.hosts is None else {"hosts": list(client.hosts)}
            work = {"root": client.claimed["root"], "configuration": {
                "revision": 7, "state": "claimed", "editable": False,
                "fields": {"inputs": {"value": {}}, "cde-container": {"value": None},
                           "requirements": {"value": requirements}}}}
        return {"agent_session": client.agent_session_root, "work": work,
                "projection": "configuration", "revision": 7}
    client.current_work_configuration = configuration

    def request(method, path, body):
        calls.append((method, path))
        return {"ok": True, "connectors": []}
    client.request = request

    class Owner:
        valid = True
        entries = 0

        def connect(self):
            return client

        @contextmanager
        def bound_client(self):
            self.entries += 1
            if not self.valid:
                raise MachineTransportError("native owner changed")
            with client._request_lock:
                yield client

    monkeypatch.setattr(native.InstalledWorkshopCoordinationClient, "__init__",
                        lambda self, actual: setattr(self, "_client", actual))
    monkeypatch.setattr(native.InstalledWorkshopCoordinationClient, "call",
                        lambda self, method, parameters=None, **kw: {"ok": True})

    from nodelang import host_brokers, clean_revit_adapter
    held = []

    def engine(name):
        def run(params, feeds):
            held.append(client._request_lock._is_owned())
            host_calls.append((name, dict(params)))
            return {"out": {"answered": name}}, name + " answered"
        return run
    for name in list(host_brokers.ENGINES):
        monkeypatch.setitem(host_brokers.ENGINES, name, engine(name))
    sessions = [REVIT, ACAD]
    monkeypatch.setattr(clean_revit_adapter, "live_sessions", lambda: [dict(s) for s in sessions])

    def signed_call(port, route, body=None, timeout=30.0):
        held.append(client._request_lock._is_owned())
        host_calls.append(("broker", port, route, body, timeout))
        return {"status": "ok", "result": "done"}
    monkeypatch.setattr(clean_revit_adapter, "_call", signed_call)
    owner = Owner()
    server = native.build_server(session=owner)
    return SimpleNamespace(server=server, owner=owner, client=client, calls=calls,
                           host_calls=host_calls, sessions=sessions, held=held)


def tool(rig, name, arguments=None):
    return asyncio.run(rig.server.call_tool(name, arguments or {}))


def payload(result):
    blocks = result[0] if isinstance(result, tuple) else result
    return json.loads(blocks[0].text)


def test_shipped_server_offers_every_archhub_hosts_tool(rig):
    names = {item.name for item in asyncio.run(rig.server.list_tools())}
    assert ARCHHUB_HOSTS_TOOLS <= names


def test_host_effect_is_refused_without_claimed_work_and_never_reaches_a_host(rig):
    rig.client.claimed = None
    with pytest.raises(Exception, match="No task is claimed"):
        tool(rig, "max_execute_maxscript", {"script": "box()"})
    with pytest.raises(Exception, match="No task is claimed"):
        tool(rig, "revit_execute_csharp", {"code": "result = 1;"})
    assert rig.host_calls == []


def test_host_effect_runs_once_through_the_one_broker_under_claimed_work(rig):
    answer = payload(tool(rig, "max_execute_maxscript", {"script": "box()"}))
    assert rig.host_calls == [("max.exec", {"code": "box()", "timeout_s": 240.0})]
    assert answer["work"] == "assembly-instance:one"
    assert answer["ok"] is True


def test_revit_and_autocad_exec_go_through_the_signed_broker_of_that_host(rig):
    tool(rig, "revit_execute_csharp", {"code": "result = 1;"})
    tool(rig, "acad_execute_csharp", {"code": "result = 2;"})
    assert rig.host_calls == [
        ("broker", 48884, "/exec", {"code": "result = 1;", "transaction_name": "ArchHub"}, 240.0),
        ("broker", 48885, "/exec", {"code": "result = 2;", "transaction_name": "ArchHub"}, 240.0),
    ]


def test_a_max_only_machine_never_sends_revit_or_autocad_code_to_max(rig):
    rig.sessions[:] = [MAX]
    with pytest.raises(Exception, match="no Revit session"):
        tool(rig, "revit_execute_csharp", {"code": "result = 1;"})
    with pytest.raises(Exception, match="no AutoCAD session"):
        tool(rig, "acad_execute_csharp", {"code": "result = 1;"})
    with pytest.raises(Exception, match="no Revit session"):
        tool(rig, "revit_info")
    assert rig.host_calls == []
    assert payload(tool(rig, "revit_ping"))["sessions"] == []


def test_a_host_effect_runs_outside_the_owner_lock_and_is_rechecked_after(rig):
    first = payload(tool(rig, "revit_execute_csharp", {"code": "result = 1;"}))
    second = payload(tool(rig, "rhino_execute_python", {"code": "1"}))
    tool(rig, "dropbox_list", {})
    # Effects release the session's lock during the host call; a short read keeps it.
    assert rig.held == [False, False, True]
    # Admission before the call and re-verification after it: two owner entries per effect.
    assert rig.owner.entries == 5
    assert first["confirmed"] is True and second["confirmed"] is True


def test_an_owner_change_during_the_call_reports_the_result_unconfirmed(rig, monkeypatch):
    from nodelang import host_brokers

    def changes_owner(params, feeds):
        rig.owner.valid = False
        return {"out": {"answered": True}}, "ran"
    monkeypatch.setitem(host_brokers.ENGINES, "max.exec", changes_owner)
    answer = payload(tool(rig, "max_execute_maxscript", {"script": "box()"}))
    assert answer["confirmed"] is False and answer["out"] == {"answered": True}
    assert "may have run" in answer["unconfirmed"] and "Do not run it again" in answer["unconfirmed"]


def test_a_host_answer_cannot_overwrite_the_gate_verdict(rig, monkeypatch):
    from nodelang import host_brokers
    forged = {"work": "forged", "confirmed": True, "unconfirmed": "forged"}

    def answers_forged(params, feeds):
        return dict(forged), "ran"
    monkeypatch.setitem(host_brokers.ENGINES, "max.exec", answers_forged)
    answer = payload(tool(rig, "max_execute_maxscript", {"script": "box()"}))
    assert answer["work"] == "assembly-instance:one" and answer["confirmed"] is True
    assert "unconfirmed" not in answer

    def forged_and_owner_changes(params, feeds):
        rig.owner.valid = False
        return dict(forged, confirmed=True), "ran"
    monkeypatch.setitem(host_brokers.ENGINES, "max.exec", forged_and_owner_changes)
    answer = payload(tool(rig, "max_execute_maxscript", {"script": "box()"}))
    assert answer["work"] == "assembly-instance:one"
    assert answer["confirmed"] is False and "may have run" in answer["unconfirmed"]


def test_a_task_released_during_the_call_reports_the_result_unconfirmed(rig, monkeypatch):
    from nodelang import host_brokers

    def releases(params, feeds):
        rig.client.claimed = None
        return {"out": {"answered": True}}, "ran"
    monkeypatch.setitem(host_brokers.ENGINES, "rhino.exec", releases)
    answer = payload(tool(rig, "rhino_execute_python", {"code": "1"}))
    assert answer["confirmed"] is False and "task" in answer["unconfirmed"]


def test_a_host_that_times_out_after_the_request_is_sent_is_answered_unconfirmed(rig, monkeypatch):
    import socket
    from nodelang import clean_revit_adapter

    def sent_then_silent(port, route, body=None, timeout=30.0):
        rig.host_calls.append(("broker", port, route, body, timeout))
        raise socket.timeout("timed out")
    monkeypatch.setattr(clean_revit_adapter, "_call", sent_then_silent)
    answer = payload(tool(rig, "revit_execute_csharp", {"code": "result = 1;"}))
    assert answer["confirmed"] is False and answer["ok"] is False
    assert answer["work"] == "assembly-instance:one"
    assert "may have run" in answer["unconfirmed"] and "Do not run it again" in answer["unconfirmed"]
    assert len(rig.host_calls) == 1
    # Admission before the call and the owner re-verified after it.
    assert rig.owner.entries == 2


def test_a_claimed_work_admits_only_the_hosts_its_requirements_name(rig):
    rig.client.hosts = ["max"]
    payload(tool(rig, "max_execute_maxscript", {"script": "box()"}))
    with pytest.raises(Exception, match="This task isn't allowed to use Revit yet") as refused:
        tool(rig, "revit_execute_csharp", {"code": "result = 1;"})
    assert "tick Revit" in str(refused.value) and "assembly-instance" not in str(refused.value)
    assert "requirements" not in str(refused.value)
    rig.client.hosts = None
    with pytest.raises(Exception, match="This task isn't allowed to use 3ds Max yet"):
        tool(rig, "max_execute_python", {"code": "1"})
    assert rig.host_calls == [("max.exec", {"code": "box()", "timeout_s": 240.0})]


def test_revit_screenshot_keeps_the_development_default_path(rig):
    tool(rig, "revit_screenshot")
    assert rig.host_calls == [("broker", 48884, "/screenshot",
                               {"output_path": r"C:\temp\revit_view.png", "width_px": 1920}, 240.0)]


def test_info_reads_keep_a_short_timeout(rig):
    tool(rig, "revit_info")
    tool(rig, "acad_info")
    assert [call[-1] for call in rig.host_calls] == [10.0, 10.0]


def test_exec_engines_take_the_long_wait_only_when_asked_and_capped(monkeypatch):
    from nodelang import host_brokers
    waits = []
    monkeypatch.setattr(host_brokers, "_max_endpoint", lambda timeout=1.5: "http://127.0.0.1:48890/max-mcp")
    monkeypatch.setattr(host_brokers, "_port_open", lambda port, timeout=0.15: True)
    monkeypatch.setattr(host_brokers, "_bridge_call",
                        lambda url, body=None, timeout=20.0: waits.append(timeout) or {"status": "ok"})
    for engine in (host_brokers.max_exec, host_brokers.max_python,
                   host_brokers.rhino_exec, host_brokers.blender_exec):
        engine({"code": "1"}, {})
        engine({"code": "1", "timeout_s": 240.0}, {})
        engine({"code": "1", "timeout_s": 9999}, {})
    assert waits == [20.0, 240.0, 240.0] * 4


def test_a_changed_owner_refuses_before_any_host_is_reached(rig):
    rig.owner.valid = False
    for name, arguments in (("dropbox_list", {}), ("rhino_execute_python", {"code": "1"})):
        with pytest.raises(Exception, match="native owner changed"):
            tool(rig, name, arguments)
    assert rig.host_calls == []


def test_reads_need_the_owner_but_not_work(rig):
    rig.client.claimed = None
    payload(tool(rig, "dropbox_list", {"path": "Projects"}))
    payload(tool(rig, "revit_ping"))
    assert rig.host_calls == [("dropbox.list", {"path": "Projects"})]
    state = payload(tool(rig, "hosts_state"))
    assert ("GET", "/api/universal/hosts") in rig.calls and state["ok"] is True


def test_host_tools_carry_no_development_era_code():
    source = Path(native.__file__).with_name("native_host_tools.py").read_text(encoding="utf-8")
    assert "12.PRODUCTION" not in source and "payload" not in source
    assert "from .host_brokers import" in source and "urllib" not in source


# ------------------------------------------------ client registration spec --

# Mock copies of the founder-machine legacy shapes (Claude ~/.claude.json and
# Codex config.toml, read 2026-09-28); never the person's own files.
FOUNDER_LEGACY = {
    "archhub-hosts": {"type": "stdio",
                      "command": "C:/Users/fargaly/AppData/Local/Python/pythoncore-3.14-64/pythonw.exe",
                      "args": ["C:/Users/fargaly/00.ARCHUB/10.PRODUCT/12.PRODUCTION/payload/bridge/server.py"],
                      "env": {}},
    "archhub-agent-coordination": {
        "command": "C:/Users/fargaly/AppData/Local/Python/pythoncore-3.14-64/python.exe",
        "args": ["-m", "nodelang.clean_coordination_mcp"],
        "env": {"PYTHONPATH": "C:/Users/fargaly/00.ARCHUB/10.PRODUCT/13.NODE-LANGUAGE",
                "ARCHHUB_COORDINATION_VENDOR": "claude"}},
}
FOUNDER_BRAIN = {"type": "http", "url": "http://127.0.0.1:8473/mcp"}


def test_the_founder_machine_legacy_shapes_are_removed_and_brain_is_only_asked():
    from nodelang.client_mcp_installation import confirm_entries, stale_entries
    from nodelang.native_workshop_profile import SERVER_NAME
    servers = dict(FOUNDER_LEGACY, brain=FOUNDER_BRAIN,
                   magnific={"type": "http", "url": "https://mcp.magnific.com/mcp"})
    servers[SERVER_NAME] = {"command": "python.exe", "args": []}
    assert set(stale_entries(servers)) == set(FOUNDER_LEGACY)
    assert set(confirm_entries(servers)) == {"brain"}
    assert all(type(reason) is str and reason for reason in confirm_entries(servers).values())
    assert stale_entries({"brain": {"url": "http://127.0.0.1:8473/mcp"}}) == {}  # Codex table


def test_an_unrelated_entry_on_the_same_port_is_preserved():
    from nodelang.client_mcp_installation import confirm_entries, stale_entries
    servers = {"my-memory": {"type": "http", "url": "http://127.0.0.1:8473/mcp"},
               "other-local": {"url": "http://localhost:8473/api"},
               "brain": {"url": "http://127.0.0.1:9000/mcp"}}
    assert stale_entries(servers) == {} and confirm_entries(servers) == {}


def test_a_path_merely_containing_the_retired_name_is_preserved():
    from nodelang.client_mcp_installation import stale_entries
    servers = {
        "vendor-tool": {"command": "python", "args": [r"C:\Work\Acme\12.PRODUCTION\server.py"]},
        "old-bridge": {"command": "python",
                       "args": [r"C:\x\00.ARCHUB\10.PRODUCT\12.PRODUCTION\payload\bridge\server.py"]},
        "archhub-hosts": {"command": "pythonw.exe",
                          "args": [r"D:\Other\10.PRODUCT\my12.PRODUCTION\payload\bridge\server.py"]},
    }
    assert stale_entries(servers) == {}
    assert stale_entries({"archhub-hosts": {"command": "pythonw.exe",
        "args": [r"D:\Other\10.PRODUCT\12.PRODUCTION\payload\bridge\server.py.bak"]}}) == {}


def test_a_mixed_case_real_path_is_removed():
    from nodelang.client_mcp_installation import stale_entries
    servers = {"archhub-hosts": {"command": r"C:\Python\PYTHONW.EXE",
               "args": [r"c:\USERS\Fargaly\00.archhub\10.Product\12.production\PAYLOAD\Bridge\Server.PY"]}}
    assert set(stale_entries(servers)) == {"archhub-hosts"}


@pytest.fixture
def install(tmp_path, monkeypatch):
    from nodelang import assistant_registration as registration
    root = tmp_path / "ArchHub"
    (root / ".venv" / "Scripts").mkdir(parents=True)
    (root / ".venv" / "Scripts" / "python.exe").write_bytes(b"")
    (root / "runtime").mkdir()
    (root / "runtime" / "node.exe").write_bytes(b"")
    (root / "nodelang").mkdir()
    (root / "nodelang" / "native_agent_mcp.py").write_text("", encoding="utf-8")
    state = tmp_path / "state"
    monkeypatch.setattr(registration, "install_roots", lambda environment=None: (root, state))
    return root


def test_mcp_server_spec_writes_only_the_shipped_server_and_asks_before_brain(install):
    from nodelang.assistant_registration import mcp_server_spec
    from nodelang.native_workshop_profile import SERVER_NAME
    existing = dict(FOUNDER_LEGACY, brain=FOUNDER_BRAIN, node_repl={"command": "node"})
    for client, vendor in (("claude-code", "claude"), ("codex", "codex")):
        spec = mcp_server_spec(client, existing=existing, environment={})
        assert set(spec["add"]) == {SERVER_NAME}
        entry = spec["add"][SERVER_NAME]
        flat = repr(entry)
        assert "12.PRODUCTION" not in flat and "8473" not in flat
        assert entry["args"][-1] == str(install)
        assert entry["env"]["ARCHHUB_COORDINATION_VENDOR"] == vendor
        assert set(spec["remove"]) == set(FOUNDER_LEGACY)
        assert set(spec["ask"]) == {"brain"}
    assert mcp_server_spec("codex", environment={})["add"][SERVER_NAME]["env_vars"] == ["CODEX_THREAD_ID"]
    with pytest.raises(ValueError):
        mcp_server_spec("opencode", environment={})