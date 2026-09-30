"""One stable stdio MCP connection while the native owner's code updates (founder order 2026-09-30).

An agent's native MCP process used to run the code it started with until someone
reconnected it by hand; after an install, most ran day-old code. The client now
launches this small host instead. It runs the native owner (native_agent_mcp) as
a worker and relays newline-delimited JSON-RPC both ways, unchanged.

Between calls it reads the installed BUILD_ID. When a new build is installed and
nothing is in flight or uncertain, it hands the SAME actor to a worker running the
new code: the old worker releases its capability (or the capability already ended
with the old application), the new worker continues that exact actor
(--expected-actor, a conditional continuation, never a new enrollment), the
client's own initialize is replayed to it privately, and the client is told the
tool list changed. Same process, same pipes: the client never reconnects.

Nothing is replayed. A call in flight, an owner that is not plainly bound, an
unresolved attempt or permit, or another application instance defers the swap;
native.owner_status then carries self_update with the reason, and it is retried.

Stdlib only by design: this process outlives every update, so it imports no
nodelang module that an install could change underneath it.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

WORKER_LOADER = ("import runpy,sys;sys.path.insert(0,sys.argv.pop(1));"
                 "runpy.run_module('nodelang.native_agent_mcp',run_name='__main__')")
HANDOFF_TOOL = "native.handoff_release"
STATUS_TOOL = "native.owner_status"
EFFECTS_TOOL = "native.owner_inspect_effects"
LAUNCHER_ENV = "ARCHHUB_NATIVE_MCP_LAUNCHER"
_PRIVATE = "archhub-launcher:"
_BUILD = re.compile(r"[A-Za-z0-9._-]{1,256}\Z")


def installed_build(root):
    """The installed BUILD_ID, the same reading quiet_update.installed_build_id makes; '' when absent."""
    try:
        with (Path(root) / "BUILD_ID").open(encoding="utf-8") as stream:
            value = stream.read(258).strip()
    except (OSError, UnicodeError):
        return ""
    return value if _BUILD.fullmatch(value) else ""


def _tool_json(response):
    """A tool result's JSON document: structured content, else its first text part."""
    result = response.get("result") if type(response) is dict else None
    if type(result) is not dict or result.get("isError"):
        return None
    structured = result.get("structuredContent")
    if type(structured) is dict:
        return structured.get("result", structured) if set(structured) == {"result"} else structured
    for part in result.get("content") or ():
        if type(part) is dict and part.get("type") == "text":
            try:
                value = json.loads(part.get("text") or "")
            except ValueError:
                return None
            return value if type(value) is dict else None
    return None


def defer_reason(status, effects=None):
    """Why this owner cannot be handed to new code now; None when it can."""
    owner = status.get("owner", status) if type(status) is dict else None
    if type(owner) is not dict or not owner.get("agent_session"):
        return "the owner holds no actor yet"
    if owner.get("state") != "bound":
        return "the owner is %s" % owner.get("state")
    if owner.get("rebind_pending") or owner.get("failed_attempt"):
        return "an owner attempt is unresolved; run native.owner_recover"
    pinned, current = owner.get("pinned") or {}, owner.get("current") or {}
    if not current or owner.get("current_error"):
        return "the application is not running"
    if pinned.get("instance_digest") != current.get("instance_digest"):
        return "the application instance changed"
    if effects is not None:
        page = effects.get("effects") if type(effects) is dict else None
        if type(page) is not dict or page.get("pending_permits") or page.get("truncated"):
            return "a file-write permit is unresolved; run native.owner_inspect_effects"
    return None


class Launcher:
    """The stable host: one client connection, one worker at a time."""

    def __init__(self, root, *, client_in, client_out, worker_argv=None, check_seconds=5.0,
                 source_seconds=30.0, extra_args=(), environment=None):
        self.root = Path(root)
        self._client_in, self._client_out = client_in, client_out
        self._argv = worker_argv or (lambda extra: [sys.executable, "-I", "-B", "-c", WORKER_LOADER,
                                                    str(self.root), *extra])
        self._check_seconds, self._source_seconds = check_seconds, source_seconds
        self._extra = [a for a in extra_args]
        self._environment = dict(os.environ if environment is None else environment)
        self._lock = threading.RLock()
        self._write = threading.Lock()
        self._inflight = {}          # client request id -> (method, tool name)
        self._private = {}           # private id -> [event, response]
        self._initialize = None      # the client's own initialize request
        self._initialized = None     # and its initialized notification
        self._held = []              # client messages that arrive during a swap
        self._swapping = False
        self._counter = 0
        self._closed = threading.Event()
        self.status = {"state": "current", "reason": None, "build": installed_build(self.root),
                       "swaps": 0}
        self._worker = None
        self._start_worker(self._extra)

    # -- worker ----------------------------------------------------------------
    def _start_worker(self, extra):
        env = dict(self._environment, **{LAUNCHER_ENV: "1"})
        worker = subprocess.Popen(self._argv(list(extra)), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self._worker = worker
        threading.Thread(target=self._pump_worker, args=(worker,), name="mcp-worker-out", daemon=True).start()
        return worker

    def _pump_worker(self, worker):
        for raw in iter(worker.stdout.readline, b""):
            try:
                message = json.loads(raw)
            except ValueError:
                continue
            ident = message.get("id") if type(message) is dict else None
            if type(ident) is str and ident.startswith(_PRIVATE):
                with self._lock:
                    waiter = self._private.get(ident)
                if waiter is not None:
                    waiter[1] = message
                    waiter[0].set()
                continue
            if worker is not self._worker:
                continue  # a retired worker no longer speaks to the client
            if ident is not None and "method" not in message:
                with self._lock:
                    method, tool = self._inflight.pop(ident, (None, None))
                message = self._shape_response(message, method, tool)
            self._send_client(message)

    def _shape_response(self, message, method, tool):
        result = message.get("result")
        if method == "tools/list" and type(result) is dict and type(result.get("tools")) is list:
            # The handoff is the launcher's own: never listed to the agent.
            result["tools"] = [t for t in result["tools"] if not (type(t) is dict and t.get("name") == HANDOFF_TOOL)]
        if method == "tools/call" and tool == STATUS_TOOL and type(result) is dict:
            status = dict(self.status)
            for part in result.get("content") or ():
                if type(part) is dict and part.get("type") == "text":
                    try:
                        value = json.loads(part.get("text") or "")
                    except ValueError:
                        break
                    if type(value) is dict:
                        part["text"] = json.dumps({**value, "self_update": status})
                    break
            if type(result.get("structuredContent")) is dict:
                result["structuredContent"] = {**result["structuredContent"], "self_update": status}
        return message

    def _to_worker(self, message):
        worker = self._worker
        worker.stdin.write(json.dumps(message).encode("utf-8") + b"\n")
        worker.stdin.flush()

    def _call(self, method, params, timeout=60.0):
        with self._lock:
            self._counter += 1
            ident = _PRIVATE + str(self._counter)
            waiter = self._private[ident] = [threading.Event(), None]
        try:
            self._to_worker({"jsonrpc": "2.0", "id": ident, "method": method, "params": params})
            if not waiter[0].wait(timeout):
                raise TimeoutError("the native owner did not answer %s" % method)
            return waiter[1]
        finally:
            with self._lock:
                self._private.pop(ident, None)

    def _tool(self, name, arguments=None, timeout=60.0):
        return _tool_json(self._call("tools/call", {"name": name, "arguments": arguments or {}}, timeout))

    # -- client ----------------------------------------------------------------
    def _send_client(self, message):
        with self._write:
            self._client_out.write(json.dumps(message).encode("utf-8") + b"\n")
            self._client_out.flush()

    def serve(self):
        """Relay until the client closes its side; then the worker ends with it."""
        checker = threading.Thread(target=self._check_loop, name="mcp-self-update", daemon=True)
        checker.start()
        try:
            for raw in iter(self._client_in.readline, b""):
                try:
                    message = json.loads(raw)
                except ValueError:
                    continue
                self._from_client(message)
        finally:
            self._closed.set()
            worker = self._worker
            try:
                worker.stdin.close()
            except OSError:
                pass
            try:
                worker.wait(timeout=15)
            except subprocess.TimeoutExpired:
                worker.kill()

    def _from_client(self, message):
        if type(message) is not dict:
            return
        method, ident = message.get("method"), message.get("id")
        if method == "initialize":
            self._initialize = message
        elif method == "notifications/initialized":
            self._initialized = message
        if method == "tools/call" and (message.get("params") or {}).get("name") == HANDOFF_TOOL:
            self._send_client({"jsonrpc": "2.0", "id": ident,
                               "error": {"code": -32601, "message": "Unknown tool"}})
            return
        with self._lock:
            if method is not None and ident is not None:
                tool = (message.get("params") or {}).get("name") if method == "tools/call" else None
                self._inflight[ident] = (method, tool)
            if self._swapping:
                self._held.append(message)
                return
        self._to_worker(message)

    # -- self-update ------------------------------------------------------------
    def _changed_source(self):
        """A source-tree run has no BUILD_ID: the worker's own disk snapshot says what changed."""
        status = self._tool(STATUS_TOOL, timeout=30.0)
        owner = (status or {}).get("owner", status) if type(status) is dict else None
        process = owner.get("process") if type(owner) is dict else None
        if type(process) is dict and process.get("disk_changed_since_import") is True:
            return "source:" + str(process.get("disk_digest_now") or "")[:16]
        return None

    def _check_loop(self):
        last_source_check = 0.0
        while not self._closed.wait(self._check_seconds):
            if self._initialized is None:
                continue
            try:
                marker = None
                build = installed_build(self.root)
                if build:
                    marker = build if build != self.status["build"] else None
                elif time.monotonic() - last_source_check >= self._source_seconds and not self._inflight:
                    last_source_check = time.monotonic()
                    marker = self._changed_source()
                if marker:
                    self.try_swap(marker)
            except Exception as exc:  # the old worker keeps serving; say why
                self.status = {**self.status, "state": "deferred", "reason": "update failed: %s" % exc}

    def try_swap(self, build):
        """Hand the same actor to new code, or defer and say why. Never replays a call."""
        with self._lock:
            if self._inflight:
                if self.status["state"] != "deferred":  # a more specific reason stays
                    self.status = {**self.status, "state": "deferred", "reason": "a call is in flight",
                                   "pending_build": build}
                return False
            self._swapping = True
        try:
            status = self._tool(STATUS_TOOL)
            owner = (status or {}).get("owner", status) if type(status) is dict else None
            effects = None
            if type(owner) is dict and (owner.get("current") or {}).get("fingerprint"):
                effects = self._tool(EFFECTS_TOOL, {"expected_owner": owner["current"]["fingerprint"]})
            reason = defer_reason(status, effects)
            if reason is not None:
                self.status = {**self.status, "state": "deferred", "reason": reason, "pending_build": build}
                return False
            actor = owner["agent_session"]
            if owner["pinned"].get("runtime_id") == owner["current"].get("runtime_id"):
                # Same application: release this worker's capability before new code continues.
                released = self._tool(HANDOFF_TOOL)
                if type(released) is not dict or released.get("released") is not True or released.get("agent_session") != actor:
                    self.status = {**self.status, "state": "deferred", "reason": "the capability release was not confirmed",
                                   "pending_build": build}
                    return False
            old = self._worker
            extra = [a for a in self._extra if a != "--expected-actor"]
            if "--expected-actor" in self._extra:
                index = self._extra.index("--expected-actor")
                extra = self._extra[:index] + self._extra[index + 2:]
            self._extra = [*extra, "--expected-actor", actor]
            self._start_worker(self._extra)
            try:
                old.stdin.close()
                old.wait(timeout=15)
            except (OSError, subprocess.TimeoutExpired):
                old.kill()
            replay = dict(self._initialize)
            answered = self._call("initialize", replay.get("params") or {})
            if type(answered) is not dict or "result" not in answered:
                raise RuntimeError("the new worker refused initialize")
            self._to_worker(self._initialized)
            after = self._tool(STATUS_TOOL)
            if type(after) is dict and after.get("tools_available") is False:
                # An entry that serves its recovery tools first: activate it, as the
                # agent's own native.resume_recover would, for the same actor.
                self._tool("native.resume_recover")
                after = self._tool(STATUS_TOOL)
            now = (after or {}).get("owner", after) if type(after) is dict else None
            if type(now) is not dict or now.get("agent_session") != actor or now.get("state") != "bound":
                self.status = {**self.status, "state": "failed", "reason": "the new code did not continue the same actor",
                               "build": build}
                return False
            self.status = {"state": "current", "reason": None, "build": build, "swaps": self.status["swaps"] + 1}
            self._send_client({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})
            return True
        finally:
            with self._lock:
                self._swapping = False
                held, self._held = self._held, []
            for message in held:
                self._to_worker(message)


def run_entry(worker_module, worker_main):
    """A native entry's process start: its worker when the launcher runs it, else the launcher."""
    if os.environ.get(LAUNCHER_ENV) == "1":
        return worker_main()
    return launch(worker_module)


def launch(worker_module):
    """Make this process the stable host and run worker_module as its worker.

    Called by the native entry points (native_agent_mcp, clean_coordination_mcp)
    when they are not already a launcher's worker, so every registered launch line
    adopts the launcher with no configuration change. The worker is the same
    module on the same interpreter with the same flags and arguments.
    """
    root = Path(__file__).resolve().parents[1]
    flags = (["-I"] if sys.flags.isolated else []) + (["-B"] if sys.flags.dont_write_bytecode else [])
    loader = ("import runpy,sys;sys.path.insert(0,sys.argv.pop(1));"
              "runpy.run_module(%r,run_name='__main__')" % worker_module)
    Launcher(root, client_in=sys.stdin.buffer, client_out=sys.stdout.buffer,
             worker_argv=lambda extra: [sys.executable, *flags, "-c", loader, str(root), *extra],
             extra_args=sys.argv[1:]).serve()
