"""The process an agent starts for ArchHub's connector: it holds the agent's stdio and never dies with the connector.

Stdlib only, so an install that is half-way through replacing packages cannot break it. It starts the
real connector (the same command line, marked ARCHHUB_MCP_SUPERVISED) as its child and relays the
newline-delimited JSON-RPC both ways. When the child ends (an install, a crash, a broken import) the
agent's pipe stays open: calls in flight get an error, new calls get "restarting", and the child is
started again until it comes up; then the agent's own initialize is replayed and the agent is told the
tool list changed. Prior art: reloaderoo (MCP restart proxy that replays initialize) and the VS Code
extension host restarted behind a stable client connection.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

RESTARTING = "ArchHub connector is restarting (an install or update is in progress); call again in a moment"
BACKOFF = (0.5, 1, 2, 5, 10)  # seconds between starts while the child keeps failing


def _parse(line):
    """The JSON-RPC message, or None when the line is not one (it is relayed as it is; the peer answers it)."""
    try:
        message = json.loads(line)
    except ValueError as error:
        print("ArchHub MCP supervisor: relaying a line that is not JSON (%s)" % error, file=sys.stderr, flush=True)
        return None
    return message if isinstance(message, dict) else None


class Supervisor:
    def __init__(self, command, env, client_in, client_out):
        self.command, self.env = command, env
        self.client_in, self.client_out = client_in, client_out
        self.lock, self.write_lock = threading.Lock(), threading.Lock()
        self.child = None
        self.initialize = None      # the agent's initialize request (replayed into every new child)
        self.initialized = None     # the agent's notifications/initialized line
        self.answered = False       # the agent already has its initialize reply
        self.replay_id = None       # a replayed initialize whose reply the agent must not see twice
        self.pending = set()        # agent request ids the current child has not answered
        self.restarts = 0
        self.closed = False

    def to_client(self, message):
        data = message if isinstance(message, bytes) else json.dumps(message).encode("utf-8")
        with self.write_lock:
            self.client_out.write(data + b"\n")
            self.client_out.flush()

    @staticmethod
    def _send(child, line):
        child.stdin.write(line + b"\n")
        child.stdin.flush()

    def start_child(self):
        """Start the connector and replay the agent's handshake into it. False when it could not start."""
        try:
            child = subprocess.Popen(self.command, env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=None, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as error:
            print("ArchHub MCP supervisor: start failed: %s" % error, file=sys.stderr, flush=True)
            return False
        threading.Thread(target=self._pump, args=(child,), daemon=True, name="archhub-mcp-child").start()
        with self.lock:
            try:
                if self.initialize is not None:
                    message = _parse(self.initialize)
                    if self.answered:
                        self.restarts += 1
                        self.replay_id = message["id"] = "archhub-supervisor-replay-%d" % self.restarts
                    else:
                        self.pending.add(message["id"])
                    self._send(child, json.dumps(message).encode("utf-8"))
                    if self.initialized is not None:
                        self._send(child, self.initialized)
            except OSError:
                return True  # it ended during the handshake; its pump starts the next one
            self.child = child  # agent requests reach it only after the handshake
        return True

    def _pump(self, child):
        """Child stdout -> agent, until the child ends; then start it again while the agent is still there."""
        for raw in iter(child.stdout.readline, b""):
            line = raw.rstrip(b"\r\n")
            message = _parse(line)
            if message is not None and "method" not in message and "id" in message:
                if message["id"] == self.replay_id:
                    self.replay_id = None
                    self.to_client({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})
                    continue
                with self.lock:
                    self.pending.discard(message["id"])
                    if self.initialize is not None and message["id"] == _parse(self.initialize).get("id"):
                        self.answered = True
            self.to_client(line)
        child.wait()
        with self.lock:
            if self.child is not child and self.child is not None:
                return
            self.child = None
            first = None if self.answered or self.initialize is None else _parse(self.initialize).get("id")
            lost, self.pending = [i for i in self.pending if i != first], set()
            closed = self.closed
        for identity in lost:
            self.to_client({"jsonrpc": "2.0", "id": identity, "error": {"code": -32603, "message": RESTARTING}})
        if not closed:
            print("ArchHub MCP supervisor: connector exited (%s); starting it again" % child.returncode,
                  file=sys.stderr, flush=True)
            self._restart()

    def _restart(self):
        attempt = 0
        while not self.closed:
            time.sleep(BACKOFF[min(attempt, len(BACKOFF) - 1)])
            attempt += 1
            if self.closed or self.start_child():
                return

    def run(self):
        if not self.start_child():
            threading.Thread(target=self._restart, daemon=True, name="archhub-mcp-restart").start()
        for raw in iter(self.client_in.readline, b""):
            line = raw.rstrip(b"\r\n")
            if not line:
                continue
            message = _parse(line)
            method = message.get("method") if message else None
            request = bool(method) and "id" in message
            with self.lock:
                if method == "initialize":
                    self.initialize, self.answered = line, False
                elif method == "notifications/initialized":
                    self.initialized = line
                child = self.child
                if child is not None:
                    if request:
                        self.pending.add(message["id"])
                    try:
                        self._send(child, line)
                        continue
                    except OSError:  # the child just ended; its pump starts it again
                        if request:
                            self.pending.discard(message["id"])
            # No connector right now: the handshake is replayed when it comes up; other requests are answered.
            if request and method != "initialize":
                self.to_client({"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32603, "message": RESTARTING}})
        with self.lock:
            self.closed = True
            child = self.child
        if child is not None:
            try:
                child.stdin.close()
                child.wait(5)
            except (OSError, subprocess.TimeoutExpired):
                child.kill()
        return 0


def supervise(command=None):
    """Run the connector under supervision; returns when the agent closes its pipe."""
    env = dict(os.environ, ARCHHUB_MCP_SUPERVISED="1")
    return Supervisor(command or [sys.executable, *sys.orig_argv[1:]], env, sys.stdin.buffer, sys.stdout.buffer).run()
