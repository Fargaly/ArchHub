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
# OpenRouter rows let the user reach Anthropic / OpenAI / Google without
# minting per-provider keys — one OAuth sign-in covers everything below
# the openrouter prefix.
KNOWN_MODELS: list[tuple[str, str]] = [
    ("anthropic:claude-opus-4-7",                       "Claude Opus 4.7 — best reasoning"),
    ("anthropic:claude-opus-4-6",                       "Claude Opus 4.6 — strong & balanced"),
    ("anthropic:claude-sonnet-4-6",                     "Claude Sonnet 4.6 — balanced"),
    ("anthropic:claude-haiku-4-5-20251001",             "Claude Haiku 4.5 — fast"),
    ("openai:gpt-4o",                                   "GPT-4o — multimodal"),
    ("openai:gpt-4o-mini",                              "GPT-4o mini — fast"),
    ("google:gemini-1.5-pro",                           "Gemini 1.5 Pro"),
    ("google:gemini-2.0-flash",                         "Gemini 2.0 Flash — fast"),
    ("openrouter:anthropic/claude-opus-4",              "OpenRouter · Claude Opus 4"),
    ("openrouter:anthropic/claude-sonnet-4",            "OpenRouter · Claude Sonnet 4"),
    ("openrouter:openai/gpt-4o",                        "OpenRouter · GPT-4o"),
    ("openrouter:google/gemini-2.0-flash-exp",          "OpenRouter · Gemini 2.0 Flash"),
    ("openrouter:meta-llama/llama-3.3-70b-instruct",    "OpenRouter · Llama 3.3 70B"),
    ("openrouter:qwen/qwen-2.5-coder-32b-instruct",     "OpenRouter · Qwen 2.5 Coder 32B"),
    ("relay:auto",                                      "Firm relay · auto"),
]


def ollama_models() -> list[tuple[str, str]]:
    """Return (model_id, label) pairs for every model pulled in Ollama."""
    try:
        from llm_providers.ollama_client import list_local_models
        return [
            (f"ollama:{name}", f"{name} — local (Ollama)")
            for name in list_local_models()
        ]
    except Exception:
        return []


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
        if list_keys():
            return True
        # Ollama needs no key
        try:
            from llm_providers.ollama_client import list_local_models
            if list_local_models():
                return True
        except Exception:
            pass
        return False

    def configured_providers(self) -> list[str]:
        providers = set(list_keys())
        # Add env-var detected providers
        import os
        env_map = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY",
                   "google": "GOOGLE_API_KEY", "openrouter": "OPENROUTER_API_KEY"}
        for p, env in env_map.items():
            if os.environ.get(env):
                providers.add(p)
        # Custom OpenAI-compatible relay (firm path) is "configured" when both
        # the URL setting and the relay key are present.
        try:
            from secrets_store import load_setting, load_api_key
            if load_setting("relay_base_url") and load_api_key("relay"):
                providers.add("relay")
        except Exception:
            pass
        # Ollama if running
        try:
            from llm_providers.ollama_client import list_local_models
            if list_local_models():
                providers.add("ollama")
        except Exception:
            pass
        return sorted(providers)

    def _get_client(self, provider: str):
        if provider in self._clients:
            return self._clients[provider]
        # Ollama runs locally — no API key needed
        if provider == "ollama":
            from llm_providers.ollama_client import OllamaClient
            self._clients[provider] = OllamaClient()
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
        elif provider == "openrouter":
            from llm_providers.openrouter_client import OpenRouterClient
            self._clients[provider] = OpenRouterClient(api_key)
        elif provider == "relay":
            from llm_providers.openrouter_client import CustomOpenAICompatibleClient
            from secrets_store import load_setting, load_api_key
            base_url = load_setting("relay_base_url") or ""
            relay_key = load_api_key("relay") or ""
            if not base_url or not relay_key:
                raise RuntimeError(
                    "Custom relay is selected but base URL or token is missing. "
                    "Open Settings to configure it."
                )
            self._clients[provider] = CustomOpenAICompatibleClient(
                api_key=relay_key, base_url=base_url
            )
        elif provider == "ollama":
            from llm_providers.ollama_client import OllamaClient
            self._clients[provider] = OllamaClient()
        else:
            raise RuntimeError(f"Unknown provider: {provider}")
        return self._clients[provider]

    # ---- routing ----------------------------------------------------------

    # Preference order per task class. The first model present in the local
    # Ollama install wins. Tuned for tool-use reliability and code quality:
    # qwen2.5-coder is the most reliable open model for Revit C# generation;
    # llama3.1 has the best tool-calling adherence among general models.
    _OLLAMA_MODEL_PREFERENCES = {
        "modeling": (
            "qwen2.5-coder:7b", "qwen2.5-coder", "deepseek-r1:8b",
            "qwen3:8b", "llama3.1:latest", "llama3.1",
        ),
        "analysis": (
            "deepseek-r1:8b", "qwen3:8b", "llama3.1:latest",
            "qwen2.5-coder:7b",
        ),
        "vision": (
            "qwen3-vl:8b", "llama3.2:latest", "llama3.1:latest",
        ),
        "quick": (
            "llama3.2:3b", "llama3.2:latest", "gemma4:latest",
            "llama3.1:latest",
        ),
        "default": (
            "llama3.1:latest", "llama3.1", "qwen3:8b",
            "qwen2.5-coder:7b", "mistral:7b",
        ),
    }

    def _pick_ollama_model(self, task: str) -> Optional[str]:
        try:
            from llm_providers.ollama_client import list_local_models
            local = list_local_models()
        except Exception:
            return None
        if not local:
            return None
        local_set = set(local)
        for candidate in self._OLLAMA_MODEL_PREFERENCES.get(task, ()):
            if candidate in local_set:
                return candidate
        # No preferred model available — fall back to whatever was first.
        return local[0]

    def _route(self, history: list[dict], requested_model: str) -> tuple[str, str, str]:
        """Return (provider, model_name, note)."""
        if requested_model and requested_model != ROUTE_AUTO:
            provider, _, model = requested_model.partition(":")
            return provider, model, ""

        # Auto-routing heuristics
        last_user_msg = next(
            (m for m in reversed(history) if m.get("role") == "user"), {}
        )
        last_user = last_user_msg.get("content", "") if last_user_msg else ""
        has_images = bool(last_user_msg.get("images") if last_user_msg else False)
        text = (last_user or "").lower()

        configured_for_vision = set(self.configured_providers())

        # Vision: if an image was attached, force a multimodal-capable model
        # before falling through to the keyword heuristics. Claude (Sonnet/Opus
        # 4.x), GPT-4o, Gemini 1.5+ and OpenRouter routes to any of those all
        # accept image_url / image content blocks.
        if has_images:
            if "anthropic" in configured_for_vision:
                return "anthropic", "claude-opus-4-7", "auto: vision → Claude Opus 4.7"
            if "openrouter" in configured_for_vision:
                return ("openrouter", "anthropic/claude-opus-4",
                        "auto: vision → OpenRouter · Claude Opus 4")
            if "openai" in configured_for_vision:
                return "openai", "gpt-4o", "auto: vision → GPT-4o"
            if "google" in configured_for_vision:
                return "google", "gemini-1.5-pro", "auto: vision → Gemini 1.5 Pro"
            # Fall through to text-only routing if no vision provider available;
            # the provider client will simply ignore the image blocks.

        modeling_signals = (
            "revit", "autocad", "3ds max", "blender", "model", "wall", "door",
            "window", "geometry", "extrude", "render", "ifc", "rvt", "dwg",
            "create", "make", "build", "add", "draw", "place", "dimension",
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
            if "openrouter" in configured:
                return "openrouter", "anthropic/claude-opus-4", "auto: modeling task → OpenRouter · Claude Opus 4"
            if "openai" in configured:
                return "openai", "gpt-4o", "auto: modeling task → GPT-4o (Anthropic unavailable)"
            if "relay" in configured:
                return "relay", "auto", "auto: modeling task → firm relay"
            if "ollama" in configured:
                m = self._pick_ollama_model("modeling")
                if m:
                    return "ollama", m, f"auto: modeling task → local Ollama {m}"

        if any(s in text for s in analysis_signals):
            if "anthropic" in configured:
                return "anthropic", "claude-sonnet-4-6", "auto: analysis → Claude Sonnet 4.6"
            if "openrouter" in configured:
                return "openrouter", "anthropic/claude-sonnet-4", "auto: analysis → OpenRouter · Claude Sonnet 4"
            if "openai" in configured:
                return "openai", "gpt-4o", "auto: analysis → GPT-4o"
            if "relay" in configured:
                return "relay", "auto", "auto: analysis → firm relay"
            if "ollama" in configured:
                m = self._pick_ollama_model("analysis")
                if m:
                    return "ollama", m, f"auto: analysis → local Ollama {m}"

        if any(s in text for s in quick_signals) or len(text) < 24:
            if "anthropic" in configured:
                return "anthropic", "claude-haiku-4-5-20251001", "auto: short → Claude Haiku"
            if "openrouter" in configured:
                return "openrouter", "google/gemini-2.0-flash-exp", "auto: short → OpenRouter · Gemini Flash"
            if "openai" in configured:
                return "openai", "gpt-4o-mini", "auto: short → GPT-4o mini"
            if "ollama" in configured:
                m = self._pick_ollama_model("quick")
                if m:
                    return "ollama", m, f"auto: short → local Ollama {m}"

        # Default
        if "anthropic" in configured:
            return "anthropic", "claude-sonnet-4-6", "auto: default → Claude Sonnet 4.6"
        if "openrouter" in configured:
            return "openrouter", "anthropic/claude-sonnet-4", "auto: default → OpenRouter · Claude Sonnet 4"
        if "openai" in configured:
            return "openai", "gpt-4o", "auto: default → GPT-4o"
        if "google" in configured:
            return "google", "gemini-1.5-pro", "auto: default → Gemini 1.5 Pro"
        if "relay" in configured:
            return "relay", "auto", "auto: default → firm relay"
        if "ollama" in configured:
            m = self._pick_ollama_model("default")
            if m:
                return "ollama", m, f"auto: default → local Ollama {m}"

        raise RuntimeError("No LLM configured. Add an API key in Settings or start Ollama.")

    # ---- complete (tool-use loop) -----------------------------------------

    def complete(
        self,
        history: list[dict],
        model: str,
        on_chunk: Optional[Callable[[str], None]] = None,
        on_tool_invocation: Optional[Callable[[ToolInvocation], None]] = None,
    ) -> LLMResponse:
        on_chunk = on_chunk or (lambda _: None)
        on_tool_invocation = on_tool_invocation or (lambda _: None)
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

            # Ollama uses a different client interface
            if provider == "ollama":
                assistant_text, raw_tool_calls = client.complete(
                    system=system_prompt,
                    history=messages,
                    model=model_name,
                    tools=tool_schemas,
                    on_chunk=chunk_handler,
                )
                full_text += assistant_text
                tool_calls = raw_tool_calls  # already [{id, name, input}]
                if not tool_calls:
                    break
            else:
                stream = client.stream_completion(
                    model=model_name,
                    system=system_prompt,
                    messages=messages,
                    tools=tool_schemas,
                    on_chunk=chunk_handler,
                )
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
            "You drive the user's AEC tools directly through tool calls. The user "
            "is an architect who never wants to write or copy code — that is your "
            "job entirely.\n\n"
            f"Active connectors right now: {active_list}.\n\n"
            "RULES:\n"
            "1. When the user asks for a modelling, drafting, annotation, render, or "
            "data action, immediately invoke the matching tool. Do NOT describe what "
            "the tool would do; call it.\n"
            "2. NEVER paste code into the chat for the user to copy. Never say "
            "'paste this into the script editor', 'use this as reference', or "
            "anything similar. The user does not have a script editor open and "
            "should not need one.\n"
            "3. If a tool call fails or returns an error, do not retry by giving "
            "the user code. Report the failure plainly in one short sentence and "
            "ask whether to retry, or suggest enabling the matching connector. "
            "Example: 'Revit isn't reachable on localhost:48884 — open Revit and "
            "make sure the ArchHub connector is enabled, then I'll retry.'\n"
            "4. If the connector for the requested tool is not in the active list "
            "above, do not invent code. Say one short sentence: which connector is "
            "needed and where to enable it (Connectors panel in the header).\n"
            "5. For modelling code, write idiomatic API calls (Revit C# via "
            "Roslyn, AutoCAD C# via Roslyn, 3ds Max via pymxs, Blender via bpy) "
            "INSIDE tool calls only — never inline in chat text.\n"
            "6. Be terse. The architect values action, not explanation."
        )
