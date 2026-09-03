"""Connector master node — `connector.run`.

ONE node executes ANY connector operation. The node's `host` + `op`
config select the operation; the remaining config (and, later, wired
inputs) are that operation's parameters.

This is slice 2 of the node-system redesign (docs/NODE_GRAMMAR.md). It
does two things:

  1. Collapses the old 18 per-host nodes + 118 one-per-op nodes into a
     single `connector` primitive.
  2. Folds the connector path INTO the workflow runner. Connector ops
     previously ran only via a separate `bridge.run_connector_op`
     path; now a connector node cooks like any other node in a graph.

The connector contract (`connectors.base.run_op`) always returns an
`OpResult` and never raises — so a bad call cannot crash the cook. A
failed op returns an honest `status: error`; it NEVER fabricates a
value when the host is offline.
"""
from __future__ import annotations

from ..graph import Port, PortType
from ..registry import NodeSpec, register


def _connector_run_executor(config: dict, inputs: dict, ctx) -> dict:
    config = config or {}
    host = str(config.get("host", "") or "").strip()
    op = str(config.get("op", "") or "").strip()
    # `op` may be fully-qualified ("excel.read_range") or bare ("read_range").
    op_id = op if "." in op else (f"{host}.{op}" if host and op else "")
    if not op_id:
        return {"status": "error",
                "error": "connector node needs a `host` and an `op`"}
    # Operation parameters: every config key except the two selectors,
    # plus any wired inputs (by port name).
    params = {k: v for k, v in config.items() if k not in ("host", "op")}
    if inputs:
        params.update(inputs)
    try:
        from connectors.base import run_op
    except Exception as ex:
        return {"status": "error",
                "error": f"connectors unavailable: {ex}"}
    res = run_op(op_id, **params)
    if not getattr(res, "ok", False):
        # Honest failure — never fabricate a value. The runner
        # propagates this to downstream nodes as upstream_error.
        return {"status": "error", "op_id": op_id,
                "error": getattr(res, "error", "") or f"{op_id} failed"}
    return {"value": getattr(res, "value", None),
            "op_id": op_id,
            "preview": getattr(res, "value_preview", "")}


register(
    NodeSpec(
        type="connector.run",
        category="connector",
        display_name="Connector",
        description="Run any host connector operation. `host` + `op` "
                    "select the operation; the remaining config is its "
                    "parameters.",
        inputs=[],
        outputs=[Port(name="value", type=PortType.ANY)],
        config_schema={
            "host": {"type": "string", "required": True},
            "op":   {"type": "string", "required": True},
        },
        icon="⇄",
    ),
    _connector_run_executor,
)
