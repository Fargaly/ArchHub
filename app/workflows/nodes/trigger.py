"""Trigger node — trigger.emit.

A trigger is a graph's entry point. When the node is cooked it emits a
fire `event` (the trigger kind + a timestamp) and passes any wired
`value` through.

The `on` config records the intended firing mode (manual / schedule /
file / host-event). The scheduled + file-watch + host-event FIRING
machinery is the separate `workflows/` triggers system; this node is
the in-graph representation of a fire — so a `trigger` primitive is a
real, placeable, cookable node like every other.
"""
from __future__ import annotations

import time

from ..graph import Port, PortType
from ..registry import NodeSpec, register


def _trigger_executor(config: dict, inputs: dict, ctx) -> dict:
    on = str((config or {}).get("on") or "manual")
    return {
        "event": {"on": on, "ts": int(time.time())},
        "value": inputs.get("value"),
    }


register(
    NodeSpec(
        type="trigger.emit",
        category="control",
        display_name="Trigger",
        description="Graph entry point — emits a fire event (kind + "
                    "timestamp) and passes `value` through.",
        inputs=[Port(name="value", type=PortType.ANY)],
        outputs=[Port(name="event", type=PortType.ANY),
                 Port(name="value", type=PortType.ANY)],
        config_schema={"on": {"type": "string",
                              "enum": ["manual", "schedule", "file",
                                       "host-event"]}},
        icon="⚡",
    ),
    _trigger_executor,
)
