"""Native MCP host contracts: direct signed brokers and local permission, no graph.
Fixture brokers only; client registration remains on the shipped server.
"""
from __future__ import annotations

import asyncio
from contextlib import nullcontext
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from nodelang import native_agent_mcp as native
from nodelang.clean_revit_adapter import _call as signed_broker_call

ARCHHUB_HOSTS_TOOLS = {
    "revit_open_document",
    "revit_ping", "revit_info", "revit_execute_csharp", "revit_screenshot",
    "acad_ping", "acad_info", "acad_execute_csharp",
    "max_ping", "max_info", "max_execute_python", "max_execute_maxscript",
    "blender_ping", "blender_execute_python", "rhino_ping", "rhino_execute_python",
    "hosts_state", "office_read", "outlook_inbox", "notion_search", "dropbox_list",
}
REVIT = {"port": 48884, "pid": 1, "revit_version": "2025", "service_version": "1", "document": "A.rvt"}


def test_office_name_reaches_existing_broker_engine(monkeypatch):
    from nodelang import native_host_tools as hosts
    received = []
    def read(params, inputs):
        received.append((params, inputs))
        return {'ok':True}, 'Office fixture'
    monkeypatch.setitem(hosts.ENGINES, 'office.read', read)
    assert hosts._engine('office.read', operation='read', name='fixture')['ok']
    assert received == [({'operation':'read', 'name':'fixture'}, {})]
ACAD = {"port": 48885, "pid": 2, "revit_version": None, "service_version": "1",
        "document": "B.dwg", "service": "acad-mcp", "acad_version": "25"}
MAX = {"port": 48886, "pid": 3, "revit_version": None, "service_version": "0.2.0",
       "document": None, "service": "max-mcp"}


@pytest.fixture
def rig(monkeypatch, tmp_path):
    from nodelang import host_brokers
    from nodelang.user_paths import state_directory
    calls = []
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(tmp_path / "ArchHub"))
    # The permission lives in the application state owner (state_directory), the file _allow_effect reads.
    settings = state_directory() / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps({"host_effects": dict.fromkeys(["revit", "acad", "max", "rhino", "blender"], True)}))
    sessions = [REVIT.copy(), ACAD.copy()]
    monkeypatch.setattr(host_brokers, "_LAST_DOCUMENT", {})
    monkeypatch.setattr(host_brokers, "broker_sessions", lambda service, **kw: [row for row in sessions
        if bool(row.get("revit_version")) == (service == "revit") and row.get("service") != "max-mcp"])
    from nodelang import clean_revit_adapter
    def call(port, route, body=None, timeout=30):
        calls.append(("broker", port, route, body, timeout))
        return {"status": "ok", "result": "done"}
    monkeypatch.setattr(clean_revit_adapter, "_call", call)
    for name in list(host_brokers.ENGINES):
        def engine(params, feeds, name=name):
            calls.append((name, dict(params)))
            return {"out": {"answered": name}}, name
        monkeypatch.setitem(host_brokers.ENGINES, name, engine)
    return SimpleNamespace(server=native.build_server(), calls=calls, sessions=sessions, settings=settings)


def tool(rig, name, arguments=None):
    return asyncio.run(rig.server.call_tool(name, arguments or {}))


def payload(answer):
    return answer[1] if isinstance(answer, tuple) else json.loads(answer[0].text)


def approved(rig, monkeypatch, name, arguments=None):
    """An agent's host effect waits on one Approve card (F344); approving it runs the call once. Returns what it ran."""
    from nodelang import hook_decision, host_exec
    held = payload(tool(rig, name, arguments))
    assert held["status"] == "Waiting for approval" and held["approvalId"], held
    host_exec._ensure_registry()
    release, ran = host_exec.INVOKERS["archhub.commands"], []
    monkeypatch.setitem(host_exec.INVOKERS, "archhub.commands",
                        lambda action, given: ran.append(release(action, given)) or ran[-1])
    [card] = [c for c in hook_decision.ask_reviews() if c["id"] == held["approvalId"]]
    assert hook_decision.ask_apply(card["id"], card["input_digest"], "approve")["status"] == "approved"
    assert len(ran) == 1
    return ran[0]


def test_all_existing_tool_names_remain(rig):
    assert ARCHHUB_HOSTS_TOOLS <= {tool.name for tool in rig.server._tool_manager.list_tools()}


def test_reads_work_without_permission_or_graph(rig):
    rig.settings.unlink()
    for name in ("revit_ping", "revit_info", "acad_ping", "acad_info", "office_read", "outlook_inbox", "dropbox_list", "notion_search"):
        tool(rig, name, {"operation": "excel.list_workbooks"} if name == "office_read" else {})
    # NOGRAPH (9afdeaa4): the server holds no Work enrolment at all; the reads above answered without one.
    assert not hasattr(rig.server, "work_control")


@pytest.fixture
def signed_reply(monkeypatch):
    from nodelang import clean_revit_adapter, host_bridge_auth

    calls = []
    monkeypatch.setattr(clean_revit_adapter, "_call", signed_broker_call)
    monkeypatch.setattr(host_bridge_auth, "ensure_secret", lambda: "isolated-fixture-secret")

    def respond(status, body):
        def open_request(request, *, timeout):
            assert request.get_header(host_bridge_auth.SIGNATURE_HEADER.capitalize())
            calls.append((request.selector, timeout))
            if status is None:
                raise TimeoutError("isolated transport timeout")
            raw = json.dumps(body).encode("utf-8")
            if status != 200:
                raise HTTPError(request.full_url, status, "fixture response", None, BytesIO(raw))
            return nullcontext(SimpleNamespace(status=status, read=lambda: raw))

        monkeypatch.setattr(host_bridge_auth.urllib.request, "urlopen", open_request)
        return calls

    return respond


@pytest.mark.parametrize("status", [401, 403, 503])
def test_native_revit_info_preserves_http_refusal(rig, signed_reply, status):
    calls = signed_reply(status, {"error": "fixture broker refusal", "document": "unexpected.rvt"})
    reply = payload(tool(rig, "revit_info"))
    assert reply == {"ok": False, "status": "error", "http_status": status, "error": "fixture broker refusal",
                     "port": REVIT["port"], "document": None}
    assert calls == [("/info", 1.5)]


@pytest.mark.parametrize("document", [None, "", "Signed.rvt"])
def test_native_revit_info_keeps_authorized_result(rig, signed_reply, document):
    answer = {"status": "ok"}
    if document is not None:
        answer["document"] = document
    signed_reply(200, answer)
    assert payload(tool(rig, "revit_info")) == {
        "ok": True, "status": "ok", "document": document or "", "port": REVIT["port"]}


def test_native_revit_info_timeout_keeps_discovery_without_a_document(rig, signed_reply):
    calls = signed_reply(None, {})
    reply = payload(tool(rig, "revit_info"))
    assert reply["ok"] is False and reply["status"] == "busy"
    assert reply["document"] is None and reply["info_source"] == "ping-discovery"
    assert reply["revit_version"] == REVIT["revit_version"] and reply["port"] == REVIT["port"]
    assert calls == [("/info", 1.5)]


@pytest.mark.parametrize("status", [200, 503])
def test_native_autocad_info_preserves_its_existing_projection(rig, signed_reply, status):
    signed_reply(status, {"status": "ok", "document_name": "Signed.dwg"})
    reply = payload(tool(rig, "acad_info"))
    assert reply["ok"] is True and reply["status"] == "ok"
    assert reply["document"] == ("Signed.dwg" if status == 200 else ACAD["document"])


@pytest.mark.parametrize("status", [200, 403])
def test_native_revit_phases_keeps_signed_result_or_refusal(rig, signed_reply, monkeypatch, status):
    from nodelang import clean_revit_adapter, hook_decision

    monkeypatch.setattr(clean_revit_adapter, "live_sessions", lambda: [REVIT])
    monkeypatch.setattr(hook_decision, "decide", lambda request: {"verdict": "allow"})
    phases = [{"name": "Existing"}, {"name": "New Construction"}]
    calls = signed_reply(status, {"status": "ok", "result": phases} if status == 200 else
                         {"error": "fixture phase read refused"})
    args = {"tool": "revit_list_phases", "arguments": {}}
    if status == 200:
        reply = payload(tool(rig, "revit_run", args))
        assert reply["ok"] is True and reply["out"] == phases
    else:
        with pytest.raises(Exception, match="Revit refused revit.list_phases: fixture phase read refused"):
            tool(rig, "revit_run", args)
    assert [route for route, _ in calls] == ["/exec"]


@pytest.mark.parametrize("name,args", [("revit_execute_csharp", {"code": "result=1;"}),
    ("revit_screenshot", {}), ("revit_open_document", {"path": "fixture.rvt"}),
    ("acad_execute_csharp", {"code": "result=1;"}), ("max_execute_python", {"code": "1"}),
    ("max_execute_maxscript", {"script": "1"}), ("rhino_execute_python", {"code": "1"}),
    ("blender_execute_python", {"code": "1"})])
def test_effects_refuse_before_dispatch_without_local_permission(rig, name, args):
    rig.settings.write_text('{}')
    with pytest.raises(Exception, match="Local host effect permission"):
        tool(rig, name, args)
    assert rig.calls == []


def test_effect_once_and_permission_recheck(rig, monkeypatch):
    from nodelang import host_brokers
    def changes(params, feeds):
        rig.calls.append("once")
        rig.settings.write_text('{}')
        return {"work": "forged", "confirmed": True, "out": 1}, "ran"
    monkeypatch.setitem(host_brokers.ENGINES, "max.exec", changes)
    result = approved(rig, monkeypatch, "max_execute_maxscript", {"script": "1"})
    assert result["confirmed"] is False and "may have run" in result["unconfirmed"]
    assert "work" not in result and rig.calls == ["once"]


def test_timeout_is_uncertain_never_retried(rig, monkeypatch):
    from nodelang import clean_revit_adapter
    def silent(*a, **kw):
        rig.calls.append("sent")
        raise TimeoutError("timeout")
    monkeypatch.setattr(clean_revit_adapter, "_call", silent)
    result = approved(rig, monkeypatch, "revit_execute_csharp", {"code": "result=1;"})
    assert result["confirmed"] is False and "Do not run it again" in result["unconfirmed"]
    assert rig.calls == ["sent"]


def test_ambiguity_and_wrong_host_refuse(rig):
    rig.sessions[:] = [REVIT, {**REVIT, "port": 48887}]
    with pytest.raises(Exception, match="name one with port"):
        tool(rig, "revit_info")
    rig.sessions[:] = [MAX]
    with pytest.raises(Exception, match="no Revit session"):
        tool(rig, "revit_info")
    assert rig.calls == []


def test_existing_payloads_timeouts_and_screenshot_default(rig, monkeypatch):
    approved(rig, monkeypatch, "revit_execute_csharp", {"code": "open", "transaction": False})
    approved(rig, monkeypatch, "revit_screenshot")
    tool(rig, "revit_info")
    tool(rig, "acad_info")
    assert rig.calls[0] == ("broker", 48884, "/exec", {"code": "open", "transaction_name": "ArchHub", "transaction": False}, 240.0)
    assert rig.calls[1] == ("broker", 48884, "/screenshot", {"output_path": r"C:\temp\revit_view.png", "width_px":1920},240.0)
    assert [row[-1] for row in rig.calls[2:]] == [1.5, 1.5]


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


def test_reads_and_status_need_no_owner(rig, monkeypatch):
    from nodelang import connector_operation_evidence
    monkeypatch.setattr(connector_operation_evidence, "host_projection", lambda: {"ok": True, "connectors": [], "operations": []})
    rig.settings.unlink()
    payload(tool(rig, "dropbox_list", {"path": "Projects"}))
    payload(tool(rig, "revit_ping"))
    state = payload(tool(rig, "hosts_state"))
    assert state["ok"] is True and state["connectors"] == [] and state["operations"] == []
    assert not hasattr(rig.server, "work_control")


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
        "env": {"PYTHONPATH": "C:/Users/fargaly/00.ARCHUB/10.PRODUCT/11.ARCHHUB-APP",
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
    opencode = mcp_server_spec("opencode", environment={})["add"][SERVER_NAME]
    assert opencode["type"] == "local" and opencode["command"][-1] == str(install)
    assert opencode["environment"]["ARCHHUB_COORDINATION_VENDOR"] == "opencode"
    with pytest.raises(ValueError):
        mcp_server_spec("unknown-client", environment={})
