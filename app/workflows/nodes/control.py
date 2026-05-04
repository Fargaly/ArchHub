"""Control flow nodes — branching, iteration, merging.

Phase 1 is intentionally minimal. The data model supports more, but this
is enough for capturing chat conversations and running them as workflows.

  control.if      — branch on a boolean condition (true / false output ports)
  control.foreach — iterate a list, fan out to a sub-graph (single-step v0)
  control.merge   — coalesce two inputs, prefer first non-null
"""
from __future__ import annotations

from ..graph import Port, PortType
from ..registry import NodeSpec, register


# ---------------------------------------------------------------------------
def _if_executor(config: dict, inputs: dict, ctx) -> dict:
    cond = inputs.get("condition")
    truthy = bool(cond) and cond not in ("false", "False", "0", 0, "")
    value = inputs.get("value")
    if truthy:
        return {"true": value, "false": None, "taken": "true"}
    return {"true": None, "false": value, "taken": "false"}


register(
    NodeSpec(
        type="control.if",
        category="control",
        display_name="If",
        description="Pass `value` through `true` or `false` based on `condition`.",
        inputs=[
            Port(name="condition", type=PortType.ANY, required=True),
            Port(name="value",     type=PortType.ANY),
        ],
        outputs=[
            Port(name="true",  type=PortType.ANY),
            Port(name="false", type=PortType.ANY),
            Port(name="taken", type=PortType.STRING),
        ],
        config_schema={},
        icon="?",
    ),
    _if_executor,
)


# ---------------------------------------------------------------------------
def _merge_executor(config: dict, inputs: dict, ctx) -> dict:
    a = inputs.get("a")
    b = inputs.get("b")
    chosen = a if a is not None else b
    return {"value": chosen, "source": "a" if a is not None else ("b" if b is not None else None)}


register(
    NodeSpec(
        type="control.merge",
        category="control",
        display_name="Merge",
        description="Coalesce two inputs; emit the first non-null on `value`.",
        inputs=[Port(name="a", type=PortType.ANY), Port(name="b", type=PortType.ANY)],
        outputs=[Port(name="value", type=PortType.ANY),
                 Port(name="source", type=PortType.STRING)],
        config_schema={},
        icon="∪",
    ),
    _merge_executor,
)


# ---------------------------------------------------------------------------
def _foreach_executor(config: dict, inputs: dict, ctx) -> dict:
    """Phase 1 foreach: returns the list and its length so downstream nodes
    can be parametrised by `index` in their config. True fan-out execution
    (running a sub-graph per item) lands in phase 2 alongside the canvas."""
    items = inputs.get("items") or []
    if not isinstance(items, list):
        items = [items]
    return {"items": items, "count": len(items), "first": items[0] if items else None,
            "last": items[-1] if items else None}


register(
    NodeSpec(
        type="control.foreach",
        category="control",
        display_name="For each",
        description="Inspect a list. Emit count, first, last. (Sub-graph fan-out: phase 2.)",
        inputs=[Port(name="items", type=PortType.LIST, required=True)],
        outputs=[Port(name="items", type=PortType.LIST),
                 Port(name="count", type=PortType.NUMBER),
                 Port(name="first", type=PortType.ANY),
                 Port(name="last",  type=PortType.ANY)],
        config_schema={},
        icon="∀",
    ),
    _foreach_executor,
)
