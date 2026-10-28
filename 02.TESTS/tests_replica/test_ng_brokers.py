"""No-graph host court: actual FastMCP dispatch, with a hostile enrollment path."""
import asyncio
import json
import pytest
from nodelang import native_agent_mcp as native, native_host_tools as hosts
from nodelang.clean_revit_adapter import _call as _signed_call
from nodelang.host_brokers import _port_open as _socket_open


def payload(answer):
    if isinstance(answer, tuple):
        return answer[1]
    return json.loads(answer[0].text)


@pytest.mark.parametrize("name", ["revit_ping", "revit_info", "acad_ping", "acad_info", "office_read", "outlook_inbox"])
def test_first_host_call_never_enrolls(name, monkeypatch):
    from nodelang.native_agent_session import NativeAgentSession
    def stalled(*a, **k):
        raise TimeoutError("main enrollment timeout path reached")
    monkeypatch.setattr(NativeAgentSession, "__init__", lambda self, **kw: None)
    monkeypatch.setattr(NativeAgentSession, "connect", stalled)
    monkeypatch.setattr(hosts, "_sessions", lambda service: {"ok": True, "sessions": [{"port": 48884}]})
    monkeypatch.setattr(hosts, "_broker", lambda *a, **k: {"ok": True, "document": "live fixture"})
    monkeypatch.setattr(hosts, "_engine", lambda *a, **k: {"ok": True})
    server = native.build_server()
    args = {"operation": "excel.list_workbooks"} if name == "office_read" else {}
    assert payload(asyncio.run(server.call_tool(name, args)))["ok"] is True
    assert server.work_control.owner is None


@pytest.fixture
def broker(monkeypatch, tmp_path):
    import threading
    import os
    from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
    from nodelang import host_brokers as brokers, host_bridge_auth as auth
    from nodelang import clean_revit_adapter
    monkeypatch.setattr(clean_revit_adapter, "_call", _signed_call)
    monkeypatch.setattr(brokers, "_port_open", _socket_open)
    calls = []
    secret = "fixture-only-signature-key-00000000000000"
    monkeypatch.setattr(auth, "ensure_secret", lambda: secret)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            self.answer()
        def do_POST(self):
            self.answer()
        def answer(self):
            import hmac, hashlib
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if self.path != "/ping":
                expected = hmac.new(secret.encode(), auth.signing_text(self.command, self.path,
                    self.headers.get(auth.TIME_HEADER, ""), self.headers.get(auth.NONCE_HEADER, ""), body), hashlib.sha256).hexdigest()
                assert hmac.compare_digest(expected, self.headers.get(auth.SIGNATURE_HEADER, ""))
            calls.append((self.path, body))
            result = {"status": "ok", "pid": os.getpid(), "service": "revit-mcp", "revit_version": "2027"}
            if self.path == "/info":
                result["document_title"] = "Fixture model"
            raw = json.dumps(result).encode()
            self.send_response(200); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
    http = ThreadingHTTPServer(("localhost", 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True); thread.start()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    directory = tmp_path / "ArchHub" / "sessions"; directory.mkdir(parents=True)
    row = {"family": "revit", "pid": os.getpid(), "port": http.server_port}
    session = directory / "revit-fixture.json"; session.write_text(json.dumps(row))
    monkeypatch.setattr(brokers, "_windows_process_table", lambda: {os.getpid(): {"name": "revit.exe"}})
    try:
        yield brokers, calls, session, row
    finally:
        http.shutdown(); http.server_close(); thread.join(timeout=2)


def test_real_signed_fixture_effect_and_discovery(broker, monkeypatch):
    from mcp.server.fastmcp import FastMCP
    brokers, calls, session, _row = broker
    assert brokers.broker_sessions("revit")[0]["document"] == "Fixture model"
    settings = session.parents[1] / "settings.json"
    server = FastMCP("fixture"); hosts.register_host_tools(server)
    with pytest.raises(Exception, match="Local host effect permission"):
        asyncio.run(server.call_tool("revit_execute_csharp", {"code": "result=1;"}))
    assert not any(route == "/exec" for route, _ in calls)
    settings.write_text(json.dumps({"host_effects": {"revit": True}}))
    answer = payload(asyncio.run(server.call_tool("revit_execute_csharp", {"code": "result=1;"})))
    assert answer["confirmed"] is True and answer["ok"] is True
    assert sum(route == "/exec" for route, _ in calls) == 1


@pytest.mark.parametrize("saved", ["broken", "[]", '{}', '{"host_effects":{"revit":"true"}}', '{"host_effects":true}', '{"host_effects":{"revit":1}}'])
def test_permission_malformed_or_non_boolean_refuses(saved, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    path = tmp_path / "ArchHub" / "settings.json"; path.parent.mkdir(); path.write_text(saved)
    with pytest.raises(hosts.HostToolRefused):
        hosts._allow_effect("revit")


@pytest.mark.parametrize("change", [{"family":"autocad"}, {"pid":-1}, {"pid":True}, {"port":True}, {"port":70000}, {"pid":999999}])
def test_session_identity_or_invalid_fields_refuse(broker, change):
    brokers, calls, session, row = broker
    session.write_text(json.dumps({**row, **change}))
    assert brokers.broker_sessions("revit") == []
    assert calls == []


def test_duplicate_malformed_and_spoofed_session_files(broker):
    brokers, _calls, session, row = broker
    (session.parent / "revit-broken.json").write_text("not json")
    (session.parent / "revit-duplicate.json").write_text(json.dumps(row))
    assert len(brokers.broker_sessions("revit")) == 1
    with pytest.raises(ValueError, match="unknown broker"):
        brokers.broker_sessions("other")


def test_real_mcp_wire_startup_and_host_calls_never_contact_app(monkeypatch):
    from mcp.shared.memory import create_connected_server_and_client_session
    from nodelang.native_agent_session import NativeAgentSession
    calls = []
    def unavailable(*args, **kwargs):
        calls.append(args)
        raise TimeoutError("app must not be contacted")
    monkeypatch.setattr(NativeAgentSession, "connect", unavailable)
    monkeypatch.setattr(hosts, "_sessions", lambda service: {"ok": True, "sessions": []})
    monkeypatch.setattr(hosts, "_broker", lambda *a, **kw: {"ok": True, "document": "fixture"})
    server = native.build_server(mailbox_call=unavailable)
    async def run():
        async with create_connected_server_and_client_session(server) as client:
            assert not (await client.call_tool("revit_ping", {})).isError
            assert not (await client.call_tool("revit_info", {})).isError
            import anyio
            await anyio.sleep(.05)
    asyncio.run(run())
    server._mailbox_stop()
    assert calls == [] and server.work_control.owner is None


def test_process_observation_failure_still_verifies_live_broker(broker, monkeypatch):
    brokers, calls, _session, row = broker
    def unavailable():
        raise brokers.ProcessEnumerationUnavailable("fixture process observation unavailable")
    monkeypatch.setattr(brokers, "_windows_process_table", unavailable)
    assert brokers.broker_sessions("revit")[0]["pid"] == row["pid"]
    assert calls[0][0] == "/ping"
