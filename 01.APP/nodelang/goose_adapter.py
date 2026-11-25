"""The BABOOM/Goose boundary. ACP is transport; Goose owns the agent loop.

Wire contract: Goose v1.54.0 ACP v1, including its enabledExtensions and
recipeDeeplink metadata. No local model/tool fallback or execution permission.
"""
from __future__ import annotations

import base64
import json
import re
import sys
from pathlib import Path
from uuid import uuid4
import threading
import time

# Goose is one row of the one ACP client; its transport and refusals live there.
from .acp_client import AcpRefused as GooseRefused, AcpResponseRefused as GooseResponseRefused


def safe_workshop_call(identity, arguments):
    if (type(identity) is not dict or identity.get("extensionName") != "archhub-agent"
            or type(arguments) is not dict):
        return False
    tool = identity.get("toolName")
    # The same fields the Workshop mailbox itself admits (workshop_mailbox.call); nothing wider.
    fields = {"archhub-agent__declare":({"task", "paths", "status", "request_id"}, {"display_name", "model", "role", "title"}),
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


# What Goose is offered on the ArchHub connector: the Workshop and the canvas, nothing else.
WORKSHOP_TOOLS = "declare,send,read,canvas.,library.search"


def workshop_mcp_server(session_id):
    from .client_mcp_installation import LOADER
    setup_env = (f"import os;os.environ['PYTHONUTF8']='1';"
                 f"os.environ['ARCHHUB_CONNECTOR_TOOLS']='{WORKSHOP_TOOLS}';"
                 f"os.environ['GOOSE_SESSION_ID']='{session_id}';")
    return {
        "type": "mcp",
        "server": {
            "type": "stdio",
            "name": "archhub-agent",
            "command": sys.executable,
            "args": ["-c", setup_env + LOADER, str(Path(__file__).resolve().parents[1])]
        },
    }


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


def goose_permission(permission, params, tool_calls):
    """Goose's own grant: only the read-only host state and the Workshop mailbox fields; everything else is cancelled."""
    call = permission.get("toolCall") or {}
    seen = tool_calls.get((permission.get("sessionId"), call.get("toolCallId"))) or {}
    meta = ((seen.get("_meta") or {}).get("goose") or {}).get("toolCall")
    identity = {k: meta.get(k) for k in ("extensionName", "toolName")} if isinstance(meta, dict) else None
    safe = permission.get("sessionId") == params.get("sessionId") and (
        identity == {"extensionName": "archhub-hosts", "toolName": "archhub-hosts__hosts_state"}
        and call.get("rawInput") == {} or safe_workshop_call(identity, call.get("rawInput")))
    option = next((row.get("optionId") for row in permission.get("options", ())
                   if row.get("kind") == "allow_once"), None) if safe else None
    return {"outcome": "selected", "optionId": option} if option else {"outcome": "cancelled"}


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
            from .baboom_persona import persona_instructions
            from .settings_owner import agent_reply_language, reply_instruction
            settings = {"goose_provider": provider, "goose_model": selected}
            recipe = {"version": "1.0.0", "title": "BABOOM", "description": "ArchHub agent",
                      "instructions": _SYSTEM + '\n' + persona_instructions() + '\n' + reply_instruction(agent_reply_language()), "settings": settings}
            encoded = base64.urlsafe_b64encode(json.dumps(recipe).encode()).decode().rstrip("=")
            # Goose owns this MCP client; messages go to the existing Workshop.
            session_id_str = "connector-" + uuid4().hex
            session = transport.request("session/new", {
                "cwd": str(self.runtime.work_dir), "mcpServers": [],
                "_meta": {"recipeDeeplink": encoded, "enabledExtensions": [{
                    "type": "mcp", "server": self.runtime.host_extension,
                    "envKeys": ["ARCHHUB_HOSTS_TOKEN"],
                    "available_tools": ["hosts_state"],
                }, workshop_mcp_server(session_id_str)]},
            }, deadline=deadline, stopped=stopped, permission=goose_permission)
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
            ]}, deadline=deadline, update=update, stopped=stopped,
                permission=goose_permission)
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
