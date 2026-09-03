"""IO and data nodes.

  input.parameter   — surface a workflow-level input as a node output
  output.parameter  — collect a value into the workflow's outputs
  data.constant     — emit a hardcoded value
  data.template     — string template with {var} substitution from inputs
  data.passthrough  — identity. Backs the `reroute` grammar primitive
                      (wire-organisation dot, AgDR-0007).
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
# Typed OUTPUT nodes — slice I follow-up. Each writes/displays/sends the
# upstream value AND passes it through unchanged so downstream wires can
# chain. Same engine module so the catalogue stays close to the registry.

def _output_file_executor(config: dict, inputs: dict, ctx) -> dict:
    """Write the upstream value to a file path. Coerces non-string values
    to JSON. Overwrites by default; `append: True` appends instead.
    Returns the incoming value so the node is also a passthrough.
    """
    import json as _json
    import os
    path = (config.get("path") or "").strip()
    if not path:
        return {"value": inputs.get("value"),
                "error": "output.file requires a `path` config"}
    val = inputs.get("value")
    if isinstance(val, (dict, list)):
        text = _json.dumps(val, indent=2)
    elif val is None:
        text = ""
    else:
        text = str(val)
    mode = "a" if config.get("append") else "w"
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, mode, encoding="utf-8") as fh:
            fh.write(text)
        return {"value": val, "bytes_written": len(text.encode("utf-8"))}
    except Exception as ex:
        return {"value": val, "error": f"{type(ex).__name__}: {ex}"}


register(
    NodeSpec(
        type="output.file",
        category="io",
        display_name="File Save",
        description="Write the upstream value to a file on disk. JSON-serialised for objects/lists.",
        inputs=[Port(name="value", type=PortType.ANY, required=True)],
        outputs=[Port(name="value", type=PortType.ANY)],
        config_schema={
            "path":   {"type": "string", "description": "Destination file path", "required": True},
            "append": {"type": "boolean", "description": "Append instead of overwrite"},
        },
        icon="💾",
    ),
    _output_file_executor,
)


def _output_console_executor(config: dict, inputs: dict, ctx) -> dict:
    """Print the upstream value to stdout (engine trace log) with an
    optional label. Returns the value untouched so the node passes through.
    """
    val = inputs.get("value")
    label = (config.get("label") or "").strip()
    line = f"[{label}] {val!r}" if label else f"{val!r}"
    try:
        # ctx may carry a trace sink; fall back to print so behaviour is
        # observable even without a configured trace.
        sink = getattr(ctx, "trace", None) if ctx else None
        if callable(sink):
            sink(line)
        else:
            print(line)
    except Exception:
        pass
    return {"value": val}


register(
    NodeSpec(
        type="output.console",
        category="io",
        display_name="Console",
        description="Log the upstream value to the engine trace (stdout fallback).",
        inputs=[Port(name="value", type=PortType.ANY, required=True)],
        outputs=[Port(name="value", type=PortType.ANY)],
        config_schema={
            "label": {"type": "string", "description": "Optional prefix label"},
        },
        icon="⌗",
    ),
    _output_console_executor,
)


def _output_display_executor(config: dict, inputs: dict, ctx) -> dict:
    """Pass-through display sink. Surfaces the value in the node's
    cooked output so the inspector + Watch bodies render it. Same shape
    as watch.preview but semantically the FINAL display of the graph.
    """
    return {"value": inputs.get("value")}


register(
    NodeSpec(
        type="output.display",
        category="io",
        display_name="Display",
        description="Final display sink. Renders the value in the inspector.",
        inputs=[Port(name="value", type=PortType.ANY, required=True)],
        outputs=[Port(name="value", type=PortType.ANY)],
        config_schema={
            "as": {"type": "string", "enum": ["auto","table","list","json","image"]},
        },
        icon="↗",
    ),
    _output_display_executor,
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
# data.passthrough — identity. Backs the `reroute` grammar primitive,
# a wire-organising dot (AgDR-0007). Cheap; tests prove it's a no-op.
def _passthrough_executor(config: dict, inputs: dict, ctx) -> dict:
    return {"value": inputs.get("value")}


register(
    NodeSpec(
        type="data.passthrough",
        category="data",
        display_name="Reroute",
        description="Identity. Used by the `reroute` primitive to "
                    "organise long wires without bending the data.",
        inputs=[Port(name="value", type=PortType.ANY, required=True)],
        outputs=[Port(name="value", type=PortType.ANY)],
        config_schema={},
        icon="↦",
    ),
    _passthrough_executor,
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
