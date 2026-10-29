"""Court: one local MCP host, lazy and reaped, shared only where stateless, behind a token; six agents' entries.

Real HTTP and real child processes. The upstream is a stand-in that speaks mcp-proxy's argv and answers
POST /mcp with its pid and a call counter, so shared (one pid) and per-agent (a pid each, own counter)
are observable. Agent configs are copies in a temp profile; nothing of the person's is touched.
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
from nodelang.mcp_share import McpHost, agent_token  # noqa: E402

FAKE = textwrap.dedent('''
    import json, os, sys
    from http.server import BaseHTTPRequestHandler, HTTPServer
    port = int(sys.argv[sys.argv.index("--port") + 1]); n = [0]
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0)); n[0] += 1
            body = json.dumps({"pid": os.getpid(), "n": n[0], "auth": self.headers.get("Authorization"),
                               "origin": self.headers.get("Origin")}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    HTTPServer(("127.0.0.1", port), H).serve_forever()
''')


LIMITS = {"port": 0, "idle_seconds": 0.2, "start_timeout": 30, "upstream_timeout": 30,
          "reap_every": 30, "poll": 0.1, "stop_wait": 5}


@pytest.fixture
def host(tmp_path):
    script = tmp_path / "fake_proxy.py"
    script.write_text(FAKE)
    spans = []
    h = McpHost({"notion": {"command": "x"}, "screen": {"command": "y"}}, {"notion"}, "s3cret",
                [sys.executable, str(script)], LIMITS, span=spans.append).start()
    h.spans = spans
    yield h
    h.close()


def call(h, name, agent, token="ok", **headers):
    port = h.httpd.server_address[1]
    token = agent_token("s3cret", agent) if token == "ok" else token
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("POST", "/%s/%s/mcp" % (name, agent), b"{}",
                 {"Authorization": "Bearer " + token, "Host": "127.0.0.1:%d" % port, **headers})
    r = conn.getresponse()
    return r.status, r.read()


def test_nothing_runs_until_the_first_call(host):
    assert host.running() == []
    assert call(host, "notion", "codex")[0] == 200
    assert host.running() == ["notion"]


def test_stateless_server_is_one_process_for_all_agents(host):
    pids = {json.loads(call(host, "notion", a)[1])["pid"] for a in ("codex", "cursor", "claude-code")}
    assert len(pids) == 1 and len(host.running()) == 1


def test_stateful_server_gets_a_copy_per_agent_with_no_crosstalk(host):
    a = [json.loads(call(host, "screen", "codex")[1]) for _ in range(3)]
    b = [json.loads(call(host, "screen", "cursor")[1]) for _ in range(3)]
    assert {x["pid"] for x in a}.isdisjoint({x["pid"] for x in b})
    assert [x["n"] for x in a] == [1, 2, 3] and [x["n"] for x in b] == [1, 2, 3]


def test_idle_upstream_is_reaped_and_restarts_on_the_next_call(host):
    first = json.loads(call(host, "notion", "codex")[1])["pid"]
    assert host.reap(now=1e12) == ["notion"] and host.running() == []
    assert json.loads(call(host, "notion", "codex")[1])["pid"] != first
    assert [e["event"] for e in host.spans] == ["start", "stop", "start"]


def test_token_and_origin_are_enforced_and_the_token_never_reaches_the_server(host):
    assert call(host, "notion", "codex", token="wrong")[0] == 401
    assert call(host, "notion", "codex", token=agent_token("s3cret", "cursor"))[0] == 401  # another agent's
    assert call(host, "notion", "codex", Origin="http://evil.example")[0] == 403
    assert call(host, "notion", "codex", Host="evil.example")[0] == 403
    assert host.running() == [], "refused calls must not start anything"
    seen = json.loads(call(host, "notion", "codex")[1])
    assert seen["auth"] is None and seen["origin"] is None


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
    assert BASE + "/notion/%s/mcp" % client in text and "keep-me" in text and "notion-mcp" not in text
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
