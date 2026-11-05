"""One local MCP endpoint for every agent on the machine.

Streamable HTTP on 127.0.0.1. Workshop, brokers and canvas are answered in this
process, so an agent does not launch a stdio shim. Stateless third-party servers
are started once, on the first call, by our own stdio front (mcp-proxy is only a
behaviour reference and is not spawned). Stateful servers (cua, rea,
desktop-commander) stay one process per MCP session, started on first use and
stopped when that session ends or the process has been idle.

Admission is the loopback Host/Origin check (403), then a per-agent bearer token
(401). The token never reaches an upstream. Every start and stop is one span.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from .http_server import QuietThreadingHTTPServer, local_browser_admission_error

MAX_BODY = 8 * 1024 * 1024
PROTOCOL = "2025-03-26"
STATEFUL = frozenset({"cua", "rea", "desktop-commander"})
AGENTS = ("claude-code", "codex", "cursor", "opencode", "gemini-cli", "antigravity", "goose")
# Names the in-process desk advertises. Calling one does not start a process.
NATIVE_TOOLS = (
    {"name": "declare", "description": "Workshop: keep your current task, paths and status.",
     "inputSchema": {"type": "object"}},
    {"name": "send", "description": "Workshop: post to the shared room.",
     "inputSchema": {"type": "object"}},
    {"name": "read", "description": "Workshop: read messages and live declarations.",
     "inputSchema": {"type": "object"}},
    {"name": "hosts_state", "description": "Brokers: which design hosts are answering.",
     "inputSchema": {"type": "object"}},
    {"name": "canvas.list_open", "description": "Canvas: documents open in this workspace.",
     "inputSchema": {"type": "object"}},
    {"name": "canvas.read", "description": "Canvas: read one .archhub document.",
     "inputSchema": {"type": "object"}},
    {"name": "library.search", "description": "Canvas: search the node library.",
     "inputSchema": {"type": "object"}},
)


def agent_token(secret: str, agent: str) -> str:
    """The bearer token bound to one agent name."""
    return hmac.new(secret.encode("utf-8"), ("mcp-share|" + agent).encode("utf-8"),
                    hashlib.sha256).hexdigest()


def load_secret(path) -> str:
    """Created once, then read back. The host and the config writer share the file."""
    path = Path(path)
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_urlsafe(32), encoding="ascii")
    return path.read_text(encoding="ascii").strip()


def match_agent(secret: str, token: str, agents) -> str | None:
    found = None
    for agent in agents:
        if hmac.compare_digest(token.encode("utf-8"), agent_token(secret, agent).encode("utf-8")):
            found = agent
    return found


class LiveDesk:
    """Workshop, brokers and canvas inside this process. Nothing is imported until a tool is called."""

    def tools(self):
        return [dict(tool) for tool in NATIVE_TOOLS]

    def call(self, name, arguments, agent, session):
        server = self._server()
        tool = server._tool_manager.get_tool(name)
        if tool is None:
            raise KeyError(name)
        import inspect
        kwargs = dict(arguments or {})
        if "ctx" in inspect.signature(tool.fn).parameters:
            kwargs["ctx"] = _CallCtx(agent, session)
        return tool.fn(**kwargs)

    def _server(self):
        if getattr(self, "_built", None) is None:
            from .native_agent_mcp import build_server
            self._built = build_server()
        return self._built


class _CallCtx:
    def __init__(self, agent, session):
        self.session = None
        self.request_context = type("RC", (), {"meta": None})()
        self.agent, self.session_id = agent, session


class _Bridge:
    """Newline JSON-RPC over a stdio child. One reader, callers wait on the matching id."""

    def __init__(self, proc, timeout):
        self.proc, self.timeout = proc, timeout
        self._seq, self._waiters, self._lock = 0, {}, threading.Lock()
        self._gone = threading.Event()
        threading.Thread(target=self._read, daemon=True, name="archhub-mcp-stdio").start()

    def _read(self):
        try:
            while True:
                line = self.proc.stdout.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line.decode("utf-8"))
                except ValueError:
                    continue
                slot = self._waiters.get(msg.get("id"))
                if slot is not None:
                    slot["msg"] = msg
                    slot["ev"].set()
        finally:
            self._gone.set()
            for slot in list(self._waiters.values()):
                slot.setdefault("msg", {"error": {"code": -32000, "message": "upstream closed"}})
                slot["ev"].set()

    def _write(self, msg):
        self.proc.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
        self.proc.stdin.flush()

    def notify(self, method, params=None):
        with self._lock:
            self._write({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def request(self, method, params=None):
        with self._lock:
            self._seq += 1
            ident = self._seq
            slot = {"ev": threading.Event()}
            self._waiters[ident] = slot
            self._write({"jsonrpc": "2.0", "id": ident, "method": method, "params": params or {}})
        if not slot["ev"].wait(self.timeout) or "msg" not in slot:
            raise OSError("upstream %s timed out" % method)
        with self._lock:
            self._waiters.pop(ident, None)
        msg = slot["msg"]
        if "error" in msg and "result" not in msg:
            raise OSError(msg["error"].get("message", "upstream error"))
        return msg.get("result")


class _Upstream:
    def __init__(self):
        self.proc, self.bridge, self.inflight, self.last = None, None, 0, time.monotonic()
        self.close_error = ""


class McpHost:
    """specs: {name: {command, args, env, stateful}}. shared: stateless names. native: in-process desk."""

    def __init__(self, specs, shared, secret, limits, span=None, native=None,
                 agents=AGENTS, stateful=STATEFUL):
        self.specs, self.shared, self.secret = dict(specs), frozenset(shared), secret
        self.limits = dict(limits)
        self._span = span or (lambda event: None)
        self.native = LiveDesk() if native is True else native
        self.agents, self.stateful = tuple(agents), frozenset(stateful)
        self._up, self._sessions, self._lock = {}, {}, threading.Lock()
        self._seq = 0
        port = int(self.limits["port"])
        self.httpd = QuietThreadingHTTPServer(("127.0.0.1", port), self._handler(self))
        self._stop = threading.Event()

    def key(self, name, agent, session):
        spec = self.specs[name]
        if name in self.stateful or spec.get("stateful"):
            return (name, agent, session)
        if name in self.shared:
            return (name,)
        return (name, agent)

    def _kill_tree(self, proc):
        """Stop the server process this host started. Agent application processes are not ours to stop."""
        if proc is None or proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(self.limits["stop_wait"])
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(self.limits["stop_wait"])

    def _stop_proc(self, up, key, why):
        proc, bridge = up.proc, up.bridge
        up.proc, up.bridge = None, None
        if bridge is not None and proc is not None and proc.stdin:
            try:
                proc.stdin.close()
            except OSError as closed:
                up.close_error = type(closed).__name__
        self._kill_tree(proc)
        if proc is not None:
            self._span({"event": "stop", "server": key[0], "agent": key[1] if len(key) > 1 else None,
                        "pid": proc.pid, "why": why, "t": time.time()})

    def _start(self, up, key, agent, extra):
        name = key[0]
        spec = self.specs[name]
        env = {**os.environ, **spec.get("env", {}), "PYTHONUNBUFFERED": "1", **extra}
        if name not in self.shared:
            env.update(spec.get("agent_env", {}).get(agent, {}))
        proc = subprocess.Popen([spec["command"], *spec.get("args", [])], env=env,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        up.proc = proc
        try:
            bridge = _Bridge(proc, self.limits["upstream_timeout"])
            bridge.request("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                          "clientInfo": {"name": "archhub-mcp-share", "version": "1"}})
            bridge.notify("notifications/initialized")
        except BaseException:
            self._stop_proc(up, key, "start_failed")
            raise OSError("mcp server %s did not start" % name)
        up.bridge = bridge
        self._span({"event": "start", "server": name, "agent": None if name in self.shared else agent,
                    "pid": proc.pid, "t": time.time()})

    def _acquire(self, name, agent, session, extra):
        key = self.key(name, agent, session)
        with self._lock:
            up = self._up.setdefault(key, _Upstream())
            up.inflight += 1
            alive = up.proc is not None and up.proc.poll() is None and up.bridge is not None
            if not alive:
                try:
                    self._start(up, key, agent, extra)
                except BaseException:
                    up.inflight -= 1
                    raise
        return up

    def reap(self, now=None):
        """Stop every upstream idle past the limit. Returns the keys stopped."""
        now = time.monotonic() if now is None else now
        stopped = []
        with self._lock:
            for key, up in self._up.items():
                if up.proc is not None and up.inflight == 0 and now - up.last > self.limits["idle_seconds"]:
                    self._stop_proc(up, key, "idle")
                    stopped.append(key)
        return stopped

    def end_session(self, session):
        """Stop stateful upstreams owned by this MCP session. Returns the keys stopped."""
        stopped = []
        with self._lock:
            self._sessions.pop(session, None)
            for key, up in self._up.items():
                if len(key) >= 3 and key[2] == session and up.proc is not None:
                    self._stop_proc(up, key, "session_end")
                    stopped.append(key)
        return stopped

    def running(self):
        with self._lock:
            return [k for k, u in self._up.items() if u.proc is not None and u.proc.poll() is None]

    @property
    def url(self):
        return "http://127.0.0.1:%d/mcp" % self.httpd.server_address[1]

    def start(self):
        threading.Thread(target=self.httpd.serve_forever, daemon=True, name="archhub-mcp-share").start()
        threading.Thread(target=self._reaper, daemon=True, name="archhub-mcp-reaper").start()
        return self

    def _reaper(self):
        while not self._stop.wait(self.limits["reap_every"]):
            self.reap()

    def close(self):
        self._stop.set()
        self.httpd.shutdown()
        self.httpd.server_close()
        with self._lock:
            for key, up in self._up.items():
                self._stop_proc(up, key, "close")

    def open_session(self, agent):
        with self._lock:
            self._seq += 1
            sid = "s%d-%s" % (self._seq, secrets.token_hex(8))
            self._sessions[sid] = {"agent": agent, "last": time.monotonic()}
        return sid

    def _dispatch(self, kind, name, agent, session, message):
        method = message.get("method", "")
        if method == "initialize":
            info = "archhub" if kind == "native" else name
            return {"protocolVersion": PROTOCOL, "capabilities": {"tools": {}},
                    "serverInfo": {"name": info, "version": "1"}}
        if method in ("ping", "notifications/initialized"):
            return {}
        if method == "tools/list":
            if kind == "native":
                return {"tools": self.native.tools()}
            up = self._acquire(name, agent, session, {"ARCHHUB_MCP_SESSION": session})
            try:
                return up.bridge.request("tools/list", message.get("params") or {})
            finally:
                self._release(up)
        if method == "tools/call":
            if kind == "native":
                params = message.get("params") or {}
                try:
                    value = self.native.call(params.get("name"), params.get("arguments") or {}, agent, session)
                except KeyError as exc:
                    return {"content": [{"type": "text", "text": "unknown tool %s" % exc}], "isError": True}
                if isinstance(value, dict) and "content" in value:
                    return value
                return {"content": [{"type": "text", "text": json.dumps(value)}], "isError": False}
            up = self._acquire(name, agent, session, {"ARCHHUB_MCP_SESSION": session})
            try:
                return up.bridge.request("tools/call", message.get("params") or {})
            finally:
                self._release(up)
        raise ValueError(method)

    def _release(self, up):
        with self._lock:
            up.inflight -= 1
            up.last = time.monotonic()

    @staticmethod
    def _handler(host):
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *_):
                return

            def _text(self, status, text, session=""):
                body = text.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                if session:
                    self.send_header("Mcp-Session-Id", session)
                self.end_headers()
                self.wfile.write(body)

            def _json(self, status, payload, session=""):
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                if session:
                    self.send_header("Mcp-Session-Id", session)
                self.end_headers()
                self.wfile.write(body)

            def _route(self):
                path = self.path.split("?", 1)[0].rstrip("/") or "/"
                if path == "/mcp":
                    return "native", None
                if path.startswith("/s/") and path.endswith("/mcp"):
                    name = path[len("/s/"):-len("/mcp")].strip("/")
                    if name in host.specs and "/" not in name:
                        return "upstream", name
                return None, None

            def _agent(self):
                scheme, _, given = self.headers.get("Authorization", "").partition(" ")
                if scheme != "Bearer" or not given:
                    return None
                return match_agent(host.secret, given, host.agents)

            def do_GET(self):
                self._text(405, "sse not offered")

            def do_DELETE(self):
                denied = local_browser_admission_error(self.headers, self.server.server_address[1])
                if denied:
                    self._text(403, denied)
                    return
                if self._agent() is None:
                    self._text(401, "token refused")
                    return
                session = self.headers.get("Mcp-Session-Id", "")
                host.end_session(session)
                self._text(200, "session ended", session)

            def do_POST(self):
                denied = local_browser_admission_error(self.headers, self.server.server_address[1])
                if denied:
                    self._text(403, denied)
                    return
                agent = self._agent()
                if agent is None:
                    self._text(401, "token refused")
                    return
                kind, name = self._route()
                if kind is None or (kind == "native" and host.native is None):
                    self._text(404, "unknown route")
                    return
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    length = -1
                if length < 0 or length > MAX_BODY or self.headers.get("Transfer-Encoding"):
                    self._text(413, "body refused")
                    return
                try:
                    message = json.loads(self.rfile.read(length) or b"{}")
                except ValueError:
                    self._text(400, "body refused")
                    return
                if not isinstance(message, dict) or not message.get("method"):
                    self._text(400, "body refused")
                    return
                method = message["method"]
                session = self.headers.get("Mcp-Session-Id", "")
                if method == "initialize":
                    session = host.open_session(agent)
                elif method.startswith("notifications/"):
                    self._text(202, "", session)
                    return
                else:
                    with host._lock:
                        held = host._sessions.get(session)
                        if held is None or held["agent"] != agent:
                            held = None
                        else:
                            held["last"] = time.monotonic()
                    if held is None:
                        self._text(404, "session refused")
                        return
                if kind == "upstream" and (name in host.stateful or host.specs[name].get("stateful")) and not session:
                    self._text(400, "session refused")
                    return
                try:
                    result = host._dispatch(kind, name, agent, session, message)
                except OSError as exc:
                    self._json(200, {"jsonrpc": "2.0", "id": message.get("id"),
                                     "error": {"code": -32000, "message": str(exc)}}, session)
                    return
                except ValueError:
                    self._json(200, {"jsonrpc": "2.0", "id": message.get("id"),
                                     "error": {"code": -32601, "message": "method not found"}}, session)
                    return
                if "id" not in message:
                    self._text(202, "", session)
                    return
                self._json(200, {"jsonrpc": "2.0", "id": message["id"], "result": result}, session)

        return Handler


def main(argv):
    """``main([config.json])`` blocks until killed.

    config.json: secret_file, spans, shared, stateful, native, app_root, agents,
    servers {name: {command, args, env, stateful}}, limits {port, idle_seconds, ...}.
    The connector is native. There is no proxy executable.
    """
    cfg = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    root = cfg.get("app_root")
    if root and root not in sys.path:
        sys.path.insert(0, root)
    spans = cfg.get("spans")

    def span(event):
        if spans:
            with open(spans, "a", encoding="utf-8") as out:
                out.write(json.dumps(event) + "\n")

    servers = {k: v for k, v in dict(cfg.get("servers", {})).items() if k != "connector"}
    native = LiveDesk() if cfg.get("native", True) else None
    McpHost(servers, cfg.get("shared", ()), load_secret(cfg["secret_file"]), cfg["limits"],
            span=span, native=native, agents=cfg.get("agents", AGENTS),
            stateful=cfg.get("stateful", STATEFUL)).start()
    threading.Event().wait()


__all__ = ["AGENTS", "McpHost", "STATEFUL", "agent_token", "load_secret", "main", "match_agent"]
