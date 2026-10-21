"""Court support: the model loop of a native Workshop agent, and nothing else.

Launched in place of the Claude CLI by a court's launch factory, with the exact argv and
environment the Workshop profile built. Everything around the model stays real: this process
starts the profile's own MCP server (nodelang.native_agent_mcp --workshop-task), which enrolls
over the application's real machine pipe as this process's descendant; it answers the CLI's
stream-json control protocol from what that server actually reports; and for a task turn it
returns the model's answer. It never reads user settings, calls a provider or writes a file.

Behavior (environment, set by the court before the profile is built):
  ARCHHUB_NATIVE_DOUBLE_ANSWER   the model's final text for a turn, or "!error" for a provider error
  ARCHHUB_NATIVE_DOUBLE_GATE     a directory: write turn-started, then wait for go before answering
  ARCHHUB_NATIVE_DOUBLE_TURNS    a file: one line is appended for every task turn this process takes
"""
import json
import os
import subprocess
import sys
import threading
import time
import uuid


def _argument(name):
    return sys.argv[sys.argv.index(name) + 1]


def _emit(event):
    sys.stdout.buffer.write((json.dumps(event, separators=(",", ":")) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


class _Mcp:
    """A minimal stdio MCP client for the profile's one server."""

    def __init__(self, spec):
        env = dict(os.environ)
        env.update(spec.get("env") or {})
        self.process = subprocess.Popen([spec["command"], *spec["args"]], env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self._next = 0

    def _send(self, message):
        self.process.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
        self.process.stdin.flush()

    def request(self, method, params):
        self._next += 1
        ident = self._next
        self._send({"jsonrpc": "2.0", "id": ident, "method": method, "params": params})
        while True:
            line = self.process.stdout.readline()
            if not line:
                raise RuntimeError("MCP server closed during " + method)
            message = json.loads(line)
            if message.get("id") == ident:
                if "error" in message:
                    raise RuntimeError("MCP %s refused: %s" % (method, message["error"]))
                return message.get("result") or {}

    def notify(self, method):
        self._send({"jsonrpc": "2.0", "method": method})

    def close(self):
        try:
            self.process.stdin.close()
        except OSError:
            pass
        try:
            self.process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.process.kill()


def main():
    session = _argument("--session-id")
    with open(_argument("--mcp-config"), encoding="utf-8") as stream:
        servers = json.load(stream)["mcpServers"]
    (name, spec), = servers.items()
    mcp = _Mcp(spec)
    tools, status = [], {"state": "pending"}

    def connect():
        try:
            mcp.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                       "clientInfo": {"name": "archhub-court-native-double", "version": "1"}})
            mcp.notify("notifications/initialized")
            tools.extend(tool["name"] for tool in mcp.request("tools/list", {}).get("tools", []))
            status["state"] = "connected"
        except Exception as error:  # noqa: BLE001 - reported through mcp_status, as the CLI does
            status["state"] = "failed"
            status["error"] = str(error)[:200]
    threading.Thread(target=connect, daemon=True).start()
    answer = os.environ.get("ARCHHUB_NATIVE_DOUBLE_ANSWER", "")
    gate = os.environ.get("ARCHHUB_NATIVE_DOUBLE_GATE")
    try:
        for raw in sys.stdin.buffer:
            event = json.loads(raw)
            if event.get("type") == "control_request":
                subtype = event["request"]["subtype"]
                if subtype == "mcp_status":
                    payload = {"mcpServers": [{"name": name, "status": status["state"],
                                               "tools": [{"name": tool} for tool in tools]}]}
                else:
                    payload = {}
                _emit({"type": "control_response", "response": {"subtype": "success",
                       "request_id": event["request_id"], "response": payload}})
            elif event.get("type") == "user":
                turns = os.environ.get("ARCHHUB_NATIVE_DOUBLE_TURNS")
                if turns:
                    with open(turns, "a", encoding="utf-8") as log:
                        log.write(session + "\n")
                if gate:
                    open(os.path.join(gate, "turn-started"), "w").close()
                    deadline = time.monotonic() + 120
                    while not os.path.exists(os.path.join(gate, "go")) and time.monotonic() < deadline:
                        time.sleep(0.05)
                if answer == "!error":
                    _emit({"type": "result", "subtype": "error_during_execution", "is_error": True,
                           "errors": ["provider unavailable"], "uuid": str(uuid.uuid4()),
                           "session_id": session})
                else:
                    _emit({"type": "result", "subtype": "success", "is_error": False, "result": answer,
                           "uuid": str(uuid.uuid4()), "session_id": session})
    finally:
        mcp.close()


if __name__ == "__main__":
    main()
