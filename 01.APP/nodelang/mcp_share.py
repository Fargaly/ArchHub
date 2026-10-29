"""One local MCP host for every agent on the machine: lazy start, idle reaping, one copy where safe.

This file is stdlib-only on purpose. The installer copies it (with http_server.py) to
%LOCALAPPDATA%\\ArchHub-Runtime, outside the folder installs replace, and the host runs from
there, so an app install or restart never closes an agent's connection.

An agent reaches a server at http://127.0.0.1:<port>/<server>/<agent>/mcp instead of launching it.
The first call starts the server behind sparfenyuk/mcp-proxy (MIT, built from source, 127.0.0.1);
an upstream with no call in flight for ``idle_seconds`` is stopped, and the next call starts it
again. Copies: a server named in ``shared`` is stateless and runs once for everyone; a spec with
``session_env`` is per session (the agent's launcher sends ``X-ArchHub-Session: VAR=value`` and
the host starts that copy with VAR=value, because a URL carries none of the spawn-time
environment the server reads its identity from); anything else gets one copy per agent. mcp-proxy
has no auth, so this front door is the check: Host/Origin by the one loopback law (403), then a
per-agent bearer token (401). The token and session header never reach the server. Every start
and stop is one span.

Streamable HTTP (/mcp) only; the legacy SSE transport carries absolute paths a prefix breaks.
"""
from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import os
import re
import secrets
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from .http_server import QuietThreadingHTTPServer, local_browser_admission_error

MAX_BODY = 8 * 1024 * 1024
SESSION_HEADER = "X-ArchHub-Session"
_SESSION_VALUE = re.compile(r"[A-Za-z0-9._-]{1,128}")
_DROP = frozenset({"connection", "keep-alive", "te", "trailer", "transfer-encoding", "upgrade",
                   "host", "content-length", "authorization", "origin", SESSION_HEADER.lower()})


def agent_token(secret: str, agent: str) -> str:
    """The one bearer token an agent presents; bound to its name, so it cannot reach another's copy."""
    return hmac.new(secret.encode("utf-8"), ("mcp-share|" + agent).encode("utf-8"),
                    hashlib.sha256).hexdigest()


def load_secret(path) -> str:
    """The host's secret: created once, then read back. Same file for the host and the installer."""
    path = Path(path)
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_urlsafe(32), encoding="ascii")
    return path.read_text(encoding="ascii").strip()


class _Upstream:
    def __init__(self):
        self.proc, self.port, self.inflight, self.last = None, None, 0, time.monotonic()


class McpHost:
    """specs: {name: {"command", "args", "env", "session_env", "agent_env"}}; shared: stateless names."""

    def __init__(self, specs, shared, secret, proxy_exe, limits, span=None):
        self.specs, self.shared, self.secret = dict(specs), frozenset(shared), secret
        self.proxy_exe = [proxy_exe] if isinstance(proxy_exe, str) else list(proxy_exe)
        self.limits = dict(limits)  # port, idle_seconds, start_timeout, upstream_timeout, reap_every, poll, stop_wait
        self._span = span or (lambda event: None)
        self._up, self._lock = {}, threading.Lock()
        self.httpd = QuietThreadingHTTPServer(("127.0.0.1", self.limits["port"]), self._handler(self))
        self._stop = threading.Event()

    # ---- lifecycle -------------------------------------------------------
    def key(self, name, agent, session=""):
        if name in self.shared:
            return (name,)
        return (name, agent, session) if self.specs[name].get("session_env") else (name, agent)

    def proxy_argv(self, name, port):
        spec = self.specs[name]
        # unverified on native Windows: flags are mcp-proxy's documented streamable-HTTP ones
        argv = [*self.proxy_exe, "--host", "127.0.0.1", "--port", str(port), "--pass-environment"]
        if name in self.shared:
            argv.append("--stateless")
        return argv + ["--", spec["command"], *spec.get("args", [])]

    def _acquire(self, name, agent, session="", extra_env=None):
        key = self.key(name, agent, session)
        with self._lock:
            up = self._up.setdefault(key, _Upstream())
            up.inflight += 1
            if up.proc is None or up.proc.poll() is not None:
                try:
                    self._start(up, key, agent, extra_env or {})
                except BaseException:
                    up.inflight -= 1
                    raise
        return up

    def _start(self, up, key, agent, extra_env):
        name = key[0]
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            up.port = probe.getsockname()[1]
        spec = self.specs[name]
        env = {**os.environ, **spec.get("env", {}), **spec.get("agent_env", {}).get(agent, {}), **extra_env}
        up.proc = subprocess.Popen(self.proxy_argv(name, up.port), env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        deadline = time.monotonic() + self.limits["start_timeout"]
        while time.monotonic() < deadline:
            if up.proc.poll() is not None:
                break
            try:
                socket.create_connection(("127.0.0.1", up.port), self.limits["poll"]).close()
                self._span({"event": "start", "server": name, "agent": None if name in self.shared else agent,
                            "pid": up.proc.pid, "port": up.port, "t": time.time()})
                return
            except OSError:
                time.sleep(self.limits["poll"])
        self._stop_proc(up, key, "start_failed")
        raise OSError("mcp server %s did not start" % name)

    def _stop_proc(self, up, key, why):
        proc, up.proc = up.proc, None
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(self.limits["stop_wait"])
            except subprocess.TimeoutExpired:
                proc.kill()
        if proc is not None:
            self._span({"event": "stop", "server": key[0], "agent": key[1] if len(key) > 1 else None,
                        "pid": proc.pid, "why": why, "t": time.time()})

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

    def running(self):
        with self._lock:
            return [k for k, u in self._up.items() if u.proc is not None and u.proc.poll() is None]

    @property
    def url(self):
        return "http://127.0.0.1:%d" % self.httpd.server_address[1]

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

    # ---- front door ------------------------------------------------------
    @staticmethod
    def _handler(host):
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"  # body ends at close, so SSE replies stream unbuffered

            def log_message(self, *_):
                return

            def _text(self, status, text):
                body = text.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _forward(self):
                denied = local_browser_admission_error(self.headers, self.server.server_address[1])
                if denied:
                    self._text(403, denied)
                    return
                parts = self.path.split("?", 1)[0].strip("/").split("/")
                if len(parts) != 3 or parts[2] != "mcp" or parts[0] not in host.specs:
                    self._text(404, "unknown route")
                    return
                name, agent = parts[0], parts[1]
                scheme, _, given = self.headers.get("Authorization", "").partition(" ")
                if scheme != "Bearer" or not hmac.compare_digest(
                        given.encode("utf-8"), agent_token(host.secret, agent).encode("utf-8")):
                    self._text(401, "token refused")
                    return
                session, extra = "", {}
                if host.specs[name].get("session_env"):
                    session = self.headers.get(SESSION_HEADER, "")
                    var, _, value = session.partition("=")
                    if var not in host.specs[name]["session_env"] or not _SESSION_VALUE.fullmatch(value):
                        self._text(400, "session refused")
                        return
                    extra = {var: value}
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    length = -1
                if length < 0 or length > MAX_BODY or self.headers.get("Transfer-Encoding"):
                    self._text(413, "body refused")
                    return
                body = self.rfile.read(length) if length else b""
                try:
                    up = host._acquire(name, agent, session, extra)
                except OSError as exc:
                    self._text(502, str(exc))
                    return
                try:
                    conn = http.client.HTTPConnection("127.0.0.1", up.port, timeout=host.limits["upstream_timeout"])
                    headers = {k: v for k, v in self.headers.items() if k.lower() not in _DROP}
                    conn.request(self.command, "/mcp", body, {**headers, "Host": "127.0.0.1:%d" % up.port,
                                                              "Content-Length": str(len(body))})
                    reply = conn.getresponse()
                    self.send_response(reply.status)
                    for k, v in reply.getheaders():
                        if k.lower() not in _DROP:
                            self.send_header(k, v)
                    self.end_headers()
                    while chunk := reply.read1(65536):
                        self.wfile.write(chunk)
                        self.wfile.flush()
                except (OSError, http.client.HTTPException) as exc:
                    host._span({"event": "stream_error", "server": name, "agent": agent,
                                "error": type(exc).__name__, "t": time.time()})
                finally:
                    with host._lock:
                        up.inflight -= 1
                        up.last = time.monotonic()

            do_GET = do_POST = do_DELETE = _forward

        return Handler


def main(argv):
    """The runtime process: ``main([config.json])``; blocks until killed.

    config.json (written by the installer, in the runtime folder):
      {"proxy": [<runtime python>, "-m", "mcp_proxy"], "secret_file": "...", "spans": "<jsonl>",
       "shared": ["name"], "servers": {"name": {"command", "args", "env", "session_env", "agent_env"}},
       "limits": {"port", "idle_seconds", "start_timeout", "upstream_timeout", "reap_every", "poll", "stop_wait"}}
    """
    cfg = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    spans = cfg.get("spans")

    def span(event):
        if spans:
            with open(spans, "a", encoding="utf-8") as out:
                out.write(json.dumps(event) + "\n")

    McpHost(cfg["servers"], cfg.get("shared", ()), load_secret(cfg["secret_file"]), cfg["proxy"],
            cfg["limits"], span=span).start()
    threading.Event().wait()


__all__ = ["McpHost", "SESSION_HEADER", "agent_token", "load_secret", "main"]
