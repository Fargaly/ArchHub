"""Custom MCP servers (Settings > Connections) and subscription sign-in, with fakes only."""
from __future__ import annotations

import io
import json
import sys
import textwrap

import pytest

from nodelang import custom_mcp, host_exec, model_router


class FakeStore:
    def __init__(self):
        self.keys = {}

    def save_api_key(self, name, value):
        self.keys[name] = value

    def load_api_key(self, name):
        return self.keys.get(name)

    def delete_api_key(self, name):
        self.keys.pop(name, None)


FAKE_SERVER = textwrap.dedent('''
    import json, os, sys
    for line in sys.stdin:
        m = json.loads(line)
        if "id" not in m:
            continue
        if m["method"] == "initialize":
            r = {"protocolVersion": "2025-03-26", "capabilities": {}, "serverInfo": {"name": "fake"}}
        elif m["method"] == "tools/list":
            r = {"tools": [{"name": "echo", "description": "Echo text",
                            "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}}},
                           {"name": "peek", "description": "Read only", "annotations": {"readOnlyHint": True},
                            "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}}}]
                          + [{"name": n, "inputSchema": {"type": "object", "properties": {"body": {"type": "string"}}}}
                             for n in ("save_draft", "draft_email", "exec_sql")]}
        else:
            a = m["params"]["arguments"]
            if os.environ.get("FAKE_COUNT"):  # one line per real tool run
                open(os.environ["FAKE_COUNT"], "a").write(m["params"]["name"] + "\\n")
            r = {"content": [{"type": "text", "text": a.get("text", "") + "|" + os.environ.get("FAKE_TOKEN", "")}]}
        print(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": r}), flush=True)
''')


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(tmp_path))
    store = FakeStore()
    monkeypatch.setattr(custom_mcp, "_secrets", lambda: store)
    script = tmp_path / "fake_mcp.py"
    script.write_text(FAKE_SERVER, encoding="utf-8")
    yield tmp_path, store, script
    for key in [k for k in host_exec.LISTERS if k.startswith(custom_mcp.PREFIX)]:
        host_exec.LISTERS.pop(key)
        host_exec.INVOKERS.pop(key)


def test_parse_takes_a_url_a_command_or_an_mcp_json_snippet():
    [(url, _)] = custom_mcp.parse("https://mcp.example.com/mcp")
    assert url == {"transport": "http", "url": "https://mcp.example.com/mcp", "name": "mcp.example.com"}
    [(cmd, _)] = custom_mcp.parse("npx -y @scope/server-files C:/work")
    assert cmd["command"] == "npx" and cmd["args"] == ["-y", "@scope/server-files", "C:/work"]
    rows = custom_mcp.parse(json.dumps({"mcpServers": {
        "files": {"command": "npx", "args": ["-y", "x"], "env": {"API_TOKEN": "t-123"}},
        "web": {"url": "https://w.example/mcp", "headers": {"Authorization": "Bearer abc"}}}}))
    assert [(e["name"], s) for e, s in rows] == [
        ("files", {("env", "API_TOKEN"): "t-123"}), ("web", {("header", "Authorization"): "Bearer abc"})]


@pytest.mark.parametrize("text, reason", [
    ("", "Paste"), ("ftp://x", "a command"), ("https://u:p@x.example/mcp", "header"),
    ("http://remote.example/mcp", "https"), ("server --api-key=" + "a" * 20, "looks like a key"),
    ("{not json", "could not be read")])
def test_bad_entries_are_refused_with_a_reason(text, reason):
    with pytest.raises(custom_mcp.McpRefused, match=reason):
        if text == "ftp://x":
            custom_mcp._one("", {"nothing": 1})
        else:
            custom_mcp.parse(text)


def test_secrets_go_to_the_store_never_the_file_and_remove_clears_them(state):
    tmp, store, _script = state
    [row] = custom_mcp.add(json.dumps({"mcpServers": {"web": {
        "url": "https://w.example/mcp", "headers": {"Authorization": "Bearer s3cret"}}}}))
    saved = (tmp / "settings" / "mcp_servers.json").read_text(encoding="utf-8")
    assert "s3cret" not in saved and row["headers"] == ["Authorization"]
    assert store.keys == {"mcp-web-header-Authorization": "Bearer s3cret"}
    custom_mcp.remove("web")
    assert store.keys == {} and custom_mcp.servers() == []


def test_a_stdio_server_becomes_a_connector_its_tools_list_and_call_with_its_secret(state):
    _tmp, _store, script = state
    snippet = {"mcpServers": {"Fake": {"command": sys.executable, "args": ["-I", str(script)],
                                        "env": {"FAKE_TOKEN": "tok"}}}}
    [row] = custom_mcp.add(json.dumps(snippet))
    assert row["id"] == "fake" and any(c["id"] == "mcp:fake" for c in host_exec.connectors())
    assert [a["name"] for a in host_exec.connector_actions("mcp:fake")] == ["echo", "peek", "save_draft", "draft_email", "exec_sql"]
    assert custom_mcp.call_tool(custom_mcp._find("fake"), "echo", {"text": "hi"}) == "hi|tok"
    custom_mcp.set_enabled("fake", False)
    with pytest.raises(host_exec.ConnectorUnreachable):
        host_exec.connector_actions("mcp:fake")


def test_an_http_server_is_called_with_its_header_from_the_store(state):
    _tmp, store, _script = state
    [row] = custom_mcp.add(json.dumps({"url": "https://w.example/mcp", "name": "Web",
                                       "headers": {"Authorization": "Bearer abc"}}))
    seen = []

    class Answer(io.BytesIO):
        headers = {"Mcp-Session-Id": "s1"}

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def opener(request, timeout):
        body = json.loads(request.data)
        seen.append((body.get("method"), request.get_header("Authorization")))
        result = {"tools": [{"name": "find", "inputSchema": {"properties": {"q": {}}}}]}
        return Answer(json.dumps({"jsonrpc": "2.0", "id": body.get("id"), "result": result}).encode())

    tools = custom_mcp.list_tools(row, store=store, opener=opener)
    assert tools == [{"name": "find", "title": "find", "inputs": ["q"], "readOnly": False}]
    assert seen[0] == ("initialize", "Bearer abc") and seen[-1][0] == "tools/list"


def _fake_server(state):
    _tmp, _store, script = state
    [row] = custom_mcp.add(json.dumps({"mcpServers": {"Fake": {"command": sys.executable, "args": ["-I", str(script)]}}}))
    return row


@pytest.mark.parametrize("run_mode", ["Accept edits", "Ask first"])
def test_a_tool_that_can_change_things_waits_for_approve_in_every_run_mode(state, run_mode):
    from nodelang import hook_decision
    _fake_server(state)
    hook_decision.write_permissions({"runMode": run_mode})
    out, label = host_exec.connector_call({"connector": "mcp:fake", "action": "echo", "args": {"text": "hi"}})
    assert label == "Waiting for you" and out["result"] is None and out["action"] == "send"
    assert custom_mcp.agent_call("fake", "echo", {"text": "hi"})["ok"] is False


def test_approve_releases_the_servers_own_tool_once(state, monkeypatch):
    import os
    from nodelang import hook_decision
    runs = state[0] / "runs.txt"
    monkeypatch.setenv("FAKE_COUNT", str(runs))
    _fake_server(state)
    hook_decision.write_permissions({"runMode": "Accept edits"})
    out, label = host_exec.connector_call({"connector": "mcp:fake", "action": "echo", "args": {"text": "go"}})
    assert label == "Waiting for you" and out["result"] is None
    holds = hook_decision._read_holds(hook_decision._ask_path(os.environ))["holds"]
    [row] = [r for r in holds.values() if r.get("status") == "pending"]
    assert row["replay"] == {"kind": "connector", "connector": "mcp:fake", "action": "echo", "arguments": {"text": "go"}}
    card = hook_decision.ask_apply(row["id"], row["input_digest"], "approve")
    assert card["status"] == "approved", card
    released = hook_decision._read_holds(hook_decision._ask_path(os.environ))["holds"][row["id"]]
    assert "go|" in json.dumps(released)  # the fake server's own echo ran, not "connector.call"
    again = hook_decision.ask_apply(row["id"], row["input_digest"], "approve")
    assert again["status"] == "approved"
    assert runs.read_text().splitlines() == ["echo"]  # held once, approved twice, run exactly once


def test_a_tool_named_like_a_draft_is_never_released_without_approve_nor_labelled_a_draft(state):
    import os
    from nodelang import hook_decision
    _fake_server(state)
    hook_decision.write_permissions({"runMode": "Accept edits"})
    for tool in ("save_draft", "draft_email", "exec_sql"):
        # Mail-shaped but non-personal (no address, name or number), so the Ask-first boundary is what is tested.
        out, label = host_exec.connector_call({"connector": "mcp:fake", "action": tool,
                                               "args": {"to": "team-inbox", "subject": "s", "body": "DROP TABLE x"}})
        assert label == "Waiting for you" and out["result"] is None, tool
    for _ in range(3):  # later decisions run the old-draft-card release; his MCP calls must not go with it
        hook_decision.decide({"tool_name": "Read", "tool_input": {"file_path": "x.txt"}, "cwd": os.getcwd()})
    holds = hook_decision._read_holds(hook_decision._ask_path(os.environ))["holds"].values()
    held = {row["replay"]["action"]: row for row in holds}
    assert {name: held[name]["status"] for name in ("save_draft", "draft_email", "exec_sql")} == dict.fromkeys(
        ("save_draft", "draft_email", "exec_sql"), "pending")
    cards = {card["id"]: card for card in hook_decision.ask_reviews()}
    for name in ("save_draft", "draft_email", "exec_sql"):
        card = cards[held[name]["id"]]
        assert "draft" not in card and "send" not in card, name


def test_personal_data_in_a_tool_call_is_refused_by_the_real_classifier(state):
    from nodelang import hook_decision
    import os
    for module in ("spacy", "presidio_analyzer"):  # the real PII classifier decide() runs; no fake here
        pytest.importorskip(module)
    _fake_server(state)
    hook_decision.write_permissions({"tools": {"mcp:fake/draft_email": "Allowed"}})  # not even his allow lets it out
    args = {"to": "maryam.haddad@example.com", "subject": "Site visit", "body": "Call me on +971 50 123 4567"}
    out, label = host_exec.connector_call({"connector": "mcp:fake", "action": "draft_email", "args": args})
    assert label == "Failed" and out["result"] is None and out["action"] == "send"
    decision = hook_decision.decide({"tool_name": "connector.call", "cwd": os.getcwd(), "tool_input": {
        "text": args["body"], "connector": "mcp:fake", "arguments": args, "mcp_tool": "mcp:fake/draft_email"}})
    assert decision["verdict"] == "refuse" and "client-data-going-public" in decision["rules"]


@pytest.mark.parametrize("run_mode", ["Ask first", "Accept edits"])
def test_the_servers_own_read_only_hint_authorizes_nothing(state, run_mode):
    from nodelang import hook_decision
    _fake_server(state)
    assert custom_mcp.list_tools(custom_mcp._find("fake"))[1] == {
        "name": "peek", "title": "Read only", "inputs": ["text"], "readOnly": True}  # a label, shown to him
    hook_decision.write_permissions({"runMode": run_mode})
    out, label = host_exec.connector_call({"connector": "mcp:fake", "action": "peek", "args": {"text": "hi"}})
    assert label == "Waiting for you" and out["result"] is None


def test_only_his_own_per_tool_rule_allows_or_stops_a_tool(state):
    from nodelang import hook_decision
    _fake_server(state)
    hook_decision.write_permissions({"runMode": "Ask first", "tools": {"mcp:fake/peek": "Allowed"}})
    out, label = host_exec.connector_call({"connector": "mcp:fake", "action": "peek", "args": {"text": "hi"}})
    assert label == "peek" and out["result"] == "hi|"
    hook_decision.write_permissions({"tools": {"mcp:fake/echo": "Allowed"}})
    out, label = host_exec.connector_call({"connector": "mcp:fake", "action": "echo", "args": {"text": "yo"}})
    assert label == "echo" and out["result"] == "yo|"
    hook_decision.write_permissions({"tools": {"mcp:fake/*": "Off"}})
    assert host_exec.connector_call({"connector": "mcp:fake", "action": "echo", "args": {"text": "x"}})[1] == "Failed"


def test_a_secret_in_the_arguments_is_refused_like_any_public_send(state, monkeypatch):
    from nodelang import hook_decision
    _fake_server(state)
    hook_decision.write_permissions({"tools": {"mcp:fake/echo": "Allowed"}})
    monkeypatch.setattr(hook_decision, "scan_secrets", lambda text, env, **kw: (
        "ok", [{"kind": "secret", "rule": "fake", "where": "text"}] if "SECRETVALUE" in text else [], "test"))
    out, label = host_exec.connector_call({"connector": "mcp:fake", "action": "echo",
                                           "args": {"text": "token SECRETVALUE"}})
    assert label == "Failed" and out["result"] is None
    assert host_exec.connector_call({"connector": "mcp:fake", "action": "echo", "args": {"text": "fine"}})[1] == "echo"


@pytest.mark.parametrize("url", ["https://x.example/mcp?apiKey=abc", "https://x.example/mcp?token=abc",
                                 "https://x.example/mcp?q=" + "A1b2C3d4" * 6])
def test_an_address_carrying_a_key_is_refused_and_nothing_is_saved(state, url):
    with pytest.raises(custom_mcp.McpRefused, match="headers"):
        custom_mcp.add(url)
    assert custom_mcp.servers() == []


def test_sign_in_fetches_nothing_that_is_not_https(state):
    fetched = []

    def opener(request, timeout):
        fetched.append(request.full_url)
        if "oauth-protected-resource" in request.full_url:
            return _Answer(json.dumps({"authorization_servers": ["http://auth.example.com"]}).encode())
        raise AssertionError("fetched " + request.full_url)

    with pytest.raises(custom_mcp.McpRefused, match="not https"):
        custom_mcp.discover("https://mcp.example.com/mcp", opener)
    assert all(url.startswith("https://mcp.example.com/") for url in fetched)
    with pytest.raises(custom_mcp.McpRefused, match="https"):
        custom_mcp.discover("http://127.0.0.1:9/mcp", opener)
    assert all(url.startswith("https://") for url in fetched)


def test_the_gateway_for_opencode_offers_the_two_agent_tools(state):
    import asyncio
    from nodelang import custom_mcp_gateway
    from mcp.server.fastmcp import FastMCP
    server = custom_mcp_gateway.register_tools(FastMCP("archhub-tools"))
    assert {tool.name for tool in server._tool_manager.list_tools()} == {"mcp_tools", "mcp_call"}
    answer = asyncio.run(server.call_tool("mcp_tools", {}))
    payload = answer[1] if isinstance(answer, tuple) else json.loads(answer[0].text)
    assert payload == {"ok": True, "servers": []}


class _Answer(io.BytesIO):
    headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_a_server_that_answers_401_asks_for_sign_in_then_uses_the_browser_grant(state):
    import time
    import urllib.error
    from nodelang import nograph_server
    _tmp, store, _script = state
    url = "https://mcp.example.com/mcp"
    metadata = {
        "https://mcp.example.com/.well-known/oauth-protected-resource/mcp": {"authorization_servers": ["https://auth.example.com"]},
        "https://auth.example.com/.well-known/oauth-authorization-server": {
            "authorization_endpoint": "https://auth.example.com/authorize", "token_endpoint": "https://auth.example.com/token",
            "registration_endpoint": "https://auth.example.com/register"}}
    seen = []

    def opener(request, timeout):
        if request.get_method() == "GET":
            if request.full_url not in metadata:
                raise urllib.error.HTTPError(request.full_url, 404, "no", {}, None)
            return _Answer(json.dumps(metadata[request.full_url]).encode())
        auth = request.get_header("Authorization")
        seen.append(auth)
        if auth != "Bearer live":
            raise urllib.error.HTTPError(request.full_url, 401, "sign in", {}, None)
        body = json.loads(request.data)
        return _Answer(json.dumps({"jsonrpc": "2.0", "id": body.get("id"), "result": {"tools": []}}).encode())

    [row] = custom_mcp.add(url)
    with pytest.raises(custom_mcp.McpRefused, match=custom_mcp.SIGN_IN_NEEDED):
        custom_mcp.list_tools(row, store=store, opener=opener)
    original = custom_mcp.list_tools
    custom_mcp.list_tools = lambda r, **kw: original(r, store=store, opener=opener)
    try:
        with pytest.raises(nograph_server.Refused, match="sign in"):
            nograph_server._mcp_op("discover_mcp_tools", [row["id"]])
        assert nograph_server._mcp_rows()[0]["status"] == "Sign in needed"
    finally:
        custom_mcp.list_tools = original
    assert custom_mcp.discover(url, opener) == {"authorize": "https://auth.example.com/authorize",
                                               "token": "https://auth.example.com/token",
                                               "register": "https://auth.example.com/register"}
    asked = {}

    def connect(**kw):
        asked.update(kw)
        kw["save"](kw["grant_key"], json.dumps({"client_id": "c", "access_token": "live", "refresh_token": "r",
                                                "expires_at": time.time() + 3600}))
        return {"ok": True}

    custom_mcp.sign_in(row["id"], store=store, opener=opener, connect=connect, open_browser=lambda u: None)
    assert asked["resource"] == url and asked["grant_key"] == "mcp-mcp-example-com-oauth-grant"
    signed = custom_mcp._find(row["id"])
    assert signed["auth"] == "oauth" and "live" not in json.dumps(custom_mcp.servers())
    assert custom_mcp.list_tools(signed, store=store, opener=opener) == []
    custom_mcp.remove(row["id"])
    assert store.keys == {}


def test_cli_sign_in_is_read_from_its_own_file_and_opens_its_own_login(tmp_path):
    env = {"USERPROFILE": str(tmp_path), "PATH": ""}
    assert model_router.cli_signed_in("codex", env) is False
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "auth.json").write_text("{}", encoding="utf-8")
    assert model_router.cli_signed_in("codex", env) is True
    assert model_router.cli_signed_in("cursor", env) is None
    started = []
    original = model_router.find_assistant
    model_router.find_assistant = lambda exe, environ=None: "C:/bin/" + exe + ".cmd"
    try:
        assert model_router.sign_in_launch("codex", popen=started.append) == {"ok": True, "opened": "console"}
        opened = []
        assert model_router.sign_in_launch("antigravity", startfile=opened.append)["opened"] == "app"
    finally:
        model_router.find_assistant = original
    assert started == [["cmd.exe", "/c", "start", "ArchHub sign-in", "cmd.exe", "/k", "C:/bin/codex.cmd", "login"]]
    with pytest.raises(model_router.ModelRouteRefused):
        model_router.sign_in_launch("grok")


def test_provider_rows_carry_sign_in_and_name_grok(tmp_path):
    rows = model_router.provider_rows(environ={"USERPROFILE": str(tmp_path), "PATH": ""},
                                      secrets_loader=lambda name: "", cloud_session=None,
                                      local_probe=lambda h, p: False, cli_probe=lambda exe: None)
    by = {row["id"]: row for row in rows}
    assert by["claude-code"]["signIn"] is False and by["claude-code"]["signedIn"] is None
    assert by["grok"]["state"] == "not supported"


def test_studio_ops_list_add_switch_and_remove(state):
    from nodelang import nograph_server
    _tmp, _store, script = state
    added = nograph_server._mcp_op("add_mcp_server", ['"%s" -I "%s"' % (sys.executable, script)])
    [row] = added["servers"]
    assert row["status"] == "5 tools" and row["tools"][0]["id"] == "echo" and row["enabled"] is True
    assert nograph_server._mcp_op("set_mcp_server_enabled", [row["id"], False])[0]["status"] == "Off"
    assert nograph_server._mcp_op("remove_mcp_server", [row["id"]]) == []
    with pytest.raises(nograph_server.Refused, match="No such"):
        nograph_server._mcp_op("discover_mcp_tools", ["gone"])


def test_preparing_a_tool_leaves_the_other_windows_file_untouched(state):
    from nodelang import nograph_server, session_files
    tmp, _store, _script = state
    path = tmp / "other.archhub"
    session_files.write_document(path, session_files.new_document("Other window"))
    session_files.SessionFiles().dispatch({"action": "open", "path": str(path)})
    original = path.read_bytes()

    node = nograph_server._mcp_op("prepare_mcp_tool", ["office", "xlsx_tool"])["node"]
    assert node["params"]["connector"] == "mcp:office" and node["params"]["action"] == "xlsx_tool"
    assert path.read_bytes() == original

    placed = nograph_server._mcp_op("import_mcp_tool", ["office", "xlsx_tool"])
    assert [n["id"] for n in session_files.read_document(path)["nodes"]] == [placed["id"]]
