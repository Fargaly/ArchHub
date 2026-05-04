"""IO and data nodes.

  input.parameter   — surface a workflow-level input as a node output
  output.parameter  — collect a value into the workflow's outputs
  data.constant     — emit a hardcoded value
  data.template     — string template with {var} substitution from inputs
"""
from __future__ import annotations

import re
from typing import Any

from ..graph import Port, PortType
from ..registry import NodeSpec, register


# ---------------------------------------------------------------------------
def _input_parameter_executor(config: dict, inputs: dict, ctx) -> dict:
    """Pull the named workflow input out of the context, return it on `value`."""
    if "__bound_value__" in inputs:
        return {"value": inputs["__bound_value__"]}
    return {"value": config.get("default")}


register(
    NodeSpec(
        type="input.parameter",
        category="io",
        display_name="Input",
        description="A workflow-level input. Fed at run time.",
        inputs=[],
        outputs=[Port(name="value", type=PortType.ANY)],
        config_schema={
            "name":        {"type": "string", "description": "Parameter name", "required": True},
            "type":        {"type": "string", "enum": ["string", "number", "boolean", "object"]},
            "description": {"type": "string"},
            "default":     {},
        },
        icon="↳",
    ),
    _input_parameter_executor,
)


# ---------------------------------------------------------------------------
def _output_parameter_executor(config: dict, inputs: dict, ctx) -> dict:
    """Sink — capture incoming `value` so the executor can collect it."""
    return {"value": inputs.get("value")}


register(
    NodeSpec(
        type="output.parameter",
        category="io",
        display_name="Output",
        description="A workflow-level output. Whatever connects here is returned.",
        inputs=[Port(name="value", type=PortType.ANY, required=True)],
        outputs=[Port(name="value", type=PortType.ANY)],
        config_schema={"name": {"type": "string", "required": True}},
        icon="↴",
    ),
    _output_parameter_executor,
)


# ---------------------------------------------------------------------------
def _constant_executor(config: dict, inputs: dict, ctx) -> dict:
    return {"value": config.get("value")}


register(
    NodeSpec(
        type="data.constant",
        category="data",
        display_name="Constant",
        description="A hardcoded value. Useful for prompts, model names, etc.",
        inputs=[],
        outputs=[Port(name="value", type=PortType.ANY)],
        config_schema={"value": {}},
        icon="•",
    ),
    _constant_executor,
)


# ---------------------------------------------------------------------------
_TEMPLATE_VAR = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _template_executor(config: dict, inputs: dict, ctx) -> dict:
    template = config.get("template", "")
    def sub(m):
        key = m.group(1)
        if key in inputs:
            return str(inputs[key])
        return m.group(0)
    return {"text": _TEMPLATE_VAR.sub(sub, template)}


register(
    NodeSpec(
        type="data.template",
        category="data",
        display_name="String template",
        description="String template with {var} substitution from input ports.",
        inputs=[Port(name="var1", type=PortType.ANY),
                Port(name="var2", type=PortType.ANY),
                Port(name="var3", type=PortType.ANY)],
        outputs=[Port(name="text", type=PortType.STRING)],
        config_schema={"template": {"type": "string", "required": True}},
        icon="¶",
    ),
    _template_executor,
)
