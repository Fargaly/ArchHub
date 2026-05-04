"""Capture a chat conversation as a runnable Workflow.

Given the chat history (list of ChatMessage with role / content / tool_invocations),
produce a Workflow JSON whose graph reproduces the same logical chain:

  - Each user message becomes an input.parameter (or a constant if it's the
    first turn and we're parameterising). This is the workflow's input.
  - Each assistant turn becomes an `llm.complete_with_tools` node.
  - Each tool invocation under that turn becomes a `tool.<name>` node wired
    to receive the LLM's output and feed back into the next LLM turn.
  - The final assistant text becomes an `output.parameter` named `answer`.

Phase 1 produces a linear graph that mirrors the conversation exactly —
no clever optimisation, no parallelism inference. The graph is editable
afterwards: rename, prune, parametrise. The user keeps the value of the
conversation without redoing it.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from .graph import Workflow, Node, Edge, Port, PortType, Trigger


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _new_edge(src_node: str, src_port: str, dst_node: str, dst_port: str) -> Edge:
    return Edge(id=_new_id("edge"), src_node=src_node, src_port=src_port,
                dst_node=dst_node, dst_port=dst_port)


def chat_to_workflow(
    history: list,                    # list of ChatMessage
    name: str | None = None,
    description: str = "",
    model: str | None = None,
) -> Workflow:
    """Convert a ChatMessage history into a Workflow graph.

    Heuristics:
      - The first user message becomes an `input.parameter` named `prompt`
        (parametrised so the workflow can be re-run with a different prompt).
      - Subsequent user messages become `data.constant` nodes (they're follow-ups
        rather than the workflow's primary input).
      - Each assistant message becomes one `llm.complete_with_tools` node whose
        prompt input is wired from the preceding user/input node.
      - Tool invocations under each assistant turn are appended as tool.* nodes
        with edges from the LLM node's `tool_invocations` output into the tool's
        args (best-effort — exact wiring depends on the tool's input schema).
      - The last assistant turn's `text` is wired into an `output.parameter`
        named `answer`.

    The resulting graph runs as a single LLM call by default. If the user
    edits it (in a future canvas) they can rewire it for richer behaviour.
    """
    name = name or f"Workflow {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    wf = Workflow.new(name=name, description=description)

    last_text_source: tuple[str, str] | None = None     # (node_id, port_name)
    last_user_source: tuple[str, str] | None = None
    is_first_user = True

    for msg in history:
        role = getattr(msg, "role", None) or msg.get("role")
        content = getattr(msg, "content", None) or msg.get("content", "")
        tool_invocations = (
            getattr(msg, "tool_invocations", None)
            or msg.get("tool_invocations")
            or []
        )

        if role == "user":
            if is_first_user:
                node = Node(
                    id=_new_id("input"), type="input.parameter",
                    label="Prompt",
                    config={"name": "prompt", "type": "string",
                            "default": content, "description": "User prompt"},
                    outputs=[Port(name="value", type=PortType.STRING)],
                )
                wf.inputs.append(Port(name="prompt", type=PortType.STRING,
                                      description="The user's prompt", required=True,
                                      default=content))
                is_first_user = False
            else:
                node = Node(
                    id=_new_id("const"), type="data.constant",
                    label="Follow-up",
                    config={"value": content},
                    outputs=[Port(name="value", type=PortType.STRING)],
                )
            wf.add_node(node)
            last_user_source = (node.id, "value")
            continue

        if role == "assistant":
            llm_node = Node(
                id=_new_id("llm"),
                type="llm.complete_with_tools",
                label="Reasoning",
                config={"model": model or "auto"},
                inputs=[Port(name="prompt", type=PortType.STRING, required=True)],
                outputs=[
                    Port(name="text",             type=PortType.STRING),
                    Port(name="tool_invocations", type=PortType.LIST),
                    Port(name="model",            type=PortType.STRING),
                ],
            )
            wf.add_node(llm_node)
            if last_user_source is not None:
                wf.add_edge(_new_edge(last_user_source[0], last_user_source[1],
                                      llm_node.id, "prompt"))
            last_text_source = (llm_node.id, "text")

            # Tool invocations under this assistant turn
            for inv in tool_invocations:
                inv_dict = inv.to_dict() if hasattr(inv, "to_dict") else inv
                tool_name = inv_dict.get("tool_name") or ""
                if not tool_name:
                    continue
                tool_node = Node(
                    id=_new_id("tool"),
                    type=f"tool.{tool_name}",
                    label=tool_name,
                    config={"args": inv_dict.get("arguments") or {}},
                    inputs=[Port(name=k, type=PortType.ANY)
                            for k in (inv_dict.get("arguments") or {}).keys()],
                    outputs=[Port(name="result", type=PortType.TOOL_RESULT),
                             Port(name="ok",     type=PortType.BOOLEAN)],
                )
                wf.add_node(tool_node)
                # Wire from the LLM's tool_invocations port into the tool node
                # as a documentation edge (the executor still pulls args from config).
                wf.add_edge(_new_edge(llm_node.id, "tool_invocations",
                                      tool_node.id, "args" if "args" in {p.name for p in tool_node.inputs}
                                                   else (tool_node.inputs[0].name if tool_node.inputs else "args")))
            continue

    # Final output node wired to the last LLM's text
    if last_text_source is not None:
        out_node = Node(
            id=_new_id("output"), type="output.parameter",
            label="Answer",
            config={"name": "answer"},
            inputs=[Port(name="value", type=PortType.STRING, required=True)],
            outputs=[Port(name="value", type=PortType.STRING)],
        )
        wf.add_node(out_node)
        wf.add_edge(_new_edge(last_text_source[0], last_text_source[1],
                              out_node.id, "value"))
        wf.outputs.append(Port(name="answer", type=PortType.STRING,
                               description="Final assistant text"))

    # Default trigger: manual
    if not wf.triggers:
        wf.triggers.append(Trigger(id=_new_id("trigger"), type="manual"))

    return wf
