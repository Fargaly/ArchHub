"""Court: the native MCP connection survives its worker ending (founder, 2026-09-30).

"The connector problem must end and never repeat." The worker (native owner)
used to be the whole server: when it died, or refused to start because the
application was still opening or its bind was refused, the client kept a dead
connection that showed "connected" while every call failed. The stable launcher
now replaces a worker that ends, answers initialize itself when the worker is
slow, never replays a call that was in flight, and tells the client when the
tools are back.
"""
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from test_native_mcp_launcher import Client, _owner  # noqa: E402

REVIVING_WORKER = r'''
import json, os, sys, threading, time
starts = os.environ["FAKE_STARTS"]
with open(starts, "a", encoding="utf-8") as out:
    out.write("x")
count = len(open(starts, encoding="utf-8").read())
if count <= int(os.environ.get("FAKE_DIE_FIRST", "0")):
    sys.exit(3)  # e.g. its bind was refused at startup
delay = float(os.environ.get("FAKE_INIT_DELAY", "0")) if count == 1 else 0.0
pid = os.getpid()
lock = threading.Lock()
def reply(ident, result):
    with lock:
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": ident, "result": result}) + "\n")
        sys.stdout.flush()
def text(value):
    return {"content": [{"type": "text", "text": json.dumps(value)}], "isError": False}
def call(ident, name):
    if name == "die":
        os._exit(1)
    if name == "native.owner_status":
        return reply(ident, text({"state": "bound"}))
    return reply(ident, text({"pid": pid}))
for line in sys.stdin:
    message = json.loads(line)
    method, ident = message.get("method"), message.get("id")
    if method == "initialize":
        time.sleep(delay)
        reply(ident, {"protocolVersion": "2025-06-18", "capabilities": {"tools": {"listChanged": True}},
                      "serverInfo": {"name": "worker", "version": str(pid)}})
    elif method == "tools/list":
        reply(ident, {"tools": [{"name": "echo"}, {"name": "die"}]})
    elif method == "tools/call":
        threading.Thread(target=call, args=(ident, message["params"]["name"]), daemon=True).start()
'''


def _client(tmp_path, monkeypatch, **env):
    script = tmp_path / "reviving_worker.py"
    script.write_text(REVIVING_WORKER, encoding="utf-8")
    monkeypatch.setenv("FAKE_STARTS", str(tmp_path / "starts"))
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    import test_native_mcp_launcher as harness
    monkeypatch.setattr(harness, "WORKER", REVIVING_WORKER)
    made = Client(tmp_path, _owner())
    made.launcher._revive_delays = (0.2,)
    return made


def _starts(tmp_path):
    return len((tmp_path / "starts").read_text(encoding="utf-8"))


def test_a_worker_that_ends_is_replaced_and_the_client_is_told(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    try:
        client.start()
        first = client.tool("echo")["pid"]
        lost = client.request("tools/call", {"name": "die", "arguments": {}}, wait=False)
        answer = client.answer(lost)
        assert "error" in answer and "not replayed" in answer["error"]["message"]
        client.notification("notifications/tools/list_changed")
        assert client.tool("echo")["pid"] != first
        assert _starts(tmp_path) == 2  # the dying call was never sent to the new worker
    finally:
        client.close()


def test_a_worker_that_dies_before_initialize_still_gives_the_client_a_server(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, FAKE_DIE_FIRST="2")
    try:
        answer = client.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                               "clientInfo": {"name": "court", "version": "1"}})
        assert answer["result"]["capabilities"]["tools"]["listChanged"] is True
        client.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        if answer["result"]["serverInfo"]["version"] == "launcher":
            # Answered by the host while no worker was up: the tools follow.
            client.notification("notifications/tools/list_changed")
        assert type(client.tool("echo")["pid"]) is int
        assert _starts(tmp_path) == 3
    finally:
        client.close()


def test_a_slow_worker_does_not_time_the_client_out(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, FAKE_INIT_DELAY="3")
    client.launcher._init_timeout = 0.5
    try:
        began = time.monotonic()
        answer = client.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                               "clientInfo": {"name": "court", "version": "1"}})
        assert time.monotonic() - began < 2.5
        assert answer["result"]["serverInfo"]["version"] == "launcher"
        client.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        client.notification("notifications/tools/list_changed", timeout=10)
        assert type(client.tool("echo")["pid"]) is int
        assert _starts(tmp_path) == 1  # the same worker, only slower; nothing restarted
    finally:
        client.close()
