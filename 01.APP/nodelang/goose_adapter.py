"""The BABOOM/Goose boundary. ACP is transport; Goose owns the agent loop.

Wire contract: Goose v1.54.0 ACP v1, including its enabledExtensions and
recipeDeeplink metadata. No local model/tool fallback or execution permission.
"""
from __future__ import annotations

import base64
import json
import queue
import re
import subprocess
import sys
from pathlib import Path
from uuid import uuid4
import threading
import time

from .model_router import ModelRouteRefused


class GooseRefused(ModelRouteRefused):
    pass


class GooseResponseRefused(GooseRefused):
    """A complete remote refusal: the connection remains synchronised."""


def safe_workshop_call(identity, arguments):
    if (type(identity) is not dict or identity.get("extensionName") != "archhub-agent"
            or type(arguments) is not dict):
        return False
    tool = identity.get("toolName")
    # The same fields the Workshop mailbox itself admits (workshop_mailbox.call); nothing wider.
    fields = {"archhub-agent__declare":({"task", "paths", "status", "request_id"}, {"display_name", "model"}),
              "archhub-agent__send":({"to", "text"}, {"reply_to", "idempotency_key"}),
              "archhub-agent__read":(set(), {"since", "declarations_after", "include_archived"})}
    if tool not in fields:
        return False
    required, optional = fields[tool]
    if not required <= set(arguments) or set(arguments) - required - optional:
        return False
    # This grant covers only the existing mailbox boundary, which validates
    # identity, audience and byte budgets again. It never grants a host effect.
    return len(json.dumps(arguments, ensure_ascii=True).encode()) <= 200000


def workshop_mcp_server():
    from .client_mcp_installation import LOADER
    return {"name":"archhub-agent", "command":sys.executable,
        "args":["-c", LOADER, str(Path(__file__).resolve().parents[1])],
        "env":[{"name":"PYTHONUTF8", "value":"1"},
               {"name":"GOOSE_SESSION_ID", "value":"connector-"+uuid4().hex}]}


def free_route(route: str) -> tuple[str, str]:
    if route == "openrouter/free":
        return "openrouter", "openrouter/free"
    if isinstance(route, str) and route.startswith("openrouter/"):
        model = route[len("openrouter/"):]
        if re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._:-]+:free", model):
            return "openrouter", model
    if isinstance(route, str) and route.startswith("ollama/"):
        model = route[len("ollama/"):]
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,180}", model):
            return "ollama", model
    raise GooseRefused("BABOOM needs an OpenRouter free route or a local Ollama model.")


class AcpTransport:
    """One bounded JSON-RPC connection to an owned stdio process."""

    def __init__(self, process):
        self.process = process
        self.inbox = queue.Queue(maxsize=256)
        self.outbox = queue.Queue(maxsize=16)
        self.sequence = 0
        self.closed = False
        self.reader = threading.Thread(target=self._read, name="archhub-goose-acp", daemon=True)
        self.reader.start()
        self.writer = threading.Thread(target=self._write, name="archhub-goose-input", daemon=True)
        self.writer.start()

    def _write(self):
        try:
            while not self.closed:
                value = self.outbox.get()
                if value is None:
                    break
                self.process.stdin.write(value)
                self.process.stdin.flush()
        except (OSError, ValueError):
            try:
                self.inbox.put_nowait(None)
            except queue.Full:
                pass

    def _read(self):
        try:
            while not self.closed:
                line = self.process.stdout.readline(1_048_577)
                if not line or len(line) > 1_048_576:
                    break
                value = json.loads(line)
                self.inbox.put_nowait(value)
        except (OSError, ValueError, queue.Full):
            pass
        finally:
            try:
                self.inbox.put_nowait(None)
            except queue.Full:
                pass

    def send(self, value):
        if self.closed:
            raise GooseRefused("The managed Goose connection is closed.")
        try:
            self.outbox.put_nowait((json.dumps({"jsonrpc": "2.0", **value}) + "\n").encode())
        except queue.Full:
            raise GooseRefused("The managed Goose connection closed; the request was not replayed.") from None

    def request(self, method, params, *, deadline, update=lambda _: None, stopped=lambda: False,
                response_error=lambda _: None):
        self.sequence += 1
        request_id = self.sequence
        tool_identities = {}
        self.send({"id": request_id, "method": method, "params": params})
        while not self.closed:
            if stopped():
                raise GooseRefused("Stopped by you")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise GooseRefused("Goose did not answer in time; the request was not replayed.")
            try:
                message = self.inbox.get(timeout=min(remaining, 0.1))
            except queue.Empty:
                continue
            if not isinstance(message, dict):
                raise GooseRefused("The managed Goose connection closed; the request was not replayed.")
            if message.get("method"):
                if "id" in message:
                    if message["method"] == "session/request_permission":
                        permission = message.get("params") or {}
                        call = permission.get("toolCall") or {}
                        identity = tool_identities.get((permission.get("sessionId"), call.get("toolCallId")))
                        safe = permission.get("sessionId") == params.get("sessionId") and (
                            identity == {"extensionName": "archhub-hosts", "toolName": "archhub-hosts__hosts_state"}
                            and call.get("rawInput") == {} or safe_workshop_call(identity, call.get("rawInput")))
                        option = next((row.get("optionId") for row in permission.get("options", ())
                                       if row.get("kind") == "allow_once"), None) if safe else None
                        outcome = {"outcome": "selected", "optionId": option} if option else {"outcome": "cancelled"}
                        self.send({"id": message["id"], "result": {"outcome": outcome}})
                    else:
                        self.send({"id": message["id"], "error": {"code": -32601, "message": "Capability not admitted"}})
                elif message["method"] == "session/update":
                    notification = message.get("params") or {}
                    item = notification.get("update") or {}
                    if item.get("sessionUpdate") == "tool_call":
                        meta = (item.get("_meta") or {}).get("goose") or {}
                        identity = meta.get("toolCall")
                        if isinstance(identity, dict):
                            tool_identities[(notification.get("sessionId"), item.get("toolCallId"))] = {
                                k: identity.get(k) for k in ("extensionName", "toolName")}
                    update(notification)
                continue
            if message.get("id") != request_id:
                raise GooseRefused("Goose returned an unexpected response identity.")
            if "error" in message:
                response_error(message["error"])
                # Provider diagnostics may contain credentials. Only the typed
                # failure crosses into the face, never the provider's raw text.
                raise GooseResponseRefused("Goose could not complete this request. No action was approved.")
            result = message.get("result")
            if not isinstance(result, dict):
                raise GooseRefused("Goose returned an invalid response.")
            return result
        raise GooseRefused("The managed Goose connection is closed.")

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
        self.reader.join(timeout=2)
        try:
            self.outbox.put_nowait(None)
        except queue.Full:
            pass
        self.writer.join(timeout=2)
        self.process.stdin.close()
        self.process.stdout.close()


class GooseAdapter:
    def __init__(self, runtime):
        self.runtime = runtime
        self.lock = threading.Lock()

    def ask(self, prompt, context_block, model, *, before_dispatch=None, generation=None,
            is_halted=None, halt_generation=None, turn_seconds=20.0, **_unused):
        provider, selected = free_route(model)
        if self.runtime is None:
            raise GooseRefused("The packaged Goose brain is not available. Open ArchHub from its launcher.")
        if generation:
            raise GooseRefused("This Goose proof supports default generation settings only.")
        if not self.lock.acquire(blocking=False):
            raise GooseRefused("BABOOM is answering another request. Wait for its answer.")
        transport = self.runtime.transport
        deadline = time.monotonic() + float(turn_seconds)
        original_generation = halt_generation() if halt_generation else None
        def stopped():
            return bool((is_halted and is_halted()) or
                        (halt_generation and halt_generation() != original_generation))
        try:
            if before_dispatch:
                before_dispatch()
            if stopped():
                raise GooseRefused("Stopped by you")
            from .agent_composer import _SYSTEM
            settings = {"goose_provider": provider, "goose_model": selected}
            recipe = {"version": "1.0.0", "title": "BABOOM", "description": "ArchHub agent",
                      "instructions": _SYSTEM, "settings": settings}
            encoded = base64.urlsafe_b64encode(json.dumps(recipe).encode()).decode().rstrip("=")
            # Goose owns this MCP client; messages go to the existing Workshop.
            session = transport.request("session/new", {
                "cwd": str(self.runtime.work_dir), "mcpServers": [workshop_mcp_server()],
                "_meta": {"recipeDeeplink": encoded, "enabledExtensions": [{
                    "type": "mcp", "server": self.runtime.host_extension,
                    "available_tools": ["hosts_state"],
                }]},
            }, deadline=deadline, stopped=stopped)
            session_id = session.get("sessionId")
            if not isinstance(session_id, str) or not session_id:
                raise GooseRefused("Goose did not create a session.")
            chunks, steps = [], {}
            def update(params):
                if params.get("sessionId") != session_id:
                    return
                item = params.get("update") or {}
                kind = item.get("sessionUpdate")
                if kind == "agent_message_chunk":
                    content = item.get("content") or {}
                    if content.get("type") == "text":
                        chunks.append(str(content.get("text") or ""))
                        if sum(map(len, chunks)) > 64_000:
                            raise GooseRefused("Goose's answer exceeded its display limit.")
                elif kind in {"tool_call", "tool_call_update"}:
                    key = item.get("toolCallId")
                    identity = ((item.get("_meta") or {}).get("goose") or {}).get("toolCall") or {}
                    name = "hosts_state" if identity.get("toolName") == "archhub-hosts__hosts_state" else item.get("title") or "Host read"
                    row = steps.setdefault(key, {"tool": name})
                    row["status"] = {"completed": "ok", "failed": "failed"}.get(item.get("status"), "running")
                    if "content" in item:
                        row["result"] = item["content"]
                    from .native_agentic_loop import publish_step
                    publish_step({"tool": str(row["tool"])[:4000],
                                  "status": str(row["status"]), "summary": ""})
            final = transport.request("session/prompt", {"sessionId": session_id, "prompt": [
                {"type": "text", "text": context_block + "\n\nUser: " + prompt},
            ]}, deadline=deadline, update=update, stopped=stopped)
            if stopped():
                raise GooseRefused("Stopped by you")
            if final.get("stopReason") != "end_turn":
                raise GooseResponseRefused("Goose stopped before completing its answer. No action was approved.")
            text = "".join(chunks).strip()
            if not text:
                raise GooseRefused("Goose returned no answer.")
            return {"text": text, "steps": list(steps.values()),
                    "via": {"family": provider, "provider": "Goose", "model": selected}}
        except GooseResponseRefused:
            raise
        except BaseException:
            # A timed-out/stopped stream cannot deliver its late response into
            # another ask. Close, do not replay or spawn a replacement here.
            self.runtime.close()
            raise
        finally:
            self.lock.release()
