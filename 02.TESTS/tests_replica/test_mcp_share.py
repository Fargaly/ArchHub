"""Court: one loopback MCP endpoint. Native tools spawn nothing. Stateless stdio is one process.

The upstream is a stand-in child that speaks newline JSON-RPC on stdin, so a shared server is one
pid and a stateful server is one pid per MCP session. Agent configs are copies in a temp profile.
"""
from __future__ import annotations

import http.client
import json
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from nodelang import client_mcp_installation as inst  # noqa: E402
import importlib.util
import time

from nodelang.mcp_share import McpHost, agent_token  # noqa: E402

FAKE = textwrap.dedent('''
    import json, os, sys
    pid = os.getpid()
    n = 0
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if "id" not in msg:
            continue
        n += 1
        method = msg.get("method")
        if method == "initialize":
            result = {"protocolVersion": "2025-03-26", "capabilities": {}, "serverInfo": {"name": "fake", "version": "0"}}
        elif method == "tools/list":
            result = {"tools": [{"name": "ping", "description": "p", "inputSchema": {"type": "object"}}]}
        else:
            result = {"content": [{"type": "text", "text": json.dumps({
                "pid": pid, "n": n, "session": os.environ.get("ARCHHUB_MCP_SESSION"),
                "auth": os.environ.get("AUTHORIZATION")})}]}
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}) + "\\n")
        sys.stdout.flush()
''')


LIMITS = {"port": 0, "idle_seconds": 0.2, "start_timeout": 30, "upstream_timeout": 30,
          "reap_every": 30, "poll": 0.1, "stop_wait": 5}


class Desk:
    """In-process Workshop, brokers and canvas. One object for every agent."""

    def __init__(self):
        self.instance = "native-1"

    def tools(self):
        return [
            {"name": "declare", "description": "Workshop", "inputSchema": {"type": "object"}},
            {"name": "hosts_state", "description": "Brokers", "inputSchema": {"type": "object"}},
            {"name": "canvas.list_open", "description": "Canvas", "inputSchema": {"type": "object"}},
        ]

    def call(self, name, arguments, agent, session):
        return {"instance": self.instance, "name": name, "agent": agent, "session": session}


@pytest.fixture
def host(tmp_path):
    script = tmp_path / "fake_stdio.py"
    script.write_text(FAKE)
    spans = []
    spec = {"command": sys.executable, "args": ["-u", str(script)]}
    h = McpHost({"notion": dict(spec), "screen": {**spec, "stateful": True},
                 "cua": {**spec, "stateful": True}},
                {"notion"}, "s3cret", LIMITS, span=spans.append, native=Desk()).start()
    h.spans = spans
    time.sleep(0.05)
    assert h.httpd.server_address[0] == "127.0.0.1"
    yield h
    h.close()


def post(h, path, agent, method, params=None, token="ok", session=None, **headers):
    port = h.httpd.server_address[1]
    if token == "ok":
        token = agent_token("s3cret", agent)
    hdrs = {"Host": "127.0.0.1:%d" % port, "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"}
    if token is not None:
        hdrs["Authorization"] = "Bearer " + token
    if session:
        hdrs["Mcp-Session-Id"] = session
    hdrs.update(headers)
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("POST", path, body.encode(), hdrs)
    reply = conn.getresponse()
    return reply.status, reply.getheader("Mcp-Session-Id"), reply.read()


def opened(h, path, agent, **headers):
    status, sid, body = post(h, path, agent, "initialize", {
        "protocolVersion": "2025-03-26", "capabilities": {},
        "clientInfo": {"name": agent, "version": "0"}}, **headers)
    assert status == 200, body
    return sid


def called(h, path, agent, sid, name="ping"):
    status, _, body = post(h, path, agent, "tools/call", {"name": name, "arguments": {}}, session=sid)
    assert status == 200, body
    payload = json.loads(body)
    assert "error" not in payload, payload
    return json.loads(payload["result"]["content"][0]["text"])


def test_nothing_runs_until_the_first_call(host):
    assert host.running() == []
    sid = opened(host, "/s/notion/mcp", "codex")
    assert host.running() == []
    assert called(host, "/s/notion/mcp", "codex", sid)["pid"] > 0
    assert host.running() == [("notion",)]


def test_stateless_server_is_one_process_for_all_agents(host):
    pids = set()
    for agent in ("codex", "cursor", "claude-code"):
        sid = opened(host, "/s/notion/mcp", agent)
        pids.add(called(host, "/s/notion/mcp", agent, sid)["pid"])
    assert len(pids) == 1 and len(host.running()) == 1


def test_stateful_server_is_one_process_per_session(host):
    first = opened(host, "/s/screen/mcp", "codex")
    second = opened(host, "/s/screen/mcp", "cursor")
    a = called(host, "/s/screen/mcp", "codex", first)
    b = called(host, "/s/screen/mcp", "cursor", second)
    again = called(host, "/s/screen/mcp", "codex", first)
    assert a["pid"] != b["pid"] and again["pid"] == a["pid"]
    assert a["session"] != b["session"] and a["auth"] is None


def test_idle_upstream_is_reaped_and_restarts_on_the_next_call(host):
    sid = opened(host, "/s/notion/mcp", "codex")
    first = called(host, "/s/notion/mcp", "codex", sid)["pid"]
    assert host.reap(now=1e12) == [("notion",)] and host.running() == []
    assert called(host, "/s/notion/mcp", "codex", sid)["pid"] != first
    assert [event["event"] for event in host.spans] == ["start", "stop", "start"]


def test_token_host_and_origin_are_refused_before_anything_starts(host):
    assert post(host, "/mcp", "codex", "initialize", token=None)[0] == 401
    assert post(host, "/s/notion/mcp", "codex", "initialize", token="wrong")[0] == 401
    assert post(host, "/s/notion/mcp", "codex", "initialize", token="not-a-token")[0] == 401
    assert post(host, "/mcp", "codex", "initialize", Origin="http://evil.example")[0] == 403
    assert post(host, "/mcp", "codex", "initialize", Host="evil.example")[0] == 403
    assert host.running() == []


def test_session_end_reaps_that_stateful_copy_only(host):
    kept = opened(host, "/s/cua/mcp", "codex")
    gone = opened(host, "/s/cua/mcp", "codex")
    live = called(host, "/s/cua/mcp", "codex", kept)
    called(host, "/s/cua/mcp", "codex", gone)
    port = host.httpd.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("DELETE", "/s/cua/mcp", headers={
        "Authorization": "Bearer " + agent_token("s3cret", "codex"),
        "Host": "127.0.0.1:%d" % port, "Mcp-Session-Id": gone})
    assert conn.getresponse().status == 200
    assert host.running() == [("cua", "codex", kept)]
    assert called(host, "/s/cua/mcp", "codex", kept)["pid"] == live["pid"]


def test_native_workshop_brokers_and_canvas_are_one_instance_and_spawn_nothing(host):
    left = opened(host, "/mcp", "codex")
    right = opened(host, "/mcp", "cursor")
    listed = json.loads(post(host, "/mcp", "codex", "tools/list", session=left)[2])
    names = {tool["name"] for tool in listed["result"]["tools"]}
    assert {"declare", "hosts_state", "canvas.list_open"} <= names
    a = called(host, "/mcp", "codex", left, "declare")
    b = called(host, "/mcp", "cursor", right, "send")
    assert a["instance"] == b["instance"] == "native-1"
    assert host.running() == []


def test_runtime_entry_is_the_url_and_the_connector_is_not_a_child(tmp_path, monkeypatch):
    install = tmp_path / "ArchHub"
    (install / ".venv" / "Scripts").mkdir(parents=True)
    (install / ".venv" / "Scripts" / "python.exe").write_bytes(b"MZ")
    (install / "nodelang").mkdir()
    (install / "nodelang" / "native_agent_mcp.py").write_text("x")
    env = {"LOCALAPPDATA": str(tmp_path), "USERPROFILE": str(tmp_path)}
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert inst.managed_entry(install, tmp_path)["command"] == str(install / ".venv" / "Scripts" / "python.exe")
    limits = {"port": 47831, "idle_seconds": 600, "start_timeout": 30, "upstream_timeout": 300,
              "reap_every": 30, "poll": 0.2, "stop_wait": 5}
    runtime = inst.deploy_runtime(install, env, limits)
    (runtime / "venv" / "Scripts").mkdir(parents=True)
    (runtime / "venv" / "Scripts" / "python.exe").write_bytes(b"MZ")
    assert inst.ensure_runtime(env, popen=lambda *a, **k: None) == "started"
    entry = inst.managed_entry(install, tmp_path, "codex")
    assert entry["url"] == "http://127.0.0.1:47831/mcp"
    assert entry["http_headers"]["Authorization"].startswith("Bearer ")
    assert "command" not in entry and str(install) not in json.dumps(entry)
    cfg = json.loads((runtime / "mcp-share.json").read_text(encoding="utf-8"))
    assert cfg["native"] is True and "proxy" not in cfg and "connector" not in cfg["servers"]
    assert "mcp_proxy" not in json.dumps(cfg)


def test_agent_onboard_verify_proves_one_url_and_stdio_is_gone(tmp_path):
    home = tmp_path / "home"
    for sub in (".cursor", ".gemini", ".gemini/antigravity", ".config/opencode", ".codex", ".claude"):
        (home / sub).mkdir(parents=True)
    shim = {"command": "python.exe", "args": ["-c", "runpy.run_module('nodelang.native_agent_mcp')"]}
    other = {"command": "keep-me"}
    for rel, key in ((".claude.json", "mcpServers"), (".cursor/mcp.json", "mcpServers"),
                     (".gemini/settings.json", "mcpServers"),
                     (".gemini/antigravity/mcp_config.json", "mcpServers"),
                     (".config/opencode/opencode.json", "mcp")):
        (home / rel).parent.mkdir(parents=True, exist_ok=True)
        (home / rel).write_text(json.dumps({"theme": "dark", key: {
            "archhub-agent": shim, "archhub-old": shim, "other": other}}), encoding="utf-8")
    (home / ".codex" / "config.toml").write_text(
        'model = "x"\n\n[mcp_servers.archhub-agent]\ncommand = "python.exe"\n'
        'args = ["nodelang.native_agent_mcp"]\n\n[mcp_servers.other]\ncommand = "keep-me"\n',
        encoding="utf-8")
    secret = tmp_path / "secret.txt"
    secret.write_text("s3cret", encoding="ascii")
    cfg_path = tmp_path / "mcp-share.json"
    cfg_path.write_text(json.dumps({"secret_file": str(secret), "limits": {"port": 47831}, "native": True}),
                        encoding="utf-8")
    spec = importlib.util.spec_from_file_location(
        "mcp_share_config",
        Path(r"C:\Users\fargaly\00.ARCHUB\00.GOVERNANCE\03.AGENT-HOOKS\mcp_share_config.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    env = {"ARCHHUB_MCP_SHARE_CONFIG": str(cfg_path), "LOCALAPPDATA": str(tmp_path)}
    report = mod.publish(home, "http://127.0.0.1:47831/mcp", "s3cret")
    assert "cursor" in report["wrote"] and any(item.endswith(":archhub-old") for item in report["removed"])
    lines = mod.sync(home, env, write=False)
    assert lines == ["verify: mcp share ok claude-code,cursor,gemini-cli,antigravity,opencode,codex"]
    for rel in (".claude.json", ".cursor/mcp.json", ".gemini/settings.json",
                ".config/opencode/opencode.json"):
        text = (home / rel).read_text(encoding="utf-8")
        assert "http://127.0.0.1:47831/mcp" in text and "native_agent_mcp" not in text and "keep-me" in text
        assert json.loads(text)["theme"] == "dark"
    toml = (home / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert 'model = "x"' in toml and "keep-me" in toml and "native_agent_mcp" not in toml
    assert "http://127.0.0.1:47831/mcp" in toml
    onboard = Path(r"C:\Users\fargaly\00.ARCHUB\00.GOVERNANCE\03.AGENT-HOOKS\agent_onboard.py").read_text(encoding="utf-8")
    assert "_mcp_share_lines(home, write=False)" in onboard
    assert 'if "--verify" in sys.argv[1:]' in onboard


# ---- the writer: six agents, copies only ------------------------------------------------------

SPECS = {"notion": {"command": "npx", "args": ["-y", "notion-mcp"]}}
BASE = "http://127.0.0.1:47831"


@pytest.fixture
def profile(tmp_path):
    for sub in (".cursor", ".gemini", ".gemini/antigravity", ".config/opencode", ".codex"):
        (tmp_path / sub).mkdir(parents=True)
    own = {"command": "npx", "args": ["-y", "notion-mcp"]}
    other = {"command": "keep-me"}
    for rel, key in ((".cursor/mcp.json", "mcpServers"), (".gemini/settings.json", "mcpServers"),
                     (".gemini/antigravity/mcp_config.json", "mcpServers"),
                     (".config/opencode/opencode.json", "mcp")):
        (tmp_path / rel).write_text(json.dumps({"theme": "dark", key: {"notion": own, "other": other}}))
    (tmp_path / ".codex/config.toml").write_text(
        'model = "x"\n\n[mcp_servers.notion]\ncommand = "npx"\nargs = ["-y", "notion-mcp"]\n\n'
        '[mcp_servers.notion.env]\nK = "v"\n\n[mcp_servers.other]\ncommand = "keep-me"\n')
    return {"USERPROFILE": str(tmp_path), "PATH": ""}, tmp_path


@pytest.mark.parametrize("client", ["cursor", "gemini-cli", "antigravity", "opencode", "codex"])
def test_entry_is_added_original_replaced_other_kept_and_restored(profile, client):
    env, home = profile
    receipt = home / "receipt.json"
    r = inst.install_gateway(client, BASE, SPECS, "tok", receipt=receipt, replace=True, environment=env)
    assert r["state"] == "registered" and r["added"] == ["archhub-notion"] and r["replaced"] == ["notion"]
    path = inst._codex_toml(env) if client == "codex" else inst._gateway_file(client, env)[0]
    text = path.read_text()
    assert BASE + "/s/notion/mcp" in text and "keep-me" in text and "notion-mcp" not in text
    if client != "codex":
        assert json.loads(text)["theme"] == "dark"
    else:
        assert 'model = "x"' in text and "[mcp_servers.notion.env]" not in text
    back = inst.remove_gateway(client, receipt=receipt, environment=env)
    assert back["restored"] == ["notion"] and back["removed"] == ["archhub-notion"]
    assert "notion-mcp" in path.read_text() and "archhub-notion" not in path.read_text()


def test_unrecognised_original_is_kept_and_unreadable_config_is_untouched(profile):
    env, home = profile
    cfg = home / ".cursor/mcp.json"
    cfg.write_text(json.dumps({"mcpServers": {"notion": {"command": "my-own-fork"}}}))
    r = inst.install_gateway("cursor", BASE, SPECS, "tok", replace=True, environment=env)
    assert r["replaced"] == [] and json.loads(cfg.read_text())["mcpServers"]["notion"] == {"command": "my-own-fork"}
    cfg.write_text("// jsonc\n{}")
    assert inst.install_gateway("cursor", BASE, SPECS, "tok", environment=env)["state"] == "config_unreadable"
    assert cfg.read_text() == "// jsonc\n{}"


def test_an_agent_that_is_not_installed_gets_no_folder(tmp_path):
    env = {"USERPROFILE": str(tmp_path), "PATH": ""}
    assert inst.install_gateway("gemini-cli", BASE, SPECS, "tok", environment=env)["state"] == "not_installed"
    assert not (tmp_path / ".gemini").exists()


def test_claude_code_goes_through_its_own_command(tmp_path):
    exe = tmp_path / "bin" / "claude.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"MZ")
    (tmp_path / ".claude.json").write_text(json.dumps({"mcpServers": {"notion": SPECS["notion"]}}))
    env = {"USERPROFILE": str(tmp_path), "PATH": str(exe.parent)}
    calls = []

    class Done:
        returncode = 0

    r = inst.install_gateway("claude-code", BASE, SPECS, "tok", replace=True, environment=env,
                             run=lambda argv, **kw: calls.append(argv) or Done())
    assert r["state"] == "registered"
    assert [c[1:4] for c in calls] == [["mcp", "remove", "notion"], ["mcp", "add-json", "archhub-notion"]]
    assert json.loads(calls[1][4])["type"] == "http"
