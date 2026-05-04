"""LLM Router — the brain.

Holds clients for every configured provider (Anthropic, OpenAI, Google) and
routes prompts to the right model. Three modes:

- ROUTE_AUTO       — heuristic: pick model based on task signal (modeling →
                     Claude Sonnet, image understanding → Claude/GPT-4o,
                     simple chat → fast cheap model).
- specific model   — user picked it in the dropdown, forward as-is.
- agent / future   — agents may override and chain multiple models.

Tool-use loop happens here: send tools to the model, when it asks to invoke
one, run it through ToolEngine, send the result back, continue until the
model returns a final assistant message.
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Callable, Optional

from secrets_store import load_api_key, list_keys
from tool_engine import ToolEngine, ToolInvocation


ROUTE_AUTO = "auto"

# (model_id, label-shown-in-dropdown). model_id is "<provider>:<api_model_name>".
KNOWN_MODELS: list[tuple[str, str]] = [
    ("anthropic:claude-opus-4-7",       "Claude Opus 4.7 — best reasoning"),
    ("anthropic:claude-opus-4-6",       "Claude Opus 4.6 — strong & balanced"),
    ("anthropic:claude-sonnet-4-6",     "Claude Sonnet 4.6 — balanced"),
    ("anthropic:claude-haiku-4-5-20251001", "Claude Haiku 4.5 — fast"),
    ("openai:gpt-4o",                   "GPT-4o — multimodal"),
    ("openai:gpt-4o-mini",              "GPT-4o mini — fast"),
    ("google:gemini-1.5-pro",           "Gemini 1.5 Pro"),
]


@dataclass
class LLMResponse:
    text: str
    model: str
    tool_invocations: list[ToolInvocation]
    routing_note: str = ""


# ---------------------------------------------------------------------------
class LLMRouter:
    def __init__(self, tools: ToolEngine):
        self.tools = tools
        self._clients: dict[str, object] = {}

    # ---- credentials ------------------------------------------------------

    def has_credentials(self) -> bool:
        return bool(list_keys())

    def configured_providers(self) -> list[str]:
        names = list_keys()
        return sorted({n for n in names})

    def _get_client(self, provider: str):
        if provider in self._clients:
            return self._clients[provider]
        api_key = load_api_key(provider)
        if not api_key:
            raise RuntimeError(f"No API key configured for {provider}. Add one in Settings.")

        if provider == "anthropic":
            from llm_providers.anthropic_client import AnthropicClient
            self._clients[provider] = AnthropicClient(api_key)
        elif provider == "openai":
            from llm_providers.openai_client import OpenAIClient
            self._clients[provider] = OpenAIClient(api_key)
        elif provider == "google":
            from llm_providers.google_client import GoogleClient
            self._clients[provider] = GoogleClient(api_key)
        else:
            raise RuntimeError(f"Unknown provider: {provider}")
        return self._clients[provider]

    # ---- routing ----------------------------------------------------------

    def _route(self, history: list[dict], requested_model: str) -> tuple[str, str, str]:
        """Return (provider, model_name, note)."""
        if requested_model and requested_model != ROUTE_AUTO:
            provider, _, model = requested_model.partition(":")
            return provider, model, ""

        # Auto-routing heuristics
        last_user = next((m["content"] for m in reversed(history) if m["role"] == "user"), "")
        text = (last_user or "").lower()

        modeling_signals = (
            "revit", "autocad", "3ds max", "blender", "model", "wall", "door",
            "window", "geometry", "extrude", "render", "ifc", "rvt", "dwg",
        )
        analysis_signals = (
            "schedule", "quantity", "takeoff", "compare", "audit", "report",
            "explain", "why", "analyze", "speckle",
        )
        quick_signals = ("hi", "hello", "thanks", "thank you")

        configured = set(self.configured_providers())

        # Image present in the last message? Use multimodal.
        # (Future: detect QImage attachments. For now, look for "look at this" etc.)
        if any(s in text for s in modeling_signals):
            if "anthropic" in configured:
                return "anthropic", "claude-opus-4-7", "auto: modeling task → Claude Opus 4.7"
            if "openai" in configured:
                return "openai", "gpt-4o", "auto: modeling task → GPT-4o (Anthropic unavailable)"

        if any(s in text for s in analysis_signals):
            if "anthropic" in configured:
                return "anthropic", "claude-sonnet-4-6", "auto: analysis → Claude Sonnet 4.6"
            if "openai" in configured:
                return "openai", "gpt-4o", "auto: analysis → GPT-4o"

        if any(s in text for s in quick_signals) or len(text) < 24:
            if "anthropic" in configured:
                return "anthropic", "claude-haiku-4-5-20251001", "auto: short → Claude Haiku"
            if "openai" in configured:
                return "openai", "gpt-4o-mini", "auto: short → GPT-4o mini"

        # Default
        if "anthropic" in configured:
            return "anthropic", "claude-sonnet-4-6", "auto: default → Claude Sonnet 4.6"
        if "openai" in configured:
            return "openai", "gpt-4o", "auto: default → GPT-4o"
        if "google" in configured:
            return "google", "gemini-1.5-pro", "auto: default → Gemini 1.5 Pro"

        raise RuntimeError("No LLM API keys configured. Open Settings to add one.")

    # ---- complete (tool-use loop) -----------------------------------------

    def complete(
        self,
        history: list[dict],
        model: str,
        on_chunk: Callable[[str], None],
        on_tool_invocation: Callable[[ToolInvocation], None],
    ) -> LLMResponse:
        provider, model_name, note = self._route(history, model)
        client = self._get_client(provider)

        # Compose system prompt
        system_prompt = self._build_system_prompt()
        tool_schemas = self.tools.tool_schemas_for(provider)

        # Tool-use loop, max 12 iterations to prevent runaway
        all_invocations: list[ToolInvocation] = []
        full_text = ""
        messages = [m for m in history]    # working copy for tool round-tripping

        for _iteration in range(12):
            text_buf = []

            def chunk_handler(piece: str) -> None:
                text_buf.append(piece)
                on_chunk(piece)

            stream = client.stream_completion(
                model=model_name,
                system=system_prompt,
                messages=messages,
                tools=tool_schemas,
                on_chunk=chunk_handler,
            )

            # `stream` returns either:
            #   {"type": "final", "text": "..."}
            #   {"type": "tool_use", "id": "...", "name": "...", "input": {...}, "text": "..."}
            #
            # If tool_use, execute and append both the assistant tool_use and tool_result
            # to messages, then loop again.

            assistant_text = stream.get("text", "")
            full_text += assistant_text

            if stream["type"] == "final":
                break

            tool_calls = stream.get("tool_calls") or []
            if not tool_calls:
                break

            # Append assistant message with tool calls (provider-shape preserved)
            messages.append({
                "role": "assistant",
                "content": assistant_text,
                "_tool_calls": tool_calls,                 # provider-specific shape
            })

            tool_results = []
            for tc in tool_calls:
                inv = ToolInvocation(
                    id=tc.get("id") or str(uuid.uuid4()),
                    tool_name=tc["name"],
                    arguments=tc.get("input") or {},
                    status="running",
                )
                all_invocations.append(inv)
                on_tool_invocation(inv)
                try:
                    result = self.tools.invoke(inv.tool_name, inv.arguments)
                    inv.result = result
                    inv.status = "ok" if (result or {}).get("status") != "error" else "error"
                except Exception as ex:
                    inv.result = {"status": "error", "error": str(ex)}
                    inv.status = "error"
                on_tool_invocation(inv)
                tool_results.append({
                    "tool_use_id": inv.id,
                    "name": inv.tool_name,
                    "content": inv.result,
                })

            messages.append({"role": "tool", "tool_results": tool_results})

        return LLMResponse(
            text=full_text,
            model=f"{provider}:{model_name}",
            tool_invocations=all_invocations,
            routing_note=note,
        )

    def _build_system_prompt(self) -> str:
        active = [e for e in self.tools.manager.entries if e.state.name == "ACTIVE"]
        active_list = ", ".join(e.display_name for e in active) if active else "(none)"
        return (
            "You are ArchHub, an AI assistant embedded in an architect's desktop. "
            "You have live access to the user's AEC tools through tool calls. "
            f"Currently active connectors: {active_list}. "
            "When the user asks to do something in a tool, prefer using the matching "
            "tool call rather than describing it. Be concise and confident; the user is "
            "an experienced architect (BIM specialist) who values accurate, deep responses "
            "without filler. If a connector isn't active, suggest opening Connectors to "
            "enable it. For modeling, write idiomatic API code (Revit C# via Roslyn, "
            "AutoCAD C# via Roslyn, 3ds Max via pymxs, Blender via bpy)."
        )
