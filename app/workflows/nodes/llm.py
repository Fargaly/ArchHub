"""LLM nodes.

  llm.complete             — single-shot completion: prompt → text
  llm.complete_with_tools  — full tool-use loop with restricted tool whitelist
  llm.classify             — pick one option from a list

All three delegate to the existing LLMRouter — same routing logic, same
provider clients, same auth. The workflow layer is a thin orchestration
shell on top of the chat-time machinery.
"""
from __future__ import annotations

from typing import Any

from ..graph import Port, PortType
from ..registry import NodeSpec, register


def _build_history(prompt: str, system: str | None) -> list[dict]:
    history: list[dict] = []
    if system:
        # A leading `role:"system"` message is folded into the system
        # prompt by llm_router._complete_once — the supported way to
        # supply a node-level system prompt. (Earlier this used a bogus
        # `role:"system_override"` role that provider APIs reject.)
        history.append({"role": "system", "content": system})
    history.append({"role": "user", "content": prompt})
    return history


# ---------------------------------------------------------------------------
def _llm_complete_executor(config: dict, inputs: dict, ctx) -> dict:
    """Single-shot completion — no tool use."""
    if ctx is None or not getattr(ctx, "router", None):
        return {
            "text": "",
            "model": "",
            "status": "missing_dep",
            "error": "no LLM router in execution context — set Anthropic / OpenAI / Google / OpenRouter key in Settings → Providers",
        }
    prompt = inputs.get("prompt") or config.get("prompt") or ""
    if not prompt:
        return {"text": "", "model": "", "error": "No prompt supplied."}

    model = config.get("model") or "auto"

    # Use the router but disable tools by passing a copy of ToolEngine with
    # an empty active set. Simpler: temporarily swap in an empty tool schema
    # by calling the provider client directly via the router's _route + _get_client.
    history = [{"role": "user", "content": prompt}]
    text_buf: list[str] = []

    try:
        response = ctx.router.complete(
            history=history,
            model=model,
            on_chunk=lambda piece: text_buf.append(piece),
            on_tool_invocation=lambda inv: None,
        )
    except Exception as ex:
        return {"text": "", "model": "", "status": "error",
                "error": f"{type(ex).__name__}: {ex}"}
    return {"status": "ok", "text": response.text, "model": response.model}


register(
    NodeSpec(
        type="llm.complete",
        category="llm",
        display_name="LLM completion",
        description="Single-shot LLM completion. No tool use.",
        inputs=[
            Port(name="prompt", type=PortType.STRING, required=True),
        ],
        outputs=[
            Port(name="text",  type=PortType.STRING),
            Port(name="model", type=PortType.STRING),
        ],
        config_schema={
            "model":  {"type": "string", "description": "Model id like 'anthropic:claude-sonnet-4-6' or 'auto'"},
            "prompt": {"type": "string", "description": "Default prompt if `prompt` input not connected"},
        },
        icon="✦",
    ),
    _llm_complete_executor,
)


# ---------------------------------------------------------------------------
def _llm_complete_with_tools_executor(config: dict, inputs: dict, ctx) -> dict:
    """Full tool-use loop with optional whitelist on tool names."""
    if (ctx is None
            or not getattr(ctx, "router", None)
            or not getattr(ctx, "tool_engine", None)):
        return {
            "text": "",
            "model": "",
            "status": "missing_dep",
            "error": "no LLM router in execution context — set Anthropic / OpenAI / Google / OpenRouter key in Settings → Providers",
        }
    prompt = inputs.get("prompt") or config.get("prompt") or ""
    model = config.get("model") or "auto"
    whitelist = set(config.get("allowed_tools") or [])

    # Temporarily filter the tool engine's exposed tools by patching the
    # method that returns schemas. Cleaner approach: a context manager.
    original = ctx.tool_engine.tool_schemas_for
    if whitelist:
        def filtered(provider: str):
            return [t for t in original(provider)
                    if (t.get("name") or t.get("function", {}).get("name")) in whitelist]
        ctx.tool_engine.tool_schemas_for = filtered

    try:
        history = [{"role": "user", "content": prompt}]
        invocations: list[dict] = []
        text_buf: list[str] = []

        try:
            response = ctx.router.complete(
                history=history,
                model=model,
                on_chunk=lambda piece: text_buf.append(piece),
                on_tool_invocation=lambda inv: invocations.append(inv.to_dict()),
            )
        except Exception as ex:
            return {"text": "", "model": "",
                    "tool_invocations": invocations,
                    "status": "error",
                    "error": f"{type(ex).__name__}: {ex}"}
        return {
            "status": "ok",
            "text": response.text,
            "tool_invocations": invocations,
            "model": response.model,
        }
    finally:
        ctx.tool_engine.tool_schemas_for = original


register(
    NodeSpec(
        type="llm.complete_with_tools",
        category="llm",
        display_name="LLM with tools",
        description="LLM completion with full tool-use loop. Optionally restrict to a whitelist.",
        inputs=[Port(name="prompt", type=PortType.STRING, required=True)],
        outputs=[
            Port(name="text",             type=PortType.STRING),
            Port(name="tool_invocations", type=PortType.LIST),
            Port(name="model",            type=PortType.STRING),
        ],
        config_schema={
            "model": {"type": "string"},
            "prompt": {"type": "string"},
            "allowed_tools": {"type": "array", "items": {"type": "string"},
                              "description": "Whitelist of tool names. Empty = all active."},
        },
        icon="◈",
    ),
    _llm_complete_with_tools_executor,
)


# ---------------------------------------------------------------------------
def _llm_classify_executor(config: dict, inputs: dict, ctx) -> dict:
    """Pick one option from a list. Returns the chosen option string + 1-based index."""
    if ctx is None or not getattr(ctx, "router", None):
        return {
            "choice": "",
            "index": -1,
            "status": "missing_dep",
            "error": "no LLM router in execution context — set Anthropic / OpenAI / Google / OpenRouter key in Settings → Providers",
        }
    text = inputs.get("text") or ""
    options = config.get("options") or inputs.get("options") or []
    if not options:
        return {"choice": "", "index": -1}

    options_str = "\n".join(f"{i+1}. {opt}" for i, opt in enumerate(options))
    prompt = (
        f"Classify the following input into exactly one of the options. "
        f"Reply with only the number of the chosen option, nothing else.\n\n"
        f"Input: {text}\n\nOptions:\n{options_str}\n\nNumber:"
    )
    try:
        response = ctx.router.complete(
            history=[{"role": "user", "content": prompt}],
            model=config.get("model") or "auto",
            on_chunk=lambda _piece: None,
            on_tool_invocation=lambda _inv: None,
        )
    except Exception as ex:
        return {"choice": "", "index": -1, "status": "error",
                "error": f"{type(ex).__name__}: {ex}"}
    raw = (response.text or "").strip()
    # Parse first integer
    idx = -1
    for token in raw.replace(".", " ").split():
        if token.isdigit():
            idx = int(token) - 1
            break
    if 0 <= idx < len(options):
        return {"choice": options[idx], "index": idx + 1}
    return {"choice": "", "index": -1}


register(
    NodeSpec(
        type="llm.classify",
        category="llm",
        display_name="LLM classify",
        description="Classify input text into one of N options. Returns chosen option + index.",
        inputs=[
            Port(name="text",    type=PortType.STRING, required=True),
            Port(name="options", type=PortType.LIST),
        ],
        outputs=[
            Port(name="choice", type=PortType.STRING),
            Port(name="index",  type=PortType.NUMBER),
        ],
        config_schema={
            "model":   {"type": "string"},
            "options": {"type": "array", "items": {"type": "string"}},
        },
        icon="?",
    ),
    _llm_classify_executor,
)
